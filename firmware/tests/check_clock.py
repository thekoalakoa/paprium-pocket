#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_clock.py - test T23 (docs/STAGE1_PLAN.md): one build-time clock, and every clock-following figure follows it
(stage 1: the FW_S1 builds of our new firmware; stage 5 adds our own song engine, FW_S5).

    python -I -B tests/check_clock.py [--root TREE]
    python -I -B tests/check_clock.py --selftest       (negative controls: each planted mistake must fail)

docs/MCU_INTERFACE.md section 7: the firmware gets the clock value from the build only (fwbuild.json clk_hz ->
-DBRD_CLK_HZ); what the chip times by its own clock, ours times
in time units; what it times by the frame, ours counts in frames.
1. No clock literal in the stage-1 sources (code, comments skipped): the stage-1 set of fwbuild.json, core/, the
   board interface files, the stage-1 Pocket and host board files, and the FW_S1 branches of buddy/buddy.h. Literals:
   both clock values and what they make (1 ms, the 84 delay, the TIM7 period, the feeder grid, the urgent deadline,
   the album divider, the frame length in master clocks).
2. tests/s1/clock_probe.c built for the host at 53,693,175 Hz (NTSC) and 53,203,424 Hz (PAL, the RTL's other CLK_HZ):
   - every CLK_* figure of board/clock.h is printed (none forgotten);
   - every time figure equals its time in cycles at that clock within +-1 cycle (CLK_MS_CYCLES: the truncated
     CLK_HZ / 1000 of the 0.2.6 ms counter);
   - the stage-1 buddy figures (BUDDY_MS_CYCLES, BUDDY_FEED_PERIOD) equal CLK_MS_CYCLES / CLK_FEED at both clocks, and
     at NTSC equal the 0.2.6 literals (buddy.h's non-FW_S1 branch): stage 1 changes no NTSC number;
   - the CPU-work figures (cycles by design) are the same at both clocks;
   - where docs/MCU_INTERFACE.md is present, its section 7 cycle table (1 ms, the 84 delay, TIM7) matches.
3. (with the stage-1 Pocket image) the two images differ only in figure values, and the image stops with the
   68000 held when NEORV32 SYSINFO_CLK differs from its build clock: see --images below once the s1 image exists.
Exit 1 on any FAIL."""
import argparse, json, os, re, shutil, struct, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
NTSC, PAL = 53693175, 53203424


def figures_from_doc(doc):
    """docs/MCU_INTERFACE.md section 7 rows: {name: (ntsc cycles, pal cycles)} for the rows this check compares"""
    out = {}
    for key, rx in (('CLK_MS_CYCLES', r'\| 1 ms \(board ms[^|]*\| clock \| 1,000 \| ([\d,.]+) \| ([\d,.]+) \|'),
                    ('CLK_84_DELAY', r"\| 84's `delay\(9,600 SysTick\)` \| clock \| 100 \| ([\d,]+) \| ([\d,]+) \|"),
                    ('CLK_TIM7', r'\| TIM7 period.*?\| ([\d,]+) \| ([\d,]+) \|')):
        m = re.search(rx, doc)
        if m:
            out[key] = tuple(int(float(g.replace(',', ''))) for g in m.groups())
    return out


def lit(s):
    """a C literal's value; a decimal run with a leading zero (a string's '2,048' splits into '048') reads as decimal"""
    s = s.replace('_', '')
    return int(s, 16) if s[:2] in ('0x', '0X') else int(s, 10)


def strip_comments(t):
    t = re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), t, flags=re.S)
    return '\n'.join(ln.split('//')[0] for ln in t.split('\n'))


def run(root, verbose=True):
    sys.path.insert(0, os.path.join(root, 'tools'))
    ok_all = True

    def res(name, ok, info=''):
        nonlocal ok_all
        ok_all &= bool(ok)
        if verbose:
            print('%-4s %s %s' % ('PASS' if ok else 'FAIL', name, info))
        return ok
    cfg = json.load(open(os.path.join(root, 'fwbuild.json')))
    s1 = cfg['s1']

    # ---- 1. no clock literal in the stage-1 sources
    lits = {NTSC: 'NTSC clock', PAL: 'PAL clock', NTSC // 1000: '1 ms NTSC', PAL // 1000: '1 ms PAL', 5369: '84 delay NTSC',
            5320: '84 delay PAL', 5482275: 'TIM7 NTSC', 5432269: 'TIM7 PAL', 7168: 'feeder grid NTSC', 7103: 'feeder grid PAL',
            39599: 'urgent NTSC', 39600: 'urgent NTSC (doc)', 896040: 'frame in MCLK', 537: 'fatal poll NTSC',
            532: 'fatal poll PAL'}
    rx = re.compile(r'(?<![\w.])(0[xX][0-9a-fA-F]+|\d[\d_]*)[uUlL]*(?![\w.])')
    files = set()
    for part in (s1.get('pocket', {}), ):
        for key in ('sources', 'compile_only', 'probe_sources'):
            files |= set(part.get(key, []))
        # the test / release variant sources too (the probe images are test
        # rigs), but not the moved 0.2.6 files (no_extra: 0.2.6 code under
        # FW_S1 guards, whose FW_S1 paths tests/check_tree.py rule 5b checks preprocessed) or the shared buddy wrapper
        for v in ('test', 'release'):
            files |= {f for f in part.get('variant_sources', {}).get(v, [])
                      if f not in part.get('no_extra', []) and not os.path.basename(f).startswith('zz_buddy')}
    for srcs in s1.get('host', {}).get('tests', {}).values():
        files |= set(srcs)
    for dp, dn, fn in os.walk(os.path.join(root, 'core')):
        if os.path.basename(dp) == 'tables':
            continue            # generated chip tables (note pitches, FM fnum): data, guarded by the leak allow-list
        files |= {os.path.relpath(os.path.join(dp, f), root).replace(os.sep, '/') for f in fn if f.endswith(('.c', '.h', '.S'))}
    for d, pat in (('board', r'.*\.h$'), ('board/pocket', r'(s1_.*|board_impl\.h|dbgsave\.h)$'), ('board/host', r'(s1_.*|board_impl\.h)$'),
                   ('interim/s1', r'.*\.h$'), ('buddy', r's1_.*\.h$')):
        dd = os.path.join(root, *d.split('/'))
        if os.path.isdir(dd):
            files |= {d + '/' + f for f in os.listdir(dd) if re.match(pat, f) and os.path.isfile(os.path.join(dd, f))}
    # the generated chip tables are data wherever they are listed (stage 5: the s5_tests host test links them), as the
    # core/ walk above skips them: the leak allow-list guards them
    files = {f for f in files if not f.startswith('core/tables/')}
    hits = []
    for f in sorted(files):
        p = os.path.join(root, *f.split('/'))
        if not os.path.exists(p):
            continue
        t = strip_comments(open(p, encoding='utf-8', errors='replace').read())
        for i, ln in enumerate(t.split('\n'), 1):
            for m in rx.finditer(ln):
                v = lit(m.group(1))
                if v in lits:
                    hits.append('%s:%d %s (%s)' % (f, i, m.group(1), lits[v]))
    bud = open(os.path.join(root, 'buddy', 'buddy.h'), encoding='utf-8').read()
    branches = re.findall(r'#if FW_S1\n(.*?)\n#else', bud, re.S)
    for b in branches:
        for m in rx.finditer(strip_comments(b)):
            v = lit(m.group(1))
            if v in lits:
                hits.append('buddy/buddy.h FW_S1 branch %s (%s)' % (m.group(1), lits[v]))
    res('1 no clock literal in the stage-1 sources (%d files + %d FW_S1 branches of buddy.h)' % (len(files), len(branches)),
        not hits and len(branches) >= 2, ' '.join(hits[:6]))

    # ---- 2. the probe at both clocks
    import fwbuild   # noqa: E402  (the tree's own build tool: the host compiler from paths.local.json / env)
    P = fwbuild.local_paths()
    cc = fwbuild.tool(P['host_bin'], cfg['host']['cc'])
    env = fwbuild.env_with(os.path.dirname(cc))
    tmp = tempfile.mkdtemp(prefix='clk_')
    vals = {}
    for hz in (NTSC, PAL):
        exe = os.path.join(tmp, 'probe_%d.exe' % hz)
        cmd = [cc, '-O1', '-Wall', '-Wextra', '-DFW_S1=1', '-DBRD_CLK_HZ=%du' % hz]
        for d in s1['host']['include'] + ['buddy']:
            cmd += ['-I', os.path.join(root, *d.split('/'))]
        r = subprocess.run(cmd + [os.path.join(root, 'tests', 's1', 'clock_probe.c'), '-o', exe], capture_output=True, text=True, env=env)
        if not res('2 probe builds at %d Hz without warnings' % hz, r.returncode == 0 and 'warning' not in r.stderr, r.stderr[-300:]):
            shutil.rmtree(tmp, ignore_errors=True)
            return False
        out = subprocess.run([exe], capture_output=True, text=True, env=env).stdout.split('\n')
        vals[hz] = {ln.split()[0]: (int(ln.split()[1]), int(ln.split()[2])) for ln in out if ln.strip()}
    shutil.rmtree(tmp, ignore_errors=True)
    clk_h = strip_comments(open(os.path.join(root, 'board', 'clock.h'), encoding='utf-8').read())
    figs = sorted(set(re.findall(r'#define\s+(CLK_\w+)', clk_h)) - {n for n in re.findall(r'#define\s+(CLK_\w+_NS)\b', clk_h)})
    missing = [f for f in figs if f not in vals[NTSC]]
    res('2 every figure of board/clock.h is in the probe (%d: %s)' % (len(figs), ' '.join(figs)), not missing, ' '.join(missing))
    bad = []
    for hz in (NTSC, PAL):
        V = vals[hz]
        if V.get('BRD_CLK_HZ', (0, 0))[1] != hz:
            bad.append('BRD_CLK_HZ at %d' % hz)
        for n, (ns, cyc) in V.items():
            if n == 'BRD_CLK_HZ' or ns == 0:
                continue
            want = ns * hz / 1e9
            if abs(cyc - want) > 1.0:
                bad.append('%s at %d Hz: %d cycles, %.3f wanted' % (n, hz, cyc, want))
        for b, c in (('BUDDY_MS_CYCLES', 'CLK_MS_CYCLES'), ('BUDDY_FEED_PERIOD', 'CLK_FEED')):
            if V.get(b) != V.get(c):
                bad.append('%s != %s at %d Hz' % (b, c, hz))
    res('2 every time figure = its time at both clocks (+-1 cycle); buddy follows clock.h', not bad, '; '.join(bad[:4]))
    legacy = {m.group(1): int(m.group(2)) for m in re.finditer(r'#define\s+(BUDDY_MS_CYCLES|BUDDY_FEED_PERIOD)\s+(\d+)u', bud)}
    nt = vals[NTSC]
    same026 = len(legacy) == 2 and all(nt[k][1] == v for k, v in legacy.items())
    res('2 at NTSC the stage-1 values are 0.2.6\'s literals (%s)' % ', '.join('%s %d' % kv for kv in sorted(legacy.items())), same026,
        ' '.join('%s=%d' % (k, nt[k][1]) for k in legacy))
    cpu = [n for n, (ns, c) in vals[NTSC].items() if ns == 0 and n != 'BRD_CLK_HZ']
    res('2 CPU-work figures (cycles by design) equal at both clocks (%d)' % len(cpu), cpu and all(vals[NTSC][n] == vals[PAL][n] for n in cpu))
    docp = os.path.join(root, 'docs', 'MCU_INTERFACE.md')
    if os.path.exists(docp):
        D = figures_from_doc(open(docp, encoding='utf-8').read())
        dbad = ['%s doc %s probe %s' % (k, v, (vals[NTSC][k][1], vals[PAL][k][1])) for k, v in D.items()
                if (vals[NTSC][k][1], vals[PAL][k][1]) != v]
        res('2 MCU_INTERFACE 7 cycle table == the probe (%d rows: %s)' % (len(D), ', '.join(sorted(D))), len(D) == 3 and not dbad, '; '.join(dbad))
    elif verbose:
        print('SKIP 2 MCU_INTERFACE 7 table (no doc: the public copy drops it)')
    return ok_all


def selftest():
    root = os.path.dirname(HERE)
    plants = [('a clock literal in core/', 'core/planted_clock.c', None, 'unsigned planted_ms = 53693u;\n'),
              ('CLK_FEED typed in as cycles', 'board/clock.h', '#define CLK_FEED                BRD_CYC_NS(CLK_FEED_NS)',
               '#define CLK_FEED                7168u'),
              ('a figure left out of the probe', 'board/clock.h', '#define CLK_URGENT              BRD_CYC_NS(CLK_URGENT_NS)',
               '#define CLK_URGENT              BRD_CYC_NS(CLK_URGENT_NS)\n#define CLK_FORGOTTEN           BRD_CYC_NS(5000u)'),
              ('buddy\'s ms back on the literal in stage 1', 'buddy/buddy.h',
               '#define BUDDY_MS_CYCLES         CLK_MS_CYCLES', '#define BUDDY_MS_CYCLES         (53693u + 0u * CLK_MS_CYCLES)'),
              ('the feeder grid moved off 0.2.6\'s NTSC value', 'board/clock.h', '#define CLK_FEED_NS             133500u',
               '#define CLK_FEED_NS             134000u')]
    good = True
    for name, f, old, new in [(None, None, None, None)] + plants:
        tmp = tempfile.mkdtemp(prefix='clkself_')
        for d in ('board', 'buddy', 'core', 'tools', 'tests', 'docs'):
            shutil.copytree(os.path.join(root, d), os.path.join(tmp, d), ignore=shutil.ignore_patterns('__pycache__'))
        for fn in ('fwbuild.json', 'paths.local.json'):
            if os.path.exists(os.path.join(root, fn)):
                shutil.copyfile(os.path.join(root, fn), os.path.join(tmp, fn))
        if f:
            p = os.path.join(tmp, *f.split('/'))
            if old is None:
                open(p, 'w', newline='\n').write(new)
            else:
                t = open(p, encoding='utf-8').read()
                assert old in t, name
                open(p, 'w', newline='\n', encoding='utf-8').write(t.replace(old, new, 1))
        r = subprocess.run([sys.executable, '-I', '-B', os.path.join(tmp, 'tests', 'check_clock.py'), '--root', tmp],
                           capture_output=True, text=True)
        want = 0 if name is None else 1
        fails = [ln[5:70] for ln in r.stdout.splitlines() if ln.startswith('FAIL')]
        print('%-4s %-48s -> rc %d %s' % ('PASS' if r.returncode == want else 'FAIL', name or 'unmodified copy passes',
                                          r.returncode, (fails or [''])[0]))
        good &= r.returncode == want
        shutil.rmtree(tmp, ignore_errors=True)
    print('ALL PASS' if good else 'SOME FAIL')
    return good


FIG_NS = {'CLK_MS_CYCLES': None, 'CLK_84_DELAY': 100000, 'CLK_TIM7': 102103750, 'CLK_FEED': 133500, 'CLK_URGENT': 737500,
          'CLK_URGENT5': 1800000, 'CLK_FATAL_POLL': 10000, 'CLK_C6_HOLD_MAX': 2000000000, 'CLK_JOB8C': 106344,
          'CLK_JOB8C_KB': 115625, 'CLK_83_WRAP': 174762667, 'CLK_83_A': 18621000, 'CLK_83_A_END': 21620000,
          'CLK_83_B': 15489000, 'CLK_83_B_END': 17888000, 'CLK_MW_SPRITE_MAX': 33400000}


def fig_pairs():
    """{(NTSC value, PAL value): name} of every clock figure, as board/clock.h computes them"""
    def val(name, ns, hz):
        return hz // 1000 if ns is None else (ns * hz + 500000000) // 1000000000
    out = {(NTSC, PAL): 'BRD_CLK_HZ'}
    for n, ns in FIG_NS.items():
        out[(val(n, ns, NTSC), val(n, ns, PAL))] = n
    return out


def dis_ins(path):
    out = []
    for ln in open(path, encoding='utf-8', errors='replace'):
        m = re.match(r'^\s*([0-9a-f]+):\t([0-9a-f]+)\s*\t(\S+)(?:\t([^#]*))?', ln)
        if m:
            out.append((int(m.group(1), 16), m.group(2), m.group(3), [o.strip() for o in (m.group(4) or '').split(',') if o.strip()]))
    return out


def const_at(ins, i):
    """the 32-bit constant a lui / addi pair (or a lone li) builds around instruction i, with its register"""
    a, h, mn, ops = ins[i]
    if mn == 'lui':
        rd, hi = ops[0], int(ops[1], 0) << 12
        for j in range(i + 1, min(i + 8, len(ins))):
            if ins[j][2] == 'addi' and ins[j][3][:2] == [rd, rd]:
                return rd, (hi + int(ins[j][3][2], 0)) & 0xFFFFFFFF
        return rd, hi & 0xFFFFFFFF
    if mn == 'addi' and len(ops) == 3:
        rd = ops[0]
        for j in range(i - 1, max(i - 8, -1), -1):
            if ins[j][2] == 'lui' and ins[j][3][0] == rd:
                return const_at(ins, j)
        if ops[1] == 'zero':
            return rd, int(ops[2], 0) & 0xFFFFFFFF
    if mn == 'li':
        return ops[0], int(ops[1], 0) & 0xFFFFFFFF
    return None, None


def images(root, variants=('test', 'release', 'probe'), verbose=True):
    """the stage-1 images built at both clocks differ only where a clock figure is built; each image runs on its own
    clock and stops (68000 held) on the other one (crt0's SYSINFO_CLK check)"""
    sys.path.insert(0, os.path.join(root, 'tests', 'equiv'))
    import fuzz_sched   # noqa: E402
    ok = True

    def res(name, good, info=''):
        nonlocal ok
        ok &= bool(good)
        if verbose:
            print('%-4s %s %s' % ('PASS' if good else 'FAIL', name, info))
        return good
    tmp = tempfile.mkdtemp(prefix='clkimg_')
    builds = {}
    for hz in (NTSC, PAL):
        cmd = [sys.executable, '-I', '-B', os.path.join(root, 'tools', 'fwbuild.py'), 's1', '--clk-hz', str(hz),
               '--out', os.path.join(tmp, str(hz))]
        for v in variants:
            cmd += ['--variant', v]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if not res('3 stage-1 images (%s) build at %d Hz' % ('/'.join(variants), hz), r.returncode == 0, r.stderr[-300:]):
            shutil.rmtree(tmp, ignore_errors=True)
            return False
        builds[hz] = os.path.join(tmp, str(hz), 's1', 'pocket72k')
    pairs = fig_pairs()
    for v in variants:
        dn, dp = (dis_ins(os.path.join(builds[hz], v, 'main.dis')) for hz in (NTSC, PAL))
        seen, bad = {}, []
        if [(a, m) for a, h, m, o in dn] != [(a, m) for a, h, m, o in dp]:
            bad.append('the instruction streams differ in length or opcode')
        else:
            for i in range(len(dn)):
                if dn[i][1] == dp[i][1]:
                    continue
                (rn, vn), (rp_, vp) = const_at(dn, i), const_at(dp, i)
                name = pairs.get((vn, vp)) if rn == rp_ and rn is not None else None
                if name is None:
                    bad.append('%#x %s %s: %s / %s' % (dn[i][0], dn[i][2], ','.join(dn[i][3]), vn, vp))
                else:
                    seen[name] = seen.get(name, 0) + 1
        rn_, rp2 = (open(os.path.join(builds[hz], v, 'img', 'rom.bin'), 'rb').read() for hz in (NTSC, PAL))
        code = {a for a, h, m, o in dn}
        if len(rn_) != len(rp2):
            bad.append('rom.bin sizes differ')
        else:
            for k in range(0, len(rn_) - 3, 4):
                if rn_[k:k + 4] != rp2[k:k + 4] and k not in code:
                    wn, wp = struct.unpack('<I', rn_[k:k + 4])[0], struct.unpack('<I', rp2[k:k + 4])[0]
                    if (wn, wp) in pairs:
                        seen[pairs[(wn, wp)]] = seen.get(pairs[(wn, wp)], 0) + 1
                    else:
                        bad.append('data word at %#x: %#x / %#x' % (k, wn, wp))
        wc = [open(os.path.join(builds[hz], v, 'img', 'wcode.bin'), 'rb').read() for hz in (NTSC, PAL)]
        if wc[0] != wc[1]:
            bad.append('the WRAM code window differs')
        res('3 %-7s NTSC vs PAL image: every difference is a clock figure (%s)' % (
            v, ', '.join('%s x%d' % kv for kv in sorted(seen.items())) or 'none'), not bad and 'BRD_CLK_HZ' in seen, '; '.join(bad[:4]))
        # the probe boots to the scheduler on the rig's board; the test / release images' boot needs the full board
        # (ROM view, the interim album): they are run to crt0's hand-over (brd_boot), where the clock check is done
        until = 'l3_thread' if v == 'probe' else 'brd_boot'
        for hz in (NTSC, PAL):
            other = PAL if hz == NTSC else NTSC
            for clk, want in ((hz, 'scheduler' if v == 'probe' else 'board boot'),
                              (other, 'stopped code 0xc1 value %#x hold 1' % other)):
                # since test builds 4a / 4b (firmware builds B Jam tested on his hardware): the TEST and (since 4b)
                # RELEASE images are v1.3 images (board/pocket/s1_boot.h S1_CACHE4B: crt0 needs minor 3 and FEAT),
                # so they boot on test build 4a's board; the probe accepts v1.2
                rg = fuzz_sched.Rig(os.path.join(builds[hz], v), 0, 0, None, sysinfo_clk=clk,
                                    user_code=0x50490103 if v in ('test', 'release') else 0x50490102)
                try:
                    got = rg.boot(limit=100000, until=until)
                except fuzz_sched.Stop:
                    got = 'fault %s' % rg.violations
                res('3 %-7s built for %d Hz, SYSINFO_CLK %d -> %s' % (v, hz, clk, want.split(' value')[0]),
                    got == want and not rg.violations, got if got != want else '')
    shutil.rmtree(tmp, ignore_errors=True)
    return ok


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--root', default=os.path.dirname(HERE))
    ap.add_argument('--selftest', action='store_true')
    ap.add_argument('--images', action='store_true', help='also build the stage-1 images at both clocks and compare them')
    a = ap.parse_args()
    if a.selftest:
        sys.exit(0 if selftest() else 1)
    ok = run(os.path.abspath(a.root))
    if a.images:
        ok &= images(os.path.abspath(a.root))
    print('ALL PASS' if ok else 'SOME FAIL')
    sys.exit(0 if ok else 1)
