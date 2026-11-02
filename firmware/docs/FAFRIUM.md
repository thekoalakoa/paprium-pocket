<!-- Copyright (C) 2026 Marsupial Solutions LLC -->
<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Fafrium: the cart firmware file

From 0.3.0 the firmware of the cart's MCU (the NEORV32 soft CPU in the core) is not compiled into the bitstream any
more. It is one file, **Fafrium**, built from this tree and shipped in the core package next to the bitstream. The
core loads it at power-on, checks it, and only then starts the firmware. The file is not signed and not encrypted.
The core checks its length, its version words, its fixed layout and two CRC-32s, and nothing else. The fixed layout
means that the reserved header words and the zero fill must be zero. The kind and build words are information only.
Like the rest of this tree the file is GPL-3.0-or-later.

Fafrium is the name we use in this tree. The file is released as **Little-Man Firmware**: on the SD card it is
`little_man_firmware.bin` in the core's Assets folder, `Assets/paprium/Koala_Koa.Paprium/`, and the Pocket names its
slot "Little-Man Firmware". The file name carries no version, so a firmware-only update is a plain swap of that one
file. The firmware's own version, 1.0 to start with, is written into the file's header as information (the kind word,
below; `mkfafrium.py show` prints it); the Pocket port itself is version 0.3.0.

One file carries everything the cart MCU runs:

| section | what | where it goes |
|---|---|---|
| IROM | the firmware's code and read-only data, 88 KB (`mcu.txt` + `mcu_ext.txt` of a build) | the MCU's IROM, 0x0000_0000 |
| WRAM | the initialised WRAM window 0x2C00-0xABFF, 32 KB (the code window and the boot overlay room) | the MCU's WRAM, 0x8000_2C00 |
| SRAM | the MegaWire code (`sram.bin` of the same build), at most 64 KB | the Pocket SRAM, 0x0800_0000 |

A build that links the CPU MATE brain (the RELEASE and TEST images) carries it in the IROM and WRAM sections, exactly
where those images have it.

## How the core loads it (Analogue Pocket)

1. The Pocket loads `little_man_firmware.bin` from the core's Assets folder as data slot 30 (`data.json`: the slot
   "Little-Man Firmware", required, read-only, bridge address 0x1100_0000, exactly 256 KB) after the ROM, the save
   and the sound cache. The ROM loader writes it
   to SDRAM at byte 0x0100_0000, away from the game ROM (the ROM size, mask and header reads see none of the file's
   first 16 MB; longer files below). The window is 256 KB, the size of the file. The bytes of a longer file wrap onto
   the start of the window, and a shorter file leaves the window's older bytes after its own, so the window alone
   cannot show the file's length. The core therefore keeps a length mark (`cartridge.sv`). The loader writes the slot
   in 16-bit words, in order: the slot's first word clears the mark, the window's last word (offset 256 KB - 2) sets
   it, and any word at or past 256 KB clears it again. So, for a file up to 32 MB, the mark is set only when the
   slot's last load ended exactly at 256 KB. The core reads each word's offset from the loader's download address,
   which has 25 bits and repeats every 32 MB: the words at offsets 16 MB to 32 MB are taken as ROM words, and from
   32 MB on the offsets start again. So the length check covers files up to 32 MB. A file whose size is a 32 MB step
   plus 256 KB (32 MB + 256 KB, 64 MB + 256 KB, and so on up to 224 MB + 256 KB) is not checked beyond that: it ends
   with the mark set, and then only the stub's checks of its last 256 KB stand between it and the firmware. This is
   known and accepted (B Jam's decision of 2026-10-31); `data.json` asks the Pocket for exactly 256 KB. From
   256 MB + 256 KB on, the file's last 256 KB would lie past the end of the bridge addresses this slot uses
   (0x1100_0000 + 256 MB is past 0x1FFF_FFFF), so they never reach the cartridge, the mark stays clear and the stub
   refuses the file (worked out from the core's address decode, not tried on a Pocket). The stub reads the mark in
   XLINK, the core's register block for its external memories (MCU 0x0A00_0000): bit 0 of the read-only word XLINK
   FAFRIUM at 0x0A00_004C is 1 unless the mark is set, and the stub refuses the file when it is 1, whatever the
   window holds. The mark is clear at power-on and no reset changes it, so with no load of the slot the stub refuses,
   and the mark keeps its verdict until the slot is loaded again; the next load of the right file is taken. The bit
   reads 0 once the firmware has started, so the firmware never sees it.
2. The bitstream's IROM holds only a boot stub (`board/pocket/fafrium/fafrium_stub.S`, at most 2 KB at 0x0); its WRAM
   is all zero. When the load is complete the MCU leaves reset into the stub, with the 68000 held. The stub reads the
   file through a boot view (MCU 0x0380_0000-0x0387_FFFF = SDRAM 0x0100_0000 + offset, open until the firmware
   starts). It checks the header and the length mark. Then, in one pass over the rest of the file, it computes the
   CRC-32 and stores every section word where it belongs. The first 2 KB of IROM, the stub's own place, waits in a
   WRAM stash. The zero fill and the end word only go into the CRC, and every fill byte must be zero.
3. With the CRC right, a short finisher run from SDRAM moves the stash into IROM [0, 2 KB), zeroes the stash, zeroes
   the file's magic and end word in SDRAM (so the window no longer holds a whole file), clears the registers and
   signals GO. The core then restarts the cart from a real reset, and the firmware's own `crt0` runs with IROM, WRAM
   and the bus map exactly as when the firmware was built into the bitstream: IROM read-only, the code window
   locked, the boot view closed. These are power-on flags, so no reset undoes them: a Soft Reset reboots the
   firmware directly and costs nothing extra.
4. If the finisher is cut by a new load after its first IROM store, the MCU is held in reset until the bitstream is
   loaded again, so a half-written IROM never runs. A cut before that store finds the stub and the file intact and
   the stub runs again.

### When the file is refused

A missing, short, long, damaged or wrong-version file never starts the firmware, with the one exception above: a
file whose size is 256 KB plus a multiple of 32 MB and whose last 256 KB are a right file. The core's length mark
refuses every other load that did not end exactly at 256 KB, whatever the window held before, except a load of
256 KB plus a multiple of 32 MB: that one ends with the mark set, so the mark does not refuse it, and only the stub's
own checks of its last 256 KB judge it (each with its own code below). The stub checks every byte of the window.
The header words must match this core's values, and the SRAM section's length must be 4-aligned and at most 64 KB.
The reserved words and the zero fill must be zero. Two CRC-32s cover the rest: the header CRC bytes
0x00-0x7B, the payload CRC bytes 0x80 to the end. The kind and build words are information, and only the header CRC
covers them. The mark sees the length to the loader's 32-bit word: a file one to three bytes short still reaches
the window's last word, because the loader pads its last 32-bit word, and then the end word refuses it, unless the
padding happens to repeat the missing bytes (our benches pad with zero bytes; the end word's last byte is not zero).
When a file is refused, the 68000 stays held, there is no sound, and the screen goes **plain red** (255, 0, 0) and
stays so, with no text. The fix is always the same: copy the `little_man_firmware.bin` from the same release as the
core, then Quit and Run.

The stub refuses for one of these reasons (kept in its register a0, for the RTL benches):

| a0 | why |
|---|---|
| 1 | no file: the magic is missing (also a stale copy whose magic the stub zeroed, an all-zero file, or a longer file whose extra bytes wrapped onto the magic) |
| 2 | the header is damaged: its CRC-32 is wrong |
| 3 | another format version or header length |
| 4 | not this file's layout: a load that did not end exactly at 256 KB, shorter or longer (the core's length mark, checked right after the magic), a reserved header word or a zero-fill byte that is not zero, another file length, layout or section table, an SRAM section longer than 64 KB, or no end word |
| 5 | another version: firmware epoch, MCU interface, FEAT word or MCU clock of this bitstream |
| 6 | the payload is damaged: its CRC-32 is wrong. The CRC is checked before the zero fill, so a damaged fill byte gives 6, while a fill byte that is not zero in a file with a right CRC gives 4 |

The Pocket itself checks the size (`size_exact`), so a file of another size may be refused before the core runs.

### Which files a core takes

- **Every kind.** One core takes a TEST or a RELEASE file, with or without the CPU MATE brain: the stub never
  refuses on the kind word (0x20), which is information only. There is no separate TEST core.
- **The epoch.** The firmware epoch (0x10) is raised only when the RTL changes in a way the firmware can see. A
  firmware-only release keeps it, so its file runs on the core the player already has, and older files of the same
  epoch still start. A file whose epoch, MCU interface, FEAT word or clock is not the core's is refused (code 5).

## The file

All words are little-endian as the MCU reads them. On disk the file is in the order the ROM loader stores it: every
16-bit pair swapped (MCU byte j = file byte j ^ 1). `tools/mkfafrium.py` writes and reads that form.

| offset | field | value |
|---|---|---|
| 0x00 | magic | 0x5246_4146 ('F' 'A' 'F' 'R') |
| 0x04 | format version (low 16) and header length (high 16) | 0x0080_0001 |
| 0x08 | file length | 0x0004_0000 (256 KB) |
| 0x0C | layout: IROM KB << 16, WRAM KB << 8, platform | 0x0058_3001 (88 KB, 48 KB, 1 = Analogue Pocket) |
| 0x10 | firmware epoch of the bitstream | 0x4641_0001 (the stub's EPOCH; changed with the RTL) |
| 0x14 | MCU interface | 0x5049_0103 (v1.3) |
| 0x18 | FEAT | 0x0058_0047 |
| 0x1C | MCU clock (Hz) | 53,693,175 |
| 0x20 | kind: bit 0 TEST, bit 1 the CPU MATE brain linked; bits 31-24 / 23-16 the firmware version, major / minor | information; the stub never refuses on it. Version 1.0 = 0x0100_0000 plus the kind bits |
| 0x24 | firmware build id (the paprium-fw commit, 32 bits) | information |
| 0x28 | number of sections | 3 |
| 0x2C | payload CRC-32 (IEEE, as zlib) over bytes 0x80-0x3FFFF | per build |
| 0x30 | IROM section: dest, length, file offset | 0x0000_0000, 0x16000, 0x80 |
| 0x3C | WRAM section: dest, length, file offset | 0x8000_2C00, 0x8000, 0x16080 |
| 0x48 | SRAM section: dest, length, file offset | 0x0800_0000, n (4-aligned, at most 0x10000), 0x1E080 |
| 0x54 | reserved, to 0x7B | zero: the stub refuses a file whose reserved words are not zero (code 4) |
| 0x7C | header CRC-32 over 0x00-0x7B | per build |
| 0x80 | IROM bytes 0x00000-0x15FFF | 90,112 B |
| 0x16080 | WRAM bytes 0x2C00-0xABFF | 32,768 B |
| 0x1E080 | the MegaWire SRAM code | n bytes |
| 0x1E080 + n | zero fill, to 0x3FFFB | zero: it is in the payload CRC, and the stub refuses a byte that is not zero (code 4) |
| 0x3FFFC | end word | 0x444E_4546 ('F' 'E' 'N' 'D') |

Every WRAM byte of a build outside 0x2C00-0xABFF must be zero (`mkfafrium.py` refuses otherwise): the stub leaves
those bytes at the bitstream's zero, as a build has them. The Pocket SRAM outside the SRAM section is not written.

## Tools

- `python -I -B tools/mkfafrium.py stub --out DIR [--install <RTL tree>/rtl/PAPRIUM]`: builds the stub and the six
  image files the bitstream reads (`mcu.txt` = the stub and zeros, `mcu_ext.txt` and the four WRAM lanes = zeros).
- `python -I -B tools/mkfafrium.py make --img <build>/img --sram <build>/img/sram.bin [--out little_man_firmware.bin]
  --kind release|test [--brain] [--version 1.0] [--build <commit>]`: the file from one firmware build. `--out`
  defaults to `little_man_firmware.bin`, the name the Pocket loads, and `--version` to the tool's FW_VERSION (1.0).
- `python -I -B tools/mkfafrium.py check little_man_firmware.bin --img <build>/img --sram <build>/img/sram.bin`: the
  file against the build's images byte for byte, with both CRCs.
- `show` decodes a header, with the kind and the firmware version read from the kind word; `bad` writes
  planted-fault copies for the RTL benches.
- `python -I -B tools/mkfafrium.py memorder little_man_firmware.bin --out DIR`: the file in memory order, as the stub
  places it. `irom.bin` is the IROM from 0x0000_0000. `wram.bin` is all 48 KB of WRAM from 0x8000_0000: the window from
  the file and zeros elsewhere. `sram.bin` is the Pocket SRAM from 0x0800_0000. The bytes the stub does not place go to
  `header.bin` and `tail.bin` (the zero fill and the end word), and `memorder.json` lists every part.
- `python -I -B tools/mkfafrium.py leak little_man_firmware.bin --elf <build>/main.elf [--elf <build>/ovl/ovl.elf]
  [--sram-elf <the SRAM code's ELF: main.elf when the build links the MegaWire code>]`: the leak guard
  (`tools/leakguard.py`, with its references from `paths.local.json`) on that memory-order copy. Every hit is
  mapped to its IROM, WRAM or SRAM address, and it must lie where the guard's ELF method allows it in the build. That
  is inside the brain's own bytes, or in code when the reference is a brain file (the ELF method scans code only
  against the other references), or in a window over an allowed table whose other bytes are all zero. The last rule
  is the leak guard's rule for built sections (B Jam's decision of 2026-10-30). Any other hit, and any hit in the
  bytes the stub does not place, fails the check (exit 1).
