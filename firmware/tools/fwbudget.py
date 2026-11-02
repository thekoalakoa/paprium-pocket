#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""fwbudget.py - size budget per module against the IROM / WRAM / SRAM regions; fails the build when over.

    python -I -B tools/fwbudget.py <build dir> [--budget tools/budget.json] [--layout <layout json>] [--txt f] [--json f]

The regions are the cart MCU's memories: IROM is its code memory (block RAM in the FPGA, read-only to the firmware),
WRAM its working RAM, and SRAM the Pocket's SRAM chip that holds the MegaWire code. rodata = read-only data.

<build dir> = build/pocket/<layout>/<variant> (main.map from tools/fwbuild.py). It makes two checks, and both measure
from the map:

1. TODAY: every byte the link kept is attributed to exactly one module of budget.json "modules" (rules: object name
   and input-section name, first match wins). A byte no rule claims fails the check, so new code cannot dodge a
   budget. The linker's alignment fill between input sections ("*fill*" lines of the map) is attributed too, as input
   section "*fill*" of object "(linker fill)". The attributed bytes of every output section must add up to its size
   in the map (otherwise the map was misread, and the check fails), so the totals equal layout.txt's. Each module has
   a cap per memory class, and a module over its cap fails. Classes:
     irom  = code + rodata + the .data load image (all of it is in the 72 KB IROM)
     wram  = .data + .bss + .noinit + .bss_noclear (run-time WRAM)
     wcode = code and rodata in the write-locked WRAM code window (.wram_text)
     brain = the brain's fixed bytes (.brain_irom, .wram_cf): checked for size, never budgeted
2. Plan (0.3.0): every module of the 0.3.0 firmware has a budget in a placement (irom, wcode, wram_upper, sram_cold,
   sram_mw, boot_overlay, ...). A plan module whose code exists today is measured through its "measured_by" modules.
   The others count at their budget, which is an estimate (with low / central / high figures beside it). The plan
   fails when the budgets of a placement add up to more than its room (the plan no longer fits), or when a measured
   plan module is over its budget. Legacy and interim modules are not in the plan: they go as the new modules that do
   what the cart's chip does take their place.
   A plan module may also name "stage1_by" modules: the code of the s1 build (the new 0.3.0 firmware, built with
   FW_S1) that does its job today. Their measured size is printed against the allocation but does not fail the check,
   because the s1 code holds parts the plan counts in other rows, and TEST-only counters. B Jam reviews and revises
   those rows: see docs/BUDGET.md section 7.
The report labels each number "MEASURED" (from this build) or "MODELLED" (a budget.json number, with its basis).
Stage numbers are the steps of the 0.3.0 work (README.md, "Terms")."""
import argparse, collections, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

CLASS = {'.text': 'irom', '.text_hi': 'irom', '.ext_text': 'irom', '.rodata': 'irom', '.wram_text': 'wcode',
         '.brain_irom': 'brain', '.data': 'data', '.sdata': 'data', '.bss': 'wram', '.bss_noclear': 'wram',
         '.bss_gap': 'wram', '.noinit': 'wram', '.bss_upper': 'wram'}


def parse_map(path, osizes=None):
    """[(out section, input section, address, size, object basename)] for every input section the link kept, and the
    linker's alignment fill as ('*fill*', '(linker fill)'); osizes (a dict) receives each output section's size"""
    lines = open(path, encoding='utf-8', errors='replace').read().split('\n')
    i0 = next(i for i, l in enumerate(lines) if l.startswith('Linker script and memory map'))
    osec = pend = None
    out = []
    for l in lines[i0 + 1:]:
        if l[:1] == '.':
            osec = l.split()[0]
            pend = None
            mo = re.match(r'^(\.\S+)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)', l)
            if mo and osizes is not None:
                osizes[osec] = osizes.get(osec, 0) + int(mo.group(3), 16)
            continue
        mf = re.match(r'^ \*fill\*\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)', l)
        if mf:
            pend = None
            if osec in CLASS and int(mf.group(2), 16):
                out.append((osec, '*fill*', int(mf.group(1), 16), int(mf.group(2), 16), '(linker fill)'))
            continue
        m = re.match(r'^ (\.\S+|COMMON)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S.*)$', l)
        if m:
            name, addr, size, obj = m.group(1), int(m.group(2), 16), int(m.group(3), 16), m.group(4)
        else:
            m2 = re.match(r'^ (\.\S+|COMMON)$', l)
            if m2:
                pend = m2.group(1)
                continue
            m3 = re.match(r'^\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S.*)$', l)
            if not (m3 and pend):
                pend = None
                continue
            name, addr, size, obj = pend, int(m3.group(1), 16), int(m3.group(2), 16), m3.group(3)
        pend = None
        if size and osec in CLASS:
            o = obj.strip().replace(chr(92), '/')
            ob = ('lib:' + os.path.basename(o.split('(')[0]) + ':' + o.split('(')[1].rstrip(')')) if '.a(' in o else os.path.basename(o)
            out.append((osec, name, addr, size, ob))
    return out


def classes(osec):
    c = CLASS[osec]
    return ['irom', 'wram'] if c == 'data' else [c]


def match(rule, osec, isec, obj):
    if 'obj' in rule and not re.search(rule['obj'], obj):
        return False
    if 'sec' in rule and not re.search(rule['sec'], isec):
        return False
    if 'out' in rule and not re.search(rule['out'], osec):
        return False
    return True


def today(entries, bud, variant):
    mods = bud['modules']
    tot = collections.OrderedDict((m['name'], collections.Counter()) for m in mods)
    items = collections.defaultdict(list)
    unattr = []
    for osec, isec, addr, size, obj in entries:
        hit = rule = None
        for m in mods:
            for r in m['rules']:
                if match(r, osec, isec, obj):
                    hit, rule = m['name'], r
                    break
            if hit:
                break
        if hit is None:
            unattr.append((osec, isec, size, obj))
            continue
        for c in ([rule['as']] if 'as' in rule else classes(osec)):
            tot[hit][c] += size
        items[hit].append((isec, size, obj))
    rows = []
    for m in mods:
        cap = m.get('cap', {})
        if isinstance(cap, dict) and variant in cap and isinstance(cap[variant], dict):
            cap = cap[variant]
        over = {c: tot[m['name']][c] - v for c, v in cap.items() if isinstance(v, int) and tot[m['name']][c] > v}
        rows.append(dict(name=m['name'], area=m.get('area', ''), plan=m.get('plan', ''), used=dict(tot[m['name']]),
                         cap={c: v for c, v in cap.items() if isinstance(v, int)}, over=over, fate=m.get('fate', '')))
    return rows, unattr, items


def plan(rows_today, bud, variant):
    """allocations per placement (an allocation over its room fails) + forecasts (low / central / high) + the
    resident-code verdict per variant"""
    meas = {r['name']: r['used'] for r in rows_today}
    P = bud['plan']
    out, bad = [], []
    for m in P['modules']:
        row = dict(m)
        row['measured'] = None
        mb = [x for x in m.get('measured_by', []) if x in meas]
        if mb:
            cls = ('wram',) if m.get('kind') == 'data' else ('irom', 'wcode')
            used = sum(v for x in mb for c, v in meas[x].items() if c in cls)
            row['measured'] = used
            if used > m['budget']:
                bad.append('%s: MEASURED %d B over its allocation %d B' % (m['name'], used, m['budget']))
        sb = [x for x in m.get('stage1_by', []) if x in meas]
        if sb:
            cls = ('wram',) if m.get('kind') == 'data' else ('irom', 'wcode')
            row['stage1'] = sum(v for x in sb for c, v in meas[x].items() if c in cls) or None
        out.append(row)
    rooms = []
    for name, r in P['placements'].items():
        mods = [m for m in out if m['placement'] == name]
        alloc = sum(m['budget'] for m in mods)
        fc = {k: sum(m[k] for m in mods) for k in ('lo', 'cen', 'hi')}
        if alloc > r['bytes']:
            bad.append('placement %s: allocations add up to %d B, room %d B (the plan does not fit)' % (name, alloc, r['bytes']))
        rooms.append(dict(name=name, room=r['bytes'], alloc=alloc, free=r['bytes'] - alloc, what=r.get('what', ''), **fc))
    # verdict: resident code (code + rodata in IROM, window, WRAM-ROM) against its room, per forecast and variant
    rs = P['resident']
    room = sum(P['placements'][p]['bytes'] for p in rs['placements'])
    data_alloc = sum(m['budget'] for m in out if m['placement'] in rs['room_minus_data_in'] and m['kind'] == 'data')
    vroom = room - data_alloc
    verdict = []
    for var in ('release', 'test'):
        mods = [m for m in out if m['placement'] in rs['placements'] and m['kind'] in rs['kinds'] and m.get('variant', var) == var]
        row = dict(variant=var, room=vroom, irom_room=P['placements']['irom']['bytes'])
        for k in ('lo', 'cen', 'hi'):
            row[k] = sum(m[k] for m in mods)
        verdict.append(row)
    return out, rooms, bad, verdict


def report(build, bud, variant):
    osizes = {}
    entries = parse_map(os.path.join(build, 'main.map'), osizes)
    rows, unattr, items = today(entries, bud, variant)
    prow, rooms, pbad, verdict = plan(rows, bud, variant)
    errs = ['unattributed: %s %s %d B (%s)' % u for u in unattr]
    # accounting: the input sections + fill of every budgeted output section == its size in the map
    got = collections.Counter()
    for osec, isec, addr, size, obj in entries:
        got[osec] += size
    errs += ['map accounting: %s is %d B in the map, its input sections and fill add up to %d B' % (o, n, got[o])
             for o, n in sorted(osizes.items()) if o in CLASS and n != got[o]]
    errs += ['%s over its cap: %s' % (r['name'], ', '.join('%s +%d B' % kv for kv in r['over'].items())) for r in rows if r['over']]
    errs += pbad
    return dict(build=build, variant=variant, today=rows, items={k: v for k, v in items.items()}, plan=prow, rooms=rooms,
                verdict=verdict, errors=errs, ok=not errs)


def fmt(o):
    L = ['size budget (tools/fwbudget.py): %s' % o['build'], '',
         'TODAY (MEASURED from main.map; irom = code + rodata + .data image, wram = run-time data, wcode = code window):',
         '  %-42s %-12s %6s %6s %6s %6s   %-34s %s' % ('module', 'area', 'irom', 'wram', 'wcode', 'brain', 'cap', 'goes')]
    tt = collections.Counter()
    for r in o['today']:
        u = r['used']
        tt.update(u)
        cap = ' '.join('%s<=%d' % kv for kv in r['cap'].items())
        L.append('  %-42s %-12s %6d %6d %6d %6d   %-34s %s%s' % (r['name'][:42], r['area'], u.get('irom', 0), u.get('wram', 0), u.get('wcode', 0),
                                                         u.get('brain', 0), cap, r['fate'], '  OVER' if r['over'] else ''))
    L.append('  %-42s %-12s %6d %6d %6d %6d' % ('total', '', tt['irom'], tt['wram'], tt['wcode'], tt['brain']))
    L += ['', 'Plan 0.3.0: allocation per module (the target it must meet) and forecast lo / cen / hi (MODELLED from MEASURED',
          'ratios and sizes; basis per module in tools/budget.json). "meas" = the size of that code today where it exists.',
          '  %-58s %-12s %6s %6s %6s %6s %7s %6s %5s' % ('module', 'placement', 'alloc', 'lo', 'cen', 'hi', 'hi-alloc', 'meas', 'stage')]
    for r in o['plan']:
        L.append('  %-58s %-12s %6d %6d %6d %6d %+7d %6s %5s%s' % (r['name'][:58], r['placement'], r['budget'], r['lo'], r['cen'], r['hi'],
                                                         r['hi'] - r['budget'], r['measured'] if r['measured'] is not None else '-',
                                                         r.get('stage', ''), ' (TEST only)' if r.get('variant') == 'test' else ''))
    for r in o['plan']:
        dr = r.get('draft')
        if dr:
            L.append('  DRAFT SLOT %s: %s%s' % (r['name'][:40], dr.get('status'), (' Os %s / O2 %s B (%s)' % (
                dr.get('bytes_Os'), dr.get('bytes_O2'), dr.get('label'))) if dr.get('bytes_Os') else ' - ' + dr.get('by', '')))
    s1rows = [r for r in o['plan'] if r.get('stage1')]
    if s1rows:
        L += ['', 'STAGE 1 code doing these modules\' jobs today (MEASURED; NOT gated: it holds parts other rows count, and TEST',
              'counters; docs/BUDGET.md section 7):',
              '  %-58s %6s %7s %7s  %s' % ('module', 'alloc', 'stage-1', 'vs alloc', 'stage-1 modules')]
        for r in s1rows:
            L.append('  %-58s %6d %7d %+7d  %s' % (r['name'][:58], r['budget'], r['stage1'], r['stage1'] - r['budget'],
                                                  '; '.join(r['stage1_by'])))
    L += ['', '  %-13s %7s %7s %7s %8s %8s %8s  %s' % ('placement', 'room', 'alloc', 'free', 'lo', 'cen', 'hi', 'what')]
    for r in o['rooms']:
        L.append('  %-13s %7d %7d %7d %8d %8d %8d  %s' % (r['name'], r['room'], r['alloc'], r['free'], r['lo'], r['cen'], r['hi'], r['what'][:80]))
    L += ['', 'VERDICT - resident code (IROM + WRAM code window + WRAM-ROM) against its room (the 72 KB IROM firmware room 41,076 B + the',
          'window and wram_upper left after their data allocations):']
    for v in o['verdict']:
        parts = []
        for k in ('lo', 'cen', 'hi'):
            d = v['room'] - v[k]
            parts.append('%s %d (%s %d; IROM alone %s)' % (k, v[k], 'free' if d >= 0 else 'OVER by', abs(d),
                                                         'holds' if v[k] <= v['irom_room'] else 'needs %d B of spill' % (v[k] - v['irom_room'])))
        L.append('  %-7s room %d: %s' % (v['variant'], v['room'], '; '.join(parts)))
    L += ['', 'errors: %d' % len(o['errors'])] + ['  ' + e for e in o['errors']]
    L += ['', 'RESULT: %s' % ('PASS' if o['ok'] else 'FAIL')]
    return '\n'.join(L) + '\n'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('build')
    ap.add_argument('--budget', default=os.path.join(HERE, 'budget.json'))
    ap.add_argument('--variant')
    ap.add_argument('--txt')
    ap.add_argument('--json')
    a = ap.parse_args()
    bud = json.load(open(a.budget))
    variant = a.variant or os.path.basename(os.path.abspath(a.build))
    o = report(a.build, bud, variant)
    t = fmt(o)
    print(t, end='')
    if a.txt:
        open(a.txt, 'w', newline='\n').write(t)
    if a.json:
        json.dump(o, open(a.json, 'w', newline='\n'), indent=1)
    sys.exit(0 if o['ok'] else 1)


if __name__ == '__main__':
    main()
