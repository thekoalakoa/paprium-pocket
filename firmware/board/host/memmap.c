/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* Map host memory at the firmware's own peripheral addresses (cfg.h: ADDR_FPGIO 0x1000000 .. ADDR_FIFO 0x7800000),
 * so the real ppm_reset(), FPGAIO and ppmio pointers work unchanged on the host. Separate file: windows.h must not
 * meet cfg.h's #define bool/true/false. */
#include <windows.h>
int host_map(void)
{
    void *p = VirtualAlloc((void *) 0x1000000, 0x6900000, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    return p == (void *) 0x1000000;
}
