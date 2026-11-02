/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/s1/s1_host_album.h - the logged interim entry points of the stage-1 host programs (FW_S1, our new firmware;
 * s1_host_album.c). */
#ifndef S1_HOST_ALBUM_H
#define S1_HOST_ALBUM_H

#include <stdint.h>

#define S1_AU_N                 256
typedef struct { uint8_t kind, arg; uint16_t a0, a1, a2; } s1_au_t;    /* = ours_host.c AuLog */
extern s1_au_t s1_au[S1_AU_N];
extern int s1_au_n;

#endif
