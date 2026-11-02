/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/s1_freg.h - the new-core register accessor's state (board layer only; the core sees brd_freg_rd/wr).
 * Shared by the Pocket board (s1_freg.c) and the host board's twin (board/host/s1_board.c). */
#ifndef S1_FREG_H
#define S1_FREG_H

#include <stdint.h>
#include "tdiag.h"

/* the chip-runner comparison's log: TEST builds, except the scheduler probe (its own 16 KB log fills wram_upper) and
   the lean FW_S5 TEST images (core/trace/tdiag.h) */
#if !PPM_RELEASE && !S1_PROBE && !TDIAG_LEAN
#define S1_ORACLE               1
#else
#define S1_ORACLE               0
#endif
#define S1_ORACLE_N             512u    /* oracle log entries (a power of 2) */
typedef struct {
    uint32_t n;                         /* writes logged since the boot (the ring keeps the last S1_ORACLE_N) */
    uint32_t e[S1_ORACLE_N];            /* bits 31-24 offset or tag, 23-0 value */
} s1_oracle_log_t;
extern s1_oracle_log_t s1_oracle_log;   /* S1_ORACLE builds only */

extern uint16_t s1_freg_shadow[16];     /* the last value written at each chip offset (index = off / 2) */

#endif
