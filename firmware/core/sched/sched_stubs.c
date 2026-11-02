/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/sched/sched_stubs.c - weak defaults of the scheduler hooks (core/sched/sched_hooks.h) for the scheduler's first
 * skeleton. Each owner module replaces its hooks with strong definitions; nothing here may survive into the FW_S5 = 0
 * test and release images (tests/check_images.py s1 fails if the test or release image links a byte of this file or
 * disp_stubs.c). Only the probe images may still use them. The stack bound does not trust these bodies:
 * tools/stack_s1.json stands a PROXY depth in for each one ("stand_in").
 * What the defaults mean: no post is dispatched (core/dispatch), the tick never starts (the song engine), no brain
 * (buddy/), no job, no wheel user (core/wdog, interim/s1). */
#include <stdint.h>
#include "sched_hooks.h"

#define WEAK __attribute__((weak))

WEAK void disp_post(uint32_t mbx, uint16_t word) { (void)mbx; (void)word; }
WEAK uint32_t disp_holdable(uint32_t mbx, uint16_t word) { (void)mbx; (void)word; return 0u; }
WEAK void disp_tick_tail(void) { }
WEAK void disp_console_reset(void) { }
#if FW_S5
WEAK void boot_warm_page(void) { }                 /* the probe images link no core/boot */
#endif
WEAK void l3_brain(void) { }
WEAK void brain_poll(void) { }
WEAK uint32_t brain_fault(uint32_t mepc) { (void)mepc; return 0u; }
WEAK uint32_t audio_tick_slice(void) { return 0u; }
WEAK void audio_tick_end(void) { }
WEAK uint32_t l3_job(void) { return 0u; }
WEAK uint32_t l3_test_work(void) { return 0u; }
WEAK void l3_idle(void) { }
WEAK void wh_wdog(uint32_t due) { (void)due; }
WEAK void wh_feed(uint32_t due) { (void)due; }
WEAK void wh_vu(uint32_t due) { (void)due; }
WEAK void wh_test(uint32_t due) { (void)due; }
