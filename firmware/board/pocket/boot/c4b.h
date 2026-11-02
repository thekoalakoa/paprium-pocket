/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/boot/c4b.h - the boot overlay of test build 4b: the first-boot unpack of the cart's sound bank into the
 * sound-cache slot (docs/MCU_INTERFACE.md v1.3 21.1 / 3.8 / 3.9; the firmware design's "Boot: WavPack unpack and the
 * save cache").
 * The name c4b (and the C4B_ prefix) comes from the hardware test build that first carried it. Section numbers below
 * (21.1, 3.8, ...) are those of docs/MCU_INTERFACE.md.
 *
 * Where it runs: the WRAM boot overlay, bitstream-initialised in wram_upper (0x80006C00-0x8000ABFF, 16 KB), linked on
 * its own (board/pocket/link/c4b_ovl.ld; tools/fwbuild.py builds it and mkimage.py places it in the WRAM image). The
 * IROM stub (boot_cache.c, called by crt0 BEFORE .data / .bss are made, 68000 held, interrupts off, no watchdog)
 * enters it only when XLINK CACHE.VALID = 0 and its header and CRC-32 are intact; crt0's .bss_upper clear then
 * overwrites it, so a later reset of the same power-on finds VALID = 1 (WARM) or, after a failed unpack, the overlay
 * gone (C4B_GONE: nothing done). Its scratch (the decoder's context, buffers, tables) is the start of wram_data, below
 * .noinit, which crt0 makes afresh right after (the build checks the bound). The result goes to c4b_rec (.noinit),
 * which the TEST image copies to the debug save (s1_cache4b.c, DBG_B_CACHE version 8).
 *
 * The flow (21.1; every path with the 68000 held):
 *   1. CACHE.VALID = 1: a reset inside the session or the Pocket's Quit / power-off reboot while it reads the file
 *      back: touch nothing (no CRAM traffic at all: the cache slot's rule) - C4B_WARM (the stub);
 *   2. else the loaded file is checked: CACHE_LOADED = the image size and XLINK LOST[31:16] = 0, then the header
 *      (magic, format, sizes, its CRC-32), the ROM key (the WavPack stream the game names: address, bytes, blocks and
 *      the CRC-32 of its block headers), then the bank as it sits in CRAM (each WavPack block's own CRC, the tail and
 *      the bank's CRC-32 against the header's) -> C4B_PASS, kept;
 *   3. else the bank is unpacked: core/wavpack from the ROM's stream into CRAM 0x100.., then the same content check
 *      over what CRAM holds (it proves the writes landed), then the header (written last, its magic word last of all),
 *      read back;
 *   4. on every non-warm boot the ROM's SFX bank is copied to CRAM 0x200000 (3.8; the synth reads this copy), BEFORE
 *      the CACHE write: a reset inside the copy then finds VALID = 0 and the overlay intact and copies it whole again,
 *      so a WARM boot never meets a half bank;
 *   5. only then, as this power-on's last store, CACHE := VALID | the image size (read back), so the Pocket writes the
 *      file back at the next Quit / power-off; a failed unpack or check sets nothing (no file is written; the next
 *      power-on unpacks again);
 *   6. the bar (XLINK BAR, 21.2) is lit only during an unpack (from its start through its check and the header) and
 *      put out before the SFX copy; the loaded file's check runs dark; EN = 0 again before the stub returns.
 * Where the bytes come from: the game's own C600 arguments, which the cart reads at C6. The MCU must know them before
 * the 68000 runs (the C6 poll gives up after 946 frames), so they are read from the same ROM words at power-on (the
 * game's pointers below). */
#ifndef C4B_H
#define C4B_H
#include <stdint.h>

/* ---- the cache image (3.8: CRAM byte i = file byte i; the image = HDR + BANK, any footer in HDR) ----------------- */
#define C4B_IMAGE_BYTES         0x152100u       /* == POCKET_CACHE_IMAGE_MAX */
#define C4B_HDR_BYTES           0x100u          /* == POCKET_CRAM_HDR_BYTES */
#define C4B_BANK_OFF            0x100u          /* CRAM byte of bank byte 0 */
#define C4B_BANK_BYTES          0x152000u       /* == POCKET_CRAM_BANK_BYTES == WVBANK_BYTES */
#define C4B_MAGIC0              0x52504150u     /* file bytes "PAPR" */
#define C4B_MAGIC1              0x31444E53u     /* file bytes "SND1" */
#define C4B_FORMAT              1u
#define C4B_MAXBLK              48u             /* WavPack blocks the header can list (the ROM's stream has 32) */
enum {                                          /* header words (index = byte offset / 4) */
    C4B_H_MAGIC0 = 0, C4B_H_MAGIC1, C4B_H_FORMAT, C4B_H_HDR_BYTES, C4B_H_IMAGE_BYTES, C4B_H_BANK_OFF, C4B_H_BANK_BYTES,
    C4B_H_SAMPLES,                              /* the samples the unpack returned (1,379,262) */
    C4B_H_STREAM,                               /* the ROM key: the stream's ROM address, its bytes, its blocks and the */
    C4B_H_STREAM_BYTES,                         /* CRC-32 of its block headers (32 bytes each) */
    C4B_H_BLOCKS,
    C4B_H_KEY,
    C4B_H_BANK_CRC,                             /* CRC-32 (IEEE 802.3) of the 0x152000 bank bytes */
    C4B_H_WRITER,                               /* the CRC-32 of the overlay that wrote it (informational) */
    C4B_H_BLKCRC,                               /* C4B_MAXBLK words: the ROM's WavPack block CRCs (informational: */
    C4B_H_CRC = C4B_H_BLKCRC + C4B_MAXBLK + 1u, /* the check reads the ROM's); then 1 reserved 0; the header's CRC-32 */
    C4B_H_WORDS                                 /* over words 0 .. C4B_H_CRC - 1 */
};
_Static_assert(C4B_H_CRC == 63u && C4B_H_WORDS * 4u == C4B_HDR_BYTES, "the 256-byte header");

/* ---- the game's pointers (ROM byte offsets; see above) ---------------------------------------------------------- */
#define C4B_ROM_TABLE_PTR       0x000AF77Cu     /* long: a0, the C600 argument table base */
#define C4B_A0_STREAM           0x774u          /* long at a0 + this: the WavPack stream */
#define C4B_A0_SFX_LO           0x778u          /* the SFX bank's start */
#define C4B_A0_SFX_HI           0x780u          /* its end */
#define C4B_SFX_ROOM            0x90000u        /* == POCKET_CRAM_SFXBANK_BYTES */

/* ---- the boot record (c4b_rec, .noinit; DBG_B_CACHE version 8 entry, 16 words) ---------------------------------- */
enum {                                          /* word 0 [7:0]: what this boot found and did */
    C4B_NONE = 0,
    C4B_WARM,                                   /* CACHE.VALID set at the start: nothing touched */
    C4B_FIRST,                                  /* no file (CACHE_LOADED 0): unpacked */
    C4B_PASS,                                   /* the file loaded whole and checked: kept */
    C4B_HDR,                                    /* the file's header wrong (magic, format, sizes or CRC; a probe file): unpacked */
    C4B_KEY,                                    /* the header right but made from another stream (the ROM key): unpacked */
    C4B_BANK,                                   /* the header right but the bank wrong (a block CRC, the tail or the CRC-32): unpacked */
    C4B_SIZE,                                   /* CACHE_LOADED not the image size (a short or longer file): unpacked */
    C4B_LOST,                                   /* CRAM writes lost while the file loaded (XLINK LOST[31:16]): unpacked */
    C4B_GONE,                                   /* CACHE.VALID 0 but the overlay overwritten (a reset after a failed unpack): nothing */
    C4B_NOROM                                   /* the game's pointers or the stream not as expected: nothing unpacked, no cache */
};
#define C4B_F_CACHE_SET         (1u << 8)       /* CACHE read back VALID | the image size after this boot's write */
#define C4B_F_UNPACKED          (1u << 9)       /* this boot unpacked the bank */
#define C4B_F_HDR_WRITTEN       (1u << 10)      /* ... and wrote the header (the unpack and its check passed) */
#define C4B_F_FAIL              (1u << 11)      /* the unpack or its check failed: no header, no CACHE (`why`) */
#define C4B_F_SFX               (1u << 12)      /* the SFX bank copied to CRAM */
#define C4B_F_BAR_OFF           (1u << 13)      /* BAR read back EN = 0 at the end */
#define C4B_F_BAR_SEEN          (1u << 14)      /* BAR's W read non-zero during the work (the video ran during the hold) */
#define C4B_F_CRCERR            (1u << 15)      /* the decoder counted WavPack block CRC errors (crc_errs) */
#define C4B_W_SHIFT             16u             /* word 0 [26:16]: the largest BAR W read */
#define C4B_F_CURVE             (1u << 27)      /* FW_S5 images (test build 5 on): the synth's output curve written to
                                                   CRAM CURVE (c4b_ovl.c curve_write, v1.3 3.8 / 3.10.6) */
enum {                                          /* `why` [7:0] for C4B_F_FAIL / C4B_NOROM (and [15:8] the wvbank code) */
    C4B_WHY_NONE = 0, C4B_WHY_PTR, C4B_WHY_STREAM, C4B_WHY_UNPACK, C4B_WHY_CHECK, C4B_WHY_HDR, C4B_WHY_CACHE
};
typedef struct {
    uint32_t kind;          /* [7:0] C4B_*, [15:8] C4B_F_*, [26:16] the largest BAR W read */
    uint32_t cache_in;      /* XLINK CACHE at the start */
    uint32_t loaded;        /* XLINK CACHE_LOADED at the start */
    uint32_t lost;          /* XLINK 0x18 at the start ([31:16] CRAM port-A writes lost in the load) */
    uint32_t bank_crc;      /* the CRC-32 of the bank as CRAM holds it at the end of this boot's check (0 if none ran) */
    uint32_t hdr_crc;       /* the loaded header's bank CRC-32 word (C4B_H_BANK_CRC), 0 with no file */
    uint32_t bad;           /* the check: [7:0] the first wrong block (0xFE the tail, 0xFF none), [15:8] blocks wrong,
                               [23:16] the header word that failed (C4B_H_*, 0xFF none), [31:24] `why` */
    uint32_t samples;       /* the samples the unpack decoded (or the header's, kept) */
    uint32_t crc_errs;      /* the decoder's WavPack CRC errors in the unpack ([31:16] the wvbank stop code) */
    uint32_t key;           /* the ROM key made at this boot (the CRC-32 of the stream's block headers) */
    uint32_t t_check;       /* TIMER cycles: the loaded file's check */
    uint32_t t_unpack;      /* the unpack */
    uint32_t t_verify;      /* the check after the unpack, the header write and its read-back */
    uint32_t t_sfx;         /* the SFX bank copy */
    uint32_t vs;            /* [15:0] VSCNT moves over the work (VDP syncs while held), [31:16] the stream's blocks */
    uint32_t stream;        /* the WavPack stream's ROM address the game's table gave */
} c4b_rec_t;
#define C4B_REC_WORDS           16u
_Static_assert(sizeof(c4b_rec_t) == 4u * C4B_REC_WORDS, "c4b_rec_t is 16 words");

/* ---- the overlay's header (the first 16 bytes at POCKET_WRAM_UPPER_LO; boot_cache.h boot_overlay_hdr) ------------- */
#define C4B_OVL_MAGIC           0x31564F50u     /* 'POV1' == BOOT_OVERLAY_MAGIC */
typedef void (*c4b_entry_t)(c4b_rec_t *rec);   /* the overlay's entry: fills rec, leaves BAR off */

#endif
