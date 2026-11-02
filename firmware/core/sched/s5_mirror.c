/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/sched/s5_mirror.c - the engine's fields as the synth reads them (docs/MCU_INTERFACE.md v1.3 3.10.1, 3.10.3,
 * 3.10.4, 3.10.5). Built only by the s5 variants (fwbuild.json: FW_S5, the full firmware); no FW_S5 = 0 image links it.
 *
 * The song engine (core/song) keeps the cart chip's RAM layouts in WRAM (S, G, SFX),
 * so each of its routines works on the same records as the cart chip's (the cart chip is the STM32 microcontroller on
 * the real cartridge; WRAM is the MCU's working RAM). The synth (region 0x06) holds the same fields where the logic
 * reads them: the 16 wave voices (VOICE[v] = the cart chip's voice 10 + v, record k = S + 0x58 + 0x70 (10 + v)), the
 * 8 SFX channels (SFX[c], record R = SFX + 0x20 + 0x34 c) and the globals (FLAGS, WMASTER, WBOOST, SMASTER, SMCFG,
 * ECHOB, ECHOS, YMFILT). This file is the copy between the two, inside every item's bracket (3.10.5: logic-owned
 * fields are read, and every field is written, only between synth_begin and synth_end):
 *   s5_mirror_in   (synth_begin, after STATUS.BUSY = 0): the logic's fields into the WRAM records (VOICE POS, DECLICK,
 *                  LAST_L / LAST_R, ENV_LEVEL, ENV_CNT, ENV_STATE; SFX PTR, POS, ID, Y, DELAY; the ECHOB / ECHOS ring
 *                  indexes; YMFILT; from STATUS / SCHED the block count, frame_pending, cur / fill
 *                  halves, the frame's count). The logic writes them only while it mixes a
 *                  block, and every mixed block moves BLKCNT, so the windows are read again only when BLKCNT has moved
 *                  since the last full read (or a second has gone by: a 4,096-block wrap with no item between);
 *   s5_mirror_out  (board_synth_put, at every item's end, before its DONE; an item with no arrival of its own moves no
 *                  DONE but writes too): every field whose engine value differs from what the synth last held (the
 *                  value read back, or the one written last) is stored with a store of the field's own size, so no
 *                  store can carry a stale neighbour over a field the logic moved (the module-start item has no arrival
 *                  of its own: a block can mix inside it, 3.10.5, as TIM6 preempts the cart chip's thread-mode job
 *                  tail);
 *   s5_mirror_pass_in  (the main-loop pass's own bracket): only what the pass reads from the logic: the wave voices'
 *                  ENV_LEVEL (with ENV_CNT, the same word) and the block count.
 * Conversions (3.10.3 / 3.10.4): a voice's BASE = its sample's CRAM byte in BANK; an SFX channel's PTR / BASE = the
 * sample's CRAM byte in SFXBANK (the ROM's SFX words, as the boot overlay of test build 4b copies them); the u16
 * envelope state, rates, FORMAT and RATE as their low bytes (every value their writers produce fits). The first store after a reset
 * writes every field (3.10.6: the state RAM is not reset; the engine's records are, at the firmware's boot), and
 * nothing is read back before it.
 * Planted (SONG_BUG, song.h): 29 no read-back of the windows, 30 the SFX windows not written, 31 the voice BASE
 * converted with the SFX bank's offset. */
#include <stdint.h>
#include "board.h"
#include "sched.h"
#include "song.h"
#include "tdiag.h"

#if !FW_S5
#error "core/sched/s5_mirror.c is the stage-5 firmware's (FW_S5)"
#endif

/* what the synth holds, word for word as the windows lay it out (the last value read back or written) */
static uint32_t sh_v[16][11];                  /* (wram_upper: pocket88k.json upper_bss_objects) */
static uint32_t sh_s[8][8];
static uint32_t sh_g[8];                        /* FLAGS WMASTER WBOOST SMASTER SMCFG ECHOB ECHOS YMFILT */
static uint32_t blk_full, t_full;               /* BLKCNT and TIMER at the last full read-back */
static uint8_t primed, force;                   /* the first store after a reset wrote every field */
s5_mirror_stats_t s5_mirror_stats;

/* field layouts of a window word: W one u32, H two u16, Q u8 u8 u16, B four u8, E u16 u8 u8 */
enum { L_W, L_H, L_Q, L_B, L_E };

static void put(uint32_t off, uint32_t v, uint32_t *h, uint32_t lay)
{
    uint32_t d = v ^ *h;
    if (force)
        d = UINT32_MAX;
    if (!d)
        return;
    *h = v;
#if !PPM_RELEASE && !TDIAG_LEAN
    s5_mirror_stats.words++;
#endif
    switch (lay) {
    case L_W:
        brd_synth_wr32(off, v);
        break;
    case L_H:
        if (d & 0xFFFFu)
            brd_synth_wr16(off, v);
        if (d >> 16)
            brd_synth_wr16(off + 2u, v >> 16);
        break;
    case L_Q:
        if (d & 0xFFu)
            brd_synth_wr8(off, v);
        if (d & 0xFF00u)
            brd_synth_wr8(off + 1u, v >> 8);
        if (d >> 16)
            brd_synth_wr16(off + 2u, v >> 16);
        break;
    case L_E:
        if (d & 0xFFFFu)
            brd_synth_wr16(off, v);
        if (d & 0xFF0000u)
            brd_synth_wr8(off + 2u, v >> 16);
        if (d >> 24)
            brd_synth_wr8(off + 3u, v >> 24);
        break;
    default:
        if (d & 0xFFu)
            brd_synth_wr8(off, v);
        if (d & 0xFF00u)
            brd_synth_wr8(off + 1u, v >> 8);
        if (d & 0xFF0000u)
            brd_synth_wr8(off + 2u, v >> 16);
        if (d >> 24)
            brd_synth_wr8(off + 3u, v >> 24);
        break;
    }
}

#define LO8(x)          ((uint32_t)(x) & 0xFFu)
#define LO16(x)         ((uint32_t)(uint16_t)(x))

static uint32_t voice_base(uint32_t bus)
{
    return (bus - song_v.sdir_bus + (SONG_BUG == 31 ? BRD_CRAM_SFXBANK_OFF : BRD_CRAM_BANK_OFF)) & BRD_CRAM_OFF_MASK;
}

static uint32_t sfx_ptr(uint32_t bus) { return (bus - song_v.sfx_bus + BRD_CRAM_SFXBANK_OFF) & BRD_CRAM_OFF_MASK; }

/* the scheduler's words from STATUS / SCHED (read every time: an instant serviced with no block moves them too) */
static void sched_words(uint32_t st)
{
    G.blkcnt = (uint16_t)BRD_SYNTH_BLKCNT(st);
    G.pending = (st & BRD_SYNTH_FPEND) ? 1u : 0u;
    G.r38 = (st & BRD_SYNTH_FILL) ? 1u : 0u;
    G.r36 = (st & BRD_SYNTH_CUR) ? 1u : 0u;
    G.r3a = (uint16_t)BRD_SYNTH_CNT(brd_synth_sched());
}

void s5_mirror_in(uint32_t st)
{
    uint32_t v, c, x, blk = BRD_SYNTH_BLKCNT(st), now;
    if (!primed)
        return;                                 /* the windows hold nothing of ours yet (3.10.6) */
    sched_words(st);
    now = brd_now();
    if (SONG_BUG == 29 || (blk == blk_full && (uint32_t)(now - t_full) < BRD_CLK_HZ))
        return;                                 /* no block mixed since the last read: the logic wrote nothing */
    blk_full = blk;
    t_full = now;
#if !PPM_RELEASE && !TDIAG_LEAN
    s5_mirror_stats.reads++;
#endif
    for (v = 0; v < 16u; v++) {
        song_voice *k = &S.v[10u + v];
        uint32_t o = BRD_SY_VOICE(v), *h = sh_v[v];
        x = brd_synth_rd(o + 0x00u);            /* POS */
        k->wpos = x;
        h[0] = x;
        x = brd_synth_rd(o + 0x10u);            /* STEP | DECLICK */
        k->declick = (int16_t)(x >> 16);
        h[4] = x;
        x = brd_synth_rd(o + 0x18u);            /* LAST_L | LAST_R */
        k->last_l = (int16_t)x;
        k->last_r = (int16_t)(x >> 16);
        h[6] = x;
        x = brd_synth_rd(o + 0x1Cu);            /* ENV_LEVEL | ENV_CNT */
        k->env_level = (int16_t)x;
        k->env_cnt = (uint16_t)(x >> 16);
        h[7] = x;
        x = brd_synth_rd(o + 0x20u);            /* ENV_STATE | BB | MUTE */
        k->env_state = (uint16_t)(x & 0xFFu);
        h[8] = x;
    }
    for (c = 0; c < 8u; c++) {
        sfx_ch *r = &SFX.ch[c];
        uint32_t o = BRD_SY_SFX(c), *h = sh_s[c];
        x = brd_synth_rd(o + 0x00u);            /* PTR (a CRAM byte: back to the engine's bus address) */
        r->cur = song_v.sfx_bus + ((x & BRD_CRAM_OFF_MASK) - BRD_CRAM_SFXBANK_OFF);
        h[0] = x;
        x = brd_synth_rd(o + 0x08u);            /* POS */
        r->pos = x;
        h[2] = x;
        x = brd_synth_rd(o + 0x10u);            /* FORMAT | RATE | ID */
        r->id = (uint16_t)(x >> 16);
        h[4] = x;
        x = brd_synth_rd(o + 0x18u);            /* LOOP | FILT | Y */
        r->r2a = (uint16_t)(x >> 16);
        h[6] = x;
        x = brd_synth_rd(o + 0x1Cu);            /* DELAY */
        r->pitch = (uint16_t)x;
        h[7] = x;
    }
    x = brd_synth_rd(BRD_SY_ECHOB);
    S.echo_wr = (uint16_t)(x >> 24);
    sh_g[5] = x;
    x = brd_synth_rd(BRD_SY_ECHOS);
    SFX.r1a = (uint16_t)(x >> 24);
    sh_g[6] = x;
    x = brd_synth_rd(BRD_SY_YMFILT);
    G.filt0 = (int16_t)x;
    G.filt1 = (int16_t)(x >> 16);
    sh_g[7] = x;
}

void s5_mirror_pass_in(uint32_t st)
{
    uint32_t v, x;
    if (!primed)
        return;
    sched_words(st);
#if !PPM_RELEASE && !TDIAG_LEAN
    s5_mirror_stats.pass_reads++;
#endif
    for (v = 0; v < 16u; v++) {
        song_voice *k = &S.v[10u + v];
        x = brd_synth_rd(BRD_SY_VOICE(v) + 0x1Cu);
        k->env_level = (int16_t)x;
        k->env_cnt = (uint16_t)(x >> 16);
        sh_v[v][7] = x;
    }
}

void s5_mirror_out(void)
{
    uint32_t v, c, f;
    force = !primed;
    for (v = 0; v < 16u; v++) {
        const song_voice *k = &S.v[10u + v];
        uint32_t o = BRD_SY_VOICE(v), *h = sh_v[v];
        put(o + 0x00u, k->wpos, &h[0], L_W);
        put(o + 0x04u, k->wlen, &h[1], L_W);
        put(o + 0x08u, k->wloop, &h[2], L_W);
        put(o + 0x0Cu, voice_base(k->wdata), &h[3], L_W);
        put(o + 0x10u, LO16(k->step) | LO16(k->declick) << 16, &h[4], L_H);
        put(o + 0x14u, LO16(k->gain0) | LO16(k->gain1) << 16, &h[5], L_H);
        put(o + 0x18u, LO16(k->last_l) | LO16(k->last_r) << 16, &h[6], L_H);
        put(o + 0x1Cu, LO16(k->env_level) | LO16(k->env_cnt) << 16, &h[7], L_H);
        put(o + 0x20u, LO8(k->env_state) | LO8(k->boost) << 8 | LO16(k->muted) << 16, &h[8], L_Q);
        put(o + 0x24u, LO8(k->env_ar) | LO8(k->env_hold) << 8 | LO8(k->env_dr) << 16 | LO8(k->env_sl) << 24, &h[9],
            L_B);
        put(o + 0x28u, LO8(k->env_st) | LO8(k->env_d2r) << 8 | LO8(k->env_rr) << 16 | LO8(k->companded) << 24,
            &h[10], L_B);
    }
    for (c = 0; c < 8u && SONG_BUG != 30; c++) {
        const sfx_ch *r = &SFX.ch[c];
        uint32_t o = BRD_SY_SFX(c), *h = sh_s[c];
        put(o + 0x00u, sfx_ptr(r->cur), &h[0], L_W);
        put(o + 0x04u, sfx_ptr(r->start), &h[1], L_W);
        put(o + 0x08u, r->pos, &h[2], L_W);
        put(o + 0x0Cu, r->len, &h[3], L_W);
        put(o + 0x10u, LO8(r->rate_type) | LO8(r->rate_mul) << 8 | LO16(r->id) << 16, &h[4], L_Q);
        put(o + 0x14u, LO16(r->gain2) | LO16(r->gain3) << 16, &h[5], L_H);
        put(o + 0x18u, LO8(r->neg) | LO8(r->shift) << 8 | LO16(r->r2a) << 16, &h[6], L_Q);
        put(o + 0x1Cu, LO16(r->pitch), &h[7], L_H);
    }
    f = (S.ready != 0) | (S.playing != 0) << 1 | (SFX.ready != 0) << 2 | (S.echo_on == 1) << 3 |
        (SFX.echo_on == 1) << 4 | (S.level != 0) << 5;
    put(BRD_SY_FLAGS, f, &sh_g[0], L_W);
    put(BRD_SY_WMASTER, LO16(S.gain0) | LO16(S.gain1) << 16, &sh_g[1], L_H);
    put(BRD_SY_WBOOST, LO16(S.boost) | LO16(G.wave_master) << 16, &sh_g[2], L_H);
    put(BRD_SY_SMASTER, LO16(SFX.gain2) | LO16(SFX.gain3) << 16, &sh_g[3], L_H);
    put(BRD_SY_SMCFG, LO16(G.sfx_master), &sh_g[4], L_H);
    put(BRD_SY_ECHOB, LO16(S.echo_gain) | LO8(S.echo_delay) << 16 | LO8(S.echo_wr) << 24, &sh_g[5], L_E);
    put(BRD_SY_ECHOS, LO16(SFX.echo_gain) | LO8(SFX.echo_delay) << 16 | LO8(SFX.r1a) << 24, &sh_g[6], L_E);
    put(BRD_SY_YMFILT, LO16(G.filt0) | LO16(G.filt1) << 16, &sh_g[7], L_H);
#if !PPM_RELEASE
    SONG_FRAME_PAD16();                 /* test build 5 on: brain hygiene (core/song/song.h): TEST's
                                           epilogue */
#endif
    force = 0u;
    primed = 1u;
}

/* every field written from the engine's records now (the boot's first DONE does it; a host harness after it puts
   another state into the records) */
void s5_mirror_prime(void)
{
    primed = 0u;
    s5_mirror_out();
}
