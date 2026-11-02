/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/zoom/zoom.c - the cart chip's zoom: F4's source, job 8's save of RAMDP $0200-$09FF and the stamps' set-up, F5's
 * integer rescale into the stamps and their copy into RAMDP, B6's restore. The cart chip is the STM32 microcontroller
 * on the real cartridge (the hex numbers are its addresses); RAMDP is the cart RAM that both the 68000 and the MCU see.
 * The dispatcher keeps the cart chip's queue and flags (core/dispatch jobs.c: job 8 saves once, sets up, opens the
 * session; job 9 rescales and copies while a session is open; job 10 restores what was saved and closes the session);
 * these are the bodies, as the cart chip runs them:
 *   job 8   0x08022CD0 the save (RAMDP $0200-$09FF -> the save buffer), then 0x08022D34 the set-up (the stamps := 0);
 *   job 9   0x08022D84 the rescale (below), then 0x08022D48 the copy-out (each stamp halfword byte-swapped into RAMDP
 *           $0200 + 2i, then cleared);
 *   job 10  0x08022D04 the restore (the save buffer -> RAMDP $0200-$09FF).
 * The rescale: the four F5 words (start, end, step, row). The first destination is the stamps' byte
 * (start >> 1 & 3 > 1 ? 0x400 : 0) + (start >> 3) x 0x40 + (start >> 1 & 1); then (end - start) / 2 columns (16-bit
 * difference). Each column reads two source rows of 32 bytes, at row x 32 + (acc / 2 & ~31) with acc stepping by
 * `step` (16 bits) before the second row and after it, and writes 32 bytes at every other byte of the stamps: the
 * first row's byte where both rows are the same row, else its high nibble with the second row's low nibble. The next
 * column starts 1, 0x3FF, 1 and -0x3C1 bytes on, in turn. Both of the cart chip's 32-byte copies are written out in
 * full, the cart chip's own shape (chosen as the faster one; a loop is ~1.2 KB smaller).
 * The cart chip's buffers are one block of its working RAM: the stamps (2 KB), the F4 source (2 KB), the save (2 KB),
 * then its sprite engine's countdowns. Ours: the stamps (zoom_st) apart from the source and the save (zoom_ss, the
 * cart chip's order). A row read past the source's end therefore reads the save, as on the cart chip, and a write past
 * the stamps' end lands in the source and then the save, as on the cart chip (the slow column below). Past the save
 * the cart chip reads and writes its sprite engine's RAM; ours reads 0 there and leaves the write out
 * (docs/ALLOWLIST.md, row B53). The game's own F5 posts stay inside the source and the stamps.
 * RAMDP is read and written a word pair at a time (the same bytes in the same order as the cart chip's halfword
 * loops).
 */
#include <stdint.h>
#include <string.h>
#include "board.h"
#include "zoom.h"
#include "disp_bodies.h"

#ifndef ZOOM_BUG
#define ZOOM_BUG 0                      /* planted bugs for tests/equiv/zoomlock.py's negative controls; never in an image
                                           that ships: 1 = the mixed column takes both nibbles from the first row; 2 = the
                                           walk after phase 1 is +0x400; 3 = the copy-out does not clear the stamps;
                                           4 = a source read past the source's end reads 0 (the save not reached) */
#endif

#if defined(__riscv)
#define ZOOM_UPPER      __attribute__((section(".bss_upper"), aligned(4)))
#else
#define ZOOM_UPPER      __attribute__((aligned(4)))
#endif

uint8_t zoom_st[ZOOM_STAMPS] __attribute__((aligned(4)));          /* the stamps (wram_data) */
zoom_ss_t zoom_ss ZOOM_UPPER;                                       /* the source and the save (wram_upper) */

#define ZOOM_RAMDP32    ((volatile uint32_t *)(volatile void *)(brd_cart_ram() + 0x100u))   /* RAMDP $0200 */

/* job 8: 0x08022CD0, RAMDP $0200-$09FF -> the save */
void job_scale_save(void)
{
    volatile uint32_t *r = ZOOM_RAMDP32;
    uint32_t *s = (uint32_t *)(void *)zoom_ss.b.save, i;
    for (i = 0; i < ZOOM_SAVE / 4u; i++)
        s[i] = r[i];
}

/* job 8: 0x08022D34, the stamps := 0 */
void job_scale_setup(void)
{
    memset(zoom_st, 0, sizeof zoom_st);
}

/* job 10: 0x08022D04, the save -> RAMDP $0200-$09FF */
void job_restore(void)
{
    volatile uint32_t *r = ZOOM_RAMDP32;
    const uint32_t *s = (const uint32_t *)(const void *)zoom_ss.b.save;
    uint32_t i;
    for (i = 0; i < ZOOM_SAVE / 4u; i++)
        r[i] = s[i];
}

/* job 9: 0x08022D84 then 0x08022D48 */
void job_rescale(const uint16_t args[4])
{
    zoom_rescale(args);
    zoom_copyout();
}

/* 0x08022D48: stamp halfword i -> RAMDP $0200 + 2i, its two bytes swapped, then the halfword := 0 */
__attribute__((noinline)) void zoom_copyout(void)
{
    volatile uint32_t *r = ZOOM_RAMDP32;
    uint32_t *s = (uint32_t *)(void *)zoom_st, i, w;
    for (i = 0; i < ZOOM_STAMPS / 4u; i++) {
        w = s[i];
        r[i] = ((w & 0x00FF00FFu) << 8) | ((w >> 8) & 0x00FF00FFu);
#if ZOOM_BUG != 3
        s[i] = 0u;
#endif
    }
}

/* a column whose rows or destination reach past the stamps or the source: byte by byte through the cart chip's block
   (the stamps, the source, the save; past the save: read 0, write left out) */
static uint8_t zoom_get(uint32_t s)
{
#if ZOOM_BUG == 4
    return s < ZOOM_SRC ? zoom_ss.raw[s] : 0u;
#else
    return s < ZOOM_SRC + ZOOM_SAVE ? zoom_ss.raw[s] : 0u;
#endif
}

static __attribute__((noinline)) void zoom_column_slow(uint32_t a, uint32_t b, uint32_t d)
{
    uint32_t i, o;
    uint8_t v;
    for (i = 0; i < 32u; i++) {
        v = zoom_get(a + i);
        if (a != b)
            v = (uint8_t)((v & 0xF0u) | (zoom_get(b + i) & 0x0Fu));
        o = d + 2u * i;
        if (o < ZOOM_STAMPS)
            zoom_st[o] = v;
        else if (o < ZOOM_STAMPS + ZOOM_SRC + ZOOM_SAVE)
            zoom_ss.raw[o - ZOOM_STAMPS] = v;
    }
}

#define ZC_SAME(k)      d[2u * (k)] = a[k];
#if ZOOM_BUG == 1
#define ZC_MIX(k)       d[2u * (k)] = a[k];
#else
#define ZC_MIX(k)       d[2u * (k)] = (uint8_t)((a[k] & 0xF0u) | (b[k] & 0x0Fu));
#endif
#define ZC_X8(M, o)     M((o) + 0u) M((o) + 1u) M((o) + 2u) M((o) + 3u) M((o) + 4u) M((o) + 5u) M((o) + 6u) M((o) + 7u)
#define ZC_X32(M)       ZC_X8(M, 0u) ZC_X8(M, 8u) ZC_X8(M, 16u) ZC_X8(M, 24u)

/* 0x08022D84: the rescale (the header above) */
__attribute__((noinline)) void zoom_rescale(const uint16_t args[4])
{
    uint32_t start = args[0], step = args[2], base = (uint32_t)args[3] * 32u;
    uint32_t ph = (start >> 1) & 3u;
    uint32_t d_off = (ph > 1u ? 0x400u : 0u) + (start >> 3) * 0x40u + ((start >> 1) & 1u);
    uint32_t n = ((uint32_t)(args[1] - start) & 0xFFFFu) >> 1, k, acc = 0u, a_off, b_off;
    for (k = 0; k != n; k++) {
        a_off = base + ((acc >> 1) & ~31u);
        acc = (acc + step) & 0xFFFFu;
        b_off = base + ((acc >> 1) & ~31u);
        acc = (acc + step) & 0xFFFFu;
        if ((a_off | b_off) < ZOOM_SRC && d_off < ZOOM_STAMPS - 62u) {
            const uint8_t *a = &zoom_ss.raw[a_off], *b = &zoom_ss.raw[b_off];
            uint8_t *d = &zoom_st[d_off];
            if (a == b) {
                ZC_X32(ZC_SAME)
            } else {
                ZC_X32(ZC_MIX)
            }
        } else {
            zoom_column_slow(a_off, b_off, d_off);
        }
        switch (ph) {                                       /* 0x08023106-0x080231E8: the stamp walk */
        case 0u:
            d_off += 1u;
            break;
        case 1u:
#if ZOOM_BUG == 2
            d_off += 0x400u;
#else
            d_off += 0x3FFu;
#endif
            break;
        case 2u:
            d_off += 1u;
            break;
        default:
            d_off -= 0x3C1u;
            break;
        }
        ph = (ph + 1u) & 3u;
    }
}

/* the FW_S5 = 0 images only (the FW_S5 images decode F4 through the cart chip's decoders, as ours has them): 0.2.6's
   decoder writes the F4 source in halfword-swapped order (its SDRAM layout); this turns the decoded bytes back into
   the order the decoder produced them, the cart chip's F4 source */
void zoom_f4_order(uint32_t len)
{
    uint16_t *h = (uint16_t *)(void *)zoom_ss.raw;
    uint32_t i, n = (len + 1u) >> 1;
    if (n > sizeof zoom_ss.raw / 2u)
        n = sizeof zoom_ss.raw / 2u;
    for (i = 0; i < n; i++)
        h[i] = (uint16_t)((h[i] << 8) | (h[i] >> 8));
}

#if FW_S5
uint32_t song_unpack80_to(const uint8_t *src, uint8_t *dst, const uint8_t *end);   /* core/song: the 0x80 and the 0x81 */
uint32_t song_unpack81_to(const uint8_t *src, uint8_t *dst, const uint8_t *end);   /* decoders, stopped at end */

/* The decode step of F4, the zoom start-up command (job type 4), done as the cart chip's job step at 0x0801A3E2
   does it. The stream's first byte picks the decoder: 0x80 (it works as the chip's does) or 0x81 (core/song/unpack81.c,
   which writes the same bytes as the chip). The bytes go into the F4 source in the order the decoder writes them, with
   no byte swap. It returns 0 when the decode wrote something, 0x11 (the job fails) when it wrote nothing, and 4 when
   the first byte is neither 0x80 nor 0x81. The chip decodes into its F4 source at 0x200119EC; its 4 KB source and save
   area, up to its zoom block's end at 0x200129EC, is our zoom_ss, so inside it every byte is the chip's. A longer
   result makes the chip write on into its sprite engine's RAM; ours stops at the end of zoom_ss and writes nothing past
   it (see docs/ALLOWLIST.md, row B57). We measured that every F4 the game posts fits, so play never reaches this. */
uint32_t zoom_f4_decode(uint32_t src)
{
    const uint8_t *p = brd_flash8() + (src & ~1u);
    const uint8_t *e = zoom_ss.raw + sizeof zoom_ss.raw;
    uint32_t n;
    if (p[0] == 0x80u)
        n = song_unpack80_to(p + 1, zoom_ss.raw, e);
    else if (p[0] == 0x81u)
        n = song_unpack81_to(p + 1, zoom_ss.raw, e);
    else
        return 4u;
    return n ? 0u : 0x11u;
}
#endif
