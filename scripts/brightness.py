#!/usr/bin/env python3
"""Localise TIMBRE errors between a hardware capture and a render, in time.

    python scripts/brightness.py <capture.mkv> <render.wav> [options]

The player's report on Theme Of Paprium was "sounds way too bright in parts,
right in others". That is a statement about time, not about the track. A
whole-track band average cannot see it: it averages the wrong parts together
with the right ones and returns a number that is true of nothing. So this tool
never reports one. It reports a curve, and then where the curve changes regime.

  1. ALIGN, and refuse if the alignment is not solid. Three independent
     broadband envelopes (log-RMS, RMS, spectral flux) are each slid over the
     capture with a true Pearson r at every lag. The tool reports every lag and
     r, whether the three agree, the runners-up (a looped track has more than
     one plausible lag, one bar apart), and a cross-check against the moment
     music starts in the capture - which is where the render's t=0 must land,
     since the render starts at module position 0. Then it re-aligns short
     windows across the track to bound DRIFT. If the peak is weak, or the
     windows disagree, it prints METHOD BLIND and reports NO brightness numbers:
     a brightness difference measured at the wrong lag is a rhythm difference
     wearing a costume, and the two are not distinguishable after the fact.

  2. MEASURE, per 50 ms frame, inside a frequency band you choose:
       - spectral centroid, reported as render/capture in semitones
       - high/low band power ratio in dB, split at --split
     Both are level-invariant, so a loudness error cannot masquerade as a
     brightness error. Frames are gated twice: on level, and on SNR above the
     capture's own in-band noise floor, so a quiet passage is not "measured"
     when what is really being measured is hiss.

  3. SEPARATE the constant from the varying. A capture-chain EQ, or a renderer
     that is uniformly dull, is a CONSTANT offset across the whole track. "Too
     bright in parts, right in others" is the RESIDUAL after that offset is
     removed. Both are reported, and the section ranking uses the residual.

  4. SEGMENT. Binary segmentation finds where the difference curve changes
     regime. You get timestamps - in render time and in capture time - for the
     worst and the best sections, and --clips writes those windows out of both
     files so the claim can be listened to instead of believed.

Restricting --band ties a claim to one voice group instead of to the whole mix.
Rough bands for this cartridge (26 voices: 6 FM, 4 PSG, 16 wave):
    80-300      bass, kick
    300-1200    mid body, most wave leads
    1200-5000   FM edge, snare body, PSG
    5000-12000  hats, cymbals, aliasing, sample-replay junk
To attribute a section to an instrument rather than to a band, re-render with
render_wave.py --voices and run this again on the same window.

Blind spots are printed at the end of every report. They are not boilerplate.

VALIDATION - what was actually tested, and how far it goes.

  Ground truth 1. The render, padded with 2.5 s of silence and attenuated 6 dB,
  fed back in as the "capture". Result: lag +2.500 s (truth 2.500), r = 1.000,
  hi/lo difference +0.00 dB, centroid +0.00 st, and the 6 dB level difference
  reported as level only. So the brightness metrics are level-invariant in
  practice, not just in theory.

  Ground truth 2. The same file with a +8 dB shelf above 3 kHz applied ONLY
  between render time 20.0 and 30.0 s. The tool put the section boundaries at
  20.03 s and 29.93 s - inside one 50 ms frame - called the render TOO DULL
  there (correct, the fake capture was the brightened one), and reported
  -0.00 dB outside. So it localises a known timbre error to the right seconds.

  Negative controls. Three deliberately mismatched capture/render pairings were
  all refused (Gothic capture vs Theme render; Theme capture vs Gothic render;
  Retro Beat capture vs Dark Rock render), and all six correct pairings passed.
  The guards are layered and no single one carries it: the three mismatches
  were caught by the sharpness guard, the drift guard, and four guards at once,
  respectively.

  KNOWN WEAKNESS, stated plainly. The alignment r is NOT a reliable match test:
  a deliberately wrong pairing scored r = 0.655 while a correct pairing scored
  r = 0.316, because a log-RMS envelope mostly encodes the slow loudness
  contour, which any two dense pieces of music share. That is why --min-r is
  set low and the real work is done by --min-sharp. But the sharpness margin is
  narrow too: over those nine pairings the worst correct pair scored 0.157 and
  the best wrong pair 0.135, against a threshold of 0.10. Nine pairings is a
  small calibration set. If this tool ever passes a pairing you do not trust,
  distrust the tool first, and check the lag by ear.

Derived from a commercial ROM and from recordings of it: keep the output local.
"""

import argparse
import os
import subprocess
import sys

import numpy as np

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")


# ------------------------------------------------------------------ decoding

def decode(path, sr, channel="mono", seconds=None):
    """Decode anything ffmpeg can read to float64 mono at sr.

    ffmpeg resamples, not us: a hand-rolled linear interpolation rolls off the
    top of the band, and the top of the band is the quantity being measured.
    """
    cmd = [FFMPEG, "-v", "error"]
    if seconds:
        cmd += ["-t", "%.3f" % seconds]
    cmd += ["-i", path, "-map", "a:0", "-ac", "2", "-ar", str(sr),
            "-f", "f32le", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout
    a = np.frombuffer(raw, dtype="<f4")
    a = a[: (len(a) // 2) * 2].reshape(-1, 2).astype(np.float64)
    if channel == "l":
        return a[:, 0]
    if channel == "r":
        return a[:, 1]
    return a.mean(axis=1)


# ------------------------------------------------------------------- my STFT
# scipy and librosa are not installed on this box. This is the whole DSP layer.

def frames(x, n, hop):
    """Framed view of x, shape (nframes, n)."""
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    m = 1 + (len(x) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(m)[:, None]
    return x[idx]


def frames_at(x, starts, n):
    """Frames beginning at arbitrary sample offsets - used by --local-align."""
    starts = np.clip(np.asarray(starts, dtype=np.int64), 0, max(len(x) - n, 0))
    if len(x) < n:
        x = np.pad(x, (0, n - len(x)))
    return x[starts[:, None] + np.arange(n)[None, :]]


def stft_power(f, sr):
    """|rfft|^2 of Hann-windowed frames. Returns (power, freqs)."""
    n = f.shape[1]
    P = np.abs(np.fft.rfft(f * np.hanning(n)[None, :], axis=1)) ** 2
    return P, np.fft.rfftfreq(n, 1.0 / sr)


def medfilt(y, k):
    if k <= 1 or len(y) < 3:
        return y
    k |= 1
    z = np.pad(y, (k // 2, k // 2), mode="edge")
    return np.median(frames(z, k, 1), axis=1)


# ---------------------------------------------------------------- envelopes

def rms_env(x, sr, hop_s):
    hop = max(int(round(hop_s * sr)), 1)
    return np.sqrt((frames(x, hop * 4, hop) ** 2).mean(axis=1) + 1e-20)


def flux_env(x, sr, hop_s, nfft=1024, smooth=11):
    """Half-wave-rectified log spectral flux, summed over all bins."""
    hop = max(int(round(hop_s * sr)), 1)
    P, _ = stft_power(frames(x, nfft, hop), sr)
    L = np.log(P + 1e-10)
    d = np.maximum(np.diff(L, axis=0, prepend=L[:1]), 0.0).sum(axis=1)
    if smooth > 1:
        w = np.hanning(smooth)
        d = np.convolve(d, w / w.sum(), "same")
    return d


def envelopes(x, sr, hop_s):
    r = rms_env(x, sr, hop_s)
    return {"logrms": np.log(r + 1e-6), "rms": r, "flux": flux_env(x, sr, hop_s)}


def music_start(x, sr):
    """First sample that is clearly above the opening noise floor."""
    fr = max(int(0.01 * sr), 1)
    e = np.sqrt(np.convolve(x * x, np.ones(fr) / fr, "same"))
    if e.max() <= 0:
        return 0.0
    thr = max(np.percentile(e[:sr], 50) * 20, e.max() * 0.02)
    return int(np.argmax(e > thr)) / sr


# ---------------------------------------------------------------- alignment

def sliding_pearson(a, b):
    """Pearson r of fixed a against every window of b. Requires len(b)>=len(a).

    Numerator by FFT correlation, window mean and variance by cumulative sums:
    O(n log n), and the peak is a real correlation coefficient rather than an
    unnormalised dot product that simply grows wherever the capture is loud.
    """
    m, n = len(a), len(b)
    if m > n:
        raise ValueError("a longer than b")
    nl = n - m + 1
    a0 = a - a.mean()
    sa = np.sqrt((a0 * a0).sum())
    if sa <= 0:
        return np.zeros(nl)
    nfft = 1 << int(np.ceil(np.log2(n + m)))
    num = np.fft.irfft(np.fft.rfft(b, nfft) * np.conj(np.fft.rfft(a0, nfft)),
                       nfft)[:nl]
    c1 = np.concatenate(([0.0], np.cumsum(b)))
    c2 = np.concatenate(([0.0], np.cumsum(b * b)))
    s1, s2 = c1[m:] - c1[:nl], c2[m:] - c2[:nl]
    den = sa * np.sqrt(np.maximum(s2 - s1 * s1 / m, 0.0))
    out = np.zeros(nl)
    ok = den > 1e-12
    out[ok] = num[ok] / den[ok]
    return out


def peak_lag(r, hop_s, lo_s=None, hi_s=None, nother=3, guard_s=1.0):
    """Best lag in r (seconds), parabolically refined, plus the runners-up."""
    lo = 0 if lo_s is None else max(0, int(lo_s / hop_s))
    hi = len(r) if hi_s is None else min(len(r), int(hi_s / hop_s) + 1)
    if hi <= lo:
        return 0.0, -1.0, []
    if hi - lo < 3:                       # too few lags to interpolate
        k = int(np.argmax(r[lo:hi]))
        return (lo + k) * hop_s, float(r[lo + k]), []
    w = r[lo:hi]
    k = int(np.argmax(w))
    top = float(w[k])
    frac = 0.0
    if 0 < k < len(w) - 1:
        y0, y1, y2 = w[k - 1], w[k], w[k + 1]
        d = y0 - 2 * y1 + y2
        if abs(d) > 1e-12:
            frac = float(np.clip(0.5 * (y0 - y2) / d, -1, 1))
    lag = (lo + k + frac) * hop_s
    others, ww, kk = [], w.copy(), k
    guard = max(int(guard_s / hop_s), 1)
    for _ in range(nother):
        ww[max(0, kk - guard):kk + guard + 1] = -2
        kk = int(np.argmax(ww))
        if ww[kk] < -1:
            break
        others.append(((lo + kk) * hop_s, float(ww[kk])))
    return lag, top, others


def window_lags(a, b, hop_s, lag0, nwin, guard):
    """Re-align nwin windows of a near lag0. Returns [(t_mid, lag, r)]."""
    out = []
    w = len(a) // nwin
    if w < int(1.0 / hop_s):
        return out
    for i in range(nwin):
        piece = a[i * w:(i + 1) * w]
        c0 = lag0 + i * w * hop_s
        s = max(0, int((c0 - guard) / hop_s))
        e = min(len(b), int((c0 + guard) / hop_s) + len(piece))
        if e - s < len(piece) + 2:
            continue
        lag, r, _ = peak_lag(sliding_pearson(piece, b[s:e]), hop_s,
                             nother=0, guard_s=guard)
        if lag is None:
            continue
        out.append(((i + 0.5) * w * hop_s, s * hop_s + lag - i * w * hop_s, r))
    return out


# --------------------------------------------------------- brightness frames

def measure(P, freqs, band, split):
    """Per-frame centroid (Hz), hi/lo ratio (dB), in-band level (dB)."""
    sel = (freqs >= band[0]) & (freqs <= band[1])
    f, Q = freqs[sel], P[:, sel]
    tot = Q.sum(axis=1) + 1e-30
    cent = (Q * f[None, :]).sum(axis=1) / tot
    ph = Q[:, f >= split].sum(axis=1) + 1e-30
    pl = Q[:, f < split].sum(axis=1) + 1e-30
    return cent, 10 * np.log10(ph / pl), 10 * np.log10(tot)


# ------------------------------------------------------------- segmentation

def binseg(y, t, min_sec, min_frames, max_segs, min_gain):
    """Binary segmentation on the mean. Returns sorted split indices.

    The minimum section length is in SECONDS of t, not in samples of y: y is
    indexed by surviving frames only, and those are not evenly spaced in time
    once the gates have dropped the quiet passages. Counting indices would make
    a section covering half the track look three frames long.
    """
    bounds, splits = [(0, len(y))], []
    while len(splits) + 1 < max_segs:
        best = None
        for (s, e) in bounds:
            seg, n = y[s:e], e - s
            if n < 2 * min_frames or t[e - 1] - t[s] < 2 * min_sec:
                continue
            base = float(((seg - seg.mean()) ** 2).sum())
            c1, c2 = np.cumsum(seg), np.cumsum(seg * seg)
            i = np.arange(min_frames, n - min_frames + 1)
            if len(i):
                ts = t[s:e]
                i = i[(ts[i - 1] - ts[0] >= min_sec) & (ts[-1] - ts[i] >= min_sec)]
            if not len(i):
                continue
            lsum, lsq, ln = c1[i - 1], c2[i - 1], i.astype(float)
            rsum, rsq, rn = c1[-1] - lsum, c2[-1] - lsq, (n - i).astype(float)
            cost = (lsq - lsum ** 2 / ln) + (rsq - rsum ** 2 / rn)
            j = int(np.argmin(cost))
            gain = base - float(cost[j])
            if best is None or gain > best[0]:
                best = (gain, s, e, s + int(i[j]))
        if best is None or best[0] < min_gain:
            break
        _, s, e, cut = best
        splits.append(cut)
        bounds.remove((s, e))
        bounds += [(s, cut), (cut, e)]
    return sorted(splits)


# ------------------------------------------------------------------ reports

def hms(t):
    return "%d:%05.2f" % (int(t // 60), t % 60)


def write_clip(path, start, dur, out, sr):
    subprocess.run([FFMPEG, "-v", "error", "-y", "-ss", "%.3f" % max(start, 0.0),
                    "-t", "%.3f" % dur, "-i", path, "-map", "a:0", "-ac", "2",
                    "-ar", str(sr), out], check=True)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("capture")
    ap.add_argument("render")
    ap.add_argument("--rate", type=int, default=32000,
                    help="analysis rate (default 32000, the renderer's own)")
    ap.add_argument("--hop", type=float, default=0.050, help="STFT hop, s")
    ap.add_argument("--fft", type=int, default=2048, help="STFT window samples")
    ap.add_argument("--band", default="80-12000",
                    help="analysis band LO-HI Hz. Restricts every number "
                         "reported, so a claim can be tied to one voice group")
    ap.add_argument("--split", type=float, default=2000.0,
                    help="hi/lo crossover in Hz for the band ratio")
    ap.add_argument("--channel", default="mono", choices=["mono", "l", "r"])
    ap.add_argument("--seconds", type=float, default=None,
                    help="analyse only the first N s of the render")
    # alignment
    ap.add_argument("--env", default="logrms", choices=["logrms", "rms", "flux"])
    ap.add_argument("--env-hop", type=float, default=0.005)
    ap.add_argument("--lag", type=float, default=None,
                    help="force the lag in seconds and skip the search")
    ap.add_argument("--lag-range", default=None, help="search only LO-HI seconds")
    ap.add_argument("--min-r", type=float, default=0.25,
                    help="refuse below this alignment r. Deliberately low: r is "
                         "a WEAK discriminator here (a deliberately mismatched "
                         "pair scored 0.655 while a correct pair scored 0.316). "
                         "The consensus and sharpness guards do the real work")
    ap.add_argument("--no-start-prior", action="store_true",
                    help="do not prefer the lag that agrees with the capture's "
                         "music start")
    ap.add_argument("--agree-tol", type=float, default=0.100,
                    help="how near the chosen lag another envelope's peak must "
                         "be to count as agreeing, s")
    ap.add_argument("--min-consensus", type=float, default=0.50,
                    help="refuse unless EVERY envelope finds, within "
                         "--agree-tol of the chosen lag, a peak at least this "
                         "fraction of its own best peak anywhere. Catches gross "
                         "disagreement; note it does NOT by itself catch a "
                         "wrong pairing - --min-sharp is the guard that does")
    ap.add_argument("--min-sharp", type=float, default=0.10,
                    help="refuse if r falls by less than this when the lag is "
                         "shifted by --sharp-shift. A flat peak means the "
                         "correlation is riding the slow loudness contour and "
                         "the lag is not actually pinned to note timing")
    ap.add_argument("--sharp-shift", type=float, default=0.100)
    ap.add_argument("--drift-windows", type=int, default=6)
    ap.add_argument("--drift-guard", type=float, default=0.25,
                    help="+/- search for each drift window, s. Keep it under "
                         "one beat or windows snap to the wrong beat")
    ap.add_argument("--max-drift", type=float, default=0.060,
                    help="a window further than this from the median lag is "
                         "TIMING SUSPECT, s")
    ap.add_argument("--local-align", action="store_true",
                    help="track the local lag per frame instead of using one "
                         "global lag (opt-in: it can hide a real timing error)")
    # gating
    ap.add_argument("--gate", type=float, default=-32.0,
                    help="frame gate, dB below each side's own 90th pct level")
    ap.add_argument("--min-snr", type=float, default=12.0,
                    help="frame gate, dB above the capture's in-band noise floor")
    # curve and sections
    ap.add_argument("--smooth", type=float, default=0.5,
                    help="median smoothing of the difference curve, s")
    ap.add_argument("--metric", default="ratio", choices=["ratio", "centroid"])
    ap.add_argument("--sections", type=int, default=8)
    ap.add_argument("--min-section", type=float, default=3.0)
    ap.add_argument("--csv", default=None, help="write the full curve here")
    ap.add_argument("--clips", default=None,
                    help="directory for worst/best A-B audio excerpts")
    ap.add_argument("--clip-len", type=float, default=8.0)
    a = ap.parse_args()

    lo, _, hi = a.band.partition("-")
    band, sr, eh = (float(lo), float(hi)), a.rate, a.env_hop

    print("capture  %s" % a.capture)
    print("render   %s" % a.render)
    cap = decode(a.capture, sr, a.channel)
    ren = decode(a.render, sr, a.channel, a.seconds)
    print("decoded  capture %.2f s, render %.2f s, %d Hz, %s"
          % (len(cap) / sr, len(ren) / sr, sr, a.channel))
    if len(ren) > len(cap):
        print("\nMETHOD BLIND: the render is longer than the capture, so there "
              "is no window to align it into. Trim it with --seconds.")
        return 2

    # ------------------------------------------------------------ 1. ALIGN
    print("\n=== ALIGNMENT ===")
    ec, er = envelopes(cap, sr, eh), envelopes(ren, sr, eh)
    lr = None
    if a.lag_range:
        x, _, y = a.lag_range.partition("-")
        lr = (float(x), float(y))
    cands = {}
    for k in ("logrms", "rms", "flux"):
        rr = sliding_pearson(er[k], ec[k])
        pk = peak_lag(rr, eh, *(lr if lr else (None, None)))
        cands[k] = (pk[0], pk[1], pk[2], rr)
    print("  envelope    lag        r")
    for k in ("logrms", "rms", "flux"):
        print("    %-8s %+8.3f s  %.3f" % (k, cands[k][0], cands[k][1]))
    ls = [cands[k][0] for k in cands]
    agree = max(ls) - min(ls)
    print("  their top picks span %.0f ms%s" % (agree * 1000,
          "" if agree < 0.100 else "  - which is fine if it is a whole loop of "
          "the track; the consensus test below is what decides"))

    lag, r, others, rcurve = cands[a.env]
    cs, rs = music_start(cap, sr), music_start(ren, sr)
    prior = cs - rs
    print("  music starts at %.3f s in the capture, %.3f s in the render"
          % (cs, rs))
    print("  so the render's t=0 should land at lag %+.3f s (module position 0)"
          % prior)
    if others:
        print("  runners-up for the %s envelope (a looped track has one per "
              "bar):" % a.env)
        for t, rr_ in others:
            print("      lag %+.3f s  (%+.3f from the winner)  r = %.3f"
                  % (t, t - lag, rr_))

    note = []
    if not a.no_start_prior and a.lag is None:
        i0 = max(0, int((prior - 2.0) / eh))
        i1 = min(len(rcurve), int((prior + 2.0) / eh) + 1)
        if i1 > i0 + 3:
            plag, pr, _ = peak_lag(rcurve, eh, i0 * eh, (i1 - 1) * eh, nother=0)
            if abs(plag - lag) > 0.030:
                if pr >= 0.9 * r:
                    note.append("the global best lag (%+.3f s, r %.3f) is NOT "
                                "the one consistent with the capture's music "
                                "start; using %+.3f s (r %.3f) instead, which "
                                "is. Pass --no-start-prior to override."
                                % (lag, r, plag, pr))
                    lag, r = plag, pr
                else:
                    note.append("the lag near the music start (%+.3f s) "
                                "correlates far worse (r %.3f vs %.3f) than "
                                "the global best, so the music-start estimate "
                                "is probably picking up something that is not "
                                "the track. Keeping %+.3f s."
                                % (plag, pr, r, lag))
    if a.lag is not None:
        note.append("lag FORCED to %+.3f s by --lag; the search result is "
                    "ignored." % a.lag)
        lag = a.lag
    for z in note:
        print("  NOTE: " + z)
    print("  CHOSEN LAG %+.3f s   r = %.3f   (envelope: %s)" % (lag, r, a.env))

    # Peak sharpness. A correlation that survives a shift of a whole note is not
    # locked to the music: it is riding the slow loudness contour, which any two
    # pieces of dense music share. This is what separates the right capture from
    # the wrong one - the raw r does not, it barely moves.
    ci = int(round(lag / eh))
    sh = int(round(a.sharp_shift / eh))
    off = []
    for d in range(int(0.6 * sh), sh + 1):       # an arc either side, not two
        for j in (ci - d, ci + d):               # bins, so one fluke cannot
            if 0 <= j < len(rcurve):             # decide it. Stays inside one
                off.append(rcurve[j])            # beat, so it cannot land on
    sharp = float(r - max(off)) if off else 0.0  # the next note and look sharp
    print("  peak sharpness: r falls %.3f when the lag is shifted by %.0f ms "
          "(a flat peak means the lag is not pinned to note timing)"
          % (sharp, a.sharp_shift * 1000))

    # Consensus. NOT "do the three envelopes pick the same argmax" - they often
    # do not, because the capture plays the track several times and a later loop
    # can match better than the first. The question is whether each envelope
    # finds a strong peak AT the chosen lag, judged against the best it achieves
    # anywhere. A wrong pairing fails this; a loop does not.
    cons = {}
    print("  consensus at the chosen lag (each envelope's own peak = 1.00):")
    for k in ("logrms", "rms", "flux"):
        c = cands[k][3]
        i0 = max(0, int((lag - a.agree_tol) / eh))
        i1 = min(len(c), int((lag + a.agree_tol) / eh) + 1)
        here = float(c[i0:i1].max()) if i1 > i0 else 0.0
        pk = float(c.max())
        cons[k] = here / max(pk, 1e-9)
        far = abs(float(np.argmax(c)) * eh - lag)
        print("    %-7s r %.3f here, best %.3f at %+.1f s -> %.2f%s"
              % (k, here, pk, float(np.argmax(c)) * eh, cons[k],
                 "   (its best is %.0f s away: a later loop of the same track)"
                 % far if far > 5.0 else ""))
    worst_cons = min(cons.values())

    amb = bool(others) and r > 0 and others[0][1] > 0.9 * r
    if amb:
        if abs(lag - prior) < 0.10:
            print("  the runner-up is within 10%% of the winner, but the winner "
                  "matches the capture's music start to %.0f ms, which settles "
                  "WHICH BAR independently of the correlation. It says nothing "
                  "about whether this is the right track - every capture in "
                  "this set starts about a second in." % (abs(lag - prior) * 1000))
            amb = False
        else:
            print("  WARNING: the runner-up is within 10%% of the winner AND the "
                  "winner does not match the music start. The track may be "
                  "aligned to the wrong bar - same rhythm, wrong music.")

    # drift
    wl = window_lags(er[a.env], ec[a.env], eh, lag, a.drift_windows,
                     a.drift_guard)
    rfloor = max(0.20, 0.4 * r)
    usable = [z for z in wl if z[2] >= rfloor]
    print("  drift: %d windows re-aligned within +/-%.2f s of the chosen lag "
          "(usable r >= %.2f)" % (len(wl), a.drift_guard, rfloor))
    med = float(np.median([z[1] for z in usable])) if usable else lag
    for t, L, rr_ in wl:
        mark = "" if rr_ >= rfloor else "   (too weak to use)"
        if rr_ >= rfloor and abs(L - med) > a.max_drift:
            mark = "   <-- TIMING SUSPECT, %+.0f ms" % ((L - med) * 1000)
        print("      render %6.1f s  lag %+.3f s  r %.3f%s" % (t, L, rr_, mark))
    bad = [z for z in usable if abs(z[1] - med) > a.max_drift]
    slope = 0.0
    monotonic = False
    if len(usable) >= 3:
        # fit on every usable window: an outlier that is NOT part of a trend
        # shows up as a poor R2, and only a trend with a good R2 is a clock error
        xs = np.array([z[0] for z in usable])
        ys = np.array([z[1] for z in usable])
        co = np.polyfit(xs, ys, 1)
        slope = float(co[0])
        pred = np.polyval(co, xs)
        ss = 1 - ((ys - pred) ** 2).sum() / max(((ys - ys.mean()) ** 2).sum(), 1e-12)
        trend = abs(slope) * (len(ren) / sr)
        print("      linear trend %+.0f ms over the render (R2 %.2f) -> implied "
              "clock ratio %.6f" % (trend * 1000, ss, 1.0 + slope))
        good = [z for z in usable if abs(z[1] - med) <= a.max_drift]
        print("      %d of %d usable windows agree within %.0f ms of the median "
              "lag (%+.3f s); their own spread is %.0f ms"
              % (len(good), len(usable), a.max_drift * 1000, med,
                 (max(z[1] for z in good) - min(z[1] for z in good)) * 1000
                 if len(good) > 1 else 0.0))
        monotonic = trend > a.max_drift and ss > 0.8

    blind = []
    if r < a.min_r:
        blind.append("alignment r = %.3f is below --min-r %.2f" % (r, a.min_r))
    if a.lag is None and worst_cons < a.min_consensus:
        blind.append("consensus %.2f (--min-consensus %.2f): at least one "
                     "envelope sees nothing special at the chosen lag while "
                     "matching much better elsewhere. The usual cause is that "
                     "this capture and this render are not the same piece of "
                     "music" % (worst_cons, a.min_consensus))
    if a.lag is None and sharp < a.min_sharp:
        blind.append("the correlation peak is flat: shifting the lag by %.0f ms "
                     "costs only %.3f of r (--min-sharp %.2f). A match that "
                     "survives being shifted by a whole note is a match to the "
                     "loudness contour, which any two dense pieces share, not "
                     "to this music" % (a.sharp_shift * 1000, sharp, a.min_sharp))
    if len(usable) < 2:
        blind.append("only %d alignment window(s) correlate well enough to "
                     "check drift at all" % len(usable))
    elif len(bad) >= max(2, int(0.34 * len(usable))):
        blind.append("%d of %d windows are more than %.0f ms off the median lag"
                     % (len(bad), len(usable), a.max_drift * 1000))
    if monotonic:
        blind.append("the lag trends monotonically by %.0f ms across the render "
                     "(clock ratio %.6f): late frames would be compared against "
                     "the wrong moment" % (abs(slope) * len(ren) / sr * 1000,
                                           1.0 + slope))
    if amb:
        blind.append("the lag is ambiguous between bars and nothing independent "
                     "resolves it")

    if blind:
        print("\nMETHOD BLIND - reporting NO brightness numbers.")
        for z in blind:
            print("  * " + z)
        print("""
  A brightness difference measured at a wrong lag is a rhythm difference in
  disguise, and the two cannot be told apart afterwards. What would get past
  this:
    - --lag S with a lag found by ear: open both files, line up one
      unmistakable hit, read the offset off the ruler
    - --lag-range LO-HI to search only where the music actually is
    - --seconds N to shorten the comparison so drift has less room
    - --env flux or --env rms if one envelope is clearly better behaved
    - a denser render (render_wave.py with more voices) if the render is too
      sparse to correlate at all""")
        return 3

    # ---------------------------------------------------------- 2. MEASURE
    hop = int(round(a.hop * sr))
    nfr = 1 + max(0, (len(ren) - a.fft) // hop)
    t_ren = np.arange(nfr) * a.hop + a.fft / (2.0 * sr)

    local = np.full(nfr, lag)
    if a.local_align and len(usable) >= 2:
        xs = np.array([z[0] for z in usable])
        ys = np.array([z[1] for z in usable])
        local = np.interp(t_ren, xs, ys)
        print("\n  --local-align: per-frame lag from %d windows, %.3f..%.3f s"
              % (len(usable), local.min(), local.max()))
    dev = np.interp(t_ren, [z[0] for z in usable], [z[1] - med for z in usable]) \
        if len(usable) >= 2 else np.zeros(nfr)

    fr_ren = frames(ren, a.fft, hop)[:nfr]
    fr_cap = frames_at(cap, np.round((t_ren - a.fft / (2.0 * sr) + local) * sr),
                       a.fft)
    Pr, freqs = stft_power(fr_ren, sr)
    Pc, _ = stft_power(fr_cap, sr)
    t_cap = t_ren + local

    cc, rc, lc = measure(Pc, freqs, band, a.split)
    cr, rr2, lr2 = measure(Pr, freqs, band, a.split)

    # In-band noise floor of the CAPTURE, from the silent lead-in BEFORE the
    # music starts. A percentile of the whole file does not work: the file is
    # 99% music, so the low percentiles land in quiet music and the "floor"
    # comes out ~25 dB too high, which then gates away every quiet passage -
    # exactly the passages where a missing echo or a dull voice would show.
    # The render gets no SNR gate at all: it is synthesised, it has no floor,
    # and its quiet passages are signal.
    lead = cap[:int(max(cs - 0.10, 0.0) * sr)]
    if len(lead) >= a.fft * 4:
        Pl, _ = stft_power(frames(lead, a.fft, a.fft), sr)
        _, _, ll = measure(Pl, freqs, band, a.split)
        floor_c, floor_how = float(np.median(ll)), "%.2f s lead-in" % (len(lead) / sr)
    else:
        Pfull, _ = stft_power(frames(cap, a.fft, hop * 4), sr)
        _, _, lfull = measure(Pfull, freqs, band, a.split)
        floor_c = float(np.percentile(lfull, 0.5))
        floor_how = ("0.5th pct of the whole file - NO usable silent lead-in, "
                     "so this floor is an upper bound and the SNR gate is "
                     "stricter than it should be")
    Prf, _ = stft_power(frames(ren, a.fft, hop * 4), sr)
    _, _, lrf = measure(Prf, freqs, band, a.split)
    quiet_r = float(np.percentile(lrf, 2))

    gate_c, gate_r = np.percentile(lc, 90) + a.gate, np.percentile(lr2, 90) + a.gate
    lvl_ok = (lc > gate_c) & (lr2 > gate_r)
    snr_ok = lc > floor_c + a.min_snr
    valid = lvl_ok & snr_ok

    print("\n=== MEASUREMENT ===")
    print("  band %.0f-%.0f Hz, hi/lo split %.0f Hz, %d frames of %.0f ms, "
          "%d-pt FFT" % (band[0], band[1], a.split, nfr, a.hop * 1000, a.fft))
    print("  capture in-band noise floor %.1f dB (from the %s); render quietest "
          "2%% %.1f dB - the render is synthesised and has no floor, so only "
          "the capture gets an SNR gate" % (floor_c, floor_how, quiet_r))
    print("  gates: level (cap > %.1f, ren > %.1f) keeps %d; capture SNR "
          "(> %.1f dB) keeps %d; both keep %d of %d (%.0f%%)"
          % (gate_c, gate_r, lvl_ok.sum(), floor_c + a.min_snr, snr_ok.sum(),
             valid.sum(), nfr, 100 * valid.mean()))
    if valid.sum() < 40 or valid.mean() < 0.15:
        print("""
  METHOD BLIND: only %d frames (%.0f%%) carry usable signal on BOTH sides in
  this band. Either the band is empty in one of the two - which is a finding,
  but a presence finding and not a brightness one - or the gates are too tight.
  Widen --band, lower --gate, lower --min-snr, or check whether the render
  simply has nothing here.""" % (valid.sum(), 100 * valid.mean()))
        return 3

    d_cent = np.where(valid, 12 * np.log2(np.maximum(cr, 1e-9) /
                                          np.maximum(cc, 1e-9)), np.nan)
    d_ratio = np.where(valid, rr2 - rc, np.nan)
    d_lvl = np.where(valid, lr2 - lc, np.nan)

    vi = np.flatnonzero(valid)
    y = medfilt((d_ratio if a.metric == "ratio" else d_cent)[vi],
                max(int(round(a.smooth / a.hop)), 1))
    unit = "dB" if a.metric == "ratio" else "st"
    const = float(np.median(y))
    res = y - const

    print("\n  CONSTANT part - the whole-track offset. Capture-chain EQ, or a")
    print("  renderer uniformly off. NOT what the player described:")
    print("    hi/lo ratio  render - capture  %+.2f dB   (median over frames)"
          % float(np.nanmedian(d_ratio)))
    print("    centroid     render / capture  %+.2f semitones"
          % float(np.nanmedian(d_cent)))
    print("    band level   render - capture  %+.2f dB   (loudness, FYI only - "
          "it does not affect anything below)" % float(np.nanmedian(d_lvl)))
    print("\n  VARYING part - this is 'too bright in parts, right in others':")
    print("    residual on the %s curve after the constant is removed:" % a.metric)
    print("      sd %.2f %s, p05 %+.2f, p95 %+.2f, full swing %.2f %s"
          % (float(np.std(res)), unit, float(np.percentile(res, 5)),
             float(np.percentile(res, 95)),
             float(np.percentile(res, 95) - np.percentile(res, 5)), unit))
    if np.std(res) < 0.3 * abs(const):
        print("      NOTE: the constant dominates the variation. In this band "
              "the error looks like a FIXED tone difference, not a localised "
              "one - which would contradict 'right in others'.")

    # -------------------------------------------------------- 3. SECTIONS
    cuts = binseg(res, t_ren[vi], a.min_section, 8, a.sections,
                  0.02 * float(np.var(res)) * len(res))
    edges = [0] + cuts + [len(res)]
    rows = []
    for s, e in zip(edges[:-1], edges[1:]):
        if e - s < 2:
            continue
        i0, i1 = vi[s], vi[min(e - 1, len(vi) - 1)]
        sus = float(np.mean(np.abs(dev[vi[s:e]]))) > a.max_drift
        rows.append(dict(t0r=t_ren[i0], t1r=t_ren[i1], t0c=t_cap[i0],
                         t1c=t_cap[i1], n=e - s, sus=sus,
                         res=float(np.mean(res[s:e])),
                         cent=float(np.nanmean(d_cent[vi[s:e]])),
                         ratio=float(np.nanmean(d_ratio[vi[s:e]])),
                         lvl=float(np.nanmean(d_lvl[vi[s:e]]))))

    print("\n=== SECTIONS (%d, segmented on the %s difference) ==="
          % (len(rows), a.metric))
    print("   render          capture         d_hi/lo  d_centroid  d_level  "
          "residual")
    for z in rows:
        print("   %s-%s %s-%s %+6.2f dB %+7.2f st %+7.1f dB %+7.2f %s%s"
              % (hms(z["t0r"]), hms(z["t1r"]), hms(z["t0c"]), hms(z["t1c"]),
                 z["ratio"], z["cent"], z["lvl"], z["res"], unit,
                 "  TIMING?" if z["sus"] else ""))

    ok = [z for z in rows if not z["sus"]] or rows
    if len(ok) < len(rows):
        print("   (%d section(s) marked TIMING? are excluded from the ranking: "
              "where the local lag drifts, a brightness difference is not "
              "trustworthy)" % (len(rows) - len(ok)))
    worst = sorted(ok, key=lambda z: -abs(z["res"]))
    best = sorted(ok, key=lambda z: abs(z["res"]))
    k = min(3, max(1, len(ok) // 2))     # keep the two lists disjoint
    worst, best = worst[:k], best[:k]
    if len(ok) < 4:
        print("\n  Only %d section(s) survived, so 'worst' and 'best' are a "
              "ranking of very few things. Treat the table above as the result."
              % len(ok))
    print("\n  WORST - furthest from this track's own norm:")
    for z in worst:
        print("    render %s-%s / capture %s-%s   render %s by %.2f %s"
              % (hms(z["t0r"]), hms(z["t1r"]), hms(z["t0c"]), hms(z["t1c"]),
                 "TOO BRIGHT" if z["res"] > 0 else "TOO DULL",
                 abs(z["res"]), unit))
        print("        absolute: hi/lo %+.2f dB, centroid %+.2f st, level "
              "%+.1f dB" % (z["ratio"], z["cent"], z["lvl"]))
    print("  BEST - closest to this track's own norm:")
    for z in best:
        print("    render %s-%s / capture %s-%s   residual %+.2f %s "
              "(hi/lo %+.2f dB, centroid %+.2f st)"
              % (hms(z["t0r"]), hms(z["t1r"]), hms(z["t0c"]), hms(z["t1c"]),
                 z["res"], unit, z["ratio"], z["cent"]))

    if a.csv:
        with open(a.csv, "w") as fh:
            fh.write("t_render_s,t_capture_s,valid,cap_centroid_hz,"
                     "ren_centroid_hz,d_centroid_st,cap_hilo_db,ren_hilo_db,"
                     "d_hilo_db,cap_level_db,ren_level_db,lag_dev_ms\n")
            for i in range(nfr):
                fh.write("%.3f,%.3f,%d,%.1f,%.1f,%.4f,%.3f,%.3f,%.4f,%.2f,"
                         "%.2f,%.1f\n"
                         % (t_ren[i], t_cap[i], int(valid[i]), cc[i], cr[i],
                            d_cent[i], rc[i], rr2[i], d_ratio[i], lc[i],
                            lr2[i], dev[i] * 1000))
        print("\n  wrote %s (%d frames, %d valid)" % (a.csv, nfr, valid.sum()))

    if a.clips:
        os.makedirs(a.clips, exist_ok=True)
        print("\n  A/B clips in %s" % a.clips)
        for tag, lst in (("worst", worst[:2]), ("best", best[:1])):
            for k, z in enumerate(lst):
                mid = 0.5 * (z["t0r"] + z["t1r"])
                st = max(0.0, min(mid - a.clip_len / 2, len(ren) / sr - a.clip_len))
                dur = min(a.clip_len, len(ren) / sr - st)
                base = "%s%d_r%05.1f" % (tag, k + 1, st)
                write_clip(a.capture, st + lag, dur,
                           os.path.join(a.clips, base + "_capture.wav"), sr)
                write_clip(a.render, st, dur,
                           os.path.join(a.clips, base + "_render.wav"), sr)
                print("    %-18s render %s  capture %s  %.1f s  residual "
                      "%+.2f %s" % (base, hms(st), hms(st + lag), dur,
                                    z["res"], unit))

    print("""
=== BLIND SPOTS of this measurement - read before quoting any number ===
  * Centroid and band ratio are MIX statistics. Inside --band they still sum
    every voice with energy there, so a flagged section is not attributed to an
    instrument. To attribute one, re-render with render_wave.py --voices and run
    this again on the same window.
  * Echo is not in the renderer. A missing 166 ms tail removes energy AFTER each
    note, which reads as the render being too dull in sparse passages and about
    right in dense ones. This tool cannot separate that from a wrong timbre.
    A render WITH echo, compared on the same window, would.
  * A missing or silent voice is visible here only if it had energy inside
    --band. A missing bass line during a 5-12 kHz comparison is invisible.
  * The capture went through a console, a RetroTink and AAC. Any fixed EQ in
    that chain sits inside the CONSTANT offset above. That is exactly why the
    section ranking uses the residual - but it also means the constant itself
    cannot be blamed on the renderer without a separate loopback measurement.
  * One lag for the whole track (unless --local-align). The drift check bounds
    the error at %.0f ms across %d usable windows; it does not correct it.
  * Frames below the gates were dropped, not measured. %.0f%% of the render was
    compared. Quiet passages are the ones most likely to be missing, and quiet
    passages are where a missing echo would show.""" % (
        max((abs(z[1] - med) for z in usable), default=0.0) * 1000,
        len(usable), 100 * valid.mean()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
