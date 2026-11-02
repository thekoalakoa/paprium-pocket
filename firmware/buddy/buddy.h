/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * buddy.h - the hook-free CPU MATE buddy on the cart NEORV32 (option D: the Mega CD link gives the game honest BUSY
 * and COMSTAT2 values), firmware glue. First written for a 0.2.6 test firmware, in a research build outside this tree.
 * ("Today" and "shipping" in the buddy files mean the 0.2.6 firmware without this glue.)
 *
 * What the glue does (zz_buddy.c, zz_buddy_trap.c):
 *   1. The main loop's existing FPGAIO ctrl read (FPGAIO = the core's register block for the MCU) also sees the stub's
 *      "send pending" and "AI off" bits (paprium_xlink LSTAT[7:0] -> fpgio ctrl[15:8]). Its test changes from
 *      (ctrl >> 3) & 1 to
 *      (ctrl >> 3) & BUDDY_LOOP_MASK: the same four instructions, so with Mega CD Mode off (no post, no
 *      $A12001 write can ever reach the stub) every pass is the same instructions and cycles as today.
 *   2. A send runs the brain (H2 = the AI call with the counter, then H1 = the word) at the end of a pass
 *      with reg_cmd == 0, as a task: MEIE + MTIE + MIE are set only while it runs. The mailbox post
 *      interrupt runs today's loop body (ppm_cmd_handler, sfx_player_update, ppm_music_vu_update) until
 *      the mailbox is quiet, so a cart reply never waits behind the brain.
 *   3. On finish: PEND, D_WORD, D_BUSY (forced >= D_WORD) and ARM; ARM is read back and re-sent if the
 *      stub did not take it.
 *   4. SRES 1 -> 0 (restart) and SBRQ 0 -> 1 (AI off): the call in flight is aborted (or discarded), and
 *      at the release (SRES = 1, SBRQ = 0) the sub init's Word RAM pattern is written into the SRAM
 *      mirror and the brain's restart flag is raised (the brain clears its AI block itself, in its H2 entry).
 *   5. R-SFX: a rate-aware feeder on the MTIME interrupt, on an absolute grid (BUDDY_FEED_PERIOD): every channel
 *      with samples left and a FIFO not full gets k = ceil((P + J) / T) + 1 pushes a tick (T = its sample period,
 *      from the SFX table, rebuilt whenever the SFX base changes - 0xC6), in channel order, with a mailbox-interrupt
 *      window (never a tick: MTIE is off inside a tick) between two channels; a tick late by m periods pushes
 *      k * (1 + m); the run's first round runs at once with interrupts off, fused with the scan (after today's own
 *      push pass at the slow path's entry); a channel started inside the run (a 0xD1 in the post ISR, also on a
 *      channel that ended earlier in the run) gets its first batch in that ISR right after the command's service; a
 *      post taken inside a tick's window leaves its scan and VU schedule to the tick's end, where windows sit between
 *      the pieces; channels are topped up before a VU row. Same per-channel code as sfx_player_update
 *      (kept in registers; part A of the glue's unit test, outside this tree, checks the values).
 *   6. R-VU: the VU due check runs at the row's due instant (MTIME compare from a calibrated
 *      FPGAIO-ms/MTIME phase), polling until the phase is known.
 */
/*
 * INTEGRATION (what the next phase must provide or keep; placeholders are marked in the code):
 *   - build: objcopy --globalize-symbol=vu_due --globalize-symbol=vu_on paprium.c.o before the link (one line in
 *     the core repository's scripts/build_mcu.sh). paprium.c is NOT recompiled differently.
 *   - brain ABI (BudEntry): H2 and H1 are plain RV-ABI calls with no arguments; they may use tp (the counter) but
 *     must not write gp (the interrupt handlers run shipping C code that addresses data through gp); H1 returns
 *     the word in a0; the counter leaves {c_hat, D_WORD, D_BUSY} at cnt_out and reads Wf at cnt_out + 12 (the glue
 *     writes 0: W lives in the stub's 12.5 MHz tick). The flag halfword is raised by the glue before the first call
 *     after a release; the brain clears it (in the restart path of its H1 / H2 entries).
 *   - memory: the glue's state is WRAM 0x80001670-0x80001873 (.noinit.zz_buddy, right after the shipping .bss;
 *     0x58 of it is the stub brain's config, gone with BUDDY_STUB_BRAIN = 0);
 *     the rate hash uses SRAM 0x08018000-0x08018BFF; the sub-init restore writes the SRAM mirror (records 4).
 *   - RTL facts relied on: LSTAT/LCLR/D_WORD/D_BUSY/PEND/ARM/LCTRL as the 0.2.6 paprium_xlink.sv has them;
 *     ctrl[15:8] = {mbx_irq, sbrq, sres, busy, late, aioff, restart, send}; FPGAIO register 6 (0x01000018) clears
 *     the mailbox latch. From our study of the game: its every SRES 1 -> 0 edge comes with SBRQ = 1 (an AI-off edge,
 *     or AI off already held).
 */
#ifndef BUDDY_H
#define BUDDY_H

#include <stdint.h>

/* ------------------------------------------------------------------ build switches */
#ifndef BUDDY_STUB_BRAIN
#define BUDDY_STUB_BRAIN        1       /* 1: placeholder brain linked into the IROM image (zz_buddy_stub.c);
                                           0: the brain comes from the PBUD image in the Pocket SRAM */
#endif
/* 1 = the real brain is linked into block RAM (the layout B Jam chose: its read-only data and code in the tail of the
   IROM's rom0 and its extension, the counting helpers in the WRAM code window, both filled by the bitstream; its data
   in WRAM and the Pocket SRAM). The entry table is zz_buddy_brain.c (written by a generator outside this tree). No
   PBUD loader. */
#ifndef BUDDY_LINKED_BRAIN
#define BUDDY_LINKED_BRAIN      0
#endif
#if BUDDY_LINKED_BRAIN && BUDDY_STUB_BRAIN
#error "BUDDY_LINKED_BRAIN needs BUDDY_STUB_BRAIN = 0"
#endif

/* ------------------------------------------------------------------ the main loop's test */
/* (ctrl >> 3): bit 0 = md_rst_status (ctrl[3]), bit 5 = send pending (ctrl[8] = LSTAT[0]),
   bit 7 = AI off (ctrl[10] = LSTAT[2]). The restart flag (ctrl[9]) powers up 1 and is NOT in the mask. */
#define BUDDY_LOOP_MASK         0xA1u

void buddy_event(uint32_t ctrl);        /* the slow path: called from ppm_start with the ctrl word */

/* ------------------------------------------------------------------ MMIO */
#define BUD_FPGAIO_CTRL         0x01000000u
#define BUD_FPGAIO_TIME         0x01000004u
#define BUD_FPGAIO_IRQCLR       0x01000018u     /* register 6: write bit 0 = 1 clears the mailbox latch */
#define BUD_RAMDP_REGCMD        0x02001FEAu
#define BUD_SFX_BASE            0x06000000u
#define BUD_FLASH_BASE          0x04000000u
#define BUD_SRAM_BASE           0x08000000u
#define BUD_XLINK_BASE          0x0A000000u

#define XL_XCFG                 0x00
#define XL_ID                   0x04
#define XL_LSTAT                0x20
#define XL_LCLR                 0x24
#define XL_DWORD                0x28
#define XL_DBUSY                0x2C
#define XL_PEND                 0x30
#define XL_ARM                  0x34
#define XL_TICK                 0x38
#define XL_LCTRL                0x3C
#define XLINK_ID_STAGE2         0x58524D32u     /* 'XRM2' */
#define XCFG_LOCK               (1u << 16)      /* SRAM image lock: MCU writes below SRAM byte 0x10000 dropped */

/* LSTAT[7:0] = {sbrq, sres, armed, busy, late, AI off, restart, send pending}; [15:8] late count; [31:16] posts */
#define LS_SEND                 0x01u
#define LS_RESTART              0x02u
#define LS_AIOFF                0x04u
#define LS_LATE                 0x08u
#define LS_BUSY                 0x10u
#define LS_ARMED                0x20u
#define LS_SRES                 0x40u
#define LS_SBRQ                 0x80u

/* fpgio ctrl read = {16'd0, mbx_irq, sbrq, sres, busy, late, AI off, restart, send, ctrl[7:0]} */
#define CT_MDRST                (1u << 3)
#define CT_SEND                 (1u << 8)
#define CT_RESTART              (1u << 9)
#define CT_AIOFF                (1u << 10)
#define CT_SRES                 (1u << 13)
#define CT_SBRQ                 (1u << 14)

#define MTIME_LO_ADDR           0xFFFFFF90u
#define MTIME_HI_ADDR           0xFFFFFF94u
#define MTIMECMP_LO_ADDR        0xFFFFFF98u
#define MTIMECMP_HI_ADDR        0xFFFFFF9Cu

/* ------------------------------------------------------------------ R-SFX feeder (the constants are estimates) */
#if FW_S1
#include "clock.h"
#define BUDDY_FEED_PERIOD       CLK_FEED        /* FW_S1: the same grid in time, 133.5
                                                   us at the build clock (clock.h) */
#else
#define BUDDY_FEED_PERIOD       7168u           /* grid period, MCU cycles (24 kHz consumes 3.20 samples per period) */
#endif
#define BUDDY_FEED_JITTER       400u            /* tick lateness allowed for in k (trap entry, longest bus access) */
#define BUDDY_FEED_K_UNKNOWN    5u              /* rate not known: priced as 24 kHz, the fastest rate in the bank */
#define BUDDY_FEED_CATCHUP      6u              /* a tick late by m whole periods pushes k * (1 + m), m <= 6 */
#define BUDDY_FEED_KMAX         48u             /* pushes per channel in one tick at most */
#define BUDDY_FEED_VU_TOPUP     3u              /* rounds pushed right before a VU row (a row blocks for 6-15k) */
#define BUDDY_FEED_RESCAN       65536u          /* re-check channels that were full (a full FIFO lasts >= 573k) */
#define BUDDY_RATE_SLOTS        256u            /* rate hash in the SRAM scratch (open addressing, 8 B an entry) */

/* ------------------------------------------------------------------ R-VU */
#if FW_S1
#define BUDDY_MS_CYCLES         CLK_MS_CYCLES   /* FW_S1: 1 ms at the build clock
                                                   (clock.h; the ms counter is retired) */
#else
#define BUDDY_MS_CYCLES         53693u          /* fpgio.sv: ctr_c counts 0..CLK_FREQ/1000-1 = 53,693 clocks a ms */
#endif
#define BUDDY_VU_POLL           512u            /* poll spacing while the ms phase is not yet known */
#define BUDDY_VU_CAL_MAX        1024u           /* phase window narrower than this = calibrated */

/* ------------------------------------------------------------------ slices of boot-time work, per main-loop pass */
#define BUDDY_SLICE_WORDS       16u             /* restore / copy: words per slice (~300-500 cycles) */
#define BUDDY_SLICE_CRC_BYTES   16u
#define BUDDY_SLICE_RATE        2u              /* SFX table entries per slice */

/* ------------------------------------------------------------------ layout placeholders */
/* SRAM map (the 0.2.6 research design's): image 0x00000-0x0FFFF, PRG tables 0x10000, scratch 0x18000, Word RAM mirror
   0x20000 (direct window: 68000 $600000 + o -> SRAM byte 0x20000 + o). */
#define BUDDY_IMG_ADDR          (BUD_SRAM_BASE + 0x00000u)
#define BUDDY_SCRATCH_ADDR      (BUD_SRAM_BASE + 0x18000u)
#define BUDDY_MIRROR_ADDR       (BUD_SRAM_BASE + 0x20000u)
/* WRAM window the PBUD fast section may be copied into (checked); the firmware's .data/.bss end at
   __crt0_bss_end and its stack grows down from the top of the 32 KB WRAM. */
#define BUDDY_WRAM_CODE_HI      0x80007000u     /* leaves 4 KB of stack (the 0.2.6 cart model's worst firmware stack +
                                                   the brain frames + one trap frame + a command handler) */

/* PBUD header (written by the research design's pack_buddy.py, outside this tree), little-endian, at BUDDY_IMG_ADDR */
typedef struct {
    uint32_t magic;             /* 'PBUD' 0x44554250 */
    uint16_t version;           /* 1 */
    uint16_t flags;
    uint32_t length;            /* payload bytes (after this 32-byte header) */
    uint32_t crc32;             /* IEEE CRC-32 of the payload */
    uint32_t entry_off;         /* payload offset of the entry table below */
    uint32_t fast_lma;          /* payload offset of the section copied into WRAM */
    uint32_t fast_vma;          /* its WRAM address */
    uint32_t fast_len;          /* bytes (0 = nothing to copy) */
} BudPbudHdr;
#define PBUD_MAGIC              0x44554250u

/* Entry table (ABI v1, a placeholder until the layout is fixed). Addresses are MCU addresses. */
typedef struct {
    uint32_t magic;             /* 'PBE1' 0x31454250 */
    uint32_t h2;                /* ENTRY_h2: one AI call ($3C10) + the counter; RV ABI, uses tp, no args */
    uint32_t h1;                /* ENTRY_h1: the word, zero-extended in a0 (runs the restart if the flag is set) */
    uint32_t cnt_out;           /* counter block: +0 c_hat, +4 D_WORD, +8 D_BUSY (out), +12 Wf = floor(W * 2^32) (in) */
    uint32_t flag;              /* the brain's "sub restarted" halfword ($16F7FE): bit 0 = 1 -> H1/H2 clear the AI block */
    uint32_t code_lo, code_hi;  /* the brain's code range (an exception there aborts the call and disables the buddy) */
    uint32_t nrestore;          /* the sub-CPU init's Word RAM pattern: records below */
    struct { uint32_t addr, bytes, fill16; } restore[4];
    /* (appended for the linked brain; zero in the stub / PBUD entries): copies done at every release after the restore,
       as halfwords (src, dst, bytes even) - the captured sub tables, SRAM PRG capture -> the brain's WRAM cap region -
       and the counter's T16 key, cleared at every aborted call and every release (a T16 build cut by an abort would
       otherwise leave a stale key over a half-written table) */
    uint32_t ncopy;
    struct { uint32_t src, dst, bytes; } copy[3];
    uint32_t t16_key;
} BudEntry;
#define PBE_MAGIC               0x31454250u

/* ------------------------------------------------------------------ diagnostics block (WRAM, read by a debugger / a
   measurement image; nothing reads it in play) */
typedef struct {
    uint32_t events, inits, sends, calls, published, discarded, aborted, ignored_halted, ignored_notready;
    uint32_t restarts, aioffs, releases, restores_done, rearms, dbusy_fixed, late_seen, arm_lost;
    uint32_t mbx_isr, mbx_cmds, ticks, pushes, catchups, vu_rows, vu_polls, rescans, exc_brain, exc_fw;
    uint32_t run_cycles_last, run_cycles_max, feed_mask_max, rate_hits, rate_miss;
    uint32_t cal_width, cal_samples, img_state, img_crc_calc, first_batches;
} BudStats;
extern BudStats bud_stats;

#endif /* BUDDY_H */
