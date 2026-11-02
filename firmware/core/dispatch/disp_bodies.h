/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/dispatch/disp_bodies.h - the effect bodies the dispatcher calls. In the first version of this firmware they
 * were the 0.2.6 bodies, re-hosted in interim/s1; the later steps replace them one by one with bodies that behave as
 * the cart chip's do (the cart chip is the STM32 microcontroller on the real cartridge).
 *
 * The dispatcher (disp.c) owns everything the cart chip's dispatcher does: the gates, refusals, the status writes, the
 * job queue and the cart-register sequences (window, decoder queue, stream control, $1FE4 bit 8). A body does only
 * what the cart chip's engine routine (sprite engine, unpacker, synth, saves) would do, as 0.2.6 did it. Bodies that
 * end a stream do the board part (SPTR then GO) themselves: that is the FPGA's half, which our board stands in for.
 *
 * 0.2.6 dispatched on the whole high byte (cmp_ptr[256]), so the cart chip's two forms of one command (bit 14 =
 * arguments, e.g. 95 / D5, 89 / C9, F0 / B0) were separate entries there, most of them "unknown" (no effect), and
 * 0.2.6 never served mailbox A. The FW_S5 = 0 bodies keep that per-byte behaviour (disp_g.cur_word / cur_mbx, a job's
 * s1_hi); the gates, refusals and status writes are the cart chip's for every form (they are the dispatcher's).
 *
 * Context: "L1" bodies run inside the mailbox handler (L1, the level-1 interrupt) with interrupts off; "job" bodies
 * run in L2c (core/sched; earlier versions ran them in the thread) with everything open.
 *
 * The cart's FPGA decodes the sprite blocks the cart chip lists (AF / B1's load list, F2's block) and DA06 / DA07's
 * 0x80 streams by itself; the cart chip writes the queue ($1FF4 / $1FF6), starts it ($1FF2 = 0x8000) and replies at
 * once, never waiting for the decode. Ours does the same since MCU interface v1.2 (B Jam's decision of 2026-10-15:
 * preservation): the dispatcher writes the cart chip's queue sequence, the RTL decodes into the workspace and GOes,
 * and every one of these posts finishes at once. The bodies give the dispatcher the frame's load list (the sprite
 * engine in core/sprite) and do the board's half: the decoder's output base before each START (brd_dec_base: 0.2.6's
 * layout, so the window serves the same words from the same workspace bytes). */
#ifndef CORE_DISP_BODIES_H
#define CORE_DISP_BODIES_H

#include <stdint.h>
#include "disp.h"
#include "tdiag.h"

/* ---- L1: audio (the interim album / SFX feeder until the song engine) ----------------------------------------- */
void body_88(uint8_t lo);                       /* audio config: 0.2.6 cmd_88 ($1800-$19FF) */
void body_c9(uint8_t lo);                       /* BGM volume */
void body_ca(uint8_t lo);                       /* SFX volume */
void body_8d(uint8_t lo);                       /* BGM stop / fade */
void body_d1(uint8_t lo);                       /* SFX play */
void body_d2(uint8_t lo);                       /* SFX stop */
void body_d3(uint8_t lo);                       /* SFX loop */
void body_d5(uint8_t lo);                       /* 0.2.6: stop the looped channels */

/* ---- L1: sprites (the sprite engine in core/sprite; the dispatcher keeps the gates and the registers) ----------- */
void     body_ad(uint8_t lo);                   /* compose object slot lo */
void     body_ae(void);                         /* frame start */
void     body_af(uint8_t mode, uint8_t parity);  /* frame end (the cart chip's close 0x080190B8: mode = lo & 3,
                                                   parity = H+$403); the flush came first; only for an open frame */
#if !PPM_RELEASE && !TDIAG_LEAN
void     body_af_replied(void);                 /* TEST: after that AF's reply, still in its L1: the SAT
                                                   snapshot's AF bookkeeping (the AF count, the latch of the $1F18
                                                   body_af read before the reply, the request; none in RELEASE) */
#endif
void     body_b0(void);                         /* sprite engine reset */
void     body_b1(void);                         /* B1: the flush's count := 0 (B1 only flushes) */
void     body_ec(uint16_t slots);               /* VRAM slot count */
uint32_t body_block_addr(uint16_t block);       /* F2: the block's ROM byte offset (the cart chip's table read) */
uint32_t body_load_list(const uint32_t **list); /* the flush (AF, B1): the blocks loaded since the last AE / B0 / flush,
                                                   as ROM byte offsets in load order (at most 15: the cart chip's cap) */
void     body_dec_scratch(void);                /* the board, before the flush's or F2's START: the decoder's output base
                                                   = 0.2.6's block scratch (brd_dec_base) */

/* ---- L1: streams (the board's half) --------------------------------------------------------------------------- */
void body_db(uint16_t a0, uint16_t a1, uint16_t a2, uint8_t mode);  /* DB06 / DB03: SPTR then GO */
void body_da_direct(uint32_t src, uint16_t dst, uint8_t mode);      /* DA06 / DA07 type 0x80, before its START: the
                                                                       decoder's output base = dst (brd_dec_base) */

/* ---- L1: MegaWire (0.2.6 until the MegaWire code) --------------------------------------------------------------- */
void body_e7(void);                             /* 0.2.6: "pretend data is in" */

/* ---- job bodies (thread). The unpack / save bodies return 0 on success or the cart chip's event code for the
   failure (the job step then sets $1FE6 bit 8 when the slot asks for it, and posts the code) --------------------- */
uint32_t job_unpack(const disp_job_t *j);       /* types 1-4: DA (mode in s1_mode), 8C (lo in s1_lo), F4; codes 4 (not
                                                   a 0x80-0x83 stream), 0x11 (0x80 / 0x81 empty), 0x12 (0x83), 0xD (8C) */
uint32_t job_eep_read(const disp_job_t *j);     /* type 5 (DF), type 6 (MegaWire init, core/mw); the result is not used */
uint32_t job_eep_write(const disp_job_t *j);    /* type 7 (E0): the FW_S5 = 0 body answers code 9 or 0; the FW_S5
                                                   one, as the cart chip's 0x0801A86C, 1 = written, 0 = not (the job
                                                   step makes the 0 its code 9: jobs.c) */
#if FW_S5
void     save_boot(void);                       /* test build S3a on: the cart's slot table from the player's ROM,
                                                   the one-time
                                                   0.2.x save import (interim/s1/bodies_s1.c; the 68000 held) */
#endif
void     job_scale_save(void);                  /* type 8: save RAMDP $0200-$09FF (0x08022CD0; core/zoom) */
void     job_scale_setup(void);                 /* type 8: the stamps := 0 (0x08022D34; core/zoom) */
void     job_rescale(const uint16_t args[4]);   /* type 9 (F5): the rescale and copy-out (0x08022D84, 0x08022D48) */
void     job_restore(void);                     /* type 10: restore RAMDP $0200-$09FF (0x08022D04; core/zoom) */
/* types 11/12: sprite, MegaWire and audio init; returns which parts came up (the job step sets the flags) */
#define SETUP_ENG               0x1u    /* sprite init 0x08019734: 0x2000FB1C + 0x400 := 1 (0x080197C2) */
#define SETUP_MW                0x2u    /* MegaWire init 0x080218FC: the MW byte := 1 (0x08021922) */
#define SETUP_SFX               0x4u    /* audio init: the SFX engine */
#define SETUP_SEQ               0x8u    /* audio init: the sequencer */
uint32_t job_setup(const uint32_t longs[8], uint32_t mw_screen);

#endif
