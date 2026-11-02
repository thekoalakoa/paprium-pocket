/* 
 * File:   appmain.h
 * Author: Igor
 *
 * Created on July 14, 2025, 8:19 PM
 */
/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */

#ifndef APPMAIN_H
#define	APPMAIN_H

#include <neorv32.h>
#include <string.h>
#include "cfg.h"
#include "mame.h"
#include "paprium.h"
#include "sfx.h"
#include "mdp.h"
#include "everdrive.h"

#if PPM_DEBUG_PRINTF
#define printf neorv32_uart_printf
#else
// 0.2.6 release: debug printf off (mame.h PPM_DEBUG_PRINTF). Not variadic-forwarding: the body is empty,
// so GCC inlines it away; the arguments are still evaluated, so no read with a side effect is lost.
static inline __attribute__((always_inline)) void ppm_printf_off(const char *format, ...) { (void) format; }
#define printf ppm_printf_off
#endif

void printHex(void *src, u32 size);

#endif	/* APPMAIN_H */

