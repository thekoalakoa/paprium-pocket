/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song_posts.c - the audio posts: the cart chip dispatcher's handler fragments for 88, C9, CA, 8C, 8D, 8E,
 * D0, D1, D2, D3, D5, D6 and the 9494 tick, split in two (core/song/README.md):
 *   song_gate()  L1, at the arrival: every gate in the cart chip's order with its refusal ($1FE6 bit 10 (A) / 9 (B)
 *                and a trace), and the parts the 68000 can see (the 8C job push with $1FE6 bits 14 / 8);
 *   song_body()  L2b, in arrival order: the engine part.
 * The cart chip is the STM32 microcontroller on the real cartridge. Written by our team: we reverse engineered the
 * STM32F4's commands as close as possible, with hardware verification. The gate order and codes are
 * core/dispatch/disp.c's, with the gaps it leaves to the song engine filled as the cart chip has them: 8C's module
 * range / null slot / header check, D1's SFX count, 8E's range. Every gate reads only boot-time state (S / G / SFX
 * ready, the BGM and SFX tables) or the job queue, so L1 decides exactly what the cart chip decides at the same
 * arrival.
 * The dispatcher (MBX) owns the entry clears, the request bit and the finish (mbx_done).
 */
#include "song.h"
#include "chip_tables.h"

#define LO(c)     ((c)->word & 0xFFu)
#define ARG(c, i) ((c)->a[i])
#define ARGB(c, i) ((c)->a[i] & 0xFFu)
#define IDX(c)    (((c)->word >> 8) & 0x3Fu)

/* refusal: $1FE6 bit 10 (A) / bit 9 (B), trace code | word << 8 */
void song_refuse(mbx_ctx *c, uint32_t code)
{
    if (c->mbox == 1)
        STATUS(1, 3, 0x400);
    if (c->mbox == 2)
        STATUS(1, 3, 0x200);
    board_trace(c->word << 8 | code, 0, 0);
}

#define REFUSE(code) do { song_refuse(c, (code)); return SONG_DONE; } while (0)

/* the 9-bit SFX level of D1 and D3; a level index past the table is masked here (the cart chip reads past its
   table there: never posted, and what it reads is not known) */
static uint32_t sfx_level(uint32_t v)
{
    return (uint32_t)(((int32_t)(int16_t)chip_level_T[v & 0x1FFu] + (int32_t)v) / 2) & 0xFFFF;
}

/* ================================================================================================================
 * L1: the gates
 * ================================================================================================================ */
uint32_t song_gate(mbx_ctx *c)
{
    uint32_t n, id;
    const uint8_t *p;
    switch (IDX(c)) {
    case 0x08:                                          /* 88 */
    case 0x09:                                          /* C9 */
    case 0x0A:                                          /* CA */
        if (G.ready == 0)
            REFUSE(6);
        return SONG_OK;
    case 0x0C:                                          /* 8C */
        if (board_job_full())
            REFUSE(5);
        if (S.ready == 0)
            REFUSE(6);
        n = LO(c) & 0x3F;
        if (n > bgm_table[0] || n == 0)
            REFUSE(7);
        if (bgm_table[n] == 0)
            return SONG_DONE;                           /* a null slot: ignored, the old music keeps playing */
        p = SONG_FLASH8(bgm_table[n]);
        if (p[0] != 0x81 && p[2] != 0x0E) {             /* refusal 7, then trace 0x0D */
            song_refuse(c, 7);
            board_trace(c->word << 8 | 0x0D, 0, 0);
            return SONG_DONE;
        }
        /* bit 14 (jobs pending), bit 8 (the last job's failure) cleared, the unpack job */
        STATUS(1, 3, 0x4000);
        STATUS(0, 3, 0x100);
        board_job_8c(bgm_table[n], n);
        return SONG_OK;
    case 0x0D:                                          /* 8D */
        if (S.ready == 0)
            REFUSE(6);
        return SONG_OK;
    case 0x0E:                                          /* 8E */
        if (G.ready == 0 || S.ready == 0)
            REFUSE(6);
        if ((LO(c) & 0x3F) > bgm_table[0])
            REFUSE(7);
        return SONG_OK;
    case 0x10:                                          /* D0 */
        if (LO(c) == 0 || ARG(c, 0) > 0x19 || c->args == 0)
            REFUSE(7);
        if (S.ready == 0)
            REFUSE(6);
        return SONG_OK;
    case 0x11:                                          /* D1 */
        id = LO(c) & 0x7F;
        if (id >= sfx_table[0].l0 || id == 0)
            REFUSE(7);
        if (c->args != 0 && (ARG(c, 0) & 0xFF) == 0)
            REFUSE(7);
        if (SFX.ready == 0)                             /* with or without args */
            REFUSE(6);
        return SONG_OK;
    case 0x12:                                          /* D2 */
        if (LO(c) == 0)
            REFUSE(7);
        if (SFX.ready == 0)
            REFUSE(6);
        return SONG_OK;
    case 0x13:                                          /* D3 (A: refusal 7) */
        if (c->mbox == 1 || LO(c) == 0 || c->args == 0)
            REFUSE(7);
        if (SFX.ready == 0)
            REFUSE(6);
        return SONG_OK;
    case 0x14:                                          /* the frame tick: its bit 13 at the arrival */
        if (G.ready != 0)
            STATUS(0, 3, 0x2000);
        return SONG_OK;
    case 0x15:                                          /* D5 */
        if (SFX.ready == 0)
            REFUSE(6);
        if (LO(c) > 1 || (LO(c) == 1 && c->args == 0))
            REFUSE(7);
        return SONG_OK;
    case 0x16:                                          /* D6 */
        if (S.ready == 0)
            REFUSE(6);
        if (LO(c) > (SONG_BUG == 40 ? 8u : 7u))         /* (planted 40, gatelock.py: D608 taken) */
            REFUSE(7);
        if (LO(c) == 5 && (c->args == 0 || (ARG(c, 0) & 0x7F) > 0x19))
            REFUSE(7);
        return SONG_OK;
    }
    return SONG_DONE;                                   /* not an audio post */
}

/* ================================================================================================================
 * L2b: the bodies
 * ================================================================================================================ */

/* ---- the 9494 frame tick (run, bail, skip) ---- */
static int tick_flush_armed;

void song_tick_head(void)
{
    if (G.ready == 0 || G.busy != 0) {                  /* bail: the flush timer off, PSG volumes, the packet now */
        G.r1a = 0;
        board_flush_timer(0);
        psg_volume_only();
        z80_packet_flush();
        tick_flush_armed = 0;
        return;
    }
    G.frame++;
    if (G.rate == 0x32 && G.frame >= 5)                 /* PAL 0..4 */
        G.frame = 0;
    else if (G.rate == 0x3C && G.frame >= 6)            /* NTSC 0..5 */
        G.frame = 0;
    G.r16 = 0;
    G.pending = 1;                                      /* frame pending (the synth's ARM register) */
    board_frame_arm(1u);
    G.r1a = 0;
    G.mode = 1;
    if (G.rate == 0x3C && G.frame == 0)
        psg_volume_only();                              /* NTSC: the 6th frame skips the sequencer */
    else
        synth_tick();
    G.mode = 2;
    board_flush_timer(1);                               /* the chip's TIM14 one-shot fires at once */
    tick_flush_armed = 1;
}

/* the TIM14 handler: the timer off, then the synth tick in mode 2 (the flush half) */
void song_tick_flush(void)
{
    if (!tick_flush_armed)
        return;
    tick_flush_armed = 0;
    board_flush_timer(0);
    synth_tick();
}

/* ---- 8C: the music stops now, the job loads the module ---- */
static void body_8c(mbx_ctx *c)
{
    S.playing = 0;
    S.loading = 0;
    S.next_track = 0;
    S.track = (uint16_t)(LO(c) & 0x3F);
    S.pan = S.pan_target;
    S.level = S.lvl_target;
    S.gain0 = (uint16_t)pan_gain(S.level, S.pan, 0);
    S.gain1 = (uint16_t)pan_gain(S.level, S.pan, 1);
    S.stop_at_zero = 0;
    S.loop = (c->word >> 7) & 1;
    S.loading = 1;
}

static void sax_mute(uint32_t m)
{
    song_voice *k;
    for (k = &S.v[0]; k != &S.v[26]; k++)
        if (k->sax != 0)
            k->muted = (uint16_t)m;
}

void song_body(mbx_ctx *c)
{
    uint32_t t, v, ch;
    int32_t ts;
    switch (IDX(c)) {
    case 0x08:                                          /* 88: the configuration */
        audio_config(c->word & 0x7F);
        return;
    case 0x09:                                          /* C9 */
        t = chip_level_T[LO(c)];
        if (G.c9_x1 == 0)
            t = ((uint32_t)(int16_t)chip_level_T[LO(c)] * 0x4Bu) / 100u;
        S.lvl_target = (uint16_t)t;
        if (c->args == 0) {
            S.pan_target = 0x80;
            S.step = 0;
            return;
        }
        S.pan_target = (uint16_t)ARGB(c, 0);
        S.step = (uint16_t)ARGB(c, 1);
        return;
    case 0x0A:                                          /* CA */
        ts = ((int16_t)chip_level_T[LO(c)] + (int32_t)LO(c)) / 2;
        if (G.c9_x1 == 0)
            ts = (int32_t)(((uint32_t)ts * 0x4Bu) / 100u);
        SFX.lvl_target = (uint16_t)ts;
        if (c->args == 0) {
            SFX.pan_target = 0x80;
            SFX.step = 0;
            return;
        }
        SFX.pan_target = (uint16_t)ARGB(c, 0);
        SFX.step = (uint16_t)ARGB(c, 1);
        return;
    case 0x0C:
        body_8c(c);
        return;
    case 0x0D:                                          /* 8D */
        S.lvl_target = 0;
        S.step = (uint16_t)LO(c);
        S.stop_at_zero = 1;
        if (LO(c) != 0 && S.level != 0)
            return;
        S.level = 0;
        S.playing = 0;
        return;
    case 0x0E:                                          /* 8E */
        t = LO(c) & 0x3F;
        if (t == 0)
            S.loop = (uint16_t)(LO(c) >> 7);
        if (bgm_table[t] == 0)
            return;
        S.next_track = (uint16_t)t;
        return;
    case 0x10:                                          /* D0: a direct note */
        v = ARG(c, 0);
        program_change(v, LO(c));
        voice_set_level(v, chip_level_T[ARG(c, 2) & 0xFF]);
        voice_set_pan(v, ARG(c, 3));
        note_on(v, ((ARG(c, 1) - 1u) << 4) & 0xFFFF);
        S.v[v].note_timer = ARG(c, 4);
        return;
    case 0x11:                                          /* D1: the SFX start */
        if (c->args == 0) {
            sfx_start(0xFF, LO(c) & 0x7F, 0xFF, 0x80, 0);
            return;
        }
        sfx_start(ARG(c, 0), LO(c) & 0x7F, sfx_level(ARG(c, 1)), ARG(c, 2), ARG(c, 3));
        return;
    case 0x12:                                          /* D2 */
        ch = sfx_alloc_channel(LO(c), 0);
        sfx_stop(ch, c->args ? ARG(c, 0) : 0);
        return;
    case 0x13:                                          /* D3 */
        ch = sfx_alloc_channel(LO(c), 0);
        sfx_update(ch, sfx_level(ARG(c, 0)), ARG(c, 1), ARG(c, 2));
        return;
    case 0x14:                                          /* the tick: both halves in one item */
        song_tick_head();
#if defined(SONG_TEST_HOOKS)
        if (song_test_mid)
            song_test_mid();
#endif
        song_tick_flush();
        return;
    case 0x15:                                          /* D5 */
        if (LO(c) == 0) {
            SFX.echo_on = 0;
            return;
        }
        SFX.echo_on = 1;
        SFX.echo_gain = (uint16_t)ARGB(c, 0);
        SFX.echo_delay = (uint16_t)ARGB(c, 1);
        return;
    case 0x16:                                          /* D6: the sub-table */
        switch (LO(c)) {
        case 0:                                         /* reset */
            S.echo_on = 0;
            S.crisis = 0;
            S.tempo_off = 0;
            S.transpose = 0;
            S.boost_state = 0;
            S.boost_target = 0;
            S.sax_flag = 0;
            S.flag2 = 0;
            S.flag3 = 0;
            sax_mute(1);
            return;
        case 1:                                         /* BGM echo */
            S.echo_on = 1;
            if (c->args == 0) {
                S.echo_gain = 0;
                S.echo_delay = 0;
                return;
            }
            S.echo_gain = (int16_t)ARGB(c, 0);
            S.echo_delay = (uint16_t)ARGB(c, 1);
            return;
        case 2:                                         /* crisis jitter */
            S.crisis = (uint16_t)(c->args ? ARG(c, 0) & 7 : 0);
            return;
        case 3:                                         /* tempo offset */
            S.tempo_off = (int16_t)((c->args ? ARGB(c, 0) : 0x80) - 0x80);
            return;
        case 4:                                         /* transpose */
            S.transpose = (int16_t)((c->args ? ARGB(c, 0) : 0x80) - 0x80);
            return;
        case 5:                                         /* mute / unmute one voice */
            v = ARG(c, 0) & 0x7F;
            S.v[v].muted = (uint16_t)((ARG(c, 0) >> 7) & 1);
            return;
        case 6:                                         /* sax flags */
            S.sax_flag = ARG(c, 0) & 1;
            S.flag2 = ARG(c, 1) & 1;
            S.flag3 = ARG(c, 2) & 1;
            sax_mute(S.sax_flag == 0);
            return;
        case 7:                                         /* boost (ignored in YM-DAC mode) */
            if (G.ymdac == 1)
                return;
            S.boost_state = 1;
            S.boost_target = (uint16_t)ARGB(c, 0);
            return;
        }
        return;
    }
}

/* ---- the main-loop job kind 2 tail: the module is unpacked, start it ---- */
int song_job_module(uint32_t report)
{
    S.loading = 0;
    if (bgm_module_init() == 0) {
        if (report != 0)
            STATUS(1, 3, 0x100);
        board_trace(0x0D, 0, 0);
        return 0;
    }
    S.playing = 1;
    return 1;
}
