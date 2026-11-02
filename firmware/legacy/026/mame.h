
// baswed on https://github.com/TheHpman/mame/blob/master/src/devices/bus/megadrive/rom.cpp
/* 
 * File:   mame.h
 * Author: Igor
 *
 * Created on July 19, 2025, 12:11 PM
 */
/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */
// Terms in this file's notes: FW_S1 is defined only when the s1 images are built (the new 0.3.0 firmware,
// tools/fwbuild.py s1). D02, D06 and the other D numbers name the differences between this 0.2.6 code and the cart's
// chip that our own study of how the cart behaves listed. MCU = the cart's NEORV32 soft CPU in the core; RAMDP = the
// cart RAM that both the 68000 and the cart chip (here the MCU) see; SAT = the sprite attribute table.

#ifndef MAME_H
#define	MAME_H

typedef struct {
    vu16 autoinc;
    vu16 lenH;
    vu16 lenL;
    vu16 srcH;
    vu16 srcM;
    vu16 srcL;
    vu16 cmdH;
    vu16 cmdL;
} ppm_dma_cmd;

typedef struct { //VDP specs
    vu16 posY;
    vu16 sizeNext;
    vu16 attrs;
    vu16 posX;
} ppm_sat_item;

typedef struct {
    vu16 anim;
    vu16 nextAnim;
    vu16 objID; //b15 = fresh assign ?
    vu16 field_6;
    vu16 attrs;
    vu16 animCounter;
    vu16 posX;
    vu16 posY;
} ppm_intf_obj;

typedef struct {
    u16 vectors[0x80]; //0x000 68k vectors table
    u16 rom_hdr[0x80]; //0x100 megadrive header data
    u16 scaling_buff[0x300]; //0x200
    u16 save_buff[0x100]; //0x800 also part of scaling data
    u16 _pad1[0x80]; //0xa00
    ppm_sat_item sat_data[144];//0xb00 // sprite allocation table sits here
    ppm_intf_obj obj_data[64]; // objects table
    u16 _pad2[0x40];
    // 0x1400
    ppm_dma_cmd dma_cmd[121];
    u16 audio_data[0x70 / 2];
    u16 net_data[0x108];

    union {
        u16 cmd_args[128];
        u32 cmd_args_long[64];
    };

    vu16 dma_total; // total size in words
    vu16 dma_budget; // per frame budget (depends on system)
    vu16 dma_remaining; // remaining budget for current frame
    vu16 dma_cmd_count;
    vu16 sat_count; // # of items present in SAT table
    vu16 unk_1f1a;
    vu16 unk_1f1c;
    vu16 unk_1f1e;
    vu16 buff[0x60];
    // main registers
    u16 reg_unk0; // 1fe0
    u16 reg_unk1; // 1fe2
    vu16 reg_status_1; // 1fe4

    struct {

        union {
            vu16 word;

            struct {
                vu16 mwire_status : 3;
                vu16 bit_3 : 1;
                // sub_9B738
                vu16 bit_4 : 1; // MW? send a900 if set
                vu16 mwire_data_in : 1; // MW ack ?
                vu16 bit_6 : 1;
                vu16 bit_7 : 1;

                vu16 eep_error1 : 1; // b8 sum error?
                vu16 eep_error2 : 1; // b9 eepr error?
                vu16 bit_10 : 1;
                vu16 bit_11 : 1;

                vu16 bit_12 : 1;
                vu16 bit_13 : 1;
                vu16 busy : 1; // b14 task busy
                vu16 bit_15 : 1;
            } bits;
        };
    } reg_status_2; // 1fe6

    u16 reg_unk4; // 1fe8
    vu16 reg_cmd; //0x1fea
    u16 reg_wdog; // unconfirmed
    u16 reg_unk_1fee; // 1fee
    u16 reg_unk_1ff0; // 1ff0
    u16 reg_unk_1ff2; // 1ff2
    u16 reg_unk_1ff4; // 1ff4
    u16 reg_unk_1ff6; // 1ff6
    u16 reg_unk_1ff8; // 1ff8
    u16 reg_unk_1ffa; // 1ffa
    u16 reg_unk_1ffc; // 1ffc
    u16 reg_unk_1ffe; // 1ffe

} ppm_ramdp;

typedef struct {
    uint16_t block_num;
    uint16_t usage;
    uint16_t age;
} ppm_vram_slot;

typedef struct {
    uint32_t offset;
    uint16_t attributes;
    uint16_t length;
} ppm_sfx;

// PPM_CHIP_ANIM_QUEUE (D06) is set here, before ppm_obj, because it decides what ppm_obj's
// bytes 12-15 hold. Its notes are with PPM_CHIP_ANIM_END below (CHIP ANIMATION QUEUE AND
// TERMINAL END) and in mame.c (CHIP ANIMATION QUEUE). Can be overridden with -D.
#ifndef PPM_CHIP_ANIM_QUEUE
#define PPM_CHIP_ANIM_QUEUE     1       // D06: queue moved into the handle at AD (record anim := queued), cancel rule, end-of-cycle switch
#endif

typedef struct {
    uint32_t anim_offset; //
    uint32_t lastDisplayedOffset; //
    uint16_t crtAnim;
    uint16_t counter;
#if PPM_CHIP_ANIM_QUEUE
    uint32_t chip_queued;  // D06: the chip's handle+8, the queued animation's first frame (0 = none).
                           // Bytes 12-15: prev_next/queue_age's with the switch off, which serve only
                           // PPM_CHAIN_FRESH_QUEUE (forced to 0 by D06). ppm_obj stays 16 bytes.
#else
    uint16_t prev_next;    // nextAnim as of the previous draw
    uint8_t  queue_age;    // draws since the queue was armed; 255 = no queue
#endif
} ppm_obj;

typedef struct { //byteswapped (endianess fix)
    int8_t posY;
    int8_t posX;
    int8_t flipPosX;
    uint8_t size; //lower nibble
    uint16_t blockNum;
    uint8_t offset; //block offset
    uint8_t attrs; //flip posY?
} ppm_spr_data;

typedef struct { //byteswapped (endianess fix)
    uint8_t flags;
    uint8_t count;
    ppm_spr_data sprites[];
} ppm_spr_data_hdr;

void ppm_init_mame();
u32 swapshorts(u32 val);
void ppm_setup_data(uint32_t bgm_file, uint32_t unk1_file, uint32_t smp_file, uint32_t unk2_file, uint32_t sfx_file, uint32_t anm_file, uint32_t blk_file);
// 0.2.6 final: B Jam's rule - the debug aids (PPM_SAT_SNAPSHOT, PPM_OBJ_DUMP, PPM_DEBUG_PRINTF) are ON
// in every test/development build and OFF in the RELEASE build only: build it with -DPPM_RELEASE=1.
// Each aid can still be overridden alone with -D<switch>=0/1.
#ifndef PPM_RELEASE
#define PPM_RELEASE             0
#endif
// printf to the cart MCU's UART. 0 = printf is an empty inline function (appmain.h): no call, no
// format strings, nothing on the UART; arguments are still evaluated.
#ifndef PPM_DEBUG_PRINTF
#if PPM_RELEASE
#define PPM_DEBUG_PRINTF        0
#else
#define PPM_DEBUG_PRINTF        1
#endif
#endif
// The "anim over" printf in ppm_obj_render (stock mega-ppm; fires on any AD whose record anim is past
// the object's anim count). Each hit costs ~33,900 MCU cycles at 921,600 baud (~3.8 % of a frame) and
// the chip has no such output, so it is OFF in BOTH variants. The silent drop itself is unchanged and
// still counted by snap_animover_* under PPM_SAT_SNAPSHOT. 1 = the old printf (the earlier 0.2.6 test builds).
#ifndef PPM_ANIMOVER_PRINTF
#define PPM_ANIMOVER_PRINTF     0
#endif
// Diagnostic capture. In the HEADER because it guards code in both mame.c and
// paprium.c, and a guard that cannot see its own #define is silently false.
#ifndef PPM_SAT_SNAPSHOT
#if PPM_RELEASE
#define PPM_SAT_SNAPSHOT        0
#else
#define PPM_SAT_SNAPSHOT        1
#endif
#endif

// Per-frame ring of load refusals over the last PPM_ONSET_FRAMES in-game frames.
// The elevator band is a TIMED event - a few background tiles look misplaced,
// then ~half a second later the squares fill in - so a whole-run refusal total
// cannot see it. 737 refusals spread over 27809 frames and 737 refusals packed
// into thirty read identically in a sticky counter and mean opposite things.
// The ring keeps the tail of the run, which is where the onset is, because the
// tester quits shortly after the band appears.
#define PPM_ONSET_RING          0
#define PPM_ONSET_FRAMES        480   // 8 seconds at 60 Hz, 2 bytes each

// The 0xDA payload CRC recorder is RETIRED. It answered its question outright -
// 48 of 48 records matched the reference decoder, so the unpack is byte-correct
// and #8 is not a decompression fault. Our da-twin tool (not in this tree) still exists and can hash
// any source address straight out of the ROM without an emulator run, so the
// on-card half can come back by setting this to 1; it does not need to sit in
// the arena consuming the only kilobyte of capture space we have.
#define PPM_DA_CRC              0

// Per-epoch delivered-word ring. An epoch is the interval between two MCU
// writes of sdram_ptr. The RTL latches, on each write, how many SDRAM reads
// advanced the pointer during the epoch that just ended and how many read
// strobes the 68000 actually issued. Equal means the tape kept step with the
// game; ack > oe is a double-advance, the mechanism the onset ring and the CRC
// card left standing. Only epochs with any traffic are recorded - frame-end
// rewinds with nothing read in between would otherwise flush the ring in
// under two seconds.
#define PPM_EPOCH_RING          0
#define PPM_EPOCH_CAP           99  // 10 bytes each + 32 meta = 1022 of the 1024-byte arena
// Bisect switch for the boot hang. 1 keeps every epoch static, offset and
// arena write exactly as built, but snap_epoch_note() returns at once without
// touching FPGAIO+0x14 or the ring. Holds bss and layout constant so the ONLY
// variable is the note's runtime path. Default 0 = the real card.
#define PPM_EPOCH_NOTE_STUB     0

// Fix candidate for #8 (PORT_PLAN: "the page model's over-read content is an
// exact formula"). The game's vblank DMA is a fixed 1,024 words and does not
// re-point between pieces, so it reads past a payload whose length is not a
// multiple of the page. GPGX's page model serves the stale mirror there -
// the previous page's tail, then this page's head - and that is what every
// clean playthrough on the emulator has rendered. A tape serves the next
// bytes of SDRAM instead. This copies the mirror's content into place after
// every 0xDA unpack so the tape serves the same bytes. Two memcpys of at
// most one page, once per 0xDA. Default 0 until the elevator log says the
// mechanism is present in the shaft and a review says build.
#define PPM_DA_PAD              0

// #8 mechanism (PORT_PLAN: "the mechanism, in the game's own code"). After a
// 0xDB the game tests reg_status_1 bit 2 (busy) ONCE and, if clear, reads
// sixteen longwords from the window at once. This firmware raises busy only
// when its main loop notices the command - one sfx_player_update later at
// worst - so the test passes during that gap and the reads come off the tape
// before the pointer has moved. The retail cart must raise busy in hardware
// on the write. Emulate that: busy SET at rest; after a command is serviced,
// clear it for a pulse the game's poll loop can see, set it again, then post
// the response. The game cannot issue its next command until the response
// lands, so busy is already up for the next test. Default 0 until the one
// non-0xDB reader of 0x1FE4 is identified (a boot-time wait for busy CLEAR
// would hang on this).
#define PPM_BUSY_REST           1
#define PPM_BUSY_PULSE_LOOPS    600   // ~40 us at 53.69 MHz; the game poll iteration is ~68 cycles = ~9 us
#define PPM_BUSY_CLEAR_THROUGH_RESP 1 // v2 (2026-09-05): after 0xDA/0xDB, clear busy BEFORE the response and hold it
                                      // clear until the game's next post (or PPM_BUSY_WAIT_LOOPS). The 0x0B41C4 reader
                                      // waits for the response and THEN polls busy-clear; under the 40 us pulse it
                                      // never saw clear and ran its 65,534-iteration timeout (~0.56 s) after every
                                      // mode-7 0xDA - the boot pause and the between-screen hitch. 0 = the pulse.
#define PPM_BUSY_WAIT_LOOPS     4000  // ~0.5-1.5 ms across NEORV32 CPI: 30x the 68000's response-to-busy-read latency,
                                      // under the SFX FIFO's time at 13 kHz. A post within it raises busy at once.

// #8, the remaining mechanism (PORT_PLAN: 'the list-order placement fix').
// The retail cart streams the frame's whole tile list into VRAM from tile 16
// upward in list order every frame, and the game authors its plane name
// tables against that layout (tile 64 in the shaft is block 3 of the list, a
// texture, in 895 cells). This firmware's LRU slot cache puts a block wherever
// a slot frees and never re-DMAs a resident one, so the layout never exists.
// With this on: decoded blocks are cached in SDRAM at PPM_BLOCK_CACHE_BASE
// (top of the 2 MB, MCU-only, the tape never reads it); every frame the
// listed blocks are memcpy'd into the 0x9000 staging area in list order and
// one DMA per listed block streams them to tile 16 + 16k, charged 0x110 each
// against the game's own dma_budget - exactly what the retail cart spends.
#define PPM_LIST_ORDER_VRAM     0
// CHIP ANIMATION QUEUE AND TERMINAL END (2026-10-08, differences D06 and D40). How each
// switch does what the cart's chip does, with the chip's addresses, is in
// mame.c (CHIP ANIMATION QUEUE). Each can be overridden with -D. With
// PPM_CHIP_ANIM_QUEUE on, the four animation heuristics below - PPM_STICKY_SWITCH,
// PPM_CHAIN_ONLY_AT_END, PPM_CHAIN_FRESH_QUEUE and PPM_CHAIN_PROP_ANIMS (the props <= 29 /
// actors >= 39 count rule) - are compiled out: the chip's rule replaces all four.
// PPM_CHIP_ANIM_END needs PPM_CHIP_ANIM_QUEUE (an #error in mame.c says so).
// PPM_CHIP_ANIM_QUEUE's default (1) is set above ppm_obj, whose bytes 12-15 it assigns (with
// it on they hold the chip's handle+8, chip_queued).
#ifndef PPM_CHIP_ANIM_END
#define PPM_CHIP_ANIM_END       1       // D40: a terminal end writes record anim := 0
#endif
// STICKY ANIMATION SWITCH (2026-09-06). The game's set-animation routine (ROM
// 0x031024) writes the record's word +0xA to 1 exactly once per animation
// change - a one-shot request, GPGX's `reset` - then the new anim number. This
// firmware reads that word as animCounter, and when a block of the NEW frame
// cannot load it rewinds: anim_offset/counter back to the old frame AND the
// game's word overwritten with previous_counter, while crtAnim already says the
// new anim. Next 0xAD: anim == crtAnim, counter == animCounter, so the advance
// path resumes the OLD animation and the switch is gone for good - the object
// slides in its previous cycle until the game asks for a different anim. GPGX
// never refuses (its DMA is free, vdp_ctrl.c fast_dma_hack), the retail cart
// streams rather than caches, so neither shows it. With this on, a refused
// switch leaves the game's request untouched and parks a sentinel in crtAnim so
// the restart re-fires on the next draw; the object shows its previous frame
// for that one frame, exactly as the advance-path rewind already does.
#if PPM_CHIP_ANIM_QUEUE
#define PPM_STICKY_SWITCH       0       // D06: a held restart stays in the chip's frame pointer, handle+0
#else
#define PPM_STICKY_SWITCH       1
#endif
#define PPM_ANIM_PENDING        0xFFFF   // never a real anim: the game masks to 12 bits
// At a rewind the SAT is about to point at the fallback frame's tiles. On the
// FIRST refused frame those slots are safe anyway: they were used last frame,
// so their age is still 0 and the victim rule (age > 0) cannot pick them. From
// the SECOND consecutive refusal they carry age 1 and usage 0, and a later
// object's load in the same frame can evict one before the vblank DMA runs -
// the sprite then shows that object's art for a frame. Touching the fallback
// blocks that are still resident keeps them at age 0 for as long as the object
// is stuck. Lookups only, no loads, so no budget is spent.
#define PPM_PIN_FALLBACK        1
// CHIP SPRITE CACHE (2026-10-08, differences D02, D03 and D04).
// How each switch does what the cart's chip does, with the chip's addresses, is in
// mame.c (CHIP SPRITE CACHE). The defaults live here so that paprium.c's B1 handler
// sees them. Each can be overridden with -D. With PPM_CHIP_CACHE_LISTS on, the
// PPM_PIN_FALLBACK pinning above is compiled out.
#ifndef PPM_CHIP_CACHE_LISTS
#define PPM_CHIP_CACHE_LISTS    1       // D02: countdowns, lists A / B / related block / C
#endif
#ifndef PPM_CHIP_CACHE_CLAIM
#define PPM_CHIP_CACHE_CLAIM    1       // D03: lowest slot first, the chip's slot -> VRAM id table
#endif
#ifndef PPM_CHIP_CACHE_MISS
#define PPM_CHIP_CACHE_MISS     1       // D04: a piece that cannot be loaded is dropped alone
#endif
#ifndef PPM_CHIP_LOAD_CAP
#define PPM_CHIP_LOAD_CAP       15      // the chip's 15 loads per load list; 0 = off
#endif
// CHIP DMA BUDGET AND POSE HOLD (2026-10-08, differences D09 and D07).
// How each does it the chip's way, with its chip addresses, is in mame.c (CHIP DMA BUDGET AND POSE
// HOLD). PPM_CHIP_POSE_HOLD needs PPM_CHIP_BUDGET (an #error says so).
#ifndef PPM_CHIP_BUDGET
#define PPM_CHIP_BUDGET         1       // D09: gate $1F12 - $1F10 >= $110, $1F10 += $110 per load, $1F14 never written, no floor
#endif
#ifndef PPM_CHIP_POSE_HOLD
#define PPM_CHIP_POSE_HOLD      1       // D07: pose pre-check; hold the previous pose, or pre-load over several frames
#endif
#ifndef PPM_CHIP_READY_FLAG
#define PPM_CHIP_READY_FLAG     1       // D18: $1F1A := 0 when a held object was restarted and not drawn since (needs D07)
#endif
// CHIP EC, B0 AND 81 (2026-10-08, differences D08, D20 and D25).
// How each does it the chip's way, with its chip addresses, is in mame.c (CHIP EC, B0 AND 81) and at
// the three handlers in paprium.c. Each can be overridden with -D; with all three at 0
// (and PPM_CHIP_ANIM_QUEUE and PPM_CHIP_ANIM_END at 0) the image is the D07/D09 one.
#ifndef PPM_CHIP_EC
#define PPM_CHIP_EC             1       // D08: gate $0801B152-$0801B178, worker $08017EE0-$08017F9E (a shrink flushes slots new..old INCLUDING new)
#endif
#ifndef PPM_CHIP_B0
#define PPM_CHIP_B0             1       // D20: $0801AD3C-$0801AD46 -> $0801940C-$0801948E: cache, lists, loads, handle +0/+4/+$C, slot count := 0; no RAMDP; also the first C6 ($0801973C-$080197B8)
#endif
#ifndef PPM_CHIP_81
#define PPM_CHIP_81             1       // D25: $0801AFC4-$0801AFE4 sets flags only: no sprite state, no RAMDP
#endif
// THE SPRITE VALUES THE GAME READS AS DATA (s1 images, 2026-10-17; B Jam's decision of 2026-10-15/16; our spec of the
// sprite values is not in this tree): $1F18, the SAT count (the game's one decision on it: 80+ entries -> its effect gate,
// ROM $33088), and $1F1C, the multiplex flag (ROM $33AEE: the mid-screen stash copy, one gate decrement less).
// $1F1A (D18) was already the chip's. The s1 images only (FW_S1): the 0.2.6 source set keeps 0.2.6's rows, so the
// milestone images never change. How each does it the chip's way, with its chip addresses, is at the code in mame.c.
//   PPM_CHIP_CLIP    D24: the chip's clip, X only ($61 <= X <= $1BF as one unsigned 16-bit compare), Y never tested,
//                    the entry's X and Y stored unmasked (ppm_obj_render)
//   PPM_CHIP_AF_END  D10 + the rest of D42: the chip's whole frame end $080190B8-$080193AC (modes 0 / 1 / 2, the second
//                    14-entry DMA, the $1F20 stash, $1F1C). Its open-frame gate (D38) and the multiplex parity H+$403
//                    are dispatcher state (core/dispatch: frame_open, af_parity); body_af hands the mode and the parity
//                    over (ppm_chip_af_mode, ppm_chip_af_parity)
// PPM_CHIP_ATTR    D23 (test build 4, 2026-10-18; B Jam: "if cart is different color change to cart"): the SAT
// attribute word as
//                    the chip composes it, one 16-bit ADD of the piece word (attr byte << 8 | tile offset), the object's
//                    attribute word and the block's VRAM id x 16 ($0802F186-$0802F192); with the object's H-flip bit the
//                    object word less $800 ($0802F41E-$0802F428) and the piece word XOR $800 ($0802F47A-$0802F48E); a pose
//                    with frame-word bit 29 clears the object's palette bits 13-14 first ($0802F104-$0802F112; a held pose:
//                    the bit of the frame drawn again, $0802F404-$0802F41C). The piece's attr bits 0-2 stay in the sum.
//                    0.2.6's field-wise rule and its object-107 door fix are not the chip's: neither is compiled with it.
//                    Needs PPM_CHIP_CLIP (the s1 entry store). 0.2.6's rule back is variant bug_spr5 (PPM_CHIP_ATTR=0)
#if FW_S1
#ifndef PPM_CHIP_CLIP
#define PPM_CHIP_CLIP           1
#endif
#ifndef PPM_CHIP_AF_END
#define PPM_CHIP_AF_END         1
#endif
#ifndef PPM_CHIP_ATTR
#define PPM_CHIP_ATTR           1
#endif
#else
#undef PPM_CHIP_CLIP
#undef PPM_CHIP_AF_END
#undef PPM_CHIP_ATTR
#define PPM_CHIP_CLIP           0
#define PPM_CHIP_AF_END         0
#define PPM_CHIP_ATTR           0
#endif
#if PPM_CHIP_ATTR && !PPM_CHIP_CLIP
#undef PPM_CHIP_ATTR
#define PPM_CHIP_ATTR           0       // bug_spr1 (0.2.6's clip back) is 0.2.6's whole entry store, attribute rule included
#endif
// SPR_BUG: planted bugs for the chip lockstep's negative controls only (tests/equiv/chiplock_slice.py; fwbuild.json
// s1 host program variants bug_spr*; never defined in an image that ships): 2 = the close never writes $1F1C,
// 4 = the stash takes entries 0-13 instead of 14-27 (mame.c); 3 = an accepted B0 does not bump the parity
// (core/dispatch); test build 4 (D23): 6 = pose bit 29 ignored (the object's palette kept), 7 = the H-flip path
// composed as the plain one (no $800 moved between the words) (mame.c). The 0.2.6 clip back is variant bug_spr1
// (PPM_CHIP_CLIP=0), 0.2.6's attribute rule back bug_spr5 (PPM_CHIP_ATTR=0).
#ifndef SPR_BUG
#define SPR_BUG 0
#endif
// DMA FLOOR (2026-09-06, second candidate; corrected the same morning). The DMA
// list is shared: the game appends its own descriptors (dma_total += 0x10 +
// words, ROM 0x09D430) and a screen transition carries up to 34 of them a frame
// (GPGX capture, PORT_PLAN 9076) against a median of 1. The game ALSO owns the
// budget arithmetic: its 0xAE sender pre-charges dma_total = 0x240 (ROM
// 0x030F8C, the full 144-entry SAT upload) and its frame routine rewrites
// 0x1F14 = dma_budget - dma_total (ROM 0x03304E-0x03305A) AFTER its appends
// and BEFORE the 0xAD stream - so anything this firmware writes into
// dma_remaining at 0xAE is discarded before the first load is gated, and the
// effective ceiling is (2816 - 576 - the game's words) / 0x110 = 8 blocks in
// an ordinary frame and nothing at all through a transition scroll. Every
// sprite load is refused for the whole scroll and the walk-in from the previous
// screen plays standing still (hardware, 2026-09-06, on the sticky-switch build:
// attacks fixed, walk-in still frozen). The retail cart overruns its vblank when
// busy and tears rather than freezing (tester).
// So the floor lives at the GATE, as an MCU-private per-frame credit: when
// dma_remaining is below one block, up to this many loads are still granted and
// NOT charged to the shared word (it is already spent). An NTSC vblank carries
// ~3,670 usable words against the game's 2,816; two blocks (0x220 = 544 words)
// fit even under a transition's descriptor overhead. 0 = off.
#define PPM_DMA_FLOOR_BLOCKS    2
#if PPM_CHIP_BUDGET
// D09: the chip has no floor. Its gate ($0802F1CC-$0802F1D6, H-flip $0802F4C4-$0802F4CE)
// refuses every load once $1F12 - $1F10 < $110 and nothing is granted past it, so the
// floor is off whenever the chip's budget is on.
#undef PPM_DMA_FLOOR_BLOCKS
#define PPM_DMA_FLOOR_BLOCKS    0
#endif
// QUEUED FOLLOW-UP ONLY AT A TERMINAL END (2026-09-06). The game queues a
// follow-up animation with bit 14 of its set-anim call (ROM 0x03103C: nextAnim
// = d1, no reset). Stock mega-ppm - and GPGX (paprium.h:1288-1297) - take that
// follow-up as soon as the CURRENT CYCLE ends, even when the animation has a
// loop target. GPGX capture 2026-09-06 (winlog-walkin-20260906.bin): at a
// screen transition the game queues idle behind the walk and then scripts the
// character across for 295 frames without touching the record; the walk ran to
// its cycle end at frame 6555 and both emulated carts switched to idle for the
// remaining 280 frames - the character slides in its standing pose. The user
// reports the retail cart keeps walking there, and in the normal stop case the
// game sets idle EXPLICITLY eight frames after the cycle end (frames 6441 ->
// 6449), so it never relies on the chain for a looping animation. Enemies show
// the same pattern (anim 2 with idle queued for 349 frames). Rule with this on:
// an animation with a loop target keeps looping; a queued follow-up is taken
// only when the animation reaches a terminal end (loop target 0), where the
// stock code would otherwise stop drawing the object.
// TURNED OFF 2026-09-10. This rule is what strands dropped weapons. Objects
// 0xDC-0xE1 (knife, pipe, wrench, pickaxe - RENDERED from ROM, not inferred) each
// carry anim 8 = a 25-frame CYCLE (the drop spin) and anim 1 = an 85-frame CYCLE
// (the ground idle, 6 poses mostly held - what the user describes as "animates
// every few seconds"). A hardware capture caught objID 0xDE mid-failure: playing
// anim 8 with anim 1 QUEUED in nextAnim. The item is asking to become the ground
// idle, and this rule refuses the chain because anim 8 has a non-zero loop target.
//
// The walk-in case this rule was added for has the same cycle->cycle shape, so
// shape cannot separate them. But 0.2.1 shipped TWO fixes together, and
// PPM_STICKY_SWITCH is the one that addressed the measured fault (a refused art
// load losing the game's one-shot reset). This one may simply have been an
// unnecessary over-correction bundled with it. Turning it off is the test:
// weapons must settle into their ground idle AND the walk-in must keep walking.
// If the walk-in regresses, this goes back to 1 and the two cases need a real
// discriminator.
// REVERTED TO 1 (2026-09-10, hardware): turning this off DOES fix the dropped
// weapons - the user confirms 0xE0 pipe, 0xDC knife, 0xDE electric stick all
// settle into their ground idle - but it REGRESSES the walk-in to moonwalking
// (sliding in the standing pose). Both cases are cycle->cycle with reset == 0,
// so neither the loop target, the queued animation's shape, nor the reset flag
// separates them. The discriminator is still unknown; see the frame-word flag
// bits 24-30, which differ between the two (weapons 01/02, characters 03/04/05)
// and are ignored by GPGX.
//
// THOSE FLAG BITS ARE NOT IT (decoded 2026-09-10). Their low nibble is the count
// of graphics blocks a pose needs that the previous pose did NOT - a VRAM
// streaming budget, matching on 24,764 of 24,893 pose boundaries across all 241
// objects (99.48%). "Weapons 01/02, characters 03/04/05" is just sprite size: a
// dropped weapon is a one-block sprite and a character a four-or-five-block one.
// Also measured and eliminated since: obj_data+0x06 (mutable nibble-packed game
// state, and the knife carries 0000 in one drop and 2233 in another); movement
// while the queue is armed (BACKWARDS - the player's walk moved 0.0% of samples
// and the knife 13.2%); and matching GPGX, which chains at every looping end and
// therefore moonwalks the walk-in as well - confirmed by matching its logged
// graphics blocks against the ROM's per-frame art.
//
// And this knob is not the narrow refinement it reads as. Across 12 minutes of
// captured play it chains 0 of 821 chain requests: EVERY animation the game ever
// arms a follow-up on has a nonzero loop target, so in practice this is "never
// chain". That is why every dropped item spins.
#if PPM_CHIP_ANIM_QUEUE
#define PPM_CHAIN_ONLY_AT_END   0       // D06: the chip switches at the end of the current cycle, looping or terminal
#else
#define PPM_CHAIN_ONLY_AT_END   1
#endif
// CHAIN AT A LOOPING END ONLY WHEN THE QUEUE WAS ARMED AT THAT END (2026-09-10).
//
// The spawn-animation reading that stood here was REFUTED before it reached
// hardware: a dropped knife is not spawned falling. It is created on the ground
// at anim 1, sits there, and the game then calls setAnim(8) to make it fall -
// the same protocol as the player's walk - so at the moment the chain is needed
// its animation was assigned by setAnim in both cases. Measured in the emulator:
// 38 of 42 weapon objects spawn at anim 1 already on the ground.
//
// What DOES separate them is WHEN the game arms the queue, relative to the
// animation it is arming it on:
//   knife/stick fall, anim 8: 25 frames, loops to index 1, so it ends at frame
//     49 (25 + 24). The game arms nextAnim=1 at exactly frame 49. Eleven of
//     eleven armings across every capture land exactly on an end.
//   player walk-in, anim 9: 49 frames, loops to index 1, ends at 49, 97, 145.
//     The game arms nextAnim=1 at 5, 17, 18, 19, 80 and 116 - never on an end,
//     0 of 31.
// So the game arms the queue ON the frame the animation finishes when it means
// "switch now", and arms it mid-cycle when it is only a standing fallback that
// it intends to resolve itself with a direct setAnim later. That is a
// synchronous handshake, and it is readable with one word of state per object.
//
// This firmware detects the end one call LATER than the emulator does - it keeps
// the frame just drawn and advances at the top of the next call - so the window
// is "armed on this call or the previous one", not "this call" alone. The
// nearest a player walk-in arming ever comes to an end is 17 frames, so the
// window has a wide margin.
//
// Blast radius: about a quarter of armings land on an end, mostly the player's
// attack animations returning to the stand, which is what chaining is for. A
// terminal end (loop target 0) still chains unconditionally.
//
// STILL A GUESS as to the cartridge's actual mechanism, but it is the only rule
// that fits both hardware-confirmed cases. See docs/PORT_PLAN.md.
// 2026-10-08: the cartridge's mechanism is now known from our study of the cart (D06). The game's
// re-arm of the same queue CANCELS it on the chip (its setAnim compares against the
// record anim the chip already set), so no timing window is involved.
#if PPM_CHIP_ANIM_QUEUE
#define PPM_CHAIN_FRESH_QUEUE   0       // D06: replaced by the chip's queue move and cancel rule
#else
#define PPM_CHAIN_FRESH_QUEUE   1
#endif
#define PPM_CHAIN_FRESH_WINDOW  1
// A PROP IS NOT AN ACTOR (2026-09-11, hardware).
//
// Two hardware experiments bracket this exactly, and between them they say what
// the rule has to be:
//
//   2026-09-10  chain at EVERY looping end, all objects. Every dropped weapon
//            settled correctly - and the character walk-in moonwalked.
//   0.2.5a   chain at a looping end when the queue was armed with the animation
//            (AT-LOAD) or left standing past 64 draws (STALE). The weapons
//            settled, a little later than original hardware - and the walk-in
//            moonwalked AGAIN.
//
// Both times the weapons wanted the wide rule and the characters refused it, so
// the discriminator is not WHEN the queue was armed at all. It is WHAT the
// object is. Those two rules both reach obj 01 anim 02 - the player's looping
// idle, queued back to the stance and then left alone for 212 to 1,067 draws -
// which is the only character animation either of them touches in 834,000
// object records, and it is enough to put a moving character into a standing
// pose.
//
// The cartridge cannot be doing this, but the population split is real and the
// firmware already has it to hand: ppm_anim_max_index, the per-object animation
// count it bounds-checks against. Measured over all 241 objects, it separates
// with a gap and no overlap:
//
//   props   2, 4, 5, 10, 11, 12, 13, 16, 17, 18, 23, 29 animations
//           - every weapon is 10: knife DC, chain DD, neon stick DE, pipe E0
//   actors  39, 61, 157, 160, 161, 220 animations
//           - all three playable characters are 157, every enemy 39 or more
//
// So: a prop takes a queued follow-up at any looping end, which is the rule
// hardware confirmed settles every weapon; an actor keeps 0.2.4's rule exactly,
// which is the rule hardware confirmed keeps the walk-in walking. Nothing an
// actor does changes from the build the user tested and passed.
//
// This is a containment boundary, not a discovery - if the cartridge's actual
// rule is ever found, it replaces this. What it buys is that the failure that
// came back twice cannot come back a third time from a rule we cannot see into.
// 2026-10-08: the cartridge's rule is now known (D06), and it has no object classes.
#if PPM_CHIP_ANIM_QUEUE
#define PPM_CHAIN_PROP_ANIMS    0       // D06: the chip treats every object alike
#else
#define PPM_CHAIN_PROP_ANIMS    32
#endif
// obj_data+0x0A IS THE GAME'S ONE-SHOT RESTART FLAG, NOT OUR COUNTER (2026-09-10).
// This firmware called it animCounter and INCREMENTED it every drawn frame, in
// memory the 68000 owns and reads back. It is a flag, and the game writes 1 to
// mean "restart this animation from frame 0".
//
// Measured on both sides:
//   emulator, 156,868 object records across three winlog captures: the field
//     holds ONLY 0 or 1. Never any other value.
//   this port, on hardware, one capture with a pickup left spinning on screen:
//     93, 137, 233, 440, 659, 900 - climbing with every frame drawn.
// GPGX acts on the 1 and writes 0 BACK so the game can ask again
// (GPGX's core/cart_hw/paprium.h:1242, inside `reload:`); this firmware never
// zeroes it, so the game's restart request can be honoured at most ONCE and can
// never be re-issued. The pickups sit at anim 0x01 with nextAnim 0xFFFF for their
// whole life - no chain is ever queued, which is why every chain-based fix missed.
// The 0.2.1 sticky-switch comment already half-named this: "a refused switch
// leaves the game's reset in place".
//
// With this on: never WRITE the field; mirror it into handle->counter so the
// switch test still detects a game write; and consume a 1 by writing 0 back, as
// GPGX does. 0 = the shipping 0.2.2/0.2.3 behaviour.
#define PPM_ANIM_FLAG_SEMANTICS 1
// COMPACT OBJECT-TABLE RECORD (2026-09-10). The full 1024-byte obj_data record was
// reclaimed from the SAT snapshot for want of a question; the pickup-spin bug is
// that question. Items keep looping their fall instead of taking their ground
// pose, and NEITHER instrumented mechanism explains it - a capture measured
// anim-over drops 0, and 5 art-refused switches of which 4 completed. So the
// game probably never asks for the ground pose at all, and what decides that is
// per object: anim, nextAnim, and the field at obj_data+0x0A.
//
// That field is worth naming carefully. mega-ppm calls it animCounter and
// INCREMENTS it every drawn frame; GPGX calls the same offset `reset` and treats
// it as a one-shot flag, taking a queued follow-up only when it reads 0 and
// setting it to 1 once consumed (gpgx paprium.h, "else if( reset == 0 )"). Those
// are incompatible readings of one field, and GPGX renders pickups correctly
// where this port does not - so the object-table record keeps it raw, per object, and lets a
// capture decide rather than another guess.
//
// 64 objects x 6 bytes = 384 bytes at SNAP_OFF_ARENA, which the onset and epoch
// rings leave free while they are off. Diagnostic; 0 for a shipping build (PPM_RELEASE).
#ifndef PPM_OBJ_DUMP
#if PPM_RELEASE
#define PPM_OBJ_DUMP            0
#else
#define PPM_OBJ_DUMP            1
#endif
#endif
// Crash-context heartbeat: a 40-byte record in battery RAM (bram 0xF70..0xF97,
// the free gap between the onset ring's meta and the dispatch block) rewritten
// at every command entry/exit, per object, per walked sprite, per stream DMA,
// at BGM unpack and at frame end. On a hang, exit the core from the Pocket
// menu: the OS writes bram to the .sav and scripts/decode_heartbeat.py reads
// where the firmware stopped. No behaviour change. Layout (big-endian):
//   0 'PHBT'  4 frame u32  8 cmd u8  9 phase u8 (1 cmd 2 render 3 dma 5 bgm 6 frame-end)
//  10 obj u8  11 sprite u8  12 count u16  14 cursor tile u16  16 stage u16
//  18 dma_cmd_count u16  20 dma_remaining u16  22 sat_count u16  24 spr_info u32
//  28 bgm unpack addr u32  32 bgm len u32  36 sp u32
//  phases added 2026-09-05: 7 walk done  8 SAT pass (sprite idx in byte 11)  9 render returned
//  10 handler tail (busy pulse / reg_cmd write pending)
// Trap record at bram 0xFD0..0xFE7 (SNAP_OFF_SPARE + 32; capture-time h[] uses the
// first bytes of SPARE, a capture zeroes it): the RTE is installed and every
// exception id 0..8 records - 0 count u16  2 first cause u8  3 hb phase at first u8
//  4 first mepc u32  8 first mtval u32  12 sp u32  16 hb frame u32  20 last cause u8
//  21 last phase u8  22 pad. The RTE still skips the faulting instruction, as the
//  crt0 dummy handler did - no behaviour change beyond the record.
#define PPM_HEARTBEAT           0
// Option B (2026-09-05): keep the MCU off SDRAM while the game runs its vblank
// DMA list. The SFX player reads samples through ppmio.flash, which the Pocket's
// MCU memory adapter serves from the same SDRAM port2; with the port2
// anti-starvation boost that steals port1 rounds exactly while the VDP reads the
// stream window on the VDP's fixed acknowledge timing - a late word = a stale
// word = flicker. While this is 1, sample reads pause from frame end (0xAF)
// until the 68000 has zeroed dma_cmd_count (the runner's last act) or the next
// frame start (0xAE), whichever first. Experiment; default OFF.
#define PPM_SFX_QUIET_DMA       0
// Port2-load experiment (2026-09-05): on the LRU baseline, add the stream
// walk's SDRAM traffic WITHOUT any stream code - a scratch memcpy of
// PPM_PORT2_LOAD_BYTES per 0xAD (SDRAM 0x1E0000 -> 0x1F0000, below the block
// cache, above every payload). If the baseline then flickers / goes dark like
// the stream cards, the mechanism is MCU port2 traffic starving the 68000's own
// ROM fetches on the VDP's fixed acknowledge - not the stream's data. Default OFF.
#define PPM_PORT2_LOAD          0
// Scratch relocation (2026-09-05): shaft-type levels park a
// mode-3 0xDA payload at SDRAM 0x9000 and read its rows back LATER through
// 0xDB06 at 0x9000+index as the elevator scrolls (ROM 0x07F956 / 0x07F448),
// while mega-ppm's block loader unpacks new blocks at 0x9000 + 0x200*n and the
// stream stages every frame's tiles at 0x9000+. Whatever the MCU wrote there
// since the payload landed is what the game reads back: 0x200-byte blocks =
// sprite art in slot-wide bands (#8), per-frame staging = every row garbage.
// With this 1 the MCU scratch (loader unpack base, stream staging, the 0xAF
// tape re-arm) moves to PPM_SCRATCH_BASE, outside the game's 64 KB payload
// space; the tape pointer is 21 bits so 0x1E0000 is reachable. cmd_F2's unpack
// and re-arm move with the scratch (its data must stay where the 0xAF re-arm
// points, as today). Default OFF until GO.
#define PPM_SCRATCH_HIGH        1
#if PPM_SCRATCH_HIGH
#define PPM_SCRATCH_BASE        0x1E0000u
#else
#define PPM_SCRATCH_BASE        0x9000u
#endif
#define PPM_SCRATCH_END         (PPM_SCRATCH_BASE + 0x6A00u)   // was the fixed 0xFA00 cap
#if PPM_SCRATCH_HIGH
// bounds: above the 64 KB payload space of the game, below the decoded-block cache at
// 0x1F8000 (PPM_BLOCK_CACHE_BASE is defined further down; the literal is asserted
// against it there too)
#if (PPM_SCRATCH_BASE < 0x10000u)
#error PPM_SCRATCH_BASE must sit above the 64 KB payload space of the game
#endif
#if (PPM_SCRATCH_BASE + 0x6A00u > 0x1F8000u)
#error PPM_SCRATCH_END overlaps the decoded-block cache
#endif
#endif
#if PPM_PORT2_LOAD && PPM_SCRATCH_HIGH
#error the PPM_PORT2_LOAD scratch memcpy (0x1E0000..0x1F1000) overlaps PPM_SCRATCH_BASE - never both
#endif
extern u32 snap_ptr_while_list_pending;   // 0xDA/0xDB pointer writes while the 0xAF list was still unconsumed (residual I7)
extern u32 snap_bgm_over;                 // BGM modules whose unpack reached the MCU scratch
#define PPM_PORT2_LOAD_BYTES    0x1000   // ~ the walk's per-object traffic (12 objects x 4 KB ~ 48 KB/frame)
#if PPM_SFX_QUIET_DMA
extern volatile u8 ppm_list_pending;   // 1 between 0xAF and the runner's completion
#endif
#if PPM_HEARTBEAT
extern volatile u8 *ppm_hb;
extern u32 ppm_hb_frame;
void ppm_hb_init(void);
static inline u32 ppm_hb_sp(void) { u32 sp; __asm__ volatile ("mv %0, sp" : "=r"(sp)); return sp; }
static inline void hb_w8(u8 off, u8 v)   { ppm_hb[off] = v; }
static inline void hb_w16(u8 off, u16 v) { ppm_hb[off] = (u8)(v >> 8); ppm_hb[off + 1] = (u8) v; }
static inline void hb_w32(u8 off, u32 v) { ppm_hb[off] = (u8)(v >> 24); ppm_hb[off + 1] = (u8)(v >> 16); ppm_hb[off + 2] = (u8)(v >> 8); ppm_hb[off + 3] = (u8) v; }
// Loop-idle mailbox snapshot (bram 0xFE8..0xFFF, the retired pointer-audit t[]
// block, capture-time only otherwise): 0 reg_cmd 2 reg_status_1 4 reg_status_2
// 6 dma_cmd_count 8 dma_total 10 dma_remaining 12 cmd_args[0] 14 loop tick
// 16 tape pointer shadow u32 20 post-overwrite count u16 22 loop-exit marker u16
// Heartbeat 4: the cart overlays the 68000 vector table with the mailbox RAM
// (ramdp->vectors[]), so the EFFECTIVE handlers are readable. At loop idle the
// bus-error (vec 2), address-error (3), illegal-instruction (4) and VBLANK (28)
// vectors are copied to bram 0xFB0..0xFBF (SPARE + 0, capture-time h[] only).
// (0xEE00 | last phase). dma_cmd_count/dma_total are 68000-owned: still holding
// the list's count at a freeze means the game never finished running the list.
void ppm_hb_idle(void);
void ppm_hb_exit(void);
void ppm_hb_overwrite(u16 posted, u16 now);
#else
// Macros, not inline functions: the arguments carry volatile mailbox/SDRAM reads
// that an empty function would still have to perform. With the switch off the
// firmware must be byte-identical to the card without the heartbeat.
#define ppm_hb_sp()      0u
#define hb_w8(off, v)    ((void) 0)
#define hb_w16(off, v)   ((void) 0)
#define hb_w32(off, v)   ((void) 0)
#define ppm_hb_idle()    ((void) 0)
#define ppm_hb_exit()    ((void) 0)
#define ppm_hb_overwrite(a, b) ((void) 0)
#endif
#define PPM_BLOCK_CACHE_BASE    0x1F8000
#if PPM_SCRATCH_HIGH && (PPM_SCRATCH_BASE + 0x6A00u > PPM_BLOCK_CACHE_BASE)
#error scratch overlaps the decoded-block cache
#endif
#define PPM_LIST_MAX            16
void snap_epoch_note(u32 ptr_prev);
extern u32 ppm_sptr_shadow;         // last sdram_ptr the MCU wrote; the RTL register is write-only

// Stream-window handshake counters. Shared between mame.c (0xAF) and paprium.c
// (0xDA / 0xDB), which is why they are declared here.
extern u32 snap_da_count;      // 0xDA unpack-and-point
extern u32 snap_db_count;      // 0xDB explicit re-point
extern u32 snap_af_clobber;    // 0xAF rewound to 0x9000 while a 0xDA dest stood
extern u32 snap_da_last_dest;  // sticky: last destination a 0xDA set
extern u32 snap_da_dest_9000;  // 0xDA destinations that WERE 0x9000 (rewind = no-op)
void snap_da_pending_set(void);
void snap_da_pending_clear(void);
void snap_db_note(u32 dst);
void snap_da_reset_high(void);
void snap_da_note_other(u32 dst);
void snap_da_note_src(u32 src, u32 len, u32 dst);
extern u32 snap_da_other[6];

void ppm_obj_add(uint8_t num);
extern u32 snap_cnt_ae, snap_cnt_af, snap_cnt_ad, snap_cnt_refresh;
void ppm_obj_frame_start();
void ppm_obj_frame_end();
#if PPM_CHIP_CACHE_MISS && PPM_CHIP_LOAD_CAP
void ppm_chip_flush_loads(void);        // B1: the chip's load-list flush, count part (mame.c)
#endif
#if FW_S1
uint32_t ppm_chip_load_list(const uint32_t **list);    // MCU interface v1.2: the load list the flush pushes (count, addresses)
#endif
#if PPM_CHIP_AF_END
extern uint8_t ppm_chip_af_mode;        // the AF post's low byte & 3 (the chip's r0 at $0801BCF2-$0801BCF6)
extern uint8_t ppm_chip_af_parity;      // H+$403 at the AF (the multiplex parity: core/dispatch af_parity)
#endif
void ppm_snapshot_boot(void);   // paprium-pocket: DIAGNOSTIC, see mcu/mame.c
#if FW_S1 && PPM_SAT_SNAPSHOT
void ppm_snapshot_sat(u32 ae0);  // TEST layout 2: ae0 = the frame-start count read with the thread's take (interrupts off)
extern u32 snap_af_n, snap_n_max, snap_n_over80;   // TEST layout 2 (mame.c): AF's close latches its count and compares
#else
void ppm_snapshot_sat(void);
#endif
void ppm_obj_reset();
void ppm_vram_set_budget(uint16_t blocks);
#if PPM_CHIP_EC
void ppm_chip_ec_count(uint16_t n);     // D08: the chip's EC worker $08017EE0-$08017F9E (mame.c)
#endif
#if PPM_CHIP_B0
void ppm_chip_b0_reset(void);           // D20: the chip's B0 worker $0801940C-$0801948E (mame.c)
#endif
u32 ppm_block_addr(u32 num);
u32 ppm_bgm_addr(u32 num);
uint32_t ppm_unpack(uint32_t source_addr, uint32_t dest_addr);
uint32_t ppm_unpack_scal(uint32_t source_addr, uint32_t dest_addr, u8 is_scaling_stamp);
void ppm_stamp_rescale(uint16_t window_start, uint16_t window_end, uint16_t factor, uint16_t stamp_offset);

extern u32 ppm_sfx_base_addr;
extern u32 ppm_bgm_unpack_addr;

#endif	/* MAME_H */

