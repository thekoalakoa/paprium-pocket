#!/usr/bin/env python3
"""Lemongrwab Paprium banner → Analogue Pocket platform .bin.

    python scripts/make_platform_lemongrwab.py <banner.jpg|png> <out.bin>

Logo side is inverted (dark ink on white → bright on black). Character/cross
side keeps shading (paper floored to black, no invert). Then Analogue blue
house style + column-major RGB565 LE (see make_platform_image.py).

Banner by Lemongrwab (https://github.com/Lemongrwab), used with permission.
"""
import sys
from PIL import Image, ImageOps, ImageFilter

W, H = 521, 165


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = sys.argv[1:3]
    im = Image.open(src).convert("RGB")
    sw, sh = im.size
    scale = max(W / sw, H / sh)
    im = im.resize((max(W, round(sw * scale)), max(H, round(sh * scale))), Image.LANCZOS)
    sw, sh = im.size
    im = im.crop(((sw - W) // 2, (sh - H) // 2, (sw - W) // 2 + W, (sh - H) // 2 + H))
    g = im.convert("L")
    px = g.load()
    best = None
    for x in range(280, 480):
        vals = [px[x, y] for y in range(10, 90)]
        if max(vals) - min(vals) > 180 and max(vals) > 230 and min(vals) < 50:
            if sum(1 for v in vals if v > 220) >= 6:
                best = x
                break
    split = (best - 12) if best else 360

    logo = ImageOps.invert(g.crop((0, 0, split, H)))
    logo = logo.point(lambda v: 0 if v < 30 else v)
    logo = ImageOps.autocontrast(logo, cutoff=1)

    right = g.crop((split, 0, W, H)).point(lambda v: 0 if v >= 245 else v)
    nz = [v for v in right.getdata() if v > 0]
    if nz:
        lo, hi = min(nz), max(nz)
        span = max(1, hi - lo)
        right = right.point(
            lambda v: 0 if v == 0 else int(50 + ((v - lo) / span) * 205)
        )

    canvas = Image.new("L", (W, H), 0)
    canvas.paste(logo, (0, 0))
    canvas.paste(right, (split, 0))
    seam = canvas.crop((max(0, split - 4), 0, min(W, split + 4), H))
    canvas.paste(seam.filter(ImageFilter.GaussianBlur(radius=0.8)), (max(0, split - 4), 0))

    out = Image.merge(
        "RGB",
        (canvas.point(lambda v: 0), canvas.point(lambda v: v // 5), canvas),
    )
    rot = out.rotate(90, expand=True)
    assert rot.size == (H, W)
    buf = bytearray()
    for r, gv, b in rot.getdata():
        buf += (((r >> 3) << 11) | ((gv >> 2) << 5) | (b >> 3)).to_bytes(2, "little")
    assert len(buf) == W * H * 2
    open(dst, "wb").write(buf)
    print("%s -> %s (%d bytes, split=%d)" % (src, dst, len(buf), split))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
