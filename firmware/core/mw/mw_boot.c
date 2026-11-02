/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/mw/mw_boot.c - the resident start of the MegaWire code (IROM, the MCU's code memory; test build S3b on; see
 * mw.h).
 *
 * The thread's first work after the 68000's release (core/sched/sched.c): the cart's MegaWire code runs this boot
 * only if the SRAM image passed its check (board: brd_sram_image_ok, which also locks it), whatever the MegaWire
 * option: On runs the cart's code as well, with no 0.2.6 signed-in look on top. A missing or
 * refused image leaves test build 5's MegaWire with the option Off (status 0, no module). The image's cold
 * part (the A858 screen) is checked here too, so the screen's first step waits for no CRC. Then the MegaWire RAM is
 * cleared once, as the cart chip's start-up clears its .bss; the cart chip's own init (0x080218FC) runs later, from
 * the game's C6, as on the cart. The check runs after the release, not before it, so the 68000 starts at the same
 * time as in test build 5, which had no MegaWire code (a check before the release started every game frame
 * later against the VDP's); the game's first MegaWire post comes with C6, ~2.8 s later, and until the check has
 * passed the gates take test build 5's paths (s3_mw_on = 0). */
#include <stdint.h>
#include <string.h>
#include "board.h"
#include "mw.h"

uint8_t s3_mw_on;
uint8_t s3_mw_checked;
uint8_t mw_tk_ph;
uint8_t mw_chk_par;
uint8_t mw_scr_on;
volatile uint8_t mw_due;
uint8_t mw_ran;
volatile uint8_t mw_aa_pending;

void s3_mw_boot(void)
{
    s3_mw_checked = 1u;
    s3_mw_on = 0u;                                          /* the MegaWire option is not read: On runs the
                                                               cart's code as Off does */
    if (!brd_sram_image_ok())                               /* no file, another build's, or damaged: as test build 5
                                                               too */
        return;
    (void)s3_sram_cold_ok();                                /* the cold part's CRC now, once (s3_sram.c) */
    memset(&mw_ram, 0, sizeof mw_ram);
    memset(&mw_stats, 0, sizeof mw_stats);
    memset(&mw_scr, 0, sizeof mw_scr);
    memset(&mw_txt, 0, sizeof mw_txt);
    memset(&mw_tk, 0, sizeof mw_tk);
    mw_tk_ph = 0u;
    mw_scr_on = 0u;
    s3_mw_on = 1u;
}
