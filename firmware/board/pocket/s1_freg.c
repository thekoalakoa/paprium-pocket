/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/s1_freg.c - the register accessor of the new-core firmware (docs/MCU_INTERFACE.md 3.4 and its finding
 * 11; docs/CART_FPGA_SPEC.md 4, 9, 15.1): every cart-register write (board_impl.h brd_freg_wr) is stored in RTL by
 * s1_freg_wr, which then keeps:
 *   - the shadow of every offset: the RTL stores only $1FE4/6/A/C; $1FE8, $1FEE, $1FF0-$1FF6 act on write and read 0,
 *     so the last value written is kept here (TEST read-back for the debug save and the test rigs; the core never
 *     reads it);
 *   - TEST: the chip-runner comparison's log, one word per write in program order: bits 31-24 the offset (0x04-0x16)
 *     or a board-only tag (S1_LOG_SPTR, S1_LOG_GO, S1_LOG_DECB), bits 23-0 the value. 512 entries in wram_upper,
 *     wrapping; the TEST telemetry stores it in the debug save, the test rigs read it from the image's memory.
 * MCU interface v1.2 (proposed): the decoder queue is the RTL's (MCU_INTERFACE.md 4.9: $1FF4 latches, $1FF6 pushes /
 * clears, $1FF2 = 0x8000 starts, as the cart FPGA takes the chip's writes); earlier versions of the new-core firmware
 * kept a firmware copy of it here for a decoder stand-in that had no user of the queue. */
#include <stdint.h>
#include "board.h"
#include "s1_freg.h"

uint16_t s1_freg_shadow[16];

#if S1_ORACLE
s1_oracle_log_t s1_oracle_log __attribute__((section(".bss_upper")));
#endif

void s1_board_log(uint32_t tag, uint32_t v)
{
#if !S1_ORACLE
    (void)tag;
    (void)v;
#else
    uint32_t s = brd_irq_save();
    s1_oracle_log.e[s1_oracle_log.n & (S1_ORACLE_N - 1u)] = (tag << 24) | (v & 0xFFFFFFu);
    s1_oracle_log.n++;
    brd_irq_restore(s);
#endif
}

void s1_freg_wr(unsigned off, uint16_t v)
{
    uint32_t s = brd_irq_save();
    off &= 0x1Eu;
    BRD_IO16(POCKET_FREG_BASE + off) = v;                   /* the RTL first: program order, nothing posted */
    s1_freg_shadow[off >> 1] = v;
#if S1_ORACLE
    s1_oracle_log.e[s1_oracle_log.n & (S1_ORACLE_N - 1u)] = ((uint32_t)off << 24) | v;
    s1_oracle_log.n++;
#endif
    brd_irq_restore(s);
}
