#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""queries_gate.py - the new core's STA query list (the firmware's docs/STAGE1_PLAN.md section 6), from queries.tcl.
(The new core = the first step of the 0.3.0 work.)

    python -I -B scripts/gate/queries_gate.py <queries.txt> [<reference queries.txt>] [--collections-only]

The reference defaults to scripts/gate/ref/queries_026s2.txt (queries.tcl on a copy of the shipped 0.2.6 seed 2).
Rules, every corner. The MCU memory rows follow the "design" line queries.tcl writes (no line: the Wishbone design):
  Wishbone (0.2.x, and the new core before the MCU fast path):
  wram_write >= +0.5 ns (the seed-6 path; the firmware's docs/MCU_INTERFACE.md 3.2 took the decode off it)   wram_read
  >= 0   rv_di_irom >= 0 test build 4, the MCU fast path (MCU_INTERFACE.md 20: the IROM / WRAM tightly coupled, every
  MCU memory path one full clk_sys cycle): tcm_wram_in, tcm_wram_out, tcm_irom_in, tcm_irom_out >= 0; ramdp_ack
  (ramdp_io's registered ack) >= 0
  Both: rv_di_regs, rv_di_ramdp, rv_di_mem >= 0 (the registered arms of mcu_dati -> rv_di, ~+0.7 in 0.2.6)
  sdram_cart_data >= the reference's - 0.25 ns (the new core's FM XOR on the 68000's ROM read path)
  hold_in, vs_in: no timed path into the synchroniser's first stage (the SDC's false path cuts it)
  hold_out, vs_out, vscnt: setup >= 0, hold > 0
  the synth (test build 5 on, the synth build: queries.tcl's "stage5 synth" line, the synth in the netlist): syn_cram_rd
  (port C read data into the synth), syn_dsp (through the synth's DSP blocks: their result pins), syn_dsp_in (through
  their data inputs: also a path that ends in a register the Fitter packed into a DSP; a project decision), syn_dacbuf_w
  / syn_dacbuf_r (the synth's CRAM port E: dac_buf and the echo rings, both ways), irom_x (the 88 KB IROM's extension
  slices into the NEORV32): setup >= 0
  every collection matched at least one node.
--collections-only (a post-map database): the collections and the "no path into the first stage" rules (structure, not
timing); the slack rules are skipped.
--profile 026 (a 0.2.x database, to prove the slack rules on a real fit): the new core's own items (the register-file
read data, the HOLD and VS synchronisers, the VS counter) are not required.
Exit 0 = PASS, 1 = FAIL, 2 = an input missing or unreadable.
"""
import argparse, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOL = 0.25
CORNERS = ['Slow 1100mV 85C Model', 'Slow 1100mV 0C Model', 'Fast 1100mV 85C Model', 'Fast 1100mV 0C Model']
GE, GT = '>=', '>'
MIN = {('wram_write', 'setup'): (GE, 0.5), ('wram_read', 'setup'): (GE, 0.0), ('rv_di_regs', 'setup'): (GE, 0.0),
       ('rv_di_ramdp', 'setup'): (GE, 0.0), ('rv_di_mem', 'setup'): (GE, 0.0), ('rv_di_irom', 'setup'): (GE, 0.0),
       ('hold_out', 'setup'): (GE, 0.0), ('hold_out', 'hold'): (GT, 0.0), ('vs_out', 'setup'): (GE, 0.0),
       ('vs_out', 'hold'): (GT, 0.0), ('vscnt', 'setup'): (GE, 0.0), ('vscnt', 'hold'): (GT, 0.0)}
# test build 4 (queries.tcl's design card4): the tightly coupled memory rows replace the Wishbone design's three
WISHBONE_ONLY_MIN = [('wram_write', 'setup'), ('wram_read', 'setup'), ('rv_di_irom', 'setup')]
CARD4_MIN = {('tcm_wram_in', 'setup'): (GE, 0.0), ('tcm_wram_out', 'setup'): (GE, 0.0), ('tcm_irom_in', 'setup'): (GE, 0.0),
             ('tcm_irom_out', 'setup'): (GE, 0.0), ('ramdp_ack', 'setup'): (GE, 0.0)}
WISHBONE_ONLY_COLS = ['wram', 'wram_wr', 'irom']
CARD4_COLS = ['tcm_wram', 'tcm_irom', 'ramdp_ack']
# the synth (test build 5 on: "stage5 synth"): the synth's rows and their collections (the synth design's gate rows;
# every fit must pass all six judges; syn_dsp_in / syn_dsp_in_p: a project decision)
S5_MIN = {('syn_cram_rd', 'setup'): (GE, 0.0), ('syn_dsp', 'setup'): (GE, 0.0), ('syn_dsp_in', 'setup'): (GE, 0.0),
          ('syn_dacbuf_w', 'setup'): (GE, 0.0), ('syn_dacbuf_r', 'setup'): (GE, 0.0), ('irom_x', 'setup'): (GE, 0.0)}
S5_COLS = ['syn_all', 'cram_c_rd', 'cram_e_rd', 'cram_all', 'syn_e', 'syn_dsp_p', 'syn_dsp_in_p', 'irom_x']
NONE_WANTED = [('hold_in', 'setup'), ('hold_in', 'hold'), ('vs_in', 'setup'), ('vs_in', 'hold')]
COLS = ['wram', 'wram_wr', 'neo', 'regs_dati', 'ramdp', 'mem_dati', 'irom', 'sdram_dout', 'cart_data', 'hold_s1', 'hold_all',
        'vs_s1', 'vs_all', 'vscnt']


def load(p):
    try:
        t = open(p, encoding='utf-8', errors='replace').read()
    except OSError as e:
        print('INPUT ERROR: %s' % e)
        sys.exit(2)
    cols = dict((k, int(n)) for k, n in re.findall(r'^collection (\S+) : (\d+)', t, re.M))
    dm = re.search(r'^design (\S+)', t, re.M)
    cols['_design'] = dm.group(1) if dm else 'wishbone'
    cols['_s5'] = bool(re.search(r'^stage5 synth', t, re.M))
    q = {}
    for ln in t.splitlines():
        x = [s.strip() for s in ln.split(' | ')]
        if len(x) >= 4 and x[0] in CORNERS:
            k = (x[0], x[1], x[2])
            if x[3] in ('NONE', 'EMPTY', 'ERROR'):
                q.setdefault(k, []).append((x[3], ' | '.join(x[4:])))
            else:
                try:
                    q.setdefault(k, []).append((float(x[3]), x[4] if len(x) > 4 else ''))
                except ValueError:
                    pass
    return cols, q


def worst(rows):
    nums = [r for r in rows if isinstance(r[0], float)]
    if nums:
        return min(nums)
    return rows[0] if rows else ('MISSING', '')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('queries')
    ap.add_argument('ref', nargs='?', default=os.path.join(HERE, 'ref', 'queries_026s2.txt'))
    ap.add_argument('--collections-only', action='store_true')
    ap.add_argument('--profile', choices=('s1', '026'), default='s1')
    a = ap.parse_args()
    cols, q = load(a.queries)
    fails = []
    design = cols.pop('_design')
    s5 = cols.pop('_s5')
    if design == 'card4':       # MCU_INTERFACE.md 20: the IROM / WRAM on the processor bus
        COLS[:] = [c for c in COLS if c not in WISHBONE_ONLY_COLS] + CARD4_COLS
        for k in WISHBONE_ONLY_MIN:
            del MIN[k]
        MIN.update(CARD4_MIN)
    if s5:                      # the synth (test build 5 on): the synth's rows
        COLS[:] = COLS + S5_COLS
        MIN.update(S5_MIN)
    print('design: %s%s' % (design, ' + stage 5 (the synth)' if s5 else ''))
    if a.profile == '026':      # a 0.2.x netlist: the new core's own items are not required
        s1_only = {'regs_dati', 'hold_s1', 'hold_all', 'vs_s1', 'vs_all', 'vscnt'}
        COLS[:] = [c for c in COLS if c not in s1_only]
        for k in [k for k in MIN if k[0] in ('hold_out', 'vs_out', 'vscnt', 'rv_di_regs')]:
            del MIN[k]
        NONE_WANTED[:] = []
    for c in COLS:
        if cols.get(c, 0) == 0:
            fails.append('collection %s matched nothing' % c)
    print('collections: ' + ', '.join('%s %d' % (c, cols.get(c, 0)) for c in COLS))
    print('%-16s %-6s %-22s %10s %10s  %s' % ('query', 'kind', 'corner', 'worst', 'limit', 'verdict'))
    for c in CORNERS:           # structure: the false paths into the synchronisers' first stages
        for name, kind in NONE_WANTED:
            rows = q.get((c, name, kind), [])
            ok = bool(rows) and all(r[0] == 'NONE' for r in rows)
            if not ok:
                fails.append('%s %s %s: a timed path into the synchroniser\'s first stage: %s' % (
                    name, kind, c.replace(' Model', ''), rows[0] if rows else 'not reported'))
            print('%-16s %-6s %-22s %10s %10s  %s' % (name, kind, c.replace(' Model', ''),
                                                      rows[0][0] if rows and not isinstance(rows[0][0], float) else
                                                      ('%.3f' % rows[0][0] if rows else 'MISSING'), 'no path', 'pass' if ok else 'FAIL'))
    if not a.collections_only:
        rcols, rq = load(a.ref)
        for c in CORNERS:
            for (name, kind), (op, lim) in sorted(MIN.items()):
                w, pth = worst(q.get((c, name, kind), []))
                ok = isinstance(w, float) and (w >= lim if op == GE else w > lim)
                if not ok:
                    fails.append('%s %s %s: %s (need %s %.1f) %s' % (name, kind, c.replace(' Model', ''), w, op, lim, pth[:140]))
                print('%-16s %-6s %-22s %10s %10s  %s' % (name, kind, c.replace(' Model', ''),
                                                          '%.3f' % w if isinstance(w, float) else w, '%s %.1f' % (op, lim),
                                                          'pass' if ok else 'FAIL'))
            w, pth = worst(q.get((c, 'sdram_cart_data', 'setup'), []))
            rw, rpth = worst(rq.get((c, 'sdram_cart_data', 'setup'), []))
            if not isinstance(rw, float):
                print('REFERENCE ERROR: no sdram_cart_data at %s in %s' % (c, a.ref))
                sys.exit(2)
            ok = isinstance(w, float) and w >= rw - TOL
            if not ok:
                fails.append('sdram_cart_data %s: %s vs 0.2.6 seed 2 %.3f (more than %.2f worse) %s' % (
                    c.replace(' Model', ''), w, rw, TOL, pth[:120]))
            print('%-16s %-6s %-22s %10s %10s  %s' % ('sdram_cart_data', 'setup', c.replace(' Model', ''),
                                                      '%.3f' % w if isinstance(w, float) else w, '>= %.3f' % (rw - TOL),
                                                      'pass' if ok else 'FAIL'))
    print('failures:' if fails else 'failures: none')
    for f in fails[:30]:
        print('  ' + f)
    print('QUERIES: %s' % ('PASS' if not fails else 'FAIL'))
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
