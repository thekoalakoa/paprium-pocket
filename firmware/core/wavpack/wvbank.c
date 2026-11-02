/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/wavpack/wvbank.c - the cart chip's sound-bank unpack (see wvbank.h). */
#include <stdint.h>
#include "wvbank.h"

static int32_t wvbank_buf [WVBANK_CHUNK] IBSS_ATTR;     /* the sample buffer, kept across chunks */
static uint8_t wvbank_out [WVBANK_CHUNK];

void wvbank_swap_entry (uint8_t *e)
{
    uint8_t t;
    int k;

    for (k = 0; k < 12; k += 4) {
        t = e [k]; e [k] = e [k + 3]; e [k + 3] = t;
        t = e [k + 1]; e [k + 1] = e [k + 2]; e [k + 2] = t;
    }
    t = e [12]; e [12] = e [13]; e [13] = t;
    t = e [14]; e [14] = e [15]; e [15] = t;
}

void wvbank_unpack (read_stream rd, wvbank_put put, wvbank_result *r)
{
    char err [80];
    WavpackContext *wpc;
    uint32_t count, n, i, off;

    r->total = r->chunks = r->crc_errors = 0;
    r->why = WVBANK_OK;
    wvpk_tables_init ();
    if (!(wpc = WavpackOpenFileInput (rd, err))) {
        r->why = WVBANK_E_OPEN;
        return;
    }
    if (!(WavpackGetMode (wpc) & MODE_LOSSLESS) || !WavpackGetNumSamples (wpc) || WavpackGetBitsPerSample (wpc) != 8 ||
        WavpackGetNumChannels (wpc) != 1) {
        r->why = WVBANK_E_MODE;                 /* nothing decoded */
        return;
    }
    count = WavpackGetNumSamples (wpc);
    if (count > WVBANK_MAX)
        count = WVBANK_MAX;
    for (off = 0; ; off += WVBANK_CHUNK) {
        n = WavpackUnpackSamples (wpc, wvbank_buf, WVBANK_CHUNK);
        for (i = 0; i < WVBANK_CHUNK; i++)
            wvbank_out [i] = (uint8_t) ((uint8_t) wvbank_buf [i] - 0x80);
        if (!r->total && (wvbank_out [0] | (uint32_t) wvbank_out [1] << 8 | (uint32_t) wvbank_out [2] << 16 |
                          (uint32_t) wvbank_out [3] << 24) != WVBANK_DIR_FIRST) {
            r->why = WVBANK_E_DIR;              /* not this bank */
            r->total = 0;
            break;
        }
        if (off < WVBANK_DIR_BYTES)             /* the directory */
            for (i = 0; i < WVBANK_CHUNK; i += 16)
                wvbank_swap_entry (wvbank_out + i);
        else                                    /* the samples */
            for (i = 0; i < WVBANK_CHUNK; i++)
                wvbank_out [i] = (uint8_t) (wvbank_out [i] - 0x80);
        if (off < WVBANK_BYTES)                 /* (a chunk past the region: never on the ROM) */
            put (off, wvbank_out, WVBANK_CHUNK);
        r->chunks++;
        r->total += n;
        if (n < WVBANK_CHUNK || r->total >= count)
            break;
    }
    r->crc_errors = WavpackGetNumErrors (wpc);
    if (r->why == WVBANK_OK && (r->total - 1u) >= WVBANK_BYTES) {
        r->why = WVBANK_E_COUNT;                /* a total of 0 or past the region */
        return;
    }
    if (r->why != WVBANK_OK)
        return;
    off = r->chunks * WVBANK_CHUNK;             /* the bytes no chunk reached */
    if (off < WVBANK_DIR_BYTES) {
        put (off, 0, WVBANK_DIR_BYTES - off);
        off = WVBANK_DIR_BYTES;
    }
    if (off < WVBANK_BYTES)
        put (off, 0, WVBANK_BYTES - off);
}
