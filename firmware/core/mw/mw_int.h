/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/mw/mw_int.h - the MegaWire port's internal calls (SRAM image only; mw.h has the interface). */
#ifndef CORE_MW_INT_H
#define CORE_MW_INT_H

#include <stdint.h>

void mw_op(uint16_t op);                        /* 0x08020EDC */
void mw_result(uint32_t sub, uint32_t code, uint32_t store, uint32_t len);     /* 0x08021338 */
void mw_drv_step(void);                         /* 0x0801E824 (mw_drv.c) */

/* the module's hardware as the chip drives it (mw_drv.c): with no module socket on the Pocket these read what the
   cart's pins read with nothing plugged in, and set nothing */
uint32_t mw_hw_adc(uint32_t ch);                /* 0x08020150: ADC1, 8 bits (the detect pin PA6 on channel 6) */
uint32_t mw_hw_rx_high(void);                   /* GPIOB IDR bit 11: the module's TX (our RX) line */

#endif
