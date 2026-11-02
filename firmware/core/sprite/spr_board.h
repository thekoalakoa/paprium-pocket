/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/sprite/spr_board.h - what the sprite engine reads and writes, through the board interface (board/board.h):
 *   - RAMDP, the 68000's cart RAM (the cart chip's FPGA view 0x68060000): halfword at byte offset A = 68000 word A;
 *   - the ROM through the flash word view (the cart chip's 0x6C000000): halfword at byte offset A = 68000 word A;
 *   - the anim container C6 unpacked into the workspace (the cart chip's SDRAM 0xC0000000), byte-native: spr_anim;
 *   - the song engine's frame rate (0x3C NTSC, 0x32 PAL; the 88 configuration writes it),
 *     read by the 50 Hz skip. The images without the song engine (the FW_S5 = 0 builds, with the interim audio) keep
 *     the same word beside the interim's 88 body (spr_rate).
 * The cart chip is the STM32 microcontroller on the real cartridge.
 */
#ifndef CORE_SPR_BOARD_H
#define CORE_SPR_BOARD_H
#include <stdint.h>
#include "board.h"

#define SPR_RAMDP       (brd_cart_ram())
#define SPR_RD(off)     (SPR_RAMDP[(off) >> 1])                 /* the RAMDP word at 68000 byte offset off */
#define SPR_RD32(off)   (*(volatile uint32_t *)&SPR_RAMDP[(off) >> 1])   /* two RAMDP words as one 32-bit access (off
                                                               4-aligned: the lower word in bits 0-15). The 68000 waits on
                                                               busy while a post's handler runs, so it never sees a half-
                                                               done pair: the words, their values and their order are the
                                                               cart chip's, as test build 5's engine stored them */
#define SPR_FLASH       ((const volatile uint8_t *)brd_rom())   /* the flash word view, byte addressed */
#define SPR_FL16(off)   (*(const volatile uint16_t *)(SPR_FLASH + (off)))

#if FW_S5
#include "song.h"
#define SPR_RATE()      (G.rate)
#else
extern uint16_t spr_rate;                                       /* the interim builds' G+0x08 */
#define SPR_RATE()      (spr_rate)
#endif

/* RAMDP byte offsets of the sprite engine's words */
#define SPR_RD_SAT      0x0B00u     /* the SAT copy: 80 entries x 8 B, then the multiplex tail */
#define SPR_RD_LINK79   0x0D7Au     /* entry 79's link word */
#define SPR_RD_OBJ      0x0F80u     /* 64 object records x 16 B */
#define SPR_RD_DMA      0x1400u     /* DMA descriptors, 8 words each */
#define SPR_DMA_N       190u        /* descriptors that fit below the register page $1FE0: one at n >= 190 is
                                       not stored (a list the game never clears; docs/ALLOWLIST.md, row B58) */
#if FW_S5
#define SPR_DMA_FITS(n) ((n) < SPR_DMA_N)
#else
#define SPR_DMA_FITS(n) 1           /* the FW_S5 = 0 images, which no current hardware test build carries:
                                       stored as before */
#endif
#define SPR_RD_USED     0x1F10u     /* words used this frame (+$110 per load) */
#define SPR_RD_BUDGET   0x1F12u     /* the frame budget (the game's) */
#define SPR_RD_WHOLE    0x1F14u     /* the whole-frame budget (the game's) */
#define SPR_RD_NDMA     0x1F16u     /* descriptors listed */
#define SPR_RD_NSAT     0x1F18u     /* SAT entries */
#define SPR_RD_READY    0x1F1Au     /* the sprite-ready flag */
#define SPR_RD_MUX      0x1F1Cu     /* the multiplex flag */
#define SPR_RD_STASH    0x1F20u     /* entries 14-27 kept for the game's HBlank copy */

/* VDP register words of the DMA descriptors */
#define SPR_VDP_INC2    0x8F02u
#define SPR_VDP_LEN_LO  0x9300u
#define SPR_VDP_LEN_HI  0x9400u
#define SPR_VDP_SRC_LO  0x9500u
#define SPR_VDP_SRC_MI  0x9600u
#define SPR_VDP_SRC_HI  0x9700u

#endif
