"""Read Paprium's animation table, in the word order the cartridge MCU sees.

ROM 0x0C0000 decompressed is the block the cartridge exposes as `ppm_anim_data`.
The MCU reads 32-bit words assembled as
`(b[o+2]<<24) | (b[o+3]<<16) | (b[o]<<8) | b[o+1]`, which is neither plain big-
nor little-endian - it falls out of the byte-swapped SDRAM the unpacker writes.

    word[objID + 1]         -> byte offset of that object's animation list
    word[objlist/4 + anim]  -> byte offset of that animation's frame list
    frame word  bit 31      = another frame follows
                bits 24..30 = flags, see below
                bits 0..23  = offset of that frame's sprite record
    the word AFTER the last frame is the LOOP TARGET; 0 means stop drawing, which
    is how an object despawns.

**The flag bits are a graphics streaming hint, not behaviour.** Their low nibble
is the number of graphics blocks this pose needs that the PREVIOUS pose did not -
measured on 24,764 of 24,893 pose boundaries across all 241 objects (99.48%), the
residue being counts >= 16 overflowing the nibble. So "weapons use 0/1/2 and
characters 3-7" is sprite size and nothing more. This cost a day; do not re-derive
it. See docs/PORT_PLAN.md and patches/README.md.

Set PAPRIUM_ANIM_BLOB (see paprium_data.py) or pass a path to load().
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paprium_data

ANIM_BASE = 0x0C0000


def load(path=None):
    """The whole table as MCU 32-bit words."""
    b = paprium_data.anim_blob() if path is None else open(path, 'rb').read()
    n = len(b) // 4
    return [(b[o + 2] << 24) | (b[o + 3] << 16) | (b[o] << 8) | b[o + 1]
            for o in range(0, n * 4, 4)]


def anim_offset(w, obj, anim):
    """Byte offset of one animation's frame list."""
    off = w[obj + 1]
    return w[(off >> 2) + anim]


def frames(w, obj, anim):
    """(frame words, loop target). Loop target 0 = the object stops drawing."""
    off = anim_offset(w, obj, anim)
    if not off or off == 0xFFFFFFFF:
        return [], None
    fr = []
    i = off >> 2
    while True:
        v = w[i]
        fr.append(v)
        if not (v & 0x80000000):
            break
        i += 1
        if len(fr) > 4096:          # malformed list; do not spin
            break
    return fr, w[i + 1] & 0xFFFFFF


def n_anims(w, obj):
    """How many animations an object has; the list ends on 0xFFFFFFFF."""
    off = w[obj + 1] >> 2
    c = 0
    while w[off + c] != 0xFFFFFFFF and c < 512:
        c += 1
    return c


def loop_index(w, obj, anim):
    """Where the loop target lands as a frame index, or None for a terminal end."""
    fr, loop = frames(w, obj, anim)
    if not fr or not loop:
        return None
    return (loop - anim_offset(w, obj, anim)) // 4


if __name__ == '__main__':
    w = load()
    obj = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0xDE
    print('object 0x%02X: %d animations' % (obj, n_anims(w, obj)))
    for a in range(n_anims(w, obj)):
        fr, loop = frames(w, obj, a)
        if not fr:
            continue
        print('   anim %02X: %3d frames  loop %s' % (
            a, len(fr),
            ('index %d' % loop_index(w, obj, a)) if loop else '0 = STOP DRAWING'))
