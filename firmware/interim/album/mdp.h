/* 
 * File:   mdp.h
 * Author: Igor
 *
 * Created on July 21, 2025, 10:58 AM
 */
/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */

#ifndef MDP_H
#define	MDP_H

void mdp_init();
void mdp_play(u8 track);
void mdp_play_once(u8 track);
void mdp_stop();
void mdp_set_vol(u8 vol);

#endif	/* MDP_H */

