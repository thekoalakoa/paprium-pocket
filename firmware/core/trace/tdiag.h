/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/trace/tdiag.h - how much TEST-only diagnostics an image carries (C and assembler files include it).
 *
 * TDIAG_LEAN 1: the FW_S5 TEST images on the Pocket (FW_S5 RV32 builds, test build S3a on; FW_S5 = the full firmware,
 * board/board.h).
 * Their debug save (board/pocket/dbgsave.h, version 10) keeps only what has caught problems on hardware: the lateness
 * signs (the RTL sprite decoder's late words and flags, the synth's TIMEOUTs, failed jobs and refusals, exceptions, the
 * stack floor), the freeze telemetry (the MCU heartbeat, the last post, the VDP's vertical-sync count, the frame ticks:
 * which side stopped, and a fatal halt's record) and the CPU MATE counters (discarded, aborted, the answers armed late,
 * the longest call), carried across the Quit's reboot. Every other TEST-only probe, check and record is left out of
 * them: the per-level cycle counters and the boot milestones (core/sched/stats.h), the synth's TEST assertions and the
 * main-loop pass counts (core/sched/s5_glue.c), the register-write log of the comparison with the cart chip
 * (board/pocket/s1_freg.h), the boot cache's record history (board/pocket/s1_cache4b.c), the dispatcher's, the
 * scheduler's, the watchdog's and the sprite engine's other counters, C6's hold record, and the AF reply's early finish
 * that only the retired SAT snapshot needed.
 * TDIAG_LEAN 0: everything else. RELEASE builds none of it either way; the FW_S5 = 0 TEST images (which no current
 * hardware test build carries) keep the full set their test rigs read (debug save version 8); the host builds keep it
 * for their unit tests; the scheduler probes keep their own. */
#ifndef CORE_TRACE_TDIAG_H
#define CORE_TRACE_TDIAG_H

#if !PPM_RELEASE && !S1_PROBE && defined(FW_S5) && FW_S5 && defined(__riscv)
#define TDIAG_LEAN              1
#else
#define TDIAG_LEAN              0
#endif

#endif
