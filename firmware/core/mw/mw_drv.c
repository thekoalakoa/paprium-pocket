/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/mw/mw_drv.c - the cart chip's MegaWire module driver step 0x0801E824, once a task tick (see mw.h).
 *
 * Driver block DRV (mw_ram.drv, the chip's 0x200100AC): +0x48 the AT bring-up done, +0x49 joined, +0x4A TCP up,
 * +0x4B probe cycles, +0x4C join tries, +0x58 present, +0x59 the RX line high, +0x5A last command, +0x5C the poll
 * count, +0x60 the driver state (u16), +0x62 the requested op, +0x107E the last ADC reading, +0x107F the power
 * profile (0 OFF, 1 AUTO, 2 FORCED; A4's low bits), +0x1080 RESTORE, +0x1081 the sub-state.
 * State 1 is the presence probe and the link-up, as the cart runs it: sub 0 releases the pins and counts a cycle,
 * sub 1 waits 6 ticks, sub 2 reads the detect pin (ADC channel 6, 8 bits) and needs two readings in 31..60 in a
 * row (else it waits to the 51st tick and starts over: one probe cycle every 57 ticks with nothing plugged in), sub 3
 * reads the RX line and applies the profile, sub 4 waits ~100 ticks (OFF), sub 5 waits 20 ticks after the link-up.
 * Not built yet (each needs a module): sub-states 6-21 (the AT bring-up: AT+RST ... AT+CWJAP_CUR?) and states 2-7
 * (join, connect, request, scan); see mw.h. */
#include <stdint.h>
#include "board.h"
#include "mw.h"
#include "mw_int.h"

/* ---- the module's pins and ADC with no module socket (STM32 plumbing: 0x08020150 HAL ADC, 0x08020898 /
   0x08020A98 / 0x08020AAC HAL GPIO, 0x080201BC USART3) ------------------------------------------------------ */
uint32_t mw_hw_adc(uint32_t ch)
{
    (void)ch;
    return 0u;                      /* nothing on the detect pin: 0, as the ADC of our model of the
                                       cart chip reads (a real cart's empty-pin reading is not measured; any value
                                       outside 31..60 takes the same path, only DRV+0x107E keeps it) */
}
uint32_t mw_hw_rx_high(void) { return 0u; }
static void mw_hw_pins(uint32_t pa0, int32_t pb10, int32_t pb11) { (void)pa0; (void)pb10; (void)pb11; }

#define SUB             MW8(drv, 0x1081)
#define POLL            MW16(drv, 0x5C)

/* 0x0801E8CE-0x0801E934: the probe cycle's reset (sub 0, and sub 4's time-out) */
static void drv_cycle_reset(void)
{
    MW16(drv, 0x5A) = 0u;
    POLL = 0u;
    MW8(drv, 0x48) = 0u;
    MW8(drv, 0x49) = 0u;
    MW8(drv, 0x4A) = 0u;
    MW8(drv, 0x4C) = 0u;
    MW16(drv, 0x1136) = 0u;
    MW16(drv, 0x1138) = 0u;
    MW16(drv, 0x113A) = 0u;
    MW16(drv, 0x113C) = 0u;
    MW16(drv, 0x113E) = 0u;
    MW8(drv, 0x4B) = (uint8_t)(MW8(drv, 0x4B) + 1u);       /* 0x0801E912-0x0801E916 */
    SUB = (uint8_t)(SUB + 1u);                              /* 0x0801E918-0x0801E91C */
    mw_hw_pins(0u, -1, -1);                                 /* 0x0801E91E: 0x08020A98(0): PA0 released (BSRR) */
    mw_hw_pins(0u, 1, -1);                                  /* 0x0801E924: 0x08020AAC(1): PB10 input, pull-up */
    mw_hw_pins(0u, -1, 2);                                  /* 0x0801E92A: 0x08020898(2): PB11 input (PB15 picks the pull) */
    POLL = 0u;                                              /* 0x0801E930 */
}

/* no jump table: its words would sit in the SRAM image's rodata, where tools/fwstack.py does not look for them */
__attribute__((optimize("no-jump-tables")))
void mw_drv_step(void)
{
    uint8_t prof = MW8(drv, 0x107F);                        /* 0x0801E834 */
    uint16_t n;
    if (prof == 0u || (prof == 1u && !MW8(drv, 0x59))) {    /* 0x0801E836-0x0801E846: OFF, or AUTO with the line low */
        if (MW16(drv, 0x60) != 1u || SUB > 4u) {            /* 0x0801E848-0x0801E858: back to the probe */
            MW16(drv, 0x60) = 1u;
            SUB = 0u;
        }
    }
    switch (MW16(drv, 0x60)) {                              /* 0x0801E866-0x0801E87A */
    case 1:
        break;
    case 2: case 3: case 4: case 5: case 6: case 7:         /* join, connect, request, scan: not built yet */
        mw_not_ported(0x0801E876u);
        return;
    default:                                                /* 0x0801F590: any other state: back to the probe */
        MW16(drv, 0x60) = 1u;
        SUB = 0u;
        return;
    }
    switch (SUB) {                                          /* 0x0801E888-0x0801E896 */
    case 1:                                                 /* 0x0801E936: wait 6 ticks */
        n = (uint16_t)(POLL + 1u);
        if (n <= 5u) {
            POLL = n;
            return;
        }
        POLL = 0u;
        SUB = 2u;                                           /* 0x0801E948-0x0801E9AA */
        return;
    case 2: {                                               /* 0x0801E950: the detect pin, twice in band */
        uint16_t old = POLL;
        uint32_t v;
        n = (uint16_t)(old + 1u);
        POLL = n;
        if (old > 1u) {                                     /* 0x0801E9A2: wait to the 51st, then start over */
            if (n > 0x32u)
                SUB = 0u;
            return;
        }
        v = mw_hw_adc(1u) & 0xFFu;                          /* 0x0801E962: 0x08020150(1) */
        MW8(drv, 0x107E) = (uint8_t)v;                      /* 0x0801E96A */
        if (v - 0x1Fu <= 0x1Du) {                           /* 0x0801E96C-0x0801E972: 31..60 */
            if (n != 2u)
                return;
            mw_hw_pins(0u, -1, 1);                          /* 0x0801E97C: 0x08020898(1): PB11 floating */
            MW8(drv, 0x58) = 1u;                            /* 0x0801E986: present */
            SUB = (uint8_t)(SUB + 1u);                      /* 0x0801E988-0x0801E98C */
            POLL = 0u;                                      /* 0x0801E99C */
            return;
        }
        if (n == 1u)                                        /* 0x0801E992-0x0801E99C: out of band at the first read */
            POLL = 2u;
        return;
    }
    case 3: {                                               /* 0x0801E9B0: the RX line and the profile */
        uint32_t hi;
        n = (uint16_t)(POLL + 1u);
        POLL = n;
        if (n <= 1u)
            return;
        hi = mw_hw_rx_high();                               /* 0x0801E9C2-0x0801E9CA: GPIOB IDR bit 11 */
        MW8(drv, 0x59) = hi ? 1u : 0u;
        if (prof == 0u) {                                   /* OFF: wait and probe again */
            POLL = 0u;                                      /* 0x0801E9DC */
            SUB = 4u;
            return;
        }
        if (!hi && prof <= 1u)                              /* AUTO waits for the line to go high */
            return;
        SUB = 5u;                                           /* 0x0801E9F4: the link-up */
        mw_hw_pins(0u, 0, -1);                              /* 0x0801E9FA: 0x08020AAC(0): PB10 USART3_TX */
        mw_hw_pins(0u, -1, 0);                              /* 0x0801EA00: 0x08020898(0): PB11 USART3_RX */
        mw_hw_pins(1u, -1, -1);                             /* 0x0801EA06: 0x08020A98(1): PA0 low */
        /* 0x0801EA0E: 0x080201BC(115,200): USART3 on (plumbing) */
        return;
    }
    case 4:                                                 /* 0x0801EA16: OFF: ~100 ticks, then probe again */
        n = (uint16_t)(POLL + 1u);
        POLL = n;
        if (n > 0x64u || prof != 0u) {
            SUB = 0u;                                       /* 0x0801EA2C */
            drv_cycle_reset();                              /* 0x0801EA30 -> 0x0801E8CE */
        }
        return;
    case 5:                                                 /* 0x0801EA32: 20 ticks after the link-up */
        n = (uint16_t)(POLL + 1u);
        POLL = n;
        if (n > 0x14u)
            SUB = 6u;
        return;
    case 6: case 7: case 8: case 9: case 10: case 11: case 12: case 13: case 14: case 15: case 16: case 17:
    case 18: case 19: case 20: case 21:                     /* 0x0801EA48-0x0801ED1A: the AT bring-up */
        mw_not_ported(0x0801EA48u);
        return;
    default:                                                /* 0x0801E8C0: sub 0 (and any value past 21) */
        MW8(drv, 0x58) = 0u;
        MW8(drv, 0x59) = 0u;
        drv_cycle_reset();
        return;
    }
}
