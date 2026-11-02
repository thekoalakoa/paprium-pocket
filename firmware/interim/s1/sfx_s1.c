/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* interim/s1/sfx_s1.c - the cart chip's SFX channels on the interim feeder (the FW_S5 = 0 build; the FW_S5 build,
 * board/board.h, leaves it out with the album path, since the cart chip's mixer is whole there). The FW_S5 = 0 builds
 * link this instead of interim/album/sfx.c (0.2.6's, which stays as it was for the 0.2.6 builds); the entry points
 * and their TEST log kinds are 0.2.6's (sfx.h). The cart chip is the STM32 microcontroller on the real cartridge.
 *
 * What the cart chip does (B Jam's decisions of 2026-10-16 and 2026-10-19: the cart's behaviour, not a workaround).
 * Written by our team: we reverse engineered the STM32F4's commands as close as possible, with hardware verification.
 * D1 starts a sound on a channel of its mask (never on a channel outside the mask: 0.2.6 put it on channel 0, where
 * nothing the game sends reaches a loop again: B Jam's cell alarm, 2026-10-18); a start may add an echo voice or a
 * spread of two voices, retriggers and a delay; D2 and D3 work on the lowest channel of the mask, with the per-channel
 * fade and the retrigger in the fade tick (the synth tick); D5 switches the SFX echo on or off and touches no
 * channel (0.2.6 stopped 6 / 7).
 * Ours keeps the cart chip's channel records and works the mixer's part out from the block count: sfx_sync gives a
 * channel's delay left, position and end from the block it started at. The block count is a 300 Hz grid on the board
 * timer (the cart chip's blocks fall within one mixer period of such a grid: estimated); the channel's position
 * steers only the channel choice and the end of a sound. The sound is 0.2.6's path: the feeder
 * (interim/s1/audio_s1.c) pushes the samples into the RTL's FIFOs; a delayed voice, the two voices of a spread, and a
 * start on a channel whose FIFO still holds samples (a taken channel; the end of the last sound), wait as "pending"
 * with the RTL volume 0 (the queued samples drain at 48 kHz, at most 5.3 ms) and the feeder starts them when due.
 * Still ours (docs/ALLOWLIST.md, row B12): the cart chip's low-pass on some voices, its pan law and gains (the spread's
 * sides are the ends of the RTL's pan), the SFX echo of D5, the short last block of a looped pass (the RTL loops
 * without a gap), and where the cart chip's random numbers come from (ours: the board timer).
 * The RTL's rate 5 is the cart chip's 4,800 Hz since test build 4 (the RTL of 2026-10-19; it was 5,333 Hz). */
#include "appmain.h"
#include "s1_interim.h"

/* cold code (a post, the synth tick, a pending start): compiled for size, in the WRAM code window (pocket72k.json
   wcode_text: the TEST IROM is full) */
#define SFX_OS                  __attribute__((optimize("Os")))
#define SFX_HOT                 __attribute__((optimize("O2")))   /* the D1 path (L1: the 68000's next post waits) */

/* AUDIO_BUG: planted bugs for tests/s1/audio_tests.c's negative controls only (fwbuild.json s1.host.negative; never
   defined in an image): 6 = 0.2.6's channel choice back (channel 0 when no channel of the mask is free: A11), 7 =
   0.2.6's D5 back (it stops channels 6 / 7: A16), 8 = the block count's boundary test of this file's first draft (a
   read a whole long period before the next boundary took the boundary for passed: the count ran away; A18) */
#ifndef AUDIO_BUG
#define AUDIO_BUG 0
#endif

#define SFX_CHAN_NUM    8

/* 0.2.6's feeder records (s1_interim.h S1SfxChan): ptr / size / step / step_num / ptr_base / size_base as the feeder
   pushes them; looped = the chip's loop byte, kept through a free as the chip does; age / decay unused */
typedef S1SfxChan SfxChan;
SfxChan sfx_chan[SFX_CHAN_NUM];
u8 s1_sfx_type[SFX_CHAN_NUM];   /* the type byte programmed (its sample rate): the feeder reads it */
u8 s1_sfx_pend;                 /* the channels waiting to start: the feeder's grid starts them (sfx_pend_run) */

/* the chip's channel record, the mixer's part as of block n0 */
typedef struct {
    u32 pos0;                   /* the position (24 kHz output samples) at n0 */
    u32 len;                    /* the length, rate-scaled */
    u32 n0;                     /* the block count at the start or the last retrigger */
    u32 nend;                   /* the block that ends the pass begun at n0 (n0 + delay + its blocks): the sound's end,
                                   or its first rewind when looped (worked out at the start: no division later) */
    u32 pblk;                   /* the blocks of a whole pass (at least 1) */
    u16 lvl, pan;               /* level (9 bits), pan */
    u16 tlvl, tpan;             /* their targets */
    u16 delay;                  /* blocks left at n0 before it mixes */
    u8  id;                     /* the sound, 0 = free */
    u8  step, free0;            /* step per update (0 = at once), freed at level 0 (D2) */
    u8  rep, repn;              /* retriggers left, its tick counter */
    u8  side;                   /* the start's spread voice: 1 = on the pan's side, 2 = the other at half (until the
                                   chip computes the gains again: a D3 at once or a fade step) */
} SfxLvl;
static SfxLvl sfx_lvl[SFX_CHAN_NUM] __attribute__((section(".bss_upper")));
static u32 sfx_go[SFX_CHAN_NUM] __attribute__((section(".bss_upper")));      /* a pending start: due at this time */
static u32 sfx_psize[SFX_CHAN_NUM] __attribute__((section(".bss_upper")));   /* ... with this many samples */
static u8 sfx_fade_n;           /* the fade tick's count (its low bit) */
static u8 sfx_ym;               /* the YM-DAC mode (88 bit 0); 0 = the cart-DAC mode */
static u8 sfx_T[256] __attribute__((section(".bss_upper")));    /* the level table's first 256 entries */

/* the FIFO's status as audio_s1.c reads it (the halfword at +0): bit 0 empty */
typedef volatile const u16 __attribute__((may_alias)) sfx_st16;
#define SFX_EMPTY(ch)           (*(sfx_st16 *)(const void *)&ppmio.sfx[ch].status & 1u)

/* ---- the block count ---------------------------------------------------------------------------------------------
   The chip mixes a block every 160 samples of its 48 kHz DAC: 300 a second, 3 every 10 ms. Ours: a grid on the board
   timer, 10 ms (s1_sfx_blk3: CLK_MS_CYCLES x 10, read in audio_s1.c, as the code window holds no clock figure: T23)
   split into 3 by Bresenham. bk_t is
   the next boundary: after each read 1 <= bk_t - now <= bk_q + 1 (a period is bk_q or bk_q + 1 cycles). Read at
   every synth tick, so a gap is short; one of up to 2^32 - bk_q cycles (80 s) is still counted right */
static u32 bk_n, bk_t, bk_q, bk_1s;
static u8 bk_r, bk_ph;
static SFX_OS void sfx_blk_init(void)
{
    u32 t3 = s1_sfx_blk3();
    bk_q = t3 / 3u;
    bk_r = (u8)(t3 - 3u * bk_q);
    bk_1s = t3 * 100u;
    bk_n = 0u;
    bk_ph = 0u;
    bk_t = brd_now() + bk_q;
}
static SFX_HOT u32 sfx_blk_now(void)
{
    u32 now = brd_now(), d = now - bk_t;
    if (bk_t - now - 1u <= bk_q - (AUDIO_BUG == 8)) /* the next boundary is still ahead (1 .. bk_q + 1 cycles) */
        return bk_n;
    while (d >= bk_1s) {                            /* whole seconds (300 blocks: the phase is unchanged) */
        bk_t += bk_1s;
        bk_n += 300u;
        d -= bk_1s;
    }
    while ((int32_t)(now - bk_t) >= 0) {
        bk_n++;
        bk_t += bk_q + (bk_ph < bk_r);
        bk_ph = bk_ph == 2u ? 0u : (u8)(bk_ph + 1u);
    }
    return bk_n;
}
#ifndef SFX_BLOCKS                                  /* (the harness replays the chip's own count) */
#define SFX_BLOCKS()            sfx_blk_now()
#endif
/* the cart chip's random number; ours from the board timer */
#ifndef SFX_RAND
static SFX_OS u32 sfx_rand(void)
{
    u32 t = brd_now();
    return t ^ (t << 16);
}
#define SFX_RAND()              sfx_rand()
#endif

/* ---- the level table ---------------------------------------------------------------------------------------------
   T is the cart chip's start-up level table, built at boot with integers only; every entry is the cart chip's
   (measured: audio_tests A7). The tables were worked out from our own study of how the cart behaves and checked on
   hardware. */
#define SFX_T_STEP      2114190000u     /* the loop's step */
SFX_OS void sfx_level_init(void)
{
    u32 x = 256u << 23, c;
    int k;
    for (k = 255; k >= 2; k--) {
        c = (x + ((1u << 23) - 1u)) >> 23;
        sfx_T[k] = c > 255u ? 255u : (u8)c;
        x = (u32)(((u64)x * SFX_T_STEP) >> 31);
    }
    sfx_T[0] = sfx_T[1] = 0;
    memset(sfx_lvl, 0, sizeof sfx_lvl);             /* (a boot's .bss is zero already: the host tests boot again) */
    s1_sfx_pend = 0u;
    sfx_ym = 0u;
    sfx_blk_init();
}

/* the 9-bit SFX level of D1 and D3 (an index past the cart chip's table reads what is not known; never posted,
   measured max 468) */
static SFX_HOT u16 sfx_level(u16 v)
{
    u32 k = v & 0x1FFu, t = k < 256u ? sfx_T[k] : k - 1u;
    return (u16)((t + v) / 2u & 0x1FFu);
}

/* the RTL volume (0.2.6's D1 scale x 96 / 128: FF -> 191) and pan; the spread's start puts a voice on one side */
static SFX_HOT void sfx_rtl(int ch)
{
    const SfxLvl *l = &sfx_lvl[ch];
    u32 v = l->lvl * 96u / 128u;
    if (l->side == 2u)
        v >>= 1;
    ppmio.sfx[ch].vol = (u16)v;
    ppmio.sfx[ch].pan = l->side ? (u8)(((l->side == 1u) == (l->pan > 0x7Fu)) ? 0xFFu : 0x00u) : (u8)l->pan;
}
static SFX_HOT void sfx_out(int ch)  /* the chip computes the gains again (the pan gain): the spread's sides are gone */
{
    sfx_lvl[ch].side = 0u;
    if (!(s1_sfx_pend & (1u << ch)))                /* (a pending start writes them when it starts) */
        sfx_rtl(ch);
}

/* the chip's free (id := 0; the loop byte stays): no more samples, silent at once */
static SFX_HOT void sfx_free(int ch)
{
    sfx_lvl[ch].id = 0u;
    sfx_chan[ch].size = 0u;
    s1_sfx_pend &= (u8)~(1u << ch);
    ppmio.sfx[ch].vol = 0u;
}

/* ceil(x / 80) without a divide (NEORV32's divider is serial): x / 80 = (x x 0xCCCCCCCD) >> 38, exact for every
   32-bit x (the multiply-shift of x / 5, then / 16) */
static SFX_HOT u32 sfx_ceil80(u32 x) { return (u32)(((u64)(x + 79u) * 0xCCCCCCCDu) >> 38); }

/* a pass begun at block n with d blocks of delay first, from position p0: its end (or first rewind) block */
static SFX_HOT void sfx_pass(SfxLvl *l, u32 n, u32 d, u32 p0)
{
    l->n0 = n;
    l->delay = (u16)d;
    l->pos0 = p0;
    l->nend = n + d + (l->len > p0 ? sfx_ceil80(l->len - p0) : 1u);
}

/* the mixer's part at block n, without a divide: the delay left (*dl); a sound that is not looped ends (id := 0) on the
   block that reaches its length. Returns nonzero while the channel has a sound */
#define SFX_INL                 static inline __attribute__((always_inline))
SFX_INL u32 sfx_live(int ch, u32 n, u32 *dl)
{
    SfxLvl *l = &sfx_lvl[ch];
    u32 b = n - l->n0;
    *dl = 0u;
    if (!l->id)
        return 0u;
    if (b <= l->delay)
        *dl = l->delay - b;
    else if (!sfx_chan[ch].looped && (int32_t)(n - l->nend) >= 0)
        l->id = 0u;
    return l->id;
}
/* ... and its position (24 kHz output samples): a divide only past the first pass of a loop */
SFX_INL u32 sfx_sync(int ch, u32 n, u32 *dl)
{
    SfxLvl *l = &sfx_lvl[ch];
    u32 b = n - l->n0;
    if (!sfx_live(ch, n, dl))
        return 0u;
    if (b <= l->delay)
        return l->pos0;
    if ((int32_t)(n - l->nend) < 0)
        return l->pos0 + 80u * (b - l->delay);
    return 80u * ((n - l->nend) % l->pblk);
}

/* the cart chip's channel pick with argument 1, one pass as the chip: each channel of the mask in turn; the first
   with no sound is taken, else the busy channel the cart chip would pick */
static SFX_HOT u32 sfx_alloc(u32 mask, u32 n)
{
    u32 ch, best = 0u, pick = 0xFFu, d;
    for (ch = 0u; ch < SFX_CHAN_NUM; ch++) {
        u32 pos, sc;
        if (!((mask >> ch) & 1u))
            continue;
        pos = sfx_sync((int)ch, n, &d);
        if (!sfx_lvl[ch].id)
            return ch;
        sc = ((pos << 7) / (sfx_lvl[ch].len + 1u)) + (0x200u - sfx_lvl[ch].lvl) * 16u;
        if (sc > best) {
            best = sc;
            pick = ch;
        }
    }
    return AUDIO_BUG == 6 ? 0u : pick;
}

/* the spread's first voice: how far ahead it starts and its position, by format and rate (rates 2-5, the others
   below) */
static const u8 sfx_ahead[2][4] = { { 4, 3, 2, 1 }, { 2, 1, 1, 0 } };
static const u8 sfx_ahead_pos[2][4] = { { 16, 15, 16, 10 }, { 16, 10, 16, 0 } };

/* one voice of a start on channel ch, at block n */
static SFX_HOT void sfx_voice(int ch, u32 id, const u8 *e, u32 type, u32 size, u32 len, u32 level, u32 pan, u32 flags,
                             u32 dly, u32 ahead, u32 pos0, u32 side, u32 n)
{
    SfxLvl *l = &sfx_lvl[ch];
    SfxChan *c = &sfx_chan[ch];
    u32 skip = ahead * ((type & 3u) == 1u ? 2u : 4u), bit = 1u << ch;
    l->id = 0u;                                     /* the sound there ends */
    l->step = l->free0 = 0u;
    l->lvl = l->tlvl = (u16)(level & 0x1FFu);
    l->pan = l->tpan = (u16)(pan & 0xFFu);
    l->len = len;
    l->pblk = len ? sfx_ceil80(len) : 1u;
    sfx_pass(l, n, dly & 0xFFFFu, pos0);
    l->rep = (u8)(((flags & 0xFFFu) >> 10) << 1);
    l->repn = 0u;
    l->side = (u8)side;
    l->id = (u8)id;
    c->ptr_base = ppm_sfx_base_addr + swapshorts(*(const u32 *)&e[0]);
    c->size_base = size;
    c->ptr = c->ptr_base + ahead * 2u;
    c->step = 0u;
    c->step_num = (type & 3u) == 1u ? 1u : 2u;  /* 8-bit for format 1, else 4-bit (the chip's SFX mix) */
    c->looped = flags >> 15;
    c->flags = flags;
    s1_sfx_type[ch] = (u8)type;
    if (dly || side || !SFX_EMPTY(ch)) {            /* pending: silent now; the old samples drain at 48 kHz. Both
                                                       voices of a spread wait for the grid's next tick, which starts
                                                       them together, A ahead as the cart chip's (two first batches in
                                                       this L1 ran a D101 over FZ12's 0.32 ms in a test run) */
        c->size = 0u;
        sfx_psize[ch] = size > skip ? size - skip : 0u;
        sfx_go[ch] = brd_now() + dly * bk_q;
        ppmio.sfx[ch].vol = 0u;
        ppmio.sfx[ch].type = (u8)(type & 0x0Fu);
        s1_sfx_pend |= (u8)bit;
    } else {
        s1_sfx_pend &= (u8)~bit;
        ppmio.sfx[ch].type = (u8)type;
        ppmio.sfx[ch].flags = 0u;               /* no RTL flag: the chip has no pitch, echo-line or gain bit */
        c->size = size > skip ? size - skip : 0u;
        sfx_rtl(ch);
    }
}

/* the SFX start */
static SFX_HOT void sfx_start(u32 mask, u32 id, u32 level, u32 pan, u32 flags)
{
    const u8 *e = &ppmio.flash[ppm_sfx_base_addr + id * 8u];
    u32 type = e[5], fmt = (type & 3u) == 1u ? 0u : 1u, rate = (type & 0x7Fu) >> 4, size, len, n = SFX_BLOCKS();
    u32 echo = 0u, spread = 0u, ahead = 0u, pos0 = 0u, dly = flags & 0xFFu, ch;  /* echo, spread: 2 = 1st voice */
    size = ((u32)e[4] << 16) | *(const u16 *)&e[6];
    if (flags & 0x0100u) {                          /* one rate up */
        if (++rate > 5u) {
            rate = 5u;
            flags -= 0x0100u;
        }
    }
    if (!sfx_ym) {                                  /* the cart-DAC mode */
        if (flags & 0x4000u) {
            echo = 2u;
        } else if ((flags & 0x2000u) && pan != 0x80u) {
            u32 r = (rate - 2u) & 0xFFu;
            if (r < 4u) {
                ahead = sfx_ahead[fmt][r];
                pos0 = sfx_ahead_pos[fmt][r];
            } else {
                ahead = fmt ? 4u : 7u;
                pos0 = fmt ? 16u : 14u;
            }
            if (ahead)
                spread = 2u;
            else
                pos0 = 0u;
        }
    }
    if (flags & 0x0100u)                            /* the length trim by rate */
        size -= rate < 2u ? 0u : rate < 5u ? 4u : 8u;
    len = rate == 2u ? size << 1 : rate == 3u ? (size * 5u) >> 1 : rate == 4u ? size << 2 :
          rate == 5u ? size * 5u : size;
    type = (type & ~0x70u) | (rate << 4);
    for (;;) {
        ch = sfx_alloc(mask, n);
        if (ch == 0xFFu)
            return;
        if (echo == 1u) {                           /* the echo voice */
            u32 r = SFX_RAND();
            pan = (((r & 1u) && pan == 0x80u) || pan > 0x80u) ? (r & 0x3Fu) + 0x20u : (r & 0x3Fu) + 0xA0u;
            level = (level & 0xFFFFu) / 3u;
            dly = ((((r & 7u) >> 1) << 3) + 0x30u + dly) & 0xFFFFu;
        }
        sfx_voice((int)ch, id, e, type, size, len, level, pan, flags, dly, ahead, pos0,
                  spread == 2u ? 1u : spread == 1u ? 2u : 0u, n);
        if (echo == 2u) {
            echo = 1u;
        } else if (spread == 2u) {                  /* the spread's second voice: from the start */
            spread = 1u;
            ahead = pos0 = 0u;
        } else {
            return;
        }
    }
}

/* D1 (0.2.6's name; mailbox B with arguments, the only form 0.2.6 served) */
SFX_HOT void sfx_play(u8 arg)
{
#if !PPM_RELEASE
    s1_au_note(1u, arg);
#endif
    sfx_start(ppmio.ramdp->cmd_args[0], arg & 0x7Fu, sfx_level(ppmio.ramdp->cmd_args[1]), ppmio.ramdp->cmd_args[2],
              ppmio.ramdp->cmd_args[3]);
}

/* the lowest channel of the mask, the chip's channel pick with argument 0 (D2 / D3 never post a mask without one) */
static SFX_OS int sfx_low_chan(u8 mask)
{
    int i;
    for (i = 0; i < SFX_CHAN_NUM - 1; i++)
        if (mask & (1u << i))
            break;
    return i;
}

/* D3 (0.2.6's name sfx_loop): the target level, the target pan and the step; step 0 sets them now. It never touches
   the loop byte (D31) */
SFX_OS void sfx_loop(u8 arg)
{
    int ch = sfx_low_chan(arg);
    SfxLvl *l = &sfx_lvl[ch];
#if !PPM_RELEASE
    s1_au_note(2u, arg);
#endif
    l->tlvl = sfx_level(ppmio.ramdp->cmd_args[0]);
    l->tpan = ppmio.ramdp->cmd_args[1] & 0xFFu;
    l->step = ppmio.ramdp->cmd_args[2] & 0xFFu;
    if (l->step == 0u) {
        l->lvl = l->tlvl;
        l->pan = l->tpan;
        sfx_out(ch);
    }
}

/* D2: arg 0 or a level already 0 frees the channel now, else a fade to 0 at that step and
   the free there */
SFX_OS void sfx_d2(u8 arg)
{
    int ch = sfx_low_chan(arg);
    SfxLvl *l = &sfx_lvl[ch];
    u16 step = ppmio.ramdp->cmd_args[0];
#if !PPM_RELEASE
    s1_au_note(3u, arg);
#endif
    if (step == 0u || l->lvl == 0u) {
        sfx_free(ch);
    } else {
        l->tlvl = 0u;
        l->step = step & 0xFFu;
        l->free0 = 1u;
    }
}

/* D5 (0.2.6's name sfx_stop): the SFX echo on (gain, delay) or off. No channel is touched;
   the echo itself is not ours yet (the RTL has none: row B12) */
SFX_OS void sfx_stop(u8 arg)
{
#if !PPM_RELEASE
    s1_au_note(3u, arg);
#endif
    (void)arg;
#if AUDIO_BUG == 7
    sfx_free(6);
    sfx_free(7);
#endif
}

/* 88 (the configuration): bit 0 = the YM-DAC mode, where a start has no echo or spread voice */
SFX_OS void sfx_mode88(u8 lo)
{
    sfx_ym = lo & 1u;
}

/* the fade tick's channel loop, once per synth tick (interim/s1/audio_s1.c audio_tick_begin, L1): each channel's
   retrigger, then its fade toward the targets; a level of 0 with the free flag frees it */
static SFX_HOT u16 sfx_toward(u16 v, u16 t, u16 step)
{
    if (v < t)
        return (u16)(v + step > t ? t : v + step);
    if (v > t)
        return (u16)(v < t + step ? t : v - step);
    return v;
}

SFX_HOT void sfx_fade_tick(void)
{
    u32 n = SFX_BLOCKS(), d, kick = 0u;
    int ch;
    sfx_fade_n++;
    for (ch = 0; ch < SFX_CHAN_NUM; ch++) {
        SfxLvl *l = &sfx_lvl[ch];
        if (!sfx_live(ch, n, &d))
            continue;
        if (l->rep) {
            if (l->repn < 1u) {
                l->repn++;
            } else {                                /* the sound again from its start (pos 0, ptr = base) */
                SfxChan *c = &sfx_chan[ch];
                l->rep--;
                l->repn = 0u;
                sfx_pass(l, n, d, 0u);              /* (the delay left, if any, still runs) */
                c->ptr = c->ptr_base;
                c->step = 0u;
                if (s1_sfx_pend & (1u << ch)) {
                    sfx_psize[ch] = c->size_base;
                } else {
                    c->size = c->size_base;
                    kick = 1u;
                }
            }
        }
        if ((l->lvl == l->tlvl && l->pan == l->tpan) || ((sfx_fade_n ^ ch) & 1))
            continue;
        if (l->step == 0u) {
            l->lvl = l->tlvl;
            l->pan = l->tpan;
        } else {
            l->lvl = sfx_toward(l->lvl, l->tlvl, l->step);
            l->pan = sfx_toward(l->pan, l->tpan, l->step);
        }
        if (l->lvl == 0u && l->free0) {
            l->free0 = 0u;
            sfx_free(ch);
        } else {
            sfx_out(ch);
        }
    }
    if (kick)
        s1_sfx_kick();
}

/* the feeder's grid (interim/s1/audio_s1.c wh_feed, interrupts off): the pending starts that are due and whose FIFO
   has drained get their RTL settings and their samples; returns their channels */
SFX_OS u32 sfx_pend_run(void)
{
    u32 m = s1_sfx_pend, now = brd_now(), go = 0u;
    int ch;
    for (ch = 0; m; ch++, m >>= 1) {
        if (!(m & 1u) || (int32_t)(now - sfx_go[ch]) < 0 || !SFX_EMPTY(ch))
            continue;
        ppmio.sfx[ch].type = s1_sfx_type[ch];
        ppmio.sfx[ch].flags = 0u;
        sfx_chan[ch].size = sfx_psize[ch];
        sfx_rtl(ch);
        go |= 1u << ch;
    }
    s1_sfx_pend &= (u8)~go;
    return go;
}
