"""Parse GPGX winlog kind 18/19/20 triples into per-object animation state.

    18: pad = reset & 0xFF   addr = (slot & 0xFF) | ((anim & 0xFF) << 8)
    19: pad = reset >> 8     addr = raw objID word (bit15 = the assign flag)
    20: pad = 0              addr = nextAnim
    stamp = (frame << 16) | v_counter

Captures taken from 2026-09-10 add the rest of the object record, so a reader can
stop inferring it: 21 = +0x06 (the word neither implementation reads), 22 =
objAttr, 23 = framePtr at entry (pad = bits 23..16), 24 = posX, 25 = posY. Kind 23
is emitted further down paprium_sprite, so it is found by scanning ahead rather
than by position. Older captures carry only 18/19/20 and parse unchanged.
"""
import struct
from collections import defaultdict


EXTRA = {21: 'f06', 22: 'attr', 24: 'posX', 25: 'posY'}


def triples(path):
    d = open(path, 'rb').read()
    n = len(d) // 8
    recs = [struct.unpack_from('<BBHI', d, i * 8) for i in range(n)]
    out = []
    i = 0
    while i < n - 2:
        if recs[i][0] == 18 and recs[i + 1][0] == 19 and recs[i + 2][0] == 20:
            a, b, c = recs[i], recs[i + 1], recs[i + 2]
            rec = dict(f=a[3] >> 16, v=a[3] & 0xFFFF, slot=a[2] & 0xFF,
                       anim=(a[2] >> 8) & 0xFF, objraw=b[2], obj=b[2] & 0x7FFF,
                       nxt=c[2], reset=a[1] | (b[1] << 8))
            i += 3
            while i < n and recs[i][0] in EXTRA:
                rec[EXTRA[recs[i][0]]] = recs[i][2]
                i += 1
            j = i
            while j < n and recs[j][0] != 18:
                if recs[j][0] == 23:
                    rec['framePtr'] = (recs[j][1] << 16) | recs[j][2]
                    break
                j += 1
            out.append(rec)
        else:
            i += 1
    return out


def runs(ts):
    """Collapse consecutive identical (anim, nextAnim, reset) into runs."""
    out = []
    prev = None
    for t in ts:
        k = (t['anim'], t['nxt'], t['reset'])
        if k != prev:
            out.append(dict(f0=t['f'], f1=t['f'], anim=k[0], nxt=k[1], reset=k[2], n=1))
            prev = k
        else:
            out[-1]['f1'] = t['f']
            out[-1]['n'] += 1
    return out


def by_object(ts):
    d = defaultdict(list)
    for t in ts:
        d[(t['obj'], t['slot'])].append(t)
    return d
