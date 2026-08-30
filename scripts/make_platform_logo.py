#!/usr/bin/env python3
"""Paprium platform artwork: the logo alone, colour-keyed off its background.

    python scripts/make_platform_logo.py <keyart.jpg> <out.bin>

The logo in the key art is a single flat magenta, #FF006A, which keys out exactly
- so the glyphs and the cross can be lifted with nothing else attached: no sky, no
cityscape, no character, and no crop rectangle showing against the canvas.

Two things this gets right that a crop cannot:

  * The search is restricted to the logo's own region FIRST. The character sprites
    contain the same magenta, so keying the whole image drags them in - the naive
    bounding box comes out 1188x656 instead of 941x264.
  * The result is a MASK, so the background is true black by construction rather
    than by thresholding something that was nearly black.

Rendered bright on black, which is Analogue's house style and holds up against the
menu's white background - the earlier light version washed out there.

See docs/PORT_PLAN.md for the .bin format (521x165, RGB565 LE, column-major).
"""
import sys
from PIL import Image

W, H = 521, 165
KEY = lambda r, g, b: r > 170 and g < 90 and 40 < b < 180      # the flat #FF006A
REGION = (0, 0, 1010, 290)     # the logo's own area; the characters share its hue


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = sys.argv[1:3]

    im = Image.open(src).convert('RGB').crop(REGION)
    px = im.load()
    mask = Image.new('L', im.size, 0)
    mp = mask.load()
    for y in range(im.size[1]):
        for x in range(im.size[0]):
            if KEY(*px[x, y]):
                mp[x, y] = 255
    box = mask.getbbox()
    if not box:
        print("error: no logo pixels matched the colour key", file=sys.stderr)
        return 1
    logo = mask.crop(box)

    k = min(W * 0.94 / logo.size[0], H * 0.86 / logo.size[1])
    logo = logo.resize((round(logo.size[0] * k), round(logo.size[1] * k)), Image.LANCZOS)

    canvas = Image.new('L', (W, H), 0)
    canvas.paste(logo, ((W - logo.size[0]) // 2, (H - logo.size[1]) // 2))
    out = Image.merge('RGB', (canvas.point(lambda v: 0),
                              canvas.point(lambda v: v // 5), canvas))

    rot = out.rotate(90, expand=True)          # stored column-major
    buf = bytearray()
    for r, g, b in list(rot.getdata()):
        buf += (((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)).to_bytes(2, 'little')
    assert len(buf) == W * H * 2, len(buf)
    open(dst, 'wb').write(buf)
    print("%s (%d bytes, logo %dx%d from bbox %s)"
          % (dst, len(buf), logo.size[0], logo.size[1], box))
    return 0


if __name__ == '__main__':
    sys.exit(main())
