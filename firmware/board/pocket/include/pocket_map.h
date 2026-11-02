/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/include/pocket_map.h - the Pocket cart MCU's hardware interface, v1.3 (docs/MCU_INTERFACE.md): v1.0 plus
 * FPGAIO slot 16, the VS counter (v1.1, 2026-10-13), plus the RTL sprite decoder: the chip's decoder writes acted on in
 * the register file and FPGAIO slots 17-22 (v1.2, 2026-10-15, proposed: MCU_INTERFACE.md 4.9), plus the synth step
 * (v1.3, frozen 2026-10-21): FPGAIO slot 14 STAMP_A and slot 23 FEAT, CAUSE.BLK / CTRL.BLKIE, XLINK 0x40-0x48 (the
 * sound-cache slot and the first-boot bar), the CRAM die-0 map and the synth's region 0x06 (MCU_INTERFACE.md
 * 3.8-3.10, 4, 21). The TEST image of test build 4a, the first sound-cache build (board/pocket/s1_cache4a.c), is the
 * first v1.3 image; it uses the cache slot and the bar only.
 * A RELEASE image still accepts a v1.2 bitstream (s1_boot.h S1_A_IFACE_MINOR): it drives no v1.3 register.
 *
 * Board layer only. The chip-exact core (core/) never includes this file: it reaches the board through
 * board/board.h (tests/check_tree.py). The legacy 0.2.6 modules keep their own constants (board/pocket/cfg.h ADDR_*,
 * buddy/buddy.h BUD_*), moved in unchanged; they describe the 0.2.6 RTL, not this interface.
 *
 * tests/check_board.py checks this file:
 *   - the block between the two "Appendix A" markers equals docs/MCU_INTERFACE.md Appendix A, define for define
 *     (names, values and order);
 *   - every other constant against the tables of MCU_INTERFACE.md (memory map 3, FPGAIO 4, CTRL 4.1, CAUSE 4.2,
 *     option word 5, interrupt codes 2) and the layout constants against board/pocket/link/pocket72k.json;
 *   - board/board.h's interface constants (BRD_*) against the POCKET_* values here.
 * Marks in the banners below: [F] = frozen by MCU interface v1.0 (v1.1, v1.2 and v1.3 add, change nothing; v1.3
 * retires the interim rows as v1.0 announced them, FEAT says which a bitstream carries); [L] = the locked 0.3.0
 * layout (pocket72k.json, docs/LAYOUT.md). */
#ifndef POCKET_MAP_H
#define POCKET_MAP_H

/* ---- MCU_INTERFACE Appendix A (v1.3), verbatim: begin ------------------------------------------------------- */
/* MCU interface v1.3 (the first new-core firmware's lines plus the synth step's). SYSINFO USER_CODE =
   POCKET_IFACE_ID. Lines tagged v1.N arrived in v1.N; a v1.2 header holds exactly the untagged, v1.1 and v1.2 lines
   (tests/check_board.py). */
#define POCKET_IFACE_ID         0x50490103u   /* 'P' 'I' major 1 minor 3 */
#define POCKET_SYSINFO_CLK      0xFFFFFFE0u
#define POCKET_SYSINFO_USER     0xFFFFFFE4u

#define POCKET_FIO(slot)        (0x01000000u + 4u * (slot))   /* slot = addr[6:2] */
#define POCKET_FIO_CTRL         POCKET_FIO(0)    /* [0] HOLD, [3] RSTSEEN, [4] MENU_MUTE_EN, [5] OPT_AT_RESET_EN,
                                                    [14:8] LSTAT, [15] CAUSE.B; write byte 0 read-modify-write */
#define POCKET_FIO_SPTR         POCKET_FIO(2)
#define POCKET_FIO_VOL_SFX      POCKET_FIO(3)    /* interim */
#define POCKET_FIO_IRQCLR       POCKET_FIO(6)    /* legacy: bit 0 = ack CAUSE.B */
#define POCKET_FIO_GO           POCKET_FIO(7)    /* W: words [20:0], 0 = stop; R: {valid, 10'0, remaining[20:0]} */
#define POCKET_FIO_CAUSE        POCKET_FIO(8)    /* R: {V,S,A,B}; W1C */
#define POCKET_FIO_MSIP         POCKET_FIO(9)
#define POCKET_FIO_TIMER        POCKET_FIO(10)
#define POCKET_FIO_TCMP         POCKET_FIO(11)
#define POCKET_FIO_TCTRL        POCKET_FIO(12)   /* bit 0 TEN */
#define POCKET_FIO_STAMP_B      POCKET_FIO(13)
#define POCKET_FIO_STAMP_A      POCKET_FIO(14)   /* v1.3: R TIMER when CAUSE.A was last set (4.6) */
#define POCKET_FIO_WLOCK        POCKET_FIO(15)   /* bits 0-20 = WRAM KB 27-47, write 1 to set */
#define POCKET_FIO_VSCNT        POCKET_FIO(16)   /* v1.1: R {16'0, VDP vertical syncs since reset, wrapping} */
#define POCKET_FIO_DEC_BASE     POCKET_FIO(17)   /* v1.2: the decoder's next output base, workspace byte offset [20:0] */
#define POCKET_FIO_DEC_STAT     POCKET_FIO(18)   /* v1.2: R depth, run, flags; W 1 clears flags 16-21 */
#define POCKET_FIO_DEC_WORDS    POCKET_FIO(19)   /* v1.2: R words written since the last START */
#define POCKET_FIO_DEC_TIME     POCKET_FIO(20)   /* v1.2: R {valid, cycles START -> GO} */
#define POCKET_FIO_DEC_MARGIN   POCKET_FIO(21)   /* v1.2: R min (first window read - GO), signed; W resets */
#define POCKET_FIO_DEC_LATECNT  POCKET_FIO(22)   /* v1.2: R window words read ahead of the decode; W clears */
#define POCKET_FIO_FEAT         POCKET_FIO(23)   /* v1.3: R what this bitstream carries (4.10), constant */
#define POCKET_CTRL_HOLD        (1u << 0)
#define POCKET_CTRL_RSTSEEN     (1u << 3)
#define POCKET_CTRL_MENU_MUTE   (1u << 4)
#define POCKET_CTRL_OPT_AT_RST  (1u << 5)        /* built dormant (B Jam's decision of 2026-10-11, STAGE1_PLAN.md Q4) */
#define POCKET_CTRL_BLKIE       (1u << 6)        /* v1.3: CAUSE.BLK takes part in the MEI line */
#define POCKET_CAUSE_B          (1u << 0)
#define POCKET_CAUSE_A          (1u << 1)
#define POCKET_CAUSE_S          (1u << 2)
#define POCKET_CAUSE_V          (1u << 3)
#define POCKET_CAUSE_BLK        (1u << 4)        /* v1.3: the synth's BUSY fell (3.10.5); W1C */

#define POCKET_RAMDP_BV_BASE    0x02800000u      /* byte view, read-only */
#define POCKET_FLASH_BV_BASE    0x04800000u      /* byte view, read-only */
#define POCKET_FREG_BASE        0x0B000000u      /* + chip offset 0x00-0x1E; stored: 0x04, 0x06, 0x0A, 0x0C */

#define POCKET_OPT_MENU         (1u << 24)
#define POCKET_OPT_JAP          (1u << 25)
#define POCKET_OPT_PAL          (1u << 26)

/* ---- v1.3 (the synth step): FEAT bits (4.10) ---- */
#define POCKET_FEAT_CACHE       (1u << 0)        /* v1.3: the sound-cache slot, XLINK CACHE / CACHE_LOADED */
#define POCKET_FEAT_BAR         (1u << 1)        /* v1.3: the first-boot bar, XLINK BAR */
#define POCKET_FEAT_SYNTH       (1u << 2)        /* v1.3: region 0x06 = the synth (3.10); CAUSE.BLK live */
#define POCKET_FEAT_SFXFIFO     (1u << 3)        /* v1.3: region 0x06 = the interim audio_sfx FIFOs; VOL_SFX live */
#define POCKET_FEAT_MDP         (1u << 4)        /* v1.3: region 0x07 = the interim MD+ block / EverDrive stub */
#define POCKET_FEAT_ALBUM       (1u << 5)        /* v1.3: the interim album path (APF slot 300) */
#define POCKET_FEAT_GS3         (1u << 6)        /* v1.3: the virtual Grand Stick III (nothing MCU-visible) */
#define POCKET_FEAT_IROM_SHIFT  16u              /* v1.3: FEAT[23:16] = the IROM size in KB (72 or 88) */
#define POCKET_FEAT_IROM_MASK   0x00FF0000u      /* v1.3 */

/* ---- v1.3: XLINK 0x40-0x48, the sound-cache slot and the first-boot bar (3.9) ---- */
#define POCKET_XL(off)          (0x0A000000u + (off))   /* v1.3: XLINK decodes addr[6:2] */
#define POCKET_XL_CACHE         POCKET_XL(0x40)  /* v1.3: [31] VALID, [22:0] SIZE; power-on reset only, one-shot */
#define POCKET_XL_CACHE_LOADED  POCKET_XL(0x44)  /* v1.3: R bytes the Pocket loaded into the cache window */
#define POCKET_XL_BAR           POCKET_XL(0x48)  /* v1.3: [31] EN, [10:0] PX; R [26:16] W (active width) */
#define POCKET_CACHE_VALID      (1u << 31)       /* v1.3 */
#define POCKET_CACHE_SIZE_MASK  0x007FFFFFu      /* v1.3 */
#define POCKET_CACHE_IMAGE_MAX  0x152100u        /* v1.3: HDR + BANK (3.8) */
#define POCKET_CACHE_BRIDGE     0x60000000u      /* v1.3: the slot's APF bridge address (21.1) */
#define POCKET_BAR_EN           (1u << 31)       /* v1.3 */
#define POCKET_BAR_PX_MASK      0x000007FFu      /* v1.3 */
#define POCKET_BAR_W_SHIFT      16u              /* v1.3 */

/* ---- v1.3: the CRAM die-0 map (3.8): MCU address = 0x09000000 + CRAM byte ---- */
#define POCKET_CR(off)          (0x09000000u + (off))   /* v1.3 */
#define POCKET_CRAM_HDR         POCKET_CR(0x000000)     /* v1.3: the cache image's header */
#define POCKET_CRAM_HDR_BYTES   0x100u                  /* v1.3 */
#define POCKET_CRAM_BANK        POCKET_CR(0x000100)     /* v1.3: the wave bank */
#define POCKET_CRAM_BANK_BYTES  0x152000u               /* v1.3 */
#define POCKET_CRAM_BGMRING     POCKET_CR(0x152100)     /* v1.3: 256 x 40 x {L,R} */
#define POCKET_CRAM_BGMRING_BYTES 0xA000u               /* v1.3 */
#define POCKET_CRAM_SFXRING     POCKET_CR(0x15C100)     /* v1.3: 256 x 20 x {L,R} */
#define POCKET_CRAM_SFXRING_BYTES 0x5000u               /* v1.3 */
#define POCKET_CRAM_DACBUF_L    POCKET_CR(0x170000)     /* v1.3: 1,920 x u16 */
#define POCKET_CRAM_DACBUF_L_BYTES 0xF00u               /* v1.3 */
#define POCKET_CRAM_DACBUF_R    POCKET_CR(0x170F00)     /* v1.3: 1,920 x u16 */
#define POCKET_CRAM_DACBUF_R_BYTES 0xF00u               /* v1.3 */
#define POCKET_CRAM_CURVE_WIN   POCKET_CR(0x180000)     /* v1.3: the curve's window */
#define POCKET_CRAM_CURVE_WIN_BYTES 0x30000u            /* v1.3 */
#define POCKET_CRAM_CURVE       POCKET_CR(0x194000)     /* v1.3: the curve, 16,384 x u16 */
#define POCKET_CRAM_CURVE_CTR   POCKET_CR(0x198000)     /* v1.3: curve index 0 */
#define POCKET_CRAM_SFXBANK     POCKET_CR(0x200000)     /* v1.3: the SFX bank as 68000 words */
#define POCKET_CRAM_SFXBANK_BYTES 0x90000u              /* v1.3: reserved (552,748 B used) */
#define POCKET_CRAM_MODSTORE    POCKET_CR(0x300000)     /* v1.3: reserved fall-back for the decoded modules */
#define POCKET_CRAM_MODSTORE_BYTES 0xC0000u             /* v1.3 */

/* ---- v1.3: the synth, region 0x06 (3.10; FEAT.SYNTH) ---- */
#define POCKET_SYN(off)         (0x06000000u + (off))   /* v1.3: addr[11:2] decoded */
#define POCKET_SYN_ID           POCKET_SYN(0x000)       /* v1.3: R 0x53350001 */
#define POCKET_SYN_CONFIG       POCKET_SYN(0x004)       /* v1.3: [1:0] MODE, [2] PAL, [3] DTWIN, [31:16] SEQ */
#define POCKET_SYN_FLAGS        POCKET_SYN(0x008)       /* v1.3 */
#define POCKET_SYN_WMASTER      POCKET_SYN(0x00C)       /* v1.3 */
#define POCKET_SYN_WBOOST       POCKET_SYN(0x010)       /* v1.3 */
#define POCKET_SYN_SMASTER      POCKET_SYN(0x014)       /* v1.3 */
#define POCKET_SYN_SMCFG        POCKET_SYN(0x018)       /* v1.3 */
#define POCKET_SYN_ECHOB        POCKET_SYN(0x01C)       /* v1.3: [15:0] GAIN, [23:16] DELAY, [31:24] INDEX */
#define POCKET_SYN_ECHOS        POCKET_SYN(0x020)       /* v1.3 */
#define POCKET_SYN_ARM          POCKET_SYN(0x024)       /* v1.3: W bit 0 = frame_pending */
#define POCKET_SYN_SEQ          POCKET_SYN(0x028)       /* v1.3: R [15:0] ARR, [31:16] DONE */
#define POCKET_SYN_DONE         POCKET_SYN(0x02C)       /* v1.3: W DONE (synth_end) */
#define POCKET_SYN_STATUS       POCKET_SYN(0x030)       /* v1.3 */
#define POCKET_SYN_PHASE        POCKET_SYN(0x034)       /* v1.3: TEST only */
#define POCKET_SYN_YMFILT       POCKET_SYN(0x038)       /* v1.3 */
#define POCKET_SYN_DTOUT        POCKET_SYN(0x03C)       /* v1.3: [15:0] GAIN Q8.8, [16] INVERT, [20:17] DCK */
#define POCKET_SYN_DIAG         POCKET_SYN(0x040)       /* v1.3 */
#define POCKET_SYN_TIMEOUT      POCKET_SYN(0x044)       /* v1.3 */
#define POCKET_SYN_SEQLAT       POCKET_SYN(0x048)       /* v1.3: R [15:0] last B arrival, [31:16] last A */
#define POCKET_SYN_SCHED        POCKET_SYN(0x04C)       /* v1.3: R [7:0] CNT, [11:8] NBLK, [31:16] HALF */
#define POCKET_SYN_ID_VALUE     0x53350001u             /* v1.3 */
#define POCKET_SYN_MODE_DT      1u                      /* v1.3: CONFIG.MODE */
#define POCKET_SYN_MODE_YM      2u                      /* v1.3 */
#define POCKET_SYN_CFG_PAL      (1u << 2)               /* v1.3 */
#define POCKET_SYN_CFG_DTWIN    (1u << 3)               /* v1.3 */
#define POCKET_SYN_CFG_SEQ_SHIFT 16u                    /* v1.3 */
#define POCKET_SYN_FL_SEQON     (1u << 0)               /* v1.3: FLAGS */
#define POCKET_SYN_FL_PLAYING   (1u << 1)               /* v1.3 */
#define POCKET_SYN_FL_SFXON     (1u << 2)               /* v1.3 */
#define POCKET_SYN_FL_BGMECHO   (1u << 3)               /* v1.3 */
#define POCKET_SYN_FL_SFXECHO   (1u << 4)               /* v1.3 */
#define POCKET_SYN_FL_LEVELNZ   (1u << 5)               /* v1.3 */
#define POCKET_SYN_ST_BUSY      (1u << 0)               /* v1.3: STATUS */
#define POCKET_SYN_ST_RUN       (1u << 1)               /* v1.3 */
#define POCKET_SYN_VOICE(v)     POCKET_SYN(0x400u + 0x40u * (v))   /* v1.3: v = 0..15 = the chip's voice 10 + v */
#define POCKET_SYN_SFX(c)       POCKET_SYN(0x800u + 0x40u * (c))   /* v1.3: c = 0..7 */
#define POCKET_SV_POS           0x00u            /* v1.3: VOICE field offsets (3.10.3) */
#define POCKET_SV_LEN           0x04u            /* v1.3 */
#define POCKET_SV_LOOP          0x08u            /* v1.3 */
#define POCKET_SV_BASE          0x0Cu            /* v1.3 */
#define POCKET_SV_STEP          0x10u            /* v1.3 */
#define POCKET_SV_DECLICK       0x12u            /* v1.3 */
#define POCKET_SV_GAIN_L        0x14u            /* v1.3 */
#define POCKET_SV_GAIN_R        0x16u            /* v1.3 */
#define POCKET_SV_LAST_L        0x18u            /* v1.3 */
#define POCKET_SV_LAST_R        0x1Au            /* v1.3 */
#define POCKET_SV_ENV_LEVEL     0x1Cu            /* v1.3 */
#define POCKET_SV_ENV_CNT       0x1Eu            /* v1.3 */
#define POCKET_SV_ENV_STATE     0x20u            /* v1.3: u8 */
#define POCKET_SV_BB            0x21u            /* v1.3: u8 */
#define POCKET_SV_MUTE          0x22u            /* v1.3 */
#define POCKET_SV_AR            0x24u            /* v1.3: u8 x 7: AR HOLD DR SL SUS D2R RR */
#define POCKET_SV_HOLD          0x25u            /* v1.3 */
#define POCKET_SV_DR            0x26u            /* v1.3 */
#define POCKET_SV_SL            0x27u            /* v1.3 */
#define POCKET_SV_SUS           0x28u            /* v1.3 */
#define POCKET_SV_D2R           0x29u            /* v1.3 */
#define POCKET_SV_RR            0x2Au            /* v1.3 */
#define POCKET_SV_COMPAND       0x2Bu            /* v1.3: u8, always 0 */
#define POCKET_SS_PTR           0x00u            /* v1.3: SFX field offsets (3.10.4) */
#define POCKET_SS_BASE          0x04u            /* v1.3 */
#define POCKET_SS_POS           0x08u            /* v1.3 */
#define POCKET_SS_LEN           0x0Cu            /* v1.3 */
#define POCKET_SS_FORMAT        0x10u            /* v1.3: u8 */
#define POCKET_SS_RATE          0x11u            /* v1.3: u8 */
#define POCKET_SS_ID            0x12u            /* v1.3 */
#define POCKET_SS_GAIN_L        0x14u            /* v1.3 */
#define POCKET_SS_GAIN_R        0x16u            /* v1.3 */
#define POCKET_SS_LOOP          0x18u            /* v1.3: u8 */
#define POCKET_SS_FILT          0x19u            /* v1.3: u8 */
#define POCKET_SS_Y             0x1Au            /* v1.3 */
#define POCKET_SS_DELAY         0x1Cu            /* v1.3 */
/* ---- MCU_INTERFACE Appendix A (v1.3), verbatim: end --------------------------------------------------------- */

/* ---- bus regions: an 8-bit decode on addr[31:24] (MCU_INTERFACE.md 3) [F] ----------------------------------- */
#define POCKET_IROM_BASE        0x00000000u   /* 72 KB, read-only: fetch 4, load 10 cycles */
#define POCKET_FPGAIO_BASE      0x01000000u   /* 32 slots of 4 B on addr[6:2] (section 4) */
#define POCKET_RAMDP_BASE       0x02000000u   /* the 68000's cart RAM $0000-$1FFF: MCU halfword at +A = 68000 word A */
#define POCKET_RAMDP_BYTES      0x2000u       /* 8 KB; $1FE0-$1FFF are MCU-only cells the 68000 never sees in v1.0 */
#define POCKET_SDRAM_BASE       0x03000000u   /* SDRAM workspace (port 2), byte-native */
#define POCKET_SDRAM_BYTES      0x200000u     /* 2 MB */
#define POCKET_FLASH_BASE       0x04000000u   /* flash word view: the 8 MB ROM image, halfword at A = 68000 word A */
#define POCKET_FLASH_BYTES      0x800000u
#define POCKET_BRAM_BASE        0x05000000u   /* battery save, byte lanes (read-modify-write) */
#define POCKET_BRAM_BYTES       0x2000u       /* 8 KB like the cart's EEPROM (docs/STAGE1_PLAN.md question Q1;
                                                 B Jam's decision of 2026-10-11) */
#define POCKET_SFX_BASE         0x06000000u   /* audio_sfx FIFOs (interim: FEAT.SFXFIFO, test builds 4 and 4a, the
                                                 fast-path and first sound-cache builds; v1.3: the synth on the synth
                                                 fit, FEAT.SYNTH, POCKET_SYN above) */
#define POCKET_MDP_BASE         0x07000000u   /* MD+ block (interim: FEAT.MDP, the same builds; gone from the synth
                                                 fit) */
#define POCKET_EDFIFO_BASE      0x07800000u   /* EverDrive FIFO stub (interim, as the MD+ block) */
#define POCKET_SRAM_BASE        0x08000000u   /* Pocket SRAM 256 KB (xram), run in place allowed */
#define POCKET_SRAM_BYTES       0x40000u
#define POCKET_CRAM_BASE        0x09000000u   /* CRAM die 0, words 0x000000-0x1FFFFF (v1.3: the 3.8 map, POCKET_CR above) */
#define POCKET_CRAM_MWTEXT      POCKET_CR(0x1B0000)   /* FW_MW (test build S3b on), firmware only (3.8, not in Appendix
                                                         A): the cart program 0x08010000-0x0803FFFF, unpacked from the
                                                         player's ROM for the MegaWire code */
#define POCKET_CRAM_MWTEXT_BYTES 0x30000u
#define POCKET_XLINK_BASE       0x0A000000u   /* XLINK register block (XCFG, ID, buddy option D; v1.3: 0x40-0x48 above) */
#define POCKET_WRAM_BASE        0x80000000u   /* WRAM 48 KB, byte lanes */
#define POCKET_NEORV32_IO_BASE  0xFFFFFF80u   /* NEORV32 internal IO: GPIO and SYSINFO only in v1.0 */

/* ---- FPGAIO slots not in Appendix A (MCU_INTERFACE.md 4) [F] ----------------------------------------------- */
#define POCKET_FIO_SLOTS        32u           /* addr[6:2]; slot 16 VSCNT (v1.1); 17-22 the decoder (v1.2); 14 STAMP_A and
                                                23 FEAT (v1.3); 24-31 reserved for v1.x */
#define POCKET_FIO_TIME_RETIRED POCKET_FIO(1) /* the 0.2.6 ms counter: retired, reads 0xFFFFFFFF; never use */
#define POCKET_FIO_VOL_BGM      POCKET_FIO(4) /* interim: no RTL consumer */
#define POCKET_FIO_DIAG         POCKET_FIO(5) /* stream count in a diagnostic RTL variant only */
#define POCKET_FIO_UNUSED_READ  0xFFFFFFFFu   /* what a retired, reserved or write-only slot reads (a v1.0-v1.2 board's
                                                 slot 23: no FEAT there, MCU_INTERFACE.md 4.10) */
#define POCKET_FEAT_CARD4A      0x0048001Bu   /* v1.3: the FEAT of the first sound-cache build, test build 4a
                                                 (4.10, 21.5; built by the cache-slot RTL item): CACHE, BAR, SFXFIFO,
                                                 MDP, IROM 72 KB */
#define POCKET_FEAT_CARD5       0x00580047u   /* v1.3: the FEAT of the synth fit, test build 5 (4.10, 21.5):
                                                 CACHE, BAR, SYNTH, GS3, IROM 88 KB */

/* ---- XLINK words not in Appendix A (MCU_INTERFACE.md 3.9) --------------------------------------------------- */
#define POCKET_XL_LOST          POCKET_XL(0x18)   /* [31:16] CRAM port-A writes lost (v1.3: the cache load's, 3.9),
                                                     [15:0] SRAM loader words lost; power-on counters */
#define POCKET_XL_LOST_CRAM_SHIFT 16u
#define POCKET_XL_LOST_SRAM_MASK  0x0000FFFFu
#define POCKET_XL_XCFG          POCKET_XL(0x00)   /* [3:0] SRAM read wait, [7:4] WE# low, [11:8] CRAM wait, [16] the
                                                     SRAM image lock (MCU stores below SRAM 0x10000 dropped); plain rw,
                                                     power-on reset only: keep bit 16 by read-modify-write (3.7) */
#define POCKET_XCFG_LOCK        (1u << 16)
#define POCKET_XL_LOADED        POCKET_XL(0x0C)   /* SRAM halfwords the APF loader wrote since power-up (3.7) */
#define POCKET_SRAM_BASE        0x08000000u       /* region 0x08: the Pocket SRAM (3.7) */
#define POCKET_SRAM_IMG_MAX     0x00010000u       /* the image area 0x00000-0x0FFFF (the lock's range) */
#define POCKET_BAR_W_MASK       0x000007FFu   /* BAR read [26:16] W: the active width (0 before the first line) */
#define POCKET_GO_WORDS_MASK    0x001FFFFFu   /* GO / remaining: 21 bits */
#define POCKET_GO_VALID         (1u << 31)    /* GO read-back: stream valid */
#define POCKET_SPTR_MASK        0x001FFFFFu   /* SPTR: 21-bit byte offset into the workspace */
#define POCKET_CTRL_LSTAT_SHIFT 8u            /* CTRL read [14:8] = XLINK LSTAT[6:0] */
#define POCKET_CTRL_CAUSE_B_RD  (1u << 15)    /* CTRL read bit 15 = CAUSE.B mirror */
#define POCKET_CTRL_RESET       0x09u         /* CTRL on every reset: HOLD | RSTSEEN */
#define POCKET_TCTRL_TEN        (1u << 0)
#define POCKET_MSIP_BIT         (1u << 0)
#define POCKET_IRQCLR_B         (1u << 0)
#define POCKET_WLOCK_KB_FIRST   27u           /* WLOCK bit k locks WRAM KB 27 + k */
#define POCKET_WLOCK_KB_LAST    47u
#define POCKET_VSCNT_MASK       0x0000FFFFu   /* VSCNT: 16 bits, wraps every 65,536 frames (18.2 min NTSC) */
#define POCKET_DEC_BASE_MASK    0x001FFFFEu   /* DEC_BASE: an even byte offset into the workspace (v1.2) */
#define POCKET_DEC_STAT_FLAGS   0x003F0000u   /* DEC_STAT bits 16-21: OVF, BADTYPE, D0, PRE, LATE, ABORT (W1 clears) */
#define POCKET_DEC_MARGIN_RESET 0x7FFFFFFFu   /* DEC_MARGIN at reset and after a write */

/* ---- cart register file, MCU side: chip offsets (MCU_INTERFACE.md 3.4) [F] ---------------------------------- */
#define POCKET_FREG_FE4         0x04u   /* $1FE4 control word: stored; the 68000 reads the composer instead */
#define POCKET_FREG_FE6         0x06u   /* $1FE6 status: stored */
#define POCKET_FREG_FE8         0x08u   /* $1FE8 window: acts on write, reads 0 */
#define POCKET_FREG_FEA         0x0Au   /* $1FEA mailbox B: stored */
#define POCKET_FREG_FEC         0x0Cu   /* $1FEC mailbox A: stored */
#define POCKET_FREG_FEE         0x0Eu   /* $1FEE: acts on write, reads 0 */
#define POCKET_FREG_FF0         0x10u   /* $1FF0 FIFO-A target: dropped (firmware shadow) */
#define POCKET_FREG_FF2         0x12u   /* $1FF2 stream control: acts on write (v1.2: decoder START / STOP), reads 0 */
#define POCKET_FREG_FF4         0x14u   /* $1FF4 queue high: latched by the RTL decoder (v1.2), reads 0 */
#define POCKET_FREG_FF6         0x16u   /* $1FF6 queue low / clear: the RTL decoder's push / clear (v1.2), reads 0 */
#define POCKET_FREG_SPAN        0x20u   /* offsets 0x00-0x1E */

/* ---- option word: NEORV32 GPIO input (MCU_INTERFACE.md 5) [F] ------------------------------------------------ */
#define POCKET_GPIO_INPUT       0xFFFFFF80u
#define POCKET_GPIO_OUTPUT      0xFFFFFF84u
#define POCKET_OPT_MODEL_MASK   0x00000740u   /* bits 6, 8-10: the $1FE4 model bits */
#define POCKET_OPT_MW_MASK      0x00070000u   /* bits 16-18: MegaWire option, three copies (7 = On) */
#define POCKET_OPT_MW_SHIFT     16u

/* ---- NEORV32 1.4.8.1 interrupts (MCU_INTERFACE.md 2, 6.1) [F] ------------------------------------------------ */
/* mcause interrupt codes (bit 31 set) and mie enable bits; priority MEI > MTI > MSI */
#define POCKET_MCAUSE_IRQ       0x80000000u
#define POCKET_IRQ_MEI          11u     /* L1: CAUSE OR (mailbox B, mailbox A, SEND, V) */
#define POCKET_IRQ_MTI          7u      /* L2a: TEN and TIMER >= TCMP (signed, within half the wrap) */
#define POCKET_IRQ_MSI          3u      /* L2b: MSIP */
#define POCKET_MIE_MEIE         (1u << POCKET_IRQ_MEI)
#define POCKET_MIE_MTIE         (1u << POCKET_IRQ_MTI)
#define POCKET_MIE_MSIE         (1u << POCKET_IRQ_MSI)
#define POCKET_MSTATUS_MIE      (1u << 3)
/* Removed in v1.0 (MTIME, UART, WDT): a load or store there gets no ack and ends in a bus-timeout access fault.
   The new-core firmware holds no such access (tests/check_board.py scans the s1 sources). */
#define POCKET_REMOVED_IO_LO    0xFFFFFF8Cu   /* WDT 0xFFFFFF8C, MTIME 0xFFFFFF90-9C, UART 0xFFFFFFA0-A4 */
#define POCKET_REMOVED_IO_HI    0xFFFFFFA8u

/* ---- 0.3.0 memory layout pocket72k [L] (must agree with board/pocket/link/pocket72k.json) -------------------- */
#define POCKET_IROM_BYTES       0x12000u      /* 72 KB: rom0 32 KB + extension 40 KB (select addr[16] | addr[15]) */
#define POCKET88_IROM_BYTES     0x16000u      /* the FW_S5 layout pocket88k (pocket88k.json): 88 KB = rom0 32 KB +
                                                 extension 56 KB (MCU_INTERFACE.md v1.3 3.1); the rest of the map as
                                                 above */
#define POCKET_IROM_LO_END      0x5360u       /* firmware 0x0000-0x535F */
#define POCKET_BRAIN_LO         0x5360u       /* brain 0x5360-0xD2EB, bytes unchanged */
#define POCKET_BRAIN_HI         0xD2ECu
#define POCKET_IROM_HI_END      0x12000u      /* firmware 0xD2EC-0x11FFF */
#define POCKET_WRAM_BYTES       0xC000u       /* 48 KB */
#define POCKET_WRAM_DATA_END    0x80001820u   /* hot data 0x0000-0x181F */
#define POCKET_BRAIN_DATA_LO    0x80001820u   /* buddy data 0x1820-0x2ABF (the brain's) */
#define POCKET_WRAM_SCHED_LO    0x80002AC0u   /* not-cleared lists / scheduler 0x2AC0-0x2BFF */
#define POCKET_WCODE_LO         0x80002C00u   /* locked code window 0x2C00-0x6BFF (constant lock, KB 11-26) */
#define POCKET_WCODE_HI         0x80006C00u
#define POCKET_WRAM_UPPER_LO    0x80006C00u   /* upper data 0x6C00-0xABFF (WLOCK-able, KB 27-42) */
#define POCKET_STACK_LO         0x8000AC00u   /* stack 0xAC00-0xBFFF (KB 43-47: WLOCK must leave it 0) */
#define POCKET_STACK_TOP        0x8000C000u

#endif
