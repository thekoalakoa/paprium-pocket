/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/board_tests.c - host unit test of the x86 fake board (board/host/s1_board.c) against the board interface
 * v1.0 rules it models (docs/BOARD_IFACE.md; docs/MCU_INTERFACE.md sections 3.4 and 4; docs/CART_FPGA_SPEC.md
 * sections 4, 5 and 7). Built and run by
 * tools/fwbuild.py s1; exit 1 on the first failed check.
 *
 * The level entry points the board calls are this test's own recorders here (the scheduler has its own test). */
#include <stdio.h>
#include <stdlib.h>
#include "board.h"

static int fails, checks;
/* no __FILE__: the executable must not carry the tree's path */
#define CHECK(c) do { checks++; if (!(c)) { fails++; printf("FAIL board_tests.c:%d %s\n", __LINE__, #c); } } while (0)

/* ---- level recorders --------------------------------------------------------------------------------------------- */
static char trace[256];
static unsigned ntrace;
static int l1_ack = 1;              /* L1 acks every cause it sees */
static int l2a_post;                /* L2a: post a 68000 write while it runs (to see MEI preempt it) */
static int l2b_arm_timer;           /* L2b: arm a past deadline (to see MTI preempt it) */

static void tr(char c) { if (ntrace < sizeof trace - 1) trace[ntrace++] = c; trace[ntrace] = 0; }

void l1_mei(void)
{
    uint32_t c = brd_cause();
    tr('1');
    CHECK(hb.mstatus_mie == 0u);                /* L1 runs closed */
    if (l1_ack)
        brd_cause_ack(c);
}
void l2a_mti(void)
{
    tr('a');
    CHECK(hb.mstatus_mie == 1u && hb.mie == (BRD_LINE_MEI & hb.mie)); /* only MEI open */
    brd_timer_disarm();
    if (l2a_post) {
        l2a_post = 0;
        hb_68k_write(BRD_FREG_FEA, 0x1234u);
        (void)brd_now();                        /* a board call: the post is taken here, inside L2a */
    }
    tr('A');
}
void l2b_msi(void)
{
    tr('b');
    brd_msi(0u);
    if (l2b_arm_timer) {
        l2b_arm_timer = 0;
        brd_timer_arm(brd_now() - 100u);        /* in the past: fires at once */
        (void)brd_now();
    }
    tr('B');
}
void l3_thread(void) { abort(); }
uint32_t sched_exception(uint32_t mcause, uint32_t mepc, uint32_t mtval) { (void)mcause; (void)mtval; return mepc + 4u; }

static void clear_trace(void) { ntrace = 0; trace[0] = 0; }
static int trace_is(const char *s) { unsigned i; for (i = 0; s[i]; i++) if (trace[i] != s[i]) return 0; return trace[i] == 0; }

int main(void)
{
    /* 1. reset values (MCU_INTERFACE.md 8): hold, everything 0, stream invalid -> busy */
    hb_reset();
    hb.options = 0x0140u | BRD_OPT_JAP | (7u << BRD_OPT_MW_SHIFT);
    CHECK(hb.hold == 1u);
    CHECK(brd_cause() == 0u && brd_stream_state() == 0u);
    CHECK(brd_freg_rd(BRD_FREG_FE4) == 0u && brd_freg_rd(BRD_FREG_FEA) == 0u);
    CHECK(hb_68k_read(BRD_FREG_FE4) == (0x4u | 0x0140u));    /* busy at rest | model bits */
    CHECK((brd_options() & BRD_OPT_MODEL_MASK) == 0x0140u);
    CHECK((brd_options() & BRD_OPT_MW_MASK) >> BRD_OPT_MW_SHIFT == 7u);
    CHECK(brd_options() & BRD_OPT_JAP);
    CHECK(!brd_menu_open());
    hb.options |= BRD_OPT_MENU;
    CHECK(brd_menu_open());
    CHECK(brd_vs_count() == 0u);                               /* v1.1 VSCNT: 0 after a reset */
    hb.vs = 0x1FFFEu;
    CHECK(brd_vs_count() == 0xFFFEu);                          /* 16 bits, wrapping */
    hb.vs = 0u;

    /* 2. register file: only $1FE4/6/A/C stored; the others read 0 */
    brd_freg_wr(BRD_FREG_FE4, 0x46F8u);
    brd_freg_wr(BRD_FREG_FE6, 0x4000u);
    brd_freg_wr(BRD_FREG_FF0, 0x8000u);
    brd_freg_wr(BRD_FREG_FF4, 0x0201u);
    CHECK(brd_freg_rd(BRD_FREG_FE4) == 0x46F8u && brd_freg_rd(BRD_FREG_FE6) == 0x4000u);
    CHECK(brd_freg_rd(BRD_FREG_FF0) == 0u && brd_freg_rd(BRD_FREG_FF4) == 0u && brd_freg_rd(BRD_FREG_FE8) == 0u);
    CHECK(hb_68k_read(BRD_FREG_FE4) == (0x4u | 0x0140u));    /* the 68000 never sees the MCU word */
    CHECK(hb_68k_read(BRD_FREG_FE6) == 0x4000u);
    CHECK(hb.nlog == 4u && hb.log[0] == ((uint32_t)BRD_FREG_FE4 << 16 | 0x46F8u));

    /* 3. mailbox B, the busy guard, the stream (CART_FPGA_SPEC.md 7) */
    hb_68k_write(BRD_FREG_FEA, 0xDA02u);
    CHECK(brd_cause() == BRD_CAUSE_B && hb.guard == 1u && brd_stamp_b() != 0u);
    brd_stream_ptr(0x1000u);
    brd_stream_go(0x80u);                       /* GO: valid, guard cleared */
    CHECK(hb.guard == 0u && (brd_stream_state() == (0x80000000u | 0x80u)));
    CHECK(hb_68k_read(BRD_FREG_FE4) == (0x0u | 0x0140u));    /* ready */
    brd_freg_wr(BRD_FREG_FE8, 1u);
    CHECK(hb.window_en == 1u);
    hb_stream_consume(0x80u);
    CHECK(brd_stream_state() == 0u && hb.sptr == 0x1100u);   /* remaining 0 drops the stream */
    hb_68k_write(BRD_FREG_FEA, 0xDB06u);
    CHECK(hb.guard == 1u);
    brd_freg_wr(BRD_FREG_FEA, 0u);              /* the reply clears the guard */
    CHECK(hb.guard == 0u && brd_freg_rd(BRD_FREG_FEA) == 0u);
    hb_68k_write(BRD_FREG_FEA, 0xF200u);
    brd_freg_wr(BRD_FREG_FF2, 0x8000u);
    CHECK(hb.guard == 0u && hb.stream_valid == 0u);
    hb_68k_write(BRD_FREG_FEA, 0x8C01u);        /* not a stream command: no guard */
    CHECK(hb.guard == 0u);
    brd_freg_wr(BRD_FREG_FF2, 0x4000u);         /* a chunk word: no effect */
    brd_stream_go(4u);
    brd_freg_wr(BRD_FREG_FF2, 0x4002u);
    CHECK(hb.stream_valid == 1u);
    brd_freg_wr(BRD_FREG_FE8, 0u);              /* window off, mini view, stream dropped */
    CHECK(hb.window_en == 0u && hb.mini_view == 1u && hb.stream_valid == 0u);
    brd_freg_wr(BRD_FREG_FE8, 1u);
    brd_freg_wr(BRD_FREG_FEE, 0x1234u);         /* any other value: no effect */
    CHECK(hb.window_en == 1u);
    brd_freg_wr(BRD_FREG_FEE, 0xAF5Bu);
    CHECK(hb.window_en == 0u);
    hb_68k_write(BRD_FREG_FEC, 0x9494u);
    CHECK(brd_cause() == (BRD_CAUSE_A | BRD_CAUSE_B) && brd_freg_rd(BRD_FREG_FEC) == 0x9494u);
    brd_cause_ack(BRD_CAUSE_B);
    CHECK(brd_cause() == BRD_CAUSE_A);
    brd_cause_ack(BRD_CAUSE_ALL);
    CHECK(brd_cause() == 0u);

    /* 4. timer: signed compare across the wrap */
    hb.now = 0xFFFFFF00u;
    brd_timer_arm(0x00000010u);                 /* 0x110 ahead, across the wrap */
    CHECK(!(hb_pending() & BRD_LINE_MTI) && brd_until(0x10u) > 0);
    hb.now = 0x00000020u;
    CHECK(hb_pending() & BRD_LINE_MTI);
    brd_timer_disarm();
    CHECK(!(hb_pending() & BRD_LINE_MTI));

    /* 5. byte views: 68000 byte order */
    brd_cart_ram()[0x10] = 0xA1B2u;             /* 68000 word $20 */
    CHECK(brd_cart_ram_byte(0x20u) == 0xA1u && brd_cart_ram_byte(0x21u) == 0xB2u);

    /* 6. the interrupt model: masking, priority, nesting like the Pocket trap entry */
    hb_reset();
    clear_trace();
    hb_68k_write(BRD_FREG_FEA, 0x8100u);
    (void)brd_now();
    CHECK(trace_is(""));                        /* MIE = 0 after reset: nothing taken */
    brd_lines_on(BRD_LINES_ALL);
    CHECK(trace_is(""));
    brd_irq_enable();
    CHECK(trace_is("1") && brd_cause() == 0u);  /* L1 at once */
    clear_trace();
    brd_msi(1u);                                /* L2b; inside it, L2a preempts on a past deadline */
    l2b_arm_timer = 1;
    (void)brd_now();
    CHECK(trace_is("baAB"));
    CHECK(hb.depth_max == 2u && hb.depth == 0u);
    clear_trace();
    l2a_post = 1;                               /* L2a; inside it, L1 preempts */
    brd_timer_arm(brd_now());
    (void)brd_now();
    CHECK(trace_is("a1A"));
    clear_trace();
    {                                           /* all three pending at once: MEI, then MTI, then MSI */
        uint32_t s = brd_irq_save();
        hb_68k_write(BRD_FREG_FEC, 0x9494u);
        brd_timer_arm(brd_now());
        brd_msi(1u);
        CHECK(trace_is(""));                    /* nothing inside the critical section */
        brd_irq_restore(s);
    }
    CHECK(trace_is("1aAbB"));
    clear_trace();
    brd_lines_off(BRD_LINE_MEI);                /* a masked line waits */
    hb_68k_write(BRD_FREG_FEA, 0x8100u);
    (void)brd_now();
    CHECK(trace_is(""));
    brd_lines_on(BRD_LINE_MEI);
    CHECK(trace_is("1"));
    CHECK(hb.taken[0] == 4u && hb.taken[1] == 3u && hb.taken[2] == 2u);

    /* 7. board control */
    brd_md_hold(0u);
    CHECK(hb.hold == 0u);
    brd_menu_mute(1u);
    brd_opt_at_reset(0u);
    CHECK(hb.menu_mute == 1u && hb.opt_at_reset == 0u);
    CHECK(board_get_handoff()->page_a == 0u && board_get_handoff()->page_b == 0u);
    brd_milestone(0x5Au);
    CHECK(hb.milestone == 0x5Au);

    printf("board_tests: %d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
