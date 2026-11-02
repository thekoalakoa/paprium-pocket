/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/audio_tests.c - host test of the interim audio on the stage-1 levels (FW_S1, our new firmware; the levels
 * are the scheduler's, core/sched/sched.h) on the x86 fake board: the
 * SFX feeder and the VU rows on the timer wheel (interim/s1/audio_s1.c, included below with a push hook), the real
 * sfx_play / sfx_loop / sfx_d2 / sfx_stop (interim/s1/sfx_s1.c: the chip's channels) and the real VU rows
 * (interim/s1/vu_s1.c). The synthetic bank's formats are the chip's (1 = 8-bit, 2 = 4-bit). Built and run by
 * tools/fwbuild.py s1 (and at the PAL clock by tests/check_clock.py --images); exit 1 on a failed check.
 *
 * The SFX FIFO model (a model written from the RTL's audio_sfx: 256 samples deep, one out every CLK_HZ x divider /
 * 48,000 cycles while not empty; the full flag is what the feeder reads before each push): an UNDERRUN is a FIFO found
 * empty while its channel still has samples to push (sfx_chan size != 0) after it was fed; a channel's first batch
 * comes in L1 right after its start, so a start is not an underrun until it was fed once.
 * The load: the 68000 posts (L1, interrupts off) at random, most short, one long (17,300 cycles, AF's estimated worst)
 * each frame, a third of them starting an SFX (all six rates, 4- and 8-bit, some looped, some stopped); the thread
 * runs long preemptible jobs; a VU module runs its rows; the Pocket menu bit is never touched (the RTL's mute).
 *   A1  0 underruns over 4 x 120 s of model time (the six rates, 48 kHz included although the bank's fastest is 24 kHz);
 *       every sample of a non-looped SFX left alone is pushed (its record ends at 0); the FIFO never overflows (the
 *       feeder respects the full flag). With the glue's rate-aware k for the start and the grid this run had 5
 *       underruns (measured 2026-10-11), with filling to full 0: interim/s1/audio_s1.c
 *   A2  the grid: one feeder tick per CLK_FEED while a channel plays, none when idle; tick_ctr counts them
 *   A3  the VU rows: each on the 0.2.6 ms grid ((2 x header[7] + FA) x 10.01257 ms), within one board-timer step of the
 *       instant s1_ms() reaches it; a stop (8D) in the middle of a row leaves every bar at 0
 *   A4  the ordered audio-call log (TEST): one entry per sfx_play / sfx_loop / sfx_stop, in call order
 *   A5  a start followed at once by a long post (AF's 17.3k cycles in L1): no underrun at any rate (the first batch
 *       fills the FIFO; with the glue's k it ran dry: negative control 3)
 *   A6  (the pass looks only at feed_playing's channels) at every board point with no section open, every
 *       channel with samples left is in feed_playing (negative control 5: the kick leaves it out); a start an L1 makes
 *       in the middle of the grid's pass, right after channel 2's batch, is fed in that same pass when its channel is
 *       above 2 (the kick's 48 pushes, then the pass's 48) and only by its kick when below (negative control 4: the
 *       pass does not look at feed_playing again)
 * The chip's SFX laws (since 2026-10-17, B Jam's decision of 2026-10-16; interim/s1/sfx_s1.c since 2026-10-19; D31 and
 * the other D-numbers are the differences of our firmware audit):
 *   A7  levels: the boot-built level table equals the chip's start-up table on all 512 entries through D1 and D3
 *       (the RTL volume for every v 0-511; FF -> 191, C0 -> 108: -4.95 dB, the cart's -5.0 dB on the punk TV); D3
 *       takes the lowest channel of its mask only
 *   A8  the loop flag (D31): D1 flags bit 15 loops the channel by itself (no D3), gapless, the same samples every pass
 *       (each push checked against the bank), and never reaches the RTL's pitch bits: with audio_sfx's rule (flags[7]
 *       -> pitch 31, one tick in 32 skipped) the FIFO model plays a 29,920-sample 6 kHz cue in 4.98667 s, not 5.1475;
 *       without bit 15 the sound ends after one pass, and a D3 no longer re-arms it
 *   A9  D2 / D3 steps on the synth tick (the 9494 with the mixer up; NTSC skips every 6th frame; a channel moves on
 *       every other tick by its parity): D1 FF looped + D2 step 6 at once (the corpus pattern) -> 43 updates of -6
 *       on alternate ticks, freed (no more samples, volume 0) at level 0, after 86 ticks = 103 +- 1 frames (1.72 s);
 *       D2 0 and D2 on a level-0 channel free at once; D3 step 1 walks level and pan by 1 an update
 *   A10 the punk TV and the pause: D1 vol 0 looped on channel 7, a D3 level ramp each frame, then 10 s with no SFX
 *       post (the pause: the game posts no D3) -> the cue keeps looping on its own; then D3 0 (volume 0 at once) and
 *       D2 0 a frame later (freed, nothing pushed after)
 * The chip's channels (since 2026-10-19, B Jam's decision of 2026-10-18 / 19 after the Block 888 cell alarm;
 * interim/s1/sfx_s1.c):
 *   A11 the cell: a looped cue on channel 6 fading out (D2 1) when a looped D1 with mask 0x40 comes: it takes
 *       channel 6 (never channel 0: 0.2.6 put it there and nothing stopped it), at full level (the old fade gone), and
 *       a D2 0 stops it: nothing pushed after on any channel. No free channel in the mask: the quietest is taken, and
 *       of equal levels the one furthest along (negative control 6: 0.2.6's choice)
 *   A12 flags 0x4000 in the cart-DAC mode: the echo voice on the next channel, as the chip makes it;
 *       none in the YM-DAC mode (88 bit 0)
 *   A13 flags 0x2000 with a pan off 0x80: the chip's two-voice spread at the sound's own rate (no RTL half rate),
 *       both voices started by the
 *       same grid tick (none in the D1's L1: FZ12's budget); at pan 0x80 one voice
 *   A14 flags bits 10-11 = n: 2n restarts of the sound (every second synth tick)
 *   A15 flags 0x0100: the chip's rate step and trim (rate 2); at rate 5 neither
 *   A16 D5 (the SFX echo switch) leaves the loops on channels 6 and 7 playing (negative control 7: 0.2.6's stop)
 *   A17 the block count after a 50 s idle with no query: a 217-block one-shot holds its channel 215 blocks in and has
 *       let it go 219 blocks in
 *   A18 the block count itself (sfx_s1.c is included here, not linked): reads at, just before and just after 3,000
 *       boundaries and after gaps of up to 79 s equal a walk of the grid (negative control 8) */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "board.h"
#include "sched.h"
#include "sched_hooks.h"

static void fifo_push(unsigned ch);
#define S1_PUSH_HOOK(ch)        fifo_push(ch)
#include "audio_s1.c"
#include "sfx_s1.c"                             /* (included, not linked: A18 reads its block count) */
#undef printf                                   /* interim/s1/appmain.h drops printf on the Pocket */

static int fails, checks;
#define CHECK(c) do { checks++; if (!(c)) { fails++; printf("FAIL audio_tests.c:%d %s\n", __LINE__, #c); } } while (0)

/* ---- what the moved 0.2.6 code needs (bodies_s1.c / mame.c on the Pocket) -------------------------------------- */
#include <math.h>
disp_state_t disp_g;                            /* (core/dispatch: audio_tick_begin reads sfx_ready) */
ppm_io ppmio;
u32 ppm_sfx_base_addr;
u32 tick_ctr;
u32 swapshorts(u32 v) { return (v << 16) | (v >> 16); }

/* ---- the FIFO model ----------------------------------------------------------------------------------------- */
#define FDEPTH  256
static SfxIO fio[8];
static struct { int level, fed; uint64_t due, first, t1; uint32_t pushes, underruns, overflow, maxl, since; int s1; } F[8];
static const uint32_t DIV[8] = { 1, 2, 4, 5, 8, 10, 10, 10 };
/* one sample out every CLK_HZ x div / 48,000 cycles; audio_sfx's pitch rule (flags[7] -> pitch 31: one tick in 32
   skipped; flags[5] -> pitch 1: one in 2) as the average period */
static uint32_t per_sample(unsigned ch)
{
    uint64_t c = (uint64_t)BRD_CLK_HZ * DIV[(fio[ch].type >> 4) & 7];
    if (fio[ch].flags & 0x80u)
        return (uint32_t)(c * 32u / 31u / 48000u);
    if (fio[ch].flags & 0x20u)
        return (uint32_t)(c * 2u / 48000u);
    return (uint32_t)(c / 48000u);
}

static void fifo_sync(void)
{
    unsigned ch;
    for (ch = 0; ch < 8; ch++) {
        if (F[ch].level <= 0)
            F[ch].due = hb.cycles;
        while (F[ch].level > 0 && F[ch].due <= hb.cycles) {
            F[ch].level--;
            F[ch].due += per_sample(ch);
        }
        fio[ch].status.fifo_full = F[ch].level >= FDEPTH;
        fio[ch].status.fifo_empry = F[ch].level == 0;
    }
}

static int seq_ch = -1;                         /* A8 / A10: every push of this channel checked against the bank */
static uint32_t seq_n, seq_bad, seq_off, seq_len;
static uint8_t flash[0x100000];
static int16_t nib_value(uint32_t k)            /* sample k (4-bit) of the entry at seq_off: high nibble first */
{
    uint8_t b = flash[(seq_off + (k >> 1)) ^ 1u];
    uint32_t n = (k & 1u) ? (b & 0x0Fu) : (uint32_t)(b >> 4);
    return (int16_t)(((n * 65536u) / 16u) - 32768);
}

static void fifo_push(unsigned ch)
{
    if ((int)ch == seq_ch) {
        if (fio[ch].sample != nib_value(seq_n % seq_len))
            seq_bad++;
        seq_n++;
    }
    fifo_sync();
    if (F[ch].level == 0)
        F[ch].due = hb.cycles + per_sample(ch);
    if (F[ch].level < FDEPTH)
        F[ch].level++;
    else
        F[ch].overflow++;
    if ((uint32_t)F[ch].level > F[ch].maxl)
        F[ch].maxl = (uint32_t)F[ch].level;
    if (!F[ch].pushes) {                            /* A11-A17: the first sample pushed and when */
        F[ch].s1 = fio[ch].sample;
        F[ch].t1 = hb.cycles;
    }
    F[ch].pushes++;
    if (!F[ch].fed) {
        F[ch].first = hb.cycles;
        F[ch].since = 0;
    }
    F[ch].since++;
    F[ch].fed = 1;
    fio[ch].status.fifo_full = F[ch].level >= FDEPTH;
    fio[ch].status.fifo_empry = 0;
}

static uint32_t stop_in_row, stop_points;       /* A3: post the 8D at the 6th board point inside an L2a (the row) */
static uint32_t inv_breaks, inv_points;         /* A6: a channel with samples left outside feed_playing (no section open) */
static uint32_t mid_word, mid_after, mid_base;  /* A6: a post made in the grid's pass, after channel mid_after's batch */
static void on_point(void)
{
    unsigned ch;
    if (hb.mstatus_mie) {
        inv_points++;
        for (ch = 0; ch < 8; ch++)
            if (sfx_chan[ch].size && !(feed_playing & (1u << ch)))
                inv_breaks++;
    }
    if (mid_word && hb.level == BRD_LINE_MTI && hb.mstatus_mie && F[mid_after].pushes != mid_base) {
        hb_68k_write(BRD_FREG_FEA, (uint16_t)mid_word);       /* L1 takes it at this very point */
        mid_word = 0;
    }
    if (stop_in_row && hb.level == BRD_LINE_MTI && hb.mstatus_mie) {
        if (++stop_points == 6u) {
            stop_in_row = 0;
            hb_68k_write(BRD_FREG_FEA, 0x8D00u);              /* L1 takes it at this very point */
        }
    } else if (stop_in_row) {
        stop_points = 0;
    }
    fifo_sync();
    for (ch = 0; ch < 8; ch++)
        if (!sfx_chan[ch].size)
            F[ch].fed = 0;                              /* ended or stopped: the FIFO drains; a new start counts once fed */
        else if (F[ch].level == 0 && F[ch].fed) {
            F[ch].underruns++;
            if (F[ch].underruns + F[(ch + 1) & 7].underruns < 12u)
                fprintf(stderr, "underrun ch %u rate %u: %u pushes in %lu cycles since its first, level %d, L%u\n", ch,
                        (fio[ch].type >> 4) & 7, F[ch].since, (unsigned long)(hb.cycles - F[ch].first), F[ch].level, hb.level);
            F[ch].fed = 0;                              /* counted once until it is fed again */
        }
}

/* ---- a synthetic SFX bank and VU module (no game byte) ----------------------------------------------------------- */
#define SFX_BASE    0x1000u
#define N_SFX       24
#define CUE_ID      25u                         /* A8 / A10: a 29,920-sample 4-bit entry at 6 kHz (the TV cue's shape) */
#define CUE_LEN     29920u
#define CUE_OFF     (0x400u + CUE_ID * 0x8000u)  /* the entry's offset: the samples sit at SFX_BASE + CUE_OFF */
static void bank(void)
{
    unsigned i;
    ppm_sfx_base_addr = SFX_BASE;
    for (i = 1; i <= N_SFX; i++) {
        uint8_t *e = &flash[SFX_BASE + i * 8u];
        uint32_t off = 0x400u + i * 0x8000u, size = 1500u + (i * 7919u) % 30000u;
        uint32_t sw = swapshorts(off);
        uint8_t rate = (uint8_t)((i - 1u) % 6u), step = (i % 3u == 0u) ? 2u : 1u;   /* the format: 2 = 4-bit, 1 = 8-bit */
        memcpy(&e[0], &sw, 4);
        e[4] = (uint8_t)(size >> 16);
        e[5] = (uint8_t)((rate << 4) | step);
        e[6] = (uint8_t)size;
        e[7] = (uint8_t)(size >> 8);
    }
    for (i = 0; i < sizeof flash; i++)
        if (i >= 0x400u + 0x8000u)
            flash[i] = (uint8_t)(i * 31u);
    {
        uint8_t *e = &flash[SFX_BASE + CUE_ID * 8u];
        uint32_t sw = swapshorts(CUE_OFF);
        memcpy(&e[0], &sw, 4);
        e[4] = (uint8_t)(CUE_LEN >> 16);
        e[5] = (uint8_t)((4u << 4) | 2u);       /* rate index 4 (6,000 Hz), 4-bit */
        e[6] = (uint8_t)CUE_LEN;
        e[7] = (uint8_t)(CUE_LEN >> 8);
        for (i = 0; i < CUE_LEN / 2u; i++)
            flash[(SFX_BASE + CUE_OFF + i) ^ 1u] = (uint8_t)(i * 7u + (i >> 5));
    }
}

/* a VU module at SDRAM 0x10000 (68000 byte order: the MCU byte a ^ 1): 1 section, 6 bars, base 3 (2 x 3 ticks a row),
   voice v's bar pointer at 0xD8 + v * 2, bar r of voice v non-zero when (v + r) is odd; event FA operand 2 on bar 1 */
#define VU_MOD      0x10000u
static void vu_module(void)
{
    uint8_t *m = (uint8_t *)hb.workspace + VU_MOD;
    unsigned v, r;
#define MB(o, x) (m[(o) ^ 1u] = (uint8_t)(x))
    MB(0x07, 3);
    MB(0x08, 1);
    MB(0x09, 0);
    MB(0x0A, 6);
    for (v = 0; v < 26u; v++) {
        uint32_t ptr = 0x200u + v * 0x40u;
        MB(0xD8 + v * 2u, ptr >> 8);
        MB(0xD9 + v * 2u, ptr);
        for (r = 0; r < 6u; r++)
            MB(ptr + r, ((v + r) & 1u) ? 1 : 0);
        MB(ptr + 6u + 8u + 2u, (v == 3u) ? 0xFA : 0x00);   /* event of idx 1 (+ bars 6 + idx 1 * 8), word 2 */
        MB(ptr + 6u + 8u + 3u, 0x02);
    }
#undef MB
}

/* ---- the levels' bodies: L1 posts, L3 jobs ---------------------------------------------------------------------- */
static uint32_t rnd_s = 1;
static uint32_t rnd(void) { rnd_s ^= rnd_s << 13; rnd_s ^= rnd_s >> 17; rnd_s ^= rnd_s << 5; return rnd_s; }
static void burn(uint32_t cyc)                  /* time spent in a body, with board points every 64 cycles */
{
    while (cyc) {
        uint32_t d = cyc > 64u ? 64u : cyc;
        hb.now += d;
        hb.cycles += d;
        cyc -= d;
        (void)brd_now();
    }
}

static uint32_t started, stopped_ch, looped_n, au_expect;
void disp_post(uint32_t mbx, uint16_t word)
{
    uint8_t lo = (uint8_t)word;
    (void)mbx;
    burn((word & 0x4000u) ? 17300u : 300u + rnd() % 2500u);
    if (word == 0x8D00u) {                      /* 8D: the VU rows stop (body_8d) */
        s1_vu_stop();
    } else if (lo >= 0x40u && lo < 0x48u) {     /* A6: SFX 1 (48 kHz, 8-bit) started on channel lo - 0x40 */
        uint16_t *args = (uint16_t *)(void *)hb.ram;
        args[0x1E10 / 2] = (uint16_t)(1u << (lo - 0x40u));
        args[0x1E12 / 2] = 0x80;
        args[0x1E14 / 2] = 0x40;
        args[0x1E16 / 2] = 0;
        sfx_play(1);
        s1_sfx_kick();
        au_expect++;
    } else if (lo && lo <= N_SFX) {             /* a D1: the body_d1 order (sfx_play, then the first batch) */
        uint16_t *args = (uint16_t *)(void *)hb.ram;
        args[0x1E10 / 2] = (uint16_t)(1u << (rnd() % 8u));
        args[0x1E12 / 2] = 0x80;
        args[0x1E14 / 2] = 0x40;
        args[0x1E16 / 2] = (rnd() % 5u == 0u) ? 0x0100u : 0u;
        sfx_play(lo);
        s1_sfx_kick();
        started++;
        au_expect++;
        if (rnd() % 7u == 0u) {                 /* D3: the chip's level / pan update (the lowest channel of the mask;
                                                   it no longer loops or re-arms: D31) */
            args[0x1E10 / 2] = 0x80;
            args[0x1E12 / 2] = 0x40;
            args[0x1E14 / 2] = 0;
            sfx_loop((u8)(args[0x1E10 / 2] ? 0xFFu : 0u));
            s1_sfx_kick();
            looped_n++;
            au_expect++;
        }
    } else if (lo == 0xF0u) {                   /* 0.2.6's stop entry (sfx_stop: now the chip's D5, no channel) */
        uint16_t *args = (uint16_t *)(void *)hb.ram;
        args[0x1E10 / 2] = 0;
        sfx_stop(0xFFu);
        stopped_ch++;
        au_expect++;
    }
    brd_freg_wr(BRD_FREG_FEA, 0u);
}
uint32_t disp_holdable(uint32_t mbx, uint16_t word) { (void)mbx; (void)word; return 0u; }
static uint32_t job_cycles;
uint32_t l3_job(void)
{
    if (!job_cycles)
        return 0u;
    burn(job_cycles > 4096u ? 4096u : job_cycles);
    job_cycles -= job_cycles > 4096u ? 4096u : job_cycles;
    return 1u;
}

static uint32_t next_post;
static void run(uint64_t cyc)                   /* the 68000 side and time */
{
    uint64_t end = hb.cycles + cyc;
    uint32_t frame_t = hb.now;
    while (hb.cycles < end) {
        if ((int32_t)(hb.now - next_post) >= 0 && brd_freg_rd(BRD_FREG_FEA) == 0u) {
            uint32_t r = rnd() % 100u;
            uint16_t w = 0x8000u;
            if (r < 33u)
                w |= (uint16_t)(1u + rnd() % N_SFX);
            else if (r < 34u)
                w |= 0xF0u;
            if ((int32_t)(hb.now - frame_t) >= (int32_t)(CLK_MS_CYCLES * 16u)) {   /* one long post a frame */
                frame_t = hb.now;
                w |= 0x4000u;
            }
            hb_68k_write(BRD_FREG_FEA, w);
            next_post = hb.now + 20000u + rnd() % 160000u;
        }
        if (!job_cycles && rnd() % 64u == 0u)
            job_cycles = 50000u + rnd() % 2000000u;
        (void)sched_l2c_once();                 /* L2c's pass (core/sched; the thread in an earlier version) */
        burn(64u);
    }
}

static void boot(uint32_t seed)
{
    hb_reset();
    memset(F, 0, sizeof F);
    memset(fio, 0, sizeof fio);
    memset(sfx_chan, 0, sizeof sfx_chan);
    memset(&s1_audio_stats, 0, sizeof s1_audio_stats);
    memset(&s1_au_log, 0, sizeof s1_au_log);
    feed_on = feed_playing = 0u;
    tick_ctr = 0;
    rnd_s = seed * 2654435761u + 1u;
    stop_in_row = stop_points = 0u;
    hb.on_point = on_point;
    ppmio.ramdp = (ppm_ramdp *)(void *)hb.ram;
    ppmio.flash = flash;
    ppmio.sdram = (u8 *)(uintptr_t)hb.workspace;
    ppmio.sfx = fio;
    bank();
    vu_module();
    sfx_level_init();
    memset(&disp_g, 0, sizeof disp_g);
    seq_ch = -1;
    sched_init();
    brd_cause_ack(BRD_CAUSE_ALL);
    brd_lines_on(BRD_LINES_ALL);
    brd_irq_enable();
    next_post = hb.now + 1000u;
    started = stopped_ch = looped_n = au_expect = 0;
}

/* ---- the chip's SFX laws (A7-A10) --------------------------------------------------------------------------------- */
static uint16_t *args_ram(void) { return (uint16_t *)(void *)hb.ram; }
static void post_d1(uint8_t id, uint16_t mask, uint16_t vol, uint16_t pan, uint16_t flags)    /* body_d1, in L1 */
{
    uint32_t s = brd_irq_save();
    args_ram()[0x1E10 / 2] = mask;
    args_ram()[0x1E12 / 2] = vol;
    args_ram()[0x1E14 / 2] = pan;
    args_ram()[0x1E16 / 2] = flags;
    sfx_play(id);
    s1_sfx_kick();
    brd_irq_restore(s);
}
static void post_d3(uint8_t mask, uint16_t vol, uint16_t pan, uint16_t step)                  /* body_d3, in L1 */
{
    uint32_t s = brd_irq_save();
    args_ram()[0x1E10 / 2] = vol;
    args_ram()[0x1E12 / 2] = pan;
    args_ram()[0x1E14 / 2] = step;
    sfx_loop(mask);
    brd_irq_restore(s);
}
static void post_d2(uint8_t mask, uint16_t arg)                                               /* body_d2, in L1 */
{
    uint32_t s = brd_irq_save();
    args_ram()[0x1E10 / 2] = arg;
    sfx_d2(mask);
    brd_irq_restore(s);
}
static void frame(void)                         /* one NTSC frame: the 9494 head (f_tick, L1), then the frame's time */
{
    uint32_t s = brd_irq_save();
    (void)audio_tick_begin(brd_now());
    brd_irq_restore(s);
    burn((uint32_t)((uint64_t)BRD_CLK_HZ * 1000u / 59923u));
}
/* the chip's level table T from its formula (core/tables README, measured equal to the chip's RAM after C6): T[k] =
   min(255, ceil(256 exp((k - 255) / 64))) for k = 2..255, T[0] = T[1] = 0, T[256 + j] = 255 + j; every value keeps
   >= 1e-3 from an integer, so the host's exp is exact enough. Independent of the firmware's fixed-point build */
static uint32_t chip_T(uint32_t k)
{
    double x;
    if (k < 2u)
        return 0u;
    if (k >= 256u)
        return 255u + (k - 256u);
    x = ceil(256.0 * exp(((double)k - 255.0) / 64.0));
    return x > 255.0 ? 255u : (uint32_t)x;
}
/* the chip's level for a posted v, as the RTL volume: (T[v] + v) / 2 (9 bits) x 96 / 128 */
static uint32_t lvl_vol(uint32_t v) { return ((chip_T(v & 0x1FFu) + v) / 2u & 0x1FFu) * 96u / 128u; }

static void sfx_law_tests(void)
{
    uint32_t v, ok, n, k, f, t0, t1;

    /* A7: levels through D1 and D3, every v 0-511, against the chip's own table */
    boot(40);
    for (v = 0, ok = 1; v < 512u; v++) {
        post_d1(1, 0x01, (uint16_t)v, 0x80, 0);
        burn(CLK_MS_CYCLES * 7u);                   /* channel 0 is taken again: its FIFO drains first (pending) */
        ok &= fio[0].vol == lvl_vol(v);
        post_d3(0x01, (uint16_t)v, 0x40, 0);
        ok &= fio[0].vol == lvl_vol(v) && fio[0].pan == 0x40;
    }
    CHECK(ok);
    CHECK(lvl_vol(0xFF) == 191u && lvl_vol(0xC0) == 108u && lvl_vol(0) == 0u);
    post_d1(1, 0x10, 0xFF, 0x80, 0);                /* channel 4 */
    post_d1(1, 0x20, 0xFF, 0x80, 0);                /* channel 5 */
    post_d3(0x30, 0xC0, 0x20, 0);                   /* the lowest channel of the mask only: channel 4 */
    CHECK(fio[4].vol == 108u && fio[4].pan == 0x20 && fio[5].vol == 191u && fio[5].pan == 0x80);
    printf("A7: D1 / D3 volumes = (T[v] + v) / 2 x 96 / 128 for every v 0-511; C0 %u vs FF %u (-4.95 dB)\n",
           lvl_vol(0xC0), lvl_vol(0xFF));

    /* A8: the loop flag. D1 flags 8000 loops channel 7 by itself, gapless, every push = the bank's sample */
    boot(41);
    seq_ch = 7;
    seq_off = SFX_BASE + CUE_OFF;
    seq_len = CUE_LEN;
    seq_n = seq_bad = 0;
    post_d1(CUE_ID, 0x80, 0xFF, 0x80, 0x8000);
    CHECK(sfx_chan[7].looped == 1u && (fio[7].flags & 0x80u) == 0u);   /* the loop byte; no pitch bit for the RTL */
    t0 = hb.now;
    while (F[7].pushes < 3u * CUE_LEN + 100u && hb.now - t0 < (uint32_t)BRD_CLK_HZ * 20u)
        burn(CLK_MS_CYCLES);
    CHECK(F[7].pushes >= 3u * CUE_LEN + 100u && F[7].underruns == 0u && sfx_chan[7].size != 0u && seq_bad == 0u);
    /* a pass in the FIFO model with audio_sfx's pitch rule on the flags written: 29,920 / 6,000 = 4.98667 s */
    t1 = per_sample(7) * CUE_LEN;
    CHECK(t1 == (uint32_t)((uint64_t)BRD_CLK_HZ * 8u / 48000u) * CUE_LEN);
    printf("A8: looped by D1 alone: %u pushes, %u wrong; a pass %.5f s (RTL flags 0x%02X: 29,920 x 8 / 48,000); with "
           "the loop bit in the pitch bits: %.5f s\n", F[7].pushes, seq_bad, CUE_LEN * 8.0 / 48000.0, fio[7].flags,
           CUE_LEN * 8.0 * 32.0 / 31.0 / 48000.0);
    seq_ch = -1;
    boot(42);                                       /* no bit 15: one pass, and a D3 does not restart it */
    post_d1(CUE_ID, 0x80, 0xFF, 0x80, 0);
    CHECK(sfx_chan[7].looped == 0u);
    for (n = 0; n < 7000u && sfx_chan[7].size; n++)
        burn(CLK_MS_CYCLES);
    CHECK(sfx_chan[7].size == 0u && F[7].pushes == CUE_LEN);
    post_d3(0x80, 0xC0, 0x80, 0);
    burn(CLK_MS_CYCLES * 200u);
    CHECK(sfx_chan[7].size == 0u && F[7].pushes == CUE_LEN && fio[7].vol == 108u);

    /* A9: D1 FF looped + D2 6 at once (the corpus pattern D128 [0020 00FF 0080 8000], D220 0006): the synth-tick fade,
       then freed */
    boot(43);
    disp_g.sfx_ready = 1u;
    post_d1(CUE_ID, 0x20, 0xFF, 0x80, 0x8000);
    post_d2(0x20, 6);
    CHECK(fio[5].vol == 191u && sfx_chan[5].size != 0u);
    for (f = 0, k = 0, ok = 1, v = 255u; f < 400u && sfx_chan[5].size; f++) {
        uint32_t before = fio[5].vol;
        frame();
        if (!sfx_chan[5].size) {                    /* the last update: level 0 with the free flag: freed */
            k++;
            ok &= v < 6u && fio[5].vol == 0u;
        } else if (fio[5].vol != before) {          /* one update: 6 down */
            v -= 6u;
            k++;
            ok &= fio[5].vol == v * 96u / 128u;
        }
    }
    CHECK(ok && k == 43u && sfx_chan[5].size == 0u && fio[5].vol == 0u);
    CHECK(f >= 101u && f <= 105u);                  /* 86 synth ticks, one frame in 6 without one */
    printf("A9: D2 6 on a looped FF: %u updates, freed after %u frames (%.2f s)\n", k, f, f / 59.922743);
    {
        uint32_t p;
        burn(CLK_MS_CYCLES * 100u);                 /* the FIFO drains (silent: volume 0), nothing pushed after */
        p = F[5].pushes;
        burn(CLK_MS_CYCLES * 100u);
        CHECK(F[5].pushes == p && F[5].level == 0);
    }
    post_d1(CUE_ID, 0x40, 0xFF, 0x80, 0x8000);      /* D2 0: freed at once */
    post_d2(0x40, 0);
    CHECK(sfx_chan[6].size == 0u && fio[6].vol == 0u);
    burn(CLK_MS_CYCLES * 100u);
    post_d1(CUE_ID, 0x40, 0x00, 0x80, 0x8000);      /* D2 6 on a channel at level 0: freed at once */
    post_d2(0x40, 6);
    CHECK(sfx_chan[6].size == 0u && fio[6].vol == 0u);
    burn(CLK_MS_CYCLES * 100u);
    post_d1(CUE_ID, 0x40, 0x20, 0x80, 0x8000);      /* D3 step 1 (the corpus D340 [0020 0080 0001]) */
    post_d3(0x40, 0x80, 0x70, 1);                   /* level 20 -> 82, pan 80 -> 70, 1 an update */
    CHECK(fio[6].vol == lvl_vol(0x20) && fio[6].pan == 0x80);
    for (f = 0, ok = 1, n = fio[6].vol, k = fio[6].pan; f < 200u; f++) {
        frame();
        ok &= fio[6].vol >= n && fio[6].vol <= n + 1u && fio[6].pan <= k && fio[6].pan + 1u >= k;
        n = fio[6].vol;
        k = fio[6].pan;
    }
    CHECK(ok && fio[6].vol == lvl_vol(0x80) && fio[6].pan == 0x70);

    /* A10: the punk TV. D14A [0080 0000 0080 8000], a D380 ramp per frame (the emitter: L += (C0 - L) / 8 + 1, capped at
       C0), then 600 frames with no SFX post (the pause), then D380 [0 80 0] and D280 [0] a frame later */
    boot(44);
    disp_g.sfx_ready = 1u;
    seq_ch = 7;
    seq_off = SFX_BASE + CUE_OFF;
    seq_len = CUE_LEN;
    seq_n = seq_bad = 0;
    post_d1(CUE_ID, 0x80, 0, 0x80, 0x8000);
    CHECK(fio[7].vol == 0u && sfx_chan[7].looped == 1u);
    for (f = 0, v = 0, ok = 1; f < 120u; f++) {
        frame();
        v = v + (0xC0u - v) / 8u + 1u;
        if (v > 0xC0u)
            v = 0xC0u;
        post_d3(0x80, (uint16_t)v, 0x80, 0);
        ok &= fio[7].vol == lvl_vol(v);
    }
    CHECK(ok && fio[7].vol == 108u);
    n = F[7].pushes;
    for (f = 0; f < 600u; f++)                      /* 10 s, no SFX post: the cue keeps looping by itself */
        frame();
    if (!(sfx_chan[7].size != 0u && F[7].pushes - n > CUE_LEN && F[7].underruns == 0u && seq_bad == 0u))
        printf("A10: size %u, %u pushes in the pause, %u underruns, %u wrong\n", sfx_chan[7].size, F[7].pushes - n,
               F[7].underruns, seq_bad);
    CHECK(sfx_chan[7].size != 0u && F[7].pushes - n > CUE_LEN && F[7].underruns == 0u && seq_bad == 0u);
    post_d3(0x80, 0, 0x80, 0);
    CHECK(fio[7].vol == 0u && sfx_chan[7].size != 0u);
    frame();
    post_d2(0x80, 0);
    CHECK(sfx_chan[7].size == 0u && fio[7].vol == 0u);
    n = F[7].pushes;
    for (f = 0; f < 30u; f++)
        frame();
    CHECK(F[7].pushes == n);
    printf("A10: the punk TV: %u samples looped (%u passes), 0 wrong, 10 s with no D3; stopped by D380 0 + D280 0\n",
           seq_n, seq_n / CUE_LEN);
    seq_ch = -1;
}

/* ---- the chip's channels (A11-A17; since 2026-10-19,
   interim/s1/sfx_s1.c) ------------------------------------------ */
#define RATE_OF(ch)     ((fio[ch].type >> 4) & 7u)
#define BLK_CYC(n)      ((uint32_t)((uint64_t)CLK_MS_CYCLES * 10u * (n) / 3u))     /* n mix blocks of 160 / 48,000 s */
#define ID2_SIZE        17338u          /* id 2: rate 1 (24 kHz), 8-bit: 1,500 + (2 x 7,919) % 30,000 samples */
#define ID4_SIZE        3176u           /* id 4: rate 3 (9.6 kHz), 8-bit */
#define ID6_SIZE        19014u          /* id 6: rate 5, 4-bit */
static int16_t sample8(uint32_t id, uint32_t k)    /* the synthetic bank's 8-bit sample k of id */
{
    return (int16_t)(((flash[(SFX_BASE + 0x400u + id * 0x8000u + k) ^ 1u] & 0xFFu) * 65536u / 256u) - 32768);
}
static void idle(uint32_t cyc)                  /* time with no board point hook (a long idle) */
{
    void (*p)(void) = hb.on_point;
    hb.on_point = 0;
    burn(cyc);
    hb.on_point = p;
}
static uint32_t until_quiet(unsigned ch, uint32_t max_ms)   /* run until channel ch has no samples left */
{
    uint32_t n;
    for (n = 0; n < max_ms && sfx_chan[ch].size; n++)
        burn(CLK_MS_CYCLES);
    burn(CLK_MS_CYCLES * 60u);                  /* its FIFO drains */
    return n;
}

static void sfx_chip_tests(void)
{
    uint32_t f, k, ok, p[8], t0, n, prev, restarts;

    /* A11: the Block 888 cell B Jam found on a test build (2026-10-18).
       The play start's COMP TRANS loops on channel 6 (D122 [0040 0080
       0080 8000]) and fades out to a free (D240 [0001]); the door breaks while it still fades: the alarm D123 [0040 00FF
       0080 8100] (mask 0x40 only). The chip takes channel 6 (its only channel: the old cue ends); 0.2.6 put the loop on
       channel 0, where the exit's D240 [0000] never reached it. Here: channel 6, full level, the old fade gone, and the
       exit's D2 0 stops it: nothing plays after. (Negative control 6: 0.2.6's choice) */
    boot(50);
    disp_g.sfx_ready = 1u;
    sfx_mode88(2);
    post_d1(CUE_ID, 0x40, 0x80, 0x80, 0x8000);
    post_d2(0x40, 1);
    for (f = 0; f < 150u; f++)
        frame();
    CHECK(sfx_chan[6].size != 0u && fio[6].vol > 0u && fio[6].vol < 30u);    /* still fading (level ~20) */
    for (k = 0; k < 8u; k++)
        p[k] = F[k].pushes;
    post_d1(CUE_ID, 0x40, 0xFF, 0x80, 0x8100);
    for (f = 0; f < 3u; f++)
        frame();
    for (k = 0, ok = 1; k < 8u; k++)
        ok &= k == 6u || F[k].pushes == p[k];
    CHECK(ok && sfx_chan[6].looped == 1u && sfx_chan[6].size != 0u && fio[6].vol == 191u && RATE_OF(6) == 5u);
    for (f = 0; f < 300u; f++)                  /* 5 s: it loops at full level (the old cue's fade ended with it) */
        frame();
    CHECK(fio[6].vol == 191u && sfx_chan[6].size != 0u);
    post_d2(0x40, 0);                           /* the cell exit */
    CHECK(sfx_chan[6].size == 0u && fio[6].vol == 0u);
    frame();
    for (k = 0; k < 8u; k++)
        p[k] = F[k].pushes;
    for (f = 0; f < 120u; f++)
        frame();
    for (k = 0, ok = 1; k < 8u; k++)
        ok &= F[k].pushes == p[k];
    CHECK(ok);
    printf("A11: the cell alarm on channel 6 (mask 0x40) while the start cue fades there; stopped by the exit's D2 0\n");

    /* the channel choice when the mask has no free channel: the quietest, then the furthest along; never outside */
    boot(51);
    post_d1(CUE_ID, 0x01, 0xFF, 0x80, 0x8000);
    post_d1(CUE_ID, 0x02, 0x40, 0x80, 0x8000);
    post_d1(CUE_ID, 0x04, 0xFF, 0x80, 0x8000);
    burn(CLK_MS_CYCLES * 50u);
    post_d1(2, 0x07, 0xFF, 0x80, 0);
    burn(CLK_MS_CYCLES * 10u);
    CHECK(RATE_OF(1) == 1u && fio[1].vol == 191u && RATE_OF(0) == 4u && RATE_OF(2) == 4u && F[3].pushes == 0u);
    boot(52);
    post_d1(CUE_ID, 0x01, 0xFF, 0x80, 0x8000);
    burn(CLK_MS_CYCLES * 100u);
    post_d1(CUE_ID, 0x02, 0xFF, 0x80, 0x8000);
    burn(CLK_MS_CYCLES * 100u);
    post_d1(CUE_ID, 0x04, 0xFF, 0x80, 0x8000);
    burn(CLK_MS_CYCLES * 100u);
    post_d1(2, 0x07, 0xFF, 0x80, 0);
    burn(CLK_MS_CYCLES * 10u);
    CHECK(RATE_OF(0) == 1u && RATE_OF(1) == 4u && RATE_OF(2) == 4u && F[3].pushes == 0u);
    printf("A11: no free channel in the mask: the quietest is taken, then the one furthest along\n");

    /* A12: the echo voice (flags 0x4000, cart-DAC mode): a second channel at level / 3, a pan on the other side, 48-72
       mix blocks later; none in the YM-DAC mode */
    boot(53);
    sfx_mode88(2);
    t0 = (uint32_t)hb.cycles;
    post_d1(2, 0x03, 0xFF, 0x30, 0x4000);
    CHECK(fio[0].vol == 191u && fio[0].pan == 0x30u && F[0].pushes > 0u && fio[1].vol == 0u && F[1].pushes == 0u);
    for (n = 0; n < 400u && !F[1].pushes; n++)
        burn(CLK_MS_CYCLES);
    n = (uint32_t)((F[1].t1 - t0) / CLK_MS_CYCLES);
    CHECK(F[1].pushes && n >= 159u && n <= 243u && fio[1].vol == 63u && fio[1].pan >= 0xA0u && fio[1].pan <= 0xDFu);
    printf("A12: the echo voice: channel 1 after %u ms, volume %u, pan 0x%02X\n", n, (unsigned)fio[1].vol,
           (unsigned)fio[1].pan);
    boot(54);
    sfx_mode88(3);
    post_d1(2, 0x03, 0xFF, 0x30, 0x4000);
    burn(CLK_MS_CYCLES * 400u);
    CHECK(F[0].pushes > 0u && F[1].pushes == 0u && fio[0].flags == 0u);

    /* A13: the spread (flags 0x2000, a pan other than 0x80): the first voice 6 samples ahead (id 4: 8-bit, rate 3) on
       the pan's side, the second from the start on the other side at half gain; both at the sound's own rate (0.2.6:
       one voice at half rate). Pan 0x80: one voice */
    boot(55);
    sfx_mode88(2);
    post_d1(4, 0x03, 0xFF, 0x00, 0x2000);
    CHECK(F[0].pushes == 0u && F[1].pushes == 0u && fio[0].vol == 0u && fio[1].vol == 0u);   /* both wait for the grid */
    burn(CLK_MS_CYCLES);
    CHECK(fio[0].pan == 0x00u && fio[0].vol == 191u && F[0].s1 == sample8(4, 6) && fio[0].flags == 0u);
    CHECK(fio[1].pan == 0xFFu && fio[1].vol == 95u && F[1].s1 == sample8(4, 0) && fio[1].flags == 0u);
    CHECK(F[1].t1 - F[0].t1 < CLK_FEED);                        /* started in the same grid tick, A first */
    until_quiet(0, 2000u);
    until_quiet(1, 2000u);
    CHECK(F[0].pushes == ID4_SIZE - 6u && F[1].pushes == ID4_SIZE);
    boot(56);
    sfx_mode88(2);
    post_d1(4, 0x03, 0xFF, 0x80, 0x2000);
    until_quiet(0, 2000u);
    CHECK(F[0].pushes == ID4_SIZE && F[1].pushes == 0u);
    printf("A13: the spread: two voices, the first 6 samples ahead; none at pan 0x80\n");

    /* A14: the retrigger (flags bits 10-11 = n: the sound from its start again 2n times, every second synth tick) */
    for (k = 1; k <= 3u; k += 2u) {
        boot(57u + k);
        disp_g.sfx_ready = 1u;
        post_d1(CUE_ID, 0x01, 0xFF, 0x80, (uint16_t)(k << 10));
        for (f = 0, restarts = 0, prev = sfx_chan[0].ptr; f < 40u; f++) {
            frame();
            restarts += sfx_chan[0].ptr < prev;
            prev = sfx_chan[0].ptr;
        }
        CHECK(restarts == 2u * k);
        printf("A14: flags 0x%04X: %u restarts\n", k << 10, restarts);
    }

    /* A15: flags 0x0100: the rate one step up and the sound 4 samples shorter (rate 2); at rate 5 the flag is dropped */
    boot(60);
    post_d1(2, 0x01, 0xFF, 0x80, 0x0100);
    CHECK(RATE_OF(0) == 2u);
    until_quiet(0, 3000u);
    CHECK(F[0].pushes == ID2_SIZE - 4u);
    boot(61);
    post_d1(6, 0x01, 0xFF, 0x80, 0x0100);
    CHECK(RATE_OF(0) == 5u);
    until_quiet(0, 6000u);
    CHECK(F[0].pushes == ID6_SIZE);

    /* A16: D5 switches the SFX echo only: the loops on channels 6 and 7 play on (0.2.6 stopped them: control 7) */
    boot(62);
    post_d1(CUE_ID, 0x40, 0xFF, 0x80, 0x8000);
    post_d1(CUE_ID, 0x80, 0xFF, 0x80, 0x8000);
    burn(CLK_MS_CYCLES * 50u);
    args_ram()[0x1E10 / 2] = 0x60;
    args_ram()[0x1E12 / 2] = 0x10;
    sfx_stop(0xC0);
    p[6] = F[6].pushes;
    p[7] = F[7].pushes;
    burn(CLK_MS_CYCLES * 500u);
    CHECK(F[6].pushes > p[6] + 1000u && F[7].pushes > p[7] + 1000u && fio[6].vol == 191u && fio[7].vol == 191u);

    /* A17: the block count (300 a second on the board timer, after a 50 s idle with no query): a one-shot of 17,338
       samples at 24 kHz holds its channel 217 blocks (723 ms); a start 2 blocks before goes to the next channel of the
       mask, one 2 blocks after to the same channel */
    for (k = 0; k < 2u; k++) {
        boot(63u + k);
        idle((uint32_t)CLK_MS_CYCLES * 50000u);
        t0 = hb.now;
        post_d1(2, 0x01, 0xFF, 0x80, 0);
        while ((int32_t)(hb.now - t0) < (int32_t)BLK_CYC(k ? 219u : 215u))  /* (a board call adds time: burn's
                                                                                 own reads included) */
            burn(64u);
        post_d1(1, 0x03, 0xFF, 0x80, 0);
        burn(CLK_MS_CYCLES * 10u);
        CHECK(k ? (RATE_OF(0) == 0u && F[1].pushes == 0u) : (RATE_OF(0) == 1u && F[1].pushes > 0u));
    }
    printf("A17: a 217-block one-shot: its channel busy 215 blocks in, free 219 blocks in (after a 50 s idle)\n");

    /* A18: the block count on its own (white box): read just before, at (twice: the second read finds the next
       boundary a whole period away, bk_q + 1 cycles after a long one) and just after each of 3,000 boundaries, the
       count equals a walk of the grid (boundaries bk_q or bk_q + 1 cycles apart by Bresenham, 3 every 10 ms), and so
       after gaps of 1, 39, 41 and 79 s with no read (negative control 8: the first draft's boundary test) */
    {
        uint32_t step0 = hb.step, rt, rn = 0u, rph = 0u, q, bad = 0u, g;
        static const uint32_t gap_s[4] = { 1u, 39u, 41u, 79u };
        boot(70);
        hb.step = 0u;
        q = bk_q;
        rt = bk_t;
        for (k = 0; k < 3000u; k++) {
            hb.now = rt - 1u;
            bad += sfx_blk_now() != rn;
            hb.now = rt;
            bad += sfx_blk_now() != rn + 1u;
            bad += sfx_blk_now() != rn + 1u;
            hb.now = rt + 1u;
            bad += sfx_blk_now() != rn + 1u;
            rn++;
            rt += q + (rph < bk_r);
            rph = rph == 2u ? 0u : rph + 1u;
        }
        for (g = 0; g < 4u; g++) {
            uint32_t t1 = hb.now + gap_s[g] * CLK_MS_CYCLES * 1000u;
            while (rt - t1 - 1u > q) {              /* the walk up to the first boundary after t1 */
                rn++;
                rt += q + (rph < bk_r);
                rph = rph == 2u ? 0u : rph + 1u;
            }
            hb.now = t1;
            bad += sfx_blk_now() != rn;
        }
        hb.step = step0;
        CHECK(bad == 0u && q * 3u + bk_r == CLK_MS_CYCLES * 10u);
        printf("A18: the block count at 3,000 boundaries (before / at, read twice / after) and after 1-79 s gaps: %u "
               "wrong\n", bad);
    }
}

int main(void)
{
    uint32_t seed, ch;
    uint32_t tot_under = 0, tot_over = 0, tot_push = 0, tot_start = 0, tot_ticks = 0;
    for (seed = 1; seed <= 4u; seed++) {
        boot(seed);
        s1_vu_start(VU_MOD);                    /* as the 8C job (L3) */
        run((uint64_t)BRD_CLK_HZ * 120u);
        for (ch = 0; ch < 8; ch++) {
            tot_under += F[ch].underruns;
            tot_over += F[ch].overflow;
            tot_push += F[ch].pushes;
        }
        tot_start += started;
        tot_ticks += s1_audio_stats.ticks;
        CHECK(s1_audio_stats.ticks == tick_ctr);                        /* A2 */
        CHECK(s1_audio_stats.vu_rows > 1000u);                          /* A3: rows ran all along */
        CHECK(s1_au_log.n == au_expect);                                 /* A4 */
    }
    printf("A1: %u SFX started, %u pushes, %u underruns, %u overflows, %u feeder ticks\n", tot_start, tot_push, tot_under,
           tot_over, tot_ticks);
    CHECK(tot_under == 0u && tot_over == 0u && tot_start > 1000u);
    printf("A6: %u board points with no section open, %u channels with samples outside feed_playing\n", inv_points,
           inv_breaks);
    CHECK(inv_points > 1000000u && inv_breaks == 0u);

    /* A1: a non-looped SFX left alone plays to its end (every sample pushed), then the grid stops */
    boot(9);
    {
        uint16_t *args = (uint16_t *)(void *)hb.ram;
        uint32_t t0, i, ended = 0, s = brd_irq_save();         /* as body_d1 in L1 */
        args[0x1E10 / 2] = 0x01;
        args[0x1E12 / 2] = 0x80;
        args[0x1E14 / 2] = 0x40;
        args[0x1E16 / 2] = 0;
        sfx_play(5);                                            /* id 5: rate 4, 8-bit */
        s1_sfx_kick();
        brd_irq_restore(s);
        t0 = s1_audio_stats.ticks;
        for (i = 0; i < 600u && !ended; i++) {
            burn(CLK_MS_CYCLES * 10u);
            ended = !feed_on;
        }
        CHECK(ended && playing_mask() == 0u && F[0].underruns == 0u);
        CHECK(F[0].pushes == 1500u + (5u * 7919u) % 30000u);
        CHECK(s1_audio_stats.ticks > t0);
        t0 = s1_audio_stats.ticks;
        burn(CLK_FEED * 20u);                                   /* A2: idle grid: no ticks */
        CHECK(s1_audio_stats.ticks == t0 && !(wheel_armed() & (1u << WH_FEED)));
    }

    /* A5: every rate (and both sample widths), started in L1 and followed at once by a 17.3k-cycle post */
    {
        uint32_t id, under = 0;
        for (id = 1; id <= 12u; id++) {
            uint16_t *args = (uint16_t *)(void *)hb.ram;
            uint32_t s;
            boot(20u + id);
            s = brd_irq_save();
            args[0x1E10 / 2] = 0x01;
            args[0x1E12 / 2] = 0x80;
            args[0x1E14 / 2] = 0x40;
            args[0x1E16 / 2] = 0;
            sfx_play((u8)id);
            s1_sfx_kick();
            burn(17300u);                                   /* the next post's body, still in L1 */
            brd_irq_restore(s);
            burn(CLK_MS_CYCLES * 50u);
            for (s = 0; s < 8u; s++)
                under += F[s].underruns;
        }
        CHECK(under == 0u);
    }

    /* A3: the VU rows at their due instants, on the 0.2.6 row clock; a stop inside a row */
    boot(11);
    s1_vu_start(VU_MOD);
    {
        uint32_t i, due = 0, have = 0, rows = s1_audio_stats.vu_rows, late = 0, n = 0, prev_t = 0, bad_gap = 0;
        /* (2 x header[7] + FA) x 10.01257 ms = (6 + 2) x 10.01257 ms (voice 3's bar 0 carries FA 2 from the first row) */
        const uint32_t gap = (uint32_t)(80.10056 * CLK_MS_CYCLES);
        for (i = 0; i < 1200000u && n < 50u; i++) {
            if (!have)
                have = s1_vu_deadline(&due);
            burn(256u);
            if (s1_audio_stats.vu_rows != rows) {               /* a row ran in this step */
                if ((int32_t)(hb.now - due) < 0 || (int32_t)(hb.now - due) > 2048)   /* the row's own board points */
                    late++;
                if (n && (hb.now - prev_t < gap - CLK_MS_CYCLES - 600u || hb.now - prev_t > gap + CLK_MS_CYCLES + 600u))
                    bad_gap++;
                prev_t = hb.now;
                rows = s1_audio_stats.vu_rows;
                have = 0;
                n++;
            }
        }
        if (!(n == 50u && late == 0u && bad_gap == 0u))
            printf("A3: %u rows, %u late, %u with a wrong gap (last gap %u)\n", n, late, bad_gap, hb.now - prev_t);
        CHECK(n == 50u && late == 0u && bad_gap == 0u);
        printf("A3: 50 VU rows, each done within 2048 cycles of its due instant, %u cycles apart\n", gap);
    }
    {
        /* the stop (8D, L1) at the 6th board point inside a row (L2a): every bar 0 afterwards, no row after it */
        uint32_t i, k, nz = 0, rows;
        stop_in_row = 1;
        for (i = 0; i < 400000u && stop_in_row; i++)
            burn(256u);
        rows = s1_audio_stats.vu_rows;
        burn(CLK_MS_CYCLES * 400u);
        for (k = 0; k < 26u * 2u; k++)
            nz += ((uint16_t *)(void *)hb.ram)[(0x1B98u >> 1) + k] != 0u;
        CHECK(!stop_in_row && stop_points >= 6u && nz == 0u && s1_audio_stats.vu_rows == rows);
    }

    /* A6: a start made by an L1 in the middle of the grid's pass, right after channel 2's batch: channel 5 (above) is
       fed in that same pass, channel 0 (below) only by its kick */
    {
        uint32_t k;
        for (k = 0; k < 2u; k++) {
            uint16_t *args = (uint16_t *)(void *)hb.ram;
            uint32_t tgt = k ? 0u : 5u, t0, s, n;
            boot(30u + k);
            s = brd_irq_save();
            args[0x1E10 / 2] = 1u << 2;
            args[0x1E12 / 2] = 0x80;
            args[0x1E14 / 2] = 0x40;
            args[0x1E16 / 2] = 0;
            sfx_play(1);                                    /* channel 2 plays (48 kHz: it drains between two ticks) */
            s1_sfx_kick();
            brd_irq_restore(s);
            burn(CLK_FEED * 3u);
            t0 = s1_audio_stats.ticks;
            mid_after = 2u;
            mid_base = F[2].pushes;
            mid_word = 0x8040u | tgt;
            for (n = 0; mid_word && n < 1000u; n++)
                burn(64u);                                  /* the next tick: the post comes after channel 2's batch */
            CHECK(!mid_word && s1_audio_stats.ticks == t0 + 1u);
            CHECK(F[tgt].pushes == (tgt > 2u ? 96u : 48u));
        }
    }

    sfx_law_tests();
    sfx_chip_tests();
    printf("audio_tests: %d checks, %d failed\n", checks, fails);
    return fails ? 1 : 0;
}
