#!/usr/bin/env python3
"""Decompress Paprium's music modules (MWMM) from the cartridge ROM.

    python scripts/dump_music.py <paprium.md> [outdir]

Modules are located through a pointer table whose base is read from ROM 0x10054;
entry 0 is the track count (62) and entries 1..62 are offsets RELATIVE to that
base. Ten are null - the cartridge genuinely has no music for those indices.

Each module begins `81 0E 57 4D 4D 4D 00 01`: `0x81` is the decoder type byte, so
the LZO stream starts one byte later, and its first instruction emits the literal
"WMMM" header. The LZO decoder here is the same one ported into the firmware
(mame.c case 0x81), so this doubles as a check on it - all 52 modules decompress.

Byte order: PLAIN file bytes, no ^1. That differs from the SFX table, which needs
the swap. Established empirically.

Header, as far as it is understood:

    +0x00  "WMMM"
    +0x04  00 01          version - constant across all 52
    +0x06  BE xx          BE constant; second byte varies (03/05)
    +0x08  xx xx          varies per track
    +0x0A  xx 10 04 00 00 00
    +0x10  26 bytes       per-voice array, 0x10 in every module. 26 is the voice
                          count in GPGX's synth loop
    +0x34  sequence data begins

Output is derived from a commercial ROM. Keep it local; gitignored.
"""
import os, struct, sys


def lzo(d, src, limit):
    """paprium_decoder_lzo, ported from Genesis Plus GX. Plain byte reads."""
    out = bytearray()
    s, state = src, 0
    while s < limit:
        c = d[s]; s += 1
        if c & 0x80:
            raw = c & 3; ln = ((c >> 5) & 3) + 5
            lz = ((c >> 2) & 7) + (d[s] << 3) + 1; s += 1
        elif c & 0x40:
            raw = c & 3; ln = ((c >> 5) & 1) + 3
            lz = ((c >> 2) & 7) + (d[s] << 3) + 1; s += 1
        elif c & 0x20:
            ln = c & 0x1F
            if ln == 0:
                ex = 0
                while True:
                    ln = d[s]; s += 1
                    if ln: break
                    ex += 255
                ln += ex + 31
            ln += 2
            c = d[s]; s += 1
            raw = c & 3; lz = (c >> 2) + (d[s] << 6) + 1; s += 1
        elif c & 0x10:
            ln = c & 7
            if ln == 0:
                ex = 0
                while True:
                    ln = d[s]; s += 1
                    if ln: break
                    ex += 255
                ln += ex + 7
            ln += 2
            lz = ((c >> 3) & 1) << 14
            c = d[s]; s += 1
            raw = c & 3; lz += (c >> 2) + (d[s] << 6) + 16384; s += 1
            if lz == 16384:
                return bytes(out)
        else:
            if state == 0:
                raw = c & 0x0F
                if raw == 0:
                    ex = 0
                    while True:
                        raw = d[s]; s += 1
                        if raw: break
                        ex += 255
                    raw += ex + 15
                raw += 3; ln = 0; state = 4
            elif state < 4:
                raw = c & 3; lz = ((c >> 2) & 3) + (d[s] << 2) + 1; s += 1; ln = 2
            else:
                raw = c & 3; lz = ((c >> 2) & 3) + (d[s] << 2) + 2049; s += 1; ln = 3
        state = raw if ln > 0 else 4
        if ln > 0:
            p = len(out) - lz
            if p < 0:
                return bytes(out)
            for _ in range(ln):
                out.append(out[p]); p += 1
        for _ in range(raw):
            out.append(d[s]); s += 1
    return bytes(out)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    d = open(sys.argv[1], 'rb').read()
    outdir = sys.argv[2] if len(sys.argv) > 2 else 'music-modules'
    os.makedirs(outdir, exist_ok=True)

    be16 = lambda o: struct.unpack_from('>H', d, o)[0]
    be32 = lambda o: (be16(o) << 16) | be16(o + 2)

    base = be32(0x10054)
    count = be32(base)
    print("pointer table 0x%08X, %d tracks" % (base, count))

    live = nulls = 0
    for t in range(1, count + 1):
        off = be32(base + t * 4)
        if not off:
            nulls += 1
            continue
        a = base + off
        if d[a:a + 6] != b'\x81\x0eWMMM':
            print("  track %-3d unexpected prologue at 0x%06X" % (t, a))
            continue
        u = lzo(d, a + 1, a + 0x8000)
        open(os.path.join(outdir, "track%02d.mwmm" % t), 'wb').write(u)
        live += 1
        if t <= 3 or t % 20 == 0:
            print("  track %-3d 0x%06X -> %5d bytes  hdr %s"
                  % (t, a, len(u), " ".join("%02X" % b for b in u[4:16])))

    print("\n%d modules written to %s/, %d null entries" % (live, outdir, nulls))
    return 0


if __name__ == '__main__':
    sys.exit(main())
