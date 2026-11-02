/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/sched/stats.h - the TEST counters: per level, the boot milestones, the freeze telemetry.
 * TEST images and host builds only: in RELEASE (PPM_RELEASE) and in the scheduler probe (S1_PROBE, which keeps its own
 * log) every hook below is a no-op whose arguments are not evaluated (never put work in them). The board copies the
 * record into the battery save (board/pocket/dbgsave.c) and tools/dbgsave.py decodes it. Times are board-timer cycles
 * (TIMER at BRD_CLK_HZ); CPU work is mcycle (brd_cycles, the same clock on the Pocket). */
#ifndef CORE_STATS_H
#define CORE_STATS_H

#include <stdint.h>
#include "tdiag.h"

/* the levels the counters split the CPU into; the thread's idle is what is left */
enum { ST_L1 = 0, ST_L2A, ST_L2B, ST_L3_WORK, ST_L3_JOB, ST_NLEVELS };

/* milestone slots: the board's boot codes (board/pocket/s1_boot.h S1_MS_*, 0x01-0x07) and the core's */
#define ST_MS_FIRST_POST        0x10u   /* the first post served (L1) */
#define ST_MS_C6_POSTED         0x11u   /* C6 accepted (its job queued) */
#define ST_MS_C6_DONE           0x12u   /* the C6 job finished */
#define ST_MS_FIRST_9494        0x13u   /* the first frame tick */
#define ST_MS_FATAL             0x14u   /* the fatal halt began */
#define ST_MS_N                 0x18u

typedef struct {
    uint32_t entries;           /* runs of the level */
    uint32_t cyc_lo, cyc_hi;    /* exclusive cycles, 64-bit (the levels nested in a run are not counted) */
    uint32_t max_incl;          /* the longest single run, nested levels included */
} st_level_t;

typedef struct {
    st_level_t lv[ST_NLEVELS];
    uint32_t ms[ST_MS_N];       /* board time of each milestone's first occurrence (0 = not reached) */
    uint32_t lat_n, lat_sum, lat_max;   /* L1 latency of mailbox B posts: STAMP_B to the read of $1FEA */
    uint32_t n84, t84_last, t84_max;    /* 84: STAMP_B to its $1FEE := 0xAF5B (the window off) */
    uint32_t n9494, t_last_9494;        /* the frame ticks (the 68000 alive) and the last one's board time */
    uint32_t t_last_post, last_word;    /* the last post served and its board time */
    uint32_t depth_max;         /* the deepest nesting of counted levels */
} st_stats_t;

#if TDIAG_LEAN
/* the FW_S5 TEST images (test build S3a on; core/trace/tdiag.h; FW_S5 = the full firmware, board/board.h): only the
   freeze telemetry's words are kept, stored in place (the frame ticks and the last post with their board times); the
   level counters, the milestones, the post latency and 84's time are left out */
typedef struct {
    uint32_t n9494, t_last_9494;        /* the frame ticks (the 68000 alive) and the last one's board time */
    uint32_t t_last_post, last_word;    /* the last post served and its board time */
} st_lean_t;
extern st_lean_t st_stats;
#define ST_ON                   0
#define ST_ENTER(l)             ((void)0)
#define ST_LEAVE()              ((void)0)
#define ST_MARK(c)              ((void)0)
#define ST_POST(w)              (st_stats.last_word = (w), st_stats.t_last_post = brd_now())
#define ST_LAT(t)               ((void)0)
#define ST_84(t)                ((void)0)
#define ST_9494()               (st_stats.n9494++, st_stats.t_last_9494 = brd_now())
#elif PPM_RELEASE || S1_PROBE
#define ST_ON                   0
#define ST_ENTER(l)             ((void)0)
#define ST_LEAVE()              ((void)0)
#define ST_MARK(c)              ((void)0)
#define ST_POST(w)              ((void)0)
#define ST_LAT(t)               ((void)0)
#define ST_84(t)                ((void)0)
#define ST_9494()               ((void)0)
#else
#define ST_ON                   1
extern st_stats_t st_stats;
void stats_enter(uint32_t level);
void stats_leave(void);
void stats_mark(uint32_t code);
void stats_post(uint32_t word);
void stats_lat(uint32_t cycles);
void stats_84(uint32_t cycles);
void stats_9494(void);
#define ST_ENTER(l)             stats_enter(l)
#define ST_LEAVE()              stats_leave()
#define ST_MARK(c)              stats_mark(c)
#define ST_POST(w)              stats_post(w)
#define ST_LAT(t)               stats_lat(t)
#define ST_84(t)                stats_84(t)
#define ST_9494()               stats_9494()
#endif

#endif
