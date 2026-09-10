# Firmware patches against krikzz/mega-ppm

`mega-ppm-pocket.patch` applies to a clean clone of
[krikzz/mega-ppm](https://github.com/krikzz/mega-ppm) and produces the firmware
this core ships in `rtl/PAPRIUM/mcu.txt`.

```bash
git clone https://github.com/krikzz/mega-ppm.git repos/mega-ppm
cd repos/mega-ppm && git apply ../../paprium-pocket/patches/mega-ppm-pocket.patch
cd ../../paprium-pocket && ./scripts/build_mcu.sh
```

`build_mcu.sh` installs into `rtl/PAPRIUM/mcu.txt` itself and reports whether the
firmware actually changed. It used to only print that path as a "reference build
for comparison", which cost a full Quartus fit built against stale firmware - see
docs/BUILD_REFERENCE.md.

The patch is kept here rather than the built binary alone because GPLv3 asks that
a distributed binary come with its corresponding source, and `mcu.txt` is a
compiled work. This is the source of our changes to it.

## What it contains

**`sfx.c` — re-arm a channel that has already finished (ours).**
`sfx_player_update()` skips any channel with `size == 0`, so the loop restart at
the bottom of its own loop is unreachable once a sample has ended. `sfx_play()`
clears `looped`, and the game enables looping *later* — the punk-TV cue starts at
volume 0 and is only looped and ramped up as the player approaches, by which time
the 4.99 s sample has run out and the channel is dead. Measured on hardware:
29,920 PCM words pushed (exactly the sample length), FIFO empty, then the volume
ramp climbing 0x00 → 0xC0 with nothing playing.

**This is a general fix, not a punk-TV one.** It re-arms *any* channel that has
already ended when looping is enabled on it, so every cue the game starts quiet and
loops up by proximity benefits. Confirmed on hardware: **all** punk TVs now play,
not only the two used to find the bug — and the looping area ambience (`0x4B`, the
subway trains) was broken the same way and is fixed by the same change.

**`mame.c` — real LZO decoder for format `0x81` (ported from Genesis Plus GX).**
Stock mega-ppm carries MAME's reverse-engineered heuristic, whose loop terminates
on `!= 0x11 // unconfirmed end code`. It mis-decodes and corrupts the subway among
other areas. Ported from GPGX's `paprium_decoder_lzo`, adjusting the cursors:
GPGX's `size` is the absolute output position, which here is `dest_addr`, so its
`lz = size - lz` becomes `copy_addr = dest_addr - lz`. krikzz fixed this privately
for MisterPezz82; the public tree still ships the broken version.

**`mame.c` — first-level door fix (krikzz's, re-applied).**
Object 107's sprite 4 is the Block 888 door and composes with palette bit `0x2000`
set, rendering in the wrong colours. Reported by MisterPezz82 as
"object 107 sprite 4, `attr &= ~0x2000`" and shipped in their V.05.

**`paprium.c` / `mdp.c` / `mdp.h` — one-shot music cues.**
`cmd_8C_bgm_play` treats bit 7 of its argument as "loop", and stock mega-ppm calls
`mdp_stop()` when it is clear — so Stage Clear, Continue, Game Over, High Score
and Ending are silent. Captured on hardware: `cmd_8C` track `0x35` (53) with bit 7
clear at the end of a stage, and 53 is one of the tracks the cue sheet marks
`REM NOLOOP`. Adds `mdp_play_once()`, sending MD+ `$11xx` (`MDP_CMD_PLAY_S`),
which this core's `paprium_mdp_adapter` already decodes as `track_loop = 0`.

**`paprium.c` — implement `0x88 audio_setting` (ours).**
Stock mega-ppm maps it to `cmd_unknown_muted` with the comment "set audio config",
so the game writes its audio configuration and reads back stale memory. GPGX
implements it (`paprium_audio_setting`): the DAC selection — the in-game "VM DAC"
option, choosing the YM2612 DAC over the cartridge's own — and the NTSC bit are
stored at cart RAM `0x1800`/`0x1801` for the game to read back. Observed on
hardware firing five times during boot with arguments `0x02` and `0x0A`.

GPGX's byte indices transcribe verbatim, which is correct rather than lucky:
`ramdp_io.sv` places a 68000 byte at address A into MCU byte `A^1`, and GPGX's
`ram[]` carries the same relationship, so the two agree.

**`paprium.c` — Boom Box VU bars (ours).**
Cart RAM `0x1B98..0x1BFF` is a per-voice stereo level feed: 26 voices of
`{u16 L, u16 R}` = 104 bytes, ending exactly at `0x1C00`. On hardware the
cartridge's music engine rewrites it every row with "does this voice have a
pattern this row" — GPGX's interpreter does the same at `paprium.h:472-473`
(`index ? 0xE0 : 0`) — and the Boom Box draws its 26-bar graph straight from it,
one bar per voice. Confirmed against a hardware capture: the graph has 26 bars.

This core substitutes CDDA and never sequences the module, so **nothing wrote
that window at all** and the game drew its bars out of uninitialised cart RAM —
they sat permanently lit. The neighbouring `0x1802..0x19FF` fill in
`cmd_88_audio_cfg` stops at `0x1A00` and never reached it.

Rather than smear one playback level across 26 identical columns, the bars are
driven from the module `cmd_8C_bgm_play` **already unpacks and then discards**,
so they show the real per-voice arrangement at the module's own tempo, and cost
no RTL. MWMM header `0x07` is frames per row (1..6 across the 52 modules), so a
row lasts `0x07/60` s; verified on hardware — Stage Clear is 105 rows with
`0x07`=3, giving 5.25 s, matching a Boom Box capture exactly.

The row tick lives in `ppm_start()`'s loop, which runs far faster than 60 Hz, so
at most one row advances per call and a carried millisecond remainder keeps the
grid from drifting. `cmd_8D` parks the bars on stop.

**`mame.c` / `mame.h` — pickup items spin forever instead of settling (ours).**
`PPM_CHAIN_ONLY_AT_END` (0.2.1) refuses a queued follow-up whenever the CURRENT
animation loops. Right for characters, wrong for dropped pickups: on hardware the
electric stick, pipe and knife loop their fall and spin instead of taking their
ground pose. The animation data at ROM `0x0C0000` (241 objects, 17,401
animations, 2,846 of them ending on a non-zero loop target) separates the two
cases with no timing heuristic at all:

| | source anim | queued target |
|---|---|---|
| characters / enemies | loops | **loops** (a 37-frame idle) |
| pickups `0x33`-`0x3D`, `0x97`-`0x9B` | loops | **terminal, 1 frame** (ground pose) |

`0x33`-`0x3D` are eleven contiguous simple objects with exactly two animations
each, a 1-frame terminal pose and a 31..97-frame looping one — a dropped weapon.
So `PPM_CHAIN_TARGET_TERMINAL` takes a queued follow-up out of a looping
animation **only when the queued animation is itself terminal**. A character's
queued idle loops and is still refused, so 0.2.1 is untouched — including the
walk-in capture where the game leaves the record alone for 295 frames and the
retail cart keeps walking.

**A frame clock was tried first and is wrong.** Waiting N frames for the game to
set the animation itself fires on that same 295-frame walk-in and puts the
character back into its sliding standing pose — the exact bug 0.2.1 fixed. The
attempt is recorded here so it is not tried again.

**Blast radius, checked against both winlog captures:** every `nextAnim` observed
for every object present (`01`, `02`, `03`, `6B`, `DC`, `DE`, `E3`) points at a
LOOPING animation, so the new arm never fires on any of them — no behaviour
change on anything the captures exercise.

## Not yet re-applied

- **Field-wise sprite attribute composition** — MisterPezz82's V.04/V.05 change,
  explicitly recorded in their own notes as harmless but *not* an elevator fix.
  Low value, so not carried over.

## Build notes

- `-march=rv32im_zicsr_zifencei`: GCC 15 split CSR and FENCE.I out of the base ISA.
  krikzz's Makefile says plain `rv32im` because his compiler folded them in.
- Built at `-O2`. MisterPezz82 used `-Os` to fit 16 KB; this core grew its IMEM to
  32 KB instead, because the MCU services the 68000 in real time and upstream
  attributes the elevator corruption to MCU starvation — trading its speed for
  space aims at the part already suspected of missing deadlines.
