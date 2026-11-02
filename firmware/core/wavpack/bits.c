////////////////////////////////////////////////////////////////////////////
//                           **** WAVPACK ****                            //
//                  Hybrid Lossless Wavefile Compressor                   //
//              Copyright (c) 1998 - 2004 Conifer Software.               //
//                          All Rights Reserved.                          //
//      Distributed under the BSD Software License (see license.txt)      //
////////////////////////////////////////////////////////////////////////////
/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */

// bits.c
// paprium-fw port (core/wavpack, test build 4b): the WavPack library the cart chip uses (the tiny decoder), for the
// first-boot unpack of the sound bank. Edited from a version we proved bit-exact on rv32im: encoder, stereo, float and
// sample-rate parts dropped, tables generated (words.c), platform headers. License: LICENSE.txt here.

// This module provides utilities to support the BitStream structure which is
// used to read and write all WavPack audio data streams. It also contains a
// wrapper for the stream I/O functions and a set of functions dealing with
// endian-ness, both for enhancing portability. Finally, a debug wrapper for
// the malloc() system is provided.

#include "wavpack.h"

#include <string.h>

////////////////////////// Bitstream functions ////////////////////////////////

// Open the specified BitStream and associate with the specified buffer.

static void bs_read (Bitstream *bs);

void bs_open_read (Bitstream *bs, uchar *buffer_start, uchar *buffer_end, read_stream file, uint32_t file_bytes)
{
    CLEAR (*bs);
    bs->buf = buffer_start;
    bs->end = buffer_end;

    if (file) {
        bs->ptr = bs->end - 1;
        bs->file_bytes = file_bytes;
        bs->file = file;
    }
    else
        bs->ptr = bs->buf - 1;

    bs->wrap = bs_read;
}

// This function is only called from the getbit() and getbits() macros when
// the BitStream has been exhausted and more data is required. Sinve these
// bistreams no longer access files, this function simple sets an error and
// resets the buffer.

static void bs_read (Bitstream *bs)
{
    if (bs->file && bs->file_bytes) {
        uint32_t bytes_read, bytes_to_read = bs->end - bs->buf;

        if (bytes_to_read > bs->file_bytes)
            bytes_to_read = bs->file_bytes;

        bytes_read = bs->file (bs->buf, bytes_to_read);

        if (bytes_read) {
            bs->end = bs->buf + bytes_read;
            bs->file_bytes -= bytes_read;
        }
        else {
            memset (bs->buf, -1, bs->end - bs->buf);
            bs->error = 1;
        }
    }
    else
        bs->error = 1;

    if (bs->error)
        memset (bs->buf, -1, bs->end - bs->buf);

    bs->ptr = bs->buf;
}

/////////////////////// Endian Correction Routines ////////////////////////////

void little_endian_to_native (void *data, char *format)
{
    uchar *cp = (uchar *) data;

    while (*format) {
        switch (*format) {
            case 'L':
                *(long *)cp = letoh32(*(long *)cp);
                cp += 4;
                break;

            case 'S':
                *(short *)cp = letoh16(*(short *)cp);
                cp += 2;
                break;

            default:
                if (*format >= '0' && *format <= '9')
                    cp += *format - '0';

                break;
        }

        format++;
    }
}

