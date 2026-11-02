/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/sched/sched_hooks.h - what the scheduler calls in the rest of the core. Each hook names the module that defines
 * it. core/sched/sched_stubs.c gives weak defaults for builds without that module; tools/stack_s1.json stands a PROXY
 * depth in for each default (the stack bound must not get smaller because a body is missing). */
#ifndef CORE_SCHED_HOOKS_H
#define CORE_SCHED_HOOKS_H

#include <stdint.h>

/* core/dispatch: the cart chip's dispatcher (both mailboxes, gates, refusals, the status helper, the finish order) */
void     disp_post(uint32_t mbx, uint16_t word);     /* L1 (and the held-post replay, interrupts off) */
uint32_t disp_holdable(uint32_t mbx, uint16_t word); /* nonzero: an engine post that must wait for the tick end */
void     disp_tick_tail(void);                       /* the 9494 tail after the tick end ($1FEC := 0, status bit 15) */
void     disp_console_reset(void);                   /* CAUSE.V (EXTI 13): the cart chip only acknowledges */
#if FW_S5
/* CAUSE.V, before its acknowledgement: the board's warm vector page (core/boot/bootpage.c); only in the FW_S5 build
   (the full firmware, board/board.h), whose RTL (test build S3c on) holds the 68000 for it */
void     boot_warm_page(void);
/* FW_S5: L1's entry with the post's arrival number (SEQLAT) and stamp (STAMP_B / STAMP_A); the dispatcher
   finishes it at once, or the engine queue does when it was full (core/song/song_oeq.c) */
void     disp_post_s5(uint32_t mbx, uint16_t word, uint16_t seq, uint32_t stamp);
/* the cart chip's main loop: a job queued or running (0x0801A3AC: the thread runs it, not the pass), and the
   pass itself with the dispatcher's 81 flags (bit 1: the counters to $1B00, bit 2: the Boom Box feed) */
uint32_t disp_s5_jobs(void);
void     disp_s5_pass(void);
#endif

/* buddy/: the CPU MATE brain call (the thread, to completion, every interrupt open) */
void     l3_brain(void);
void     brain_poll(void);                           /* L1 and L2a while a call is in flight: ask an abort if needed */
uint32_t brain_fault(uint32_t mepc);                 /* an exception: nonzero = resume there (it aborted the call) */

/* the song engine; the FW_S5 = 0 build: empty (the tick never starts); TEST probe: a synthetic tick */
uint32_t audio_tick_slice(void);                     /* one slice; nonzero while slices remain */
void     audio_tick_end(void);                       /* the tick end: packet, $1880 copy, Boom Box feed */

/* core/dispatch: L2c (earlier, the thread): the name keeps the thread's l3_ prefix of the cart chip's main loop */
uint32_t l3_job(void);                               /* one job of the cart chip's queue; nonzero = ran one */
/* buddy/ and the TEST counters: the thread, below the brain call */
uint32_t l3_test_work(void);                         /* TEST's diagnostics with no deadline (interim: the SAT snapshot);
                                                        nonzero = did something; RELEASE: nothing */
void     l3_idle(void);                              /* housekeeping slices (buddy restart / restore, LSTAT polls) */

/* wheel callbacks (the table in core/sched/wheel.c): due = the deadline that fired */
void     wh_urgent(uint32_t due);                    /* sched */
void     wh_wdog(uint32_t due);                      /* core/wdog */
void     wh_feed(uint32_t due);                      /* interim/s1 */
void     wh_vu(uint32_t due);                        /* interim/s1 */
void     wh_test(uint32_t due);                      /* TEST probe */

/* (no decoder hook: the cart FPGA's sprite decoder is RTL, MCU interface v1.2) */

#endif
