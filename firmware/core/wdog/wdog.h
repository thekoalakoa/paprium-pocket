/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/wdog/wdog.h - the cart chip's TIM7 housekeeping tick: the watchdog and the heartbeat, the same steps as the
 * cart chip's (the STM32 microcontroller on the real cartridge), with the Pocket-menu gate. The fatal halt they end in
 * is core/trace (fatal.h). */
#ifndef CORE_WDOG_H
#define CORE_WDOG_H

#include <stdint.h>

/* the TIM7 tick on the timer wheel (WH_WDOG): first tick CLK_TIM7 from now. The board boot calls it once, after the
   acknowledges of docs/MCU_INTERFACE.md rule 6.3.1 and before the lines are enabled (the cart chip starts TIM7 in its
   board init 0x08020828, just before app init; the watchdog is disarmed until 81, so the phase is not seen) */
void wdog_start(void);

/* TEST counters (the TEST telemetry stores them; RELEASE keeps them at 0) */
typedef struct {
    uint32_t ticks;             /* TIM7 ticks run: the MCU heartbeat of the freeze telemetry */
    uint32_t gated;             /* ticks that skipped the watchdog because the Pocket menu was open (row B7) */
    uint32_t merged;            /* TIM7 periods merged into one tick (L2a held up for more than a period) */
    uint32_t arm_max;           /* the highest watchdog count seen (G+0x190; 41 trips) */
} wdog_stats_t;
extern wdog_stats_t wdog_stats;

#endif
