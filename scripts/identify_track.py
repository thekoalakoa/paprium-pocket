#!/usr/bin/env python3
"""Blind-match a RECORDING OF REAL PAPRIUM HARDWARE against all 52 modules.

    python scripts/identify_track.py <recording>    # any format ffmpeg reads

Hand it a capture of the cartridge's own audio and it ranks every module by how
well the decoded pitch content matches. You do NOT need to say which track it
is - that is what makes this a test rather than a demonstration.

    right module ranks #1 by a clear margin  ->  the note/octave decode is right
    right module ranks mid-pack              ->  the decode is wrong

WHY REAL HARDWARE AND NOT THE ALBUM: the released soundtrack was tested and
FAILED as a reference - decoded pitch classes matched own-audio at chance (1 of
16), and no header or command field matched its tempo (best 0.496 against a
0.501 mean null). Different names, editorial lengths. It is an independent
studio production, not a render of the cartridge, so it can differ in key and
tempo and prove nothing. Only the cartridge's own output can validate this.

The chroma feature itself is validated: a different segment of the same
recording identifies it 8/8, mean rank 1.00.
"""
import glob, math, os, struct, subprocess, sys, tempfile

HDR, SR, FRAME, LO, HI = 0xD8, 11025, 4096, 45, 85

def norm(v):
    t = sum(v) or 1.0
    return [x / t for x in v]

def corr(a, b):
    ma, mb = sum(a)/12, sum(b)/12
    na = sum((x-ma)**2 for x in a)**.5; nb = sum((x-mb)**2 for x in b)**.5
    return sum((a[i]-ma)*(b[i]-mb) for i in range(12))/(na*nb) if na and nb else 0

def module_chroma(path):
    d = open(path, 'rb').read()
    for n in range(1, (len(d) - HDR) // 2):
        w = struct.unpack('>%dH' % n, d[HDR:HDR + 2*n])
        if HDR + 2*n == min(w) and max(w) <= len(d): break
    else:
        return None
    pts = sorted(set(w)) + [len(d)]
    h = [0.0]*12
    for i in range(len(pts)-1):
        p = d[pts[i]:pts[i+1]]
        for k in range(0, len(p)-1, 2):
            if 1 <= p[k] <= 12 and 1 <= p[k+1] <= 10:
                h[(p[k]-1) % 12] += 1
    return norm(h) if sum(h) else None

def audio_chroma(path):
    tmp = os.path.join(tempfile.gettempdir(), 'id.raw')
    # a headerless .pcm needs its format stated; anything else ffmpeg probes
    pre = (['-f', 's16le', '-ar', '48000', '-ac', '2']
           if path.lower().endswith('.pcm') else [])
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y'] + pre + ['-i', path,
                    '-f', 's16le', '-ar', str(SR), '-ac', '1', tmp], check=True)
    raw = open(tmp, 'rb').read()
    s = struct.unpack('<%dh' % (len(raw)//2), raw)
    if len(s) < SR * 20:
        print("warning: only %.0f s of audio - 60 s or more is much safer"
              % (len(s)/SR), file=sys.stderr)
    freqs = [(m, 440.0 * 2 ** ((m-69)/12.0)) for m in range(LO, HI)]
    h = [0.0]*12
    for off in range(0, len(s)-FRAME, FRAME):
        fr = s[off:off+FRAME]
        for m, f in freqs:
            k = 2.0*math.cos(2.0*math.pi*f/SR); s1 = s2 = 0.0
            for x in fr:
                s0 = x + k*s1 - s2; s2 = s1; s1 = s0
            h[m % 12] += math.sqrt(max(0.0, s1*s1 + s2*s2 - k*s1*s2))
    return norm(h)

def main():
    if len(sys.argv) < 2:
        print(__doc__); return 2
    print("analysing recording ...", flush=True)
    a = audio_chroma(sys.argv[1])
    rows = []
    for f in sorted(glob.glob('../music-modules/track*.mwmm')):
        c = module_chroma(f)
        if not c: continue
        best = max(range(12), key=lambda r: corr(c[r:]+c[:r], a))
        title = bytes(b ^ 0xA5 for b in open(f,'rb').read()[0x78:0x98]).rstrip(b'\x00')
        rows.append((corr(c[best:]+c[:best], a), os.path.basename(f),
                     title.decode('latin1', 'replace')))
    rows.sort(reverse=True)
    print("\n%-6s %-14s %-8s %s" % ("rank", "module", "corr", "title"))
    for i, (sc, nm, t) in enumerate(rows[:10], 1):
        print("%-6d %-14s %+.3f   %s" % (i, nm, sc, t))
    print("   ... %d modules total" % len(rows))
    gap = rows[0][0] - rows[1][0]
    print("\ntop-to-second gap: %+.3f" % gap)
    print("A correct decode should put the real track at #1 with a clear gap.")
    print("If you know which track you recorded, its rank is the whole result.")

if __name__ == '__main__':
    sys.exit(main())
