#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_tree.py - static guards on the source tree (no build needed).

    python -I -B tests/check_tree.py [--brain-dir DIR]
    python -I -B tests/check_tree.py --selftest     (rule 5's negative controls: each planted mistake must fail)

1. core/ is board-independent: in code (comments skipped), no board address literal (MCU regions 0x01-0x07/0x09/0x0A/
   0x0B, WRAM 0x8000xxxx, NEORV32 IO 0xFFFFFFxx), no board identifier (ADDR_*, FPGAIO, POCKET_*, BUD_*, GPIO_INPUT,
   MTIME), and board/board.h is the only board header it includes: every #include in core/ names board.h, a header of
   core/ itself, or a standard C header (stdint.h, stddef.h, stdbool.h, string.h, limits.h).
2. board/pocket/include/pocket_map.h's layout constants equal board/pocket/link/pocket72k.json.
3. board/pocket/link/pocket72k.ld is exactly what tools/mkld.py generates from the JSON (and pocket88k.ld, the layout
   of the stage-5 images, which add our own song engine).
4. No game-derived bytes in the tree: no tracked file holds a 64-byte run of brain.bin, cf.bin or rodata.bin (the
   0.2.6 brain and the stage-1 one, "brain_dir" / "brain_dir_s1", when known), and no file is a ROM-sized blob (> 1 MB) or a .bin/.md/.gen/.smd ROM image.
5. The stage-1 source set (fwbuild.json "s1": its sources, the test / release variant sources, compile_only, and the
   stage-1 headers) reaches no 0.2.6 cart register and types no clock (MCU interface v1.0 moved the registers from
   the RAMDP page $1FE0-$1FFF to the register file; the clock comes from the build only, MCU_INTERFACE.md 7):
   a. the stage-1 files themselves, comments skipped (the moved 0.2.6 files and the shared buddy wrapper are left to
      b: they are 0.2.6 code under FW_S1 guards): no reg_cmd / reg_status_* / BUD_RAMDP_REG* name, no literal in the
      0.2.6 register page 0x02001FE0-0x02001FFF;
   b. every translation unit preprocessed exactly as tools/fwbuild.py compiles it, test and release, with the build's
      clock value replaced by a name (so a typed-in clock cannot hide behind it): no member access to reg_cmd /
      reg_status_*, no register-page literal, no clock literal (53,693,175 / 53,203,424 Hz, or their ms counts
      53,693 / 53,203); the clock name must reach at least one unit. Needs the RISC-V gcc (paths.local.json
      "riscv_bin"): SKIP without it. The derived clock figures (84 delay, TIM7, feeder grid...) are
      tests/check_clock.py's rule 1.
6. One allow-list: tests/equiv/allowlist.json is the only maintained list (the plan's "Testing rule"); docs/ALLOWLIST.md
   is its plain-English review page. Every JSON id has exactly one row there (a line starting "| **<id>** |") and the
   page has no row the JSON lacks. SKIP (ids still checked unique) in a copy without the page."""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import mkld   # noqa: E402

ok_all = True


def res(name, ok, info=''):
    global ok_all
    ok_all &= bool(ok)
    print('%-4s %s %s' % ('PASS' if ok else 'FAIL', name, info))


# ---- rule 5: the stage-1 source set (FW_S1, our new firmware)
S1_NUM = re.compile(r'(?<![\w.])(0[xX][0-9a-fA-F]+|\d[\d_]*)[uUlL]*(?![\w.])')
S1_REG_ID = re.compile(r'\b(reg_cmd|reg_status_\w+|BUD_RAMDP_REG\w*)\b')
S1_REG_USE = re.compile(r'(->|\.)\s*(reg_cmd|reg_status_\w+)\b')
S1_PAGE = (0x02001FE0, 0x02001FFF)
S1_CLOCKS = {53693175: 'NTSC clock', 53203424: 'PAL clock', 53693: '1 ms NTSC', 53203: '1 ms PAL'}
S1_CLK_TOKEN = 'S1_BRD_CLK_HZ_FROM_THE_BUILD'


def s1_val(s):
    s = s.replace('_', '')
    return int(s, 16) if s[:2] in ('0x', '0X') else int(s, 10)


def s1_strip(t):
    t = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), t, flags=re.S)
    return '\n'.join(ln.split('//')[0] for ln in t.split('\n'))


def s1_scan(code, pre):
    """[(line, what)]: register names (raw text) or member accesses (preprocessed), page literals, clock literals
    (preprocessed only: in raw text the clock figures are check_clock's)"""
    out = []
    for i, ln in enumerate(code.split('\n'), 1):
        for m in (S1_REG_USE if pre else S1_REG_ID).finditer(ln):
            out.append((i, m.group(0).strip()))
        for m in S1_NUM.finditer(ln):
            v = s1_val(m.group(1))
            if S1_PAGE[0] <= v <= S1_PAGE[1]:
                out.append((i, '%s (0.2.6 register page)' % m.group(1)))
            elif pre and v in S1_CLOCKS:
                out.append((i, '%s (%s)' % (m.group(1), S1_CLOCKS[v])))
    return out


def s1_files(root):
    """fwbuild.json at root -> (cfg, {variant: its sources}, the stage-1 files of rule 5a)"""
    cfg = json.load(open(os.path.join(root, 'fwbuild.json')))
    sp = cfg['s1']['pocket']
    moved = set(sp.get('no_extra', []))
    per = {v: sp['sources'] + sp.get('variant_sources', {}).get(v, []) for v in ('test', 'release')}
    own = set(sp.get('compile_only', []))
    for ss in per.values():
        own |= {s for s in ss if s not in moved and not os.path.basename(s).startswith('zz_buddy')}
    for dp, dn, fn in os.walk(os.path.join(root, 'core')):
        own |= {os.path.relpath(os.path.join(dp, f), root).replace(os.sep, '/') for f in fn if f.endswith('.h')}
    for d, pat in (('interim/s1', r'.*\.h$'), ('board', r'.*\.h$'), ('board/pocket', r'(s1_.*|dbgsave)\.h$'),
                   ('buddy', r's1_.*\.h$')):
        dd = os.path.join(root, *d.split('/'))
        own |= {d + '/' + f for f in os.listdir(dd) if re.match(pat, f) and os.path.isfile(os.path.join(dd, f))}
    return cfg, per, sorted(own)


def s1_compiler():
    """(gcc, env) of tools/fwbuild.py's RISC-V toolchain, or (None, None)"""
    try:
        import fwbuild   # noqa: E402  (the tree's own build tool: paths.local.json / environment)
        P = fwbuild.local_paths()
        gcc = fwbuild.tool(P['riscv_bin'], fwbuild.CFG['pocket']['prefix'] + 'gcc')
        return gcc, fwbuild.env_with(os.path.dirname(gcc))
    except SystemExit:
        return None, None


def s1_rules(root, gcc, env, only=None):
    """rule 5 on the tree at root: (5a hits, 5b hits, stage-1 files, units preprocessed, units the clock name reached);
    only = the sources to preprocess (the selftest's planted files), None = all"""
    cfg, per, own = s1_files(root)
    raw = []
    for f in own:
        txt = open(os.path.join(root, *f.split('/')), encoding='utf-8', errors='replace').read()
        raw += ['%s:%d %s' % (f, i, w) for i, w in s1_scan(s1_strip(txt), False)]
    pre, n, tok = [], 0, 0
    if gcc:
        sp, pc = cfg['s1']['pocket'], cfg['pocket']
        incs = []
        for d in sp['include']:
            incs += ['-I', os.path.join(root, *d.split('/'))]
        for v, srcs in per.items():
            opts = pc['cc_opts'] + sp.get('cc_extra', []) + cfg['s1']['defines'] + ['-DBRD_CLK_HZ=' + S1_CLK_TOKEN] + \
                sp['variants'][v]['defines']
            opts = [o for o in opts if not o.startswith(('-l', '-Wl,', '-nostartfiles'))]
            for s in srcs:
                if only is not None and s not in only:
                    continue
                r = subprocess.run([gcc, '-E', '-P'] + opts + incs + [os.path.join(root, *s.split('/'))], env=env,
                                   capture_output=True, text=True)
                n += 1
                if r.returncode:
                    pre.append('%s %s: the preprocessor failed: %s' % (v, s, r.stderr.strip()[:200]))
                    continue
                tok += S1_CLK_TOKEN in r.stdout
                pre += ['%s %s: %s' % (v, s, w) for i, w in s1_scan(r.stdout, True)]
    return raw, pre, len(own), n, tok


S1_PLANTS = [
    ('a reg_cmd read in a stage-1 file', 'core/sched/wheel.c',
     '\nunsigned short planted_rd(void) { return ppmio.ramdp->reg_cmd; }\n', True),
    ('the register page typed into the board layer', 'board/pocket/s1_board.c',
     '\nvolatile unsigned short *const planted_reg = (volatile unsigned short *)0x02001FEAu;\n', True),
    ('BUD_RAMDP_REGCMD used by the stage-1 glue', 'buddy/s1_glue.c',
     '\nvolatile unsigned short *planted_glue(void) { return (volatile unsigned short *)BUD_RAMDP_REGCMD; }\n', True),
    ("a 0.2.6 register read on a moved file's FW_S1 path", 'legacy/026/mame.c',
     '\nunsigned short planted_026(void) { return ppmio.ramdp->reg_status_1; }\n', True),
    ("a clock literal on a moved file's FW_S1 path", 'interim/album/mdp.c', '\nunsigned planted_ms = 53693u;\n', True),
    ('control: the same read on the 0.2.6 path only (#if !FW_S1)', 'legacy/026/mame.c',
     '\n#if !FW_S1\nunsigned short planted_026(void) { return ppmio.ramdp->reg_status_1; }\n#endif\n', False),
    ('control: register names and a clock in a comment', 'core/sched/wheel.c',
     '\n/* 0.2.6 read reg_cmd / reg_status_1 at 0x02001FEA, 53693 cycles a ms */\n', False)]


def selftest():
    """rule 5's negative controls on copies of the tree: each planted mistake must be found, the controls must not"""
    gcc, env = s1_compiler()
    if not gcc:
        print('FAIL the selftest needs the RISC-V gcc (paths.local.json "riscv_bin")')
        return False
    good = True
    files = {f for _, f, _, _ in S1_PLANTS}
    for name, f, text, want in [('unmodified copy passes', None, None, False)] + S1_PLANTS:
        tmp = tempfile.mkdtemp(prefix='treeself_')
        try:
            for d in ('board', 'core', 'interim', 'legacy', 'buddy', 'tests/s1'):
                shutil.copytree(os.path.join(ROOT, *d.split('/')), os.path.join(tmp, *d.split('/')),
                                ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copyfile(os.path.join(ROOT, 'fwbuild.json'), os.path.join(tmp, 'fwbuild.json'))
            if f:
                with open(os.path.join(tmp, *f.split('/')), 'a', newline='\n') as fh:
                    fh.write(text)
            raw, pre, nown, n, tok = s1_rules(tmp, gcc, env, only={f} if f else files)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        found = raw + pre
        ok = bool(found) == want and n > 0
        good &= ok
        print('%-4s %-62s -> %d hit(s) %s' % ('PASS' if ok else 'FAIL', name, len(found), (found or [''])[0][:70]))
    print('ALL PASS' if good else 'SOME FAIL')
    return good


ap = argparse.ArgumentParser()
ap.add_argument('--brain-dir')
ap.add_argument('--selftest', action='store_true')
a = ap.parse_args()
if a.selftest:
    sys.exit(0 if selftest() else 1)

# 1. core/
# MCU region literals: 0x01..0x07, 0x09, 0x0A (0x08xxxxxx is left out: it is also the STM32 flash, and chip offsets are
# allowed in core/), WRAM 0x8000xxxx, NEORV32 IO 0xFFFFFFxx. Comments are skipped (chip citations live there).
ADDR = re.compile(r'(?<![0-9a-zA-Z_])0x(0[1-79aAbB][0-9a-fA-F]{6}|8000[0-9a-fA-F]{4}|[fF]{6}[0-9a-fA-F]{2})(?![0-9a-fA-F])')
IDENT = re.compile(r'\b(ADDR_\w+|FPGAIO|POCKET_\w+|BUD_\w+|GPIO_INPUT|MTIME\w*)\b')
INC = re.compile(r'#\s*include\s*[<"]([^">]+)[">]')
STD_H = {'stdint.h', 'stddef.h', 'stdbool.h', 'string.h', 'limits.h'}
CORE_H = {f for dp, dn, fn in os.walk(os.path.join(ROOT, 'core')) for f in fn if f.endswith('.h')}


def bad_include(code):
    m = INC.search(code)
    return bool(m) and not (m.group(1) == 'board.h' or m.group(1) in STD_H or os.path.basename(m.group(1)) in CORE_H)


hits = []
for dp, dn, fn in os.walk(os.path.join(ROOT, 'core')):
    for f in fn:
        if f.endswith(('.c', '.h', '.S', '.s')):
            p = os.path.join(dp, f)
            txt = open(p, encoding='utf-8', errors='replace').read()
            txt = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), txt, flags=re.S)   # keep line numbers
            for i, ln in enumerate(txt.split('\n'), 1):
                code = ln.split('//')[0]
                if ADDR.search(code) or IDENT.search(code) or bad_include(code):
                    hits.append('%s:%d' % (os.path.relpath(p, ROOT), i))
res('1 core/ has no board addresses or identifiers; its only board header is board.h', not hits, ' '.join(hits[:10]))

# 2. pocket_map.h vs pocket72k.json
lay = json.load(open(os.path.join(ROOT, 'board', 'pocket', 'link', 'pocket72k.json')))
R = {r['name']: (int(r['lo'], 0), int(r['hi'], 0)) for r in lay['regions']}
H = {}
for ln in open(os.path.join(ROOT, 'board', 'pocket', 'include', 'pocket_map.h')):
    m = re.match(r'#define\s+(POCKET_\w+)\s+(0x[0-9A-Fa-f]+)u', ln)
    if m:
        H[m.group(1)] = int(m.group(2), 16)
want = {'POCKET_IROM_BYTES': 1024 * (lay['irom']['rom0_kb'] + lay['irom']['ext_kb']),
        'POCKET_IROM_LO_END': R['irom_lo'][1], 'POCKET_BRAIN_LO': R['brain'][0], 'POCKET_BRAIN_HI': R['brain'][1],
        'POCKET_IROM_HI_END': R['irom_hi'][1], 'POCKET_WRAM_BYTES': 1024 * lay['wram']['kb'],
        'POCKET_WRAM_DATA_END': R['wram_data'][1], 'POCKET_BRAIN_DATA_LO': R['brain_data'][0],
        'POCKET_WRAM_SCHED_LO': R['wram_sched'][0], 'POCKET_WCODE_LO': R['wcode'][0], 'POCKET_WCODE_HI': R['wcode'][1],
        'POCKET_WRAM_UPPER_LO': R['wram_upper'][0], 'POCKET_STACK_LO': R['stack'][0], 'POCKET_STACK_TOP': R['stack'][1]}
bad = ['%s=%#x (json %#x)' % (k, H.get(k, -1), v) for k, v in want.items() if H.get(k) != v]
res('2 pocket_map.h layout constants == pocket72k.json', not bad, ' '.join(bad))

# 3. generated linker script
src = mkld.gen(lay)
cur = open(os.path.join(ROOT, 'board', 'pocket', 'link', 'pocket72k.ld'), 'rb').read().decode()
res('3 pocket72k.ld == mkld.py(pocket72k.json)', cur == src)
lay88 = json.load(open(os.path.join(ROOT, 'board', 'pocket', 'link', 'pocket88k.json')))     # stage 5 (our
                                                                                             # own song engine)
cur = open(os.path.join(ROOT, 'board', 'pocket', 'link', 'pocket88k.ld'), 'rb').read().decode()
res('3 pocket88k.ld == mkld.py(pocket88k.json) (stage 5)', cur == mkld.gen(lay88))

# 4. no game-derived bytes
files = subprocess.run(['git', '-C', ROOT, 'ls-files', '--cached', '--others', '--exclude-standard'],
                       capture_output=True, text=True).stdout.split()
big = [f for f in files if os.path.getsize(os.path.join(ROOT, f)) > 1 << 20 or f.lower().endswith(('.bin', '.md5x', '.gen', '.smd')) or
       (f.lower().endswith('.md') and os.path.getsize(os.path.join(ROOT, f)) > 1 << 20)]
res('4 no ROM-sized blobs or .bin images in the tree (%d files)' % len(files), not big, ' '.join(big[:10]))
loc4 = json.load(open(os.path.join(ROOT, 'paths.local.json'))) if os.path.exists(os.path.join(ROOT, 'paths.local.json')) else {}
bdir = a.brain_dir or os.environ.get('PAPRIUM_BRAIN_DIR') or loc4.get('brain_dir')
bdir_s1 = os.environ.get('PAPRIUM_BRAIN_DIR_S1') or loc4.get('brain_dir_s1')     # the stage-1 brain (with the counter
                                                                                 # fix of docs/STAGE1_PLAN.md X3)
bdirs = [d for d in (bdir, bdir_s1) if d and os.path.isdir(d)]
if bdirs:
    probes = []
    for d in bdirs:
        for fn in ('brain.bin', 'cf.bin', 'rodata.bin'):
            b = open(os.path.join(d, fn), 'rb').read()
            probes += [b[i:i + 64] for i in range(0, len(b) - 64, 1024) if len(set(b[i:i + 64])) > 8]
    leak = [f for f in files if any(pr in open(os.path.join(ROOT, f), 'rb').read() for pr in probes)]
    res('4 no tracked file contains brain, cf or rodata bytes (%d probes, %d brain dirs)' % (len(probes), len(bdirs)),
        not leak, ' '.join(leak))
else:
    print('SKIP 4 brain-byte scan (no brain dir)')

# 5. the stage-1 source set
gcc, genv = s1_compiler()
raw, pre, nown, nunits, ntok = s1_rules(ROOT, gcc, genv)
res('5a stage-1 files (%d, comments skipped): no reg_cmd / reg_status_* / BUD_RAMDP_REG* name, no 0.2.6 register-page '
    'literal' % nown, not raw, ' '.join(raw[:6]))
if gcc:
    res('5b the stage-1 set preprocessed as built (%d units, test + release; the clock name in %d): no reg_cmd / '
        'reg_status_* access, no register-page or clock literal' % (nunits, ntok), not pre and ntok > 0, ' | '.join(pre[:4]))
else:
    print('SKIP 5b the stage-1 set preprocessed (no RISC-V gcc: paths.local.json "riscv_bin")')

# 6. one allow-list: tests/equiv/allowlist.json is the list; docs/ALLOWLIST.md is its review page, row for row
al = json.load(open(os.path.join(ROOT, 'tests', 'equiv', 'allowlist.json'), encoding='utf-8'))
jids = [e['id'] for e in al['entries']]
pagef = os.path.join(ROOT, 'docs', 'ALLOWLIST.md')
page = open(pagef, encoding='utf-8').read() if os.path.exists(pagef) else None
mids = re.findall(r'^\| \*\*([AB]\d+)\*\* \|', page, flags=re.M) if page is not None else []
uniq = len(set(jids)) == len(jids)
bad = [] if uniq else ['json ids not unique']
if page is None:
    print('%s 6 one allow-list: no docs/ALLOWLIST.md in this copy, rows not compared (%d JSON entries, ids unique: %s)'
          % ('SKIP' if uniq else 'FAIL', len(jids), uniq))
    ok_all &= uniq
else:
    bad += ['%s: in allowlist.json, no row in ALLOWLIST.md' % i for i in jids if i not in mids]
    bad += ['%s: a row in ALLOWLIST.md, not in allowlist.json' % i for i in mids if i not in jids]
    bad += ['%s: %d rows in ALLOWLIST.md' % (i, mids.count(i)) for i in sorted(set(mids)) if mids.count(i) > 1]
    res('6 one allow-list: docs/ALLOWLIST.md has one row per tests/equiv/allowlist.json entry (%d)' % len(jids), not bad,
        ' '.join(bad[:6]))
print('ALL PASS' if ok_all else 'SOME FAIL')
sys.exit(0 if ok_all else 1)
