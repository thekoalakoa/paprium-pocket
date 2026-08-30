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
from PIL import Image, ImageOps

W, H = 521, 165


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    blue = '--blue' in sys.argv[1:]
    invert = '--invert' in sys.argv[1:]
    value  = '--value'  in sys.argv[1:]
    fit    = '--fit'    in sys.argv[1:]
    crop = next((a.split('=', 1)[1] for a in sys.argv[1:]
                 if a.startswith('--crop=')), None)
    if len(args) != 2:
        print(__doc__)
        return 2
    src, dst = args

    im = Image.open(src).convert('RGB')

    if crop:
        im = im.crop(tuple(int(v) for v in crop.split(',')))

    # --fit letterboxes instead of cropping: scale to FIT inside the frame and
    # centre on black. Needed for a source whose aspect is nowhere near 3.158:1 -
    # a 768x768 character scaled to fill would keep only ~32% of his height, i.e.
    # a horizontal band through his chest.
    if fit:
        sw, sh = im.size
        k = min(W / sw, H / sh)
        im = im.resize((max(1, round(sw * k)), max(1, round(sh * k))), Image.LANCZOS)
        canvas = Image.new('RGB', (W, H), (255, 255, 255) if invert else (0, 0, 0))
        canvas.paste(im, ((W - im.size[0]) // 2, (H - im.size[1]) // 2))
        im = canvas
    else:
        # scale to fill, then centre-crop to the frame
        sw, sh = im.size
        scale = max(W / sw, H / sh)
        im = im.resize((max(W, round(sw * scale)), max(H, round(sh * scale))), Image.LANCZOS)
        sw, sh = im.size
        im = im.crop(((sw - W) // 2, (sh - H) // 2, (sw - W) // 2 + W, (sh - H) // 2 + H))

    if blue:
        # --value maps HSV brightness rather than luminance. A saturated hue like
        # Paprium's magenta logo has high brightness but LOW luminance, so a normal
        # greyscale conversion renders it dim next to near-white pixel art. Using V
        # keeps saturated artwork as prominent as it looks in the original.
        g = im.convert('HSV').getchannel('V') if value else im.convert('L')
        if invert:
            # Analogue's stock images are BRIGHT art on a BLACK ground. A source
            # with a light background and dark subject (dark logo on a pale sky)
            # comes out backwards - the artwork reads as a hole. Inverting first
            # puts the subject bright and the ground black, as the house style has
            # it. Also lifts contrast, since a 521px-wide downscale of a detailed
            # image goes muddy otherwise.
            g = ImageOps.invert(g)
        # Normalise either way. A saturated colour (Paprium's magenta logo) carries
        # less luminance than it appears to, so a straight map leaves it dim against
        # a dark ground; autocontrast pulls the subject back up.
        g = ImageOps.autocontrast(g, cutoff=1)
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
