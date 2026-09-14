#!/usr/bin/env python3
"""Measure whether the cartridge applies an echo, and with what delay and feedback.

    python scripts/echo_probe.py --hw "1E Gothic.mkv" --ref renders/v2/Gothic.wav
                                 [--moduledir DIR --track 30]
                                 [--seconds 55] [--rate 32000]
                                 [--lag-min 40] [--lag-max 600]
                                 [--dump DIR] [--json OUT.json]

The working belief is 166 ms at about 33% feedback. That number came from a
command constant (0x4000), never from a measurement. This script measures.

--hw sources are hardware (captures, .mkv or .wav). --ref sources are CONTROLS:
our own renders, which contain NO delay line at all. Every number printed for a
--hw source is printed for the --ref sources too, and the verdict is driven by
the DIFFERENCE. If a "delay" shows up in the render as well, the probe is
reading the music's own rhythm and its answer is worthless - the script says so
in those words rather than reporting a delay.

WHAT MAKES THIS HARD HERE
    A delay line is measured on exposed decays: after an isolated note stops,
    the repeats stand alone. This music has no exposed decays. Over the four
    tracks under study the longest gap between ANY two of the 26 voices' note
    onsets is 0.32 s; on the stricter occupancy model in solo_windows.py - which
    counts a note still sounding from ten seconds ago - NO note is ever alone
    and the longest stretch before another voice speaks is 160 ms, shorter than
    the delay being tested. The captures start and end in the middle of the
    music, so there is no run-out tail either. A window shorter than about twice
    the delay cannot carry a lag measurement at all.
    So the per-window methods below run on whatever BAND-LIMITED decays can be
    found - a hat or a stab in a band where nothing else is playing outlives the
    full-mix gap by a long way - and they are backed by two GLOBAL methods that
    need no exposed tail. Whole-track statistics are the wrong tool for judging
    one voice out of 26; but a delay line is not a voice, it is a filter over
    the whole mix, and a filter is exactly what a whole-track spectrum can see.

METHODS (they fail differently, on purpose)
  M1  envelope autocorrelation, per window. Amplitude envelope of one band after
      the note's own attack, detrended in dB so the decay slope does not swamp
      the repeats, autocorrelated across the lag range.
  M2  peak picking on the tail, per window. Local maxima of the band envelope
      after the onset: their spacing is the delay, their step down is the
      feedback in dB per repeat, and their COUNT separates a single slapback
      from a feedback line.
  M3  cepstrum. A delay puts ripple of period 1/D into the power spectrum, which
      is a peak at quefrency D in the cepstrum. Run per window on the tail, and
      globally on the long-term average power spectrum where it is strongest:
      averaging power spectra leaves the filter term |H(f)|^2 exactly intact, so
      a 166 ms delay must show as 6.0 Hz ripple across the whole spectrum.
  M4  raw waveform autocorrelation. A delay line emits a SAMPLE-EXACT copy, so
      rho(D) of the waveform (not of the envelope) is the feedback coefficient
      directly: for y = x + a*y(t-D) with a broadband dry mix, rho(D) = a.
      Run per window and globally.

THE TRAP, STATED UP FRONT
    Rows here are 80.1 ms. Retriggered samples on a row grid put real peaks at
    80, 160, 240 ms into every one of these methods, and 160 ms is 3.7% away
    from the 166 ms being looked for. Any lag within --grid-tol of a multiple of
    the row period is printed as GRID, and a GRID answer the render reproduces
    is rhythm, not echo. The row period comes from the module when
    --moduledir/--track are given, or from --grid-ms.

WHAT IT MEASURED, 2026-09-14
    Four tracks, 55 s each from the music start, against their renders, with a
    166 ms / 0.33 delay spliced into each capture as the sensitivity control:

        track (capture)       G-CEP at 166 ms    strongest peak 40-600 ms
        1E Gothic                    +0.0006     +0.021 at 41 ms
        39 Theme of Paprium          -0.0006     +0.044 at 48 ms
        16 Dark Rock (control)       +0.0032     +0.035 at 43 ms
        3E Waterfront (control)      +0.0008     +0.016 at 41 ms
        any of them, +166ms/0.33     +0.303      +0.305 at 166 ms

    G-CEP's value at a lag IS the feedback coefficient a delay there would
    carry, so the middle column reads: nothing at 166 ms, in any track, above
    a = 0.003 (-50 dB per repeat). Injecting the believed delay into the SAME
    capture returns +0.303 at exactly 166.0 ms, and a sweep down the feedback
    scale recovers 0.20 -> 0.184, 0.10 -> 0.092, 0.05 -> 0.046, 0.03 -> 0.028,
    with the injected peak still winning the whole range at a = 0.03. So the
    probe is not blind: 166 ms at 33% is refuted by a factor of about 100, and
    NO delay of any length between 40 and 600 ms is present above a = 0.04.
    The 0x4000 constant does not mean a delay line, or does not reach the audio.
    The ~24 ms peak seen in every source, capture and render alike, is this
    script's own lifter corner (1 / --lifter-hz) and is why --lag-min is 40.

Reads the captures and the renders. The output is measurement derived from a
commercial ROM and from recordings of it: keep it local.
"""

import argparse
import json
import os
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CLK = 99.8745
BANDS = [(60, 200), (200, 800), (800, 3000), (3000, 8000), (8000, 15000)]


# ------------------------------------------------------------------ decoding

def decode(path, seconds, rate, start=0.0):
    """Stereo float arrays (L, R) from anything ffmpeg can open."""
    cmd = ["ffmpeg", "-v", "error"]
    if start:
        cmd += ["-ss", "%.6f" % start]
    cmd += ["-t", "%.3f" % seconds, "-i", path, "-map", "a:0",
            "-ac", "2", "-ar", str(rate), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, stdout=subprocess.PIPE, check=True).stdout
    x = np.frombuffer(raw, dtype="<f4").astype(np.float64)
    x = x[:(len(x) // 2) * 2].reshape(-1, 2)
    return np.ascontiguousarray(x[:, 0]), np.ascontiguousarray(x[:, 1])


def music_start(path, rate, look=20.0):
    """Seconds from file start to the first music. Captures open on silence."""
    l, r = decode(path, look, rate)
    x = (l + r) * 0.5
    if len(x) < rate:
        return 0.0
    fr = int(0.01 * rate)
    n = len(x) // fr
    e = np.sqrt((x[:n * fr].reshape(n, fr) ** 2).mean(1))
    floor = float(np.percentile(e[:100], 50))
    thr = max(floor * 20.0, e.max() * 0.02)
    k = int(np.argmax(e > thr))
    return k * 0.01 if e[k] > thr else 0.0


# ------------------------------------------------------------------ dsp bits

def bandpass(x, sr, lo, hi):
    """Brick-wall band limit in the FFT domain. Zero phase, which matters here:
    a phase-shifting filter moves the very repeats we are trying to time."""
    n = len(x)
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(n, 1.0 / sr)
    X[(f < lo) | (f > hi)] = 0.0
    return np.fft.irfft(X, n)


def envelope(x, sr, hop=0.001, frame=0.004):
    """RMS envelope on a fixed hop, by cumulative sum. Returns (env, hop_samples)."""
    h, f = max(int(sr * hop), 1), max(int(sr * frame), 2)
    if len(x) < f + h:
        return np.zeros(0), h
    c = np.concatenate([[0.0], np.cumsum(x * x)])
    n = (len(x) - f) // h + 1
    i = np.arange(n) * h
    return np.sqrt(np.maximum(c[i + f] - c[i], 0.0) / f), h


def rolling(a, k, how):
    """Rolling min/max over a centred window of k samples, edges clamped."""
    k = int(k) | 1
    if k < 3 or len(a) < k:
        return a.copy()
    from numpy.lib.stride_tricks import sliding_window_view
    w = sliding_window_view(a, k)
    v = w.min(1) if how == "min" else w.max(1)
    lo = (k - 1) // 2
    return np.concatenate([np.full(lo, v[0]), v, np.full(k - 1 - lo, v[-1])])


def acf(x, maxlag, unbias=True):
    """Normalised autocorrelation 0..maxlag, rho(0) = 1."""
    n = len(x)
    maxlag = int(maxlag)
    if maxlag < 4 or n < 2 * maxlag:
        return None
    nf = 1 << int(np.ceil(np.log2(2 * n)))
    X = np.fft.rfft(x - x.mean(), nf)
    r = np.fft.irfft(X * np.conj(X), nf)[:maxlag + 1]
    if r[0] <= 0:
        return None
    if unbias:
        r = r / (n - np.arange(maxlag + 1))
    return r / r[0]


def smooth_f(a, k):
    """Box smoother by cumulative sum, used to lifter a spectrum."""
    k = int(k) | 1
    if k < 3:
        return a.copy()
    c = np.concatenate([[0.0], np.cumsum(a)])
    n = len(a)
    i = np.arange(n)
    lo = np.maximum(i - k // 2, 0)
    hi = np.minimum(i + k // 2 + 1, n)
    return (c[hi] - c[lo]) / (hi - lo)


def cepstrum(logspec, sr, nfft, lo, hi):
    """Peak of the real cepstrum of a log POWER spectrum, inside a lag window.

    For a feedback comb with coefficient a,
        log|H(f)|^2 = 2 * sum_k (a^k / k) * cos(k*2*pi*f*D)
    so the cepstral value at quefrency D is a itself. That identity is where the
    feedback figure reported by M3/G-CEP comes from; it is only as good as the
    liftering that removed the source's own spectral envelope, so treat it as an
    estimate to be cross-checked against M4's rho(D) and M2's dB per repeat."""
    c = np.fft.irfft(logspec, nfft)
    q = np.arange(len(c)) / float(sr)
    m = (q >= lo) & (q <= hi)
    if not m.any():
        return None
    sub, qs = c[m], q[m]
    k = int(np.argmax(sub))
    med = float(np.median(np.abs(sub)))
    return dict(lag=float(qs[k]), val=float(sub[k]),
                z=float(sub[k] / med) if med > 0 else 0.0,
                curve=(qs, sub))


def peak_in(rho, sr, lo, hi):
    """Best peak of a correlation curve inside a lag window, with a z-score
    against the spread of the rest of that window."""
    if rho is None:
        return None
    lag = np.arange(len(rho)) / float(sr)
    m = (lag >= lo) & (lag <= hi)
    if m.sum() < 8:
        return None
    sub, ls = rho[m], lag[m]
    k = int(np.argmax(sub))
    others = np.delete(sub, slice(max(0, k - 3), k + 4))
    sd = float(others.std()) if len(others) > 8 else 0.0
    return dict(lag=float(ls[k]), val=float(sub[k]),
                z=float((sub[k] - others.mean()) / sd) if sd > 0 else 0.0,
                curve=(ls, sub))


def peaks_in(ls, vals, k=5, sep=0.010):
    """The k strongest local maxima of a curve, at least sep seconds apart.

    argmax alone is not enough. This music's own bar period is a real, strong
    peak in every one of these curves; an echo at 166 ms can sit underneath it
    and never be the maximum. The list is what gets compared against the
    control, not just the winner."""
    out = []
    v = np.asarray(vals)
    idx = np.argsort(-v)
    for i in idx:
        if any(abs(ls[i] - ls[j]) < sep for j in out):
            continue
        if 0 < i < len(v) - 1 and not (v[i] >= v[i - 1] and v[i] >= v[i + 1]):
            continue
        out.append(int(i))
        if len(out) >= k:
            break
    return [(float(ls[i]), float(v[i])) for i in out]


# ------------------------------------------------------- finding exposed tails

def band_tails(x, sr, min_tail, want, rise_db=6.0, min_drop=10.0):
    """Band-limited decays: a transient in one band with nothing else hitting
    THAT band for min_tail seconds afterwards.

    The full mix never goes quiet in this music, but single bands do. A hat in
    8-15 kHz or a stab in 800-3000 Hz can have a clear half second behind it
    while the other voices carry on elsewhere in the spectrum. Those windows are
    where a delay line - which repeats the band along with everything else - is
    visible without needing the whole arrangement to stop.

    Returns [(exposure_db, t0, t1, lo, hi)], most exposed first."""
    out = []
    for lo, hi in BANDS:
        hi = min(hi, sr * 0.45)
        if lo >= hi:
            continue
        y = bandpass(x, sr, lo, hi)
        e, h = envelope(y, sr, 0.001, 0.004)
        if len(e) < 200:
            continue
        fps = sr / h
        edb = 20.0 * np.log10(np.maximum(e, 1e-9))
        back = rolling(edb, 0.025 * fps, "min")
        loc = rolling(edb, 0.011 * fps, "max")
        hit = np.where((edb - back >= rise_db) & (edb >= loc - 1e-9))[0]
        if len(hit) < 2:
            continue
        nt = int(min_tail * fps)
        guard = int(0.020 * fps)
        for i in hit:
            j = i + nt
            if j >= len(edb):
                break
            if ((hit > i + guard) & (hit <= j)).any():
                continue
            tail = float(edb[j - int(0.06 * fps):j].max())
            drop = float(edb[i]) - tail
            if drop < min_drop:
                continue
            out.append((drop, i / fps, j / fps, lo, hi))
    out.sort(key=lambda z: -z[0])
    keep, used = [], []
    for w in out:
        # keep windows apart in time, so one busy second cannot supply them all
        if any(abs(w[1] - u) < 0.25 and w[3] == b for u, b in used):
            continue
        keep.append(w)
        used.append((w[1], w[3]))
        if len(keep) >= want:
            break
    return keep


def solo_tails(moddir, track, want, seconds, min_tail):
    """Exposed tails from scripts/solo_windows.py, which models voice OCCUPANCY
    rather than onsets - a note still sounding from ten seconds ago disqualifies
    a window, which an onset-only gap test misses.

    Returns (windows, best_clean_after, n_solo_notes). The second and third are
    reported whether or not any window qualifies, because on this corpus they
    are the finding: across Gothic, Theme Of Paprium, Dark Rock and Waterfront
    Beat NO note is ever alone, and the longest stretch after any note before
    another voice speaks is 160 ms - shorter than the 166 ms being tested. That
    is why the per-window methods are structurally blind here and the global
    ones carry the result.

    Imported defensively: solo_windows is a sibling tool under active change,
    and this probe must not fall over if its API moves."""
    try:
        import mwmm
        import solo_windows as sw
    except Exception:
        return [], None, None
    try:
        mods = {m.n: m for m in mwmm.load_all(moddir)}
        if track not in mods:
            return [], None, None
        notes, _ = sw.notes_of(mods[track], seconds + 5.0)
        cands = sw.survey(notes, seconds)
    except Exception as exc:
        print("     (solo_windows unavailable: %s)" % exc)
        return [], None, None
    if not cands:
        return [], None, None
    ca = [c["clean_after"] for c in cands if np.isfinite(c["clean_after"])]
    best = float(max(ca)) if ca else 0.0
    nsolo = sum(1 for c in cands if c["n_others"] == 0)
    out = []
    for c in sorted(cands, key=lambda z: -z["clean_after"]):
        if c["clean_after"] < min_tail or not np.isfinite(c["clean_after"]):
            break
        out.append((c["clean_after"] * 1000.0, c["t"], c["t"] + c["clean_after"], 0, 0))
        if len(out) >= want:
            break
    return out, best, nsolo


def module_gaps(moddir, track, want, seconds):
    """Largest holes in the all-voice onset list, from the solved row clock.
    Also returns the row period, which is what the GRID annotation needs."""
    try:
        import mwmm
        import voice_notes as vn
    except Exception:
        return [], None
    try:
        mods = {m.n: m for m in mwmm.load_all(moddir)}
    except Exception:
        return [], None
    if track not in mods:
        return [], None
    m = mods[track]
    grid = 2 * m.d[0x07] / CLK
    rows, _ = vn.timeline(m, set(range(26)), 1)
    t = np.array(sorted(r[0] for r in rows))
    t = t[t < seconds]
    if len(t) < 4:
        return [], grid
    d = np.diff(t)
    order = np.argsort(-d)[:want]
    return [(float(d[k]), float(t[k]), float(t[k] + d[k]), 0, 0) for k in order], grid


# ------------------------------------------------------------- per-window pass

def window_probe(x, sr, w, lag_lo, lag_hi):
    """M1, M2, M3, M4 on one exposed tail."""
    drop, t0, t1, lo, hi = w
    a = int(t0 * sr)
    b = min(int(t1 * sr), len(x))
    if b - a < int(0.08 * sr):
        return None
    seg = np.ascontiguousarray(x[a:b])
    span = (b - a) / sr
    # A lag is only measurable if the window holds it about twice over, and the
    # autocorrelation needs strictly more than 2x the lag in samples - at 0.60
    # of the span M4 silently returned nothing on every window.
    hl = min(lag_hi, span * 0.45)
    if hl <= lag_lo:
        return None
    band = bandpass(seg, sr, lo, hi) if hi > lo else seg
    res = dict(t0=t0, t1=t1, lo=lo, hi=hi, drop=drop, lag_hi=hl)

    e, h = envelope(band, sr, 0.001, 0.005)
    fps = sr / h

    # M1 - envelope autocorrelation, after the attack, detrended in dB so the
    # note's own decay slope does not dominate the correlation.
    skip = int(0.020 * fps)
    if len(e) > skip + 64:
        edb = 20.0 * np.log10(np.maximum(e[skip:], 1e-9))
        tt = np.arange(len(edb), dtype=float)
        edb = edb - np.polyval(np.polyfit(tt, edb, 1), tt)
        res["m1"] = peak_in(acf(edb, min(hl * fps, len(edb) // 2)), fps, lag_lo, hl)
    else:
        res["m1"] = None

    # M2 - repeat peaks in the tail: their spacing, and the step down between
    # them. A feedback line gives several evenly spaced peaks each a fixed
    # number of dB below the last; one repeat and no more is a slapback.
    res["m2"] = dict(n=0, spacing=None, step=None, npeaks=0)
    if len(e) > 64:
        edb = 20.0 * np.log10(np.maximum(e, 1e-9))
        sm = smooth_f(edb, 0.008 * fps)
        loc = rolling(sm, 0.021 * fps, "max")
        mn = rolling(sm, 0.021 * fps, "min")
        pk = np.where((sm >= loc - 1e-9) & (sm - mn >= 1.5))[0]
        pk = pk[pk > int(0.015 * fps)]
        if len(pk) >= 2:
            sp = np.diff(pk) / fps
            st = np.diff(sm[pk])
            g = (sp >= lag_lo) & (sp <= hl)
            res["m2"] = dict(n=int(g.sum()), npeaks=int(len(pk)),
                             spacing=float(np.median(sp[g])) if g.any() else None,
                             step=float(np.median(st[g])) if g.any() else None)
        else:
            res["m2"]["npeaks"] = int(len(pk))

    # M3 - cepstrum of the tail.
    nf = 1 << int(np.ceil(np.log2(max(len(seg), 1024) * 2)))
    S = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), nf)) ** 2
    ls = np.log(S + S.max() * 1e-10)
    ls = ls - smooth_f(ls, max(40.0 / (sr / nf), 3))
    res["m3"] = cepstrum(ls, sr, nf, lag_lo, hl)

    # M4 - raw waveform autocorrelation. rho(D) IS the feedback coefficient.
    res["m4"] = peak_in(acf(seg, hl * sr), sr, lag_lo, hl)
    return res


# ------------------------------------------------------------- global methods

def global_probe(x, sr, lag_lo, lag_hi, lifter=40.0):
    """The methods that need no exposed tail.

    G-CEP  long-term average power spectrum -> cepstrum. Averaging power spectra
           leaves |H(f)|^2 exactly in place, so a delay's 1/D ripple survives any
           amount of averaging while the music's own spectrum smooths out. This
           is the strongest test available on music this dense.
    G-ACF  frame-averaged RAW waveform autocorrelation; rho(D) = feedback.
    G-ENV  envelope autocorrelation over the whole span. Expected to read the
           RHYTHM. It is printed so the rhythm's lags are on the table by name,
           not mistaken for a delay later.
    """
    out = {}

    nfft = 1 << int(np.ceil(np.log2(sr * 2)))        # ~2 s frames -> ~0.5 Hz bins
    hop = nfft // 2
    win = np.hanning(nfft)
    acc = np.zeros(nfft // 2 + 1)
    nfr = 0
    for i in range(0, len(x) - nfft, hop):
        acc += np.abs(np.fft.rfft(x[i:i + nfft] * win)) ** 2
        nfr += 1
    if nfr:
        acc /= nfr
        ls = np.log(acc + acc.max() * 1e-12)
        ls = ls - smooth_f(ls, max(lifter / (sr / nfft), 3))
        c = cepstrum(ls, sr, nfft, lag_lo, lag_hi)
        if c:
            c["nframes"] = nfr
        out["gcep"] = c
    else:
        out["gcep"] = None

    N = 1 << int(np.ceil(np.log2(4 * lag_hi * sr)))
    ml = int(lag_hi * sr)
    num = np.zeros(ml + 1)
    den = 0.0
    if len(x) >= N + N // 2:
        nf2 = 2 * N
        for i in range(0, len(x) - N, N // 2):
            s = x[i:i + N]
            s = s - s.mean()
            X = np.fft.rfft(s, nf2)
            r = np.fft.irfft(X * np.conj(X), nf2)[:ml + 1]
            num += r
            den += r[0]
        if den > 0:
            rho = (num / den) * (float(N) / (N - np.arange(ml + 1)))
            out["gacf"] = peak_in(rho, sr, lag_lo, lag_hi)
    out.setdefault("gacf", None)

    e, h = envelope(x, sr, 0.002, 0.008)
    if len(e) > 2000:
        fps = sr / h
        edb = 20.0 * np.log10(np.maximum(e, 1e-9))
        edb = edb - smooth_f(edb, 2.0 * fps)
        out["genv"] = peak_in(acf(edb, lag_hi * fps), fps, lag_lo, lag_hi)
    else:
        out["genv"] = None
    return out


# ----------------------------------------------------------------- reporting

def ascii_curve(ls, vals, width=70, height=8, mark=None):
    """A curve the reader can check by eye. One number out of a correlation is
    not evidence anybody can argue with; a shape is."""
    if len(ls) < 2:
        return []
    idx = np.linspace(0, len(ls) - 1, width).astype(int)
    v = vals[idx]
    lo, hi = float(v.min()), float(v.max())
    if hi - lo < 1e-12:
        hi = lo + 1e-12
    rows = []
    for r in range(height, 0, -1):
        thr = lo + (hi - lo) * (r - 0.5) / height
        rows.append("     |" + "".join("#" if z >= thr else " " for z in v))
    rows.append("     +" + "-" * width)
    left = "%.0f" % (ls[idx][0] * 1000)
    right = "%.0f ms" % (ls[idx][-1] * 1000)
    rows.append("      " + left + " " * max(1, width - len(left) - len(right)) + right)
    if mark is not None:
        p = int(np.argmin(np.abs(ls[idx] - mark)))
        rows.insert(height, "     |" + " " * p + "^ %.1f ms" % (mark * 1000))
    return rows


def grid_flag(lag, grid, tol):
    if not grid or not lag:
        return ""
    k = int(round(lag / grid))
    if k >= 1 and abs(lag - k * grid) <= tol * k * grid:
        return "  GRID %dx%.0f" % (k, grid * 1000)
    return ""


def fmt(p, grid, tol):
    if not p:
        return "      --"
    return "%7.1f ms  val %+.3f  z %5.1f%s" % (p["lag"] * 1000, p["val"], p["z"],
                                               grid_flag(p["lag"], grid, tol))


def inject(x, sr, delay, fb):
    """Feed a signal through a known feedback delay: y[n] = x[n] + fb*y[n-D].

    This is what makes a NEGATIVE result mean anything. "The probe found no
    echo" is worth nothing on its own - the probe might simply be blind on this
    material. Running the same probe over the same capture with a known delay
    spliced in shows what a real one would have looked like here, and how small
    a one could still have been seen."""
    d = int(round(delay * sr))
    if d < 1 or d >= len(x):
        return x.copy()
    y = x.copy()
    for i in range(d, len(y)):
        y[i] += fb * y[i - d]
    return y


def run_source(path, label, role, a, grid, spike=None):
    if not os.path.exists(path):
        print("\n!! missing: %s" % path)
        return None
    off = music_start(path, a.rate) if a.align else 0.0
    l, r = decode(path, a.seconds, a.rate, off)
    if len(l) < a.rate * 5:
        print("\n!! %s: less than 5 s of audio decoded" % label)
        return None
    if spike:
        d, fb = spike
        l = inject(l, a.rate, d, fb)
        r = inject(r, a.rate, d, fb)
    mono = (l + r) * 0.5
    lag_lo, lag_hi = a.lag_min / 1000.0, a.lag_max / 1000.0

    print("\n" + "=" * 78)
    print("%-4s %s" % (role.upper(), path))
    if spike:
        print("     SENSITIVITY CONTROL: a known %.1f ms / %.2f feedback delay was "
              "spliced\n     into this source. The probe must find it, or it is blind."
              % (spike[0] * 1000.0, spike[1]))
    print("     %s | music starts %.3f s | %.1f s @ %d Hz | peak %.3f | rms %.4f"
          % (label, off, len(mono) / a.rate, a.rate,
             float(np.abs(mono).max()), float(np.sqrt((mono ** 2).mean()))))

    g = {ch: global_probe(v, a.rate, lag_lo, lag_hi, a.lifter_hz)
         for ch, v in (("mono", mono), ("L", l), ("R", r))}
    print("\n  GLOBAL - no exposed tail needed.  best lag in %.0f-%.0f ms"
          % (a.lag_min, a.lag_max))
    for ch in ("mono", "L", "R"):
        for key, name in (("gcep", "G-CEP"), ("gacf", "G-ACF"), ("genv", "G-ENV")):
            print("     %-5s %-7s %s" % (ch, name, fmt(g[ch][key], grid, a.grid_tol)))
    if a.at:
        # The number that makes a null quantitative. G-CEP's value at a lag IS
        # the feedback coefficient that a delay at that lag would need to have,
        # so reading it off at 166 ms bounds the belief directly.
        print("\n  VALUE AT NAMED LAGS (G-CEP value = the feedback coefficient a")
        print("  that a delay at that lag would have to carry)")
        for ms in [float(z) for z in a.at.split(",")]:
            line = "     %7.1f ms " % ms
            for key, name in (("gcep", "G-CEP"), ("gacf", "G-ACF")):
                p = g["mono"][key]
                if p and "curve" in p:
                    ls, vs = p["curve"]
                    k = int(np.argmin(np.abs(ls - ms / 1000.0)))
                    v = float(vs[k])
                    line += " %s %+.4f (%s dB) " % (
                        name, v, "%.1f" % (20.0 * np.log10(v)) if v > 1e-6 else " -inf")
            print(line)

    for key, name in (("gcep", "G-CEP cepstrum"), ("gacf", "G-ACF waveform autocorrelation")):
        p = g["mono"][key]
        if p and "curve" in p:
            print("\n  %s, mono - top peaks:" % name)
            for lg, vv in peaks_in(p["curve"][0], p["curve"][1], 5):
                print("       %7.1f ms  val %+.3f%s"
                      % (lg * 1000.0, vv, grid_flag(lg, grid, a.grid_tol)))
            for ln in ascii_curve(p["curve"][0], p["curve"][1], mark=p["lag"]):
                print(ln)

    if a.dump:
        # The falsifier you can hear. With --spike this pair is the same seconds
        # of the same capture with and without a known delay: if the hardware
        # already had one, the two would sound alike.
        os.makedirs(a.dump, exist_ok=True)
        nm = os.path.join(a.dump, "AB_%s.wav" % label.replace(":", "-"))
        st = np.stack([l, r], axis=1)
        st = st / max(float(np.abs(st).max()), 1e-9) * 0.89
        wv = wave.open(nm, "wb")
        wv.setnchannels(2)
        wv.setsampwidth(2)
        wv.setframerate(a.rate)
        wv.writeframes((st.reshape(-1) * 32767).astype("<i2").tobytes())
        wv.close()
        print("\n  A/B file: %s" % nm)

    wins = band_tails(mono, a.rate, a.min_tail / 1000.0, a.windows)
    extra = []
    if a.moduledir and a.track:
        gaps, _ = module_gaps(a.moduledir, a.track, 8, a.seconds)
        extra = [(d * 1000.0, t0, t1, 0, int(a.rate * 0.45))
                 for d, t0, t1, _, _ in gaps if d >= a.min_tail / 1000.0]
        solo, best, nsolo = solo_tails(a.moduledir, a.track, 8, a.seconds,
                                       a.min_tail / 1000.0)
        if best is not None:
            print("\n  solo_windows.py on this module: %d notes are alone in the mix;"
                  % nsolo)
            print("  the longest stretch after ANY note before another voice speaks "
                  "is %.0f ms." % (best * 1000.0))
            if best * 1000.0 < a.lag_min:
                print("  That is shorter than the shortest lag being tested (%.0f ms),"
                      % a.lag_min)
                print("  so no module-derived window can carry this measurement at all.")
        extra += [(d, t0, t1, 0, int(a.rate * 0.45)) for d, t0, t1, _, _ in solo]
    allw = wins + extra
    per_band = ", ".join("%d-%dHz x%d" % (lo, hi, sum(1 for w in wins if w[3] == lo))
                         for lo, hi in BANDS if any(w[3] == lo for w in wins))
    print("\n  EXPOSED TAILS >= %.0f ms: %d band-limited (%s); %d from the module"
          % (a.min_tail, len(wins), per_band or "none", len(extra)))

    rows = [p for p in (window_probe(mono, a.rate, w, lag_lo, lag_hi) for w in allw) if p]
    if not rows:
        print("     METHOD BLIND on the per-window tests: no window in this source is")
        print("     long enough to hold a %.0f-%.0f ms lag twice over. What would be"
              % (a.lag_min, a.lag_max))
        print("     needed is a capture that ENDS - the boombox stopped, or a fade -")
        print("     so the delay line empties into silence. Lower --min-tail to see")
        print("     shorter windows, at the cost of the longer lags.")
    else:
        print("     %-4s %-16s %-24s %s" % ("n", "method", "median lag", "detail"))
        for key, name in (("m1", "M1 env-ACF"), ("m3", "M3 cepstrum"),
                          ("m4", "M4 raw-ACF")):
            v = [p[key] for p in rows if p.get(key)]
            if not v:
                print("     %-4d %-16s %-24s" % (0, name, "--"))
                continue
            lags = np.array([z["lag"] for z in v]) * 1000.0
            m = float(np.median(lags))
            iqr = float(np.percentile(lags, 75) - np.percentile(lags, 25)) if len(lags) > 3 else -1
            print("     %-4d %-16s %-24s median val %+.3f  IQR %.0f ms"
                  % (len(v), name, "%.1f ms%s" % (m, grid_flag(m / 1000.0, grid, a.grid_tol)),
                     float(np.median([z["val"] for z in v])), iqr))
        sp = [p["m2"]["spacing"] * 1000.0 for p in rows if p["m2"]["spacing"]]
        st = [p["m2"]["step"] for p in rows if p["m2"]["step"] is not None]
        npk = [p["m2"]["npeaks"] for p in rows]
        print("     %-4d %-16s %-24s median step %+.1f dB/repeat, %.1f peaks/tail"
              % (len(sp), "M2 tail peaks",
                 ("%.1f ms%s" % (float(np.median(sp)),
                                 grid_flag(np.median(sp) / 1000.0, grid, a.grid_tol)))
                 if sp else "--",
                 float(np.median(st)) if st else 0.0,
                 float(np.median(npk)) if npk else 0.0))
        if a.dump:
            os.makedirs(a.dump, exist_ok=True)
            n = 0
            for p in sorted(rows, key=lambda z: -z["drop"])[:a.dump_n]:
                s = mono[int(max(p["t0"] - 0.10, 0) * a.rate):
                         int((p["t1"] + 0.15) * a.rate)]
                if not len(s):
                    continue
                s = s / max(float(np.abs(s).max()), 1e-9) * 0.9
                nm = "%s_%07.3fs_%d-%dHz_drop%02.0fdB.wav" % (
                    label.replace(":", "-"), p["t0"], p["lo"], p["hi"], p["drop"])
                wv = wave.open(os.path.join(a.dump, nm), "wb")
                wv.setnchannels(1)
                wv.setsampwidth(2)
                wv.setframerate(a.rate)
                wv.writeframes((s * 32767).astype("<i2").tobytes())
                wv.close()
                n += 1
            print("     wrote %d tail clips to %s" % (n, a.dump))

    return dict(label=label, role=role, path=path, offset=off, glob=g, windows=rows,
                spike=list(spike) if spike else None)


def verdict(results, a, grid):
    hw = [r for r in results if r and r["role"] == "hw"]
    ref = [r for r in results if r and r["role"] == "ref"]
    print("\n" + "=" * 78)
    print("VERDICT")
    print("=" * 78)
    if not hw:
        print("  No hardware source was given.")
        return
    if not ref:
        print("  NO CONTROL WAS RUN. Without a --ref render this probe cannot tell an")
        print("  echo from the music's own rhythm. Treat every number above as unproven.")
        return

    def pick(r, key, ch="mono"):
        p = r["glob"][ch][key]
        return (p["lag"] * 1000.0, p["val"], p["z"]) if p else (None, 0.0, 0.0)

    print("  %-7s %-16s %-26s %s" % ("method", "source", "HARDWARE", "RENDER (no echo)"))
    agree = []
    for key, name in (("gcep", "G-CEP"), ("gacf", "G-ACF"), ("genv", "G-ENV")):
        for h in hw:
            hl, hv, hz = pick(h, key)
            for c in ref:
                rl, rv, rz = pick(c, key)
                print("  %-7s %-16s %-26s %s"
                      % (name, h["label"][:16],
                         ("%7.1f ms  val %+.3f  z%5.1f" % (hl, hv, hz)) if hl else "--",
                         ("%7.1f ms  val %+.3f  z%5.1f" % (rl, rv, rz)) if rl else "--"))
                if hl and rl:
                    agree.append((name, h["label"], hl, hv, hz, rl, rv,
                                  abs(hl - rl) <= a.grid_tol * max(hl, rl)))
                break

    # The discriminator. Both curves live on the same lag axis, so subtracting
    # the control from the hardware removes everything the music does by itself
    # and leaves only what the hardware adds. A delay line survives this; a bar
    # period does not.
    print("\n  DIFFERENTIAL  hardware minus control, mono. Only what the hardware")
    print("  ADDS survives this subtraction - the music's own rhythm cancels.")
    for key, name in (("gcep", "G-CEP"), ("gacf", "G-ACF")):
        for h in hw:
            hp = h["glob"]["mono"][key]
            for c in ref:
                cp = c["glob"]["mono"][key]
                if not hp or not cp or "curve" not in hp or "curve" not in cp:
                    continue
                n = min(len(hp["curve"][1]), len(cp["curve"][1]))
                ls = hp["curve"][0][:n]
                d = hp["curve"][1][:n] - cp["curve"][1][:n]
                print("\n    %s  %s  -  %s" % (name, h["label"][:20], c["label"][:20]))
                for lg, vv in peaks_in(ls, d, 4):
                    print("       %7.1f ms  delta %+.3f%s"
                          % (lg * 1000.0, vv, grid_flag(lg, grid, a.grid_tol)))
                for ln in ascii_curve(ls, d, mark=float(ls[int(np.argmax(d))])):
                    print(ln)

    print()
    same = [x for x in agree if x[7]]
    if same:
        print("  THE PROBE IS READING THE MUSIC, NOT A DELAY LINE, on: %s"
              % ", ".join("%s (%.0f ms in both)" % (x[0], x[2]) for x in same))
        print("  Our render has no delay line at all, so any lag it reproduces is the")
        print("  note grid. Those rows are worthless as echo evidence.")
    live = [x for x in agree if not x[7]]
    if live:
        print("  Lags present in hardware that the render does NOT show:")
        for name, lab, hl, hv, hz, rl, rv, _ in live:
            print("     %-7s %-16s hw %7.1f ms (val %+.3f, z %.1f) vs render %7.1f ms"
                  "  %s" % (name, lab[:16], hl, hv, hz, rl,
                            grid_flag(hl / 1000.0, grid, a.grid_tol) or "off-grid"))
        for h in hw:
            fb = [x[3] for x in live
                  if x[1] == h["label"] and x[0] in ("G-CEP", "G-ACF") and x[3] > 0]
            if fb:
                aa = float(np.median(fb))
                print("     %-16s implied feedback a ~ %.3f = %.1f dB per repeat"
                      % (h["label"][:16], aa, 20.0 * np.log10(max(aa, 1e-6))))
    else:
        print("  Nothing in hardware that the render does not also show.")
    spk = [r for r in results if r and r["role"] == "spk"]
    if spk:
        print("\n  SENSITIVITY CONTROL - the same probe on the same hardware audio with")
        print("  a KNOWN delay spliced in. This is what a real one would have looked")
        print("  like in this material, and it is the only thing that makes the null")
        print("  above mean anything.")
        for s in spk:
            d, fb = s["spike"]
            for key, name in (("gcep", "G-CEP"), ("gacf", "G-ACF")):
                p = s["glob"]["mono"][key]
                if not p:
                    continue
                hit = abs(p["lag"] - d) <= 0.02 * d
                print("     %-7s injected %6.1f ms fb %.2f -> found %7.1f ms val %+.3f"
                      "  %s" % (name, d * 1000.0, fb, p["lag"] * 1000.0, p["val"],
                                "RECOVERED" if hit else "MISSED - PROBE IS BLIND HERE"))
        for h in hw:
            for key, name in (("gcep", "G-CEP"), ("gacf", "G-ACF")):
                p = h["glob"]["mono"][key]
                if p:
                    print("     %-7s %-16s real capture, strongest anything in the"
                          " range: val %+.3f at %.1f ms"
                          % (name, h["label"][:16], p["val"], p["lag"] * 1000.0))
    else:
        print("\n  No --spike control was run. A null from this probe is not evidence")
        print("  of no echo until --spike shows the probe can see one in this audio.")

    print()
    print("  A delay is only proven here when the lag is (a) absent from the render,")
    print("  (b) off the row grid, and (c) the same across methods and channels.")
    print("  Anything less is stated as inconclusive, not as a measurement.")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hw", action="append", default=[],
                    help="hardware capture (.mkv/.wav). repeatable")
    ap.add_argument("--ref", action="append", default=[],
                    help="CONTROL with no echo - our own render. repeatable")
    ap.add_argument("--moduledir", default=None)
    ap.add_argument("--track", type=int, default=None,
                    help="module number: gives the row grid and the full-mix gaps")
    ap.add_argument("--grid-ms", type=float, default=None,
                    help="row period in ms, when --moduledir is not to hand")
    ap.add_argument("--grid-tol", type=float, default=0.03,
                    help="relative tolerance for calling a lag GRID-aligned")
    ap.add_argument("--seconds", type=float, default=55.0)
    ap.add_argument("--rate", type=int, default=32000,
                    help="analysis rate. 32000 matches the render's own bandwidth, "
                         "which keeps hardware and control comparable")
    ap.add_argument("--lag-min", type=float, default=40.0,
                    help="ms. Below this the cepstrum reads note harmonics rather "
                         "than a delay, and the lifter's own corner at "
                         "1/--lifter-hz (25 ms at the default) sits there too - it "
                         "appears in the renders as well, which is how it was caught")
    ap.add_argument("--lag-max", type=float, default=600.0)
    ap.add_argument("--min-tail", type=float, default=300.0,
                    help="ms of exposed decay a per-window test needs")
    ap.add_argument("--windows", type=int, default=40)
    ap.add_argument("--align", action="store_true", default=True)
    ap.add_argument("--no-align", dest="align", action="store_false")
    ap.add_argument("--lifter-hz", type=float, default=40.0,
                    help="width in Hz of the box that removes the source's own "
                         "spectral envelope before the global cepstrum. A real comb "
                         "does not move when this changes; a liftering artefact does")
    ap.add_argument("--at", default="166",
                    help="comma-separated lags in ms to read the curves at, whether "
                         "or not there is a peak there. 166 is the belief under test")
    ap.add_argument("--spike", default=None, metavar="MS,FB",
                    help="sensitivity control: also run each --hw source with a "
                         "known delay spliced in, e.g. 166,0.33. A null result is "
                         "only worth quoting when this comes back positive - it is "
                         "what proves the probe can see an echo in THIS material. "
                         "Repeat with a small FB to find the detection floor")
    ap.add_argument("--dump", default=None, help="write the best tails here as wav")
    ap.add_argument("--dump-n", type=int, default=6)
    ap.add_argument("--json", default=None)
    a = ap.parse_args()

    grid = a.grid_ms / 1000.0 if a.grid_ms else None
    if grid is None and a.moduledir and a.track:
        _, grid = module_gaps(a.moduledir, a.track, 1, a.seconds)
    if grid:
        print("row period %.1f ms -> grid lags at %s ms"
              % (grid * 1000.0,
                 ", ".join("%.0f" % (k * grid * 1000.0) for k in range(1, 8))))
    else:
        print("no row grid given (--moduledir/--track or --grid-ms): rhythm lags "
              "will not be flagged")

    spike = None
    if a.spike:
        ms, _, fb = a.spike.partition(",")
        spike = (float(ms) / 1000.0, float(fb or 0.33))

    results = []
    for i, p in enumerate(a.hw):
        results.append(run_source(
            p, "hw%d:%s" % (i + 1, os.path.splitext(os.path.basename(p))[0][:12]),
            "hw", a, grid))
        if spike:
            results.append(run_source(
                p, "spk%d:%s" % (i + 1, os.path.splitext(os.path.basename(p))[0][:11]),
                "spk", a, grid, spike))
    for i, p in enumerate(a.ref):
        results.append(run_source(
            p, "ref%d:%s" % (i + 1, os.path.splitext(os.path.basename(p))[0][:12]),
            "ref", a, grid))
    verdict(results, a, grid)

    if a.json:
        def strip(o):
            if isinstance(o, dict):
                return {k: strip(v) for k, v in o.items() if k != "curve"}
            if isinstance(o, list):
                return [strip(v) for v in o]
            if isinstance(o, (np.floating, np.integer)):
                return float(o)
            return o
        with open(a.json, "w") as fh:
            json.dump(strip(results), fh, indent=1)
        print("\nwrote %s" % a.json)


if __name__ == "__main__":
    main()
