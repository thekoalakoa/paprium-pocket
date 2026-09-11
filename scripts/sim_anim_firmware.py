"""Replay this firmware's ppm_obj_render against recorded object-table traces.

    python scripts/sim_anim_firmware.py <winlog.bin> [more.bin ...]
    WINDOW=2 python scripts/sim_anim_firmware.py <winlog.bin>

**Why this exists, and why the emulator is not a substitute.** Genesis Plus GX
decides what to do at the end of an animation on the call that DRAWS its last
frame. This firmware keeps the frame just drawn and decides on the NEXT call. A
dropped weapon's queued follow-up is armed in the one-frame gap between those two
points, so the two implementations give opposite answers on exactly the case that
matters. Running a rule in the emulator to "confirm" it would have been
meaningless either way.

What makes the replay honest is that the game's whole side of the interface -
`anim`, `nextAnim`, `reset`, per object per frame - is recorded in the winlog, and
the animation data is in the ROM. That is everything ppm_obj_render reads. Replay
is exact up to the first chain; after that this firmware writes `anim` back and
the game would diverge from the recording, so each object episode is reported only
to its first chain.

Used to settle the 0.2.4 dropped-weapon fix: 5,558 object episodes across four
captures, 11 of 11 weapon chains fired and 0 chains out of the character walk-in,
identically for every window from 0 to 4. See patches/README.md.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_data
import winlog_objects

WINDOW = int(os.environ.get('WINDOW', '1'))     # PPM_CHAIN_FRESH_WINDOW
WEAPONS = {0xDC, 0xDD, 0xDE, 0xDF, 0xE0, 0xE1}  # knife, electric stick, pipe
WALK = 0x09                                     # the walk-in animation to guard
PLAYERS = (0x01, 0x02, 0x03)


def sim(w, rows, obj):
    """First chain this firmware would take: (frame, from anim, to anim, age)."""
    anim_off = None
    crt = None
    prev_next = 0xFFFF
    age = 0xFF
    first = True
    for t in rows:
        nxt = t['nxt']
        if nxt == 0xFFFF:
            age = 0xFF
        elif prev_next == 0xFFFF:
            age = 0
        elif age < 0xFF:
            age += 1
        prev_next = nxt

        # the game never changes anim without raising reset in the same call
        # (setAnim, ROM 0x031024), so either signal means a fresh load
        load = first or t['reset'] == 1 or t['anim'] != crt
        first = False
        if load:
            try:
                anim_off = anim_data.anim_offset(w, obj, t['anim'])
            except Exception:
                anim_off = None
            crt = t['anim']
            continue
        if anim_off is None:
            continue
        try:
            word = w[anim_off >> 2]
        except Exception:
            continue
        if word & 0x80000000:
            anim_off += 4                       # not the last frame; advance
            continue
        loop = w[(anim_off + 4) >> 2] & 0xFFFFFF
        if nxt != 0xFFFF and (loop == 0 or age <= WINDOW):
            return (t['f'], crt, nxt, age)
        anim_off = loop
        if not anim_off:                        # terminal end: stop drawing
            return None
    return None


def episodes(ts):
    """Split each (object, slot) stream where the object leaves and comes back."""
    by = defaultdict(list)
    for t in ts:
        by[(t['obj'], t['slot'])].append(t)
    out = []
    for k, rs in by.items():
        cur = []
        prevf = None
        for t in rs:
            if prevf is not None and t['f'] > prevf + 3:
                if cur:
                    out.append((k[0], cur))
                cur = []
            cur.append(t)
            prevf = t['f']
        if cur:
            out.append((k[0], cur))
    return out


def main():
    caps = sys.argv[1:]
    if not caps:
        raise SystemExit(__doc__)
    w = anim_data.load()
    print('PPM_CHAIN_FRESH_WINDOW = %d\n' % WINDOW)
    tot = defaultdict(int)
    n_eps = 0
    for cap in caps:
        if not os.path.exists(cap):
            print('%-40s missing, skipped' % cap)
            continue
        eps = episodes(winlog_objects.triples(cap))
        n_eps += len(eps)
        fired = [(o, sim(w, rows, o)) for o, rows in eps]
        fired = [(o, r) for o, r in fired if r]
        print('%-40s %5d episodes, %4d chain' % (os.path.basename(cap), len(eps), len(fired)))
        for o, r in fired:
            tot[(o, r[1], r[2])] += 1

    print('\nWHAT CHAINED')
    print('%-6s %-8s %-8s %-8s %s' % ('obj', 'from', 'to', 'count', 'note'))
    for (o, a, b), c in sorted(tot.items(), key=lambda x: -x[1]):
        note = 'WEAPON' if o in WEAPONS else ('PLAYER' if o in PLAYERS else '')
        print('%-6s %-8s %-8s %-8d %s' % ('%02X' % o, '%02X' % a, '%04X' % b, c, note))

    weap = sum(c for (o, _a, _b), c in tot.items() if o in WEAPONS)
    walk = any(o in PLAYERS and a == WALK for (o, a, _b) in tot)
    print('\n%d episodes replayed' % n_eps)
    print('weapon chains fired : %d' % weap)
    print('walk-in guard       : %s' % (
        'FAILED - a chain came out of anim %02X' % WALK if walk
        else 'passed, no chain out of anim %02X' % WALK))


if __name__ == '__main__':
    main()
