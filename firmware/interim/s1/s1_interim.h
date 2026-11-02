/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* the interim layer of the new firmware: the 0.2.6 bodies re-hosted under the cart chip's command
 * map (core/dispatch/disp_bodies.h), the boot of the 0.2.6 modules, and the few board hooks only the interim code
 * needs (the FW_S5 build leaves the album path out). The cart FPGA's sprite decoder is the RTL's (MCU interface v1.2). */
#ifndef S1_INTERIM_H
#define S1_INTERIM_H

#include <stdint.h>

/* the board boot calls this after the boot page (board/pocket/s1_board.c brd_boot): ppmio onto the board's memories,
   the 0.2.6 sprite-engine init, the album (mdp_init, bounded under FW_S1: docs/BOOT_SPEC.md, row BOOT-02), the volumes
   at 0xFF */
void s1_interim_boot(void);

/* ---- board hooks for the interim code (each board defines them) ---------------------------------------------- */
#define S1_VOL_SFX              0u
#define S1_VOL_BGM              1u
void  s1_board_vol(uint32_t which, uint8_t v);  /* FPGAIO slot 3 VOL_SFX / slot 4 VOL_BGM (ignored by v1.0 RTL) */
void *s1_board_sfx(void);                       /* the audio_sfx FIFO block (region 0x06, interim) */

/* ---- the Boom Box VU rows (moved from paprium.c; the timing runs on the board timer). The update runs on the timer
   wheel (wh_vu, interim/s1/audio_s1.c) at the row's due instant; start and stop re-arm it ------------------------- */
void     s1_vu_start(uint32_t mod_addr);        /* L3 (the 8C job): interrupts off inside */
void     s1_vu_stop(void);                      /* L1 (8D) */
uint32_t s1_vu_update(void);                    /* one row if it is due; nonzero while the rows run (L2a) */
uint32_t s1_vu_deadline(uint32_t *t);           /* nonzero while the rows run: *t = the board time the next is due */

/* ---- the interim audio on the scheduler's levels (interim/s1/audio_s1.c; host: no-ops, tests/s1) --------------- */
extern uint8_t s1_sfx_type[8];                  /* interim/s1/sfx_s1.c: the type byte a start programmed */
typedef struct {                                /* the SFX channels' feeder records (interim/s1/sfx_s1.c; 0.2.6's sfx.c
                                                   SfxChan, the same 10 words): the feeder (audio_s1.c) pushes from them */
    uint32_t age, ptr, size, step, step_num, decay, looped, ptr_base, size_base, flags;
} S1SfxChan;
extern S1SfxChan sfx_chan[8];
uint32_t s1_sfx_blk3(void);                     /* interim/s1/audio_s1.c: three SFX mix blocks (10 ms) in cycles, for
                                                   sfx_s1.c's block count (a clock figure: kept out of the code window) */
void s1_sfx_kick(void);                         /* L1, after a D1 body: a started channel's first batch */
void s1_vu_kick(void);                          /* after a VU start / stop: the next row on the wheel, or none */
typedef struct {
    uint32_t ticks, catchups, pushes, first_batches, vu_rows;
#if !PPM_RELEASE
    /* TEST, debug save version 6 (2026-10-19: B Jam heard no Blue Bar street music in a hardware test): the album's
       state, written by interim/album/mdp.c (its calls, and s1_album_poll at every debug-save write). RELEASE keeps the
       5-word layout. */
    uint32_t alb_res;       /* at the write: [15:0] the MD+ result word {current_track, 7'b0, playing} (the CDDA
                               fetch's track and whether it plays; paprium_mdp_adapter.sv), [31:16] the command word
                               the adapter last took */
    uint32_t alb_xl14;      /* at the write: XLINK 0x14, [15:0] CDDA underruns (saturating), [31:16] snoop overflows */
    uint32_t alb_xl18;      /* at the write: XLINK 0x18, [15:0] SRAM loader words lost, [31:16] CRAM ring writes lost */
    uint32_t alb_calls;     /* [15:0] the last play request's command word (0x11tt once, 0x12tt loop; 0 none since the
                               boot), [31:16] the last album call's (also 0x1300 stop, 0x15vv volume, 0x0000 the init);
                               bit 15 of a half (S1_ALB_OFF) = not written: the album was off (mdp_on 0) */
    uint32_t alb_play_f;    /* the last play request's frame: the VS count since the boot (taken by the first write
                               after it from the VSCNT the call read) */
    uint32_t alb_play_und;  /* the CDDA underruns at the first write after it (at most a write period later) */
    uint32_t alb_wait;      /* frames from the last play request while the result word's playing bit stayed 0: it
                               runs until a write sees playing (then it is how long the start took, within a write
                               period), a stop or the next request; bit 31 (S1_ALB_WAITING) = still waiting,
                               bit 30 (S1_ALB_STOPPED) = a stop ended the wait before the track played */
    uint32_t alb_wait_max;  /* the session's longest such wait, frames */
#endif
} s1_audio_stats_t;
extern s1_audio_stats_t s1_audio_stats;         /* TEST counters (the TEST telemetry stores them) */
#define S1_ALB_OFF              0x8000u
#define S1_ALB_WAITING          0x80000000u
#define S1_ALB_STOPPED          0x40000000u
void s1_album_poll(uint32_t frames);            /* TEST: the album's state now (board/pocket/dbgsave.c, every write, with
                                                   the VS count since the boot) */
/* TEST: the ordered audio-call log, one word per album / SFX entry call in call order: bits 31-24 the kind (as the
   host's tests/s1/s1_host_album.c: 1 sfx_play, 2 sfx_loop, 3 sfx_stop, 10 mdp_init, 11 mdp_play, 12 mdp_play_once,
   13 mdp_stop, 14 mdp_set_vol), 23-16 the argument, 15-0 the posts dispatched so far (L1 calls carry their own post;
   a job tail's calls carry a later count: the 8C job's mdp_play after the posts it overlapped). Since debug save
   version 7 (test build 4a, 2026-10-21): the last 128 calls (was 256), so the record has room for the sound-cache
   probe's block (board/pocket/dbgsave.h); a power of 2 (the ring index is n & (S1_AU_LOG - 1)) */
#define S1_AU_LOG               128u
typedef struct {
    uint32_t n;
    uint32_t e[S1_AU_LOG];
} s1_au_log_t;
extern s1_au_log_t s1_au_log;
void s1_au_note(uint32_t kind, uint32_t arg);

/* ---- TEST counters of the decoder's board half (the RTL decodes, since MCU interface v1.2) ----------------------- */
typedef struct {
    uint32_t da_direct, go_words_last;          /* DA06 / DA07 0x80 streams handed to the RTL; the last firmware GO */
    uint32_t dec_flushes, dec_entries, dec_list_max;   /* AF / B1 flushes, the blocks they pushed, the longest list */
} s1_interim_stats_t;
extern s1_interim_stats_t s1_interim_stats;

#endif
