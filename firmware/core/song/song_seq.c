/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song_seq.c - the sequencer (the tick, the step, the row reader, the module start), the module command
 * interpreter, the per-tick voice effects and the note functions. Written by our team: we reverse engineered the
 * STM32F4's commands as close as possible, with hardware verification. The cart chip is the STM32 microcontroller on
 * the real cartridge.
 */
#include "song.h"
#include "chip_tables.h"

const uint8_t *song_mod;                       /* the module the sequencer plays */
#define MOD        song_mod
#define MOD_NPOS   (MOD[8])
#define MOD_LOOP   (MOD[9])
#define MOD_ROWS   (MOD[0x0A])

/* the row order: the wave voices 10..25, then the PSG voices 6..9, then FM 0..5 */
static uint32_t voice_order(uint32_t i)
{
    return i < 16u ? i + 10u : i < 20u ? i - 10u : i - 20u;
}

/* mode bit 0 = sequencer half, bit 1 = flush half */
void synth_tick(void)
{
    G.busy = 1;
    if (G.mode & 1) {
        psg_volume_msg();
        seq_tick();
        psg_envelope_tick();
        master_fade_tick();
    }
    if (G.mode & 2) {
        z80_packet_flush();
        S.wait_flush = 0;
    }
    G.busy = 0;
}

void seq_tick(void)
{
    uint32_t npos, rows, i, v, pat, idx;
    const uint8_t *row;

    if (S.ready == 0 || S.loading != 0 || S.wait_flush != 0)
        return;
    if (S.playing == 0) {
        for (v = 0; v != 6; v++)
            fm_level_refresh(v);
        return;
    }
    npos = MOD_NPOS;
    rows = MOD_ROWS;
    if (rows == 0)
        rows = 0x100;
    for (v = 0; v != 26; v++)
        voice_tick_effects(v);

    i = S.resume;
    if (i - 1 < 0x19) {
        /* a row was cut short by the Z80 budget: finish it, the timer keeps counting */
        S.tick++;
    } else {
        if ((S.row & 1) && (int)S.tick < (int)(S.speed - 1 + S.tempo_off + S.swing)) {
            S.tick++;
            return;
        }
        if ((int)S.tick < (int)(S.speed - 1 + S.tempo_off)) {
            S.tick++;
            return;
        }
        i = 0;
        S.tick = 0;
    }
    do {
        v = voice_order(i);
        pat = (uint32_t)MOD[(v * npos + S.order + 0x6C) * 2] << 8 | MOD[(v * npos + S.order + 0x6C) * 2 + 1];
        idx = MOD[S.row + pat];
        if (idx == 0) {
            if (v < 6)
                fm_level_refresh(v);
        } else {
            row = MOD + idx * 8 + rows + pat;
            if (v < 10 && (int)G.q_budget < (int)(G.q_cost + row_z80_cost(v, row)))
                break;
            row_parse(v, row);
        }
        i = (i + 1) & 0xFFFF;
    } while (i != 26);
    S.resume = (uint16_t)i;
    if (i != 26)
        return;
    if (S.jump_order == 0xFFFF && S.jump_row == 0xFFFF) {
        if ((int)S.row < (int)(rows - 1)) {
            S.row++;
        } else {
            S.row = 0;
            if ((int)S.order < (int)(npos - 1))
                S.order++;
            else if (S.loop == 0)
                S.playing = 0;
            else
                S.order = MOD_LOOP;
        }
    } else {
        if (S.jump_order != 0xFFFF) {
            S.order = S.jump_order;
            S.jump_order = 0xFFFF;
        }
        if (S.jump_row != 0xFFFF) {
            S.row = S.jump_row;
            S.jump_row = 0xFFFF;
        }
    }
}

/* 8-byte row = note, octave, 3 x (cmd, operand) */
void row_parse(uint32_t v, const uint8_t *row)
{
    uint32_t note = row[0];
    uint32_t raw = 0, pitch = 0;
    int has_note = 0;
    int32_t p;
    const uint8_t *c;
    song_voice *k = &S.v[v];

    if (note == 0x0E) {
        /* the chip clears VOICE 0's arpeggio / slide / trill here, whatever voice the row is on (kept) */
        S.v[0].arp_lo = 0;
        S.v[0].arp_hi = 0;
        S.v[0].pi_step = 0;
        if (S.v[0].mode == 2)
            S.v[0].mode = 0;
        note_off_hard(v);
    } else if (note < 0x0F) {
        if (note != 0) {
            uint32_t oct = row[1];
            if (oct > 11)
                oct = 11;
            raw = note;
            p = (int16_t)(S.transpose - 1 + note + oct * 12);
            if (p < 0)
                p = 0;
            pitch = (uint16_t)(p << 4);
            has_note = 1;
        }
    } else if (note == 0x0F) {
        note_release_soft(v);
    }
    for (c = row + 2; c != row + 8; c += 2)
        module_command(v, c[0], c[1], pitch);
    if (v < 6)
        fm_level_refresh(v);
    if (has_note) {
        /* the chip clears VOICE 3's arpeggio step on every note row (kept) */
        S.v[3].arp_state = 0;
        if (k->ps_step == 0xFFF)
            voice_set_pan(v, (rand_systick() & 15) * 16 + 8 - (SONG_BUG == 8));
        if (k->rdet_n != 0) {
            uint32_t r, n;
            k->rdet_cnt++;
            r = rand_systick() & 0xFFFF;            /* the low 16 bits, as on the cart */
            n = k->rdet_n;
            pitch = (uint16_t)((r % n) - (n >> 1) + pitch);
            if ((int16_t)pitch < 0)
                pitch = 0;
        }
        if (k->detune1 != 0) {
            pitch = (uint16_t)(k->detune1 + pitch);
            k->detune1 = 0;
            if ((int16_t)pitch < 0)
                pitch = 0;
        }
        if (k->mode == 4) {
            k->mode_param = (int16_t)pitch;
        } else {
            if (v != 9)
                raw = pitch;
            note_on(v, raw);
        }
    } else if (k->detune1 != 0 && k->pitch != 0) {
        note_pitch_update(v, (k->pitch + k->detune1) & 0xFFFF);
        k->detune1 = 0;
    }
}

int fm_row_cost(uint32_t v, const uint8_t *row)
{
    const uint8_t *c;
    int cost = 0;
    for (c = row + 2; c != row + 8; c += 2) {
        uint32_t cmd = c[0];
        if (cmd == 0x0F) {
            if (S.v[v].program != c[1])
                cost += 0x2D;
        } else if (cmd > 0x0E && cmd - 0x1A < 4) {
            cost += 5;
        }
    }
    return (int16_t)cost;
}

/* a row's Z80 cost */
int row_z80_cost(uint32_t v, const uint8_t *row)
{
    if (v < 6)
        return (int16_t)(fm_row_cost(v, row) + 0x2A);
    return (v < 10) << 3;
}

void voice_set_pan(uint32_t v, uint32_t pan)
{
    song_voice *k = &S.v[v];
    k->pan = (uint16_t)pan;
    k->gain0 = (uint16_t)pan_gain(k->level, pan, 0);
    k->gain1 = (uint16_t)pan_gain(k->level, pan, 1);
}

void voice_set_level(uint32_t v, uint32_t level)
{
    song_voice *k = &S.v[v];
    k->level = (uint16_t)level;
    k->gain0 = (uint16_t)pan_gain(level, k->pan, 0);
    k->gain1 = (uint16_t)pan_gain(level, k->pan, 1);
}

void program_change(uint32_t v, uint32_t prog)
{
    if (v < 6)
        fm_program_msg(v, prog);
    else if (v < 10)
        psg_program_change(v, prog);
    else
        wave_program_change(v, prog);
}

/* the module command interpreter */
void module_command(uint32_t v, uint32_t cmd, uint32_t op, uint32_t pitch)
{
    song_voice *k = &S.v[v];
    uint32_t code;
    uint16_t lo = op & 15, hi = (op >> 4) & 15;
    (void)pitch;

    switch (cmd) {
    case 0x00:
        return;
    case 0x01:                                  /* level; stops a 05 / 06 slide */
        k->ls_step = 0;
        if (v < 6)
            voice_set_level(v, chip_level_T[(0xFF - (op >> 1)) & 0xFFFF]);
        else if (v > 9)
            voice_set_level(v, chip_level_T[(0xFF - op) & 0xFFFF]);
        else
            voice_set_level(v, ((0xFF - op) & 0xF0) + 8);
        return;
    case 0x02:
        voice_set_pan(v, op);
        return;
    case 0x03:
        k->ls_step = 0;
        code = 0x30E;
        break;
    case 0x04:
        k->ls_step = 0;
        code = 0x40E;
        break;
    case 0x05:                                  /* level slide down / up */
        k->ls_rate = (uint8_t)hi;
        k->ls_step = (int16_t)-lo;
        k->ls_cnt = 0;
        return;
    case 0x06:
        k->ls_rate = (uint8_t)hi;
        k->ls_step = (int16_t)lo;
        k->ls_cnt = 0;
        return;
    case 0x07:                                  /* pitch slide down / up */
        k->pi_rate = (uint8_t)hi;
        k->pi_step = (int16_t)-lo;
        k->pi_cnt = 0;
        return;
    case 0x08:
        k->pi_rate = (uint8_t)hi;
        k->pi_step = (int16_t)lo;
        k->pi_cnt = 0;
        return;
    case 0x09:                                  /* pan slide */
        k->ps_rate = (uint8_t)hi;
        k->ps_step = (int16_t)-lo;
        k->ps_cnt = 0;
        return;
    case 0x0A:
        k->ps_rate = (uint8_t)hi;
        k->ps_step = (int16_t)lo;
        k->ps_cnt = 0;
        return;
    case 0x0B:                                  /* re-strike runs */
    case 0x0C:
        if ((op & 0xFF) == 0 || lo == 0) {
            k->mode = 0;
            return;
        }
        k->mode = 1;
        k->mode_rate = (uint8_t)hi;
        k->mode_param = cmd == 0x0B ? (int16_t)-lo : (int16_t)lo;
        k->mode_cnt = 0;
        return;
    case 0x0D:                                  /* pitch trill */
        if ((op & 0xFF) == 0) {
            k->mode = (uint8_t)op;
            return;
        }
        k->mode = 2;
        goto trill;
    case 0x0E:                                  /* level trill */
        if ((op & 0xFF) == 0) {
            k->mode = (uint8_t)op;
            return;
        }
        k->mode = 3;
    trill:
        k->mode_rate = (uint8_t)hi;
        k->mode_param = (int16_t)lo;
        k->mode_cnt = 0;
        k->trill = 0;
        return;
    case 0x0F:                                  /* program change */
        if (k->program != op)
            program_change(v, op);
        return;
    case 0x10:                                  /* random detune range */
        k->rdet_n = lo;
        return;
    case 0x11:                                  /* one-shot detune */
        k->detune1 = (op & 0xF0) == 0 ? (int16_t)lo : (int16_t)-lo;
        return;
    case 0x12:                                  /* random pan */
        k->ps_step = 0xFFF;
        k->ps_rate = (uint8_t)op;
        k->ps_cnt = 0;
        if (op == 0)
            k->ps_step = 0;
        return;
    case 0x13:
        k->ls_step = 0;
        code = 0x130E;
        break;
    case 0x14:                                  /* arpeggio with re-strike / legato */
    case 0x15:
        k->arp_hi = (int16_t)(hi << 4);
        k->arp_lo = (int16_t)(lo << 4);
        k->arp_restrike = cmd == 0x14;
        k->arp_state = 0;
        k->arp_cnt = 0;
        k->arp_rate = 0;
        return;
    case 0x16:
        k->arp_cnt = 0;
        k->arp_rate = (uint8_t)op;
        return;
    case 0x17:
        code = 0x170E;
        break;
    case 0x18:                                  /* note delay */
        if ((op & 0xFF) == 0) {
            k->mode = (uint8_t)op;
            return;
        }
        k->mode = 4;
        k->mode_rate = (uint8_t)op;
        k->mode_cnt = 0;
        return;
    case 0x19:
        code = 0x190E;
        break;
    case 0x1A: case 0x1B: case 0x1C: case 0x1D: /* operator TL */
        if (v < 6) {
            fm_tl_msg(v, (cmd - 0x1A) & 0xFFFF, op);
            return;
        }
        code = 0x0E | cmd << 8;
        break;
    case 0x55:                                  /* sax-layer marker */
        if (k->sax == 0) {
            k->sax = 1;
            if (S.sax_flag == 0)
                k->muted = 1;
        }
        return;
    case 0xBB:                                  /* boost flag */
        k->boost = 1;
        return;
    case 0xE0: case 0xF0: case 0xFF:
        return;
    case 0xFA:                                  /* swing */
        S.swing = op & 15;
        return;
    case 0xFB:                                  /* pattern break */
        if (MOD_NPOS <= (uint32_t)S.order + 1 || (MOD_ROWS != 0 && MOD_ROWS <= op))
            return;
        S.jump_order = (uint16_t)(S.order + 1);
        S.jump_row = (uint16_t)op;
        return;
    case 0xFC:                                  /* row skip */
        if (MOD_ROWS != 0 && (int)MOD_ROWS <= (int)(S.row + op))
            return;
        S.jump_row = (uint16_t)(op + S.row);
        return;
    case 0xFD:                                  /* position jump */
        S.jump_order = (uint16_t)op;
        if (MOD_NPOS <= op)
            S.jump_order = 0;
        S.jump_row = 0;
        return;
    case 0xFE:                                  /* set speed */
        S.speed = (uint16_t)op;
        return;
    default:
        code = 0x0F | cmd << 8;
        break;
    }
    board_trace(code, 0, 0);
}

/* the crisis jitter, then the back-end; skipped while muted */
void note_on(uint32_t v, uint32_t pitch)
{
    song_voice *k = &S.v[v];
    if (v != 9 && S.crisis != 0) {
        int32_t j = (int16_t)(S.crisis * ((rand_systick() & 15) - 7));
        int16_t p = (int16_t)((int16_t)pitch + (int16_t)(j / 4));
        if (p < 0)
            p = 0;
        pitch = (uint16_t)p;
    }
    if (k->muted != 0)
        return;
    if (v < 6) {
        fm_note_msg(v, pitch, 1);
        k->env_level = (int16_t)k->level;
    } else if (v < 10) {
        psg_note_on(v, pitch, 1);
    } else {
        wave_note_on(v, pitch, 1);
    }
}

void note_release_soft(uint32_t v)
{
    if (v < 6) {
        fm_keyoff_msg(v, 0);
        S.v[v].env_level = (int16_t)(S.v[v].env_level / 2);
    } else if (v < 10) {
        psg_note_off(v, 0);
    } else {
        wave_note_off(v, 0);
    }
}

void note_off_hard(uint32_t v)
{
    if (v < 6) {
        fm_keyoff_msg(v, 1);
        S.v[v].env_level = 0;
    } else if (v < 10) {
        psg_note_off(v, 1);
    } else {
        wave_note_off(v, 1);
    }
}

/* legato */
void note_pitch_update(uint32_t v, uint32_t pitch)
{
    if (S.v[v].muted != 0)
        return;
    if (v < 6)
        fm_note_msg(v, pitch, 0);
    else if (v < 10)
        psg_note_on(v, pitch, 0);
    else
        wave_note_on(v, pitch, 0);
}

static uint32_t clamp_pitch(int32_t p)
{
    if (p <= 0)
        return 1;
    if (p > 0x5FF)
        return 0x5FF;
    return (uint32_t)p;
}

/* the note timer, level / pan / pitch slides, the arpeggio, modes 1-4 */
void voice_tick_effects(uint32_t v)
{
    song_voice *k = &S.v[v];
    int32_t s, t;
    uint16_t u;

    u = (uint16_t)(k->note_timer - 1);
    if (u < 0xFFFE && (k->note_timer = u) == 0)
        note_release_soft(v);

    s = k->ls_step;
    if (s != 0 && k->pitch != 0) {
        if (k->ls_cnt + 1u < k->ls_rate) {
            k->ls_cnt++;
        } else {
            k->ls_cnt = 0;
            t = k->level + s;
            voice_set_level(v, t < 0x100 ? (uint32_t)(t & ~(t >> 31)) : 0xFF);
        }
    }
    s = k->ps_step;
    if (s != 0 && s != 0xFFF && k->pitch != 0) {
        if (k->ps_cnt + 1u < k->ps_rate) {
            k->ps_cnt++;
        } else {
            k->ps_cnt = 0;
            t = k->pan + s;
            voice_set_pan(v, t < 0x100 ? (uint32_t)(t & ~(t >> 31)) : 0xFF);
        }
    }
    s = k->pi_step;
    if (s != 0 && k->pitch != 0) {
        if (k->pi_cnt + 1u < k->pi_rate) {
            k->pi_cnt++;
        } else {
            k->pi_cnt = 0;
            note_pitch_update(v, clamp_pitch(k->pitch + s) & 0xFFFF);
        }
    }
    s = k->arp_lo;
    if ((s != 0 || k->arp_hi != 0) && k->pitch != 0) {
        uint32_t c = k->arp_cnt + 1u, p0 = k->pitch;
        if (c < k->arp_rate) {
            k->arp_cnt = (uint8_t)c;
            if (k->arp_rate <= (c & 0xFF) + 1 && k->arp_restrike)
                note_off_hard(v);
        } else {
            uint8_t st;
            uint32_t p;
            k->arp_cnt = 0;
            st = k->arp_state;
            if (st == 0) {
                st = 1;
            } else if (st == 1) {
                st = 2;
                s = k->arp_hi - s;
            } else {
                s = -k->arp_hi;
                st = 0;
            }
            k->arp_state = st;
            p = clamp_pitch((int32_t)p0 + s);
            if (k->arp_restrike == 0) {
                note_pitch_update(v, p & 0xFFFF);
            } else {
                note_off_hard(v);
                note_on(v, p & 0xFFFF);
            }
        }
    }
    if (k->mode == 0)
        return;
    if (k->mode_cnt + 1u < k->mode_rate) {
        k->mode_cnt++;
        return;
    }
    k->mode_cnt = 0;
    switch (k->mode) {
    case 1:                                     /* re-strike run */
        t = k->mode_param * 16 + k->pitch;
        if ((uint32_t)t < 0x5FF) {
            note_on(v, (uint32_t)t & 0xFFFF);
            k->arp_state = 0;
        } else {
            k->mode = 0;
        }
        return;
    case 2:                                     /* pitch trill */
        if (k->pitch == 0)
            return;
        if (k->trill == 0) {
            k->trill = 1;
            s = k->mode_param;
        } else {
            k->trill = 0;
            s = -k->mode_param;
        }
        note_pitch_update(v, clamp_pitch(s + k->pitch) & 0xFFFF);
        return;
    case 3:                                     /* level trill */
        if (k->pitch == 0)
            return;
        if (k->trill == 0) {
            k->trill = 1;
            t = k->level - k->mode_param;
        } else {
            k->trill = 0;
            t = k->level + k->mode_param;
        }
        voice_set_level(v, t < 0x100 ? (uint32_t)(t & ~(t >> 31)) : 0xFF);
        return;
    case 4:                                     /* delayed note-on */
        note_on(v, (uint16_t)k->mode_param);
        k->arp_state = 0;
        k->mode = 0;
        return;
    }
}

/* the module start: the header check, the effects cleared, each voice's level / program / pan from the header */
uint32_t bgm_module_init(void)
{
    uint32_t v;
    const uint8_t *h = MOD + 0x10;
    if (MOD[0] != 'W' || MOD[3] != 'M')
        return 0;
    music_fx_reset(0);
    S.tick = 0;
    S.jump_order = 0xFFFF;
    S.jump_row = 0xFFFF;
    S.order = 0;
    S.row = 0;
    S.speed = MOD[7];
    S.swing = 0;
    S.resume = 26;
    G.r14 = 0;
    G.r16 = 0;
    G.pending = 0;
    if (SONG_BUG != 17)
        board_frame_arm(0u);                    /* (the logic owns frame_pending) */
    G.q_len = 0;
    G.q_last = 0;
    Z80Q[0] = 0;
    for (v = 0; v != 26; v++, h++) {
        song_voice *k = &S.v[v];
        memset(&k->ls_rate, 0, 0x24);
        k->wlen = 0;
        k->env_state = 0;
        k->env_level = 0;
        k->pitch = 0;
        k->muted = 0;
        k->declick = 0;
        k->program = 0xFFFF;
        k->fm_vol_sent = 0xFFFF;
        k->fm_pan_sent = 0xFFFF;
        if (v > 9 || (note_off_hard(v), v > 5))
            program_change(v, h[0x1A]);
        voice_set_level(v, chip_level_T[0xFF - h[0]]);
        voice_set_pan(v, h[0x4E]);
    }
    S.wait_flush = 1;
    G.r16 = 1;
    SONG_FRAME_PAD16();                         /* test build 5 on: brain hygiene (song.h) */
    return 1;
}

void music_fx_reset(int all)
{
    S.echo_on = 0;
    S.transpose = 0;
    S.tempo_off = 0;
    S.crisis = 0;
    S.sax_flag = 0;
    S.flag2 = 0;
    S.flag3 = 0;
    if (all) {
        S.boost_state = 0;
        S.boost = 0;
        S.boost_target = 0;
    }
}

/* the random number the cart draws */
uint32_t rand_systick(void)
{
    uint32_t t = board_rand_src();
    return t ^ t << 16;
}
