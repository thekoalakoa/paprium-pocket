#!/usr/bin/env python3
"""Test the MWMM note decode against the real recording of the same song.

    python scripts/validate_pitch.py <n> [<n> ...]

music-modules/trackNN.mwmm and cdda/trackNN.pcm are the same piece: the cue's
TRACK numbers line up with the module numbers. So the decoded notes and the
released audio must agree on which pitch classes the song uses.

Chroma of the audio is measured with Goertzel filters (no numpy here). The
decoded histogram is compared at all 12 rotations, because the note byte's
reference pitch is unknown. A correct model peaks sharply at ONE rotation and
scores far better against its own audio than against another track's.
"""
import glob, math, os, struct, subprocess, sys, tempfile

HDR, SR, FRAME = 0xD8, 11025, 4096
LO, HI = 45, 85                      # MIDI range scanned

def decoded_chroma(path):
    d = open(path, 'rb').read()
    for n in range(1, (len(d) - HDR) // 2):
        w = struct.unpack('>%dH' % n, d[HDR:HDR + 2 * n])
        if HDR + 2 * n == min(w) and max(w) <= len(d): break
    pts = sorted(set(w)) + [len(d)]
    h = [0.0] * 12
    for i in range(len(pts) - 1):
        p = d[pts[i]:pts[i + 1]]
        for k in range(0, len(p) - 1, 2):
            if 1 <= p[k] <= 12 and p[k + 1] <= 10:
                h[(p[k] - 1) % 12] += 1
    return h

def audio_chroma(pcm, seconds=45):
    """48k s16 stereo -> 11025 mono, then Goertzel energy per pitch class."""
    tmp = os.path.join(tempfile.gettempdir(), 'vp.raw')
    sz = os.path.getsize(pcm)
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y',
                    '-f', 's16le', '-ar', '48000', '-ac', '2',
                    '-ss', str(int(sz / 4 / 48000 * 0.25)), '-t', str(seconds),
                    '-i', pcm, '-f', 's16le', '-ar', str(SR), '-ac', '1', tmp],
                   check=True)
    raw = open(tmp, 'rb').read()
    s = struct.unpack('<%dh' % (len(raw) // 2), raw)
    freqs = [(m, 440.0 * 2 ** ((m - 69) / 12.0)) for m in range(LO, HI)]
    h = [0.0] * 12
    for off in range(0, len(s) - FRAME, FRAME):
        fr = s[off:off + FRAME]
        for m, f in freqs:
            k = 2.0 * math.cos(2.0 * math.pi * f / SR)
            s1 = s2 = 0.0
            for x in fr:
                s0 = x + k * s1 - s2; s2 = s1; s1 = s0
            h[m % 12] += math.sqrt(max(0.0, s1*s1 + s2*s2 - k*s1*s2))
    return h

def norm(v):
    t = sum(v) or 1.0
    return [x / t for x in v]

def corr(a, b):
    ma, mb = sum(a)/12, sum(b)/12
    na = sum((x-ma)**2 for x in a) ** .5
    nb = sum((x-mb)**2 for x in b) ** .5
    return sum((a[i]-ma)*(b[i]-mb) for i in range(12)) / (na*nb) if na and nb else 0

def main():
    ns = sys.argv[1:] or ['01', '05']
    dec = {n: norm(decoded_chroma('../music-modules/track%s.mwmm' % n)) for n in ns}
    aud = {}
    for n in ns:
        print("analysing cdda/track%s.pcm ..." % n, flush=True)
        aud[n] = norm(audio_chroma('../cdda/track%s.pcm' % n))
    print()
    for n in ns:
        best = max(range(12), key=lambda r: corr(dec[n][r:]+dec[n][:r], aud[n]))
        scores = sorted((corr(dec[n][r:]+dec[n][:r], aud[n]) for r in range(12)),
                        reverse=True)
        print("module %s vs its OWN audio : best r=%2d  corr %+.3f   "
              "(2nd %+.3f, worst %+.3f)" % (n, best, scores[0], scores[1], scores[-1]))
        for m in ns:
            if m == n: continue
            x = max(corr(dec[n][r:]+dec[n][:r], aud[m]) for r in range(12))
            print("            vs track %s audio : best corr %+.3f   <- control" % (m, x))
    print()
    print("A correct pitch model: own-audio corr high (>0.6) and clearly above the")
    print("control. Similar numbers everywhere means the decode carries no real pitch.")

if __name__ == '__main__':
    sys.exit(main())
