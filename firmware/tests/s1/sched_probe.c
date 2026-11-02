/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/sched_probe.c - the scheduler probe (the stage-1 TEST image "probe" only, FW_S1; never in a shipped image).
 * L1, L2a, L2b, L2c and the thread are the scheduler's levels (core/sched/sched.h).
 *
 * Strong definitions of the scheduler hooks (core/sched/sched_hooks.h) that make every path of core/sched visible to
 * the RV32 fuzz rig (tests/equiv/fuzz_sched.py), which plays the 68000 side and injects interrupts:
 *   - disp_post: logs the post, flips $1FE6 bit 0 in a critical section (counted), finishes it ($1FEA := 0 for B;
 *     for A: 0x9494 starts the synthetic tick when probe_cfg[PK_TICK] is set, anything else is finished at once);
 *   - disp_holdable: bit 14 of the word marks an engine post (held while the tick runs);
 *   - audio_tick_slice / audio_tick_end / disp_tick_tail: a synthetic tick of PK_SLICES slices of PK_SLICE_CYC
 *     cycles; the tail flips $1FE6 bit 2 and finishes the A post ($1FEC := 0);
 *   - l3_brain: a synthetic brain call of PK_BRAIN_CYC cycles, in the thread with every interrupt open;
 *   - a B post with bit 0 set queues one job (sched_work_post: MSI); l3_job runs it in L2c and flips $1FE6 bit 1 in a
 *     critical section (counted) - the L2c path with MSI open, and a raise at random instants;
 *   - wh_test: a periodic wheel slot (PK_WHEEL_PER cycles), lateness logged.
 * The rig reads probe_log / probe_n* / probe_fe6 by symbol and checks FZ5, FZ7, FZ8, FZ9 and FZ11. With
 * SCHED_BUG == 5 the l3 status write is split outside its critical section (a planted bug the rig must catch). */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"

#ifndef SCHED_BUG
#define SCHED_BUG 0
#endif

enum { PK_TICK, PK_SLICES, PK_SLICE_CYC, PK_BRAIN_CYC, PK_WHEEL_PER, PK_L3_EVERY, PK_N };   /* PK_L3_EVERY: unused since
                                                                                    2026-10-15 (jobs come
                                                                                    from B posts) */
/* defaults; the rig overwrites them at the first instruction of brd_boot */
volatile uint32_t probe_cfg[PK_N] = { 1u, 4u, 2000u, 150000u, 7168u, 64u };

/* the log: pairs {kind << 24 | data, time} */
enum { LG_DISPATCH = 1, LG_TICK_START, LG_TICK_END, LG_BRAIN_START, LG_BRAIN_END, LG_WHEEL, LG_TAIL };
#define PROBE_LOG_N             2048u
volatile uint32_t probe_log[2 * PROBE_LOG_N] __attribute__((section(".bss_upper.probe_log")));   /* 16 KB: wram_upper */
volatile uint32_t probe_nlog, probe_nlost;
volatile uint32_t probe_n_disp, probe_n_l3, probe_n_tail, probe_slices_left, probe_l3_loops, probe_jobs;
volatile uint16_t probe_fe6;

static void plog(uint32_t kind, uint32_t data)
{
    uint32_t s = sched_crit_enter(), n = probe_nlog;
    if (n < PROBE_LOG_N) {
        probe_log[2u * n] = (kind << 24) | (data & 0xFFFFFFu);
        probe_log[2u * n + 1u] = brd_now();
        probe_nlog = n + 1u;
    } else {
        probe_nlost++;
    }
    sched_crit_leave(s);
}

static void burn(uint32_t cycles)
{
    uint32_t t0 = brd_now();
    while ((int32_t)(brd_now() - t0) < (int32_t)cycles)
        ;
}

/* a status read-modify-write, the way the dispatcher's status
   helper does it: shadow and register in one MIE-off section */
static void status_flip(uint16_t bit, volatile uint32_t *count)
{
    uint32_t s = sched_crit_enter();
    probe_fe6 ^= bit;
    brd_freg_wr(BRD_FREG_FE6, probe_fe6);
    (*count)++;
    sched_crit_leave(s);
}

void disp_post(uint32_t mbx, uint16_t word)
{
    plog(LG_DISPATCH, (mbx << 16) | word);
    status_flip(1u, &probe_n_disp);
    if (mbx == MBX_B) {
        if (word & 1u) {                                /* a job for L2c */
            probe_jobs++;
            sched_work_post();
        }
        brd_freg_wr(BRD_FREG_FEA, 0u);
    } else if (word == 0x9494u && probe_cfg[PK_TICK]) {
        probe_slices_left = probe_cfg[PK_SLICES];
        plog(LG_TICK_START, 0u);
        sched_tick_start(brd_now());
    } else {
        brd_freg_wr(BRD_FREG_FEC, 0u);
    }
}

uint32_t disp_holdable(uint32_t mbx, uint16_t word) { (void)mbx; return (word & 0x4000u) != 0u; }

void disp_tick_tail(void)
{
    plog(LG_TAIL, 0u);
    status_flip(4u, &probe_n_tail);
    brd_freg_wr(BRD_FREG_FEC, 0u);
}

void disp_console_reset(void) { }

uint32_t audio_tick_slice(void)
{
    if (probe_slices_left == 0u)
        return 0u;
    burn(probe_cfg[PK_SLICE_CYC]);
    return --probe_slices_left != 0u;
}

void audio_tick_end(void) { plog(LG_TICK_END, probe_slices_left); }

void l3_brain(void)
{
    plog(LG_BRAIN_START, 0u);
    burn(probe_cfg[PK_BRAIN_CYC]);
    plog(LG_BRAIN_END, 0u);
}

uint32_t l3_job(void)                                   /* L2c: one queued job */
{
    uint32_t s = sched_crit_enter(), have = probe_jobs != 0u;
    if (have)
        probe_jobs--;
    sched_crit_leave(s);
    if (!have)
        return 0u;
    probe_l3_loops++;
#if SCHED_BUG == 5
    {   /* planted: the read-modify-write split outside a critical section */
        uint16_t v = probe_fe6 ^ 2u;
        burn(200u);
        brd_freg_wr(BRD_FREG_FE6, v);
        probe_fe6 = v;
        probe_n_l3++;
    }
#else
    status_flip(2u, &probe_n_l3);
#endif
    return 1u;
}

uint32_t l3_test_work(void) { return 0u; }

void l3_idle(void)
{
    if (!(wheel_armed() & (1u << WH_TEST)) && probe_cfg[PK_WHEEL_PER])
        wheel_arm(WH_TEST, brd_now() + probe_cfg[PK_WHEEL_PER]);
}

void wh_test(uint32_t due)
{
    plog(LG_WHEEL, brd_now() - due);
    wheel_arm(WH_TEST, due + probe_cfg[PK_WHEEL_PER]);
}
