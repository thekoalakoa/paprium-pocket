/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/mw/mw_res.c - the MegaWire init's interrupts-off block and the E7 / A9 / A6 bodies, resident (IROM, the MCU's
 * code memory; test build S3b on; see mw.h).
 *
 * The cart's MegaWire init 0x080218FC queues the record's EEPROM read and sets its status bits with interrupts off
 * (cpsid 0x08021936 ... cpsie 0x080219AA). This is that block, the same stores in the same order. It lives in the
 * IROM because code fetched from the SRAM is ~10x slower (measured on a bench test): from there the block would hold
 * every interrupt off for ~3k cycles (our timing test then measured test build 5's packet margin at -58 us at C6), from
 * here a few hundred. */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "disp.h"
#include "mw.h"

void mw_init_irqoff(void)
{
    uint32_t s = sched_crit_enter();                        /* 0x08021936 cpsid i */
    disp_job_t *j = disp_job_slot(0u);                      /* 0x08021938-0x08021948: slot G+0x12 & 0xF */
    j->b1c = 9u;                                            /* 0x0802194A: EEPROM slot 9, the MegaWire record */
    j->p24 = 0x5AFCDD04u;                                   /* 0x08021950 */
    j->type = JOB_EEP_READ_MW;                              /* 0x08021954 */
    j->p18 = 0u;                                            /* 0x08021958: the record (0x20012A6C; ours mw_ram.eep) */
    j->fail_en = 0u;                                        /* 0x0802195A */
    j->s1_hi = 0u;
    disp_job_commit(1u);                                    /* 0x0802195C: G+0x12 += 1 */
    st_set(1u, ST_FE6, 0x4000u);                            /* 0x08021964: bit 14, a job pending */
    /* 0x08021968: 0x0801FF38 starts TIM7 (plumbing: ours ticks from boot) */
    sched_work_post();                                      /* ours: the job queue's wake-up (L2c runs it) */
    st_set(0u, ST_FE6, 0x20u);                              /* 0x08021972 */
    brd_cart_ram()[0x1C10u >> 1] = 0u;                      /* 0x0802197E */
    st_set(0u, ST_FE6, 0x10u);                              /* 0x08021986 */
    st_set(0u, ST_FE6, 0x1u);                               /* 0x08021990 */
    st_set(0u, ST_FE6, 0x2u);                               /* 0x0802199A */
    st_set(0u, ST_FE6, 0x4u);                               /* 0x080219A4 */
    MW32(mw, MW_HOME) = 0u;                                 /* 0x080219A8 */
    sched_crit_leave(s);                                    /* 0x080219AA cpsie i */
}

/* 0x0801C3FA: E7's body, after its gates (core/dispatch/disp.c f_e7): the packet from $1E10 into the E7 staging
   (the 68000 words as stored, one word more for an odd length, then its length bytes swapped), MW+0x122 := 1 (to
   send), the error byte := 0, $1FE6 |= 0x10, MW+0x123 := 0, $1C10 := 0, $1FE6 &= ~0x20. The task reads the packet at
   its next tick (0x08021388). Resident: it runs in the mailbox (L1). */
void mw_e7_body(void)
{
    volatile uint16_t *ram = brd_cart_ram();
    uint32_t len = ram[(0x1E10u >> 1) + 1u], n, i;          /* 0x0801C3FA-0x0801C406 */
    uint8_t t;
    n = (len + 4u) >> 1;
    if (len & 1u)
        n++;
    for (i = 0; i < n; i++) {                               /* 0x0801C414-0x0801C420 */
        uint16_t w = ram[(0x1E10u >> 1) + i];
        mw_ram.e7b[2u * i] = (uint8_t)(w >> 8);
        mw_ram.e7b[2u * i + 1u] = (uint8_t)w;
    }
    t = mw_ram.e7b[2];                                      /* 0x0801C422-0x0801C432: bytes 2 and 3 swapped */
#if MW_BUG != 2                                             /* (planted bug 2: the length bytes left as stored) */
    mw_ram.e7b[2] = mw_ram.e7b[3];
    mw_ram.e7b[3] = t;
#else
    (void)t;
#endif
    MW8(mw, MW_E7_PEND) = 1u;                               /* 0x0801C43C */
    MW8(mw, MW_ERRBYTE) = 0u;                               /* 0x0801C440 */
    st_set(1u, ST_FE6, 0x10u);                              /* 0x0801C442-0x0801C44C */
    MW8(mw, MW_RESULT) = 0u;                                /* 0x0801C456 */
    ram[0x1C10u >> 1] = 0u;                                 /* 0x0801C45C */
    st_set(0u, ST_FE6, 0x20u);                              /* 0x0801C45E-0x0801C46A */
}

/* 0x0801C29E: A9's body, after its gates (f_a9): the packet no longer to send, $1FE6 &= ~0x10 */
void mw_a9_body(void)
{
    MW8(mw, MW_E7_PEND) = 0u;                               /* 0x0801C2A4 */
#if MW_BUG != 3                                             /* (planted bug 3: $1FE6 bit 4 left set) */
    st_set(0u, ST_FE6, 0x10u);                              /* 0x0801C2A6-0x0801C2B2 */
#endif
}

/* 0x0801C2B8: A6's body, after its gates (f_a6): the result taken, $1C10 := 0, $1FE6 &= ~0x20 */
void mw_a6_body(void)
{
    MW8(mw, MW_RESULT) = 0u;                                /* 0x0801C2BE */
    brd_cart_ram()[0x1C10u >> 1] = 0u;                      /* 0x0801C2C8 */
    st_set(0u, ST_FE6, 0x20u);                              /* 0x0801C2CA-0x0801C2D4 */
}
