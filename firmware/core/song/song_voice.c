/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song_voice.c - the voice back-ends (wave program / note, PSG program / note / envelope) and the pitch and
 * gain helpers. Written by our team: we reverse engineered the STM32F4's commands as close as possible, with
 * hardware verification. The cart chip is the STM32 microcontroller on the real cartridge.
 */
#include "song.h"
#include "chip_tables.h"

#define SDIR32(n, o)  (*(const uint32_t *)(const void *)(song_v.sdir + (n) * 16u + (o)))
#define SDIR_FLAGS(n) (*(const uint16_t *)(const void *)(song_v.sdir + (n) * 16u + 12u))

/* the wave program's record; an empty directory entry -> length 0, program not stored */
void wave_program_change(uint32_t v, uint32_t prog)
{
    const uint8_t *r = song_v.wprog + prog * 16u;
    uint32_t smp = r[8];
    song_voice *k = &S.v[v];
    if (SDIR32(smp, 0) == 0) {
        k->wlen = 0;
        return;
    }
    k->sample   = r[8];
    k->program  = (uint16_t)prog;
    k->env_ar   = r[0];
    k->env_hold = r[1];
    k->env_dr   = r[2];
    k->env_sl   = r[6];
    k->env_st   = r[3];
    k->env_d2r  = r[4];
    k->env_rr   = r[5];
    k->wb       = (int8_t)r[11];
    k->step     = 0;
    k->wpos     = 0;
    k->wdata    = song_v.sdir_bus + SDIR32(smp, 0);
    k->wlen     = SDIR32(smp, 4);
    k->wloop    = SDIR32(smp, 8);
    k->pitch    = 0;
    if ((SDIR_FLAGS(smp) & 3) == 1)
        k->rate_khz = 24;
    else if ((SDIR_FLAGS(smp) & 3) == 2)
        k->rate_khz = 12;
    else
        k->rate_khz = 48;
    k->companded = (uint8_t)(SDIR_FLAGS(smp) >> 15);
}

/* the program's envelope preset */
void psg_program_change(uint32_t v, uint32_t prog)
{
    const uint8_t *r = song_v.psgenv + prog * 8u;
    song_voice *k = &S.v[v];
    k->program  = (uint16_t)prog;
    k->env_ar   = r[0];
    k->env_hold = r[1];
    k->env_dr   = r[2];
    k->env_sl   = r[6];
    k->env_st   = r[3];
    k->env_d2r  = r[4];
    k->env_rr   = r[5];
}

/* the PSG ADSR per sequencer tick, voices 6-9, level 0..255 */
void psg_envelope_tick(void)
{
    song_voice *k;
    int16_t l;
    uint16_t d;
    if (S.ready == 0 || S.playing == 0)
        return;
    for (k = &S.v[6]; k != &S.v[10]; k++) {
        switch (k->env_state) {
        case 0:
            k->env_level = 0;
            break;
        case 1:
            if (k->env_ar == 0) {
                k->env_level = 0xFF;
            } else {
                l = (int16_t)(k->env_ar + k->env_level);
                k->env_level = l;
                if (l > 0xFE) {
                    k->env_cnt = 0;
                    k->env_level = 0xFF;
                    k->env_state = 2;
                }
            }
            break;
        case 2:
            if (k->env_hold <= (uint16_t)++k->env_cnt)
                k->env_state = 3;
            break;
        case 3:
            l = (int16_t)(k->env_level - k->env_dr);
            k->env_level = l;
            if ((int)l <= (int)k->env_sl) {
                k->env_cnt = 0;
                k->env_level = (int16_t)k->env_sl;
                k->env_state = 4;
            }
            break;
        case 4:
            if (k->env_st <= (uint16_t)++k->env_cnt)
                k->env_state = 5;
            break;
        case 5:
            d = SONG_BUG == 4 ? k->env_rr : k->env_d2r;
            goto fall;
        case 6:
            d = k->env_rr;
        fall:
            l = (int16_t)(k->env_level - d);
            k->env_level = l;
            if (l < 1) {
                k->env_cnt = 0;
                k->env_level = 0;
                k->env_state = 0;
            }
            break;
        case 7:
            l = (int16_t)(k->env_level / 2 - 0x20);
            if (l < 1) {
                k->env_level = 0;
                k->env_state = 0;
            } else {
                k->env_level = l;
            }
            break;
        }
    }
}

void wave_note_off(uint32_t v, int hard)
{
    song_voice *k = &S.v[v];
    if (hard == 0) {
        if (k->pitch != 0 && k->note_timer != 0)
            k->env_state = 6;
    } else {
        k->env_state = 7;
    }
    k->note_timer = 0;
}

/* the wave step (8.8) for a pitch */
void wave_note_on(uint32_t v, uint32_t pitch, int new_note)
{
    song_voice *k = &S.v[v];
    if (new_note) {
        k->declick = 8;
        k->wpos = 0;
    }
    if (k->pitch != (uint16_t)pitch) {
        int32_t a = (int32_t)(note_freq(pitch) << 8) / (int32_t)note_freq(0x300);
        uint32_t b = ((uint32_t)k->rate_khz << 8) / 48u;
        uint32_t s = (uint32_t)(a * (int32_t)b) >> 8;
        k->step = s ? (uint16_t)(s + (SONG_BUG == 1)) : 1;
    }
    k->pitch = (uint16_t)pitch;
    k->note_timer = 0xFFFF;
    if (new_note)
        k->env_state = 1;
}

void psg_note_on(uint32_t v, uint32_t pitch, int new_note)
{
    song_voice *k = &S.v[v];
    if (k->pitch != (uint16_t)pitch)
        psg_tone_msg(v, pitch);
    k->pitch = (uint16_t)pitch;
    k->note_timer = 0xFFFF;
    if (new_note)
        k->env_state = 1;
}

void psg_note_off(uint32_t v, int hard)
{
    song_voice *k = &S.v[v];
    if (hard == 0) {
        if (k->pitch != 0 && k->note_timer != 0)
            k->env_state = 6;
    } else {
        k->env_state = 7;
    }
    k->note_timer = 0;
}

/* the note table read; past its 108 entries, song_note_tail (song_tables.c: read from the player's ROM at the
   boot) */
static uint32_t note_tab(uint32_t i)
{
    if (i < SONG_NOTE_N)
        return chip_note_pitch[i];
    i = (i - SONG_NOTE_N) * 2u;
    if (i + 1u < SONG_NOTE_TAIL_N)
        return (uint32_t)song_note_tail[i] | (uint32_t)song_note_tail[i + 1u] << 8;
    song_note_far++;                    /* past the tail read at boot: not known (counted, the lockstep reports it) */
    return 0;
}

/* a pitch's frequency */
uint32_t note_freq(uint32_t p)
{
    uint32_t f = note_tab(p >> 4);
    if (p & 15) {
        int32_t d = ((int32_t)(int16_t)note_tab((p >> 4) + 1) - (int32_t)f) * (int32_t)(p & 15);
        f = (uint32_t)((d / 16) + (int32_t)f) & 0xFFFF;
    }
    return f;
}

/* a pitch's FM fnum and block */
uint32_t fm_fnum(uint32_t p)
{
    uint32_t n = (p >> 4) % 12u;
    int32_t f0 = (int16_t)chip_fm_fnum[n];
    int32_t d = (int32_t)(int16_t)chip_fm_fnum[n + 1] - f0;
    uint32_t blk = (p / 0xC0u) & 0xFFFF;
    return ((uint32_t)((d / 16) * (int32_t)(p & 15) + f0) | (blk << 11)) & 0xFFFF;
}

/* a pitch's PSG period, at the NTSC or the PAL clock */
uint32_t psg_period(uint32_t p)
{
    uint32_t f = note_freq(p);
    if (f == 0)
        return 0;                       /* a divide by 0 (unreachable inside the table; the cart's result not known) */
    if (G.rate == 0x3C)
        return (0x369E99u / (f << 5)) & 0xFFFF;
    return (0x361F0Du / (f << 5)) & 0xFFFF;
}

uint32_t mul_clamp(int a, int b, uint32_t c)
{
    uint32_t r = (uint32_t)(b * a) >> 8;
    if (c < r)
        r = c;
    return r & 0xFFFF;
}

uint32_t mul2_clamp(int a, int b, int c, uint32_t d)
{
    uint32_t r = (((uint32_t)(a * b) >> 8) * (uint32_t)c) >> 8;
    if (d < r)
        r = d;
    return r & 0xFFFF;
}

/* a side's gain from the pan tables */
uint32_t pan_gain(uint32_t level, uint32_t pan, int side)
{
    pan &= 0xFF;
    if (side == 1) {
        pan = 0xFF - pan;
    } else if (side != 0) {
        if (side != 2) {
            if (side != 3)
                return 0;
            pan = 0xFF - pan;
        }
        return (uint32_t)chip_pan_A[pan] * (level & 0x1FF) >> 8;
    }
    return (uint32_t)chip_pan_B[pan] * (level & 0x1FF) >> 8;
}
