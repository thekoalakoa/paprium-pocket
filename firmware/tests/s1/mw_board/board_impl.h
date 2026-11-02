/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/mw_board/board_impl.h - the minimal host board of tests/s1/mw_host.c (the MegaWire port's oracle
 * harness, tests/equiv/mw_oracle.py and tests/equiv/mw_screen.py): cart RAM, the ROM, the SDRAM workspace and CRAM
 * MWTEXT as arrays, the options word, interrupts as a counter, the board timer and $1FEA as variables. Only what
 * core/mw and its stubs use is defined. */
#ifndef MW_BOARD_IMPL_H
#define MW_BOARD_IMPL_H
#include <stdint.h>

extern uint16_t mwh_ram[0x1000];
extern uint16_t mwh_romw[0x400000];      /* the ROM as 68000 words (the board's word view) */
extern uint32_t mwh_options;
extern uint32_t mwh_irq;

static inline volatile uint16_t *brd_cart_ram(void) { return mwh_ram; }
static inline volatile uint16_t *brd_rom(void) { return mwh_romw; }
uint8_t mwh_rom_byte(uint32_t a);
static inline uint8_t brd_rom_byte(uint32_t a) { return mwh_rom_byte(a); }
static inline uint32_t brd_options(void) { return mwh_options; }
static inline uint32_t brd_irq_save(void) { return mwh_irq++; }
static inline void brd_irq_restore(uint32_t s) { mwh_irq = s; }
extern uint32_t mwh_time;                /* the board timer (the screen's waits: tests/equiv/mw_screen.py) */
static inline uint32_t brd_now(void) { return mwh_time; }
extern uint16_t mwh_fea;                 /* $1FEA as the MCU reads it */
static inline uint16_t brd_freg_rd(unsigned off) { return off == 0x0Au ? mwh_fea : 0u; }
void mwh_freg_wr(unsigned off, uint16_t v);
static inline void brd_freg_wr(unsigned off, uint16_t v) { mwh_freg_wr(off, v); }
extern uint8_t mwh_ws[0x20000];          /* the SDRAM workspace's first 128 KB (the chip's 0xC0000000) */
static inline volatile uint8_t *brd_workspace(void) { return mwh_ws; }
extern uint8_t mwh_rom8[0x800000];       /* the ROM's bytes (the flash byte view) */
static inline const uint8_t *brd_flash8(void) { return mwh_rom8; }
extern uint8_t mwh_text[0x30000];        /* CRAM MWTEXT */
static inline volatile uint8_t *brd_mwtext(void) { return mwh_text; }
#endif
