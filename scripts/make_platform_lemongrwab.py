#!/usr/bin/env python3
"""Lemongrwab Paprium banner → Analogue Pocket platform .bin (original tones).

    python scripts/make_platform_lemongrwab.py <banner.jpg|png> <out.bin>

The Pocket's platform list displays greyscale even when the file is Analogue
"house blue", so this keeps Lemongrwab's original dark-on-light tones.

Letterboxes onto a white 521×165 canvas (scale-to-fit) so the full logo and
character survive — scale-to-fill centre-crop clips the WM mark and the sprite.

Format: RGB565 LE, column-major (see make_platform_image.py).

Banner by Lemongrwab (https://github.com/Lemongrwab), used with permission.
"""
import sys
from PIL import Image

W, H = 521, 165


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = sys.argv[1:3]
    im = Image.open(src).convert("RGB")
    sw, sh = im.size
    k = min(W / sw, H / sh)
    im = im.resize((max(1, round(sw * k)), max(1, round(sh * k))), Image.LANCZOS)
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    canvas.paste(im, ((W - im.size[0]) // 2, (H - im.size[1]) // 2))

    rot = canvas.rotate(90, expand=True)
    assert rot.size == (H, W)
    buf = bytearray()
    for r, g, b in rot.getdata():
        buf += (((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)).to_bytes(2, "little")
    assert len(buf) == W * H * 2
    open(dst, "wb").write(buf)
    print("%s -> %s (%d bytes, original tones, fit-white)" % (src, dst, len(buf)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
