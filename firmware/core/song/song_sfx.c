/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song_sfx.c - the masters and fades (the fade tick), SFX control (the table init, the channel pick,
 * start, stop, update) and the Boom Box feed. Written by our team: we reverse engineered the STM32F4's commands as
 * close as possible, with hardware verification. The cart chip is the STM32 microcontroller on the real cartridge.
 */
#include "song.h"

/* one fade step toward a target (the chip's shape for the level and pan of the music, the SFX, each channel) */
#define STEP_TOWARD(cur, tgt, stp)                                       \
    do {                                                                 \
        if ((int)(int16_t)(cur) < (int)(tgt)) {                          \
            (cur) = (uint16_t)((cur) + (stp));                           \
            if ((int)(tgt) < (int)(int16_t)(cur)) (cur) = (uint16_t)(tgt); \
        } else if ((int)(tgt) < (int)(int16_t)(cur)) {                   \
            (cur) = (uint16_t)((cur) - (stp));                           \
            if ((int)(int16_t)(cur) < (int)(tgt)) (cur) = (uint16_t)(tgt); \
        }                                                                \
    } while (0)

/* the music level / pan fades, stop at silence, the boost ramp (D6 07), the SFX master and the
   channel fades and retriggers */
void master_fade_tick(void)
{
    uint16_t boost = S.boost, btarget = S.boost_target;
    uint32_t lvl, i;
    sfx_ch *c;

    if (S.ready != 0) {
        uint16_t pan;
        lvl = S.lvl_target;
        if (S.step == 0) {
            S.level = S.lvl_target;
            pan = S.pan_target;
            if (lvl == 0 && S.stop_at_zero != 0) {
                S.stop_at_zero = 0;
                S.playing = 0;
                lvl = 0;
            }
        } else {
            STEP_TOWARD(S.level, lvl, S.step);
            lvl = S.level;
            if (lvl == 0 && S.stop_at_zero != 0) {
                S.stop_at_zero = 0;
                S.playing = 0;
            }
            pan = S.pan;
            STEP_TOWARD(pan, S.pan_target, S.step);
        }
        S.pan = pan;
        S.gain0 = (uint16_t)pan_gain(lvl, S.pan, 0);
        S.gain1 = (uint16_t)pan_gain(S.level, S.pan, 1);
        if (S.boost_state == 0) {
            boost = 0;
            btarget = 0;
        } else {
            S.boost_state++;
            boost = S.boost;
            btarget = S.boost_target;
            if (S.boost_state > 4) {
                S.boost_state = 1;
                if (S.boost < S.boost_target) {
                    S.boost_state = 4;
                    boost = (uint16_t)(S.boost + 4);
                } else if (S.boost_target == 0) {
                    if (S.boost == 0)
                        S.boost_state = 0;
                    else
                        boost = (uint16_t)(S.boost - 1);
                } else {
                    btarget = 0;
                }
            }
        }
    }
    S.boost_target = btarget;
    S.boost = boost;
    if (SFX.ready == 0)
        return;

    SFX.frame = (uint16_t)(SFX.frame + (SONG_BUG != 3));
    if (SFX.step == 0) {
        SFX.level = SFX.lvl_target;
        SFX.pan = SFX.pan_target;
        lvl = SFX.lvl_target;
    } else {
        STEP_TOWARD(SFX.level, SFX.lvl_target, SFX.step);
        lvl = SFX.level;
        STEP_TOWARD(SFX.pan, SFX.pan_target, SFX.step);
    }
    SFX.gain2 = (uint16_t)pan_gain(lvl, SFX.pan, 2);
    SFX.gain3 = (uint16_t)pan_gain(SFX.level, SFX.pan, 3);

    for (i = 0, c = &SFX.ch[0]; i != 8; i++, c++) {
        if (c->id == 0)
            continue;
        if (c->loops != 0) {
            if (c->loop_cnt < c->loop_div) {
                c->loop_cnt++;
            } else {
                c->pos = 0;
                c->cur = c->start;
                c->loops--;
                c->loop_cnt = 0;
            }
        }
        /* the channel fades run on alternate ticks, the channel's parity against the tick count */
        if ((c->level != c->lvl_target || c->pan != c->pan_target) && ((SFX.frame ^ i) & 1) == 0) {
            uint32_t l = c->lvl_target;
            uint16_t s = c->step;
            if (s == 0) {
                c->level = (uint16_t)l;
                if (l == 0 && c->stop != 0) {
                    c->id = 0;
                    c->stop = 0;
                }
                c->pan = c->pan_target;
            } else {
                STEP_TOWARD(c->level, l, s);
                l = c->level;
                if (l == 0 && c->stop != 0) {
                    c->id = 0;
                    c->stop = 0;
                }
                STEP_TOWARD(c->pan, c->pan_target, s);
            }
            c->gain2 = (uint16_t)pan_gain(l, c->pan, 2);
            c->gain3 = (uint16_t)pan_gain(c->level, c->pan, 3);
        }
    }
}

/* the SFX table init (C6 long 4): the SFX table from the cart flash (the 16-bit view); record 0 = the header */
uint32_t sfx_table_init(uint32_t addr)
{
    const uint8_t *b;
    sfx_rec *r;
    uint32_t n, i, a = addr & ~1u;
    sfx_table[0].ptr = 0;
    sfx_table[0].flags = 0;
    sfx_table[0].l2 = 0;
    sfx_table[0].l1 = 0;
    sfx_table[0].l0 = 0;
    if (addr == 0)
        return 0;
    b = song_v.flash16 + a;
#define H(k) ((uint32_t)*(const uint16_t *)(const void *)(b + 2u * (k)))
    n = b[6];
    if (H(0) != 0 || n == 0)
        return 0;
    sfx_table[0].l0 = (uint8_t)(n + 1);
    song_v.sfx_bus = song_v.flash16_bus + a;    /* (ours: the bank the records point into; docs/MCU_INTERFACE.md
                                                   v1.3 3.10.4 counts an SFX window's PTR from it) */
    for (i = 1, r = &sfx_table[1]; i < n + 1; i++, r++, b += 8) {
        int32_t off = (int32_t)(H(4) << 16 | H(5));
        r->ptr = song_v.flash16_bus + a + 2u * (uint32_t)((off - ((int32_t)(int16_t)H(4) >> 15)) >> 1);
        r->flags = (uint8_t)(H(6) >> 8);
        r->l2 = (uint8_t)H(6);
        r->l1 = (uint8_t)(H(7) >> 8);
        r->l0 = (uint8_t)H(7);
    }
#undef H
    return 1;
}

/* pick = 0 -> the first channel of the mask; else a free one, or the most advanced */
uint32_t sfx_alloc_channel(uint32_t mask, int pick)
{
    uint32_t i, best = 0xFF, bestv = 0;
    sfx_ch *c;
    for (i = 0, c = &SFX.ch[0]; i != 8; i++, c++) {
        if ((mask >> i) & 1) {
            uint32_t p;
            if (pick == 0)
                return i;
            p = ((c->pos << 7) / (c->len + 1)) + (0x200 - c->level) * 16;
            if (c->id == 0)
                return i;
            if (bestv < p) {
                best = i;
                bestv = p;
            }
        }
    }
    return best;
}

/* the spread's first voice: by format (8-bit / 4-bit) and rate 2..5, the start
   (halfwords ahead) and the position */
static const uint8_t sfx_spread_start[2][4] = { { 4, 3, 2, 1 }, { 2, 1, 1, 0 } };
static const uint8_t sfx_spread_pos[2][4] = { { 16, 15, 16, 10 }, { 16, 10, 16, 0 } };
/* the length trim by rate */
static const uint8_t sfx_trim[6] = { 0, 0, 4, 4, 4, 8 };

/* start SFX id on a channel of mask; the spread (0x2000), the echo voice (0x4000) */
void sfx_start(uint32_t mask, uint32_t id, uint32_t vol, uint32_t pan, uint32_t flags)
{
    sfx_rec *r = &sfx_table[id];
    uint32_t rate = (r->flags & 0x7F) >> 4;
    uint32_t pitch = flags & 0xFF;
    uint32_t skip = 0, start = 0, spread = 0;
    int variant;

    if ((flags & 0x100) && ++rate > 5) {
        flags = (flags - 0x100) & 0xFFFF;
        rate = 5;
    }
    variant = 0;
    if (G.ymdac == 0) {
        if (flags & 0x4000) {
            variant = 2;
        } else if ((flags & 0x2000) && pan != 0x80) {
            uint32_t j = (rate - 2) & 0xFF;
            uint32_t f = (r->flags & 3) == 1 ? 0u : 1u;
            if (j >= 4) {
                skip = f == 0 ? 0x0E : 0x10;
                start = f == 0 ? 7 : 4;
            } else {
                start = sfx_spread_start[f][j];
                skip = sfx_spread_pos[f][j];
                if (start == 0) {
                    skip = 0;
                    goto go;
                }
            }
            spread = 2;
        }
    }
go:
    for (;;) {
        uint32_t ch = sfx_alloc_channel(mask, 1) & 0xFF, len;
        uint8_t sh;
        sfx_ch *c;
        if (ch == 0xFF)
            return;
        c = &SFX.ch[ch];
        if (variant == 1) {
            uint32_t qr = rand_systick();
            if (((qr & 1) == 0 || pan != 0x80) && pan < 0x81)
                pan = (qr & 0x3F) + 0xA0;
            else
                pan = (qr & 0x3F) + 0x20;
            vol = (vol / 3) & 0xFFFF;
            pitch = (((qr & 7) >> 1) * 8 + 0x30 + pitch) & 0xFFFF;
        }
        c->step = 0;
        c->starts++;
        c->id = 0;
        c->stop = 0;
        c->level = (uint16_t)(vol & 0x1FF);
        c->pan = (uint16_t)(pan & 0xFF);
        c->neg = (uint8_t)(flags >> 15);
        c->lvl_target = (uint16_t)(vol & 0x1FF);
        len = ((uint32_t)r->l2 << 16) | ((uint32_t)r->l1 << 8) | r->l0;
        c->pan_target = (uint16_t)(pan & 0xFF);
        c->len = len;
        if (flags & 0x100)
            c->len = len - (rate < 6 ? sfx_trim[rate] : 0u);
        c->rate_type = r->flags & 3;
        c->rate_mul = (uint16_t)rate;
        c->loop_div = 1;
        c->loops = (uint8_t)(((flags & 0xFFF) >> 10) << 1);
        c->loop_cnt = 0;
        c->gain2 = (uint16_t)pan_gain(vol & 0x1FF, pan & 0xFF, 2);
        c->gain3 = (uint16_t)pan_gain(c->level, c->pan, 3);
        if (spread != 0) {
            if (spread == 2) {
                if (pan > 0x7F)
                    c->gain2 = 0;
                else
                    c->gain3 = 0;
            } else {
                if (pan < 0x80) {
                    c->gain3 = (uint16_t)(c->gain2 >> 1);
                    c->gain2 = 0;
                } else {
                    c->gain2 = (uint16_t)(c->gain3 >> 1);
                    c->gain3 = 0;
                }
            }
        }
        sh = 0;
        len = c->len;
        switch (c->rate_mul) {
        case 2: len <<= 1; sh = 1; break;
        case 3: len = (len * 25) / 10; sh = 2; break;
        case 4: len <<= 2; sh = 2; break;
        case 5: sh = 3; len *= 5; break;
        }
        c->len = len;
        c->pos = skip;
        c->cur = r->ptr + start * 2;
        c->start = r->ptr;
        c->pitch = (uint16_t)pitch;
        if (spread == 1)
            sh += 1;
        else if ((flags & 0x1000) || variant == 1)
            sh += 2;
        c->shift = sh;
        c->r2a = 0;
        c->id = (uint16_t)id;
        if (variant == 2) {
            variant = 1;
        } else {
            if (spread != 2)
                return;
            spread = 1;
            skip = 0;
            start = 0;
        }
    }
}

/* D2 stop - at once, or fade out by rel */
void sfx_stop(uint32_t ch, uint32_t rel)
{
    sfx_ch *c = &SFX.ch[ch];
    if (rel == 0 || c->level == 0) {
        c->id = 0;
    } else {
        c->lvl_target = 0;
        c->step = rel & 0xFF;
        c->stop = 1;
    }
}

/* D3's update (one routine with two entries on the cart chip) */
void sfx_update(uint32_t ch, uint32_t vol, uint32_t pan, uint32_t step)
{
    sfx_ch *c = &SFX.ch[ch];
    vol &= 0x1FF;
    pan &= 0xFF;
    c->lvl_target = (uint16_t)vol;
    c->pan_target = (uint16_t)pan;
    c->step = step & 0xFF;
    if (step == 0) {
        c->pan = (uint16_t)pan;
        c->level = (uint16_t)vol;
        c->gain2 = (uint16_t)pan_gain(vol, pan, 2);
        c->gain3 = (uint16_t)pan_gain(c->level, c->pan, 3);
    }
}

/* 64 words to RAMDP $1B90 (track, sum, order, row, then side 0 / 1 meters per voice). The cart chip
   builds 56 words on its stack and copies 64: words 56-63 are what its stack held there (ours are 0) */
void boombox_feed(void)
{
    uint16_t w[64];
    uint32_t v, sum = 0, a, b;
    uint16_t *o = &w[4];
    volatile uint16_t *d = &song_v.ramdp[0x1B90 / 2];
    const song_voice *k = &S.v[0];
    uint32_t i;

    for (v = 0; v != 26; v++, k++, o += 2) {
        if (v < 6) {
            a = b = (uint16_t)k->env_level;
        } else if (v > 9) {
            a = ((uint32_t)(((int32_t)k->env_level * (int32_t)k->gain0) / 0x600) * 5) >> 2;
            b = (((uint32_t)(((int32_t)k->env_level * (int32_t)k->gain1) / 0x600) * 5) >> 2) & 0xFFFF;
        } else {
            a = b = mul_clamp(k->env_level, k->level, 0xFF);
        }
        o[0] = (uint16_t)a;
        o[1] = (uint16_t)b;
        sum = (sum + b) & 0xFFFF;
        w[1] = (uint16_t)sum;
    }
    w[0] = S.track;
    w[2] = S.order;
    w[3] = S.row;
    for (i = 56; i < 64; i++)
        w[i] = 0;
    for (i = 0; i < 64; i++)
        d[i] = w[i];
}
