#!/usr/bin/env python3
"""Extract Paprium's music instrument bank (WavPack) from the cartridge ROM.

    python scripts/dump_wave.py <paprium.md> [out.wv]

The bank is located through the same pointer table as the SFX bank, four bytes
earlier (GPGX `paprium.h:2837`):

    base = be32(rom + be32(rom + 0xAF77C) + 0x774)

It is **WavPack** - magic "wvpk" - holding 1,379,262 samples in one-second blocks.
The low byte of each 16-bit sample is zero: the real data is 8-bit unsigned, which
is how the cartridge's synth reads it.

Decode with ffmpeg:

    ffmpeg -i wave-bank.wv wave-bank.wav

The result is derived from a commercial ROM. Keep it local; it is gitignored
alongside the SFX dump.
"""
import struct, sys


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    d = open(sys.argv[1], 'rb').read()
    out = sys.argv[2] if len(sys.argv) > 2 else 'wave-bank.wv'

    be16 = lambda o: struct.unpack_from('>H', d, o)[0]
    be32 = lambda o: (be16(o) << 16) | be16(o + 2)

    base = be32(0xAF77C)
    wave, sfx = be32(base + 0x774), be32(base + 0x778)
    print("wave bank 0x%06X .. 0x%06X  (%d bytes)" % (wave, sfx, sfx - wave))

    if d[wave:wave + 4] != b'wvpk':
        print("error: no WavPack magic at 0x%06X - wrong ROM?" % wave, file=sys.stderr)
        return 1

    total = struct.unpack_from('<I', d, wave + 12)[0]
    print("version 0x%04X, %d samples (%.1f s at 44100)"
          % (struct.unpack_from('<H', d, wave + 8)[0], total, total / 44100))

    blocks = bytearray()
    off, n = wave, 0
    while off < sfx - 32 and d[off:off + 4] == b'wvpk':
        size = struct.unpack_from('<I', d, off + 4)[0] + 8
        blocks += d[off:off + size]
        off += size
        n += 1

    open(out, 'wb').write(blocks)
    print("%d blocks, %d bytes -> %s" % (n, len(blocks), out))
    if off != sfx:
        print("note: block chain ended at 0x%06X, sfx pointer is 0x%06X" % (off, sfx))
    return 0


if __name__ == '__main__':
    sys.exit(main())
