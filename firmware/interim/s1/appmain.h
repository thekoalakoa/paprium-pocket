/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */
/* interim/s1/appmain.h - the new firmware's "appmain.h", which the moved 0.2.6 sources include (legacy/026/mame.c,
 * interim/album, interim/s1). First on the new firmware's include path (fwbuild.json s1), so those files get this
 * one instead of board/pocket/appmain.h or board/host/appmain.h; the 0.2.6 source set never sees it.
 *
 * Differences from the 0.2.6 header, each on purpose:
 *   - no <neorv32.h>: nothing moved into the new firmware uses the NEORV32 HAL (the heartbeat and trap record are
 *     off, PPM_HEARTBEAT 0), and MTIME, UART and WDT are not built (docs/MCU_INTERFACE.md section 2);
 *   - board.h: the board interface v1.0 (time, the stream, the register file) for the FW_S1 guards (FW_S1 = every
 *     build of the new firmware's source set);
 *   - printf drops its arguments: there is no UART (docs/MCU_INTERFACE.md section 2, TEST printf only in host builds
 *     of 0.2.6), and an argument such as mame.c's unknown-packer print of ppmio.ramdp->reg_cmd would otherwise still
 *     be evaluated: an MCU read of RAMDP $1FEA, which no new firmware code may make (docs/CART_FPGA_SPEC.md 15.1). */
#ifndef APPMAIN_H
#define APPMAIN_H

#include <stdint.h>
#include <string.h>
#include "board.h"
#include "cfg.h"
/* the FW_S5 TEST images (FW_S5 = the full firmware, board/board.h) no longer carry 0.2.6's SAT snapshot diagnostic
   (test build S3a on);
   the cart has no such copy, and its 2.7 KB of TEST IROM went to the stage-3 code that does what the cart chip does
   (the unpackers, the zoom, the saves and MegaWire; README.md "Terms"). The FW_S5 = 0 images keep it
   (their test rigs read it: fuzz_s1 --q1). RELEASE never had it. */
#if FW_S5 && !defined(PPM_SAT_SNAPSHOT)
#define PPM_SAT_SNAPSHOT        0
#endif
#include "mame.h"
#include "paprium.h"
#include "sfx.h"
#include "mdp.h"
#include "everdrive.h"

#define printf(...)             ((void)0)

/* a clock figure the compiler cannot fold into another constant (a product, a compare's figure - 1, a division's
   multiply-and-shift): the images built for the two clocks then differ only in the figure itself
   (tests/check_clock.py --images) */
static inline uint32_t s1_clk(uint32_t v) { __asm__ ("" : "+r" (v)); return v; }

void printHex(void *src, u32 size);

/* TEST (PPM_SAT_SNAPSHOT): AF's SAT snapshot (mame.c ppm_obj_frame_end, 0.2.6's diagnostic) is over L1's budget, so
   the thread makes it below the brain call (interim/s1/bodies_s1.c l3_test_work) */
void s1_sat_snapshot_later(void);

#endif
