#!/usr/bin/env python3
"""Generate icon.bin for the Paprium core: the cross from the Paprium logo.

The Pocket icon format is 36x36 pixels, 16 bits per pixel with brightness in the
upper 8 bits, stored rotated 90 degrees counter-clockwise. Greyscale and tiny -
cover art does not survive it, so this draws the logo's cross as a silhouette,
which is what reads at this size.

The shape is the dagger-style cross that follows the wordmark: a long vertical
stroke tapering to a point at the bottom, crossed high by a shorter horizontal
bar. Kept chunky because a 36x36 greyscale icon has no room for fine strokes.

Usage: make_paprium_icon.py [output.bin]
"""
import os
import sys

from PIL import Image, ImageDraw

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_OUT = os.path.join(
    PROJECT_DIR, "pkg", "pocket", "Cores", "Koala_Koa.Paprium", "icon.bin"
)

SIZE = 36


def draw_cross():
    img = Image.new("L", (SIZE, SIZE), 0)
    d = ImageDraw.Draw(img)

    # Vertical stroke: full height less a margin, 6 px wide, centred
    d.rectangle((15, 3, 20, 26), fill=255)

    # Tapered point below the stroke - three rows narrowing to a tip
    d.rectangle((16, 27, 19, 29), fill=255)
    d.rectangle((17, 30, 18, 32), fill=255)

    # Crossbar set high, as on the logo, 5 px tall
    d.rectangle((7, 10, 28, 14), fill=255)

    return img


def to_bin(img):
    rotated = img.transpose(Image.ROTATE_90)
    out = bytearray()
    for v in rotated.tobytes():
        out += bytes((v, 0))  # brightness in the upper 8 bits
    return bytes(out)


def preview(img):
    """ASCII preview so the shape can be judged without a Pocket to hand."""
    px = img.load()
    return "\n".join(
        "".join("#" if px[x, y] else "." for x in range(SIZE)) for y in range(SIZE)
    )


def main():
    img = draw_cross()
    data = to_bin(img)
    assert len(data) == SIZE * SIZE * 2, len(data)

    out = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT
    with open(out, "wb") as f:
        f.write(data)

    print(preview(img))
    print(f"\nwrote {out} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
