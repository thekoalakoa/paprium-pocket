/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/clock_probe.c - prints every clock-following figure of board/clock.h, and the buddy figures that follow
 * it in stage 1 (the FW_S1 builds of our new firmware: buddy/buddy.h), for the build clock. tests/check_clock.py
 * compiles it at both clocks and checks the numbers (test T23, docs/BOARD_IFACE.md section 6). One line per figure:
 * name, nanoseconds (0 = a counter figure), cycles. */
#include <stdio.h>
#include "board.h"
#include "buddy.h"

#define FIG(name, ns) printf("%s %lu %lu\n", #name, (unsigned long)(ns), (unsigned long)(name))

int main(void)
{
    printf("BRD_CLK_HZ 0 %lu\n", (unsigned long)BRD_CLK_HZ);
    FIG(CLK_MS_CYCLES, 1000000u);
    FIG(CLK_84_DELAY, CLK_84_DELAY_NS);
    FIG(CLK_TIM7, CLK_TIM7_NS);
    FIG(CLK_FEED, CLK_FEED_NS);
    FIG(CLK_URGENT, CLK_URGENT_NS);
    FIG(CLK_URGENT5, CLK_URGENT5_NS);
    FIG(CLK_FATAL_POLL, CLK_FATAL_POLL_NS);
    FIG(CLK_C6_HOLD_MAX, CLK_C6_HOLD_MAX_NS);
    FIG(CLK_JOB8C, CLK_JOB8C_NS);
    FIG(CLK_JOB8C_KB, CLK_JOB8C_KB_NS);
    FIG(CLK_83_WRAP, CLK_83_WRAP_NS);
    FIG(CLK_83_A, CLK_83_A_NS);
    FIG(CLK_83_A_END, CLK_83_A_END_NS);
    FIG(CLK_83_B, CLK_83_B_NS);
    FIG(CLK_83_B_END, CLK_83_B_END_NS);
    FIG(CLK_MW_SPRITE_MAX, CLK_MW_SPRITE_MAX_NS);
    FIG(BUDDY_MS_CYCLES, 1000000u);
    FIG(BUDDY_FEED_PERIOD, CLK_FEED_NS);
    /* CPU-work figures stay in cycles (MCU_INTERFACE.md 7): printed so the check sees them unchanged at both clocks */
    FIG(BUDDY_FEED_JITTER, 0u);
    FIG(BUDDY_FEED_RESCAN, 0u);
    FIG(BUDDY_VU_POLL, 0u);
    FIG(BUDDY_VU_CAL_MAX, 0u);
    return 0;
}
