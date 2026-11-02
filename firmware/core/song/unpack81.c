/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/unpack81.c - the decoder for the game's 0x81 packed streams (the entries are described in unpack81.h).
 *
 * Written by our team from our own study of how the cart behaves: on every 0x81 stream the game has, it writes the
 * same bytes as the cart's chip, and the same number of them.
 *
 * The format
 * ----------
 * A body is a list of instructions. Each one starts with a command byte, and some kinds then read more bytes: length
 * bytes, one or two distance bytes and literal bytes. An instruction either appends LITERAL bytes, taken from the body
 * as they are, or COPIES bytes the output already holds: LENGTH bytes, each one taken from DISTANCE bytes before it.
 * The bytes of a copy are made one at a time, in order, so a copy that is longer than its distance repeats the last
 * DISTANCE bytes (distance 1 repeats one byte). After every copy come 0-3 more literal bytes, its TAIL; the tail count
 * is in bits 1-0 of the command byte (short and near copies) or of the first distance byte (mid and far copies).
 *
 *   command byte   kind        length                          distance
 *   0x40-0xFF      near copy   1 + bits 7-5: 3-8               1 + bits 4-2 + 8 x the next byte: 1-2,048
 *   0x20-0x3F      mid copy    2 + bits 4-0: 3-33, or long     1 + bits 15-2 of the next two bytes (low byte first):
 *                                                              1-16,384
 *   0x10-0x1F      far copy    2 + bits 2-0: 3-9, or long      16,384 + 16,384 x bit 3 + bits 15-2 of the next two
 *                                                              bytes: 16,385-49,151. Bit 3 and bits 15-2 all zero
 *                                                              is the END of the body instead (its length and tail
 *                                                              are not used; its bytes count as read).
 *   0x00-0x0F      what it means depends on what the instruction before it appended:
 *                  - nothing (a copy with no tail, or the start of the body): a literal run of 3 + bits 3-0 bytes
 *                    (4-18), or long;
 *                  - 1-3 tail bytes: a short copy of 2 bytes from 1 + bits 3-2 + 4 x the next byte (1-1,024) back;
 *                  - a literal run of 4 or more bytes: a short copy of 3 bytes from 2,049 + bits 3-2 + 4 x the next
 *                    byte (2,049-3,072) back.
 *
 * A LONG length: when the length field is zero, the bytes after the command byte extend it. Each zero byte adds 255,
 * and the first non-zero byte adds its own value and ends the count. The field's largest value (15 for a literal run,
 * 31 for a mid copy, 7 for a far copy) is added first, then the 3 or the 2 of the table, so a long literal run is at
 * least 19 bytes, a long mid copy at least 34 and a long far copy at least 10. The length bytes come before the
 * distance bytes.
 *
 * The first byte of a body has one more meaning: 18 or more starts the body with a run of (that byte - 17) literal
 * bytes, 1-238. A run of 1-3 counts as a tail for the next command byte, one of 4 or more as a literal run. A first
 * byte of 17 or less is an ordinary command byte. The three bytes 0x11 0x00 0x00 alone are the empty body.
 *
 * Decoding ends only at the end instruction. The game's streams never copy from before the destination, never lack
 * their end, and in them a command byte of 0x00-0x0F is always a literal run; the short copies and the start run are
 * still decoded exactly as above.
 *
 * How the code is laid out
 * ------------------------
 * There are two bodies. unpack81_whole is the fast one: the game's own data, no limit checked. The limited body serves
 * both unpack81_until and unpack81_checked: it checks the limits once per instruction, not once per byte, and when the
 * output limit falls inside an instruction it writes the bytes that still fit and stops. Both loops first write what
 * the instruction just read appends (len bytes from `from`, then `tail` literal bytes from the body), then read the
 * next command byte; a literal run is written by the same loop, with `from` pointing into the body. `mode` keeps what
 * the instruction before the command byte appended, which is all a command byte of 0x00-0x0F needs: 0 nothing, 1-3 a
 * copy's tail, AFTER_RUN a literal run (a start run of 1-3 bytes counts as a tail).
 * The whole body writes the first two bytes of every copy outside the byte loop, and a literal run writes two more in
 * its own branch: every instruction has at least that many bytes, and those bytes then cost no loop step or branch.
 * Every copy and every literal run is written one byte at a time, and the code reads back only bytes it has already
 * written, so it works on any destination whatever its alignment. This firmware runs on our core's MCU (the NEORV32,
 * a RISC-V soft CPU inside the FPGA), and it unpacks into three kinds of memory: the SDRAM workspace (a part of the
 * Pocket's SDRAM that the MCU uses as scratch memory), WRAM (the MCU's own 48 KB of working RAM inside the FPGA) and
 * the MegaWire screen's text area in CRAM (the Pocket's cellular RAM, a separate RAM chip on the Pocket that our core
 * maps into the MCU's address space).
 *
 * The input check of the limited body: at every command byte at least 3 body bytes are known to be left. A body can
 * only finish at its end instruction, which is 3 bytes long, so each instruction checks, before it is accepted, that
 * its own bytes and 3 more are there. A body that fails this check could never have finished inside the limit, so the
 * answer is the same as if every byte were checked as it is read.
 *
 * The file has no read-only data (no switch tables, no constant arrays). IROM is the MCU's 88 KB code memory inside
 * the FPGA, which holds the firmware's code and its read-only data. The Pocket firmware images put read-only data in
 * the part of IROM after the CPU MATE brain (see board/pocket/link/pocket88k.json), which has very little room.
 */
#include "song.h"
#include "unpack81.h"

/* SONG_BUG 25 (song.h's list of planted bugs, for the host test's negative control only; never set in an image that
   ships): a mid copy takes its bytes from one place too near, so the test that checks a mid copy must fail. */
#if SONG_BUG == 25
#define MID_BACK 0u
#else
#define MID_BACK 1u
#endif

#define AFTER_RUN 4u            /* `mode` after a literal run */

/* Copies bytes forward, one at a time, from *from to out until out reaches stop (at least one byte); returns the new
   out. The empty asm statement emits no instruction: it only keeps the store ahead of the step of `out`, so the loop
   does not end with a store just before its branch. On our core's MCU a branch right after a load or a store takes
   about 1.5 cycles longer (measured with a small benchmark in a simulation of our core's logic). */
static inline __attribute__((always_inline)) uint8_t *copy_forward(uint8_t *out, const uint8_t **from, const uint8_t *stop)
{
    const uint8_t *f = *from;

    do {
        uint8_t b = *f++;
        *out = b;
        __asm__ ("" : "+r" (out));
        out++;
    } while (out != stop);
    *from = f;
    return out;
}

/* The same for two bytes or more: the first two are written before the loop. Still one byte at a time and in order,
   so an overlapping copy (distance 1 or 2) reads back the bytes just written. */
static inline __attribute__((always_inline)) uint8_t *copy_two_or_more(uint8_t *out, const uint8_t **from, const uint8_t *stop)
{
    const uint8_t *f = *from;

    out[0] = f[0];
    out[1] = f[1];
    out += 2;
    f += 2;
    if (out != stop)
        out = copy_forward(out, &f, stop);
    *from = f;
    return out;
}

/* A long length (see the top of this file): returns 255 for every zero byte plus the value of the first non-zero
   byte, and moves *pin past them. No limit is checked. */
static inline __attribute__((always_inline)) uint32_t long_length(const uint8_t **pin)
{
    const uint8_t *in = *pin;
    uint32_t n = 0, b;

    while ((b = *in++) == 0u)
        n += 255u;
    *pin = in;
    return n + b;
}

/* The same with the input limit of the limited body: returns 0 when a length byte would be read at or past in_end.
   It also gives up (returns 0) once the count comes within 1,023 of the largest 32-bit value: no output limit can hold
   a copy that long, so such a body is refused anyway, and the count and the sums made from it can never wrap around. */
static inline __attribute__((always_inline)) uint32_t long_length_limited(const uint8_t **pin, uintptr_t in_end)
{
    const uint8_t *in = *pin;
    uint32_t n = 0, b;

    for (;;) {
        if ((uintptr_t)in >= in_end)
            return 0u;
        b = *in++;
        if (b != 0u)
            break;
        n += 255u;
        if (n > UINT32_MAX - 1023u)
            return 0u;
    }
    *pin = in;
    return n + b;
}

uint32_t UNPACK81_WHOLE(const uint8_t *src, uint8_t *dst)
{
    const uint8_t *in = src;
    uint8_t *out = dst;
    const uint8_t *from;
    uint32_t c, len, tail = 0, mode = 0;

    c = *in++;
    if (c >= 18u) {
        /* the body opens with a run of c - 17 literal bytes */
        len = c - 17u;
        out = copy_forward(out, &in, out + len);
        mode = len < 4u ? len : AFTER_RUN;
        c = *in++;
    }
    goto decode;
    for (;;) {
        /* write what the instruction just read appends: len bytes (2 or more) from `from`, then its tail */
        out = copy_two_or_more(out, &from, out + len);
        if (tail != 0u)
            out = copy_forward(out, &in, out + tail);
        c = *in++;
decode:
        if (c >= 0x40u) {                               /* near copy */
            len = (c >> 5) + 1u;
            from = out - 1 - ((c >> 2) & 7u) - ((uint32_t)*in++ << 3);
            tail = c & 3u;
        } else if (c < 0x10u) {
            if (mode == 0u) {
                /* literal run: its first two bytes are written here, the rest at the top of the loop */
                len = c;
                if (len == 0u)
                    len = 15u + long_length(&in);
                len += 3u;
                out[0] = in[0];
                out[1] = in[1];
                out += 2;
                from = in + 2;
                in += len;
                len -= 2u;
                mode = AFTER_RUN;
                continue;
            }
            len = 2u;                                   /* short copy */
            from = out - 1 - ((c >> 2) & 3u) - ((uint32_t)*in++ << 2);
            if (mode == AFTER_RUN) {
                len = 3u;
                from -= 2048;
            }
            tail = c & 3u;
        } else if (c >= 0x20u) {                        /* mid copy */
            len = c & 31u;
            if (len == 0u)
                len = 31u + long_length(&in);
            len += 2u;
            from = out - MID_BACK - (in[0] >> 2) - ((uint32_t)in[1] << 6);
            tail = in[0] & 3u;
            in += 2;
        } else {                                        /* far copy, or the end */
            uint32_t back;
            len = c & 7u;
            if (len == 0u)
                len = 7u + long_length(&in);
            len += 2u;
            back = (in[0] >> 2) + ((uint32_t)in[1] << 6) + ((c & 8u) << 11);
            tail = in[0] & 3u;
            in += 2;
            if (back == 0u)
                return (uint32_t)(out - dst);
            from = out - 16384u - back;
        }
        mode = tail;
    }
}

/* The limited body. in_end / out_end: the first input address that must not be read and the first output address
   that must not be written (unpack81_until passes the highest address as in_end: no input limit). used = 0 for
   unpack81_until. For unpack81_checked, *used holds the low 32 bits of src's address while the body runs (it saves a
   register) and gets the body bytes read at the end instruction. The result is the bytes written at the end
   instruction. When the body stops early (the output limit, or input that breaks a rule) the result is
   UNPACK81_REFUSED when used is given, and the bytes written so far when it is not. */
static uint32_t unpack81_limited(const uint8_t *src, uintptr_t in_end, uint8_t *dst, uintptr_t out_end, uint32_t *used)
{
    const uint8_t *in = src;
    uint8_t *out = dst;
    const uint8_t *from;
    uintptr_t room;
    uint32_t c, len, tail = 0, mode = 0, back;

    if (used)
        *used = (uint32_t)(uintptr_t)src;
    if (in_end - (uintptr_t)in < 3u)
        goto refuse;
    c = *in++;
    if (c < 18u)
        goto decode;                                    /* an ordinary command byte */
    /* the body opens with a run of c - 17 literal bytes; they and the next command must be there */
    len = c - 17u;
    if (in_end - (uintptr_t)in < len + 3u)
        goto refuse;
    mode = len < 4u ? len : AFTER_RUN;
    from = in;
    in += len;
    for (;;) {
        if (len + tail > out_end - (uintptr_t)out)
            goto partial;
        out = copy_forward(out, &from, out + len);
        if (__builtin_expect(tail != 0u, 0))
            out = copy_forward(out, &in, out + tail);
        c = *in++;
decode:
        /* c and the two bytes after it are known to be inside the input */
        if (c >= 0x40u) {                               /* near copy */
            len = (c >> 5) + 1u;
            back = 1u + ((c >> 2) & 7u) + ((uint32_t)*in++ << 3);
            tail = c & 3u;
        } else if (c >= 0x20u) {                        /* mid copy */
            len = c & 31u;
            if (__builtin_expect(len == 0u, 0)) {
                len = long_length_limited(&in, in_end);
                if (len == 0u || in_end - (uintptr_t)in < 2u)
                    goto refuse;
                len += 31u;
            }
            len += 2u;
            back = MID_BACK + (in[0] >> 2) + ((uint32_t)in[1] << 6);
            tail = in[0] & 3u;
            in += 2;
        } else if (c >= 0x10u) {                        /* far copy, or the end */
            len = c & 7u;
            if (__builtin_expect(len == 0u, 0)) {
                len = long_length_limited(&in, in_end);
                if (len == 0u || in_end - (uintptr_t)in < 2u)
                    goto refuse;
                len += 7u;
            }
            len += 2u;
            back = (in[0] >> 2) + ((uint32_t)in[1] << 6) + ((c & 8u) << 11);
            tail = in[0] & 3u;
            in += 2;
            if (__builtin_expect(back == 0u, 0)) {
                if (used)
                    *used = (uint32_t)(uintptr_t)in - *used;
                return (uint32_t)(out - dst);
            }
            back += 16384u;
        } else if (mode == 0u) {                        /* literal run: it and the next command must be there */
            len = c;
            if (len == 0u) {
                len = long_length_limited(&in, in_end);
                if (len == 0u)
                    goto refuse;
                len += 15u;
            }
            len += 3u;
            if (in_end - (uintptr_t)in < len + 3u)
                goto refuse;
            from = in;
            in += len;
            tail = 0u;
            mode = AFTER_RUN;
            continue;
        } else {                                        /* short copy */
            len = 2u;
            back = 1u + ((c >> 2) & 3u) + ((uint32_t)*in++ << 2);
            if (mode == AFTER_RUN) {
                len = 3u;
                back += 2048u;
            }
            tail = c & 3u;
        }
        /* a copy: it must not reach back before the destination, and its tail and the next command must be there */
        if (back > (uint32_t)(out - dst) || in_end - (uintptr_t)in < tail + 3u)
            goto refuse;
        from = out - back;
        mode = tail;
    }

partial:
    /* The output limit falls inside this instruction: write the bytes that fit (len bytes from `from`, then the
       tail from the body) and stop. */
    room = out_end - (uintptr_t)out;
    if (len > room)
        len = (uint32_t)room;
    room -= len;
    if (tail > room)
        tail = (uint32_t)room;
    if (len != 0u)
        out = copy_forward(out, &from, out + len);
    if (tail != 0u)
        out = copy_forward(out, &in, out + tail);
refuse:
    return used ? UNPACK81_REFUSED : (uint32_t)(out - dst);
}

uint32_t UNPACK81_UNTIL(const uint8_t *src, uint8_t *dst, const uint8_t *end)
{
    const uint8_t *lit = src + 1;
    uint32_t c, n = 0, room;

    if (end <= dst)
        return 0u;
    /* A room that ends inside the body's first literal run (every game stream starts with one) is filled here, without
       the set-up of the limited body. A long first run is taken here only when its length is a single byte. */
    room = (uint32_t)(end - dst);
    c = src[0];
    if (c != 0u) {
        n = c + 3u;
    } else if (src[1] != 0u) {
        n = 18u + src[1];
        lit++;
    }
    if (c < 0x10u && room <= n) {
        copy_forward(dst, &lit, end);
        return room;
    }
    return unpack81_limited(src, UINTPTR_MAX, dst, (uintptr_t)end, 0);
}

uint32_t unpack81_checked(const uint8_t *src, uint32_t available, uint8_t *dst, uint32_t capacity, uint32_t *used)
{
    uintptr_t in_end = (uintptr_t)src + available;
    uintptr_t out_end = (uintptr_t)dst + capacity;

    if (in_end < (uintptr_t)src)            /* a limit past the top of the address space: the top is the limit */
        in_end = UINTPTR_MAX;
    if (out_end < (uintptr_t)dst)
        out_end = UINTPTR_MAX;
    return unpack81_limited(src, in_end, dst, out_end, used);
}
