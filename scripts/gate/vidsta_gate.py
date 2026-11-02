#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""vidsta_gate.py - the clk_md -> dot clock crossing under the new core's SDC form (the firmware's
docs/STAGE1_PLAN.md, test T24), from vidsta.tcl.

    python -I -B scripts/gate/vidsta_gate.py <vidsta.tsv> [--structure-only]

Rules, for each dot clock (general[2] = H40, general[4] = H32), each of the four corners, setup and hold:
  - exactly 28 timed (from, to) pairs from clk_md (general[1]), and their 28 destinations are scanline_filler's capture
    registers hsync_r, vsync_r, vblank_r, hblank_r, rgb_r[0..23], each once (h32_sync's first stage is false-pathed);
  - every pair is register to register: 0 logic levels;
  - the setup relationship is the same edge (|relationship| < 0.5 ns: the SDC's -start -setup 0 window; 0.2.6's
    -setup 2 form gives 158.3 / 195.6 ns, no exception gives 9.3);
  - setup slack >= 0 and hold slack >= 0 on every pair;
  - no timed pair into a dot clock from any other clock (the SDC's RULE: every other crossing is a synchroniser with
    its own false path).
--structure-only (a post-map database): pairs, destinations, levels and relationship only; the slacks are skipped.
Exit 0 = PASS, 1 = FAIL, 2 = an input missing or unreadable.
"""
import argparse, csv, re, sys

CORNERS = ['Slow 1100mV 85C Model', 'Slow 1100mV 0C Model', 'Fast 1100mV 85C Model', 'Fast 1100mV 0C Model']
MD = 'general[1]'
WANT = {'hsync_r', 'vsync_r', 'vblank_r', 'hblank_r'} | {'rgb_r[%d]' % i for i in range(24)}
# the new core from fit round 2: the pixel flops are dffeas primitives in a generate loop, named rgb_r[n].ff (both
# forms)
DST = re.compile(r'scanline_filler:scanline_filler\|(hsync_r|vsync_r|vblank_r|hblank_r|rgb_r\[\d+\])(?:\.ff)?$')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tsv')
    ap.add_argument('--structure-only', action='store_true')
    a = ap.parse_args()
    try:
        rows = list(csv.DictReader(open(a.tsv, newline='', encoding='utf-8', errors='replace'), delimiter='\t'))
    except OSError as e:
        print('INPUT ERROR: %s' % e)
        sys.exit(2)
    if not rows:
        print('INPUT ERROR: no rows in %s' % a.tsv)
        sys.exit(2)
    fails = []
    print('%-22s %-4s %-5s %6s %7s %7s %9s %9s %s' % ('corner', 'dot', 'kind', 'pairs', 'levels', 'other', 'worst', 'rel', 'verdict'))
    for c in CORNERS:
        for dot in ('h40', 'h32'):
            for kind in ('setup', 'hold'):
                rr = [r for r in rows if r['corner'] == c and r['dot'] == dot and r['kind'] == kind]
                err = [r for r in rr if r['from'] == 'ERROR']
                md = [r for r in rr if MD in r['from_clock'] and r['from'] != 'ERROR']
                other = [r for r in rr if MD not in r['from_clock'] and r['from'] != 'ERROR']
                bad = []
                if err:
                    bad.append('Quartus refused the query: %s' % err[0]['to'][:120])
                pairs = {(r['from'], r['to']) for r in md}
                dst = []
                for r in md:
                    m = DST.search(r['to'])
                    dst.append(m.group(1) if m else r['to'])
                if len(pairs) != 28:
                    bad.append('%d pairs from clk_md (want 28)' % len(pairs))
                if sorted(dst) != sorted(WANT):
                    missing, extra = sorted(WANT - set(dst)), sorted(set(dst) - WANT)
                    dup = sorted({d for d in dst if dst.count(d) > 1})
                    bad.append('destinations: missing %s extra %s twice %s' % (missing[:4], [e[-60:] for e in extra[:3]], dup[:4]))
                lv = [int(r['levels']) for r in md if r['levels'] not in ('NA', '')]
                if any(x != 0 for x in lv):
                    bad.append('%d pair(s) with logic levels (max %d)' % (sum(1 for x in lv if x), max(lv)))
                if other:
                    bad.append('%d timed pair(s) from other clocks: %s' % (len(other), other[0]['from_clock'][-40:]))
                rel = [float(r['relationship']) for r in md if r['relationship'] not in ('NA', '')]
                if kind == 'setup' and rel and max(abs(x) for x in rel) >= 0.5:
                    bad.append('setup relationship %.3f ns (not the same-edge window)' % max(rel, key=abs))
                sl = [float(r['slack']) for r in md if r['slack'] not in ('NA', '')]
                w = min(sl) if sl else None
                if not a.structure_only and (w is None or w < 0):
                    bad.append('worst %s slack %s' % (kind, '%.3f' % w if w is not None else 'none'))
                print('%-22s %-4s %-5s %6d %7s %7d %9s %9s %s' % (
                    c.replace(' Model', ''), dot, kind, len(pairs), max(lv) if lv else '-', len(other),
                    '%.3f' % w if w is not None else '-', '%.3f' % max(rel, key=abs) if rel else '-', 'pass' if not bad else 'FAIL'))
                fails += ['%s %s %s: %s' % (c.replace(' Model', ''), dot, kind, b) for b in bad]
    print('failures:' if fails else 'failures: none')
    for f in fails[:24]:
        print('  ' + f)
    print('VIDSTA: %s' % ('PASS' if not fails else 'FAIL'))
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
