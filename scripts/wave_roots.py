#!/usr/bin/env python3
"""Measure the natural pitch of each instrument in the cartridge's wave bank.

    python scripts/wave_roots.py <wave-bank.wav> [--min-conf 0.75]

`scripts/dump_wave.py` extracts the bank; decode it to WAV with ffmpeg first.
The program table sits at offset 0 of the decoded bank - 256 entries of 16 bytes,
94 live (see the project notes). Per entry, big-endian:

    +0x00  4  sample pointer into the bank
    +0x04  4  sample length
    +0x08  4  loop point, 0xFFFFFFFF = none
    +0x0C  2  type; GPGX uses type+1 as an index into {1,2,4,5,8,9},
              giving a base rate of 48000/N Hz
    +0x0E  2  zero

**There is no root-pitch field.** A program's root is baked into its audio, so it
has to be measured - which this does, by autocorrelation on the 8-bit sample
played at its base rate.

What that shows: the melodic instruments are **recorded at C**. A large family
sits at ~130.5 Hz (C3) - programs 0x04, 0x05, 0x23, 0x2B, 0x55, 0x56, 0x57 - and
another at ~259-265 Hz (C4), including 0x09, 0x0E, 0x27, 0x28. Percussion and
noise entries have no stable pitch and are reported as such rather than given a
spurious number.

This does NOT by itself solve the absolute anchor C in
`pitch = 12*byte1 + byte0 + C`: knowing a sample's root still needs one reliable
(program, semitone, measured frequency) triple to tie the note numbering to it,
and the blank-slot residues do not supply one. What it does give is the root of
every pitched program, which is half of that equation.
"""

import argparse
import wave

import numpy as np

RATES = [1, 2, 4, 5, 8, 9]
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def load_bank(path):
    """The bank as its original 8-bit byte stream."""
    w = wave.open(path)
    raw = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    return (((raw >> 8) & 0xFF) ^ 0x80).astype(np.uint8)


def pitch(sig, sr):
    """Root pitch as the COMMON DIVISOR of the sample's strong partials.

    Two simpler estimators were tried and each fails on real cartridge samples.
    Autocorrelation latches onto the noisy tail of a steeply decaying sample -
    it put program 0x01 at 1853 Hz when its partials are 70 and 141 Hz. Plain
    harmonic-sum, or taking the strongest peak, picks a harmonic instead of the
    fundamental - program 0x0E's loudest partial is its 2nd (520 Hz over a real
    261 Hz), and 0x24's visible series 1045/1567/2089/2610 is 2x,3x,4x,5x of
    522 Hz with no energy at the fundamental at all.

    What is reliable is the SPACING. Score each candidate f0 by how much of the
    measured peak energy sits within tolerance of an integer multiple of it, and
    keep the HIGHEST f0 that explains essentially as much as the best - so a
    subharmonic, which trivially explains everything, does not win.
    """
    x = sig.astype(np.float64) - 128.0
    if len(x) < 2048:
        return None
    NF = 1 << int(np.log2(min(len(x), 16384)))
    if NF < 2048:
        return None
    w = np.hanning(NF)
    acc = np.zeros(NF // 2 + 1)
    frames = 0
    for i in range(0, max(min(len(x) - NF, NF * 8), 1), NF // 2):
        acc += np.abs(np.fft.rfft(x[i:i + NF] * w))
        frames += 1
    if not frames:
        return None
    acc /= frames
    freqs = np.fft.rfftfreq(NF, 1.0 / sr)
    ok = (freqs >= 40) & (freqs <= min(4000, sr * 0.45))
    v, f = acc[ok], freqs[ok]
    if len(v) < 16 or v.max() <= 0:
        return None

    peaks = [i for i in range(1, len(v) - 1)
             if v[i] > v[i - 1] and v[i] >= v[i + 1] and v[i] > 0.12 * v.max()]
    if not peaks:
        return None
    peaks.sort(key=lambda i: -v[i])
    peaks = peaks[:12]
    pf = np.array([f[i] for i in peaks])
    pm = np.array([v[i] for i in peaks])
    total = pm.sum()

    def explains(f0):
        if f0 <= 0:
            return 0.0
        r = pf / f0
        near = np.abs(r - np.round(r)) < 0.06
        near &= np.round(r) >= 1
        near &= np.round(r) <= 16
        return float(pm[near].sum())

    cands = sorted({round(pf[i] / h, 3) for i in range(len(pf)) for h in range(1, 9)
                    if 35 <= pf[i] / h <= 4000})
    if not cands:
        return None
    scored = [(explains(c), c) for c in cands]
    best = max(s for s, _ in scored)
    if best <= 0:
        return None
    # highest f0 that still explains ~everything the best one does
    f0 = max(c for s, c in scored if s >= 0.97 * best)
    conf = float(best / (total + 1e-30))
    return (f0, conf)


def requested_notes(moddir):
    """{program: [MIDI notes the music asks of it]} over every wave voice, whole corpus.

    Tracks the program exactly the way render_wave.render() does - the static
    byte at +0x2A as the initial value, then command 0x0F wherever it appears -
    so the two agree on which sample a note lands on.
    """
    import collections
    import mwmm

    req = collections.defaultdict(list)
    for m in mwmm.load_all(moddir):
        for v in range(10, 26):
            prog = m.d[0x2A + (v ^ 1)] or None
            for _, ev in m.timeline(v):
                for k in (2, 4, 6):
                    if ev[k] == 0x0F:
                        prog = ev[k + 1]
                if ev[0] and ev[0] != 0x0E and prog is not None:
                    req[prog].append(12 * ev[1] + ev[0] + 11)
    return req


def octave_fix(roots, req, span=6):
    """{program: whole-octave shift} to put a measured root where the music uses it.

    `pitch` above is reliable on the SPACING of a sample's partials and
    unreliable on which of them is the fundamental, so its answer is right
    modulo an octave and wrong by up to five of them: program 0x3F measures at
    MIDI 106.3 with confidence 1.00 while every one of its 1,440 notes asks for
    B2 to B4. Nothing in the sample settles it, but the music does - a sampler
    part is written near its instrument's own register.

    So take the octave that centres each program's note distribution on its root.
    Corpus-wide that moves the notes sitting beyond render_wave's +/-24 semitone
    guard - which are played at the sample's own rate, in the wrong octave, and
    are heard as a missing or a shrill instrument - from 31.2% to 1.7%.

    UNVALIDATED, AND PROBABLY WRONG. Kept for experiment only; render_wave does
    not apply it unless asked with --octave-fix. Both arguments once made for it
    have since failed:

      * "it takes notes beyond the +/-24 guard from 31.2% to 1.7%". True, and
        worthless: this function minimises median|note - root| and the guard is
        |note - root| > 24, so it is optimising the statistic it is scored on.
      * "the corrected roots land on pitch class C at p = 1.2e-10". Vacuous. The
        correction is root + 12*k and a whole-octave shift CANNOT change pitch
        class. That p-value measures `pitch` above, not this function, and it
        carries exactly zero information about the octave - which is the only
        thing this function chooses.

    Measured against it: 24 programs that `pitch` rates at confidence 1.00 - a
    complete harmonic ladder, the case it is most reliable on - get moved, by up
    to five octaves. Rendering with it applied puts Gothic voice 12 (written C5)
    at MIDI 38.7 and Waterfront Beat voice 13 (written C4) at 33.1.

    The real question it was trying to answer is still open: the music routinely
    asks a program for notes two to five octaves from where its sample measures,
    and nobody yet knows whether the cartridge transposes that far, uses a rate
    table rather than equal temperament, or carries a per-program tuning we have
    not found. Settle THAT from a hardware capture, not from a fit.
    """
    import numpy as np

    out = {}
    for p, root in roots.items():
        n = req.get(p)
        if root is None or not n:
            continue
        n = np.asarray(n, dtype=float)
        out[p] = min(range(-span, span + 1),
                     key=lambda k: np.median(np.abs(n - (root + 12 * k))))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bank")
    ap.add_argument("--min-conf", type=float, default=0.75)
    a = ap.parse_args()

    b = load_bank(a.bank)
    be32 = lambda o: int.from_bytes(b[o:o + 4].tobytes(), "big")
    be16 = lambda o: int.from_bytes(b[o:o + 2].tobytes(), "big")

    print("%-6s %9s %5s %7s %10s %9s %-5s %6s"
          % ("prog", "length", "type", "rate", "root Hz", "MIDI", "note", "conf"))
    pitched = 0
    for p in range(256):
        ptr, ln, typ = be32(p * 16), be32(p * 16 + 4), be16(p * 16 + 12)
        if not ln or ptr >= len(b):
            continue
        ridx = typ + 1 if typ + 1 < len(RATES) else 1
        sr = 48000 // RATES[ridx]
        r = pitch(b[ptr:ptr + min(ln, 200000)], sr)
        if not r or r[1] < a.min_conf or r[0] <= 0:
            print("%-6s %9d %5d %7d %10s %9s %-5s %6s"
                  % ("0x%02X" % p, ln, typ, sr, "-", "-", "unpitched",
                     "%.2f" % r[1] if r else "-"))
            continue
        midi = 69 + 12 * np.log2(r[0] / 440.0)
        print("%-6s %9d %5d %7d %10.2f %9.2f %-5s %6.2f"
              % ("0x%02X" % p, ln, typ, sr, r[0], midi,
                 NAMES[int(round(midi)) % 12] + str(int(round(midi)) // 12 - 1), r[1]))
        pitched += 1
    print("\n%d pitched programs at confidence >= %.2f" % (pitched, a.min_conf))


if __name__ == "__main__":
    main()
