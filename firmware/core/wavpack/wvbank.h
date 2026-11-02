/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/wavpack/wvbank.h - the cart chip's sound-bank unpack (test build 4b), on the WavPack tiny decoder of this
 * folder. The cart chip is the STM32 microcontroller on the real cartridge. Written by our team: we reverse engineered
 * the STM32F4's commands as close as possible, with hardware verification. On the real ROM the unpacked bank equals
 * the cart chip's (measured by tests/equiv/cache4b.py on the RV32 image). The firmware never keeps a failed unpack
 * (board/pocket/boot/c4b_ovl.c). */
#ifndef WVBANK_H
#define WVBANK_H
#include <stdint.h>
#include "wavpack.h"

#define WVBANK_BYTES        0x152000u       /* the bank region */
#define WVBANK_MAX          0x152100u       /* the sample limit */
#define WVBANK_DIR_BYTES    0x1000u         /* the directory: 256 entries of 16 bytes */
#define WVBANK_CHUNK        256u            /* samples (and bytes) a WavpackUnpackSamples call asks for */
#define WVBANK_DIR_FIRST    0x00100000u     /* the bank's first four bytes, as a little-endian word */

/* the output: n = 256 final bank bytes at bank offset off (a multiple of 256), or (b = 0) n bytes of the never-written
   tail at off; offsets past WVBANK_BYTES are never passed */
typedef void (*wvbank_put)(uint32_t off, const uint8_t *b, uint32_t n);

typedef struct {
    uint32_t total;         /* the samples decoded (0 = refused or failed) */
    uint32_t chunks;        /* 256-byte chunks written */
    uint32_t crc_errors;    /* the decoder's block CRC mismatches (WavpackGetNumErrors; the cart chip ignores them) */
    uint32_t why;           /* WVBANK_OK or the first WVBANK_E_* that stopped it */
} wvbank_result;

enum { WVBANK_OK = 0, WVBANK_E_OPEN, WVBANK_E_MODE, WVBANK_E_DIR, WVBANK_E_COUNT };

/* the sound-bank unpack; tables made first (wvpk_tables_init). rd = the stream reader, put = the sink */
void wvbank_unpack (read_stream rd, wvbank_put put, wvbank_result *r);

/* a directory entry's byte order, 16 bytes in place (its own inverse) */
void wvbank_swap_entry (uint8_t *e);

#endif
