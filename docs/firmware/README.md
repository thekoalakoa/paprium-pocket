# MCU firmware

**Fafrium (0.3.0), released as Little-Man Firmware.** The firmware is not built into the bitstream any more. The
bitstream's MCU images are a boot stub and zeros: `rtl/PAPRIUM/mcu.txt` holds the stub
(`board/pocket/fafrium/fafrium_stub.S` of the firmware tree, at most 2 KB at 0x0, then zeros to 32 KB), `mcu_ext.txt`
and the four WRAM lanes are all zero. The firmware itself (the 88 KB IROM image, the initialised WRAM window and the
MegaWire SRAM code of one build) arrives as one file, `little_man_firmware.bin` in the core's Assets folder, data slot
30 in `data.json` (the slot "Little-Man Firmware": required, read-only, bridge 0x1100_0000, exactly 256 KB). Fafrium
is the name this tree and the firmware tree use; the file is released as Little-Man Firmware, and the firmware's own
version (1.0 for the first release) is written into the file's header as information. The ROM loader writes it to
SDRAM at byte 0x0100_0000 (`cartridge.sv`: loader address bit 24, a 256 KB window). The core keeps a length mark that
is set only when the slot's last load ended exactly at 256 KB: the slot's first word clears it, the window's last word
sets it, and any word at or past 256 KB clears it again. The stub reads it in XLINK, the core's register block for its
external memories (MCU 0x0A00_0000), as the read-only word FAFRIUM at 0x0A00_004C (`fw_len_bad`: 1 unless the length
was exact), so a shorter or a longer file is refused whatever the window held before. The mark covers files up to 32
MB: the loader's download address has 25 bits and repeats every 32 MB, so a longer file whose size is 256 KB plus a
multiple of 32 MB, from 32 MB + 256 KB up to 224 MB + 256 KB, ends with the mark set, and then only the stub's checks
of its last 256 KB stand in its way. From 256 MB + 256 KB on, the file's last 256 KB lie past the bridge addresses
that reach the ROM loader (0x1000_0000-0x1FFF_FFFF), so the mark stays clear and the stub refuses the file (worked out
from the address decode, not tried on a Pocket). This is known and accepted (B Jam's decision of 2026-10-31);
`data.json` asks the Pocket for exactly 256 KB. The stub reads the file through a boot view (MCU 0x0380_0000,
`paprium_mcu_mem.sv`, open until the firmware starts). It checks the file's length, its version words, its reserved
and zero-fill bytes and both CRC-32s. It copies every section into IROM, WRAM and the Pocket SRAM, and signals GO
(`mcu_core.sv`: the IROM takes word stores and the WRAM code window is open only before GO, both power-on flags);
`core_top.sv` then restarts the cart from a real reset and the firmware's own `crt0` runs exactly as when it was built
in. A file the stub refuses keeps the 68000 held and the screen plain red (`paprium_holdvid.sv`). The file format, the
checks and the tools (`tools/mkfafrium.py stub --install rtl/PAPRIUM` writes these six images; `mkfafrium.py make`
builds the file from a firmware build) are in the firmware tree's `docs/FAFRIUM.md`. The stub images of this tree:
`mcu.txt` `2bb694a1`, `mcu_ext.txt` `ad0cbda4`, `wram_b0` .. `wram_b3` `4ef4b102`. The rest of this page describes the
firmware builds themselves: the same images, which now travel in the file instead of the bitstream.

The cartridge's MCU runs our firmware on the core's NEORV32 (RISC-V) soft CPU. The 0.3.0 work was done in numbered
stages: 1 = the new firmware's own start-up, scheduler, dispatcher and board layer ("the stage-1 images"), 2 = the
sprite engine, 3 = the unpackers, saves, zoom and MegaWire, 4 = the sound bank cache, 5 = the music: our own song engine
and synth ("the stage-5 images"). The firmware builds B Jam tested on his own Pocket along the way are named test
builds (test build 4, 4a, 4b, 5 and S3c below). From 0.3.0's stage 1 the firmware comes
from its own tree, now the [`firmware/`](../../firmware/) folder of this repository: the cart chip's dispatcher, status layer and job queue, the board layer for the MCU
interface the RTL implements (v1.0, plus the VS counter in FPGAIO slot 16 since v1.1, plus the cart FPGA's sprite
decoder and load-list queue in slots 17-22 since v1.2, plus test build 4a's v1.3: the FEAT word in slot 23, STAMP_A in slot
14, and the nonvolatile sound-cache slot in CRAM with its XLINK CACHE / CACHE_LOADED / BAR words), and, until their own
stages replace them, the 0.2.6 command
bodies, the interim album and SFX feeder, and the CPU MATE glue. This repository carries the six block-RAM images the
RTL reads, built from that tree, and the tools that build them:

| image | what | read by |
|---|---|---|
| `rtl/PAPRIUM/mcu.txt` | IROM, first 32 KB (8,192 words) | `mcu_core.sv` (`$readmemh`) |
| `rtl/PAPRIUM/mcu_ext.txt` | IROM extension: 56 KB (14,336 words) from test build 5; 40 KB (10,240 words) on test builds 4-4b | `mcu_core.sv` (`EXT_KB = IROM_KB - 32`: 56 from test build 5, 40 before) |
| `rtl/PAPRIUM/wram_b0.txt` | cart WRAM, byte lane 0 = bytes 4k (12,288 lines) | `memory.sv` |
| `rtl/PAPRIUM/wram_b1.txt` .. `wram_b3.txt` | cart WRAM, byte lanes 1-3 = bytes 4k + 1 .. 4k + 3 | `memory.sv` |

Test build 4 (the MCU fast path, section 20 of the firmware tree's `docs/MCU_INTERFACE.md`) put the WRAM on the NEORV32's processor bus as four 8-bit lanes, so its
image is four files. Before it the same bytes were two files, `wram_hi.txt` (even bytes) and `wram_lo.txt` (odd); the
firmware build still writes both forms from one byte array, and `build_mcu.sh` installs the four lanes.

The IROM is 72 KB on test builds 4-4b: the first 32 KB plus one 40 KB extension. From test build 5 (stage 5; MCU
interface v1.3, section 3.1) it is 88 KB: the first 32 KB plus a 56 KB extension in seven 2048 x 32 slices, the size the bitstream's FEAT word
reports (core_top's `PAPRIUM_IROM_KB`, passed to `mcu_core` through `paprium_cart`), and the firmware links its
`pocket88k` layout for it. The CPU MATE brain (below) fills it from 0x5360 to
0xD2EB; the firmware's own code sits under it and after it. The WRAM is 48 KB; the CPU MATE glue runs from a 16 KB code
window in it (0x2C00-0x6BFF), which the RTL write-locks. The firmware tree's linker script (generated from its
`board/pocket/link/pocket72k.json`) places all of it. A build without the brain keeps the same layout with zeros in the
brain's place.

## Building it

Needs bash (Git Bash on Windows works), Python 3, git, the
[xPack riscv-none-elf GCC 15.2.0](https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases) toolchain and a
firmware tree, the [`firmware/`](../../firmware/) folder of this repository. No `make`.

```bash
./scripts/build_mcu.sh --s5 --wram-blob --no-install --fw firmware   # a firmware's images, checked both ways
```

**On this tree (from the firmware file on).** `rtl/PAPRIUM/` holds the boot stub, and the firmware goes in
`little_man_firmware.bin`, which the firmware tree's `tools/mkfafrium.py make` builds from a firmware build. So
`build_mcu.sh` is run with `--no-install`: it still builds the images and checks them both ways. It refuses to
install over the stub, because a bitstream built from installed images would run that firmware built in and never
load the file; `--replace-stub` allows it for a test bitstream (never commit such images). A firmware with the
MegaWire code links that code for the Pocket SRAM (0x08000000-0x0800FFFF at the `pocket88k` layout): both splits
leave it out of the block-RAM images, write it as `sram.bin` and must agree on it too (`mkimage.py --sram`, the
range read from the firmware tree's layout). `sram.bin` travels in the firmware file, never in the bitstream.
The four builds of Little-Man Firmware 1.0 (`ovl.img` `e4f2cb41` in all four; `sram.bin`
`d4ec8522` for RELEASE and `f7cce49f` for TEST, with or without the brain):

| build (Little-Man Firmware 1.0) | command | mcu.txt | mcu_ext.txt | wram_b0 | wram_b1 | wram_b2 | wram_b3 |
|---|---|---|---|---|---|---|---|
| RELEASE, no brain | `build_mcu.sh --s5 --wram-blob --no-install` | `78fe3580` | `b3c2df8e` | `6f075d7a` | `b8a2a015` | `d483a45c` | `5d2149aa` |
| RELEASE | `build_mcu.sh --s5 --brain DIR --wram-blob --no-install` | `a1c7d4a0` | `e136e791` | `f8594eff` | `04b9d15a` | `5e88be5b` | `74e0c0f1` |
| TEST | `build_mcu.sh --s5 --test --brain DIR --wram-blob --no-install` | `5afa74c3` | `79619438` | `50725b75` | `32bb5244` | `8dffbbd7` | `9a2ee8be` |
| TEST, no brain | `build_mcu.sh --s5 --test --wram-blob --no-install` | `e2a3f3b6` | `fdc8a3cb` | `2a14e6c6` | `a83a09be` | `37d3d711` | `66312044` |

`build_mcu.sh` builds one image set with the firmware tree's own build (`tools/fwbuild.py s1 --images-only`: the
stage-1 source set, the 72 KB / 48 KB layout, the tree's stack-bound and size checks), splits the same ELF again with
this repository's `scripts/firmware/mkimage.py` and refuses to go on unless both give the same files and the four WRAM
lanes hold exactly the bytes of the firmware build's even / odd pair, checks their shapes (8,192 / 10,240 words,
12,288 lines a lane), prints their md5s, says whether they are a known build, and installs them into `rtl/PAPRIUM/`. `--no-install` leaves `rtl/PAPRIUM/` alone; `--help` lists the rest. The firmware tree is
found through `--fw`, `$PAPRIUM_FW` or the `firmware/` folder of this repository; the toolchain through `--gcc-bin`, `$RISCV_GCC_BIN` or
`PATH`. Another GCC version builds working firmware with other md5s.

| build (test build 4a's firmware) | command | mcu.txt | mcu_ext.txt | wram_b0 | wram_b1 | wram_b2 | wram_b3 |
|---|---|---|---|---|---|---|---|
| RELEASE, no brain (committed until test build 5) | `build_mcu.sh` | `096fe23b` | `31444366` | `d0242d25` | `d93120ae` | `4b1d709a` | `d2a1706a` |
| RELEASE | `build_mcu.sh --brain DIR` | `f5c58628` | `250091e5` | `b9925ba1` | `5e289070` | `de53c0b3` | `01e4db7a` |
| TEST | `build_mcu.sh --test --brain DIR` | `7d302a06` | `5df79079` | `86deb30f` | `247d2f63` | `ddf41c30` | `023b8c6f` |
| TEST, no brain | `build_mcu.sh --test` | `4e5145a1` | `3b871768` | `22f9bd9f` | `4b95f57e` | `4e6074b9` | `83aa94ca` |

The even / odd pair of the same builds (what the RTL before test build 4 reads; `wram_hi.txt` / `wram_lo.txt`, written by
the firmware build too): `8b99de32` / `17ad00f4`, `c740c70c` / `fa23a102`, `6cde8da8` / `cba48b72`, `ed5de4fd` /
`599414a5`. `build_mcu.sh` makes the lanes again with this repository's `mkimage.py` and checks both forms against the
firmware build's. The RELEASE images are test build 4's byte for byte: test build 4a changes only the
TEST firmware.

**Test build 5 (the committed images).** From test build 5 on, the stage-5 images (the cart's own music player on the
synth, the first-boot unpack, the synth's output curve written by the boot overlay) are the fwbuild variants
`s5release` / `s5test` at the `pocket88k` layout: `build_mcu.sh --s5` builds those and splits them for the 88 KB
IROM (`mcu_ext.txt` 14,336 words). Installing refuses an image whose IROM size is not the RTL's (core_top
`PAPRIUM_IROM_KB`), so a 72 KB image cannot reach an 88 KB bitstream by mistake. Test build 5's four builds (`ovl.img`
`e4f2cb41`, 15,840 of 16,384 B, in all four):

| build (test build 5's firmware) | command | mcu.txt | mcu_ext.txt | wram_b0 | wram_b1 | wram_b2 | wram_b3 |
|---|---|---|---|---|---|---|---|
| RELEASE, no brain (committed until test build S3c) | `build_mcu.sh --s5 --wram-blob` | `ae8babb8` | `4c4de530` | `6f075d7a` | `0f4e1970` | `58ee8b1c` | `aeff1416` |
| RELEASE | `build_mcu.sh --s5 --brain DIR --wram-blob` | `ac270ab1` | `bbb86136` | `f8594eff` | `f9ce8473` | `73dad06d` | `7e1abee6` |
| TEST | `build_mcu.sh --s5 --test --brain DIR --wram-blob` | `e9e0c5cb` | `3014345a` | `38a418d2` | `d05b7f2f` | `c056905c` | `ffa9a6f9` |
| TEST, no brain | `build_mcu.sh --s5 --test --wram-blob` | `13ab4752` | `a1861acf` | `e41464c0` | `57f4b8cf` | `4a25e9d3` | `cc6ccbba` |

The even / odd pair of the RELEASE no-brain build (written by the firmware build too): `6a49213b` / `ebbe858b`.

**Test build S3c (the images committed until the firmware file; the refit with the Console Reset).** Its firmware is
the first step of stage 2 (command F5's stamp rescale stepped in integers) + the Console Reset's warm vector page on
CAUSE.V; the same commands and layout as test build 5:

| build (test build S3c's firmware) | command | mcu.txt | mcu_ext.txt | wram_b0 | wram_b1 | wram_b2 | wram_b3 |
|---|---|---|---|---|---|---|---|
| RELEASE, no brain (committed until the firmware file) | `build_mcu.sh --s5 --wram-blob` | `fea7467c` | `936aef3b` | `6f075d7a` | `fab4302e` | `ec44ab25` | `50221f93` |
| RELEASE | `build_mcu.sh --s5 --brain DIR --wram-blob` | `2d7b3dbf` | `6e23bacb` | `f8594eff` | `7217e52b` | `cf3ce6f2` | `2f913f19` |
| TEST | `build_mcu.sh --s5 --test --brain DIR --wram-blob` | `1989bd5d` | `181df599` | `38a418d2` | `279701b5` | `2474df73` | `feef6ca2` |
| TEST, no brain | `build_mcu.sh --s5 --test --wram-blob` | `6270931d` | `ece789cc` | `e41464c0` | `c7a9d95b` | `9ba5709d` | `86ac7a76` |

Test build
4a's table above and test build 4b's below are the builds of those earlier test builds (not committed any more; `build_mcu.sh` still
names them when it makes them, without `--s5` and with `--no-install`, since this RTL is 88 KB).

**The WRAM boot overlay (test build 4b on).** From test build 4b on every image also carries the first-boot unpack of
the cart's sound bank (the firmware tree's `core/wavpack`; we reverse engineered the STM32F4's commands as close as
possible, with hardware verification) as a WRAM boot overlay:
`ovl.img`, linked on its own by the firmware tree, a 16-byte header (`POV1`, length, CRC-32, entry) and its code, at
0x80006C00 in a 16 KB room the bitstream initialises. `build_mcu.sh --wram-blob` places it where the firmware build
placed it (`mkimage.py --wram-blob`), checks that both builds list the same blob (image.json `wram_blobs`), reads it
back from the lanes the way the firmware's IROM stub checks it before entering it (`scripts/firmware/ovlcheck.py`:
magic, length, entry, CRC-32, the bytes = `ovl.img`, the rest of the room zero), and again from `rtl/PAPRIUM/` after
the install. It refuses a build that made an overlay without `--wram-blob` (lanes without it boot with no unpack and
no sound bank), and `--wram-blob` on a build that made none. Test build 4b's images, not committed here (`ovl.img` md5
`e09e3062`, 15,124 of 16,384 B, in all four):

| build (test build 4b's firmware) | command | mcu.txt | mcu_ext.txt | wram_b0 | wram_b1 | wram_b2 | wram_b3 |
|---|---|---|---|---|---|---|---|
| RELEASE, no brain | `build_mcu.sh --wram-blob` | `5b9e1089` | `3d5beae1` | `75fe689d` | `f1806226` | `bb68b047` | `36061f9d` |
| RELEASE | `build_mcu.sh --brain DIR --wram-blob` | `77199389` | `81110d61` | `059f517f` | `883cad55` | `192d87d3` | `36510358` |
| TEST | `build_mcu.sh --test --brain DIR --wram-blob` | `4bf961e3` | `a60b18e4` | `04a27acb` | `aadfc363` | `99c4f57e` | `b45d62d5` |
| TEST, no brain | `build_mcu.sh --test --wram-blob` | `00a68ec9` | `4aa6b5ea` | `a51ab309` | `fe4e9527` | `906ab0d5` | `b5bc8c39` |

RELEASE is `-DPPM_RELEASE=1`: the debug aids are compiled out. TEST keeps them: the per-level counters, the boot
milestones, the freeze telemetry and the debug save (the upper half of the 8 KB `.sav`, decoded by the firmware tree's
`tools/dbgsave.py`), and 0.2.6's snapshots. The images have CRLF line ends on every platform (`.gitattributes` stores
them byte for byte), so the md5s are the same on Windows, Linux and macOS.

The images need the stage-1 RTL (MCU interface v1.x, same major, a minor at least their own): their start-up code checks
the interface version and the clock the bitstream reports and stops, with the 68000 held, on anything else (a 0.2.x
bitstream reads 0 there). The RTL is v1.3 since test build 4a (v1.2 since the sprite decoder, in stage 1; v1.1 since the
VS counter). The RELEASE images are built for v1.2 and refuse a v1.1 or v1.0 bitstream: their firmware no longer decodes
the sprite blocks itself (the flush, F2 and DA06 / DA07 with a 0x80 source push their blocks into the RTL decoder's
queue as the cart's chip does, and AF, B1, F2, DA06 and DA07 reply at once), so on a v1.1 bitstream no sprite block
would ever be decoded. A v1.3 bitstream takes them as they are.

The TEST images are built for v1.3 and also refuse a v1.2 bitstream (stop code 0xC2), or a v1.3 one whose FEAT word
(FPGAIO slot 23) lacks CACHE, BAR, SFXFIFO or MDP or reports less than 72 KB of IROM (stop code 0xC3). Before they
release the 68000 they run test build 4a's sound-cache probe on the nonvolatile cache slot (1,384,704 B in CRAM at the MCU's
0x09000000):
- On a cold start whose slot file the Pocket loaded whole (CACHE_LOADED = the size, LOST = 0) and whose every word is
  right, they keep it.
- Otherwise they write the probe pattern, with the header last.
- Then they set XLINK CACHE to VALID | size, so the Pocket writes the slot back at the Quit.
- After a reset inside the session (CACHE.VALID already set), they touch nothing.
The bar falls during the check and rises during the fill. Each boot's result is in the debug save (version 7), and the
firmware tree's `tools/dbgsave.py` prints it.

Test build 5's images (both variants) are v1.3 images for the stage-5 bitstream: they stop (0xC3) unless
FEAT carries CACHE, BAR and SYNTH and reports at least 88 KB of IROM, which this RTL's FEAT (0x0058_0047: CACHE, BAR,
SYNTH, GS3, IROM 88) does; test build 4a's TEST image and test build 4b's images would refuse it (they want SFXFIFO and MDP).

## The CPU MATE brain is not in the repository

The CPU MATE partner (0.2.6 on) is driven by a "brain" that runs on the MCU, a reverse-engineered emulation of the
game's CPU partner. It holds game-derived bytes, so it does not belong in git: it ships as a separate download next to each release, three files with these md5s (0.3.0,
stage 1 on):

| file | md5 | where it goes |
|---|---|---|
| `brain.bin` | `b9a7659287d70709e44639255e2eaccf` | IROM 0x5360-0xD2EB |
| `cf.bin` | `a5fa37b435f26f9fc2c8fd62d218d7ef` | start of the WRAM code window, 0x80002C00 |
| `rodata.bin` | `5b1d74f454b578196ed1e82548f01b99` | 0x80004110 (after `cf.bin` and 64 zero bytes) |

The stage-1 brain is 0.2.6's (`brain.bin` `1b64e14d`, the `cpu-mate-brain_0.2.6` download) with a fix to its cycle
counter: nine immediates of the brain's own cycle counter move to their structural twins, so its not-before release times
equal the original's with three player slots and in the Arena (measured on 45,474 calls; before, +116 sub cycles on
Arcade Multiplayer census calls and +2 in the Arena, released late). Same size and place; `cf.bin` and `rodata.bin`
are unchanged. The firmware tree pins it as `fwbuild.json` `s1.brain` and refuses the 0.2.6 file.

`build_mcu.sh --brain DIR` passes the folder to the firmware build, which checks those md5s and links the three files
in. `cpu-mate-brain/` at the top of the repository is git-ignored for this, but any folder works.

**Without `--brain`** the firmware tree links zero files of the same sizes in the brain's place, so the layout and
every other byte are the brain build's (measured: the RELEASE and TEST images with and without the brain differ only
inside 0x5360-0xD2EB and the cf.bin / rodata.bin ranges of the code window). The CPU MATE glue finds no brain (its two
entry words are zero, which is no RISC-V instruction) and switches itself off at its first event, as 0.2.6's no-brain
build did: with a Mega CD unit selected, the game still finds the Mega CD and offers its CPU MATE mode, but the link
keeps the plain stub answers (sub CPU never busy, pad word 0), so the partner does not move on its own. Everything
else runs as in the release.

### Why the committed images have no brain

- The brain-bearing images contain the brain whole, byte for byte, so committing them would put game-derived bytes in
  git.
- The no-brain images contain none of it. Every 16-byte window of the three files (every 64 bytes; raw, as hex
  text, and as the even / odd byte lanes the WRAM files split) was searched for in them: in test build 4's
  RELEASE and TEST no-brain images 6 windows match, all generic RV32 compiler code that the firmware's own functions
  also contain: a register-restore epilogue (`lw s0..s3`) that several of them end with in the IROM
  (`chip_af_over80`, `job_unpack`, and in TEST `prev_take` and `wh_feed`; two `cf.bin` windows with the same 16
  bytes); register restores in the code window, where the firmware's SFX code sits, as even WRAM byte lanes
  (`sfx_play`'s `lw s0..s11` and return: those two `cf.bin` windows, one more `cf.bin` window and one `brain.bin`
  window; and a reload of temporaries in `sfx_fade_tick`); and the register saves (`sw s1..s9`) of the CPU MATE call
  wrapper `buddy_call_brain` (one `brain.bin` lane and one `cf.bin` lane). The same images searched with 32-byte
  windows (raw, hex text, the even / odd pair and the four lanes joined): none in RELEASE; in TEST one, the generic
  `lw s0..s7` epilogue (`cf.bin` + 0x1080) in `mcu_ext.txt`. Test build 4a's RELEASE no-brain images are these bytes. Its
  TEST no-brain images give the same result with 32-byte windows: only that `cf.bin` + 0x1080
  epilogue, in `mcu_ext.txt`. The longest run of consecutive brain bytes in them is 35 B. Test build 4b's no-brain images
  (with the WRAM boot overlay; not committed here) add one pair, in the WRAM lanes and in
  `ovl.img`: two more generic register-restore epilogues, both inside the overlay's sound-bank decoder, `cf.bin` + 0x5C0
  (`lw s0..s5`, `addi sp`, `ret`: `read_metadata_buff`, WRAM 0x80008050) and `cf.bin` + 0x1080 (`lw s0..s7`:
  `read_decorr_samples`, 0x80008580), the same bytes at the same places in a no-brain build made from source; RELEASE
  shows no other window, TEST the same `mcu_ext.txt` epilogue as before; the longest run of brain bytes is 36 B.
- They have the shapes of the brain-bearing ones, and the plain Quartus build works from a clean clone with nothing to
  download.

## Building the bitstream with the brain

```bash
./scripts/build_mcu.sh --fw firmware --brain cpu-mate-brain    # installs the brain-bearing RELEASE images
quartus_sh -t generate.tcl paprium <seed>
git checkout -- rtl/PAPRIUM/mcu.txt rtl/PAPRIUM/mcu_ext.txt rtl/PAPRIUM/wram_b0.txt rtl/PAPRIUM/wram_b1.txt \
    rtl/PAPRIUM/wram_b2.txt rtl/PAPRIUM/wram_b3.txt
```

Never commit the images `--brain` installs. The last line puts the committed ones back; running `build_mcu.sh` without
`--brain` does the same.

A firmware-only change reaches a fitted bitstream without a refit: `scripts/mkmif.py` writes the memories' init files
into the fit's `db/` folder from these four images (matched to the RAMs by module, width and depth), then
`quartus_cdb --update_mif` and `quartus_asm` rebuild the bitstream around the same placement. Run `mkmif.py --check` on
the images a fit was built from once per new fit (every file must be IDENTICAL) before trusting the route. Check that
the bitstream's md5 changed, not just the fit (docs/BUILD_REFERENCE.md).

## Before 0.3.0

0.2.x built krikzz's [mega-ppm](https://github.com/krikzz/mega-ppm) at its pinned commit `84be6bd` with
`patches/mega-ppm-pocket.patch` and `scripts/firmware/paprium_mcu.ld` (IROM 54 KB = 32 KB + a 22 KB extension, WRAM
32 KB: `mkimage.py --ext-kb 22 --wram-kb 32`); `patches/README.md` describes that patch. The firmware tree keeps those
0.2.6 sources and rebuilds the shipped 0.2.6 images byte for byte from them (the check of its first milestone); the stage-1 images
above are the next step. mega-ppm is BSD-3-Clause, Copyright (c) 2025 krikzz; NEORV32's runtime is BSD-3-Clause,
Copyright (c) 2020 Stephan Nolting.

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
