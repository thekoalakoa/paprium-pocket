# MCU firmware

The cartridge's MCU runs krikzz's [mega-ppm](https://github.com/krikzz/mega-ppm) firmware on the core's NEORV32
(RISC-V) soft CPU. This repository carries our changes as one patch against mega-ppm's pinned commit `84be6bd`,
plus the tools that build it into the four block-RAM images the RTL reads:

| image | what | read by |
|---|---|---|
| `rtl/PAPRIUM/mcu.txt` | IROM, first 32 KB | `mcu_core.sv` (`$readmemh`) |
| `rtl/PAPRIUM/mcu_ext.txt` | IROM extension, 22 KB | `mcu_core.sv` |
| `rtl/PAPRIUM/wram_hi.txt` | cart WRAM, even bytes (16,384 lines) | `memory.sv` |
| `rtl/PAPRIUM/wram_lo.txt` | cart WRAM, odd bytes | `memory.sv` |

Since 0.2.6 the IROM is 54 KB: the first 32 KB plus a 22 KB extension. The CPU MATE brain (below) fills it from
0x5360; the firmware's own code sits under it, and a few boot-only functions after it. The CPU MATE glue runs from a
16 KB code window in the cart WRAM (0x2C00-0x6BFF), which the RTL write-locks. `scripts/firmware/paprium_mcu.ld`
places all of it. A build without the brain keeps the same layout and leaves the brain's range zero.

## Building it

Needs bash (Git Bash on Windows works), git, tar, Python 3, the
[xPack riscv-none-elf GCC 15.2.0](https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases) toolchain and
a clone of mega-ppm. No `make`.

```bash
git clone https://github.com/krikzz/mega-ppm.git ../repos/mega-ppm     # or pass --mega-ppm DIR
./scripts/build_mcu.sh                                                 # = the committed images
```

`build_mcu.sh` reads the pinned commit with `git archive` (your clone's checkout and branch do not matter and are never
touched), applies `patches/mega-ppm-pocket.patch`, compiles, links, splits the result into the four images, prints
their md5s, says whether they are a known build, and installs them into `rtl/PAPRIUM/`. `--no-install` leaves
`rtl/PAPRIUM/` alone; `--help` lists the rest. The toolchain is found through `--gcc-bin`, `$RISCV_GCC_BIN`, `PATH`,
or `../tools/xpack-riscv-none-elf-gcc-15.2.0-1/bin`. Another GCC version builds working firmware with other md5s.

| build | command | mcu.txt | mcu_ext.txt | wram_hi.txt | wram_lo.txt |
|---|---|---|---|---|---|
| RELEASE, no brain (committed) | `build_mcu.sh` | `23e5d47a` | `e2883aca` | `fc470b86` | `36b0468a` |
| RELEASE, the shipped 0.2.6 | `build_mcu.sh --brain DIR` | `1570f367` | `d7da4574` | `1dfe3f40` | `502a6b1b` |
| TEST | `build_mcu.sh --test --brain DIR` | `52801d28` | `2c297175` | `fb00f0ca` | `d0fd1a9b` |
| TEST, no brain | `build_mcu.sh --test` | `8836a7e5` | `45974a8d` | `d29ca4eb` | `2ec453fe` |

RELEASE is `-DPPM_RELEASE=1`: the debug aids (UART printf, SAT snapshot, object dump) are compiled out. TEST keeps
them. The images have CRLF line ends on every platform (`.gitattributes` stores them byte for byte), so the md5s are
the same on Windows, Linux and macOS.

## The CPU MATE brain is not in the repository

The CPU MATE partner (0.2.6) is driven by a "brain" that runs on the MCU. It is made from the game's own code, so it
does not belong in git: it ships as a separate download next to each release, three files with these md5s:

| file | md5 | where it goes |
|---|---|---|
| `brain.bin` | `1b64e14d710e8768d3385d1421162bc7` | IROM 0x5360-0xD2EB |
| `cf.bin` | `a5fa37b435f26f9fc2c8fd62d218d7ef` | start of the WRAM code window, 0x80002C00 |
| `rodata.bin` | `5b1d74f454b578196ed1e82548f01b99` | 0x80004110 (after `cf.bin` and 64 zero bytes) |

`build_mcu.sh --brain DIR` checks those md5s and links the three files in (`zz_buddy_brain.c` `.incbin`s them).
`cpu-mate-brain/` at the top of the repository is git-ignored for this, but any folder works.

**Without `--brain`** the same source is built with `BUDDY_NO_BRAIN=1`: no brain code, and the CPU MATE glue
switches itself off at its first event. The firmware boots and runs as in the release. The Pocket menu works as in
the release too (Little-Man, Arcade Stage Select, 6-Button, 32X Mode, Console, Mega CD, MegaWire). The only change
is the CPU MATE: with a Mega CD unit selected, the game still finds the Mega CD and still offers its CPU MATE mode,
but the link keeps the plain stub answers (sub CPU never busy, pad word 0). The partner gets no input from the
cartridge, so it does not move on its own. (This comes from the RTL, the firmware and a simulation of the core
running this firmware; it was not tried on hardware.)

### Why the committed images have no brain

- The shipped RELEASE images contain the brain whole: all three files sit at the addresses above, byte for byte, so
  committing them would put game-derived bytes in git.
- The no-brain RELEASE images contain none of it. Every 16-byte run of the three files was searched for in them:
  8 short runs of 16-40 bytes match, and all 8 are generic RV32 compiler code (register save/restore epilogues and
  `li` zeroing sequences) that the firmware's own functions also contain.
- The no-brain images have the same shapes and sizes as the release ones (512 / 352 / 16,384 / 16,384 lines). The
  plain Quartus build works from a clean clone, with nothing to download.
- They are built from the same source as the release: the brain's three `.incbin`s and the glue's
  `BUDDY_NO_BRAIN` branch are the only differences, and both are in `patches/mega-ppm-pocket.patch`.

So the repository builds a complete core minus the partner's brain, and anyone with the release download rebuilds
the exact shipped firmware.

## Building the release bitstream

```bash
./scripts/build_mcu.sh --brain cpu-mate-brain      # installs the brain-bearing RELEASE images, md5s as above
quartus_sh -t generate.tcl paprium 3               # the 0.2.6 fit used seed 3
git checkout -- rtl/PAPRIUM/mcu.txt rtl/PAPRIUM/mcu_ext.txt rtl/PAPRIUM/wram_hi.txt rtl/PAPRIUM/wram_lo.txt
```

Never commit the images `--brain` installs. The last line puts the committed ones back. Running `build_mcu.sh` with
no arguments does the same.

A firmware-only change only reaches the bitstream through these files: check the bitstream's md5 changed, not just
the fit (docs/BUILD_REFERENCE.md). Quartus synthesis ignores comments, but a fresh fit is not guaranteed to reproduce
the released `.rbf_r` bit for bit. The released one was fitted with the TEST images, and the RELEASE images were then
put in with a memory-init update. The release download stays the reference bitstream.

## The patch

`patches/mega-ppm-pocket.patch` is a plain `git diff` against mega-ppm `84be6bd` (8 files changed, 4 added:
`buddy.h`, `zz_buddy.c`, `zz_buddy_brain.c`, `zz_buddy_trap.c`). mega-ppm is BSD-3-Clause, Copyright (c) 2025
krikzz; NEORV32's runtime and linker script are BSD-3-Clause, Copyright (c) 2020 Stephan Nolting. What each change
does and why: `patches/README.md`.

To work on the firmware, extract and patch a tree the same way the script does, edit it, and regenerate the patch
from that tree:

```bash
mkdir fw && git -C ../repos/mega-ppm archive 84be6bd mcu | tar -x -C fw
cd fw && git init -q && git add -A && git -c user.name=fw -c user.email=fw commit -qm base
tr -d '\r' < ../patches/mega-ppm-pocket.patch | git apply
# ... edit mcu/*.c ...
git add -A && git diff --cached > ../new.patch      # then put the old patch's header lines back on top
```

## History

Before 0.2.6, `mcu.txt` alone was the firmware (32 KB IROM, no WRAM code). Diagnostic firmware states from the 0.1.x
investigation, by `mcu.txt` md5:

| mcu.txt | switches | bitstreams |
|---|---|---|
| `357663aa` | onset ring 1, epoch 0, pad 0 | `dec2f09f` (ring) |
| `14844a95` | onset ring 1, epoch 0, pad 0, stub staged | control `80e68bc9`, cut-2 sweep, epoch sweep, fcut |
| `5235f357` | onset ring 0, epoch 1 | `53076197` (hangs) |
| `8111bd8a` | onset ring 1, epoch 0, **PPM_DA_PAD 1** | not fitted |

A firmware-only change is a ROM-only change to the bitstream: fitted on the same RTL at the same seed, it lands on
the same placement (the control proved this against the epoch build).
