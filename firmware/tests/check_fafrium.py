#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_fafrium.py - the Fafrium file tools (docs/FAFRIUM.md) against each other and against a build:

    python -I -B tests/check_fafrium.py [--build DIR]   (DIR: a Pocket build's variant folder; default
                                                         build/s1/pocket88k/s5release, made by tools/fwbuild.py all)

1. the format constants of tools/mkfafrium.py equal the boot stub's own (.equ lines of
   board/pocket/fafrium/fafrium_stub.S): magic, end word, format, file length, layout, epoch, MCU interface, FEAT, clock,
   the section places, the stub's room;
2. `mkfafrium.py stub` builds the stub (it refuses a stub over its room, a finisher with an absolute address, a wrong
   CRC table) and its six images have the RTL's shapes (8,192 / 14,336 words, 12,288 lines a lane) with only the stub
   non-zero; SKIP without the RISC-V gcc (paths.local.json "riscv_bin");
3. `make` from the build's images (and its sram.bin, if it has one), then `check`: the file is 256 KB and equals the
   images byte for byte; `show` reads the firmware version (mkfafrium.py FW_VERSION) and the kind from the kind word;
4. every planted fault of `bad` fails `check` (negative controls). SKIP 3-4 without the build;
5. `memorder`: the file in memory order is the build's IROM image, its whole WRAM image and its SRAM code. The bytes
   that the stub does not place are the header, the zero fill and the end word;
6. `leak` on the file in memory order. It needs paths.local.json "refs" and "brain_dir", as tools/leakguard.py does,
   and is skipped without them. The allowed places follow the leak guard's rule for built sections (B Jam's decision
   of 2026-10-30). The test passes only when `leak` finds no hit at all outside the allowed places: not in the bytes
   the file format adds, and not in the image's own code or data either. (The level table and the note table's
   12-byte tail, which once sat in the image as data, are no longer in it: the firmware computes the level table at
   power-on and reads the tail from the player's ROM, so nothing has to be let through.) Five planted controls, each
   in a temporary copy that is deleted afterwards, must each be reported by `leak` at their place, outside the
   allowed places: ROM bytes in a zero stretch of the WRAM window, cart-program bytes in the IROM's zero tail,
   sub-CPU bytes in the zero fill, the file's own chip_note_pitch table (an allowed table) copied to a place that is
   not its object, and ROM bytes written inside another read-only data object of the image (the largest one in IROM
   that is not one of the two allowed tables). The last one is the control for the image's own data: a hit there
   is not allowed either."""
import argparse, hashlib, json, os, re, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = [sys.executable, '-I', '-B']
TOOL = os.path.join(ROOT, 'tools', 'mkfafrium.py')
STUB = os.path.join(ROOT, 'board', 'pocket', 'fafrium', 'fafrium_stub.S')
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import mkfafrium as M   # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket88k', 's5release'))
a = ap.parse_args()
fails = 0


def res(name, ok, info=''):
    global fails
    fails += not ok
    print('%-4s %s %s' % ('PASS' if ok else 'FAIL', name, info))


def run(*args):
    r = subprocess.run(PY + [TOOL] + list(args), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# 1 the constants
eq = {}
for line in open(STUB):
    m = re.match(r'\s*\.equ\s+(\w+),\s*([^/]+?)\s*(/\*.*)?$', line)
    if m:
        expr = m.group(2)
        for k in sorted(eq, key=len, reverse=True):
            expr = re.sub(r'\b%s\b' % k, str(eq[k]), expr)
        eq[m.group(1)] = int(eval(expr, {}))
pairs = [('MAGIC', M.MAGIC), ('ENDW', M.ENDW), ('HVER', M.HVER), ('HLEN', M.HLEN), ('FLEN', M.FLEN), ('LAYOUT', M.LAYOUT),
         ('EPOCH', M.EPOCH), ('IFACE', M.IFACE), ('FEAT', M.FEAT), ('CLKHZ', M.CLKHZ), ('IROM_LEN', M.IROM_LEN),
         ('W_DST', M.W_DST), ('W_LEN', M.W_LEN), ('S_DST', M.S_DST), ('S_MAX', M.S_MAX), ('S_OFF', M.S_OFF),
         ('STUB_LEN', M.STUB_LEN)]
bad = [k for k, v in pairs if eq.get(k) != v]
res('the stub and mkfafrium.py name the same format (%d constants)' % len(pairs), not bad, ' '.join(bad))

with tempfile.TemporaryDirectory() as tmp:
    # 2 the stub
    if not M.local_gcc_bin():
        print('SKIP the stub build (no RISC-V gcc: paths.local.json "riscv_bin")')
    else:
        rc, out = run('stub', '--out', os.path.join(tmp, 'stub'))
        res('mkfafrium.py stub: the stub fits its room, its finisher is position-independent, its table is CRC-32', rc == 0,
            out.strip().splitlines()[-1] if rc else '')
        if rc == 0:
            w = lambda n: open(os.path.join(tmp, 'stub', n)).read().split()
            shapes = (len(w('mcu.txt')), len(w('mcu_ext.txt'))) + tuple(len(w('wram_b%d.txt' % k)) for k in range(4))
            st = open(os.path.join(tmp, 'stub', 'stub.bin'), 'rb').read()
            nz = [i for i, x in enumerate(w('mcu.txt')) if int(x, 16)]
            zero = not any(int(x, 16) for n in ['mcu_ext.txt'] + ['wram_b%d.txt' % k for k in range(4)] for x in w(n))
            res('the six bitstream images: the RTL shapes, only the stub non-zero', shapes == (8192, 14336) + (12288,) * 4
                and zero and (not nz or nz[-1] < (len(st) + 3) // 4), '%s, stub %d B' % (shapes, len(st)))
    # 3-4 a file from the build
    img = os.path.join(a.build, 'img')
    if not os.path.exists(os.path.join(img, 'mcu.txt')):
        print('SKIP make / check / the planted faults (no build at %s: tools/fwbuild.py all)' % a.build)
    else:
        sram = os.path.join(img, 'sram.bin')
        sa = ['--sram', sram] if os.path.exists(sram) else []
        f = os.path.join(tmp, 'fafrium.bin')
        rc1, o1 = run('make', '--img', img, *sa, '--out', f)
        rc2, o2 = run('check', f, '--img', img, *sa)
        res('make + check: the file = the build\'s images byte for byte (%s)' % os.path.basename(a.build),
            rc1 == 0 and rc2 == 0 and os.path.getsize(f) == M.FLEN, o2.strip().splitlines()[-1] if o2.strip() else '')
        rc4, o4 = run('show', f)
        try:
            sv = json.loads(o4)
        except ValueError:
            sv = {}
        res('show: the kind word carries the firmware version %s and the kind (RELEASE)' % M.FW_VERSION,
            rc4 == 0 and sv.get('version') == M.FW_VERSION and sv.get('kind_name', '').startswith('RELEASE'),
            '%s, %s' % (sv.get('version'), sv.get('kind_name')))
        caught = []
        for k in M.BADS:
            b = os.path.join(tmp, 'bad_%s.bin' % k)
            rc, _ = run('bad', f, k, b)
            rc3, _ = run('check', b, '--img', img, *sa)
            if rc == 0 and rc3 != 0:
                caught.append(k)
        res('check refuses every planted fault (%d negative controls)' % len(M.BADS), len(caught) == len(M.BADS),
            'missed: ' + ' '.join(k for k in M.BADS if k not in caught) if len(caught) != len(M.BADS) else '')
        # 5 the file in memory order
        irom, wram, _ = M.read_images(img)
        sram_b = open(sram, 'rb').read() if sa else b''
        lg = M.swap16(open(f, 'rb').read())
        parts = {n: b for n, _, _, b in M.memorder(lg)}
        rc, o5 = run('memorder', f, '--out', os.path.join(tmp, 'mo'))
        disk = {n: open(os.path.join(tmp, 'mo', n + '.bin'), 'rb').read() for n in parts} if rc == 0 else {}
        res('memorder: IROM = the IROM image, WRAM = the whole WRAM image, SRAM = the SRAM code; not placed: the header, '
            'the zero fill and the end word', rc == 0 and disk == parts and parts['irom'] == irom and parts['wram'] == wram
            and parts['sram'] == sram_b and parts['header'] == lg[:M.HLEN] and len(parts['tail']) == M.FLEN - M.S_OFF -
            len(sram_b) and not any(parts['tail'][:-4]) and parts['tail'][-4:] == struct.pack('<I', M.ENDW),
            '%d / %d / %d B' % (len(parts['irom']), len(parts['wram']), len(parts['sram'])))
        # 6 the leak guard on the memory-order copy
        loc_p = os.path.join(ROOT, 'paths.local.json')
        loc = json.load(open(loc_p)) if os.path.exists(loc_p) else {}
        elf = os.path.join(a.build, 'main.elf')
        ovl = os.path.join(a.build, 'ovl', 'ovl.elf')
        if not (loc.get('refs') and (os.environ.get('PAPRIUM_BRAIN_DIR') or loc.get('brain_dir'))) or not os.path.exists(elf):
            print('SKIP the memory-order leak check (paths.local.json "refs" / "brain_dir", or %s, missing)' % elf)
        else:
            # main.elf of a build with the MegaWire code also holds the SRAM code's sections (at 0x0800_0000), so it is
            # the SRAM code's ELF too: without it the SRAM part's hits could not be placed
            ea = ['--elf', elf] + (['--elf', ovl] if os.path.exists(ovl) else []) + (['--sram-elf', elf] if sa else [])

            def leak(path, tag):
                j = os.path.join(tmp, 'leak_%s.json' % tag)
                rc, out = run('leak', path, *ea, '--json', j)
                return rc, (json.load(open(j)) if os.path.exists(j) else None), out

            def outside(rep):
                """the hits outside the allowed places"""
                return [h for h in rep['hits'] if not h['allowed']]

            rc, rep, out = leak(f, 'file')
            if rep is None:
                res('leak: the guard runs on the file in memory order', False, out.strip().splitlines()[-1] if out.strip() else '')
            else:
                bad = outside(rep)
                objs = {}
                for h in bad:
                    objs['%s %s' % (h['part'], h['symbol'])] = objs.get('%s %s' % (h['part'], h['symbol']), 0) + 1
                res('leak: no hit outside the allowed places in the file in memory order (none that the file format '
                    'adds, none in the image\'s own code or data)', rc == 0 and not bad,
                    '%d raw hits, %d outside the allowed places%s' % (
                        rep['raw_hits'], len(bad), (': ' + ', '.join('%s %d' % kv for kv in sorted(objs.items()))) if bad else ''))
                # planted controls: game bytes read in place from the references (md5-checked), written only into tmp
                sys.path.insert(0, os.path.join(ROOT, 'tools'))
                import leakguard as LG   # noqa: E402
                cfg = json.load(open(os.path.join(ROOT, 'tools', 'leakguard.json')))
                W = cfg['window']
                refd = {}
                for k in ('rom', 'cart_program', 'sub_program'):
                    d = open(loc['refs'][k], 'rb').read()
                    assert hashlib.md5(d).hexdigest() == cfg['references'][k]['md5'], k
                    refd[k] = d

                def chunk(d, start, n=48):
                    for o in range(start, len(d) - n):
                        c = d[o:o + n]
                        if all(LG.strong_bytes(c[i:i + 12], W) for i in range(0, n - 11, 12)):
                            return c
                    raise SystemExit('no strong chunk from %#x' % start)

                def zero_run(b, lo, hi, n, from_end=False):
                    rng = range(hi - n, lo - 1, -4) if from_end else range(lo, hi - n + 1, 4)
                    for o in rng:
                        if not any(b[o:o + n]):
                            return o
                    raise SystemExit('no zero run of %d B' % n)

                w0 = M.W_DST - 0x80000000
                wo = zero_run(wram, w0, w0 + M.W_LEN, 512)            # a zero stretch inside the WRAM window
                io = zero_run(irom, 0, M.IROM_LEN, 128, from_end=True)  # the IROM's zero tail
                fo = M.S_OFF + len(sram_b) + 0x1000                  # the zero fill
                import fwelf   # noqa: E402
                nps = [s for s in fwelf.symbols(elf) if s['name'] == 'chip_note_pitch']
                plants = [('ROM bytes in the WRAM window', 'wram', M.HLEN + M.IROM_LEN + wo - w0 + 64, 0x80000000 + wo + 64,
                           chunk(refd['rom'], 0x400)),
                          ('cart-program bytes in the IROM\'s zero tail', 'irom', M.HLEN + io + 32, io + 32,
                           chunk(refd['cart_program'], 0x15DF0)),
                          ('sub-CPU bytes in the zero fill', 'tail', fo, fo - M.S_OFF - len(sram_b), chunk(refd['sub_program'], 0x2E00))]
                if nps:
                    np0 = nps[0]['value']
                    plants.append(('the allowed chip_note_pitch table copied off its object', 'wram',
                                   M.HLEN + M.IROM_LEN + wo - w0 + 64, 0x80000000 + wo + 64,
                                   bytes(lg[M.HLEN + np0:M.HLEN + np0 + nps[0]['size']])))
                # another read-only data object in IROM: the largest .rodata object that is not an allowed table
                ros = sorted((s for s in fwelf.symbols(elf) if s['type'] == 'OBJECT' and s['section'] == '.rodata'
                              and s['size'] >= 64 and s['value'] + s['size'] <= M.IROM_LEN
                              and s['name'] not in ('chip_note_pitch', 'chip_fm_fnum')), key=lambda s: -s['size'])
                if ros:
                    plants.append(('ROM bytes inside the image\'s own data object %s' % ros[0]['name'], 'irom',
                                   M.HLEN + ros[0]['value'] + 8, ros[0]['value'] + 8, chunk(refd['rom'], 0x400)))
                for i, (what, part, foff, at, b) in enumerate(plants):
                    pl = bytearray(lg)
                    pl[foff:foff + len(b)] = b
                    M.recrc(pl)
                    p = os.path.join(tmp, 'plant_%d.bin' % i)
                    open(p, 'wb').write(M.swap16(bytes(pl)))
                    rc, rep, out = leak(p, 'plant_%d' % i)
                    os.remove(p)

                    def at_plant(h):
                        x = int(h['at'].lstrip('+'), 16)
                        return h['part'] == part and at - 12 < x < at + len(b)
                    hs = [h for h in (rep or {}).get('hits', []) if not h['allowed'] and at_plant(h)]
                    res('leak catches a planted control at its place, outside the allowed places: %s' % what,
                        rc == 1 and bool(hs),
                        '%d windows at %s %s' % (len(hs), part, ('0x%08X' % at) if part != 'tail' else '+0x%X' % at))
                res('the five planted controls were all made', len(plants) == 5, '%d made' % len(plants))
print('ALL PASS' if not fails else '%d FAILED' % fails)
sys.exit(1 if fails else 0)
