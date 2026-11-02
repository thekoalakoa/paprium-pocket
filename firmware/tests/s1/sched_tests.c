/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/sched_tests.c - host unit test of the stage-1 scheduler (core/sched, FW_S1: our new firmware's) on the x86
 * fake board (board/host/s1_board.c). Built and run by tools/fwbuild.py s1; exit 1 on the first failed check.
 *
 * Deterministic scenarios the RV32 fuzz rig cannot reach under the 68000 protocol (two held posts in one tick, both
 * orders), plus the wheel order, the tick end with a long brain call running and the urgent promotion's deadline, the
 * exception hook, and B Jam's decision of 2026-10-15: the CPU MATE brain call is the thread's and every piece of the
 * game's work preempts it - the jobs (L2c, a tick start nesting L2b above a job), the SFX feeder and the rest of the
 * wheel (never held for a call); TEST's debug save runs below the call. (Since 2026-10-15 no firmware decoder level:
 * the cart FPGA's sprite decoder is RTL, MCU interface v1.2.) The hooks (core/sched/sched_hooks.h) are this test's own
 * recorders; core/sched/sched_stubs.c is not linked. The thread is this test's code: it calls sched_thread_once(). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "stats.h"

static int fails, checks;
/* no __FILE__: the executable must not carry the tree's path */
#define CHECK(c) do { checks++; if (!(c)) { fails++; printf("FAIL sched_tests.c:%d %s\n", __LINE__, #c); } } while (0)

/* ---- event log ----------------------------------------------------------------------------------------------- */
enum { E_DISP = 1, E_TICK_END, E_TAIL, E_BRAIN, E_WHEEL, E_JOB };
static struct { int kind; uint32_t a, b, t; } ev[256];
static int nev;
static void rec(int kind, uint32_t a, uint32_t b) { if (nev < 256) { ev[nev].kind = kind; ev[nev].a = a; ev[nev].b = b; ev[nev].t = hb.now; nev++; } }
static int find(int kind, uint32_t a, uint32_t b, int from)
{
    for (int i = from; i < nev; i++)
        if (ev[i].kind == kind && ev[i].a == a && (b == 0xFFFFFFFFu || ev[i].b == b))
            return i;
    return -1;
}

/* ---- hooks --------------------------------------------------------------------------------------------------- */
static int slices_left, slice_cost = 1000, brain_cost;
static int jobs_left, in_job, job_tick_at = -1, tick_in_job;
static void (*inject)(int slice);       /* the 68000 side, called from inside a slice */
static uint32_t tick_start_t;

void disp_post(uint32_t mbx, uint16_t word)
{
    rec(E_DISP, mbx, word);
    if (mbx == MBX_B) {
        brd_freg_wr(BRD_FREG_FEA, 0u);
    } else if (word == 0x9494u) {
        tick_start_t = brd_now();
        sched_tick_start(tick_start_t);
    } else {
        brd_freg_wr(BRD_FREG_FEC, 0u);
    }
}
uint32_t disp_holdable(uint32_t mbx, uint16_t word) { (void)mbx; return (word & 0x4000u) != 0u; }
void disp_tick_tail(void) { rec(E_TAIL, 0, 0); brd_freg_wr(BRD_FREG_FEC, 0u); }
void disp_console_reset(void) { }
uint32_t audio_tick_slice(void)
{
    int k = slices_left;
    if (k <= 0)
        return 0u;
    hb.now += (uint32_t)slice_cost;
    if (in_job)
        tick_in_job++;                                  /* a slice above a job (a nested L2b) */
    if (inject)
        inject(k);
    (void)brd_now();                                    /* a point where L1 / L2a may preempt the slice */
    return --slices_left > 0;
}
void audio_tick_end(void) { rec(E_TICK_END, (uint32_t)slices_left, 0); }
static int post_9494_in_brain, arm_feed_in_brain, job_in_brain, brain_level_bad;
static int polls_in_brain, polls_outside, in_brain_now;
void l3_brain(void)
{
    uint32_t t0 = brd_now();
    rec(E_BRAIN, 0, 0);
    if (hb.level != 0u)
        brain_level_bad++;                              /* the call is the thread's: never inside a level */
    in_brain_now = 1;
    while ((int32_t)(brd_now() - t0) < brain_cost) {  /* every call is a point: L1 and L2a preempt the brain */
        hb.now += 64u;
        if (post_9494_in_brain && (int32_t)(hb.now - t0) > 10000) {
            post_9494_in_brain = 0;
            hb_68k_write(BRD_FREG_FEC, 0x9494u);        /* the 68000's tick post while the brain call runs */
        }
        if (arm_feed_in_brain && (int32_t)(hb.now - t0) > 5000) {
            uint32_t s = brd_irq_save();                /* as L1's s1_sfx_kick arms an idle grid (interrupts off) */
            arm_feed_in_brain = 0;
            wheel_arm(WH_FEED, hb.now + 100u);
            brd_irq_restore(s);
        }
        if (job_in_brain && (int32_t)(hb.now - t0) > 6000) {
            uint32_t s = brd_irq_save();                /* as L1's job commit */
            job_in_brain = 0;
            jobs_left++;
            sched_work_post();
            brd_irq_restore(s);
        }
    }
    in_brain_now = 0;
}
void brain_poll(void) { if (in_brain_now) polls_in_brain++; else polls_outside++; }   /* the glue's abort check */
uint32_t brain_fault(uint32_t mepc) { (void)mepc; return 0u; }
static int job_cost = 3000, job_level;                  /* L2c: a fake job queue (job_level: the level it ran at) */
static int r1_plant;                                    /* 7d: a job queued right after a look that found none */
uint32_t l3_job(void)
{
    if (jobs_left <= 0) {
        if (r1_plant) {                                 /* the queue is read (empty) and l3_job is on its way back */
            uint32_t s = brd_irq_save();                /* as L1's job commit */
            r1_plant = 0;
            jobs_left++;
            sched_work_post();
            brd_irq_restore(s);                         /* a point: the nested L2b (MSI open in L2c) is taken here */
        }
        return 0u;
    }
    rec(E_JOB, (uint32_t)jobs_left, 0);
    job_level = (int)hb.level;
    in_job = 1;
    for (int c = 0; c < job_cost; c += 64) {
        hb.now += 64u;
        if (job_tick_at >= 0 && c == job_tick_at) {
            uint32_t s = brd_irq_save();                /* as L1's 9494 (interrupts off): a tick starts in the job */
            job_tick_at = -1;
            slices_left = 2;
            sched_tick_start(hb.now);
            brd_irq_restore(s);
        }
        (void)brd_now();
    }
    in_job = 0;
    jobs_left--;
    return 1u;
}
uint32_t l3_test_work(void) { return 0u; }
void l3_idle(void) { }
static uint32_t wh_last[WH_N];
static int wh_order[16], nwh;
static void wh_rec(unsigned slot, uint32_t due) { wh_last[slot] = due; if (nwh < 16) wh_order[nwh++] = (int)slot; rec(E_WHEEL, slot, due); }
static int feed_in_brain, wdog_in_brain;               /* 7c: wheel callbacks that ran inside a brain call */
static uint32_t feed_t;
void wh_wdog(uint32_t due) { wdog_in_brain += in_brain_now; wh_rec(WH_WDOG, due); }
void wh_feed(uint32_t due) { feed_in_brain += in_brain_now; feed_t = hb.now; wh_rec(WH_FEED, due); }
void wh_vu(uint32_t due) { wh_rec(WH_VU, due); }
static uint32_t wh_level;
void wh_test(uint32_t due) { wh_level = hb.level; wh_rec(WH_TEST, due); }

/* ---- 68000 helpers -------------------------------------------------------------------------------------------- */
static void post_b(uint16_t w) { hb_68k_write(BRD_FREG_FEA, w); }
static void post_a(uint16_t w) { hb_68k_write(BRD_FREG_FEC, w); }
static void settle(void) { for (int i = 0; i < 64; i++) (void)brd_now(); }
static void thread(void) { for (int i = 0; i < 8; i++) { (void)sched_thread_once(); settle(); } }   /* the thread's passes */

static void inj_b_then_a(int slice) { if (slice == 3) post_b(0xC001u); if (slice == 2) post_a(0xC002u); }
static void inj_a_then_b(int slice) { if (slice == 3) post_a(0xC003u); if (slice == 2) post_b(0xC004u); }
static void inj_plain(int slice) { if (slice == 3) post_b(0x8005u); }

static void boot(void)
{
    hb_reset();
    memset(&sched_stats, 0, sizeof sched_stats);
    memset(&st_stats, 0, sizeof st_stats);
    sched_init();
    nev = 0;
    nwh = 0;
    inject = NULL;
    jobs_left = 0;
    job_tick_at = -1;
    tick_in_job = 0;
    r1_plant = 0;
    brd_cause_ack(BRD_CAUSE_ALL);
    brd_lines_on(BRD_LINES_ALL);
    brd_irq_enable();
}

int main(void)
{
    int i, j, t;

    /* 1. a plain B post: dispatched at the next board point, finished */
    boot();
    post_b(0x8100u);
    settle();
    CHECK(find(E_DISP, MBX_B, 0x8100u, 0) == 0 && brd_freg_rd(BRD_FREG_FEA) == 0u && brd_cause() == 0u);
    CHECK(sched_stats.l1 == 1u && sched_stats.posts_b == 1u);

    /* 2. a tick run by L2b: slices, the end, the tail, in that order */
    slices_left = 4;
    post_a(0x9494u);
    settle();
    t = find(E_TICK_END, 0, 0xFFFFFFFFu, 0);
    CHECK(t > 0 && find(E_TAIL, 0, 0, t) == t + 1 && !sched_tick_running() && brd_freg_rd(BRD_FREG_FEC) == 0u);
    CHECK(sched_stats.slices == 4u && sched_stats.ticks_urgent == 0u && !(wheel_armed() & (1u << WH_URGENT)));

    /* 3. two engine posts in one tick, B first: held, then replayed after the tail in arrival order (B, A) */
    boot();
    slices_left = 4;
    inject = inj_b_then_a;
    post_a(0x9494u);
    settle();
    t = find(E_TAIL, 0, 0, 0);
    i = find(E_DISP, MBX_B, 0xC001u, 0);
    j = find(E_DISP, MBX_A, 0xC002u, 0);
    CHECK(t > 0 && i > t && j > i);
    CHECK(sched_stats.held == 2u && sched_stats.replayed == 2u && sched_stats.held_overflow == 0u);

    /* 4. the other order: A first, then B -> replayed A, B */
    boot();
    slices_left = 4;
    inject = inj_a_then_b;
    post_a(0x9494u);
    settle();
    t = find(E_TAIL, 0, 0, 0);
    i = find(E_DISP, MBX_A, 0xC003u, 0);
    j = find(E_DISP, MBX_B, 0xC004u, 0);
    CHECK(t > 0 && i > t && j > i);

    /* 5. a plain post during a tick is not held: dispatched before the tick end */
    boot();
    slices_left = 4;
    inject = inj_plain;
    post_a(0x9494u);
    settle();
    i = find(E_DISP, MBX_B, 0x8005u, 0);
    t = find(E_TICK_END, 0, 0xFFFFFFFFu, 0);
    CHECK(i > 0 && t > i && sched_stats.held == 0u);

    /* 6a. a tick that starts while a long brain call runs: the call is the thread's, so L2b preempts it and
           ends the tick within its slices (+ a few board points), long before the call ends; no urgent promotion */
    boot();
    brain_cost = 400000;
    slices_left = 4;
    slice_cost = 2000;
    post_9494_in_brain = 1;
    polls_in_brain = polls_outside = 0;
    brain_level_bad = 0;
    hb.cause |= BRD_CAUSE_S;                            /* a SEND: L1 marks the call pending; the thread makes it; 10,000
                                                           cycles in, the 68000 posts 9494, L1 starts the tick, L2b runs it */
    settle();
    CHECK(find(E_BRAIN, 0, 0, 0) < 0);                  /* L1 makes no call: the thread does */
    (void)sched_thread_once();
    t = find(E_TICK_END, 0, 0xFFFFFFFFu, 0);
    CHECK(find(E_BRAIN, 0, 0, 0) >= 0 && find(E_BRAIN, 0, 0, 0) < t && brain_level_bad == 0);
    CHECK(t > 0 && sched_stats.ticks_urgent == 0u && !(wheel_armed() & (1u << WH_URGENT)));
    CHECK(t > 0 && (int32_t)(ev[t].t - tick_start_t) <= (int32_t)(4u * 2000u + 4096u));
    CHECK(polls_in_brain >= 1 && polls_outside == 0);   /* L1 (the 9494) above the call asks the glue's abort
                                                           check, nobody else does */
    {   /* the TEST per-level counters = the levels the fake board took, the brain call counted in the L2b slot */
        CHECK(st_stats.lv[ST_L1].entries == hb.taken[0] && st_stats.lv[ST_L1].entries == sched_stats.l1);
        CHECK(st_stats.lv[ST_L2A].entries == hb.taken[1]);
        CHECK(st_stats.lv[ST_L2B].entries == hb.taken[2] + sched_stats.brain_calls);
        CHECK(st_stats.depth_max >= 2u && st_stats.lat_n == sched_stats.posts_b);   /* L1 inside the call */
    }
    brain_cost = 0;
    settle();

    /* 6b. the urgent promotion: with L2b unable to run (MSI masked), the tick still ends by CLK_URGENT + its slices
           (+ a few board points) from the urgent slot in L2a, not before its deadline */
    boot();
    slices_left = 4;
    slice_cost = 2000;
    brd_lines_off(BRD_LINE_MSI);
    post_a(0x9494u);
    settle();                                           /* L1: the tick starts (MSI raised, masked) */
    CHECK(sched_tick_running());
    for (i = 0; i < 400 && sched_tick_running(); i++) {
        hb.now += 512u;
        settle();
    }
    t = find(E_TICK_END, 0, 0xFFFFFFFFu, 0);
    CHECK(t > 0 && sched_stats.ticks_urgent == 1u);
    CHECK(t > 0 && (int32_t)(ev[t].t - tick_start_t) <= (int32_t)(CLK_URGENT + 4u * 2000u + 4096u));
    CHECK(t > 0 && (int32_t)(ev[t].t - tick_start_t) >= (int32_t)CLK_URGENT);   /* not before its deadline */
    brd_lines_on(BRD_LINE_MSI);
    settle();

    /* 7. the wheel: callbacks in deadline order; equal deadlines lowest slot first; past deadlines at once */
    boot();
    {
        uint32_t n0 = brd_now();
        wheel_arm(WH_VU, n0 + 3000u);
        wheel_arm(WH_WDOG, n0 + 1000u);
        wheel_arm(WH_TEST, n0 + 3000u);
        wheel_arm(WH_FEED, n0 + 2000u);
        CHECK(hb.ten == 1u && hb.tcmp == n0 + 1000u);    /* the compare holds the earliest */
        hb.now += 5000u;
        settle();
        thread();                                       /* WH_TEST: marked due by L2a, run by the thread */
        CHECK(nwh == 4 && wh_order[0] == WH_WDOG && wh_order[1] == WH_FEED && wh_order[2] == WH_VU && wh_order[3] == WH_TEST);
        CHECK(wh_last[WH_WDOG] == n0 + 1000u && wheel_armed() == 0u && hb.ten == 0u);
        wheel_arm(WH_FEED, brd_now() - 10u);            /* in the past: runs at the next point */
        settle();
        CHECK(nwh == 5 && wh_order[4] == WH_FEED);
        wheel_arm(WH_VU, brd_now() + 100000u);
        wheel_disarm(WH_VU);
        hb.now += 200000u;
        settle();
        CHECK(nwh == 5 && hb.ten == 0u);
        /* across the 2^32 wrap */
        hb.now = 0xFFFFF000u;
        wheel_arm(WH_TEST, 0x00000800u);
        CHECK(hb.tcmp == 0x00000800u && hb.ten == 1u);
        settle();
        CHECK(nwh == 5);                                 /* not yet: 0x1800 cycles ahead */
        hb.now = 0x00000900u;
        settle();
        thread();
        CHECK(nwh == 6 && wh_order[5] == WH_TEST);
    }

    /* 7b. a job posted while a brain call runs: it runs at once, above the call (L2c inside L2b) */
    boot();
    brain_cost = 20000;
    job_in_brain = 1;
    hb.cause |= BRD_CAUSE_S;
    settle();
    (void)sched_thread_once();
    {
        int b = find(E_BRAIN, 0, 0, 0), j = find(E_JOB, 1u, 0, 0);
        CHECK(b == 0 && j > b && jobs_left == 0);
        CHECK(in_brain_now == 0 && ev[j].t - ev[b].t < 20000u);   /* inside the call's time, not after it */
        CHECK(job_level == (int)BRD_LINE_MSI);           /* the job ran in L2c (inside L2b) */
        CHECK(sched_stats.brain_calls == 1u && hb.msip == 0u);
    }
    /* a tick that starts in the middle of a job runs at once from a nested L2b (MSI open in L2c); the job goes on */
    boot();
    jobs_left = 1;
    job_cost = 4000;
    job_tick_at = 1024;
    tick_in_job = 0;
    sched_work_post();
    settle();
    CHECK(jobs_left == 0 && tick_in_job == 2 && !sched_tick_running());
    CHECK(sched_stats.l2b >= 2u && hb.depth_max >= 2u);  /* the nested L2b */
    job_cost = 3000;
    /* 7d. the lost wake-up of the builds from 2026-10-15 until its fix of 2026-10-18 (found from rig freezes in a check
           run): a job queued after a pass's l3_job has
           looked at the queue and found it empty, before the pass ends: the nested L2b clears MSIP, finds the pass
           running and leaves it alone, so the pass must look again before it leaves (planted bug sched_tests_bug9 =
           SCHED_BUG 9, the look again left out: the job stays queued with MSIP clear) */
    boot();
    jobs_left = 1;
    r1_plant = 1;
    sched_work_post();
    settle();
    CHECK(r1_plant == 0 && jobs_left == 0 && hb.msip == 0u);  /* planted, and the planted job ran */
    CHECK(find(E_JOB, 1u, 0, 0) >= 0 && find(E_JOB, 1u, 0, find(E_JOB, 1u, 0, 0) + 1) > 0);   /* both jobs */
    CHECK(sched_stats.l2b >= 2u && hb.depth_max >= 2u);  /* the plant was taken by a nested L2b (the race's shape) */
    /* a deferred wheel slot (TEST's debug save) runs in the thread, after a brain call that is pending at the same time */
    boot();
    brain_cost = 3000;
    wheel_arm(WH_TEST, brd_now() + 100u);
    hb.now += 200u;
    hb.cause |= BRD_CAUSE_S;
    settle();
    CHECK(find(E_WHEEL, WH_TEST, 0xFFFFFFFFu, 0) < 0 && wheel_low_pending() != 0u);   /* marked due, not run in L2a */
    thread();
    {
        int b = find(E_BRAIN, 0, 0, 0), w = find(E_WHEEL, WH_TEST, 0xFFFFFFFFu, 0);
        CHECK(b >= 0 && w > b && wheel_low_pending() == 0u && wh_level == 0u);
    }
    brain_cost = 0;

    /* 7c. nothing of the wheel waits for a brain call (an earlier version held the SFX feeder): a feeder deadline and a
           watchdog deadline inside the call both run inside it, at their deadlines; a feeder armed during the call (a
           D1's kick in L1) runs inside it too */
    boot();
    brain_cost = 20000;
    feed_in_brain = wdog_in_brain = 0;
    {
        uint32_t n0 = brd_now();
        wheel_arm(WH_FEED, n0 + 2000u);                  /* due inside the call */
        wheel_arm(WH_WDOG, n0 + 5000u);                  /* due inside the call too */
        hb.cause |= BRD_CAUSE_S;
        settle();
        (void)sched_thread_once();
        i = find(E_BRAIN, 0, 0, 0);
        j = find(E_WHEEL, WH_FEED, n0 + 2000u, 0);
        t = find(E_WHEEL, WH_WDOG, n0 + 5000u, 0);
        CHECK(i == 0 && j > i && t > j);                 /* call, the feeder inside it, then the watchdog inside it */
        CHECK(wdog_in_brain == 1 && feed_in_brain == 1);
        CHECK(j > 0 && (int32_t)(feed_t - (n0 + 2000u)) >= 0 && (int32_t)(feed_t - (n0 + 2000u)) <= 2048);   /* on time */
        CHECK(sched_stats.brain_calls == 1u && !(wheel_armed() & (1u << WH_FEED)));
    }
    boot();                                             /* armed during the call (L1's kick): runs inside it too */
    brain_cost = 20000;
    feed_in_brain = 0;
    arm_feed_in_brain = 1;
    hb.cause |= BRD_CAUSE_S;
    settle();
    (void)sched_thread_once();
    CHECK(arm_feed_in_brain == 0 && feed_in_brain == 1);
    brain_cost = 0;

    /* 8. an empty MEI entry (the CPU latch fired after the ack) returns at once */
    boot();
    {
        uint32_t s = brd_irq_save();
        l1_mei();
        brd_irq_restore(s);
        CHECK(sched_stats.l1_empty == 1u && nev == 0);
    }

    /* 9. exceptions: resume at the next instruction, the first one recorded */
    CHECK(sched_exception(2u, 0x1000u, 0xDEADu) == 0x1004u && sched_exception(5u, 0x2000u, 0u) == 0x2004u);
    CHECK(sched_stats.exc == 2u && sched_stats.exc_first_cause == 2u && sched_stats.exc_first_epc == 0x1000u);

    printf("sched_tests: %d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
