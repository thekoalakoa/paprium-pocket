/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/dispatch/disp_stubs.c - weak defaults of the hooks the dispatcher calls that another module defines.
 * Each owner replaces its hook with a strong definition; tools/stack_s1.json stands a depth in for each default.
 *   fatal_halt        core/trace/fatal.c (the fatal-halt subset: LED code, "WE SUX" poll, MCU reset = brd_full_reset).
 *                     The default: interrupts off, the 68000 keeps running on what it has, the MCU stops (the cart
 *                     chip's halt without the backdoor). Reached only by 85 and the fatal paths, none of which the
 *                     game posts.
 *   audio_tick_begin  the song tick (interim/s1/audio_s1.c defines one): 0 = the tick is empty, L1 (the mailbox
 *                     interrupt) finishes inline. */
#include <stdint.h>
#include "board.h"
#include "disp.h"

#define WEAK __attribute__((weak))

WEAK void fatal_halt(uint32_t code, uint32_t a, uint32_t b)
{
    (void)code;
    (void)a;
    (void)b;
    (void)brd_irq_save();
    for (;;)
        ;
}

WEAK uint32_t audio_tick_begin(uint32_t stamp)
{
    (void)stamp;
    return 0u;
}
