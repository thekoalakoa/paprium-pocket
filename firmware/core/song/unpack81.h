/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/unpack81.h - the decoder for the game's 0x81 packed streams.
 *
 * The game keeps much of its data packed: music modules, name tables and maps, tables, and the cart program block.
 * Each packed stream starts with a type byte. Type 0x81 is the format known publicly as LZO1X; unpack81.c explains it.
 * The callers read the type byte themselves and pass the address of the byte after it, the first byte of the BODY.
 * The decoder writes its output forward from the destination, one byte after the other with no gap, and returns how
 * many bytes it wrote. It writes nothing before the destination and nothing after the last output byte.
 *
 * Three entries share the format:
 *
 *   whole   (src, dst)                               -> bytes written
 *     Decodes the whole body and checks no limit, as the cart's chip does. It is only given the game's own streams,
 *     which are all well formed. Its users: the DA unpack job (the 68000's request to unpack a ROM block into the
 *     workspace), the music module store, and the power-on read of the cart program block (save_boot).
 *
 *   until   (src, dst, end)                          -> bytes written
 *     Writes the same bytes as whole, in the same order, but never one at or past `end` (the first address that must
 *     not be written): it stops at the first byte that would land there. The result is the smaller of the stream's
 *     full length and end - dst; end = dst writes nothing and returns 0. The F4 job (the zoom picture unpack) uses it.
 *
 *   unpack81_checked (src, available, dst, capacity, used) -> bytes written, or UNPACK81_REFUSED
 *     For input that may not be the game's own (the MegaWire screen reads whatever ROM the player loaded). `available`
 *     is how many body bytes may be read from src on, `capacity` how many bytes may be written from dst on, and `used`
 *     points to a 32-bit word (it must not be 0). It refuses (returns UNPACK81_REFUSED) when a byte would be read at or
 *     past src + available, when a byte would be written at or past dst + capacity, or when a copy would reach back
 *     before dst. On a refusal the bytes already written and the word at `used` are left undefined. Otherwise, at the
 *     end instruction, it returns the bytes written and stores the body bytes it read (the end instruction included)
 *     into *used.
 *
 * Names: the first two entries are declared in song.h as song_unpack81 and song_unpack81_to, the names the rest of
 * the firmware and the test tools use. With UNPACK81_SONG_NAMES set to 1 this file defines them under those names.
 * With UNPACK81_SONG_NAMES 0 (the default) it defines them as unpack81_whole and unpack81_until instead, so it can be
 * built beside another decoder that defines song.h's names. unpack81_checked has one name in both cases.
 */
#ifndef UNPACK81_H
#define UNPACK81_H
#include <stdint.h>

#ifndef UNPACK81_SONG_NAMES
#define UNPACK81_SONG_NAMES 0
#endif

#if UNPACK81_SONG_NAMES
#define UNPACK81_WHOLE  song_unpack81
#define UNPACK81_UNTIL  song_unpack81_to
#else
#define UNPACK81_WHOLE  unpack81_whole
#define UNPACK81_UNTIL  unpack81_until
#endif

#define UNPACK81_REFUSED  UINT32_MAX    /* unpack81_checked's answer to input it will not decode */

uint32_t UNPACK81_WHOLE(const uint8_t *src, uint8_t *dst);
uint32_t UNPACK81_UNTIL(const uint8_t *src, uint8_t *dst, const uint8_t *end);
uint32_t unpack81_checked(const uint8_t *src, uint32_t available, uint8_t *dst, uint32_t capacity, uint32_t *used);

#endif
