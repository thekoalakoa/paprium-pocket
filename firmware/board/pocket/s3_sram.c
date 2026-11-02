/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/s3_sram.c - the MegaWire code: the SRAM image, which the Little-Man Firmware file carries
 * (docs/MCU_INTERFACE.md 3.7).
 *
 * The MegaWire code and its rodata are built from this tree with the rest of the firmware (one link: the IROM, WRAM
 * and SRAM images come from the same ELF). From 0.3.0 the SRAM image travels inside the firmware file (Fafrium,
 * docs/FAFRIUM.md, released as Little-Man Firmware): at every power-on the core's boot stub checks the whole file
 * with its CRC-32 and copies the image into SRAM 0x00000-0x0FFFF before the firmware starts. (Before that file, the
 * image was its own file, which an APF data slot loaded into SRAM through the shared data loader.) Nothing
 * calls into the image before this check has passed; the thread runs it first after the 68000's release
 * (core/mw/mw_boot.c), so the 68000 starts at test build 5's time (test build 5 is the synth build B Jam
 * tested on hardware; a check before the release, even a short one, moved every game frame against the VDP's; the rig
 * model, our RV32 model of the board running the firmware images, measured C6's hold one VBlank shorter):
 *   - the header (64 B at SRAM 0x0): magic, version, length (4-aligned, 0x44..0x10000), the CRC-32 (IEEE) of the
 *     hot part [0x40, hot end), the link id (a number the build derives from this link's objects, so a file from any
 *     other build is refused: its code would call into another IROM), the hot end, and the CRC-32 of the cold part
 *     [hot end, length). The hot part is the code the MegaWire task runs every tick; the cold part (the A858 screen
 *     and the cart program's text) runs only on the screen: a cold part that fails its own check (s3_sram_cold_ok,
 *     right after this one) leaves the task running and the screen uncalled;
 *   - (no longer XLINK LOADED and LOST: they count the SRAM halfwords the APF data loader wrote and lost since
 *     power-up, and the loader writes nothing into SRAM now: the boot stub places the image, so LOADED reads 0. The
 *     stub's own CRC-32 check of the file and the checks here stand in for them: a file from another build, a
 *     damaged one and SRAM left over from another core are all still refused. Refusal state 5, which those counts
 *     gave, is no longer used);
 *   - the hot part's CRC-32 from the IROM, in whole-word loads with a 16-entry table (boot_crc32_words): the same
 *     result as the bytewise boot_crc32, bit for bit (tests/stub_tests.c), at ~64 cycles a byte against its ~228
 *     (the rig model; the bytewise one took 39.15 ms for 30,032 B in the RTL simulation of the SRAM fetch path).
 * Then the image lock is set: XCFG |= bit 16 by read-modify-write (XCFG is a plain rw register, and every other
 * XCFG write in this tree keeps the bit the same way), so no stray MCU store can change the code afterwards. XCFG
 * and the image survive every reset but power-off; the check runs again at every boot (open item O7 of
 * docs/MCU_INTERFACE.md: whether a Pocket reset reloads the slot is a hardware check). The header itself is linked
 * here and filled by tools/mkimage.py. */
#include <stdint.h>
#include "pocket_map.h"
#include "board.h"
#include "boot_cache.h"

#define S3_SRAM_MAGIC           0x33574D50u     /* 'PMW3' */
#define S3_SRAM_VERSION         0x00010002u     /* image layout 1, minor 2: the hot and cold parts */

extern char __sram_link_id[];                   /* fwbuild: --defsym, the link's id (0x40000800 | 30 bits of a CRC) */
extern char __sram_img_end[];
extern char __sram_hot_off[];                   /* the link: the hot part's end, as an offset into the image */

typedef struct {
    uint32_t magic, version, length, crc32, link_id, hot_end, crc32_cold;
    uint32_t pad[9];
} s3_sram_hdr_t;

const s3_sram_hdr_t s3_sram_hdr __attribute__((section(".sram_hdr"), used)) = {
    S3_SRAM_MAGIC, S3_SRAM_VERSION, 0u, 0u, (uint32_t)(uintptr_t)__sram_link_id, (uint32_t)(uintptr_t)__sram_hot_off,
    0u, { 0u }
};

uint32_t s3_sram_state;                         /* TEST and the debug save: 0 not checked, 1 OK, 2-4 and 6 why
                                                   refused (5 is no longer used) */
uint8_t s3_sram_cold;                           /* the cold part: 0 not checked yet, 1 OK, 2 refused */

uint32_t brd_sram_image_ok(void)
{
    const volatile s3_sram_hdr_t *h = (const volatile s3_sram_hdr_t *)(uintptr_t)POCKET_SRAM_BASE;
    uint32_t len = h->length;
    if (h->magic != S3_SRAM_MAGIC || h->version != S3_SRAM_VERSION)
        s3_sram_state = 2u;
    else if (h->link_id != (uint32_t)(uintptr_t)__sram_link_id)
        s3_sram_state = 3u;
    else if (len < 0x44u || len > POCKET_SRAM_IMG_MAX || (len & 3u) ||
             len != (uint32_t)(uintptr_t)__sram_img_end - POCKET_SRAM_BASE ||
             h->hot_end != (uint32_t)(uintptr_t)__sram_hot_off)
        s3_sram_state = 4u;
    else if (boot_crc32_words((const volatile uint32_t *)(uintptr_t)(POCKET_SRAM_BASE + 0x40u),
                              h->hot_end - 0x40u) != h->crc32)
        s3_sram_state = 6u;
    else {
        BRD_IO32(POCKET_XL_XCFG) = BRD_IO32(POCKET_XL_XCFG) | POCKET_XCFG_LOCK;    /* read-modify-write */
        s3_sram_state = 1u;
    }
    s3_sram_cold = 0u;
    return s3_sram_state == 1u;
}

/* the cold part's CRC-32, once a boot, before the first call into it (core/mw/mw_boot.c, right after the check above;
   the screen's gate asks again and gets the answer kept here); a refusal leaves the cold code uncalled for this boot */
__attribute__((noinline))
uint32_t s3_sram_cold_ok(void)
{
    const volatile s3_sram_hdr_t *h = (const volatile s3_sram_hdr_t *)(uintptr_t)POCKET_SRAM_BASE;
    if (s3_sram_cold == 0u)
        s3_sram_cold = boot_crc32_words((const volatile uint32_t *)(uintptr_t)(POCKET_SRAM_BASE + h->hot_end),
                                        h->length - h->hot_end) == h->crc32_cold ? 1u : 2u;
    return s3_sram_cold == 1u;
}
