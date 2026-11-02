/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/board.h - the board interface v1.2: the ONLY header the chip-exact core (core/) includes.
 *
 * One C interface, two boards: board/pocket (the Analogue Pocket cart MCU on MCU interface v1.2,
 * docs/MCU_INTERFACE.md) and board/host (the x86 fake board for host builds and tests). A MiSTer board would supply
 * the same (docs/MCU_INTERFACE.md section 10). The reference is docs/BOARD_IFACE.md; tests/check_board.py checks the
 * constants here against board/pocket/include/pocket_map.h and docs/MCU_INTERFACE.md, and tests/check_tree.py that
 * core/ includes nothing else from the board. "MCU_INTERFACE.md 4.2" below means section 4.2 of that document.
 *
 * Each board supplies "board_impl.h" on its own include path, which defines everything declared BRD_INLINE below as
 * static inline functions (on the Pocket they sit on reply paths; the host's call its board model). No board
 * address appears in this file.
 * Version: BRD_IFACE_MAJOR changes when a meaning changes, BRD_IFACE_MINOR when something is added (1: brd_vs_count,
 * the VS counter of MCU interface v1.1, 2026-10-13; 2: brd_dec_base, the RTL sprite decoder of MCU interface v1.2,
 * 2026-10-15, proposed). */
#ifndef BOARD_H
#define BOARD_H

#include <stdint.h>
#include "clock.h"          /* BRD_CLK_HZ (from the build), BRD_CYC_NS / BRD_CYC_US, the clock-following figures */

#define BRD_IFACE_MAJOR         1
#define BRD_IFACE_MINOR         2

/* FW_S5 = 1 builds the firmware's song engine with its ordered engine queue, on MCU interface v1.3 (the synth). Only
   the s5 variants of tools/fwbuild.py define it (s5test = the TEST image, s5release = the RELEASE image, and their
   probes); every other image of the s1 source set (fwbuild.json "s1") builds without it, byte for byte as before */
#ifndef FW_S5
#define FW_S5                   0
#endif

/* ---- interrupt causes: the level latches behind L1 (MCU_INTERFACE.md 4.2) ------------------------------------ */
#define BRD_CAUSE_B             0x1u    /* mailbox B: a 68000 write of $1FEA (the chip's EXTI 14) */
#define BRD_CAUSE_A             0x2u    /* mailbox A: a 68000 write of $1FEC (EXTI 15: the tick) */
#define BRD_CAUSE_S             0x4u    /* CPU MATE SEND: one event per sub-CPU post */
#define BRD_CAUSE_V             0x8u    /* console reset, 68000 only (EXTI 13; the Pocket menu's Console Reset,
                                           added 2026-10-27) */
#define BRD_CAUSE_ALL           0xFu

/* ---- interrupt lines = levels (MCU_INTERFACE.md 6.1): masks of the RISC-V mie register ---------------------- */
#define BRD_LINE_MEI            (1u << 11)  /* L1  l1_mei:  CAUSE (priority 1) */
#define BRD_LINE_MTI            (1u << 7)   /* L2a l2a_mti: the timer compare (priority 2) */
#define BRD_LINE_MSI            (1u << 3)   /* L2b l2b_msi: the software interrupt (priority 3) */
#define BRD_LINES_ALL           (BRD_LINE_MEI | BRD_LINE_MTI | BRD_LINE_MSI)

/* ---- cart register file, MCU side, at the chip's offsets (MCU_INTERFACE.md 3.4) ------------------------------ */
#define BRD_FREG_FE4            0x04u   /* $1FE4 control word: stored (the 68000 reads busy | model instead) */
#define BRD_FREG_FE6            0x06u   /* $1FE6 status: stored */
#define BRD_FREG_FE8            0x08u   /* $1FE8 window: acts on write (1 on; 0 off + mini view), reads 0 */
#define BRD_FREG_FEA            0x0Au   /* $1FEA mailbox B: stored; an MCU write clears the busy guard, raises nothing */
#define BRD_FREG_FEC            0x0Cu   /* $1FEC mailbox A: stored */
#define BRD_FREG_FEE            0x0Eu   /* $1FEE: acts on write (window off + mini view), reads 0 */
#define BRD_FREG_FF0            0x10u   /* $1FF0 FIFO-A target: no RTL storage (the firmware keeps it) */
#define BRD_FREG_FF2            0x12u   /* $1FF2 stream control: acts on write (v1.2: the decoder's START 0x8000 /
                                           STOP), reads 0 */
#define BRD_FREG_FF4            0x14u   /* $1FF4 queue high: the decoder latches it (v1.2), reads 0 */
#define BRD_FREG_FF6            0x16u   /* $1FF6 queue low / clear: the decoder's push (even) / clear (odd) (v1.2) */

/* ---- the option word (MCU_INTERFACE.md 5): live, read once at boot by the game ----------------------------- */
#define BRD_OPT_MODEL_MASK      0x00000740u /* bits 6, 8-10: the $1FE4 Console model bits */
#define BRD_OPT_MW_MASK         0x00070000u /* bits 16-18: MegaWire option, three copies (7 = On) */
#define BRD_OPT_MW_SHIFT        16u
#define BRD_OPT_MENU            (1u << 24)  /* the Pocket menu is open (68000 paused) */
#define BRD_OPT_JAP             (1u << 25)  /* Console region = Japan */
#define BRD_OPT_PAL             (1u << 26)  /* PAL build (0 in every v1.0 Pocket build) */

/* ---- memory sizes every board provides (MCU_INTERFACE.md 3, 10.5) ------------------------------------------- */
#define BRD_CART_RAM_BYTES      0x2000u     /* the 68000's cart RAM $0000-$1FFF ($1FE0-$1FFF: never touched here) */
#define BRD_CART_RAM_USER_END   0x1FE0u     /* firmware stores stay below the register page */
#define BRD_ROM_BYTES           0x800000u   /* the 8 MB ROM image */
#define BRD_WORKSPACE_BYTES     0x200000u   /* the stream workspace (2 MB) */
#define BRD_SAVE_BYTES          0x2000u     /* battery save, 8 KB like the cart's EEPROM */
#define BRD_STREAM_MAX_WORDS    0x1FFFFFu   /* GO length: 21 bits */
#define BRD_VS_COUNT_MASK       0xFFFFu     /* the VS count: 16 bits, wrapping (brd_vs_count) */
#define BRD_DEC_BASE_MASK       0x1FFFFEu   /* the decoder's output base: an even workspace byte offset (v1.2) */

#define BRD_INLINE static inline

/* ================================================================================================================
 * Board functions (defined by the board's board_impl.h or its board sources)
 * ================================================================================================================ */

/* ---- time: the board timer counts BRD_CLK_HZ cycles and wraps at 2^32 (80 s NTSC) (MCU_INTERFACE.md 4.3) ----- */
BRD_INLINE uint32_t brd_now(void);                      /* TIMER */
BRD_INLINE void     brd_timer_arm(uint32_t deadline);   /* compare := deadline, enable: the MTI level is up while
                                                           (now - deadline) >= 0 (signed); a past deadline fires at once */
BRD_INLINE void     brd_timer_disarm(void);             /* enable := 0: the MTI level drops */
BRD_INLINE uint32_t brd_cycles(void);                   /* the CPU cycle counter (mcycle), for TEST counters */

/* ---- interrupt sources --------------------------------------------------------------------------------------- */
BRD_INLINE uint32_t brd_cause(void);                    /* BRD_CAUSE_* bits that are set */
BRD_INLINE void     brd_cause_ack(uint32_t bits);       /* clear them (write 1 to clear); a set in the same clock wins */
BRD_INLINE uint32_t brd_stamp_b(void);                  /* brd_now() at the clock BRD_CAUSE_B was last set */
BRD_INLINE void     brd_msi(uint32_t on);               /* the software interrupt level (L2b): 1 raise, 0 clear */

/* ---- CPU interrupt state (rules: MCU_INTERFACE.md 6.3) ------------------------------------------------------ */
BRD_INLINE uint32_t brd_irq_save(void);                 /* global interrupts off; returns the previous state */
BRD_INLINE void     brd_irq_restore(uint32_t saved);    /* back to that state */
BRD_INLINE void     brd_irq_enable(void);               /* global interrupts on */
BRD_INLINE void     brd_lines_on(uint32_t lines);       /* BRD_LINE_* enables on */
BRD_INLINE void     brd_lines_off(uint32_t lines);      /* BRD_LINE_* enables off */
BRD_INLINE void     brd_lines_flush(uint32_t lines);    /* enable off then on: drops a request the CPU latched
                                                           before the source was acknowledged (rule 6.3.3) */

/* ---- cart register file (MCU_INTERFACE.md 3.4): 16-bit, program order, nothing posted ----------------------- */
BRD_INLINE uint16_t brd_freg_rd(unsigned off);          /* BRD_FREG_*: the stored word, 0 for the others */
BRD_INLINE void     brd_freg_wr(unsigned off, uint16_t v);

/* ---- the $C000 stream (MCU_INTERFACE.md 4.5): pointer first, then GO ---------------------------------------- */
BRD_INLINE void     brd_stream_ptr(uint32_t byte_off);  /* window start: even byte offset into the workspace */
BRD_INLINE void     brd_stream_go(uint32_t words);      /* N > 0: N words valid from the pointer; 0: stream invalid */
BRD_INLINE uint32_t brd_stream_state(void);             /* bit 31 valid, bits 20:0 words remaining */
/* ---- the sprite decoder (interface v1.2, MCU_INTERFACE.md 4.9): the RTL decodes what the chip's queue writes list - */
BRD_INLINE void     brd_dec_base(uint32_t byte_off);    /* the next START's output base (even workspace byte offset):
                                                           written before each $1FF2 = 0x8000 that has entries; the RTL
                                                           then loads SPTR with it, decodes there and GOes itself */

/* ---- memories ------------------------------------------------------------------------------------------------ */
BRD_INLINE volatile uint16_t *brd_cart_ram(void);           /* halfword i = 68000 word 2*i */
BRD_INLINE uint8_t            brd_cart_ram_byte(uint32_t a);  /* 68000 byte a (the byte view; read only) */
BRD_INLINE volatile uint16_t *brd_rom(void);                /* halfword i = ROM word 2*i (the patchable image) */
BRD_INLINE uint8_t            brd_rom_byte(uint32_t a);       /* ROM byte a (the byte view; read only) */
BRD_INLINE volatile uint8_t  *brd_workspace(void);          /* the stream workspace, byte-native */
BRD_INLINE volatile uint8_t  *brd_save(void);               /* battery save, byte lanes */

#if FW_MW
/* ---- FW_MW = 1 (the MegaWire code, test build S3b on): the Pocket SRAM image that holds it (MCU_INTERFACE.md 3.7) */
uint32_t brd_sram_image_ok(void);                       /* boot, once: the image in SRAM (from the firmware file) is
                                                           this build's and intact (header, link id, the hot part's
                                                           CRC-32); 1 also sets the image lock. Nothing calls
                                                           into the image unless it returned 1 */
uint32_t s3_sram_cold_ok(void);                         /* the image's cold part (the A858 screen) checked by its own
                                                           CRC-32, once a boot: nothing calls into it unless 1 */
#endif

/* ---- options and the Pocket menu ----------------------------------------------------------------------------- */
BRD_INLINE uint32_t brd_options(void);                  /* the option word (BRD_OPT_*) */
BRD_INLINE uint32_t brd_menu_open(void);                /* nonzero while the Pocket menu is open */

/* ---- the VDP's frames (interface v1.1): TEST telemetry, and since 2026-10-17 the C6 hold's frame count (both
   variants; a job's length, never a reply: core/dispatch/jobs.c) --------------------------------------------------- */
BRD_INLINE uint32_t brd_vs_count(void);                 /* the VDP's vertical syncs (frames) since the last reset,
                                                           BRD_VS_COUNT_MASK bits, wrapping: alive while it moves
                                                           (MCU_INTERFACE.md 4.8 VSCNT) */

#if FW_S5
/* ---- FW_S5 (MCU interface v1.3, frozen 2026-10-21; MCU_INTERFACE.md 3.10.5 and 4.6): the arrival numbers and the
   synth's order ----
   ARR counts the 68000's writes to $1FEA / $1FEC (the pulses that set CAUSE.B / A), 16 bits wrapping; the write that
   makes ARR = n is arrival n. DONE = n tells the synth that arrivals up to n are served (a block waits for it). */
BRD_INLINE uint32_t brd_seqlat(void);                   /* SEQLAT: [15:0] the arrival number of the last 68000 write
                                                           to $1FEA, [31:16] of the last to $1FEC */
BRD_INLINE uint32_t brd_stamp_a(void);                  /* STAMP_A: TIMER at the clock CAUSE.A was last set */
BRD_INLINE uint32_t brd_synth_seq(void);                /* SEQ: [15:0] ARR, [31:16] DONE */
BRD_INLINE uint32_t brd_synth_status(void);             /* STATUS: [0] BUSY, [8:5] QDEPTH, [27:16] BLKCNT (blocks mixed,
                                                           mod 4,096) */
BRD_INLINE void     brd_synth_done(uint32_t n);         /* DONE := n[15:0] (only forward, in arrival order) */
#define BRD_SYNTH_BUSY          0x1u
#define BRD_SYNTH_QDEPTH(s)     (((s) >> 5) & 0xFu)     /* the TIM6 instants queued (v1.3 3.10.5) */
#define BRD_SYNTH_BLKCNT(s)     (((s) >> 16) & 0xFFFu)
/* the tick's other v1.3 lines (MCU_INTERFACE.md 3.10.1, 3.8) and the module store (a design decision) */
BRD_INLINE void     brd_synth_arm(uint32_t v);          /* ARM := v[0]: the chip's frame_pending (G+0x18) */
BRD_INLINE uint32_t brd_synth_sched(void);              /* SCHED: [7:0] CNT (G+0x3A), [11:8] NBLK, [31:16] HALF */
BRD_INLINE uint32_t brd_synth_diag(void);               /* DIAG: [7:0] INCOMPLETE, [15:8] TIMEOUTS, [23:16] WBUSY,
                                                           [31:24] UNDERRUN, saturating */
BRD_INLINE void     brd_synth_diag_clear(void);         /* any DIAG write clears all four */
BRD_INLINE const volatile int16_t *brd_dacbuf_l(void);  /* CRAM DACBUF_L: the chip's dac_buf_L, 1,920 x u16 */
#define BRD_SYNTH_CNT(s)        ((s) & 0xFFu)
#define BRD_DACBUF_N            1920u       /* dac_buf_L entries; dac_buf_R follows at once (CRAM 0x170F00) */
#define BRD_MODSTORE_OFF        0x0A0000u   /* the module store in the SDRAM workspace (a census of the game's SDRAM
                                               writes counted 0 writes there on the images of test build 4,
                                               the fast-path build) */
#define BRD_MODSTORE_BYTES      0x92000u    /* 598,016 B: the directory + the 52 modules (594,544 B) word-aligned */
#define BRD_MODSTORE_DIR        0x210u      /* magic, count, 64 offsets, 64 lengths, to 16 B: the first module's
                                               offset */
#define BRD_MODSTORE_MAGIC      0x5254534Du /* 'MSTR' */
/* C6's views and the CONFIG write (MCU_INTERFACE.md v1.3 3.5, 3.8, 3.10.1-3.10.2) */
BRD_INLINE const uint8_t *brd_flash8(void);             /* the flash byte view: byte a = ROM byte a (3.5) */
BRD_INLINE const uint8_t *brd_flash16(void);            /* the flash word view as bytes: byte a = ROM byte a ^ 1 */
#if FW_MW
BRD_INLINE volatile uint8_t *brd_mwtext(void);          /* FW_MW: CRAM MWTEXT, byte i = the cart program's byte
                                                           0x08010000 + i once core/mw/mw_text.c has unpacked it (3.8) */
#endif
BRD_INLINE const uint8_t *brd_bank(void);               /* CRAM BANK: byte i = the chip's SDRAM 0xC0089800 + i (3.8) */
BRD_INLINE volatile uint16_t *brd_dacbuf(void);         /* CRAM DACBUF_L (writable), DACBUF_R right after it */
BRD_INLINE void     brd_synth_config(uint32_t v);       /* CONFIG := v: [1:0] MODE, [2] PAL, [3] DTWIN, [31:16] SEQ */
BRD_INLINE uint32_t brd_bank_ok(uint32_t stream);       /* test build 5 on: the wave bank in CRAM BANK is this
                                                           power-on's unpack or
                                                           checked file (XLINK CACHE.VALID, MCU_INTERFACE.md v1.3 3.9 /
                                                           21.1) and was made from this WavPack stream (the ROM byte
                                                           address the game's C600 names = the cache header's ROM key,
                                                           board/pocket/boot/c4b.h C4B_H_STREAM) */
#define BRD_C6TAB_OFF           0x132000u   /* C6's tables in the workspace, right after the module store (inside the
                                               free span 0x0965F6-0x1DFFFF that the SDRAM census found): the wave
                                               programs 0x1000 B, then the PSG presets 0x800 B */
/* the synth's fields (MCU_INTERFACE.md v1.3 3.10.1 the global registers, 3.10.3 the voice windows, 3.10.4 the SFX
   windows; offsets into region 0x06) and its block-done event (4.2 CAUSE.BLK, 4.1 CTRL.BLKIE). A store writes only
   its byte lanes; a load returns the whole word (3.10). The logic-owned fields are read, and every field is written,
   only between synth_begin and synth_end (3.10.5): core/sched/s5_mirror.c */
#define BRD_CAUSE_BLK           0x10u   /* v1.3: the synth's BUSY fell (3.10.5); W1C; raises MEI with CTRL.BLKIE */
BRD_INLINE uint32_t brd_synth_rd(uint32_t off);         /* the region 0x06 word at off (word aligned) */
BRD_INLINE void     brd_synth_wr32(uint32_t off, uint32_t v);
BRD_INLINE void     brd_synth_wr16(uint32_t off, uint32_t v);   /* a halfword store: lanes off, off + 1 only */
BRD_INLINE void     brd_synth_wr8(uint32_t off, uint32_t v);    /* a byte store: lane off only */
void     brd_synth_blkie(uint32_t on);                  /* CTRL.BLKIE: CAUSE.BLK takes part in the MEI line */
#define BRD_SY_FLAGS            0x008u  /* [0] SEQON [1] PLAYING [2] SFXON [3] BGMECHO [4] SFXECHO [5] LEVELNZ */
#define BRD_SY_WMASTER          0x00Cu  /* [15:0] L, [31:16] R */
#define BRD_SY_WBOOST           0x010u  /* [15:0] BOOST, [31:16] WAVEMASTER */
#define BRD_SY_SMASTER          0x014u  /* [15:0] L, [31:16] R */
#define BRD_SY_SMCFG            0x018u  /* [15:0] SFXMASTER */
#define BRD_SY_ECHOB            0x01Cu  /* [15:0] GAIN, [23:16] DELAY, [31:24] INDEX (logic) */
#define BRD_SY_ECHOS            0x020u  /* [15:0] GAIN, [23:16] DELAY, [31:24] INDEX (logic) */
#define BRD_SY_STATUS           0x030u  /* [0] BUSY [1] RUN [2] FPEND [3] FILL [4] CUR [8:5] QDEPTH [27:16] BLKCNT */
#define BRD_SY_YMFILT           0x038u  /* [15:0] A, [31:16] B (logic) */
#define BRD_SY_SCHED            0x04Cu  /* [7:0] CNT [11:8] NBLK [31:16] HALF */
#define BRD_SY_VOICE(v)         (0x400u + 0x40u * (v))  /* v = 0..15 = the chip's voice 10 + v */
#define BRD_SY_SFX(c)           (0x800u + 0x40u * (c))  /* c = 0..7 */
#define BRD_SYNTH_FPEND         0x4u    /* STATUS bits: frame_pending, fill_half, cur_half */
#define BRD_SYNTH_FILL          0x8u
#define BRD_SYNTH_CUR           0x10u
#define BRD_CRAM_BANK_OFF       0x100u      /* the wave bank's CRAM byte (3.8 BANK):
                                               a voice window's BASE */
#define BRD_CRAM_SFXBANK_OFF    0x200000u   /* the SFX bank's CRAM byte (3.8 SFXBANK = the ROM's SFX words from the
                                               SFX table's address): an SFX window's PTR / BASE */
#define BRD_CRAM_OFF_MASK       0x3FFFFFu   /* a window's CRAM offset field [21:0] */
#endif

/* ---- board control (the board layer's boot; the core calls none of these on a reply path) ------------------- */
void brd_md_hold(uint32_t hold);                        /* 1: the 68000 is held; 0: released (the last boot step) */
void brd_menu_mute(uint32_t on);                        /* the music pause + SFX mute while the menu is open */
void brd_opt_at_reset(uint32_t on);                     /* the dormant "options apply at reset" latch (0 = 0.2.6) */
void brd_full_reset(void) __attribute__((noreturn));    /* hold the 68000, mask interrupts, restart the firmware from
                                                           its reset vector; the RTL state stays (the cart's MCU reset) */
void brd_milestone(uint32_t code);                      /* TEST boot milestone (no effect in RELEASE) */

/* ---- the hand-off block (docs/BOOT_SPEC.md 3): what the cart's bootloader leaves for app init-------------------- */
typedef struct {
    uint32_t w1fe0;     /* copied by app init, never used: 0 */
    uint32_t w1fe4;     /* copied by app init, never used: 0 */
    uint32_t page_a;    /* MegaWire page A (FW_MW); 0 in the first new-core firmware */
    uint32_t page_b;    /* MegaWire page B, the font (FW_MW); 0 in the first new-core firmware */
} board_handoff;
const board_handoff *board_get_handoff(void);

/* ================================================================================================================
 * Core functions the board calls (defined in core/)
 * ================================================================================================================ */
void l1_mei(void);                                      /* L1, from the trap entry, interrupts off throughout */
void l2a_mti(void);                                     /* L2a, MEI open */
void l2b_msi(void);                                     /* L2b, MEI and MTI open */
void l3_thread(void) __attribute__((noreturn));         /* L3, everything open; entered last by the boot */
uint32_t sched_exception(uint32_t mcause, uint32_t mepc, uint32_t mtval);  /* an exception: returns where to resume */

/* ---- helpers built on the functions above (same on every board) --------------------------------------------- */
static inline int32_t brd_until(uint32_t deadline) { return (int32_t)(deadline - brd_now()); }

#include "board_impl.h"

#endif
