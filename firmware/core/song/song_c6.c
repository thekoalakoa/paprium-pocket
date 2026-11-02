/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song_c6.c - C6, the cart chip's audio init, and our own 8C pre-decode: every music module is unpacked
 * once, at C6, so the 8C job has nothing left to decode.
 *
 * Ours, in the C6 setup job (core/dispatch/jobs.c): song_c6_begin (the views; dac_buf: nothing reads it before the
 * CONFIG write), song_c6_init as an engine item (in order with the posts: the engine state is touched by the queue's
 * items only), song_c6_banks (the decodes into the views and the gates; the wave bank itself is unpacked at the first
 * boot, before the 68000 runs: board_bank_ok), song_store_modules (ours: every module decoded once, so the 8C job need
 * not decode), song_c6_ready as an item (the BGM table). The game posts no audio before C6 is done (it waits on $1FE6
 * bit 14), so, as far as we can tell, splitting the job into two items changes nothing the game can see.
 *
 * Written by our team: we reverse engineered the STM32F4's commands as close as possible, with hardware verification.
 * The 0x81 streams (the format known publicly as LZO1X) are decoded by our own decoder, core/song/unpack81.c:
 * song_unpack81 and song_unpack81_to, declared in song.h.
 */
#include "song.h"
#include "chip_tables.h"

/* ---- the 0x80 stream decoder. One body for both entries: song_unpack80 writes as far as the stream goes (end 0:
   the checks fold away); song_unpack80_to stops at end (F4's job: the cart chip's zoom block, docs/ALLOWLIST.md
   row B57) */
#define CLAMP80(n)  do { if (end && (n) > (uint32_t)(end - o)) (n) = (uint32_t)(end - o); } while (0)
static inline __attribute__((always_inline)) uint32_t unpack80(const uint8_t *src, uint8_t *dst, const uint8_t *end)
{
    uint8_t *o = dst;
    const uint8_t *m;
    uint32_t c, n, i;
    for (;;) {
        if (end && o >= end)
            return (uint32_t)(o - dst);
        c = src[0];
        n = c & 0x3Fu;
        switch (c & 0xC0u) {
        case 0x00u:
            if (n == 0)
                return (uint32_t)(o - dst);
            CLAMP80(n);
            for (i = 0; i < n; i++)
                o[i] = src[1 + i];
            o += n;
            src += n + 1u;
            break;
        case 0x40u:
            CLAMP80(n);
            for (i = 0; i < n; i++)
                o[i] = src[1];
            o += n;
            src += 2;
            break;
        case 0x80u:
            CLAMP80(n);
            m = o - src[1];
            for (i = 0; i < n; i++)
                o[i] = m[i];
            o += n;
            src += 2;
            break;
        default:
            CLAMP80(n);
            for (i = 0; i < n; i++)
                o[i] = 0;
            o += n;
            src += SONG_BUG == 28 ? 2 : 1;
            break;
        }
    }
}
#undef CLAMP80
uint32_t song_unpack80(const uint8_t *src, uint8_t *dst) { return unpack80(src, dst, 0); }
uint32_t song_unpack80_to(const uint8_t *src, uint8_t *dst, const uint8_t *end) { return unpack80(src, dst, end); }

/* ---- C6 ---- */
#define FLASH16_U16(a)  (*(const uint16_t *)(const void *)(song_v.flash16 + (a)))
static uint32_t c6_bgm;                                 /* C6 long 0, the BGM table's flash address */

void song_c6_begin(void)
{
    board_c6_views();
    if (SONG_BUG != 23)
        board_dacbuf_zero();
}

/* engine item 1: the cart chip's audio set-up, up to its bank load */
void song_c6_init(uint32_t sfx_addr)
{
    memset(&S, 0, sizeof S);
    memset(&SFX, 0, sizeof SFX);
    G.ready = 0;
    G.r16 = 0;
    G.q_len = 0;
    Z80Q[0] = 0;                                        /* the queue's first byte */
    G.force_mono = 0;
    G.q_budget = 0xFFF;
    G.last_cfg = 0xFF;                                  /* so the 88 configuration runs in full */
    G.q_last = 0;
    G.q_cost = 0;
    G.r36 = 0;
    G.r3a = 0xFF;
    G.r3c = 0;
    G.r3d = 0;
    G.c9_x1 = 0;
    S.track = 0;                                        /* (cleared already) */
    S.pan_target = 0;
    S.pan = 0;
    S.lvl_target = 0;
    S.level = 0;
    S.next_track = 0;
    G.r38 = 1;
    /* the table set-up: core/tables (the six tables are generated constants) */
    audio_config(2);                                    /* DT NTSC (CONFIG, dated at this item) */
    /* the block timer's interrupt enable: the synth's TIM6 runs from its reset; blocks follow CONFIG's MODE */
    G.ready = 1;
    if (sfx_table_init(sfx_addr))
        SFX.ready = 1;
}

/* the BGM table's entry i (as the cart chip's bank load builds it) */
uint32_t song_bgm_entry(uint32_t addr, uint32_t i)
{
    uint32_t a = addr & ~1u, v = ((uint32_t)FLASH16_U16(a + 4u * i) << 16) | FLASH16_U16(a + 4u * i + 2u);
    if (v == 0)
        return 0;
    if (SONG_BUG != 26)
        v = (uint32_t)(((int32_t)(v + (v >> 31))) >> 1) << 1;
    return v + a + song_v.flash8_bus;
}

/* the bank load's decodes and gates; the BGM table itself is song_c6_ready's (an item). Returns 2 when every gate
   passes, 1 when the table is built but a later gate fails, 0 when a gate before the table fails */
uint32_t song_c6_banks(const uint32_t longs[8])
{
    uint32_t bgm = longs[0], wp = longs[1], wav = longs[2], psg = longs[3], n;
    const uint8_t *p;
    uint8_t *d;
    c6_bgm = bgm;
    if (bgm == 0 || wp == 0 || wav == 0 || psg == 0)
        return 0;
    p = song_v.flash8 + (wp & ~1u);
    if (p[0] != 0x80u)
        return 0;
    d = board_c6_tab(0);
    n = song_unpack80(p + 1, d);
    if (n > 0x1000u)
        return 0;
    for (; n < 0x1000u; n++)
        d[n] = 0;
    p = song_v.flash8 + (psg & ~1u);
    if (p[0] != 0x80u)
        return 0;
    d = board_c6_tab(1);
    n = song_unpack80(p + 1, d);
    if (n > 0x800u)
        return 0;
    for (; n < 0x800u; n++)
        d[n] = 0;
    if (FLASH16_U16(bgm & ~1u) != 0 || song_v.flash16[(bgm & ~1u) + 2u] > 0x3Fu)
        return 0;
    p = song_v.flash8 + (wav & ~1u);
    if (p[0] != 0x77u)
        return 1;
    if (!board_bank_ok(wav))                            /* the wave bank: unpacked at the first boot (test build 4b's
                                                           boot cache) */
        return 1;
    return 2;
}

/* engine item 2: the BGM table and the sequencer's ready flag */
void song_c6_ready(uint32_t level)
{
    uint32_t a = c6_bgm, n, i;
    if (level >= 1u) {
        n = (uint32_t)song_v.flash16[(a & ~1u) + 2u] + 1u;
        bgm_table[0] = n;
        for (i = 1; i < n; i++)
            bgm_table[i] = song_bgm_entry(a, i);
        for (i = n; i < 64u; i++)
            bgm_table[i] = 0;
        SONG_FRAME_PAD16();             /* test build 5 on: brain hygiene (song.h); in the path that
                                           has the frame */
    }
    if (level >= 2u)
        S.ready = 1;
}

/* ours: every module of the BGM table decoded once into the store (the cart chip decodes one at each 8C job), by
   the stream's type byte (0x80 and 0x81; the game's 52 modules are all 0x81, measured); the directory's magic last */
uint32_t song_store_modules(uint32_t bgm_addr)
{
    uint32_t a = bgm_addr & ~1u, n = (uint32_t)song_v.flash16[a + 2u] + 1u, i, e, len, room, count = 0, ok = 1;
    const uint8_t *p;
    uint8_t *d;
    board_store_begin();
    for (i = 1; i < n; i++) {
        e = song_bgm_entry(bgm_addr, i);
        if (e == 0)
            continue;
        p = SONG_FLASH8(e);
        if (p[0] != 0x80u && p[0] != 0x81u)             /* 0x82 / 0x83 / others: never in the game (measured) */
            continue;
        d = board_store_slot(&room);
        len = p[0] == 0x81u ? song_unpack81(p + 1, d) : song_unpack80(p + 1, d);
        if (len > room) {                               /* past the store: the directory is not made valid */
            ok = 0;
            break;
        }
        if (len == 0)                                   /* the chip's job fails on it (trace 0x11): no module */
            continue;
        board_store_put(i, len);
        count++;
    }
    board_store_end(ok);
    return ok ? count : 0;
}
