/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/include/pocket_s5.h - the MCU interface v1.3 lines the FW_S5 firmware (the song engine on the synth)
 * reads.
 *
 * MCU interface v1.3 was frozen on 2026-10-21. Since the merge of test build 5 (with test build
 * 4b's boot overlay) pocket_map.h carries the v1.3 Appendix A in whole (checked against docs/MCU_INTERFACE.md by
 * tests/check_board.py); these POCKET_SY_* names stay as the FW_S5 code's spelling of it, each asserted below equal
 * to its Appendix A twin (POCKET_SYN_*); no other s1 image includes this file. */
#ifndef POCKET_S5_H
#define POCKET_S5_H

#include "pocket_map.h"

#define POCKET_FIO_STAMP_A      POCKET_FIO(14)   /* v1.3: R TIMER when CAUSE.A was last set (4.6) */
#define POCKET_SY_BASE          0x06000000u      /* v1.3 region 0x06: the synth (3.10) */
#define POCKET_SY(off)          (POCKET_SY_BASE + (off))
#define POCKET_SY_ID            POCKET_SY(0x000) /* 0x5335_0001 */
#define POCKET_SY_CONFIG        POCKET_SY(0x004)
#define POCKET_SY_ARM           POCKET_SY(0x024)
#define POCKET_SY_SEQ           POCKET_SY(0x028) /* [15:0] ARR, [31:16] DONE */
#define POCKET_SY_DONE          POCKET_SY(0x02C) /* W: DONE := [15:0] */
#define POCKET_SY_STATUS        POCKET_SY(0x030) /* [0] BUSY, [1] RUN, [2] FPEND, [3] FILL, [4] CUR, [8:5] QDEPTH,
                                                    [27:16] BLKCNT */
#define POCKET_SY_SEQLAT        POCKET_SY(0x048) /* [15:0] B, [31:16] A */
#define POCKET_SY_DIAG          POCKET_SY(0x040) /* [7:0] INCOMPLETE, [15:8] TIMEOUTS, [23:16] WBUSY, [31:24] UNDERRUN;
                                                    any write clears all four */
#define POCKET_SY_SCHED         POCKET_SY(0x04C) /* [7:0] CNT, [11:8] NBLK, [31:16] HALF */
#define POCKET_CR(off)          (0x09000000u + (off))   /* v1.3 3.8: MCU address = 0x09000000 + CRAM byte */
#define POCKET_CRAM_DACBUF_L    POCKET_CR(0x170000)     /* v1.3: 1,920 x u16 (the $1880 stream) */
#define POCKET_CRAM_BANK        POCKET_CR(0x000100)     /* v1.3: the wave bank, the chip's SDRAM 0xC0089800 */
#define POCKET_CTRL_BLKIE       (1u << 6)        /* v1.3: CAUSE.BLK takes part in the MEI line */
#define POCKET_CAUSE_BLK        (1u << 4)        /* v1.3: the synth's BUSY fell (3.10.5); W1C */

_Static_assert(POCKET_SY_BASE == POCKET_SYN(0) && POCKET_SY_ID == POCKET_SYN_ID && POCKET_SY_CONFIG == POCKET_SYN_CONFIG &&
               POCKET_SY_ARM == POCKET_SYN_ARM && POCKET_SY_SEQ == POCKET_SYN_SEQ && POCKET_SY_DONE == POCKET_SYN_DONE &&
               POCKET_SY_STATUS == POCKET_SYN_STATUS && POCKET_SY_SEQLAT == POCKET_SYN_SEQLAT &&
               POCKET_SY_DIAG == POCKET_SYN_DIAG && POCKET_SY_SCHED == POCKET_SYN_SCHED,
               "pocket_s5.h's names == MCU_INTERFACE v1.3 Appendix A (pocket_map.h, card 5)");

#endif
