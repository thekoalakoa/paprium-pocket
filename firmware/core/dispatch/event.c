/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/dispatch/event.c - the cart chip's event_post 0x08020B24, its non-fatal half. The cart chip is the STM32
 * microcontroller on the real cartridge; this does the same steps (written by our team from our own study of how the
 * cart behaves).
 *
 * Every refusal, job failure and fatal path posts an event (r0 = code, r1, r2). The cart chip counts codes whose bits
 * 31-30 are clear and whose low byte is at most 0xF: G+0x196 + 2 * code += 1 (0x08020B36-0x08020B4C); the 81-bit-1
 * main loop copies those 16 counters to RAMDP $1B00 (in the FW_S5 build, test build 5 on: song_main_pass through
 * disp_s5_pass; the FW_S5 = 0 build has no main-loop pass). With r2 = 0 it returns (0x08020C7E); with r2 != 0 it is
 * fatal: the LED code, the "WE SUX" poll of $1FEA and the MCU reset (fatal_halt, core/trace/fatal.c). */
#include <stdint.h>
#include "board.h"
#include "disp.h"
#include "tdiag.h"

void chip_trace(uint32_t code, uint32_t a, uint32_t b)
{
    if ((code >> 30) == 0u && (code & 0xFFu) <= 0xFu)       /* 0x08020B36-0x08020B3E */
        disp_g.trace_cnt[code & 0xFu]++;                    /* 0x08020B40-0x08020B4C */
#if !PPM_RELEASE && !TDIAG_LEAN
    disp_g.last_trace = code;
#endif
    if (b)                                                  /* 0x08020B4E-0x08020B54 */
        fatal_halt(code, a, b);
}
