#!/usr/bin/env python3
"""Find the moments where exactly ONE voice is playing, and cut them out.

    python scripts/solo_windows.py <moduledir> <track> [--seconds 60]
    python scripts/solo_windows.py <moduledir> <track> --extract <capture.mkv>
                                   --render <render.wav> --out <dir>

Paprium's music is 26 voices deep - 6 FM, 4 PSG, 16 wave - and a hardware
capture is a stereo mix of all of them. That makes whole-track statistics
useless for judging one instrument: a band average or a chroma correlation over
sixty seconds cannot see three voices out of twenty-six, and trying it has
already produced one wrong answer on this project. If a claim is going to be
made about an instrument being too loud, too bright, or missing, it has to rest
on a moment where that instrument is the only thing making a sound.

This script finds those moments. For every note in the module it asks whether
any OTHER voice is sounding, or starts sounding, anywhere inside a guard window
around the onset. What survives is the list of places in the track where a
capture can be attributed to a single instrument.

WHAT "SOUNDING" MEANS. The same thing it means in the renderer, because the two
have to agree or the extracted pairs do not line up. The event timeline comes
from render_wave.event_timeline(), unmodified: a note lasts until that voice's
next NOTE or gate release (0x0E), is never cut short by a parameter-only record,
and is clamped to [0.05, 4.0] s the way render() clamps it. Program (0x0F) and
pan (0x02) are tracked over every record, so a note carries the program actually
in force when it starts.

OCCUPANCY IS DELIBERATELY PESSIMISTIC. A note occupies its voice even when the
renderer would drop it - unknown wave program, pitch out of range - because
hardware still plays it and it still contaminates the capture. The candidate's
own `rendered` flag says whether OUR renderer would have placed it, which is a
different and equally interesting question: a solo note that is missing from the
render is exactly the "missing instruments even?" case.

THE SAX MAN IS OFF, matching render_wave's default. Voices carrying the 0x55
marker are an option the player enables in the boombox; the plain captures do
not contain him and the renderer mutes him, so he is ignored on both sides here
- neither a candidate nor a masker. --sax puts him back on both.

KNOWN BLIND SPOTS. A window this script calls isolated can still be contaminated:
  * Echo. The cartridge appears to run a ~166 ms delay at about a third
    feedback, and it is not in the renderer at all. A note 200 ms after a loud
    passage has that passage's tail underneath it. That is what --guard-before
    is for: the 250 ms default clears one echo tap, 700 ms clears three.
  * A note held past 4 s. The renderer stops there and so does this occupancy
    model, so a genuinely sustained pad is invisible beyond that point.
  * The voice's own previous note, whose 40 ms release ramp overlaps the onset
    when the part is legato. `same` in the table is the distance back to it.
  * Reverb, and anything hardware does that is not in the module data.
None of these are visible from module data. They are reported, not assumed away.

--extract cuts each window out of the capture's audio and out of a render, into
a matched pair of wavs plus an A/B file holding both in sequence. The render is
scaled by ONE global gain measured over the whole aligned overlap, so a per-note
level difference in the output is a real difference and not a mastering offset.
Alignment is measured, not assumed, by cross-correlating the two ONSET-FLUX
curves - where the notes attack, which is the one thing a render and a cartridge
agree about - then re-measuring the lag in overlapping chunks and taking the
median. Every part of that is printed, including the chunks that disagreed and
an independent first-sound check, so an alignment that locked onto the wrong bar
announces itself instead of quietly cutting the wrong seconds.

Derived from a commercial ROM. Modules, captures, renders and everything this
writes stay out of the repo.
"""

import argparse
import json
import os
import subprocess
import sys
import wave

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mwmm
import render_wave

if not hasattr(render_wave, "event_timeline"):
    raise SystemExit(
        "render_wave.py has no event_timeline(). This script reuses the renderer's own\n"
        "note timeline on purpose and will not reimplement the clock beside it.")

NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
INF = float("inf")
# Brightness is compared inside a band both sides actually have. A 32 kHz render
# is empty above 16 kHz and a 48 kHz capture is not, so an unrestricted spectral
# centroid would call the hardware brighter by construction.
FMAX = 12000.0


def kind_of(v):
    return "FM" if v < 6 else ("PSG" if v < 10 else "WAVE")


def note_name(midi):
    return "%s%d" % (NAMES[midi % 12], midi // 12 - 1)


def jsafe(o):
    """JSON has no infinity. Gaps with nothing on the other side become null."""
    if isinstance(o, dict):
        return {k: jsafe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsafe(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return round(f, 6) if np.isfinite(f) else None
    return o


# ----------------------------------------------------------------- the notes

def notes_of(m, seconds, anchor=11, rate=32000, sax=False, progs=None):
    """Every note the module plays, as dicts, on the renderer's own rules.

    t / dur / end are onset, sounding length and stop, in seconds. prog and pan
    are what is in force at the onset. `rendered` is whether render_wave would
    actually place this note, and `why` says what stopped it.

    The list runs past `seconds` - event_timeline overshoots by four seconds -
    and that is on purpose: a note starting just after the horizon still masks a
    candidate just before it.
    """
    muted = set() if sax else render_wave.sax_voices(m)
    prog = {v: (m.d[0x2A + (v ^ 1)] or None) for v in range(26)}
    pan = {v: 0x80 for v in range(26)}
    out, prev_on = [], {}
    for tt, v, e, end in render_wave.event_timeline(m, seconds):
        # identical to render()'s loop: commands first, then the note test, so a
        # record carrying both a 0x0F and a note uses the NEW program
        for k in (2, 4, 6):
            if e[k] == 0x0F:
                prog[v] = e[k + 1]
            elif e[k] == 0x02:
                pan[v] = e[k + 1]
        if not (1 <= e[0] <= 12):
            continue
        if v in muted:
            continue                      # not in the render, not in the capture
        midi = 12 * e[1] + e[0] + anchor
        f = 440.0 * 2.0 ** ((midi - 69) / 12.0)
        dur = min(max(end - tt, 0.05), 4.0)          # render_wave's own clamp
        why = ""
        if int(dur * rate) < 16:
            why = "under 16 samples"
        elif f < 20:
            why = "below 20 Hz"
        elif f > rate * 0.45:
            why = "above 0.45*rate"
        elif v >= 10 and progs is not None and prog[v] not in progs:
            why = "program 0x%02X not in the wave bank" % (prog[v] or 0)
        out.append(dict(t=tt, dur=dur, end=tt + dur, voice=v, kind=kind_of(v),
                        prog=prog[v], pan=pan[v], byte0=e[0], byte1=e[1],
                        midi=midi, note=note_name(midi), hz=f,
                        rendered=not why, why=why,
                        prev_same_voice_dt=tt - prev_on[v] if v in prev_on else INF))
        prev_on[v] = tt
    return out, sorted(muted)


# --------------------------------------------------------------- the windows

def survey(notes, horizon, guard_before=0.25, guard_after=0.40,
           min_sounding=0.12, voices=None, pad=0.05, tail=0.25):
    """Every eligible note, told how many OTHER voices share its guard window.

    A note at t0 on voice v is isolated when every note on every other voice has
    a sounding interval that misses [t0 - guard_before, t0 + guard_after]. The
    test is on INTERVALS, not onsets: a note that started ten seconds ago and is
    still running disqualifies the window, which an onset-only test would miss.

    Nothing is filtered out here. `n_others` is returned for every note so the
    caller can say what the BEST any note in this track manages is - which on a
    dense track is the only useful thing to say, and is a real finding rather
    than an empty list.
    """
    if not notes:
        return []
    t0s = np.array([n["t"] for n in notes])
    t1s = np.array([n["end"] for n in notes])
    vs = np.array([n["voice"] for n in notes])
    progs = [n["prog"] for n in notes]
    out = []
    for n in notes:
        if n["t"] > horizon or n["dur"] < min_sounding:
            continue
        if voices is not None and n["voice"] not in voices:
            continue
        t0 = n["t"]
        other = vs != n["voice"]
        hit = other & (t0s < t0 + guard_after) & (t1s > t0 - guard_before)
        seen = {}
        for i in np.nonzero(hit)[0]:
            seen.setdefault(int(vs[i]), progs[i])
        before, after = other & (t1s <= t0), other & (t0s >= t0)
        gap_before = t0 - float(t1s[before].max()) if before.any() else INF
        clean_after = float(t0s[after].min()) - t0 if after.any() else INF
        # keep the note and its decay, cut the moment anything else can be heard
        span = min(clean_after, n["dur"] + tail) if not seen else n["dur"] + tail
        w = dict(n)
        w.update(gap_before=gap_before, clean_after=clean_after,
                 n_others=len(seen), others=sorted(seen),
                 others_prog=["v%d:0x%02X" % (v, p) for v, p in sorted(seen.items())
                              if p is not None],
                 win_start=t0 - pad, win_len=pad + span, meas_len=span)
        out.append(w)
    return out


# ------------------------------------------------------------------ audio io

def read_wav(path):
    w = wave.open(path, "rb")
    n, ch, sw, sr = w.getnframes(), w.getnchannels(), w.getsampwidth(), w.getframerate()
    raw = w.readframes(n)
    w.close()
    if sw != 2:
        raise SystemExit("%s is %d-bit; only 16-bit PCM is handled here" % (path, sw * 8))
    return np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, ch) / 32768.0, sr


def write_wav(path, a, sr):
    a = np.clip(a, -1.0, 1.0)
    w = wave.open(path, "wb")
    w.setnchannels(a.shape[1] if a.ndim > 1 else 1)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes((a.reshape(-1) * 32767).astype("<i2").tobytes())
    w.close()


def capture_audio(mkv, cache_dir, rate=48000):
    """Decode the capture's audio ONCE to a cached wav, then slice it in numpy.

    One ffmpeg call per window would be a hundred seeks into an h264 mkv, each
    one accurate only to whatever the demuxer feels like; this is a single
    linear decode and every cut after it is exact to the sample.
    """
    stem = os.path.splitext(os.path.basename(mkv))[0].replace(" ", "_")
    out = os.path.join(cache_dir, "_decoded_%s_%d.wav" % (stem, rate))
    if not (os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(mkv)):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", mkv, "-vn",
                        "-ac", "2", "-ar", str(rate), "-acodec", "pcm_s16le", out],
                       check=True)
    return read_wav(out)


FPS = 200.0          # feature frame rate for alignment, 5 ms per frame


def envelope(a, sr, fps=FPS):
    """Short-term RMS of the mono sum."""
    x = a.mean(axis=1) if a.ndim > 1 else a
    hop = max(int(round(sr / fps)), 1)
    n = len(x) // hop
    return np.sqrt((x[:n * hop].reshape(n, hop) ** 2).mean(axis=1)) if n > 1 else np.zeros(0)


def onset_flux(a, sr, fps=FPS, nfft=1024):
    """Half-wave-rectified spectral flux: where the music ATTACKS.

    Alignment used to run on the RMS envelope and it was wrong, not marginally
    but by seconds - it put Electro Acid Funk at -7.7 s with a correlation of
    0.24, and its best lag moved to a different answer every time the length of
    the compared span changed. The reason is that a render and a cartridge do
    not agree about LOUDNESS, so a loudness curve mostly measures the disagreement
    - and on a looping dance track the curve repeats every bar anyway, so the
    correlation has one broad flat ridge with no peak on it.

    Flux asks the one question the two do agree on: when does a new note start.
    On the same file it puts the lag at +1.270 s, which is the capture's own
    first onset to within 25 ms, and it holds that answer in every eight-second
    chunk from 5 s to 63 s.
    """
    x = a.mean(axis=1) if a.ndim > 1 else a
    hop = max(int(round(sr / fps)), 1)
    n = (len(x) - nfft) // hop
    if n < 2:
        return np.zeros(0)
    idx = np.arange(nfft)[None, :] + hop * np.arange(n)[:, None]
    mag = np.abs(np.fft.rfft(x[idx] * np.hanning(nfft), axis=1))
    d = np.diff(mag, axis=0)
    d[d < 0] = 0.0
    return np.concatenate([[0.0], d.sum(axis=1)])


def first_sound(a, sr, frac=0.02, fps=FPS):
    """When the file stops being silent: the independent check on the correlation,
    and the only one that does not care about bar periodicity.

    This reads the RMS ENVELOPE, not the flux, and the difference matters. Run on
    flux against a percentile of the whole track it reported Electro Acid Funk's
    render as starting at 7.830 s, because that render's solo bass intro sits
    15 dB below the body of the track and never crosses a threshold scaled to the
    body. Silence, unlike loudness, is a thing the two recordings agree on.
    """
    e = envelope(a, sr, fps)
    if not len(e):
        return None
    hot = np.nonzero(e > frac * np.percentile(e, 95))[0]
    return float(hot[0]) / fps if len(hot) else None


def xcorr_lag(c, r, max_lag_s, fps=FPS):
    """Lag in seconds that best aligns envelope r onto envelope c, and its peak.

    Positive means the capture is LATE: capture[t] matches render[t - lag]. Both
    are normalised and zero-padded, so the peak reads as a correlation
    coefficient and a weak one means the alignment should not be believed.
    """
    if len(c) < 8 or len(r) < 8:
        return 0.0, 0.0
    a, b = c - c.mean(), r - r.mean()
    if a.std() <= 0 or b.std() <= 0:
        return 0.0, 0.0
    a, b = a / a.std(), b / b.std()
    size = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    cc = np.fft.irfft(np.fft.rfft(a, size) * np.conj(np.fft.rfft(b, size)), size)
    cc /= min(len(a), len(b))
    k = min(int(round(max_lag_s * fps)), size // 2 - 1)
    lags = np.concatenate([np.arange(0, k + 1), np.arange(size - k, size)])
    j = int(np.argmax(cc[lags]))
    lag = lags[j] if lags[j] <= k else lags[j] - size
    return lag / fps, float(cc[lags][j])


def align(cap, csr, ren, rsr, seconds, max_lag_s=30.0, span=8.0, step=5.0,
          min_corr=0.30, tol=0.05):
    """Measure capture time as a linear function of module time.

        capture_t = offset + (1 + drift) * module_t

    The offset comes from a global flux cross-correlation; the drift comes from
    re-measuring the lag in overlapping chunks across the track and fitting a
    line through the confident ones. A cartridge clock and a 99.8745 Hz software
    clock do not have to run at the same speed, and if they do not then no
    single offset can serve a whole track - so this measures rather than hopes.
    On Electro Acid Funk the fit comes back at +1.270 s with a drift of
    0.0000 s/s, i.e. the solved clock and the hardware agree exactly over 60 s.

    Everything measured is returned, including the runner-up lag: on a looping
    track the competing peaks sit one bar apart, and a small margin over the
    runner-up is the signature of an alignment that has locked onto the wrong bar.
    """
    fc = onset_flux(cap, csr)[:int((seconds + max_lag_s + span) * FPS)]
    fr = onset_flux(ren, rsr)[:int(seconds * FPS)]
    off, peak = xcorr_lag(fc, fr, max_lag_s)

    # runner-up, ignoring everything within half a second of the winner
    runner = (None, 0.0)
    k = int(max_lag_s * FPS)
    if len(fc) > 8 and len(fr) > 8:
        a, b = fc - fc.mean(), fr - fr.mean()
        if a.std() > 0 and b.std() > 0:
            size = 1 << int(np.ceil(np.log2(len(a) + len(b))))
            cc = np.fft.irfft(np.fft.rfft(a / a.std(), size) *
                              np.conj(np.fft.rfft(b / b.std(), size)), size)
            cc /= min(len(a), len(b))
            lags = np.concatenate([np.arange(0, k + 1), np.arange(size - k, size)])
            vals, secs = cc[lags], np.where(lags <= k, lags, lags - size) / FPS
            far = np.abs(secs - off) > 0.5
            if far.any():
                j = int(np.argmax(vals[far]))
                runner = (float(secs[far][j]), float(vals[far][j]))

    # An independent estimate that cannot be fooled by bar periodicity: line the
    # two files' first sounds up. It is coarse - it says nothing about drift -
    # but it is the only check that knows which bar is the FIRST one.
    cf, rf = first_sound(cap, csr), first_sound(ren, rsr)
    naive = (cf - rf) if (cf is not None and rf is not None) else None

    best = None
    for centre in [c for c in (off, naive) if c is not None]:
        cand = _consensus(fc, fr, centre, seconds, span, step, min_corr, tol)
        if best is None or (cand["score"], cand["inliers"]) > (best["score"], best["inliers"]):
            best = cand
    if best is None:
        best = dict(offset=off, drift=0.0, chunks=[], inliers=0, outliers=0, score=0.0)

    return dict(offset=float(best["offset"]), drift=float(best["drift"]),
                peak=float(peak), runner_lag=runner[0], runner_peak=runner[1],
                chunks=best["chunks"], confident=best["inliers"],
                outliers=best["outliers"], chunk_corr=best["score"],
                coarse_offset=float(off), capture_first_onset=cf,
                render_first_onset=rf,
                naive_offset=float(naive) if naive is not None else None)


def _consensus(fc, fr, centre, seconds, span, step, min_corr, tol):
    """Re-measure the lag in overlapping chunks around `centre`, then agree.

    The agreement is a MEDIAN and not a least-squares fit, and that is the whole
    point. Chunk lags on a looping track do not scatter randomly - a chunk that
    mislocks lands a whole bar away, and one such outlier drags a fitted line
    into inventing a tempo drift that is not there. It did exactly that on
    Gothic: nine chunks said +1.455 s, two mislocked a bar early, and the fit
    reported 0.0087 s/s of drift and an offset 0.35 s off the truth. The median
    ignores them, and the drift is then fitted only through the inliers - and
    only reported at all when it is bigger than the tolerance it was measured
    with.
    """
    chunks = []
    t0 = 0.0
    while t0 + span <= seconds:
        a = fr[int(t0 * FPS):int((t0 + span) * FPS)]
        if len(a) > 32 and a.std() > 0:
            a = (a - a.mean()) / a.std()
            top = (-9.0, 0.0)
            for L in np.arange(t0 + centre - 1.0, t0 + centre + 1.0, 1.0 / FPS):
                j = int(round(L * FPS))
                if j < 0 or j + len(a) > len(fc):
                    continue
                q = fc[j:j + len(a)]
                s = q.std()
                if s <= 0:
                    continue
                v = float((a * ((q - q.mean()) / s)).mean())
                if v > top[0]:
                    top = (v, L - t0)
            if top[0] > -9.0:
                chunks.append((t0, top[1], top[0]))
        t0 += step

    good = [(t, l, c) for t, l, c in chunks if c >= min_corr]
    if not good:
        return dict(offset=centre, drift=0.0, chunks=chunks, inliers=0,
                    outliers=len(chunks), score=0.0)
    base = float(np.median([l for _, l, _ in good]))
    inl = [(t, l, c) for t, l, c in good if abs(l - base) <= tol]
    drift = 0.0
    if len(inl) >= 4 and (inl[-1][0] - inl[0][0]) > 0.4 * seconds:
        d, b = np.polyfit([t for t, _, _ in inl], [l for _, l, _ in inl], 1)
        if abs(d * seconds) > tol:        # only report drift we can actually see
            drift, base = float(d), float(b)
    return dict(offset=base, drift=drift, chunks=chunks, inliers=len(inl),
                outliers=len(good) - len(inl),
                score=float(np.mean([c for _, _, c in inl])) if inl else 0.0)


def slice_at(a, sr, t, length):
    i0 = int(round(t * sr))
    i1 = i0 + int(round(length * sr))
    return a[i0:i1] if 0 <= i0 and i1 <= len(a) else None


def resample_to(a, sr, new_sr):
    if sr == new_sr:
        return a
    n = int(round(len(a) * new_sr / float(sr)))
    src, dst = np.arange(len(a)), np.arange(n) * (sr / float(new_sr))
    return np.stack([np.interp(dst, src, a[:, c]) for c in range(a.shape[1])], axis=1)


def rms_db(a):
    v = float(np.sqrt((a ** 2).mean())) if len(a) else 0.0
    return 20.0 * np.log10(v) if v > 1e-9 else -120.0


def centroid_hz(a, sr, fmax=FMAX):
    """Energy-weighted mean frequency under fmax: the crude reading of 'bright'.

    Band-limited so a 32 kHz render and a 48 kHz capture are asked the same
    question. It is a summary, not a verdict - two different spectra can share a
    centroid, so use it to rank windows and then LISTEN to the A/B file.
    """
    x = a.mean(axis=1) if a.ndim > 1 else a
    if len(x) < 64:
        return 0.0
    mag = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    f = np.fft.rfftfreq(len(x), 1.0 / sr)
    keep = f <= fmax
    mag, f = mag[keep], f[keep]
    s = mag.sum()
    return float((mag * f).sum() / s) if s > 0 else 0.0


# ---------------------------------------------------------------- extraction

def extract(cands, mkv, renwav, outdir, seconds, offset=None, refine=0.0,
            gap=0.25, max_lag_s=30.0):
    os.makedirs(outdir, exist_ok=True)
    cap, csr = capture_audio(mkv, outdir)
    ren, rsr = read_wav(renwav)

    auto = offset is None
    al = None
    drift = 0.0
    if auto:
        al = align(cap, csr, ren, rsr, seconds, max_lag_s)
        offset, drift = al["offset"], al["drift"]

    # ONE global gain for the whole run: per-window normalisation would erase
    # the very thing the player is asking about.
    t = max(offset, 0.0)
    ov = min(seconds, len(ren) / float(rsr), len(cap) / float(csr) - t)
    cs = slice_at(cap, csr, t, ov) if ov > 1.0 else None
    rs = ren[:int(ov * rsr)] if ov > 1.0 else None
    g_db = (rms_db(cs) - rms_db(rs)) if cs is not None else 0.0
    gain = 10.0 ** (g_db / 20.0)

    print("capture : %s  (%.1f s @ %d Hz)" % (os.path.basename(mkv), len(cap) / csr, csr))
    print("render  : %s  (%.1f s @ %d Hz)" % (os.path.basename(renwav), len(ren) / rsr, rsr))
    if auto:
        print("offset  : %+.3f s, drift %+.5f s/s   (%d chunks agree, %d mislocked,"
              " mean chunk corr %.3f)"
              % (offset, drift, al["confident"], al["outliers"], al["chunk_corr"]))
        print("          coarse flux correlation %+.3f s at peak %.3f; first-sound check %s"
              % (al["coarse_offset"], al["peak"],
                 ("%+.3f s" % al["naive_offset"]) if al["naive_offset"] is not None
                 else "n/a"))
        if al["runner_lag"] is not None:
            print("          runner-up lag %+.3f s at %.3f - a thin margin here means the"
                  " lock may be one bar out" % (al["runner_lag"], al["runner_peak"]))
        if al["naive_offset"] is not None and abs(al["naive_offset"] - offset) > 0.15:
            print("  WARNING: the first-sound check says %+.3f s, %.3f s from the chosen"
                  " offset.\n           One of them is wrong. Listen to a pair before"
                  " believing any number below."
                  % (al["naive_offset"], abs(al["naive_offset"] - offset)))
        if al["confident"] < 3:
            print("  WARNING: only %d chunks agreed - there is no consensus and this offset"
                  " is a guess." % al["confident"])
        if al["chunk_corr"] < 0.30:
            print("  WARNING: mean chunk correlation %.3f is weak. The render may be too far"
                  " from the\n           capture to align, or they are not the same"
                  " performance." % al["chunk_corr"])
        if al["outliers"] and al["runner_peak"] > 0.9 * al["peak"]:
            print("  WARNING: %d chunk(s) locked a bar away and the runner-up peak is nearly"
                  " as strong\n           as the winner. This track loops; check a pair by"
                  " ear." % al["outliers"])
        if abs(drift) > 1e-4:
            print("  WARNING: drift %+.5f s/s is %.2f s across %.0f s. It is applied, but"
                  " late windows\n           are the least trustworthy."
                  % (drift, drift * seconds, seconds))
        if abs(abs(offset) - max_lag_s) < 1e-6:
            print("  WARNING: the offset sits on the search limit; raise --max-lag.")
    else:
        print("offset  : %+.3f s (given)" % offset)
    print("gain    : render scaled %+.2f dB onto the capture's overall RMS" % g_db)
    print("")

    renv = onset_flux(ren, rsr) if refine else None
    capv = onset_flux(cap, csr) if refine else None
    rows, dropped = [], 0
    for w in cands:
        base = "w%03d_v%02d_p%s_t%08.3f_%s" % (
            w["index"], w["voice"],
            ("%02X" % w["prog"]) if w["prog"] is not None else "xx", w["t"], w["note"])
        lag, corr = 0.0, None
        t_cap = w["win_start"] + offset + drift * w["win_start"]
        if refine:
            lag, corr = local_lag(renv, capv, w["win_start"], t_cap, w["win_len"], refine)
            t_cap += lag

        hw = slice_at(cap, csr, t_cap, w["win_len"])
        rr = slice_at(ren, rsr, w["win_start"], w["win_len"])
        if hw is None or rr is None:
            dropped += 1
            continue
        rr = rr * gain
        hwm = hw[int(round((w["win_len"] - w["meas_len"]) * csr)):]
        rrm = rr[int(round((w["win_len"] - w["meas_len"]) * rsr)):]

        fh, fr, fa = (os.path.join(outdir, base + s)
                      for s in ("_hw.wav", "_render.wav", "_AB.wav"))
        write_wav(fh, hw, csr)
        write_wav(fr, rr, rsr)
        write_wav(fa, np.concatenate([hw, np.zeros((int(gap * csr), hw.shape[1])),
                                      resample_to(rr, rsr, csr)]), csr)

        r = dict(w)
        r.update(capture_t=t_cap, refine_lag=lag, refine_corr=corr,
                 hw_rms_db=rms_db(hwm), render_rms_db=rms_db(rrm),
                 hw_centroid_hz=centroid_hz(hwm, csr),
                 render_centroid_hz=centroid_hz(rrm, rsr),
                 files=dict(hw=os.path.basename(fh), render=os.path.basename(fr),
                            ab=os.path.basename(fa)))
        r["level_err_db"] = r["render_rms_db"] - r["hw_rms_db"]
        r["centroid_ratio"] = (r["render_centroid_hz"] / r["hw_centroid_hz"]
                               if r["hw_centroid_hz"] > 0 else None)
        rows.append(r)
    if dropped:
        print("%d windows fell outside one of the two files and were skipped" % dropped)

    meta = dict(capture=mkv, render=renwav, offset_s=offset, drift_s_per_s=drift,
                align=al, render_gain_db=g_db, capture_rate=csr, render_rate=rsr,
                refine=refine, windows=len(rows))
    return rows, meta


def local_lag(renv, capv, t_ren, t_cap, length, search, fps=FPS):
    """Best local realignment of one window, and how well it correlates.

    Opt-in, because on an isolated note there is little for it to lock onto and
    a confident lock onto the wrong neighbour is silent damage. The correlation
    comes back with it so a bad one is visible in the table.
    """
    i0 = int(t_ren * fps)
    seg = renv[i0:i0 + max(int(length * fps), 4)]
    k = int(search * fps)
    j0 = int(t_cap * fps) - k
    if len(seg) < 4 or j0 < 0 or j0 + len(seg) + 2 * k > len(capv):
        return 0.0, None
    s = seg - seg.mean()
    sn = np.linalg.norm(s) or 1.0
    best, bl = -9e9, 0
    for d in range(-k, k + 1):
        q = capv[j0 + k + d:j0 + k + d + len(seg)]
        qq = q - q.mean()
        c = float((s * qq).sum() / (sn * (np.linalg.norm(qq) or 1.0)))
        if c > best:
            best, bl = c, d
    return bl / fps, best


# ------------------------------------------------------------------- reports

def fmt(x, spec="%.3f"):
    return "inf" if x == INF else spec % x


def print_table(cands, muted, m, a):
    what = "isolated" if not a.max_others else "windows with <= %d other voices" % a.max_others
    print("track %d  %s   first %.0f s   %d %s windows"
          % (m.n, m.title, a.seconds, len(cands), what))
    print("guards: %.0f ms before / %.0f ms after, note at least %.0f ms long"
          % (a.guard_before * 1000, a.guard_after * 1000, a.min_sounding * 1000))
    if muted:
        print("sax-man voices %s ignored on both sides, as render_wave mutes them" % muted)
    if a.max_others:
        print("*** --max-others %d: these are NOT solo notes. Every one of them has other\n"
              "*** instruments playing underneath, listed in the `others` column. Anything\n"
              "*** measured here is a measurement of that MIX, not of the named voice."
              % a.max_others)
    if not cands:
        return
    print("\n%4s %9s %4s %5s %5s %6s %5s %9s %7s %8s %8s %6s %-10s %s"
          % ("idx", "seconds", "v", "kind", "prog", "note", "midi", "Hz", "dur",
             "quiet<", "clean>", "same", "others", "rendered"))
    for w in cands:
        print("%4d %9.3f %4d %5s %5s %6s %5d %9.2f %7.3f %8s %8s %6s %-10s %s"
              % (w["index"], w["t"], w["voice"], w["kind"],
                 ("0x%02X" % w["prog"]) if w["prog"] is not None else "--",
                 w["note"], w["midi"], w["hz"], w["dur"], fmt(w["gap_before"]),
                 fmt(w["clean_after"]), fmt(w["prev_same_voice_dt"], "%.2f"),
                 ",".join(str(v) for v in w["others"]) or "-",
                 "yes" if w["rendered"] else "NO: " + w["why"]))


def print_coverage(notes, rows, cands, seconds):
    import collections
    tot = collections.Counter(n["voice"] for n in notes if n["t"] <= seconds)
    got = collections.Counter(w["voice"] for w in cands)
    print("\nper-voice coverage in the first %.0f s:" % seconds)
    print("%5s %5s %8s %9s %8s %10s" % ("voice", "kind", "notes", "kept", "share", "best"))
    for v in sorted(tot):
        mine = [w["n_others"] for w in rows if w["voice"] == v]
        print("%5d %5s %8d %9d %7.1f%% %10s"
              % (v, kind_of(v), tot[v], got.get(v, 0), 100.0 * got.get(v, 0) / tot[v],
                 ("%d others" % min(mine)) if mine else "-"))
    print("\nvoices WITH a kept window: %s" % (sorted(got) or "NONE"))
    blind = [v for v in sorted(tot) if v not in got]
    if blind:
        print("voices with NONE - no per-note claim is possible for these here: %s" % blind)

    # The histogram is the honest headline on a dense track: when the smallest
    # bar is at four other voices, no threshold setting will produce a solo, and
    # saying so is worth more than an empty table.
    h = collections.Counter(w["n_others"] for w in rows)
    if h:
        print("\nhow crowded every eligible note is (other voices sounding in its window):")
        for k in sorted(h)[:10]:
            print("   %2d others  %5d notes  %s" % (k, h[k], "#" * min(h[k], 60)))
        best = min(h)
        if best == 0:
            print("   -> %d notes are genuinely solo." % h[0])
        else:
            print("   -> NOTHING in this track is solo. The quietest moment still has %d"
                  " other\n      voices playing, so a per-note claim about one instrument"
                  " is IMPOSSIBLE here." % best)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("moduledir")
    ap.add_argument("track", type=int)
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--anchor", type=int, default=11, help="solved value is 11")
    ap.add_argument("--rate", type=int, default=32000,
                    help="render rate, used only to say whether a note is renderable")
    ap.add_argument("--guard-before", type=float, default=0.25,
                    help="seconds with no other voice sounding BEFORE the onset")
    ap.add_argument("--guard-after", type=float, default=0.40,
                    help="seconds with no other voice sounding AFTER the onset")
    ap.add_argument("--min-sounding", type=float, default=0.12,
                    help="the isolated note must itself last at least this long")
    ap.add_argument("--max-others", type=int, default=0,
                    help="keep windows with up to this many OTHER voices sounding. 0, the "
                         "default, is the only setting that yields a solo note; anything "
                         "higher is a labelled mix and cannot support a claim about one "
                         "instrument on its own")
    ap.add_argument("--voices", default=None, help="only consider these, e.g. 10-25")
    ap.add_argument("--pad", type=float, default=0.05,
                    help="seconds of lead-in kept in each cut window")
    ap.add_argument("--tail", type=float, default=0.25,
                    help="seconds of decay kept after the note, while it stays clean")
    ap.add_argument("--sax", action="store_true",
                    help="include the sax-man voices; OFF by default, like render_wave")
    ap.add_argument("--bank", default=None,
                    help="wave-bank wav, so the run can say a wave program is MISSING")
    ap.add_argument("--json", default=None, help="write the candidates here")
    ap.add_argument("--extract", default=None, metavar="CAPTURE.MKV",
                    help="also cut every window out of this capture")
    ap.add_argument("--render", default=None, metavar="RENDER.WAV",
                    help="the render to cut the matching windows from")
    ap.add_argument("--out", default=None, help="directory for the extracted wavs")
    ap.add_argument("--capture-offset", type=float, default=None,
                    help="seconds to add to module time to reach capture time; "
                         "measured from the onset flux when not given")
    ap.add_argument("--max-lag", type=float, default=30.0,
                    help="how far the automatic offset search may look")
    ap.add_argument("--refine", type=float, default=0.0, metavar="SECONDS",
                    help="per-window local realignment, +/- this much. Off by default: "
                         "a wrong local lock is silent damage, and the reported "
                         "correlation is the only way to catch it")
    ap.add_argument("--max", type=int, default=0, help="stop after this many windows")
    a = ap.parse_args()

    voices = None
    if a.voices:
        lo, _, hi = a.voices.partition("-")
        voices = set(range(int(lo), int(hi or lo) + 1))

    progs = None
    if a.bank:
        from wave_roots import load_bank
        progs = render_wave.program_table(load_bank(a.bank))

    m = {x.n: x for x in mwmm.load_all(a.moduledir)}[a.track]
    notes, muted = notes_of(m, a.seconds, a.anchor, a.rate, a.sax, progs)
    rows = survey(notes, a.seconds, a.guard_before, a.guard_after,
                  a.min_sounding, voices, a.pad, a.tail)
    cands = [w for w in rows if w["n_others"] <= a.max_others]
    if a.max:
        cands = cands[:a.max]
    for i, w in enumerate(cands):
        w["index"] = i

    print_table(cands, muted, m, a)
    print_coverage(notes, rows, cands, a.seconds)

    doc = dict(track=m.n, title=m.title, seconds=a.seconds, anchor=a.anchor,
               guard_before=a.guard_before, guard_after=a.guard_after,
               min_sounding=a.min_sounding, max_others=a.max_others,
               sax=a.sax, sax_voices=muted, isolated=(a.max_others == 0),
               notes_total=len([n for n in notes if n["t"] <= a.seconds]),
               eligible=len(rows), windows=len(cands),
               best_n_others=min([w["n_others"] for w in rows], default=None),
               candidates=cands)

    if a.extract:
        if not (a.render and a.out):
            raise SystemExit("--extract needs --render and --out")
        print("")
        rows, meta = extract(cands, a.extract, a.render, a.out, a.seconds,
                             a.capture_offset, a.refine, max_lag_s=a.max_lag)
        doc["extract"], doc["candidates"] = meta, rows
        if rows:
            print("%4s %9s %4s %5s %6s %8s %8s %8s %8s %8s %s"
                  % ("idx", "seconds", "v", "kind", "note", "hw dB", "ren dB",
                     "err dB", "hw cen", "ren cen", "files  w###_..._{hw,render,AB}.wav"))
            for r in rows:
                print("%4d %9.3f %4d %5s %6s %8.1f %8.1f %+8.1f %8.0f %8.0f %s"
                      % (r["index"], r["t"], r["voice"], r["kind"], r["note"],
                         r["hw_rms_db"], r["render_rms_db"], r["level_err_db"],
                         r["hw_centroid_hz"], r["render_centroid_hz"],
                         r["files"]["hw"][:-7]))
            print("\nerr dB is render minus hardware AFTER the one global gain match, so"
                  "\npositive means this note is louder in our render than on the cart.")
        print("%d window pairs in %s" % (len(rows), a.out))
        if not a.json:
            a.json = os.path.join(a.out, "solo_windows_track%02d.json" % m.n)

    if a.json:
        with open(a.json, "w") as f:
            json.dump(jsafe(doc), f, indent=1)
        print("json -> %s" % a.json)


if __name__ == "__main__":
    main()
