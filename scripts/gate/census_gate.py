#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""census_gate.py - the class envelope of the firmware's docs/STAGE1_PLAN.md section 6 from census.tcl's K lines,
against the shipped 0.2.6 seed 2. (Profile s1 = the new core, the first step of the 0.3.0 work.)

    python -I -B scripts/gate/census_gate.py <census.txt> [<base census.txt>] [--json OUT] [--profile s1|026]
                                             [--structure-only]

The base defaults to scripts/gate/ref/base_census_026s2.txt (census.tcl on a copy of the shipped 0.2.6 seed-2 fit,
the final 0.2.6 tree tree_s2 = release 44c9fa69). Rules, at the two slow corners (where these classes sit at or below 0;
the fast corners, ~+4 to +5 ns on every class, are printed and not gated, so seed noise there cannot reject a seed):
  - every freeze-capable class (FX68K CCR, the VD bus, VA / rAS -> VD, VDP io_data, VDP io_address, Z80 internal):
    worst setup slack into clk_md >= the base's - 0.25 ns (a seed more than 0.25 ns worse is rejected, even when it
    passes the gate); a class whose collections matched nothing (EMPTY) fails; a class with no timed path (NOPATH) passes
    and is printed;
  - the Z80 enable class (zclk_q, the look-ahead register of the Z80 latch enable in ym7101 -> the Z80's latches):
    worst setup >= 0 (profile s1; --profile 026, a 0.2.x netlist without zclk_q, prints the class from the VDP prescaler
    instead and does not gate it);
  - the base must hold every class (else the reference is wrong: exit 2).
Printed, not gated: the vram1 endpoints below 0 by the classes of our earlier VRAM timing trial: A (nbyte), B (snapshot
read address), C (main RAM port-B address), D (copy flags need[] and F5's snoop look-ahead sn_pre_q) - "V1B" when C or D
is below 0, the round-level trigger for vram_alt.v's shadow pins, its F4 (2 or more of 6 seeds) - and the negative
clk_md census (D lines) beside the base's.
--structure-only (a post-map database): every class must match nodes (no EMPTY); its slacks are estimates and not gated.
Exit 0 = PASS, 1 = FAIL, 2 = an input missing or unreadable.
"""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOL = 0.25
CORNERS = ['Slow 1100mV 85C Model', 'Slow 1100mV 0C Model', 'Fast 1100mV 85C Model', 'Fast 1100mV 0C Model']
GATED = CORNERS[:2]
FREEZE = ['fx68k_ccr', 'vd_bus', 'va_ras_vd', 'vdp_io_data', 'vdp_io_address', 'z80_internal']
ENABLE = ['z80_enable']


def load(p):
    try:
        t = open(p, encoding='utf-8', errors='replace').read()
    except OSError as e:
        print('INPUT ERROR: %s' % e)
        sys.exit(2)
    k, vr, dl = {}, [], {}
    for ln in t.splitlines():
        x = [s.strip() for s in ln.split(' | ')]
        if len(x) >= 4 and x[0] == 'K' and x[1] in CORNERS:
            if x[3] in ('EMPTY', 'NOPATH'):
                k[(x[1], x[2])] = (x[3], '')
            else:
                try:
                    k[(x[1], x[2])] = (float(x[3]), x[4] if len(x) > 4 else '')
                except ValueError:
                    pass
        elif len(x) >= 3 and x[0] == 'A' and x[1] in CORNERS:
            try:
                vr.append((x[1], float(x[2]), x[3]))
            except ValueError:
                pass
        elif len(x) >= 5 and x[0] == 'D' and x[1] in CORNERS and x[2].startswith('worst '):
            dl.setdefault(x[1], []).append((float(x[2].split()[1]), x[5] if len(x) > 5 else ''))
    return k, vr, dl


def vclass(path):
    to = path.split(' -> ')[-1]
    if 'nbyte' in to:
        return 'A'
    if '|need[' in to or 'need[' in to.split('|')[-1] or '|sn_pre_q' in to:   # F5: the look-ahead of need[col] & row match
        return 'D'
    if 'portb_address' in to and ('|sb' in to or 'sb|' in to or ':sb' in to):
        return 'B'
    if 'portb_address' in to:
        return 'C'
    return '-'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('census')
    ap.add_argument('base', nargs='?', default=os.path.join(HERE, 'ref', 'base_census_026s2.txt'))
    ap.add_argument('--json')
    ap.add_argument('--profile', choices=('s1', '026'), default='s1')
    ap.add_argument('--structure-only', action='store_true')
    a = ap.parse_args()
    new, vr, dnew = load(a.census)
    base, _, dbase = load(a.base)
    fails, out = [], {}
    for name in FREEZE + ENABLE:
        for c in CORNERS:
            if (c, name) not in base:
                print('REFERENCE ERROR: the base has no class %s at %s' % (name, c))
                sys.exit(2)
    print('%-15s %-22s %10s %10s %10s  %s' % ('class', 'corner', 'new', 'base', 'margin', 'verdict'))
    for name in FREEZE + ENABLE:
        for c in CORNERS:
            nv = new.get((c, name), ('MISSING', ''))[0]
            bv = base[(c, name)][0]
            if nv in ('MISSING', 'EMPTY'):
                verdict = 'FAIL (%s)' % nv
                fails.append('%s %s: %s' % (name, c, nv))
            elif a.structure_only:
                verdict = 'matched (post-map: slack not gated)'
            elif c not in GATED:
                verdict = 'not gated (fast corner)'
            elif nv == 'NOPATH':
                verdict = 'pass (no timed path)'
            elif name in ENABLE and a.profile == '026':
                verdict = 'not gated (a netlist without V4)'
            elif name in ENABLE:
                ok = nv >= 0.0
                verdict = 'pass' if ok else 'FAIL (Z80 enable class below 0)'
                if not ok:
                    fails.append('%s %s: %+.3f < 0' % (name, c, nv))
            else:
                if isinstance(bv, str):
                    ok, verdict = True, 'pass (base %s)' % bv
                else:
                    ok = nv >= bv - TOL
                    verdict = 'pass' if ok else 'FAIL (more than %.2f ns worse than 0.2.6 seed 2)' % TOL
                if not ok:
                    fails.append('%s %s: %+.3f vs base %+.3f (worse by %.3f)' % (name, c, nv, bv, bv - nv))
            nvs = '%+.3f' % nv if isinstance(nv, float) else nv
            bvs = '%+.3f' % bv if isinstance(bv, float) else bv
            mg = '%+.3f' % (nv - bv) if isinstance(nv, float) and isinstance(bv, float) else '-'
            print('%-15s %-22s %10s %10s %10s  %s' % (name, c.replace(' Model', ''), nvs, bvs, mg, verdict))
            out.setdefault(name, {})[c] = dict(new=nv, base=bv, verdict=verdict)
    # vram1 classes (information; the shadow-pin trigger V1B is a round-level one)
    neg = [(c, s, p, vclass(p)) for c, s, p in vr if s < 0]
    cls = sorted({k for c, s, p, k in neg})
    v1b = any(k in ('C', 'D') for k in cls)
    print('vram1 endpoints below 0: %d, classes %s%s' % (len(neg), ''.join(cls) or '-', '  V1B: class C or D below 0' if v1b else ''))
    for c, s, p, k in sorted(neg, key=lambda e: e[1])[:8]:
        print('    %s %-22s %+.3f %s' % (k, c.replace(' Model', ''), s, p[:150]))
    for c in CORNERS[:2]:
        nw = min((s for s, g in dnew.get(c, [])), default=None)
        bw = min((s for s, g in dbase.get(c, [])), default=None)
        print('clk_md negative census %s: worst %s (%d groups), base %s (%d groups)' % (
            c.replace(' Model', ''), '%+.3f' % nw if nw is not None else 'none', len(dnew.get(c, [])),
            '%+.3f' % bw if bw is not None else 'none', len(dbase.get(c, []))))
    if a.json:
        json.dump(dict(classes=out, vram1_negative_classes=cls, v1b=v1b, fails=fails), open(a.json, 'w'), indent=1)
    print('failures:' if fails else 'failures: none')
    for f in fails:
        print('  ' + f)
    print('CLASS ENVELOPE: %s' % ('PASS' if not fails else 'FAIL'))
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
