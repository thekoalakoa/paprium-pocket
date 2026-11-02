#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""sdpins_gate.py <fit.rpt> - the SDRAM-pin part of the new core's fit gate (the firmware's docs/STAGE1_PLAN.md
section 6), from fit.rpt alone. (The new core = the first step of the 0.3.0 work. The rules of this check are those
of its first version, written when the new core was reviewed.)

The new core's SDRAM I/O change asks for every SDRAM pin register in its IOE (pocket.tcl FAST_*_REGISTER requests; the
qsf's ALLOW_SYNCH_CTRL_USAGE OFF on the sdram instance removes the clear/load pair that made the fitter refuse 12 of
them on 0.2.x with warning 176279). The 0.2.6 seed gate (setup >= -2.60 ns) cannot see a pin that falls out of its IOE,
so this check reads the fitter's own answer:
  (a) no "Warning (176279)" that names a dram_* pin;
  (b) in the fitter's pin tables, Output Register = yes on dram_a[0..12], dram_ba[0..1], dram_dqm[0..1], dram_ras_n,
      dram_cas_n, dram_we_n, and Input / Output / Output Enable Register = yes on dram_dq[0..15].
dram_clk (an altddio_out) and dram_cke (a constant) are reported, not gated.
Exit 0 = PASS, 1 = FAIL, 2 = the report could not be read. The STA half (the SDRAM pad budgets in four corners and the
B1 register -> pad metric) is sdram_sta.tcl + sdram_gate.py.
"""
import re, sys

if len(sys.argv) != 2:
    print(__doc__)
    sys.exit(2)
path = sys.argv[1]
try:
    txt = open(path, encoding='utf-8', errors='replace').read()
except OSError as e:
    print('ERROR: %s' % e)
    sys.exit(2)
lines = txt.split('\n')

# (a) 176279 warnings naming a dram pin
w176 = [l.strip() for l in lines if '176279' in l and 'dram_' in l]

# (b) pin tables (the same parse as the pin tool of our 0.2.6 byte-fix comparison)
pins = {}
i = 0
while i < len(lines):
    m = re.match(r'^; (Input Pins|Output Pins|Bidir Pins)\s+;', lines[i])
    if m:
        hdr = [h.strip() for h in lines[i + 2].split(';')]
        j = i + 4
        while j < len(lines) and lines[j].startswith(';'):
            row = dict(zip(hdr, [c.strip() for c in lines[j].split(';')]))
            if row.get('Name'):
                pins[row['Name']] = row
            j += 1
        i = j
    else:
        i += 1
if not pins:
    print('ERROR: no pin tables in', path)
    sys.exit(2)

want = {}
for n in ['dram_a[%d]' % k for k in range(13)] + ['dram_ba[0]', 'dram_ba[1]', 'dram_dqm[0]', 'dram_dqm[1]',
                                                  'dram_ras_n', 'dram_cas_n', 'dram_we_n']:
    want[n] = ('Output Register',)
for k in range(16):
    want['dram_dq[%d]' % k] = ('Input Register', 'Output Register', 'Output Enable Register')

bad, missing = [], []
for n, cols in want.items():
    r = pins.get(n)
    if r is None:
        missing.append(n)
        continue
    for c in cols:
        if r.get(c, '?').lower() != 'yes':
            bad.append('%s %s=%s' % (n, c, r.get(c, '?')))

print('fit report:', path)
print('(a) warnings 176279 naming dram_*: %d' % len(w176))
for l in w176[:20]:
    print('    ' + l[:200])
print('(b) dram pin registers not in their IOE: %d%s' % (len(bad), (' -> ' + ', '.join(bad)) if bad else ''))
if missing:
    print('    pins missing from the tables: ' + ', '.join(missing))
for n in ('dram_clk', 'dram_cke'):
    r = pins.get(n)
    if r:
        print('    (info) %s: output register %s' % (n, r.get('Output Register', '?')))
ok = not w176 and not bad and not missing
print('SDRAM pins: %s' % ('PASS' if ok else 'FAIL'))
sys.exit(0 if ok else 1)
