#!/usr/bin/env python3
"""Paprium core icon: the logo's cross, colour-keyed from the key art.

    python scripts/make_core_icon.py <keyart.jpg> <out.bin>

FORMAT, which differs from the platform artwork: 36x36, RGB565 little-endian,
and ROW-MAJOR - not the column-major layout platform images use. Verified by
decoding the shipped icon both ways; only row-major renders upright.

The cross is lifted the same way as the wordmark: the logo is a flat #FF006A, so
a colour key isolates it exactly, and the cross is then cut at the last gap of
empty columns - the space between the M and the cross. That avoids the previous
icon's artefact, a spike out to the right where a hand crop had caught part of the
adjacent letter.

Colour matches the shipped icon exactly: 0x00FF, rgb(0,28,255) on black.
"""
import struct, sys
from PIL import Image

N = 36
BLUE = 0x00FF          # rgb(0,28,255), the shipped icon's exact colour
KEY = lambda r, g, b: r > 170 and g < 90 and 40 < b < 180
REGION = (0, 0, 1010, 290)


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
    m = mask.crop(mask.getbbox())
    mw, mh = m.size
    mpx = m.load()

    cols = [any(mpx[x, y] for y in range(mh)) for x in range(mw)]
    cut = mw
    while cut > 0 and cols[cut - 1]:
        cut -= 1                      # walk back over the cross itself
    while cut > 0 and not cols[cut - 1]:
        cut -= 1                      # then over the gap before it
    cross = m.crop((cut, 0, mw, mh))
    cross = cross.crop(cross.getbbox())

    k = min(N * 0.92 / cross.size[0], N * 0.92 / cross.size[1])
    cross = cross.resize((max(1, round(cross.size[0] * k)),
                          max(1, round(cross.size[1] * k))), Image.LANCZOS)
    canvas = Image.new('L', (N, N), 0)
    canvas.paste(cross, ((N - cross.size[0]) // 2, (N - cross.size[1]) // 2))

    buf = bytearray()
    for v in list(canvas.getdata()):
        buf += struct.pack('<H', BLUE if v >= 128 else 0)
    assert len(buf) == N * N * 2, len(buf)
    open(dst, 'wb').write(buf)
    print("%s (%d bytes, cross %dx%d)" % (dst, len(buf), cross.size[0], cross.size[1]))
    return 0


if __name__ == '__main__':
    sys.exit(main())
