/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/boot/boot_cache.c - the 0.3.0 power-on path's IROM stub (test build 4b; boot_cache.h has
 * the plan).
 * Runs from crt0 before .data / .bss exist: no global but the .noinit record, no table, no call out of this file but
 * the overlay's entry. The CRC is bitwise (no 1 KB table in the IROM): ~1.4 M cycles for a 14 KB overlay, estimated,
 * once a non-warm boot. Planted bugs for tests/equiv/cache4b.py: C4B_BUG 8 (the bar left on: here and in the overlay),
 * 9 (the overlay entered without its CRC), 10 (CACHE.VALID ignored). */
#include <stdint.h>
#include "pocket_map.h"
#include "boot_cache.h"
#ifndef C4B_BUG
#define C4B_BUG 0
#endif
#define BRD_C4B_IO(a) (*(volatile uint32_t *)(uintptr_t)(a))

c4b_rec_t c4b_rec __attribute__((section(".noinit.c4b")));   /* this boot's record: written by the stub every boot */

/* CRC-32 (IEEE), bitwise: no table, so no 1 KB of rodata in the IROM for a boot-only check */
uint32_t boot_crc32(const void *p, uint32_t n)
{
    const uint8_t *b = (const uint8_t *) p;
    uint32_t c = 0xFFFFFFFFu;
    while (n--) {
        c ^= *b++;
        for (int k = 0; k < 8; k++)
            c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
    }
    return ~c;
}

/* CRC-32 (IEEE) of n bytes (n a multiple of 4) read as whole 32-bit words, for the SRAM image's check (the MegaWire
   code, board/pocket/s3_sram.c; in the thread after the 68000's release): the same result as boot_crc32 on the same
   bytes, bit for bit (tests/stub_tests.c compares the two). A word's four bytes, lowest address first, are its
   little-endian value, so c ^= w followed by 32 bit steps is the bytewise CRC of those four bytes; the 16-entry table
   takes four bit steps at a time. Plumbing only: the SRAM image's check is the Pocket's own (the cart's chip runs its
   code from its own flash). */
static const uint32_t boot_crc_nib[16] = {
    0x00000000u, 0x1DB71064u, 0x3B6E20C8u, 0x26D930ACu, 0x76DC4190u, 0x6B6B51F4u, 0x4DB26158u, 0x5005713Cu,
    0xEDB88320u, 0xF00F9344u, 0xD6D6A3E8u, 0xCB61B38Cu, 0x9B64C2B0u, 0x86D3D2D4u, 0xA00AE278u, 0xBDBDF21Cu
};
uint32_t boot_crc32_words(const volatile uint32_t *w, uint32_t n)
{
    uint32_t c = 0xFFFFFFFFu;
    for (; n >= 4u; n -= 4u) {
        c ^= *w++;
        for (int k = 0; k < 8; k++)
            c = (c >> 4) ^ boot_crc_nib[c & 15u];
    }
    return ~c;
}

/* the overlay is usable only if its header is intact and its CRC matches: after a warm reset .bss has overwritten it */
int boot_overlay_ok(const boot_overlay_hdr *h, uint32_t room)
{
    if (h->magic != BOOT_OVERLAY_MAGIC || h->length > room - sizeof *h || h->entry < sizeof *h ||
        h->entry >= sizeof *h + h->length)
        return 0;
#if C4B_BUG == 9
    return 1;                                       /* planted: the overlay entered without its CRC */
#endif
    return boot_crc32(h + 1, h->length) == h->crc32;
}

boot_cache_state boot_cache_check(uint32_t cache_reg, const boot_overlay_hdr *overlay, uint32_t room)
{
#if C4B_BUG == 10
    cache_reg = 0;                                  /* planted: VALID ignored, a warm boot checks / rewrites the image */
#endif
    if (cache_reg & POCKET_CACHE_VALID)
        return BOOT_CACHE_VALID;
    if (overlay && boot_overlay_ok(overlay, room))
        return BOOT_CACHE_FIRST_BOOT;
    return BOOT_CACHE_SILENT;
}

void boot_cache_boot(c4b_rec_t *r)
{
    volatile uint32_t *w = (volatile uint32_t *) r;
    const boot_overlay_hdr *h = (const boot_overlay_hdr *)(uintptr_t) POCKET_WRAM_UPPER_LO;
    uint32_t i;
    for (i = 0; i < C4B_REC_WORDS; i++)
        w[i] = 0;
    r->cache_in = BRD_C4B_IO(POCKET_XL_CACHE);
    r->loaded = BRD_C4B_IO(POCKET_XL_CACHE_LOADED);
    r->lost = BRD_C4B_IO(POCKET_XL_LOST);
    switch (boot_cache_check(r->cache_in, h, POCKET_STACK_LO - POCKET_WRAM_UPPER_LO)) {
    case BOOT_CACHE_VALID:
        r->kind = C4B_WARM;
        break;
    case BOOT_CACHE_FIRST_BOOT:
        ((c4b_entry_t)((uintptr_t) h + h->entry))(r);
        break;
    default:
        r->kind = C4B_GONE;
        break;
    }
#if C4B_BUG != 8
    BRD_C4B_IO(POCKET_XL_BAR) = 0u;                 /* MCU_INTERFACE.md 21.2: EN = 0 before the 68000 is released */
#endif
    if (!(BRD_C4B_IO(POCKET_XL_BAR) & POCKET_BAR_EN))
        r->kind |= C4B_F_BAR_OFF;
}
