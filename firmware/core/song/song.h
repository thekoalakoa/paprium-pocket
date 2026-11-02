/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song.h - the cart chip's song engine: the sequencer, the module commands, the voice back-ends, the Z80
 * packet, the masters and fades, SFX control, the Boom Box feed and the audio posts, on the ordered engine queue
 * (core/song/README.md). The cart chip is the STM32 microcontroller on the real cartridge. Written by our team:
 * we reverse engineered the STM32F4's commands as close as possible, with hardware verification.
 *
 * The state keeps the cart chip's layouts (asserted in song_tables.c): S (the sequencer's globals and 26 voice
 * records), the SFX record table, G (the audio globals), SFX (8 channels), the BGM table, the Z80 message queue and the
 * packet staging.
 *
 * Who owns what (the synth contract): the logic (our RTL synth) owns the wave voices' POS, LAST L/R, DECLICK and
 * envelope state / level / counter, the echo ring indexes, the SFX channels' PTR / POS / ID / filter state / DELAY, and
 * the block scheduler's G fields (BLKCNT, frame pending, the YM filter states, the halves and count). The firmware
 * writes some of them where the cart chip's engine does (note-on, program change, the 88 configuration) and reads
 * them only inside synth_begin / synth_end.
 */
#ifndef SONG_H
#define SONG_H
#include <stdint.h>
#include <stddef.h>
#include <string.h>

/* SONG_BUG: planted bugs for the negative controls of the lockstep harness and the test rigs only (never defined in an
   image that ships): 1 the wave step + 1, 2 the FM level message's cost, 3 the SFX tick count, 4 the PSG decay 2 at
   the release rate, 5 one meter block lost, 6 two queued items swapped, 7 the YM-DAC stream's second sample, 8 the
   random pan; (the queue, song_oeq.c / core/dispatch/jobs.c) 9 DONE := the finished item's own arrival number (the
   first version's rule: a post with no engine part after it, a refused B next to a 9494, is left behind), 10 retired
   (the first version's "DONE now" at a refused post's arrival with the queue idle: with L1 in arrival order every
   older arrival is served and finished then, so it is no longer a fault), 11 a full queue drops the post's engine
   part and finishes it instead of holding it back, 12 the 8C job
   leaves (bit 14) before its module-start item has run, 13 no DONE written at an item end (only at an L1 end with
   nothing waiting: DONE left behind); (the tick's board side) 14 the YM-DAC underrun counted in a word of its own (the
   first version's split: $1B00 word 11 never counts it), 15 the flush reads the frame's block count from the WRAM
   shadow instead of the synth (SCHED), 16 the $1880 stream read from DACBUF_R instead of DACBUF_L,
   17 the module start's frame_pending clear not sent to the synth (ARM), 18 the main-loop pass copies the counters
   without folding the DT half of counter 11 (DIAG.INCOMPLETE); (the DIAG clear, core/dispatch/disp.c
   board_trace_fold) 19 DIAG cleared without the STATUS test (the first rule: a count made between the read and the
   clear is lost), 20 the last DIAG read before the STATUS read (a count made between them is lost), 21 a put-off clear
   forgets the counts already folded (they are folded again); (C6 and the 8C pre-decode: song_c6.c,
   core/dispatch/jobs.c, song_oeq.c, core/sched/s5_glue.c) 22 the 8C job does not hold the cart chip's busy time (the
   module starts at once), 23 C6 leaves dac_buf as it was, 24 the main-loop pass runs while a job runs, 25 the 0x81
   decoder's mid-copy distance one short (core/song/unpack81.c), 26 a BGM table entry not rounded to even, 27 CONFIG's
   SEQ 0 instead of the arrival of the item that writes it, 28 the 0x80 decoder skips two stream bytes in a zero
   run; (the synth's fields and the main-loop pass)
   29 the windows not read back (core/sched/s5_mirror.c), 30 the SFX windows not written, 31 a voice's BASE
   converted with the SFX bank's offset, 32 no pass inside an item (song_oeq.c), 33 no pass after a block
   (core/sched/sched.c), 34 no pass at a job's tail (core/dispatch/jobs.c), 35 the pass runs while a job is queued
   or running (core/dispatch/disp.c: bit 3 and the feed then move inside an 8C's job, which the cart chip never does),
   36 no pass after a post that queued no item (core/sched/sched.c: a refusal's trace count misses $1B00), 37 the
   bracketed pass does not read STATUS again after its ENV_LEVEL reads (core/sched/s5_glue.c: a block during the reads
   gives a set that straddles it, where the pass must see a whole block or none); (test build 5's TEST counts) 38 a DONE
   store with no hold-off: the WBUSY it added not counted (core/sched/s5_glue.c: A1 would blame a legal DONE store), 39
   every item's stores excused from A1 (core/sched/s5_glue.c: a post's or a tick's store that meets a block passes; only
   the module starts + C6 items are excused) */
/* Test build 5 on, brain hygiene: the GCC register-restore epilogue of a few of our FW_S5 functions came out equal to a
   32-byte window of the CPU MATE brain (CPU MATE is the computer-controlled partner), which the release checks search
   every image without the brain for (an 8-word run of lw s* / addi sp / ret). SONG_FRAME_PAD16() gives such a function
   16 B of frame it never touches, so its save / restore offsets and its sp adjustment differ; the asm emits no
   instruction.
   Each use sits where its function already has its frame (no shrink-wrapped path gains a prologue). Measured per
   image: RELEASE's code words differ only in sp-relative immediates (the same instructions, the same cycles); TEST's
   s5_mirror_out also places one lui of its tail before its first two restores (the same three). RV32 FW_S5 builds
   only (FW_S5 = the full firmware, board/board.h): the host builds and the FW_S5 = 0 images are unchanged. */
#if defined(__riscv) && defined(FW_S5) && FW_S5
#define SONG_FRAME_PAD16()      do { uint32_t frame_pad_[4]; __asm__ volatile ("" : "=m" (frame_pad_)); } while (0)
#else
#define SONG_FRAME_PAD16()      do { } while (0)
#endif
#ifndef SONG_BUG
#define SONG_BUG 0
#endif

/* ---- voice record, 26 of them in S (the cart chip's field names) ---- */
typedef struct {
    uint32_t wlen;          /* wave sample length (end index) */
    uint32_t wpos;          /* wave position 24.8 (logic) */
    uint32_t wloop;         /* loop start (0xFFFFFFFF one-shot) */
    uint32_t wdata;         /* sample data, the logic's bus address */
    int16_t  last_l;        /* (logic) */
    int16_t  last_r;        /* (logic) */
    int16_t  declick;       /* (logic counts it down) */
    uint8_t  rate_khz;
    uint8_t  companded;
    uint16_t muted;
    uint16_t step;          /* wave step 8.8 */
    uint16_t env_state;
    int16_t  env_level;     /* envelope level (wave, logic) / FM and PSG meter (firmware) */
    uint16_t r78;
    uint16_t env_cnt;
    uint16_t r7c;
    uint16_t pitch;         /* 1/16 semitone */
    uint16_t note_timer;
    uint16_t pan;
    uint16_t level;
    uint16_t gain0;
    uint16_t gain1;
    uint16_t program;
    uint16_t sample;
    uint16_t env_ar;
    uint16_t env_hold;
    uint16_t env_dr;
    uint16_t env_sl;
    uint16_t env_st;
    uint16_t env_d2r;
    uint16_t env_rr;
    int16_t  wb;
    uint16_t fm_vol_sent;
    uint16_t fm_pan_sent;
    uint8_t  ls_rate;       /* level slide */
    uint8_t  ls_cnt;
    int16_t  ls_step;
    uint8_t  ps_rate;       /* pan slide */
    uint8_t  ps_cnt;
    int16_t  ps_step;       /* (0xFFF = random pan) */
    uint8_t  pi_rate;       /* pitch slide */
    uint8_t  pi_cnt;
    int16_t  pi_step;
    int16_t  arp_hi;
    int16_t  arp_lo;
    uint8_t  arp_restrike;
    uint8_t  arp_state;
    uint8_t  arp_cnt;
    uint8_t  arp_rate;
    int16_t  detune1;
    uint16_t rdet_n;
    uint16_t rdet_cnt;
    uint8_t  mode;
    uint8_t  mode_rate;
    int16_t  mode_param;
    uint16_t rc0;
    uint8_t  trill;
    uint8_t  mode_cnt;
    uint8_t  sax;
    uint8_t  boost;
    uint16_t rc6;
} song_voice;

/* ---- sequencer globals S + voices ---- */
typedef struct {
    uint32_t ready;
    uint16_t echo_on;
    int16_t  echo_gain;
    uint16_t r08, r0a;
    int16_t  transpose;
    int16_t  tempo_off;
    uint16_t crisis;
    uint16_t sax_flag;
    uint16_t flag2, flag3;
    uint16_t boost_state;
    uint16_t boost;
    uint16_t boost_target;
    uint16_t loading;
    uint16_t wait_flush;
    uint16_t playing;
    uint16_t track;
    uint16_t next_track;
    uint16_t lvl_target;
    uint16_t pan_target;
    uint16_t step;
    uint16_t stop_at_zero;
    uint16_t level;
    uint16_t pan;
    uint16_t gain0, gain1;
    uint16_t r38;
    uint16_t order;
    uint16_t row;
    uint16_t resume;
    uint16_t tick;
    uint16_t speed;
    uint16_t jump_order;
    uint16_t jump_row;
    uint16_t swing;
    uint16_t echo_wr;       /* (logic: the BGM echo ring index) */
    uint16_t echo_delay;
    uint16_t r4e;
    uint16_t loop;
    uint16_t r52, r54, r56;
    song_voice v[26];
} song_seq;

/* ---- audio globals G ---- */
typedef struct {
    uint32_t ready;
    uint8_t  busy;          /* the synth tick running */
    uint8_t  mode;          /* the synth tick's mode: 1 sequencer half, 2 flush half */
    uint16_t ymdac;
    uint16_t rate;          /* 0x3C NTSC / 0x32 PAL */
    uint16_t c9_x1;
    uint16_t samples;       /* HALF */
    uint16_t blocks;        /* NBLK */
    uint16_t blkcnt;        /* (logic: blocks mixed, 12 bits) */
    uint16_t r12, r14, r16;
    uint16_t pending;       /* (logic: frame pending; the tick sets it) */
    uint8_t  r1a, r1b;
    uint16_t frame;         /* 0..5 NTSC / 0..4 PAL */
    uint16_t q_last;
    uint16_t q_len;
    uint16_t q_cost;
    uint16_t q_budget;
    int16_t  filt0, filt1;  /* (logic: YM output filter states) */
    uint16_t psg_master;
    uint16_t wave_master;
    uint16_t sfx_master;
    uint16_t fm_master;
    uint16_t raw_pitch;
    uint16_t r34, r36, r38, r3a; /* (r36 / r38 / r3a: the logic's halves and count) */
    uint8_t  r3c, r3d;
    uint8_t  last_cfg;
    uint8_t  force_mono;
} song_g;

/* ---- SFX channel and SFX globals ---- */
typedef struct {
    uint32_t cur;           /* (logic) */
    uint32_t start;
    uint32_t pos;           /* (logic) */
    uint32_t len;
    uint16_t rate_type;
    uint16_t rate_mul;
    uint16_t id;            /* (the logic clears it at the end) */
    uint16_t starts;
    uint16_t lvl_target;
    uint16_t pan_target;
    uint16_t step;
    uint16_t stop;
    uint16_t level;
    uint16_t pan;
    uint16_t gain2;
    uint16_t gain3;
    uint8_t  neg;
    uint8_t  shift;
    uint16_t r2a;           /* (logic: filter state) */
    uint16_t pitch;         /* delay (logic counts it down) */
    uint16_t r2e;
    uint8_t  loops;
    uint8_t  loop_div;
    uint8_t  loop_cnt;
    uint8_t  r33;
} sfx_ch;

typedef struct {
    uint16_t ready;
    uint16_t echo_on;
    uint16_t echo_gain;
    uint16_t r06, r08;
    uint16_t lvl_target;
    uint16_t pan_target;
    uint16_t step;
    uint16_t r10;
    uint16_t level;
    uint16_t pan;
    uint16_t gain2, gain3;
    uint16_t r1a;           /* (logic: the SFX echo ring index) */
    uint16_t echo_delay;
    uint16_t frame;
    sfx_ch   ch[8];
} song_sfx;

/* SFX table: record 0 = header (count + 1 in byte 7), records 1..n = 8-byte entries */
typedef struct {
    uint32_t ptr;           /* the sample words, the logic's bus address */
    uint8_t  flags, l2, l1, l0;
} sfx_rec;

/* mailbox context: what the handler fragments share */
typedef struct {
    uint32_t mbox;          /* 1 = A ($1FEC), 2 = B ($1FEA) */
    uint32_t word;          /* B word & 0x3FFF, A word & 0x3F00 */
    uint32_t args;          /* bit 14 (B; A 0) */
    const uint16_t *a;      /* the argument words ($1E10..), as taken at the arrival */
} mbx_ctx;

extern song_seq    S;
extern song_g      G;
extern song_sfx    SFX;
extern sfx_rec     sfx_table[256];
extern uint32_t    bgm_table[64];          /* count + 63 module addresses */
extern uint8_t     z80_q_area[4 + 0x80];   /* 4 bytes below the queue (the coalesce rewrites at q - 4) */
#define Z80Q       (z80_q_area + 4)
extern uint16_t    z80_packet[0xE0];       /* header word, messages, stream at word 0x40 */
/* (the cart chip's underrun count is event_post's trace counter 11: the board counts it there,
   board_underrun / board_trace_fold) */
#if SONG_BUG == 14
extern uint32_t    song_bug14_underrun;    /* SONG_BUG 14: the first version's separate word */
#endif

/* the cart chip's two hand-typed tables (B Jam's decision of 2026-10-10; tools/leak_allow.json) and what follows the
   note table */
#define SONG_NOTE_N        108u
#define SONG_NOTE_TAIL_N   12u
extern const uint16_t chip_note_pitch[108];    /* the note pitches */
extern const uint16_t chip_fm_fnum[13];        /* the FM fnums */
extern uint8_t        song_note_tail[SONG_NOTE_TAIL_N];   /* the bytes after the note table, which the note lookup
                                                 can read: the boot reads them from the player's ROM (save_boot) */
extern uint32_t       song_note_far;           /* note reads past the tail read at boot (TEST telemetry) */

#include "song_board.h"

/* ---- the engine's routines ---- */
/* sequencer / commands */
void     synth_tick(void);
void     seq_tick(void);
void     row_parse(uint32_t v, const uint8_t *row);
int      fm_row_cost(uint32_t v, const uint8_t *row);
int      row_z80_cost(uint32_t v, const uint8_t *row);
uint32_t bgm_module_init(void);
void     music_fx_reset(int all);
void     module_command(uint32_t v, uint32_t cmd, uint32_t op, uint32_t pitch);
void     voice_tick_effects(uint32_t v);
void     program_change(uint32_t v, uint32_t prog);
void     voice_set_level(uint32_t v, uint32_t level);
void     voice_set_pan(uint32_t v, uint32_t pan);
void     note_on(uint32_t v, uint32_t pitch);
void     note_release_soft(uint32_t v);
void     note_off_hard(uint32_t v);
void     note_pitch_update(uint32_t v, uint32_t pitch);
uint32_t rand_systick(void);
/* voice back-ends and helpers */
void     wave_program_change(uint32_t v, uint32_t prog);
void     wave_note_on(uint32_t v, uint32_t pitch, int new_note);
void     wave_note_off(uint32_t v, int hard);
void     psg_program_change(uint32_t v, uint32_t prog);
void     psg_note_on(uint32_t v, uint32_t pitch, int new_note);
void     psg_note_off(uint32_t v, int hard);
void     psg_envelope_tick(void);
uint32_t note_freq(uint32_t p);
uint32_t fm_fnum(uint32_t p);
uint32_t psg_period(uint32_t p);
uint32_t mul_clamp(int a, int b, uint32_t c);
uint32_t mul2_clamp(int a, int b, int c, uint32_t d);
uint32_t pan_gain(uint32_t level, uint32_t pan, int side);
/* Z80 messages and packet */
void     fm_level_msg(uint32_t v);
void     psg_tone_msg(uint32_t v, uint32_t pitch);
void     fm_level_refresh(uint32_t v);
void     psg_volume_msg(void);
void     psg_volume_only(void);
void     fm_tl_msg(uint32_t ch, uint32_t op, uint32_t tl);
void     fm_program_msg(uint32_t v, uint32_t prog);
void     fm_keyoff_msg(uint32_t v, int hard);
void     fm_note_msg(uint32_t v, uint32_t pitch, int new_note);
int      z80_packet_build(void);
void     z80_packet_flush(void);
/* masters, SFX, Boom Box */
void     master_fade_tick(void);
uint32_t sfx_table_init(uint32_t addr);
uint32_t sfx_alloc_channel(uint32_t mask, int pick);
void     sfx_start(uint32_t mask, uint32_t id, uint32_t vol, uint32_t pan, uint32_t flags);
void     sfx_stop(uint32_t ch, uint32_t rel);
void     sfx_update(uint32_t ch, uint32_t vol, uint32_t pan, uint32_t step);
void     boombox_feed(void);
void     audio_config(uint32_t cfg);

/* ---- the audio posts: gates (L1, at the arrival) and bodies (L2b, in arrival order); song_posts.c ---- */
enum {
    SONG_OK = 0,            /* accepted: the body is queued */
    SONG_DONE = 1,          /* accepted, nothing for the engine (a null 8C slot, a refusal already made) */
};
uint32_t song_gate(mbx_ctx *c);             /* the fragment's gates in the cart chip's order: SONG_OK or SONG_DONE */
void     song_body(mbx_ctx *c);             /* the fragment's engine part */
void     song_refuse(mbx_ctx *c, uint32_t code);

/* ---- the ordered engine queue and the L1 / L2 split (song_oeq.c; core/song/README.md) -------------------------
 * L1 (the mailbox, interrupt level, core/sched l1_mei): song_l1_seen(n) for EVERY post it serves (n = its arrival
 * number, docs/MCU_INTERFACE.md v1.3 SEQLAT), then the dispatcher; an audio post's fragment and the 9494 call
 * song_arrive(), and the dispatcher finishes the post at once (or, when the queue is full, later: SONG_ARR_HELD); at
 * the end of the L1 entry song_l1_end(). L2b (the engine level, l2b_msi): song_run_one() runs the oldest item, between
 * board_synth_begin() and board_synth_end(DONE), and DONE never passes an arrival whose engine part is still waiting.
 * L2a (the urgent finish, wh_urgent): song_tick_due() / song_run_one() with interrupts off. L2c (the job level):
 * song_job_done() hands a ready module back as an item, so the module start runs in arrival order too, and the job
 * waits (song_job_waiting) until it has run. The main-loop pass is song_main_pass(): the cart chip runs it on every
 * main-loop iteration (whenever no interrupt is active and no job runs), so ours runs it after every item and after
 * every mixed block, and after every job (core/sched/sched.c, s5_glue.c), never while a job is queued. */
#define SONG_Q_N        8u      /* 8 slots (decided 2026-10-22), FZ8 strict; the game's own worst is 7 arrivals +
                                   the 8C's module-start item (measured in a census of the game's posts) */
#define SONG_ARGS_N     5u
enum { SQ_POST = 1, SQ_TICK = 2, SQ_JOB = 3, SQ_CALL = 4 };     /* SQ_JOB and SQ_CALL have no arrival */
typedef struct {
    uint16_t seq;               /* the arrival number (SQ_JOB: none) */
    uint8_t  kind;              /* SQ_POST / SQ_TICK / SQ_JOB */
    uint8_t  mbox;
    uint16_t word;              /* mbx_ctx.word */
    uint16_t args;              /* mbx_ctx.args */
    uint16_t a[SONG_ARGS_N];    /* $1E10.. at the arrival */
    uint16_t r;
    uint32_t stamp;             /* SQ_TICK: TIMER at its 9494 (STAMP_A): the urgent finish counts from it; SQ_CALL:
                                   fn's argument */
    const uint8_t *mod;         /* SQ_JOB: the ready module */
    void (*fn)(uint32_t);       /* SQ_CALL: a job's engine part (C6's audio init) */
} song_item;

/* song_arrive's answer to the dispatcher */
enum { SONG_ARR_DONE = 0,       /* nothing for the engine (refused, a null 8C slot): finish the post now */
       SONG_ARR_ITEM = 1,       /* its engine part is queued: finish the post now */
       SONG_ARR_HELD = 2 };     /* the queue is full: do NOT finish it; the queue takes it (its gates then) at the
                                   next item end and finishes it through board_post_finish() */
void     song_oeq_init(uint16_t arr);       /* boot: nothing pending, DONE := ARR (the board's arrival count) */
void     song_l1_seen(uint16_t seq);        /* L1: an arrival it serves (any post) */
uint32_t song_arrive(uint32_t mbox, uint32_t word, const volatile uint16_t *args, uint16_t seq, uint32_t stamp);
uint32_t song_l1_end(void);                 /* L1, at its end: nothing waiting -> DONE := the newest arrival served;
                                               nonzero = items wait (L2b must run) */
uint32_t song_work(void);                   /* nonzero: an item waits (L2b's look) */
uint32_t song_run_one(void);                /* L2b (MTI masked) or the urgent finish (MIE off): the oldest item, then
                                               DONE; nonzero = ran one */
uint32_t song_run(void);                    /* every waiting item (host harnesses) */
uint32_t song_tick_due(uint32_t *stamp);    /* a tick item waits (queued, not running, or held back): the oldest
                                               one's 9494 stamp */
uint32_t song_job_done(const uint8_t *mod); /* L2c: the module start as an item (no arrival); 0 = the queue is full */
uint32_t song_call(void (*fn)(uint32_t), uint32_t arg);   /* L2c: fn(arg) as an item (no arrival); 0 = full
                                               (test build 5's TEST: A1 excuses its stores, and only C6's two items are
                                               named for that: another caller needs a decision first) */
uint32_t song_job_waiting(void);            /* an SQ_JOB / SQ_CALL item that has not finished */
int      song_job_module(uint32_t report);  /* the job kind 2 tail: the module start */
extern volatile uint8_t song_pass_hold;     /* a job runs: the main-loop pass waits (the cart chip's pass is its
                                               thread, which the job holds) */
void     song_main_pass(const uint16_t *dbg, uint32_t boombox_on);
uint32_t song_q_depth(void);
uint16_t song_done(void);                   /* the DONE last written (TEST, rigs) */
extern uint32_t song_q_over;                /* posts held back by a full queue (TEST; never, by our estimate) */
extern uint32_t song_q_max;                 /* the deepest the queue has been, the running item included */
void     song_meters(uint32_t blk);         /* the lazy FM / PSG meter decay up to block count blk */
extern uint16_t song_meter_blk;             /* the block count the meters are decayed to */
extern const uint8_t *song_mod;             /* the module the sequencer plays */

/* tick halves (the 9494's EXTI part and its TIM14 flush; the queue runs both in one item) */
void     song_tick_head(void);
void     song_tick_flush(void);

/* ---- C6 and the 8C pre-decode (song_c6.c). The C6 setup job (core/dispatch/jobs.c, L2c) runs song_c6_begin,
   song_c6_init as an item, song_c6_banks (then our module pre-decode into the store) and song_c6_ready as an item.
   The 0x81 decoder is our own (core/song/unpack81.c). We decode every module once, at C6, so our 8C job only waits
   for as long as the cart chip's decode would take (see core/dispatch/jobs.c and CLK_JOB8C in board/clock.h). */
void     song_c6_begin(void);
void     song_c6_init(uint32_t sfx_addr);
uint32_t song_c6_banks(const uint32_t longs[8]);    /* 2 = every gate passed, 1 = the BGM table only, 0 = neither */
void     song_c6_ready(uint32_t level);
uint32_t song_bgm_entry(uint32_t addr, uint32_t i);  /* the BGM table's entry i as the chip's bank load builds it */
uint32_t song_unpack80(const uint8_t *src, uint8_t *dst);       /* bytes written */
/* The 0x81 decoder is core/song/unpack81.c (unpack81.h describes its three entries). With UNPACK81_SONG_NAMES set to 1
   that file defines its whole-stream entry and its stop-at-end entry under the two names declared here,
   song_unpack81 and song_unpack81_to; unpack81.c includes this header before its own, so it sees the setting below. */
#ifndef UNPACK81_SONG_NAMES
#define UNPACK81_SONG_NAMES 1
#endif
uint32_t song_unpack81(const uint8_t *src, uint8_t *dst);       /* bytes written */
uint32_t song_unpack80_to(const uint8_t *src, uint8_t *dst, const uint8_t *end);   /* the same, nothing written at or */
uint32_t song_unpack81_to(const uint8_t *src, uint8_t *dst, const uint8_t *end);   /* past end (F4's job) */
uint32_t song_store_modules(uint32_t bgm_addr);     /* ours: the 8C modules decoded once; the count stored */
#if defined(SONG_TEST_HOOKS)
extern void (*song_test_pre)(uint32_t kind, uint32_t seq);     /* host harness: an item is about to start (before
                                                                  synth_begin: the synth's fields of its instant) */
extern void (*song_test_mid)(void);         /* host harness: called between the tick's halves */
extern void (*song_test_begin)(uint32_t kind, uint32_t seq);   /* host harness: an item starts (song_oeq.c) */
#endif

#endif
