/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */
/* board/host/appmain.h - HOST board header, in place of board/pocket/appmain.h.
 *
 * The firmware sources #include "appmain.h"; the host build puts board/host first on the include path, so they get
 * this file instead of the Pocket one. Same includes as the Pocket header (cfg.h, mame.h, paprium.h, sfx.h, mdp.h,
 * everdrive.h), minus <neorv32.h>: the few NEORV32 names the shared sources use come from host_neorv32.h, and the
 * RISC-V inline-assembly templates they contain are assembled by host_rv_asm.h's x86 macros. ADDR_* stay the
 * firmware's own constants (board/pocket/cfg.h); memmap.c maps host memory at those addresses, so ppm_reset(),
 * FPGAIO and ppmio run unmodified. Derived from the matching header of our comparison harness (not in this
 * repository). */
#ifndef APPMAIN_H
#define APPMAIN_H
#include "host_rv_asm.h"
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdarg.h>
#include "host_neorv32.h"
#include "cfg.h"
#include "mame.h"
#include "paprium.h"
#include "sfx.h"
#include "mdp.h"
#include "everdrive.h"

int host_printf(const char *fmt, ...);
#if PPM_DEBUG_PRINTF
#define printf host_printf
#else
/* the RELEASE rule of board/pocket/appmain.h: printf compiles to nothing, arguments still evaluated */
static inline __attribute__((always_inline)) void ppm_printf_off(const char *format, ...) { (void) format; }
#define printf ppm_printf_off
#endif
#define neorv32_uart_printf host_printf
void printHex(void *src, u32 size);
#endif
