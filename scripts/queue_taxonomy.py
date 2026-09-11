"""Where the game arms an animation queue, how long it leaves it, and what that
means for the chain rule.

    python scripts/queue_taxonomy.py ../vdp-capture/*.bin
    STALE=64 python scripts/queue_taxonomy.py ...      # test another threshold

This is the measurement the 0.2.5 chain rule is built on, kept so the thresholds
can be re-derived rather than trusted. It prints three reports:

  ARMINGS    every queue arming, classified by where it falls in the animation
             running at the time - AT-LOAD (the same draw that set the
             animation), AT-END (the draw it finishes) or MID - with the queue's
             age when that animation next ends. AT-LOAD always ends at age ==
             the animation's length, which is why a freshness window can never
             fire on it.

  LIFETIMES  how many draws each queue stood and how it ended: RESOLVED (the
             game set `anim` itself), CLEARED (the game withdrew the queue) or
             GONE (it never came back - the handover a dropped item gets).

  ENDS       every animation end reached with a queue standing, attributed to
             the branch that fires on it. AT_LOAD and STALE are kept as analysis
             knobs because they are the history: both were tried on hardware and
             both moonwalked the walk-in, because both reach obj 01 anim 02.

  POPULATION the animation count per object, which is what the shipped rule
             actually keys on (PPM_CHAIN_PROP_ANIMS). Props and actors separate
             with a gap and no overlap, and the firmware already keeps this
             number: ppm_anim_max_index.

The replay never chains - it follows the recording - so every end is visible,
including the ones a chain would have hidden.
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anim_data
import winlog_objects

STALE = int(os.environ.get('STALE', '64'))      # tried and reverted; see above
WINDOW = int(os.environ.get('WINDOW', '1'))     # PPM_CHAIN_FRESH_WINDOW
AT_LOAD = int(os.environ.get('AT_LOAD', '1'))   # tried and reverted; see above
PROP = int(os.environ.get('PROP', '32'))        # PPM_CHAIN_PROP_ANIMS
CHARS = (0x01, 0x02, 0x03)                      # the three playable characters


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


def walk(w, rows, obj, arm, firstend, life, ends):
    off = None
    crt = None
    prev_next = 0xFFFF
    age = 0xFF
    at_load = 0
    first = True
    pend = None                                 # (anim, where) awaiting an end
    stood = 0
    aanim = None

    def close(how):
        if aanim is not None and stood:
            life[(obj, aanim)].append((stood, how))

    for t in rows:
        nxt = t['nxt']
        armed_now = (nxt != 0xFFFF and prev_next == 0xFFFF)
        if nxt == 0xFFFF:
            if aanim is not None:
                close('RESOLVED' if t['anim'] != aanim else 'CLEARED')
            age = 0xFF
            at_load = 0
            pend = None
            aanim = None
            stood = 0
        elif armed_now:
            close('RESOLVED')
            age = 0
            aanim = t['anim']
            stood = 1
        else:
            if age < 0xFF:
                age += 1
            if aanim is not None and t['anim'] != aanim:
                close('RESOLVED')
                aanim = t['anim']
                stood = 1
            else:
                stood += 1
        prev_next = nxt

        # the game never changes anim without raising reset in the same call
        # (setAnim, ROM 0x031024), so either signal means a fresh load
        load = first or t['reset'] == 1 or t['anim'] != crt
        first = False
        if load:
            try:
                off = anim_data.anim_offset(w, obj, t['anim'])
            except Exception:
                off = None
            crt = t['anim']
            at_load = 1 if age == 0 else 0
            if armed_now:
                arm[(obj, crt, 'AT-LOAD')] += 1
                pend = (crt, 'AT-LOAD')
            continue
        if off is None:
            continue
        try:
            word = w[off >> 2]
        except Exception:
            continue
        at_end = not (word & 0x80000000)
        if armed_now:
            where = 'AT-END' if at_end else 'MID'
            arm[(obj, crt, where)] += 1
            pend = (crt, where)
        if not at_end:
            off += 4
            continue

        loop = w[(off + 4) >> 2] & 0xFFFFFF
        if nxt != 0xFFFF:
            why = ('terminal' if loop == 0 else 'at-end' if age <= WINDOW
                   else 'at-load' if (AT_LOAD and at_load)
                   else 'stale' if (STALE and age >= STALE) else 'none')
            ends[(obj, crt, why)].append(age)
            if pend:
                firstend[(obj, pend[0], pend[1])].append(age)
                pend = None
        off = loop
        if not off:                             # terminal end: stop drawing
            close('GONE')
            return
    close('GONE')


def main():
    caps = sys.argv[1:]
    if not caps:
        raise SystemExit(__doc__)
    w = anim_data.load()
    arm = defaultdict(int)
    firstend = defaultdict(list)
    life = defaultdict(list)
    ends = defaultdict(list)
    n = 0
    for cap in caps:
        if not os.path.exists(cap):
            print('%-44s missing, skipped' % os.path.basename(cap))
            continue
        ts = winlog_objects.triples(cap)
        n += len(ts)
        for obj, rows in episodes(ts):
            walk(w, rows, obj, arm, firstend, life, ends)
        print('%-44s %8d records' % (os.path.basename(cap), len(ts)))
    print('\n%d object records\n' % n)

    print('ARMINGS')
    print('  %-5s %-5s %-8s %-7s %-6s %s' % ('obj', 'anim', 'where', 'count', 'len', 'age at the next end'))
    for (obj, a, where), c in sorted(arm.items()):
        try:
            ln = len(anim_data.frames(w, obj, a)[0])
        except Exception:
            ln = -1
        u = sorted(set(firstend.get((obj, a, where), [])))
        print('  %-5s %-5s %-8s %-7d %-6d %s' % (
            '%02X' % obj, '%02X' % a, where, c, ln,
            (','.join(str(x) for x in u[:8]) + (' ...' if len(u) > 8 else '')) if u else '(no end)'))

    print('\nLIFETIMES  (draws a queue stood, and how it ended)')
    print('  %-5s %-5s %-6s %-26s %s' % ('obj', 'anim', 'count', 'draws', 'how'))
    for k in sorted(life):
        v = sorted(x[0] for x in life[k])
        if len(v) < 2:
            continue
        how = defaultdict(int)
        for _d, h in life[k]:
            how[h] += 1
        print('  %-5s %-5s %-6d min %-5d med %-5d max %-6d %s' % (
            '%02X' % k[0], '%02X' % k[1], len(v), v[0], v[len(v) // 2], v[-1],
            ' '.join('%s=%d' % x for x in sorted(how.items()))))

    print('\nENDS reached with a queue standing   (STALE = %d, WINDOW = %d)' % (STALE, WINDOW))
    print('  %-10s %-10s %-10s %s' % ('branch', 'characters', 'others', 'age range'))
    for why in ('terminal', 'at-end', 'at-load', 'stale', 'none'):
        ca = [x for k, v in ends.items() if k[2] == why and k[0] in CHARS for x in v]
        oa = [x for k, v in ends.items() if k[2] == why and k[0] not in CHARS for x in v]
        a = ca + oa
        print('  %-10s %-10d %-10d %s' % (why, len(ca), len(oa),
              ('%d..%d' % (min(a), max(a))) if a else '-'))
    worst = [(max(v), k) for k, v in ends.items()
             if k[0] in CHARS and k[2] in ('none', 'stale')]
    if worst:
        age, k = max(worst)
        print('\n  oldest queue a character carries into an end: %d draws '
              '(obj %02X anim %02X)' % (age, k[0], k[1]))
        print('  A stale-queue rule has to clear that - and 0.2.5a shows clearing')
        print('  it is not enough, because obj 01 anim 02 goes far past it.')
    bad = sum(len(v) for k, v in ends.items() if k[0] in CHARS and k[2] == 'stale')
    print('  character ends the stale branch would fire on: %d%s' % (
        bad, '   <== THRESHOLD TOO LOW' if bad else ''))

    print('')
    print('POPULATION  (PPM_CHAIN_PROP_ANIMS = %d)' % PROP)
    props, actors = [], []
    for obj in sorted(set(k[0] for k in ends) | set(k[0] for k in arm)):
        try:
            na = anim_data.n_anims(w, obj)
        except Exception:
            na = 999
        (props if na <= PROP else actors).append((obj, na))
    print('  props  (chain at any looping end): %s' % ' '.join(
        '%02X/%d' % x for x in props))
    print('  actors (0.2.4 rule unchanged)   : %s' % ' '.join(
        '%02X/%d' % (o, n if n < 999 else -1) for o, n in actors))
    if props and actors:
        print('  gap: largest prop %d animations, smallest actor %d' % (
            max(n for _o, n in props), min(n for _o, n in actors)))


if __name__ == '__main__':
    main()
