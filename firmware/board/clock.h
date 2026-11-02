/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/clock.h - the one build-time clock value and the clock-following figures (board interface v1.0).
 *
 * The clock rule (docs/MCU_INTERFACE.md section 7; B Jam's decision of 2026-10-10, "clock-following timers"): the MCU
 * runs at the board clock BRD_CLK_HZ, which comes from the build only (fwbuild.json "clk_hz" per layout, passed as
 * -DBRD_CLK_HZ by tools/fwbuild.py) and equals the RTL's CLK_HZ parameter (NTSC 53,693,175 Hz; a PAL build
 * 53,203,424 Hz). No source file holds a clock literal (tests/check_clock.py). crt0 compares BRD_CLK_HZ with NEORV32
 * SYSINFO_CLK before anything else runs.
 *
 * Rule: what the chip times by its own clock, ours times in nanoseconds here and converts with BRD_CLK_HZ (rounded
 * to the nearest cycle); what the chip times by the console frame, ours counts in frames (9494 posts) and keeps out
 * of this file. CPU work (trap costs, slice lengths, feeder jitter) stays in cycles: it scales with the clock by
 * itself. tests/check_clock.py (test T23) builds at 53,693,175 and 53,203,424 Hz and proves every figure below equal in
 * time (+-1 cycle), the NTSC values equal to 0.2.6's literals, and two s1 images (the new-core source set) different
 * only in these figures. Each figure says how it is known: "known from our study of the cart", "inferred", or "estimated" (a
 * number from the firmware's interrupt design, not measured). */
#ifndef BOARD_CLOCK_H
#define BOARD_CLOCK_H

#include <stdint.h>

#ifndef BRD_CLK_HZ
#error "BRD_CLK_HZ comes from the build (fwbuild.json clk_hz); no source file may define the clock"
#endif

/* cycles for a time, rounded to the nearest cycle; compile-time when the argument is a constant */
#define BRD_CYC_NS(ns)  ((uint32_t)((((uint64_t)(ns)) * (uint64_t)(BRD_CLK_HZ) + 500000000ull) / 1000000000ull))
#define BRD_CYC_US(us)  BRD_CYC_NS((uint64_t)(us) * 1000ull)

/* ---- the clock-following figures (MCU_INTERFACE.md 7) --------------------------------------------------------- */
/* 1 ms as the 0.2.6 RTL ms counter counted it (CLK_FREQ / 1000, truncated); CPU MATE's (buddy) BUDDY_MS_CYCLES */
#define CLK_MS_CYCLES           ((uint32_t)(BRD_CLK_HZ / 1000u))
/* 84: the chip's delay(9,600 SysTick) at 96 MHz before it turns the window off (known from our study of the cart) */
#define CLK_84_DELAY_NS         100000u
#define CLK_84_DELAY            BRD_CYC_NS(CLK_84_DELAY_NS)
/* TIM7 period: heartbeat, watchdog tick, MegaWire task; (PSC 979 + 1) x (ARR 5000 + 1) at a 48 MHz timer clock
   (inferred) */
#define CLK_TIM7_NS             102103750u
#define CLK_TIM7                BRD_CYC_NS(CLK_TIM7_NS)
/* interim SFX feeder grid (CPU MATE's BUDDY_FEED_PERIOD; 0.2.6 used 7,168 cycles = 133.5 us at the NTSC clock) */
#define CLK_FEED_NS             133500u
#define CLK_FEED                BRD_CYC_NS(CLK_FEED_NS)
/* urgent song-tick promotion after the 9494 (estimated in the firmware's interrupt design; the s1 images arm it only
   in the TEST probe) */
#define CLK_URGENT_NS           737500u
#define CLK_URGENT              BRD_CYC_NS(CLK_URGENT_NS)
/* FW_S5: the tick still waiting this long after its 9494 (STAMP_A) is finished with interrupts off (level L2a;
   MCU_INTERFACE.md v1.3 4.6: TCMP = STAMP_A + 1.8 ms); the Z80 reads the packet ~3.0 ms after the 9494 (measured in
   a co-simulation: the firmware running on a simulation of the RTL) */
#define CLK_URGENT5_NS          1800000u
#define CLK_URGENT5             BRD_CYC_NS(CLK_URGENT5_NS)
/* the fatal halt's "WE SUX" poll period: the chip's delay(960 SysTick) at 96 MHz between two polls of $1FEA (known from
   our study of the cart) */
#define CLK_FATAL_POLL_NS       10000u
#define CLK_FATAL_POLL          BRD_CYC_NS(CLK_FATAL_POLL_NS)
/* the C6 hold's guard (core/dispatch/jobs.c; docs/ALLOWLIST.md, row B34): the hold counts VDP frames (VSCNT); a count
   that stops (a dead VDP) ends it this long after the C600 post (the hold itself: 80 frames, 1.34 s NTSC / 1.6 s PAL) */
#define CLK_C6_HOLD_MAX_NS      2000000000u
#define CLK_C6_HOLD_MAX         BRD_CYC_NS(CLK_C6_HOLD_MAX_NS)
/* FW_S5: the cart chip's 8C job time, which our 8C job holds (level L2c; B Jam's decision of 2026-10-10 that the game
   sees the cart's timing; core/dispatch/jobs.c): 10,209 + 11.10 Thumb instructions a decoded byte (the decode and
   the module start, measured, fit residual <= 10.6 %) at the chip's 96 MHz, one
   instruction a cycle (estimated; the chip's real speed is not known): 106,343.75 ns, + 115.625 ns a decoded byte =
   115,625 ns a thousand bytes */
#define CLK_JOB8C_NS            106344u
#define CLK_JOB8C               BRD_CYC_NS(CLK_JOB8C_NS)
#define CLK_JOB8C_KB_NS         115625u
#define CLK_JOB8C_KB            BRD_CYC_NS(CLK_JOB8C_KB_NS)
/* FW_S5 (test build S3a on): 83's frame-period check (core/dispatch/disp.c f_83; the chip's routine at 0x080209B4). The
   chip measures on its SysTick, 24 bits at 96 MHz, so the time it sees wraps at 2^24 / 96 MHz; the frame period it
   accepts lies in one of two windows of whole microseconds, 18,621-21,619 and 15,489-17,887 (each _END below is
   exclusive; known from our study of the cart) */
#define CLK_83_WRAP_NS          174762667u
#define CLK_83_WRAP             BRD_CYC_NS(CLK_83_WRAP_NS)
#define CLK_83_A_NS             18621000u
#define CLK_83_A                BRD_CYC_NS(CLK_83_A_NS)
#define CLK_83_A_END_NS         21620000u
#define CLK_83_A_END            BRD_CYC_NS(CLK_83_A_END_NS)
#define CLK_83_B_NS             15489000u
#define CLK_83_B                BRD_CYC_NS(CLK_83_B_NS)
#define CLK_83_B_END_NS         17888000u
#define CLK_83_B_END            BRD_CYC_NS(CLK_83_B_END_NS)
/* FW_MW (test build S3b on; core/sched/sched.c): the MegaWire task waits while the game's sprite frame is open (AE
   taken, AF not yet), but not for one the thread first saw longer ago than this (two NTSC frames): the game keeps some
   frames open for many frames, and the Options pad code's A858 jumps to cart RAM before its AF; neither may stop the
   task */
#define CLK_MW_SPRITE_MAX_NS    33400000u
#define CLK_MW_SPRITE_MAX       BRD_CYC_NS(CLK_MW_SPRITE_MAX_NS)

#endif
