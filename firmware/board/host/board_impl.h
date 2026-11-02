/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/host/board_impl.h - the x86 fake board's definitions of the board interface v1.2 (board/board.h).
 *
 * Included at the end of board.h; never included directly. Every inline function calls the board model in
 * board/host/s1_board.c ("hb"), which keeps the MCU interface v1.0 state (timer, CAUSE, MSIP, register file with the
 * RTL's window / busy / stream rules, option word, memories) and a simple CPU interrupt model: every board call is a
 * point where a pending level can be taken while interrupts are on, with the levels and nesting of the Pocket's trap
 * entry (MEI > MTI > MSI; L1 runs closed, L2a with MEI open, L2b with MEI and MTI open). The Pocket's instruction-
 * level behaviour (the NEORV32 interrupt latch, preemption between any two instructions) is the RV32 test rig's job
 * (tests/equiv/fuzz_sched.py), not this model's. */
#ifndef BOARD_IMPL_HOST_H
#define BOARD_IMPL_HOST_H

#include <stdint.h>

#define HB_RAM_WORDS            (BRD_CART_RAM_BYTES / 2u)
#define HB_WORKSPACE_ALLOC      0x1000000u      /* bytes allocated for the 2 MB workspace (see hb_reset) */

typedef struct {
    /* time */
    uint32_t now, tcmp, ten, step;      /* step: cycles added at every board call (default 8) */
    uint64_t cycles;
    /* interrupt sources and CPU state */
    uint32_t cause, stamp_b, msip;
    uint32_t mie, mstatus_mie;          /* RISC-V mie (BRD_LINE_* bits) and mstatus.MIE (0/1) */
    uint32_t level;                     /* 0 thread, else the BRD_LINE_* of the level running (innermost) */
    uint32_t depth, depth_max, taken[3];/* nesting depth now / max; levels taken: MEI, MTI, MSI */
    /* register file (docs/MCU_INTERFACE.md 3.4) and the RTL state behind it (docs/CART_FPGA_SPEC.md 5, 7) */
    uint16_t freg[16];                  /* stored words at off / 2 (only FE4, FE6, FEA, FEC are stored) */
    uint32_t window_en, mini_view, stream_valid, guard, sptr, remaining;
    /* board control, options */
    uint32_t hold, menu_mute, opt_at_reset, options, milestone, resets;
    /* memories */
    uint16_t ram[HB_RAM_WORDS];
    uint8_t  save[BRD_SAVE_BYTES];
    uint8_t *workspace;                 /* BRD_WORKSPACE_BYTES, allocated by hb_reset */
    uint16_t *rom;                      /* NULL unless a test provides one (BRD_ROM_BYTES) */
    /* register-file write log (off << 16 | value), for tests and the chip-runner comparison; the board-only writes are
       logged as tag << 24 | value (HB_LOG_SPTR, HB_LOG_GO: bit 30 set, never a register entry) */
    uint32_t log[4096], nlog;
    /* the twin of the Pocket's register accessor (board/pocket/s1_freg.c): every offset's last value */
    uint16_t shadow[16];
    /* v1.2: the RTL sprite decoder (MCU_INTERFACE.md 4.9), timeless: a START decodes and GOes at once
       (tests/equiv/rtlmodel.py models its timing): the queue (23-bit even ROM byte addresses, in push order), HI,
       DEC_BASE, STARTs that had entries, the words the last one produced, and the DEC_STAT flags (bits 16-21) */
    uint32_t dec_q[16], dec_n, dec_hi, dec_base, dec_starts, dec_words, dec_flags;
    uint32_t vol_sfx, vol_bgm;          /* the interim volume registers (s1_board_vol) */
    uint32_t vs;                        /* v1.1 VSCNT: the VDP's vertical syncs since the reset (a test may set it) */
    uint32_t vs_next, vs_frame;         /* the modelled VDP: the next VS start (TIMER value) and the frame length in
                                           cycles (hb_reset: 262 lines x 3,420 MCLK, the first VS start one frame after
                                           the reset); each board call that passes vs_next counts one VS start (the C6
                                           hold counts them); vs_frame 0 = a stopped VDP */
    /* v1.3 (FW_S5): ARR counts the 68000's $1FEA / $1FEC writes (16 bits); SEQLAT the last of each
       mailbox; STAMP_A; the synth's DONE (written by the firmware) and STATUS (BUSY, BLKCNT: set by a test) */
    uint32_t arr, seqlat, stamp_a, done, sy_status, done_writes;
    /* v1.3: ARM (the last value and every write: arm_log[0..arm_n), wrapping at 64), SCHED and DIAG as a test sets
       them (a DIAG write clears it), and CRAM die 0's MCU window (0x400000 bytes, allocated by hb_reset; a test puts
       the synth's dac_buf at DACBUF_L) */
    uint32_t sy_arm, arm_n, arm_log[64], sy_sched, sy_diag, diag_clears;
    uint16_t *cram;
    /* v1.3: the flash views C6 reads (NULL unless a test provides them; kept across hb_reset, as rom) and CONFIG
       (the last value and every write: cfg_log[0..cfg_n), wrapping at 64) */
    const uint8_t *flash8, *flash16;
    uint32_t sy_config, cfg_n, cfg_log[64];
    /* v1.3: region 0x06's plain words (the globals FLAGS .. ECHOS, YMFILT and the voice / SFX windows, little
       endian; the order registers above answer their own offsets), the MCU stores into them (count, and the
       last offset), CTRL.BLKIE (CAUSE.BLK, bit 4, raises MEI only with it), the MCU loads from region 0x06 */
    uint8_t  sy_win[0x1000];
    uint32_t sy_wr_n, sy_wr_last, blkie, sy_rd_n;
    /* test hooks */
    void (*on_point)(void);             /* called at every board call (after time advances, before interrupts) */
    int   no_irq;                       /* 1: the model never takes an interrupt */
    void (*on_done)(uint32_t n);        /* v1.3: called at every DONE write (a test's block model) */
} hb_state;

extern hb_state hb;

void     hb_reset(void);                                /* power-on: every register at its v1.0 reset value */
void     hb_point(void);                                /* advance time, then take pending levels if allowed */
uint32_t hb_pending(void);                              /* BRD_LINE_* levels up now */
void     hb_68k_write(unsigned off, uint16_t v);        /* a 68000 word write into $1FE0-$1FFF */
uint16_t hb_68k_read(unsigned off);                     /* what the 68000 reads there (the $1FE4 composer etc.) */
void     hb_freg_write(unsigned off, uint16_t v);       /* the MCU-side write with its RTL effects */
void     hb_go(uint32_t words);
void     hb_stream_consume(uint32_t words);             /* the 68000 reads words from the open window */
void     hb_irq_restore(uint32_t saved);
void     hb_log_board(uint32_t tag, uint32_t v);        /* a board-only write into the log */
#define HB_LOG_SPTR             0x40u
#define HB_LOG_GO               0x41u
#define HB_LOG_DECB             0x42u   /* v1.2: the firmware's DEC_BASE write (brd_dec_base) */
#define HB_LOG_RTLGO            0x43u   /* v1.2: the RTL decoder's own GO at the end of a START (not a firmware write:
                                           the Pocket's chip-runner log cannot see it; the host log shows it for the
                                           test rigs) */
#define HB_DEC_OVF              (1u << 16)  /* DEC_STAT flags (MCU_INTERFACE.md 4.9) */
#define HB_DEC_BADTYPE          (1u << 17)
#define HB_DEC_D0               (1u << 18)
#define HB_DEC_PRE              (1u << 19)

/* ---- time ---------------------------------------------------------------------------------------------------- */
static inline uint32_t brd_now(void) { hb_point(); return hb.now; }
static inline void brd_timer_arm(uint32_t deadline) { hb_point(); hb.tcmp = deadline; hb.ten = 1u; }
static inline void brd_timer_disarm(void) { hb_point(); hb.ten = 0u; }
static inline uint32_t brd_cycles(void) { hb_point(); return (uint32_t)hb.cycles; }

/* ---- interrupt sources --------------------------------------------------------------------------------------- */
#if FW_S5
static inline uint32_t brd_cause(void) { hb_point(); return hb.cause & 0x1Fu; }   /* v1.3: + BLK (bit 4) */
#else
static inline uint32_t brd_cause(void) { hb_point(); return hb.cause & 0xFu; }
#endif
static inline void brd_cause_ack(uint32_t bits) { hb_point(); hb.cause &= ~bits; }
static inline uint32_t brd_stamp_b(void) { hb_point(); return hb.stamp_b; }
static inline void brd_msi(uint32_t on) { hb_point(); hb.msip = on ? 1u : 0u; }

/* ---- CPU interrupt state ------------------------------------------------------------------------------------- */
static inline uint32_t brd_irq_save(void)
{
    uint32_t s;
    hb_point();
    s = hb.mstatus_mie;
    hb.mstatus_mie = 0u;
    return s;
}
static inline void brd_irq_restore(uint32_t saved) { hb_irq_restore(saved); }
static inline void brd_irq_enable(void) { hb_irq_restore(1u); }
static inline void brd_lines_on(uint32_t lines) { hb.mie |= lines; hb_point(); }
static inline void brd_lines_off(uint32_t lines) { hb_point(); hb.mie &= ~lines; }
static inline void brd_lines_flush(uint32_t lines) { hb_point(); (void)lines; }   /* no CPU latch in this model */

/* ---- cart register file -------------------------------------------------------------------------------------- */
static inline uint16_t brd_freg_rd(unsigned off)
{
    hb_point();
    return (off == BRD_FREG_FE4 || off == BRD_FREG_FE6 || off == BRD_FREG_FEA || off == BRD_FREG_FEC)
        ? hb.freg[(off >> 1) & 15u] : 0u;
}
static inline void brd_freg_wr(unsigned off, uint16_t v) { hb_point(); hb_freg_write(off, v); }

/* ---- stream -------------------------------------------------------------------------------------------------- */
static inline void brd_stream_ptr(uint32_t byte_off)
{
    hb_point();
    hb.sptr = byte_off & BRD_STREAM_MAX_WORDS;
    hb_log_board(HB_LOG_SPTR, hb.sptr);
}
static inline void brd_stream_go(uint32_t words)
{
    hb_point();
    hb_go(words & BRD_STREAM_MAX_WORDS);
    hb_log_board(HB_LOG_GO, words & BRD_STREAM_MAX_WORDS);
}
static inline uint32_t brd_stream_state(void)
{
    hb_point();
    return (hb.stream_valid ? 0x80000000u : 0u) | (hb.remaining & BRD_STREAM_MAX_WORDS);
}

/* ---- the sprite decoder (interface v1.2) --------------------------------------------------------------------- */
static inline void brd_dec_base(uint32_t byte_off)
{
    hb_point();
    hb.dec_base = byte_off & BRD_DEC_BASE_MASK;
    hb_log_board(HB_LOG_DECB, hb.dec_base);
}

/* ---- memories ------------------------------------------------------------------------------------------------ */
static inline volatile uint16_t *brd_cart_ram(void) { return hb.ram; }
static inline uint8_t brd_cart_ram_byte(uint32_t a)
{
    uint16_t w = hb.ram[(a & (BRD_CART_RAM_BYTES - 1u)) >> 1];
    return (uint8_t)((a & 1u) ? w : (w >> 8));          /* 68000 byte order: the even byte is the high half */
}
static inline volatile uint16_t *brd_rom(void) { return hb.rom; }
static inline uint8_t brd_rom_byte(uint32_t a)
{
    uint16_t w = hb.rom ? hb.rom[(a & (BRD_ROM_BYTES - 1u)) >> 1] : 0u;
    return (uint8_t)((a & 1u) ? w : (w >> 8));
}
static inline volatile uint8_t *brd_workspace(void) { return hb.workspace; }
static inline volatile uint8_t *brd_save(void) { return hb.save; }

/* ---- telemetry (interface v1.1) ------------------------------------------------------------------------------ */
static inline uint32_t brd_vs_count(void) { hb_point(); return hb.vs & BRD_VS_COUNT_MASK; }

#if FW_S5
/* ---- FW_S5 (interface v1.3): arrivals and the synth's order --------------------------------------------------- */
static inline uint32_t brd_seqlat(void) { hb_point(); return hb.seqlat; }
static inline uint32_t brd_stamp_a(void) { hb_point(); return hb.stamp_a; }
static inline uint32_t brd_synth_seq(void) { hb_point(); return (hb.arr & 0xFFFFu) | (hb.done << 16); }
static inline uint32_t brd_synth_status(void) { hb_point(); return hb.sy_status; }
static inline void brd_synth_done(uint32_t n)
{
    hb_point();
    hb.done = n & 0xFFFFu;
    hb.done_writes++;
    if (hb.on_done)
        hb.on_done(hb.done);
}
static inline void brd_synth_arm(uint32_t v)
{
    hb_point();
    hb.sy_arm = v & 1u;
    hb.arm_log[hb.arm_n++ & 63u] = v & 1u;
}
static inline uint32_t brd_synth_sched(void) { hb_point(); return hb.sy_sched; }
static inline uint32_t brd_synth_diag(void) { hb_point(); return hb.sy_diag; }
static inline void brd_synth_diag_clear(void) { hb_point(); hb.sy_diag = 0u; hb.diag_clears++; }
static inline const volatile int16_t *brd_dacbuf_l(void) { return (const volatile int16_t *)(hb.cram + 0x170000u / 2u); }
static inline const uint8_t *brd_flash8(void) { return hb.flash8; }
static inline const uint8_t *brd_flash16(void) { return hb.flash16; }
static inline const uint8_t *brd_bank(void) { return (const uint8_t *)hb.cram + 0x100u; }
static inline volatile uint16_t *brd_dacbuf(void) { return hb.cram + 0x170000u / 2u; }
void hb_config_apply(uint32_t v);                       /* s1_board.c: CONFIG's scheduler half */
static inline uint32_t brd_bank_ok(uint32_t stream) { (void)stream; return 1u; }   /* test build 5 on: no
                                                           cache slot on the host: the harness puts the chip's bank in
                                                           hb.cram */
static inline void brd_synth_config(uint32_t v)
{
    hb_point();
    hb.sy_config = v;
    hb.cfg_log[hb.cfg_n++ & 63u] = v;
    hb_config_apply(v);
}
/* the synth's fields (hb_synth_rd / hb_synth_wr in s1_board.c: the order registers answer as above) */
uint32_t hb_synth_rd(uint32_t off);
void     hb_synth_wr(uint32_t off, uint32_t v, uint32_t bytes);
static inline uint32_t brd_synth_rd(uint32_t off) { hb_point(); return hb_synth_rd(off); }
static inline void brd_synth_wr32(uint32_t off, uint32_t v) { hb_point(); hb_synth_wr(off, v, 4u); }
static inline void brd_synth_wr16(uint32_t off, uint32_t v) { hb_point(); hb_synth_wr(off, v, 2u); }
static inline void brd_synth_wr8(uint32_t off, uint32_t v) { hb_point(); hb_synth_wr(off, v, 1u); }
#endif

/* ---- options ------------------------------------------------------------------------------------------------- */
static inline uint32_t brd_options(void) { hb_point(); return hb.options; }
static inline uint32_t brd_menu_open(void) { return brd_options() & BRD_OPT_MENU; }

#endif
