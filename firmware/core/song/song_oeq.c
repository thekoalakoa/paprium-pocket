/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song_oeq.c - the ordered engine queue and the L1 / L2 split (core/song/README.md, "The ordered queue").
 *
 * The cart chip (the STM32 microcontroller on the real cartridge) runs every audio post and the 9494 in one serial
 * interrupt context (EXTI15_10, prio 1: each post's handler runs to its end before the next arrival is looked at; the
 * tick's packet flush, TIM14 prio 2, fires at once after it), and mixes a block at a TIM6 instant (prio 3) only after
 * every post that arrived before it. Ours keeps that ORDER and moves the WORK:
 *   L1  (core/sched l1_mei, interrupts off), for every post IN ARRIVAL ORDER (both mailboxes pending: the older by
 *       SEQLAT first): song_l1_seen(n) with its arrival number n (docs/MCU_INTERFACE.md v1.3 SEQLAT), then the
 *       dispatcher. An audio post's fragment (and the 9494's) calls song_arrive(): the cart chip's
 *       gates and refusals, the argument copy and the parts the 68000 can see (the 8C job push, $1FE6 bits 14 / 8 /
 *       13); the engine part becomes an item with its arrival number, and the dispatcher finishes the post at once
 *       (docs/ALLOWLIST.md, row B39: replies up to ~0.1 ms earlier than the cart's). At the end of the L1 entry
 *       song_l1_end() writes DONE when nothing waits, else L1 raises MSI.
 *   L2b (core/sched l2b_msi) song_run_one(): the oldest item, between board_synth_begin() and board_synth_end(DONE);
 *       MTI is masked around it, so an item is atomic against the urgent finish. The tick is an item too (its
 *       sequencer half and its packet flush in one).
 *   L2a (core/sched wh_urgent): a tick still waiting 1.8 ms after its 9494 (STAMP_A) is run with interrupts off,
 *       with every item ahead of it (song_tick_due, song_run_one), so the Z80 (it reads the packet ~3.0 ms after the
 *       9494) never reads a late one.
 *   L2c (core/dispatch jobs.c): song_job_done() hands the 8C job's module back as an item, so the module start runs
 *       in arrival order; the job leaves, and $1FE6 bit 14 is rewritten, only after that item has run (on the cart
 *       chip the job's tail, which starts the module, also runs before the job step's end).
 * DONE (docs/MCU_INTERFACE.md v1.3 3.10.5): DONE = n says every arrival up to n is served, so it must never pass an
 * arrival whose engine part has not run. L1 serves the posts in arrival order, the held posts are taken oldest first,
 * and a new post is held while any is held, so the queue is in arrival order (B Jam's decision 3(a), docs/ALLOWLIST.md
 * row B39); the urgent finish runs the queue from its head, so items always end in that order. An item's own number is
 * still not DONE: a post with no engine part (refused, a null 8C slot, any non-audio post) takes no slot and only moves
 * "seen", so after the last item DONE must reach it too (SONG_BUG 9 leaves it behind). So DONE is computed every time:
 * the oldest arrival still pending (queued with an arrival, or held back) minus 1, or, with nothing pending, the newest
 * arrival L1 has served ("seen"); it is a full scan, not the head, so DONE stays safe even if the order were ever
 * broken. A refused post's DONE comes with the next DONE written (at the end of its L1 entry when nothing waits, else
 * at the next item end).
 * The module-start item has no arrival of its own, so a block can start while it runs (the synth holds blocks only
 * for arrivals: v1.3 3.10.5), as TIM6 can preempt the cart chip's thread-mode job tail in the middle of
 * its module start. Holding the 8C's arrival until the module start would keep every block waiting for the whole job,
 * behind any unpack job ahead of it in the queue (tens of ms: past the 5 ms hold-off TIMEOUT), so it is not done (a
 * hold bit in the synth, proposed, would make it atomic, as our zero-time model of the cart chip has it).
 * A full queue holds the post back before its gates run (SONG_ARR_HELD: the dispatcher does not finish it, so the
 * 68000 waits on that mailbox as it waits for a busy cart chip); the next item end takes it (its gates run then: the
 * cart chip would also serve it only when it gets to it) and finishes it (board_post_finish). Counted in song_q_over;
 * the 68000's protocol (one post per mailbox until it is finished) leaves at most one held post per mailbox.
 */
#include "song.h"
#include "tdiag.h"

static song_item q[SONG_Q_N];
static volatile uint8_t q_wr, q_rd, q_busy;     /* q_rd moves at an item's END: the running item keeps its slot */
static uint16_t seen, done;                     /* the newest arrival L1 has served; the DONE last written */

typedef struct {
    uint8_t  on, mbox;
    uint16_t seq;
    uint32_t word, stamp;
    uint16_t a[SONG_ARGS_N];
} song_held;
static song_held held[2];                       /* held back by a full queue, by mailbox ([0] A, [1] B); taken oldest
                                                   arrival first */

uint32_t song_q_over, song_q_max;
uint16_t song_meter_blk;
volatile uint8_t song_pass_hold;                /* a job runs (core/dispatch/jobs.c sets it around every job) */
#if defined(SONG_TEST_HOOKS)
void (*song_test_pre)(uint32_t kind, uint32_t seq);   /* host harness: an item is about to start (the synth's
                                                        fields of its instant go into the board's region 0x06 here,
                                                        before synth_begin reads them back) */
void (*song_test_mid)(void);
void (*song_test_begin)(uint32_t kind, uint32_t seq);  /* host harness: an item starts (after synth_begin): the
                                                            logic-owned state of its arrival's instant goes in here */
#endif

/* test build 5's TEST: core/sched/s5_glue.c counts these DONE stores (sched.h s5_test_stats_t); a host rig without the
   glue links this no-op */
#if !PPM_RELEASE && !TDIAG_LEAN
__attribute__((weak)) void board_done_free(void) { }
#endif

/* how far an arrival number is past DONE (an arrival still pending: 1 .. 0x7FFF) */
#define AHEAD(x)  ((uint16_t)((uint16_t)(x) - done))

void song_oeq_init(uint16_t arr)
{
    q_wr = q_rd = q_busy = 0u;
    held[0].on = held[1].on = 0u;
    seen = done = arr;
    board_synth_end(arr);
}

uint32_t song_q_depth(void)
{
    return (uint32_t)(uint8_t)(q_wr - q_rd);
}

uint16_t song_done(void)
{
    return done;
}

void song_l1_seen(uint16_t seq)
{
    if (AHEAD(seq) > AHEAD(seen) && AHEAD(seq) < 0x8000u)
        seen = seq;
}

/* the gates and the push, with the arguments as taken at the arrival (L1, or the item end for a held post: both
   with interrupts off) */
static uint32_t arrive(uint32_t mbox, uint32_t w, const uint16_t *a, uint16_t seq, uint32_t stamp)
{
    mbx_ctx c;
    song_item *it;
    uint32_t i, d;

    c.mbox = mbox;
    if (mbox == 1) {
        c.word = w & 0x3F00u;
        c.args = 0;
    } else {
        c.word = w & 0x3FFFu;
        c.args = (w >> 14) & 1u;
    }
    c.a = a;
    if (song_gate(&c) != SONG_OK)
        return SONG_ARR_DONE;
    it = &q[q_wr % SONG_Q_N];
    it->seq = seq;
    it->kind = (c.word >> 8) == 0x14 ? SQ_TICK : SQ_POST;
    it->mbox = (uint8_t)mbox;
    it->word = (uint16_t)c.word;
    it->args = (uint16_t)c.args;
    for (i = 0; i < SONG_ARGS_N; i++)
        it->a[i] = a[i];
    it->stamp = stamp;
    it->mod = 0;
    q_wr++;                                     /* after the fields: L2b reads q_wr */
    d = (uint8_t)(q_wr - q_rd);
    if (d > song_q_max)
        song_q_max = d;
    return SONG_ARR_ITEM;
}

/* L1: one arrival. mbox 1 = A ($1FEC), 2 = B ($1FEA); w = the word as posted; args = RAMDP $1E10..; seq = its
   arrival number; stamp = TIMER at its arrival (STAMP_A / STAMP_B) */
uint32_t song_arrive(uint32_t mbox, uint32_t w, const volatile uint16_t *args, uint16_t seq, uint32_t stamp)
{
    uint16_t a[SONG_ARGS_N];
    uint32_t i;
    for (i = 0; i < SONG_ARGS_N; i++)
        a[i] = args[i];
    if ((uint8_t)(q_wr - q_rd) >= SONG_Q_N || held[0].on || held[1].on) {
        song_held *h = &held[mbox == 1 ? 0 : 1];
        song_q_over++;
#if SONG_BUG == 11
        return SONG_ARR_DONE;                   /* planted: the engine part dropped, the post finished */
#endif
        h->on = 1u;
        h->mbox = (uint8_t)mbox;
        h->seq = seq;
        h->word = w;
        h->stamp = stamp;
        for (i = 0; i < SONG_ARGS_N; i++)
            h->a[i] = a[i];
        return SONG_ARR_HELD;
    }
    return arrive(mbox, w, a, seq, stamp);
}

/* DONE: the oldest arrival still pending, minus 1; nothing pending: the newest arrival served */
static uint16_t done_value(void)
{
    uint32_t best = (uint32_t)AHEAD(seen) + 1u, k, n = (uint8_t)(q_wr - q_rd);
    for (k = 0; k < n; k++) {
        const song_item *it = &q[(uint8_t)(q_rd + k) % SONG_Q_N];
        if (it->kind < SQ_JOB && AHEAD(it->seq) < best)      /* SQ_JOB / SQ_CALL: no arrival */
            best = AHEAD(it->seq);
    }
    for (k = 0; k < 2; k++)
        if (held[k].on && AHEAD(held[k].seq) < best)
            best = AHEAD(held[k].seq);
    return (uint16_t)(done + best - 1u);
}

uint32_t song_l1_end(void)
{
    uint16_t d;
    if (q_wr != q_rd)
        return 1u;                              /* L2b runs them and writes DONE (a held post implies a full queue) */
    d = done_value();                           /* the newest served */
    if (d != done) {
        done = d;
#if !PPM_RELEASE && !TDIAG_LEAN
        board_done_free();                      /* (test build 5's TEST: no hold-off before this store) */
#endif
        board_synth_end(d);
    }
    return 0u;
}

uint32_t song_work(void)
{
    return q_wr != q_rd && !q_busy;
}

/* the held posts, oldest arrival first (both are newer than every queued item: a post is held while any is), while
   there is room: their gates and push now, then their finish */
static void take_held(void)
{
    for (;;) {
        song_held *h;
        if (held[0].on && (!held[1].on || AHEAD(held[0].seq) < AHEAD(held[1].seq)))
            h = &held[0];
        else if (held[1].on)
            h = &held[1];
        else
            return;
        if ((uint8_t)(q_wr - q_rd) >= SONG_Q_N)
            return;
        h->on = 0u;
        (void)arrive(h->mbox, h->word, h->a, h->seq, h->stamp);
        board_post_finish(h->mbox);
    }
}

/* L2b (MTI masked) or the urgent finish (interrupts off): the oldest item */
uint32_t song_run_one(void)
{
    song_item *it;
    mbx_ctx c;
    uint32_t s;
    uint16_t d;

    s = board_crit_enter();
    if (q_wr == q_rd || q_busy) {
        board_crit_leave(s);
        return 0u;
    }
#if SONG_BUG == 6
    if ((uint8_t)(q_wr - q_rd) >= 2) {          /* the planted order bug: the next two items swapped */
        song_item t = q[q_rd % SONG_Q_N];
        q[q_rd % SONG_Q_N] = q[(uint8_t)(q_rd + 1u) % SONG_Q_N];
        q[(uint8_t)(q_rd + 1u) % SONG_Q_N] = t;
    }
#endif
    it = &q[q_rd % SONG_Q_N];
    q_busy = 1u;
    board_crit_leave(s);

#if defined(SONG_TEST_HOOKS)
    if (song_test_pre)
        song_test_pre(it->kind, it->seq);
#endif
    board_synth_begin(it->kind >= SQ_JOB ? done : it->seq);
#if defined(SONG_TEST_HOOKS)
    if (song_test_begin)
        song_test_begin(it->kind, it->seq);
#endif
    song_meters(board_blkcnt());
    if (it->kind == SQ_POST || it->kind == SQ_TICK) {
        c.mbox = it->mbox;
        c.word = it->word;
        c.args = it->args;
        c.a = it->a;
        song_body(&c);
    } else if (it->kind == SQ_JOB) {
        song_mod = it->mod;
        (void)song_job_module(0);               /* 8C's job has no failure report (fail_en 0) */
    } else if (it->kind == SQ_CALL) {
        it->fn(it->stamp);                      /* a job's engine part (C6's audio init) */
    }
    if (SONG_BUG != 32)
        board_item_pass();                      /* the cart chip's main-loop pass on the state the item left */
    board_synth_put();                          /* the item's fields to the synth, before its DONE */

    s = board_crit_enter();
    q_rd++;
    q_busy = 0u;
    take_held();
    d = done_value();
#if SONG_BUG == 9
    d = it->kind >= SQ_JOB ? done : it->seq;    /* planted: the item's own number */
#endif
    if (SONG_BUG != 13 && d != done) {          /* (SONG_BUG 13, planted: no DONE at an item end) */
        done = d;
#if !PPM_RELEASE && !TDIAG_LEAN
        if (it->kind >= SQ_JOB)
            board_done_free();                  /* (test build 5's TEST: an item with no arrival held nothing
                                                   off) */
#endif
        board_synth_end(d);
    }
    board_crit_leave(s);
    return 1u;
}

uint32_t song_run(void)
{
    uint32_t n = 0;
    while (song_run_one())
        n++;
    return n;
}

/* a tick waits (queued and not running, or held back): the oldest 9494's stamp (the queue is in arrival order, so it
   is the first tick found; the whole queue is looked at, so the urgent follows the oldest stamp whatever) */
uint32_t song_tick_due(uint32_t *stamp)
{
    uint32_t k, n = (uint8_t)(q_wr - q_rd), any = 0u, best = 0u;
    for (k = q_busy ? 1u : 0u; k < n; k++) {
        const song_item *it = &q[(uint8_t)(q_rd + k) % SONG_Q_N];
        if (it->kind == SQ_TICK && (!any || (int32_t)(it->stamp - best) < 0)) {
            best = it->stamp;
            any = 1u;
        }
    }
    for (k = 0; k < 2; k++)
        if (held[k].on && ((held[k].word >> 8) & 0x3Fu) == 0x14u && (!any || (int32_t)(held[k].stamp - best) < 0)) {
            best = held[k].stamp;
            any = 1u;
        }
    if (any)
        *stamp = best;
    return any;
}

/* L2c: the 8C module is ready (the store decoded at C6 on the Pocket); it runs with no arrival of its own */
uint32_t song_job_done(const uint8_t *mod)
{
    song_item *it;
    uint32_t s = board_crit_enter(), d;
    if ((uint8_t)(q_wr - q_rd) >= SONG_Q_N) {
        board_crit_leave(s);
        return 0u;
    }
    it = &q[q_wr % SONG_Q_N];
    it->seq = 0;
    it->kind = SQ_JOB;
    it->mbox = 0;
    it->word = 0;
    it->args = 0;
    it->stamp = 0;
    it->mod = mod;
    q_wr++;
    d = (uint8_t)(q_wr - q_rd);
    if (d > song_q_max)
        song_q_max = d;
    board_crit_leave(s);
    return 1u;
}

/* L2c: fn(arg) as an item with no arrival of its own, in order with the posts and the ticks (a job's part that
   writes the engine state: C6's audio init, core/song/song_c6.c); the job waits for it (song_job_waiting) */
uint32_t song_call(void (*fn)(uint32_t), uint32_t arg)
{
    song_item *it;
    uint32_t s = board_crit_enter(), d;
    if ((uint8_t)(q_wr - q_rd) >= SONG_Q_N) {
        board_crit_leave(s);
        return 0u;
    }
    it = &q[q_wr % SONG_Q_N];
    it->seq = 0;
    it->kind = SQ_CALL;
    it->mbox = 0;
    it->word = 0;
    it->args = 0;
    it->stamp = arg;
    it->mod = 0;
    it->fn = fn;
    q_wr++;
    d = (uint8_t)(q_wr - q_rd);
    if (d > song_q_max)
        song_q_max = d;
    board_crit_leave(s);
    return 1u;
}

uint32_t song_job_waiting(void)
{
    uint32_t k, n = (uint8_t)(q_wr - q_rd);
    for (k = 0; k < n; k++)
        if (q[(uint8_t)(q_rd + k) % SONG_Q_N].kind >= SQ_JOB)
            return 1u;
    return 0u;
}

/* the FM / PSG meters (of voices 0-9): the cart chip's block envelope step takes 1 from each non-zero meter
   per mixed block, voices 0-5 while music plays, voices 0-9 while it is stopped; the logic counts the blocks
   (BLKCNT, 12 bits) and the firmware applies them here, before any engine work reads or writes a meter */
void song_meters(uint32_t blk)
{
    uint32_t n = (blk - song_meter_blk) & 0xFFFu, v, top = S.playing != 0 ? 6u : 10u;
    song_meter_blk = (uint16_t)(blk & 0xFFFu);
    if (SONG_BUG == 5 && n > 1)
        n--;
    if (n == 0)
        return;
    for (v = 0; v < top; v++) {
        int32_t l = S.v[v].env_level;
        if (l > 0)
            l = l > (int32_t)n ? l - (int32_t)n : 0;
        else if (l < 0)
            l -= (int32_t)n;
        S.v[v].env_level = (int16_t)l;
    }
}

/* the cart chip's main-loop pass. The cart chip's thread mode is one loop with no WFI, so the pass runs over and over
   whenever no interrupt is active and no job is running: what the 68000 reads at $1FE6 bit 3, $1B00 and $1B90 is
   this pass over the state the LATEST interrupt left (a mixed block, a post, a 9494 and its flush). It does not run while a job runs (the job is thread mode too): bit 3 and the
   feed hold across an 8C decode, and the job's tail runs one pass.
   Work: $1FE6 bit 3 := music playing (cleared again after a stop or a song end); the 81 bit 1 counters to
   RAMDP $1B00 (16 halfwords: the dispatcher's, passed in; NULL = 81 bit 1 off), counter 11's DT half folded in
   first (board_trace_fold: the cart chip's DT block mix counts it in the same word); the Boom Box feed (81
   bit 2 and the sequencer ready).
   Ours: where the cart chip's thread would run it: inside every engine item's synth_begin / synth_end after its
   body (board_item_pass), so on the state the item left with no block between, as the zero-time model runs the
   pass after a post; after every block the logic mixes (CAUSE.BLK -> L2b, its own bracket: core/sched/s5_glue.c
   board_pass_bracket, which reads the wave voices' ENV_LEVEL back first, v1.3 3.10.3 / 3.10.5, a whole block or
   none); and
   once after every job (the job tail). Never while a job is queued or running (the cart chip's thread runs the
   job), so bit 3 and the feed hold across an 8C's job as on the cart, and never in the middle of an item.
   It reads the FM / PSG meters, which the cart chip decays per block before its pass sees them, so it applies the
   lazy meter decay to BLKCNT first. */
void song_main_pass(const uint16_t *dbg, uint32_t boombox_on)
{
    uint32_t i;
    if (song_pass_hold && SONG_BUG != 24)
        return;                         /* a job runs; the cart chip's pass is its thread, which the job holds */
    song_meters(board_blkcnt());
    STATUS(S.playing != 0 ? 1u : 0u, 3, 8);
    if (SONG_BUG != 18)
        board_trace_fold(0u);           /* counter 11's DT half before the copy */
    if (dbg)
        for (i = 0; i < 16; i++)
            song_v.ramdp[0x1B00 / 2 + i] = dbg[i];
    if (boombox_on && S.ready != 0)
        boombox_feed();
}
