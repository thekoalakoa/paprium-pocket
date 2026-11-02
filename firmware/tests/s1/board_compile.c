/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/board_compile.c - compile check of board/board.h with the Pocket board (board/pocket/board_impl.h) for
 * RV32IM with the stage-1 flags (FW_S1, our new firmware): every interface function used once, so each inline
 * definition is type-checked and emitted. Compiled (not linked) by
 * tools/fwbuild.py s1; its object's size is printed as information only. */
#include "board.h"

uint32_t board_compile_probe(uint32_t x);
uint32_t board_compile_probe(uint32_t x)
{
    uint32_t s = brd_irq_save(), acc = 0;
    acc += brd_now() + brd_cycles() + brd_cause() + brd_stamp_b() + brd_stream_state() + brd_options();
    acc += brd_menu_open() + (uint32_t)brd_until(x) + brd_vs_count();
    brd_timer_arm(x);
    brd_timer_disarm();
    brd_cause_ack(BRD_CAUSE_ALL);
    brd_msi(1u);
    brd_lines_off(BRD_LINE_MTI);
    brd_lines_on(BRD_LINES_ALL);
    brd_lines_flush(BRD_LINE_MEI);
    acc += brd_freg_rd(BRD_FREG_FEA);
    brd_freg_wr(BRD_FREG_FE6, (uint16_t)x);
    brd_stream_ptr(x);
    brd_stream_go(x >> 1);
    acc += brd_cart_ram()[1] + brd_cart_ram_byte(x) + brd_rom()[2] + brd_rom_byte(x) + brd_workspace()[3] + brd_save()[4];
    acc += BRD_CYC_US(100) + BRD_CYC_NS(1000);
    brd_irq_restore(s);
    brd_irq_enable();
    return acc;
}
