/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/boot/appinit.c - app start and app init: the steps the cart chip (the STM32 microcontroller on the real
 * cartridge) runs in its app start (cart chip address 0x0801FAE4) and its app init (0x0801F980), written by our team
 * from our own study of how the cart behaves (docs/BOOT_SPEC.md, row BOOT-14). The hex numbers in the comments below
 * are the cart chip's addresses for each step, kept as references; BOOT-nn names are rows of docs/BOOT_SPEC.md.
 *
 * app_start = the stores into the dispatcher state, app init, then $1FE6 bit 15 and $1FE4 bit 13 through the status
 * helper. Left out, because they are STM32 plumbing: the board init 0x08020828 (clocks, timers, GPIO; ours is in
 * board/pocket), the dummy read of RAMDP $0108 (docs/ALLOWLIST.md, row B23; docs/BOOT_SPEC.md, row AL-09) and the
 * call of the main loop (ours is the scheduler's l3_thread, which the board enters after it releases the 68000).
 * RAMDP is the cart RAM that both the 68000 and the cart chip see. The hand-off block the bootloader leaves at RAMDP
 * $1FE0-$1FEF (the MCU side) comes from the board here (board_get_handoff, docs/BOOT_SPEC.md section 3; all zero on
 * the Pocket). The warm path ($1FEA = 0x1234) and $1FE6 bit 12 are kept as the cart chip has them, although both
 * registers reset to 0 on ours (docs/BOOT_SPEC.md, row AL-04). */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "disp.h"
#include "appinit.h"

static void app_init(void)                                  /* 0x0801F980 */
{
    const board_handoff *h = board_get_handoff();
    uint16_t s0, s1, fe6;
    unsigned i;
    disp_g.handoff[0] = h->w1fe0;                           /* 0x0801F98E-0x0801F994: G+0x180 */
    disp_g.handoff[1] = h->w1fe4;                           /* 0x0801F99A-0x0801F9A0: G+0x184 */
    disp_g.handoff[2] = h->page_a;                          /* 0x0801F9A6-0x0801F9AC: G+0x188 */
    disp_g.handoff[3] = h->page_b;                          /* 0x0801F9B2-0x0801F9B8: G+0x18C */
    disp_g.g178 = 0x10u;                                    /* 0x0801F9BE */
    disp_g.g17c = 0u;                                       /* 0x0801F9C8 */
    for (i = 0; i < 16u; i++)                               /* 0x0801F9CA: memset(G+0x196, 0, 0x20) */
        disp_g.trace_cnt[i] = 0u;
    disp_g.mw_ready = 0u;                                   /* 0x0801F9D2 */
    disp_g.mixer = 0u;                                      /* 0x0801F9D8 */
    disp_g.f81[0] = 0u;                                     /* 0x0801F9DC */
    disp_g.seq_ready = 0u;                                  /* 0x0801F9DE */
    disp_g.f81[1] = 0u;                                     /* 0x0801F9E2 */
    disp_g.sfx_ready = 0u;                                  /* 0x0801F9E4 */
    disp_g.eng_ready = 0u;                                  /* 0x0801F9EA */
    disp_g.sc_session = 0u;                                 /* 0x0801F9F0 */
    disp_g.wd_arm = 1u;                                     /* 0x0801F9F8 */
    disp_g.f81[2] = 0u;                                     /* 0x0801F9FA */
    disp_g.q_wr = 0u;                                       /* 0x0801F9FC */
    disp_g.q_rd = 0u;                                       /* 0x0801F9FE */
    disp_g.wd_count = 1u;                                   /* 0x0801FA04 */
    s0 = brd_freg_rd(BRD_FREG_FE6);                         /* 0x0801FA06 */
    s1 = brd_freg_rd(BRD_FREG_FE6);                         /* 0x0801FA08 */
    fe6 = (uint16_t)((s1 & 0x1000u) | 0x4000u);             /* 0x0801FA0C-0x0801FA14 */
    st_init_words(fe6, 0x46F8u);                            /* 0x0801FA1C, 0x0801FA1E: the shadows */
    brd_freg_wr(BRD_FREG_FF0, 0x8000u);                     /* 0x0801FA20 */
    brd_freg_wr(BRD_FREG_FF2, 0x8000u);                     /* 0x0801FA26 */
    st_store(ST_FE6);                                       /* 0x0801FA28 */
    st_store(ST_FE4);                                       /* 0x0801FA2E */
    if (!(fe6 & 0x1000u) && brd_freg_rd(BRD_FREG_FEA) == 0x1234u)   /* 0x0801FA30-0x0801FA3A: the warm path */
        brd_freg_wr(BRD_FREG_FEA, 0u);                      /* 0x0801FA88 */
    brd_freg_wr(BRD_FREG_FEC, 0u);                          /* 0x0801FA40 */
    {
        uint32_t s = sched_crit_enter();                    /* 0x0801FA42 */
        if (s0 & 0x1000u) {                                 /* 0x0801FA44: boot into the MegaWire screen */
            disp_job_t *j = disp_job_slot(0u);              /* 0x0801FA48-0x0801FA72 (its MegaWire memset: core/mw) */
            j->type = JOB_SETUP_MW;
            j->fail_en = 0u;
            disp_job_commit(1u);
        }
        disp_g.g174 = 0u;                                   /* 0x0801FA7A */
        disp_g.g176 = 0u;                                   /* 0x0801FA7E */
        disp_g.app_ready = 1u;                              /* 0x0801FA82: the mailboxes are served from here */
        sched_crit_leave(s);
    }
}

void app_start(void)                                        /* 0x0801FAE4 */
{
    disp_g.mw_ready = 0u;                                   /* 0x0801FAEA */
    disp_g.mixer = 0u;                                      /* 0x0801FAF0 */
    disp_g.sfx_ready = 0u;                                  /* 0x0801FAF4 */
    disp_g.seq_ready = 0u;                                  /* 0x0801FAF8 */
    disp_g.eng_ready = 0u;                                  /* 0x0801FB02 */
    disp_g.f81[3] = 0u;                                     /* 0x0801FB04 */
    disp_g.wd_arm = 0u;                                     /* 0x0801FB0C: the watchdog disarmed (BOOT-16) */
    disp_g.wd_count = 0u;                                   /* 0x0801FB10 */
    disp_g.app_ready = 0u;                                  /* 0x0801FB12 */
    disp_g.sc_session = 0u;                                 /* 0x0801FB14 */
    disp_g.sc_saved = 0u;                                   /* 0x0801FB16 */
    disp_g.g194 = 1u;                                       /* 0x0801FB18-0x0801FB20: 0x192 - 0x92 - 0xFF = 1 (the
                                                               heartbeat counts only above 1, so this has no effect) */
    /* 0x0801FB22: board init 0x08020828 (STM32 plumbing; ours ran before) */
    app_init();                                             /* 0x0801FB26 */
    st_set(1u, ST_FE6, 0x8000u);                            /* 0x0801FB34: mailbox idle */
    st_set(1u, ST_FE4, 0x2000u);                            /* 0x0801FB44: heartbeat bit */
    /* 0x0801FB4A: the main loop 0x0801A394 (ours: the board releases the 68000, then l3_thread) */
}
