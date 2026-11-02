#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""sdram_gate.py - the SDRAM pins' STA (the new core's SDRAM I/O change; the firmware's docs/STAGE1_PLAN.md section
6), from sdram_sta.tcl (or the output of our earlier bootpaths.tcl, for B1).

    python -I -B scripts/gate/sdram_gate.py <sdram_sta.txt> [--b1-only]

  PADS  (the SDRAM pad budgets in the project SDC) every dram_* output (dram_a, dram_ba, dram_dqm, dram_ras_n,
        dram_cas_n,
        dram_we_n, dram_dq, dram_clk; dram_cke is a constant) has a timed path with setup >= 0 and hold >= 0, and so has
        every dram_dq input, in all four corners. A pin with no timed path fails (a budget that no longer reaches it).
  B1    (a metric from our comparison of the 0.2.6 byte-fix builds, calibrated on five hardware-tested fits): over the
        address, bank, DQM and
        command pins, the worst register -> pad delay at slow 85C <= 9.74 ns (the shipped 0.2.6 seed 2, which boots:
        9.737; f0ec00cc, black screen on every boot: 12.836); and, when the session-only output constraint ran (P2
        lines), the worst P2 setup at fast 85C >= -0.10 ns with at most one bit below 0.
--b1-only: B1 alone (0.2.x databases, which have no pad budgets; an old bootpaths.tcl output reads the same way).
Exit 0 = PASS, 1 = FAIL, 2 = an input missing or unreadable.
"""
import argparse, sys

CORNERS = ['Slow 1100mV 85C Model', 'Slow 1100mV 0C Model', 'Fast 1100mV 85C Model', 'Fast 1100mV 0C Model']
CMD = ['dram_a[%d]' % i for i in range(13)] + ['dram_ba[0]', 'dram_ba[1]', 'dram_dqm[0]', 'dram_dqm[1]', 'dram_ras_n',
                                               'dram_cas_n', 'dram_we_n']
DQ = ['dram_dq[%d]' % i for i in range(16)]
OUTS = CMD + DQ + ['dram_clk']
B1_MAX_S85, B1_P2_F85, B1_P2_BITS = 9.74, -0.10, 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sta')
    ap.add_argument('--b1-only', action='store_true')
    a = ap.parse_args()
    try:
        lines = open(a.sta, encoding='utf-8', errors='replace').read().splitlines()
    except OSError as e:
        print('INPUT ERROR: %s' % e)
        sys.exit(2)
    pad, dly, p2 = {}, {}, {}
    for ln in lines:
        x = [s.strip() for s in ln.split(' | ')]
        if len(x) < 3 or x[0] not in CORNERS:
            continue
        c, what, v = x[0], x[1], x[2]
        if what.startswith('pad '):
            _, d, kind, port = what.split()
            try:
                pad[(c, d, kind, port)] = float(v)
            except ValueError:
                pad[(c, d, kind, port)] = v
        elif what.startswith('sdpin '):
            try:
                dly[(c, what[6:])] = float(v.split()[1])
            except (ValueError, IndexError):
                pass
        elif what.startswith('P2 setup '):
            try:
                p2[(c, what[9:])] = float(v)
            except ValueError:
                pass
    if not dly:
        print('INPUT ERROR: no sdpin lines in %s' % a.sta)
        sys.exit(2)
    fails = []
    if not a.b1_only:
        bad = []
        for c in CORNERS:
            for kind in ('setup', 'hold'):
                for port in OUTS:
                    v = pad.get((c, 'out', kind, port))
                    if not isinstance(v, float) or v < 0:
                        bad.append('%s out %s %s: %s' % (c.replace(' Model', ''), kind, port, v))
                for port in DQ:
                    v = pad.get((c, 'in', kind, port))
                    if not isinstance(v, float) or v < 0:
                        bad.append('%s in %s %s: %s' % (c.replace(' Model', ''), kind, port, v))
        nums = [v for v in pad.values() if isinstance(v, float)]
        print('PADS: %d checks (4 corners x setup / hold x %d outputs + %d inputs), worst %s, %d failing' % (
            4 * 2 * (len(OUTS) + len(DQ)), len(OUTS), len(DQ), '%.3f' % min(nums) if nums else 'none', len(bad)))
        for b in bad[:12]:
            print('    ' + b)
        fails += ['PADS ' + b for b in bad]
    s85 = CORNERS[0]
    d = [(dly[(s85, p)], p) for p in CMD if (s85, p) in dly]
    if len(d) != len(CMD):
        fails.append('B1 register -> pad delay missing for %d pins' % (len(CMD) - len(d)))
    wd = max(d) if d else (None, '-')
    print('B1: worst register -> pad at slow 85C %s (%s), limit %.2f' % (wd[0], wd[1], B1_MAX_S85))
    if wd[0] is None or wd[0] > B1_MAX_S85:
        fails.append('B1 worst register -> pad %s ns at slow 85C (%s) > %.2f' % (wd[0], wd[1], B1_MAX_S85))
    f85 = CORNERS[2]
    pp = [(p2[(f85, p)], p) for p in CMD if (f85, p) in p2]
    if pp:
        wp, neg = min(pp), [p for v, p in pp if v < 0]
        print('B1: P2 (session-only dram_clk constraint) fast 85C worst %.3f (%s), %d bit(s) below 0' % (wp[0], wp[1], len(neg)))
        if wp[0] < B1_P2_F85 or len(neg) > B1_P2_BITS:
            fails.append('B1 P2 fast 85C worst %.3f (%s), %d bits below 0 (limits %.2f, %d)' % (wp[0], wp[1], len(neg),
                                                                                              B1_P2_F85, B1_P2_BITS))
    else:
        print('B1: no P2 lines (the session-only constraint was not run): register -> pad only')
    print('failures:' if fails else 'failures: none')
    for f in fails[:30]:
        print('  ' + f)
    print('SDRAM PINS (STA): %s' % ('PASS' if not fails else 'FAIL'))
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
