/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/wdog/wdog.c - the cart chip's TIM7 tick: watchdog 0x08020E50 and heartbeat 0x08020DE8, the same steps as the
 * cart chip's (the cart chip is the STM32 microcontroller on the real cartridge; the hex numbers are its addresses).
 *
 * The cart chip's TIM7 (PSC 979, ARR 5000; ~9.8 Hz on a 48 MHz timer clock, which is inferred) interrupt 0x08015400
 * runs, in this order, the watchdog 0x08020E50, the heartbeat 0x08020DE8 and the MegaWire task 0x080219CC (core/mw).
 * Ours is the wheel slot WH_WDOG every CLK_TIM7 (board/clock.h, a time: the same period at either build clock;
 * tests/check_clock.py, test T23).
 *
 * Watchdog state lives in the cart chip's global block (disp_g, core/dispatch/disp.h), written where ours has the cart
 * chip's code that sets it (core/boot/appinit.c, core/dispatch/disp.c, core/mw/mw_screen.c):
 *   G+0x190 (wd_arm): app start := 0, then app init := 1 (0x0801F9F8); 81 := 1; 84 and A858 := 0; every 9494 := 2 if
 *     it is not 0. The tick counts it only above 1, so it runs from the first 9494 after app init (the game posts 81
 *     at frame 169 and the first 9494 at frame 190; 84 switches it off for good) and trips on the tick that takes it
 *     past 40: the 39th tick with no 9494 in between (3.88-3.98 s at the inferred TIM7 rate);
 *   G+0x192 (wd_count): app start := 0, app init := 1 (0x0801FA04); every 9494, 84 and A858 := 0; the tick counts it
 *     only above 1 and trips past 100. Nothing raises it above 1, so it has no effect; kept all the same.
 *   G+0xC (f81[3], 81 bit 4): a trip resets the MCU instead of halting (the game posts 810E / 810F: bit 4 clear, so
 *     the cart halts; docs/ALLOWLIST.md, row B17 maps the reset to our full cart reset).
 * The heartbeat counts G+0x194 only above 1; app start sets 1 and nothing else writes it, so it has no effect either;
 * kept all the same: past 2,400 ticks it clears $1FE4 bit 13 and stops, and while it runs a set $1FE4 bit 11 (the MCU
 * word, the cart chip's EEPROM-job flag) is fatal (0x400000FB).
 *
 * Ours only (docs/ALLOWLIST.md, row B7): the watchdog does not count while the Pocket menu is open (the 68000 is
 * paused there, so no 9494 comes); the heartbeat is not gated. TIM7 has one update flag, so periods missed while L2a
 * (the timer interrupt level) is held up merge into one tick (only the boot can hold it that long). */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "disp.h"
#include "fatal.h"
#include "wdog.h"
#include "tdiag.h"
#if FW_MW
#include "mw.h"
#endif

/* WDOG_BUG: a planted bug for the negative controls of the RV32 fuzz test only (fwbuild.json s1 variant
   test_bug_wdog; never defined in an image that ships): 1 = the Pocket-menu gate is left out (property FZ10) */
#ifndef WDOG_BUG
#define WDOG_BUG 0
#endif

#if PPM_RELEASE
#define WD_COUNT(f)             ((void)0)
#elif TDIAG_LEAN                                /* the lean TEST image (tdiag.h; test build S3a on): the
                                                   heartbeat only */
#define WD_COUNT(f)             (WD_KEEP_##f)
#define WD_KEEP_ticks           (wdog_stats.ticks++)
#define WD_KEEP_gated           ((void)0)
#define WD_KEEP_merged          ((void)0)
#else
#define WD_COUNT(f)             (wdog_stats.f++)
#endif

wdog_stats_t wdog_stats;

void wdog_start(void)
{
    wheel_arm(WH_WDOG, brd_now() + CLK_TIM7);
}

/* 0x08020EAA-0x08020EC0: the trip (and the G+0x192 path) */
static void __attribute__((noreturn)) wd_trip(void)
{
    (void)brd_irq_save();                                   /* 0x08020EAA cpsid i: never re-enabled */
    brd_freg_wr(BRD_FREG_FEE, 0xAF5Bu);                     /* 0x08020EB4: the window off, the mini view */
    st_raw_fe4(0x4200u);                                    /* 0x08020EBA: a direct store; the helper's shadow stays */
    chip_trace(0x400000FAu, 0x80u, 0x28u);                  /* 0x08020EC0: event_post, fatal: never returns */
    for (;;)
        ;
}

/* 0x08020E86-0x08020EA4: the trip with 81 bit 4 set: $1FE4 := 0, 300 x delay(96,000) = 300 ms, MCU reset */
static void __attribute__((noreturn)) wd_reset(void)
{
    uint32_t n;
    (void)brd_irq_save();                                   /* 0x08020E86 */
    st_raw_fe4(0u);                                         /* 0x08020E94 */
    for (n = 300u; n; n--)                                  /* 0x08020E8A-0x08020EA2 */
        chip_wait(CLK_MS_CYCLES);
    mcu_reset();                                            /* 0x08020EA4 */
}

/* 0x08020E50 */
static void wd_watchdog(void)
{
    if (disp_g.wd_count > 1u) {                             /* 0x08020E52-0x08020E5C */
        disp_g.wd_count = (uint16_t)(disp_g.wd_count + 1u); /* 0x08020E6A-0x08020E6E */
        if (disp_g.wd_count > 100u)                         /* 0x08020E70 */
            wd_trip();
    }
    if (disp_g.wd_arm > 1u) {                               /* 0x08020E5E-0x08020E66 */
        disp_g.wd_arm = (uint16_t)(disp_g.wd_arm + 1u);     /* 0x08020E76-0x08020E7A */
#if !PPM_RELEASE && !TDIAG_LEAN
        if (disp_g.wd_arm > wdog_stats.arm_max)
            wdog_stats.arm_max = disp_g.wd_arm;
#endif
        if (disp_g.wd_arm > 40u) {                          /* 0x08020E7C */
            if (disp_g.f81[3])                              /* 0x08020E80: 81 bit 4 */
                wd_reset();
            wd_trip();
        }
    }
}

/* 0x08020DE8 */
static void wd_heartbeat(void)
{
    if (disp_g.g194 <= 1u)                                  /* 0x08020DF0-0x08020DF4 */
        return;
    if (brd_freg_rd(BRD_FREG_FE4) & 0x0800u) {              /* 0x08020DFA-0x08020DFE: the stored MCU word, bit 11 */
        (void)brd_irq_save();                               /* 0x08020E00 */
        brd_freg_wr(BRD_FREG_FEE, 0xAF5Bu);                 /* 0x08020E06 */
        st_raw_fe4(0x4200u);                                /* 0x08020E0C */
        chip_trace(0x400000FBu, 0x80u, 0x28u);              /* 0x08020E12: fatal, never returns */
    }
    disp_g.g194 = (uint16_t)(disp_g.g194 + 1u);             /* 0x08020E1C-0x08020E24 */
    if (disp_g.g194 > 2400u) {                              /* 0x08020E26 */
        st_set(0u, ST_FE4, 0x2000u);                        /* 0x08020E2A-0x08020E38 (the helper's own section) */
        disp_g.g194 = 0u;                                   /* 0x08020E3C */
    }
}

/* the TIM7 interrupt 0x08015400, on the wheel (L2a, MEI open) */
void wh_wdog(uint32_t due)
{
    uint32_t next = due + CLK_TIM7;
    while (brd_until(next) <= 0) {                          /* one update flag: missed periods merge */
        next += CLK_TIM7;
        WD_COUNT(merged);
    }
    wheel_arm(WH_WDOG, next);
    WD_COUNT(ticks);
    if (WDOG_BUG == 1 || !brd_menu_open())                  /* row B7: gated while the Pocket menu is open */
        wd_watchdog();                                      /* 0x0801541A */
    else
        WD_COUNT(gated);
    wd_heartbeat();                                         /* 0x0801541E */
    /* 0x08015422: the MegaWire task 0x080219CC (core/mw): the thread runs it (L3, below every reply path, as the
       cart's TIM7 at NVIC 4 runs below its music interrupts; at L2a its rare ticks would exceed test build 5's packet
       margin, estimated on a bench test at 0.95-2.89 ms with SRAM's costs) */
#if FW_MW
    if (s3_mw_on)
        mw_due = (uint8_t)(mw_due + 1u);                    /* one task run per tick (sched.c) */
#endif
}
