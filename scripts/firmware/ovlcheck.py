# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""Read the WRAM boot overlay (test build 4b on, a build B Jam tested on his own Pocket: the firmware's first-boot
unpack of the cart's sound bank) back from the
four WRAM lane images the RTL reads (wram_b0.txt .. wram_b3.txt: line k of wram_b<i> = MCU byte 4k + i, from WRAM
0x80000000) and check it the way the firmware's IROM stub checks it before it enters it (the firmware/ folder's
board/pocket/boot/boot_cache.c, boot_overlay_ok): the 16-byte header at the overlay's address (magic 'POV1'
0x31564F50, length <= room - 16, 16 <= entry < 16 + length, the CRC-32 of the length bytes after the header == the
header's CRC-32), then byte for byte against the firmware build's ovl.img, and the rest of its room zero.

    python ovlcheck.py <image dir> <ovl.img> [--addr 0x80006C00] [--room 16384]

Exit 0 when the overlay is intact and equals ovl.img, 1 otherwise (also when the magic is absent: an image without
the overlay boots without the unpack). scripts/build_mcu.sh --wram-blob runs it on the images it made and again on
rtl/PAPRIUM/ after the install. Files are only read."""
import argparse, hashlib, os, struct, sys, zlib

WRAM_BASE = 0x80000000
MAGIC = 0x31564F50

ap = argparse.ArgumentParser()
ap.add_argument('dir'); ap.add_argument('ovl')
ap.add_argument('--addr', default='0x80006C00')
ap.add_argument('--room', type=int, default=16384)
a = ap.parse_args()
addr = int(a.addr, 0)
lanes = [[int(x, 16) for x in open(os.path.join(a.dir, 'wram_b%d.txt' % i)).read().split()] for i in range(4)]
n = min(len(x) for x in lanes)
wram = bytearray(4 * n)
for i in range(4):
    wram[i::4] = bytes(v & 0xFF for v in lanes[i][:n])
ref = open(a.ovl, 'rb').read()
o = addr - WRAM_BASE
ok = 0 <= o and o + a.room <= len(wram) and len(ref) <= a.room
if not ok:
    print('ovlcheck: the room %#x (+%d) or ovl.img (%d B) does not fit the %d B WRAM image' % (addr, a.room, len(ref), len(wram)))
    sys.exit(1)
magic, length, crc, entry = struct.unpack_from('<4I', wram, o)
where = '/'.join(os.path.abspath(a.dir).replace('\\', '/').split('/')[-2:])
print('  overlay read back from %s/wram_b0..b3.txt: %#x magic %#010x, length %d, CRC-32 %08x, entry +%#x'
      % (where, addr, magic, length, crc, entry))
if magic != MAGIC:
    print("  NO OVERLAY: the magic is not 'POV1' (%#010x)" % MAGIC)
    sys.exit(1)
hdr = length <= a.room - 16 and 16 <= entry < 16 + length
c = zlib.crc32(bytes(wram[o + 16:o + 16 + length])) & 0xFFFFFFFF
same = bytes(wram[o:o + len(ref)]) == ref
tail = not any(wram[o + len(ref):o + a.room])
print('  the stub\'s test: length <= %d %s, 16 <= entry < 16 + length %s, CRC-32 of the body %08x == %08x %s; '
      '= ovl.img (%d B, md5 %s) %s; the %d B after it zero %s'
      % (a.room - 16, length <= a.room - 16, 16 <= entry < 16 + length, c, crc, c == crc, len(ref),
         hashlib.md5(ref).hexdigest(), same, a.room - len(ref), tail))
ok = hdr and c == crc and same and tail
print('  -> ' + ('OVERLAY INTACT' if ok else 'OVERLAY BAD'))
sys.exit(0 if ok else 1)
