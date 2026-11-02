#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""gate.py - the new core's seed gate (the firmware's docs/STAGE1_PLAN.md section 6): setup >= -2.60 ns, hold > 0,
sta_xcheck clean, no empty collection. (The new core = the first step of the 0.3.0 work; profile s1 = its SDC.)

    python -I -B scripts/gate/gate.py --xcheck xcheck.txt [--summary megadrive_pocket.sta.summary] [--log FILE ...]
                                      [--profile s1|026] [--collections-only]

  1  sta.summary (the fit's own STA): the worst setup over every clock and corner >= -2.60 ns (LESS NEGATIVE IS
     BETTER: -2.50 passes, -2.90 fails; docs/BUILD_REFERENCE.md), and the worst hold > 0 in every corner.
  2  xcheck.txt (scripts/gate/xcheck.tcl on the fitted database): every collection of the profile is listed and matched
     at least one node (profile s1: the new core's SDC's C2c, MV, HOLD, VS, Scum!, P2, P2r, P0, RM, SP, C2a, C2b, the
     FX68K and audio multicycles, option D, h32_sync, the SDRAM pins and, from the synth step (test build 4a, the first
     0.3.0 hardware test build of the sound cache), the first-boot bar's two synchronisers bar_sync / bar_w_sync, (test
     build 5, the synth build) the hold picture's hold_vid_sync; profile 026: 0.2.6's eleven xfix
     collections); the
     audio IIR collection may be empty only when no register of audio_cond's iir_filter survives synthesis (the
     Paprium build removes the whole filter, and the SDC then says so in a plain message); in
     every corner every clk_sys <-> clk_md crossing has setup >= 0 and hold > 0, setup into clk_sys >= 0, the worst hold
     of the design > 0 and no failing hold path.
  3  the logs and reports given with --log (the fit / sta reports, the quartus_sta logs of the gate's runs): no critical
     warning from an SDC guard ("pocket: ... matched nothing", "critical_warning ... pocket:").
--collections-only (a post-map database, no fit): rule 2's collections only; rules 1 and the slacks of 2 are skipped.
Exit 0 = PASS, 1 = FAIL, 2 = an input missing or unreadable.
"""
import argparse, os, re, sys

GATE_SETUP = -2.60
CORNERS = ['Slow 1100mV 85C Model', 'Slow 1100mV 0C Model', 'Fast 1100mV 85C Model', 'Fast 1100mV 0C Model']
PROFILES = {
    's1': ['p2', 'p2r', 'p2r_dst', 'sdram', 'p0', 'rm', 'sp_ptr', 'sp_held', 'c2a', 'c2b', 'c2c', 'mv', 'hold', 'vs',
           'scum_src', 'scum_dst', 'fx68k_ir', 'fx68k_uadr', 'audio_iir', 'od_vals', 'od_caps', 'vid_h32s', 'sdram_pins',
           'vid_bar', 'bar_w',    # test build 4a on: the first-boot bar's synchronisers (core_constraints.sdc BAR / BARW)
           'vid_hold'],           # test build 5 on: the hold picture's synchroniser (core_constraints.sdc HOLDV)
    '026': ['p2', 'p2r', 'sdram', 'p0', 'rm', 'sp_ptr', 'sp_held', 'sp_ph', 'c1', 'c2a', 'c2b'],
}
RULES = [('setup sys->md', '>=', 0.0), ('setup md->sys', '>=', 0.0), ('hold sys->md', '>', 0.0),
         ('hold md->sys', '>', 0.0), ('setup to clk_sys', '>=', 0.0), ('hold any', '>', 0.0)]
GUARD = re.compile(r'(matched nothing|critical[ _]warning.*pocket:)', re.I)


def read(p):
    try:
        return open(p, encoding='utf-8', errors='replace').read()
    except OSError as e:
        print('INPUT ERROR: %s' % e)
        sys.exit(2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--summary')
    ap.add_argument('--xcheck', required=True)
    ap.add_argument('--log', nargs='*', default=[])
    ap.add_argument('--profile', choices=sorted(PROFILES), default='s1')
    ap.add_argument('--collections-only', action='store_true')
    a = ap.parse_args()
    fails = []
    # 1 sta.summary
    if not a.collections_only:
        if not a.summary:
            print('INPUT ERROR: --summary is needed unless --collections-only')
            sys.exit(2)
        worst = {}
        for t, s in re.findall(r'Type\s*:\s*(.+?)\nSlack\s*:\s*(\S+)', read(a.summary)):
            m = re.match(r"(Slow 1100mV 85C|Slow 1100mV 0C|Fast 1100mV 85C|Fast 1100mV 0C) Model (Setup|Hold) '(.+)'", t)
            if m:
                k = (m.group(1) + ' Model', m.group(2))
                worst[k] = min(worst.get(k, 1e9), float(s))
        if not worst:
            print('INPUT ERROR: no Setup / Hold rows in %s' % a.summary)
            sys.exit(2)
        setup = min(v for (c, k), v in worst.items() if k == 'Setup')
        print('1 sta.summary: worst setup %.3f (gate >= %.2f)' % (setup, GATE_SETUP))
        if not setup >= GATE_SETUP:
            fails.append('1 worst setup %.3f < %.2f' % (setup, GATE_SETUP))
        for c in CORNERS:
            h = worst.get((c, 'Hold'))
            s = worst.get((c, 'Setup'))
            print('  %-24s setup %s  hold %s' % (c, '%.3f' % s if s is not None else 'NONE', '%.3f' % h if h is not None else 'NONE'))
            if h is None or not h > 0:
                fails.append('1 %s worst hold %s (gate > 0)' % (c, h))
    # 2 xcheck
    xc = read(a.xcheck)
    cols = dict((t, int(n)) for t, n in re.findall(r'^collection (\S+) : (\d+)', xc, re.M))
    print('2 xcheck collections (%s): %s' % (a.profile, ', '.join('%s %d' % kv for kv in cols.items())))
    for t in PROFILES[a.profile]:
        if t not in cols:
            fails.append('2 collection %s not listed (xcheck.tcl run with another profile?)' % t)
        elif cols[t] == 0 and not (t == 'audio_iir' and cols.get('audio_iir_any') == 0):
            fails.append('2 collection %s matched nothing' % t)
    if not a.collections_only:
        rows, counts = {}, {}
        for ln in xc.splitlines():
            p = [x.strip() for x in ln.split(' | ', 3)]
            if len(p) >= 3 and p[0] in CORNERS and p[1] == 'counts':
                mm = re.search(r'failing hold paths \(cap 500\): (\d+)', p[2])
                counts[p[0]] = int(mm.group(1)) if mm else None
            elif len(p) >= 4 and p[0] in CORNERS:
                try:
                    rows.setdefault((p[0], p[1]), []).append((float(p[2]), p[3]))
                except ValueError:
                    pass
        print('  %-24s ' % 'corner' + ' '.join('%16s' % r[0] for r in RULES) + '  failing-hold')
        for c in CORNERS:
            cells = []
            for lbl, op, lim in RULES:
                v = rows.get((c, lbl))
                if not v:
                    cells.append('%16s' % 'NONE')
                    fails.append('2 %s %s: no path reported' % (c, lbl))
                    continue
                w, pth = min(v)
                ok = (w >= lim) if op == '>=' else (w > lim)
                cells.append('%15.3f%s' % (w, ' ' if ok else '!'))
                if not ok:
                    fails.append('2 %s %s worst %.3f (need %s %g): %s' % (c, lbl, w, op, lim, pth[:160]))
            n = counts.get(c)
            if n != 0:
                fails.append('2 %s failing hold paths: %s' % (c, n))
            print('  %-24s ' % c.replace(' Model', '') + ' '.join(cells) + '  %s' % n)
    # 3 SDC guard messages
    for p in a.log:
        hits = [ln.strip() for ln in read(p).splitlines() if GUARD.search(ln)]
        print('3 %s: %d SDC guard message(s)' % (os.path.basename(p), len(hits)))
        for h in hits[:6]:
            print('    ' + h[:200])
        if hits:
            fails.append('3 %d SDC guard message(s) in %s' % (len(hits), os.path.basename(p)))
    print('failures:' if fails else 'failures: none')
    for f in fails:
        print('  ' + f)
    print('GATE: %s' % ('PASS' if not fails else 'FAIL'))
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
