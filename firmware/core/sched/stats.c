/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/sched/stats.c - the TEST counters (docs/STAGE1_PLAN.md). TEST builds only: RELEASE and the scheduler probe
 * compile this file to nothing (core/sched/stats.h turns every hook into a no-op).
 *
 * Per level (L1, L2a, L2b, and the thread's board work, jobs and idle): entries, exclusive cycles (the levels nested in
 * a run are subtracted, so the sums split the CPU between the levels) and the longest inclusive run. The levels nest
 * as the trap entry nests them, so a small stack of open runs is enough: a run is opened at the level's entry and
 * closed at its exit, both with interrupts off for the few instructions of the bookkeeping (a level that preempts
 * between them only adds its own run on top).
 * Also: the boot milestones (the first board time of each), the L1 latency of mailbox B posts from the RTL's post
 * stamp (STAMP_B, docs/MCU_INTERFACE.md 4.6), 84's window-off time from the same stamp (checked on hardware too), and
 * the freeze telemetry (the frame ticks and the last post with their times; the MCU heartbeat is the watchdog's tick
 * count, core/wdog). The debug save (board/pocket/dbgsave.c) copies them into the battery save for tools/dbgsave.py. */
#include <stdint.h>
#include "board.h"
#include "stats.h"

#if TDIAG_LEAN
st_lean_t st_stats __attribute__((section(".bss_upper")));   /* FW_S5 TEST (test build S3a on): the freeze telemetry
                                                                only (stats.h) */
#endif

#if ST_ON
st_stats_t st_stats __attribute__((section(".bss_upper")));

#define ST_DEPTH                8u
static struct { uint32_t level, t0, nested; } open_[ST_DEPTH] __attribute__((section(".bss_upper")));
static uint32_t depth __attribute__((section(".bss_upper")));

void stats_enter(uint32_t level)
{
    uint32_t s = brd_irq_save();
    if (depth < ST_DEPTH) {
        open_[depth].level = level;
        open_[depth].nested = 0u;
        open_[depth].t0 = brd_cycles();
    }
    depth++;
    if (depth > st_stats.depth_max)
        st_stats.depth_max = depth;
    brd_irq_restore(s);
}

void stats_leave(void)
{
    uint32_t s = brd_irq_save();
    uint32_t now = brd_cycles();
    if (depth && depth <= ST_DEPTH) {
        uint32_t d = depth - 1u, incl = now - open_[d].t0, excl = incl - open_[d].nested;
        st_level_t *l = &st_stats.lv[open_[d].level];
        uint32_t lo = l->cyc_lo + excl;
        l->cyc_hi += lo < l->cyc_lo;
        l->cyc_lo = lo;
        l->entries++;
        if (incl > l->max_incl)
            l->max_incl = incl;
        if (d)
            open_[d - 1u].nested += incl;
    }
    if (depth)
        depth--;
    brd_irq_restore(s);
}

void stats_mark(uint32_t code)
{
    if (code < ST_MS_N && !st_stats.ms[code]) {
        uint32_t t = brd_now();
        st_stats.ms[code] = t ? t : 1u;
    }
}

void stats_post(uint32_t word)
{
    st_stats.last_word = word;
    st_stats.t_last_post = brd_now();
    stats_mark(ST_MS_FIRST_POST);
}

void stats_lat(uint32_t cycles)
{
    st_stats.lat_n++;
    st_stats.lat_sum += cycles;
    if (cycles > st_stats.lat_max)
        st_stats.lat_max = cycles;
}

void stats_84(uint32_t cycles)
{
    st_stats.n84++;
    st_stats.t84_last = cycles;
    if (cycles > st_stats.t84_max)
        st_stats.t84_max = cycles;
}

void stats_9494(void)
{
    st_stats.n9494++;
    st_stats.t_last_9494 = brd_now();
    stats_mark(ST_MS_FIRST_9494);
}
#endif
