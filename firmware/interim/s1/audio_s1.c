/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* interim/s1/audio_s1.c - the interim audio on the scheduler's levels (the FW_S5 build leaves it out with the album
 * path; FW_S5 = the full firmware, board/board.h).
 *
 * 0.2.6 pushed the SFX samples from its main loop (sfx_player_update, one sample per playing channel per pass: the
 * FIFOs stayed nearly full) and, while a brain call ran, from a rate-aware feeder on an MTIME grid (buddy/zz_buddy.c,
 * hardware-tested in 0.2.6). The new firmware has no main loop: that feeder runs on the timer wheel (WH_FEED, L2a, the
 * timer interrupt level) at all times, on the same grid in time (CLK_FEED = 133.5 us, 7,168 cycles at NTSC), while any
 * channel has samples left (an earlier version held the slot for a CPU MATE brain call; since 2026-10-15 the call runs
 * below the wheel and never holds it); a tick late by m periods (behind L1 or a decoder request) is a catch-up, the
 * same full pass:
 *   - every tick each playing channel is pushed until its FIFO reads full, at most BUDDY_FEED_KMAX (48) samples: the
 *     0.2.6 main loop's "keep it full" on the grid. The glue's rate-aware k (ceil((P + J) / T) + 1: 8, 5, 3, 3, 2, 2
 *     for the six rates; k x (1 + m) for a tick late by m periods) only keeps a FIFO level, which suited a brain call
 *     that starts with full FIFOs; with k for the start and the grid, a young channel stays low for ~100 ticks and a
 *     long post (AF, 17.3k cycles, estimated) empties it (measured in tests/s1/audio_tests.c's FIFO model: 5 underruns
 *     in 4 x 120 s; 0 once the start fills the FIFO, whichever the grid pushes). Filling on the grid too gives back the
 *     main loop's margin after any stall; once full, a tick costs one status read per channel;
 *   - the per-sample code is sfx_player_update's (zz_buddy.c chan_batch, checked against it there: same flash byte,
 *     the same 4- / 8-bit conversion, the same pointer / size / step / loop bookkeeping);
 *   - the channel's rate is the one the start programs (interim/s1/sfx_s1.c, kept in s1_sfx_type): 0.2.6's glue looked
 *     it up in a hash of the SFX table it built in the SRAM scratch (0x08018000, MegaWire RAM once the MegaWire code
 *     landed); the value is the same (the table's rate, one step down with flag 0x0100: the cart chip's, 5 at most);
 *   - a channel that starts (D1; until 2026-10-17 also D3 re-arming a channel that had ended) is filled the same way
 *     right after the command, in L1 (0.2.6 feed_started gave it k); a start that waits (the cart chip's start delay:
 *     the echo voice; or a FIFO that still holds the last sound's samples, drained silent first: sfx_s1.c
 *     s1_sfx_pend) is started by the grid's next tick that finds it due (sfx_pend_run), and keeps the grid running
 *     meanwhile; a retrigger on the synth tick refills its channel and kicks it as a D1 does. A post that follows a
 *     start at once holds L1 for up to 17.3k cycles (AF) or 12k (88's fill), longer than k samples last (measured on
 *     the RV32 board model, with a bench outside this tree: a 12 kHz start with k = 3 ran dry inside the 88 that
 *     followed it); at most 48 pushes, ~2k cycles of L1; an idle grid starts then;
 *   - each channel's batch runs with interrupts off (L1's D1 / D2 / D3 change the same channel records); a post waits
 *     behind one channel's batch at most, never behind the whole pass (0.2.6's MIE windows between channels).
 * The Boom Box VU rows (interim/s1/vu_s1.c) run on the wheel (WH_VU) at the row's due instant on the 0.2.6 millisecond
 * grid, after a three-round top-up of the playing channels (a row holds L2a for 6-15k cycles). The song tick hooks are
 * empty here (the song engine of the FW_S5 build has its own). tick_ctr (0.2.6's channel age; the cart chip's channel
 * choice has no age, so nothing reads it) counts feeder ticks. MENU_MUTE_EN is set by the board boot
 * (board/pocket/s1_board.c): the RTL pauses the album and zeroes the SFX pair while the Pocket menu is open; the feeder
 * keeps pushing into the FIFOs meanwhile.
 * TEST: the ordered audio-call log (S1_AU_LOG entries in wram_upper), each call with the post count and the level.
 * Since 2026-10-15 (B Jam's decision: the CPU MATE must not slow everything else down): the same pushes in the same
 * ticks for about 40% fewer cycles a tick (feed_chans below; interim/README.md "The feeder's cost"). */
#include "appmain.h"
#include "sched.h"
#include "sched_hooks.h"
#include "disp.h"
#include "buddy.h"
#include "s1_interim.h"

extern u32 tick_ctr;                    /* (the channel records, S1SfxChan sfx_chan[8]: s1_interim.h, sfx_s1.c) */

/* AUDIO_BUG: planted bugs for tests/s1/audio_tests.c's negative controls only (fwbuild.json s1.host.negative; never
   defined in an image): 3 = a started channel's first batch only the glue's rate-aware k (2 is in vu_s1.c); 4 = the
   grid's pass does not look at feed_playing again after a channel (a channel an L1 starts above it waits for the next
   tick); 5 = a start's kick does not put the channel in feed_playing (the pass never looks at it) */
#ifndef AUDIO_BUG
#define AUDIO_BUG 0
#endif

/* the host test's FIFO model (tests/s1/audio_tests.c includes this file with its own hook); nothing on the Pocket */
#ifndef S1_PUSH_HOOK
#define S1_PUSH_HOOK(ch)        ((void)0)
#endif

static u32 feed_on;                     /* WH_FEED armed */
static u32 feed_playing;                /* every channel with samples left: set by the start's kick (D1, in the same
                                           L1 as sfx_play; a retrigger's, in the synth tick's L1) and by the pending
                                           starts the grid makes (sfx_pend_run, interrupts off), the only writers of a
                                           nonzero size; exact
                                           again at the end of each grid tick; a stopped or ended channel keeps its bit
                                           until then (a superset: the pass reads the size before it pushes) */

#if PPM_RELEASE
s1_audio_stats_t s1_audio_stats;
#else
s1_audio_stats_t s1_audio_stats __attribute__((section(".bss_upper")));   /* TEST: 14 words with the album's;
                                                       wram_data is tight (docs/STAGE1_PLAN.md 5.3) */
#endif

#if PPM_RELEASE
#define AS(f, n)                ((void)0)       /* the argument is not evaluated: never put work in it */
#else
#define AS(f, n)                (s1_audio_stats.f += (n))
#endif

/* the FIFO's full flag: SfxIO status bit 1 (fifo_full), read as the halfword the bitfield read loads (lhu at +0) */
typedef volatile const u16 __attribute__((may_alias)) sfx_status16;
#define SFX_FULL(io)            (*(sfx_status16 *)(const void *)&(io)->status & 2u)

/* up to k pushes into channel ch (k >= 1; the channel has samples left), as zz_buddy.c chan_batch does; returns the
   pushes made. The per-sample code is sfx_player_update's: the same flash byte, 4- / 8-bit conversion, pointer / size
   / step / loop bookkeeping, and the same status read before every push. Since 2026-10-15: the first status read
   comes before the channel record is loaded (a FIFO still full from the last tick costs one read: the slow rates'
   common case), each format has its own loop, and a sample's only taken branch is the loop's */
static inline __attribute__((always_inline)) u32 chan_batch(S1SfxChan *c, SfxIO *io, const u8 *fl, u32 ch, u32 k)
{
    u32 ptr, size, n = 0u;
    (void)ch;                                           /* (the host test's FIFO model only) */
    if (SFX_FULL(io))
        return 0u;
    ptr = c->ptr;
    size = c->size;
    if (c->step_num == 2) {                             /* 4-bit: two samples a byte, the high nibble first */
        u32 step = c->step;
        int byte = fl[ptr ^ 1];                         /* the byte both nibbles come from (step 1: the low one is
                                                           next, of the byte read again, as 0.2.6 does) */
        if (step)
            goto low;
        for (;;) {
            io->sample = ((((byte >> 4) & 0x0F) * 65536) / 16) - 32768;   /* the high nibble */
            S1_PUSH_HOOK(ch);
            n++;
            step = 1;
            if (__builtin_expect(--size == 0, 0)) {
                if (!c->looped)
                    break;
                ptr = c->ptr_base;                      /* (step stays 1: the low nibble of the first byte is next) */
                size = c->size_base;
                if (size == 0)
                    break;
                byte = fl[ptr ^ 1];
            }
            if (n == k || SFX_FULL(io))
                break;
low:
            io->sample = (((byte & 0x0F) * 65536) / 16) - 32768;          /* the low nibble */
            S1_PUSH_HOOK(ch);
            n++;
            step = 0;
            ptr++;
            if (__builtin_expect(--size == 0, 0)) {
                if (!c->looped)
                    break;
                ptr = c->ptr_base;
                size = c->size_base;
                if (size == 0)
                    break;
            }
            if (n == k || SFX_FULL(io))
                break;
            byte = fl[ptr ^ 1];
        }
        c->step = step;
    } else {
        for (;;) {
            int sample = fl[ptr ^ 1];
            ptr++;
            sample = (((sample & 0xFF) * 65536) / 256) - 32768;
            io->sample = sample;
            S1_PUSH_HOOK(ch);
            n++;
            if (__builtin_expect(--size == 0, 0)) {
                if (!c->looped)
                    break;
                ptr = c->ptr_base;
                size = c->size_base;
                if (size == 0)
                    break;
            }
            if (n == k || SFX_FULL(io))
                break;
        }
    }
    c->ptr = ptr;
    c->size = size;
    return n;
}

#if AUDIO_BUG == 3
/* the glue's rate-aware k (zz_buddy.c bud_k_by_rate; the divider table /1 /2 /4 /5 /8 /10 of audio_sfx): pushes per
   grid tick by rate index, for audio_tests.c's negative control 3 only */
static const u8 k_by_rate[8] = { 8, 5, 3, 3, 2, 2, 2, 2 };
static u32 chan_k(u32 ch, u32 m)
{
    u32 k = k_by_rate[(s1_sfx_type[ch] >> 4) & 7u] * m;
    return k > BUDDY_FEED_KMAX ? BUDDY_FEED_KMAX : k;
}
#endif

static u32 playing_mask(void)
{
    u32 ch, m = 0;
    for (ch = 0; ch < 8u; ch++)
        m |= (u32)(sfx_chan[ch].size != 0) << ch;
    return m;
}

/* the channels of m with samples left, in channel order, each pushed until its FIFO reads full (at most
   BUDDY_FEED_KMAX), one channel at a time with interrupts off (an L1 may come between two channels). pass = the grid's
   pass: m is feed_playing, read again after each channel fed, so a channel an L1 starts above the one just fed is fed
   in this pass too (the other channels have no samples: feed_playing holds every one that has). Returns the pushes
   made (the caller counts them, interrupts off). A leaf, the batch inlined: no registers to save */
static __attribute__((noinline)) u32 feed_chans(u32 m, u32 pass)
{
    S1SfxChan *c = sfx_chan;
    SfxIO *io = ppmio.sfx;
    const u8 *fl = ppmio.flash;
    u32 ch = 0u, tot = 0u;
    for (; m; m >>= 1, ch++, c++, io++) {
        if (m & 1u) {
            u32 s = brd_irq_save();
            if (c->size)
                tot += chan_batch(c, io, fl, ch, BUDDY_FEED_KMAX);
            brd_irq_restore(s);
            if (pass && AUDIO_BUG != 4)
                m = feed_playing >> ch;             /* again: an L1 may have started a channel above this one */
        }
    }
    return tot;
}

/* the grid (L2a, MEI open) */
void wh_feed(uint32_t due)
{
    uint32_t per = s1_clk(CLK_FEED);               /* opaque: the compiler folds no product of it */
    uint32_t next = due + per, m = 1u, s, fp, live, n, b;
    const S1SfxChan *c;
    if (brd_until(next) <= 0) {                     /* late (a long section, the brain call's hold) */
        while (brd_until(next) <= 0 && m <= BUDDY_FEED_CATCHUP) {   /* late by m - 1 whole periods (counted) */
            next += per;
            m++;
        }
        if (brd_until(next) <= 0)                   /* far behind: the grid starts again */
            next = brd_now() + per;
    }
    if (m > 1u)
        AS(catchups, 1u);
    AS(ticks, 1u);
    tick_ctr++;
    if (s1_sfx_pend) {                              /* the starts that wait (a delay, a FIFO draining: sfx_s1.c) */
        s = brd_irq_save();
        feed_playing |= sfx_pend_run();
        brd_irq_restore(s);
    }
    n = feed_chans(feed_playing, 1u);
    s = brd_irq_save();                             /* a D1 may have started a channel during the pass */
    AS(pushes, n);
    fp = live = feed_playing;                       /* playing_mask(): only feed_playing's channels can have samples */
    for (b = 1u, c = sfx_chan; b <= fp; b <<= 1, c++)
        if ((fp & b) && !c->size)
            live &= ~b;
    feed_playing = live;
    feed_on = (live | s1_sfx_pend) != 0u;
    if (feed_on)
        wheel_arm(WH_FEED, next);
    brd_irq_restore(s);
    (void)n;
}

/* the SFX channels' block count (interim/s1/sfx_s1.c): three of the cart chip's mix blocks, 10 ms, in cycles. Here
   and not in sfx_s1.c: that file is in the WRAM code window, which carries no clock figure (tests/check_clock.py
   --images) */
uint32_t s1_sfx_blk3(void)
{
    return s1_clk(CLK_MS_CYCLES) * 10u;
}

/* L1, after a D1 body (since 2026-10-17 D3 starts nothing): a channel that has just started gets its first batch now,
   and an idle grid starts */
void s1_sfx_kick(void)
{
    u32 mask = playing_mask(), nw = mask & ~feed_playing, n;
#if AUDIO_BUG == 3
    u32 ch;
    for (ch = 0, n = 0; ch < 8u; ch++)
        if (nw & (1u << ch))
            n += chan_batch(&sfx_chan[ch], &ppmio.sfx[ch], ppmio.flash, ch, chan_k(ch, 1u));
#else
    n = nw ? feed_chans(nw, 0u) : 0u;               /* interrupts are off in L1: the sections are empty */
#endif
    AS(pushes, n);
    for (; nw; nw &= nw - 1u)
        AS(first_batches, 1u);
    feed_playing = AUDIO_BUG == 5 ? feed_playing : playing_mask();
    (void)n;
    if (!feed_on && (feed_playing | s1_sfx_pend)) {
        feed_on = 1u;
        wheel_arm(WH_FEED, brd_now() + CLK_FEED);
    }
}

/* ---- the VU rows ------------------------------------------------------------------------------------------------ */
void s1_vu_kick(void)                               /* after a start or a stop (vu_s1.c): the next row, or none */
{
    uint32_t t;
    if (s1_vu_deadline(&t))
        wheel_arm(WH_VU, t);
    else
        wheel_disarm(WH_VU);
}

void wh_vu(uint32_t due)
{
    (void)due;
    if (feed_playing) {                             /* the row holds L2a for 6-15k cycles: topped up first */
        u32 n = feed_chans(feed_playing, 1u), s = brd_irq_save();
        AS(pushes, n);
        brd_irq_restore(s);
        (void)n;
    }
    if (s1_vu_update())
        AS(vu_rows, 1u);
    s1_vu_kick();
}

/* ---- the song tick: empty here (the 9494 finishes inline in L1) ------------------------------------------------- */
/* except the cart chip's per-channel SFX fade (D2 / D3 with a step; B Jam's decision of 2026-10-16), which the cart
   chip runs on its synth tick: the 9494 head with the mixer up (core/dispatch f_tick) counts frames, and at 60 Hz the
   6th frame skips the synth tick (the frame skip: the counter at 6 -> 0, skipped); at 50 Hz
   (5 -> 0) none is skipped. The cart chip takes 50 / 60 from 83's measurement (core/dispatch disp_83_check); here the
   PAL option bit (0 in every Pocket build). Where the cart chip's counter starts against ours is not known (both count
   from the first 9494 after C6 here, an estimate) */
static uint8_t tick_frames;                     /* the cart chip's frame counter */
uint32_t audio_tick_begin(uint32_t stamp)
{
    (void)stamp;
    tick_frames++;
    if (brd_options() & BRD_OPT_PAL) {
        if (tick_frames >= 5u)
            tick_frames = 0u;
    } else if (tick_frames >= 6u) {
        tick_frames = 0u;
        return 0u;                              /* NTSC: the 6th frame has no synth tick */
    }
    if (disp_g.sfx_ready)                       /* the fade tick's SFX part needs the SFX engine (C6) */
        sfx_fade_tick();
    return 0u;
}
uint32_t audio_tick_slice(void) { return 0u; }
void audio_tick_end(void) { }

/* ---- TEST: the ordered audio-call log ---------------------------------------------------------------------------- */
#if !PPM_RELEASE
s1_au_log_t s1_au_log __attribute__((section(".bss_upper")));
void s1_au_note(uint32_t kind, uint32_t arg)
{
    uint32_t s = brd_irq_save();
    s1_au_log.e[s1_au_log.n & (S1_AU_LOG - 1u)] = (kind << 24) | ((arg & 0xFFu) << 16) |
                                                  ((sched_stats.posts_a + sched_stats.posts_b) & 0xFFFFu);
    s1_au_log.n++;
    brd_irq_restore(s);
}
#endif
