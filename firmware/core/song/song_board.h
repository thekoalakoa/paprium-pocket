/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song_board.h - what the song engine needs from the board (core/ holds no board addresses).
 *
 * Views: the board fills song_views at boot (the Pocket: the wave bank and the SFX bank in CRAM, the Pocket's
 * cellular RAM; the module store, the ROM; the host harness: the cart chip's memories). Each view also has the BUS
 * ADDRESS the engine stores in a record for the logic to read (a wave voice's BASE, an SFX record's PTR, a BGM table
 * entry), as on the cart chip (the STM32 microcontroller on the real cartridge).
 * Hooks: the status helper ($1FE6 / $1FE4), the trace (event_post), the packet copy
 * to RAMDP $1800 (the cart chip's DMA routine; RAMDP is the cart RAM that both the 68000 and the MCU see),
 * the flush timer (the cart chip's TIM14 one-shot), the random source (its SysTick VAL), the 88 mode switch (its DAC
 * DMA and pins), the 8C job push, synth_begin / synth_end. The synth is our RTL sound engine; its registers are in
 * docs/MCU_INTERFACE.md v1.3 section 3.10.
 */
#ifndef SONG_BOARD_H
#define SONG_BOARD_H
#include <stdint.h>

typedef struct {
    const uint8_t  *wprog;      /* wave programs 256 x 16 */
    const uint8_t  *psgenv;     /* PSG presets 256 x 8 */
    const uint8_t  *sdir;       /* sample directory + bank */
    const uint8_t  *flash16;    /* cart flash, the 16-bit view: ROM byte p at p ^ 1 */
    const uint8_t  *flash8;     /* cart flash, the byte view */
    uint32_t        sdir_bus;   /* the bus addresses of sdir, flash16 and flash8 */
    uint32_t        flash16_bus;
    uint32_t        flash8_bus;
    volatile uint16_t *ramdp;   /* 68000 cart RAM $0000-$1FFF as halfwords */
    const volatile int16_t *dac_buf;   /* the logic's output buffer, left side (cart chip dac_buf_L; the
                                   Pocket: CRAM DACBUF_L, docs/MCU_INTERFACE.md v1.3 3.8, the synth writes it) */
    uint32_t        sfx_bus;   /* the SFX bank's first word in the 16-bit flash view, as a bus address (the
                                   SFX table's own address, sfx_table_init): an SFX record's pointer - this = its
                                   byte in CRAM SFXBANK (docs/MCU_INTERFACE.md v1.3 3.10.4), where the boot
                                   overlay of test build 4b (board/pocket/boot/c4b_ovl.c) copies the bank */
} song_views_t;
extern song_views_t song_v;

/* a module address (a BGM table entry, a byte-view bus address) as a pointer */
#define SONG_FLASH8(a)  (song_v.flash8 + ((uint32_t)(a) - song_v.flash8_bus))

/* status helper (set, reg, mask): reg 3 = $1FE6 (the cart chip's), set 1 = OR, 0 = AND NOT; trace (code, a, b) */
void     board_status(uint32_t set, uint32_t reg, uint32_t mask);
void     board_trace(uint32_t code, uint32_t a, uint32_t b);
/* the packet: words halfwords of src to RAMDP $1800 (the Z80 reads it ~3.0 ms after the 9494) */
int      board_packet_dma(const uint16_t *src, uint32_t words);
/* flush timer (the cart chip's TIM14 one-shot): n = 0 stops, n > 0 arms; the cart chip's fires at once, so the
   queue runs the flush in the tick's own item */
void     board_flush_timer(uint32_t n);
/* the cart chip's random source */
uint32_t board_rand_src(void);
/* 88: the cart chip's DAC DMA starts / stops and its DAC pins = the synth's CONFIG register on the Pocket (MODE
   2 YM / 1 DT, PAL, SEQ = the arrival of the item that runs the 88 configuration, docs/MCU_INTERFACE.md v1.3 3.10.2) */
void     board_dac_mode(uint32_t ym, uint32_t ntsc);
/* 8C: the job queue full (the cart chip's 16-slot queue, gate 5), and the unpack job's push (L2c; the $1FE6 bits
   the 68000 can see are the gate's own) */
uint32_t board_job_full(void);
void     board_job_8c(uint32_t src_bus, uint32_t track);
/* the synth's ordering contract (docs/MCU_INTERFACE.md v1.3 3.10.5): begin waits while a block runs (seq = the item's
   arrival, for the record); end writes DONE := done, the newest arrival of which everything up to it is served
   (song_oeq.c computes it: never an item's own number alone, never backwards) */
void     board_synth_begin(uint16_t seq);
void     board_synth_end(uint16_t done);
void     board_done_free(void);              /* test build 5's TEST: the next DONE store has no hold-off before it
                                                (L1's, a module start's, a C6 item's): core/sched/s5_glue.c counts
                                                it for the synth's TEST assertion A1 (weak no-op here for the
                                                host rigs) */
/* the logic's block count (docs/MCU_INTERFACE.md v1.3 STATUS [27:16], mod 4,096) for the lazy meter decay */
uint32_t board_blkcnt(void);
/* the tick's board side (docs/MCU_INTERFACE.md v1.3 3.10.1, 3.10.5, 21.3 items 4-5).
   board_frame_arm: the cart chip's frame_pending store: 1 in the 9494's sequencer half, 0 at the module start; the
   logic owns the flag (the cart chip's block interrupt clears it), so on the Pocket it is the synth's ARM register.
   board_frame_cnt: the blocks the logic has mixed in this frame (the synth's SCHED [7:0]),
   which the flush reads for the YM-DAC underrun (the Z80 packet build); read inside the tick's item, where no
   block runs.
   board_underrun: one more underrun in the cart chip's u16 that is also event_post's trace counter 11 (the one the
   main-loop pass copies to $1B00 word 11): the board counts it there (one shared u16, as the cart chip has it).
   board_trace_fold: the same word's DT half: the DT block mix (logic) counts every DT half it
   finds incomplete; the synth counts them in DIAG.INCOMPLETE and the board adds the new ones to counter 11 before
   anything reads it (the main-loop pass, which copies it to $1B00). Read only; in_item (the tick's flush, inside
   synth_begin / synth_end) also clears DIAG once a count is high, so the saturating counts never stick, and only
   when STATUS shows that no instant can be serviced before the clear (core/dispatch/disp.c: no count is lost).
   board_views_init: the views the tick needs (RAMDP, DACBUF_L), at boot (sched_init); C6 adds the rest. */
void     board_frame_arm(uint32_t pending);
uint32_t board_frame_cnt(void);
void     board_underrun(void);
void     board_trace_fold(uint32_t in_item);
void     board_views_init(void);
/* a critical section (interrupts off, nesting: the board's MIE-off section); the finish of a post the full
   queue held back, when the queue takes it (the dispatcher's mbx_done: $1FEA / $1FEC := 0, bit 15); the
   8C module of a track (the store decoded at C6, its busy time held to the cart chip's; NULL = none; the store's
   place: the SDRAM workspace, core/sched/s5_glue.c) */
uint32_t board_crit_enter(void);
void     board_crit_leave(uint32_t s);
void     board_post_finish(uint32_t mbox);
const uint8_t *board_module(uint32_t track);
/* C6 and the 8C pre-decode (core/song/song_c6.c; the board side in core/sched/s5_glue.c).
   board_module_len: the decoded length of the track's module in the store (0 = none).
   board_c6_views: C6's views (the flash byte and word views, the wave bank, the wave programs and PSG presets in the
   workspace) with the cart chip's bus addresses; board_c6_tab: the writable table (0 = the wave programs, 4,096 B;
   1 = the PSG presets, 2,048 B) C6 decodes into; board_dacbuf_zero: the C6 set-up's dac_buf memsets (both 1,920-entry
   rings); board_bank_ok: the wave bank is in place for the C6 stream the game names (the cart chip's
   bank decode; ours: test build 4b's first-boot unpack in board/pocket/boot, which ran at boot).
   The store writer (C6 only): begin (the magic cleared first), slot (the next module's place and the room left),
   put (the module's offset and length into the directory), end (the count, then the magic last, when ok). */
uint32_t board_module_len(uint32_t track);
void     board_c6_views(void);
uint8_t *board_c6_tab(uint32_t which);
void     board_dacbuf_zero(void);
uint32_t board_bank_ok(uint32_t stream);
void     board_store_begin(void);
uint8_t *board_store_slot(uint32_t *room);
void     board_store_put(uint32_t track, uint32_t len);
void     board_store_end(uint32_t ok);
/* the cart chip's main-loop pass after an item (song_run_one, inside its synth_begin / synth_end, so it reads the
   state the item left with no block between; skipped while a job is queued or running, as the cart chip's thread
   runs the job then: core/sched/s5_glue.c) */
void     board_item_pass(void);
/* the item's fields to the synth (docs/MCU_INTERFACE.md v1.3 3.10.3-3.10.5), at every item's end before its DONE */
void     board_synth_put(void);

/* the cart chip calls its status helper with interrupts off; the board's helper is atomic itself
   (core/dispatch/status.c st_set), so the engine calls it plainly from either level */
#define STATUS(set, reg, mask) board_status((set), (reg), (mask))

#endif
