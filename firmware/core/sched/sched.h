/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/sched/sched.h - the scheduler: four levels, the timer wheel, MSI work, held posts, the urgent tick.
 *
 * The design is in docs/STAGE1_PLAN.md and docs/MCU_INTERFACE.md section 6, with B Jam's rule of 2026-10-15: the
 * CPU MATE brain call (CPU MATE is the computer-controlled partner), which the game does not use all the time, never
 * delays the game's own work - it runs in the time left, at the bottom:
 *   L1  l1_mei    MEI (CAUSE), interrupts off throughout: ack, read the post, hold it or dispatch it, SEND -> brain.
 *   L2a l2a_mti   MTI (timer), MEI open: the timer wheel (watchdog tick, SFX feeder grid, VU row, urgent tick).
 *   L2b l2b_msi   MSI, MEI and MTI open: the song tick in slices (MTI masked per slice), the tick end and the held
 *                 posts; then L2c.
 *   L2c (in L2b)  one pass with MSI open again: one job of the cart chip's queue; a tick start nests L2b above it.
 *                 The cart FPGA's sprite decoder is RTL (MCU interface v1.2): no firmware level decodes.
 *   L3  l3_thread the thread: the CPU MATE brain call, then TEST's diagnostics (the debug save, the SAT snapshot),
 *                 then idle housekeeping. L1, the wheel and the jobs all preempt the call.
 * MEI, MTI and MSI are the MCU's external, timer and software interrupt lines; CAUSE is the RTL register that says why
 * MEI was raised; the cart chip is the STM32 microcontroller on the real cartridge. The trap entry (board) masks the
 * level's own line and every lower one, opens MIE for L2a / L2b, and restores mie on the way out (that restore is the
 * flush of docs/MCU_INTERFACE.md rule 6.3.3 for the level's own line).
 *
 * Who fills the hooks (sched_hooks.h): the cart chip's dispatcher (core/dispatch) disp_*, the jobs (core/dispatch)
 * l3_job, the brain glue (buddy/) l2b_brain, the audio tick (the song engine; the FW_S5 = 0 build = empty, the TEST
 * probe = synthetic) audio_tick_*, the wheel callbacks wh_* (core/wdog for the watchdog, interim/s1 for the feeder and
 * VU). Without their owners, core/sched/sched_stubs.c gives weak defaults, and tools/stack_s1.json stands the PROXY
 * depths in for them. FW_S5 (board/board.h) builds the full firmware on MCU interface v1.3; FW_S5 = 0 is the earlier
 * firmware. */
#ifndef CORE_SCHED_H
#define CORE_SCHED_H

#include <stdint.h>
#include "board.h"

/* ---- mailboxes (the chip's EXTI 14 = B, 15 = A) ---------------------------------------------------------------- */
#define MBX_B                   0u
#define MBX_A                   1u

/* ---- timer wheel slots, lowest first when two are due (urgent before everything) ------------------------------ */
enum {
    WH_URGENT = 0,              /* sched: the urgent song-tick promotion (the song engine; TEST probe) */
    WH_WDOG,                    /* the TIM7-rate watchdog / heartbeat tick (core/wdog) */
    WH_FEED,                    /* the interim SFX feeder grid (interim/s1) */
    WH_VU,                      /* the interim Boom Box VU row (interim/s1) */
    WH_TEST,                    /* TEST probe only */
    WH_N                        /* (the decoder stand-in WH_DEC left the wheel; since v1.2 the RTL decodes) */
};
/* slots whose callbacks have no deadline: L2a only marks them due, the thread runs them, below the brain call (TEST's
   diagnostics stay below it; an earlier version ran them in L2c): TEST's debug save (board/pocket/dbgsave.c). The
   scheduler probe's WH_TEST measures the wheel itself: it stays in L2a. No slot is ever held for a brain call (an
   earlier version held the SFX feeder's; B Jam's rule of 2026-10-15: the call must not slow the game's own work, so
   the feeder preempts it again) */
#if S1_PROBE
#define WH_LOW_SLOTS            0u
#else
#define WH_LOW_SLOTS            (1u << WH_TEST)
#endif

/* ---- critical sections (MIE off; docs/MCU_INTERFACE.md rule 6.3.5) ------------------------------------------- */
static inline uint32_t sched_crit_enter(void) { return brd_irq_save(); }
static inline void sched_crit_leave(uint32_t s) { brd_irq_restore(s); }

/* ---- the timer wheel (L2a) ----------------------------------------------------------------------------------- */
void wheel_arm(unsigned slot, uint32_t deadline);   /* (re)arm; any level; a past deadline runs at the next L2a */
void wheel_disarm(unsigned slot);
uint32_t wheel_armed(void);                          /* bit per slot */
uint32_t wheel_low_pending(void);                    /* WH_LOW_SLOTS slots due and not run yet (bit per slot) */
void wheel_low_run(void);                            /* the thread: the lowest of them, one a call */
void wheel_init(void);                               /* everything disarmed, the timer off (sched_init) */

/* ---- MSI work (L2b / L2c) and the thread ---------------------------------------------------------------------- */
void sched_brain_post(void);                         /* L1 on SEND (or the thread's housekeeping): a brain call is
                                                        pending; the thread makes it when nothing else is left */
void sched_brain_poll(void);                         /* L1 / L2a before they return: while a call is in flight, the
                                                        glue's abort check (brain_poll, buddy/) */
void sched_work_post(void);                          /* L1: a job was queued: raises MSI (L2c runs it) */
uint32_t sched_l2c_once(void);                       /* L2c (and a host harness's drain): one job;
                                                        nonzero = ran one; never twice on top of itself */
uint32_t sched_thread_once(void);                    /* one pass of the thread loop (l3_thread; host tests): 1 = a brain
                                                        call, 2 = a TEST diagnostic, 0 = idle housekeeping */

/* ---- the song tick: started by the 9494 handler, ended by L2b or by the urgent promotion in L2a --------------- */
void sched_tick_start(uint32_t stamp);               /* L1: the tick is pending (audio_tick_begin said so) */
uint32_t sched_tick_running(void);

/* ---- held posts: an engine post that arrives while the tick runs waits for the tick end, in arrival order ------ */
/* (L1 asks disp_holdable(); the replay goes through disp_post() after the tick end, interrupts off) */

/* ---- state, init --------------------------------------------------------------------------------------------- */
void sched_init(void);                               /* boot, before interrupts are enabled */

typedef struct {
    uint32_t l1, l1_empty, l2a, l2b, l3_loops;       /* level entries; MEI entries with CAUSE = 0 */
    uint32_t posts_b, posts_a, sends, held, held_overflow, replayed;
    uint32_t ticks, ticks_urgent, slices, brain_calls, wheel_runs;
    uint32_t exc, exc_first_cause, exc_first_epc, exc_first_tval;
    uint32_t l2b_active;                             /* TEST: 1 while l2b_msi runs (the RV32 model's FZ5 check) */
} sched_stats_t;
extern sched_stats_t sched_stats;                    /* TEST counters (the debug save, board/pocket/dbgsave.c, stores
                                                        them); exceptions in both */

#if FW_S5
/* ---- FW_S5: the synth's fields (core/sched/s5_mirror.c) and the main-loop pass ------------------------------
   docs/MCU_INTERFACE.md v1.3 3.10.5: the logic-owned fields are read, and every field is written, only between
   synth_begin and synth_end; board_synth_begin calls s5_mirror_in once STATUS.BUSY = 0 (status = that STATUS word),
   and every item ends with board_synth_put (s5_mirror_out) before its DONE. The pass runs as the cart chip's thread
   runs it (main_loop 0x0801A3AC: the job queue empty -> the pass 0x0801A60A; a job's tail 0x0801A5E6 -> the pass):
   inside every item (core/song/song_oeq.c, board_item_pass) when no job is queued or running; after every block the
   synth mixes (CAUSE.BLK -> L2b, board_pass_bracket, skipped when BLKCNT has not moved since the last pass: an instant
   serviced with no block also lowers BUSY); after an L1 entry that served a post and queued no item (a refusal, a
   non-audio post: its trace counters, $1B00); and once after every job (jobs.c: sched_pass_post, forced).
   Each bracketed pass runs in L2b with MTI masked, as an item does: atomic against the urgent finish. */
void s5_mirror_in(uint32_t status);
void s5_mirror_pass_in(uint32_t status);
void s5_mirror_out(void);
void s5_mirror_prime(void);                          /* every field written now (boot; a host harness) */
typedef struct { uint32_t reads, pass_reads, words; } s5_mirror_stats_t;
extern s5_mirror_stats_t s5_mirror_stats;            /* TEST: full read-backs, pass read-backs, words written */
void sched_pass_post(void);                          /* a job ended: its tail's pass (L2b, forced) */
void board_pass_bracket(uint32_t why);               /* L2b: the pass in its own bracket (core/sched/s5_glue.c) */
#define S5_PASS_TAIL            1u                   /* why: a job ended (the chip's job tail: forced) */
#define S5_PASS_POST            2u                   /* L1 served a post that queued no item */
#define S5_PASS_BLK             4u                   /* the synth mixed a block (CAUSE.BLK) */
typedef struct { uint32_t blk, item, bracket, tail, skip_job, skip_same, post, retry; } s5_pass_stats_t;
extern s5_pass_stats_t s5_pass_stats;                /* TEST: CAUSE.BLK entries; passes in items / after blocks /
                                                        job tails; passes skipped (a job queued; no block since);
                                                        passes after a post with no item; bracketed reads made
                                                        again because a block ran during them */
/* test build 5's TEST image: the counts behind the synth's TEST assertions and the boot facts, kept by
   core/sched/s5_glue.c and written by the debug save (board/pocket/dbgsave.c, version 9):
     A1 "no non-DONE write while RUN": DIAG.WBUSY counts every MCU write while a block runs (docs/MCU_INTERFACE.md v1.3
        3.10.1), DONE stores included; the writes that can meet RUN are the DONE stores made with no hold-off
        (done_free counts them: L1's DONE after a post with no item, and one at the end of an item with no arrival;
        done_wbusy = the WBUSY they added, DIAG read just before and just after each, interrupts off: measured 1-2 a
        run) and the stores of the items with no arrival of their own, the module starts + C6 items: SQ_JOB, the 8C
        job's module start (the job tail, which can be preempted), and SQ_CALL, C6's two engine call items
        song_c6_init and song_c6_ready (the cart chip's audio set-up, in thread mode and preemptible the same way;
        song_c6_init's window holds C6's CONFIG write, the DT start). They are the only items with no arrival
        (song_job_done's one caller is the 8C job, song_call's is C6's c6_item, twice).
        jobs = those items (module starts + C6 items: the 8C's module starts and C6's two a boot), job_wbusy = the
        WBUSY their stores added (DIAG read at the item's begin and after its stores; no free DONE store can fall
        inside that window: song_l1_end writes none while an item is queued or running), overlaps = those items with
        any. A1 fails when WBUSY > done_wbusy + job_wbusy ("no non-DONE write while RUN", except the stores of the
        module-start item and of C6's two engine call items, which are the cart chip's preemptible engine items, and
        nothing else): any other write met a block (a store of a post's or a tick's item, an item's DONE made while a
        block ran, a CONFIG write outside C6's init item); job_wbusy itself is a diagnostic, counted and reported,
        never a failure;
     A2 DIAG.UNDERRUN <= the DT starts (dt_starts: CONFIG writes with MODE = DT; the pre-roll take after a DT start
        may miss);
     A3 DIAG.TIMEOUTS = 0 (no instant serviced on the 5 ms TIMEOUT).
   t_config: the board time of the first CONFIG write of this boot (a warm boot's flush window). */
typedef struct { uint32_t done_free, dt_starts, jobs, overlaps, t_config, job_wbusy, done_wbusy; } s5_test_stats_t;
extern s5_test_stats_t s5_test;                      /* TEST (zero in RELEASE builds, never written) */
#endif

#endif
