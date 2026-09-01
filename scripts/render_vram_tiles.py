"""Render Mega Drive tile patterns and plane maps out of a Genesis Plus GX savestate.

    python scripts/render_vram_tiles.py <state> --out <dir>
    python scripts/render_vram_tiles.py <state> --out <dir> --range 800-863

Why this exists: counting nametable references tells you a pattern range is being
drawn, not what it draws. A cell is a pointer - repeating one brick 200 times is
200 references and a handful of tiles. To find out whether tiles 800-863 really
are "the cell-room floor", you have to look at them.

Everything comes from the savestate, so there is no ROM decode involved and no
Pocket build. Tile indices are VRAM slots filled at runtime by the streaming
allocator, so the same index holds different pixels in different scenes - which is
exactly why this renders per-scene rather than from the ROM.

Outputs, per state:

    tiles-<range>.png    an atlas of the pattern range, 16 tiles per row
    planeA.png           plane A as the VDP would draw it, from its nametable
    planeB.png           plane B likewise
    planeA-marked.png    the same, with cells whose tile index is in the range
                         tinted red - this is the one that answers "is it floor?"
    report.txt           per-tile reference counts and which palettes use them

Formats:
    pattern   32 bytes per tile, 8x8 4bpp, high nibble = left pixel
    CRAM      64 entries, 0000 BBB0 GGG0 RRR0, 3 bits per channel
    nametable cell  bit 15 priority, 14-13 palette, 12 vflip, 11 hflip, 10-0 tile
"""
import os
import struct
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_gpgx_state import (load, unswap, VERSION, WORK_RAM, ZRAM, ZSTATE,
                              ZBANK, IO_REG, SAT_SZ, VRAM_SZ, CRAM_SZ, VSRAM_SZ)

PLANE_SIZES = {0: 32, 1: 64, 2: 64, 3: 128}


def read_state(path):
    blob, _ = load(path)
    base = blob.index(VERSION) + 16
    v = base + WORK_RAM + ZRAM + ZSTATE + ZBANK + IO_REG
    vram = unswap(blob[v + SAT_SZ: v + SAT_SZ + VRAM_SZ])
    cram = blob[v + SAT_SZ + VRAM_SZ: v + SAT_SZ + VRAM_SZ + CRAM_SZ]
    reg = blob[v + SAT_SZ + VRAM_SZ + CRAM_SZ + VSRAM_SZ:][:0x20]
    return vram, cram, reg


def palettes(cram):
    """4 palettes x 16 colours, as RGB tuples. Index 0 is transparent in use.

    GPGX does NOT store the raw bus value. vdp_ctrl.c packs it on write:

        data = ((data & 0xE00) >> 3) | ((data & 0x0E0) >> 2) | ((data & 0x00E) >> 1)

    which is 9-bit BBBGGGRRR, stored native-endian. Decoding it as the bus format
    0000BBB0GGG0RRR0 yields a monochrome blue image - which is exactly what the
    first version of this script produced, and it looked enough like broken data
    to nearly get the savestates blamed for it.
    """
    out = []
    for p in range(4):
        pal = []
        for i in range(16):
            v = struct.unpack_from('<H', cram, (p * 16 + i) * 2)[0]
            r = (v >> 0) & 7
            g = (v >> 3) & 7
            b = (v >> 6) & 7
            pal.append((r * 36, g * 36, b * 36))
        out.append(pal)
    return out


def tile_pixels(vram, idx):
    """8x8 palette indices for one tile."""
    o = idx * 32
    rows = []
    for y in range(8):
        row = []
        for x in range(4):
            b = vram[o + y * 4 + x]
            row.append(b >> 4)
            row.append(b & 15)
        rows.append(row)
    return rows


def draw_atlas(vram, pals, first, last, pal_idx, scale=3):
    n = last - first + 1
    cols = 16
    rows = (n + cols - 1) // cols
    img = Image.new('RGB', (cols * 8, rows * 8), (24, 24, 32))
    px = img.load()
    for k in range(n):
        tx, ty = (k % cols) * 8, (k // cols) * 8
        for y, line in enumerate(tile_pixels(vram, first + k)):
            for x, c in enumerate(line):
                px[tx + x, ty + y] = pals[pal_idx][c]
    return img.resize((img.width * scale, img.height * scale), Image.NEAREST)


def draw_plane(vram, pals, base, w, h, mark=None):
    """Render a nametable exactly as the VDP indexes it."""
    img = Image.new('RGB', (w * 8, h * 8), (0, 0, 0))
    px = img.load()
    for cy in range(h):
        for cx in range(w):
            cell = struct.unpack_from('>H', vram, base + (cy * w + cx) * 2)[0]
            tile = cell & 0x7FF
            pal = (cell >> 13) & 3
            hflip = (cell >> 11) & 1
            vflip = (cell >> 12) & 1
            hit = mark and mark[0] <= tile <= mark[1]
            rows = tile_pixels(vram, tile)
            for y in range(8):
                sy = 7 - y if vflip else y
                for x in range(8):
                    sx = 7 - x if hflip else x
                    c = rows[sy][sx]
                    r, g, b = pals[pal][c]
                    if hit:
                        r = min(255, r // 2 + 128)
                        g = g // 2
                        b = b // 2
                    px[cx * 8 + x, cy * 8 + y] = (r, g, b)
    return img


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if not args:
        raise SystemExit(__doc__)
    state = args[0]

    outdir = 'vram-render'
    if '--out' in sys.argv:
        outdir = sys.argv[sys.argv.index('--out') + 1]
    rng = (800, 863)
    if '--range' in sys.argv:
        a, b = sys.argv[sys.argv.index('--range') + 1].split('-')
        rng = (int(a), int(b))
    os.makedirs(outdir, exist_ok=True)

    vram, cram, reg = read_state(state)
    pals = palettes(cram)

    planeA = (reg[2] & 0x38) << 10
    planeB = (reg[4] & 0x07) << 13
    w, h = PLANE_SIZES[reg[16] & 3], PLANE_SIZES[(reg[16] >> 4) & 3]

    print("state    : %s" % state)
    print("plane A  : 0x%04X   plane B: 0x%04X   %dx%d cells" % (planeA, planeB, w, h))
    print("range    : tiles %d-%d  (VRAM 0x%04X-0x%04X)" % (rng[0], rng[1], rng[0]*32, rng[1]*32+31))
    print()

    # Which palettes actually get used with tiles in the range, and how often.
    refs = {}
    for base, name in ((planeA, 'A'), (planeB, 'B')):
        for i in range(w * h):
            cell = struct.unpack_from('>H', vram, base + i * 2)[0]
            t = cell & 0x7FF
            if rng[0] <= t <= rng[1]:
                d = refs.setdefault(t, {'A': 0, 'B': 0, 'pals': set()})
                d[name] += 1
                d['pals'].add((cell >> 13) & 3)

    lines = ["tile   VRAM      refs A   refs B   palettes",
             "----------------------------------------------"]
    for t in sorted(refs):
        d = refs[t]
        lines.append("%4d   0x%04X    %5d    %5d   %s"
                     % (t, t * 32, d['A'], d['B'], sorted(d['pals'])))
    total = sum(d['A'] + d['B'] for d in refs.values())
    lines.append("")
    lines.append("%d distinct tiles referenced, %d cells total" % (len(refs), total))
    lines.append("A cell is a pointer: many cells, few unique tiles, is what a")
    lines.append("repeated floor or wall stamp looks like.")
    report = "\n".join(lines)
    print(report)
    open(os.path.join(outdir, 'report.txt'), 'w').write(report + "\n")

    pal_used = sorted({p for d in refs.values() for p in d['pals']}) or [0]
    draw_atlas(vram, pals, rng[0], rng[1], pal_used[0]).save(
        os.path.join(outdir, 'tiles-%d-%d.png' % rng))
    draw_plane(vram, pals, planeA, w, h).save(os.path.join(outdir, 'planeA.png'))
    draw_plane(vram, pals, planeB, w, h).save(os.path.join(outdir, 'planeB.png'))
    draw_plane(vram, pals, planeA, w, h, mark=rng).save(
        os.path.join(outdir, 'planeA-marked.png'))
    draw_plane(vram, pals, planeB, w, h, mark=rng).save(
        os.path.join(outdir, 'planeB-marked.png'))
    print()
    print("wrote atlas, planeA/B and marked versions to %s/" % outdir)


if __name__ == '__main__':
    main()
