/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/s1_boot.h - the new core's Pocket start-up constants shared by s1_crt0.S, s1_trap.S and s1_board.c.
 *
 * The assembler cannot read pocket_map.h's C constants (their u suffixes), so the few that crt0 and the trap entry
 * need are written here without one (S1_A_*); s1_board.c static-asserts each against pocket_map.h. */
#ifndef S1_BOOT_H
#define S1_BOOT_H

#include "tdiag.h"

/* ---- S1_CACHE4B (test build 4b on): the first-boot unpack of the sound bank into the cache slot (boot/c4b.h) -- */
/* The S1_CACHE4B images (TEST and RELEASE; the name comes from test build 4b, the hardware test build that first
   carried them) unpack
   the cart's sound bank into the 1.38 MB sound-cache slot on a power-on without a good cache file and keep it there
   (docs/MCU_INTERFACE.md v1.3 21.1): crt0 calls the boot-cache stub (board/pocket/boot/boot_cache.c) before .data /
   .bss, which enters the WRAM boot overlay. They drive XLINK 0x40-0x48 and the CRAM, so they are v1.3 images: crt0
   refuses a v1.2 bitstream (on test build 4's, XLINK 0x40 would be XCFG) and a v1.3 one without the cache
   slot, the bar, the interim FIFOs and MD+ block they drive, or with a smaller IROM (MCU_INTERFACE.md 1, rule 2). The
   TEST image copies the boot's record to the debug save (s1_cache4b.c, version 8). The scheduler probe carries none
   of it (no XLINK on its rigs) and keeps accepting v1.2.
   The FW_S5 images (test build 5 on): the same boot cache, the overlay also writing the synth's output curve (c4b_ovl.c
   curve_write); crt0 then wants test build 5's blocks (the cache slot, the bar, the synth) and the 88 KB IROM
   (MCU_INTERFACE.md v1.3 21.3 item 1, 21.5), and the TEST image keeps the record in its FW_S5 debug save. */
#if !S1_PROBE
#define S1_CACHE4B              1
#else
#define S1_CACHE4B              0
#endif
#if !PPM_RELEASE && !S1_PROBE && !TDIAG_LEAN
#define S1_CACHE4B_REC          1               /* TEST: the record in the debug save (not
                                                   in the lean FW_S5 TEST images, core/trace/tdiag.h) */
#else
#define S1_CACHE4B_REC          0
#endif

/* ---- for the assembler (each == its pocket_map.h twin: s1_board.c) ------------------------------------------- */
#define S1_A_FIO_CTRL           0x01000000      /* POCKET_FIO_CTRL */
#define S1_A_CTRL_HOLD          1               /* POCKET_CTRL_HOLD */
#define S1_A_SYSINFO_CLK        0xFFFFFFE0      /* POCKET_SYSINFO_CLK; USER_CODE at +4 */
#define S1_A_IFACE_PI_MAJOR     0x504901        /* POCKET_IFACE_ID >> 8: 'P' 'I' major */
#if S1_CACHE4B
#define S1_A_IFACE_MINOR        0x03            /* POCKET_IFACE_ID & 0xFF: the oldest minor this firmware accepts (v1.3:
                                                   the cache slot and the bar, test builds 4a and 4b) */
#define S1_A_FIO_FEAT           0x0100005C      /* POCKET_FIO_FEAT (slot 23) */
#ifndef C4B_BUG
#define C4B_BUG                 0
#endif
#if FW_S5 && C4B_BUG != 16                      /* (C4B_BUG 16, planted: test build 4a's bits for an FW_S5
                                                   image) */
#define S1_A_FEAT_NEED          0x07            /* FW_S5 (test build 5 on): POCKET_FEAT_CACHE | BAR | SYNTH: what this
                                                   image drives (21.3 item 1; SYNTH = 1 means SFXFIFO = 0: no interim
                                                   FIFO / MD+ access) */
#define S1_A_FEAT_IROM_KB       88              /* the pocket88k layout: FEAT[23:16] must be at least this */
#else
#define S1_A_FEAT_NEED          0x1B            /* POCKET_FEAT_CACHE | BAR | SFXFIFO | MDP: what this image drives */
#define S1_A_FEAT_IROM_KB       72              /* the pocket72k layout: FEAT[23:16] must be at least this */
#endif
#else
#define S1_A_IFACE_MINOR        0x02            /* the oldest minor this firmware accepts (v1.2: the RTL sprite decoder;
                                                   v1.1 brought the VS counter): the probe uses no v1.3 word */
#endif
#define S1_A_IRQ_MEI            11              /* POCKET_IRQ_MEI */
#define S1_A_IRQ_MTI            7               /* POCKET_IRQ_MTI */
#define S1_A_IRQ_MSI            3               /* POCKET_IRQ_MSI */
#define S1_A_MIE_MEIE           0x800           /* POCKET_MIE_MEIE */
#define S1_A_MIE_MTIE           0x080           /* POCKET_MIE_MTIE */
#define S1_A_MIE_MSIE           0x008           /* POCKET_MIE_MSIE */

/* ---- the crt0 / boot record (.noinit: survives a firmware restart; the TEST debug save carries it) --------------- */
#define S1_REC_MAGIC            0x53314254      /* 'S1BT' */
#define S1_STOP_CLOCK           0xC1            /* SYSINFO_CLK != BRD_CLK_HZ: the 68000 stays held, the MCU stops */
#define S1_STOP_IFACE           0xC2            /* USER_CODE is not MCU interface v1.(>= our minor) */
#define S1_STOP_FEAT            0xC3            /* S1_CACHE4B (test builds 4a and 4b on): FEAT lacks a block this
                                                   image drives, or the IROM is
                                                   smaller than its layout (value = FEAT as read) */
#define S1_MS_CRT0              0x01            /* crt0 done, the board boot entered */
#define S1_MS_IRQ_ON            0x02            /* causes acknowledged, lines enabled, MIE on */
#define S1_MS_PAGE              0x03            /* the boot page, patches and header are in cart RAM (P3, P4) */
#define S1_MS_INTERIM           0x04            /* the 0.2.6 modules and the album are up (mdp_init returned) */
#define S1_MS_APPINIT           0x05            /* app start / app init and the MegaWire status are done (P5) */
#define S1_MS_RELEASED          0x06            /* the 68000 is released (P6, the last step) */
#define S1_MS_RELEASE_SLOW      0x07            /* the HOLD bit did not read back clear within the bound: released anyway */
#define S1_MS_CACHE4A           0x08            /* test build 4b, TEST: the boot cache's record taken (s1_cache4b.c,
                                                   after crt0's
                                                   stub and overlay ran; the record in the debug save's DBG_B_CACHE) */

/* TEST: crt0 fills the stack from its floor to its own frame with this word; the high-water mark is the lowest word
   that differs (FZ11: the word at the floor is never overwritten) */
#define S1_STACK_FILL           0x5AC3A55A

#ifndef __ASSEMBLER__
#include <stdint.h>
typedef struct {
    uint32_t magic;             /* S1_REC_MAGIC once a code was written */
    uint32_t code;              /* the last milestone (TEST) or the crt0 stop code (both variants) */
    uint32_t time;              /* brd_now() at that milestone (0 for a crt0 stop) */
    uint32_t value;             /* crt0 stop: the SYSINFO word that did not match */
} s1_boot_rec_t;
extern volatile s1_boot_rec_t s1_boot_rec;
void brd_boot(void) __attribute__((noreturn));
#endif

#endif
