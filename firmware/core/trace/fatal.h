/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/trace/fatal.h - event_post's fatal half (fatal.c) and the MCU self-reset (mcureset.c), the same steps as the
 * cart chip's (the STM32 microcontroller on the real cartridge). fatal_halt itself is declared in core/dispatch/disp.h
 * (event.c calls it). */
#ifndef CORE_FATAL_H
#define CORE_FATAL_H

#include <stdint.h>

/* 0x0801FCC8: interrupts off, $1FE4 := 0 (a direct store), the MCU reset. Ours: the cart's MCU-only reset,
   brd_full_reset (docs/ALLOWLIST.md, row B17: the 68000 is held, the firmware restarts, the RTL state stays) */
void mcu_reset(void) __attribute__((noreturn));

/* a busy wait of n board-timer cycles: the cart chip's delay() 0x08020880 (SysTick at 96 MHz), ours on TIMER */
void chip_wait(uint32_t n);

/* TEST record of the halt (stored in the debug save) */
typedef struct {
    uint32_t code;              /* event_post's r0 (0 = no halt) */
    uint32_t a, b;              /* r1, r2 */
    uint32_t time;              /* brd_now() at the halt */
    uint32_t polls;             /* "WE SUX" polls made */
} fatal_rec_t;
extern volatile fatal_rec_t fatal_rec;

#endif
