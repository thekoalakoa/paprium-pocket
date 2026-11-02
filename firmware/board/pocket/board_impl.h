/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/board_impl.h - the Pocket's definitions of the board interface v1.2 inline functions (board/board.h).
 *
 * Included at the end of board.h; never included directly. Every access is one load or store to the MCU interface
 * v1.0 registers (pocket_map.h, docs/MCU_INTERFACE.md) or one CSR instruction. MMIO is volatile and the CSR
 * statements that open or close interrupts clobber memory, so the compiler keeps program order across them. */
#ifndef BOARD_IMPL_POCKET_H
#define BOARD_IMPL_POCKET_H

#include <stdint.h>
#include "pocket_map.h"

#define BRD_IO32(a)             (*(volatile uint32_t *)(uintptr_t)(a))
#define BRD_IO16(a)             (*(volatile uint16_t *)(uintptr_t)(a))

/* ---- time ---------------------------------------------------------------------------------------------------- */
static inline uint32_t brd_now(void) { return BRD_IO32(POCKET_FIO_TIMER); }
static inline void brd_timer_arm(uint32_t deadline)
{
    BRD_IO32(POCKET_FIO_TCMP) = deadline;
    BRD_IO32(POCKET_FIO_TCTRL) = POCKET_TCTRL_TEN;
}
static inline void brd_timer_disarm(void) { BRD_IO32(POCKET_FIO_TCTRL) = 0u; }
static inline uint32_t brd_cycles(void)
{
    uint32_t c;
    __asm__ volatile ("csrr %0, mcycle" : "=r"(c));
    return c;
}

/* ---- interrupt sources --------------------------------------------------------------------------------------- */
#if FW_S5
static inline uint32_t brd_cause(void) { return BRD_IO32(POCKET_FIO_CAUSE) & 0x1Fu; }   /* v1.3: + BLK (bit 4) */
#else
static inline uint32_t brd_cause(void) { return BRD_IO32(POCKET_FIO_CAUSE) & 0xFu; }
#endif
static inline void brd_cause_ack(uint32_t bits) { BRD_IO32(POCKET_FIO_CAUSE) = bits; }
static inline uint32_t brd_stamp_b(void) { return BRD_IO32(POCKET_FIO_STAMP_B); }
static inline void brd_msi(uint32_t on) { BRD_IO32(POCKET_FIO_MSIP) = on ? POCKET_MSIP_BIT : 0u; }

/* ---- CPU interrupt state ------------------------------------------------------------------------------------- */
static inline uint32_t brd_irq_save(void)
{
    uint32_t s;
    __asm__ volatile ("csrrci %0, mstatus, 8" : "=r"(s) : : "memory");
    return s & POCKET_MSTATUS_MIE;
}
static inline void brd_irq_restore(uint32_t saved)
{
    __asm__ volatile ("csrs mstatus, %0" : : "r"(saved & POCKET_MSTATUS_MIE) : "memory");
}
static inline void brd_irq_enable(void) { __asm__ volatile ("csrsi mstatus, 8" : : : "memory"); }
static inline void brd_lines_on(uint32_t lines) { __asm__ volatile ("csrs mie, %0" : : "r"(lines) : "memory"); }
static inline void brd_lines_off(uint32_t lines) { __asm__ volatile ("csrc mie, %0" : : "r"(lines) : "memory"); }
static inline void brd_lines_flush(uint32_t lines)
{
    __asm__ volatile ("csrc mie, %0\n\tcsrs mie, %0" : : "r"(lines) : "memory");
}

/* ---- cart register file -------------------------------------------------------------------------------------- */
/* The register accessor (board/pocket/s1_freg.c): every write is stored in RTL first (program order, nothing posted:
   docs/MCU_INTERFACE.md 3.4; v1.2: the RTL's sprite decoder acts on $1FF2 / $1FF4 / $1FF6 itself, 4.9), then the
   accessor keeps the firmware shadow of every offset (the RTL stores only $1FE4/6/A/C) and, in TEST builds, appends
   the write to the chip-runner comparison's log (docs/CART_FPGA_SPEC.md 15.1). Reads return what the RTL returns: the
   stored word, 0 for the act-on-write offsets. */
void s1_freg_wr(unsigned off, uint16_t v);               /* the store, then the shadow / queue / log */
void s1_board_log(uint32_t tag, uint32_t v);            /* TEST: the chip-runner log for the board-only writes */
#define S1_LOG_SPTR             0x40u                   /* log tags of the board-only writes (rule T4) */
#define S1_LOG_GO               0x41u
#define S1_LOG_DECB             0x42u                   /* v1.2: DEC_BASE before a decoder START */
static inline uint16_t brd_freg_rd(unsigned off) { return BRD_IO16(POCKET_FREG_BASE + off); }
static inline void brd_freg_wr(unsigned off, uint16_t v) { s1_freg_wr(off, v); }

/* ---- stream: pointer first, then GO (MCU_INTERFACE.md 4.5) ----------------------------------------------------- */
static inline void brd_stream_ptr(uint32_t byte_off)
{
    BRD_IO32(POCKET_FIO_SPTR) = byte_off & POCKET_SPTR_MASK;
    s1_board_log(S1_LOG_SPTR, byte_off & POCKET_SPTR_MASK);   /* the chip-runner log (TEST; else an empty call) */
}
static inline void brd_stream_go(uint32_t words)
{
    BRD_IO32(POCKET_FIO_GO) = words & POCKET_GO_WORDS_MASK;
    s1_board_log(S1_LOG_GO, words & POCKET_GO_WORDS_MASK);
}
static inline uint32_t brd_stream_state(void) { return BRD_IO32(POCKET_FIO_GO); }

/* ---- the sprite decoder (MCU interface v1.2, 4.9) ---------------------------------------------------------------- */
static inline void brd_dec_base(uint32_t byte_off)
{
    BRD_IO32(POCKET_FIO_DEC_BASE) = byte_off & POCKET_DEC_BASE_MASK;
    s1_board_log(S1_LOG_DECB, byte_off & POCKET_DEC_BASE_MASK);
}

/* ---- memories ------------------------------------------------------------------------------------------------ */
static inline volatile uint16_t *brd_cart_ram(void) { return (volatile uint16_t *)(uintptr_t)POCKET_RAMDP_BASE; }
static inline uint8_t brd_cart_ram_byte(uint32_t a)
{
    return *(const volatile uint8_t *)(uintptr_t)(POCKET_RAMDP_BV_BASE + (a & (POCKET_RAMDP_BYTES - 1u)));
}
static inline volatile uint16_t *brd_rom(void) { return (volatile uint16_t *)(uintptr_t)POCKET_FLASH_BASE; }
static inline uint8_t brd_rom_byte(uint32_t a)
{
    return *(const volatile uint8_t *)(uintptr_t)(POCKET_FLASH_BV_BASE + (a & (POCKET_FLASH_BYTES - 1u)));
}
static inline volatile uint8_t *brd_workspace(void) { return (volatile uint8_t *)(uintptr_t)POCKET_SDRAM_BASE; }
static inline volatile uint8_t *brd_save(void) { return (volatile uint8_t *)(uintptr_t)POCKET_BRAM_BASE; }

/* ---- telemetry (MCU interface v1.1) ---------------------------------------------------------------------------- */
static inline uint32_t brd_vs_count(void) { return BRD_IO32(POCKET_FIO_VSCNT) & POCKET_VSCNT_MASK; }

#if FW_S5
/* ---- FW_S5 (MCU interface v1.3): arrivals and the synth's order ---------------------------------------------- */
#include "pocket_s5.h"
static inline uint32_t brd_seqlat(void) { return BRD_IO32(POCKET_SY_SEQLAT); }
static inline uint32_t brd_stamp_a(void) { return BRD_IO32(POCKET_FIO_STAMP_A); }
static inline uint32_t brd_synth_seq(void) { return BRD_IO32(POCKET_SY_SEQ); }
static inline uint32_t brd_synth_status(void) { return BRD_IO32(POCKET_SY_STATUS); }
static inline void brd_synth_done(uint32_t n) { BRD_IO32(POCKET_SY_DONE) = n & 0xFFFFu; }
static inline void brd_synth_arm(uint32_t v) { BRD_IO32(POCKET_SY_ARM) = v & 1u; }
static inline uint32_t brd_synth_sched(void) { return BRD_IO32(POCKET_SY_SCHED); }
static inline uint32_t brd_synth_diag(void) { return BRD_IO32(POCKET_SY_DIAG); }
static inline void brd_synth_diag_clear(void) { BRD_IO32(POCKET_SY_DIAG) = 0u; }
static inline const volatile int16_t *brd_dacbuf_l(void)
{
    return (const volatile int16_t *)(uintptr_t)POCKET_CRAM_DACBUF_L;
}
static inline const uint8_t *brd_flash8(void) { return (const uint8_t *)(uintptr_t)POCKET_FLASH_BV_BASE; }
static inline const uint8_t *brd_flash16(void) { return (const uint8_t *)(uintptr_t)POCKET_FLASH_BASE; }
static inline const uint8_t *brd_bank(void) { return (const uint8_t *)(uintptr_t)POCKET_CRAM_BANK; }
static inline volatile uint8_t *brd_mwtext(void) { return (volatile uint8_t *)(uintptr_t)POCKET_CRAM_MWTEXT; }
static inline volatile uint16_t *brd_dacbuf(void) { return (volatile uint16_t *)(uintptr_t)POCKET_CRAM_DACBUF_L; }
static inline void brd_synth_config(uint32_t v) { BRD_IO32(POCKET_SY_CONFIG) = v; }
/* test build 5 on: XLINK CACHE (power-on only, set last by the boot cache once the bank checked) and the header's
   ROM key word
   (CRAM HDR word 8, c4b.h C4B_H_STREAM; the header is part of the checked image) */
static inline uint32_t brd_bank_ok(uint32_t stream)
{
    return (BRD_IO32(POCKET_XL_CACHE) & POCKET_CACHE_VALID) != 0u &&
           (BRD_IO32(POCKET_XL_CACHE) & POCKET_CACHE_SIZE_MASK) == POCKET_CACHE_IMAGE_MAX &&
           BRD_IO32(POCKET_CRAM_HDR + 4u * 8u) == (stream & ~1u);   /* the stream as song_c6 reads it */
}
/* the synth's fields (v1.3 3.10: a store writes only its byte lanes, a load returns the whole word) */
static inline uint32_t brd_synth_rd(uint32_t off) { return BRD_IO32(POCKET_SY_BASE + off); }
static inline void brd_synth_wr32(uint32_t off, uint32_t v) { BRD_IO32(POCKET_SY_BASE + off) = v; }
static inline void brd_synth_wr16(uint32_t off, uint32_t v) { BRD_IO16(POCKET_SY_BASE + off) = (uint16_t)v; }
static inline void brd_synth_wr8(uint32_t off, uint32_t v)
{
    *(volatile uint8_t *)(uintptr_t)(POCKET_SY_BASE + off) = (uint8_t)v;
}
#endif

/* ---- options ------------------------------------------------------------------------------------------------- */
static inline uint32_t brd_options(void) { return BRD_IO32(POCKET_GPIO_INPUT); }
static inline uint32_t brd_menu_open(void) { return brd_options() & POCKET_OPT_MENU; }

#endif
