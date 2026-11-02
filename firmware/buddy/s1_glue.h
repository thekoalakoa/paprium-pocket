/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* buddy/s1_glue.h - the CPU MATE glue on the new firmware's levels (FW_S1; see buddy/README.md): what the board and the
   core see of it.
 * The core's hooks (l3_brain, brain_poll, brain_fault, l3_idle) are declared in core/sched/sched_hooks.h. */
#ifndef BUDDY_S1_GLUE_H
#define BUDDY_S1_GLUE_H

#include <stdint.h>

/* the board boot, before the lines are enabled (MCU_INTERFACE rule 6.3.1): the wrapper's state cleared, XLINK LCLR of
   the send / late flags of before this boot */
void buddy_s1_boot(void);

/* set while an abort of the call in flight is asked (board/pocket/s1_board.c holds it; the trap exit reads it) */
extern volatile uint32_t s1_brain_abort;
/* the trap exit's question while s1_brain_abort is set: where the interrupted code resumes (the abort landing if it
   was the call itself) */
uint32_t s1_brain_resume(uint32_t mepc);

/* TEST counters (the debug save, board/pocket/dbgsave.c, stores them). cycles_* are wall time: every level that
   preempted the call is in them.
   late_seen is retired (2026-10-19; debug save version 6: it stays 0, the layout kept): it counted every publish that
   found the stub's sticky LATE flag up from any earlier late ARM, so it read ~100 % (31,629 of 36,904 calls in B Jam's
   long hardware run of one test build) while the real late rate in the co-simulations (the RTL and the firmware
   simulated together) was 3-60 %. The words after cycles_max are TEST only (RELEASE keeps the 22-word layout), in the
   debug save from version 6:
     late         the answers whose ARM came after the original's instant, D_WORD: the stub's LATE flag read after that
                  ARM (publish clears it just before the ARM; the RTL gives the ARM's event priority over a same-clock
                  clear), each counted once, also when the game's next post overtook publish's read (a fix of
                  2026-10-19). Expected since the call waits for the game's work; it matters only if the game reads
                  $A12024 before the ARM, which the co-simulations never saw (stale reads 0);
     late_max     the most sub cycles (12.5 MHz, 80 ns) an answer came after D_WORD: TICK at the busy release (or at the
                  read, a few sub cycles after the ARM, while the busy deadline is still ahead) minus D_WORD, from the
                  answers whose TICK read came before the game's next post (the same fix: TICK restarts at a post, so a
                  later read holds no lateness of this answer; such an answer still counts in late);
     short_calls  answers with D_WORD under S1_SHORT_DWORD sub cycles: the brain's short word-0000 path, taken while
                  no CPU MATE partner is active (context: the census alone, as on the cart). */
typedef struct {
    uint32_t inits, events, sends, deferred, calls, published, discarded, aborted, abort_landings, ignored_halted;
    uint32_t ignored_notready, restarts, aioffs, releases, restores_done, rearms, dbusy_fixed, late_seen, arm_lost;
    uint32_t exc_brain, cycles_last, cycles_max;
#if !PPM_RELEASE
    uint32_t late, late_max, short_calls;
#endif
} s1_glue_stats_t;
extern s1_glue_stats_t s1_glue_stats;
#define S1_SHORT_DWORD          1000u           /* sub cycles (80 us): the word-0000 path's D_WORD is ~465 (co-sims) */

#endif
