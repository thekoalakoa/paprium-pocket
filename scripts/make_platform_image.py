#!/usr/bin/env python3
"""Convert an image into an Analogue Pocket platform artwork .bin.

    python scripts/make_platform_image.py <image> <out.bin> [--blue]

THE FORMAT IS NOT OBVIOUS, and was worked out by decoding Analogue's own files
rather than from documentation:

    521 x 165 pixels, 16bpp RGB565 LITTLE-ENDIAN  ->  exactly 171,930 bytes
    stored COLUMN-MAJOR as a 165-wide x 521-tall buffer

That last part is the trap. Read the bytes as a 521x165 row-major image and you
get horizontal streaks; read them as 165x521 and rotate -90 and the artwork
appears. So writing is the inverse: rotate the finished 521x165 artwork +90 into
a 165x521 buffer, then emit it row-major.

Aspect: the frame is 3.158:1. A wider or narrower source is scaled to fill and
centre-cropped, which loses less than letterboxing into a 165px-tall strip.

--blue renders in Analogue's house style: every stock platform image is
monochrome blue on black, so a full-colour or greyscale image will stand out
from the rest of the list. Purely cosmetic; the plain conversion is faithful.
"""
import sys
from PIL import Image

W, H = 521, 165


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    blue = '--blue' in sys.argv[1:]
    if len(args) != 2:
        print(__doc__)
        return 2
    src, dst = args

    im = Image.open(src).convert('RGB')

    # scale to fill, then centre-crop to the frame
    sw, sh = im.size
    scale = max(W / sw, H / sh)
    im = im.resize((max(W, round(sw * scale)), max(H, round(sh * scale))), Image.LANCZOS)
    sw, sh = im.size
    im = im.crop(((sw - W) // 2, (sh - H) // 2, (sw - W) // 2 + W, (sh - H) // 2 + H))

    if blue:
        g = im.convert('L')
        im = Image.merge('RGB', (g.point(lambda v: 0),
                                 g.point(lambda v: v // 5),
                                 g))

    # rotate into the stored orientation and emit row-major RGB565 LE
    rot = im.rotate(90, expand=True)
    assert rot.size == (H, W), rot.size

    out = bytearray()
    for r, g, b in list(rot.getdata()):
        out += (((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)).to_bytes(2, 'little')

    assert len(out) == W * H * 2, len(out)
    open(dst, 'wb').write(out)
    print("%s -> %s  (%d bytes, %dx%d%s)"
          % (src, dst, len(out), W, H, ", blue" if blue else ""))
    return 0


if __name__ == '__main__':
    sys.exit(main())
