#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""mkimage.py - split a linked firmware ELF into the cart MCU's block-RAM init files.

    python -I -B tools/mkimage.py <main.elf> <out dir> --ext-kb N [--rom0-kb 32] [--wram-kb 32]
                                  [--wram-init 0x80002C00:0x80006C00 ...] [--wram-blob 0x80006C00:<file> ...]
                                  [--objdump <riscv objdump>]

Outputs (formats exactly as the 0.2.6 build wrote them, so a legacy54k build is byte-identical to the shipped 0.2.6
images). IROM is the MCU's code memory and WRAM its working RAM, both block RAM in the FPGA; RTL is the core's
hardware description.
  mcu.txt      rom0 = IROM bytes 0x0000 .. rom0_kb KB: 16 words a line, each word = 4 bytes in address order, upper-case
               hex, CRLF between lines, one trailing space after the last word (krikzz's bin_to_verilog layout)
  mcu_ext.txt  the IROM extension = bytes from rom0_kb KB, padded to ext_kb x 256 words, same format
  wram_hi.txt  WRAM even bytes (cell k = MCU byte 2k), wram_kb x 512 lines of 2 hex digits, CRLF
  wram_lo.txt  WRAM odd bytes  (cell k = MCU byte 2k+1); zero outside the bitstream-initialised ranges
  wram_b0.txt .. wram_b3.txt  the same WRAM bytes as four byte lanes (line k of wram_b<i> = MCU byte 4k + i),
               wram_kb x 256 lines each, same line format. The newer RTL (the WRAM tightly coupled to the NEORV32,
               paprium_wram as four 8-bit lanes) reads these, older RTL the pair above; both come from one byte array
  rom.bin, wcode.bin, image.json   (diagnostics; image.json has CRLF line ends like the 0.2.6 build's)
The rom image is the ELF's load image (PT_LOAD by physical address) below 0x80000000; every WRAM load segment must sit
inside one of the --wram-init ranges (default: the buddy code window 0x80002C00-0x80006C00). --wram-blob ADDR:FILE
places FILE's bytes at WRAM address ADDR: the WRAM boot overlay (test build 4b), linked on its own (board/pocket/link/
c4b_ovl.ld); it must sit inside an init range and overlap no load segment of the ELF.

Derived from the mkimage.py that built the shipped 0.2.6 images: the logic and the output bytes are the same; the
sizes and the WRAM ranges are parameters, and the objdump path is an argument instead of a constant.
Stage numbers are the steps of the 0.3.0 work (README.md, "Terms")."""
import argparse, hashlib, json, os, struct, subprocess, sys

ap = argparse.ArgumentParser()
ap.add_argument('elf'); ap.add_argument('out')
ap.add_argument('--ext-kb', type=int, required=True)
ap.add_argument('--rom0-kb', type=int, default=32)
ap.add_argument('--wram-kb', type=int, default=32)
ap.add_argument('--wram-init', action='append', default=None, help='lo:hi (hi exclusive), repeatable')
ap.add_argument('--wram-blob', action='append', default=[], help='addr:file (card 4b: the boot overlay), repeatable')
ap.add_argument('--objdump', default='riscv-none-elf-objdump')
ap.add_argument('--sram', default=None, help='lo:hi (stage 3): load segments there form sram.bin, the SRAM image '
                'the APF data slot loads; its header (64 B at lo: magic, version, length, CRC-32, link id) gets the '
                'length and the CRC-32 of [0x40, length) here')
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)
WINIT = [tuple(int(x, 0) for x in r.split(':')) for r in (a.wram_init or ['0x80002C00:0x80006C00'])]
WRAM_BASE = 0x80000000
WRAM_BYTES = 1024 * a.wram_kb


def sections(elf):
    r = subprocess.run([a.objdump, '-h', elf], capture_output=True, text=True, check=True).stdout.split('\n')
    s = {}
    for ln in r:
        p = ln.split()
        if len(p) >= 6 and p[0].isdigit():
            s[p[1] + ('' if p[1] not in s else '#2')] = dict(size=int(p[2], 16), vma=int(p[3], 16), lma=int(p[4], 16))
    return s


S = sections(a.elf)

# load image from the PT_LOAD program headers (by physical = load address), not objcopy -j: the NEORV32 script has two
# output sections named .rodata, and a multi-section objcopy output zero-filled the first
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
    if SR and SR[0] <= p_paddr < SR[1]:
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
# wcode.bin = the first init range from its start to the end of its last loaded byte (0.2.6: the code window)
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
for lane in range(4):   # the four byte lanes of the newer RTL of test build 4 (paprium_wram's ram_b0 .. ram_b3)
    open(os.path.join(a.out, 'wram_b%d.txt' % lane), 'w', newline='\r\n').write(
        ''.join(f'{wram[4 * k + lane]:02X}\n' for k in range(WRAM_BYTES // 4)))
srep = {}
if SR:      # the SRAM image: header words 2 (the length), 3 (the CRC-32 of the hot part, [0x40, hot end)) and 6 (the
            # CRC-32 of the cold part, [hot end, length)) are filled here. Word 5 holds the hot end's offset (the link's).
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
