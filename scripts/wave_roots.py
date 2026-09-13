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
