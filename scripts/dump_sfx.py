#!/usr/bin/env python3
"""Dump the Paprium cartridge SFX sample bank to WAV.

    python scripts/dump_sfx.py <paprium.md> [outdir]

The cart holds its sound effects as raw PCM in ROM - unlike the music, which is
compressed and needs the DATENMEISTER decoder. That makes the SFX bank readable
offline, which is how we check whether a scene's audio is an effect rather than
a music track.

Layout, taken from Genesis Plus GX (`paprium.h`, sfx_play / paprium_sfx_voice):

    sfx_ptr = be32(rom + be32(rom + 0xAF77C) + 0x778)
    entry N = 8 bytes at sfx_ptr + N*8
        +0  u32  offset of the samples, relative to sfx_ptr
        +4  u8   type   (see the ^1 note)
        +5  u8   size high byte
        +6  u16  size low word          size counts SAMPLES, not bytes
    type >> 4  -> rate index into {1,2,4,5,8,9}, i.e. 48000/N Hz
    type &  3  -> depth: 1 = 8-bit unsigned, 2 = 4-bit packed, high nibble first

BYTE ORDER, the part that is easy to get wrong. GPGX keeps `cart.rom` byte-swapped
against the file, so a `*(uint16*)` read yields the big-endian value directly and a
plain byte read lands on the neighbouring byte. Therefore:

  * the table's u8 fields are read WITHOUT `^1` in GPGX, so they need `^1` here;
  * the sample read is `cart.rom + sfx_ptr + (voice->ptr^1)`, which already carries
    an explicit `^1`, so it resolves to the PLAIN file byte - no swap here.

Getting that backwards still produces plausible-looking output, so the result is
checked three ways: the entries must pack contiguously, the sizes must agree with
depth, and GPGX's high-nibble-first order must come out smoother than low-first.
Run with --verify to re-run those checks.
"""
import os, struct, sys, wave, statistics

RATES = [1, 2, 4, 5, 8, 9]


def load(path):
    with open(path, 'rb') as f:
        return f.read()


def be16(d, o): return struct.unpack_from('>H', d, o)[0]
def be32(d, o): return (be16(d, o) << 16) | be16(d, o + 2)
def tbl8(d, o): return d[o ^ 1]          # table u8: GPGX omits ^1, so apply it


def sfx_base(d):
    return be32(d, be32(d, 0xAF77C) + 0x778)


def entries(d):
    base = sfx_base(d)
    for i in range(128):
        b = base + i * 8
        ptr = be32(d, b)
        size = (tbl8(d, b + 4) << 16) | be16(d, b + 6)
        typ = tbl8(d, b + 5)
        if ptr == 0 and size == 0:
            continue
        rate_i, depth = typ >> 4, typ & 3
        if rate_i >= len(RATES) or depth not in (1, 2):
            continue                      # entry 0 is type 0 and unused
        yield i, ptr, size, depth, 48000 // RATES[rate_i]


def decode(d, base, ptr, size, depth, hi_first=True):
    out = bytearray()
    cnt = off = 0
    for _ in range(size):
        byte = d[base + ptr + off]        # plain file byte - see module docstring
        if depth == 1:
            v = byte * 256 - 32768
        else:
            hi, lo = byte >> 4, byte & 0x0F
            first, second = (hi, lo) if hi_first else (lo, hi)
            v = (first if cnt == 0 else second) * 4096 - 32768
        out += struct.pack('<h', max(-32768, min(32767, v)))
        cnt += 1
        if cnt >= depth:
            off += 1
            cnt = 0
    return bytes(out)


def roughness(pcm):
    s = struct.unpack(f'<{len(pcm)//2}h', pcm)
    if len(s) < 3:
        return float('inf')
    dev = statistics.pstdev(s) or 1
    return sum(abs(s[i + 1] - s[i]) for i in range(len(s) - 1)) / (len(s) - 1) / dev


def verify(d):
    base = ents = None
    ents = sorted(entries(d), key=lambda e: e[1])
    exact = pad = bad = 0
    for a, nxt in zip(ents, ents[1:]):
        _, ptr, size, depth, _ = a
        delta = nxt[1] - (ptr + -(-size // depth))
        if delta == 0:   exact += 1
        elif delta == 1: pad += 1
        else:            bad += 1
    print(f"contiguity: {exact} exact joins, {pad} word-padded, {bad} unexplained")

    base = sfx_base(d)
    hi = lo = 0
    for _, ptr, size, depth, _ in ents:
        if depth != 2:
            continue
        if roughness(decode(d, base, ptr, size, depth, True)) <= \
           roughness(decode(d, base, ptr, size, depth, False)):
            hi += 1
        else:
            lo += 1
    print(f"nibble order: high-first smoother in {hi}, low-first in {lo} "
          f"(GPGX says high-first, so high should win)")
    return bad == 0 and hi > lo


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('-')]
    if not args:
        print(__doc__)
        return 2
    rom = load(args[0])
    outdir = args[1] if len(args) > 1 else 'sfx-dump'

    print(f"sfx_ptr = 0x{sfx_base(rom):08X}")
    if '--verify' in sys.argv:
        return 0 if verify(rom) else 1

    os.makedirs(outdir, exist_ok=True)
    base = sfx_base(rom)
    n = 0
    for i, ptr, size, depth, hz in entries(rom):
        pcm = decode(rom, base, ptr, size, depth)
        name = (f"sfx_{i:03d}_0x{i:02X}_{hz}Hz_"
                f"{4 if depth == 2 else 8}bit_{size/hz:.2f}s.wav")
        with wave.open(os.path.join(outdir, name), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(hz)
            w.writeframes(pcm)
        n += 1
    print(f"wrote {n} WAVs to {outdir}/")
    return 0


if __name__ == '__main__':
    sys.exit(main())
