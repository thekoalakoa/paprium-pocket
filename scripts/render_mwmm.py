#!/usr/bin/env python3
"""Render an MWMM music module to a WAV, to test the decoded format by ear.

    python scripts/render_mwmm.py track01.mwmm out.wav [--cols 13] [--layout par|seq]

This is a FORMAT PROBE, not a synth. It plays square waves so that a wrong
guess sounds wrong in an obvious way. Recognisable melody = the pitch model is
right. Atonal noise = it is not.

Model under test (docs/PORT_PLAN.md):

    0xD8        order list, u16 big-endian ABSOLUTE file offsets, self-delimiting
    min(order)  patterns, contiguous, rows of 8 bytes
    row         2 events of 4 bytes
    event       note, octave, effect, param      <- the part being tested
    pitch       octave*12 + note-1, note 1..12, 0 = no note

Evidence for note/octave: across 1172 near-duplicate pattern pairs, a note-byte
delta that wraps is accompanied by the matching octave step 75-84% of the time,
and every wrap pair resolves to the SAME net interval (+5/oct-1 == -7/oct+0).
Evidence against: the note-byte histogram decays monotonically rather than
showing seven hot values, which is not what a key looks like.
"""
import struct, sys, wave, math

HDR = 0xD8
SR  = 22050

def load(path):
    d = open(path, 'rb').read()
    for n in range(1, (len(d) - HDR) // 2):
        w = struct.unpack('>%dH' % n, d[HDR:HDR + 2 * n])
        if HDR + 2 * n == min(w) and max(w) <= len(d):
            return w, d
    raise SystemExit("no self-consistent order list - not an MWMM module?")

def events(pat):
    """Rows of 8 bytes, 2 events of 4. Yields (note, octave) per event."""
    for r in range(0, len(pat) - 7, 8):
        for e in (0, 4):
            yield pat[r + e], pat[r + e + 1]

def voice_rows(order, d, cols, layout):
    """Return one list of (note,octave) per voice, time-aligned by row index."""
    pts = sorted(set(order)) + [len(d)]
    pat = lambda p: d[p:pts[pts.index(p) + 1]]
    if layout == 'seq':                      # voice-major: concatenate down a column
        return [[ev for p in order[c::cols] for ev in events(pat(p))]
                for c in range(cols)]
    out = [[] for _ in range(cols)]          # parallel: positions are barriers
    for pos in range(len(order) // cols):
        row = order[pos * cols:(pos + 1) * cols]
        span = max(len(list(events(pat(p)))) for p in row)
        for c, p in enumerate(row):
            ev = list(events(pat(p)))
            out[c] += ev + [(0, 0)] * (span - len(ev))
    return out

def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    o = {x.split('=')[0]: x.split('=')[-1] for x in sys.argv[1:] if x.startswith('--')}
    if len(a) < 2:
        print(__doc__); return 2
    cols   = int(o.get('--cols', 13))
    layout = o.get('--layout', 'par')
    tick   = float(o.get('--tick', 0.06))            # seconds per row

    order, d = load(a[0])
    if len(order) % cols:
        print("order list is %d entries, not divisible by %d" % (len(order), cols))
        return 1
    voices = voice_rows(order, d, cols, layout)
    n = max(len(v) for v in voices)
    print("%d voices, %d event-slots, %.1f s at %.0f ms/row"
          % (len(voices), n, n * tick, tick * 1000))

    spr = int(SR * tick)
    buf = [0.0] * (n * spr + SR)
    used = 0
    for v in voices:
        phase = 0.0
        for i, (note, oct_) in enumerate(v):
            if not (1 <= note <= 12) or oct_ > 10:
                continue
            used += 1
            f = 440.0 * 2 ** (((oct_ * 12 + note - 1) - 69) / 12.0)
            for s in range(spr):
                phase += f / SR
                env = min(1.0, (spr - s) / (0.25 * spr))     # decay, kills clicks
                buf[i * spr + s] += (1.0 if phase % 1.0 < 0.5 else -1.0) * 0.10 * env
    print("%d of %d slots decoded as notes (%.0f%%)" % (used, n * len(voices),
                                                        100 * used / (n * len(voices))))
    peak = max(1e-9, max(abs(x) for x in buf))
    with wave.open(a[1], 'w') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(SR)
        f.writeframes(b''.join(struct.pack('<h', int(32000 * x / peak)) for x in buf))
    print("wrote %s" % a[1])

if __name__ == '__main__':
    sys.exit(main())
