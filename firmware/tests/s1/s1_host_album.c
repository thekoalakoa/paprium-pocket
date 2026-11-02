/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/s1_host_album.c - the interim album / SFX entry points on the x86 host, as board/host/ours_host.c has them
 * for the 0.2.6 build: LOGGED with their argument and RAMDP $1E10-$1E15 (the interface the 68000 drives), not
 * executed. The stage-1 host programs (FW_S1, our new firmware: tests/s1/s1_ours.c, disp_tests.c, boot_tests.c) link
 * this instead of interim/album/{sfx,mdp,everdrive}.c, which drive fixed MCU addresses. Same record layout as
 * ours_host.c (8 bytes: kind, arg, a0, a1, a2), so the two hosts' audio logs compare byte for byte. */
#include "appmain.h"
#include "s1_host_album.h"

s1_au_t s1_au[S1_AU_N];
int s1_au_n;

static void au_put(uint8_t k, uint8_t a)
{
    if (s1_au_n < S1_AU_N) {
        s1_au[s1_au_n].kind = k;
        s1_au[s1_au_n].arg = a;
        s1_au[s1_au_n].a0 = ppmio.ramdp->cmd_args[0];
        s1_au[s1_au_n].a1 = ppmio.ramdp->cmd_args[1];
        s1_au[s1_au_n].a2 = ppmio.ramdp->cmd_args[2];
        s1_au_n++;
    }
}

void sfx_play(u8 a) { au_put(1, a); }
void sfx_loop(u8 a) { au_put(2, a); }
void sfx_stop(u8 a) { au_put(3, a); }
void sfx_d2(u8 a) { au_put(3, a); }        /* stage 1: D2's entry (the chip's law); the same kind as 0.2.6's sfx_stop */
void sfx_fade_tick(void) { }
void sfx_level_init(void) { }
void sfx_mode88(u8 lo) { (void)lo; }       /* stage 1: the 88 mode bit for the chip's SFX starts (no log entry) */
void sfx_player_update(void) { }
void mdp_init(void) { au_put(10, 0); }
void mdp_play(u8 t) { au_put(11, t); }
void mdp_play_once(u8 t) { au_put(12, t); }
void mdp_stop(void) { au_put(13, 0); }
void mdp_set_vol(u8 v) { au_put(14, v); }

/* the interim audio (interim/s1/audio_s1.c on the Pocket): the replay runs no SFX feeder and no VU rows on the wheel,
   as the final 0.2.6 host replay runs neither (its main loop is not run): the kicks are no-ops here */
void s1_sfx_kick(void) { }
void s1_vu_kick(void) { }
