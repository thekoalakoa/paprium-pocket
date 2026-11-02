# legacy/026 - the final 0.2.6 firmware modules, as-is

Moved in UNCHANGED from the final 0.2.6 firmware that passed on hardware (from its source folder; the md5s are the ones
its `src_md5.txt` lists):

| file | md5 | role |
|---|---|---|
| `mame.c` | e264b0ca | sprite engine (with the chip's behaviour for differences D02-D04, D06-D09, D18, D20, D25, D40 and the float part of D42), unpackers, DA/DB/F2, float F5, debug aids |
| `mame.h` | bb680307 | its header and the PPM_* switches (PPM_RELEASE etc.) |
| `paprium.c` | 983f5e18 | main loop, reset, command dispatch, the interim music/VU commands, option bits |
| `paprium.h` | b4a1f632 | FPGAIO / ramdp structures |

The D numbers name the differences between the 0.2.6 firmware and the cart's chip that our own study of how the cart
behaves listed. FPGAIO is the core's register block for the MCU (docs/MCU_INTERFACE.md section 4; the MCU is the cart's
NEORV32 soft CPU in the core); ramdp is the cart RAM that both the 68000 and the cart chip see. 
These are mega-ppm-derived and use board addresses directly (FPGAIO, ADDR_*): they are the exception to core/'s rule
and go module by module as core/ gains code that does what the cart's chip does. The 0.3.0 work did that in stages:
stage 1 the main loop and dispatcher, stage 2 the sprite engine, stage 3 F5/F4 and the saves. Do not edit them for
0.3.0 work: a change here changes the milestone-1 images.

The s1 exception (2026-10-11; work items W5 / W6 of docs/STAGE1_PLAN.md): `mame.c` has two `#if FW_S1` guards,
compiled only into the s1 images (the new 0.3.0 firmware, `tools/fwbuild.py s1`): the AF frame end sets the window
pointer through the board (`brd_stream_ptr`) instead of `FPGAIO->sdram_ptr`, and the float F5 copy is left out (it
moved to `interim/s1/f5_s1.c` with a static buffer). Without `FW_S1` the file compiles to the same code: milestone 1
(legacy54k == final 0.2.6) and the replay slice still pass. The md5 above is the imported file's.

2026-10-17 (B Jam's decision of 2026-10-15/16): two more of the chip's behaviours, compiled only into the s1 images
(`mame.h`: `PPM_CHIP_CLIP` and `PPM_CHIP_AF_END` are 1 under `FW_S1` and forced to 0 without it): the chip's clip rule
D24 in `ppm_obj_render` (X only, `$61..$1BF` as one unsigned compare, Y never tested, X / Y stored unmasked) and the
chip's whole AF frame end D10 + the rest of D42 in `ppm_close_sprite_table` (modes 0-2, the second 14-entry DMA, the
`$1F20` stash, `$1F1C`; the mode and the parity come from the dispatcher through `ppm_chip_af_mode` /
`ppm_chip_af_parity`). For MCU time in AD's and AF's L1 (L1 = the mailbox interrupt level) the s1 compose writes each
SAT entry (SAT = the sprite attribute table) as two 32-bit stores (Y | link, attr | X) and reads the object record's
attribute word once, and the close stores its descriptors, the overflow move and the stash word-wide: the same bytes in
the same places. With the chip's cache lists (D02) nothing reads a VRAM slot's `usage` or `age` (only the 0.2.6 victim
search, built without them), so the s1 images also leave out AE's 64-slot usage clear and the per-hit / per-claim
marks, as an earlier change (with MCU interface v1.2) left out AF's age pass. The 0.2.6 source set still compiles the
0.2.6 clip, entry stores, close and slot marks: milestone 1 and the replay slice are unchanged.
`SPR_BUG` (planted bugs 2 and 4) exists only for the chip lockstep's negative controls.

2026-10-27: the s1 and s5 images link the new sprite engine (`core/sprite`, which does what the cart's chip does)
instead of this file's: nothing there calls `ppm_obj_add`, the frame start / end or the slot loader any more, so the
linker leaves them out (0 B of this file's sprite engine in those images, measured); `ppm_setup_data`, the unpackers
and TEST's snapshot stay (the snapshot reads the new engine's counters under `FW_S1`). The 0.2.6 source set is
unchanged. This file's `SPR_BUG` plants no longer reach a chip-lockstep build: the bug_spr1-7 variants plant theirs in
core/sprite (3 stays in core/dispatch).

2026-10-17 (AF's reply): the s1 close stores the same words in the same order for fewer MCU instructions: its
descriptors are built inline with the constant words held in registers, the end mark's Y and link clear are one read
and one word store of the entry's first word, the stash is 28 word copies fully unrolled in one tail-called helper
(`chip_af_stash`), and the 80+ tables run out of line, compiled for size (`chip_af_over80`: one move helper, the
relink four entries a pass); `ppm_obj_frame_end` does its WRAM bookkeeping before the close (a tail call) and drops a
`$1F18` read nothing used. Only under `FW_S1`: the 0.2.6 source set is unchanged.
