#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""fwobjs.py - bytes per object file and per tree area, measured from a GNU ld map.

    python -I -B tools/fwobjs.py <main.map> [--manifest fwbuild.json] [--txt out.txt]

Every input section the link kept is attributed to its object (archive members count as their library) and to the
output section it went to, grouped as: code (.text, .text_hi, .ext_text), rodata (.rodata*), data (.data image),
bss (.bss, .bss_noclear, .bss_gap, .noinit), window (.wram_text: code + rodata in the WRAM code window), brain
(.brain_irom). Objects are mapped to tree areas through fwbuild.json's source list (legacy/026, interim/album, buddy,
board/pocket, ...); library members are 'lib'. IROM (the cart MCU's code memory) bytes = code + rodata (read-only
data) + data (the .data image lives in the IROM).
The linker's alignment fill between input sections ("*fill*" in the map) is its own row, '(linker fill)' in area
'link', so the totals equal the ELF section sizes in layout.txt. Caveat: merged string literals (.rodata.str*) are
attributed by the linker to the first object that has them."""
import argparse, collections, json, os, re

KIND = [('window', ('.wram_text',)), ('brain', ('.brain_irom',)), ('code', ('.text', '.text_hi', '.ext_text')),
        ('rodata', ('.rodata', '.rodata1', '.rodata_arrays')), ('data', ('.data', '.sdata')),
        ('bss', ('.bss', '.bss_noclear', '.bss_gap', '.noinit', '.sbss', '.tbss', '.sbss2'))]
COLS = ('code', 'rodata', 'data', 'bss', 'window', 'brain')


def kind_of(osec):
    for k, names in KIND:
        if osec in names:
            return k
    return None


def parse(path):
    lines = open(path, encoding='utf-8', errors='replace').read().split('\n')
    i0 = next(i for i, l in enumerate(lines) if l.startswith('Linker script and memory map'))
    out = collections.defaultdict(collections.Counter)
    osec = None
    pend = None
    for l in lines[i0 + 1:]:
        if l[:1] == '.':                                  # an output section statement
            osec = l.split()[0]; pend = None
            continue
        mf = re.match(r'^ \*fill\*\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)', l)
        if mf:                                            # alignment fill between input sections
            pend = None
            if kind_of(osec):
                out['(linker fill)'][kind_of(osec)] += int(mf.group(2), 16)
            continue
        m = re.match(r'^ (\.\S+|COMMON)\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S.*)$', l)
        if m:
            name, size, obj = m.group(1), int(m.group(3), 16), m.group(4)
        else:
            m2 = re.match(r'^ (\.\S+|COMMON)$', l)
            if m2:
                pend = m2.group(1)
                continue
            m3 = re.match(r'^\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S.*)$', l)
            if not (m3 and pend):
                pend = None
                continue
            name, size, obj = pend, int(m3.group(2), 16), m3.group(3)
        pend = None
        k = kind_of(osec)
        if k and size:
            out[obj.strip()][k] += size
    return out


def area(obj, srcmap):
    if obj == '(linker fill)':
        return 'link'
    o = obj.replace(chr(92), '/')
    if '.a(' in o:
        return 'lib (' + os.path.basename(o.split('(')[0]) + ')'
    return srcmap.get(os.path.basename(o), '?')


def report(mapf, manifest):
    cfg = json.load(open(manifest))
    srcmap = {}
    s1 = cfg.get('s1', {}).get('pocket', {})
    for s in cfg['pocket']['sources'] + s1.get('sources', []) + [x for v in s1.get('variant_sources', {}).values() for x in v]:
        d = os.path.dirname(s)
        srcmap.setdefault(os.path.basename(s) + '.o', 'board/pocket/neorv32' if d.startswith('board/pocket/neorv32') else d)
    per = parse(mapf)
    rows = sorted(((area(obj, srcmap), os.path.basename(obj.replace(chr(92), '/')), c) for obj, c in per.items()),
                  key=lambda r: (r[0], r[1]))
    head = '  %-24s %-28s %7s %7s %6s %6s %7s %7s %7s' % (('area', 'object') + COLS + ('IROM',))
    o = ['bytes per object (MEASURED from %s; IROM = code + rodata + data image)' % os.path.basename(mapf), '', head]
    tot = collections.defaultdict(collections.Counter)
    for a, ob, c in rows:
        o.append('  %-24s %-28s %7d %7d %6d %6d %7d %7d %7d' % ((a, ob[:28]) + tuple(c[k] for k in COLS) + (c['code'] + c['rodata'] + c['data'],)))
        tot[a].update(c)
    o += ['', 'per area:']
    allc = collections.Counter()
    for a in sorted(tot):
        c = tot[a]; allc.update(c)
        o.append('  %-53s %7d %7d %6d %6d %7d %7d %7d' % ((a,) + tuple(c[k] for k in COLS) + (c['code'] + c['rodata'] + c['data'],)))
    o.append('  %-53s %7d %7d %6d %6d %7d %7d %7d' % (('total',) + tuple(allc[k] for k in COLS) + (allc['code'] + allc['rodata'] + allc['data'],)))
    return '\n'.join(o) + '\n', {a: dict(c) for a, c in tot.items()}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('map')
    ap.add_argument('--manifest', default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'fwbuild.json'))
    ap.add_argument('--txt')
    a = ap.parse_args()
    t, _ = report(a.map, a.manifest)
    print(t, end='')
    if a.txt:
        open(a.txt, 'w', newline='\n').write(t)
