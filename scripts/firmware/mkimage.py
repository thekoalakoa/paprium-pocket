# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""Split a linked Paprium MCU firmware ELF into the block-RAM init files the RTL reads with $readmemh
(rtl/PAPRIUM/mcu_core.sv: mcu.txt, mcu_ext.txt; rtl/PAPRIUM/memory.sv: wram_b0.txt .. wram_b3.txt from test build 4
on, wram_hi.txt / wram_lo.txt before it; a test build is a build B Jam tested on his own Pocket).

    python mkimage.py <main.elf> <out dir> [--rom0-kb 32] [--ext-kb 40] [--wram-kb 48]
                      [--wram-init 0x80002C00:0x80006C00 ...] [--wram-blob 0x80006C00:<file> ...]
                      [--objdump riscv-none-elf-objdump] [--sram 0x08000000:0x08010000]

The defaults are the 0.3.0 shapes the stage-1 RTL reads (stage 1 = the first stage of the 0.3.0 work: the new
firmware's own start-up, scheduler, dispatcher and board layer; the firmware tree's docs/MCU_INTERFACE.md v1.0, sections
3.1-3.2): IROM 72 KB = rom0 32 KB + one
40 KB extension (mcu_core.sv EXT_KB = 40), WRAM 48 KB (memory.sv: 24,576 lines per file). The 0.2.x shapes were
--ext-kb 22 --wram-kb 32.

  mcu.txt      rom0 = IROM bytes 0x0000 .. rom0_kb KB: 16 words a line, each word = 4 bytes in address order, upper-case
               hex, CRLF between lines, one trailing space after the last word (krikzz's bin_to_verilog layout; the
               RTL swaps the bytes back)
  mcu_ext.txt  the IROM extension = bytes from rom0_kb KB, padded to ext_kb x 256 words, same format
  wram_hi.txt  WRAM even bytes (cell k = MCU byte 2k), wram_kb x 512 lines of 2 hex digits, CRLF
  wram_lo.txt  WRAM odd bytes  (cell k = MCU byte 2k+1); zero outside the bitstream-initialised ranges
  wram_b0.txt .. wram_b3.txt  the same WRAM bytes as four byte lanes (line k of wram_b<i> = MCU byte 4k + i),
               wram_kb x 256 lines each, same line format: test build 4's paprium_wram (four 8-bit lanes, tightly coupled
               to the NEORV32) reads these; the pair above is what the RTL before test build 4 reads (both from one
               byte array)
  sram.bin     with --sram LO:HI only: the ELF's load segments inside [LO, HI), the MegaWire code the firmware runs
               from the Pocket SRAM, with three words of its 64-byte header filled in here: the length (word 2) and
               the CRC-32s of the hot part [0x40, hot end) (word 3) and of the cold part [hot end, length) (word 6);
               word 5 holds the hot end, as the link placed it. It is not a block-RAM image: it travels in the
               firmware file (Little-Man Firmware), and on the test builds before that file in the MegaWire data slot.
  rom.bin, wcode.bin, image.json   (diagnostics; with --sram, image.json also names sram.bin's size, CRC and md5)
The rom image is the ELF's load image (PT_LOAD by physical address) below 0x80000000, the --sram range left out; every WRAM load segment must sit
inside one of the --wram-init ranges (default: the code window 0x80002C00-0x80006C00, which the RTL write-locks).
--wram-blob ADDR:FILE (test build 4b on) places FILE's bytes at WRAM address ADDR: the WRAM boot overlay (ovl.img, linked on
its own by the firmware tree); it must sit inside an init range and overlap no load segment of the ELF, and image.json
lists it under wram_blobs (address, bytes, md5).

The same tool as the firmware tree's tools/mkimage.py (in this repository's firmware/ folder), with the stage-1 shapes as defaults: the logic and
the output bytes are the same, and scripts/build_mcu.sh checks that this copy reproduces the firmware build's images
byte for byte."""
import argparse, hashlib, json, os, struct, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument('elf'); ap.add_argument('out')
ap.add_argument('--rom0-kb', type=int, default=32)
ap.add_argument('--ext-kb', type=int, default=40)
ap.add_argument('--wram-kb', type=int, default=48)
ap.add_argument('--wram-init', action='append', default=None, help='lo:hi (hi exclusive), repeatable')
ap.add_argument('--wram-blob', action='append', default=[], help='addr:file (card 4b on: the boot overlay), repeatable')
ap.add_argument('--objdump', default='riscv-none-elf-objdump', help='for the section list in image.json only')
ap.add_argument('--sram', default=None, help='lo:hi: load segments there form sram.bin, the MegaWire code for the '
                'Pocket SRAM; its 64-byte header at lo gets the length and the two CRC-32 words here')
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
WINIT = [tuple(int(x, 0) for x in r.split(':')) for r in (a.wram_init or ['0x80002C00:0x80006C00'])]
WRAM_BASE = 0x80000000
WRAM_BYTES = 1024 * a.wram_kb


def sections(elf):
    try:
        r = subprocess.run([a.objdump, '-h', elf], capture_output=True, text=True, check=True).stdout.split('\n')
    except (OSError, subprocess.CalledProcessError):
        return {}
    s = {}
    for ln in r:
        p = ln.split()
        if len(p) >= 6 and p[0].isdigit():
            s[p[1] + ('' if p[1] not in s else '#2')] = dict(size=int(p[2], 16), vma=int(p[3], 16), lma=int(p[4], 16))
    return s


S = sections(a.elf)

# the load image from the PT_LOAD program headers (by physical = load address), not objcopy -j: the NEORV32 script
# has two output sections named .rodata, and a multi-section objcopy output zero-fills the first
E = open(a.elf, 'rb').read()
assert E[:4] == b'\x7fELF' and E[4] == 1 and E[5] == 1, 'ELF32 little-endian expected'
e_phoff, = struct.unpack_from('<I', E, 28); e_phentsize, e_phnum = struct.unpack_from('<HH', E, 42)
rom = bytearray(); wram = bytearray(WRAM_BYTES); wc = None
SR = tuple(int(x, 0) for x in a.sram.split(':')) if a.sram else None
sram = bytearray()
for i in range(e_phnum):
    p_type, p_off, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from('<8I', E, e_phoff + i * e_phentsize)
    if p_type != 1 or p_filesz == 0:
        continue
    data = E[p_off:p_off + p_filesz]
    if SR and SR[0] <= p_paddr < SR[1]:     # the MegaWire code for the Pocket SRAM: sram.bin, not a block-RAM image
        if p_paddr + p_filesz > SR[1]:
            sys.exit(f'load segment at {p_paddr:#x} (+{p_filesz}) runs past the SRAM image room')
        o = p_paddr - SR[0]
        if len(sram) < o + p_filesz:
            sram.extend(b'\0' * (o + p_filesz - len(sram)))
        sram[o:o + p_filesz] = data
        continue
    if p_paddr < WRAM_BASE:
        if len(rom) < p_paddr + p_filesz:
            rom.extend(b'\0' * (p_paddr + p_filesz - len(rom)))
        rom[p_paddr:p_paddr + p_filesz] = data
    else:
        rng = [r for r in WINIT if r[0] <= p_paddr and p_paddr + p_filesz <= r[1]]
        if not rng:
            sys.exit(f'load segment at {p_paddr:#x} (+{p_filesz}) is neither rom nor a bitstream-initialised WRAM range')
        o = p_paddr - WRAM_BASE
        wram[o:o + p_filesz] = data
        wc = (min(wc[0], p_paddr), max(wc[1], p_paddr + p_filesz)) if wc else (p_paddr, p_paddr + p_filesz)
rom = bytes(rom)
loaded = [(p_paddr, p_paddr + p_filesz) for i in range(e_phnum)
          for p_type, p_off, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align in
          [struct.unpack_from('<8I', E, e_phoff + i * e_phentsize)] if p_type == 1 and p_filesz and p_paddr >= WRAM_BASE]
blobs = []
for spec in a.wram_blob:
    adr, fn = spec.split(':', 1)
    adr = int(adr, 0)
    b = open(fn, 'rb').read()
    if not [r for r in WINIT if r[0] <= adr and adr + len(b) <= r[1]]:
        sys.exit(f'wram blob {fn} at {adr:#x} (+{len(b)}) is outside every bitstream-initialised WRAM range')
    if [s for s in loaded if s[0] < adr + len(b) and adr < s[1]]:
        sys.exit(f'wram blob {fn} at {adr:#x} (+{len(b)}) overlaps a load segment of the ELF')
    wram[adr - WRAM_BASE:adr - WRAM_BASE + len(b)] = b
    blobs.append(dict(addr=hex(adr), bytes=len(b), md5=hashlib.md5(b).hexdigest()))
# wcode.bin = the first init range from its start to the end of its last loaded byte (the code window)
w0 = WINIT[0][0]
wcb = bytes(wram[w0 - WRAM_BASE:wc[1] - WRAM_BASE]) if wc else b''
open(os.path.join(a.out, 'rom.bin'), 'wb').write(rom)
open(os.path.join(a.out, 'wcode.bin'), 'wb').write(wcb)
ROM0, EXT = 1024 * a.rom0_kb, 1024 * a.ext_kb
if len(rom) > ROM0 + EXT:
    sys.exit(f'rom image {len(rom)} B > rom0 + extension {ROM0 + EXT} B')


def words_txt(b, nwords=None):
    b = b + b'\0' * (-len(b) % 4)
    if nwords is not None:
        b = b + b'\0' * (4 * nwords - len(b))
    w = [b[i:i + 4].hex().upper() for i in range(0, len(b), 4)]
    # krikzz's bin_to_verilog layout, byte for byte: CRLF between lines, the last line ends in one space
    return '\r\n'.join(' '.join(w[i:i + 16]) for i in range(0, len(w), 16)) + ' '


open(os.path.join(a.out, 'mcu.txt'), 'w', newline='').write(words_txt(rom[:ROM0], ROM0 // 4 if len(rom) < ROM0 else None))
open(os.path.join(a.out, 'mcu_ext.txt'), 'w', newline='').write(words_txt(rom[ROM0:], 256 * a.ext_kb) if a.ext_kb else '')
half = WRAM_BYTES // 2
open(os.path.join(a.out, 'wram_hi.txt'), 'w', newline='\r\n').write(''.join(f'{wram[2 * k]:02X}\n' for k in range(half)))
open(os.path.join(a.out, 'wram_lo.txt'), 'w', newline='\r\n').write(''.join(f'{wram[2 * k + 1]:02X}\n' for k in range(half)))
for lane in range(4):   # test build 4 on: the four byte lanes (paprium_wram's ram_b0 .. ram_b3)
    open(os.path.join(a.out, 'wram_b%d.txt' % lane), 'w', newline='\r\n').write(
        ''.join(f'{wram[4 * k + lane]:02X}\n' for k in range(WRAM_BYTES // 4)))
srep = {}
if SR:      # the SRAM image: header words 2 (length), 3 (CRC-32 of the hot part [0x40, hot end)) and 6 (CRC-32 of the
            # cold part [hot end, length)) filled here; word 5 holds the hot end's offset (the link's)
    import zlib
    if sram:
        sram.extend(b'\0' * (-len(sram) % 4))
        magic = struct.unpack_from('<I', sram, 0)[0]
        if len(sram) < 0x44 or magic == 0:
            sys.exit('the SRAM image has no header at its start')
        struct.pack_into('<I', sram, 8, len(sram))
        hot = struct.unpack_from('<I', sram, 20)[0]       # word 5: the hot part's end, an offset into the image
        if not (0x40 <= hot <= len(sram)) or hot & 3:
            sys.exit('the SRAM image header names no hot end inside it (word 5: %#x)' % hot)
        struct.pack_into('<I', sram, 12, zlib.crc32(bytes(sram[0x40:hot])) & 0xFFFFFFFF)
        struct.pack_into('<I', sram, 24, zlib.crc32(bytes(sram[hot:])) & 0xFFFFFFFF)
    open(os.path.join(a.out, 'sram.bin'), 'wb').write(bytes(sram))
    srep = dict(sram_bytes=len(sram), sram_crc32='%08x' % (struct.unpack_from('<I', sram, 12)[0] if sram else 0),
                md5_sram=hashlib.md5(bytes(sram)).hexdigest())
rep = dict(rom_bytes=len(rom), rom0_used=min(len(rom), ROM0), ext_used=max(0, len(rom) - ROM0), ext_bytes=EXT,
           wram_code_bytes=len(wcb), wram_code_base=hex(w0) if wc else None,
           md5_rom=hashlib.md5(rom).hexdigest(), md5_wcode=hashlib.md5(wcb).hexdigest(), **({"wram_blobs": blobs} if blobs else {}),
           **srep,
           sections={k: v for k, v in S.items() if v['size']})
json.dump(rep, open(os.path.join(a.out, 'image.json'), 'w', newline='\r\n'), indent=1)
print(json.dumps({k: v for k, v in rep.items() if k != 'sections'}))
