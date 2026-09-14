#!/usr/bin/env python3
"""Read the cartridge's own per-voice level meter out of a hardware capture.

    python scripts/vu_meter.py <capture.mkv> [--out-dir DIR] [--seconds N]

The in-game Boom Box screen draws a live bar graph along the bottom of the
picture - one teal bar per synth slot - and every hardware capture records it at
60 fps in lockstep with the audio. That bar graph is the cartridge telling us
its own mix, frame by frame. It is the only ground truth we have for *level*:
the module format carries notes, programs, pan and tempo, but no volume command
has ever been identified (0x01, 0x07, 0x08 and 0x1A all tested negative), so
until now per-voice gain in the renderer was a guess. This reads it off the
picture instead of inferring it.

The meter is quantised, so this is not an approximation of a continuous level -
it is the exact integer the cartridge wrote, recovered losslessly.

METHOD
  * Bars are teal, RGB about (6, 207, 101); the mask is (G>100) & (G > R+40).
    Plenty of other teal exists on screen - scrolling text, sprite highlights,
    two static widgets to the right of the meter - so the mask alone is not
    enough and the bar grid has to be located first.
  * Geometry is auto-detected per capture, not hardcoded. Every bar always
    reaches the floor, so AND-ing the mask across a few dozen frames spread over
    the file leaves the floor dots standing and burns everything that moves
    away. The surviving runs of the right width, spaced regularly, are the bars;
    the bottom of those runs is the baseline. The result is then checked against
    the reference geometry below and the script refuses to continue if a capture
    is framed differently enough to matter.
  * Height is measured as the CONTIGUOUS run of lit rows upward from the
    baseline, inside that bar's own columns only. Contiguity is what rejects a
    sprite drifting through the strip: a detached blob above the bar cannot
    lengthen it.

Level is height/quantum - 1, but the quantum is measured rather than assumed:
--quantum auto takes the largest step that explains every height seen in the
whole file to within a pixel, and the height histogram is printed either way so
the claim can be checked by eye.

Writes <out-dir>/<name>.npz (frame-time axis in seconds, per-frame heights and
levels for all slots) and <out-dir>/<name>.txt (the summary).

Derived from recordings of a commercial game. Keep the output local - it is
game data and does not belong in the repo.
"""

import argparse
import json
import os
import re
import subprocess
import sys

import numpy as np

# Teal bar colour test. Measured on "1E Gothic.mkv": bar pixels are
# RGB (0..37, 194..213, 88..133), so both halves have wide margin.
G_MIN = 100
G_OVER_R = 40

# Reference geometry, measured on "1E Gothic.mkv" and confirmed on
# "39 Theme of Pap.mkv". Detection must land within TOL of this.
REFERENCE = dict(nbars=32, x0=440, pitch=16.42, barw=12, baseline=966)
TOL = dict(x0=4.0, pitch=0.6, barw=3.0, baseline=6.0)

# How far above the baseline to crop. Tallest bar seen is 72 px, so this leaves
# a large margin; a bar that reached the top of the crop would be reported.
CROP_UP = 136

PROBE_FRAMES = 48
PROBE_Y0 = 700          # geometry probe looks only at the bottom of the screen
MIN_RUN_W, MAX_RUN_W = 6, 20
BATCH = 64              # frames decoded per pipe read


# ---------------------------------------------------------------- ffmpeg ----

def probe_video(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-show_entries", "format=duration",
         "-of", "json", path],
        stdout=subprocess.PIPE, check=True).stdout
    j = json.loads(out)
    st = j["streams"][0]
    num, den = st["r_frame_rate"].split("/")
    fps = float(num) / float(den)
    dur = float(j.get("format", {}).get("duration") or 0.0)
    return int(st["width"]), int(st["height"]), fps, dur


def grab(path, t, w, h):
    """One RGB frame at time t, or None past the end."""
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
         "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, check=True).stdout
    if len(raw) < w * h * 3:
        return None
    return np.frombuffer(raw[:w * h * 3], dtype=np.uint8).reshape(h, w, 3)


def teal(rgb):
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    return (g > G_MIN) & (g > r + G_OVER_R)


# -------------------------------------------------------------- geometry ----

def runs_of(row):
    """[(start, width)] for each run of True in a 1-D boolean array."""
    d = np.diff(np.concatenate(([0], row.astype(np.int8), [0])))
    st = np.nonzero(d == 1)[0]
    en = np.nonzero(d == -1)[0]
    return list(zip(st.tolist(), (en - st).tolist()))


def detect_geometry(path, w, h, dur, nprobe=PROBE_FRAMES, verbose=True):
    """Find the bar grid by AND-ing the teal mask over frames spread in time.

    Anything that ever moves - a scrolling sprite, a bar rising - drops out of
    the AND. The bars' floor dots survive because a bar never falls below the
    floor, which is exactly the invariant that makes this robust.
    """
    ts = np.linspace(0.5, max(1.0, dur - 1.0), nprobe)
    acc = None
    got = 0
    for t in ts:
        f = grab(path, float(t), w, h)
        if f is None:
            continue
        m = teal(f[PROBE_Y0:, :, :])
        acc = m if acc is None else (acc & m)
        got += 1
    if got < 4:
        raise SystemExit(f"{path}: only {got} probe frames decoded")

    colprof = acc.any(axis=0)
    cand = [(s, wd) for s, wd in runs_of(colprof) if MIN_RUN_W <= wd <= MAX_RUN_W]
    if len(cand) < 8:
        raise SystemExit(f"{path}: found {len(cand)} bar-shaped runs, expected ~32")

    # Keep only runs on the dominant pitch, so a stray widget of bar-like width
    # cannot join the grid.
    centres = np.array([s + wd / 2.0 for s, wd in cand])
    diffs = np.diff(centres)
    pitch0 = float(np.median(diffs))
    keep = [0]
    for i in range(1, len(cand)):
        if abs((centres[i] - centres[keep[-1]]) / pitch0 - round((centres[i] - centres[keep[-1]]) / pitch0)) < 0.25:
            keep.append(i)
    cand = [cand[i] for i in keep]
    starts = np.array([s for s, _ in cand], dtype=float)
    widths = np.array([wd for _, wd in cand], dtype=float)
    nbars = len(cand)

    # Least-squares pitch over the whole grid, not just adjacent differences.
    k = np.arange(nbars, dtype=float)
    A = np.stack([k, np.ones(nbars)], axis=1)
    pitch, x0 = np.linalg.lstsq(A, starts, rcond=None)[0]
    resid = float(np.abs(A @ [pitch, x0] - starts).max())

    # Baseline: the lowest row that is lit in every probe frame inside the bars.
    barcols = np.zeros(w, dtype=bool)
    for s, wd in cand:
        barcols[s:s + wd] = True
    rowprof = (acc & barcols[None, :]).sum(axis=1)
    lit = np.nonzero(rowprof >= 0.5 * barcols.sum())[0]
    if len(lit) == 0:
        raise SystemExit(f"{path}: could not find the meter baseline")
    baseline = PROBE_Y0 + int(lit.max())
    floor_h = 1
    while (baseline - PROBE_Y0 - floor_h) >= 0 and rowprof[baseline - PROBE_Y0 - floor_h] >= 0.5 * barcols.sum():
        floor_h += 1

    geom = dict(nbars=nbars, x0=float(x0), pitch=float(pitch),
                barw=int(round(np.median(widths))), baseline=baseline,
                floor_h=floor_h, grid_resid=resid,
                starts=[int(s) for s, _ in cand], widths=[int(x) for _, x in cand],
                probe_frames=got)

    if verbose:
        print(f"  geometry: {nbars} bars, x0={x0:.2f}, pitch={pitch:.3f} px "
              f"(grid residual {resid:.2f} px), width={geom['barw']} px, "
              f"baseline y={baseline}, floor height={floor_h} px "
              f"[{got} probe frames]")

    bad = []
    if nbars != REFERENCE["nbars"]:
        bad.append(f"bar count {nbars} != {REFERENCE['nbars']}")
    for key, tol in TOL.items():
        if abs(geom[key] - REFERENCE[key]) > tol:
            bad.append(f"{key} {geom[key]:.2f} differs from reference "
                       f"{REFERENCE[key]} by more than {tol}")
    if bad:
        raise SystemExit(f"{path}: geometry does not match the reference:\n  "
                         + "\n  ".join(bad))
    return geom


# ---------------------------------------------------------------- stream ----

def read_heights(path, geom, w, seconds=None, verbose=True):
    """Per-frame contiguous bar height, in pixels, for every slot."""
    starts, widths = geom["starts"], geom["widths"]
    cx0 = max(0, starts[0] - 2)
    cx1 = min(w, starts[-1] + widths[-1] + 2)
    cw = cx1 - cx0
    y0 = geom["baseline"] - CROP_UP + 1
    ch = CROP_UP

    # Sample the CENTRE of each bar, not its full width: the outer column or two
    # are antialiased by the capture's rescale and sit near the colour
    # threshold, so including them only adds noise.
    k = max(3, geom["barw"] - 6)
    idx = np.array([[int(round(s + wd / 2.0 - k / 2.0)) - cx0 + i for i in range(k)]
                    for s, wd in zip(starts, widths)])
    need = max(2, (k + 1) // 2)

    # format=rgb24 MUST come before crop. Left to itself ffmpeg crops in the
    # decoder's yuv420p, where x and w are rounded to even - a 525 px crop
    # silently becomes 524, and reshaping the pipe at the requested stride
    # shears the picture by a pixel per row. The size check below is what
    # caught that, so it stays.
    vf = f"format=rgb24,crop={cw}:{ch}:{cx0}:{y0}"
    fsz = cw * ch * 3
    probe = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-an", "-vf", vf, "-frames:v", "1",
         "-pix_fmt", "rgb24", "-f", "rawvideo", "-"],
        stdout=subprocess.PIPE, check=True).stdout
    if len(probe) != fsz:
        raise SystemExit(f"{path}: ffmpeg returned {len(probe)} bytes for a "
                         f"{cw}x{ch} rgb24 frame, expected {fsz} - the crop was "
                         f"resized, so the pipe cannot be reshaped safely")

    cmd = ["ffmpeg", "-v", "error"]
    if seconds:
        cmd += ["-t", str(seconds)]
    cmd += ["-i", path, "-an", "-vf", vf,
            "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, bufsize=fsz * BATCH)

    out = []
    nf = 0
    try:
        while True:
            buf = proc.stdout.read(fsz * BATCH)
            if not buf:
                break
            n = len(buf) // fsz
            if n == 0:
                break
            a = np.frombuffer(buf[:n * fsz], dtype=np.uint8).reshape(n, ch, cw, 3)
            m = teal(a)                              # (n, ch, cw)
            # (n, ch, nbars): how many of that bar's columns are lit in that row
            cnt = m[:, :, idx].sum(axis=3)
            on = cnt >= need
            # Contiguous run upward from the baseline = bottom row of the crop.
            rev = on[:, ::-1, :]
            h = np.cumprod(rev, axis=1).sum(axis=1)
            out.append(h.astype(np.uint8))
            nf += n
            if verbose and nf % 3000 < BATCH:
                print(f"    {nf} frames", end="\r", flush=True)
    finally:
        proc.stdout.close()
        proc.wait()
    if verbose:
        print(f"    {nf} frames read      ")
    if not out:
        raise SystemExit(f"{path}: no frames decoded")
    return np.concatenate(out, axis=0), ch


# --------------------------------------------------------------- quantum ----

def find_quantum(heights, floor_h, forced=None):
    """Largest step that explains every observed height to within a pixel.

    The captures are a scaled recording, not a framebuffer dump, so a bar drawn
    n*q tall can land n*q-1 px tall. A quantum is accepted only if EVERY height
    in the file sits within 1 px of a multiple of it - one outlier disqualifies
    it, which is what stops 1 or 3 from trivially "fitting".
    """
    vals = np.unique(heights)
    vals = vals[vals > 0]
    if forced:
        q = forced
        resid = int(np.abs(vals - q * np.round(vals / q)).max())
        return q, resid, vals
    best = (1, 0)
    for q in range(2, int(vals.max()) + 1):
        resid = np.abs(vals - q * np.round(vals / q)).max()
        if resid <= 1:
            best = (q, int(resid))
    return best[0], best[1], vals


# --------------------------------------------------------------- summary ----

def summarise(name, t, heights, levels, geom, q, qresid, vals, hist, valid):
    L = []
    p = L.append
    nf, nb = levels.shape
    p(f"=== {name} ===")
    p(f"frames {nf}  ({t[-1]:.2f} s, {1.0/np.median(np.diff(t)):.3f} fps)"
      f"   meter on screen in {valid.sum()} frames ({100.0*valid.mean():.2f}%)")
    p(f"geometry  {geom['nbars']} bars  x0={geom['x0']:.2f}  pitch={geom['pitch']:.3f} px"
      f"  width={geom['barw']} px  baseline y={geom['baseline']}  floor={geom['floor_h']} px")
    p("")
    tot = sum(c for _, c in hist)
    p(f"HEIGHT HISTOGRAM ({tot} bar-samples from the {valid.sum()} valid frames; "
      f"height in px, contiguous up from the baseline)")
    for hv, c in hist:
        star = "" if q and abs(hv - q * round(hv / q)) <= 1 else "   <-- NOT a multiple of the quantum"
        p(f"  h={hv:4d}  n={c:9d}  {100.0*c/tot:6.3f}%   h/{q}={hv/q:6.3f}{star}")
    p("")
    p(f"quantum = {q} px (max residual {qresid} px over {len(vals)} distinct heights)")
    p(f"level = round(height/{q}) - 1   ->  observed levels "
      f"{int(levels[valid].min())}..{int(levels[valid].max())}")
    p("")
    p("PER-SLOT SUMMARY  (only frames where the meter is on screen)")
    p("  slot  frames>floor   %active   maxlvl   mean-lvl-when-active")
    v = levels[valid]
    for b in range(nb):
        col = v[:, b]
        act = col > 0
        mean = float(col[act].mean()) if act.any() else 0.0
        p(f"  {b:4d}  {int(act.sum()):12d}  {100.0*act.mean():8.3f}%  {int(col.max()):6d}"
          f"   {mean:20.3f}")
    p("")
    p("NOTE: level 0 is the floor dot. The meter cannot separate 'voice idle' from")
    p("'voice sounding at the lowest level' - both draw one 9 px dot. METHOD BLIND to")
    p("that distinction; only levels 1..7 are positive evidence of a voice sounding.")
    p("")
    dead = [b for b in range(nb) if not (v[:, b] > 0).any()]
    p(f"slots that NEVER rise above the floor: {dead if dead else 'none'}")
    tail = list(range(26, nb))
    p(f"SLOTS 26..{nb-1} (beyond the 26 voices the module format defines):")
    for b in tail:
        col = v[:, b]
        p(f"  slot {b}: frames above floor = {int((col>0).sum())}, max level = {int(col.max())}")
    return "\n".join(L)


def cross_check(path, levels, valid, moddir, track):
    """Does slot k move exactly when module voice k has notes?

    An independent check on the whole reading: the meter is decoded from pixels,
    the voice list from the module bytes, and nothing links them. If slot index
    were not voice index - or the grid were off by a bar - the two sets would
    disagree.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import mwmm
    import voice_notes as vn

    mods = {m.n: m for m in mwmm.load_all(moddir)}
    if track not in mods:
        return f"\nMODULE CROSS-CHECK: no module for boombox slot {track} in {moddir}"
    m = mods[track]
    tl = vn.timeline(m, list(range(26)), 2)
    if isinstance(tl, tuple):
        tl = tl[0]
    mod_v = sorted({e[1] for e in tl})
    meter_v = [b for b in range(levels.shape[1]) if (levels[valid][:, b] > 0).any()]
    only_mod = sorted(set(mod_v) - set(meter_v))
    only_meter = sorted(set(meter_v) - set(mod_v))
    L = ["", f"MODULE CROSS-CHECK vs track {track} ({m.title!r} by {m.composer!r})",
         f"  voices carrying notes in the module : {mod_v}",
         f"  slots that rise above the floor     : {meter_v}",
         f"  in the module but the meter is flat : {only_mod or 'none'}",
         f"  meter moves but no notes in module  : {only_meter or 'none'}",
         f"  header vol[] (static per-voice)     : {m.vol}"]
    L.append("  VERDICT: " + ("slot index == voice index, sets match exactly"
                              if not only_mod and not only_meter else
                              "SETS DISAGREE - slot/voice mapping is not 1:1 as assumed"))
    return "\n".join(L)


def debug_png(path, geom, w, h, dur, out):
    """Draw the detected grid over a real frame so a human can check it."""
    try:
        from PIL import Image
    except ImportError:
        return None
    f = grab(path, min(30.0, dur / 2), w, h)
    if f is None:
        return None
    y0 = geom["baseline"] - CROP_UP + 1
    x0 = max(0, geom["starts"][0] - 8)
    x1 = min(w, geom["starts"][-1] + geom["widths"][-1] + 8)
    img = np.array(f[y0:geom["baseline"] + 4, x0:x1], dtype=np.uint8).copy()
    for s, wd in zip(geom["starts"], geom["widths"]):       # bar edges, red
        for xx in (s - x0, s - x0 + wd - 1):
            if 0 <= xx < img.shape[1]:
                img[:, xx] = (255, 0, 0)
    img[geom["baseline"] - y0, :] = (255, 255, 0)            # baseline, yellow
    for lv in range(1, 9):                                   # level rules, white
        yy = geom["baseline"] - y0 - lv * geom["floor_h"]
        if 0 <= yy < img.shape[0]:
            img[yy, ::4] = (255, 255, 255)
    Image.fromarray(img).save(out)
    return out


# ------------------------------------------------------------------ main ----

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captures", nargs="+", help="capture .mkv files")
    ap.add_argument("--out-dir", default="vu", help="where the .npz/.txt go (default ./vu)")
    ap.add_argument("--seconds", type=float, default=None, help="stop after N seconds")
    ap.add_argument("--probe-frames", type=int, default=PROBE_FRAMES)
    ap.add_argument("--quantum", default="auto",
                    help="'auto' (default) or a pixel step to force")
    ap.add_argument("--modules", default=None,
                    help="module directory; cross-checks the slots that move "
                         "against the voices the module actually plays. The "
                         "boombox slot is taken from the capture's hex prefix "
                         "('1E Gothic.mkv' -> track 30).")
    ap.add_argument("--debug-png", action="store_true",
                    help="write a frame with the detected grid drawn on it")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    forced = None if args.quantum == "auto" else int(args.quantum)

    for path in args.captures:
        name = re.sub(r"[^0-9A-Za-z]+", "_",
                      os.path.splitext(os.path.basename(path))[0]).strip("_")
        print(f"\n{os.path.basename(path)}")
        w, h, fps, dur = probe_video(path)
        print(f"  {w}x{h} @ {fps:g} fps, {dur:.2f} s")
        geom = detect_geometry(path, w, h, dur, args.probe_frames)

        heights, crop_h = read_heights(path, geom, w, args.seconds)
        nf, nb = heights.shape
        t = np.arange(nf, dtype=np.float64) / fps

        if int(heights.max()) >= crop_h:
            print(f"  WARNING: a bar reached the top of the {crop_h}px crop - "
                  f"heights may be clipped")

        # A frame counts only if the meter is actually drawn.
        valid = (heights > 0).sum(axis=1) >= max(8, int(0.75 * nb))

        q, qresid, vals = find_quantum(heights[valid], geom["floor_h"], forced)
        hv, hc = np.unique(heights[valid], return_counts=True)
        hist = [(int(a), int(b)) for a, b in zip(hv, hc)]

        levels = np.where(heights > 0,
                          np.rint(heights.astype(np.float64) / q) - 1, -1)
        levels = np.clip(levels, -1, None).astype(np.int8)

        txt = summarise(os.path.basename(path), t, heights, levels, geom,
                        q, qresid, vals, hist, valid)
        if args.modules:
            mt = re.match(r"([0-9A-Fa-f]{2})[ _]", os.path.basename(path))
            if mt:
                txt += "\n" + cross_check(path, levels, valid, args.modules,
                                          int(mt.group(1), 16))
            else:
                txt += ("\n\nMODULE CROSS-CHECK skipped: no hex boombox slot "
                        "prefix on the capture filename")
        print(txt)
        if args.debug_png:
            png = debug_png(path, geom, w, h, dur,
                            os.path.join(args.out_dir, name + "_grid.png"))
            if png:
                print(f"\n  -> {png}")

        npz = os.path.join(args.out_dir, name + ".npz")
        np.savez_compressed(
            npz, t=t, heights=heights, levels=levels, valid=valid,
            quantum=np.int32(q), quantum_resid=np.int32(qresid), fps=np.float64(fps),
            bar_x=np.array(geom["starts"]), bar_w=np.array(geom["widths"]),
            baseline=np.int32(geom["baseline"]), floor_h=np.int32(geom["floor_h"]),
            pitch=np.float64(geom["pitch"]), x0=np.float64(geom["x0"]),
            capture=np.array(os.path.basename(path)))
        with open(os.path.join(args.out_dir, name + ".txt"), "w") as f:
            f.write(txt + "\n")
        print(f"\n  -> {npz}")
        print(f"  -> {os.path.join(args.out_dir, name + '.txt')}")


if __name__ == "__main__":
    main()
