////////////////////////////////////////////////////////////////////////////
//                           **** WAVPACK ****                            //
//                  Hybrid Lossless Wavefile Compressor                   //
//              Copyright (c) 1998 - 2004 Conifer Software.               //
//                          All Rights Reserved.                          //
//      Distributed under the BSD Software License (see license.txt)      //
////////////////////////////////////////////////////////////////////////////
/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */

// unpack.c
// paprium-fw port (core/wavpack, test build 4b): the WavPack library the cart chip uses (the tiny decoder), for the
// first-boot unpack of the sound bank. Edited from a version we proved bit-exact on rv32im: encoder, stereo, float and
// sample-rate parts dropped, tables generated (words.c), platform headers. License: LICENSE.txt here.

// This module actually handles the decompression of the audio data, except
// for the entropy decoding which is handled by the words.c module. For
// maximum efficiency, the conversion is isolated to tight loops that handle
// an entire buffer.

#include "wavpack.h"

#include <string.h>

static void strcpy_loc (char *dst, char *src) { while ((*dst++ = *src++) != 0); }

#define LOSSY_MUTE

///////////////////////////// executable code ////////////////////////////////

// This function initializes everything required to unpack a WavPack block
// and must be called before unpack_samples() is called to obtain audio data.
// It is assumed that the WavpackHeader has been read into the wps->wphdr
// (in the current WavpackStream). This is where all the metadata blocks are
// scanned up to the one containing the audio bitstream.

int unpack_init (WavpackContext *wpc)
{
    WavpackStream *wps = &wpc->stream;
    WavpackMetadata wpmd;

    if (wps->wphdr.block_samples && wps->wphdr.block_index != (uint32_t) -1)
        wps->sample_index = wps->wphdr.block_index;

    wps->mute_error = FALSE;
    wps->crc = (uint32_t) -1;   // paprium-fw port: the literal all-ones (core/ types no 0xFFFFFFxx: check_tree rule 1)
    CLEAR (wps->wvbits);
    CLEAR (wps->decorr_passes);
    CLEAR (wps->w);

    while (read_metadata_buff (wpc, &wpmd)) {
        if (!process_metadata (wpc, &wpmd)) {
            strcpy_loc (wpc->error_message, "invalid metadata!");
            return FALSE;
        }

        if (wpmd.id == ID_WV_BITSTREAM)
            break;
    }

    if (wps->wphdr.block_samples && !bs_is_open (&wps->wvbits)) {
        strcpy_loc (wpc->error_message, "invalid WavPack file!");
        return FALSE;
    }

    if (wps->wphdr.block_samples) {
        if ((wps->wphdr.flags & INT32_DATA) && wps->int32_sent_bits)
            wpc->lossy_blocks = TRUE;

        if ((wps->wphdr.flags & FLOAT_DATA) &&
            wps->float_flags & (FLOAT_EXCEPTIONS | FLOAT_ZEROS_SENT | FLOAT_SHIFT_SENT | FLOAT_SHIFT_SAME))
                wpc->lossy_blocks = TRUE;
    }

    return TRUE;
}

// This function initialzes the main bitstream for audio samples, which must
// be in the "wv" file.

int init_wv_bitstream (WavpackContext *wpc, WavpackMetadata *wpmd)
{
    WavpackStream *wps = &wpc->stream;

    if (wpmd->data)
        bs_open_read (&wps->wvbits, wpmd->data, (unsigned char *) wpmd->data + wpmd->byte_length, NULL, 0);
    else if (wpmd->byte_length)
        bs_open_read (&wps->wvbits, wpc->read_buffer, wpc->read_buffer + sizeof (wpc->read_buffer),
            wpc->infile, wpmd->byte_length + (wpmd->byte_length & 1));

    return TRUE;
}

// Read decorrelation terms from specified metadata block into the
// decorr_passes array. The terms range from -3 to 8, plus 17 & 18;
// other values are reserved and generate errors for now. The delta
// ranges from 0 to 7 with all values valid. Note that the terms are
// stored in the opposite order in the decorr_passes array compared
// to packing.

int read_decorr_terms (WavpackStream *wps, WavpackMetadata *wpmd)
{
    int termcnt = wpmd->byte_length;
    uchar *byteptr = wpmd->data;
    struct decorr_pass *dpp;

    if (termcnt > MAX_NTERMS)
        return FALSE;

    wps->num_terms = termcnt;

    for (dpp = wps->decorr_passes + termcnt - 1; termcnt--; dpp--) {
        dpp->term = (int)(*byteptr & 0x1f) - 5;
        dpp->delta = (*byteptr++ >> 5) & 0x7;

        if (!dpp->term || dpp->term < -3 || (dpp->term > MAX_TERM && dpp->term < 17) || dpp->term > 18)
            return FALSE;
    }

    return TRUE;
}

// Read decorrelation weights from specified metadata block into the
// decorr_passes array. The weights range +/-1024, but are rounded and
// truncated to fit in signed chars for metadata storage. Weights are
// separate for the two channels and are specified from the "last" term
// (first during encode). Unspecified weights are set to zero.

int read_decorr_weights (WavpackStream *wps, WavpackMetadata *wpmd)
{
    int termcnt = wpmd->byte_length, tcount;
    signed char *byteptr = wpmd->data;
    struct decorr_pass *dpp;

    if (!(wps->wphdr.flags & MONO_DATA))
        termcnt /= 2;

    if (termcnt > wps->num_terms)
        return FALSE;

    for (tcount = wps->num_terms, dpp = wps->decorr_passes; tcount--; dpp++)
        dpp->weight_A = dpp->weight_B = 0;

    while (--dpp >= wps->decorr_passes && termcnt--) {
        dpp->weight_A = restore_weight (*byteptr++);

        if (!(wps->wphdr.flags & MONO_DATA))
            dpp->weight_B = restore_weight (*byteptr++);
    }

    return TRUE;
}

// Read decorrelation samples from specified metadata block into the
// decorr_passes array. The samples are signed 32-bit values, but are
// converted to signed log2 values for storage in metadata. Values are
// stored for both channels and are specified from the "last" term
// (first during encode) with unspecified samples set to zero. The
// number of samples stored varies with the actual term value, so
// those must obviously come first in the metadata.

int read_decorr_samples (WavpackStream *wps, WavpackMetadata *wpmd)
{
    uchar *byteptr = wpmd->data;
    uchar *endptr = byteptr + wpmd->byte_length;
    struct decorr_pass *dpp;
    int tcount;

    for (tcount = wps->num_terms, dpp = wps->decorr_passes; tcount--; dpp++) {
        CLEAR (dpp->samples_A);
        CLEAR (dpp->samples_B);
    }

    if (wps->wphdr.version == 0x402 && (wps->wphdr.flags & HYBRID_FLAG)) {
        byteptr += 2;

        if (!(wps->wphdr.flags & MONO_DATA))
            byteptr += 2;
    }

    while (dpp-- > wps->decorr_passes && byteptr < endptr)
        if (dpp->term > MAX_TERM) {
            dpp->samples_A [0] = exp2s ((short)(byteptr [0] + (byteptr [1] << 8)));
            dpp->samples_A [1] = exp2s ((short)(byteptr [2] + (byteptr [3] << 8)));
            byteptr += 4;

            if (!(wps->wphdr.flags & MONO_DATA)) {
                dpp->samples_B [0] = exp2s ((short)(byteptr [0] + (byteptr [1] << 8)));
                dpp->samples_B [1] = exp2s ((short)(byteptr [2] + (byteptr [3] << 8)));
                byteptr += 4;
            }
        }
        else if (dpp->term < 0) {
            dpp->samples_A [0] = exp2s ((short)(byteptr [0] + (byteptr [1] << 8)));
            dpp->samples_B [0] = exp2s ((short)(byteptr [2] + (byteptr [3] << 8)));
            byteptr += 4;
        }
        else {
            int m = 0, cnt = dpp->term;

            while (cnt--) {
                dpp->samples_A [m] = exp2s ((short)(byteptr [0] + (byteptr [1] << 8)));
                byteptr += 2;

                if (!(wps->wphdr.flags & MONO_DATA)) {
                    dpp->samples_B [m] = exp2s ((short)(byteptr [0] + (byteptr [1] << 8)));
                    byteptr += 2;
                }

                m++;
            }
        }

    return byteptr == endptr;
}

// Read the int32 data from the specified metadata into the specified stream.
// This data is used for integer data that has more than 24 bits of magnitude
// or, in some cases, used to eliminate redundant bits from any audio stream.

int read_int32_info (WavpackStream *wps, WavpackMetadata *wpmd)
{
    int bytecnt = wpmd->byte_length;
    char *byteptr = wpmd->data;

    if (bytecnt != 4)
        return FALSE;

    wps->int32_sent_bits = *byteptr++;
    wps->int32_zeros = *byteptr++;
    wps->int32_ones = *byteptr++;
    wps->int32_dups = *byteptr;
    return TRUE;
}

// Read multichannel information from metadata. The first byte is the total
// number of channels and the following bytes represent the channel_mask
// as described for Microsoft WAVEFORMATEX.

int read_channel_info (WavpackContext *wpc, WavpackMetadata *wpmd)
{
    int bytecnt = wpmd->byte_length, shift = 0;
    char *byteptr = wpmd->data;
    uint32_t mask = 0;

    if (!bytecnt || bytecnt > 5)
        return FALSE;

    wpc->config.num_channels = *byteptr++;

    while (--bytecnt) {
        mask |= (uint32_t) *byteptr++ << shift;
        shift += 8;
    }

    wpc->config.channel_mask = mask;
    return TRUE;
}

// Read configuration information from metadata.

int read_config_info (WavpackContext *wpc, WavpackMetadata *wpmd)
{
    int bytecnt = wpmd->byte_length;
    uchar *byteptr = wpmd->data;

    if (bytecnt >= 3) {
        wpc->config.flags &= 0xff;
        wpc->config.flags |= (int32_t) *byteptr++ << 8;
        wpc->config.flags |= (int32_t) *byteptr++ << 16;
        wpc->config.flags |= (int32_t) *byteptr << 24;
    }

    return TRUE;
}

// Read non-standard sampling rate from metadata.

int read_sample_rate (WavpackContext *wpc, WavpackMetadata *wpmd)
{
    int bytecnt = wpmd->byte_length;
    uchar *byteptr = wpmd->data;

    if (bytecnt == 3) {
        wpc->config.sample_rate = (int32_t) *byteptr++;
        wpc->config.sample_rate |= (int32_t) *byteptr++ << 8;
        wpc->config.sample_rate |= (int32_t) *byteptr++ << 16;
    }

    return TRUE;
}

// This monster actually unpacks the WavPack bitstream(s) into the specified
// buffer as 32-bit integers or floats (depending on orignal data). Lossy
// samples will be clipped to their original limits (i.e. 8-bit samples are
// clipped to -128/+127) but are still returned in int32_ts. It is up to the
// caller to potentially reformat this for the final output including any
// multichannel distribution, block alignment or endian compensation. The
// function unpack_init() must have been called and the entire WavPack block
// must still be visible (although wps->blockbuff will not be accessed again).
// For maximum clarity, the function is broken up into segments that handle
// various modes. This makes for a few extra infrequent flag checks, but
// makes the code easier to follow because the nesting does not become so
// deep. For maximum efficiency, the conversion is isolated to tight loops
// that handle an entire buffer. The function returns the total number of
// samples unpacked, which can be less than the number requested if an error
// occurs or the end of the block is reached.

static void decorr_mono_pass (struct decorr_pass *dpp, int32_t *buffer, int32_t sample_count);
static void fixup_samples (WavpackStream *wps, int32_t *buffer, uint32_t sample_count);

int32_t unpack_samples (WavpackContext *wpc, int32_t *buffer, uint32_t sample_count)
{
    WavpackStream *wps = &wpc->stream;
    uint32_t flags = wps->wphdr.flags, crc = wps->crc, i;
    int32_t mute_limit = (1L << ((flags & MAG_MASK) >> MAG_LSB)) + 2;
    struct decorr_pass *dpp;
    int32_t *bptr, *eptr;
    int tcount;

    if (wps->sample_index + sample_count > wps->wphdr.block_index + wps->wphdr.block_samples)
        sample_count = wps->wphdr.block_index + wps->wphdr.block_samples - wps->sample_index;

    if (wps->mute_error) {
        memset (buffer, 0, sample_count * 4);    // paprium-fw port: the output is always mono (one int32 a sample)
        wps->sample_index += sample_count;
        return sample_count;
    }

    if (flags & HYBRID_FLAG)
        mute_limit *= 2;

    ///////////////////// handle version 4 mono data /////////////////////////

    if (flags & MONO_DATA) {
        eptr = buffer + sample_count;
        i = get_words (buffer, sample_count, flags, &wps->w, &wps->wvbits);

        for (tcount = wps->num_terms, dpp = wps->decorr_passes; tcount--; dpp++)
            decorr_mono_pass (dpp, buffer, sample_count);

        for (bptr = buffer; bptr < eptr; ++bptr) {
            if (__builtin_labs (bptr [0]) > mute_limit) {
                i = bptr - buffer;
                break;
            }

            crc = crc * 3 + bptr [0];
        }
    }

    //////////////////// paprium-fw port: no stereo decode ////////////////////////

    // The cart decodes only mono streams (it refuses any other before the first sample), so the stereo path has
    // no effect; a block that is not mono is muted here (the mute path below).

    else
        i = 0;

    if (i != sample_count) {
        memset (buffer, 0, sample_count * 4);    // paprium-fw port: the output is always mono (one int32 a sample)
        wps->mute_error = TRUE;
        i = sample_count;
    }

    fixup_samples (wps, buffer, i);

    wps->sample_index += i;
    wps->crc = crc;

    return i;
}

static void decorr_mono_pass (struct decorr_pass *dpp, int32_t *buffer, int32_t sample_count)
{
    int32_t delta = dpp->delta, weight_A = dpp->weight_A;
    int32_t *bptr, *eptr = buffer + sample_count, sam_A;
    int m, k;

    switch (dpp->term) {

        case 17:
            for (bptr = buffer; bptr < eptr; bptr++) {
                sam_A = 2 * dpp->samples_A [0] - dpp->samples_A [1];
                dpp->samples_A [1] = dpp->samples_A [0];
                dpp->samples_A [0] = apply_weight (weight_A, sam_A) + bptr [0];
                update_weight (weight_A, delta, sam_A, bptr [0]);
                bptr [0] = dpp->samples_A [0];
            }

            break;

        case 18:
            for (bptr = buffer; bptr < eptr; bptr++) {
                sam_A = (3 * dpp->samples_A [0] - dpp->samples_A [1]) >> 1;
                dpp->samples_A [1] = dpp->samples_A [0];
                dpp->samples_A [0] = apply_weight (weight_A, sam_A) + bptr [0];
                update_weight (weight_A, delta, sam_A, bptr [0]);
                bptr [0] = dpp->samples_A [0];
            }

            break;

        default:
            for (m = 0, k = dpp->term & (MAX_TERM - 1), bptr = buffer; bptr < eptr; bptr++) {
                sam_A = dpp->samples_A [m];
                dpp->samples_A [k] = apply_weight (weight_A, sam_A) + bptr [0];
                update_weight (weight_A, delta, sam_A, bptr [0]);
                bptr [0] = dpp->samples_A [k];
                m = (m + 1) & (MAX_TERM - 1);
                k = (k + 1) & (MAX_TERM - 1);
            }

            if (m) {
                int32_t temp_samples [MAX_TERM];

                memcpy (temp_samples, dpp->samples_A, sizeof (dpp->samples_A));

                for (k = 0; k < MAX_TERM; k++, m++)
                    dpp->samples_A [k] = temp_samples [m & (MAX_TERM - 1)];
            }

            break;
    }

    dpp->weight_A = weight_A;
}


// This is a helper function for unpack_samples() that applies several final
// operations. First, if the data is 32-bit float data, then that conversion
// is done in the float.c module (whether lossy or lossless) and we return.
// Otherwise, if the extended integer data applies, then that operation is
// executed first. If the unpacked data is lossy (and not corrected) then
// it is clipped and shifted in a single operation. Otherwise, if it's
// lossless then the last step is to apply the final shift (if any).

// Rockbox's copy of this function returned every integer sample as 28 bits
// and left the lossy clipping to its dsp module. Here the 28-bit scaling is
// gone again (the samples come out right-justified, as the tiny decoder
// gives them); the lossy clipping stays out (the sound bank is lossless).

static void fixup_samples (WavpackStream *wps, int32_t *buffer, uint32_t sample_count)
{
    uint32_t flags = wps->wphdr.flags;
    int shift = (flags & SHIFT_MASK) >> SHIFT_LSB;

    /* Rockbox 28-bit scaling removed: original tiny decoder output (right-justified samples) */

    if (flags & INT32_DATA) {
        uint32_t count = (flags & MONO_DATA) ? sample_count : sample_count * 2;
        int sent_bits = wps->int32_sent_bits, zeros = wps->int32_zeros;
        int ones = wps->int32_ones, dups = wps->int32_dups;
        int32_t *dptr = buffer;

        if (!(flags & HYBRID_FLAG) && !sent_bits && (zeros + ones + dups))
            while (count--) {
                if (zeros)
                    *dptr <<= zeros;
                else if (ones)
                    *dptr = ((*dptr + 1) << ones) - 1;
                else if (dups)
                    *dptr = ((*dptr + (*dptr & 1)) << dups) - (*dptr & 1);

                dptr++;
            }
        else
            shift += zeros + sent_bits + ones + dups;
    }

    if (shift > 0) {
        if (!(flags & MONO_DATA))
            sample_count *= 2;

        while (sample_count--)
            *buffer++ <<= shift;
    }
    else if (shift < 0) {
        shift = -shift;

        if (!(flags & MONO_DATA))
            sample_count *= 2;

        while (sample_count--)
            *buffer++ >>= shift;
    }
}

// This function checks the crc value(s) for an unpacked block, returning the
// number of actual crc errors detected for the block. The block must be
// completely unpacked before this test is valid. For losslessly unpacked
// blocks of float or extended integer data the extended crc is also checked.
// Note that WavPack's crc is not a CCITT approved polynomial algorithm, but
// is a much simpler method that is virtually as robust for real world data.

int check_crc_error (WavpackContext *wpc)
{
    WavpackStream *wps = &wpc->stream;
    int result = 0;

    if (wps->crc != wps->wphdr.crc)
        ++result;

    return result;
}
