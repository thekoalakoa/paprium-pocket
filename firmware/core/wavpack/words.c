////////////////////////////////////////////////////////////////////////////
//                           **** WAVPACK ****                            //
//                  Hybrid Lossless Wavefile Compressor                   //
//              Copyright (c) 1998 - 2004 Conifer Software.               //
//                          All Rights Reserved.                          //
////////////////////////////////////////////////////////////////////////////
/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */

// words.c
// paprium-fw port (core/wavpack, test build 4b): the WavPack library the cart chip uses (the tiny decoder), for the
// first-boot unpack of the sound bank. Edited from a version we proved bit-exact on rv32im: encoder, stereo, float and
// sample-rate parts dropped, tables generated (words.c), platform headers. License: LICENSE.txt here.

// This module provides entropy word encoding and decoding functions using
// a variation on the Rice method.  This was introduced in version 3.93
// because it allows splitting the data into a "lossy" stream and a
// "correction" stream in a very efficient manner and is therefore ideal
// for the "hybrid" mode.  For 4.0, the efficiency of this method was
// significantly improved by moving away from the normal Rice restriction of
// using powers of two for the modulus divisions and now the method can be
// used for both hybrid and pure lossless encoding.

// Samples are divided by median probabilities at 5/7 (71.43%), 10/49 (20.41%),
// and 20/343 (5.83%). Each zone has 3.5 times fewer samples than the
// previous. Using standard Rice coding on this data would result in 1.4
// bits per sample average (not counting sign bit). However, there is a
// very simple encoding that is over 99% efficient with this data and
// results in about 1.22 bits per sample.

#include "wavpack.h"

#include <string.h>

//////////////////////////////// local macros /////////////////////////////////

#define LIMIT_ONES 16   // maximum consecutive 1s sent for "div" data

// these control the time constant "slow_level" which is used for hybrid mode
// that controls bitrate as a function of residual level (HYBRID_BITRATE).
#define SLS 8
#define SLO ((1 << (SLS - 1)))

// these control the time constant of the 3 median level breakpoints
#define DIV0 128        // 5/7 of samples
#define DIV1 64         // 10/49 of samples
#define DIV2 32         // 20/343 of samples

// this macro retrieves the specified median breakpoint (without frac; min = 1)
#define GET_MED(med) (((c->median [med]) >> 4) + 1)

// These macros update the specified median breakpoints. Note that the median
// is incremented when the sample is higher than the median, else decremented.
// They are designed so that the median will never drop below 1 and the value
// is essentially stationary if there are 2 increments for every 5 decrements.

#define INC_MED0() (c->median [0] += ((c->median [0] + DIV0) / DIV0) * 5)
#define DEC_MED0() (c->median [0] -= ((c->median [0] + (DIV0-2)) / DIV0) * 2)
#define INC_MED1() (c->median [1] += ((c->median [1] + DIV1) / DIV1) * 5)
#define DEC_MED1() (c->median [1] -= ((c->median [1] + (DIV1-2)) / DIV1) * 2)
#define INC_MED2() (c->median [2] += ((c->median [2] + DIV2) / DIV2) * 5)
#define DEC_MED2() (c->median [2] -= ((c->median [2] + (DIV2-2)) / DIV2) * 2)

#define count_bits(av) ( \
 (av) < (1 << 8) ? nbits_table [av] : \
  ( \
   (av) < (1L << 16) ? nbits_table [(av) >> 8] + 8 : \
   ((av) < (1L << 24) ? nbits_table [(av) >> 16] + 16 : nbits_table [(av) >> 24] + 24) \
  ) \
)

///////////////////////////// local table storage ////////////////////////////

// paprium-fw port: the four tables are generated at run time by wvpk_tables_init () (end of this file) from
// their formulas; the cart chip holds the same 1,024 bytes as constants (measured equal 2026-10-22). Call it
// before any decode.
static char nbits_table [256];
static uchar log2_table [256];
static uchar exp2_table [256];
static char ones_count_table [256];

///////////////////////////// executable code ////////////////////////////////

void init_words (WavpackStream *wps)
{
    CLEAR (wps->w);
}

static int mylog2 (uint32_t avalue);

// Read the median log2 values from the specifed metadata structure, convert
// them back to 32-bit unsigned values and store them. If length is not
// exactly correct then we flag and return an error.

int read_entropy_vars (WavpackStream *wps, WavpackMetadata *wpmd)
{
    uchar *byteptr = wpmd->data;

    if (wpmd->byte_length != ((wps->wphdr.flags & MONO_DATA) ? 6 : 12))
        return FALSE;

    wps->w.c [0].median [0] = exp2s (byteptr [0] + (byteptr [1] << 8));
    wps->w.c [0].median [1] = exp2s (byteptr [2] + (byteptr [3] << 8));
    wps->w.c [0].median [2] = exp2s (byteptr [4] + (byteptr [5] << 8));

    if (!(wps->wphdr.flags & MONO_DATA)) {
        wps->w.c [1].median [0] = exp2s (byteptr [6] + (byteptr [7] << 8));
        wps->w.c [1].median [1] = exp2s (byteptr [8] + (byteptr [9] << 8));
        wps->w.c [1].median [2] = exp2s (byteptr [10] + (byteptr [11] << 8));
    }

    return TRUE;
}

// Read the hybrid related values from the specifed metadata structure, convert
// them back to their internal formats and store them. The extended profile
// stuff is not implemented yet, so return an error if we get more data than
// we know what to do with.

int read_hybrid_profile (WavpackStream *wps, WavpackMetadata *wpmd)
{
    uchar *byteptr = wpmd->data;
    uchar *endptr = byteptr + wpmd->byte_length;

    if (wps->wphdr.flags & HYBRID_BITRATE) {
        wps->w.c [0].slow_level = exp2s (byteptr [0] + (byteptr [1] << 8));
        byteptr += 2;

        if (!(wps->wphdr.flags & MONO_DATA)) {
            wps->w.c [1].slow_level = exp2s (byteptr [0] + (byteptr [1] << 8));
            byteptr += 2;
        }
    }

    wps->w.bitrate_acc [0] = (int32_t)(byteptr [0] + (byteptr [1] << 8)) << 16;
    byteptr += 2;

    if (!(wps->wphdr.flags & MONO_DATA)) {
        wps->w.bitrate_acc [1] = (int32_t)(byteptr [0] + (byteptr [1] << 8)) << 16;
        byteptr += 2;
    }

    if (byteptr < endptr) {
        wps->w.bitrate_delta [0] = exp2s ((short)(byteptr [0] + (byteptr [1] << 8)));
        byteptr += 2;

        if (!(wps->wphdr.flags & MONO_DATA)) {
            wps->w.bitrate_delta [1] = exp2s ((short)(byteptr [0] + (byteptr [1] << 8)));
            byteptr += 2;
        }

        if (byteptr < endptr)
            return FALSE;
    }
    else
        wps->w.bitrate_delta [0] = wps->w.bitrate_delta [1] = 0;

    return TRUE;
}

// This function is called during both encoding and decoding of hybrid data to
// update the "error_limit" variable which determines the maximum sample error
// allowed in the main bitstream. In the HYBRID_BITRATE mode (which is the only
// currently implemented) this is calculated from the slow_level values and the
// bitrate accumulators. Note that the bitrate accumulators can be changing.

static void update_error_limit (struct words_data *w, uint32_t flags)
{
    int bitrate_0 = (w->bitrate_acc [0] += w->bitrate_delta [0]) >> 16;

    if (flags & MONO_DATA) {
        if (flags & HYBRID_BITRATE) {
            int slow_log_0 = (w->c [0].slow_level + SLO) >> SLS;

            if (slow_log_0 - bitrate_0 > -0x100)
                w->c [0].error_limit = exp2s (slow_log_0 - bitrate_0 + 0x100);
            else
                w->c [0].error_limit = 0;
        }
        else
            w->c [0].error_limit = exp2s (bitrate_0);
    }
    else {
        int bitrate_1 = (w->bitrate_acc [1] += w->bitrate_delta [1]) >> 16;

        if (flags & HYBRID_BITRATE) {
            int slow_log_0 = (w->c [0].slow_level + SLO) >> SLS;
            int slow_log_1 = (w->c [1].slow_level + SLO) >> SLS;

            if (flags & HYBRID_BALANCE) {
                int balance = (slow_log_1 - slow_log_0 + bitrate_1 + 1) >> 1;

                if (balance > bitrate_0) {
                    bitrate_1 = bitrate_0 * 2;
                    bitrate_0 = 0;
                }
                else if (-balance > bitrate_0) {
                    bitrate_0 = bitrate_0 * 2;
                    bitrate_1 = 0;
                }
                else {
                    bitrate_1 = bitrate_0 + balance;
                    bitrate_0 = bitrate_0 - balance;
                }
            }

            if (slow_log_0 - bitrate_0 > -0x100)
                w->c [0].error_limit = exp2s (slow_log_0 - bitrate_0 + 0x100);
            else
                w->c [0].error_limit = 0;

            if (slow_log_1 - bitrate_1 > -0x100)
                w->c [1].error_limit = exp2s (slow_log_1 - bitrate_1 + 0x100);
            else
                w->c [1].error_limit = 0;
        }
        else {
            w->c [0].error_limit = exp2s (bitrate_0);
            w->c [1].error_limit = exp2s (bitrate_1);
        }
    }
}

static uint32_t read_code (Bitstream *bs, uint32_t maxcode);

// Read the next word from the bitstream "wvbits" and return the value. This
// function can be used for hybrid or lossless streams, but since an
// optimized version is available for lossless this function would normally
// be used for hybrid only. If a hybrid lossless stream is being read then
// the "correction" offset is written at the specified pointer. A return value
// of WORD_EOF indicates that the end of the bitstream was reached (all 1s) or
// some other error occurred.

int32_t get_words (int32_t *buffer, int nsamples, uint32_t flags,
                struct words_data *w, Bitstream *bs)
{
    register struct entropy_data *c = w->c;
    int csamples;

    if (!(flags & MONO_DATA))
        nsamples *= 2;

    for (csamples = 0; csamples < nsamples; ++csamples) {
        uint32_t ones_count, low, mid, high;

        if (!(flags & MONO_DATA))
            c = w->c + (csamples & 1);

        if (!(w->c [0].median [0] & ~1) && !w->holding_zero && !w->holding_one && !(w->c [1].median [0] & ~1)) {
            uint32_t mask;
            int cbits;

            if (w->zeros_acc) {
                if (--w->zeros_acc) {
                    c->slow_level -= (c->slow_level + SLO) >> SLS;
                    *buffer++ = 0;
                    continue;
                }
            }
            else {
                for (cbits = 0; cbits < 33 && getbit (bs); ++cbits);

                if (cbits == 33)
                    break;

                if (cbits < 2)
                    w->zeros_acc = cbits;
                else {
                    for (mask = 1, w->zeros_acc = 0; --cbits; mask <<= 1)
                        if (getbit (bs))
                            w->zeros_acc |= mask;

                    w->zeros_acc |= mask;
                }

                if (w->zeros_acc) {
                    c->slow_level -= (c->slow_level + SLO) >> SLS;
                    CLEAR (w->c [0].median);
                    CLEAR (w->c [1].median);
                    *buffer++ = 0;
                    continue;
                }
            }
        }

        if (w->holding_zero)
            ones_count = w->holding_zero = 0;
        else {
            int next8;

            if (bs->bc < 8) {
                if (++(bs->ptr) == bs->end)
                    bs->wrap (bs);

                next8 = (bs->sr |= *(bs->ptr) << bs->bc) & 0xff;
                bs->bc += 8;
            }
            else
                next8 = bs->sr & 0xff;

            if (next8 == 0xff) {
                bs->bc -= 8;
                bs->sr >>= 8;

                for (ones_count = 8; ones_count < (LIMIT_ONES + 1) && getbit (bs); ++ones_count);

                if (ones_count == (LIMIT_ONES + 1))
                    break;

                if (ones_count == LIMIT_ONES) {
                    uint32_t mask;
                    int cbits;

                    for (cbits = 0; cbits < 33 && getbit (bs); ++cbits);

                    if (cbits == 33)
                        break;

                    if (cbits < 2)
                        ones_count = cbits;
                    else {
                        for (mask = 1, ones_count = 0; --cbits; mask <<= 1)
                            if (getbit (bs))
                                ones_count |= mask;

                        ones_count |= mask;
                    }

                    ones_count += LIMIT_ONES;
                }
            }
            else {
                bs->bc -= (ones_count = ones_count_table [next8]) + 1;
                bs->sr >>= ones_count + 1;
            }

            if (w->holding_one) {
                w->holding_one = ones_count & 1;
                ones_count = (ones_count >> 1) + 1;
            }
            else {
                w->holding_one = ones_count & 1;
                ones_count >>= 1;
            }

            w->holding_zero = ~w->holding_one & 1;
        }

        if ((flags & HYBRID_FLAG) && ((flags & MONO_DATA) || !(csamples & 1)))
            update_error_limit (w, flags);

        if (ones_count == 0) {
            low = 0;
            high = GET_MED (0) - 1;
            DEC_MED0 ();
        }
        else {
            low = GET_MED (0);
            INC_MED0 ();

            if (ones_count == 1) {
                high = low + GET_MED (1) - 1;
                DEC_MED1 ();
            }
            else {
                low += GET_MED (1);
                INC_MED1 ();

                if (ones_count == 2) {
                    high = low + GET_MED (2) - 1;
                    DEC_MED2 ();
                }
                else {
                    low += (ones_count - 2) * GET_MED (2);
                    high = low + GET_MED (2) - 1;
                    INC_MED2 ();
                }
            }
        }

        mid = (high + low + 1) >> 1;

        if (!c->error_limit)
            mid = read_code (bs, high - low) + low;
        else while (high - low > c->error_limit) {
            if (getbit (bs))
                mid = (high + (low = mid) + 1) >> 1;
            else
                mid = ((high = mid - 1) + low + 1) >> 1;
        }

        *buffer++ = getbit (bs) ? ~mid : mid;

        if (flags & HYBRID_BITRATE)
            c->slow_level = c->slow_level - ((c->slow_level + SLO) >> SLS) + mylog2 (mid);
    }

    return (flags & MONO_DATA) ? csamples : (csamples / 2);
}

// Read a single unsigned value from the specified bitstream with a value
// from 0 to maxcode. If there are exactly a power of two number of possible
// codes then this will read a fixed number of bits; otherwise it reads the
// minimum number of bits and then determines whether another bit is needed
// to define the code.

static uint32_t read_code (Bitstream *bs, uint32_t maxcode)
{
    int bitcount = count_bits (maxcode);
    uint32_t extras = (1L << bitcount) - maxcode - 1, code;

    if (!bitcount)
        return 0;

    getbits (&code, bitcount - 1, bs);
    code &= (1L << (bitcount - 1)) - 1;

    if (code >= extras) {
        code = (code << 1) - extras;

        if (getbit (bs))
            ++code;
    }

    return code;
}

// The concept of a base 2 logarithm is used in many parts of WavPack. It is
// a way of sufficiently accurately representing 32-bit signed and unsigned
// values storing only 16 bits (actually fewer). It is also used in the hybrid
// mode for quickly comparing the relative magnitude of large values (i.e.
// division) and providing smooth exponentials using only addition.

// These are not strict logarithms in that they become linear around zero and
// can therefore represent both zero and negative values. They have 8 bits
// of precision and in "roundtrip" conversions the total error never exceeds 1
// part in 225 except for the cases of +/-115 and +/-195 (which error by 1).


// This function returns the log2 for the specified 32-bit unsigned value.
// The maximum value allowed is about 0xff800000 and returns 8447.

static int mylog2 (uint32_t avalue)
{
    int dbits;

    if ((avalue += avalue >> 9) < (1 << 8)) {
        dbits = nbits_table [avalue];
        return (dbits << 8) + log2_table [(avalue << (9 - dbits)) & 0xff];
    }
    else {
        if (avalue < (1L << 16))
            dbits = nbits_table [avalue >> 8] + 8;
        else if (avalue < (1L << 24))
            dbits = nbits_table [avalue >> 16] + 16;
        else
            dbits = nbits_table [avalue >> 24] + 24;

        return (dbits << 8) + log2_table [(avalue >> (dbits - 9)) & 0xff];
    }
}

// This function returns the log2 for the specified 32-bit signed value.
// All input values are valid and the return values are in the range of
// +/- 8192.

// This function returns the original integer represented by the supplied
// logarithm (at least within the provided accuracy). The log is signed,
// but since a full 32-bit value is returned this can be used for unsigned
// conversions as well (i.e. the input range is -8192 to +8447).

int32_t exp2s (int log)
{
    uint32_t value;

    if (log < 0)
        return -exp2s (-log);

    value = exp2_table [log & 0xff] | 0x100;

    if ((log >>= 8) <= 9)
        return value >> (9 - log);
    else
        return value << (log - 9);
}

// This function converts the 8-bit signed character version of a weight stored
// in metadata back to the internal weight (which is normally +/-1024).

int restore_weight (signed char weight)
{
    int result;

    if ((result = (int) weight << 3) > 0)
        result += (result + 64) >> 7;

    return result;
}

// paprium-fw port: the four tables from their formulas (the cart chip holds them as 1,024 bytes of constants;
// this tree types no table, tests/check_tree.py and tools/leakguard.py):
//   nbits_table [i]      = the bit length of i (0 for 0)
//   ones_count_table [i] = the number of 1 bits at the bottom of i (8 for 255)
//   exp2_table [i]       = round (256 * 2^(i/256)) - 256
//   log2_table [i]       = round (256 * log2 (1 + i/256))
// Integer only: P(k) = 2^(k/512) in Q30 as the product of the factors 2^(2^b/512) over the set bits b of k (at most
// nine), the factors made by repeated square roots of 2. Every P(k) is then within ~2e-8 of exact, while the closest
// entry of either rounded table is 8e-4 of a step from a rounding edge (measured 2026-10-22), so both are exact;
// tests/equiv/cache4b.py checks all four against the formulas in exact arithmetic.

static uint32_t wvpk_isqrt (uint64_t x)
{
    uint64_t r = 0, b = (uint64_t) 1 << 62;

    while (b > x)
        b >>= 2;

    while (b) {
        if (x >= r + b) {
            x -= r + b;
            r = (r >> 1) + b;
        }
        else
            r >>= 1;

        b >>= 2;
    }

    return (uint32_t) r;
}

static uint32_t wvpk_pow512 (const uint32_t *f, uint32_t k)
{
    uint32_t v = 1u << 30;
    int b;

    for (b = 0; b < 9; b++)
        if (k & (1u << b))
            v = (uint32_t) (((uint64_t) v * f [b] + (1u << 29)) >> 30);

    return v;
}

void wvpk_tables_init (void)
{
    uint32_t f [9], i, j, v, x;
    int b;

    f [8] = wvpk_isqrt ((uint64_t) 1 << 61);                // 2^(256/512) = sqrt (2), Q30

    for (b = 7; b >= 0; b--)
        f [b] = wvpk_isqrt ((uint64_t) f [b + 1] << 30);    // 2^(2^b/512)

    for (i = 0, j = 1; i < 256; i++) {
        for (v = i, b = 0; v; v >>= 1)
            b++;

        nbits_table [i] = b;

        for (v = i, b = 0; v & 1; v >>= 1)
            b++;

        ones_count_table [i] = b;
        exp2_table [i] = ((wvpk_pow512 (f, 2 * i) + (1u << 21)) >> 22) - 256;
        x = (256 + i) << 22;                                // 1 + i/256 in Q30

        while (j <= 256 && wvpk_pow512 (f, 2 * j - 1) <= x)   // the half-steps 2^((2j-1)/512) at or below it
            j++;

        log2_table [i] = j - 1;
    }
}
