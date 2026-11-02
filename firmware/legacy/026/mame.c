
// baswed on https://github.com/TheHpman/mame/blob/master/src/devices/bus/megadrive/rom.cpp
/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */
// Terms in this file's notes: FW_S1 is defined only when the s1 images are built (the new 0.3.0 firmware,
// tools/fwbuild.py s1), FW_S5 only for their s5 variants, which add the song engine. D02, D06 and the other D numbers
// name the differences between this 0.2.6 code and the cart's chip that our own study of how the cart behaves listed.
// The MCU is the cart's NEORV32 soft CPU in the core; RAMDP is the cart RAM that both the 68000 and the cart chip (here
// the MCU) see; SAT is the sprite attribute table; RTL is the core's hardware description.

#include "appmain.h"

#define PPM_DATA_START_ADDR     0x10000	// base sdram unpack address
// paprium-pocket A/B switch for the Block 888 door fix below. 0x2000 is sprite
// palette bit 0, so that fix moves object 107's sprite 4 onto another palette
// line. Hardware shows a red floor where original hardware is green, which is
// exactly what a wrong palette line looks like - so the suspicion is that
// x == 4 is the FLOOR sprite in this build rather than the door panel.
//
// Set to 0 to disable and compare. See docs/PORT_PLAN.md.
#define PPM_DOOR_FIX            1

// paprium-pocket: 53 slots, the full request. The cap at 49 was REMOVED after an
// A/B on hardware, 2026-08-31. The two-range map is UNCHANGED: slots 49-52 use the
// +0x4b jump to tiles 1984-2047 = VRAM 0xF800-0xFFFF. NOT the 0x6400 remap, which
// is forbidden - see below.
//
// Stock maps slot -> tile as ((x + (x <= 0x30 ? 1 : 0x4b)) << 4).
//
// WHY THE CAP WENT. It rested on two claims and both failed:
//   - the collision target was "the sprite attribute and hscroll tables at 0xF800".
//     GPGX shows the SAT is DMAed to 0xF000 and ends at 0xF27F, so the sprite
//     attribute table is NOT there
//   - "visibly improved the elevator on hardware" was never a tester report. Asked
//     directly, the answer was that it felt the same or similar
//
// A/B RESULT, tester on real hardware, cap 49 vs 53 on the same map:
//   elevator shaft   THE SAME. Nothing visible lives at 0xF800, or writing there
//                    does no visible harm. The cap bought nothing it claimed to
//   walks / anims    MUCH BETTER. This is the real finding
//   cell room, door  unaffected
//
// So animation starvation is partly RESIDENCY-bound, not purely fill-bound as this
// file previously concluded. Fill rate (dma_budget, 10-16 blocks/frame) still caps
// how fast a scrolling shaft can be refilled - which is why the elevator did not
// move - but holding 53 blocks resident instead of 49 avoids reloads the LRU would
// otherwise have to redo, and that is enough to stop many load_block failures and
// the previous_offset rewinds they cause.
//
// Do not re-cap without a hardware observation to justify it.
//
// REMAP ATTEMPT, REFUTED (2026-08-30). Capping costs four blocks of cache while
// INTERCOM asks for 53, so the four slots were moved into the gap the two-range map
// skips - linear (x + 1), putting them at tiles 800-863 = 0x6400-0x6BFF, far below
// the 0xC000 nametable floor. **The cell-room floor glitched immediately.**
//
// So that gap is NOT free: the game already owns it. A 32x32 nametable at 0x6400 is
// 0x800 bytes = tiles 800-863 EXACTLY, which is the range the remap wrote patterns
// into, and a floor built from that plane would break in the cell room and nowhere
// else first. The jump to 0x4b is deliberate, not an artefact.
//
// Diagnostic value: cap-at-49 leaves the cell room clean, 53 slots at 0xF800 leave
// the cell room clean, and only this placement breaks it - so it is the ADDRESS,
// not the extra four blocks.
//
// Do not retry tiles 864-927: if the map is 64x32 it occupies 0x6400-0x73FF, i.e.
// tiles 800-927, and that slice is still inside it. The cheap discriminator is a
// ONE-SLOT write at tile 864 (0x6C00) - floor dies -> 64x32; floor lives -> 32x32
// and 864-927 is usable. Otherwise tiles 928-991 (0x7400-0x7BFF) clears both.
//
// INTERCOM is NOT an untested LRU case: the remap never became a valid slot-bound
// experiment, because it broke before the shaft was reached.
#define PPM_VRAM_SAFE_SLOTS     0x35   // 53, the full request. Was 0x31 (49).

// NOTE: a reserved blank "miss block" was tried here and REMOVED - it changed
// nothing, because the elevator's stale squares come from load_block failing and
// the object re-rendering its previous animation frame, not from find_block
// returning 0. Full implementation in git: "EXPERIMENT: reserved MISS_BLOCK for
// cache misses" (2026-08-30). See docs/PORT_PLAN.md.

// paprium-pocket: compose the sprite attribute field-wise, as GPGX does, rather
// than XORing the whole word. Ours XORs tile attrs, object attrs and the block's
// tile index together, which only agrees with GPGX while the object's priority
// and palette bits are zero. When BOTH the tile and the object set priority the
// XOR cancels to 0 and the sprite drops behind the background; when both set
// palette the XOR scrambles it and the colours come out wrong.
//
// The doorway leaving the first room renders its floor red where hardware shows
// green - a wrong-palette symptom - and disabling the Block 888 door fix changed
// nothing, so the palette is being composed wrongly rather than overridden.
//
// MisterPezz82 built and tested this against the ELEVATOR (2026-06-25) and it did
// not help there, but they kept it in V.04 as harmless. It was never tested
// against the doorway, which is what this probe is for.
#define PPM_FIELDWISE_ATTRS     1

// paprium-pocket: DIAGNOSTIC, kept OFF. Forces the priority bit on every SAT
// entry. Left in place because its result is worth not re-deriving.
//
// RUN AND REFUTED ON HARDWARE 2026-08-31. Other sprites came forward; the player
// and the bombs did not move. So the "player drops behind the background" symptom
// is NOT clear SAT priority, and no attribute-composition change in this file can
// fix it - which also means mega-ppm's whole-word XOR, the documented upstream
// cause, does not explain that symptom either.
//
// The negative is strong rather than inconclusive: a high-priority sprite is
// topmost on a Mega Drive, ahead of plane A, plane B and the window. Forced to
// maximum priority and still occluded means something other than layering is
// happening. The two live candidates are that the player is a 68000-managed
// sprite this function never touches, or region-based masking (window plane, or
// a sprite at X=0 masking its scanlines). Both need an emulator VDP/SAT viewer.
//
// See docs/PORT_PLAN.md, "Sprite priority: NOT SAT priority".
// paprium-pocket: DIAGNOSTIC, OFF. Kept because its result is worth not
// re-deriving. Run twice: 2026-08-31 by eye, and 2026-09-01 alongside the SAT
// snapshot so the probe's own effect could be verified rather than assumed.
//
// RESULT: priority is NOT the mechanism. The capture showed every entry this
// firmware composes reading priority 1, and the tester confirmed the probe
// visibly worked elsewhere - an extra life came out from behind a bed, and the
// escalator stopped occluding the player. The rooftop player STILL drew behind.
//
// Those bed and escalator cases are intended depth: plane pri-1 over sprite
// pri-0. Forcing priority broke them. They are not mask bugs and must not be
// "fixed".
//
// See PPM_MASK_PROBE below for what is actually doing it.
#define PPM_FORCE_SPRITE_PRI    0

// paprium-pocket: MASK RELINK, DIAGNOSTIC. The candidate fix.
//
// Root cause, from comparing a hardware capture with an emulator state where the
// symptom does not occur: the three X=0 masks are IDENTICAL and at the same Y
// ladder in both, but sit at different places in the link chain.
//
//     emulator (no symptom)   masks at chain positions 25, 27, 29
//     our port  (symptom)     masks at chain positions  8, 10, 12
//
// Masking hides sprites LATER in the chain, so on hardware only the tail is
// affected and the player - earlier - is safe. On ours the masks sit near the
// front and catch nearly everything we compose.
//
// The 68000 writes them at whatever sat_count holds at that instant; hardware has
// ~32 cartridge sprites composed by then and we have ~14, so our composition runs
// later in the frame than it should. Fixing THAT is the real repair. This moves
// the masks to where hardware puts them instead, which should free the player
// while keeping the boss and door masked - unlike deleting them, which fixed the
// player by breaking the boss.
//
// PPM_MASK_MOVE_AFTER is CALIBRATED TO ONE CAPTURE and is the weak part. In that
// frame the player sat at chain 15-22 and the boss at 39-48, so any insertion
// point between them works; 18 puts the masks near the emulator's relative
// position. It is a heuristic, not a derivation - if a later capture shows the
// player and boss at different chain positions, this number is wrong for that
// scene. Validate against the capture, not by eye alone.
//
// If fewer than PPM_MASK_MOVE_AFTER of our entries exist, the masks end up
// unlinked entirely, which degrades to the blanket-kill behaviour - the known
// safe-ish fallback rather than something new.
// paprium-pocket: see the probe in ppm_obj_frame_end. OFF - it is a separate
// experiment from the mask work and must not be enabled in the same build, or
// neither result means anything.
#define PPM_DMA_OVERBUDGET      0
#define PPM_DMA_OVERBUDGET_NUM  3
#define PPM_DMA_OVERBUDGET_DEN  2

// Size of the real sprite allocation table (mame.h: sat_data[144]). The relink
// pass is bounded by this, not by the 80 the snapshot caps at - a link byte can
// legally name entry 143, and the old visited[10] bitmap was being indexed out of
// bounds by every node above 79.
#define PPM_SAT_ENTRIES         144

// Event log instead of the object-table record. 0 keeps the existing capture.
#define PPM_EVENT_LOG           0

// ---------------------------------------------------------------------------
// INLINE COMPOSITION - the actual root cause of the mask position.
//
// krikzz's firmware QUEUES every sprite command and renders the whole queue in
// one batch at frame end:
//
//     void ppm_obj_add(uint8_t num) { *ppm_drawListPtr++ = num; }   // queue only
//     cmd_AF_frame_end() -> render everything
//
// Genesis Plus GX composes each one AS THE COMMAND ARRIVES:
//
//     case 0xAD: paprium_sprite(data);   // appends at sat_count, right now
//
// The game's real sequence is 0xAD x17, then it writes its sprite masks, then
// more 0xAD. GPGX interleaves exactly that, so its rooftop masks land at 31-36.
// We defer everything, so the masks - and anything else the 68000 writes into
// the SAT mid-frame - are already in the table before we append a single sprite:
//
//     emulator   0-13 HUD/dummies   14-30 composed   31-36 MASKS   37+ composed
//     ours       0-13 HUD/dummies   14-19 MASKS      20-42 composed
//
// Entries 0-13 match tile for tile, so this is not the 68000 behaving
// differently. It is our ordering.
//
// That is why PPM_MASK_AFTER_INDEX was never tunable: the mask position is not a
// number to pick, it is an ordering we removed - and no amount of relinking
// afterwards can reconstruct it, because by then the interleaving is gone.
//
// ppm_block_unpack_addr is the one frame-scoped global involved: a scratch
// allocator the batch reset before rendering. It moves to frame start.
#define PPM_INLINE_COMPOSE      1

// MOVED TO THE TOP 2026-09-03. It used to sit further down the file, BELOW
// ppm_dma_refresh and ppm_obj_frame_start - so the `#if PPM_SAT_SNAPSHOT` guards
// inside those two functions saw the macro UNDEFINED and compiled their counters
// out entirely. Both read 0 on hardware, which was taken as evidence that 0xAE
// was not dispatched and cost two wrong theories, one of which briefly implicated
// the shipped release. The dispatch counter added in paprium.c then measured
// 0xAE at 30,585 against 0xAF at 30,584.
//
// A guard placed above its own #define is silently false. Keep every switch here.
// PPM_SAT_SNAPSHOT lives in mame.h, NOT here.
//
// It was in this file twice over, and both times a `#if PPM_SAT_SNAPSHOT` that
// could not see it silently compiled a counter out and the zero was then read as
// a measurement. First below its own use in this file; then in paprium.c, which
// is a different translation unit and never saw a mame.c #define at all - so the
// 0xAE/0xAF/0xAD dispatch counters read zero and the decoder announced "0xAE is
// NOT dispatched" about a chip that dispatches it 30,585 times.
//
// A switch that guards code in more than one file belongs in the header.
// 2026-09-01: 13, from the second elevator capture, where the tester identified
// every group from a rendered layout AND photographed the screen so nothing was
// recalled from memory:
//
//     our #1-#5    entries 20-24   (unidentified, foreground)  keep unmasked
//     our #6-#10   entries 25-29   PLAYER                      keep unmasked
//     our #11      entry  30                                   keep unmasked
//     our #12-#13  entries 31-32   npc                         keep unmasked
//     our #14-#15  entries 33-34   SCROLLING ENEMY             should be masked
//     our #16-#23  entries 35-42   the elevator it rides       should be masked
//
// so the masks belong immediately after our 13th composed sprite.
//
// The previous value, 8, came from an earlier frame with a different object set.
// In THIS frame our #8 is entry 27, which is inside the player - 8 would have
// hidden his back half. Same scene, different frame, different answer.
//
// That is the open question about this whole approach: whether one constant can
// be right game-wide, or whether the boundary between foreground and background
// moves with whatever objects happen to be alive. The tester's position is that a
// fixed number should work if the render ORDER is consistent, and that fixing one
// scene fixes the others. This build tests exactly that - if 13 also behaves in
// the rooftop, the constant generalises and the approach is viable.
//
// KNOWN LIMITATION - this number cannot serve both scenes. In the rooftop capture
// the player occupies our entries #3-#10, so 8 would splice the masks through the
// middle of him. That frame wanted ~18. A fixed count is scene-specific, which is
// why relocating masks by position is a PROBE and not the fix.
//
// The fix is the timing relationship: get our composition to happen before the
// 68000 writes its masks, so they land where hardware puts them without help.
// Expect elevator better, rooftop possibly worse with this build.

#define PPM_MAX_VRAM_SLOTS      64
#define PPM_OBJECTS_COUNT       64
#define PPM_MAX_OBJ_BLOCKS      32

// ---------------------------------------------------------------------------
// CHIP SPRITE CACHE (2026-10-08; differences D02, D03 and D04)
//
// As the real cart's STM32 program does it, from our own study of how the cart behaves. The program image:
// the cart program, Thumb-2, linked at $08010000
// (image offset = address - $08010000). The sprite composer runs from RAM at
// $20002F9C; every composer address below is its FLASH copy (RAM address =
// flash address - $0802E590 + $20002500, so $0802F02C runs at $20002F9C).
//
// The chip keeps its tables per VRAM id; the id of the chip's slot n is
// $08025DB8[n], and our slot x is the chip's slot n = x + 1. So:
//   $200129EC[id]   countdown byte, $20 on use or load ..... ppm_chip_cd[x]
//   $2001346C, count $20013730   list A (free) .............. ppm_chip_list[0], ppm_chip_n[0]
//   $200070E4, count $20012AD0   list B (idle) .............. ppm_chip_list[1], ppm_chip_n[1]
//   $20013298, count $20013094   list C (used last frame) ... ppm_chip_list[2], ppm_chip_n[2]
//   $20008164[block] block->id, $20012AD4[id] id->block .... ppm_vram_slots[x].block_num (searched)
//   $20010028       load (stream) list count ............... ppm_chip_loads
//
// D02 PPM_CHIP_CACHE_LISTS: countdown := $20 on every use or load; every AE ages
//     the slots into lists A/B/C; a miss takes list A, then B, then the piece's
//     related block, then C, and only then drops the piece. Replaces the LRU
//     victim search; PPM_PIN_FALLBACK's pinning is compiled out while it is on.
// D03 PPM_CHIP_CACHE_CLAIM: every list is popped from its END, which is the lowest
//     slot (the aging walks the slots downwards), and slot -> VRAM id follows the
//     chip's table $08025DB8. Claim order only exists on the lists, so this needs
//     PPM_CHIP_CACHE_LISTS. Set to 0 (with the lists on) the lists are popped from
//     their FRONT, highest slot first, and our old slot -> id map is used.
//     CLAIM also writes a load's DMA descriptor words in the chip's order
//     ($0802F69E-$0802F6C6). The register words still come before the two command
//     words in either order, so the VDP ends up doing the same transfer.
// D04 PPM_CHIP_CACHE_MISS: a piece that cannot be loaded is dropped alone - no SAT
//     entry, the object's other pieces are drawn, its animation advances. No
//     whole-object rewind and no ppm_vram_find_block, so never VRAM tile 0.
// PPM_CHIP_LOAD_CAP: part of the chip's miss path ($0802F1D8-$0802F1DE): no load
//     once 15 are listed. 0 = off. Needs PPM_CHIP_CACHE_MISS. The count is cleared
//     at AE ($08018FE2-$08018FE8) and by the load-list flush $08018FFC, which both
//     AF ($080190D2) and B1 ($0801BFBA) call: see ppm_chip_flush_loads().
// The four switch defaults are in mame.h, so that paprium.c's B1 handler sees them.
// Left as ours here (other differences, not done the chip's way in this section): clipping (D24; the s1 images do it
// the chip's way, PPM_CHIP_CLIP in ppm_obj_render), the attribute word (D23; the s1 images do it the chip's way since
// 2026-10-18, first on test build 4; PPM_CHIP_ATTR). The animation queue (D06) and the terminal end (D40) follow the
// chip under PPM_CHIP_ANIM_QUEUE and PPM_CHIP_ANIM_END: see CHIP ANIMATION QUEUE below. The budget
// gate and the floor (D09), the pose pre-check and hold (D07) and the $1F1A ready flag
// (D18) follow the chip under their own switches: see CHIP DMA BUDGET AND POSE HOLD below.
// EC (D08), B0 (D20) and 81 (D25) follow the chip under PPM_CHIP_EC, PPM_CHIP_B0 and
// PPM_CHIP_81: see CHIP EC, B0 AND 81 below. With PPM_CHIP_EC off, only EC's list
// rebuild after a shrink follows the chip (ppm_chip_rebuild, from ppm_vram_set_budget); the EC
// gate and the flush of slot n itself (the chip's loop $08017F18-$08017F3A starts AT the
// new count, so our slot count-1 keeps its block) do not.
#if PPM_CHIP_CACHE_CLAIM && !PPM_CHIP_CACHE_LISTS
#error PPM_CHIP_CACHE_CLAIM is the pop end of the chip lists, so it needs PPM_CHIP_CACHE_LISTS
#endif
#if PPM_LIST_ORDER_VRAM && (PPM_CHIP_CACHE_LISTS || PPM_CHIP_CACHE_MISS)
#error the chip cache switches assume the slot loader, not the retired PPM_LIST_ORDER_VRAM stream
#endif

// ---------------------------------------------------------------------------
// CHIP DMA BUDGET AND POSE HOLD (2026-10-08; differences D09 and D07)
//
// Same chip image and address convention as above (composer flash $0802F02C, runs
// at $20002F9C). The composer copies five RAMDP words into locals at entry and
// works on the locals for the whole AD:
//   $0802F03A-$0802F046  sp[8]   := $1F12, the frame budget        (read only)
//   $0802F048-$0802F04E  sp[$18] := $1F14, the whole-frame budget  (read only)
//   $0802F050-$0802F056  sp[0]   := $1F10, words used: +$110 per load
//   $0802F058-$0802F05E  sp[4]   := $1F18, SAT entries
//   $0802F060-$0802F068  sp[$C]  := $1F16, DMA descriptors: +1 per load
// and stores $1F10, $1F18 and $1F16 back at exit ($0802F3CA-$0802F3E6). $1F12 and
// $1F14 have no writer anywhere in the image (every literal load of $1F10-$1F1A:
// the composer entry/exit above, the AF close $0801916C/$0801918E/$08019142/
// $080191BC/$080190D6 and $080195B2 = $1F1A). AE ($0801BFAC -> $08018FBC) touches
// neither $1F10 nor $1F14: the game itself resets $1F10 at AE and writes
// $1F14 = $1F12 - $1F10 after its own DMA appends (ROM $3304C-$33056).
//
// D09 PPM_CHIP_BUDGET:
//   gate    no load when $1F12 <= $1F10 + $10F, i.e. $1F12 - $1F10 < $110, a signed
//           compare of the zero-extended words: $0802F1CC-$0802F1D6 (H-flip
//           $0802F4C4-$0802F4CE, pre-load pass $0802F30A-$0802F316)
//   charge  $1F10 += $110 kept to 16 bits (uxth): $0802F6C8-$0802F6D6 (H-flip
//           $0802F62C-$0802F63A, pre-load pass $0802F7B0-$0802F7BA)
//   ppm_chip_f10 / ppm_chip_f12 are sp[0] / sp[8]: read where our composer starts
//   (ppm_obj_render, before the pose is looked at), $1F10 written back at its exits.
//   Replaces our gate on $1F14 >= $110, $1F14 -= $110 per load, the AE rewrite
//   $1F14 = $1F12 - $1F10 (ppm_dma_refresh) with its u16 wrap, and the
//   PPM_DMA_FLOOR_BLOCKS floor (forced to 0 in mame.h).
//
// D07 PPM_CHIP_POSE_HOLD (needs D09, D02 lists, D04 per-piece miss, sticky switch):
//   n = frame word bits 24-28, the blocks the pose declares ($0802F09A-$0802F0B6)
//   $0802F0B8-$0802F0C4  $1F10 + n*$110 <= $1F12: the pose is drawn ($0802F0C6)
//   $0802F2A0-$0802F2AA  else n*$110 <= $1F14: HOLD ($0802F3C0)
//   $0802F2AC-$0802F5B2  else PROGRESSIVE: a pose with no pieces is drawn
//                        ($0802F2BC-$0802F2C6); otherwise one pass over its pieces,
//                        no SAT: resident -> countdown $20; missing -> gate, 15-load
//                        cap, list A, list B (no related block, no list C), claim.
//                        No piece missing -> the pose is drawn and the frame advances
//                        ($0802F5B0 -> $0802F0C6); else HOLD ($0802F5AE -> $0802F3C0)
//   HOLD                 $0802F3C0-$0802F3C8, $0802F404-$0802F41C -> $0802F108: the
//                        previous frame (handle+4) is drawn through the normal
//                        per-piece path, the frame pointer stays; no previous frame
//                        -> nothing drawn ($0802F3C8 -> $0802F3CA). Returns 0.
//   Ours draws after advancing, so "the pose about to be drawn" is the frame
//   handle->anim_offset points at after the switch / advance, and a HOLD is the
//   existing rewind (blocks_available = false): the previous pose is drawn and the
//   frame stays. A held switch stays pending through PPM_STICKY_SWITCH (on the chip
//   the restart already sits in the handle's frame pointer, $0801956E-$0801958C).
//   "The previous pose" is the chip's handle+4, kept in handle->lastDisplayedOffset:
//   the frame the normal path last drew ($0802F0CE), 0 after a restart with objID
//   bit 15 ($080195B8-$080195BE), and NOT cleared by a terminal end.
//   A hold with no previous frame clears objID bit 15 all the same: the chip clears
//   it in the restart path before the composer runs ($080195B8-$080195BC), held or not.
//   With PPM_CHIP_ANIM_QUEUE (D06) ours keeps the chip's own frame pointer instead:
//   anim_offset is handle+0, the frame to draw next, stepped when a pose is drawn; a
//   HOLD draws handle+4 and leaves handle+0 alone, with no rewind and no sticky switch
//   (see CHIP ANIMATION QUEUE, before ppm_obj_render).
//   Not done the chip's way: the 50 Hz skip ($0802F5B4, D39).
//
// D18 PPM_CHIP_READY_FLAG (needs D07): the composer returns 0 for every hold
// ($0802F3C0-$0802F3C4, sp[$28] := 0) and 1 for a drawn pose ($0802F0FC-$0802F102). The
// AD handler keeps handle+$C: := 0 by a +$A restart ($080194E2-$080194E6 test, $0801958A
// clear), := 1 by a drawn return or an empty frame pointer ($0801952A-$08019530). A 0
// return with handle+$C still 0 writes $1F1A := 0 ($080195A0-$080195B4). The game sets
// $1F1A to 1 at every AE ($30F92) and its ready gate ($7CD32, polled at $7EA3C, 141
// stage-script call sites) waits on it, so a stage script waits until a newly started
// object is actually on screen. handle+$C is kept in ppm_chip_shown[] (not in ppm_obj,
// whose layout the switches leave alone).
#if PPM_CHIP_POSE_HOLD && !PPM_CHIP_BUDGET
#error PPM_CHIP_POSE_HOLD reads the chip budget words ($1F10 with every load counted in it, $1F14 as the game wrote it), so it needs PPM_CHIP_BUDGET
#endif
#if PPM_CHIP_POSE_HOLD && !(PPM_CHIP_CACHE_LISTS && PPM_CHIP_CACHE_MISS)
#error PPM_CHIP_POSE_HOLD pre-loads from the chip lists A and B and draws a held pose through the per-piece miss path, so it needs PPM_CHIP_CACHE_LISTS and PPM_CHIP_CACHE_MISS
#endif
#if PPM_CHIP_POSE_HOLD && !PPM_STICKY_SWITCH && !PPM_CHIP_ANIM_QUEUE
#error PPM_CHIP_POSE_HOLD keeps a held switch pending through PPM_STICKY_SWITCH (or by the frame pointer of the chip, PPM_CHIP_ANIM_QUEUE); without either a held switch is lost, which the chip never does
#endif
#if PPM_CHIP_BUDGET && PPM_LIST_ORDER_VRAM
#error PPM_CHIP_BUDGET assumes the slot loader, not the retired PPM_LIST_ORDER_VRAM stream
#endif
#if PPM_CHIP_READY_FLAG && !PPM_CHIP_POSE_HOLD
#error PPM_CHIP_READY_FLAG clears $1F1A on a D07 hold ($080195A0-$080195B4), so it needs PPM_CHIP_POSE_HOLD
#endif
#if PPM_CHIP_READY_FLAG && !PPM_ANIM_FLAG_SEMANTICS
#error PPM_CHIP_READY_FLAG reads +$A as the one-shot restart flag of the game ($080194E2-$080194E6), so it needs PPM_ANIM_FLAG_SEMANTICS
#endif

// ---------------------------------------------------------------------------
// CHIP EC, B0 AND 81 (2026-10-08; differences D08, D20 and D25)
//
// Same chip image and address convention as above. H = $2000FB1C is the chip's
// sprite-engine block: H+$400 the engine flag, H+$402 the slot count (our
// ppm_vram_max_slot), H + 16*slot the 64 object handles: +0 frame pointer (our
// anim_offset), +4 last drawn frame (lastDisplayedOffset, D07), +8 the queued anim's
// first frame (chip_queued, ours' handle bytes 12-15, D06; none with PPM_CHIP_ANIM_QUEUE
// off), +$C drawn since restart (ppm_chip_shown, D18).
//
// Engine flag (EC and B0): byte H+$400, set to 1 by the engine init $08019734 at
// $080197C2-$080197CA, which the C6 setup job runs ($0801A54A-$0801A552, with C6's 6th
// and 7th longs); cleared only at app init ($0801F9E6-$0801F9EA, $0801FAFE-$0801FB02).
// Ours: ppm_chip_engine_ready in paprium.c, set at the end of cmd_C6_setup_data and
// never cleared (power-on bss). EC and B0 are refused while it is 0.
// The engine init begins with the B0 worker's steps ($0801973C-$080197B8, the same as
// $08019410-$0801948A), so with PPM_CHIP_B0 ours' C6 runs ppm_chip_b0_reset() before it
// raises the flag. The chip does that for the FIRST C6 only: its C6 handler $0801B1FA
// completes without queuing the setup job once the word $2001341C != 0
// ($0801B204-$0801B20C), and the job sets that word to 1 ($0801A346); only the reset
// path clears it (Reset_Handler $08024BF8 -> main $080153BC -> $0801FAE4, $0801FAF0).
// So ours resets the engine only while the flag is still 0. (Ours re-runs its data
// setup on a later C6, which the chip does not: a C6 difference, not followed here.)
//
// D08 PPM_CHIP_EC. Gate $0801B152-$0801B178 (paprium.c cmd_EC_vram_budget; table entry
//   $2C, shared by $AC and $EC): engine flag set, bit 14 of the posted word set (the
//   $EC form), arg0 == 0, arg1 <= $80 (bhi); then $0801CD5E-$0801CD60 calls the worker
//   $08017EE0(0, arg1), ppm_chip_ec_count() below:
//   $08017EF4-$08017EF6  old := count, count := new
//   $08017EFA-$08017EFC  old <= new (bls): return. A grow stores the count only; the
//                        new slots join the lists at the next AE aging.
//   $08017F18-$08017F3A  shrink: for chip slots s = new .. old INCLUSIVE (ble), id =
//                        $08025DB8[s]; if id->block[id] != 0: block->id[block] := 0
//                        ($08017F26), id->block[id] := 0 ($08017F2A), countdown[id] := 0
//                        ($08017F30). Slot new itself is flushed although it stays
//                        inside the count. Chip slot s is our x = s - 1; chip slot 0 is
//                        id 0, which never holds a block.
//   $08017F3C-$08017F90  shrink: the list rebuild, ppm_chip_rebuild() (count 0: all
//                        three lists empty)
//   Deviation, the count range: the gate takes counts up to $80. The chip's aging then
//   skips every AE (count above $35, $08017FEA-$08017FEE), and a later shrink would
//   walk $08025DB8 past its $36 entries into the DMA word table $08025DF0 (id $80).
//   Ours keeps the $35 cap (64 slots, PPM_SLOT_ID defined to slot $34). The game never
//   posts above $35: the 24 ROM call sites of its EC post routine $3106E push arg0 0
//   and a count from $01..$35, and every captured EC is $EC00, arg0 0, $01..$35.
//   Not followed: the refusal's $1FE6 bit 9 and error log (0x08020B24, codes 6 and 7).
//   The chip clears bit 9 again at the next command start ($0801BA62-$0801BA70), which
//   our command handler does not, so the bit would stick here.
//
// D20 PPM_CHIP_B0. Entry $0801AD3C-$0801AD6A (paprium.c cmd_B0_sprite_init; table entry
//   $30, shared by $B0 and $F0; no bit-14 or argument test): engine flag 0 -> refusal
//   (code 6); else $0801AD48 -> $0801BFC2 -> the worker $0801940C-$0801948E,
//   ppm_chip_b0_reset() below:
//   $08019438-$0801943E  load-list count $20010028 := 0 ......... ppm_chip_loads
//   $08019440-$0801944C  list counts A, B, C := 0 ................. ppm_chip_n[]
//   $0801944E-$08019468  id->block, countdowns, block->id := 0 .... ppm_vram_reset_blocks(0)
//   $0801946C-$08019482  all 64 handles: +0, +4, +8 := 0, +$C := 0 . ppm_object_handles[]
//                                                                    (+8: chip_queued, D06),
//                                                                    ppm_chip_shown[]
//   $08019484-$0801948A  slot count H+$402 := 0, until the next EC . ppm_vram_max_slot
//   B0 writes no RAMDP, so the $1F20-$1F8F clear (GPGX's paprium_sprite_init) goes with
//   the switch on. Not followed (no counterpart here): the AE aging call $08019410 (its
//   lists and countdowns are cleared right after), H+$403 += 1 ($08019414-$0801941C, the
//   AE counter, D10; the s1 images count it in core/dispatch f_b0), FPGA +$16 := 1
//   ($0801941E-$08019426), $1FE4 bit 8 cleared
//   ($08019428-$08019436). Of ours' handle, only the chip's own fields are cleared: +0
//   (anim_offset), +4 (lastDisplayedOffset), +8 (chip_queued, ours' bytes 12-15, with
//   PPM_CHIP_ANIM_QUEUE) and +$C (ppm_chip_shown). Ours' crtAnim and counter (and, with
//   PPM_CHIP_ANIM_QUEUE off, prev_next and queue_age in bytes 12-15) are not chip fields;
//   they mirror the game's object
//   record, which B0 leaves alone, so they are kept. At the next AD an object the game
//   has not restarted takes ours' next-frame path, finds anim_offset 0 and draws nothing
//   (ppm_chip_shown := 1), as the chip does: frame pointer 0 and +$A == 0 ->
//   $08019524-$08019530, +$C := 1, nothing drawn. (With PPM_CHIP_ANIM_QUEUE a queued anim
//   still moves into +8 and the record first, $080194EC-$08019522, as on the chip.)
//
// D25 PPM_CHIP_81: the chip's 81 ($0801AFC4-$0801AFE4) sets flags only and touches no
//   sprite state and no RAMDP: see paprium.c cmd_81_init.

#if PPM_CHIP_CACHE_CLAIM
// slot -> VRAM id, the chip's table $08025DB8: slot n <= $31 -> id n, slots $32..$35
// -> ids $7F, $7E, $7D, $7C. Our slot x = n - 1. VRAM byte address = id << 9.
#define PPM_SLOT_ID(x)          ((x) <= 0x30 ? (x) + 1 : 0xB0 - (x))
#else
#define PPM_SLOT_ID(x)          ((x) + ((x) <= 0x30 ? 1 : 0x4b))
#endif

void ppm_vram_reset_blocks(uint16_t last_block);
void ppm_close_sprite_table();
void ppm_obj_render(uint16_t obj_slot);
#if PPM_CHIP_CACHE_LISTS
// the piece's size byte rides along for the related-block rule ($0802F248-$0802F26A)
uint16_t ppm_vram_load_block(uint16_t num, uint8_t size);
#define PPM_LOAD_BLOCK(num, size)   ppm_vram_load_block((num), (size))
#else
uint16_t ppm_vram_load_block(uint16_t num);
#define PPM_LOAD_BLOCK(num, size)   ppm_vram_load_block(num)
#endif
uint16_t ppm_vram_find_block(uint16_t num);

ppm_vram_slot ppm_vram_slots[PPM_MAX_VRAM_SLOTS];
#if PPM_LIST_ORDER_VRAM
// The retail stream, as GPGX's paprium_sprite does it: per object, per sprite
// with a block, off-screen or not, in order - copy the sprite's tiles into
// staging at the staging cursor, queue one DMA of that size to the VRAM
// cursor, remember the tile, advance both cursors by the sprite's own size.
static uint32_t ppm_stream_vram;    // VRAM byte address of the next sprite's tiles (0x200 at frame start)
static uint32_t ppm_stream_walked;         // sprites streamed this frame
static uint32_t ppm_stream_walked_shadow;  // last frame's count, read by the ring
static uint32_t ppm_stream_stage;   // SDRAM staging cursor (0x9000 at frame start)
static uint32_t ppm_stream_over;    // sprites that did not fit staging or the DMA list
static void ppm_stream_dma(uint32_t vram_addr, uint32_t bytes) {
    uint32_t words = bytes >> 1;
    ppm_dma_cmd *e = &ppmio.ramdp->dma_cmd[ppmio.ramdp->dma_cmd_count++];
    ppmio.ramdp->dma_remaining -= (words + 0x10);
    hb_w8(9, 3); hb_w16(14, (u16)(vram_addr >> 5)); hb_w16(16, (u16) ppm_stream_stage); hb_w16(18, ppmio.ramdp->dma_cmd_count); hb_w16(20, ppmio.ramdp->dma_remaining);
    e->autoinc = 0x8f02;
    e->lenH = 0x9400 | ((words >> 8) & 0xFF); e->lenL = 0x9300 | (words & 0xFF);
    e->srcH = 0x9700; e->srcM = 0x9660; e->srcL = 0x9500;              // 0xC000, the window
    // VDP DMA control words from the BYTE address, as GPGX builds them
    // (0x4000 | A13..A0, then 0x80 | A15..A14). The slot loader's formula
    // takes a 0x200-byte SLOT index; fed a tile index it lands every sprite
    // 16x further along VRAM (title chaos with an aligned cursor).
    { uint32_t command = ((0x4000u | (vram_addr & 0x3FFFu)) << 16) | (0x0080u | ((vram_addr >> 14) & 3u));
      e->cmdH = command >> 16; e->cmdL = command; }
}
// Walk one object's sprite list. tiles[x] receives each sprite's VRAM tile (or 0
// if it has no block / did not fit). Returns false if any block failed to load.
static bool ppm_stream_walk(ppm_spr_data_hdr *spr_info, uint16_t *tiles) {
    bool ok = true;
    ppm_spr_data *sd = &spr_info->sprites[0];
    for (uint16_t x = 0; x < spr_info->count; sd++, x++) {
        hb_w8(11, (u8) x);
        tiles[x] = 0;
        if (!sd->blockNum) continue;
        uint16_t slot1 = ppm_vram_load_block(sd->blockNum);        // cache slot + 1, or 0
        uint32_t w = ((sd->size >> 2) & 3) + 1, h = (sd->size & 3) + 1, bytes = w * h * 0x20;
        if (!slot1 || ppm_stream_stage + bytes > PPM_SCRATCH_END || ppmio.ramdp->dma_cmd_count >= 120) {
            // no cache slot, or out of staging / descriptors: leave this sprite's VRAM
            // stale but KEEP THE CURSOR MOVING, so every later sprite lands where the
            // game's layout expects. Skipping it shifted the whole title screen.
            if (!slot1) ok = false; else ppm_stream_over++;
            tiles[x] = (uint16_t)(ppm_stream_vram >> 5);
            ppm_stream_vram += bytes;
            continue;
        }
        memcpy(&ppmio.sdram[ppm_stream_stage],
               &ppmio.sdram[PPM_BLOCK_CACHE_BASE + (uint32_t)(slot1 - 1) * 0x200 + (uint32_t) sd->offset * 0x20], bytes);
        ppm_stream_dma(ppm_stream_vram, bytes);
        ppm_stream_walked++;
        tiles[x] = (uint16_t)(ppm_stream_vram >> 5);
        ppm_stream_vram += bytes; ppm_stream_stage += bytes;
    }
    return ok;
}
#endif
uint8_t ppm_drawList[PPM_OBJECTS_COUNT]; // contains slot #
uint8_t *ppm_drawListPtr;
uint16_t ppm_vram_max_slot;

#if PPM_CHIP_CACHE_MISS && PPM_CHIP_LOAD_CAP
static uint8_t ppm_chip_loads;          // $20010028: loads listed since the last AE or flush (AF, B1)
#endif
#if FW_S1
#if !(PPM_CHIP_CACHE_MISS && PPM_CHIP_LOAD_CAP)
#error stage 1 pushes the chip's load list: it needs the chip's count (PPM_CHIP_CACHE_MISS, PPM_CHIP_LOAD_CAP)
#endif
// With MCU interface v1.2 (the s1 images): the load list itself, the flash address of each block in load order, which the
// chip's flush pushes into its FPGA's queue last to first ($08019020-$0801907A; core/dispatch flush_regs) and the
// RTL decodes. The count is ppm_chip_loads: every place that clears it (AE, B0, B1, the AF close) clears the list.
static uint32_t ppm_chip_load_addr[PPM_CHIP_LOAD_CAP];
uint32_t ppm_chip_load_list(const uint32_t **list) { *list = ppm_chip_load_addr; return ppm_chip_loads; }
#endif
#if PPM_CHIP_BUDGET
static uint16_t ppm_chip_f10;           // composer sp[0]:  $1F10 at entry ($0802F050-$0802F056), +$110 per load, stored at exit
static uint16_t ppm_chip_f12;           // composer sp[8]:  $1F12 at entry ($0802F03A-$0802F046), the frame budget
#endif
#if PPM_CHIP_POSE_HOLD
static uint16_t ppm_chip_f14;           // composer sp[$18]: $1F14 at entry ($0802F048-$0802F04E), the whole-frame budget
static uint8_t ppm_chip_ab_only;        // set during the D07 pre-load pass: claims from lists A and B only
#endif
#if PPM_CHIP_READY_FLAG
static uint8_t ppm_chip_shown[PPM_OBJECTS_COUNT];   // D18: the chip's handle+$C, 0 = restarted and not drawn since
#endif
// D06's handle+8 (the queued animation's first frame, 0 = none) is ppm_obj.chip_queued (mame.h),
// bytes 12-15 of ours' handle, with PPM_CHIP_ANIM_QUEUE: no array of its own.
#if PPM_CHIP_CACHE_LISTS
#define PPM_CHIP_A              0       // free: countdown 0 (never used, or idle ~31 frames)
#define PPM_CHIP_B              1       // idle: countdown 1..$1E after aging (2..$1F minus 1, $08018024-$0801802E)
#define PPM_CHIP_C              2       // used last frame: countdown $1F after aging
static uint8_t ppm_chip_cd[PPM_MAX_VRAM_SLOTS];                 // $200129EC[id]
static uint8_t ppm_chip_list[3][PPM_MAX_VRAM_SLOTS];            // $2001346C / $200070E4 / $20013298
static uint8_t ppm_chip_n[3];                                   // $20013730 / $20012AD0 / $20013094

// AE aging, $08017FDC-$08018716 (the slot count picks an entry point through the
// jump table $08025838 into an unrolled walk) with its out-of-line steps
// $08018932-$08018FB0:
//   $08017FE0-$08017FEE  slot count ($2000FB1C+$402) above $35: nothing is aged
//   walk the chip's slots count..1 (ids $08025DB8[count] down to [1]), each once:
//     countdown $20   -> countdown $1F, append to list C   (e.g. $08018F74-$08018F80)
//     countdown 0, 1  -> countdown 0,   append to list A   (e.g. $08018F84-$08018F90)
//     2..$1F          -> countdown - 1, append to list B   (e.g. $08018024-$0801802E)
//   $0801870A-$08018714  store the three counts
// Appending while walking down leaves the highest slot first and slot 1 last.
static void ppm_chip_age(void) {
    uint8_t na = 0, nb = 0, nc = 0;
    if (ppm_vram_max_slot > 0x35) {
        return;
    }
    for (uint16_t x = ppm_vram_max_slot; x-- > 0;) {
        uint8_t c = ppm_chip_cd[x];
        if (c == 0x20) {
            ppm_chip_cd[x] = 0x1F;
            ppm_chip_list[PPM_CHIP_C][nc++] = (uint8_t) x;
        } else if (c <= 1) {
            ppm_chip_cd[x] = 0;
            ppm_chip_list[PPM_CHIP_A][na++] = (uint8_t) x;
        } else {
            ppm_chip_cd[x] = c - 1;
            ppm_chip_list[PPM_CHIP_B][nb++] = (uint8_t) x;
        }
    }
    ppm_chip_n[PPM_CHIP_A] = na;
    ppm_chip_n[PPM_CHIP_B] = nb;
    ppm_chip_n[PPM_CHIP_C] = nc;
}

// EC shrink, list rebuild $08017F3C-$08017F90: walk slots count..1 again, countdowns
// untouched: $1F -> C ($08017F6E-70, $08017FA0-A8), 0 -> A ($08017F72-84), else -> B
// ($08017F5A-60); counts stored $08017F86-$08017F90. (EC grow stores the count only.)
static void ppm_chip_rebuild(void) {
    uint8_t na = 0, nb = 0, nc = 0;
    for (uint16_t x = ppm_vram_max_slot; x-- > 0;) {
        uint8_t c = ppm_chip_cd[x];
        if (c == 0x1F) {
            ppm_chip_list[PPM_CHIP_C][nc++] = (uint8_t) x;
        } else if (c == 0) {
            ppm_chip_list[PPM_CHIP_A][na++] = (uint8_t) x;
        } else {
            ppm_chip_list[PPM_CHIP_B][nb++] = (uint8_t) x;
        }
    }
    ppm_chip_n[PPM_CHIP_A] = na;
    ppm_chip_n[PPM_CHIP_B] = nb;
    ppm_chip_n[PPM_CHIP_C] = nc;
}

// Take one slot from a list, $0802F1EE-$0802F1FE (A), $0802F226-$0802F238 (B),
// $0802F27E-$0802F28E (C): pop the last entry; it is taken if its countdown allows
// (A: == 0, B and C: <= $1F, i.e. not used this frame), else it is discarded and
// the next one popped. The shortened count is stored back ($0802F66C, $0802F7E4,
// $0802F804; $0802F818, $0802F82A, $0802F29C when the list runs out).
static int ppm_chip_take(uint8_t l, uint8_t max_cd) {
    while (ppm_chip_n[l]) {
#if PPM_CHIP_CACHE_CLAIM
        uint8_t x = ppm_chip_list[l][--ppm_chip_n[l]];          // the end: lowest slot first (D03)
#else
        uint8_t x = ppm_chip_list[l][0];                        // comparison only: the front, highest slot first
        memmove(&ppm_chip_list[l][0], &ppm_chip_list[l][1], --ppm_chip_n[l]);
#endif
        if (ppm_chip_cd[x] <= max_cd) {
            return x;
        }
    }
    return -1;
}

// Miss: which slot the piece may take. $0802F1E0-$0802F298 (the H-flip copy is
// $0802F4D8-$0802F592, the same rules).
static int ppm_chip_victim(uint16_t num, uint8_t size) {
    int x;
    if ((x = ppm_chip_take(PPM_CHIP_A, 0)) >= 0) {              // 1. list A, $0802F1E0-$0802F210
        return x;
    }
    if ((x = ppm_chip_take(PPM_CHIP_B, 0x1F)) >= 0) {           // 2. list B, $0802F212-$0802F246
        return x;
    }
#if PPM_CHIP_POSE_HOLD
    if (ppm_chip_ab_only) {                                     // D07 pre-load pass: list A $0802F320-$0802F344,
        return -1;                                              // list B $0802F346-$0802F376, then the next piece
    }                                                           // ($0802F378, $0802F810-$0802F816): no related block, no list C
#endif
    {                                                           // 3. related block, $0802F248-$0802F26A:
        uint16_t rel = (uint16_t) (num + (size >> 4) - 9);      //    block + (size byte >> 4) - 9 (uxth)
        if (rel != num && rel != 0) {                           //    same block -> skip; block->id[0] is never set
            ppm_vram_slot *slot = ppm_vram_slots;
            for (uint16_t i = 0; i < ppm_vram_max_slot; slot++, i++) {
                if (slot->block_num == rel) {                   //    resident ...
                    if (ppm_chip_cd[i] <= 0x1F) {               //    ... and not used this frame: take its slot
                        return i;
                    }
                    break;
                }
            }
        }
    }
    if ((x = ppm_chip_take(PPM_CHIP_C, 0x1F)) >= 0) {           // 4. list C, $0802F26C-$0802F296
        return x;
    }
    return -1;                                                  // 5. none: the piece is dropped, $0802F298
}
#endif

uint32_t *ppm_bgm_tracks_offsets;
uint32_t ppm_bgm_tracks_base_addr;
uint32_t ppm_bgm_unpack_addr;

uint32_t ppm_unk_data_addr;
uint32_t ppm_unk_data2_addr;

ppm_sfx *ppm_sfx_data;
uint32_t ppm_sfx_base_addr;

uint32_t ppm_anim_data_base_addr;
uint32_t *ppm_anim_data;
uint16_t ppm_anim_max_index[256];

uint32_t *ppm_gfx_blocks_offsets;
uint32_t ppm_gfx_blocks_base_addr;
uint32_t ppm_max_gfx_block;

uint32_t ppm_block_unpack_addr;   // widened 2026-09-05: PPM_SCRATCH_BASE 0x1E0000 does not fit in 16 bits
ppm_obj ppm_object_handles[PPM_OBJECTS_COUNT]; // matching intf objs
#if FW_S1   // test build S3a on (2026-10-28): F4's source is the cart chip's, in core/zoom (zoom_ss), decoded here
            // until a later change (FW_S5, below)
#include "zoom.h"
#define PPM_SCALE_STAMP_BUF     (zoom_ss.raw)
#else
uint8_t ppm_scale_stamp[64][32];
#define PPM_SCALE_STAMP_BUF     (ppm_scale_stamp)
#endif

void ppm_init_mame() {

    ppm_drawListPtr = ppm_drawList;
}

void ppm_vram_reset_blocks(uint16_t last_block) {

    ppm_vram_slot *slot = &ppm_vram_slots[last_block];

    for (uint16_t i = last_block; i < PPM_MAX_VRAM_SLOTS; slot++, i++) {
        slot->block_num = 0;
        slot->usage = 0;
        slot->age = 0;
#if PPM_CHIP_CACHE_LISTS
        ppm_chip_cd[i] = 0;
#endif
    }
}

void ppm_obj_reset() {

    ppm_vram_reset_blocks(0);

    memset((void *) ppmio.ramdp->obj_data, 0, sizeof (ppmio.ramdp->obj_data));
    ppm_drawListPtr = ppm_drawList;
}

void ppm_vram_set_budget(uint16_t blocks) {
    // paprium-pocket PROBE. Slot index maps to a VRAM byte address of
    // block_index << 9, and slots 49-52 become block_index 124-127, i.e.
    // 0xF800-0xFFFF - where a Mega Drive conventionally keeps the sprite
    // attribute table (0xF800) and the horizontal scroll table (0xFC00).
    //
    // Capturing to the elevator showed the game requesting budgets of
    // 1, 2, 29, 40, 49 and 53. Only 53 reaches slots 49-52, and the elevator is
    // the only place 53 was seen - so on this hypothesis the elevator is the one
    // scene that DMAs graphics over its own SAT and hscroll table. That predicts
    // garbage sprites at wrong priority, and scroll tearing.
    //
    // Capping at 49 keeps every slot inside 0x0200-0x63FF, which cannot collide.
    // If the corruption goes away, the hypothesis is confirmed and this is also
    // the workaround. Costs 4 blocks of streaming capacity.
    if (blocks > PPM_VRAM_SAFE_SLOTS) {
        blocks = PPM_VRAM_SAFE_SLOTS;
    }

    // temp failsafe
    if (blocks > 0x35) {
        printf("Allocation error (0x%x blocks)\n", blocks);
        blocks = 0x35;
    }
#if PPM_CHIP_CACHE_LISTS
    uint16_t old_count = ppm_vram_max_slot;
#endif
    ppm_vram_reset_blocks((ppm_vram_max_slot = blocks));
#if PPM_CHIP_CACHE_LISTS
    if (old_count > blocks) {
        ppm_chip_rebuild();                 // $08017F3C-$08017F90
    }
#endif
}

#if PPM_CHIP_EC
// D08: the chip's EC worker $08017EE0-$08017F9E, called by the gate in paprium.c
// cmd_EC_vram_budget ($0801B178 -> $0801CD5E-$0801CD60) with arg1 as the new count.
// See CHIP EC, B0 AND 81 above.
void ppm_chip_ec_count(uint16_t n) {

    if (n > 0x35) {                         // deviation: ours caps the count at $35, the last
        n = 0x35;                           // entry of the chip's slot table $08025DB8
    }
    uint16_t old = ppm_vram_max_slot;       // $08017EF4: old := count (byte H+$402)
    ppm_vram_max_slot = n;                  // $08017EF6: count := new
    if (old <= n) {                         // $08017EFA-$08017EFC (bls): grow or same, the count only
        return;
    }
    // $08017F18-$08017F3A: chip slots new..old INCLUSIVE (ble), our x = new-1 .. old-1
    uint16_t x = n ? n - 1 : 0;
    ppm_vram_slot *slot = &ppm_vram_slots[x];
    for (; x < old; slot++, x++) {
        if (slot->block_num) {              // $08017F18-$08017F20: id->block[id] != 0
            slot->block_num = 0;            // $08017F26 block->id[block] := 0, $08017F2A id->block[id] := 0
#if PPM_CHIP_CACHE_LISTS
            ppm_chip_cd[x] = 0;             // $08017F2C-$08017F30: countdown[id] := 0
#endif
        }
        slot->usage = 0;                    // ours' LRU fields (no chip counterpart), cleared
        slot->age = 0;                      // as ppm_vram_reset_blocks clears them
    }
#if PPM_CHIP_CACHE_LISTS
    ppm_chip_rebuild();                     // $08017F3C-$08017F90: walk count..1 into A/B/C
#endif
}
#endif

#if PPM_CHIP_B0
// D20: the chip's B0 worker $0801940C-$0801948E, called by the entry in paprium.c
// cmd_B0_sprite_init ($0801AD48 -> $0801BFC2). See CHIP EC, B0 AND 81 above.
void ppm_chip_b0_reset(void) {

#if PPM_CHIP_CACHE_MISS && PPM_CHIP_LOAD_CAP
    ppm_chip_loads = 0;                     // $08019438-$0801943E: load-list count $20010028 := 0
#endif
#if PPM_CHIP_CACHE_LISTS
    ppm_chip_n[PPM_CHIP_A] = 0;             // $08019440-$0801944C: list counts A $20013730,
    ppm_chip_n[PPM_CHIP_B] = 0;             // B $20012AD0 and C $20013094 := 0
    ppm_chip_n[PPM_CHIP_C] = 0;
#endif
    ppm_vram_reset_blocks(0);               // $0801944E-$08019468: id->block $20012AD4, countdowns
                                            // $200129EC and block->id $20008164 := 0
    for (uint16_t x = 0; x < PPM_OBJECTS_COUNT; x++) {             // $0801946C-$08019482: all 64 handles
        ppm_object_handles[x].anim_offset = 0;                      // +0, the frame pointer ($0801947A)
        ppm_object_handles[x].lastDisplayedOffset = 0;              // +4, the last drawn frame ($08019478)
#if PPM_CHIP_ANIM_QUEUE
        ppm_object_handles[x].chip_queued = 0;                      // +8, the queued animation ($0801947C, D06)
#endif
    }                                       // crtAnim, counter (and prev_next, queue_age with
                                            // PPM_CHIP_ANIM_QUEUE off) are ours' mirrors of
                                            // the game's record, not chip fields: kept (see above)
#if PPM_CHIP_READY_FLAG
    memset(ppm_chip_shown, 0, sizeof (ppm_chip_shown));             // $08019476: handle+$C := 0
#endif
    ppm_vram_max_slot = 0;                  // $08019484-$0801948A: slot count H+$402 := 0
}
#endif

#if FW_S5   // the s5 images (test build S3a on): the three containers through the cart chip's decoders
            // (interim/s1/bodies_s1.c)
uint32_t s5_unpack_ws(uint32_t src, uint32_t dst);
#define PPM_SETUP_UNPACK(s, d)  s5_unpack_ws((s), (d))
#else
#define PPM_SETUP_UNPACK(s, d)  ppm_unpack((s), (d))
#endif
void ppm_setup_data(uint32_t bgm_file, uint32_t unk1_file, uint32_t smp_file, uint32_t unk2_file, uint32_t sfx_file, uint32_t anm_file, uint32_t blk_file) {

    uint32_t unpack_addr = PPM_DATA_START_ADDR;

    // setup misc data (unpack some of thoses to sdram):
    // bgm data
    printf("BGM data: 0x%x\n", bgm_file);
    ppm_bgm_tracks_base_addr = bgm_file;
    ppm_bgm_tracks_offsets = (uint32_t *) & ppmio.flash[bgm_file]; // m_rom[bgm_file / 2];
    // ?? data
    printf("uk1 data: 0x%x > 0x%x\n", unk1_file, unpack_addr);
    ppm_unk_data_addr = unpack_addr;
    unpack_addr += PPM_SETUP_UNPACK(unk1_file, unpack_addr);
    unpack_addr++;
    unpack_addr &= ~1;


    //++unpack_addr &= 0xfffffffeu; // word align
    // samples data (WavPack file)
    printf("SMP data: 0x%x >  0x%x\n", smp_file, unpack_addr);
    // unpacked data is about 1.4MB
    // ?? data
    printf("uk2 data: 0x%x > 0x%x\n", unk2_file, unpack_addr);
    ppm_unk_data2_addr = unpack_addr;
    unpack_addr += PPM_SETUP_UNPACK(unk2_file, unpack_addr);
    //++unpack_addr &= 0xfffffffeu; // word align
    unpack_addr++;
    unpack_addr &= ~1;


    // sfx data
    printf("SFX data: 0x%x\n", sfx_file);
    ppm_sfx_base_addr = sfx_file;
    ppm_sfx_data = (ppm_sfx *) & ppmio.flash[sfx_file]; //m_rom[sfx_file / 2];
    ppm_sfx *fx = &ppm_sfx_data[1]; 

    for (int x = 1; x <= ppm_sfx_data[0].length; fx++, x++) {
        //printf("\tSFX 0x%x: 0x%x / 0x%x / 0x%x\n", x, swapshorts(fx->offset), fx->attributes, fx->length);
    }
    // animation data
    printf("ANM data: 0x%x > 0x%x\n", anm_file, unpack_addr);
    ppm_anim_data_base_addr = unpack_addr;
    unpack_addr += PPM_SETUP_UNPACK(anm_file, unpack_addr);
    //++unpack_addr &= 0xfffffffeu; // word align
    unpack_addr++;
    unpack_addr &= ~1;


    ppm_anim_data = (uint32_t *) & ppmio.sdram[ppm_anim_data_base_addr]; // ppm_sdram[ppm_anim_data_base_addr / 2];
    printf("anim data for 0x%x objs\n", ppm_anim_data[0]);

    for (uint16_t x = 1; x <= ppm_anim_data[0]; x++) {

        uint32_t anim_offset = ppm_anim_data[x];
        uint16_t anim_count = 0;

        //printf("offset: %x\n", anim_offset);

        while (ppm_anim_data[anim_count + (anim_offset / 4)] != 0xffffffffu) {
            anim_count++;
        }
        ppm_anim_max_index[x - 1] = anim_count - 1;
        //printf("\tobj 0x%x (0x%x): %i anims\n", x, anim_offset, anim_count);

        if (anim_offset & 0x3) {
            printf("(unaligned pointers)\n");
        }
    }

    // blocks data
    printf("BLK data: 0x%x\n", blk_file);
    ppm_gfx_blocks_base_addr = blk_file;
    ppm_gfx_blocks_offsets = (uint32_t *) & ppmio.flash[blk_file]; //m_rom[blk_file / 2];
    ppm_max_gfx_block = swapshorts(ppm_gfx_blocks_offsets[0]) - 1;
    printf("blocks addr: %x, count: %i\n", ppm_gfx_blocks_base_addr, swapshorts(ppm_gfx_blocks_offsets[0]));

    printf("unpack addr finish: 0x%x / free: 0x%x\n", unpack_addr, 0x200000 - unpack_addr);
    ppm_bgm_unpack_addr = unpack_addr;

}

u32 swapshorts(u32 val) {

    return (val >> 16) | (val << 16);
}

uint32_t ppm_unpack(uint32_t source_addr, uint32_t dest_addr) {

    return ppm_unpack_scal(source_addr, dest_addr, 0);
}

uint32_t ppm_unpack_scal(uint32_t source_addr, uint32_t dest_addr, u8 is_scaling_stamp) {

    // packed data is byte width, ^1 on all addresses to fix endian mumbo jumbo
    uint8_t code, count, data_byte;
    uint32_t copy_addr;
    uint32_t initial_dest_addr = dest_addr;
    uint8_t *packed_data = (uint8_t *) ppmio.flash; // m_rom;
    uint8_t *unpacked_data = is_scaling_stamp ? (uint8_t *) PPM_SCALE_STAMP_BUF : (uint8_t *) ppmio.sdram; // ppm_sdram;

    uint16_t copy_size, literal_size;

    //printf("unpack format: %x\n", packed_data[source_addr]);

    switch (packed_data[source_addr++ ^ 1]) {

        case 0x80:

            while ((code = packed_data[source_addr++ ^ 1])) {

                switch (count = code & 0x3f, code >> 6) {
                    case 0:
                        while (count--)
                            unpacked_data[dest_addr++ ^ 1] = packed_data[source_addr++ ^ 1];
                        break;
                    case 1:
                        data_byte = packed_data[source_addr++ ^ 1];
                        while (count--)
                            unpacked_data[dest_addr++ ^ 1] = data_byte;
                        break;
                    case 2:
                        copy_addr = dest_addr - packed_data[source_addr++ ^ 1];
                        while (count--)
                            unpacked_data[dest_addr++ ^ 1] = unpacked_data[copy_addr++ ^ 1];
                        break;
                    case 3:
                        while (count--)
                            unpacked_data[dest_addr++ ^ 1] = 0;
                        break;
                }
            }
            break;

        case 0x81: {

            // paprium-pocket: real LZO decoder, ported from Genesis Plus GX
            // (paprium.h, paprium_decoder_lzo). Stock mega-ppm ships MAME's
            // reverse-engineered heuristic here - the one whose loop terminates
            // on `!= 0x11 // unconfirmed end code` - which mis-decodes and
            // corrupts the subway among other areas. krikzz fixed this privately
            // for MisterPezz82; the public tree still has the broken version.
            //
            // Textbook LZO1X: the opcode's top bits select the format, lengths
            // use the 255-extension encoding, and `state` (literals emitted by
            // the previous instruction) selects a shorter distance encoding
            // right after a literal run - the detail reimplementations miss.
            //
            // GPGX's `size` is the absolute output cursor, which here is
            // dest_addr, so its `lz = size - lz` becomes copy_addr = dest_addr - lz.
            int len, lz, raw_n, state = 0, extra;
            uint8_t c;

            while (1) {
                c = packed_data[source_addr++ ^ 1];

                if (c & 0x80) {                      // code_80
                    raw_n = c & 0x03;
                    len = ((c >> 5) & 0x03) + 5;
                    lz = (c >> 2) & 0x07;
                    lz += packed_data[source_addr++ ^ 1] << 3;
                    lz += 1;
                }
                else if (c & 0x40) {                 // code_40
                    raw_n = c & 0x03;
                    len = ((c >> 5) & 1) + 3;
                    lz = (c >> 2) & 0x07;
                    lz += packed_data[source_addr++ ^ 1] << 3;
                    lz += 1;
                }
                else if (c & 0x20) {                 // code_20
                    len = c & 0x1F;
                    if (len == 0) {
                        extra = 0;
                        while (1) {
                            len = packed_data[source_addr++ ^ 1];
                            if (len) break;
                            extra += 255;
                        }
                        len += extra + 31;
                    }
                    len += 2;
                    c = packed_data[source_addr++ ^ 1];
                    raw_n = c & 0x03;
                    lz = c >> 2;
                    lz += packed_data[source_addr++ ^ 1] << 6;
                    lz += 1;
                }
                else if (c & 0x10) {                 // code_10
                    len = c & 0x07;
                    if (len == 0) {
                        extra = 0;
                        while (1) {
                            len = packed_data[source_addr++ ^ 1];
                            if (len) break;
                            extra += 255;
                        }
                        len += extra + 7;
                    }
                    len += 2;
                    lz = ((c >> 3) & 1) << 14;
                    c = packed_data[source_addr++ ^ 1];
                    raw_n = c & 0x03;
                    lz += c >> 2;
                    lz += packed_data[source_addr++ ^ 1] << 6;
                    lz += 16384;
                    if (lz == 16384) break;          // end of stream
                }
                else {                               // code_00
                    if (state == 0) {
                        raw_n = c & 0x0F;
                        if (raw_n == 0) {
                            extra = 0;
                            while (1) {
                                raw_n = packed_data[source_addr++ ^ 1];
                                if (raw_n) break;
                                extra += 255;
                            }
                            raw_n += extra + 15;
                        }
                        raw_n += 3;
                        len = 0;
                        state = 4;
                    }
                    else if (state < 4) {
                        raw_n = c & 0x03;
                        lz = (c >> 2) & 0x03;
                        lz += packed_data[source_addr++ ^ 1] << 2;
                        lz += 1;
                        len = 2;
                    }
                    else {
                        raw_n = c & 0x03;
                        lz = (c >> 2) & 0x03;
                        lz += packed_data[source_addr++ ^ 1] << 2;
                        lz += 2049;
                        len = 3;
                    }
                }

                state = (len > 0) ? raw_n : 4;
                copy_addr = dest_addr - lz;

                while (1) {
                    if (len > 0) {
                        unpacked_data[dest_addr++ ^ 1] = unpacked_data[copy_addr++ ^ 1];
                        len--;
                    }
                    else if (raw_n > 0) {
                        unpacked_data[dest_addr++ ^ 1] = packed_data[source_addr++ ^ 1];
                        raw_n--;
                    }
                    else break;
                }
            }
            }
            break;

        default:
            printf("unknown packer format, wrong address? (0x%x) %x\n", source_addr - 1, ppmio.ramdp->reg_cmd);
            break;
    }

    return dest_addr - initial_dest_addr;
}

void ppm_obj_add(uint8_t num) {
#if PPM_INLINE_COMPOSE
    // Compose now, exactly as GPGX's `case 0xAD: paprium_sprite(data)` does, so
    // the sprites the 68000 asked for before it writes its masks are actually in
    // the table when it writes them.
#if PPM_CHIP_ANIM_QUEUE
    if (ppmio.ramdp->obj_data[num].objID) {     // $080194DA-$080194E0: objID word 0, the AD does nothing (return 0):
        ppm_obj_render(num);                    // no restart, queue, draw, handle+$C or $1F1A (D06, CHIP ANIMATION QUEUE)
    }
#else
    ppm_obj_render(num);
#endif
    hb_w8(9, 9);
#else
    *ppm_drawListPtr++ = num;
#endif
}


// The one open question left after the ordering fix: destructibles sometimes do
// not show their destroyed sprite. ppm_obj_render drops an object outright when
// its animation index exceeds what we computed as that object's maximum, and that
// early-out is silent - it only ever printf'd, which nothing on hardware reads.
//
// This is a MEASUREMENT, not a diagnosis. If a barrel stays whole while the
// counter stays 0, that return is not the cause and the suspect is wrong.
static u16 snap_animover_hits = 0;
// The other two silent returns in ppm_block_load, both of which mean "the block
// never arrived, draw with whatever tiles happen to be there".
// DISPATCH COUNTERS. The frame tick in ppm_obj_frame_start read 0 on hardware
// while slot-freeing - which only frame_start does for active slots - says it
// runs. The offset check passed, so the zero is real and unexplained.
//
// snap_cnt_ae is incremented in cmd_AE_frame_start itself, in paprium.c, one
// call earlier than snap_frames. That pair is the discriminator:
//
//   ae > 0, frames == 0   the dispatch happens and the reporting is at fault
//   ae == 0, frames == 0  0xAE is genuinely not sent, and ppm_dma_refresh() in
//                         frame_start never runs - so the pillar fix came from
//                         frame_end NO LONGER refreshing, i.e. from us no longer
//                         clobbering a value the 68000 maintains
//
// af and ad bound the frame rate and the sprite rate for scale, and refresh
// counts the call we actually care about.
u32 snap_cnt_ae = 0, snap_cnt_af = 0, snap_cnt_ad = 0, snap_cnt_refresh = 0;
static u16 snap_dma_starved = 0;        // out of DMA budget this frame
static u16 snap_noslot      = 0;        // every VRAM slot already in use
static u16 snap_switch_refused = 0;     // animation switch refused for budget/slot, kept pending
static u16 snap_switch_retry_ok = 0;    // a pending switch that completed on a later draw
static u16 snap_floor_frames = 0;       // frames where the game's own DMA left < 1 block and the floor lifted it
#if PPM_DMA_FLOOR_BLOCKS
static u16 snap_floor_run = 0, snap_floor_run_max = 0;   // consecutive such frames, and the longest run
static u8 ppm_floor_used = 0;            // PPM_DMA_FLOOR_BLOCKS: loads granted from the floor this frame
#else
static u16 snap_floor_run_max = 0;       // no floor (PPM_CHIP_BUDGET): stays 0 in the snapshot
#endif
// EVICTION AUDIT - the firmware-only question for the elevator corruption (#8).
//
// A slot is evicted when nobody REQUESTED its block this frame (usage is cleared
// every frame in frame_start and only set by ppm_block_load). Sprites are
// re-requested every frame so their slots are safe. BACKGROUND tiles are not: the
// game DMAs the plane's name table, which keeps pointing at a tile index, but
// nothing calls ppm_block_load for it again. So a background block ages at
// usage == 0, becomes the preferred victim, and its slot is overwritten with other
// art while the plane is still displaying it.
//
// That predicts the reported symptom exactly - recognisable artwork from
// elsewhere, riding with the plane, accumulating and never recovering. It needs no
// bus tap: eviction is a decision this firmware makes and can count.
//
// The number that matters is evictions of a slot that HELD REAL ART (block_num
// non-zero) and was not re-requested. A static room should be near zero; if the
// shaft is thrashing, it will not be.
static u32 snap_evict_live  = 0;        // evicted a slot that held real art
static u16 snap_evict_frame = 0;        // this frame's count
static u16 snap_evict_worst = 0;        // worst single frame all run
static u16 snap_evict_reload = 0;       // evicted, then the SAME block reloaded later
static u16 snap_evicted_ring[32];       // recently evicted block numbers
static u8  snap_evicted_at  = 0;

// STREAM-WINDOW HANDSHAKE. Two writers point the 68000's read window:
//   0xDA  unpack to an arbitrary dest, then point at it - and the game RELIES on
//         that persisting (dropping the write regressed the cell room on hardware)
//   0xAF  rewind to 0x9000 unconditionally, every frame
// plus 0xDB, which the game uses to re-point explicitly.
//
// If the game re-points with 0xDB before every read, the rewind is harmless. If it
// leans on a 0xDA pointer surviving, an 0xAF in between hands the 68000 sprite
// blocks where background art should be - which is what the shaft garbage looks
// like. GPGX never rewinds: paprium_sprite_stop leaves decoder_ptr alone.
//
// snap_da_dest_9000 is the cheap disqualifier: if shaft 0xDAs already target
// 0x9000 the rewind is a no-op and the race does not exist.
u32 snap_da_count = 0, snap_db_count = 0, snap_af_clobber = 0;
u32 snap_da_last_dest = 0, snap_da_dest_9000 = 0;
static u8 snap_da_pending = 0;
u32 snap_loader_high_since_da = PPM_SCRATCH_BASE;   // furthest the loader has written since 0xDA
static u32 snap_frames      = 0;          // in-game frames, for a per-frame rate
u32 snap_da_other[6];                     // the non-0x9000 0xDA destinations
static u8 snap_da_other_n = 0;

// CRC RECORDER. The choreography, destinations, sources and lengths all measure
// correct - but a wrong UNPACK (right source, right destination, wrong bytes)
// fits every one of those. This hashes what actually landed.
//
// 16 bytes x 48 records in the reclaimed arena (768 of 1024), meta at +768.
// IEEE 0xEDB88320, init/final 0xFFFFFFFF, over ppmio.sdram[dst + i] with no ^1,
// so a GPGX twin over decoder_ram can be compared directly.
#define SNAP_DA_MAX   48
#define SNAP_FENCE_LEN 0x8000u
#define SNAP_CRC_TAG  0xC2C1C2C1u
// Distinct from SNAP_CRC_TAG so a decoder cannot read one card's arena as the
// other's - the two layouts share every byte of it.
#define SNAP_RING_TAG 0xB0D5E701u
#define SNAP_EP_TAG   0xE70C0DE1u          /* epoch ring; distinct from both above */

#if PPM_DA_CRC
// 768 bytes of records plus a 1 KB lookup table. The onset ring is 960 bytes and
// this MCU has no room for both, which is the other half of why the CRC card is
// retired rather than merely unread.
u32 snap_da_src[SNAP_DA_MAX];
u32 snap_da_len[SNAP_DA_MAX];
u32 snap_da_crc[SNAP_DA_MAX];
u32 snap_da_dst[SNAP_DA_MAX];
#endif
static u8 snap_da_n = 0;
u32 snap_da_repeat = 0;

u32 snap_fence_crc = 0;
u32 snap_fence_at = 0;                      // snap_frames when the fence was taken

#if PPM_DA_CRC
static u32 snap_crc_tab[256];
static u8  snap_crc_ready = 0;
#endif

#if PPM_DA_CRC
static void snap_crc_init(void) {
    for (u32 i = 0; i < 256; i++) {
        u32 c = i;
        for (u8 k = 0; k < 8; k++) {
            c = (c & 1u) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
        }
        snap_crc_tab[i] = c;
    }
    snap_crc_ready = 1;
}

// Table-driven: ~3 ms for 32 KB on this MCU. Fine for the 51 0xDA calls in a run;
// NOT fine every SAT frame, which is why the fence is throttled.
u32 snap_crc32(u32 base, u32 n) {
    if (!snap_crc_ready) {
        snap_crc_init();
    }
    const u8 *p = (const u8 *) ppmio.sdram + base;
    u32 c = 0xFFFFFFFFu;
    for (u32 i = 0; i < n; i++) {
        c = snap_crc_tab[(c ^ p[i]) & 0xFFu] ^ (c >> 8);
    }
    return c ^ 0xFFFFFFFFu;
}

void snap_fence_take(void) {
    snap_fence_crc = snap_crc32(0, SNAP_FENCE_LEN);
    snap_fence_at = snap_frames;
}
#else
void snap_fence_take(void) { }
#endif

void snap_da_note_src(u32 src, u32 len, u32 dst) {
#if !PPM_DA_CRC
    // Retired with the CRC card. The point is not just that the output has no
    // home in the arena any more - it is that hashing up to 32 KB costs ~3 ms,
    // inside the frame, and the onset ring exists to measure per-frame load
    // pressure. Leaving this in would tax the exact frames being counted.
    (void) src; (void) len; (void) dst;
#else
    u32 n = (len > SNAP_FENCE_LEN) ? SNAP_FENCE_LEN : len;
    if (snap_da_n && src == snap_da_src[snap_da_n - 1]) {
        snap_da_repeat++;
    }
    if (snap_da_n < SNAP_DA_MAX) {
        snap_da_src[snap_da_n] = src;
        snap_da_len[snap_da_n] = len;
        snap_da_crc[snap_da_n] = snap_crc32(dst, n);
        snap_da_dst[snap_da_n] = dst;
        snap_da_n++;
    }
    // Optional refresh: if this payload expanded inside the fenced region, retake
    // the fence now so it lines up with the bytes just hashed.
    if (dst + n <= SNAP_FENCE_LEN) {
        snap_fence_take();
    }
#endif
}

// paprium.c sets and clears this; it stays static here so nothing else can poke it.
void snap_da_pending_set(void)   { snap_da_pending = 1; }
void snap_da_pending_clear(void) { snap_da_pending = 0; }
void snap_da_reset_high(void)    { snap_loader_high_since_da = PPM_SCRATCH_BASE; }
void snap_da_note_other(u32 dst) {
    if (snap_da_other_n < 6) {
        snap_da_other[snap_da_other_n++] = dst;
    }
}

// WHERE THE PER-FRAME FEEDER AIMS.
//
// 0xDA turned out to be rare - 49 in a run - and 43 of those 49 targeted 0x9000.
// 0xDB is the actual per-frame feeder at 1109. So the background payload is
// decompressed into the sprite scratch pad and then read back piecemeal, while
// ppm_block_load is walking that same pad +0x200 per block every frame.
//
// ppm_block_unpack_addr IS the loader's high-water mark for the current frame, so
// [0x9000, ppm_block_unpack_addr) is exactly the region the loader has already
// overwritten. A 0xDB aiming in there is reading sprite art where the game meant
// background art.
//
// This does not yet prove #8: streets load sprites from 0x9000 too. The shaft has
// to be special - more re-points into the live region, or a payload big enough
// that it must survive frames of loading.
// CLUSTERING, not volume. A high stale count proves nothing on its own: after a
// 0xDA to 0x9000 the loader always walks that pad, so ANY later 0xDB into 0x9xxx
// registers as a smash even when the 68000 is deliberately fetching sprite tiles.
// What would distinguish a plane feed being re-read is the hits piling onto the
// SAME destination. Scattered means ordinary sprite traffic.
u32 snap_db_stale_first = 0;   // first destination seen stale
u32 snap_db_stale_same = 0;    // how many stale hits shared that exact address
u32 snap_db_below = 0;   // below the pad entirely
u32 snap_db_high = 0;    // at or above 0xF200, outside staging
u32 snap_db_last = 0, snap_db_max = 0;
// 948 of 1173 re-points aimed below 0x9000, where the firmware never unpacks
// anything. That is either the shaft's real read source or - far more likely - the
// game parking the pointer at zero between uses, which would make the whole count
// meaningless. Counting them was not enough; record WHAT they are.
// CROSS-FRAME high-water mark. The first version of this check compared a 0xDB
// destination against ppm_block_unpack_addr, which RESETS TO 0x9000 EVERY FRAME -
// so it could only ever see a same-frame overwrite, and reported zero hits by
// construction. The mechanism is inherently cross-frame: 0xDA unpacks once, the
// game reads it back over many frames with 0xDB, and every intervening frame the
// loader walks 0x9000+ again. This tracks the furthest the loader has written
// SINCE THE LAST 0xDA, which is the region the payload can no longer be trusted in.
//
// GPGX has no equivalent exposure: its 0xDA decompresses into decoder_ram, a
// private buffer, so nothing else writes there. mega-ppm shares the pad.
u32 snap_db_stale = 0;                 // aimed where the loader has since written
u32 snap_ptr_while_list_pending = 0;   // DA/DB pointer write while dma_cmd_count != 0 (list built at 0xAF, runner not yet run)
u32 snap_bgm_over = 0;
u32 snap_db_zero = 0;                  // aimed at 0 exactly: an idle/reset value
u32 snap_db_min = 0xFFFFFFFF;          // smallest NON-ZERO destination seen
u32 snap_db_ring[2];                   // two real samples, newest last
// 947 re-points aim below 0x9000 at REAL addresses (only 1 was zero), the lowest
// being 0x80, in a region the firmware never unpacks into. The global max is
// 0x9FC0 and says nothing about them. The max BELOW 0x9000 does: clustered near
// 0x80-0x100 means parking values, as meaningless as zeros; spanning to 0x8FFF
// means real read bases across a whole region.
u32 snap_db_max_below = 0;
// THE SIX. 0xDA is the only firmware writer below 0x9000, and 43 of 49 measured
// 0xDAs went to 0x9000 - so six did not. If max_below spans toward 0x8FFF, those
// six are the only candidates for having filled that region, and they are the list
// to produce rather than a writer to invent. Recorded in order, first six kept.

static u8 snap_db_ring_at = 0;

void snap_db_note(u32 dst) {
    snap_db_last = dst;
    if (dst > snap_db_max) {
        snap_db_max = dst;
    }
    if (dst >= PPM_SCRATCH_BASE && dst < snap_loader_high_since_da) {
        snap_db_stale++;               // the payload here has been overwritten
        if (!snap_db_stale_first) {
            snap_db_stale_first = dst;
        }
        if (dst == snap_db_stale_first) {
            snap_db_stale_same++;
        }
    }
    if (dst == 0) {
        snap_db_zero++;
    } else {
        if (dst < snap_db_min) {
            snap_db_min = dst;
        }
        snap_db_ring[snap_db_ring_at] = dst;
        snap_db_ring_at = (u8) ((snap_db_ring_at + 1) & 1);
    }
    if (dst < 0x9000) {
        snap_db_below++;
        if (dst > snap_db_max_below) {
            snap_db_max_below = dst;
        }
    } else if (dst >= 0xF200) {
        snap_db_high++;
    }
    // NOTE: the old same-frame test lived here and was invalid - it compared
    // against ppm_block_unpack_addr, which resets to 0x9000 every frame, so it
    // could only ever catch an overwrite within the same frame and reported zero
    // by construction. snap_db_stale above uses the cross-frame mark instead.
}
// A refusal count with no denominator is unreadable - 1176 refusals is healthy
// against forty thousand loads and alarming against twelve hundred. So count the
// successes and the frames too, and let the capture print the ratios.
u32 ppm_sptr_shadow = 0;                // last sdram_ptr the MCU wrote (RTL reg is write-only)
static u32 snap_loads_ok    = 0;        // blocks actually unpacked and queued

#if PPM_EPOCH_RING
// 10 bytes per active epoch: ack u16, oe u16, frame u16, ptr u32.
static u8  snap_ep[PPM_EPOCH_CAP * 10];
static u16 snap_ep_idx = 0;
static u32 snap_ep_seen = 0;        // active epochs committed
static u32 snap_ep_total = 0;       // every epoch, active or not
static u32 snap_ep_mism = 0;        // epochs where ack != oe
static u16 snap_ep_worst = 0;       // largest |ack - oe| in one epoch
static u32 snap_ep_first_mism = 0;  // snap_frames at the first mismatch, 0 = none
static u32 snap_ep_sum_ack = 0, snap_ep_sum_oe = 0;

// Called IMMEDIATELY AFTER every write of FPGAIO->sdram_ptr, with the pointer
// that was in force before it. The RTL latched the ended epoch on that write,
// so the read here is the epoch [ptr_prev .. this write).
void snap_epoch_note(u32 ptr_prev) {
#if PPM_EPOCH_NOTE_STUB
    (void) ptr_prev;
    return;                 // bisect: statics and layout intact, runtime path removed
#endif
    u32 v   = FPGAIO->stream_cnt;
    u16 ack = (u16) (v >> 16);
    u16 oe  = (u16) v;
    snap_ep_total++;
    if (!ack && !oe) return;                        // idle epoch, not recorded
    u16 d = ack > oe ? ack - oe : oe - ack;
    if (d) {
        snap_ep_mism++;
        if (d > snap_ep_worst) snap_ep_worst = d;
        if (!snap_ep_first_mism) snap_ep_first_mism = snap_frames;
    }
    snap_ep_sum_ack += ack;
    snap_ep_sum_oe  += oe;
    u8 *c = &snap_ep[snap_ep_idx * 10];
    c[0] = (u8)(ack >> 8); c[1] = (u8) ack;
    c[2] = (u8)(oe  >> 8); c[3] = (u8) oe;
    c[4] = (u8)(snap_frames >> 8); c[5] = (u8) snap_frames;
    c[6] = (u8)(ptr_prev >> 24); c[7] = (u8)(ptr_prev >> 16);
    c[8] = (u8)(ptr_prev >> 8);  c[9] = (u8) ptr_prev;
    snap_ep_idx = (u16)((snap_ep_idx + 1) % PPM_EPOCH_CAP);
    if (snap_ep_seen != 0xFFFFFFFF) snap_ep_seen++;
}
#endif

#if PPM_ONSET_RING
// One cell per in-game frame, overwriting the oldest once full. Both halves of
// the first byte saturate at 15: measured rates are 0.027 refusals and 0.79
// loads per frame, so four bits is generous, and a frame that somehow exceeds
// it reads as "at least 15" rather than wrapping to a small number.
static u8  snap_ring[PPM_ONSET_FRAMES * 2];
static u16 snap_ring_idx  = 0;          // next cell to write
static u32 snap_ring_seen = 0;          // frames committed, to spot a short run
static u8  snap_f_refuse  = 0;          // this frame, reset on commit
static u8  snap_f_load    = 0;
static u16 snap_f_worst   = 0;          // worst refusals in any single frame

// Commit the frame that just ENDED. Called from frame_start before
// ppm_dma_refresh(), so ramdp->dma_remaining is still last frame's leftover -
// the number that decides starvation. Refreshing first would overwrite the
// only value worth recording with a full budget.
static void snap_ring_commit(void) {
    u32 rem = ppmio.ramdp->dma_remaining;
    u32 afford = rem / 0x110;           // whole blocks still payable for
    if (afford > 255) afford = 255;
#if PPM_LIST_ORDER_VRAM
    // Under the stream, budget affordability is meaningless (charged per sprite,
    // never refused, u16 underflow). Record instead the highest VRAM tile the
    // stream's cursor reached this frame - GPGX's title stays at tiles 16-80,
    // the shaft at 16-154. A cursor past the scene's plane art is the corruption.
    afford = ppm_stream_vram >> 5; if (afford > 255) afford = 255;
#endif
    u8 *c = &snap_ring[snap_ring_idx * 2];
#if PPM_LIST_ORDER_VRAM
    // under the stream, byte 0 is the number of sprites streamed last frame
    c[0] = (u8) (ppm_stream_walked_shadow > 255 ? 255 : ppm_stream_walked_shadow);
#else
    c[0] = (u8) (((snap_f_refuse > 15 ? 15 : snap_f_refuse) << 4)
                 | (snap_f_load > 15 ? 15 : snap_f_load));
#endif
    c[1] = (u8) afford;
    if (snap_f_refuse > snap_f_worst) snap_f_worst = snap_f_refuse;
    snap_ring_idx = (u16) ((snap_ring_idx + 1) % PPM_ONSET_FRAMES);
    if (snap_ring_seen != 0xFFFFFFFF) snap_ring_seen++;
    snap_f_refuse = snap_f_load = 0;
}
#endif

// Refresh the frame's DMA budget.
//
// This used to sit in ppm_obj_frame_end, immediately before the batch render, and
// that was correct WHILE the batch was where every object got composed. Moving
// composition to the 0xAD command left it stranded: inline renders run before
// frame_end, so every one of them tested dma_remaining LEFT OVER FROM THE
// PREVIOUS FRAME, already spent down to near zero.
//
// It gates exactly one path in ppm_block_load:
//
//     if (ppmio.ramdp->dma_remaining < 0x110) return 0;   // block never loads
//
// Art already resident hits the slot cache and returns before that check, which
// is why almost everything looked right. A NEWLY needed block - the destroyed
// pillar's graphics - takes the load path, and only that one starved. The intact
// pillar you still see is a plane tile; the destroyed sprite never got its tiles.
//
// dma_total and dma_cmd_count are 68000-owned, so reading them at frame start is
// reading what the game intends for this frame.
static void ppm_dma_refresh(void) {
#if PPM_SAT_SNAPSHOT
    snap_cnt_refresh++;
#endif
#if PPM_CHIP_BUDGET
    // D09: nothing to refresh. The chip's AE ($0801BFAC -> $08018FBC) touches
    // neither $1F10 nor $1F14, and no code in the chip writes $1F14 at all; the
    // game writes it itself before the 0xAD stream (ROM $3304C-$33056).
#elif PPM_DMA_OVERBUDGET
    // paprium-pocket: DMA OVERBUDGET PROBE, DIAGNOSTIC. OFF BY DEFAULT.
    //
    // Hypothesis from the tester, and it inverts the assumption this file has
    // been carrying: on ORIGINAL HARDWARE Paprium visibly tears when the screen
    // is busy, but it does NOT lose animation. Our port is the other way round -
    // no tearing, dropped frames. If the real cartridge routinely overruns its
    // vblank and accepts tearing as the price, then respecting dma_budget exactly
    // is OUR deviation, not the safe choice, and the frozen-walk symptom is
    // self-inflicted.
    //
    // dma_budget is written by the 68000 and read by us; it is the game's own
    // statement of how many words fit in vblank. This does NOT overwrite it -
    // the game can still read back what it wrote. It only inflates the figure we
    // budget OURSELVES against, so the cartridge queues more blocks per frame.
    //
    // Expect tearing or torn tiles if it works as intended. That is the point:
    // the question is whether animation smooths out at the same time, which
    // would mean we are trading an artefact hardware also has for frames it also
    // has. If tiles corrupt without animation improving, the trade is bad and
    // this stays off.
    //
    // Numerator/denominator rather than a shift so the ratio can be tuned from a
    // single number. 3/2 = 1.5x is the first try.
    {
        uint32_t b = (uint32_t) ppmio.ramdp->dma_budget;
        b = (b * PPM_DMA_OVERBUDGET_NUM) / PPM_DMA_OVERBUDGET_DEN;
        if (b > 0xFFFF) {
            b = 0xFFFF;
        }
        ppmio.ramdp->dma_remaining = (uint16_t) b - ppmio.ramdp->dma_total;
    }
#else
    ppmio.ramdp->dma_remaining = ppmio.ramdp->dma_budget - ppmio.ramdp->dma_total;
#endif
}

void ppm_obj_frame_start() {

#if PPM_SAT_SNAPSHOT
    snap_frames++;
#endif
#if PPM_ONSET_RING
    snap_ring_commit();     // MUST precede ppm_dma_refresh() - see the note there
#endif
    ppm_drawListPtr = ppm_drawList;
#if PPM_DMA_FLOOR_BLOCKS
#if PPM_SAT_SNAPSHOT
    // Book the frame that just ended: did the floor carry any of its loads?
    if (ppm_floor_used) {
        if (snap_floor_frames != 0xffff) snap_floor_frames++;
        if (snap_floor_run != 0xffff) snap_floor_run++;
        if (snap_floor_run > snap_floor_run_max) snap_floor_run_max = snap_floor_run;
    } else {
        snap_floor_run = 0;
    }
#endif
    ppm_floor_used = 0;
#endif
#if PPM_INLINE_COMPOSE
    ppm_block_unpack_addr = PPM_SCRATCH_BASE;   // was reset by the batch; nothing else uses it
#if PPM_LIST_ORDER_VRAM
#if PPM_SFX_QUIET_DMA
    ppm_list_pending = 0;
#endif
    ppm_stream_walked_shadow = ppm_stream_walked; ppm_stream_walked = 0; ppm_stream_vram = 0x200; ppm_stream_stage = PPM_SCRATCH_BASE;
#endif
    ppm_dma_refresh();                // MUST precede any inline compose
#endif

#if PPM_SAT_SNAPSHOT
    if (snap_evict_frame > snap_evict_worst) {
        snap_evict_worst = snap_evict_frame;
    }
    snap_evict_frame = 0;
#endif

    // all blocks unused
#if !(FW_S1 && PPM_CHIP_CACHE_LISTS)   // s1 images (2026-10-17): with the chip's cache lists (D02) nothing reads a slot's
                                        // usage or age (only the 0.2.6 victim search, built without them): the 64-slot
                                        // clear and the per-hit / per-claim marks below are left out of AE's and AD's L1,
                                        // as an earlier change left the age pass out of AF's (MCU time the chip's AF close needs)
    ppm_vram_slot *slot = ppm_vram_slots;

    for (uint16_t x = 0; x < PPM_MAX_VRAM_SLOTS; slot++, x++) {
        slot->usage = 0;
    }
#endif
#if PPM_CHIP_CACHE_LISTS
    ppm_chip_age();                         // AE $0801BFAC -> $08018FBC -> aging $08017FDC, first thing
#endif
#if PPM_CHIP_CACHE_MISS && PPM_CHIP_LOAD_CAP
    ppm_chip_loads = 0;                     // $08018FE2-$08018FE8: load list cleared at AE
#endif
}

// paprium-pocket: SAT SNAPSHOT, DIAGNOSTIC. NOT FOR SHIPPING - set to 0.
//
// Reads the sprite list THIS firmware builds at 0xB00, on real hardware, and
// parks it in battery-backed RAM which the Pocket persists to Paprium.sav.
// Firmware only - no RTL, no VDP tap, no cmdlog.
//
// bram is 4 KB and the game uses 0x000-0x8FF (arg4 -> 0x000, arg1..3 ->
// 0x400/0x600/0x800), so 0x900+ is free and the save data is not touched.
//
//   0x900  'PBOT' + u16 boot counter          written unconditionally at setup
//   0x910  'PSAT' + u16 best sat_count        the capture itself
//   0x918  80 x ppm_sat_item   (640 B)
//   0xB98  64 x ppm_intf_obj   (1024 B)
//
// TWO THINGS CHANGED AFTER THE FIRST ATTEMPT CAME BACK EMPTY.
//
// 1. The trigger no longer depends on an assumption. The first version fired from
//    cmd_B1, on the belief that the game sends 0xB1 when the player pauses - which
//    came from GPGX's NAME for that handler and was never measured. It now runs
//    from ppm_obj_frame_end, which is the render path and certainly executes, and
//    it keeps the frame with the HIGHEST sat_count seen so far. Busy scenes win,
//    so playing to the rooftop captures the rooftop without the player timing
//    anything.
//
// 2. 'PBOT' is written at setup, before any gameplay. It is a control: if the
//    boot marker reaches the .sav and the capture does not, the write-back path
//    works and the capture logic is at fault. If NEITHER arrives, the Pocket is
//    not persisting MCU writes to backup RAM at all, and no amount of trigger
//    work will help. The first attempt could not tell these apart, which is why
//    it produced no information rather than a negative result.
//
// Note this game effectively never saves - scripts/decode_cmdlog.py says it
// outright, "one capture must survive a full playthrough" - so nothing here may
// depend on the game writing its own save.
//
// S1 IMAGES (FW_S1, TEST only): LAYOUT 2, 2026-10-17. B Jam's second save from a hardware test
// held a frame of 80 OR MORE entries that could only be inferred (entry 79 linked
// on to entry 80): the count was stored capped at 80, and the last busy frame is
// whatever was on screen at the quit, not the crowded one. The game composes up
// to 128+ entries a frame and the console's table holds 80. Layout 2 keeps TWO
// frames, both closed tables, and the session's count of the crowded ones:
//
//   0x906  'S' '2'                              the layout tag (0x906-0x90F were unused)
//   0x908  u16 the latest frame's TRUE count     (its capped count = min(count, 80);
//                                                 bit 15 set = torn, below)
//   0x90A  u16 the most entries any AF closed this session    } AF's compare / store
//   0x90C  u32 AFs that closed more than 80 entries this session } (bodies_s1.c)
//   0x910  'PSAT', u16 capped, u16 TRUE count (b15 torn) the CROWDED frame: the most
//   0x918  80 x ppm_sat_item  (640 B)                  entries this session, the
//   0xB98  64 x 6 B object record (PPM_OBJ_DUMP)       latest of equals (>= 20)
//   0xD18  80 x ppm_sat_item  (640 B)  the LATEST frame >= 20 (0.2.6's rule), in
//                                      the arena the rings leave free
//   0xF98  AE, AF, AD (u32 each; AF = the latest frame's AF number) and, in
//          layout 2, the crowded frame's AF number (it was the refresh count,
//          which equals AE: both count at every frame start)
//   0xFFF  t[23] = 2 (0 in layout 1): a layout-1 image writing over a layout-2
//          capture clears it, so the reader never takes one layout for the other
//
// Both frames fit with one object record, which goes with the crowded frame: where
// the latest frame was is where the player quit; where the crowded one was is
// not known otherwise. Per session, as before: the counts start at 0 at every
// boot, and a frame under 20 entries (menus, the quit's restart) writes nothing.
// AF only latches the count and does the two compares (no loop: L1's budget);
// the copies are the thread's (interim/s1/bodies_s1.c l3_test_work), with every
// interrupt open: a frame start (AE) that comes after the thread took the request
// (the take reads AE's count with interrupts off, since 2026-10-18) sets bit 15 of that
// frame's true count (TORN: the next frame's table may be mixed in). One that
// comes before the thread starts drops the request (bodies_s1.c), so the
// session's most at 0x90A can exceed the kept frame's count.

#if PPM_SAT_SNAPSHOT
#define SNAP_BOOT   0x900
#define SNAP_BASE   0x910
#if FW_S1
#define SNAP_L2     0x906                    // layout 2's header (see above)
#define SNAP_OFF_LATEST (8 + 640 + 64 * 6)   // the latest frame's SAT: the arena past the object record, to the dispatch block
u32 snap_af_n, snap_n_max, snap_n_over80;    // AF's close: the count it closed, the session's most, AFs over 80
static u32 snap_crowd_n, snap_crowd_af;      // the kept crowded frame: its true count and AF number (this session)
#if PPM_HEARTBEAT || PPM_ONSET_RING || PPM_EPOCH_RING || PPM_DA_CRC
#error "layout 2 keeps the latest frame's SAT in the arena: no heartbeat, ring or CRC table may claim it"
#endif
#endif
#if PPM_HEARTBEAT
#define SNAP_OFF_HB 1632   // == ring meta end (648 + 480*2 + 24); dispatch block starts at 1672
_Static_assert(648 + PPM_ONSET_FRAMES * 2 + 24 <= SNAP_OFF_HB, "heartbeat overlaps the ring meta");
_Static_assert(SNAP_OFF_HB + 40 <= 8 + 640 + 1024, "heartbeat overlaps the dispatch block");
volatile u8 *ppm_hb;
u32 ppm_hb_frame;
#define SNAP_OFF_TRAP (SNAP_OFF_SPARE_C + 32)
#define SNAP_OFF_SPARE_C (8 + 640 + 1024 + 16 + 8)   // == SNAP_OFF_SPARE, file-scope copy
_Static_assert(SNAP_OFF_TRAP + 24 <= 8 + 640 + 1024 + 80, "trap record overruns SPARE into t[]");
static volatile u8 *ppm_trap;
static void ppm_trap_put32(u8 off, u32 v) { ppm_trap[off] = (u8)(v >> 24); ppm_trap[off+1] = (u8)(v >> 16); ppm_trap[off+2] = (u8)(v >> 8); ppm_trap[off+3] = (u8) v; }
static void ppm_trap_rec(void) {
    u32 cause = neorv32_cpu_csr_read(CSR_MCAUSE);
    u32 pc    = neorv32_cpu_csr_read(CSR_MSCRATCH);   // the RTE core parks the faulting mepc here
    u32 bad   = neorv32_cpu_csr_read(CSR_MTVAL);
    u32 sp; __asm__ volatile ("mv %0, sp" : "=r"(sp));
    u16 n = (u16)((ppm_trap[0] << 8) | ppm_trap[1]);
    if (n == 0) {
        ppm_trap[2] = (u8) cause; ppm_trap[3] = ppm_hb[9];
        ppm_trap_put32(4, pc); ppm_trap_put32(8, bad); ppm_trap_put32(12, sp); ppm_trap_put32(16, ppm_hb_frame);
    }
    if (n != 0xFFFF) n++;
    ppm_trap[0] = (u8)(n >> 8); ppm_trap[1] = (u8) n;
    ppm_trap[20] = (u8) cause; ppm_trap[21] = ppm_hb[9];
}
#define SNAP_OFF_IDLE (8 + 640 + 1024 + 80)   // == SNAP_OFF_T, 24 bytes to the window end
_Static_assert(SNAP_OFF_IDLE + 24 <= 1776, "idle snapshot overruns the save window");
static volatile u8 *ppm_idle; static u16 ppm_idle_tick, ppm_idle_ovw;
static void ppm_idle_w16(u8 off, u16 v) { ppm_idle[off] = (u8)(v >> 8); ppm_idle[off + 1] = (u8) v; }
#define SNAP_OFF_VEC (8 + 640 + 1024 + 16 + 8)   // == SNAP_OFF_SPARE
static volatile u8 *ppm_vec;
static void ppm_vec_put(u8 off, u16 hi, u16 lo) { ppm_vec[off] = (u8)(hi >> 8); ppm_vec[off+1] = (u8) hi; ppm_vec[off+2] = (u8)(lo >> 8); ppm_vec[off+3] = (u8) lo; }
void ppm_hb_idle(void) {
    if ((++ppm_idle_tick & 63) != 0) return;
    ppm_idle_w16(0, ppmio.ramdp->reg_cmd); ppm_idle_w16(2, ppmio.ramdp->reg_status_1); ppm_idle_w16(4, ppmio.ramdp->reg_status_2.word);
    ppm_idle_w16(6, ppmio.ramdp->dma_cmd_count); ppm_idle_w16(8, ppmio.ramdp->dma_total); ppm_idle_w16(10, ppmio.ramdp->dma_remaining);
    ppm_idle_w16(12, (u16)(snap_bgm_over > 0xFFFF ? 0xFFFF : snap_bgm_over)); ppm_idle_w16(14, ppm_idle_tick);
    ppm_trap[22] = (u8)(snap_ptr_while_list_pending >> 8); ppm_trap[23] = (u8) snap_ptr_while_list_pending;
    { const vu16 *v = ppmio.ramdp->vectors;   // 68000 vectors, big-endian words as the 68000 sees them (byte-swapped in ramdp)
      ppm_vec_put(0, v[2*2], v[2*2+1]); ppm_vec_put(4, v[3*2], v[3*2+1]); ppm_vec_put(8, v[4*2], v[4*2+1]); ppm_vec_put(12, v[28*2], v[28*2+1]); }
    ppm_idle[16] = (u8)(ppm_sptr_shadow >> 24); ppm_idle[17] = (u8)(ppm_sptr_shadow >> 16); ppm_idle[18] = (u8)(ppm_sptr_shadow >> 8); ppm_idle[19] = (u8) ppm_sptr_shadow;
}
void ppm_hb_exit(void) { ppm_idle_w16(22, (u16)(0xEE00 | ppm_hb[9])); }
void ppm_hb_overwrite(u16 posted, u16 now) { if (now != posted) { if (ppm_idle_ovw != 0xFFFF) ppm_idle_ovw++; ppm_idle_w16(20, ppm_idle_ovw); } }
void ppm_hb_init(void) {
    ppm_hb = &ppmio.bram[SNAP_BASE + SNAP_OFF_HB];
    for (u8 i = 0; i < 40; i++) ppm_hb[i] = 0;
    ppm_hb[0] = 'P'; ppm_hb[1] = 'H'; ppm_hb[2] = 'B'; ppm_hb[3] = 'T';
    ppm_trap = &ppmio.bram[SNAP_BASE + SNAP_OFF_TRAP];
    for (u8 i = 0; i < 24; i++) ppm_trap[i] = 0;
    neorv32_rte_setup();
    for (u8 id = 0; id <= 8; id++) neorv32_rte_exception_install(id, ppm_trap_rec);
    ppm_idle = &ppmio.bram[SNAP_BASE + SNAP_OFF_IDLE]; ppm_vec = &ppmio.bram[SNAP_BASE + SNAP_OFF_VEC]; for (u8 i = 0; i < 16; i++) ppm_vec[i] = 0; for (u8 i = 0; i < 24; i++) ppm_idle[i] = 0; ppm_idle_tick = 0; ppm_idle_ovw = 0;
}
#endif

// Was "keep the busiest frame". Changed 2026-09-01: on a run to a late level the
// player passes through many busy scenes and any of them can out-count the target,
// so a long run could be spent and still capture the wrong fight. Now the LAST
// busy frame wins, which the player controls exactly - quit where you want the
// capture. Cheap enough to rewrite every frame that qualifies.

void ppm_snapshot_boot(void) {
#if PPM_HEARTBEAT
    ppm_hb_init();
#endif
    u8 *b = &ppmio.bram[SNAP_BOOT];
    u16 n = (u16) ((b[4] << 8) | b[5]);

    if (!(b[0] == 'P' && b[1] == 'B' && b[2] == 'O' && b[3] == 'T')) {
        n = 0;
    }
    n++;

    b[4] = (u8) (n >> 8);
    b[5] = (u8) n;
    b[0] = 'P'; b[1] = 'B'; b[2] = 'O'; b[3] = 'T';
}


static u8  snap_animover_id   = 0xFF;   // objID low byte, last hit
static u8  snap_animover_anim = 0xFF;   // the anim index it asked for
static u8  snap_animover_max  = 0xFF;   // what we thought that object's max was

#if FW_S1
// ae0: the frame-start count the thread read in the same interrupts-off section as its take of the request (since
// 2026-10-18, a review finding: read here, a frame start between the take and this read went unflagged); a frame start (AE, L1)
// after the take, before or during the copies below, makes this a torn copy (flagged, not dropped)
void ppm_snapshot_sat(u32 ae0) {
    u16 n = (u16) *(volatile u32 *) &snap_af_n;      // layout 2: the true count AF latched for the table it closed
    u16 count = n;
    u32 af0 = *(volatile u32 *) &snap_cnt_af;
#else
void ppm_snapshot_sat(void) {
    u16 count = ppmio.ramdp->sat_count;
#endif

    if (count < 20) {
        return;                 // ignore menus and transitions
    }
    if (count > 80) {
        count = 80;
    }

    u8 *b = &ppmio.bram[SNAP_BASE];

#if FW_S1
    // Layout 2: the latest frame always; the crowded one when this frame has at
    // least as many entries as the one kept (the latest of equals wins).
    u8 crowd = n >= snap_crowd_n;
    memcpy(&b[SNAP_OFF_LATEST], &ppmio.ramdp->sat_data[0], 80 * 8);
    if (crowd) {
        snap_crowd_n = n;
        snap_crowd_af = af0;
        memcpy(&b[8], &ppmio.ramdp->sat_data[0], 80 * 8);
    }
#else
    memcpy(&b[8], &ppmio.ramdp->sat_data[0], 80 * 8);
#endif

    // The 1024-byte object-table record used to live here. It has not informed a
    // conclusion since the SAT ownership map was deleted, and every counter added
    // since has been squeezing into scraps while it sat unread. Reclaimed.
    // b[648..1671] is now the counter arena; SNAP_OFF_* below carve it up.
    // ONE MAP FOR EVERY COUNTER. Two instruments were once given the same offset
    // by hand and the second silently overwrote the first, which a capture then
    // reported as a 4-billion eviction count. Offsets are named here, once, and
    // derived from each other so they cannot overlap.
    //
    //   +0   dispatch   0xAE / 0xAF / 0xAD / dma_refresh     16 bytes
    //   +16  eviction   live / worst / thrash                 8 bytes
    //   +24  spare
    #define SNAP_OFF_ARENA     (8 + 640)          // 1024 bytes, was obj_data
    #define SNAP_OFF_DAOTHER   (SNAP_OFF_ARENA)   // six u32
    #define SNAP_OFF_DISPATCH  (8 + 640 + 1024)
    #define SNAP_OFF_EVICT     (SNAP_OFF_DISPATCH + 16)
    #define SNAP_OFF_SPARE     (SNAP_OFF_EVICT + 8)
    // The 80 bytes reclaimed from the owner map end where t[] begins. Naming the
    // offsets stopped anyone hand-picking a duplicate address; it did NOT stop a
    // block growing past its neighbour, which is how a 56-byte hole nearly got an
    // 80-byte write. Overflow is a compile error from here on.
    #define SNAP_SPARE_BYTES   56
    #define SNAP_OFF_T         (8 + 640 + 1024 + 80)

#if PPM_OBJ_DUMP
    // Compact object-table record, 64 objects x 6 bytes, in the arena the onset and
    // epoch rings leave free. Same mutual exclusion as those rings: only ONE
    // instrument may claim the arena and the compiler decides, rather than a
    // reader discovering the overlap in a capture.
    #define SNAP_OFF_OBJ       (SNAP_OFF_ARENA)
    #define SNAP_OBJ_BYTES     (64 * 6)
    _Static_assert(SNAP_OFF_OBJ + SNAP_OBJ_BYTES <= SNAP_OFF_DISPATCH,
                   "object record would overrun the dispatch block");
    #if PPM_ONSET_RING || PPM_EPOCH_RING || PPM_DA_CRC
    #error "PPM_OBJ_DUMP and another arena user are both enabled; enable one"
    #endif

    // Big-endian, like every other counter in this block:
    //   +0 objID low byte
    //   +1 anim low 7 bits, bit 7 = the objID 0x8000 fresh-assign flag
    //   +2..3 nextAnim
    //   +4..5 obj_data+0x0A - animCounter to this firmware, `reset` to GPGX
#if FW_S1
    // Layout 2: the object record goes with the crowded frame, and the latest frame's SAT
    // follows it in the arena.
    _Static_assert(SNAP_OFF_OBJ + SNAP_OBJ_BYTES <= SNAP_OFF_LATEST,
                   "object record would overrun the latest frame's SAT");
    if (crowd)
#endif
    for (int q = 0; q < 64; q++) {
        ppm_intf_obj *io = &ppmio.ramdp->obj_data[q];
        u8 *r = &b[SNAP_OFF_OBJ + q * 6];
        u16 id = io->objID;
        r[0] = (u8) id;
        r[1] = (u8) ((io->anim & 0x7F) | ((id & 0x8000) ? 0x80 : 0));
        r[2] = (u8) (io->nextAnim >> 8);
        r[3] = (u8) io->nextAnim;
        r[4] = (u8) (io->animCounter >> 8);
        r[5] = (u8) io->animCounter;
    }
#endif

    _Static_assert(SNAP_OFF_SPARE + SNAP_SPARE_BYTES <= SNAP_OFF_T,
                   "snapshot counter block would overrun t[]");
    // t[] is 24 bytes to the end of the 1776-byte window. Guard it too: the six
    // 0xDA destinations were nearly written past the end of the save because only
    // the block above was bounded.
    _Static_assert(SNAP_OFF_T + 24 <= 1776, "t[] would overrun the save window");
    _Static_assert(SNAP_OFF_DAOTHER + 768 + 20 <= SNAP_OFF_DISPATCH,
                   "0xDA CRC table and meta would overrun the dispatch block");
#if PPM_ONSET_RING
    // The ring and the CRC table both want the whole arena. Only one can have
    // it, and the compiler decides rather than a later reader discovering an
    // overlap in a capture - which is exactly how the "4 billion evictions" and
    // the bogus destination list were both produced.
    #define SNAP_OFF_RING      (SNAP_OFF_ARENA)
    #define SNAP_OFF_RINGMETA  (SNAP_OFF_RING + PPM_ONSET_FRAMES * 2)
    _Static_assert(SNAP_OFF_RINGMETA + 24 <= SNAP_OFF_DISPATCH,
                   "onset ring and its meta would overrun the dispatch block");
    #if PPM_DA_CRC
    #error "PPM_ONSET_RING and PPM_DA_CRC both claim the arena; enable one"
    #endif
#endif
#if PPM_EPOCH_RING
    #define SNAP_OFF_EP        (SNAP_OFF_ARENA)
    #define SNAP_OFF_EPMETA    (SNAP_OFF_EP + PPM_EPOCH_CAP * 10)
    _Static_assert(SNAP_OFF_EPMETA + 32 <= SNAP_OFF_DISPATCH,
                   "epoch ring and its meta would overrun the dispatch block");
    #if PPM_ONSET_RING || PPM_DA_CRC
    #error "PPM_EPOCH_RING shares the arena with the onset ring and the CRC table; enable one"
    #endif
#endif

#if FW_S1
    _Static_assert(SNAP_OFF_LATEST + 80 * 8 <= SNAP_OFF_DISPATCH,
                   "the latest frame's SAT would overrun the dispatch block");
    // A frame start (AE) since the thread took the request (ae0, read with the
    // take, since 2026-10-18) and so before or during the copies: the game may have begun
    // the next frame's table under them (the thread runs with interrupts open,
    // after the brain call). Bit 15 of the frame's true count says so; a later
    // frame with as many entries replaces a torn crowded table as any equal does.
    u8 torn = *(volatile u32 *) &snap_cnt_ae != ae0 ? 0x80 : 0;
#endif

    // Dispatch counters, in the 80 bytes the (broken, unused) owner map had.
    {
        u8 *d = &b[SNAP_OFF_DISPATCH];
#if FW_S1
        u32 v[4] = { snap_cnt_ae, af0, snap_cnt_ad, snap_crowd_af };   // layout 2: +4 = the latest frame's AF, +12 the crowded one's
#else
        u32 v[4] = { snap_cnt_ae, snap_cnt_af, snap_cnt_ad, snap_cnt_refresh };
#endif
        for (u8 i = 0; i < 4; i++) {
            d[i * 4 + 0] = (u8) (v[i] >> 24); d[i * 4 + 1] = (u8) (v[i] >> 16);
            d[i * 4 + 2] = (u8) (v[i] >> 8);  d[i * 4 + 3] = (u8) v[i];
        }
        for (u8 i = SNAP_OFF_SPARE - SNAP_OFF_DISPATCH; i < 80; i++) d[i] = 0;
    }

#if FW_S1
    if (crowd) {
        b[4] = (u8) (count >> 8);
        b[5] = (u8) count;
        b[6] = (u8) ((n >> 8) | torn);   // layout 2: the TRUE count (uncapped) beside the capped one, bit 15 = torn
        b[7] = (u8) n;                   // (the animation-over hits that were here are in t[0..1] too)
    }
    {
        u8 *g = &ppmio.bram[SNAP_L2];
        u32 m = snap_n_max > 0xFFFF ? 0xFFFF : snap_n_max, o = snap_n_over80;
        g[0] = 'S'; g[1] = '2';
        g[2] = (u8) ((n >> 8) | torn); g[3] = (u8) n;
        g[4] = (u8) (m >> 8); g[5] = (u8) m;
        g[6] = (u8) (o >> 24); g[7] = (u8) (o >> 16); g[8] = (u8) (o >> 8); g[9] = (u8) o;
    }
#else
    b[4] = (u8) (count >> 8);
    b[5] = (u8) count;
    // How many masks the probe neutralised this frame, so the capture itself
    // proves the pass ran rather than leaving it to be assumed.
    b[6] = (u8) (snap_animover_hits >> 8);
    b[7] = (u8) snap_animover_hits;
#endif

    // Sticky run totals, past the owner map at 0xF88..0xFD7. The relink counters
    // that lived here are gone with the pass; what is left is the one open
    // question - see snap_animover_* above.
#if FW_S1
    // With FW_S1 the sprite engine is core/sprite, which does what the cart's chip does (this file's
    // engine is not linked); its TEST counters stand in for the cache figures.
    {
        extern uint16_t spr_cnt_starved, spr_cnt_noslot;
        extern uint32_t spr_cnt_loads, spr_cnt_evict;
        snap_dma_starved = spr_cnt_starved;
        snap_noslot = spr_cnt_noslot;
        snap_loads_ok = spr_cnt_loads;
        snap_evict_live = spr_cnt_evict;
    }
#endif
    u8 *t = &b[8 + 640 + 1024 + 80];
    t[0] = (u8) (snap_animover_hits >> 8);
    t[1] = (u8) snap_animover_hits;
    t[2] = snap_animover_id;
    t[3] = snap_animover_anim;
    t[4] = snap_animover_max;
    t[5] = (u8) (snap_dma_starved >> 8);
    t[6] = (u8) snap_dma_starved;
    t[7] = (u8) (snap_noslot >> 8);
    t[8] = (u8) snap_noslot;
    t[9]  = (u8) (snap_loads_ok >> 24); t[10] = (u8) (snap_loads_ok >> 16);
    t[11] = (u8) (snap_loads_ok >> 8);  t[12] = (u8) snap_loads_ok;
    t[13] = (u8) (snap_frames >> 24);   t[14] = (u8) (snap_frames >> 16);
    t[15] = (u8) (snap_frames >> 8);    t[16] = (u8) snap_frames;
    // t[17..22] were the dead stream-pointer audit (never written). Reused 2026-09-06.
    t[17] = (u8) (snap_switch_refused >> 8);  t[18] = (u8) snap_switch_refused;
    t[19] = (u8) (snap_switch_retry_ok >> 8); t[20] = (u8) snap_switch_retry_ok;
    t[21] = (u8) (snap_floor_frames >> 8);   t[22] = (u8) snap_floor_frames;
#if FW_S1
    t[23] = 2;              // layout 2 (with the tag at 0x906; a layout-1 write clears it)
#else
    t[23] = 0;
#endif
    u8 *e = &b[SNAP_OFF_EVICT];
    e[0] = (u8) (snap_evict_live >> 24); e[1] = (u8) (snap_evict_live >> 16);
    e[2] = (u8) (snap_evict_live >> 8);  e[3] = (u8) snap_evict_live;
    e[4] = (u8) (snap_evict_worst >> 8); e[5] = (u8) snap_evict_worst;
    e[6] = (u8) (snap_evict_reload >> 8); e[7] = (u8) snap_evict_reload;
    u8 *h = &b[SNAP_OFF_SPARE];
    #define SNAP_PUT32(o, v) do { h[(o)+0] = (u8)((v) >> 24); h[(o)+1] = (u8)((v) >> 16);                                   h[(o)+2] = (u8)((v) >> 8);  h[(o)+3] = (u8)(v); } while (0)
    SNAP_PUT32(0,  snap_da_count);
    SNAP_PUT32(4,  snap_db_count);
    SNAP_PUT32(8,  snap_af_clobber);
    SNAP_PUT32(12, snap_da_last_dest);
    SNAP_PUT32(16, snap_da_dest_9000);
    SNAP_PUT32(20, snap_db_stale_first);
    SNAP_PUT32(24, snap_db_below);
    h[28] = (u8) (snap_floor_run_max >> 8); h[29] = (u8) snap_floor_run_max;   // 2026-09-06, floor run
    SNAP_PUT32(28, snap_db_stale);
    SNAP_PUT32(32, snap_db_last);
    SNAP_PUT32(36, snap_db_max);
    SNAP_PUT32(40, snap_db_zero);
    SNAP_PUT32(44, snap_db_min == 0xFFFFFFFF ? 0 : snap_db_min);
    SNAP_PUT32(48, snap_db_max_below);
    SNAP_PUT32(52, snap_db_stale_same);
#if PPM_DA_CRC
    // 16 bytes x 48 records, meta at +768. Layout fixed by an earlier draft so a
    // GPGX twin can print the same table.
    u8 *o = &b[SNAP_OFF_DAOTHER];
    for (u8 i = 0; i < SNAP_DA_MAX; i++) {
        u8 *q = &o[i * 16];
        u32 v[4] = { snap_da_src[i], snap_da_len[i], snap_da_crc[i], snap_da_dst[i] };
        for (u8 k = 0; k < 4; k++) {
            q[k * 4 + 0] = (u8) (v[k] >> 24); q[k * 4 + 1] = (u8) (v[k] >> 16);
            q[k * 4 + 2] = (u8) (v[k] >> 8);  q[k * 4 + 3] = (u8) v[k];
        }
    }
    {
        // Fence: 32 KB is ~3 ms on this MCU, so it is NOT taken every SAT frame -
        // that would add an 18% frame-time tax to the very scene being measured.
        // Once per 60 in-game frames, plus a refresh right after any 0xDA that
        // expanded inside the region. fence_age says how stale the reading is.
        if (snap_frames - snap_fence_at >= 60) {
            snap_fence_take();
        }
        u8 *m = &o[768];
        m[0] = 0; m[1] = snap_da_n;
        m[2] = 0; m[3] = SNAP_DA_MAX;
        u32 mv[4] = { snap_fence_crc, SNAP_FENCE_LEN, SNAP_CRC_TAG,
                      snap_frames - snap_fence_at };
        for (u8 k = 0; k < 4; k++) {
            m[4 + k * 4 + 0] = (u8) (mv[k] >> 24); m[4 + k * 4 + 1] = (u8) (mv[k] >> 16);
            m[4 + k * 4 + 2] = (u8) (mv[k] >> 8);  m[4 + k * 4 + 3] = (u8) mv[k];
        }
    }
#endif  // PPM_DA_CRC

#if PPM_EPOCH_RING
    memcpy(&b[SNAP_OFF_EP], snap_ep, PPM_EPOCH_CAP * 10);
    {
        u8 *r = &b[SNAP_OFF_EPMETA];
        u32 rv[8] = { ((u32) snap_ep_idx << 16) | PPM_EPOCH_CAP,
                      snap_ep_seen,
                      SNAP_EP_TAG,
                      snap_ep_total,
                      ((u32) snap_ep_worst << 16) | (snap_ep_mism > 0xFFFF ? 0xFFFF : snap_ep_mism),
                      snap_ep_first_mism,
                      snap_ep_sum_ack,
                      snap_ep_sum_oe };
        for (u8 k = 0; k < 8; k++) {
            r[k * 4 + 0] = (u8) (rv[k] >> 24); r[k * 4 + 1] = (u8) (rv[k] >> 16);
            r[k * 4 + 2] = (u8) (rv[k] >> 8);  r[k * 4 + 3] = (u8) rv[k];
        }
    }
#endif

#if PPM_ONSET_RING
    // The ring, oldest-first order left to the decoder: snap_ring_idx says where
    // the write head is, and the decoder rotates. Writing it out rotated here
    // would cost MCU time in the frame being measured for no gain.
    memcpy(&b[SNAP_OFF_RING], snap_ring, PPM_ONSET_FRAMES * 2);
    {
        u8 *r = &b[SNAP_OFF_RINGMETA];
        // dma_budget is a ROM constant the GAME writes (0x0B00 or 0x1200 -> 10
        // or 16 blocks a frame). Recording it makes the affordability column
        // readable without working out separately which room
        // this was.
        u32 rv[6] = { ((u32) snap_ring_idx << 16) | PPM_ONSET_FRAMES,
                      snap_ring_seen,
                      SNAP_RING_TAG,
                      ((u32) ppmio.ramdp->dma_budget << 16) | snap_f_worst,
                      snap_dma_starved,
                      snap_loads_ok };
        for (u8 k = 0; k < 6; k++) {
            r[k * 4 + 0] = (u8) (rv[k] >> 24); r[k * 4 + 1] = (u8) (rv[k] >> 16);
            r[k * 4 + 2] = (u8) (rv[k] >> 8);  r[k * 4 + 3] = (u8) rv[k];
        }
    }
#endif

    // Magic last, so a half-written capture is never read as a good one.
    b[0] = 'P'; b[1] = 'S'; b[2] = 'A'; b[3] = 'T';
}
#endif

// ---------------------------------------------------------------------------
// EVENT LOG
//
// The snapshot is ONE frame, and every question that has actually blocked this
// investigation is a question about time: was the figure ever on the chain this
// boot, did it leave before or after the pass first wrote, does it leave on a
// frame the pass touched at all. A single frame cannot answer any of those, which
// is why the station has now cost four captures and four theories.
//
// So: log an entry every time a node LEAVES the reachable chain, and one when it
// comes back. Frame number, the node, the entry that now points past it, and
// whether the pass wrote that frame. One play session then says outright whether
// the game unlinks 14-19 itself or one of our writes did it.
//
// Keeps the FIRST events rather than the last - the onset is the whole point -
// and counts the total so a full buffer is never mistaken for a quiet run.
#if PPM_EVENT_LOG

#define EVT_CAP   130

static u8  evt_map[(PPM_SAT_ENTRIES + 7) / 8];       // reachable last frame
static u8  evt_link[PPM_SAT_ENTRIES];                // each node's link last frame
static u8  evt_buf[EVT_CAP * 8];
static u16 evt_frame = 0;
static u16 evt_total = 0;                            // events seen, buffer or not
static u8  evt_n = 0;                                // events actually stored
static u8  evt_armed = 0;                            // first frame has no "before"

static void evt_put(u16 frame, u8 node, u8 prev, u8 newlink, u8 flags, u16 tile) {
    evt_total++;
    if (evt_n >= EVT_CAP) {
        return;
    }
    u8 *e = &evt_buf[evt_n * 8];
    e[0] = (u8) (frame >> 8);
    e[1] = (u8) frame;
    e[2] = node;
    e[3] = prev;
    e[4] = newlink;
    e[5] = flags;
    e[6] = (u8) (tile >> 8);
    e[7] = (u8) tile;
    evt_n++;
}

// flags
#define EVT_F_JOINED   0x01   // node came back, rather than left
#define EVT_F_WROTE    0x02   // the relink pass stored links this frame
#define EVT_F_BAILED   0x04   // the relink pass stood down this frame

void ppm_event_frame(void) {
    u8 cur[(PPM_SAT_ENTRIES + 7) / 8];
    u16 node = 0, guard = 0;
    u8 flags = 0;

    if (ppmio.ramdp->sat_count < 20) {
        return;                     // menus and transitions: not the subject
    }

    for (u8 i = 0; i < sizeof(cur); i++) {
        cur[i] = 0;
    }

    while (guard++ <= PPM_SAT_ENTRIES) {
        if (node >= PPM_SAT_ENTRIES) {
            break;
        }
        if (cur[node >> 3] & (1u << (node & 7))) {
            break;                  // cycle
        }
        cur[node >> 3] |= (1u << (node & 7));
        u8 link = ppmio.ramdp->sat_data[node].sizeNext & 0xff;
        if (link == 0) {
            break;
        }
        node = link;
    }

    if (evt_armed) {
        for (u16 i = 0; i < PPM_SAT_ENTRIES; i++) {
            u8 was = (evt_map[i >> 3] >> (i & 7)) & 1;
            u8 is  = (cur[i >> 3]     >> (i & 7)) & 1;
            if (was == is) {
                continue;
            }
            // Who used to point at it, and where does that entry point now? That
            // pair is the difference between "the game rerouted around it" and
            // "our rewrite did".
            u8 prev = 0xFF;
            for (u16 j = 0; j < PPM_SAT_ENTRIES; j++) {
                if (evt_link[j] == (u8) i) {
                    prev = (u8) j;
                    break;
                }
            }
            evt_put(evt_frame, (u8) i, prev,
                    prev == 0xFF ? 0xFF
                                 : (u8) (ppmio.ramdp->sat_data[prev].sizeNext & 0xff),
                    (u8) (flags | (is ? EVT_F_JOINED : 0)),
                    ppmio.ramdp->sat_data[i].attrs & 0x7ff);
        }
    }

    for (u8 i = 0; i < sizeof(cur); i++) {
        evt_map[i] = cur[i];
    }
    for (u16 i = 0; i < PPM_SAT_ENTRIES; i++) {
        evt_link[i] = ppmio.ramdp->sat_data[i].sizeNext & 0xff;
    }
    evt_armed = 1;
    evt_frame++;
}

// Written INSTEAD of the object table and owner map - the timeline is worth more
// than either, and there is not room for both.
void ppm_snapshot_events(void) {
    u8 *b = &ppmio.bram[SNAP_BASE];

    if (ppmio.ramdp->sat_count < 20) {
        return;
    }

    b[4] = (u8) (evt_frame >> 8);       b[5] = (u8) evt_frame;
    b[6] = (u8) (evt_total >> 8);       b[7] = (u8) evt_total;
    b[8] = evt_n;
    b[9] = (u8) ppmio.ramdp->sat_count;
    b[10] = (u8) (snap_animover_hits >> 8); b[11] = (u8) snap_animover_hits;
    b[12] = snap_animover_id;
    b[13] = snap_animover_anim;
    b[14] = snap_animover_max;
    b[15] = 0;

    memcpy(&b[16], &ppmio.ramdp->sat_data[0], 640);
    memcpy(&b[16 + 640], evt_buf, sizeof(evt_buf));

    b[0] = 'P'; b[1] = 'E'; b[2] = 'V'; b[3] = 'T';
}
#endif

#if PPM_SFX_QUIET_DMA
volatile u8 ppm_list_pending;
#endif
#if PPM_CHIP_CACHE_MISS && PPM_CHIP_LOAD_CAP
// B1: the chip's dispatch table $08025910[$31] = $0801AD0C, which (engine flag
// $2000FB1C+$400 set) goes to $0801BFBA: BL to the load-list flush $08018FFC. The
// flush ends with the list count := 0 ($0801907C-$0801907E), so the 15-load cap
// starts again after a B1. The flush's only other caller is the AF close
// ($080190D2), which ppm_obj_frame_end does inline. Only the count is handled
// here: the list itself is the chip's hand-off to the cart FPGA (D43).
void ppm_chip_flush_loads(void) {
    ppm_chip_loads = 0;                     // $0801907C-$0801907E
}
#endif
void ppm_obj_frame_end() {
#if PPM_SFX_QUIET_DMA
    ppm_list_pending = 1;
#endif
#if PPM_HEARTBEAT
    ppm_hb_frame++; hb_w32(4, ppm_hb_frame); hb_w8(9, 6); hb_w16(22, ppmio.ramdp->sat_count); hb_w16(18, ppmio.ramdp->dma_cmd_count);
#endif


#if !PPM_INLINE_COMPOSE
    ppm_block_unpack_addr = PPM_SCRATCH_BASE;
#endif

    // The frame's DMA budget is refreshed in ppm_dma_refresh(), which moved to
    // frame START when composition moved to the 0xAD command. See it for why.
#if !PPM_INLINE_COMPOSE
    ppm_dma_refresh();
#endif


    // TWIN CURSORS. ppm_block_unpack_addr is where the MCU unpacks blocks TO;
    // FPGAIO->sdram_ptr at the end of this function is where the 68000's DMA
    // reads them FROM. They must start each frame together and advance in
    // lockstep. They used to sit two lines apart down there; PPM_INLINE_COMPOSE
    // moved only the write cursor to frame_start, leaving the pair split across
    // two different commands.
    //
    // 0xAE is dispatched reliably - measured at 30,585 against 30,584 for 0xAF -
    // so this has never actually bitten. Resetting here as well is idempotent and
    // removes the dependency on one command firing for the pair to stay matched.
    ppm_block_unpack_addr = PPM_SCRATCH_BASE;


    //printf("dma: %i\n", ppmio.ramdp->dma_remaining);

#if !FW_S1   // s1 images (2026-10-17): nothing reads it; its volatile RAMDP read cost AF's reply MCU time
    uint16_t sat_first = ppmio.ramdp->sat_count;   // ours start here
#endif

    uint8_t *ptr = ppm_drawList;

#if !PPM_INLINE_COMPOSE
    while (ptr != ppm_drawListPtr) {
        ppm_obj_render(*ptr++);
        hb_w8(9, 9);
    }
#endif



#if PPM_SAT_SNAPSHOT
    // paprium-pocket: DIAGNOSTIC. Snapshot AFTER the render loop, so the capture
    // is the frame just composed rather than the previous one. That matters when
    // PPM_FORCE_SPRITE_PRI is also on: the point of that pairing is to read back
    // the very entries the OR was applied to.
#if PPM_EVENT_LOG
    ppm_event_frame();
    ppm_snapshot_events();
#elif FW_S1   // s1 images: the 640-B copy is over L1's 0.32 ms budget: the thread makes it; AF's L1 asks for it after
              // its reply (interim/s1 body_af_replied, since 2026-10-18: before it, the request and its compares cost the reply)
#else
    ppm_snapshot_sat();
#endif
#endif

#if !(FW_S1 && PPM_CHIP_CACHE_LISTS)   // MCU interface v1.2: with the chip's cache lists (D02) nothing reads a slot's age (only
                                        // the 0.2.6 victim search, built without them), so the s1 images leave the 64-slot
                                        // pass out of AF's reply (measured: ~60 us of it, TEST, on the priced RV32 model)
    ppm_vram_slot *slot = ppm_vram_slots;

    for (uint16_t x = 0; x < PPM_MAX_VRAM_SLOTS; slot++, x++) {

        if (!slot->usage) {
            slot->age++;
        }
    }
#endif

#if PPM_CHIP_CACHE_MISS && PPM_CHIP_LOAD_CAP
    ppm_chip_loads = 0;                     // AF close $080190D2 -> flush $08018FFC: count := 0 at $0801907C-$0801907E
#endif
#if FW_S1 && PPM_CHIP_AF_END && !PPM_EPOCH_RING
    // s1 images (2026-10-17): the WRAM bookkeeping below (nothing the 68000 or the RTL sees, and nothing the close
    // reads) is done first, so the chip's close is the last call (a tail call: MCU time in AF's reply)
#if PPM_SAT_SNAPSHOT
    if (snap_da_pending) {
        snap_af_clobber++;
        snap_da_pending = 0;
    }
#endif
    ppm_sptr_shadow = PPM_SCRATCH_BASE;
    ppm_close_sprite_table();
#else
    ppm_close_sprite_table();
    //ppm_sdram_pointer = &ppm_sdram[0x9000 / 2];
#if PPM_SAT_SNAPSHOT
    // Counted BEFORE the rewind: did a 0xDA point the window somewhere else since
    // the last frame end, and is that pointer about to be thrown away?
    if (snap_da_pending) {
        snap_af_clobber++;
        snap_da_pending = 0;
    }
#endif
    {
        u32 prev_ptr = ppm_sptr_shadow;
#if !FW_S1   // MCU interface v1.2: the RTL decoder loads SPTR with its output base at the flush's START
        FPGAIO->sdram_ptr = PPM_SCRATCH_BASE;
#endif
        ppm_sptr_shadow = PPM_SCRATCH_BASE;
#if PPM_EPOCH_RING
        snap_epoch_note(prev_ptr);
#endif
    }
#endif
}

#if PPM_CHIP_AF_END
// D10 + the rest of D42 (s1 images, 2026-10-17; B Jam's decision of 2026-10-15/16): the chip's whole frame end $080190B8-$080193AC,
// after the load-list flush it calls first ($080190D2; ours core/dispatch flush_regs). The dispatcher runs it only for
// an AF that an AE opened (D38, $0801BCE6-$0801BCEE) and hands over the mode (the post's low byte & 3) and the parity
// H+$403 (+1 at every AE, accepted B0 and the first C6's sprite init). $1F18 is read ($080190D6), never written; the
// chip never uploads more than 80 entries.
//   count <= 80: end mark at entry[count] (Y 0, link byte 0, size kept), entry 79's link byte 0 ([$D7A]), $1F1C := 0,
//     DMA 1 = entries 0..count (80 when the count is 80) to VRAM $F000, DMA 2 = entries 0-13 again, the stash
//     $1F20-$1F8F := entries 14-27 (the game's H-int $10DA0 copies the stash over SAT 0-13 below line $30 only when
//     $1F1C != 0, $33AEE)
//   count > 80, AF02 ($08019204): on an even parity the overflow past entry 93 moves down (count <= 128: entries
//     94..count-1 over 188-count..93; above: 94-127 over 60-93); entries 14..top-2 relinked to k - 13, entry top-1
//     ends the list (top = 94, or the count when that is 94 or less); $1F1C := 1; DMA 1 = 66 entries from entry 28 to
//     VRAM $F070; DMA 2 and the stash. The VDP then shows entries 0-13 at the top, 14-27 below line $30 (the stash),
//     28-93 in slots 14-79 and the overflow rotated in on alternate frames: the cart's flicker
//   count > 80, AF01 ($080192A2): on an even parity the overflow (80..min(count, 128)-1) moves over the last entries;
//     end mark at entry count (or 128); $1F1C := 0; DMA 1 = 80 entries; no DMA 2, no stash
//   count > 80, AF00 ($08019276): truncated at 80 (entry 80 = end mark), $1F1C := 0, DMA 1 = 80 entries, DMA 2, stash
//   count > 80, mode 3 ($0801929E): the chip writes DMA 2 through a register that path never set (the caller's sl, not
//     the RAMDP); not followed (what it overwrites is not known; the game's sender $30FB2 posts AF02 or AF01 only):
//     nothing after the flush
uint8_t ppm_chip_af_mode, ppm_chip_af_parity;

// MCU time (the RV32 test bench on the priced clock: every RAMDP access 9 clocks, an ALU instruction 4, a taken branch or a
// jump 8-10): the close runs in AF's L1 before the reply. Every store lands where the chip's does, in the chip's order,
// with the same bytes; only the store widths differ, which nothing sees (the 68000 waits for the reply before it reads
// any of them). On 2026-10-17: the same stores in the same order for fewer MCU instructions (our RV32 close bench,
// not in this tree: the halfword write sequence equal, cycles estimated):
//   - each descriptor is four 32-bit stores (halfword k at +2k: the chip's eight halfword stores, $08019142-$0801916A /
//     $08019186-$080191AE), then $1F10 += its words and $1F16 += 1, each read and stored where the chip does
//     ($0801916C-$08019180 / $080191B0-$080191C6); DMA 2 goes right after DMA 1 (the chip's r6); the descriptor words
//     are built inline (chip_af_desc is always inlined, so the constant ones are constants);
//   - the end mark's Y := 0 and link-byte clear (the chip's strh, then ldrh / strh at entry[count]) are one read and one
//     32-bit store of the entry's first word: Y at +0, then the link word at +2, the same halfwords in the same order;
//   - the stash $080191C8-$080191E6 (56 halfwords, ascending) is 28 aligned 32-bit copies, fully unrolled, in one shared
//     helper the common close reaches by a tail call (chip_af_stash);
//   - the relink loop ($08019334-$0801936C, four entries a pass) and the overflow move ($080192EC-$0801931A) run in the
//     chip's order with the link value carried in a register; the multiplexed tables (count > 80) are out of line and
//     compiled for size (chip_af_over80), so the common close needs no stack frame.
#define CHIP_DESC_W(lo, hi)     ((uint32_t) (lo) | ((uint32_t) (hi) << 16))    // (both halves below 0x10000)
#define CHIP_DESC_W2            CHIP_DESC_W(0x9700, 0x9605)                     // +8 $9700, +A $9605 (every descriptor)
#define CHIP_DESC_W3(vram)      CHIP_DESC_W(vram, 0x0083)                       // +C $7000 = VRAM $F000 ($7070 = $F070), +E

static inline __attribute__((always_inline)) void chip_af_desc(ppm_ramdp *r, vu32 *d, uint32_t w0, uint32_t w1,
                                                               uint32_t w2, uint32_t w3, uint32_t words) {
    d[0] = w0;                                  // +0 autoinc $8F02, +2 $93xx (struct names follow mame.h order,
    d[1] = w1;                                  // +4 $95xx, +6 $94xx      values and order follow the chip)
    d[2] = w2;                                  // +8, +A
    d[3] = w3;                                  // +C, +E
    r->dma_total = (uint16_t) (r->dma_total + words);           // $1F10
    r->dma_cmd_count = (uint16_t) (r->dma_cmd_count + 1u);      // $1F16
}

// the same, out of line, for the multiplexed tables (count > 80: rare, and their loops dwarf the call)
static __attribute__((noinline)) void chip_af_desc_x(ppm_ramdp *r, vu32 *d, uint32_t w0, uint32_t w1, uint32_t w3,
                                                    uint32_t words) {
    chip_af_desc(r, d, w0, w1, CHIP_DESC_W2, w3, words);
}

// the stash $1F20 := entries 14-27 (planted bug 4: entries 0-13): 28 word copies, each a load and a store, ascending
static __attribute__((noinline)) void chip_af_stash(ppm_ramdp *r) {
    const vu32 *src = (const vu32 *) &r->sat_data[SPR_BUG == 4 ? 0 : 14];
    vu32 *dst = (vu32 *) &r->buff[0];
#define CHIP_STASH4(k)  do { dst[k] = src[k]; dst[(k) + 1] = src[(k) + 1]; dst[(k) + 2] = src[(k) + 2]; \
                             dst[(k) + 3] = src[(k) + 3]; } while (0)
    CHIP_STASH4(0); CHIP_STASH4(4); CHIP_STASH4(8); CHIP_STASH4(12); CHIP_STASH4(16); CHIP_STASH4(20); CHIP_STASH4(24);
#undef CHIP_STASH4
}

// the overflow move $080192EC-$0801931A: entries from..to-1 down by to - from (on both paths the shift is the entry
// count), each relinked to k + 1 - shift (the chip's four halfword stores Y, link, attr, X as two words: Y | link,
// attr | X; the entries never overlap and the copy runs upwards). The link halfword (link & $F00) + k + 1 - shift is
// the word's top half: the word masked to Y and the size bits plus the running link << 16 (k + 1 - shift is 33-127
// on both paths, so nothing carries).
static __attribute__((noinline)) void chip_af_move(vu32 *s, uint32_t from, uint32_t to) {
    vu32 *p = s + 2 * from, *e = s + 2 * to, *q = s + 2 * (2 * from - to);
    uint32_t lk = (2 * from + 1u - to) << 16;
    while (p != e) {
        uint32_t w0 = p[0], w1 = p[1];
        q[0] = (w0 & 0x0f00ffffu) + lk;
        q[1] = w1;
        p += 2;
        q += 2;
        lk += 0x10000u;
    }
}

static inline void chip_af_f1c(ppm_ramdp *r, uint16_t v) {
#if SPR_BUG == 2
    (void) r;
    (void) v;                                       // planted: $1F1C never written (chiplock_slice negative control)
#else
    r->unk_1f1c = v;
#endif
}

// the end mark at entry at: Y 0 and the link byte 0 (size kept) as one word, then entry 79's link byte 0
// ($080190E2-$08019100, $0801923E-$08019258, $08019276-$0801928E)
static inline void chip_af_end(ppm_sat_item *s, uint32_t at) {
    ((vu32 *) s)[2 * at] &= 0x0f000000u;
    s[79].sizeNext &= 0x0f00;
}

// count > 80 ($080191F8): the multiplexed tables, by the mode
static __attribute__((noinline, optimize("Os"))) void chip_af_over80(ppm_ramdp *r, vu32 *d, uint32_t count) {
    ppm_sat_item *s = r->sat_data;
    uint32_t even = !(ppm_chip_af_parity & 1);                    // H+$403 bit 0 ($08019228-$08019230, $080192CA-$080192D2)
    uint32_t mode = ppm_chip_af_mode;
    uint32_t to = count > 0x80 ? 0x80 : count;                    // the overflow ends at 128
    if (mode == 2) {                                              // $08019204
        uint32_t top = 94;
        if (count > 94) {                                         // $08019224 -> $080192CA, $08019232-$08019238 ->
            if (even)                                             // $08019392: 94..to-1 over 188-to..93 (above 128:
                chip_af_move((vu32 *) s, 94, to);                 // 94-127 over 60-93)
        } else {
            top = count;                                          // $0801932C: the list ends at the count
        }
        {                                                         // $08019334-$0801936C: entries 14..top-2 relinked
            vu16 *p = &s[14].sizeNext, *e = &s[top - 1].sizeNext; // to k - 13 (VDP slots 14-79), ascending; top is
            uint32_t lk = 1, k;                                   // 81-94 here, so 66-79 entries, four a pass
            for (k = (top - 15u) & 3u; k; k--) {
                *p = (uint16_t) ((*p & 0x0f00) + lk);
                p += 4;
                lk++;
            }
            while (p != e) {
                p[0] = (uint16_t) ((p[0] & 0x0f00) + lk);
                p[4] = (uint16_t) ((p[4] & 0x0f00) + lk + 1u);
                p[8] = (uint16_t) ((p[8] & 0x0f00) + lk + 2u);
                p[12] = (uint16_t) ((p[12] & 0x0f00) + lk + 3u);
                p += 16;
                lk += 4;
            }
            *e &= 0x0f00;                                         // $08019372-$08019382: entry top-1 ends the list
        }
        chip_af_f1c(r, 1);                                        // $08019384-$0801938C
        chip_af_desc_x(r, d, CHIP_DESC_W(0x8f02, 0x9308), CHIP_DESC_W(0x95F0, 0x9401), CHIP_DESC_W3(0x7070), 0x118);
                                                                  // DMA 1: entries 28-93 to VRAM $F070
    } else if (mode <= 1) {                                       // AF01 $080192A2: the overflow (on an even parity)
        if (mode == 0)                                            // over the last entries, the end mark at the count
            to = 0x50;                                            // or 128, no DMA 2, no stash; AF00 $08019276:
        else if (even)                                            // truncated at 80
            chip_af_move((vu32 *) s, 0x50, to);                   // $080192D4 / $08019392
        chip_af_end(s, to);                                       // $0801923E-$08019258 / $08019276-$0801928E
        chip_af_f1c(r, 0);                                        // $0801925A-$0801925C
        chip_af_desc_x(r, d, CHIP_DESC_W(0x8f02, 0x9340), CHIP_DESC_W(0x9580, 0x9401), CHIP_DESC_W3(0x7000), 0x150);
        if (mode)                                                 // $0801925E-$08019274 -> $0801913C; AF01: r3 = 0
            return;                                               // ($08019182-$08019184)
    } else {
        return;                                                   // mode 3 above 80: not followed (see above)
    }
    chip_af_desc_x(r, d + 4, CHIP_DESC_W(0x8f02, 0x9338), CHIP_DESC_W(0x9580, 0x9400), CHIP_DESC_W3(0x7000), 72);
    chip_af_stash(r);                                             // DMA 2: entries 0-13 again, $08019186-$080191C6;
}                                                                 // the stash $080191C8-$080191E6

void ppm_close_sprite_table() {
    ppm_ramdp *r = ppmio.ramdp;
    uint32_t count = r->sat_count;                                // $080190D6-$080190DA
    vu32 *d = (vu32 *) &r->dma_cmd[r->dma_cmd_count];             // $1400 + $1F16 * 16 ($08019142-$0801914E)
    if (count > 0x50) {                                           // $080190DC-$080190E0
        chip_af_over80(r, d, count);
        return;
    }
    {
        uint32_t n = count + 1u, w2 = CHIP_DESC_W2, w3 = CHIP_DESC_W3(0x7000);
        __asm__ ("" : "+r" (w2), "+r" (w3));                     // (built once for both descriptors)
        chip_af_end(r->sat_data, count);                          // $080190E2-$08019100
        chip_af_f1c(r, 0);                                        // $0801912A-$0801912E
        if (n == 0x51)                                            // $08019102-$08019106 -> $08019290: 80 entries
            chip_af_desc(r, d, CHIP_DESC_W(0x8f02, 0x9340), CHIP_DESC_W(0x9580, 0x9401), w2, w3, 0x150);
        else                                                      // $08019108-$08019128: n entries = 4n words
            chip_af_desc(r, d, CHIP_DESC_W(0x8f02, 0x9300) + ((n << 18) & 0xff0000u),  // +2 $9300 + (4n & $FF)
                         CHIP_DESC_W(0x9580, 0x9400) + ((n >> 6) << 16),                // +6 $9400 + (4n >> 8)
                         w2, w3, (n + 4u) << 2);
        chip_af_desc(r, d + 4, CHIP_DESC_W(0x8f02, 0x9338), CHIP_DESC_W(0x9580, 0x9400), w2, w3, 72);
        chip_af_stash(r);                                         // DMA 2 ($08019186-$080191C6), the stash
    }
}

#else
// paprium3 float candidate: the chip's sprite-table close (AF, $080190B8) for
// $1F18 <= $50. 0 builds the old close below, for the with/without sims.
#ifndef PPM_FLOAT_ENDMARK
#define PPM_FLOAT_ENDMARK       1
#endif

void ppm_close_sprite_table() {
#if PPM_FLOAT_ENDMARK
    // As the chip does it (the cart program, base $08010000):
    //   $080190D6-$080190F4  end mark at entry[count]: Y = 0, link byte 0, size kept
    //   $080190F6-$08019100  entry 79 link byte 0 ([$D7A] &= $0F00)
    //   $08019102-$08019180  upload count+1 entries to VRAM $F000, $1F10/$1F16 bumped
    //   $08019102-$08019106 + $08019290-$0801929C  count == $50: upload 80, not 81
    // Not done the chip's way (cart-match list): $0801912C-$0801912E ($1F1C = 0), the second
    // 14-entry DMA $08019186-$080191C6, the $1F20 stash $080191C8-$080191E6, and the
    // count > $50 multiplex path $080191F8-$080193AC (the old close below runs).
    uint16_t count = ppmio.ramdp->sat_count;                    // $080190D6-$080190DA
    if (count <= 0x50) {                                          // $080190DC-$080190E0
        ppm_sat_item *end = &ppmio.ramdp->sat_data[count];        // $B00 + count*8, at most $D80
        end->posY = 0;                                            // $080190E2-$080190E6
        end->sizeNext &= 0x0f00;                                  // $080190E8-$080190F4
        ppmio.ramdp->sat_data[79].sizeNext &= 0x0f00;             // $080190F6-$08019100
        uint16_t n = count + 1;                                   // $080190F8-$080190FC
        uint16_t len_lo, len_hi, words;
        if (n == 0x51) {                                          // $08019102-$08019106 -> $08019290
            len_lo = 0x9340; len_hi = 0x9401; words = 0x150;      // $08019290-$0801929C
        } else {
            uint16_t w = n << 2;                                  // $0801910E
            len_lo = 0x9300 + (w & 0xff);                         // $08019108-$08019116
            len_hi = 0x9400 + (w >> 8);                           // $08019118-$0801911C, $08019124-$08019128
            words  = (n + 4) << 2;                                // $0801911A-$08019122
        }
        ppm_dma_cmd *d = &ppmio.ramdp->dma_cmd[ppmio.ramdp->dma_cmd_count];   // $08019142-$0801914E: $1400 + $1F16*16
        d->autoinc = 0x8f02;    // word 0   $0801914C   (struct names follow mame.h order,
        d->lenH    = len_lo;    // word 1   $08019152    values and order follow the chip)
        d->lenL    = 0x9580;    // word 2   $08019158
        d->srcH    = len_hi;    // word 3   $0801915C
        d->srcM    = 0x9700;    // word 4   $0801915E
        d->srcL    = 0x9605;    // word 5   $08019162
        d->cmdH    = 0x7000;    // word 6   $08019166   VRAM $F000
        d->cmdL    = 0x0083;    // word 7   $0801916A
        ppmio.ramdp->dma_total += words;                          // $0801916C-$08019178
        ppmio.ramdp->dma_cmd_count++;                             // $0801917A-$08019180
        return;
    }
#endif

    ppm_sat_item *sat_entry = &ppmio.ramdp->sat_data[ppmio.ramdp->sat_count];

    if (!ppmio.ramdp->sat_count) {
        sat_entry->posY = 0x10;
        sat_entry->sizeNext = 0;
        sat_entry->attrs = 0;
        sat_entry->posX = 0x10;
        ppmio.ramdp->sat_count++;
    } else {
        (--sat_entry)->sizeNext &= 0xff00;
    }

    ppm_dma_cmd *dma_entry = &ppmio.ramdp->dma_cmd[ppmio.ramdp->dma_cmd_count++];
    dma_entry->autoinc = 0x8f02;

    uint16_t word_size = ppmio.ramdp->sat_count * (sizeof (ppm_sat_item) / 2);
    dma_entry->lenH = 0x9400 + (word_size >> 8);
    dma_entry->lenL = 0x9300 + (word_size & 0xff);

    uint32_t sat_addr = offsetof(ppm_ramdp, sat_data) / 2;
    dma_entry->srcH = 0x9700 + ((sat_addr >> 16) & 0xff);
    dma_entry->srcM = 0x9600 + ((sat_addr >> 8) & 0xff);
    dma_entry->srcL = 0x9500 + (sat_addr & 0xff);

    // xfer to SAT location in VRAM (0xf000)
    dma_entry->cmdH = 0x7000;
    dma_entry->cmdL = 0x0083;
}
#endif

#if PPM_PIN_FALLBACK && !PPM_CHIP_CACHE_LISTS
// Mark a resident block as used this frame so the LRU will not hand its slot to
// a later object. A miss is silently ignored: nothing is loaded here.
static void ppm_vram_touch_block(uint16_t num) {
    ppm_vram_slot *slot = ppm_vram_slots;
    for (uint16_t x = 0; x < ppm_vram_max_slot; slot++, x++) {
        if (slot->block_num == num) {
            slot->usage++;
            slot->age = 0;
            return;
        }
    }
}
#endif

#if PPM_CHIP_POSE_HOLD
// Pre-load pass, hit test: block->id != 0 ($0802F302-$0802F308); a resident block
// is marked used, countdown := $20 ($0802F2EE-$0802F2F2), exactly as the hit path of
// ppm_vram_load_block marks it. Searched once here, so a resident piece costs one
// slot search, not two.
static bool ppm_chip_preload_hit(uint16_t num) {
    ppm_vram_slot *slot = ppm_vram_slots;
    for (uint16_t x = 0; x < ppm_vram_max_slot; slot++, x++) {
        if (slot->block_num == num) {
#if !(FW_S1 && PPM_CHIP_CACHE_LISTS)   // s1 images: nothing reads them with the chip's lists (ppm_obj_frame_start)
            slot->usage++;
            slot->age = 0;
#endif
            ppm_chip_cd[x] = 0x20;
            return true;
        }
    }
    return false;
}

// D07 PROGRESSIVE, $0802F2C8-$0802F5B2: one pass over the pose's pieces, nothing
// drawn. True when no piece was missing (the pose is then drawn and advances,
// $0802F5B0 -> $0802F0C6); false = hold ($0802F5AE -> $0802F3C0). Out of line:
// it runs for a few big poses only, and keeps ppm_obj_render's registers free.
static bool __attribute__((noinline)) ppm_chip_preload(ppm_spr_data_hdr *spr_info) {
    bool complete = true;                                              // $0802F2D2-$0802F2E4: r0 := 1
    ppm_spr_data *sd = &spr_info->sprites[0];
    ppm_chip_ab_only = 1;
    for (uint16_t x = 0; x < spr_info->count; sd++, x++) {            // $0802F2F4-$0802F2FA: next piece, to the end
        if (!sd->blockNum) {                                           // $0802F2FC-$0802F300
            continue;
        }
        if (ppm_chip_preload_hit(sd->blockNum)) {                      // resident: countdown := $20, next
            continue;
        }
        complete = false;                                              // $0802F312 (and $0802F7D8 after a claim): any
                                                                       // missing piece clears the flag, loaded or not
        // missing: gate $0802F30A-$0802F316, cap $0802F318-$0802F31E, list A $0802F320-$0802F344,
        // list B $0802F346-$0802F376, claim $0802F76C-$0802F7DA ($1F10 += $110 at $0802F7B0-$0802F7BA),
        // else left for a later frame ($0802F378-$0802F37A)
        PPM_LOAD_BLOCK(sd->blockNum, sd->size);
    }
    ppm_chip_ab_only = 0;
    return complete;                                                   // $0802F594-$0802F5B2
}

// D07, the pose budget pre-check. fw = the frame word of the pose about to be
// drawn, spr_info = its pose data. True = the chip holds this draw (the previous
// pose is drawn, the frame does not advance); false = the pose is drawn.
static inline bool ppm_chip_pose_hold(uint32_t fw, ppm_spr_data_hdr *spr_info) {
    int32_t need = (int32_t) ((fw >> 24) & 0x1F) * 0x110;              // $0802F0A4-$0802F0B6: n = bits 24-28; $0802F0B8-$0802F0BE: n*256 + n*16
    if ((int32_t) ppm_chip_f10 + need <= (int32_t) ppm_chip_f12) {     // $0802F0B8-$0802F0C4: signed, ble -> $0802F0C6
        return false;
    }
    if (need <= (int32_t) ppm_chip_f14) {                              // $0802F2A0-$0802F2AA: (n*16 + n)*16 <= $1F14 -> hold $0802F3C0
        return true;
    }
    if (!spr_info->count) {                                            // $0802F2AC-$0802F2C6: piece count 0 -> drawn, $0802F0C6
        return false;
    }
    return !ppm_chip_preload(spr_info);                                // PROGRESSIVE
}
#endif

// ---------------------------------------------------------------------------
// CHIP ANIMATION QUEUE AND TERMINAL END (2026-10-08; differences D06 and D40)
//
// Same chip image and address convention as above. The AD handler is $080194BC(slot);
// the record is RAMDP $0F80 + 16*slot (+0 anim, +2 nextAnim, +4 objID, +$A the restart
// flag); the handle is $2000FB1C + 16*slot: +0 the frame to draw NEXT, +4 the frame drawn
// last, +8 the first frame of the queued animation, +$C the D18 flag. Per AD:
//   $080194DA-$080194E0  objID word 0: nothing at all (return 0): no restart, no queue step,
//                        no draw, no handle+$C or $1F1A write. Done as the chip does with D06, because ours'
//                        queue step now writes the record and must not for objID 0. The test
//                        sits in ppm_obj_add, before ppm_obj_render is called: inside
//                        ppm_obj_render the early return made GCC's code for the whole
//                        function ~19% slower (estimated with our RV32 cost model), for one compare.
//   $080194E2-$080194E6  +$A != 0: the restart ($0801953E-$0801958E): handle+0 := the
//                        first frame of record anim, handle+8 := 0, handle+$C := 0,
//                        +$A := 0; objID bit 15 also clears handle+4 ($080195B8-$080195C2)
//   $080194EC-$08019522  QUEUE (D06): nextAnim 0 = nothing queued. $FFFF ($080194F2-$080194F6)
//                        or nextAnim >= the object's anim count (the byte table
//                        $2000FB1C+$404+objID, $080194F8-$08019504) CANCELS: handle+8 := 0
//                        ($08019590-$08019596). Otherwise handle+8 := the first frame of
//                        nextAnim ($08019506-$0801951C) and record anim := nextAnim
//                        ($0801951E). Both ways nextAnim := 0 ($08019520-$08019522).
//   $08019524-$08019530  handle+0 == 0: nothing drawn (handle+$C := 1)
//   $08019598-$0801959E  else the composer, $0802F02C(handle, record)
// Composer, after the D07 pre-check passes ($0802F0C6): handle+4 := handle+0 ($0802F0CE),
// then the FRAME STEP, before the pose is drawn:
//   $0802F0D0-$0802F0D6  frame word bit 31 set: more frames -> handle+0 += 4 ($0802F5C4-$0802F5C6)
//   $0802F0D8-$0802F0DE  last frame and handle+8 != 0: END-OF-CYCLE SWITCH (D06), whether the
//                        animation loops or not: handle+0 := handle+8, handle+8 := 0
//                        ($0802F3FC-$0802F402). The record is not written here.
//   $0802F0E0-$0802F0E8  else handle+0 := the loop target (the next word, 19 bits)
//   $0802F0EA-$0802F0EC  loop target 0 = TERMINAL END (D40): record anim := 0. handle+0 is
//                        0, so nothing is drawn after this frame until a restart.
// A HOLD ($0802F3C0-$0802F41C, D07) draws handle+4 and writes neither handle+0 nor handle+8.
//
// The game's setAnim ($31024-$3106C) compares against the record: a plain call with the
// running anim does nothing ($31054-$31056); a queue call (bit 14) with the record's anim
// writes nextAnim := $FFFF ($31046-$31048, $31064), which the chip takes as a cancel. So on
// the chip a re-armed queue cancels itself and the walk-in keeps walking, and a single queue
// (a dropped weapon) switches at the end of the current cycle. Ours left the record alone,
// so the re-arm wrote the queued anim again; the timing heuristics PPM_STICKY_SWITCH,
// PPM_CHAIN_ONLY_AT_END, PPM_CHAIN_FRESH_QUEUE and PPM_CHAIN_PROP_ANIMS worked around that.
//
// PPM_CHIP_ANIM_QUEUE (D06) does the queue move, the cancel rule and the frame step as the chip does. Ours'
// handle then holds the chip's: handle->anim_offset = handle+0 (the frame to draw next),
// handle->lastDisplayedOffset = handle+4 (the frame drawn last, also D07's), and
// handle->chip_queued = handle+8 (ppm_obj's bytes 12-15, which hold prev_next and queue_age
// with this switch off; those serve only PPM_CHAIN_FRESH_QUEUE, compiled out here). The
// frame is stepped where the chip steps it, when a pose is drawn, so the end-of-cycle switch
// sees the queue as it stands at that AD (ours used to decide at the next AD). A held pose
// (D07) leaves handle+0 and handle+8 alone, so a held restart is not lost: this replaces
// PPM_STICKY_SWITCH. The four heuristics are compiled out (mame.h).
// PPM_CHIP_ANIM_END (D40) does the terminal end's record anim := 0 as the chip does.
// Ours keeps its restart rule (D19, not followed: ours restarts on objID bit 15, a changed
// anim or +$A; the chip only on +$A). So that ours' own record writes (the queue move, the
// terminal end) are not read back as the game's, crtAnim follows them.
// B0 (D20, ppm_chip_b0_reset) clears handle+8 with the rest of the handle ($0801947C).
// Not followed, all D19 or D39 (none reachable on the recorded streams): the restart trigger;
// the chip stores objID & $3FFF at a bit-15 restart, ours clears bit 15 only; the chip checks
// the anim and objID ranges only in its restart ($08019540-$08019564) and indexes its count
// table with the raw objID word ($080194FA-$08019500), ours checks anim & $FF on every AD
// and indexes with objID & $FF (equal for all 241 objects of the shipped data); the 50 Hz
// skip ($0802F5B4-$0802F5C2, $0802F702-$0802F706, D39).
#if PPM_CHIP_ANIM_QUEUE && (PPM_STICKY_SWITCH || PPM_CHAIN_ONLY_AT_END || PPM_CHAIN_FRESH_QUEUE || PPM_CHAIN_PROP_ANIMS)
#error PPM_CHIP_ANIM_QUEUE replaces PPM_STICKY_SWITCH and PPM_CHAIN_*: the chip has one queue rule ($080194EC-$08019522, $0802F0D8-$0802F0DE) and no timing or object-class rule
#endif
#if PPM_CHIP_ANIM_END && !PPM_CHIP_ANIM_QUEUE
#error PPM_CHIP_ANIM_END is a branch of the frame step of the chip ($0802F0D8-$0802F0EC), taken at the AD that draws the last frame; ours without PPM_CHIP_ANIM_QUEUE finds the end one AD later, so it needs PPM_CHIP_ANIM_QUEUE
#endif
#if PPM_CHIP_ANIM_QUEUE && !PPM_ANIM_FLAG_SEMANTICS
#error PPM_CHIP_ANIM_QUEUE reads +$A as the chip does, the one-shot restart flag it clears ($0801958C); the old counter reading writes the word of the game every draw, so it needs PPM_ANIM_FLAG_SEMANTICS
#endif
#if PPM_CHIP_ATTR && !PPM_CHIP_ANIM_QUEUE
#error PPM_CHIP_ATTR (D23) reads the drawn frame's word where the D06 path keeps it (handle+0, or handle+4 for a hold), so it needs PPM_CHIP_ANIM_QUEUE
#endif
#if PPM_CHIP_ANIM_QUEUE && PPM_LIST_ORDER_VRAM
#error PPM_CHIP_ANIM_QUEUE assumes the slot loader, not the retired PPM_LIST_ORDER_VRAM stream
#endif
#if PPM_CHIP_ANIM_QUEUE && !PPM_INLINE_COMPOSE
#error PPM_CHIP_ANIM_QUEUE moves the queue at the AD itself ($080194EC-$08019522), so it needs PPM_INLINE_COMPOSE; a render at AF would read the record after the later writes of the game in the same frame
#endif
#if PPM_CHIP_ANIM_QUEUE
_Static_assert(sizeof (ppm_obj) == 16 && __builtin_offsetof(ppm_obj, chip_queued) == 12,
               "D06 keeps the chip's handle+8 in ppm_obj's bytes 12-15; ppm_obj stays 16 bytes");
#endif

void ppm_obj_render(uint16_t obj_slot) {

    ppm_intf_obj *intf_obj = &ppmio.ramdp->obj_data[obj_slot]; // interface obj
    ppm_obj *handle = &ppm_object_handles[obj_slot]; // internal handle

    if ((intf_obj->anim & 0xff) > ppm_anim_max_index[intf_obj->objID & 0xff]) {
#if PPM_ANIMOVER_PRINTF
        printf("anim over for ID %x: 0x%x/0x%x\n", intf_obj->objID & 0xff, intf_obj->anim & 0xff, ppm_anim_max_index[intf_obj->objID & 0xff]);
#endif
#if PPM_SAT_SNAPSHOT
        // Silent drop, now counted - see snap_animover_* for why.
        if (snap_animover_hits != 0xffff) snap_animover_hits++;
        snap_animover_id   = (u8) (intf_obj->objID & 0xff);
        snap_animover_anim = (u8) (intf_obj->anim & 0xff);
        snap_animover_max  = ppm_anim_max_index[intf_obj->objID & 0xff];
#endif
        return;
    }

    uint32_t offset, data_offset;
#if PPM_CHIP_ANIM_QUEUE
    // D06, see CHIP ANIMATION QUEUE above. anim_offset is the chip's handle+0 (the frame
    // to draw next), lastDisplayedOffset its handle+4, chip_queued its handle+8.
#if PPM_SAT_SNAPSHOT
    bool restarted = false;                     // diagnostics only: a restart held on this draw
#endif
    // restart: ours' rule, not the chip's (D19 not followed); what it does is the chip's
    // restart, $0801953E-$0801958E
    if ((intf_obj->objID & 0x8000) || (intf_obj->anim != handle->crtAnim) || (intf_obj->animCounter != handle->counter)) {
        if (intf_obj->objID & 0x8000) {
            handle->lastDisplayedOffset = 0;    // $080195B8-$080195BE: handle+4 := 0
            intf_obj->objID &= 0x7fff;          // before the composer, held or not. The chip stores objID & $3FFF
                                                // ($0801953E-$08019540, strh $080195BC); ours clears bit 15 only (D19)
        }
        offset = ppm_anim_data[(intf_obj->objID & 0xff) + 1]; // obj offset
        handle->anim_offset = ppm_anim_data[(offset >> 2) + (intf_obj->anim & 0xff)];  // $0801956E-$08019584: handle+0 := first frame
        handle->chip_queued = 0;                // $08019586-$08019588: handle+8 := 0
        handle->crtAnim = intf_obj->anim;
        handle->counter = intf_obj->animCounter;
#if PPM_CHIP_READY_FLAG
        if (intf_obj->animCounter) {
            ppm_chip_shown[obj_slot] = 0;       // D18: +$A != 0 is a restart ($080194E2-$080194E6): handle+$C := 0, $0801958A
        }
#endif
        if (intf_obj->animCounter == 1) {       // PPM_ANIM_FLAG_SEMANTICS: the restart flag is consumed,
            intf_obj->animCounter = 0;          // +$A := 0 ($0801958C)
            handle->counter = 0;
        }
#if PPM_SAT_SNAPSHOT
        restarted = true;
#endif
    }
    // queue, $080194EC-$08019522: the queue moves into the handle at once
    {
        uint16_t queued = intf_obj->nextAnim;   // $080194EC
        if (queued) {                           // $080194EE-$080194F0: 0 = nothing queued
            if (queued == 0xffff ||             // $080194F2-$080194F6: cancel
                    queued >= (uint16_t) (ppm_anim_max_index[intf_obj->objID & 0xff] + 1)) {   // $080194F8-$08019504: >= the anim count, cancel
                handle->chip_queued = 0;        // $08019590-$08019594: handle+8 := 0
            } else {
                offset = ppm_anim_data[(intf_obj->objID & 0xff) + 1];
                handle->chip_queued = ppm_anim_data[(offset >> 2) + queued];          // $08019506-$0801951C: handle+8 := its first frame
                intf_obj->anim = queued;        // $0801951E: record anim := queued
                handle->crtAnim = queued;       // ours' restart rule must not read our own write as the game's
            }
            intf_obj->nextAnim = 0;             // $08019520-$08019522
        }
    }
    if (!(offset = handle->anim_offset)) {      // $08019524-$08019528: no frame to draw
#if PPM_CHIP_READY_FLAG
        ppm_chip_shown[obj_slot] = 1;           // D18: handle+$C := 1 ($0801952A-$08019530)
#endif
        return;
    }
#if PPM_CHIP_ATTR
    uint32_t pose_word = ppm_anim_data[offset >> 2];        // the frame word of handle+0 ($0802F0A6); D23 reads its bit 29
    data_offset = pose_word & 0xffffffu;                    // the pose of handle+0 ($0802F09A-$0802F0A6)
#else
    data_offset = ppm_anim_data[offset >> 2] & 0xffffffu; // the pose of handle+0 ($0802F09A-$0802F0A6)
#endif
#else
#if PPM_CHIP_POSE_HOLD
    // D07: a hold draws the chip's handle+4, the frame its normal path last drew
    // (stored at $0802F0CE). It survives a terminal end, where the chip clears only
    // the frame pointer ($0802F0E0-$0802F0EC) and ours clears anim_offset, so after
    // a terminal end and a held restart the chip still draws the old last frame.
    // Kept in the handle's unused lastDisplayedOffset; equal to anim_offset otherwise.
    uint32_t previous_offset = handle->lastDisplayedOffset;
#else
    uint32_t previous_offset = handle->anim_offset;
#endif
    uint16_t previous_counter = handle->counter;
#if PPM_CHAIN_FRESH_QUEUE
    // How long has the game's queue been standing? Armed on this draw = 0. A
    // queue armed at an end, or on the draw that set the animation, means
    // "switch when this finishes"; one armed mid-cycle is a fallback the game
    // resolves itself within 41 draws, and acting on THAT is what strands a
    // character in its standing pose. See mame.h for the measurements.
    // A recycled slot must not inherit the last tenant's queue: a weapon created
    // with its follow-up already armed would read as an old queue and never chain.
    if (intf_obj->objID & 0x8000) {
        handle->prev_next = 0xffff;
    }
    if (intf_obj->nextAnim == 0xffff) {
        handle->queue_age = 0xff;
    } else if (handle->prev_next == 0xffff) {
        handle->queue_age = 0;
    } else if (handle->queue_age < 0xff) {
        handle->queue_age++;
    }
    handle->prev_next = intf_obj->nextAnim;
    uint8_t queue_age = handle->queue_age;
#endif
#if PPM_STICKY_SWITCH
    uint16_t previous_crtAnim = handle->crtAnim;
    bool switched = false;
#endif

    //	printf("Slot 0x%02x (ID 0x%04x): ", obj_slot, intf_obj->objID);

    // set / update animation
    if ((intf_obj->objID & 0x8000) || (intf_obj->anim != handle->crtAnim) || (intf_obj->animCounter != handle->counter)) {
        // fresh obj?
        if (intf_obj->objID & 0x8000) {
            previous_offset = 0, previous_counter = 1;
#if PPM_CHIP_POSE_HOLD
            handle->lastDisplayedOffset = 0;    // restart with objID bit 15: handle+4 := 0, $080195B8-$080195BE
#endif
        }

        offset = ppm_anim_data[(intf_obj->objID & 0xff) + 1]; // obj offset
        offset = ppm_anim_data[(offset >> 2) + (intf_obj->anim & 0xff)]; // anim offset
        data_offset = ppm_anim_data[offset >> 2] & 0xffffffu; // data offset

        handle->anim_offset = offset;
        handle->crtAnim = intf_obj->anim;
        handle->counter = intf_obj->animCounter;
#if PPM_CHIP_READY_FLAG
        if (intf_obj->animCounter) {
            ppm_chip_shown[obj_slot] = 0;   // D18: +$A != 0 is a restart ($080194E2-$080194E6): handle+$C := 0, $0801958A
        }
#endif
#if PPM_ANIM_FLAG_SEMANTICS
        // The animation has just been (re)loaded from its first frame, which is
        // exactly what a restart request asks for - so acknowledge it by writing
        // 0 back, as GPGX does. Without this the field never returns to 0 and the
        // game can never issue a second request.
        if (intf_obj->animCounter == 1) {
            intf_obj->animCounter = 0;
            handle->counter = 0;
        }
#endif
#if PPM_STICKY_SWITCH
        switched = true;
#endif
    } else {
        // move to next frame

        // get current offset (previous frame)
        if (!(offset = handle->anim_offset)) {
#if PPM_CHIP_READY_FLAG
            ppm_chip_shown[obj_slot] = 1;   // D18: no frame pointer, handle+$C := 1 ($08019524-$08019530)
#endif
            return;
        }
        // read data pointer
        data_offset = ppm_anim_data[offset >> 2];

        if (data_offset & 0x80000000u) {
            // previous frame was not last, just move to next
            offset += 4;
        } else {
            // anim is over, do we have fallback anim?
#if PPM_CHAIN_ONLY_AT_END
            // See PPM_CHAIN_ONLY_AT_END in mame.h: a looping animation ignores the
            // queued follow-up; only a terminal end (loop target 0) takes it.
            if (intf_obj->nextAnim != 0xffff &&
                ((ppm_anim_data[(offset + 4) >> 2] & 0xffffffu) == 0
#if PPM_CHAIN_FRESH_QUEUE
                 // an actor chains at a looping end only for a queue armed at
                 // that end - see PPM_CHAIN_FRESH_QUEUE in mame.h
                 || queue_age <= PPM_CHAIN_FRESH_WINDOW
#endif
#if PPM_CHAIN_PROP_ANIMS
                 // a prop always chains: it has no state machine behind it, and
                 // the game drops one and never writes its animation again
                 || ppm_anim_max_index[intf_obj->objID & 0xff] < PPM_CHAIN_PROP_ANIMS
#endif
                )) {
#else
            if (intf_obj->nextAnim != 0xffff) {
#endif
                // yes, switch anims
                intf_obj->anim = intf_obj->nextAnim;
                intf_obj->nextAnim = 0xffff; // unverified
                ppm_obj_render(obj_slot);
                hb_w8(9, 9);
                return;
            } else {
                // no, take anim loop
                offset = ppm_anim_data[(offset + 4) >> 2] & 0xffffffu;
            }
        }

        if (!(handle->anim_offset = offset)) {
            // store offset
#if PPM_CHIP_READY_FLAG
            ppm_chip_shown[obj_slot] = 1;   // D18: terminal end, no frame pointer: handle+$C := 1 ($08019524-$08019530)
#endif
            return;
        }

        data_offset = ppm_anim_data[offset >> 2] & 0xffffffu;
#if PPM_ANIM_FLAG_SEMANTICS
        // Do NOT write the game's flag. Mirror it instead, so the switch test
        // above still fires when the GAME writes it and never on our own account.
        handle->counter = intf_obj->animCounter;
#else
        intf_obj->animCounter++;
        handle->counter++;
#endif
    }
#endif

    // render sprite to SAT
    // > data might not be 4 bytes aligned, access via ppm_sdram <
    ppm_spr_data_hdr *spr_info = (ppm_spr_data_hdr *) & ppmio.sdram[(ppm_anim_data_base_addr + data_offset)];
    hb_w8(9, 2); hb_w8(10, (u8) obj_slot); hb_w16(12, spr_info->count); hb_w32(24, data_offset);
#if PPM_PORT2_LOAD
    memcpy(&ppmio.sdram[0x1F0000], &ppmio.sdram[0x1E0000], PPM_PORT2_LOAD_BYTES);   // port2 traffic only; nothing reads it
#endif
    ppm_sat_item *satEntry = &ppmio.ramdp->sat_data[ppmio.ramdp->sat_count];
    int16_t posX = intf_obj->posX;
    int16_t posY = intf_obj->posY;

#if PPM_CHIP_BUDGET
    ppm_chip_f10 = ppmio.ramdp->dma_total;          // $0802F050-$0802F056: sp[0] := $1F10
    ppm_chip_f12 = ppmio.ramdp->dma_budget;         // $0802F03A-$0802F046: sp[8] := $1F12
#endif
#if PPM_CHIP_POSE_HOLD
    ppm_chip_f14 = ppmio.ramdp->dma_remaining;      // $0802F048-$0802F04E: sp[$18] := $1F14 (the game's word)
#endif
    bool blocks_available = true;
    // load new spr data
    ppm_spr_data *spr_data = &spr_info->sprites[0];

#if PPM_LIST_ORDER_VRAM
    uint16_t stream_tiles[64];
    if (spr_info->count > 64) blocks_available = false;
    else blocks_available = ppm_stream_walk(spr_info, stream_tiles);
#elif PPM_CHIP_CACHE_MISS
    // D04: no separate load pass and no all-or-nothing verdict. Each piece is found
    // or loaded in the compose loop below, one at a time, as the chip does
    // ($0802F1A4-$0802F298; H-flip $0802F49C-$0802F592), so blocks_available stays
    // true and the whole-object rewind below never runs - except for a D07 hold
    // (PPM_CHIP_POSE_HOLD), which uses it to draw the previous pose.
#else
    for (uint16_t x = 0; x < spr_info->count; spr_data++, x++) {

        if (!spr_data->blockNum) {
            continue;
        }

        if (!PPM_LOAD_BLOCK(spr_data->blockNum, spr_data->size)) {
            blocks_available = false;
            // break; need to iterate all to keep resevations?
        }
    }
#endif

#if PPM_CHIP_POSE_HOLD
    // D07: pre-check the pose about to be drawn ($0802F09A-$0802F0C4), and pre-load
    // it if it can never fit one frame ($0802F2AC-$0802F5B2). A hold ($0802F3C0) is
    // the rewind below: previous pose drawn, frame not advanced, a switch kept pending.
    if (ppm_chip_pose_hold(ppm_anim_data[handle->anim_offset >> 2], spr_info)) {
        blocks_available = false;
    }
#endif
#if PPM_STICKY_SWITCH && PPM_SAT_SNAPSHOT
    if (switched && blocks_available && previous_crtAnim == PPM_ANIM_PENDING) {
        if (snap_switch_retry_ok != 0xffff) snap_switch_retry_ok++;
    }
#endif
    hb_w8(9, 7);
    if (!blocks_available) {
#if PPM_CHIP_READY_FLAG
        if (!ppm_chip_shown[obj_slot]) {
            ppmio.ramdp->unk_1f1a = 0;      // D18: held (return 0, $0802F3C0-$0802F3C4) before its first draw since
        }                                   // the restart: $1F1A := 0, $080195A0-$080195B4
#endif
#if PPM_STICKY_SWITCH
        // See PPM_STICKY_SWITCH in mame.h. The game's anim word and its one-shot
        // reset stay exactly as it wrote them; the sentinel makes the next draw
        // take the set/update path again whichever of the three triggers it was
        // (anim change, forced restart of the same anim, or a nextAnim chain).
        if (switched) {
            handle->crtAnim = PPM_ANIM_PENDING;
#if PPM_SAT_SNAPSHOT
            if (snap_switch_refused != 0xffff) snap_switch_refused++;
#endif
        }
#endif
#if PPM_CHIP_ANIM_QUEUE
        // D06: HOLD, $0802F3C0-$0802F41C. handle+0 and handle+8 stay as they are (a held
        // restart or a pending switch is kept by them, not by a sentinel); the frame drawn
        // last, handle+4, is drawn again ($0802F404-$0802F41C -> $0802F108).
        uint32_t previous_offset = handle->lastDisplayedOffset;    // $0802F3C2
#if PPM_SAT_SNAPSHOT
        if (restarted && snap_switch_refused != 0xffff) snap_switch_refused++;     // a restart held on its first draw
#endif
#endif

        if (previous_offset) {
#if !PPM_CHIP_ANIM_QUEUE
            // restore offset/counter
            handle->anim_offset = previous_offset;
            handle->counter = previous_counter;
#if PPM_ANIM_FLAG_SEMANTICS
            // Nothing to rewind: this firmware no longer writes the field at all.
            (void) previous_counter;
#else
#if PPM_STICKY_SWITCH
            if (!switched)      // a refused ADVANCE rewinds the counter too; a refused switch leaves the game's reset in place
#endif
            intf_obj->animCounter = previous_counter;
#endif
#endif
#if PPM_CHIP_ATTR
            pose_word = ppm_anim_data[previous_offset >> 2];   // D23: a hold tests bit 29 of handle+4's word ($0802F40C-$0802F41C)
            data_offset = pose_word & 0xffffff;
#else
            data_offset = ppm_anim_data[previous_offset >> 2] & 0xffffff;
#endif
            spr_info = (ppm_spr_data_hdr *) & ppmio.sdram[(ppm_anim_data_base_addr + data_offset)];
#if PPM_PIN_FALLBACK && !PPM_CHIP_CACHE_LISTS
            {
                ppm_spr_data *fb = &spr_info->sprites[0];
                for (uint16_t x = 0; x < spr_info->count; fb++, x++) {
                    if (fb->blockNum) {
                        ppm_vram_touch_block(fb->blockNum);
                    }
                }
            }
#endif

        } else {
#if PPM_CHIP_BUDGET
            // held with no previous frame, $0802F3C8 -> $0802F3CA-$0802F3D6: $1F10 is
            // stored all the same (the D07 pre-load pass may have loaded)
            ppmio.ramdp->dma_total = ppm_chip_f10;
#endif
#if PPM_CHIP_POSE_HOLD
            intf_obj->objID &= 0x7fff;      // the chip clears bit 15 before the composer, held or not ($080195B8-$080195BC)
#endif
            return;
        }
    }
#if PPM_CHIP_POSE_HOLD || PPM_CHIP_ANIM_QUEUE
    else {
        handle->lastDisplayedOffset = handle->anim_offset;  // drawn: handle+4 := this frame, $0802F0CE (before the pieces)
#if PPM_CHIP_ANIM_QUEUE
        // D06 frame step, done where the chip does it: at the draw, before the pieces
        {
            uint32_t next = handle->anim_offset;
            if (ppm_anim_data[next >> 2] & 0x80000000u) {   // $0802F0D0-$0802F0D6: bit 31 set, more frames follow
                next += 4;                                  // $0802F5C4-$0802F5C6 (the 50 Hz skip $0802F5B4-$0802F5C2 is D39, not followed)
            } else if (handle->chip_queued) {               // $0802F0D8-$0802F0DE: last frame, an animation queued:
                next = handle->chip_queued;                 // $0802F3FC: switch at this cycle end, looping or terminal
                handle->chip_queued = 0;                    // $0802F3FE-$0802F400: handle+8 := 0
            } else {
                next = ppm_anim_data[(next + 4) >> 2] & 0x7ffffu;   // $0802F0E0-$0802F0E6: the loop target, 19 bits
#if PPM_CHIP_ANIM_END
                if (!next) {                                // $0802F0EA: terminal end (D40)
                    intf_obj->anim = 0;                     // $0802F0EC: record anim := 0
                    handle->crtAnim = 0;                    // ours' restart rule must not read our own write as the game's
                }
#endif
            }
            handle->anim_offset = next;                     // $0802F0E8 / $0802F3FC / $0802F5C6: handle+0
        }
#endif
#if PPM_CHIP_READY_FLAG
        ppm_chip_shown[obj_slot] = 1;       // D18: drawn, the composer returns 1 ($0802F102): handle+$C := 1 ($0801952A-$08019530)
#endif
    }
#endif

#if PPM_LIST_ORDER_VRAM
    // No re-walk on fallback: a second walk advanced the cursor twice and shifted
    // every later object. The previous animation's sprites take the tiles recorded
    // for the new one's positions - one object stale for one frame, layout intact.
#endif
    spr_data = &spr_info->sprites[0];
#if PPM_CHIP_CLIP
    // s1 images (2026-10-17): the record's attribute word and the door test read once (the 68000 waits for the reply, so
    // the record cannot change while the AD runs; every RAMDP read costs MCU time in AD's L1)
    const uint16_t rec_attrs = intf_obj->attrs;
#if PPM_CHIP_ATTR
    // D23 (test build 4 on, 2026-10-18), once per pose as the chip does: pose bit 29 (bit 5 of the frame word's top
    // byte) clears the object's palette bits ($0802F104-$0802F112: [sp+$14] &= $FFFF9FFF); the H-flip test reads the
    // result ($0802F12E-$0802F130); the flip path keeps the object word less $800 ($0802F41E-$0802F428, uxth) and XORs
    // $800 into each piece word ($0802F47A-$0802F47E). The plain path adds the words as they are ($0802F186-$0802F190).
    uint16_t attr_obj = rec_attrs;
#if SPR_BUG != 6
    if (pose_word & 0x20000000u) {
        attr_obj &= 0x9fff;
    }
#endif
    uint16_t attr_xor = 0;
#if SPR_BUG != 7
    if (attr_obj & 0x0800) {
        attr_obj = (uint16_t) (attr_obj - 0x0800);
        attr_xor = 0x0800;
    }
#endif
#elif PPM_DOOR_FIX
    const int rec_door = (intf_obj->objID & 0xff) == 107;
#endif
#endif


    for (uint16_t x = 0; x < spr_info->count; spr_data++, x++) {
        hb_w8(9, 8); hb_w8(11, (u8) x);

        posX += (intf_obj->attrs & 0x0800) ? spr_data->flipPosX : spr_data->posX;
        posY += spr_data->posY;

        if (!spr_data->blockNum) {
            continue;
        }
#if PPM_CHIP_CACHE_MISS
        // Per piece, before the clip test (the chip marks and loads off-screen pieces
        // too): hit $0802F1C2-$0802F1CA -> countdown $20 $0802F156-$0802F158; miss
        // $0802F1CC-$0802F298 -> claim $0802F666-$0802F6FC. When nothing can be
        // claimed (budget, the 15-load cap or no slot) the piece is dropped:
        // $0802F298 / $0802F29E -> $0802F19A, the next piece, no SAT entry.
        uint16_t piece_tile = PPM_LOAD_BLOCK(spr_data->blockNum, spr_data->size);
        if (!piece_tile) {
            continue;
        }
#endif

#if PPM_CHIP_CLIP
        // D24, the chip's clip (s1 images, 2026-10-17): after the piece's load or hit, one test on X alone,
        // ($61 <= X <= $1BF) as one unsigned 16-bit compare ($0802F15A-$0802F166; H-flip $0802F44E-$0802F45A);
        // Y is never tested, so pieces above or below the screen get entries as on the cart (the count $1F18 the
        // game's 80+ gate reads). X and Y are the 16-bit sums of the object's position and the piece offsets,
        // stored unmasked as the chip stores them.
        if ((uint16_t) (posX - 0x61) > 0x15E) {
            continue;
        }
        {
            // The entry, the same bytes as 0.2.6's field stores (the chip's Y, link, attr, X): the count read once,
            // Y | link and attr | X as two 32-bit stores (MCU time in AD's L1; the 68000 reads none of it before the
            // reply). The attribute word: the chip's (D23, test build 4 on; PPM_CHIP_ATTR), else 0.2.6's rule and door
            // fix.
            uint16_t cnt = (uint16_t) (ppmio.ramdp->sat_count + 1);
            uint16_t attr;
            ppmio.ramdp->sat_count = cnt;
#if PPM_CHIP_ATTR
            // D23: piece word (attr << 8 | offset, the halfword at piece +6, $0802F188 / $0802F47A) [^ $800 with H-flip]
            // + the object word + id x 16 (piece_tile, $0802F18C), one 16-bit sum stored at entry +4 ($0802F192 / $0802F48E)
            attr = (uint16_t) (((((uint16_t) spr_data->attrs << 8) | spr_data->offset) ^ attr_xor) + attr_obj + piece_tile);
#elif PPM_FIELDWISE_ATTRS
            {
                uint16_t tileAttr = (spr_data->attrs & 0xf8) << 8;
                uint16_t objAttr  = rec_attrs;
#if PPM_CHIP_CACHE_MISS
                uint16_t tileIdx  = piece_tile + spr_data->offset;     // id*16 + offset, as $0802F18C-$0802F190
#else
#error "stage 1 composes with the chip's cache (PPM_CHIP_CACHE_MISS)"
#endif
                // tile wins for priority and palette; flip and tile index stay XOR
                uint16_t pri  = (tileAttr & 0x8000) ? (tileAttr & 0x8000) : (objAttr & 0x8000);
                uint16_t pal  = (tileAttr & 0x6000) ? (tileAttr & 0x6000) : (objAttr & 0x6000);
                uint16_t flip = (tileAttr ^ objAttr) & 0x1800;
                uint16_t tile = (objAttr ^ tileIdx) & 0x07ff;
                attr = pri | pal | flip | tile;
            }
#elif PPM_CHIP_CACHE_MISS
            attr = ((spr_data->attrs & 0xf8) << 8) ^ rec_attrs ^ (piece_tile + spr_data->offset);
#else
#error "stage 1 composes with the chip's cache (PPM_CHIP_CACHE_MISS)"
#endif
#if PPM_DOOR_FIX && !PPM_CHIP_ATTR
            if (rec_door && x == 4) {           // krikzz's first-level door fix (object 107, sprite 4), as below
                attr &= ~0x2000;
            }
#endif
#if PPM_FORCE_SPRITE_PRI
            attr |= 0x8000;
#endif
            ((vu32 *) satEntry)[0] = (uint32_t) (uint16_t) posY
                                   | ((uint32_t) (((spr_data->size & 0xf) << 8) + (cnt & 0xff)) << 16);
            ((vu32 *) satEntry)[1] = (uint32_t) attr | ((uint32_t) (uint16_t) posX << 16);
        }
#else
        // clipping
        if ((posX >= 320 + 128) ||
                (posY >= 240 + 128) ||
                (posX < 128 - ((((spr_data->size >> 2) & 0x3) + 1) * 8)) ||
                (posY < 128 - (((spr_data->size & 0x3) + 1) * 8))) {
            continue;
        }

        ppmio.ramdp->sat_count++;
        satEntry->posX = posX & 0x1ff;
        satEntry->posY = posY & 0x3ff;
        satEntry->sizeNext = ((spr_data->size & 0xf) << 8) + (ppmio.ramdp->sat_count & 0xff);
#if PPM_FIELDWISE_ATTRS
        {
            uint16_t tileAttr = (spr_data->attrs & 0xf8) << 8;
            uint16_t objAttr  = intf_obj->attrs;
#if PPM_LIST_ORDER_VRAM
            uint16_t tileIdx  = stream_tiles[x];
#elif PPM_CHIP_CACHE_MISS
            uint16_t tileIdx  = piece_tile + spr_data->offset;     // id*16 + offset, as $0802F18C-$0802F190
#else
            uint16_t tileIdx  = ppm_vram_find_block(spr_data->blockNum) + spr_data->offset;
#endif

            // tile wins for priority and palette; flip and tile index stay XOR
            uint16_t pri  = (tileAttr & 0x8000) ? (tileAttr & 0x8000) : (objAttr & 0x8000);
            uint16_t pal  = (tileAttr & 0x6000) ? (tileAttr & 0x6000) : (objAttr & 0x6000);
            uint16_t flip = (tileAttr ^ objAttr) & 0x1800;
            uint16_t tile = (objAttr ^ tileIdx) & 0x07ff;

            satEntry->attrs = pri | pal | flip | tile;
        }
#elif PPM_CHIP_CACHE_MISS
        satEntry->attrs = ((spr_data->attrs & 0xf8) << 8) ^ intf_obj->attrs ^ (piece_tile + spr_data->offset);
#else
        satEntry->attrs = ((spr_data->attrs & 0xf8) << 8) ^ intf_obj->attrs ^ (ppm_vram_find_block(spr_data->blockNum) + spr_data->offset); // whole attr word?
#endif

        // paprium-pocket: krikzz's first-level door fix, re-applied. Object 107's
        // sprite 4 is the Block 888 door, and it composes with palette bit 0x2000
        // set, so it renders in the wrong colours. Reported by MisterPezz82 as
        // "object 107 sprite 4, attr &= ~0x2000" and shipped in their V.05; krikzz
        // supplied it privately, so the public mega-ppm tree does not carry it.
#if PPM_DOOR_FIX
        if ((intf_obj->objID & 0xff) == 107 && x == 4) {
            satEntry->attrs &= ~0x2000;
        }
#endif

#if PPM_FORCE_SPRITE_PRI
        // OR'd on AFTER field-wise composition and after the door fix, so this
        // does not fight either path - whatever they decided, priority ends set.
        satEntry->attrs |= 0x8000;
#endif
#endif
        satEntry++;
    }

#if PPM_CHIP_BUDGET
    ppmio.ramdp->dma_total = ppm_chip_f10;          // $0802F3CA-$0802F3D6: $1F10 stored at exit
#endif
    intf_obj->objID &= 0x7fff;
}

#if PPM_CHIP_CACHE_LISTS
uint16_t ppm_vram_load_block(uint16_t num, uint8_t size) {
#else
uint16_t ppm_vram_load_block(uint16_t num) {
#endif

    if (!num) {
        return 0;
    }

    // is block already in VRAM?
    ppm_vram_slot *slot = ppm_vram_slots;

    for (uint16_t x = 0; x < ppm_vram_max_slot; slot++, x++) {

        if (slot->block_num == num) {
#if !(FW_S1 && PPM_CHIP_CACHE_LISTS)   // s1 images: nothing reads them with the chip's lists (ppm_obj_frame_start)
            slot->usage++;
            slot->age = 0;
#endif
#if PPM_CHIP_CACHE_LISTS
            ppm_chip_cd[x] = 0x20;          // hit: $0802F1C2-$0802F1CA, countdown := $20 at $0802F156-$0802F158
#endif
#if PPM_LIST_ORDER_VRAM
            return x + 1;                                  // cache slot + 1; the walk places tiles
#else
            return (PPM_SLOT_ID(x) << 4);
#endif
        }
    }

    // enough DMA budget?
#if PPM_CHIP_BUDGET
    // D09 gate, $0802F1CC-$0802F1D6 (H-flip $0802F4C4-$0802F4CE, D07 pre-load
    // $0802F30A-$0802F316): r0 = sp[0] + $10 + $FF; cmp sp[8], r0; ble -> no load.
    if ((int32_t) ppm_chip_f12 <= (int32_t) ppm_chip_f10 + 0x10F) {
#else
    bool floor_grant = false;
#if PPM_DMA_FLOOR_BLOCKS && !PPM_LIST_ORDER_VRAM
    // See PPM_DMA_FLOOR_BLOCKS in mame.h: the shared word is spent (by the game's
    // own descriptors, or by us), but the vblank still has room for a few blocks.
    if (ppmio.ramdp->dma_remaining < 0x110 && ppm_floor_used < PPM_DMA_FLOOR_BLOCKS) {
        floor_grant = true;
    }
#endif
#if PPM_LIST_ORDER_VRAM
    if (0) {   // the stream never refuses for budget: 1,800 refusals in 1,187 title frames skipped sprites and drifted the cursor
#else
    if (ppmio.ramdp->dma_remaining < 0x110 && !floor_grant) {
#endif
#endif
#if PPM_SAT_SNAPSHOT
        if (snap_dma_starved != 0xffff) snap_dma_starved++;
#endif
#if PPM_ONSET_RING
        if (snap_f_refuse != 0xff) snap_f_refuse++;
#endif
        return 0;
    }

#if PPM_CHIP_CACHE_MISS && PPM_CHIP_LOAD_CAP
    // $0802F1D8-$0802F1DE: no load once 15 are in the load list ($20010028 > 14)
    if (ppm_chip_loads >= PPM_CHIP_LOAD_CAP) {
        return 0;
    }
#endif

#if PPM_CHIP_CACHE_LISTS
    // D02: list A, list B, the related block, list C ($0802F1E0-$0802F298)
    uint16_t block_index = 0xffff;
    {
        int v = ppm_chip_victim(num, size);
        if (v >= 0) {
            block_index = (uint16_t) v;
        }
    }
#else
    // find oldest slot to load into
    uint32_t max_age = 0;
    uint16_t block_index = 0xffff;
    slot = ppm_vram_slots;

    for (uint16_t x = 0; x < ppm_vram_max_slot; slot++, x++)
        if ((!slot->usage) && (slot->age > max_age)) {
            max_age = slot->age;
            block_index = x;
        }
#endif

    // no slot available?
    if (block_index == 0xffff) {
#if PPM_SAT_SNAPSHOT
        if (snap_noslot != 0xffff) snap_noslot++;
#endif
        return 0;
    }

    // found slot & have budget, unpack and DMA the block
    slot = &ppm_vram_slots[block_index];
#if PPM_SAT_SNAPSHOT
    // Count only evictions that DESTROY something: the slot held a real block and
    // is being handed to a different one. Re-taking a slot for the same block is
    // not a loss.
    if (slot->block_num && slot->block_num != num) {
        snap_evict_live++;
        if (snap_evict_frame != 0xffff) snap_evict_frame++;
        snap_evicted_ring[snap_evicted_at] = slot->block_num;
        snap_evicted_at = (u8) ((snap_evicted_at + 1) & 31);
    }
    // Was the block we are ABOUT TO LOAD one we evicted recently? That is
    // thrashing - paying to fetch back what we just threw away - and it means the
    // slot budget is short for the scene rather than the eviction being one-way.
    for (u8 q = 0; q < 32; q++) {
        if (snap_evicted_ring[q] == num) {
            if (snap_evict_reload != 0xffff) snap_evict_reload++;
            snap_evicted_ring[q] = 0;
            break;
        }
    }
#endif
    slot->block_num = num;              // claim $0802F66E-$0802F69C: old block out, new block in
#if !(FW_S1 && PPM_CHIP_CACHE_LISTS)   // s1 images: nothing reads them with the chip's lists (ppm_obj_frame_start)
    slot->usage++;
    slot->age = 0;
#endif
#if PPM_CHIP_CACHE_LISTS
    ppm_chip_cd[block_index] = 0x20;    // $0802F6FC-$0802F700 -> $0802F156-$0802F158
#endif
#if PPM_CHIP_CACHE_MISS && PPM_CHIP_LOAD_CAP
    ppm_chip_loads++;                   // $0802F6DE-$0802F6FA: block appended to the load list
#endif

#if PPM_SAT_SNAPSHOT
    snap_loads_ok++;                    // counted here, control flow untouched
#if PPM_ONSET_RING
    if (snap_f_load != 0xff) snap_f_load++;
#endif
    if ((u32) ppm_block_unpack_addr + 0x200 > snap_loader_high_since_da) {
        snap_loader_high_since_da = (u32) ppm_block_unpack_addr + 0x200;
    }
#endif
#if PPM_LIST_ORDER_VRAM
    ppm_unpack(ppm_block_addr(num), PPM_BLOCK_CACHE_BASE + (uint32_t) block_index * 0x200);
    slot->block_num = num;
    slot->usage++;
    return block_index + 1;
#else
#if FW_S1   // MCU interface v1.2: the cart's FPGA decodes the block (D43), and so does ours (the RTL): it is listed here,
            // the flush pushes the list (core/dispatch flush_regs), the RTL decodes it to this same slot
    ppm_chip_load_addr[ppm_chip_loads - 1u] = ppm_block_addr(num);
#if S1_BUG == 3
    ppm_unpack(ppm_block_addr(num), ppm_block_unpack_addr);   // planted (fuzz_s1 FZ12 decode): 0.2.6's place, in L1
#endif
#else
    ppm_unpack(ppm_block_addr(num), ppm_block_unpack_addr);
#endif
    ppm_block_unpack_addr += 0x200;

    ppm_dma_cmd *dma_entry = &ppmio.ramdp->dma_cmd[ppmio.ramdp->dma_cmd_count++];

#if PPM_CHIP_BUDGET
    ppm_chip_f10 = (uint16_t) (ppm_chip_f10 + 0x110);  // D09: $0802F6C8-$0802F6D6 (H-flip $0802F62C-$0802F63A,
                                                    // pre-load $0802F7B0-$0802F7BA): sp[0] += $110, uxth
#else
#if PPM_DMA_FLOOR_BLOCKS
    if (floor_grant) {
        ppm_floor_used++;               // carried by the floor; the shared word is already spent
    } else
#endif
    ppmio.ramdp->dma_remaining -= 0x110;
#endif
#if PPM_CHIP_CACHE_CLAIM
    // $0802F69E-$0802F6C6: the chip's word order (mame.h field names, chip values and order):
    // 8F02, 9300, 9500, 9401, 9700, 9660 = 0x100 words from $C000, then the command
    // words of $08025EF0[id] / $08025DF0[id] (= the formula below, checked id 0..$7F)
    dma_entry->autoinc = 0x8f02;    // word 0
    dma_entry->lenH = 0x9300;       // word 1
    dma_entry->lenL = 0x9500;       // word 2
    dma_entry->srcH = 0x9401;       // word 3
    dma_entry->srcM = 0x9700;       // word 4
    dma_entry->srcL = 0x9660;       // word 5
#else
    dma_entry->autoinc = 0x8f02;
    dma_entry->lenH = 0x9401;
    dma_entry->lenL = 0x9300; // 0x100 words = one 0x200-byte block (the comment used to say 0x200 words)
    dma_entry->srcH = 0x9700;
    dma_entry->srcM = 0x9660;
    dma_entry->srcL = 0x9500; // 0xc000 source
#endif

    block_index = PPM_SLOT_ID(block_index); // translate index
    uint32_t command = (((block_index << 25) | (block_index >> 5)) & 0x3fff0003) | 0x40000080;

    dma_entry->cmdH = command >> 16;
    dma_entry->cmdL = command;

    //printf("vram %x %x\n", block_index, command);

    return (block_index << 4);
#endif
}

u32 ppm_block_addr(u32 num) {

    return ppm_gfx_blocks_base_addr + swapshorts(ppm_gfx_blocks_offsets[(num)]);
}

u32 ppm_bgm_addr(u32 num) {

    return ppm_bgm_tracks_base_addr + swapshorts(ppm_bgm_tracks_offsets[(num)]);
}

uint16_t ppm_vram_find_block(uint16_t num) { // return tile index
#if PPM_LIST_ORDER_VRAM
    (void) num; return 0;                     // the stream walk records tiles; nothing looks them up
#endif

    ppm_vram_slot *slot = ppm_vram_slots;

    for (uint16_t x = 0; x < ppm_vram_max_slot; slot++, x++) {

        if (slot->block_num == num) {

            return (PPM_SLOT_ID(x) << 4);
        }
    }
    return 0;
}

#if !FW_S1   // s1 images: moved to interim/s1/f5_s1.c (s1_stamp_rescale) with a static buffer: F5 is a job there
void ppm_stamp_rescale(uint16_t window_start, uint16_t window_end, uint16_t factor, uint16_t stamp_offset) {

    // prepare temp buffer
    uint8_t scaled_stamp[128][32];

    memset(scaled_stamp, 0, sizeof (scaled_stamp));

    // scale the stamp in temp buffer
    float offset = (float) stamp_offset;
    float adder = (float) factor / 64;
    for (uint16_t y = window_start; y < window_end; offset += adder, y++)
        memcpy(&scaled_stamp[y][0], &ppm_scale_stamp[(int) offset][0], 32);

    // translate data: 128*32px block, as 4*32 px strips
    // layout is weird because... reasons?
    for (uint16_t s = 0; s < 32; s++) // 4px strips
    {
        // uint16_t clmn = ((s << 4) & 0xffe0) + (s & 1 ? 0x200 : 0);
        uint16_t clmn = ((s & 0xfe) << 4) + ((s & 1) << 9);
        for (uint16_t y = 0; y < 32; y++) {
            // 1 word contains 4 pixels
            ppmio.ramdp->scaling_buff[clmn + y] =
                    (((scaled_stamp[(s << 2) + 0][y ^ 1] & 0xf0) |
                    (scaled_stamp[(s << 2) + 1][y ^ 1] & 0x0f))
                    << 8) +
                    (((scaled_stamp[(s << 2) + 2][y ^ 1] & 0xf0) |
                    (scaled_stamp[(s << 2) + 3][y ^ 1] & 0x0f)));
        }
    }
}
#endif
