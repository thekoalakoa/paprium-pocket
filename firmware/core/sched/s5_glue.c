/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/sched/s5_glue.c - the song engine's board hooks (core/song/song_board.h) on the board interface. Built only by
 * the s5 variants (fwbuild.json: FW_S5, the full firmware, board/board.h); no FW_S5 = 0 image links it.
 *
 * The synth's ordering contract (docs/MCU_INTERFACE.md v1.3 3.10.5): synth_begin waits while the synth runs a block
 * or may start the next one (STATUS.BUSY = 0 seen: no block can start before DONE moves, since every newer instant
 * waits for a newer arrival), synth_end writes DONE; the block count for the lazy meters; the critical section.
 * The tick's board side (v1.3 3.10.1 / 3.10.5 / 21.3 items 4-5): the frame_pending writes to ARM, the frame's block
 * count from SCHED, the views (RAMDP, the cart RAM the 68000 sees; DACBUF_L in CRAM, the Pocket's cellular RAM, as the
 * $1880 stream's source), the packet copy; the module store's place: the SDRAM workspace from BRD_MODSTORE_OFF, a
 * directory that C6 writes and board_module reads.
 *   board_packet_dma  the cart chip's DMA of the packet staging to RAMDP $1800, as a copy (0xC5 words
 *                     NTSC YM-DAC at most: the messages + the $1880 stream);
 *   board_rand_src    the cart chip reads SysTick VAL; ours the board timer (a proposed allow-list row: random numbers
 *                     from our timer have the cart chip's spread but not its values); weak, so the lockstep harness
 *                     (which runs the cart chip's program and ours side by side) can replay the cart chip's values;
 *   board_module is weak: the host tests replace it.
 * The audio start and C6 (v1.3 3.5, 3.8, 3.10.1-3.10.2): the 88 configuration's DAC start / stop as the CONFIG
 * write (MODE, PAL, DTWIN 0 = the clamp of docs/ALLOWLIST.md row B41, SEQ = the arrival of the item that runs it:
 * the 88's, or C6's init item's DONE); C6's views (the flash byte and word views with the cart chip's bus addresses,
 * the wave bank in CRAM, the wave programs and PSG presets in the workspace at BRD_C6TAB_OFF); dac_buf cleared at C6;
 * the store writer and its directory with the modules' lengths (for the 8C job's busy time).
 * The synth's fields and the pass: synth_begin and board_synth_put carry the engine's fields from and to the synth
 * (core/sched/s5_mirror.c), the main-loop pass's two entries (board_item_pass in an item, board_pass_bracket from L2b;
 * core/sched/sched.h). */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "song.h"
#include "tdiag.h"

#if !FW_S5
#error "core/sched/s5_glue.c is the stage-5 firmware's (FW_S5)"
#endif

#define WEAK __attribute__((weak))
#if PPM_RELEASE || TDIAG_LEAN                  /* (the lean TEST image, test build S3a on: no assertions,
                                                  no pass counts) */
#define COUNT_S5(f)             ((void)0)
#define COUNT_T(f)              ((void)0)
#else
#define COUNT_S5(f)             (s5_pass_stats.f++)
#define COUNT_T(f)              (s5_test.f++)
#endif
s5_test_stats_t s5_test;                                   /* test build 5's TEST (sched.h): the synth assertions'
                                                              counts */
#if !PPM_RELEASE && !TDIAG_LEAN
static uint8_t s5_hold;                                    /* the running item holds the synth's blocks off (its
                                                              arrival is past DONE: v1.3 3.10.5); set by synth_begin */
static uint16_t s5_blk_begin;                              /* BLKCNT when that item began (an item with no hold) */
static uint8_t s5_wbusy_begin;                             /* DIAG.WBUSY when that item began */
static uint8_t s5_free_on;                                 /* board_done_free said: the next DONE store has no hold-off */
static uint8_t s5_free_w0;                                 /* DIAG.WBUSY just before that store */
#endif

static uint32_t synth_wait(void)
{
    uint32_t st;
    do
        st = brd_synth_status();
    while (st & BRD_SYNTH_BUSY);                           /* at most one block (~0.67 ms worst, estimated) */
    return st;
}

static uint16_t s5_item_seq;                               /* the running item's arrival (synth_begin's): CONFIG's SEQ */

/* the logic's fields of this instant into the engine's records (core/sched/s5_mirror.c) */
void board_synth_begin(uint16_t seq)
{
    uint32_t st = synth_wait();
    s5_item_seq = seq;
#if !PPM_RELEASE && !TDIAG_LEAN                         /* test build 5's TEST: A1's split (sched.h) */
    s5_hold = seq != song_done();                           /* an arrival past DONE: every newer instant waits; an
                                                               item with no arrival (seq = DONE: the module start, C6's
                                                               two engine items) holds nothing */
#if SONG_BUG == 39
    s5_hold = 0u;                                           /* planted: every item excused from A1, the posts' and the
                                                               ticks' too (only the module start and C6's two engine
                                                               items should be) */
#endif
    s5_blk_begin = (uint16_t)BRD_SYNTH_BLKCNT(st);
    if (!s5_hold)
        s5_wbusy_begin = (uint8_t)(brd_synth_diag() >> 16);
#endif
    s5_mirror_in(st);
}

void board_synth_end(uint16_t done)
{
    brd_synth_done(done);
#if !PPM_RELEASE && !TDIAG_LEAN
    if (s5_free_on) {                                       /* test build 5's TEST: the WBUSY this free DONE store
                                                               added (0 or 1: nothing else is stored between the two
                                                               DIAG reads) */
        s5_free_on = 0u;
        if (SONG_BUG != 38)                                 /* (SONG_BUG 38, planted: the store's WBUSY not counted) */
            s5_test.done_wbusy += ((brd_synth_diag() >> 16) - s5_free_w0) & 0xFFu;
    }
#endif
}

/* test build 5's TEST: the next DONE store has no hold-off before it (L1's after a post with no item; one at the end of
   an item with no arrival: a module start's, a C6 engine item's), so it may meet a running block, legally: DIAG.WBUSY
   is read here and again right after the store (board_synth_end), and the difference is A1's legal WBUSY
   (done_wbusy). core/song/song_oeq.c calls it just before board_synth_end, with interrupts off (L1, or L2b's
   critical section): no other store and no DIAG clear (the tick item's, in its own critical section) can come
   between the two reads */
#if !TDIAG_LEAN                                 /* (the lean TEST image calls none: core/song/song_oeq.c) */
void board_done_free(void)
{
#if !PPM_RELEASE
    COUNT_T(done_free);
    s5_free_w0 = (uint8_t)(brd_synth_diag() >> 16);
    s5_free_on = 1u;
#endif
}
#endif

/* every field the item changed to the synth (song_run_one, at every item's end, before its DONE: the blocks
   waiting for that DONE see them; an item with no arrival of its own, the module start or a C6 engine item, moves
   no DONE but writes its fields all the same) */
void board_synth_put(void)
{
    s5_mirror_out();
#if !PPM_RELEASE && !TDIAG_LEAN
    if (!s5_hold) {                                         /* test build 5's TEST: an item with no hold-off (the module
                                                               start, C6's song_c6_init / song_c6_ready: SQ_JOB /
                                                               SQ_CALL): did a block start while it stored? */
        uint32_t st = brd_synth_status(), w = ((brd_synth_diag() >> 16) - s5_wbusy_begin) & 0xFFu;
        COUNT_T(jobs);
        if ((st & BRD_SYNTH_BUSY) || BRD_SYNTH_BLKCNT(st) != s5_blk_begin)
            COUNT_T(overlaps);
        s5_test.job_wbusy += w;                             /* (the DIAG clear is the tick item's: never in between) */
    }
#endif
}

/* the cart chip's main-loop pass (core/song/song_oeq.c song_main_pass; core/sched/sched.h says where it runs).
   pass_blk = the block count the last pass saw: a block-done event with no block since (an instant serviced with
   no block) leaves the pass's inputs as they were, so it is skipped */
s5_pass_stats_t s5_pass_stats;
static uint32_t pass_blk = UINT32_MAX;
static uint32_t snap_on, snap_blk;          /* a bracketed pass runs on its snapshot (board_pass_bracket) */
#if defined(SONG_TEST_HOOKS)
void (*s5_test_pass)(uint32_t why);        /* host harness: a bracketed pass is about to read the synth */
#endif

void board_item_pass(void)
{
    if (disp_s5_jobs()) {
        COUNT_S5(skip_job);
        return;
    }
    if (song_q_depth() > 1u) {          /* another item waits (a burst): its pass covers this one, as the cart
                                           chip's tail-chained handlers return to its thread once */
        COUNT_S5(skip_same);
        return;
    }
    COUNT_S5(item);
    pass_blk = board_blkcnt();
    disp_s5_pass();
}

void board_pass_bracket(uint32_t why)
{
    uint32_t st;
    if (!(why & S5_PASS_TAIL) && disp_s5_jobs()) {     /* the job's own tail runs the pass at its end */
        COUNT_S5(skip_job);
        return;
    }
#if defined(SONG_TEST_HOOKS)
    if (s5_test_pass)
        s5_test_pass(why);
#endif
    /* The pass sees a whole block or none. No arrival is pending here, so BUSY = 0 does not hold the next block off
       (docs/MCU_INTERFACE.md v1.3 3.10.5 holds blocks only behind an arrival not yet DONE): the 16 ENV_LEVEL words are
       read, then STATUS again; a block that ran meanwhile shows as BUSY or a moved BLKCNT (the synth moves BLKCNT as
       it starts a block and holds RUN until the block's writes are done: the synth's RTL, paprium_synth_sched.sv), and
       the whole set is read again after it. The
       pass then reads only that snapshot: the records, and the snapshot's BLKCNT for the meters (board_blkcnt) */
    for (;;) {
        uint32_t st2;
        st = synth_wait();
        if (why == S5_PASS_BLK && BRD_SYNTH_BLKCNT(st) == pass_blk) {
            COUNT_S5(skip_same);
            return;
        }
        s5_mirror_pass_in(st);
        st2 = brd_synth_status();
        if (SONG_BUG == 37 || (!(st2 & BRD_SYNTH_BUSY) && BRD_SYNTH_BLKCNT(st2) == BRD_SYNTH_BLKCNT(st)))
            break;
        COUNT_S5(retry);
    }
    if (why & S5_PASS_TAIL)
        COUNT_S5(tail);
    else if (why & S5_PASS_POST)
        COUNT_S5(post);
    else
        COUNT_S5(bracket);
    pass_blk = BRD_SYNTH_BLKCNT(st);
    snap_blk = pass_blk;
    snap_on = 1u;
    disp_s5_pass();
    snap_on = 0u;
}

/* the block count the meters decay to: STATUS.BLKCNT, or inside a bracketed pass its snapshot's (a block after the
   snapshot must not reach the FM / PSG meters while the wave levels are the snapshot's). Inside an item with an
   arrival the synth holds every block, so there the two are the same */
uint32_t board_blkcnt(void) { return snap_on ? snap_blk : BRD_SYNTH_BLKCNT(brd_synth_status()); }

uint32_t board_crit_enter(void) { return sched_crit_enter(); }
void board_crit_leave(uint32_t s) { sched_crit_leave(s); }

int board_packet_dma(const uint16_t *src, uint32_t words)
{
    volatile uint16_t *d = brd_cart_ram() + (0x1800u >> 1);
    uint32_t i;
    for (i = 0; i < words; i++)
        d[i] = src[i];
    return 1;
}

void board_flush_timer(uint32_t n) { (void)n; }            /* the cart chip's TIM14 fires at once: the tick's own item */

WEAK uint32_t board_rand_src(void) { return brd_now(); }

void board_frame_arm(uint32_t pending) { brd_synth_arm(pending & 1u); }
uint32_t board_frame_cnt(void) { return BRD_SYNTH_CNT(brd_synth_sched()); }

/* the views the tick reads and writes: RAMDP (the packet, $1B00, $1B90) and the synth's dac_buf_L in CRAM (the $1880
   stream, L[6i] / L[6i+3]: docs/MCU_INTERFACE.md v1.3 3.8 DACBUF_L); C6 adds the program, preset, directory and
   flash views */
void board_views_init(void)
{
    song_v.ramdp = brd_cart_ram();
    song_v.dac_buf = SONG_BUG == 16 ? brd_dacbuf_l() + BRD_DACBUF_N : brd_dacbuf_l();
}

/* the 88 configuration: the cart chip's DMA start / stop and DAC pin set-up = CONFIG (v1.3 3.10.2: written
   exactly when the cart chip's body runs; the synth applies the scheduler half and, in DT, restarts both rings at
   index 0, dated at SEQ's arrival) */
void board_dac_mode(uint32_t ym, uint32_t ntsc)
{
    uint32_t seq = SONG_BUG == 27 ? 0u : (uint32_t)s5_item_seq;
    brd_synth_config((ym ? 2u : 1u) | (ntsc ? 0u : 4u) | (seq << 16));
#if !PPM_RELEASE && !TDIAG_LEAN
    if (!ym)
        COUNT_T(dt_starts);                                 /* test build 5's TEST: A2's bound */
    if (!s5_test.t_config)
        s5_test.t_config = brd_now() | 1u;
#endif
}

/* C6's views: the cart chip's flash views and its bank keep their bus addresses in
   the engine's state (the synth's mirror converts them: docs/MCU_INTERFACE.md v1.3 3.10.3-3.10.4) */
void board_c6_views(void)
{
    volatile uint8_t *ws = brd_workspace() + BRD_C6TAB_OFF;
    song_v.flash16 = brd_flash16();
    song_v.flash16_bus = 0x6C000000u;
    song_v.flash8 = brd_flash8();
    song_v.flash8_bus = 0x6C800000u;
    song_v.sdir = brd_bank();
    song_v.sdir_bus = 0xC0089800u;
    song_v.wprog = (const uint8_t *)(uintptr_t)ws;
    song_v.psgenv = (const uint8_t *)(uintptr_t)(ws + 0x1000u);
}

uint8_t *board_c6_tab(uint32_t which)
{
    return (uint8_t *)(uintptr_t)(brd_workspace() + BRD_C6TAB_OFF + (which ? 0x1000u : 0u));
}

/* the audio set-up's memsets of dac_buf_L / R: both CRAM rings, 1,920 entries each */
void board_dacbuf_zero(void)
{
    volatile uint16_t *d = brd_dacbuf();
    uint32_t i;
    for (i = 0; i < 2u * BRD_DACBUF_N; i++)
        d[i] = 0;
}

/* the C6 wave bank (the decode's count 1..0x152000): test build 4b's first-boot unpack (board/pocket/boot) puts it
   in CRAM BANK before the 68000 runs. Test build 5 on: the board's answer (brd_bank_ok: on the Pocket, CACHE.VALID set
   at this power-on and the bank made from the stream the game's C600 names, the header's ROM key,
   board/pocket/boot/c4b.h); weak: the host tests replace it */
WEAK uint32_t board_bank_ok(uint32_t stream)
{
    return brd_bank_ok(stream);
}

/* the module store: the SDRAM workspace from BRD_MODSTORE_OFF holds a directory, then the 52 modules as C6 decodes
   them: +0 magic BRD_MODSTORE_MAGIC (written last), +4 the module count, +8.. one u32 per track 0..63 = the module's
   offset from the store's start (0 = none), +0x108.. one u32 per track = its decoded length; modules from
   BRD_MODSTORE_DIR, each at a 16-byte offset. The 68000 cannot see the workspace. */
#define MS_DIR()  ((volatile uint32_t *)(volatile void *)(brd_workspace() + BRD_MODSTORE_OFF))
static uint32_t ms_next;                                    /* C6: the next module's offset */

WEAK const uint8_t *board_module(uint32_t track)
{
    const volatile uint32_t *dir = MS_DIR();
    uint32_t off, len;
    if (dir[0] != BRD_MODSTORE_MAGIC || track > 63u)
        return 0;
    off = dir[2u + track];
    len = dir[66u + track];
    if (off < BRD_MODSTORE_DIR || off >= BRD_MODSTORE_BYTES || len > BRD_MODSTORE_BYTES - off)
        return 0;
    return (const uint8_t *)(uintptr_t)(brd_workspace() + BRD_MODSTORE_OFF + off);
}

WEAK uint32_t board_module_len(uint32_t track)
{
    const volatile uint32_t *dir = MS_DIR();
    if (dir[0] != BRD_MODSTORE_MAGIC || track > 63u)
        return 0;
    return dir[66u + track];
}

void board_store_begin(void)
{
    volatile uint32_t *dir = MS_DIR();
    uint32_t i;
    dir[0] = 0;                                             /* the magic first of all: no reader takes a half store */
    for (i = 1; i < 130u; i++)
        dir[i] = 0;
    ms_next = BRD_MODSTORE_DIR;
}

uint8_t *board_store_slot(uint32_t *room)
{
    *room = BRD_MODSTORE_BYTES - ms_next;
    return (uint8_t *)(uintptr_t)(brd_workspace() + BRD_MODSTORE_OFF + ms_next);
}

void board_store_put(uint32_t track, uint32_t len)
{
    volatile uint32_t *dir = MS_DIR();
    if (track > 63u)
        return;
    dir[2u + track] = ms_next;
    dir[66u + track] = len;
    dir[1] += 1u;
    ms_next = (ms_next + len + 15u) & ~15u;
}

void board_store_end(uint32_t ok)
{
    if (ok)
        MS_DIR()[0] = BRD_MODSTORE_MAGIC;                   /* last */
}
