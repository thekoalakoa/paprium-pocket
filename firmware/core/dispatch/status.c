/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/dispatch/status.c - the cart chip's status helper 0x08022C78: the ONLY writer of $1FE4 and $1FE6. The cart chip
 * is the STM32 microcontroller on the real cartridge; this does the same steps (written by our team from our own study
 * of how the cart behaves).
 *
 * The cart chip keeps a shadow of each word (G+0xE for $1FE4, G+0x10 for $1FE6), sets or clears a mask in the shadow
 * and stores the whole word (0x08022CBA / 0x08022CA2). Every caller brackets it with cpsid/cpsie, so the
 * read-modify-write is atomic against the mailbox interrupt; ours takes the same critical section inside the helper
 * (docs/MCU_INTERFACE.md 6.3.5). A register other than 2 / 3 posts trace 0xC (0x08020CA8) and stores nothing.
 * The MCU reads $1FE4 back as the stored word (docs/MCU_INTERFACE.md 3.4; the heartbeat tests bit 11), so the shadow
 * and the register agree after every call (property FZ7 of tests/s1/disp_tests.c). Three cart chip paths store
 * without the helper, and ours does the same: app init (0x0801FA1C-0x0801FA2E: shadow and register), 85 and the fatal
 * paths (0x0801B68E: register only). */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "disp.h"

static uint16_t sh_fe4;         /* G+0xE */
static uint16_t sh_fe6;         /* G+0x10 */

#ifndef DISP_BUG
#define DISP_BUG 0
#endif

void st_set(uint32_t on, uint32_t reg, uint16_t mask)
{
#if DISP_BUG == 4                               /* planted (disp.c): the read-modify-write outside its critical section */
    uint32_t s = 0u;
    if (reg == ST_FE6) {
        uint16_t v = on ? (uint16_t)(sh_fe6 | mask) : (uint16_t)(sh_fe6 & ~mask);
        (void)brd_now();                        /* a point where the mailbox interrupt can come in */
        sh_fe6 = v;
        brd_freg_wr(BRD_FREG_FE6, v);
        return;
    }
    s = sched_crit_enter();
#else
    uint32_t s = sched_crit_enter();
#endif
    if (reg == ST_FE6) {                        /* 0x08022C8E */
        uint16_t v = on ? (uint16_t)(sh_fe6 | mask) : (uint16_t)(sh_fe6 & ~mask);
        sh_fe6 = v;
        brd_freg_wr(BRD_FREG_FE6, v);           /* 0x08022CA2 */
    } else if (reg == ST_FE4) {                 /* 0x08022CA6 */
        uint16_t v = on ? (uint16_t)(sh_fe4 | mask) : (uint16_t)(sh_fe4 & ~mask);
        sh_fe4 = v;
        brd_freg_wr(BRD_FREG_FE4, v);           /* 0x08022CBA */
    } else {
        chip_trace(0xCu, 0u, 0u);               /* 0x08022C84: event 0xC via 0x08020CA8 */
    }
    sched_crit_leave(s);
}

uint16_t st_shadow(uint32_t reg) { return reg == ST_FE4 ? sh_fe4 : sh_fe6; }

void st_init_words(uint16_t fe6, uint16_t fe4)
{
    uint32_t s = sched_crit_enter();
    sh_fe6 = fe6;                               /* 0x0801FA1C */
    sh_fe4 = fe4;                               /* 0x0801FA1E */
    sched_crit_leave(s);
}

void st_store(uint32_t reg)
{
    if (reg == ST_FE6)
        brd_freg_wr(BRD_FREG_FE6, sh_fe6);      /* 0x0801FA28 */
    else
        brd_freg_wr(BRD_FREG_FE4, sh_fe4);      /* 0x0801FA2E */
}

void st_raw_fe4(uint16_t v) { brd_freg_wr(BRD_FREG_FE4, v); }
