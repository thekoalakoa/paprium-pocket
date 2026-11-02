/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/trace/fatal.c - event_post's fatal half 0x08020B56-0x08020C7C and the MCU self-reset 0x0801FCC8. The hex
 * numbers are the cart chip's addresses; the cart chip is the STM32 microcontroller on the real cartridge.
 *
 * event_post (0x08020B24, core/dispatch/event.c) is fatal when its third argument is not 0: 85, the watchdog and the
 * heartbeat (core/wdog), and the cart chip's other fatal paths. The cart chip then, with interrupts off for good:
 *   1. shows the code on a debug LED (0x08020B58-0x08020BC4): pin low, delay 10 ms; for each of the code's bits 0-15
 *      a set bit drives the pin high at once, a clear bit drives it low and waits 1 ms; pin low, delay 10 ms;
 *   2. polls the low byte of $1FEA (as the 68000 last wrote it) every delay(960) = 10 us for the bytes 'W', 'E', ' ',
 *      'S', 'U', 'X' and 0, one state per poll (0x08020BDA-0x08020C4C, a 7-way byte jump table at 0x08020BEA): state n
 *      advances when its byte is seen and falls back to 0 on any other byte; state 6 resets the MCU on a 0 byte. The
 *      poll also blinks a second LED every 4,000 / 8,000 polls (0x08020C54-0x08020C6E).
 * The Pocket has no LED: the LED writes are left out, their waits kept, so the poll starts when the cart chip's does
 * and runs at the cart chip's rate (the backdoor's timing is the 68000's to see). No game code sends the backdoor
 * (docs/BOOT_SPEC.md, row AL-03); while the MCU is halted the 68000 runs on what it has, as on the cart.
 * TEST: the halt reaches the .sav. Interrupts stay off from here on, so the debug save's periodic write
 * (the wheel, L2a) never comes again: brd_milestone(ST_MS_FATAL) writes the record at once, inside the first 10 ms
 * wait (which then runs to its deadline, so the poll still starts when the cart chip's does), and again every 65,536
 * polls (~0.66 s; one write, ~2-15k cycles, between two polls) so the record shows the halt still running. */
#include <stdint.h>
#include "board.h"
#include "disp.h"
#include "fatal.h"
#include "stats.h"

volatile fatal_rec_t fatal_rec;

static void fatal_ms(uint32_t ms)
{
    while (ms--)
        chip_wait(CLK_MS_CYCLES);                           /* delay(96,000) = 1 ms at 96 MHz */
}

#if !PPM_RELEASE && !TDIAG_LEAN
static __attribute__((noinline)) void fatal_poll_count(void)   /* TEST: one poll counted; every 65,536th rewrites the */
{                                                              /* debug save (the halt still running) */
    fatal_rec.polls++;
    if (!(fatal_rec.polls & 0xFFFFu))
        brd_milestone(ST_MS_FATAL);
}
#endif

void fatal_halt(uint32_t code, uint32_t a, uint32_t b)
{
    uint32_t i, st = 0u;
    (void)brd_irq_save();                                   /* 0x08020B56 cpsid i */
#if TDIAG_LEAN                                  /* lean TEST (tdiag.h; test build S3a on): the record, then
                                                   RELEASE's halt */
    fatal_rec.code = code;
    fatal_rec.a = a;
    fatal_rec.b = b;
    fatal_rec.time = brd_now();
    brd_milestone(ST_MS_FATAL);                             /* the debug save written now */
    fatal_ms(10u);                                          /* 0x08020B8A-0x08020B90: delay(960,000) */
#elif !PPM_RELEASE
    fatal_rec.code = code;
    fatal_rec.a = a;
    fatal_rec.b = b;
    fatal_rec.time = brd_now();
    ST_MARK(ST_MS_FATAL);
    brd_milestone(ST_MS_FATAL);                             /* the debug save written now (board/pocket/dbgsave.c) */
    {
        volatile uint32_t n = 10u;                          /* the rest of 0x08020B8A-0x08020B90: delay(960,000) on */
        for (i = 0, st = fatal_rec.time; i < n; i++) {      /* 1 ms deadlines from the halt; n volatile, so the */
            st += CLK_MS_CYCLES;                            /* compiler folds no product of the clock figure */
                                                            /* (tests/check_clock.py, test T23) */
            while (brd_until(st) > 0)
                ;
        }
        st = 0u;
    }
#else
    (void)a;
    (void)b;
    fatal_ms(10u);                                          /* 0x08020B8A-0x08020B90: delay(960,000) */
#endif
    for (i = 0; i < 16u; i++)                               /* 0x08020B96-0x08020BB6 */
        if (!(code & (1u << i)))
            fatal_ms(1u);                                   /* 0x08020BAA-0x08020BAE: delay(96,000) */
    fatal_ms(10u);                                          /* 0x08020BC0-0x08020BC2: delay(960,000) */
    for (;;) {
        uint8_t c = (uint8_t)brd_freg_rd(BRD_FREG_FEA);     /* 0x08020BF2 ...: ldrh $1FEA, & 0xFF */
#if !PPM_RELEASE && !TDIAG_LEAN
        fatal_poll_count();
#endif
        switch (st) {                                       /* the jump table at 0x08020BEA */
        case 0: st = (c == 0x57u) ? 1u : 0u; break;         /* 0x08020BF2 'W' */
        case 1: st = (c == 0x45u) ? 2u : 0u; break;         /* 0x08020C00 'E' */
        case 2: st = (c == 0x20u) ? 3u : 0u; break;         /* 0x08020C0E ' ' */
        case 3: st = (c == 0x53u) ? 4u : 0u; break;         /* 0x08020C1C 'S' */
        case 4: st = (c == 0x55u) ? 5u : 0u; break;         /* 0x08020C2A 'U' */
        case 5: st = (c == 0x58u) ? 6u : 0u; break;         /* 0x08020C38 'X' */
        default:                                            /* 0x08020C46: state 6 */
            if (c == 0u)
                mcu_reset();                                /* 0x08020C4C */
            st = 0u;                                        /* 0x08020C52 */
            break;
        }
        chip_wait(CLK_FATAL_POLL);                          /* 0x08020C70-0x08020C78: delay(960) = 10 us */
    }
}
