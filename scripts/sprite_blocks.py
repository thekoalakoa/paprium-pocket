"""Fingerprint each animation frame by the graphics blocks it draws.

This is what makes the reference emulator falsifiable. Genesis Plus GX logs one
winlog record (kind 15) per drawn sprite piece carrying its block number, so
matching that list against the blocks a frame is supposed to draw tells you WHICH
animation was really rendered - independently of what the game's RAM said the
animation was. That is how GPGX was caught drawing a character's idle art for 279
frames of a 295-frame walk-in while the object table still read `anim = 9`.

Sprite record, natural blob order:

    header  +0 count   +1 flags
    record  +0 posX +1 posY +2 size +3 flipPosX +4..5 blockNum (BE16) +6 attrs +7 ofs

stride 8. The emulator indexes the same bytes as `blob[x ^ 1]` because it reads
them out of the byte-swapped SDRAM array; reading the blob naturally, as here,
gives the same values.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_data
import paprium_data


def blocks(blob, data_offset):
    """(piece count, block numbers) for one frame's sprite record, in draw order."""
    d = data_offset
    count = blob[d]
    out = []
    p = d + 2
    for _ in range(count):
        out.append((blob[p + 4] << 8) | blob[p + 5])
        p += 8
    return count, tuple(out)


def frame_fps(w, blob, obj, anim):
    """[(frame index, piece count, block tuple)] for one animation."""
    fr, _ = anim_data.frames(w, obj, anim)
    out = []
    for i, v in enumerate(fr):
        d = v & 0xFFFFFF
        if not d:
            out.append((i, 0, ()))
            continue
        c, b = blocks(blob, d)
        out.append((i, c, b))
    return out


def fingerprints(w, blob, obj):
    """{block tuple -> set of animations that draw it} for one object.

    A block tuple can belong to more than one animation when they share art, so
    treat a single-element result as an identification and a larger one as a
    constraint.
    """
    m = {}
    for a in range(anim_data.n_anims(w, obj)):
        for _i, _c, b in frame_fps(w, blob, obj, a):
            if b:
                m.setdefault(b, set()).add(a)
    return m


if __name__ == '__main__':
    w = anim_data.load()
    blob = paprium_data.anim_blob()
    obj = int(sys.argv[1], 0) if len(sys.argv) > 1 else 0xDE
    anim = int(sys.argv[2], 0) if len(sys.argv) > 2 else 8
    print('object 0x%02X anim 0x%02X' % (obj, anim))
    seen = []
    for i, c, b in frame_fps(w, blob, obj, anim):
        if not seen or seen[-1][1] != b:
            seen.append((i, b, c))
    for i, b, c in seen:
        print('   frame %3d  %d pieces  blocks %s' % (i, c, list(b)[:12]))
