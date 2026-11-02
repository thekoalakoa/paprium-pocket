/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/boot/boot_cache.h - the 0.3.0 power-on path (test build 4b): the bank cache and the WRAM boot
 * overlay (before the new-core work this interface was only a stub).
 *
 * crt0 (board/pocket/s1_crt0.S) calls boot_cache_boot after its interface checks and BEFORE it copies .data and clears
 * .bss: the 68000 is held (CTRL.HOLD), interrupts are off, the watchdog is not running (locked decisions of the
 * project plan). The stub uses registers, its stack and the .noinit record only:
 *   1. XLINK CACHE.VALID = 1: a warm reset (a reset inside the session, the Pocket's Quit / power-off reboot): touch
 *      nothing (C4B_WARM);
 *   2. otherwise the boot overlay (bitstream-initialised in wram_upper, as the firmware design has it) is entered if
 *      its header is intact and its CRC-32 matches: it checks the loaded cache file or unpacks the bank
 *      (board/pocket/boot/c4b.h);
 *   3. otherwise (a reset after crt0 overwrote the overlay, i.e. after an unpack that failed in this power-on): nothing,
 *      the wave bank stays as it is (C4B_GONE);
 *   and BAR EN = 0 on every path (docs/MCU_INTERFACE.md 21.2; BAR resets on every reset anyway: this covers the
 *   MCU-only restart).
 * The overlay's own size, entry and CRC come from tools/fwbuild.py (the header below, written at build time). */
#ifndef BOOT_CACHE_H
#define BOOT_CACHE_H
#include <stdint.h>
#include "c4b.h"

#define BOOT_OVERLAY_MAGIC 0x31564F50u   /* 'POV1' little-endian: Paprium boot OVerlay, version 1 */

typedef struct {
    uint32_t magic;      /* BOOT_OVERLAY_MAGIC */
    uint32_t length;     /* bytes covered by crc32, following this header */
    uint32_t crc32;      /* CRC-32 (IEEE 802.3, reflected, poly 0xEDB88320, init/xorout 0xFFFFFFFF) of those bytes */
    uint32_t entry;      /* offset of the entry (c4b_entry_t) from the header (0 = none) */
} boot_overlay_hdr;
_Static_assert(BOOT_OVERLAY_MAGIC == C4B_OVL_MAGIC, "the overlay magic");

typedef enum {
    BOOT_CACHE_UNKNOWN = 0,   /* (unused since test build 4b: the registers exist) */
    BOOT_CACHE_VALID,         /* cache_valid = 1: a warm boot, touch nothing */
    BOOT_CACHE_FIRST_BOOT,    /* cache invalid, overlay present: check the file, unpack if needed (with the bar) */
    BOOT_CACHE_SILENT         /* cache invalid, overlay gone: the wave bank as it is until a power cycle */
} boot_cache_state;

uint32_t boot_crc32(const void *p, uint32_t n);
uint32_t boot_crc32_words(const volatile uint32_t *w, uint32_t n);   /* n a multiple of 4: the same CRC */
int boot_overlay_ok(const boot_overlay_hdr *h, uint32_t room);
boot_cache_state boot_cache_check(uint32_t cache_reg, const boot_overlay_hdr *overlay, uint32_t room);
void boot_cache_boot(c4b_rec_t *rec);   /* crt0's call (above); rec = the .noinit boot record */
extern c4b_rec_t c4b_rec;               /* .noinit (s1_board.c): this boot's record (TEST copies it to the debug save) */

#endif
