#!/usr/bin/env python3
"""Per-voice mix levels read off the cartridge's own on-screen VU meter.

    python scripts/vu_gain.py <capture.npz> [--law linear|db3] [--stat max|p99|median]

The Boom Box screen draws a live level meter along the bottom - 32 bars, eight
quantised heights each - and every hardware capture recorded it at 60 fps beside
the audio. That meter is the per-voice level feed at cart RAM 0x1B98-0x1BFF,
which is to say the synth reporting its own mix. `scripts/vu_meter.py` decodes it
out of the video; this turns it into a gain per voice.

Why it is needed: per-voice volume is NOT in the module. Array A at +0x10 is 0x10
on all 26 voices of all 52 modules, and 0x01/0x07/0x08/0x1A have each been tested
as the volume command and refuted. The proof that the level is generated at
runtime is Theme Of Paprium voices 24 and 25: 256 notes each, identical
semitones, identical program sequence - and hardware holds them two meter levels
apart for the whole track. No rule reading the module can produce that.

Bars 26-31 never leave the floor in any of the four decoded captures (54,748
frames), so the meter is the 26 module voices plus six dead slots.

The statistic is the voice's CEILING, not its average. A gain sets how loud a
voice can get and its envelope moves below that, so a voice held at level 4 for
231 seconds - Gothic's PSG voice 6 - is a voice turned down, whereas a low median
may only mean a short decay.

Two amplitude laws are offered because the meter's own law is unmeasured: the bar
is an integer 0..7 and nothing yet says whether that is amplitude or decibels.
Only the ORDERING of voices is independent of the choice.

Derived from a commercial ROM: keep the output local.
"""

import argparse
import json

import numpy as np

NVOICE = 26


def levels(npz):
    """(frames x 32) integer levels 0..7, valid frames only."""
    d = np.load(npz)
    h = d["heights"].astype(int)[d["valid"]]
    q = int(d["quantum"]) or 9
    return np.maximum(h // q - 1, 0)


def ceilings(lv, stat="max"):
    """Per-voice level ceiling, one integer each."""
    out = {}
    for v in range(NVOICE):
        col = lv[:, v]
        act = col[col > 0]
        if not len(act):
            continue
        out[v] = int({"max": act.max(),
                      "p99": np.percentile(act, 99),
                      "median": np.median(act)}[stat])
    return out


def gains(ceil, law="linear", ref=None):
    """Level -> linear gain, normalised so the median voice sits at 1.0.

    Normalising matters: the absolute loudness of the render is already set by
    the timbre calibration, and what the meter adds is the BALANCE between
    voices. Renormalising keeps this from being a master volume change.
    """
    amp = {"linear": lambda L: L / 7.0,
           "db3":    lambda L: 10.0 ** ((L - 7) * 3.0 / 20.0)}[law]
    g = {v: amp(L) for v, L in ceil.items()}
    if not g:
        return g
    mid = ref if ref is not None else float(np.median(list(g.values())))
    return {v: float(np.clip(x / mid, 0.02, 8.0)) for v, x in g.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("npz")
    ap.add_argument("--law", default="linear", choices=["linear", "db3"])
    ap.add_argument("--stat", default="max", choices=["max", "p99", "median"])
    ap.add_argument("--out", default=None, help="write the table as JSON")
    a = ap.parse_args()

    lv = levels(a.npz)
    ceil = ceilings(lv, a.stat)
    g = gains(ceil, a.law)
    klass = lambda v: "FM " if v < 6 else ("PSG" if v < 10 else "wav")
    print("%-6s %-4s %7s %8s %9s %9s" % ("voice", "cls", "ceil", "gain", "dB", "active%"))
    for v in range(NVOICE):
        if v not in ceil:
            print("%-6d %-4s %7s %8s %9s %9s" % (v, klass(v), "-", "-", "-", "0.0"))
            continue
        act = 100.0 * (lv[:, v] > 0).mean()
        print("%-6d %-4s %7d %8.3f %+9.1f %9.1f"
              % (v, klass(v), ceil[v], g[v], 20 * np.log10(g[v]), act))
    if a.out:
        json.dump({str(k): v for k, v in g.items()}, open(a.out, "w"), indent=1)
        print("wrote %s" % a.out)


if __name__ == "__main__":
    main()
