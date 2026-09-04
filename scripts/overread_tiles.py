"""Map every window over-read to the VRAM tiles it landed in, and count the
on-screen cells that paint those tiles.

    python scripts/overread_tiles.py paprium_winlog.bin "Paprium.state.auto"

The window log (apply_gpgx_winlog.py + apply_gpgx_dmalog.py) says which
words the 68000 read from the stream window and, per 68k-bus DMA, where the
VDP put them. A GPGX savestate taken at the end of the same run holds the
name tables, VRAM, palettes and scroll. Together:

  1. group window reads into "streams": runs of window-sourced DMAs with no
     re-point (0xDA/0xDB/0xAF) between them, as the game issues them;
  2. within a stream, the payload delivered by the decoder is the sum of the
     page sizes turned; every word DMA'd beyond that is an over-read;
  3. those over-read words have a VRAM destination (the DMA that carried
     them), hence a tile range;
  4. scan plane A and plane B for cells referencing those tiles, and say how
     many are on screen given the scroll at the moment of the state.

This is the tile-1509 finding on the train, done for every stream at once.
"""
import struct
import sys

sys.path.insert(0, __file__.rsplit('/', 1)[0] if '/' in __file__ else '.')
import parse_gpgx_state as P
import render_vram_tiles as R

KIND_WORD, KIND_BYTE, KIND_PAGE, KIND_DB, KIND_DA, KIND_AF, KIND_DMA, KIND_DMA2 = range(8)


def load_log(path):
    d = open(path, 'rb').read()
    return [struct.unpack_from('<BBHI', d, i * 8) for i in range(len(d) // 8)]


def streams(recs):
    """Yield (frame_start, pages_bytes, dmas) per stream. A stream is delimited by
    re-point commands; pages_bytes is the payload the decoder delivered into
    it; dmas is the list of window-sourced (frame, dest, code, words)."""
    cur = None
    pend = None
    for kind, pad, addr, stamp in recs:
        fr = stamp >> 16
        if kind in (KIND_DB, KIND_DA, KIND_AF):
            if cur and cur['dmas']:
                yield cur
            cur = None
            continue
        if cur is None:
            cur = {'frame': fr, 'pages': 0, 'dmas': []}
        if kind == KIND_PAGE:
            cur['pages'] += addr
        elif kind == KIND_DMA:
            pend = (fr, addr)
        elif kind == KIND_DMA2 and pend:
            f, dest = pend
            src = stamp
            if (src >> 16) == 0 and 0xC000 <= (src & 0xFFFF) <= 0xFFFF:
                cur['dmas'].append((f, dest, pad, addr))
            pend = None
    if cur and cur['dmas']:
        yield cur


def state_tables(path):
    vram, cram, reg = R.read_state(path)
    blob, _ = P.load(path)
    s = blob.find(P.VERSION)
    base = None
    for b in range(s, s + 64):
        vdp = b + P.WORK_RAM + P.ZRAM + P.ZSTATE + P.ZBANK + P.IO_REG
        ro = vdp + P.SAT_SZ + P.VRAM_SZ + P.CRAM_SZ + P.VSRAM_SZ
        r = blob[ro:ro + 6]
        if len(r) == 6 and r[2] == reg[2] and r[4] == reg[4]:
            base = b
            break
    vdp = base + P.WORK_RAM + P.ZRAM + P.ZSTATE + P.ZBANK + P.IO_REG
    vsram = P.unswap(blob[vdp + P.SAT_SZ + P.VRAM_SZ + P.CRAM_SZ:
                          vdp + P.SAT_SZ + P.VRAM_SZ + P.CRAM_SZ + P.VSRAM_SZ])
    planeA = (reg[2] & 0x38) << 10
    planeB = (reg[4] & 0x07) << 13
    hsbase = (reg[13] & 0x3F) << 10
    sz = reg[16]
    W = {0: 32, 1: 64, 3: 128}.get(sz & 3, 32)
    H = {0: 32, 1: 64, 3: 128}.get((sz >> 4) & 3, 32)
    # 10-bit scroll values; the sign-extended read is only for arithmetic
    hsA = struct.unpack('<h', vram[hsbase:hsbase + 2])[0] & 0x3FF
    hsB = struct.unpack('<h', vram[hsbase + 2:hsbase + 4])[0] & 0x3FF
    vsA = struct.unpack('<h', vsram[0:2])[0] & 0x3FF
    vsB = struct.unpack('<h', vsram[2:4])[0] & 0x3FF
    return vram, {'A': (planeA, hsA, vsA), 'B': (planeB, hsB, vsB)}, W, H


def cells_for(vram, plane, W, H, lo, hi):
    base, hs, vs = plane
    on, off = 0, 0
    pals = {}
    for i in range(W * H):
        e = vram[base + i * 2] | (vram[base + i * 2 + 1] << 8)
        t = e & 0x7FF
        if lo <= t <= hi:
            col, row = i % W, i // W
            px = (col * 8 + hs) % (W * 8)
            py = (row * 8 - vs) % (H * 8)
            if px < 320 and py < 224:
                on += 1
            else:
                off += 1
            p = (e >> 13) & 3
            pals[p] = pals.get(p, 0) + 1
    return on, off, pals


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    recs = load_log(sys.argv[1])
    vram, planes, W, H = state_tables(sys.argv[2])
    print("planes %dx%d   A 0x%04X hs %d vs %d   B 0x%04X hs %d vs %d"
          % (W, H, planes['A'][0], planes['A'][1], planes['A'][2],
             planes['B'][0], planes['B'][1], planes['B'][2]))
    print()
    total_over = 0
    findings = []
    for st in streams(recs):
        dmas = st['dmas']
        delivered = st['pages']
        words = sum(d[3] for d in dmas)
        over = words - delivered // 2
        if over <= 0:
            continue
        total_over += over
        # walk the DMAs to find where the over-read words landed
        acc = 0
        ranges = []
        for f, dest, code, n in dmas:
            start_word = acc
            acc += n
            if code != 1:
                continue                      # not VRAM
            if acc * 2 > delivered:
                first_over_word = max(start_word, delivered // 2)
                lo = dest + (first_over_word - start_word) * 2
                hi = dest + n * 2
                ranges.append((lo, hi, f))
        print("STREAM at frame %d: %d window DMAs, delivered %d bytes, DMA'd %d words -> %d words over-read"
              % (st['frame'], len(dmas), delivered, words, over))
        for lo, hi, f in ranges:
            tlo, thi = lo // 32, (hi - 1) // 32
            print("  frame %d: over-read bytes land at VRAM 0x%04X-0x%04X = tiles %d-%d" % (f, lo, hi - 1, tlo, thi))
            for name in ('A', 'B'):
                on, off, pals = cells_for(vram, planes[name], W, H, tlo, thi)
                if on or off:
                    print("     plane %s references them in %d cells (%d ON SCREEN), palettes %s"
                          % (name, on + off, on, dict(sorted(pals.items()))))
                    findings.append((f, tlo, thi, name, on))
        print()
    print("TOTAL over-read words this run: %d" % total_over)
    if not findings:
        print("No over-read tile is referenced by either name table at the end of the run.")
        print("Either no stream over-read, or the over-read tiles are never painted -")
        print("in which case the mechanism is invisible here, whatever the tape serves.")
    else:
        on = sum(x[4] for x in findings)
        print("Over-read tiles ARE painted: %d on-screen cells across %d (stream, plane) findings."
              % (on, len(findings)))
        print("On GPGX those cells show the stale mirror's bytes; on the Pocket, SDRAM past")
        print("the payload. PPM_DA_PAD makes the tape serve the mirror's bytes instead.")


if __name__ == '__main__':
    main()
