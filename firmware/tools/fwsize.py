#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""fwsize.py - per-section sizes and per-region use / free space of a linked firmware ELF, against a layout JSON.

    python -I -B tools/fwsize.py <main.elf> <layout.json> [--json out.json] [--txt out.txt]

Reads the ELF's section headers directly (no toolchain needed). Every allocated section is assigned to the region that
holds its run address (VMA); a section with a different load address (LMA, e.g. .data's image in the IROM) is also
counted in the region that holds the LMA. 'free' = region size minus the bytes of the sections in it (both VMA and LMA
uses), so it is what a further link could still place there. Every number is measured from the ELF."""
import argparse, json, struct


def elf_sections(path):
    E = open(path, 'rb').read()
    assert E[:4] == b'\x7fELF' and E[4] == 1 and E[5] == 1
    e_shoff, = struct.unpack_from('<I', E, 32)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', E, 46)
    e_phoff, = struct.unpack_from('<I', E, 28); e_phentsize, e_phnum = struct.unpack_from('<HH', E, 42)
    sh = [struct.unpack_from('<10I', E, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    stro = sh[e_shstrndx][4]

    def name(o):
        return E[stro + o:E.index(b'\0', stro + o)].decode()
    ph = [struct.unpack_from('<8I', E, e_phoff + i * e_phentsize) for i in range(e_phnum)]
    out = []
    for s in sh:
        nm, typ, flags, addr, off, size = name(s[0]), s[1], s[2], s[3], s[4], s[5]
        if not (flags & 2) or size == 0:          # SHF_ALLOC
            continue
        lma = addr
        if typ != 8:                              # not NOBITS: find the LMA through the program headers
            for p in ph:
                if p[0] == 1 and p[1] <= off < p[1] + p[4]:
                    lma = p[3] + (off - p[1])
        out.append(dict(name=nm, vma=addr, lma=lma, size=size, nobits=(typ == 8)))
    return out


def report(elf, lay):
    regs = [dict(r, lo=int(r['lo'], 0), hi=int(r['hi'], 0)) for r in lay['regions']]
    secs = elf_sections(elf)

    def reg_of(a):
        for r in regs:
            if r['lo'] <= a < r['hi']:
                return r['name']
        return None
    use = {r['name']: [] for r in regs}
    rows = []
    for s in secs:
        rv = reg_of(s['vma']); rl = reg_of(s['lma']) if s['lma'] != s['vma'] else None
        rows.append(dict(s, region=rv, load_region=rl))
        if rv:
            use[rv].append((s['name'], s['vma'], s['size']))
        if rl:
            use[rl].append((s['name'] + ' (load image)', s['lma'], s['size']))
    regrep = []
    for r in regs:
        used = sum(x[2] for x in use[r['name']])
        top = max([x[1] + x[2] for x in use[r['name']]], default=r['lo'])
        # a fixed or stack region with no linked section is owned by something the linker does not see (the brain's
        # data, the stack): reported as reserved, not as free
        reserved = r.get('kind') in ('fixed', 'stack') and not use[r['name']]
        regrep.append(dict(name=r['name'], lo=r['lo'], hi=r['hi'], size=r['hi'] - r['lo'], kind=r.get('kind'),
                           used=used, free=0 if reserved else r['hi'] - r['lo'] - used, reserved=reserved,
                           end_of_use=top, tail_free=0 if reserved else r['hi'] - top,
                           sections=[dict(name=n, addr=a, size=z) for n, a, z in use[r['name']]]))
    return rows, regrep


def fmt(rows, regrep, title):
    o = [title, '', 'sections (MEASURED, ELF section headers):', '  %-14s %10s %10s %8s  %-12s %s' % ('section', 'vma', 'lma', 'bytes', 'region', 'load region')]
    for s in rows:
        o.append('  %-14s 0x%08X 0x%08X %8d  %-12s %s' % (s['name'], s['vma'], s['lma'], s['size'], s['region'] or '-', s['load_region'] or ''))
    o += ['', 'regions (used = sections placed there; free = size - used; reserved = owned outside the link):',
          '  %-11s %-23s %8s %8s %8s  %s' % ('region', 'range', 'size', 'used', 'free', 'kind / contents')]
    for r in regrep:
        o.append('  %-11s 0x%08X-0x%08X %8d %8d %8d  %s: %s' % (
            r['name'], r['lo'], r['hi'] - 1, r['size'], r['used'], r['free'], r['kind'],
            ', '.join('%s %d' % (x['name'], x['size']) for x in r['sections']) or ('reserved' if r['reserved'] else '(empty)')))
    return '\n'.join(o) + '\n'


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('elf'); ap.add_argument('layout')
    ap.add_argument('--json'); ap.add_argument('--txt')
    a = ap.parse_args()
    lay = json.load(open(a.layout))
    rows, regrep = report(a.elf, lay)
    t = fmt(rows, regrep, 'layout %s, %s' % (lay['name'], a.elf))
    print(t, end='')
    if a.txt:
        open(a.txt, 'w', newline='\n').write(t)
    if a.json:
        json.dump(dict(layout=lay['name'], sections=rows, regions=regrep), open(a.json, 'w', newline='\n'), indent=1)
