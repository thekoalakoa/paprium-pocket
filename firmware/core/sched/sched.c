/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/sched/sched.c - the four levels, MSI work, held posts and the song tick.
 *
 * The rules (docs/MCU_INTERFACE.md section 6.3) and where each is kept here:
 *   6.3.2 ack before read / before release: l1_mei acks a CAUSE bit before it reads that mailbox, so a post landing
 *         after the ack sets the bit again (property FZ5 of tests/equiv/fuzz_sched.py: no lost post);
 *   6.3.3 flush after ack: l1_mei flushes MEI before it returns; L2a / L2b are flushed by the trap entry's restore of
 *         mie; L2b's per-slice MTI masks are undone by brd_lines_on, which is the flush for MTI;
 *         L2c opens MSI only after L2b has cleared MSIP and looked, and a nested L2b's entry masks MSI until its exit
 *         (the flush);
 *   6.3.4 an MEI entry with CAUSE = 0 returns at once;
 *   6.3.5 every shared state change below is inside an MIE-off section, or in L1 (which runs with MIE off).
 * MEI, MTI and MSI are the MCU's external, timer and software interrupt lines (MSIP: the software interrupt's pending
 * bit); CAUSE is the RTL register that says why MEI was raised. In the FW_S5 = 0 build (the earlier firmware) the song
 * tick is empty (nothing calls sched_tick_start outside the TEST probe); its plumbing was built and fuzzed then because
 * the song engine was to be firmware-only on the frozen interface.
 *
 * In the FW_S5 build (the full firmware, board/board.h; docs/MCU_INTERFACE.md v1.3 section 6.1): the held posts, the
 * single tick slot and the deferred tick finish are gone. L1 tags every post with its arrival number (SEQLAT) and
 * serves the posts in arrival order, each at once; the music body becomes an item of the ordered engine queue
 * (core/song/song_oeq.c), so the queue is in arrival order; L2b runs the items in that order,
 * each atomic against L2a (MTI masked), before it looks at the jobs; the urgent slot runs a tick still waiting
 * CLK_URGENT5 after its 9494 (STAMP_A), with every item ahead of it, interrupts off. */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"
#include "stats.h"
#if FW_MW
#include "disp.h"
#include "mw.h"
#endif
#if FW_S5
#include "song.h"
#endif

#if PPM_RELEASE || TDIAG_LEAN                  /* (TDIAG_LEAN, test build S3a on: core/trace/tdiag.h) */
#define COUNT(f)                ((void)0)
#else
#define COUNT(f)                (sched_stats.f++)
#endif

/* SCHED_BUG: planted bugs for the negative controls of the RV32 fuzz tests only (fwbuild.json s1 variants probe_bug_*
   and test_bug_sched1 / test_bug_l2c / test_bug_hold; never defined in an image that ships): 1 = the post read before
   its ack, 2 = MSIP cleared after the look, 3 = held posts replayed before the tick end, 4 = the brain call runs with
   MSI and MTI masked, as the cart's sub-CPU runs it (a song tick waits for the whole call: FZ9; the earlier plant 4,
   no urgent promotion, cannot fail FZ9 any more, now that the call is below L2b), 6 = the brain call runs with MSI
   masked (the jobs wait for the call: FZ13), 7 = the brain call holds the SFX feeder (MTI masked for the call, as an
   earlier version held the feeder's slot: FZ14), 9 = the lost wake-up of the earlier versions (the 2026-10-18 fix left
   out: a nested L2b that finds a pass running clears MSIP and leaves, and the pass below does not look again:
   tests/equiv/race_s1.py, tests/s1/sched_tests.c 7d). FW_S5: 1, 2, 4, 6, 9 keep their meaning; 10 = an engine item
   not atomic against L2a (MTI left open around it: the urgent finish comes in the middle of one and cannot run the
   queue), 11 = L1 queues an item and raises no MSI for it, 12 = the urgent finish does nothing, 13 = L1 serves
   mailbox B before A whenever both are pending, whatever their arrival order (an earlier version's order). FZ5-FZ14
   are the properties the fuzz tests check (tests/equiv/fuzz_sched.py, fuzz_s1.py). */
#ifndef SCHED_BUG
#define SCHED_BUG 0
#endif

sched_stats_t sched_stats;

/* ---- state (written in L1 or inside MIE-off sections only) --------------------------------------------------- */
static volatile uint32_t brain_pending;     /* L1 sets on SEND; the thread clears it before the call */
static volatile uint32_t brain_active;      /* the thread, around the call: L1 / L2a poll the glue's abort check */
#if !FW_S5
static volatile uint32_t tick_running;      /* sched_tick_start .. sched_tick_finish */
#endif
static volatile uint32_t l2c_active;        /* around an L2c pass: a nested L2b leaves L2c alone */
static volatile uint32_t l2c_missed;        /* a nested L2b cleared MSIP and left the pass below it alone: that pass may
                                               have looked at the queue already, so it looks again */
#if !FW_S5
static uint32_t held_n;                     /* held posts, at most one per mailbox, in arrival order */
static uint32_t held_mbx[2];
static uint16_t held_word[2];
#else
static uint32_t urg_on, urg_due;            /* the urgent slot is armed for this deadline (s5_urgent_arm) */
static volatile uint32_t blk_seen, blk_done; /* CAUSE.BLK entries L1 served / that a pass has covered */
static volatile uint32_t pass_tail;         /* a job ended: its tail's pass is due */
static volatile uint32_t post_seen, post_done;  /* L1 entries that served a post and queued no item / that
                                               a pass has covered */
#endif

void sched_init(void)
{
    brain_pending = 0u;
    brain_active = 0u;
#if !FW_S5
    tick_running = 0u;
#endif
    l2c_active = 0u;
    l2c_missed = 0u;
#if !FW_S5
    held_n = 0u;
#else
    urg_on = 0u;
#endif
    wheel_init();
#if FW_S5
    board_views_init();                         /* the tick's RAMDP / DACBUF_L views */
    blk_seen = blk_done = 0u;                   /* no pass due */
    post_seen = post_done = 0u;
    pass_tail = 0u;
    s5_mirror_prime();                          /* every synth field from the engine's records
                                                   (docs/MCU_INTERFACE.md v1.3 3.10.6: the state RAM is not reset) */
    song_oeq_init((uint16_t)brd_synth_seq());   /* nothing pending: DONE := ARR (0 after every reset) */
#endif
}

/* ---- L1 ------------------------------------------------------------------------------------------------------- */
#if FW_S5
/* the urgent slot follows the oldest tick that waits (L1 after it queued one, L2b after every item, L2a after the
   finish); interrupts off */
static void s5_urgent_arm(void)
{
    uint32_t st;
    if (song_tick_due(&st)) {
        st += CLK_URGENT5;
        if (!urg_on || st != urg_due) {
            urg_on = 1u;
            urg_due = st;
            wheel_arm(WH_URGENT, st);
        }
    } else if (urg_on) {
        urg_on = 0u;
        wheel_disarm(WH_URGENT);
    }
}

/* one post: its arrival number first (DONE must cover it even when it has no engine part), then the dispatcher */
static void l1_post_s5(uint32_t mbx, uint16_t word, uint16_t seq, uint32_t stamp)
{
    song_l1_seen(seq);
    ST_POST(word);
    disp_post_s5(mbx, word, seq, stamp);
}

/* mailbox B / A: acknowledged first, then its arrival number (SEQLAT) and its word (rule 6.3.2) */
static void l1_serve_b(void)
{
    uint32_t sl;
#if SCHED_BUG == 1
    uint16_t w = brd_freg_rd(BRD_FREG_FEA);
    brd_cause_ack(BRD_CAUSE_B);
    COUNT(posts_b);
    sl = brd_seqlat();
    l1_post_s5(MBX_B, w, (uint16_t)sl, brd_stamp_b());
#else
    brd_cause_ack(BRD_CAUSE_B);
    COUNT(posts_b);
    ST_LAT(brd_now() - brd_stamp_b());          /* TEST: the post's latency from the RTL's stamp */
    sl = brd_seqlat();
    l1_post_s5(MBX_B, brd_freg_rd(BRD_FREG_FEA), (uint16_t)sl, brd_stamp_b());
#endif
}

static void l1_serve_a(void)
{
    uint32_t sl;
    brd_cause_ack(BRD_CAUSE_A);
    COUNT(posts_a);
    sl = brd_seqlat();
    l1_post_s5(MBX_A, brd_freg_rd(BRD_FREG_FEC), (uint16_t)(sl >> 16), brd_stamp_a());
}

void l1_mei(void)
{
    uint32_t c, sl, served = 0u;
    ST_ENTER(ST_L1);
    c = brd_cause();
    COUNT(l1);
    if (!c)
        COUNT(l1_empty);
    while (c) {
        /* V (EXTI 13) first, then the two mailboxes in ARRIVAL order, then ours: SEND. Arrival order is the order this
           design follows (B Jam's decision 3(a), docs/ALLOWLIST.md row B39; docs/MCU_INTERFACE.md v1.3 3.10.5, "SEQLAT
           ... so L1 can tell which came first", 6.1 and rule 6.3.8): our zero-time model of the cart chip serves every
           post at its arrival, so a block between two arrivals sees the older one's writes only. The cart chip's EXTI
           line order (14 = B before 15 = A, inferred) decides only when both are pending at one of its entries, which
           depends on the cart chip's own latency, as ours being pending together depends on ours: ours does not follow
           it (an allow-list row was proposed for it). Both pending: SEQLAT holds both numbers (a mailbox is not posted
           again until finished) */
        if (c & BRD_CAUSE_V) {
            boot_warm_page();           /* the board's warm vector page first: the RTL holds the 68000 until */
            brd_cause_ack(BRD_CAUSE_V); /* this acknowledgement */
            disp_console_reset();
        }
        if (c & (BRD_CAUSE_A | BRD_CAUSE_B))
            served = 1u;                /* a post served (its main-loop pass follows) */
        if ((c & (BRD_CAUSE_A | BRD_CAUSE_B)) == (BRD_CAUSE_A | BRD_CAUSE_B)) {
            sl = brd_seqlat();
#if SCHED_BUG == 13
            sl = 0u;                    /* planted: B first whatever came first (the chip's line order) */
#endif
            if ((int16_t)(uint16_t)((uint16_t)sl - (uint16_t)(sl >> 16)) > 0) {    /* B the newer: A first */
                l1_serve_a();
                l1_serve_b();
            } else {
                l1_serve_b();
                l1_serve_a();
            }
        } else if (c & BRD_CAUSE_B) {
            l1_serve_b();
        } else if (c & BRD_CAUSE_A) {
            l1_serve_a();
        }
        if (c & BRD_CAUSE_S) {
            brd_cause_ack(BRD_CAUSE_S);
            COUNT(sends);
            sched_brain_post();
        }
        if (c & BRD_CAUSE_BLK) {        /* the synth mixed a block (BUSY fell): L2b runs the main-loop
                                           pass after it (rule 6.3.2: acknowledged first, then BUSY read again) */
            brd_cause_ack(BRD_CAUSE_BLK);
            blk_seen++;
#if !PPM_RELEASE && !TDIAG_LEAN
            s5_pass_stats.blk++;
#endif
            brd_msi(1u);
        }
        c = brd_cause();                /* posts that came in while L1 ran: served in the same entry */
    }
#if SCHED_BUG == 11
    (void)song_l1_end();                /* planted: the items wait for some other raise of MSI */
    (void)served;
#else
    if (song_l1_end())                  /* DONE now when nothing waits; else L2b runs the items (and writes DONE) */
        brd_msi(1u);
    else if (served && SONG_BUG != 36) {    /* no item waits (a refusal, a non-audio post): the cart chip's */
        post_seen++;                        /* main-loop pass after the post all the same (its counters, bit 3) */
        brd_msi(1u);
    }
#endif
    s5_urgent_arm();
    sched_brain_poll();
    ST_LEAVE();
    brd_lines_flush(BRD_LINE_MEI);      /* rule 6.3.3: the CPU latched MEI again before the acks */
}
#else
static void l1_post(uint32_t mbx, uint16_t word)
{
    if (tick_running && disp_holdable(mbx, word)) {
        if (held_n < 2u && (held_n == 0u || held_mbx[0] != mbx)) {
            held_mbx[held_n] = mbx;
            held_word[held_n] = word;
            held_n++;
            COUNT(held);
            return;
        }
        COUNT(held_overflow);           /* the protocol makes this impossible (one post per mailbox until finished):
                                           serve it now rather than lose it */
    }
    ST_POST(word);
    disp_post(mbx, word);
}

void l1_mei(void)
{
    uint32_t c;
    ST_ENTER(ST_L1);
    c = brd_cause();
    COUNT(l1);
    if (!c)
        COUNT(l1_empty);
    while (c) {
        /* the cart chip's EXTI order: 13 (V), 14 (B), 15 (A); then ours: SEND */
        if (c & BRD_CAUSE_V) {
            brd_cause_ack(BRD_CAUSE_V);
            disp_console_reset();
        }
        if (c & BRD_CAUSE_B) {
#if SCHED_BUG == 1
            uint16_t w = brd_freg_rd(BRD_FREG_FEA);
            brd_cause_ack(BRD_CAUSE_B);
            COUNT(posts_b);
            l1_post(MBX_B, w);
#else
            brd_cause_ack(BRD_CAUSE_B);
            COUNT(posts_b);
            ST_LAT(brd_now() - brd_stamp_b());          /* TEST: the post's latency from the RTL's stamp */
            l1_post(MBX_B, brd_freg_rd(BRD_FREG_FEA));
#endif
        }
        if (c & BRD_CAUSE_A) {
            brd_cause_ack(BRD_CAUSE_A);
            COUNT(posts_a);
            l1_post(MBX_A, brd_freg_rd(BRD_FREG_FEC));
        }
        if (c & BRD_CAUSE_S) {
            brd_cause_ack(BRD_CAUSE_S);
            COUNT(sends);
            sched_brain_post();
        }
        c = brd_cause();                /* posts that came in while L1 ran: served in the same entry */
    }
    sched_brain_poll();
    ST_LEAVE();
    brd_lines_flush(BRD_LINE_MEI);      /* rule 6.3.3: the CPU latched MEI again before the acks */
}
#endif

void sched_brain_poll(void)
{
    if (brain_active)
        brain_poll();
}

/* the brain call is the thread's: no interrupt is raised for it, and nothing is held */
void sched_brain_post(void) { brain_pending = 1u; }

/* a job queued (L1): L2b runs it as L2c, above the thread's brain call */
void sched_work_post(void) { brd_msi(1u); }

#if FW_S5
/* a job ended (L2c, core/dispatch/jobs.c): the cart chip's job tail runs the main-loop pass (0x0801A5E6 ->
   0x0801A60A) whatever is queued: L2b runs it, forced, before it looks at the next job */
void sched_pass_post(void)
{
    uint32_t s = sched_crit_enter();
    pass_tail = 1u;
    brd_msi(1u);
    sched_crit_leave(s);
}
#endif

/* ---- the song tick ------------------------------------------------------------------------------------------- */
#if FW_S5
/* the urgent finish (L2a, the slot armed by s5_urgent_arm): every tick still waiting CLK_URGENT5 after its 9494 runs
   now, with the items ahead of it, interrupts off: L2a runs only between two items (each masks MTI), so the queue is
   never half way through one here. Interrupts off, the Z80's packet read (~3.0 ms after the 9494) cannot be
   overtaken by L1 work */
void wh_urgent(uint32_t due)
{
    uint32_t s, st;
    (void)due;
    s = sched_crit_enter();
    urg_on = 0u;                                    /* (the wheel disarmed the slot before calling) */
    while (SCHED_BUG != 12 && song_tick_due(&st) && brd_until(st + CLK_URGENT5) <= 0) {
        COUNT(ticks_urgent);
        if (!song_run_one())
            break;
    }
    s5_urgent_arm();
    sched_crit_leave(s);
}
#else
void sched_tick_start(uint32_t stamp)
{
    uint32_t s = sched_crit_enter();
    tick_running = 1u;
    COUNT(ticks);
    wheel_arm(WH_URGENT, stamp + CLK_URGENT);
    brd_msi(1u);
    sched_crit_leave(s);
}

uint32_t sched_tick_running(void) { return tick_running; }

/* the tick end, then the 9494 tail, then the held posts in arrival order; interrupts off throughout */
static void sched_replay_held(void)
{
    uint32_t i, n = held_n;
    held_n = 0u;
    for (i = 0; i < n; i++) {
        COUNT(replayed);
        disp_post(held_mbx[i], held_word[i]);
    }
}

static void sched_tick_finish(void)
{
    uint32_t s = sched_crit_enter();
    if (tick_running) {
        wheel_disarm(WH_URGENT);
#if SCHED_BUG == 3
        sched_replay_held();
#endif
        audio_tick_end();
        tick_running = 0u;
        disp_tick_tail();
#if SCHED_BUG != 3
        sched_replay_held();
#endif
    }
    sched_crit_leave(s);
}

/* the urgent promotion (L2a, MEI open): the rest of the tick runs here, above a brain call */
void wh_urgent(uint32_t due)
{
    (void)due;
    if (!tick_running)
        return;
    COUNT(ticks_urgent);
    while (tick_running && audio_tick_slice())
        COUNT(slices);
    sched_tick_finish();
}
#endif

/* ---- L2b, and L2c below it ------------------------------------------------------------------------------------
 * L2b: the song tick's slices first (the song engine's; MTI masked per slice), then L2c: one job of the cart chip's
 * queue (l3_job, the work the cart chip's main loop did), with MSI open again, so a tick start posted meanwhile takes
 * a fresh L2b on top of it at once; a nested L2b leaves L2c to the one below (l2c_active), so the jobs run in order
 * from one context. Such a nested L2b has cleared MSIP before it looked, and the raise it cleared can be a job the
 * pass below has already looked past (l3_job has read the queue's indices, or is on its way back with 'nothing
 * queued'), so it says so (l2c_missed) and the pass below looks again before it leaves (fixed 2026-10-18; before that
 * the job was lost: the 68000 spun on $1FE6 bit 14 for good, as in the attract and Arena freezes we saw on the RV32
 * board model). The flag is cleared before MSI opens and read after it is masked again, so no nested L2b can set it
 * unseen. The cart FPGA's sprite decoder is RTL (MCU interface v1.2: no firmware decode at any level; earlier
 * versions had a stand-in on the wheel, in L2c and in L2b). The CPU MATE brain call is the thread's, below all of it
 * (B Jam's rule of 2026-10-15: the CPU buddy, which the game does not use all the time, must not slow everything else
 * down; earlier versions ran the call above the decoder and the jobs and held the SFX feeder for it, and on test build
 * 2 the game slowed, sound effects with it, in busy fights). On the cart the sub-CPU runs the call on its own; on
 * one CPU the game's work comes first and the call takes the time that is left. L1 preempts everything, as it
 * preempts L2b.
 * FW_S5: the engine queue's items take the slices' place: one item per look, MTI masked around it (atomic
 * against the urgent finish), then the look again; the jobs only when no item waits. An item queued by an L1 that
 * comes during L2c raises MSI, so it nests a fresh L2b above the pass at once (the 8C job waits for its module-start
 * item that way: core/dispatch/jobs.c); one queued during an item is seen by the next look. */
uint32_t sched_l2c_once(void)
{
    uint32_t r;
    if (l2c_active)
        return 0u;
    l2c_active = 1u;
    r = l3_job();
    l2c_active = 0u;
    return r;
}

void l2b_msi(void)
{
#if !PPM_RELEASE && !TDIAG_LEAN
    uint32_t was_active = sched_stats.l2b_active;
#endif
    ST_ENTER(ST_L2B);
    COUNT(l2b);
#if !PPM_RELEASE && !TDIAG_LEAN
    sched_stats.l2b_active = 1u;
#endif
    for (;;) {
#if SCHED_BUG != 2
        brd_msi(0u);                    /* clear first, then look: a raise after this point re-enters */
#endif
#if FW_S5
        if (song_work()) {
            uint32_t s, n = blk_seen, p = post_seen;    /* the blocks and posts before the item: its own
                                                           pass covers them */
#if SCHED_BUG != 10
            brd_lines_off(BRD_LINE_MTI);    /* an item is atomic against L2a (the urgent finish) */
#endif
            COUNT(slices);
            (void)song_run_one();
            s = sched_crit_enter();
            s5_urgent_arm();                /* the next tick that waits, or none */
            sched_crit_leave(s);
#if SCHED_BUG != 10
            brd_lines_on(BRD_LINE_MTI);     /* and the flush for MTI */
#endif
            blk_done = n;
            post_done = p;
            continue;
        }
        if (SONG_BUG == 33)
            blk_done = blk_seen;            /* planted: no pass after a block */
        if (blk_seen != blk_done || post_seen != post_done || pass_tail) {  /* the main-loop pass after a
                                                                              block, a post, or a job's tail */
            uint32_t s = sched_crit_enter(), n = blk_seen, p = post_seen, why;
            why = (pass_tail ? S5_PASS_TAIL : 0u) | (p != post_done ? S5_PASS_POST : 0u) |
                (n != blk_done ? S5_PASS_BLK : 0u);
            pass_tail = 0u;
            sched_crit_leave(s);
            brd_lines_off(BRD_LINE_MTI);    /* atomic against L2a, as an item */
            board_pass_bracket(why);
            brd_lines_on(BRD_LINE_MTI);
            blk_done = n;
            post_done = p;
            continue;
        }
#else
        if (tick_running) {
            uint32_t more;
            brd_lines_off(BRD_LINE_MTI);    /* a slice is atomic against L2a (the urgent promotion) */
            if (tick_running) {
                COUNT(slices);
                more = audio_tick_slice();
                if (!more)
                    sched_tick_finish();
            }
            brd_lines_on(BRD_LINE_MTI);     /* and the flush for MTI */
            continue;
        }
#endif
        if (!l2c_active) {
            uint32_t ran;
            l2c_missed = 0u;                /* (MSI masked: no nested L2b until the line below) */
            brd_lines_on(BRD_LINE_MSI);     /* L2c: a tick start raised from now on nests L2b above the pass */
            ran = sched_l2c_once();
            brd_lines_off(BRD_LINE_MSI);    /* back to L2b; a raise after this is seen by the look above */
            if (ran || l2c_missed)          /* l2c_missed is read with MSI masked: no nested L2b sets it after this */
                continue;
        }
#if SCHED_BUG != 9
        else {
            l2c_missed = 1u;                /* the raise cleared above may be a job the pass below has looked past */
        }
#endif
#if SCHED_BUG == 2
        brd_msi(0u);
#endif
        break;
    }
#if !PPM_RELEASE && !TDIAG_LEAN
    sched_stats.l2b_active = was_active;
#endif
    ST_LEAVE();
#if FW_S5 && (PPM_RELEASE || TDIAG_LEAN)
    SONG_FRAME_PAD16();                 /* test build 5 on: brain hygiene (core/song/song.h): RELEASE's
                                           epilogue, and since test build S3a the lean TEST image's (the
                                           same code there) */
#endif
}

/* ---- L3 ------------------------------------------------------------------------------------------------------- */
#if FW_MW
/* FW_MW: the game's sprite frame is open (AE taken, AF not yet: the cart chip's H+$401, disp_g.frame_open), so its
   AD / AF replies are still to come: the MegaWire task waits. A frame the thread first saw open longer than
   CLK_MW_SPRITE_MAX ago (the same AE: the multiplex count AE raises, H+$403) no longer holds it */
static uint8_t mw_spr_par;
static uint32_t mw_spr_t;
static uint32_t mw_sprite_wait(void)
{
    uint8_t p;
    if (!disp_g.frame_open)
        return 0u;
    p = disp_g.af_parity;
    if (p != mw_spr_par) {
        mw_spr_par = p;
        mw_spr_t = brd_now();
        return 1u;
    }
    return brd_now() - mw_spr_t < CLK_MW_SPRITE_MAX;
}
#endif

/* the thread: the CPU MATE brain call when one is pending (every interrupt open: L1, the wheel and the jobs preempt it; the glue's abort lands through the trap exit of whichever level interrupted it), then TEST's
   diagnostics (no deadline: the debug save, the SAT snapshot), then the idle housekeeping. The TEST counters keep the
   debug record's layout: the call is counted in the L2b slot, where it ran in earlier versions */
uint32_t sched_thread_once(void)
{
    if (brain_pending) {
        brain_pending = 0u;
        COUNT(brain_calls);
        ST_ENTER(ST_L2B);
#if SCHED_BUG == 6
        brd_lines_off(BRD_LINE_MSI);        /* planted: the jobs wait for the call */
#elif SCHED_BUG == 7
        brd_lines_off(BRD_LINE_MTI);        /* planted: the SFX feeder (the whole wheel) waits for the call */
#elif SCHED_BUG == 4
        brd_lines_off(BRD_LINE_MSI | BRD_LINE_MTI);     /* planted: everything but L1 waits for the call */
#endif
        brain_active = 1u;
        l3_brain();
        brain_active = 0u;
#if SCHED_BUG == 6
        brd_lines_on(BRD_LINE_MSI);
#elif SCHED_BUG == 7
        brd_lines_on(BRD_LINE_MTI);
#elif SCHED_BUG == 4
        brd_lines_on(BRD_LINE_MSI | BRD_LINE_MTI);
#endif
        ST_LEAVE();
        return 1u;
    }
#if FW_MW
    if (!s3_mw_checked) {                   /* the SRAM image's check, the thread's first work after the
                                               68000's release (core/mw/mw_boot.c): so the 68000 starts at the same
                                               time as in test build 5, before the MegaWire code; nothing calls into the
                                               image before it has passed */
        ST_ENTER(ST_L3_WORK);
        s3_mw_boot();
        ST_LEAVE();
        return 3u;
    }
    if (s3_mw_on && (mw_tk_ph != 0u || mw_due != mw_ran) && !mw_sprite_wait()) {
        /* the cart's MegaWire task (TIM7, core/mw), below the brain call: on the cart the sub-CPU runs CPU MATE beside
           the cart chip, so the MegaWire never delays it (in a test run with the tick above the call, 15 more words
           came late in 1,932 calls); with no module the tick has nothing a player can see. Once per L2a tick, as the
           cart's TIM7 runs it once a period: a tick the thread could not take in time (a long job) runs late, not
           dropped. In steps between the cart chip's own steps (mw_tick_part), one a thread step, and none starts while
           the game's sprite frame is open (up to CLK_MW_SPRITE_MAX) or a 68000 post waits in mailbox B: the cart's
           MegaWire work never delays its AD / AE / AF replies. The check is made again with the interrupts off and the
           step entered with them still off; the step opens them as its first act and leaves at once if a frame opened
           meanwhile (the multiplex count moved: an AE taken as they opened), so no step starts its work inside the
           bound after an AE; an AE during a step lets that one step end, the next waits for the AF or the bound */
        uint32_t s = sched_crit_enter();
        if (!mw_sprite_wait() && !(brd_cause() & BRD_CAUSE_B)) {
            uint32_t ph = mw_tk_ph, r;
            mw_chk_par = disp_g.af_parity;
            ST_ENTER(ST_L3_WORK);
            r = mw_tick_part(s);
            ST_LEAVE();
            if (ph == MW_PH_A && r != MW_STEP_YIELD)
                mw_ran = (uint8_t)(mw_ran + 1u);
            return 3u;
        }
        sched_crit_leave(s);
    }
    if (s3_mw_on && mw_scr_on && mw_tk_ph == 0u && MW16(mw, MW_SCREEN) != 0u &&
        ((disp_g.q_wr ^ disp_g.q_rd) & 0xFu) == 0u && (mw_scr.ph == 0u || brd_until(mw_scr.due) <= 0) &&
        s3_sram_cold_ok()) {
        /* the cart's MegaWire screen (A858): the cart chip's main loop calls its screen loop 0x080225F8 at the end of
           every pass while the screen state is not 0 and no job is queued (0x0801A672-0x0801A680); here one step of
           that call once its wait is over, below the tick and never between two of its steps (the cart chip's TIM7
           task interrupts its main loop, never the other way round; core/mw/mw_screen.c). No sprite wait here: after
           its A858 the game posts no sprite work (it jumps to cart RAM, then runs page A), and a frame it left open
           must not move the screen's times against the cart chip's. The idle path reads only resident state
           (mw_tk_ph, mw_scr_on): an SRAM load there would lengthen every wait for an interrupt
           (docs/MCU_INTERFACE.md 3.7, the costs) */
        ST_ENTER(ST_L3_WORK);
        mw_screen_step();
        ST_LEAVE();
        return 3u;
    }
#endif
    if (wheel_low_pending()) {
        wheel_low_run();                    /* TEST's debug save */
        return 2u;
    }
    if (l3_test_work())                     /* TEST's SAT snapshot */
        return 2u;
    l3_idle();
    return 0u;
}

void l3_thread(void)
{
    for (;;) {
        COUNT(l3_loops);
        (void)sched_thread_once();
    }
}

/* ---- exceptions (from the trap entry, interrupts off) --------------------------------------------------------- */
/* ours keeps 0.2.6's "move on" (the faulting instruction is skipped; RV32 without C: 4 bytes) without its s0/s1
   swap, and records the first one for the TEST boot milestones. An exception in a brain call's code aborts the
   call and turns the buddy off (buddy/, as 0.2.6's buddy_exc_brain did): the glue says where to resume. */
uint32_t sched_exception(uint32_t mcause, uint32_t mepc, uint32_t mtval)
{
    uint32_t r;
    if (sched_stats.exc++ == 0u) {
        sched_stats.exc_first_cause = mcause;
        sched_stats.exc_first_epc = mepc;
        sched_stats.exc_first_tval = mtval;
    }
    r = brain_fault(mepc);
    return r ? r : mepc + 4u;
}
