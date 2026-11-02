/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/boot/c4b_ovl.c - test build 4b's WRAM boot overlay (the flow, the ROM map, the check, the unpack sink,
 * the header, the SFX copy, the bar). The plan and the record are in c4b.h; the unpack itself is core/wavpack. Section
 * numbers (21.1, 3.8, ...) are those of docs/MCU_INTERFACE.md.
 *
 * Linked on its own for 0x80006C00 (board/pocket/link/c4b_ovl.ld): no .data (its image must stay byte-identical while
 * it runs: a reset in the middle re-enters it, and the stub checks its CRC-32), no gp, its .bss at the start of
 * wram_data (made zero here: crt0 has not run yet). Board layer: the cache slot's XLINK words, the CRAM die-0 window,
 * the flash views, FPGAIO TIMER / VSCNT. Planted bugs for tests/equiv/cache4b.py's negative controls: C4B_BUG.
 * The FW_S5 images (test build 5 on; C4B_CURVE): the synth's output curve is written to CRAM CURVE on every non-warm
 * boot, beside the SFX bank and before CACHE (curve_write; c5_curve.h has its packed form). */
#include <stdint.h>
#include "pocket_map.h"
#include "c4b.h"
#include "wvbank.h"
#if FW_S5
#define C4B_CURVE               1               /* FW_S5 (test build 5 on): the synth's output curve (curve_write) */
#include "c5_curve.h"
#else
#define C4B_CURVE               0
#endif

#define IO32(a)                 (*(volatile uint32_t *)(uintptr_t)(a))
#define CRAMW                   ((volatile uint32_t *)(uintptr_t)POCKET_CRAM_HDR)       /* CRAM byte 4w = word w */
#define ROMB(a)                 (*(const volatile uint8_t *)(uintptr_t)(POCKET_FLASH_BV_BASE + (a)))
#define ROMBW(a)                (*(const volatile uint32_t *)(uintptr_t)(POCKET_FLASH_BV_BASE + (a)))  /* bytes a..a+3 */
#define ROMWW(a)                (*(const volatile uint32_t *)(uintptr_t)(POCKET_FLASH_BASE + (a)))  /* words a, a + 2 */
#define BANK_W0                 (C4B_BANK_OFF / 4u)
#define CHUNKS                  (C4B_BANK_BYTES / 256u)
#define BAR_W_NONE              320u            /* the bar's width while W reads 0 (as test build 4a had it) */
#ifndef C4B_BUG
#define C4B_BUG                 0
#endif

_Static_assert(C4B_IMAGE_BYTES == POCKET_CACHE_IMAGE_MAX && C4B_HDR_BYTES == POCKET_CRAM_HDR_BYTES &&
               C4B_BANK_BYTES == POCKET_CRAM_BANK_BYTES && C4B_BANK_BYTES == WVBANK_BYTES &&
               POCKET_CRAM_BANK == POCKET_CRAM_HDR + C4B_BANK_OFF && C4B_SFX_ROOM == POCKET_CRAM_SFXBANK_BYTES,
               "the image is HDR + BANK (MCU_INTERFACE 3.8)");

/* ---- scratch (.bss at the start of wram_data; zeroed by the entry) ------------------------------------------- */
extern uint32_t __ovl_bss_start[], __ovl_bss_end[], __ovl_stk_start[], __ovl_stk_end[];
static c4b_rec_t *rec;
static uint32_t crc_tab[256];
static uint32_t hdr[C4B_H_WORDS];               /* the header as loaded (the check) or as made (the unpack) */
static uint32_t blk_lo[C4B_MAXBLK], blk_n[C4B_MAXBLK], blk_crc[C4B_MAXBLK];
static uint32_t nblk, stream, stream_bytes, total, key;
static uint32_t buf[2][64];                     /* the check's chunk and the one before (the tail rule) */
static uint32_t src;                            /* the decoder's read position (ROM byte offset) */
static uint32_t bar_w, bar_total;

/* the decoder calls memcpy / memset (it is built -ffreestanding); small and plain */
void *memcpy(void *d, const void *s, unsigned n)
{
    uint8_t *p = d;
    const uint8_t *q = s;
    if (!(((uintptr_t)p | (uintptr_t)q) & 3u))
        for (; n >= 4u; n -= 4u, p += 4, q += 4)
            *(uint32_t *)(void *)p = *(const uint32_t *)(const void *)q;
    while (n--)
        *p++ = *q++;
    return d;
}
void *memset(void *d, int c, unsigned n)
{
    uint8_t *p = d;
    uint32_t w = (uint8_t)c * 0x01010101u;
    if (!((uintptr_t)p & 3u))
        for (; n >= 4u; n -= 4u, p += 4)
            *(uint32_t *)(void *)p = w;
    while (n--)
        *p++ = (uint8_t)c;
    return d;
}

static uint32_t now(void) { return IO32(POCKET_FIO_TIMER); }

static uint32_t crc32(uint32_t c, const uint8_t *p, uint32_t n)
{
    while (n--)
        c = crc_tab[(c ^ *p++) & 0xFFu] ^ (c >> 8);
    return c;
}

static uint32_t rom_be32(uint32_t a)
{
    return (uint32_t)ROMB(a) << 24 | (uint32_t)ROMB(a + 1u) << 16 | (uint32_t)ROMB(a + 2u) << 8 | ROMB(a + 3u);
}
static uint32_t rom_le32(uint32_t a)
{
    return ROMB(a) | (uint32_t)ROMB(a + 1u) << 8 | (uint32_t)ROMB(a + 2u) << 16 | (uint32_t)ROMB(a + 3u) << 24;
}

/* the bar's W read live, the largest kept in the record (the TEST diagnosis: did the video run during the hold) */
static uint32_t bar_seen(void)
{
    uint32_t w = (IO32(POCKET_XL_BAR) >> POCKET_BAR_W_SHIFT) & POCKET_BAR_W_MASK;
    if (w > (rec->kind >> C4B_W_SHIFT))
        rec->kind = (rec->kind & 0xFFFFu) | (w << C4B_W_SHIFT);
    return w;
}

/* the bar (21.2: lit only during a first-boot unpack): PX = done x W / total; W live (0 before a complete line:
   BAR_W_NONE) */
static void bar(uint32_t done)
{
    uint32_t w = bar_seen();
    if (!w)
        w = BAR_W_NONE;
    bar_w = w;
    IO32(POCKET_XL_BAR) = POCKET_BAR_EN | ((done * w / bar_total) & POCKET_BAR_PX_MASK);  /* < 2^32: 0x152000 x 2047 */
}

/* ---- the ROM: the game's C600 arguments, the WavPack stream's blocks (c4b.h) -------------------------------- */
static uint32_t rom_map(void)
{
    uint32_t a0 = rom_be32(C4B_ROM_TABLE_PTR), p, k, bi, bn, tot, ck;
    uint8_t h[32];
    if ((a0 & 1u) || a0 > POCKET_FLASH_BYTES - 0x800u)
        return C4B_WHY_PTR;
    stream = rom_be32(a0 + C4B_A0_STREAM) & ~1u;                        /* bit 0 masked, as on the cart */
    rec->stream = stream;
    if (stream > POCKET_FLASH_BYTES - 32u || ROMB(stream) != 'w')
        return C4B_WHY_PTR;                                             /* the first byte, as the cart checks it */
    key = 0xFFFFFFFFu;
    for (p = stream, k = 0, tot = 0; ; k++) {
        if (k == C4B_MAXBLK || p > POCKET_FLASH_BYTES - 32u)
            return C4B_WHY_STREAM;
        for (bi = 0; bi < 32u; bi++)
            h[bi] = ROMB(p + bi);
        if (h[0] != 'w' || h[1] != 'v' || h[2] != 'p' || h[3] != 'k')
            return C4B_WHY_STREAM;
        key = crc32(key, h, 32u);
        ck = rom_le32(p + 4u);
        if (!k)
            tot = rom_le32(p + 12u);                                    /* total_samples (the first block's) */
        bi = rom_le32(p + 16u);                                         /* block_index, block_samples, crc */
        bn = rom_le32(p + 20u);
        if (bi != (k ? blk_lo[k - 1u] + blk_n[k - 1u] : 0u) || !bn || ck > POCKET_FLASH_BYTES)
            return C4B_WHY_STREAM;                                      /* (contiguous blocks: the ROM's 32 are) */
        blk_lo[k] = bi;
        blk_n[k] = bn;
        blk_crc[k] = rom_le32(p + 28u);
        p += 8u + ck;
        if (bi + bn >= tot)
            break;
    }
    nblk = k + 1u;
    stream_bytes = p - stream;
    total = tot < WVBANK_MAX ? tot : WVBANK_MAX;                        /* the chip's count */
    if (total - 1u >= C4B_BANK_BYTES || blk_lo[nblk - 1u] + blk_n[nblk - 1u] != tot)
        return C4B_WHY_STREAM;
    key = ~key;
    rec->key = key;
    rec->vs |= nblk << 16;
    return C4B_WHY_NONE;
}

/* ---- the bank as CRAM holds it: every block's WavPack CRC, the tail, and the CRC-32 of all of it. Returns the
   number of wrong blocks (the tail counts as one) and in *bad its record form ([15:8] that count, [7:0] the first: a
   block, 0xFE the tail, 0xFF none); rec->bank_crc = the CRC-32. The bar is not touched here (21.2: the loaded file's
   check runs dark; after an unpack it stays as the unpack left it); W is sampled for the record. ------------------- */
static uint32_t check_bank(uint32_t *bad)
{
    uint32_t c, i, j, n, t, w, k = 0, wc = 0xFFFFFFFFu, cc = 0xFFFFFFFFu, nbad = 0, first = 0xFFu;
    uint32_t tail_end = (total + 255u) & ~255u, *cur, *prv;
    uint32_t e[64];
    for (c = 0; c < CHUNKS; c++) {
        cur = buf[c & 1u];
        prv = buf[(c & 1u) ^ 1u];
        if (!(c & 15u)) {
#if C4B_BUG == 13
            bar(c * 256u);                                              /* planted: the bar lit during the file's check */
#else
            (void)bar_seen();
#endif
        }
        for (i = 0; i < 64u; i++) {                                     /* the chunk, and its CRC-32 */
            w = CRAMW[BANK_W0 + c * 64u + i];
            cur[i] = w;
            cc ^= w;
            cc = crc_tab[cc & 0xFFu] ^ (cc >> 8);
            cc = crc_tab[cc & 0xFFu] ^ (cc >> 8);
            cc = crc_tab[cc & 0xFFu] ^ (cc >> 8);
            cc = crc_tab[cc & 0xFFu] ^ (cc >> 8);
        }
        t = c * 256u;
        if (t < total) {                                                /* the samples of this chunk: s per byte */
            const int8_t *s = (const int8_t *)(const void *)cur;
            if (t < WVBANK_DIR_BYTES) {                                 /* the directory */
                for (i = 0; i < 64u; i++)
                    e[i] = cur[i];
                for (i = 0; i < 256u; i += 16u)
                    wvbank_swap_entry((uint8_t *)(void *)e + i);
                for (i = 0; i < 64u; i++)
                    e[i] ^= 0x80808080u;
                s = (const int8_t *)(const void *)e;
            }
            for (i = 0; i < 256u && t + i < total; i = j) {             /* segments split at the block ends */
                if (t + i == blk_lo[k] + blk_n[k]) {                    /* a block ends: its CRC */
                    if (wc != blk_crc[k] && !nbad++)
                        first = k;
                    k++;
                    wc = 0xFFFFFFFFu;
                }
                n = blk_lo[k] + blk_n[k] - t;                           /* this block's end, as a chunk index */
                if (n > 256u)
                    n = 256u;
                if (n > total - t)
                    n = total - t;
                for (j = i; j < n; j++)
                    wc = (wc << 1) + wc + (uint32_t)(int32_t)s[j];      /* the block's WavPack CRC */
            }
        }
        if (t + 256u > total && t < C4B_BANK_BYTES) {                   /* the tail in this chunk */
            const uint8_t *b = (const uint8_t *)cur, *q = (const uint8_t *)prv;
            for (i = 0; i < 256u; i++) {
                if (t + i < total)
                    continue;
                w = t + i < tail_end ? q[i] : (t + i < WVBANK_DIR_BYTES ? 0u : 0x80u);
                if (b[i] != w) {
                    if (!nbad++)
                        first = 0xFEu;
                    break;
                }
            }
        }
    }
    if (k != nblk - 1u || wc != blk_crc[k]) {                           /* the last block */
        if (!nbad++)
            first = k;
    }
    rec->bank_crc = ~cc;
    *bad = (nbad > 0xFFu ? 0xFFu : nbad) << 8 | first;
    return nbad;
}

/* ---- the loaded file (21.1 step 2) ------------------------------------------------------------------------- */
static uint32_t check_file(void)
{
    uint32_t i, n, bad, bad_word = 0xFFu;
    if (!rec->loaded)
        return C4B_FIRST;
#if C4B_BUG != 4
    if (rec->loaded != C4B_IMAGE_BYTES)
        return C4B_SIZE;
#endif
    if (rec->lost >> POCKET_XL_LOST_CRAM_SHIFT)
        return C4B_LOST;
    for (i = 0; i < C4B_H_WORDS; i++)
        hdr[i] = CRAMW[i];
    rec->hdr_crc = hdr[C4B_H_BANK_CRC];
    if (hdr[C4B_H_MAGIC0] != C4B_MAGIC0 || hdr[C4B_H_MAGIC1] != C4B_MAGIC1)
        bad_word = C4B_H_MAGIC0;
    else if (hdr[C4B_H_FORMAT] != C4B_FORMAT)
        bad_word = C4B_H_FORMAT;
    else if (hdr[C4B_H_HDR_BYTES] != C4B_HDR_BYTES || hdr[C4B_H_IMAGE_BYTES] != C4B_IMAGE_BYTES ||
             hdr[C4B_H_BANK_OFF] != C4B_BANK_OFF || hdr[C4B_H_BANK_BYTES] != C4B_BANK_BYTES)
        bad_word = C4B_H_HDR_BYTES;
    else if (~crc32(0xFFFFFFFFu, (const uint8_t *)hdr, 4u * C4B_H_CRC) != hdr[C4B_H_CRC])
        bad_word = C4B_H_CRC;
    if (bad_word != 0xFFu) {
        rec->bad = (rec->bad & 0xFF00FFFFu) | bad_word << 16;
        return C4B_HDR;
    }
#if C4B_BUG != 6
    if (hdr[C4B_H_STREAM] != stream || hdr[C4B_H_STREAM_BYTES] != stream_bytes || hdr[C4B_H_BLOCKS] != nblk ||
        hdr[C4B_H_KEY] != key || hdr[C4B_H_SAMPLES] != total) {
        rec->bad = (rec->bad & 0xFF00FFFFu) | (uint32_t)C4B_H_KEY << 16;
        return C4B_KEY;
    }
#endif
    n = check_bank(&bad);
    rec->bad = (rec->bad & 0xFFFF0000u) | bad;                          /* the loaded file's diagnosis (kept) */
#if C4B_BUG == 1
    n = 0, hdr[C4B_H_BANK_CRC] = rec->bank_crc;                         /* planted: the content's verdict ignored */
#endif
    if (n || rec->bank_crc != hdr[C4B_H_BANK_CRC])
        return C4B_BANK;
    rec->samples = hdr[C4B_H_SAMPLES];
    return C4B_PASS;
}

/* ---- the unpack (21.1 step 3) -------------------------------------------------------------------------------- */
static int32_t rd(void *dst, int32_t n)                    /* the decoder's read callback: a copy, in order */
{
    uint8_t *d = dst;
    uint32_t a = src, k;
    if (n < 0)
        n = 0;
    if ((uint32_t)n > POCKET_FLASH_BYTES - a)
        n = (int32_t)(POCKET_FLASH_BYTES - a);
    k = (uint32_t)n;
    while (k && ((a | (uint32_t)(uintptr_t)d) & 3u)) {
        *d++ = ROMB(a);
        a++, k--;
    }
    for (; k >= 4u; k -= 4u, a += 4u, d += 4)
        *(uint32_t *)(void *)d = ROMBW(a);
    while (k) {
        *d++ = ROMB(a);
        a++, k--;
    }
    src = a;
    return n;
}

static void put(uint32_t off, const uint8_t *b, uint32_t n)   /* bank bytes -> CRAM byte 0x100 + off */
{
    uint32_t i, w = (C4B_BANK_OFF + off) / 4u;
    if (b) {
        const uint32_t *s = (const uint32_t *)(const void *)b;
        for (i = 0; i < n / 4u; i++) {
#if C4B_BUG == 2
            if (off == 0x80000u && i == 7u)
                continue;                                               /* planted: one word of the bank not written */
#endif
            CRAMW[w + i] = s[i];
        }
        bar(off + n);
    } else {
        uint32_t v = off < WVBANK_DIR_BYTES ? 0u : 0x80808080u;
#if C4B_BUG == 3
        return;                                                         /* planted: the tail not written */
#endif
        for (i = 0; i < n / 4u; i++)
            CRAMW[w + i] = v;
    }
}

static uint32_t unpack(void)
{
    wvbank_result r;
    uint32_t i, t0 = now();
    CRAMW[C4B_H_MAGIC0] = 0;                    /* the old header's magic first: a cut unpack never looks kept */
    rec->kind |= C4B_F_UNPACKED;
    src = stream;
    bar_total = C4B_BANK_BYTES;
    bar(0u);                                    /* 21.2: the bar lights with the unpack (its check and header after it) */
    wvbank_unpack(rd, put, &r);
    rec->t_unpack = now() - t0;
    rec->samples = r.total;
    rec->crc_errs = r.crc_errors | r.why << 16;
    if (r.crc_errors)
        rec->kind |= C4B_F_CRCERR;
    t0 = now();
    if (r.why != WVBANK_OK || r.total != total || r.crc_errors) {
        rec->t_verify = now() - t0;
        return C4B_WHY_UNPACK | r.why << 8;
    }
    if (check_bank(&i)) {                                               /* what CRAM holds now (the writes landed) */
        rec->bad = (rec->bad & 0xFFFF0000u) | i;                        /* (a failure replaces the load's diagnosis) */
        rec->t_verify = now() - t0;
        return C4B_WHY_CHECK;
    }
    for (i = 0; i < C4B_H_WORDS; i++)
        hdr[i] = 0;
    hdr[C4B_H_MAGIC0] = C4B_MAGIC0;
    hdr[C4B_H_MAGIC1] = C4B_MAGIC1;
    hdr[C4B_H_FORMAT] = C4B_FORMAT;
    hdr[C4B_H_HDR_BYTES] = C4B_HDR_BYTES;
    hdr[C4B_H_IMAGE_BYTES] = C4B_IMAGE_BYTES;
    hdr[C4B_H_BANK_OFF] = C4B_BANK_OFF;
    hdr[C4B_H_BANK_BYTES] = C4B_BANK_BYTES;
    hdr[C4B_H_SAMPLES] = r.total;
    hdr[C4B_H_STREAM] = stream;
    hdr[C4B_H_STREAM_BYTES] = stream_bytes;
    hdr[C4B_H_BLOCKS] = nblk;
    hdr[C4B_H_KEY] = key;
    hdr[C4B_H_BANK_CRC] = rec->bank_crc;
    hdr[C4B_H_WRITER] = IO32(POCKET_WRAM_UPPER_LO + 8u);                /* the overlay header's CRC-32 */
    for (i = 0; i < nblk; i++)
        hdr[C4B_H_BLKCRC + i] = blk_crc[i];
    hdr[C4B_H_CRC] = ~crc32(0xFFFFFFFFu, (const uint8_t *)hdr, 4u * C4B_H_CRC);
#if C4B_BUG == 5
    CRAMW[C4B_H_MAGIC0] = hdr[C4B_H_MAGIC0];                            /* planted: the magic before the rest */
#endif
#if C4B_BUG == 11
    IO32(POCKET_XL_CACHE) = POCKET_CACHE_VALID | C4B_IMAGE_BYTES;       /* planted: CACHE set before the header */
#endif
    for (i = C4B_H_WORDS; i-- > 0u; )                                   /* the header last, its magic last of all */
        CRAMW[i] = hdr[i];
    for (i = 0; i < C4B_H_WORDS && CRAMW[i] == hdr[i]; i++)
        ;
    rec->t_verify = now() - t0;
    if (i != C4B_H_WORDS)
        return C4B_WHY_HDR;
    rec->kind |= C4B_F_HDR_WRITTEN;
    return C4B_WHY_NONE;
}

/* ---- the SFX bank (21.1 step 5): ROM words [lo, hi) from the flash word view to CRAM 0x200000 (3.8) ------------ */
static void sfx_copy(void)
{
    uint32_t a0 = rom_be32(C4B_ROM_TABLE_PTR), lo, hi, a, t0 = now();
    volatile uint32_t *d = (volatile uint32_t *)(uintptr_t)POCKET_CRAM_SFXBANK;
    if ((a0 & 1u) || a0 > POCKET_FLASH_BYTES - 0x800u)
        return;
    lo = rom_be32(a0 + C4B_A0_SFX_LO);
    hi = rom_be32(a0 + C4B_A0_SFX_HI);
    if (((lo | hi) & 3u) || hi <= lo || hi > POCKET_FLASH_BYTES || hi - lo > C4B_SFX_ROOM)
        return;
    for (a = lo; a < hi; a += 4u)
        *d++ = ROMWW(a);
    rec->kind |= C4B_F_SFX;
    rec->t_sfx = now() - t0;
}

#if C4B_CURVE
/* ---- FW_S5 (test build 5 on): the synth's output curve (v1.3 3.8 CURVE_WIN 0x194000-0x19BFFF, index 0 at 0x198000;
   3.10.6: the curve written at every boot). The CRAM keeps it across resets
   (the controller resets at power-on only), so a warm boot, which touches nothing, finds it; this runs on every
   non-warm boot, BEFORE CACHE, so a reset in the middle finds VALID = 0 and writes it whole again. Halfword stores
   (CRAM's 16-bit halves), both halves of the curve as c5_curve.h rebuilds it. ----------------------------------- */
static void curve_write(void)
{
    volatile uint16_t *c = (volatile uint16_t *)(uintptr_t)POCKET_CRAM_CURVE_CTR;
    uint32_t m, q = 0u, f, k;
    for (m = 0; m <= 8192u; m++) {
        if (m < C5_CURVE_LIN) {
            q = 2u * m + 1u;
        } else if (m < C5_CURVE_KNEE_N) {
            k = m - C5_CURVE_LIN;
            q += (c5_curve_step[k >> 2] >> (2u * (k & 3u))) & 3u;
        }
        f = m < C5_CURVE_KNEE_N ? (61u * q) >> 6 : C5_CURVE_PLATEAU;
#if C4B_BUG == 14
        if (m == 1000u)
            f++;                                    /* planted: one curve entry pair one code off */
#endif
        if (m < 8192u)
            c[m] = (uint16_t)(2047u + f);           /* input +m */
        if (m)
            c[-(int32_t)m] = (uint16_t)(2047u - f); /* input -m (m = 8192: entry 0, the table's start) */
    }
    rec->kind |= C4B_F_CURVE;
}
#endif

/* ---- the entry (the stub calls it with rec's XLINK words filled, VALID = 0, the overlay checked) --------------- */
__attribute__((section(".text.c4b_entry"), used)) void c4b_ovl_main(c4b_rec_t *r)
{
    uint32_t *p, i, kind, why, vs0, t0, sp;
    __asm__ volatile ("mv %0, sp" : "=r"(sp));
    if (sp < (uint32_t)(uintptr_t)__ovl_stk_end + 512u) {              /* the stack must stay above the second scratch */
        r->kind = C4B_NOROM;                                            /* (measured depth ~0.7 KB of 1.5 KB: never) */
        r->bad = (uint32_t)C4B_WHY_PTR << 24;
        return;
    }
    for (p = __ovl_bss_start; p < __ovl_bss_end; p++)                  /* our scratch: crt0 has not run */
        *p = 0;
    for (p = __ovl_stk_start; p < __ovl_stk_end; p++)                  /* the second, at the stack's floor */
        *p = 0;
    rec = r;
    r->bad = 0x00FF00FFu;                                               /* no wrong block, no wrong header word (yet) */
    vs0 = IO32(POCKET_FIO_VSCNT);
    for (i = 0; i < 256u; i++) {                                        /* CRC-32 (IEEE 802.3, reflected) */
        uint32_t c = i, j;
        for (j = 0; j < 8u; j++)
            c = (c >> 1) ^ (0xEDB88320u & (0u - (c & 1u)));
        crc_tab[i] = c;
    }
    (void)bar_seen();
    t0 = now();
    if ((why = rom_map()) != C4B_WHY_NONE) {
        r->kind |= C4B_NOROM;
        r->bad = (r->bad & 0x00FFFFFFu) | why << 24;
        sfx_copy();
#if C4B_CURVE
        curve_write();          /* FW_S5 (test build 5 on): no bank, but the SFX still mix through the curve */
#endif
    } else {
        kind = check_file();
        r->t_check = now() - t0;
        r->kind |= kind;
        why = C4B_WHY_NONE;
        if (kind != C4B_PASS) {
            why = unpack();
#if C4B_BUG != 8
            IO32(POCKET_XL_BAR) = 0u;                                   /* 21.2: the bar ends with the unpack */
#endif
        }
#if C4B_BUG != 12
        sfx_copy();             /* BEFORE CACHE: CACHE is this power-on's last store, so a reset inside the copy finds
                                   VALID = 0 and the overlay intact, and the next boot copies the bank whole again (a
                                   WARM boot never meets a half-copied SFX bank) */
#endif
#if C4B_CURVE && C4B_BUG != 15
        curve_write();          /* FW_S5 (test build 5 on): the synth's curve, also before CACHE (C4B_BUG 15, planted:
                                   not written) */
#endif
        if (why != C4B_WHY_NONE) {
            r->kind |= C4B_F_FAIL;
            r->bad = (r->bad & 0x00FFFFFFu) | (why & 0xFFu) << 24;
        } else {
#if C4B_BUG == 7
            if (kind != C4B_PASS)
                CRAMW[BANK_W0 + 5u] ^= 1u;                              /* planted: the bank changed after its check */
#endif
            IO32(POCKET_XL_CACHE) = POCKET_CACHE_VALID | C4B_IMAGE_BYTES;   /* the one write of this power-on, last */
            if (IO32(POCKET_XL_CACHE) == (POCKET_CACHE_VALID | C4B_IMAGE_BYTES))
                r->kind |= C4B_F_CACHE_SET;
        }
#if C4B_BUG == 12
        sfx_copy();                                                     /* planted: test build 4b's first order, after
                                                                           CACHE */
#endif
    }
#if C4B_BUG != 8
    IO32(POCKET_XL_BAR) = 0u;                                           /* 21.2: EN = 0 before the 68000 runs */
#endif                                                                  /* (the stub writes it again on every path) */
    if (!(IO32(POCKET_XL_BAR) & POCKET_BAR_EN))
        r->kind |= C4B_F_BAR_OFF;
    if (r->kind >> C4B_W_SHIFT)
        r->kind |= C4B_F_BAR_SEEN;
    r->vs = (r->vs & 0xFFFF0000u) | ((IO32(POCKET_FIO_VSCNT) - vs0) & POCKET_VSCNT_MASK);
}
