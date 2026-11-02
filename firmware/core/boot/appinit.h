/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/boot/appinit.h - the boot steps of the core (docs/BOOT_SPEC.md sections 1-3). Board-independent: both boards
 * run them from their boot (board/pocket/s1_board.c brd_boot; the host tests in the same order). */
#ifndef CORE_APPINIT_H
#define CORE_APPINIT_H

#include <stdint.h>

/* Steps P3 and P4 of docs/BOOT_SPEC.md (rows BOOT-04 to BOOT-06), in bootpage.c: the boot page, ROM $0000-$1FDF, into
   cart RAM (the header letters at $1E0-$1E2 stay as the ROM file has them, since row BOOT-07 was dropped), the
   boot-page patches (docs/ALLOWLIST.md, row B3), the ROM patch at $81104 and the header word $1E4 = $FF00 */
void boot_page(void);
/* Step P5 of docs/BOOT_SPEC.md (row BOOT-14): the cart chip's app start and app init (appinit.c) */
void app_start(void);
/* Step P5 of docs/BOOT_SPEC.md (row BOOT-09), only in builds without FW_MW (FW_MW = 1 builds the MegaWire code in
   core/mw): the MegaWire option status into $1FE6 bits 0-2 through the status helper (bootpage.c). With FW_MW the
   cart chip's MegaWire init, as core/mw has it, runs instead */
void boot_mw_status(void);
#if FW_S5
/* What a console Reset finds: the warm vector page, RAMDP $0000-$00FF = the boot page's vectors with the reset PC
   $00010100 (bootpage.c). RAMDP is the cart RAM that both the 68000 and the MCU see. In the FW_S5 build the
   level-1 interrupt handler (L1, core/sched) calls it on CAUSE.V, before the acknowledgement that lets the RTL
   release the 68000 */
void boot_warm_page(void);
#endif

#endif
