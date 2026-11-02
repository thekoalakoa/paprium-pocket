/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/boot/bootpage.c - what the cart's bootloader and FPGA leave in cart RAM before the 68000 runs (docs/BOOT_SPEC.md
 * steps P3 and P4: rows BOOT-04 to BOOT-06; step P5: row BOOT-09; row BOOT-07 was dropped on 2026-10-16).
 *
 * Board-independent (board.h only): the Pocket and the host board run the same steps, before app_start and with the
 * 68000 held. The constants are the decided rows of docs/BOOT_SPEC.md (the boot-page patches: docs/ALLOWLIST.md, row
 * B3; the header word $1E4 = $FF00: docs/BOOT_SPEC.md, row AL-06). None of these constants is a ROM byte; the page
 * itself is read from the ROM image at boot. The BOOT-nn names in the comments below are rows of docs/BOOT_SPEC.md. */
#include <stdint.h>
#include "board.h"
#include "disp.h"
#include "appinit.h"

/* The hold-B line ($9725C: the 4 hex digits of ROM $1000A, the letters at $1E0-$1E2, a fixed four-character text
   from the game code, then a space for
   $1E4 = $FF00) shows the ROM file's own digits and letters: the page copy leaves $1E0-$1E3 as the ROM has them. The
   letters belong to the cart, not the console. This was measured: B Jam's pink US cart prints the ROM header's region
   letters unchanged in a US CDX and in a Japanese LaserActive alike. So the firmware has no letter switch per console
   region any more (B Jam's decision of 2026-10-16: row BOOT-07 dropped). */

void boot_page(void)
{
    volatile uint16_t *ram = brd_cart_ram();
    volatile uint16_t *rom = brd_rom();
    uint32_t i;
    for (i = 0; i < (BRD_CART_RAM_USER_END >> 1); i++)      /* BOOT-04: ROM $0000-$1FDF, 8,160 B; $1FE0-$1FFF is the */
        ram[i] = rom[i];                                    /* register file and is never written here */
    ram[0x1D1Cu >> 1] = 0x0004u;                            /* BOOT-05 (a boot-page patch): 'SE' read -> $C00004 */
    ram[0x1D2Cu >> 1] = (uint16_t)(ram[0x1D2Cu >> 1] | 0x0100u);   /* the test inverted: passes on the first try */
    ram[0x1562u >> 1] = 0x0001u;                            /* the post-splash jump -> $10100 */
    ram[0x1564u >> 1] = 0x0100u;
    rom[0x81104u >> 1] = 0x4E71u;                           /* the emulator check -> nop (the ROM image; idempotent) */
    ram[0x01E4u >> 1] = 0xFF00u;                            /* BOOT-06: the hold-B line ends in a space */
}

/* What a console Reset finds. The cart chip only acknowledges EXTI13, its console-reset interrupt (disp.c
   disp_console_reset). What serves the 68000's vectors after a console Reset on the real cart (its FPGA, its
   bootloader or the $200000 stub) is not known, so this builds the one variant that reproduces every Reset we
   captured, and the GPGX emulator's "warm" reset run: RAMDP $0000-$00FF = the boot page's own vector table, with the
   reset PC = $00010100 (the game's entry, the address the post-splash jump goes to), and the rest of RAMDP
   ($0100-$1FDF: the game's data, and the stamps command F5 writes during a zoom) and work RAM left as they are. RAMDP
   is the cart RAM that both the 68000 and the MCU see. The RTL holds the 68000 in reset until CAUSE.V is
   acknowledged, so the board writes this page first (the level-1 interrupt handler L1 in core/sched). Whether the
   game then locks up ($80B78 before its first entry, stamp data under the boot vectors during a zoom) or restarts at
   the NX terminal follows from that state alone. The 810E and C600 posts that follow are handled as the cart chip
   handles them: the board answers none of them. Only in the FW_S5 build (the full firmware, on MCU interface v1.3):
   its RTL is the one that holds the 68000 for this. */
#if FW_S5
void boot_warm_page(void)
{
    volatile uint16_t *ram = brd_cart_ram();
    volatile uint16_t *rom = brd_rom();
    uint32_t i;
    for (i = 0; i < (0x0100u >> 1); i++)                   /* vectors 0-63: the boot page's (ROM $0000-$00FF) */
        ram[i] = rom[i];
    ram[0x0004u >> 1] = 0x0001u;                            /* the reset PC: $00010100 */
    ram[0x0006u >> 1] = 0x0100u;
}
#endif

void boot_mw_status(void)
{
    uint16_t mw = (uint16_t)((brd_options() & BRD_OPT_MW_MASK) >> BRD_OPT_MW_SHIFT);   /* 7 = On, 0 = Off */
    if (mw)
        st_set(1u, ST_FE6, mw);                             /* the shadow keeps them for every later status write */
}
