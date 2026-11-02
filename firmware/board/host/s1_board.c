/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/host/s1_board.c - the x86 fake board of the board interface v1.2 (board/board.h, docs/BOARD_IFACE.md).
 *
 * A model of what MCU interface v1.0 (docs/MCU_INTERFACE.md) and the cart RTL (docs/CART_FPGA_SPEC.md 3.4, 4, 5, 7)
 * show the firmware, for host builds of core/ and their tests:
 *   - timer: TIMER advances hb.step cycles at every board call (hb_point) and by hb_advance(); the MTI level is up
 *     while TEN and (TIMER - TCMP) >= 0 (signed);
 *   - VSCNT (v1.1): the VDP's VS starts, one per hb.vs_frame cycles of TIMER (an NTSC frame from the reset; a test may
 *     move hb.vs_next or stop the VDP with vs_frame 0);
 *   - CAUSE {V,S,A,B} level latches, W1C acks; a 68000 write of $1FEA sets B (and STAMP_B), of $1FEC sets A;
 *   - the register file stores $1FE4/6/A/C only; $1FE8 / $1FEE / $1FF2 act on write; the busy guard is set by a
 *     68000 $1FEA write whose high byte is a stream command and cleared by an MCU $1FEA write, a clearing $1FF2 write
 *     or GO; busy = guard | !stream_valid; the 68000 reads $1FE4 as busy << 2 | the model bits;
 *   - interrupts: at every board call, a pending level whose mie bit is set is taken when mstatus.MIE is 1, highest
 *     first, with the Pocket trap entry's masking (L1 closed; L2a opens MEI; L2b opens MEI and MTI) and the trap's
 *     restore of mie and MIE afterwards. No CPU interrupt latch is modelled (the RV32 test rig models NEORV32's).
 *   - v1.2 (docs/MCU_INTERFACE.md 4.9): the RTL sprite decoder on the chip's own writes: $1FF4 latches HI,
 *     $1FF6 odd clears and even pushes, $1FF2 = 0x8000 with entries queued loads SPTR with DEC_BASE and decodes the
 *     entries last-pushed first, contiguous from DEC_BASE, with the chip's 0x80 algorithm, then GOes: all of it at the
 *     START (this model has no time; tests/equiv/rtlmodel.py times the decode against the 68000's reads).
 * Not modelled: bus timing, the stream engine's reads (remaining only falls through hb_stream_consume), RAMDP
 * contention. The rules come from the text of docs/MCU_INTERFACE.md and docs/CART_FPGA_SPEC.md (checked against
 * that text), not from RTL runs. */
#include <stdlib.h>
#include <string.h>
#include "board.h"

hb_state hb;

/* the modelled VDP (VSCNT, v1.1): an NTSC frame, 262 lines of 3,420 master clocks; the MCU clock is the master clock */
#define HB_VDP_LINES            262u
#define HB_LINE_MCLK            3420u

static board_handoff hb_handoff;    /* the first new-core firmware: all zero (docs/BOOT_SPEC.md 3) */

void hb_reset(void)
{
    uint8_t *ws = hb.workspace;
    uint16_t *rom = hb.rom;
    uint16_t *cram = hb.cram;
    const uint8_t *f8 = hb.flash8, *f16 = hb.flash16;
    memset(&hb, 0, sizeof hb);
    hb.flash8 = f8;                 /* (a test's flash views stay, as the ROM does) */
    hb.flash16 = f16;
    hb.cram = cram ? cram : (uint16_t *)calloc(1, 0x400000u);   /* CRAM die 0's MCU window */
    /* 16 MB, like the 0.2.6 host's SDRAM window: a wild offset in the moved 0.2.6 code (garbage objects in a test)
       reads zeros instead of faulting; the Pocket's workspace aliases every 2 MB (MCU_INTERFACE.md 3) */
    hb.workspace = ws ? ws : (uint8_t *)calloc(1, HB_WORKSPACE_ALLOC);
    hb.rom = rom;
    hb.step = 8u;
    hb.hold = 1u;                   /* CTRL = 0x09 on every reset: HOLD, RSTSEEN */
    hb.vs_frame = HB_VDP_LINES * HB_LINE_MCLK;
    hb.vs_next = hb.vs_frame;
}

uint32_t hb_pending(void)
{
    uint32_t p = 0;
    if ((hb.cause & 0xFu) || (hb.blkie && (hb.cause & 0x10u)))     /* v1.3: BLK with CTRL.BLKIE */
        p |= BRD_LINE_MEI;
    if (hb.ten && (int32_t)(hb.now - hb.tcmp) >= 0)
        p |= BRD_LINE_MTI;
    if (hb.msip)
        p |= BRD_LINE_MSI;
    return p;
}

/* the Pocket trap entry (board/pocket/s1_trap.S), as a function: one level, nested by recursion */
static void hb_trap(uint32_t line)
{
    uint32_t mie0 = hb.mie, lvl0 = hb.level;
    hb.mstatus_mie = 0u;            /* the CPU clears MIE on entry */
    hb.level = line;
    hb.depth++;
    if (hb.depth > hb.depth_max)
        hb.depth_max = hb.depth;
    if (line == BRD_LINE_MEI) {
        hb.taken[0]++;
        l1_mei();
    } else if (line == BRD_LINE_MTI) {
        hb.taken[1]++;
        hb.mie = mie0 & BRD_LINE_MEI;
        hb.mstatus_mie = 1u;
        l2a_mti();
        hb.mstatus_mie = 0u;
    } else {
        hb.taken[2]++;
        hb.mie = mie0 & (BRD_LINE_MEI | BRD_LINE_MTI);
        hb.mstatus_mie = 1u;
        l2b_msi();
        hb.mstatus_mie = 0u;
    }
    hb.depth--;
    hb.level = lvl0;
    hb.mie = mie0;                  /* the trap restores mie (the flush) and mret restores MIE = 1 */
    hb.mstatus_mie = 1u;
}

/* nesting is bounded by the masking itself: L1 runs with MIE = 0, L2a with MEI only, L2b with MEI and MTI */
static void hb_take(void)
{
    if (hb.no_irq)
        return;
    while (hb.mstatus_mie) {
        uint32_t p = hb_pending() & hb.mie;
        if (!p)
            break;
        hb_trap((p & BRD_LINE_MEI) ? BRD_LINE_MEI : (p & BRD_LINE_MTI) ? BRD_LINE_MTI : BRD_LINE_MSI);
    }
}

void hb_stream_consume(uint32_t words)
{
    while (words-- && hb.stream_valid && hb.window_en && !hb.mini_view) {
        hb.sptr = (hb.sptr + 2u) & BRD_STREAM_MAX_WORDS;
        if (--hb.remaining == 0u)
            hb.stream_valid = 0u;
    }
}

void hb_point(void)
{
    hb.now += hb.step;
    hb.cycles += hb.step;
    while (hb.vs_frame && (int32_t)(hb.now - hb.vs_next) >= 0) {   /* the modelled VDP's VS starts (VSCNT) */
        hb.vs++;
        hb.vs_next += hb.vs_frame;
    }
    if (hb.on_point)
        hb.on_point();
    hb_take();
}

void hb_irq_restore(uint32_t saved)
{
    hb.mstatus_mie = saved ? 1u : 0u;
    hb_point();
}

void hb_go(uint32_t words)
{
    if (words) {
        hb.remaining = words;
        hb.stream_valid = 1u;
        hb.guard = 0u;
    } else {
        hb.stream_valid = 0u;
    }
}

static void hb_log(unsigned off, uint16_t v)
{
    if (hb.nlog < sizeof hb.log / sizeof hb.log[0])
        hb.log[hb.nlog++] = ((uint32_t)off << 16) | v;
}

void hb_log_board(uint32_t tag, uint32_t v)
{
    if (hb.nlog < sizeof hb.log / sizeof hb.log[0])
        hb.log[hb.nlog++] = (tag << 24) | (v & 0xFFFFFFu);
}

/* ---- the RTL sprite decoder (v1.2, MCU_INTERFACE.md 4.9), timeless ---------------------------------------------- */
#define HB_WS_MASK              (BRD_WORKSPACE_BYTES - 1u)
#define HB_DEC_OUT_MAX          0x100000u       /* a stream with no end code stops here (never in the data) */
static uint8_t hb_romb(uint32_t a)              /* ROM byte a (hb.rom holds 68000 words: byte a at a ^ 1) */
{
    return hb.rom ? ((const uint8_t *)hb.rom)[(a & (BRD_ROM_BYTES - 1u)) ^ 1u] : 0u;
}
static uint8_t *hb_wsb(uint32_t o) { return &hb.workspace[((hb.dec_base + o) & HB_WS_MASK) ^ 1u]; }   /* the same view */

/* one entry from its type byte at ROM a (even), output from byte o of the START; returns the new o. As the chip's
   0x80 unpacker does it (the chip's routine at RAM 0x20003EE8): a copy reads the bytes already written, byte by byte
   forward; distance 0 writes nothing (the RTL's choice, flag D0) and a reference before the START's base reads the
   workspace there (the chip's semantics; the RTL reads a stale ring byte: flag PRE). Neither is in the data (our
   decoder design notes) */
static uint32_t hb_dec_entry(uint32_t a, uint32_t o)
{
    if (hb_romb(a) != 0x80u) {                  /* not a 0x80 stream: skipped */
        hb.dec_flags |= HB_DEC_BADTYPE;
        return o;
    }
    a++;
    while (o < HB_DEC_OUT_MAX) {
        uint8_t t = hb_romb(a++), b;
        uint32_t n = t & 0x3Fu, d;
        switch (t >> 6) {
        case 0:
            if (!n)
                return o;                       /* the end code */
            while (n--)
                *hb_wsb(o++) = hb_romb(a++);
            break;
        case 1:
            b = hb_romb(a++);
            while (n--)
                *hb_wsb(o++) = b;
            break;
        case 2:
            d = hb_romb(a++);
            if (!d) {
                hb.dec_flags |= HB_DEC_D0;
                o += n;
                break;
            }
            if (n && o < d)
                hb.dec_flags |= HB_DEC_PRE;
            while (n--) {
                *hb_wsb(o) = *hb_wsb(o - d);
                o++;
            }
            break;
        default:
            while (n--)
                *hb_wsb(o++) = 0u;
            break;
        }
    }
    return o;
}

/* the decoder's part of a register write (after the earlier stream rules of the same write) */
static void hb_decoder(unsigned off, uint16_t v)
{
    if (off == BRD_FREG_FF4) {
        hb.dec_hi = v;
    } else if (off == BRD_FREG_FF6) {
        if (v & 1u)
            hb.dec_n = 0u;                      /* CLEAR */
        else if (hb.dec_n < 16u)
            hb.dec_q[hb.dec_n++] = ((hb.dec_hi & 0x7Fu) << 16) | (v & 0xFFFEu);   /* PUSH */
        else
            hb.dec_flags |= HB_DEC_OVF;
    } else if (off == BRD_FREG_FF2 && v == 0x8000u && hb.dec_n) {   /* START with entries; an empty one does nothing */
        uint32_t o = 0u, k = hb.dec_n;
        hb.dec_n = 0u;
        hb.sptr = hb.dec_base;
        while (k--)                             /* last pushed, first served */
            o = hb_dec_entry(hb.dec_q[k], o);
        hb.dec_starts++;
        hb.dec_words = o >> 1;
        hb_go(o >> 1);
        hb_log_board(HB_LOG_RTLGO, o >> 1);
    }
}

/* the twin of the Pocket's register accessor (board/pocket/s1_freg.c): the shadow */
static void hb_accessor(unsigned off, uint16_t v)
{
    hb.shadow[off >> 1] = v;
}

void hb_freg_write(unsigned off, uint16_t v)
{
    off &= 0x1Eu;
    hb_log(off, v);
    hb_accessor(off, v);
    switch (off) {
    case BRD_FREG_FE4: case BRD_FREG_FE6: case BRD_FREG_FEC:
        hb.freg[off >> 1] = v;
        break;
    case BRD_FREG_FEA:
        hb.freg[off >> 1] = v;
        hb.guard = 0u;                          /* an MCU write of $1FEA clears the busy guard; raises nothing */
        break;
    case BRD_FREG_FE8:
        if (v & 1u) {
            hb.window_en = 1u;
        } else {
            hb.window_en = 0u;
            hb.mini_view = 1u;
            hb.stream_valid = 0u;               /* window_en falling drops the stream */
        }
        break;
    case BRD_FREG_FEE:
        if (v == 0xAF5Bu) {                     /* the "MCU stops serving" value: window off, mini view */
            hb.window_en = 0u;
            hb.mini_view = 1u;
            hb.stream_valid = 0u;
        }
        break;
    case BRD_FREG_FF2:
        if (v == 0u || (v & 0x8000u)) {         /* stop / start: the stream is invalid until GO; guard cleared */
            hb.stream_valid = 0u;
            hb.guard = 0u;
        }
        break;
    default:                                    /* $1FF0, $1FF4, $1FF6 and the unused offsets: not stored */
        break;
    }
    hb_decoder(off, v);                         /* v1.2: the RTL decoder's queue and START */
}

void hb_68k_write(unsigned off, uint16_t v)
{
    off &= 0x1Eu;
    if (off == BRD_FREG_FEA) {
        uint8_t hi = (uint8_t)(v >> 8);
        hb.freg[off >> 1] = v;
        hb.cause |= BRD_CAUSE_B;
        hb.stamp_b = hb.now;
        hb.arr = (hb.arr + 1u) & 0xFFFFu;       /* v1.3: arrival n (MCU_INTERFACE.md 3.10.5) */
        hb.seqlat = (hb.seqlat & 0xFFFF0000u) | hb.arr;
        if (hi == 0xDAu || hi == 0xDBu || hi == 0xF2u)
            hb.guard = 1u;                      /* a stream command: busy until the MCU answers */
    } else if (off == BRD_FREG_FEC) {
        hb.freg[off >> 1] = v;
        hb.cause |= BRD_CAUSE_A;
        hb.stamp_a = hb.now;                    /* v1.3 STAMP_A */
        hb.arr = (hb.arr + 1u) & 0xFFFFu;
        hb.seqlat = (hb.seqlat & 0xFFFFu) | (hb.arr << 16);
    }                                           /* the 68000 writes nowhere else in the page */
}

uint16_t hb_68k_read(unsigned off)
{
    off &= 0x1Eu;
    if (off == BRD_FREG_FE4) {
        uint32_t busy = hb.guard | !hb.stream_valid;
        return (uint16_t)((busy << 2) | (hb.options & BRD_OPT_MODEL_MASK));
    }
    if (off == BRD_FREG_FE6 || off == BRD_FREG_FEA || off == BRD_FREG_FEC)
        return hb.freg[off >> 1];
    return 0u;
}

/* ---- board control ------------------------------------------------------------------------------------------- */
void brd_md_hold(uint32_t hold) { hb_point(); hb.hold = hold ? 1u : 0u; }
void brd_menu_mute(uint32_t on) { hb_point(); hb.menu_mute = on ? 1u : 0u; }
void brd_opt_at_reset(uint32_t on) { hb_point(); hb.opt_at_reset = on ? 1u : 0u; }
void brd_milestone(uint32_t code) { hb.milestone = code; }
#if FW_S5
void brd_synth_blkie(uint32_t on) { hb_point(); hb.blkie = on ? 1u : 0u; }

/* what a CONFIG write does to the scheduler words the firmware reads back (MCU_INTERFACE.md v1.3 3.10.2, as the
   chip's 88 configuration does it): DT and YM give FILL 1, CUR 0, CNT 0xFF and their HALF / NBLK; MODE 0 / 3 HALF 0 */
void hb_config_apply(uint32_t v)
{
    uint32_t mode = v & 3u, pal = (v >> 2) & 1u, half, nblk;
    if (mode == 1u || mode == 2u) {
        half = (mode == 2u && !pal) ? 800u : 960u;
        nblk = (mode == 2u && !pal) ? 5u : 6u;
        hb.sy_status = (hb.sy_status & ~(BRD_SYNTH_FILL | BRD_SYNTH_CUR)) | BRD_SYNTH_FILL;
        hb.sy_sched = 0xFFu | nblk << 8 | half << 16;
    } else
        hb.sy_sched &= 0xFFFFu;
}

/* ---- region 0x06 (MCU_INTERFACE.md v1.3 3.10): the order registers as the arrival and tick fields above, the rest
   plain words (a store writes its byte lanes; a test plays the synth's own writes into sy_win) ------------------ */
uint32_t hb_synth_rd(uint32_t off)
{
    off &= 0xFFCu;
    hb.sy_rd_n++;
    switch (off) {
    case 0x000u: return 0x53350001u;
    case 0x004u: return hb.sy_config;           /* CONFIG (brd_synth_config) */
    case 0x024u: return 0u;
    case 0x028u: return (hb.arr & 0xFFFFu) | (hb.done << 16);
    case 0x02Cu: return hb.done;
    case 0x030u: return hb.sy_status;
    case 0x040u: return hb.sy_diag;
    case 0x048u: return hb.seqlat;
    case 0x04Cu: return hb.sy_sched;
    }
    return (uint32_t)hb.sy_win[off] | (uint32_t)hb.sy_win[off + 1u] << 8 | (uint32_t)hb.sy_win[off + 2u] << 16 |
           (uint32_t)hb.sy_win[off + 3u] << 24;
}

void hb_synth_wr(uint32_t off, uint32_t v, uint32_t bytes)
{
    uint32_t i;
    off &= 0xFFFu;
    switch (off & ~3u) {
    case 0x000u: case 0x004u: case 0x024u: case 0x028u: case 0x02Cu: case 0x030u: case 0x040u: case 0x048u:
    case 0x04Cu:
        abort();                                /* the mirror never stores into an order register */
    }
    for (i = 0; i < bytes; i++)
        hb.sy_win[(off + i) & 0xFFFu] = (uint8_t)(v >> (8u * i));
    hb.sy_wr_n++;
    hb.sy_wr_last = off;
}
#endif

void hb_full_reset_hook(void) __attribute__((weak, noreturn));
void brd_full_reset(void)
{
    hb.hold = 1u;
    hb.mstatus_mie = 0u;
    hb.resets++;
    if (hb_full_reset_hook)
        hb_full_reset_hook();
    abort();
}

const board_handoff *board_get_handoff(void) { return &hb_handoff; }

/* ---- interim board hooks (interim/s1/s1_interim.h) ----------------------------------------------------------- */
static uint8_t hb_sfx_regs[8 * 16];             /* the audio_sfx FIFO block: 8 channels (interim; never read back) */
void s1_board_vol(uint32_t which, uint8_t v) { if (which) hb.vol_bgm = v; else hb.vol_sfx = v; }
void *s1_board_sfx(void) { return hb_sfx_regs; }
