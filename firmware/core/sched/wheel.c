/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/sched/wheel.c - the timer wheel on the board timer (L2a, the timer interrupt level; docs/MCU_INTERFACE.md 4.3,
 * 6.3.5).
 *
 * WH_N fixed slots, each a deadline in board-timer cycles and an armed bit. The compare holds the earliest armed
 * deadline (signed distance from now, so the 2^32 wrap is harmless within the 40 s horizon); with nothing armed the
 * timer is off. l2a_mti runs every due slot, lowest slot first, one at a time: the slot is disarmed under MIE off, then
 * its callback runs with MEI open and may re-arm itself (a periodic slot re-arms at due + period: an absolute grid, no
 * drift). Every edit is atomic (MIE off). A deadline written in the past fires at once (the compare is a level), so
 * none is lost; the trap entry's restore of mie on the way out is the MTI flush. A slot in WH_LOW_SLOTS (work with no
 * deadline: TEST's debug save) is marked due here and its callback runs in the thread, below the brain call (an
 * earlier version ran it in L2c). No slot is held for a brain call any more (an earlier version held the SFX feeder's;
 * now the wheel preempts the call, as everything else of the game's does).
 *
 * The cost: the wheel runs every 133.5 us while an SFX channel plays (the interim feeder), so its own work
 * is a fixed share of the MCU. While l2a_mti runs (w_in_l2a), an arm or disarm only edits the slot: l2a_mti finds due
 * slots by their deadlines, not by the compare, and MTI stays masked until its trap exit (the trap entry masks the
 * level's own line), so it programs the compare once, in the critical section of its last look, from the TIMER value
 * it read there. An L1 nested in L2a edits the slots the same way (its edit is seen by that last look); every other
 * level programs at once. Same deadlines, same order of callbacks, same compare when L2a returns. */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "stats.h"

/* SCHED_BUG 8 (tests/s1/sched_tests.c's negative control only, fwbuild.json sched_tests_bug8; never in an image): l2a_mti
   leaves w_in_l2a set, so no arm outside L2a programs the compare again (the other SCHED_BUG values: core/sched/sched.c) */
#ifndef SCHED_BUG
#define SCHED_BUG 0
#endif

typedef void (*wheel_fn)(uint32_t due);

/* the callbacks, by slot (tools/stack_s1.json resolves l2a_mti's and wheel_low_run's indirect calls as this table:
   "re:^wh_") */
static void (*const wheel_fns[WH_N])(uint32_t) = {
    [WH_URGENT] = wh_urgent,
    [WH_WDOG] = wh_wdog,
    [WH_FEED] = wh_feed,
    [WH_VU] = wh_vu,
    [WH_TEST] = wh_test,
};

static uint32_t w_deadline[WH_N];
static volatile uint32_t w_armed;
static volatile uint32_t w_low;             /* slots of WH_LOW_SLOTS that fell due: their callbacks wait for the thread
                                               (the due time stays in w_deadline: only the callback re-arms its slot) */
static volatile uint32_t w_in_l2a;          /* 1 while l2a_mti runs: it programs the compare once, on its way out */

/* MIE off: program the compare with the earliest armed deadline (seen from now; the first of equal ones), or switch
   the timer off */
static void wheel_program_at(uint32_t now)
{
    uint32_t a = w_armed, best;
    const uint32_t *d = w_deadline;
    int32_t bd;
    if (!a) {
        brd_timer_disarm();
        return;
    }
    while (!(a & 1u)) {
        a >>= 1;
        d++;
    }
    best = *d;
    bd = (int32_t)(best - now);
    while ((a >>= 1) != 0u) {
        d++;
        if ((a & 1u) && (int32_t)(*d - now) < bd) {
            best = *d;
            bd = (int32_t)(best - now);
        }
    }
    brd_timer_arm(best);
}

/* MIE off: after a slot edit; inside l2a_mti the edit waits for its last look */
static void wheel_program(void)
{
    if (!w_in_l2a)
        wheel_program_at(brd_now());
}

void wheel_arm(unsigned slot, uint32_t deadline)
{
    uint32_t s = sched_crit_enter();
    w_deadline[slot] = deadline;
    w_armed |= 1u << slot;
    wheel_program();
    sched_crit_leave(s);
}

void wheel_disarm(unsigned slot)
{
    uint32_t s = sched_crit_enter();
    w_armed &= ~(1u << slot);
    wheel_program();
    sched_crit_leave(s);
}

uint32_t wheel_armed(void) { return w_armed; }

void wheel_init(void)
{
    unsigned i;
    w_armed = 0u;
    w_low = 0u;
    w_in_l2a = 0u;
    for (i = 0; i < WH_N; i++)
        w_deadline[i] = 0u;
    brd_timer_disarm();
}

/* one look of l2a_mti (interrupts off inside): the lowest armed slot whose deadline has come, disarmed, as
   slot | deadline << 32 (a WH_LOW_SLOTS slot is only marked due, for the thread, and the look goes on); with none due, the
   compare is programmed (wheel_program_at's choice: the earliest, the first of equal ones, found in the same walk) from
   the same TIMER read and WH_N comes back. A function of its own, so l2a_mti keeps nothing in registers across the
   callbacks (its frame was 13 saved registers) */
_Static_assert(WH_N == 5, "l2a_look walks the five slots one by one");

static __attribute__((noinline)) uint64_t l2a_look(void)
{
    for (;;) {
        uint32_t s = sched_crit_enter(), now = brd_now(), a = w_armed, i, bx = UINT32_MAX, best = 0u, due;
        /* slot K armed: due when its deadline has come (the lowest such slot runs first); else a candidate for the
           compare: the smallest distance ahead (all are below 2^31 here; the first of equal ones) */
#define LOOK(K) \
        if (a & (1u << (K))) { \
            uint32_t d = w_deadline[K]; \
            if ((int32_t)(now - d) >= 0) { \
                i = (K); \
                goto hit; \
            } \
            if (d - now < bx) { \
                bx = d - now; \
                best = d; \
            } \
        }
        LOOK(0) LOOK(1) LOOK(2) LOOK(3) LOOK(4)
#undef LOOK
        if (a)                                  /* nothing due: the next deadline, or the timer off */
            brd_timer_arm(best);
        else
            brd_timer_disarm();
#if SCHED_BUG != 8
        w_in_l2a = 0u;                          /* (in the same section: an arm after this programs at once) */
#endif
        sched_crit_leave(s);
        return WH_N;
hit:
        w_armed &= ~(1u << i);
        if (WH_LOW_SLOTS & (1u << i)) {         /* no deadline: its callback runs in the thread, below the brain call */
            w_low |= 1u << i;
            sched_crit_leave(s);
            continue;
        }
        due = w_deadline[i];
        sched_crit_leave(s);
        return (uint64_t)i | ((uint64_t)due << 32);
    }
}

void l2a_mti(void)
{
    uint64_t r;
    ST_ENTER(ST_L2A);
#if !PPM_RELEASE && !TDIAG_LEAN
    sched_stats.l2a++;
#endif
    w_in_l2a = 1u;
    while ((uint32_t)(r = l2a_look()) != WH_N) {
#if !PPM_RELEASE && !TDIAG_LEAN
        sched_stats.wheel_runs++;
#endif
        wheel_fns[(uint32_t)r]((uint32_t)(r >> 32));
    }
    sched_brain_poll();                 /* above a brain call: its abort check (buddy/) */
    ST_LEAVE();
}

/* the thread (core/sched sched_thread_once): the deferred slots, lowest first, one a call */
uint32_t wheel_low_pending(void) { return w_low; }

void wheel_low_run(void)
{
    uint32_t s = sched_crit_enter(), a = w_low, due = 0u;
    unsigned i, hit = WH_N;
    for (i = 0; i < WH_N; i++) {
        if (a & (1u << i)) {
            hit = i;
            due = w_deadline[i];
            break;
        }
    }
    if (hit != WH_N)
        w_low = a & ~(1u << hit);
    sched_crit_leave(s);
    if (hit == WH_N)
        return;
#if !PPM_RELEASE && !TDIAG_LEAN
    sched_stats.wheel_runs++;
#endif
    wheel_fns[hit](due);
    __asm__ volatile ("" : : : "memory");  /* not a tail call: tools/fwstack.py follows indirect calls, not tail jumps */
}
