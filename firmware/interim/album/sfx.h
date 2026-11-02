/* 
 * File:   sfx.h
 * Author: Igor
 *
 * Created on July 20, 2025, 7:41 PM
 */
/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */

#ifndef SFX_H
#define	SFX_H

void sfx_play(u8 arg);
void sfx_loop(u8 arg);
void sfx_stop(u8 arg);
void sfx_player_update();
/* the new firmware (FW_S1 only, interim/s1/sfx_s1.c: the cart chip's SFX channels): D2, the per-channel fade on the
   synth tick, the level table, the 88 mode bit, and the feeder's pending starts */
void sfx_d2(u8 arg);
void sfx_fade_tick(void);
void sfx_level_init(void);
void sfx_mode88(u8 lo);
u32 sfx_pend_run(void);
extern u8 s1_sfx_pend;

#endif	/* SFX_H */

