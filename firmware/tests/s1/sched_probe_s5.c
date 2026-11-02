/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/sched_probe_s5.c - the scheduler probe of the stage-5 path (FW_S5, the builds with our own song engine;
 * fwbuild.json s1 variant s5probe; never in a shipped image; stages are the steps of the 0.3.0 work, README.md
 * "Terms"). L1, L2a, L2b, L2c and the thread are the scheduler's levels (core/sched/sched.h).
 *
 * The real stage-5 L1 / L2a / L2b / L2c code (core/sched with FW_S5), the real ordered engine queue
 * (core/song/song_oeq.c: song_arrive, the DONE rule, the held posts, the urgent's song_tick_due, song_job_done) and
 * the real synth glue (core/sched/s5_glue.c: synth_begin waits on STATUS.BUSY, synth_end writes DONE) on the RV32 rig
 * tests/equiv/fuzz_sched_s5.py, which plays the 68000 and the synth (MCU interface v1.3: ARR, SEQLAT, STAMP_A, the
 * TIM6 instants with their NEED, BUSY, BLKCNT, the DONE hold-off). What is synthetic here:
 *   - disp_post_s5 (the dispatcher): logs the post with its arrival number, flips $1FE6 bit 0 in a critical section
 *     (FZ7), hands mailbox B words with bit 14 (an engine post; bit 13 too = refused by its gate) and the 9494 to
 *     song_arrive, queues a probe job for a B word with bit 0 (as stage 1's probe), and finishes the post unless the
 *     queue held it back;
 *   - song_gate / song_body (the engine): the gate accepts the tick and the engine posts not marked refused; the body
 *     logs its start and end and burns PK_ITEM_CYC cycles (a tick PK_TICK_CYC); probe_item_open says an item's body
 *     is running (the rig checks that no block starts then: MCU_INTERFACE v1.3 3.10.5);
 *   - an engine post with table index 0x0C (an 8C) also queues a module job; l3_job runs the module jobs first (each
 *     hands a module back: song_job_done, and waits for its item, as core/dispatch/jobs.c's 8C job does; song_job_module
 *     logs it, probe_mod_open set: a block may start inside it, as TIM6 preempts the chip's job tail; the rig counts
 *     those), then the plain probe jobs (PK_MOD_EVERY: unused);
 *   - l3_brain: a synthetic brain call of PK_BRAIN_CYC cycles in the thread; wh_test: a periodic timer-wheel slot.
 * The rig reads probe_log / probe_* by symbol. SCHED_BUG / SONG_BUG plant the bugs (fwbuild.json s5probe_*). */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "song.h"

#if !FW_S5 || !S1_PROBE
#error "tests/s1/sched_probe_s5.c is the stage-5 probe (FW_S5, S1_PROBE)"
#endif

enum { PK_BRAIN_CYC, PK_WHEEL_PER, PK_ITEM_CYC, PK_TICK_CYC, PK_MOD_EVERY, PK_N };
/* defaults; the rig overwrites them at the first instruction of brd_boot (odd: a 4-aligned value equal to a function's
   address by layout reads as an address taken to tools/fwstack.py; an earlier build met it twice, 0x7D0) */
volatile uint32_t probe_cfg[PK_N] = { 150001u, 7169u, 2001u, 8001u, 4u };

/* the log: pairs {kind << 24 | data, time} */
enum { LG_DISPATCH = 1, LG_ITEM_START, LG_ITEM_END, LG_BRAIN_START, LG_BRAIN_END, LG_WHEEL, LG_FIN_HELD, LG_JOB,
       LG_MODITEM };
#define PROBE_LOG_N             1792u
volatile uint32_t probe_log[2 * PROBE_LOG_N] __attribute__((section(".bss_upper.probe_log")));   /* 14 KB: wram_upper,
                                                   beside the queue's state (pocket88k upper_bss_objects) */
volatile uint32_t probe_nlog, probe_nlost;
volatile uint32_t probe_n_disp, probe_n_l3, probe_jobs, probe_jobs_run, probe_items, probe_item_open, probe_held,
                  probe_mod_open;
volatile uint32_t probe_mod_items, probe_mod_wait_bad, probe_wheel_runs, probe_wheel_late_max, probe_mjobs;
volatile uint16_t probe_fe6;
static const uint8_t probe_mod[4];
const uint8_t *song_mod;                        /* (core/song/song_seq.c's: the module the job item hands over) */
song_seq S;                                     /* (core/song/song_tables.c's: song_meters reads the meters there) */
song_views_t song_v;

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

static void status_flip(uint16_t bit, volatile uint32_t *count)
{
    uint32_t s = sched_crit_enter();
    probe_fe6 ^= bit;
    brd_freg_wr(BRD_FREG_FE6, probe_fe6);
    (*count)++;
    sched_crit_leave(s);
}

/* ---- the dispatcher (L1) ---- */
void disp_post_s5(uint32_t mbx, uint16_t word, uint16_t seq, uint32_t stamp)
{
    uint32_t r = SONG_ARR_DONE;
    (void)seq;                                  /* (the rig knows each post's arrival number: it counts ARR) */
    plog(LG_DISPATCH, (mbx << 16) | word);
    status_flip(1u, &probe_n_disp);
    if (mbx == MBX_B) {
        if (word & 0x4000u)
            r = song_arrive(2u, word, brd_cart_ram() + (0x1E10u >> 1), seq, stamp);
        else if (word & 1u) {
            probe_jobs++;
            sched_work_post();
        }
        if (r == SONG_ARR_HELD)
            probe_held++;
        else
            brd_freg_wr(BRD_FREG_FEA, 0u);
    } else {
        if (word == 0x9494u)
            r = song_arrive(1u, word, brd_cart_ram() + (0x1E10u >> 1), seq, stamp);
        if (r == SONG_ARR_HELD)
            probe_held++;
        else
            brd_freg_wr(BRD_FREG_FEC, 0u);
    }
}
void disp_console_reset(void) { }
void boot_warm_page(void) { }                  /* stage 3: the warm vector page (core/boot) */

/* the queue took a held post (its gate ran): the dispatcher's finish */
void board_post_finish(uint32_t mbox)
{
    plog(LG_FIN_HELD, mbox);
    brd_freg_wr(mbox == 1u ? BRD_FREG_FEC : BRD_FREG_FEA, 0u);
}

/* ---- the engine (synthetic) ---- */
uint32_t song_gate(mbx_ctx *c)
{
    if (((c->word >> 8) & 0x3Fu) == 0x14u)
        return SONG_OK;                         /* the tick */
    if (c->word & 0x2000u)
        return SONG_DONE;                       /* bit 13: refused by its gate */
    if (((c->word >> 8) & 0x3Fu) == 0x0Cu) {   /* an 8C: its job, pushed by the gate (song_posts.c board_job_8c) */
        probe_mjobs++;
        sched_work_post();
    }
    return SONG_OK;
}

void song_body(mbx_ctx *c)
{
    uint32_t tick = ((c->word >> 8) & 0x3Fu) == 0x14u;
    plog(LG_ITEM_START, (c->mbox << 16) | (c->word & 0xFFFFu));
    probe_item_open = 1u;
    burn(tick ? probe_cfg[PK_TICK_CYC] : probe_cfg[PK_ITEM_CYC]);
    probe_items++;
    probe_item_open = 0u;
    plog(LG_ITEM_END, (c->mbox << 16) | (c->word & 0xFFFFu));
}

int song_job_module(uint32_t report)
{
    (void)report;
    plog(LG_MODITEM, 0u);
    probe_mod_open = 1u;
    burn(probe_cfg[PK_ITEM_CYC]);
    probe_mod_open = 0u;
    probe_mod_items++;
    return 1;
}

/* what song_oeq.c's other functions reach (song_meters, song_main_pass: unused by the probe) */
void board_status(uint32_t set, uint32_t reg, uint32_t mask) { (void)set; (void)reg; (void)mask; }
void boombox_feed(void) { }
void board_trace_fold(uint32_t in_item) { (void)in_item; }
/* the synth's fields and the pass's dispatcher hooks (the probe's engine is synthetic; its rig models no
   window and raises no CAUSE.BLK) */
void s5_mirror_in(uint32_t status) { (void)status; }
void s5_mirror_pass_in(uint32_t status) { (void)status; }
void s5_mirror_out(void) { }
void s5_mirror_prime(void) { }
uint32_t disp_s5_jobs(void) { return 0u; }
void disp_s5_pass(void) { }

/* ---- L2c: the probe's jobs; every PK_MOD_EVERY-th hands a module back and waits for its item (jobs.c's 8C) ---- */
uint32_t l3_job(void)
{
    uint32_t s = sched_crit_enter(), mod = probe_mjobs != 0u, have = mod || probe_jobs != 0u;
    if (mod)
        probe_mjobs--;
    else if (have)
        probe_jobs--;
    sched_crit_leave(s);
    if (!have)
        return 0u;
    probe_jobs_run++;
    plog(LG_JOB, probe_jobs_run);
    if (mod) {
        uint32_t before = probe_mod_items;
        while (!song_job_done(probe_mod))
            sched_work_post();
        while (song_job_waiting())
            sched_work_post();
        if (probe_mod_items != before + 1u)
            probe_mod_wait_bad++;               /* the job left before its item ran */
    }
    status_flip(2u, &probe_n_l3);
    return 1u;
}

uint32_t l3_test_work(void) { return 0u; }

void l3_idle(void)
{
    if (!(wheel_armed() & (1u << WH_TEST)) && probe_cfg[PK_WHEEL_PER])
        wheel_arm(WH_TEST, brd_now() + probe_cfg[PK_WHEEL_PER]);
}

void l3_brain(void)
{
    plog(LG_BRAIN_START, 0u);
    burn(probe_cfg[PK_BRAIN_CYC]);
    plog(LG_BRAIN_END, 0u);
}

void wh_test(uint32_t due)
{
    uint32_t late = brd_now() - due;
    probe_wheel_runs++;
    if (late > probe_wheel_late_max)
        probe_wheel_late_max = late;
    wheel_arm(WH_TEST, due + probe_cfg[PK_WHEEL_PER]);
}
