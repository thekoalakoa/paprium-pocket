/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* core/mw/mw_text.c - the cart program's text, read from the player's ROM at run time (declared in mw.h).
 *
 * The MegaWire code reads strings from the cart program, which the cart's chip runs from its own flash at 0x08010000:
 * the MegaWire screen's lines, the access point's default name and, with a module, the AT commands and the HTTP text.
 * They are the cart's own bytes, so this tree never holds them (see docs/ALLOWLIST.md, row B49). The game's ROM carries
 * the cart program as one packed stream of type 0x81 at ROM offset 0x101A18: 91,440 bytes that unpack to 196,608. The
 * first time the MegaWire code needs the text, this file unpacks that stream from the ROM the player loaded into
 * MWTEXT, the area of CRAM set aside for it (CRAM is the Pocket's cellular RAM, a RAM chip our core maps for the MCU:
 * docs/MCU_INTERFACE.md 3.8), and then reads the bytes there at the chip's own addresses. CRAM keeps its contents over
 * every reset but a power-off; the unpacking and its check run again each boot. This is plumbing only: the cart's
 * chip has the program in its flash, and the Pocket rebuilds it from the ROM.
 *
 * The unpacking is done by the firmware's one 0x81 decoder, core/song/unpack81.c, through its checked entry
 * unpack81_checked. That decoder stays in IROM (the MCU's code memory inside the FPGA); this file belongs to the
 * MegaWire code, which runs from the Pocket's SRAM (the SRAM image), and calls it as an ordinary function. The checked
 * entry reads no byte past the stream and writes no byte past MWTEXT, and it refuses input that is not well formed,
 * because the player may load a ROM that is not the game's. The text is accepted only when the stream unpacks to
 * exactly 196,608 bytes using exactly its 91,439 body bytes; otherwise it is refused and the screen shows no lines.
 * One mw_text_run call does the whole stream; the screen calls it from its thread step, which is off every reply
 * path. */
#include <stdint.h>
#include "board.h"
#include "mw.h"
#include "unpack81.h"

#define MWT_ROM         0x101A18u       /* the stream's type byte in the game's ROM */
#define MWT_PACKED      91440u          /* its packed size: the type byte and the body, the end instruction included */

mw_txt_t mw_txt __attribute__((section(".sram_bss"), aligned(4)));

void mw_text_start(void)
{
    if (mw_txt.st != 0u)
        return;
    mw_txt.src = MWT_ROM + 1u;
    mw_txt.out = 0u;
    mw_txt.st = brd_flash8()[MWT_ROM] == 0x81u ? 1u : 3u;
}

uint32_t mw_text_run(uint32_t n)
{
    uint32_t used = 0u, got;
    (void)n;                            /* one call unpacks the whole stream */
    if (mw_txt.st == 1u) {
        got = unpack81_checked(brd_flash8() + MWT_ROM + 1u, MWT_PACKED - 1u, (uint8_t *)(uintptr_t)brd_mwtext(),
                               MW_TEXT_BYTES, &used);
        if (got == MW_TEXT_BYTES && used == MWT_PACKED - 1u) {
            mw_txt.src = MWT_ROM + MWT_PACKED;
            mw_txt.out = got;
            mw_txt.st = 2u;
        } else {
            mw_txt.st = 3u;
        }
    }
    return mw_txt.st >= 2u;             /* 1 once the text is accepted (2) or refused (3) */
}

uint32_t mw_text_ok(void) { return mw_txt.st == 2u; }

uint8_t mw_text8(uint32_t chip_addr) { return brd_mwtext()[(chip_addr - MW_TEXT_BASE) % MW_TEXT_BYTES]; }
