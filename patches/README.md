# Firmware patches against krikzz/mega-ppm

`mega-ppm-pocket.patch` applies to a clean clone of
[krikzz/mega-ppm](https://github.com/krikzz/mega-ppm) and produces the firmware
this core ships in `rtl/PAPRIUM/mcu.txt`.

```bash
git clone https://github.com/krikzz/mega-ppm.git repos/mega-ppm
cd repos/mega-ppm && git apply ../../paprium-pocket/patches/mega-ppm-pocket.patch
cd ../../paprium-pocket && ./scripts/build_mcu.sh
cp build_output/mcu/mcu.txt rtl/PAPRIUM/mcu.txt
```

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
ramp climbing 0x00 → 0xC0 with nothing playing. **Fixes both punk TVs.**

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

## Not yet re-applied

- **`cmd_8C` one-shot music cues** — MisterPezz82's V.04 change routing bit-7-clear
  cues (Stage Clear, Continue, Game Over, High Score, Ending) through
  `mdp_play_once` instead of stopping them. Its absence shows as no end-of-stage
  music.
- **Field-wise sprite attribute composition** — their V.04/V.05 change, explicitly
  recorded as harmless but *not* an elevator fix.

## Build notes

- `-march=rv32im_zicsr_zifencei`: GCC 15 split CSR and FENCE.I out of the base ISA.
  krikzz's Makefile says plain `rv32im` because his compiler folded them in.
- Built at `-O2`. MisterPezz82 used `-Os` to fit 16 KB; this core grew its IMEM to
  32 KB instead, because the MCU services the 68000 in real time and upstream
  attributes the elevator corruption to MCU starvation — trading its speed for
  space aims at the part already suspected of missing deadlines.
