/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/*
 * core/song/song_cfg.c - the 88 configuration: bit 0 YM-DAC mode, bit 1 NTSC, bit 2 raw pitch, bit 3
 * C9 x1. The chip's DAC DMA start / stop and DAC pins become the synth's CONFIG write on the Pocket (board hook);
 * the scheduler fields it writes are the logic's.
 */
#include "song.h"

void audio_config(uint32_t cfg)
{
    int ym, ntsc;
    if (G.last_cfg == cfg)
        return;
    G.last_cfg = (uint8_t)(cfg & 0x7F);
    ym = cfg & 1;
    G.ymdac = (uint16_t)ym;
    ntsc = (cfg & 2) != 0;
    G.rate = ntsc ? 0x3C : 0x32;
    G.raw_pitch = (cfg & 4) != 0;
    G.c9_x1 = (cfg & 8) != 0;
    if (ym == 1 && ntsc) {
        G.blocks = 5;
        G.samples = 800;
        G.r12 = (uint16_t)ym;
        G.r38 = (uint16_t)ym;
    } else {
        S.v[5].program = 0xFFFF;
        G.blocks = 6;
        G.samples = 0x3C0;
        G.r38 = 1;
        G.r36 = 0;
        G.r3a = 0xFF;
        if (ym != 1) {
            G.psg_master = 0x10C;
            G.fm_master = 0xE1;
            G.wave_master = 0x10D;
            G.sfx_master = 0x100;
            board_dac_mode(0, (uint32_t)ntsc);      /* the cart chip's DAC DMA start */
            return;
        }
    }
    G.r3a = 0xFF;
    G.r36 = 0;
    S.v[5].program = 0xFFFF;
    G.psg_master = 0x100;
    G.wave_master = 0x100;
    G.fm_master = 0xC3;
    G.sfx_master = 0x1C7;
    board_dac_mode(1, (uint32_t)ntsc);              /* the cart chip's DAC DMA stop */
}
