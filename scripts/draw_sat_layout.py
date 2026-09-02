"""Draw the captured sprite list as a labelled screen layout, so a human who has
seen the scene can say which box is which.

    python scripts/draw_sat_layout.py <Paprium.sav> <out.png>

The snapshot holds the sprite ATTRIBUTE TABLE - position, size, tile index,
priority, palette - but not the tile patterns, so this cannot draw the artwork.
What it can do is put every sprite exactly where the VDP would, at the right size,
with its entry number on it. The arrangement of a boss, a player and a HUD is
usually recognisable from shape and position alone.

Colour coding is the thing that matters for the open question:

    RED    priority 0   drawn BEHIND any high-priority background tile
    BLUE   priority 1   drawn in front of everything

Only sprites reachable through the link chain are drawn, because those are the
only ones the VDP renders. Stale entries are listed separately.
"""
import struct
import sys

from PIL import Image, ImageDraw

SCREEN_W, SCREEN_H = 320, 224
SCALE = 3


def load(path):
    d = open(path, 'rb').read()
    return d[0x900:0x1000]


def swapped(b):
    s = bytearray(len(b))
    s[0::2] = b[1::2]
    s[1::2] = b[0::2]
    return bytes(s)


def entries(b):
    out = []
    for i in range(80):
        e = b[0x18 + i * 8: 0x18 + i * 8 + 8]
        out.append({
            'n': i,
            'y': (struct.unpack('>H', e[0:2])[0] & 0x3FF) - 128,
            'w': (((e[2] >> 2) & 3) + 1) * 8,
            'h': ((e[2] & 3) + 1) * 8,
            'link': e[3],
            'attr': struct.unpack('>H', e[4:6])[0],
            'x': (struct.unpack('>H', e[6:8])[0] & 0x1FF) - 128,
        })
    return out


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    b = load(sys.argv[1])
    hdr = swapped(b)
    if hdr[0x10:0x14] != b'PSAT':
        raise SystemExit("no capture in that save")

    ents = entries(b)
    chain, i, seen = [], 0, set()
    while i not in seen and len(chain) < 80:
        seen.add(i)
        chain.append(ents[i])
        if ents[i]['link'] == 0:
            break
        i = ents[i]['link']

    img = Image.new('RGB', (SCREEN_W * SCALE, SCREEN_H * SCALE), (18, 18, 24))
    d = ImageDraw.Draw(img)

    # faint screen grid, 32 px, to help place things by eye
    for gx in range(0, SCREEN_W, 32):
        d.line([(gx * SCALE, 0), (gx * SCALE, SCREEN_H * SCALE)], fill=(38, 38, 48))
    for gy in range(0, SCREEN_H, 32):
        d.line([(0, gy * SCALE), (SCREEN_W * SCALE, gy * SCALE)], fill=(38, 38, 48))

    drawn = 0
    for e in chain:
        if not (-64 < e['x'] < SCREEN_W and -64 < e['y'] < SCREEN_H):
            continue
        drawn += 1
        # Colour cycles per box so neighbouring sprites of the same object stay
        # tellable apart by eye. Priority is printed in the table instead - in a
        # capture with the priority probe off, everything we compose is pri 0 and
        # colouring by it says nothing.
        PALETTE = [(255, 120, 120), (120, 200, 255), (150, 255, 150),
                   (255, 220, 120), (220, 150, 255), (140, 255, 230)]
        col = PALETTE[e['n'] % len(PALETTE)]
        x0, y0 = e['x'] * SCALE, e['y'] * SCALE
        x1, y1 = (e['x'] + e['w']) * SCALE - 1, (e['y'] + e['h']) * SCALE - 1
        d.rectangle([x0, y0, x1, y1], outline=col, width=2)
        d.text((x0 + 3, y0 + 2), str(e['n']), fill=col)

    # Orphans, drawn dashed in yellow. Added 2026-09-02: the subway capture had a
    # whole character in entries 14-19 that this picture did not show, because it
    # only ever drew the chain and the chain was what had lost them. A sprite the
    # game wrote and the VDP never drew has to be visible here or the picture is
    # quietly lying about the frame.
    count = struct.unpack('>H', hdr[0x14:0x16])[0]
    reached = set(e['n'] for e in chain)
    orphans = [e for e in ents[:min(max(count + 4, 1), 80)]
               if e['n'] not in reached and -64 < e['x'] < SCREEN_W and -64 < e['y'] < SCREEN_H]
    for e in orphans:
        x0, y0 = e['x'] * SCALE, e['y'] * SCALE
        x1, y1 = (e['x'] + e['w']) * SCALE - 1, (e['y'] + e['h']) * SCALE - 1
        for t in range(x0, x1, 12):
            d.line([(t, y0), (min(t + 6, x1), y0)], fill=(255, 255, 80))
            d.line([(t, y1), (min(t + 6, x1), y1)], fill=(255, 255, 80))
        for t in range(y0, y1, 12):
            d.line([(x0, t), (x0, min(t + 6, y1))], fill=(255, 255, 80))
            d.line([(x1, t), (x1, min(t + 6, y1))], fill=(255, 255, 80))
        d.text((x0 + 3, y0 + 2), "%d ORPHAN" % e['n'], fill=(255, 255, 80))

    legend = [
        "sprite layout from the hardware capture - %d of %d chain entries on screen" % (drawn, len(chain)),
        "YELLOW DASHED = in the table, on screen, NOT in the link chain -> never drawn (%d)" % len(orphans),
        "BLUE = priority 1 (in front)     RED = priority 0 (behind high-priority background)",
        "number = SAT entry index",
    ]
    for k, line in enumerate(legend):
        d.text((6, 6 + k * 12), line, fill=(200, 200, 210))

    img.save(sys.argv[2])
    print("wrote %s" % sys.argv[2])
    print()
    print("Sprites drawn, so you can name them:")
    print("  entry    X    Y    size   pri  pal   tile")
    for e in chain:
        if not (-64 < e['x'] < SCREEN_W and -64 < e['y'] < SCREEN_H):
            continue
        print("    %3d  %4d %4d  %2dx%-2d   %d    %d   0x%03X"
              % (e['n'], e['x'], e['y'], e['w'], e['h'],
                 (e['attr'] >> 15) & 1, (e['attr'] >> 13) & 3, e['attr'] & 0x7FF))


if __name__ == '__main__':
    main()
