#!/usr/bin/env python3
"""Convert an image into an Analogue Pocket platform artwork .bin.

    python scripts/make_platform_image.py <image> <out.bin>
    python scripts/make_platform_image.py --decode <in.bin> <out.png>

THE FORMAT IS NOT OBVIOUS, and was worked out by decoding Analogue's own files
rather than from documentation:

    521 x 165 pixels, MONOCHROME: one 8-bit grey level per pixel in the LOW byte
    of a 16-bit slot, high byte always zero  ->  exactly 171,930 bytes
    stored COLUMN-MAJOR as a 165-wide x 521-tall buffer

That last part is one trap. Read the bytes as a 521x165 row-major image and you
get horizontal streaks; read them as 165x521 and rotate and the artwork appears.

**The colour depth is the other trap, and this script had it wrong until
2026-09-11.** It is not RGB565. Measured across all 376 stock platform images on
a Pocket card: EVERY odd byte is zero in EVERY one of them, and a real file has
exactly 256 distinct 16-bit words, all with a zero high byte. The Pocket reads
the low byte as a grey level and the images are monochrome by construction.

Writing RGB565 here is why the artwork needed so many attempts. --blue used to
tint the greyscale as (0, g/5, g) before packing, and packing THAT as RGB565
happens to leave a rough brightness ramp in the low byte - the only byte that is
read - so "blue" appeared to work while a plain conversion produced garbage. The
tint was never visible on the device: the format cannot carry a hue.

Aspect: the frame is 3.158:1. A wider or narrower source is scaled to fill and
centre-cropped, which loses less than letterboxing into a 165px-tall strip.

--blue is accepted and ignored, and kept only so old invocations still run. The
stock images look blue on the Pocket because the DEVICE tints a monochrome image,
not because the file carries a colour. --invert and --value remain useful: they
choose how the source's tones map onto that single grey channel.
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
    raw    = '--raw'    in sys.argv[1:]     # skip autocontrast, for round-tripping
    crop = next((a.split('=', 1)[1] for a in sys.argv[1:]
                 if a.startswith('--crop=')), None)
    if len(args) != 2:
        print(__doc__)
        return 2
    src, dst = args

    if '--decode' in sys.argv[1:]:
        b = open(src, 'rb').read()
        if len(b) != W * H * 2:
            raise SystemExit('%s is %d bytes, expected %d' % (src, len(b), W * H * 2))
        im = Image.new('L', (W, H))
        px = im.load()
        for x in range(W):
            for y in range(H):
                px[x, y] = b[((W - 1 - x) * H + y) * 2]
        im.save(dst)
        print('%s -> %s  (%dx%d, grey)' % (src, dst, W, H))
        return 0

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

    # The file is monochrome, so the tone mapping is the only choice that
    # survives. --value maps HSV brightness rather than luminance: a saturated
    # hue has high brightness but LOW luminance, so a straight greyscale
    # conversion renders it dim next to near-white pixel art.
    g = im.convert('HSV').getchannel('V') if value else im.convert('L')
    if invert:
        # Analogue's stock images are BRIGHT art on a BLACK ground. A source with
        # a light background and dark subject comes out backwards - the artwork
        # reads as a hole - so invert puts the subject bright and the ground
        # black, as the house style has it.
        g = ImageOps.invert(g)
    if not raw:
        g = ImageOps.autocontrast(g, cutoff=1)

    # Emit column-major with the grey level in the low byte. Written as explicit
    # indexing rather than a PIL rotate so it is visibly the exact inverse of
    # decode() below, which was checked against real artwork.
    out = bytearray(W * H * 2)
    px = g.load()
    for x in range(W):
        for y in range(H):
            out[((W - 1 - x) * H + y) * 2] = px[x, y]

    assert len(out) == W * H * 2, len(out)
    open(dst, 'wb').write(out)
    print("%s -> %s  (%d bytes, %dx%d, monochrome)" % (src, dst, len(out), W, H))
    return 0


if __name__ == '__main__':
    sys.exit(main())
