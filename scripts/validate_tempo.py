#!/usr/bin/env python3
"""Measure the OST tempo and look for a matching field in the MWMM header.

    python scripts/validate_tempo.py

Tempo, unlike duration, is a real invariant here. A game stage theme loops
forever and the released track is an edit of it - intro, a few loops, a fade -
so its LENGTH says nothing about the module. Its BPM still does, as long as the
album was not re-produced at a different tempo.

BPM is measured from the audio alone: energy envelope at 43 fps, positive
first difference as onset strength, autocorrelation over lags covering 60-200
BPM. Then every header byte and u16 is correlated against it.

The module header already implies a tick grid without reference to any audio:

    +0x0B  rows per bar    0x10 (16) on most tracks, 0x18 (24) on track 03
    +0x0C  beats per bar   0x04      on most tracks, 0x06      on track 03

Both give 4 rows per beat, so a tempo field should satisfy
BPM = rows_per_second * 60 / 4 for whatever the real tick rate turns out to be.
"""
import glob, math, os, struct, subprocess, sys, tempfile

HDR, SR, HOP = 0xD8, 11025, 256
FPS = SR / HOP

def bpm(pcm, seconds=60):
    sz = os.path.getsize(pcm)
    tmp = os.path.join(tempfile.gettempdir(), 'bp.raw')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 's16le',
                    '-ar', '48000', '-ac', '2',
                    '-ss', str(int(sz / 4 / 48000 * 0.25)), '-t', str(seconds),
                    '-i', pcm, '-f', 's16le', '-ar', str(SR), '-ac', '1', tmp],
                   check=True)
    raw = open(tmp, 'rb').read()
    s = struct.unpack('<%dh' % (len(raw) // 2), raw)
    e = []
    for i in range(0, len(s) - HOP, HOP):
        e.append(math.log(1.0 + sum(x * x for x in s[i:i + HOP]) / HOP))
    on = [max(0.0, e[i] - e[i - 1]) for i in range(1, len(e))]
    m = sum(on) / len(on)
    on = [x - m for x in on]
    best, bl = 0.0, 0
    for lag in range(int(FPS * 60 / 200), int(FPS * 60 / 60) + 1):
        c = sum(on[i] * on[i + lag] for i in range(len(on) - lag))
        if c > best: best, bl = c, lag
    return 60.0 * FPS / bl if bl else 0.0

def pear(a, b):
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    na = sum((x-ma)**2 for x in a)**.5; nb = sum((x-mb)**2 for x in b)**.5
    return sum((a[i]-ma)*(b[i]-mb) for i in range(len(a)))/(na*nb) if na and nb else 0

def main():
    recs = []
    for f in sorted(glob.glob('../music-modules/track*.mwmm')):
        n = os.path.basename(f)[5:7]
        pcm = '../cdda/track%s.pcm' % n
        if not os.path.exists(pcm) or os.path.getsize(pcm) < 48000*4*20: continue
        recs.append((n, open(f, 'rb').read(), pcm))
    print("measuring tempo of %d recordings ..." % len(recs), flush=True)
    out = []
    for n, d, pcm in recs:
        b = bpm(pcm)
        out.append((n, d, b))
        print("  track %s  %6.1f BPM" % (n, b), flush=True)
    bs = [o[2] for o in out]
    print("\nmeasured BPM: mean %.0f, range %.0f-%.0f" % (sum(bs)/len(bs), min(bs), max(bs)))
    cands = []
    for off in range(0, 0x78):
        v = [o[1][off] for o in out]
        if len(set(v)) > 3: cands.append(("byte %02X" % off, v))
    for off in range(0, 0x77):
        v = [struct.unpack('>H', o[1][off:off+2])[0] for o in out]
        if len(set(v)) > 3: cands.append(("u16  %02X" % off, v))
    sc = sorted(((abs(pear(v, bs)), pear(v, bs), nm) for nm, v in cands), reverse=True)
    print("\nheader fields most correlated with measured BPM:")
    for a, c, nm in sc[:10]:
        print("  %-9s %+.3f %s" % (nm, c, "<- STRONG" if a > 0.7 else ""))
    if sc and sc[0][0] < 0.5:
        print("\nNothing above 0.5. No header field tracks tempo, so either the")
        print("tempo lives elsewhere or the album was re-produced at its own tempo.")

if __name__ == '__main__':
    sys.exit(main())
