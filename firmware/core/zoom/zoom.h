/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/zoom/zoom.h - the cart chip's zoom buffers and routines (zoom.c; the cart chip is the STM32 microcontroller on
   the real cartridge). */
#ifndef ZOOM_H
#define ZOOM_H
#include <stdint.h>

#define ZOOM_STAMPS     0x800u          /* the stamps, 2 x 1 KB (the cart chip's 0x200111EC A, 0x200115EC B) */
#define ZOOM_SRC        0x800u          /* the F4 source (0x200119EC) */
#define ZOOM_SAVE       0x800u          /* the save of RAMDP $0200-$09FF (0x200121EC) */

/* the F4 source and the save, in the cart chip's order (one block: a read past the source's end lands in the save, as
   on the cart chip); the stamps sit apart (zoom_st) and zoom.c maps a write past their end onto this block */
typedef union {
    uint8_t  raw[ZOOM_SRC + ZOOM_SAVE];
    struct {
        uint8_t  src[ZOOM_SRC];
        uint16_t save[ZOOM_SAVE / 2u];  /* RAMDP words $0200-$09FF, as the cart chip's halfword stores leave them */
    } b;
    uint32_t align_;
} zoom_ss_t;
extern zoom_ss_t zoom_ss;
extern uint8_t zoom_st[ZOOM_STAMPS];

void zoom_rescale(const uint16_t args[4]);  /* 0x08022D84: F5 (start, end, step, row) into the stamps */
void zoom_copyout(void);                    /* 0x08022D48: the stamps -> RAMDP $0200, byte-swapped; the stamps := 0 */
void zoom_f4_order(uint32_t len);           /* the FW_S5 = 0 images: 0.2.6's F4 decode put in the decoder's byte order */
uint32_t zoom_f4_decode(uint32_t src);      /* the FW_S5 images: F4's job decode, stopped at the zoom block's end */

#endif
