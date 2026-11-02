/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song_z80.c - the Z80 message builders and the per-frame packet to RAMDP $1800 (+ the YM-DAC stream at
 * $1880). Written by our team: we reverse engineered the STM32F4's commands as close as possible, with hardware
 * verification. The cart chip is the STM32 microcontroller on the real cartridge, RAMDP the cart RAM that both the
 * 68000 and the MCU see. The queue is 0x80 bytes; a message for the same channel as the previous one is written over
 * it.
 */
#include "song.h"
#include "chip_tables.h"

#define Q      Z80Q
#define QPREV  (Z80Q - 4)

/* msg 4: a voice's level and pan */
void fm_level_msg(uint32_t v)
{
    uint8_t *base = Q;
    uint8_t *m;
    int coalesce;
    uint32_t att, mm;
    song_voice *k = &S.v[v];

    if (Q[G.q_last] == 4 && Q[G.q_last + 1] == v) {
        coalesce = 1;
        base = QPREV;
    } else {
        coalesce = 0;
        if (G.q_len > 0x7B)
            return;
    }
    m = base + G.q_len;
    att = (uint16_t)(0xFF - chip_level_T[(0xFFu - S.level) & 0x1FFu]);
    m[0] = 4;
    m[1] = (uint8_t)v;
    if (att > 0xFF)
        att = 0xFF;
    mm = mul_clamp((int)att, G.fm_master, 0xFF);
    m[2] = (uint8_t)mul_clamp(k->level, (int)mm, 0xFF);
    m[3] = (uint8_t)k->pan;
    if (!coalesce) {
        G.q_last = G.q_len;
        G.q_len += 4;
        G.q_cost += 0x16 - (SONG_BUG == 2);
    }
}

/* msg 0x0B: a PSG voice's tone (voice 9: the noise mode) */
void psg_tone_msg(uint32_t v, uint32_t pitch)
{
    uint8_t *base = Q;
    uint8_t *m;
    int coalesce;
    uint8_t lo, hi;
    uint32_t n;

    if (Q[G.q_last] == 0x0B && Q[G.q_last + 1] == v) {
        coalesce = 1;
        base = QPREV;
    } else {
        coalesce = 0;
        if (G.q_len > 0x7B)
            return;
    }
    m = base + G.q_len;
    if (v == 9) {
        if (pitch == 6) {
            lo = 0xE5; hi = 0;
        } else if (pitch == 7) {
            lo = 0xE6; hi = 0;
        } else {
            lo = 0xE4;
            if (pitch != 5)
                return;
            hi = 0;
        }
    } else if (G.raw_pitch == 0) {
        n = psg_period(pitch);
        hi = (uint8_t)(n >> 8);
        lo = (uint8_t)n;
    } else {
        hi = (uint8_t)(pitch >> 8);
        lo = (uint8_t)pitch;
    }
    m[2] = hi;
    m[0] = 0x0B;
    m[1] = (uint8_t)(v - 6);
    m[3] = lo;
    S.v[v].pitch = (uint16_t)pitch;
    if (!coalesce) {
        G.q_last = G.q_len;
        G.q_len += 4;
        G.q_cost += 4;
    }
}

/* msg 4 only when the level or the pan changed and the budget allows; once per row */
void fm_level_refresh(uint32_t v)
{
    song_voice *k = &S.v[v];
    uint32_t vol = mul_clamp(k->level, (int)((uint32_t)G.fm_master * S.level) >> 8, 0xFF);
    if ((k->fm_vol_sent != vol || k->pan != k->fm_pan_sent) &&
        (uint32_t)G.q_cost + 0x15 < G.q_budget) {
        k->fm_vol_sent = (uint16_t)mul_clamp(k->level, (int)((uint32_t)G.fm_master * S.level) >> 8, 0xFF);
        k->fm_pan_sent = k->pan;
        fm_level_msg(v);
    }
}

/* msg 0x0C with the four PSG volumes, every frame */
void psg_volume_msg(void)
{
    uint32_t n = G.q_len, i;
    uint32_t m = (uint32_t)G.psg_master * S.level;
    if (n >= 0x7B)
        return;
    Q[n] = 0x0C;
    for (i = 0; i < 4; i++) {
        const song_voice *k = &S.v[6 + i];
        Q[n + 1 + i] = k->env_state == 0 ? 0 : (uint8_t)mul2_clamp(k->env_level, k->level, (int)m >> 8, 0xFF);
    }
    G.q_last = G.q_len;
    G.q_len += 5;
}

void psg_volume_only(void)
{
    psg_volume_msg();
}

/* msg 0x0D: an operator TL (the module commands 1A-1D) */
void fm_tl_msg(uint32_t ch, uint32_t op, uint32_t tl)
{
    uint32_t n = G.q_len;
    if (n < 0x7C) {
        Q[n] = 0x0D;
        Q[n + 1] = (uint8_t)ch;
        Q[n + 2] = (uint8_t)op;
        Q[n + 3] = (uint8_t)tl;
        G.q_last = G.q_len;
        G.q_len += 4;
        G.q_cost += 5;
    }
}

/* msg 0x0A: an FM program */
void fm_program_msg(uint32_t v, uint32_t prog)
{
    uint32_t n = G.q_len;
    if (n < 0x7D) {
        S.v[v].program = (uint16_t)prog;
        Q[n + 1] = (uint8_t)v;
        Q[n] = 0x0A;
        Q[n + 2] = (uint8_t)prog;
        G.q_last = G.q_len;
        G.q_len += 3;
        G.q_cost += 0x2D;
    }
}

/* msg 7 (key-off) or 8 (a hard key-off) */
void fm_keyoff_msg(uint32_t v, int hard)
{
    uint32_t n = G.q_len;
    uint8_t c;
    if (n >= 0x7E)
        return;
    if (hard == 0) {
        if ((uint32_t)(Q[G.q_last] - 7) > 1 || Q[G.q_last + 1] != v) {
            Q[n + 1] = (uint8_t)v;
            Q[n] = 7;
            G.q_last = G.q_len;
            G.q_len += 2;
            G.q_cost += 4;
        }
    } else if (Q[G.q_last] == 8 && (c = Q[G.q_last + 1]) == v) {
        Q[n - 2] = 8;
        Q[n - 1] = c;
    } else {
        Q[n + 1] = (uint8_t)v;
        Q[n] = 8;
        G.q_last = G.q_len;
        G.q_len += 2;
        G.q_cost += 9;
    }
}

/* msg 6 for a new note, msg 9 for legato */
void fm_note_msg(uint32_t v, uint32_t pitch, int new_note)
{
    uint32_t n = G.q_len;
    uint32_t f;
    uint8_t lo, hi, ch;
    if (n > 0x7B)
        return;
    ch = (uint8_t)v;
    f = pitch;
    if (G.raw_pitch == 0)
        f = fm_fnum(pitch);
    lo = (uint8_t)f;
    hi = (uint8_t)(f >> 8);
    if (new_note == 0) {
        if (Q[G.q_last] != 9 || Q[G.q_last + 1] != v) {
            Q[n] = 9;
            Q[n + 1] = ch;
            Q[n + 2] = hi;
            Q[n + 3] = lo;
            S.v[v].pitch = (uint16_t)pitch;
            G.q_last = G.q_len;
            G.q_len += 4;
            G.q_cost += 5;
            return;
        }
        QPREV[n] = 9;
        QPREV[n + 1] = ch;
        QPREV[n + 2] = hi;
        QPREV[n + 3] = lo;
    } else {
        uint32_t l = G.q_last;
        if (Q[l] == 6) {
            if (Q[l + 1] != v) {
                Q[n] = 6;
                goto fresh;
            }
        } else {
            if (Q[l] != 9 || Q[l + 1] != v) {
                Q[n] = 6;
            fresh:
                Q[n + 1] = ch;
                Q[n + 2] = hi;
                Q[n + 3] = lo;
                S.v[v].pitch = (uint16_t)pitch;
                G.q_last = G.q_len;
                G.q_len += 4;
                G.q_cost += 0x0B;
                return;
            }
            G.q_cost += 6;
        }
        QPREV[n] = 6;
        QPREV[n + 1] = ch;
        QPREV[n + 2] = hi;
        QPREV[n + 3] = lo;
    }
    S.v[v].pitch = (uint16_t)pitch;
}

/* the packet: the header, the messages, the end; YM-DAC: the stream at word 0x40 */
int z80_packet_build(void)
{
    int16_t rate = (int16_t)G.rate;
    int16_t ym = (int16_t)G.ymdac;
    uint16_t hdr;
    uint32_t words, n, i;
    const volatile int16_t *s;
    uint16_t *d;

    if (G.ymdac == 1) {
        hdr = 0x1C0;
        z80_packet[0] = 0x180;
    } else {
        hdr = 0x140;
        z80_packet[0] = 0x100;
    }
    if (G.rate == 0x3C)
        z80_packet[0] = hdr;
    if (S.playing != 0)
        z80_packet[0] |= 0x20;
    Q[G.q_len] = 0;
    G.q_len++;
    Q[G.q_len] = 0;
    G.q_len++;
    n = G.q_len >> 1;
    for (i = 0; i < n; i++) {
        uint16_t w = (uint16_t)(Q[2 * i] | Q[2 * i + 1] << 8);
        z80_packet[1 + i] = (uint16_t)(w << 8 | w >> 8);
    }
    if (ym == 1) {
        /* the frame's blocks mixed so far are the logic's: read from the synth */
        if ((SONG_BUG == 15 ? (uint32_t)G.r3a : board_frame_cnt()) < G.blocks) {
#if SONG_BUG == 14
            song_bug14_underrun++;
#else
            board_underrun();               /* the chip's u16 = trace counter 11 (N1) */
#endif
        }
        if (rate == 0x3C) {
            words = 0xC5;
            n = 0x85;
        } else {
            words = 0xE0;
            n = 0xA0;
        }
        s = song_v.dac_buf;
        d = &z80_packet[0x40];
        for (i = 0; i < n; i++, s += 6)
            *d++ = (uint16_t)(s[0] * 0x100 + s[SONG_BUG == 7 ? 2 : 3]);
    } else {
        words = 0x40;
    }
    return board_packet_dma(z80_packet, words) != 0;
}

/* build + send, reset the queue and the per-frame budget */
void z80_packet_flush(void)
{
    board_trace_fold(1u);           /* (in the tick's item, so the DIAG counts may be cleared) */
    z80_packet_build();
    G.q_len = 0;
    G.q_last = 0;
    Q[0] = 0;
    G.q_budget = 0x98;
    G.q_cost = 5;
    G.r16 = 1;
    STATUS(1, 3, 0x2000);
}
