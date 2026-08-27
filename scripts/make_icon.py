#!/usr/bin/env python3
"""Generate the author icon (icon.bin) for all core packages.

pocket: no upstream counterpart. The Pocket icon format is a rotated 16-bit blob
no image tool writes directly.

The icon is a blocky pi symbol (the Praetorians' calling card from
"The Net", 1995). Analogue Pocket icon format: 36x36 pixels, 16 bits
per pixel with brightness in the upper 8 bits, stored rotated 90
degrees counter-clockwise (see analogue.co/developer/docs/packaging-a-core).
"""
import glob
import os
import sys

from PIL import Image, ImageDraw

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def draw_pi():
    img = Image.new("L", (36, 36), 0)
    d = ImageDraw.Draw(img)
    d.rectangle((4, 6, 31, 9), fill=255)     # top bar
    d.rectangle((9, 10, 13, 29), fill=255)   # left leg
    d.rectangle((22, 10, 26, 29), fill=255)  # right leg
    return img


def to_bin(img):
    rotated = img.transpose(Image.ROTATE_90)
    out = bytearray()
    for v in rotated.tobytes():
        out += bytes((v, 0))  # brightness in the upper 8 bits
    return bytes(out)


def main():
    data = to_bin(draw_pi())
    assert len(data) == 36 * 36 * 2
    cores = sorted(glob.glob(os.path.join(PROJECT_DIR, "pkg", "pocket", "Cores", "*", "")))
    if not cores:
        sys.exit("no core packages found under pkg/pocket/Cores/")
    for d in cores:
        path = os.path.join(d, "icon.bin")
        with open(path, "wb") as f:
            f.write(data)
        print(f"wrote {os.path.relpath(path, PROJECT_DIR)} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
