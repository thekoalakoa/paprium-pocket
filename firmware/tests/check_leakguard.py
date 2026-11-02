#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_leakguard.py - the numeric-literal leak guard catches what it must, and its allow-list is exact.

    python -I -B tests/check_leakguard.py

1. Policy: tools/leak_allow.json holds exactly the two tables B Jam decided to type in (a locked decision of the plan):
   note_pitch = chip_note_pitch 108 x u16 and fm_pitch = chip_fm_fnum 13 x u16, each pinned by a values hash.
2. Clean pass: the guard on this tree (sources and every Pocket build's sections) with the real allow-list: exit 0,
   and both allow entries match exactly in core/song/song_tables.c and nowhere else in the sources (stage 5, our own
   song engine, typed the tables in; until then both matched nothing),
   and as exactly matching linked objects in the stage-5 builds.
3. Positive controls: files planted in a temporary directory OUTSIDE the tree (deleted afterwards) with values read
   in place from the reference images; one guard run over them must exit 1 and report every one:
     p1  8 values from the cart program's rodata, as u16 hex in a C array        (the required control)
     p2  the same 8 values in decimal in a Python list
     p3  12 bytes of the cart program's rodata as u8, one .byte per line in a .S file
     p4  8 big-endian words of the ROM, decimal, in a C header
     p5  the p1 values inside a C block comment
     p6  8 u32 words of the cart program's rodata, hex
     raw a raw binary (scanned like a built data section) with 12 rodata bytes (one data window) inside noise
   and the allow-list rule, with a temporary allow file whose places point into the temp dir:
     ok          chip_note_pitch[108] with the exact values: its hits are ALLOWED, no error
     bad_value   the same with one value changed: an allow error, and its other windows still hit
     bad_count   chip_fm_fnum with 12 of the 13 values: an allow error, and it hits
     bad_place   chip_fm_fnum exact, but outside the allowed place: an allow error, and it hits
     elf_ok      a linked RV32 ELF (xPack GCC, paths.local.json "riscv_bin") with the exact chip_note_pitch object:
                 its section hits are ALLOWED
     elf_bad     the same ELF with one value changed: an allow error, and its section hits fail
     elf_tail    the exact chip_note_pitch object followed by the chip's own next 12 bytes (its host-name string):
                 the windows that reach into those bytes still fail (only zero bytes may sit beside an allowed table)
     elf_zero    the exact chip_fm_fnum object followed by the chip's own two bytes after it (zeros): those windows
                 are ALLOWED (the zero-byte rule: B Jam's decision of 2026-10-30)
The reference paths come from paths.local.json "refs" (as for the guard). Exit 1 if any check fails."""
import hashlib, json, os, random, shutil, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
T = os.path.join(ROOT, 'tools')
sys.path.insert(0, T)
import leakguard as LG   # noqa: E402

ok_all = True


def res(name, ok, info=''):
    global ok_all
    ok_all &= bool(ok)
    print('%-4s %s %s' % ('PASS' if ok else 'FAIL', name, info))


def guard(*args):
    r = subprocess.run([sys.executable, '-I', '-B', os.path.join(T, 'leakguard.py')] + list(args), capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


# 1. policy
allow = json.load(open(os.path.join(T, 'leak_allow.json')))
want = {'note_pitch': ('chip_note_pitch', 'u16', 108), 'fm_pitch': ('chip_fm_fnum', 'u16', 13)}
got = {e['id']: (e['symbol'], e['elem'], e['count']) for e in allow['entries']}
shaok = all(len(e['values_sha256']) == 64 and int(e['values_sha256'], 16) >= 0 for e in allow['entries'])
res('1 allow-list holds exactly note_pitch 108 x u16 and fm_pitch 13 x u16, hash-pinned',
    got == want and len(allow['entries']) == 2 and shaok, json.dumps(got))

# 2. clean pass
tmp = tempfile.mkdtemp(prefix='pfw_leak_')
try:
    rc, out = guard('--json', os.path.join(tmp, 'clean.json'))
    rep = json.load(open(os.path.join(tmp, 'clean.json'))) if os.path.exists(os.path.join(tmp, 'clean.json')) else {}
    ents = rep.get('allow_entries', {})
    def placed(v):
        """one source place, in core/song/song_tables.c; the rest are the builds' linked objects; every one matches"""
        ps = [x.strip() for x in v.split(';')]
        src = [x for x in ps if ':' in x.split(' ')[0]]
        return (len(src) == 1 and src[0].startswith('core/song/song_tables.c:') and all(x.endswith(' matches') for x in ps)
                and all(' @' in x for x in ps if x not in src))
    typed = len(ents) == 2 and all(placed(v) for v in ents.values())
    res('2 clean pass: this tree and its builds, real allow-list -> exit 0, both entries match exactly in '
        'core/song/song_tables.c only (and as the builds\' linked objects)', rc == 0 and typed,
        out.strip().splitlines()[0] if out.strip() else '')
    if rc == 2:
        print(out)

    # 3. positive controls (values read in place; written only into the temp dir)
    loc = json.load(open(os.path.join(ROOT, 'paths.local.json')))
    cfg = json.load(open(os.path.join(T, 'leakguard.json')))
    W = cfg['window']
    cp = open(loc['refs']['cart_program'], 'rb').read()
    rom = open(loc['refs']['rom'], 'rb').read()
    assert hashlib.md5(cp).hexdigest() == cfg['references']['cart_program']['md5']
    assert hashlib.md5(rom).hexdigest() == cfg['references']['rom']['md5']

    def first_window(data, start, n, fmt, size, end=None):
        """the first window of n values (struct fmt) from `start` that the guard does not skip as weak"""
        end = end or len(data)
        for o in range(start, end - n * size, size):
            vals = list(struct.unpack_from('<' + fmt[-1] * n if fmt[0] == '<' else '>' + fmt[-1] * n, data, o))
            w = data[o:o + n * size]
            if not LG.weak(vals, W) and LG.strong_bytes(w, W) and data.count(w) == 1:
                return o, vals
        raise SystemExit('no eligible window from %#x' % start)

    # cart program rodata (image offsets of the chip map's rodata objects, cart program md5 checked above)
    o1, v1 = first_window(cp, 0x15DF0, 8, '<H', 2)            # DMA command words per sprite id (a)
    o3, v3 = first_window(cp, 0x15DB8, W['values_u8'], '<B', 1)  # slot -> VRAM id table
    o6, v6 = first_window(cp, 0x15BC4, 8, '<I', 4)            # hardware base constants (one word each)
    o4, v4 = first_window(rom, 0x400, 8, '>H', 2)             # ROM: 68000 big-endian words
    n_raw = cfg['sections']['data_window_bytes']
    o7 = next(o for o in range(0x15DF0, 0x16288) if LG.strong_bytes(cp[o:o + n_raw], W) and cp.count(cp[o:o + n_raw]) == 1)
    note = list(struct.unpack_from('<108H', cp, 0x1E358))
    fnum = list(struct.unpack_from('<13H', cp, 0x16288))
    d = os.path.join(tmp, 'planted')
    for sub in ('', 'allow_ok', 'allow_bad_value', 'allow_bad_count', 'elsewhere'):
        os.makedirs(os.path.join(d, sub), exist_ok=True)

    def wr(rel, text):
        open(os.path.join(d, rel), 'w', newline='\n').write(text)

    hx = lambda vals, w: ', '.join('0x%0*X' % (w, v) for v in vals)
    wr('p1_u16_hex.c', 'static const unsigned short planted[8] = { %s };\n' % hx(v1, 4))
    wr('p2_u16_dec.py', 'PLANTED = [%s]\n' % ', '.join(str(v) for v in v1))
    wr('p3_u8.S', '    .section .rodata\nplanted:\n' + ''.join('    .byte 0x%02X\n' % v for v in v3))
    wr('p4_rom_be.h', 'static const unsigned short planted_be[8] = {\n    %s\n};\n' % ', '.join(str(v) for v in v4))
    wr('p5_comment.c', '/* a table pasted into a comment:\n   %s\n */\nint x;\n' % ' '.join('0x%04x' % v for v in v1))
    wr('p6_u32.c', 'static const unsigned planted32[8] = { %s };\n' % hx(v6, 8))
    arr = lambda sym, vals: 'const unsigned short %s[%d] = {\n    %s\n};\n' % (sym, len(vals), ', '.join(str(v) for v in vals))
    wr('allow_ok/notes.c', arr('chip_note_pitch', note))
    bad = list(note)
    bad[50] += 1
    wr('allow_bad_value/notes.c', arr('chip_note_pitch', bad))
    wr('allow_bad_count/fnum.c', arr('chip_fm_fnum', fnum[:12]))
    wr('elsewhere/fnum.c', arr('chip_fm_fnum', fnum))
    rng = random.Random(0x5EED)
    raw = bytes(rng.getrandbits(8) for _ in range(500)) + cp[o7:o7 + n_raw] + bytes(rng.getrandbits(8) for _ in range(500))
    open(os.path.join(tmp, 'raw.bin'), 'wb').write(raw)
    # two linked RV32 ELFs holding chip_note_pitch: exact, and with one value changed
    gcc = os.path.join(loc.get('riscv_bin', ''), 'riscv-none-elf-gcc')
    tail = list(cp[0x1E358 + 216:0x1E358 + 228])
    after_fnum = list(cp[0x16288 + 26:0x16288 + 28])
    for tag, src in (('elf_tail', 'const unsigned short chip_note_pitch[108] = { %s };\n'
                                  'const unsigned char planted_tail[12] = { %s };\n' % (', '.join(str(v) for v in note),
                                                                                ', '.join(str(v) for v in tail))),
                     ('elf_zero', 'const unsigned short chip_fm_fnum[13] = { %s };\n'
                                  'const unsigned char planted_after[2] = { %s };\n'
                                  'const unsigned char planted_filler[4] = { 90, 165, 90, 165 };\n' % (
                                      ', '.join(str(v) for v in fnum), ', '.join(str(v) for v in after_fnum)))):
        c = os.path.join(tmp, tag + '.c')
        open(c, 'w', newline='\n').write(src + 'void _start(void) { for (;;); }\n')
        r = subprocess.run([gcc, '-march=rv32im', '-mabi=ilp32', '-O2', '-fno-toplevel-reorder', '-nostdlib',
                            '-nostartfiles', '-Wl,-e,_start', '-Wl,-Ttext=0x1000', c, '-o', os.path.join(tmp, tag + '.elf')],
                           capture_output=True, text=True)
        if r.returncode:
            raise SystemExit('cannot link the control ELF: %s' % r.stderr[-500:])
    elfs = ['--extra-elf', os.path.join(tmp, 'elf_tail.elf'), '--extra-elf', os.path.join(tmp, 'elf_zero.elf')]
    for tag, vals in (('elf_ok', note), ('elf_bad', bad)):
        c = os.path.join(tmp, tag + '.c')
        open(c, 'w', newline='\n').write('const unsigned short chip_note_pitch[108] = { %s };\n'
                                         'void _start(void) { for (;;); }\n' % ', '.join(str(v) for v in vals))
        r = subprocess.run([gcc, '-march=rv32im', '-mabi=ilp32', '-O2', '-nostdlib', '-nostartfiles', '-Wl,-e,_start',
                            '-Wl,-Ttext=0x1000', c, '-o', os.path.join(tmp, tag + '.elf')], capture_output=True, text=True)
        if r.returncode:
            raise SystemExit('cannot link the control ELF: %s' % r.stderr[-500:])
        elfs += ['--extra-elf', os.path.join(tmp, tag + '.elf')]
    A = json.loads(json.dumps(allow))
    for e in A['entries']:
        e['path_glob'] = '*/planted/allow_*'
    json.dump(A, open(os.path.join(tmp, 'allow.json'), 'w'))
    rc, out = guard('--no-tree', '--no-built', '--extra', d, '--extra-section', os.path.join(tmp, 'raw.bin'), *elfs,
                    '--allow', os.path.join(tmp, 'allow.json'), '--json', os.path.join(tmp, 'pos.json'))
    rep = json.load(open(os.path.join(tmp, 'pos.json'))) if os.path.exists(os.path.join(tmp, 'pos.json')) else {'hits': [], 'allowed_hits': [], 'errors': []}
    hit_in = lambda frag: [h for h in rep['hits'] if frag in h.get('src', h.get('elf', ''))]
    res('3 positive-control run exits 1', rc == 1, 'rc %d' % rc)
    for frag, what in (('p1_u16_hex.c', '8 cart-program rodata values as u16 hex (C array)'),
                       ('p2_u16_dec.py', 'the same 8 values in decimal (Python list)'),
                       ('p3_u8.S', '%d rodata bytes as .byte lines (.S)' % W['values_u8']),
                       ('p4_rom_be.h', '8 ROM big-endian words in decimal (C header)'),
                       ('p5_comment.c', 'the 8 values inside a block comment'),
                       ('p6_u32.c', '8 rodata u32 words in hex'),
                       ('raw.bin', '%d rodata bytes inside a raw section' % n_raw)):
        hs = hit_in(frag)
        res('3 caught: %s' % what, bool(hs), ('%d windows, e.g. %s +0x%X as %s' % (
            len(hs), hs[0]['ref'], hs[0]['ref_offset'], hs[0].get('as', 'raw'))) if hs else 'NOT CAUGHT')
    okd = [h for h in rep['allowed_hits'] if '/allow_ok/' in h.get('src', '')]
    errs = rep['errors']
    res('3 allow-list: the exact chip_note_pitch[108] is allowed (no failing hit, no error)',
        okd and not hit_in('/allow_ok/') and not any('/allow_ok/' in e for e in errs), '%d allowed windows' % len(okd))
    for frag, what in (('/allow_bad_value/', 'one value changed'), ('/allow_bad_count/', '12 of 13 values'),
                       ('/elsewhere/', 'exact values outside the allowed place')):
        res('3 allow-list: %s -> an allow error and failing hits' % what,
            any(frag in e for e in errs) and bool(hit_in(frag)), '; '.join(e for e in errs if frag in e)[:150])
    oke = [h for h in rep['allowed_hits'] if 'elf_ok.elf' in h.get('elf', '')]
    res('3 allow-list: a linked ELF with the exact chip_note_pitch object is allowed',
        oke and not hit_in('elf_ok.elf') and not any('elf_ok.elf' in e for e in errs), '%d allowed windows' % len(oke))
    res('3 allow-list: the ELF with one value changed -> an allow error and failing section hits',
        any('elf_bad.elf' in e for e in errs) and bool(hit_in('elf_bad.elf')),
        '%d windows; %s' % (len(hit_in('elf_bad.elf')), '; '.join(e for e in errs if 'elf_bad.elf' in e)[-90:]))
    ht = hit_in('elf_tail.elf')
    res('3 allow-list: the exact note table followed by the chip\'s own next 12 bytes -> those windows still fail',
        bool(ht) and all(h['addr'] + h['len'] > 0 for h in ht) and not any('elf_tail.elf' in e for e in errs),
        '%d failing windows, %d allowed' % (len(ht), len([h for h in rep['allowed_hits'] if 'elf_tail.elf' in h.get('elf', '')])))
    az = [h for h in rep['allowed_hits'] if 'elf_zero.elf' in h.get('elf', '')]
    res('3 allow-list: the exact fnum table followed by the chip\'s own two zero bytes -> those windows are allowed',
        bool(az) and not hit_in('elf_zero.elf') and not any('elf_zero.elf' in e for e in errs) and not any(after_fnum),
        '%d allowed windows, %d failing' % (len(az), len(hit_in('elf_zero.elf'))))
finally:
    shutil.rmtree(tmp, ignore_errors=True)
print('ALL PASS' if ok_all else 'SOME FAIL')
sys.exit(0 if ok_all else 1)
