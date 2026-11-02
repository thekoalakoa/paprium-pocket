/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song_tables.c - the song engine's state (the cart chip's RAM layouts, asserted below) and its two
 * hand-typed cart chip tables. The cart chip is the STM32 microcontroller on the real cartridge.
 *
 * chip_note_pitch and chip_fm_fnum are the ONLY cart chip values typed into this tree as numbers (B Jam's decision of
 * 2026-10-10; tools/leak_allow.json pins them). Note lookups can read past the note table: song_note_tail holds the 12
 * bytes the cart chip has there, which the boot reads from the player's ROM (interim/s1/bodies_s1.c save_boot: the
 * cart program the game carries), so they are not typed in here. Every other table the engine reads is generated
 * (core/tables) or computed in the code. The tables were worked out from our own study of how the cart behaves and
 * checked on hardware.
 */
#include "song.h"

song_seq    S;
song_g      G;
song_sfx    SFX;
sfx_rec     sfx_table[256];
uint32_t    bgm_table[64];
uint8_t     z80_q_area[4 + 0x80] __attribute__((aligned(4)));
uint16_t    z80_packet[0xE0];
#if SONG_BUG == 14
uint32_t    song_bug14_underrun;
#endif
uint32_t    song_note_far;
song_views_t song_v;

/* the note pitches */
const uint16_t chip_note_pitch[108] = {
    16, 17, 18, 19, 20, 22, 23, 24, 26, 27, 29, 31, 33, 35, 37, 39, 41, 44, 46, 49, 52, 55, 58, 62, 65, 69, 73, 78,
    82, 87, 92, 98, 104, 110, 116, 123, 131, 139, 147, 155, 165, 175, 185, 196, 208, 220, 233, 247, 262, 277, 294,
    311, 330, 349, 370, 392, 415, 440, 466, 494, 523, 554, 587, 622, 659, 698, 740, 784, 831, 880, 923, 988, 1046,
    1109, 1175, 1244, 1318, 1397, 1480, 1570, 1661, 1760, 1865, 1976, 2093, 2217, 2349, 2489, 2637, 2793, 2960, 3136,
    3322, 3520, 3729, 3951, 4186, 4435, 4698, 4978, 5274, 5587, 5919, 6271, 6644, 7040, 7459, 7902 };

/* the FM fnums */
const uint16_t chip_fm_fnum[13] = { 644, 681, 722, 765, 810, 858, 910, 964, 1021, 1081, 1146, 1214, 1288 };

/* the 12 bytes after the note table, from the player's ROM at the boot (save_boot; zeros when
   the ROM gives no cart program) */
uint8_t song_note_tail[SONG_NOTE_TAIL_N];

_Static_assert(sizeof(song_voice) == 0x70, "voice record");
_Static_assert(offsetof(song_seq, v) == 0x58, "S layout");
_Static_assert(offsetof(song_seq, order) == 0x3A, "S layout");
_Static_assert(offsetof(song_seq, loop) == 0x50, "S layout");
_Static_assert(sizeof(song_seq) == 0xBB8, "S size");
_Static_assert(offsetof(song_g, blkcnt) == 0x10, "G layout");
_Static_assert(offsetof(song_g, pending) == 0x18, "G layout");
_Static_assert(offsetof(song_g, q_len) == 0x20, "G layout");
_Static_assert(offsetof(song_g, fm_master) == 0x30, "G layout");
_Static_assert(offsetof(song_g, last_cfg) == 0x3E, "G layout");
_Static_assert(sizeof(song_g) == 0x40, "G size");
_Static_assert(sizeof(sfx_ch) == 0x34, "SFX channel");
_Static_assert(offsetof(song_sfx, ch) == 0x20, "SFX layout");
_Static_assert(sizeof(song_sfx) == 0x1C0, "SFX size");
_Static_assert(sizeof(sfx_rec) == 8, "SFX record");
_Static_assert(offsetof(song_voice, mode_param) == 0xBE - 0x58, "voice layout");
_Static_assert(offsetof(song_voice, sax) == 0xC4 - 0x58, "voice layout");
