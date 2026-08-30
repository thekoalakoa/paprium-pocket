#!/usr/bin/env python3
"""Compose the Paprium platform artwork from two sources.

    python scripts/make_platform_composite.py <character.png> <keyart.jpg> <out.bin>

WHY A COMPOSITE: the frame is 521x165, roughly 3.16:1. The character art is
768x768. Scaling him to fill would keep about 32% of his height - a horizontal
band through his chest - and letterboxing him leaves two thirds of a very wide
frame empty. Pairing him with the logo uses the width the frame actually has.

Both halves are mapped to Analogue's monochrome blue house style, but from
DIFFERENT channels, because the sources differ:

  character  white ground, so INVERT luminance - otherwise the background is the
             brightest thing on screen, which is backwards from every stock image
  logo       already bright on dark, so use HSV VALUE - the magenta has high
             brightness but low luminance and a plain greyscale leaves it dim

Both are floored to true black so neither crop shows as a rectangle against the
canvas. See docs/PORT_PLAN.md for the .bin format (column-major, RGB565 LE).
"""
import sys
from PIL import Image, ImageOps

W, H = 521, 165


def floor(g, t):
    return g.point(lambda v: 0 if v < t else v)


def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    char_path, key_path, out_path = sys.argv[1:4]

    ch = Image.open(char_path).convert('RGB').crop((90, 40, 640, 700))
    cg = floor(ImageOps.autocontrast(ImageOps.invert(ch.convert('L')), cutoff=1), 45)
    k = (H - 8) / cg.size[1]
    cg = cg.resize((round(cg.size[0] * k), round(cg.size[1] * k)), Image.LANCZOS)

    lg = Image.open(key_path).convert('RGB').crop((18, 8, 965, 268))
    lv = floor(ImageOps.autocontrast(lg.convert('HSV').getchannel('V'), cutoff=1), 70)
    k2 = min((W - cg.size[0] - 34) / lv.size[0], 128 / lv.size[1])
    lv = lv.resize((round(lv.size[0] * k2), round(lv.size[1] * k2)), Image.LANCZOS)

    canvas = Image.new('L', (W, H), 0)
    canvas.paste(cg, (10, (H - cg.size[1]) // 2))
    canvas.paste(lv, (10 + cg.size[0] + 14, (H - lv.size[1]) // 2))
    out = Image.merge('RGB', (canvas.point(lambda v: 0),
                              canvas.point(lambda v: v // 5), canvas))

    rot = out.rotate(90, expand=True)          # stored column-major
    buf = bytearray()
    for r, g, b in list(rot.getdata()):
        buf += (((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)).to_bytes(2, 'little')
    assert len(buf) == W * H * 2, len(buf)
    open(out_path, 'wb').write(buf)
    print("%s (%d bytes, %dx%d)" % (out_path, len(buf), W, H))
    return 0


if __name__ == '__main__':
    sys.exit(main())
