/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/trace/mcureset.c - the MCU self-reset 0x0801FCC8 and the cart chip's busy wait 0x08020880 (cart chip addresses;
 * the cart chip is the STM32 microcontroller on the real cartridge).
 *
 * Callers: the fatal halt's "WE SUX" backdoor (fatal.c) and the watchdog with 81 bit 4 (core/wdog). Kept apart from
 * fatal.c so the host replay (tests/s1/s1_ours.c), which stops a post where the cart chip halts, can link the watchdog
 * without the halt's endless poll. */
#include <stdint.h>
#include "board.h"
#include "disp.h"
#include "fatal.h"

void chip_wait(uint32_t n)
{
    uint32_t end = brd_now() + n;
    while (brd_until(end) > 0)
        ;
}

void mcu_reset(void)
{
    (void)brd_irq_save();                                   /* 0x0801FCCA cpsid i */
    st_raw_fe4(0u);                                         /* 0x0801FCD2: a direct store */
    brd_full_reset();                                       /* 0x0801FCD6: NVIC_SystemReset; ours: docs/ALLOWLIST.md,
                                                               row B17 */
}
