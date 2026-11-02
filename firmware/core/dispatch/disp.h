/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/dispatch/disp.h - the dispatcher, status layer and job queue, as the cart chip has them.
 *
 * The cart chip is the STM32 microcontroller on the real cartridge. These parts were written by our team from our own
 * study of how the cart behaves, and do the same steps as the cart chip's (it runs the cart program; the addresses
 * below are the cart chip's, cited for every part):
 *   - mailbox entry / finish: mailbox_irq 0x0801AC3C (the app-ready test, the request bit, the finish
 *     $1FEA := 0 / $1FEC := 0 then $1FE6 |= 0x8000 at 0x0801AC64);
 *   - the two dispatchers: mailbox A 0x0801B712 (table 0x080259EC, entry clears $1FE6 0x8400), mailbox B
 *     0x0801BA4E (table 0x08025AC8, entry clears 0x8200); 55 entries each, index = word bits 8-13, bit 14 = the
 *     argument flag (mailbox B only), index > 0x36 -> the default refusal (A 0x0801BA3C, B 0x0801B6F0);
 *   - every table entry's gates in the cart chip's order, its refusal code and its status writes; refusals set $1FE6
 *     bit 10 (A) or bit 9 (B) and post a trace (event_post 0x08020B24, code | index-and-argument << 8);
 *   - the status helper 0x08022C78 (shadows G+0xE / G+0x10, set or clear a mask, store the whole word; every
 *     caller wraps it in cpsid/cpsie): st_set() is the only writer of $1FE4 / $1FE6 (status.c);
 *   - the 16-slot job queue (G+0x12 write index, G+0x13 read index, 20-byte slots from G+0x14) and the main
 *     loop's job step 0x0801A3AC-0x0801A608 (one job, then the read index and $1FE6 bit 14 := queue not empty);
 *   - C6 (0x0801B1FA, one-shot on the mixer flag), 81 (0x0801AFC4), 82 (0x0801B6DC), 84 (0x0801B69E),
 *     85 (0x0801B680), the 9494 head (0x0801AE88).
 * Mailbox B is RAMDP $1FEA and mailbox A is RAMDP $1FEC (RAMDP = the cart RAM that both the 68000 and the MCU see);
 * commands are named by their hex bytes, and G is the cart chip's global block. What the effect bodies do is not here:
 * the first version of this firmware ran the 0.2.6 bodies (interim/s1) through disp_bodies.h; the cart chip's own
 * bodies replace them one subsystem at a time. FW_S5 (board/board.h) builds the full firmware on MCU interface
 * v1.3; FW_MW builds the MegaWire code (core/mw).
 *
 * Gates that the first version left for later steps (each fragment says where): the sprite state (the AD sprite index:
 * stage 2, the sprite engine; the AF frame-open gate is here), the MegaWire byte and send flag (stage 3, the MegaWire
 * code), the song / SFX tables (8C/8E track range and null slot, D1 id range: stage 5, the song engine), 83's
 * frame-period windows (stage 3). The C6-done flags (mixer, sequencer, SFX engine), the sprite engine flag, the open
 * frame and the multiplex parity are dispatcher state and are here. docs: core/dispatch/README.md. */
#ifndef CORE_DISP_H
#define CORE_DISP_H

#include <stdint.h>
#include "board.h"

/* ---- the status helper (chip 0x08022C78): r0 = set (1) / clear (0), r1 = register, r2 = mask -------------- */
#define ST_FE4                  2u      /* r1 = 2: $1FE4 control word, shadow G+0xE */
#define ST_FE6                  3u      /* r1 = 3: $1FE6 status, shadow G+0x10 */
void     st_set(uint32_t on, uint32_t reg, uint16_t mask);   /* interrupts off inside (the callers' cpsid/cpsie) */
uint16_t st_shadow(uint32_t reg);                           /* the shadow word (what the MCU last stored) */
/* app init's direct stores (0x0801FA1C-0x0801FA2E): the shadows first, then each register from its shadow */
void     st_init_words(uint16_t fe6, uint16_t fe4);
void     st_store(uint32_t reg);
/* 85 and the fatal paths store $1FE4 without the helper (0x0801B68E): register only, shadow unchanged */
void     st_raw_fe4(uint16_t v);

/* ---- job slots (chip G+0x14 + 20 * slot) --------------------------------------------------------------------- */
enum {
    JOB_UNPACK_1 = 1,           /* types 1-4 share the unpacker 0x0801A3E2 */
    JOB_UNPACK_8C = 2,          /* 8C: the BGM module, then the module start */
    JOB_UNPACK_DA = 3,          /* DA (modes 2 and 7 through a job): then rev16 */
    JOB_UNPACK_F4 = 4,          /* F4: the scaling source */
    JOB_EEP_READ = 5,           /* DF */
    JOB_EEP_READ_MW = 6,        /* MegaWire init's EEPROM read (core/mw) */
    JOB_EEP_WRITE = 7,          /* E0 */
    JOB_SCALE_SAVE = 8,         /* F4's second job */
    JOB_RESCALE = 9,            /* F5 */
    JOB_RESTORE = 10,           /* B6 */
    JOB_SETUP = 11,             /* C6 */
    JOB_SETUP_MW = 12           /* app init with $1FE6 bit 12: setup + the MegaWire screen (unreachable on ours) */
};

typedef struct {                /* 20 bytes, the chip's slot layout (+0x14..+0x27) with ours in its padding */
    uint8_t  fail_en;           /* +0x14: a failure sets $1FE6 bit 8 */
    uint8_t  type;              /* +0x15 */
    uint8_t  b16;               /* +0x16: E0 slot */
    uint8_t  s1_mode;           /* (ours, the cart chip's padding) DA mode, for the interim/s1 body */
    uint32_t p18;               /* +0x18: destination; ours an offset (DA: the args[0] word; DF: RAMDP address) */
    uint8_t  b1c;               /* +0x1C: DF slot */
    uint8_t  s1_lo;             /* (ours) the posted low byte, for the FW_S5 = 0 body */
    uint8_t  s1_hi;             /* (ours) the post's high byte (0: mailbox A), for the FW_S5 = 0 body (0.2.6 per byte) */
    uint8_t  s1_pad;
    uint32_t p20;               /* +0x20: source; ours an offset (DA / F4: ROM byte offset; E0: RAMDP address) */
    uint32_t p24;               /* +0x24: EEPROM key */
} disp_job_t;

/* ---- the chip's global block G (0x20006F2C) and the flags the gates read ------------------------------------ */
typedef struct {
    uint8_t  app_ready;         /* G+0x08: mailboxes served (app init end) */
    uint8_t  f81[4];            /* G+0x09..0x0C: 81 bits 1-4 (debug counters, Boom Box feed, MegaWire task, watchdog
                                   may reset the MCU) */
    uint8_t  q_wr, q_rd;        /* G+0x12, G+0x13: job queue indices (low 4 bits = slot) */
    disp_job_t q[16];           /* G+0x14 */
    uint32_t c6_longs[8];       /* G+0x154: C6's eight argument longs */
    uint16_t g174, g176;        /* G+0x174 / +0x176: 83's frame period (app init clears them) */
    uint16_t g178;              /* G+0x178 := 0x10 at app init */
    uint32_t g17c;              /* G+0x17C: 83's SysTick latch, 0 at app init */
    uint32_t handoff[4];        /* G+0x180..0x18F: the bootloader hand-off block (docs/BOOT_SPEC.md section 3) */
    uint16_t wd_arm;            /* G+0x190: the watchdog count (app init and 81 := 1, 9494 := 2 if not 0, 84 / A858 := 0;
                                   the TIM7 tick counts it above 1 and trips past 40: core/wdog) */
    uint16_t wd_count;          /* G+0x192: a second count (app init := 1; 9494 / 84 / A858 := 0; counted above 1, trips
                                   past 100); nothing raises it above 1, so it is inert (core/wdog) */
    uint16_t g194;              /* G+0x194: the heartbeat count, := 1 at app start (counted above 1: no effect) */
    uint16_t trace_cnt[16];     /* G+0x196: event_post's counters, one per code 0-15 (cleared at app init; 81 bit 1
                                   copies them to RAMDP $1B00 every main-loop pass: FW_S5, test
                                   build 5 on, disp_s5_pass) */
    /* flags outside G that the gates read */
    uint8_t  mixer;             /* the C6 one-shot (audio init done) */
    uint8_t  seq_ready;         /* the sequencer (audio init) */
    uint8_t  sfx_ready;         /* the SFX engine (audio init) */
    uint8_t  mw_ready;          /* 0x20006D70: the MegaWire byte (MegaWire init; its gates are in the MegaWire code) */
    uint8_t  eng_ready;         /* 0x2000FB1C + 0x400: the sprite engine (sprite init in job 11) */
    uint8_t  frame_open;        /* 0x2000FB1C + 0x401: AE opened a frame; AF without it only finishes */
    uint8_t  af_parity;         /* 0x2000FB1C + 0x403: +1 at every AE (0x08018FC2-0x08018FCA), accepted B0
                                   (0x08019414-0x0801941C) and the first C6's sprite init (0x08019740-0x08019748); bit 0 =
                                   the multiplex parity AF's frame end reads (0x08019228, 0x080192CA) */
    /* the scaling state (0x2001345C) */
    uint16_t sc_session;        /* +0x0: an F4 source is loaded (job 8 := 1, B6 := 0) */
    uint16_t sc_args[4];        /* +0x2..+0x8: F5's four arguments */
    uint16_t sc_pending;        /* +0xA: an F5 rescale is queued */
    uint16_t sc_saved;          /* +0xC: RAMDP $0200-$09FF is saved (job 8, core/zoom body) */
    /* ours: the post being dispatched (the FW_S5 = 0 bodies keep 0.2.6's per-byte behaviour with it, disp_bodies.h) */
    uint16_t cur_word;          /* the word as posted ($1FEA for B, $1FEC for A) */
    uint8_t  cur_mbx;           /* MBX_B / MBX_A */
#if FW_S5
    uint16_t cur_seq;           /* FW_S5: its arrival number (SEQLAT, docs/MCU_INTERFACE.md v1.3 3.10.5) */
    uint32_t cur_stamp;         /* FW_S5: TIMER at its arrival (STAMP_B / STAMP_A) */
#endif
    /* ours: the C6 hold (docs/ALLOWLIST.md, row B34; jobs.c c6_hold): the C600 post's RTL stamp and the VS count read
       in its L1 (the level-1 interrupt handler, core/sched) */
    uint32_t c6_t;
    uint16_t c6_v;
    /* ours: TEST counters */
    uint32_t refusals, last_trace, jobs_run, jobs_failed;
} disp_state_t;
extern disp_state_t disp_g;
/* TEST: the last C6 hold (jobs.c): bits 7-0 the case (1, or 2 when the game's first read fell between a VBlank start
   and its VS start, 3 when the job started after the case check's deadline), 15-8 the end (1 waited, 2 our set-up
   already past the release, 3 the guard), 31-16 the VS starts counted when the set-up ended */
extern uint32_t c6_hold_test;

/* ---- app start / app init (core/boot/appinit.c) and the dispatcher's own init ---------------------------------- */
void disp_reset(void);                          /* app start 0x0801FAE4's stores into G and the flags */

/* ---- the job queue (jobs.c) ---------------------------------------------------------------------------------- */
uint32_t    disp_queue_full(uint32_t free_needed);      /* the chip's ((wr + n) ^ rd) & 0xF == 0 test */
disp_job_t *disp_job_slot(uint32_t ahead);              /* the slot at (wr + ahead) & 0xF */
void        disp_job_commit(uint32_t n);                /* wr += n (L1, interrupts off) */

/* ---- event_post 0x08020B24 (event.c): a code with bits 31-30 clear and a low byte <= 0xF counts in
   trace_cnt[code & 0xFF]; a nonzero third argument is fatal: fatal_halt() never returns ---------------------- */
void chip_trace(uint32_t code, uint32_t a, uint32_t b);

/* ---- hooks that other modules define (weak defaults in disp_stubs.c) ------------------------------------------ */
/* event_post's fatal half (0x08020B56-0x08020C7C), in core/trace/fatal.c: the LED code, the "WE SUX" poll of $1FEA,
   the MCU reset (ours: brd_full_reset, docs/ALLOWLIST.md, row B17). The weak default halts with interrupts off. */
void fatal_halt(uint32_t code, uint32_t a, uint32_t b) __attribute__((noreturn));
/* the song tick behind the 9494 head; nonzero = slices pending (L2b runs them, the finish waits for
   disp_tick_tail). The empty default = 0: the tick does nothing and L1 finishes inline. */
uint32_t audio_tick_begin(uint32_t stamp);
#define EEP_KEY                 0x8C543FC4u     /* the save scramble key the chip stores in DF / E0 jobs (+0x24) */
#if FW_S5
/* test build S3a on: 83's frame-period check (disp.c f_83, the cart chip's 0x080209B4): n = 0 stamps, n > 0 measures; 1
   = accepted.
   Outside f_83 only tests/equiv/f83lock.py calls it (by its symbol, and compares it with the cart chip's 0x080209B4). */
uint32_t disp_83_check(uint32_t n);
#endif

#endif
