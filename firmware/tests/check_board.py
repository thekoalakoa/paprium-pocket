#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_board.py - the board interface against MCU interface v1.N (no build needed; v1.1 = v1.0 plus FPGAIO slot
16 VSCNT, 2026-10-13; v1.2 = v1.1 plus the RTL sprite decoder, FPGAIO slots 17-22, 2026-10-15, proposed; v1.3 = v1.2
plus the parts of stage 5 (our own song engine and synth): STAMP_A, FEAT, CAUSE.BLK / CTRL.BLKIE, XLINK 0x40-0x48, the
synth in region 0x06, the CRAM map, frozen 2026-10-21). The page may be ahead of the header: the header holds the
page's v1.(header) subset. FPGAIO = the core's register block for the MCU (a slot is one of its registers).

    python -I -B tests/check_board.py [--rtl DIR] [--doc docs/MCU_INTERFACE.md] [--root TREE]
    python -I -B tests/check_board.py --selftest          (17 planted mistakes, each must fail; a v1.3 header must pass;
                                                           since test build 4a (a firmware build B Jam tested on his
                                                           hardware): with the tree's v1.3 header, that header as a
                                                           v1.2 header must pass too, and the tag plant runs against it)

1. board/pocket/include/pocket_map.h: the block between its two "Appendix A" markers equals docs/MCU_INTERFACE.md
   Appendix A define for define (names, values and order; comments may differ), restricted to the lines whose comment
   tag ("/* v1.N") is at most the header's minor version; POCKET_IFACE_ID is the header's own version in the header and
   the page's (its title "# MCU interface v1.N") in the page, and the page is never older than the header.
1b. (a v1.3 page) every v1.3 table against the page's own Appendix A lines, so the block the stage-5 firmware will paste
   into pocket_map.h is checked before any header holds it: the CRAM map (3.8: base and size of every region, no
   overlap, the curve at its place in its window), XLINK 0x40-0x48 (3.9), the synth's global registers, their CONFIG /
   FLAGS / STATUS bits and its ID value (3.10.1), the VOICE and SFX field offsets and window bases (3.10.3-3.10.4), the
   FEAT bits (4.10). FPGAIO slots, CTRL and CAUSE rows newer than the header are checked against the page's lines (2).
2. pocket_map.h against the doc's tables: the memory map (section 3: base, size and byte views of every region), the
   FPGAIO slot table (section 4: slot -> address -> name, CTRL reset value), CTRL bits (4.1), CAUSE bits (4.2), the
   option word bits (5), the interrupt codes and mie bits (2), the interface id (1), the GO / SPTR widths (4.5), the
   WLOCK range (4.7) and the register-file offsets with the stored set (3.4).
3. board/board.h against pocket_map.h: every interface constant (BRD_CAUSE_*, BRD_LINE_*, BRD_FREG_*, BRD_OPT_*,
   the memory sizes, the GO width); board.h holds no board address literal and no POCKET_* name.
4. The clock: every layout's fwbuild.json clk_hz equals the doc's NTSC value (section 7), and the PAL value in the doc
   is the one tests/check_clock.py builds at.
5. The stage-1 sources (FW_S1, our new firmware: fwbuild.json "s1" + board/pocket/*s1* + core/) hold no access to
   removed IO (MTIME, UART, WDT: a bus-timeout fault on v1.0),
   no use of the retired ms counter, and no NTSC clock literal.
6. --rtl DIR (an RTL tree with rtl/PAPRIUM): the NEORV32 USER_CODE equals POCKET_IFACE_ID, CLOCK_FREQUENCY is not a
   literal, a CLK_HZ parameter carries the doc's two clock values, FPGAIO decodes addr[6:2], and (v1.1) slot 16 reads
   {16'0, the VS count}, the count clears on every reset, and the SDC false-paths only the VS synchroniser's first
   stage. Each found item must match; an RTL tree that predates v1.0 FAILS (the negative control: the 0.2.6 release
   tree), and a v1.0 tree fails the v1.1 items. Test build 4 (the MCU fast path: the IROM / WRAM on the NEORV32's
   processor bus, found by mcu_tcm_wram in mcu_core.sv; a tree without it prints SKIP for these): the tightly coupled
   windows are the whole regions 0x00 / 0x80 (docs/MCU_INTERFACE.md section 3: aliasing unchanged) with MEM_INT_*_USE
   false (SYSINFO unchanged), RAMDP answers with ramdp_io's registered ack (a constant ack reads the cell a clock early
   once the fetch is fast), and the WRAM reads the four lane images wram_b0..b3 that tools/mkimage.py writes.
   --selftest --rtl <an RTL tree from test build 4 on>: also 3 planted RTL mistakes of that build on a copy, each must
   fail. With a v1.2 header (the RTL sprite decoder, 2026-10-15): FPGAIO slots
   17-22 read from and are written to paprium_hwdec, whose read mux serves DEC_BASE, STAT, WORDS, TIME, MARGIN,
   LATECNT in the header's slot order; the decoder's reset clears the queue, the run and DEC_BASE and sets MARGIN to
   0x7FFFFFFF; the register file passes +12 / +14 / +16 (word 5) to it and its MCU reads of words 4-5 stay 0; START is
   $1FF2 = 0x8000 and CLEAR is $1FF6 bit 0. A v1.1 RTL tree fails these items (and USER_CODE); a v1.1 header skips them.
Without the doc steps 1, 2 and 4 print SKIP. Exit 1 on any FAIL."""
import argparse, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ok_all = True


def res(name, ok, info=''):
    global ok_all
    ok_all &= bool(ok)
    print('%-4s %s %s' % ('PASS' if ok else 'FAIL', name, info))
    return ok


def strip_c_comments(t):
    return re.sub(r'/\*.*?\*/', lambda m: '\n' * m.group(0).count('\n'), t, flags=re.S)


DEF = re.compile(r'^\s*#define\s+(\w+)(\([^)]*\))?\s*(.*?)\s*$')


def defines(text, tags=False):
    """[(name, params, value text)] in order, comments stripped, whitespace normalised; with tags=True each item also
    carries the minor version its line's comment names ("/* v1.N ..."), 0 for an untagged (v1.0) line"""
    out = []
    raw = text.split('\n')
    for i, ln in enumerate(strip_c_comments(text).split('\n')):     # strip_c_comments keeps the line count
        m = DEF.match(ln.split('//')[0])
        if m:
            item = (m.group(1), m.group(2) or '', re.sub(r'\s+', '', m.group(3)))
            if tags:
                t = re.search(r'/\*\s*v1\.(\d+)', raw[i])
                item += (int(t.group(1)) if t else 0,)
            out.append(item)
    return out


def evaluate(defs):
    """evaluate the integer defines of one header (macros of one argument included)"""
    env, fun = {}, {}
    for n, p, v in defs:
        if p:
            fun[n] = (p.strip('()').strip(), v)
    for _ in range(4):
        for n, p, v in defs:
            if p or n in env:
                continue
            x = v
            for f, (arg, body) in fun.items():
                x = re.sub(r'\b%s\(([^()]*)\)' % f, lambda m: '(' + re.sub(r'\b%s\b' % arg, '(' + m.group(1) + ')', body) + ')', x)
            x = re.sub(r'\b(0[xX][0-9a-fA-F]+|\d+)[uUlL]*\b', r'\1', x)
            x = re.sub(r'\b([A-Z_][A-Z0-9_]*)\b', lambda m: str(env[m.group(1)]) if m.group(1) in env else m.group(1), x)
            if re.fullmatch(r'[0-9a-fA-FxX()+\-*/<>|&~ ]+', x):
                try:
                    env[n] = eval(x.replace('/', '//'), {'__builtins__': {}}) & 0xFFFFFFFF
                except Exception:
                    pass
    return env


def hexnum(s):
    return int(s.replace('_', ''), 16)


ap = argparse.ArgumentParser()
ap.add_argument('--rtl', help='RTL tree (holding rtl/PAPRIUM) to compare with the header')
ap.add_argument('--doc', help='default <root>/docs/MCU_INTERFACE.md')
ap.add_argument('--root', default=ROOT, help='tree to check (default: this one)')
ap.add_argument('--selftest', action='store_true', help='negative controls: each planted mistake must fail')
a = ap.parse_args()
if a.selftest:
    import shutil, subprocess, tempfile
    tmp = tempfile.mkdtemp(prefix='chkboard_')
    for d in ('board', 'core', os.path.join('tests', 's1')):
        shutil.copytree(os.path.join(ROOT, d), os.path.join(tmp, d))
    os.makedirs(os.path.join(tmp, 'docs'))
    for f in (os.path.join('docs', 'MCU_INTERFACE.md'), 'fwbuild.json'):
        shutil.copyfile(os.path.join(ROOT, f), os.path.join(tmp, f))
    plants = [('pocket_map.h Appendix A: CAUSE in slot 6', 'board/pocket/include/pocket_map.h',
               '#define POCKET_FIO_CAUSE        POCKET_FIO(8)', '#define POCKET_FIO_CAUSE        POCKET_FIO(6)'),
              ('pocket_map.h: battery save 4 KB', 'board/pocket/include/pocket_map.h',
               '#define POCKET_BRAM_BYTES       0x2000u', '#define POCKET_BRAM_BYTES       0x1000u'),
              ('board.h: SEND on cause bit 3', 'board/board.h',
               '#define BRD_CAUSE_S             0x4u', '#define BRD_CAUSE_S             0x8u'),
              ('board.h: a board address literal', 'board/board.h',
               '#define BRD_IFACE_MINOR         2', '#define BRD_IFACE_MINOR         2\n#define BRD_X 0x01000020u'),
              ('core/: an MTIME access', 'core/README.md', None, None),
              ('doc: MSIP at the TIMER slot address', 'docs/MCU_INTERFACE.md',
               '| 9 | 0x0100_0024 | MSIP |', '| 9 | 0x0100_0028 | MSIP |'),
              ('fwbuild.json: clk_hz off by one', 'fwbuild.json', '"clk_hz": 53693175', '"clk_hz": 53693176'),
              ('doc: VSCNT in slot 17 (v1.1)', 'docs/MCU_INTERFACE.md',
               '| 16 | 0x0100_0040 | VSCNT (v1.1) |', '| 17 | 0x0100_0044 | VSCNT (v1.1) |'),
              ('pocket_map.h Appendix A: DEC_BASE in slot 18 (v1.2)', 'board/pocket/include/pocket_map.h',
               '#define POCKET_FIO_DEC_BASE     POCKET_FIO(17)', '#define POCKET_FIO_DEC_BASE     POCKET_FIO(18)'),
              # v1.3: the page's own tables against its Appendix A lines, and the tag rule
              ('doc: STAMP_A at the WLOCK address (v1.3)', 'docs/MCU_INTERFACE.md',
               '| 14 | 0x0100_0038 | STAMP_A (v1.3) |', '| 14 | 0x0100_003C | STAMP_A (v1.3) |'),
              ('doc Appendix A: CAUSE.BLK on bit 5 (v1.3)', 'docs/MCU_INTERFACE.md',
               '#define POCKET_CAUSE_BLK        (1u << 4)', '#define POCKET_CAUSE_BLK        (1u << 5)'),
              ('doc Appendix A: a v1.3 line without its tag', 'docs/MCU_INTERFACE.md',
               'POCKET_FIO(23)   /* v1.3: R what', 'POCKET_FIO(23)   /* R what'),
              ('doc: the synth DONE at 0x030 (v1.3)', 'docs/MCU_INTERFACE.md', '| 0x02C | DONE |', '| 0x030 | DONE |'),
              ('doc: CRAM BGMRING one byte late (v1.3)', 'docs/MCU_INTERFACE.md',
               '| 0x152100-0x15C0FF | BGMRING |', '| 0x152101-0x15C0FF | BGMRING |'),
              ('doc: XLINK CACHE_LOADED at 0x48 (v1.3)', 'docs/MCU_INTERFACE.md',
               '| 0x44 | 0x0A00_0044 | CACHE_LOADED (v1.3) |', '| 0x48 | 0x0A00_0048 | CACHE_LOADED (v1.3) |'),
              ('doc: SFX ID at +0x14 (v1.3)', 'docs/MCU_INTERFACE.md', '| +0x12 | ID |', '| +0x14 | ID |'),
              ('doc: FEAT SYNTH on bit 3 (v1.3)', 'docs/MCU_INTERFACE.md', '| 2 | SYNTH |', '| 3 | SYNTH |')]
    good = True
    r = subprocess.run([sys.executable, '-I', '-B', __file__, '--root', tmp], capture_output=True, text=True)
    print('%-4s unmodified copy passes' % ('PASS' if r.returncode == 0 else 'FAIL'))
    good &= r.returncode == 0
    # since test build 4a (2026-10-21): the tree's header is v1.3. The tag rule (a page line's "/* v1.N" decides which
    # header holds it) shows only with an older header, so the tag plant runs against the header as a v1.2 header would
    # be: the page's untagged, v1.1 and v1.2 Appendix A lines between the markers (POCKET_IFACE_ID 0x50490102) and slot
    # 14 under its v1.2 name, as the pocket_map.h of test build 4
    # held them; that header must pass as it is (the subset rule)
    pmp = os.path.join(tmp, 'board', 'pocket', 'include', 'pocket_map.h')
    pm_keep = open(pmp, encoding='utf-8').read()
    hdr_minor = int(re.search(r'POCKET_IFACE_ID\s+0x504901([0-9A-Fa-f]{2})u', pm_keep).group(1), 16)
    v12_hdr = None
    if hdr_minor >= 3:
        dtx = open(os.path.join(tmp, 'docs', 'MCU_INTERFACE.md'), encoding='utf-8').read()
        dblk = re.search(r'## Appendix A\..*?```c\n(.*?)```', dtx, re.S).group(1)
        lines = [ln for ln in dblk.split('\n') if not (DEF.match(ln.split('//')[0]) and
                                                     re.search(r'/\*\s*v1\.([3-9]|\d\d)', ln))]
        b12 = '\n'.join(lines).replace('0x50490103u', '0x50490102u')
        mk = re.search(r'(/\* ---- MCU_INTERFACE Appendix A \(v1\.)\d+(\), verbatim: begin[^\n]*\n)(.*?\n)([^\n]*Appendix A '
                       r'\(v1\.)\d+(\), verbatim: end[^\n]*\n)', pm_keep, re.S)
        v12_hdr = (pm_keep[:mk.start()] + mk.group(1) + '2' + mk.group(2) + b12 + mk.group(4) + '2' + mk.group(5) +
                   '#define POCKET_FIO_STAMP_A_RSV  POCKET_FIO(14)/* reserved for STAMP_A (a later v1.x, stage 5) */\n' +
                   pm_keep[mk.end():])
        open(pmp, 'w', newline='\n', encoding='utf-8').write(v12_hdr)
        r = subprocess.run([sys.executable, '-I', '-B', __file__, '--root', tmp], capture_output=True, text=True)
        fails = [ln[5:60] for ln in r.stdout.splitlines() if ln.startswith('FAIL')]
        print('%-4s the header as a v1.2 header (the page\'s v1.2 lines) passes -> rc %d %s' % (
            'PASS' if r.returncode == 0 else 'FAIL', r.returncode, (fails or [''])[0]))
        good &= r.returncode == 0
        open(pmp, 'w', newline='\n', encoding='utf-8').write(pm_keep)
    for name, f, old_s, new_s in plants:
        if v12_hdr and 'without its tag' in name:
            open(pmp, 'w', newline='\n', encoding='utf-8').write(v12_hdr)
        fp = os.path.join(tmp, *f.split('/'))
        keep = open(fp, encoding='utf-8').read()
        if old_s is None:
            fp = os.path.join(tmp, 'core', 'planted_mtime.c')
            open(fp, 'w').write('unsigned planted(void) { return *(volatile unsigned *)MTIME_LO; }\n')
        else:
            assert old_s in keep, name
            open(fp, 'w', newline='\n', encoding='utf-8').write(keep.replace(old_s, new_s, 1))
        r = subprocess.run([sys.executable, '-I', '-B', __file__, '--root', tmp], capture_output=True, text=True)
        fails = [ln[5:60] for ln in r.stdout.splitlines() if ln.startswith('FAIL')]
        print('%-4s planted: %-44s -> rc %d %s' % ('PASS' if r.returncode == 1 else 'FAIL', name, r.returncode, (fails or [''])[0]))
        good &= r.returncode == 1
        if old_s is None:
            os.remove(fp)
        else:
            open(fp, 'w', newline='\n', encoding='utf-8').write(keep)
        if v12_hdr and 'without its tag' in name:
            open(pmp, 'w', newline='\n', encoding='utf-8').write(pm_keep)
    # v1.3 positive control: a header that pastes the page's whole Appendix A between its markers (what the first v1.3
    # firmware will do) must pass, and the same header with one v1.3 line dropped must fail
    dtxt = open(os.path.join(tmp, 'docs', 'MCU_INTERFACE.md'), encoding='utf-8').read()
    dmin = re.search(r'^# MCU interface v1\.(\d+)', dtxt, re.M)
    if dmin and int(dmin.group(1)) >= 3:
        pmp = os.path.join(tmp, 'board', 'pocket', 'include', 'pocket_map.h')
        keep = open(pmp, encoding='utf-8').read()
        blk = re.search(r'## Appendix A\..*?```c\n(.*?)```', dtxt, re.S).group(1)
        mk = re.search(r'(/\* ---- MCU_INTERFACE Appendix A \(v1\.)\d+(\), verbatim: begin[^\n]*\n)(.*?\n)([^\n]*Appendix A \(v1\.)\d+(\), verbatim: end)', keep, re.S)
        v = dmin.group(1)
        new = keep[:mk.start()] + mk.group(1) + v + mk.group(2) + blk + mk.group(4) + v + mk.group(5) + keep[mk.end():]
        for name, txt, want in (('positive: a v1.%s header (the page\'s Appendix A pasted) passes' % v, new, 0),
                                ('planted: that header without POCKET_FIO_FEAT', re.sub(r'#define POCKET_FIO_FEAT[^\n]*\n', '', new), 1)):
            open(pmp, 'w', newline='\n', encoding='utf-8').write(txt)
            r = subprocess.run([sys.executable, '-I', '-B', __file__, '--root', tmp], capture_output=True, text=True)
            fails = [ln[5:60] for ln in r.stdout.splitlines() if ln.startswith('FAIL')]
            print('%-4s %-53s -> rc %d %s' % ('PASS' if r.returncode == want else 'FAIL', name, r.returncode, (fails or [''])[0]))
            good &= r.returncode == want
        open(pmp, 'w', newline='\n', encoding='utf-8').write(keep)
    # test build 4: with --rtl (an RTL tree from test build 4 on),
    # three planted RTL mistakes on a copy of the files step 6 reads
    if a.rtl:
        trtl = os.path.join(tmp, 'rtl_copy')
        for sub in (os.path.join('rtl', 'PAPRIUM'), os.path.join('target', 'pocket')):
            os.makedirs(os.path.join(trtl, sub))
            for fn in os.listdir(os.path.join(a.rtl, sub)):
                if fn.endswith(('.sv', '.v', '.vhd', '.sdc')):
                    shutil.copyfile(os.path.join(a.rtl, sub, fn), os.path.join(trtl, sub, fn))
        r = subprocess.run([sys.executable, '-I', '-B', __file__, '--root', tmp, '--rtl', trtl], capture_output=True, text=True)
        card4 = 'SKIP 6 RTL card-4' not in r.stdout
        print('%-4s unmodified copy passes with --rtl (%s)' % ('PASS' if r.returncode == 0 else 'FAIL', 'a card-4 tree' if card4 else 'no card-4 items'))
        good &= r.returncode == 0
        rplants = [('card 4: RAMDP acked by the constant 1', 'rtl/PAPRIUM/paprium_cart.sv',
                    'mcu.map.ramdp                   ? mcu_ack_ramdp :', ''),
                   ('card 4: a 64 KB WRAM window (aliases lost)', 'rtl/PAPRIUM/paprium_neorv32.vhd',
                    'MEM_TCM_DMEM_SIZE            => 16*1024*1024', 'MEM_TCM_DMEM_SIZE            => 64*1024'),
                   ('card 4: the WRAM reads the 16-bit pair', 'rtl/PAPRIUM/memory.sv',
                    '$readmemh("wram_b0.txt", ram_b0);', '$readmemh("wram_hi.txt", ram_b0);')] if card4 else []
        for name, f, old_s, new_s in rplants:
            fp = os.path.join(trtl, *f.split('/'))
            keep = open(fp, 'rb').read().decode('latin1')
            assert old_s in keep, name
            open(fp, 'wb').write(keep.replace(old_s, new_s, 1).encode('latin1'))
            r = subprocess.run([sys.executable, '-I', '-B', __file__, '--root', tmp, '--rtl', trtl], capture_output=True, text=True)
            fails = [ln[5:60] for ln in r.stdout.splitlines() if ln.startswith('FAIL')]
            print('%-4s planted: %-44s -> rc %d %s' % ('PASS' if r.returncode == 1 else 'FAIL', name, r.returncode, (fails or [''])[0]))
            good &= r.returncode == 1
            open(fp, 'wb').write(keep.encode('latin1'))
    shutil.rmtree(tmp, ignore_errors=True)
    print('ALL PASS' if good else 'SOME FAIL')
    sys.exit(0 if good else 1)
ROOT = os.path.abspath(a.root)
a.doc = a.doc or os.path.join(ROOT, 'docs', 'MCU_INTERFACE.md')

pm_path = os.path.join(ROOT, 'board', 'pocket', 'include', 'pocket_map.h')
bh_path = os.path.join(ROOT, 'board', 'board.h')
pm_txt = open(pm_path, encoding='utf-8').read()
bh_txt = open(bh_path, encoding='utf-8').read()
PM = evaluate(defines(pm_txt))
BH = evaluate(defines(bh_txt))
doc = open(a.doc, encoding='utf-8').read() if os.path.exists(a.doc) else None
cfg = json.load(open(os.path.join(ROOT, 'fwbuild.json')))

# ---- 1. Appendix A verbatim (the header's version subset of the page's block)
HDR_MINOR = PM.get('POCKET_IFACE_ID', 0) & 0xFF
DOC_MINOR = None
DA = {}         # the page's own Appendix A lines, evaluated (all versions)
DT = []         # the page's Appendix A lines with their version tags
if doc is None:
    print('SKIP 1-2, 4 the doc comparisons (no %s: the public copy drops it)' % os.path.relpath(a.doc, ROOT))
else:
    tm = re.search(r'^# MCU interface v1\.(\d+)', doc, re.M)
    DOC_MINOR = int(tm.group(1)) if tm else -1
    m = re.search(r'## Appendix A\..*?```c\n(.*?)```', doc, re.S)
    blk = re.search(r'Appendix A \(v1\.\d+\), verbatim: begin[^\n]*\n(.*?)\n[^\n]*Appendix A \(v1\.\d+\), verbatim: end', pm_txt, re.S)
    if res('1 Appendix A found in the doc and between the markers in pocket_map.h', m and blk):
        DT, ha = defines(m.group(1), tags=True), defines(blk.group(1))
        DA = evaluate([x[:3] for x in DT])
        da = [x[:3] for x in DT if x[3] <= HDR_MINOR and x[0] != 'POCKET_IFACE_ID']
        hb = [x for x in ha if x[0] != 'POCKET_IFACE_ID']
        diff = [str(x) + ' / ' + str(y) for x, y in zip(da, hb) if x != y]
        res('1 pocket_map.h Appendix A == MCU_INTERFACE Appendix A, its v1.%d lines (%d of %d defines, in order)'
            % (HDR_MINOR, len(da), len(DT)),
            da == hb, ' '.join(diff[:4]) + ('' if len(da) == len(hb) else ' count %d vs %d' % (len(da), len(hb))))
        newest = max([x[3] for x in DT] + [0])
        res('1 versions: page v1.%d (Appendix A id %#010x), header v1.%d (%#010x); page >= header, no line newer than the page'
            % (DOC_MINOR, DA.get('POCKET_IFACE_ID', 0), HDR_MINOR, PM.get('POCKET_IFACE_ID', 0)),
            DOC_MINOR >= HDR_MINOR >= 2 and DA.get('POCKET_IFACE_ID') == 0x50490100 | DOC_MINOR
            and PM.get('POCKET_IFACE_ID') == 0x50490100 | HDR_MINOR and newest <= DOC_MINOR,
            'newest tag v1.%d' % newest)

    def src_for(name):
        """rows newer than the header are checked against the page's own Appendix A lines, the rest against the header"""
        mv = re.search(r'\(v1\.(\d+)\)', name)
        return (DA, 'page') if mv and int(mv.group(1)) > HDR_MINOR else (PM, 'header')

    # ---- 2. tables
    sec = lambda title: re.search(r'\n#+ %s.*?(?=\n#|\Z)' % re.escape(title), doc, re.S).group(0)   # to the next heading
    rows = lambda t: [[c.strip() for c in ln.strip().strip('|').split('|')] for ln in t.split('\n') if ln.startswith('| ')]
    # 2a. memory map (section 3)
    mm = {}
    for r in rows(sec('3. Memory map')):
        mt = re.match(r'(0x[0-9A-Fa-f_]+)-(0x[0-9A-Fa-f_]+)', r[1]) if len(r) > 2 else None
        if mt and re.match(r'0x[0-9A-F]{2}$', r[0]):
            mm.setdefault(r[0], []).append((hexnum(mt.group(1)[2:]), hexnum(mt.group(2)[2:]) + 1, r[2]))
    want = [('0x00', 0, 'POCKET_IROM_BASE', 'POCKET_IROM_BYTES'), ('0x01', 0, 'POCKET_FPGAIO_BASE', None),
            ('0x02', 0, 'POCKET_RAMDP_BASE', 'POCKET_RAMDP_BYTES'), ('0x02', 1, 'POCKET_RAMDP_BV_BASE', 'POCKET_RAMDP_BYTES'),
            ('0x03', 0, 'POCKET_SDRAM_BASE', 'POCKET_SDRAM_BYTES'), ('0x04', 0, 'POCKET_FLASH_BASE', 'POCKET_FLASH_BYTES'),
            ('0x04', 1, 'POCKET_FLASH_BV_BASE', 'POCKET_FLASH_BYTES'), ('0x05', 0, 'POCKET_BRAM_BASE', 'POCKET_BRAM_BYTES'),
            ('0x08', 0, 'POCKET_SRAM_BASE', 'POCKET_SRAM_BYTES'), ('0x09', 0, 'POCKET_CRAM_BASE', None),
            ('0x0A', 0, 'POCKET_XLINK_BASE', None), ('0x0B', 0, 'POCKET_FREG_BASE', 'POCKET_FREG_SPAN'),
            ('0x80', 0, 'POCKET_WRAM_BASE', 'POCKET_WRAM_BYTES'), ('0xFF', 0, 'POCKET_NEORV32_IO_BASE', None)]
    bad = []
    for reg, k, base, size in want:
        lst = mm.get(reg, [])
        if len(lst) <= k:
            bad.append('%s row %d missing' % (reg, k))
            continue
        lo, hi, _ = lst[k]
        if PM.get(base) != lo:
            bad.append('%s=%#x doc %#x' % (base, PM.get(base, -1), lo))
        if size and PM.get(size) != hi - lo:
            bad.append('%s=%#x doc %#x' % (size, PM.get(size, -1), hi - lo))
    if PM.get('POCKET_FPGAIO_BASE') and mm.get('0x01') and mm['0x01'][0][1] - mm['0x01'][0][0] != 4 * PM.get('POCKET_FIO_SLOTS', 0):
        bad.append('FPGAIO span vs POCKET_FIO_SLOTS')
    m6 = re.search(r'\| 0x06 \| (0x[0-9A-F_]+)-', doc)
    m7 = re.search(r'\| 0x07 \| (0x[0-9A-F_]+) / (0x[0-9A-F_]+)', doc)
    for mt, names in ((m6, ['POCKET_SFX_BASE']), (m7, ['POCKET_MDP_BASE', 'POCKET_EDFIFO_BASE'])):
        if not mt:
            bad.append('row %s missing' % names[0])
            continue
        for g, n in enumerate(names, 1):
            if PM.get(n) != hexnum(mt.group(g)[2:]):
                bad.append(n)
    res('2 memory map (section 3): %d regions, bases and sizes' % len(want), not bad, ' '.join(bad))
    # 2b. FPGAIO slots (section 4)
    names = {'CTRL': 'POCKET_FIO_CTRL', '(TIME_MS, retired)': 'POCKET_FIO_TIME_RETIRED', 'SPTR': 'POCKET_FIO_SPTR',
             'VOL_SFX': 'POCKET_FIO_VOL_SFX', 'VOL_BGM': 'POCKET_FIO_VOL_BGM', 'DIAG': 'POCKET_FIO_DIAG',
             'IRQCLR (legacy)': 'POCKET_FIO_IRQCLR', 'STREAM_GO': 'POCKET_FIO_GO', 'CAUSE': 'POCKET_FIO_CAUSE',
             'MSIP': 'POCKET_FIO_MSIP', 'TIMER': 'POCKET_FIO_TIMER', 'TCMP': 'POCKET_FIO_TCMP', 'TCTRL': 'POCKET_FIO_TCTRL',
             'STAMP_B': 'POCKET_FIO_STAMP_B', '(STAMP_A, reserved for a later v1.x)': 'POCKET_FIO_STAMP_A_RSV',
             'WLOCK': 'POCKET_FIO_WLOCK', 'VSCNT (v1.1)': 'POCKET_FIO_VSCNT', 'DEC_BASE (v1.2)': 'POCKET_FIO_DEC_BASE',
             'DEC_STAT (v1.2)': 'POCKET_FIO_DEC_STAT', 'DEC_WORDS (v1.2)': 'POCKET_FIO_DEC_WORDS',
             'DEC_TIME (v1.2)': 'POCKET_FIO_DEC_TIME', 'DEC_MARGIN (v1.2)': 'POCKET_FIO_DEC_MARGIN',
             'DEC_LATECNT (v1.2)': 'POCKET_FIO_DEC_LATECNT',
             'STAMP_A (v1.3)': 'POCKET_FIO_STAMP_A', 'FEAT (v1.3)': 'POCKET_FIO_FEAT'}
    srows = [r for r in rows(sec('4. FPGAIO v1.')) if re.fullmatch(r'\d+', r[0])]
    bad = []
    for r in srows:
        slot, addr, nm = int(r[0]), hexnum(r[1][2:]), r[2]
        if addr != 0x01000000 + 4 * slot:
            bad.append('doc slot %d address %s' % (slot, r[1]))
        pn = names.get(nm)
        S, sn = src_for(nm)
        if pn is None:
            bad.append('doc slot %d name %r has no header name' % (slot, nm))
        elif S.get(pn) != addr:
            bad.append('%s=%#x doc %#x (%s)' % (pn, S.get(pn, -1), addr, sn))
        if pn == 'POCKET_FIO_STAMP_A' and HDR_MINOR < 3 and PM.get('POCKET_FIO_STAMP_A_RSV') != addr:
            bad.append('POCKET_FIO_STAMP_A_RSV (the v1.2 header\'s name for slot 14)')
    ctrl = [r for r in srows if r[2] == 'CTRL']
    if not ctrl or not ctrl[0][4].startswith('0x%02X' % PM.get('POCKET_CTRL_RESET', -1)):
        bad.append('CTRL reset value')
    nslot = 23 + (1 if DOC_MINOR >= 3 else 0)      # v1.3 adds slot 23 FEAT (slot 14 changes name only)
    res('2 FPGAIO slot table (section 4): %d slots, address and name' % len(srows), len(srows) == nslot and not bad, ' '.join(bad))
    s48 = sec('4.8 VSCNT')
    res('2 VSCNT (4.8, v1.1): slot 16, 16 bits, 0 on every reset',
        PM.get('POCKET_FIO_VSCNT') == 0x01000040 and PM.get('POCKET_VSCNT_MASK') == 0xFFFF and "`{16'0, count[15:0]}`" in s48
        and '0 at configuration and on every reset' in s48 and re.search(r'\| VSCNT \(v1\.1\) \| 0 \| 0 \|', doc) is not None)
    s49 = sec('4.9 The sprite decoder')
    dbad = []
    if PM.get('POCKET_DEC_BASE_MASK') != 0x1FFFFE or '| 17 | 0x0100_0044 | DEC_BASE (v1.2) | [20:0] | 0 |' not in doc:
        dbad.append('DEC_BASE width / reset')
    if PM.get('POCKET_DEC_MARGIN_RESET') != 0x7FFFFFFF or '| 21 | 0x0100_0054 | DEC_MARGIN (v1.2) | [31:0] | 0x7FFF_FFFF |' not in doc:
        dbad.append('DEC_MARGIN reset')
    if PM.get('POCKET_DEC_STAT_FLAGS') != 0x3F0000 or '[16] OVF, [17] BADTYPE, [18] D0, [19] PRE, [20] LATE, [21] ABORT' not in doc:
        dbad.append('DEC_STAT flags')
    for w in ('0x8000 = START', 'odd = CLEAR', 'even = PUSH', 'last-pushed first'):
        if w not in s49:
            dbad.append('4.9: %r' % w)
    if not re.search(r'\| decoder queue, run, HI, DEC_BASE, .*\| 0 \| 0 \(DEC_MARGIN 0x7FFF_FFFF\) \|', doc):
        dbad.append('reset row (section 8)')
    res('2 the sprite decoder (4.9, v1.2): slots 17-22, DEC_BASE even 21 bits, DEC_STAT flags, MARGIN reset, the queue '
        'rules, the reset row', not dbad, ' '.join(dbad))
    # 2c. CTRL bits (4.1) and CAUSE bits (4.2)
    bits = {'HOLD (`md_rst`)': 'POCKET_CTRL_HOLD', 'RSTSEEN': 'POCKET_CTRL_RSTSEEN', 'MENU_MUTE_EN': 'POCKET_CTRL_MENU_MUTE',
            'OPT_AT_RESET_EN': 'POCKET_CTRL_OPT_AT_RST', 'CAUSE.B': 'POCKET_CTRL_CAUSE_B_RD', 'BLKIE (v1.3)': 'POCKET_CTRL_BLKIE'}
    crows = [r for r in rows(sec('4.1 CTRL (slot 0)')) if re.fullmatch(r'\d+', r[0])]
    bad = ['%s bit %s (%s)' % (bits[r[1]], r[0], src_for(r[1])[1]) for r in crows
           if r[1] in bits and src_for(r[1])[0].get(bits[r[1]]) != 1 << int(r[0])]
    seen = {r[1] for r in crows}
    vers = lambda k: int(re.search(r'\(v1\.(\d+)\)', k).group(1)) if re.search(r'\(v1\.(\d+)\)', k) else 0
    bad += ['doc has no CTRL row %s' % k for k in bits if k not in seen and vers(k) <= DOC_MINOR]
    rst = sum(1 << int(r[0]) for r in crows if r[4].strip('*').startswith('1'))
    if rst != PM.get('POCKET_CTRL_RESET'):
        bad.append('CTRL "every reset" column = %#x vs POCKET_CTRL_RESET' % rst)
    cb = {'B': 'POCKET_CAUSE_B', 'A': 'POCKET_CAUSE_A', 'S': 'POCKET_CAUSE_S', 'V': 'POCKET_CAUSE_V', 'BLK': 'POCKET_CAUSE_BLK'}
    krows = [r for r in rows(sec('4.2 CAUSE (slot 8)')) if re.fullmatch(r'\d+', r[0])]
    for r in krows:
        k = r[1].split(':')[0].strip()
        S, sn = src_for(r[1])
        if k not in cb:
            bad.append('doc CAUSE bit %s name %r has no header name' % (r[0], k))
        elif S.get(cb[k]) != 1 << int(r[0]):
            bad.append('%s (%s)' % (cb[k], sn))
    ncause = 4 + (1 if DOC_MINOR >= 3 else 0)       # v1.3 adds bit 4 BLK
    res('2 CTRL bits (4.1, reset value 0x%02X) and CAUSE bits (4.2)' % rst, not bad and len(krows) == ncause, ' '.join(bad))
    # 2d. option word (5)
    s5 = sec('5. The option word')
    obad = []
    if not re.search(r'\| 6 \| `\$1FE4` bit 6', s5) or not re.search(r'\| 10:8 \| `\$1FE4` bits 8-10', s5) \
            or PM.get('POCKET_OPT_MODEL_MASK') != (1 << 6 | 7 << 8):
        obad.append('model bits')
    if not re.search(r'\| 18:16 \| MegaWire', s5) or PM.get('POCKET_OPT_MW_MASK') != 7 << 16 or PM.get('POCKET_OPT_MW_SHIFT') != 16:
        obad.append('MegaWire bits')
    for bit, nm in ((24, 'MENU'), (25, 'JAP'), (26, 'PAL')):
        if not re.search(r'\| \*\*%d\*\* \| 0 \| \*\*%s' % (bit, nm), s5) or PM.get('POCKET_OPT_' + nm) != 1 << bit:
            obad.append(nm)
    res('2 option word bits (section 5): model 6/8-10, MegaWire 16-18, MENU 24, JAP 25, PAL 26', not obad, ' '.join(obad))
    # 2e. interrupt codes (2), interface id (1), widths (4.5, 4.7), register file (3.4)
    ibad = []
    for nm, code in (('MEI', 11), ('MTI', 7), ('MSI', 3)):
        if not re.search(r'%s\s+0x%08X' % (nm, 0x80000000 | code), doc) or PM.get('POCKET_IRQ_' + nm) != code \
                or PM.get('POCKET_MIE_%sE' % nm) != 1 << code:
            ibad.append(nm)
    if not re.search(r'MEIE 11, MTIE 7, MSIE 3', doc):
        ibad.append('mie bit list')
    if '**0x5049_01%02X**' % HDR_MINOR not in doc or '**0x5049_01%02X**' % DOC_MINOR not in doc \
            or PM.get('POCKET_IFACE_ID') != 0x50490100 | HDR_MINOR or HDR_MINOR < 2:
        ibad.append('interface id (section 1 names the header\'s and the page\'s id in bold; the header is v1.2 or later)')
    if PM.get('POCKET_SYSINFO_CLK') != 0xFFFFFFE0 or 'SYSINFO_CLK (0xFFFF_FFE0)' not in doc:
        ibad.append('SYSINFO_CLK')
    if '**21 bits**' not in sec('4.5 Stream pointer') or PM.get('POCKET_GO_WORDS_MASK') != (1 << 21) - 1 \
            or PM.get('POCKET_SPTR_MASK') != (1 << 21) - 1:
        ibad.append('GO / SPTR width')
    if 'Bits 0-20 lock WRAM KB 27-47' not in doc or (PM.get('POCKET_WLOCK_KB_FIRST'), PM.get('POCKET_WLOCK_KB_LAST')) != (27, 47):
        ibad.append('WLOCK range')
    frows = [r for r in rows(sec('3.4 Cart register file')) if re.match(r'\+[0-9A-F]+', r[0])]
    fmap = {'$1FE4': 'FE4', '$1FE6': 'FE6', '$1FE8': 'FE8', '$1FEA': 'FEA', '$1FEC': 'FEC', '$1FEE': 'FEE',
            '$1FF0': 'FF0', '$1FF2': 'FF2', '$1FF4': 'FF4', '$1FF6': 'FF6'}
    nreg = 0
    for r in frows:
        mreg = re.match(r'`(\$1F[0-9A-F]{2})`', r[2])
        if mreg and mreg.group(1) in fmap:
            nreg += 1
            off = int(r[0].split(',')[0].strip('+'), 16)
            if PM.get('POCKET_FREG_' + fmap[mreg.group(1)]) != off:
                ibad.append('POCKET_FREG_' + fmap[mreg.group(1)])
    stored = re.search(r'stored: (0x[0-9A-F]{2}(?:, 0x[0-9A-F]{2})*)', doc)
    if nreg != 10 or not stored or stored.group(1) != '0x04, 0x06, 0x0A, 0x0C':
        ibad.append('register-file rows (%d) / stored set' % nreg)
    res('2 interrupt codes (2), interface id (1), GO/SPTR 21 bits (4.5), WLOCK KB 27-47 (4.7), register file (3.4)', not ibad, ' '.join(ibad))

    # 2f. (a v1.3 page) the v1.3 tables against the page's own Appendix A lines (1b in the header comment)
    if DOC_MINOR >= 3:
        vbad, cnt = [], {}

        def chk(name, want):
            if DA.get(name) != want:
                vbad.append('%s=%s doc %#x' % (name, '%#x' % DA[name] if name in DA else 'missing', want))

        # the CRAM map (3.8): base and size of every region, in order, no overlap, inside the 4 MB window
        s38, regs = sec('3.8 CRAM'), []
        for r in rows(s38):
            mt = re.fullmatch(r'0x([0-9A-F]{6})-0x([0-9A-F]{6})', r[0])
            if mt and len(r) > 1 and r[1] != '-':
                lo, hi = int(mt.group(1), 16), int(mt.group(2), 16)
                chk('POCKET_CRAM_' + r[1], 0x09000000 + lo)
                chk('POCKET_CRAM_%s_BYTES' % r[1], hi - lo + 1)
                regs.append((lo, hi, r[1]))
        if any(b[0] <= a[1] for a, b in zip(regs, regs[1:])) or not regs or regs[-1][1] > 0x3FFFFD:
            vbad.append('CRAM regions overlap or leave the window')
        mc = re.search(r'\*\*0x([0-9A-F]{6})-0x([0-9A-F]{6}), centre \(index 0\) 0x([0-9A-F]{6})\*\*', s38)
        if not mc:
            vbad.append('3.8: the curve row')
        else:
            clo, chi, cc = (int(g, 16) for g in mc.groups())
            chk('POCKET_CRAM_CURVE', 0x09000000 + clo)
            chk('POCKET_CRAM_CURVE_CTR', 0x09000000 + cc)
            if chi - clo + 1 != 2 * 16384 or cc - clo != 2 * 8192 or DA.get('POCKET_CRAM_CURVE_CTR', 0) - DA.get('POCKET_CRAM_CURVE_WIN', 0) != 0x18000:
                vbad.append('the curve: 16,384 entries, index 0 at entry 8,192, 0x18000 into its window (finding 20)')
        cnt['CRAM'] = len(regs)
        # XLINK 0x40-0x48 (3.9)
        n = 0
        for r in rows(sec('3.9 XLINK')):
            if re.fullmatch(r'0x[0-9A-F]{2}', r[0]) and len(r) > 2 and '(v1.3)' in r[2]:
                chk('POCKET_XL_' + r[2].replace('(v1.3)', '').strip(), 0x0A000000 + int(r[0], 16))
                n += 1
        cnt['XLINK'] = n
        # the synth's global registers, their bits and the ID value (3.10.1)
        n = 0
        for r in rows(sec('3.10.1 Global registers')):
            if re.fullmatch(r'0x[0-9A-F]{3}', r[0]) and len(r) > 2:
                chk('POCKET_SYN_' + r[1], 0x06000000 + int(r[0], 16))
                n += 1
                for pre, reg in (('POCKET_SYN_FL_', 'FLAGS'), ('POCKET_SYN_ST_', 'STATUS'), ('POCKET_SYN_CFG_', 'CONFIG')):
                    if r[1] == reg:
                        for b, nm in re.findall(r'\[(\d+)\] ([A-Z]+)', r[2]):
                            if pre + nm in DA or reg == 'FLAGS':
                                chk(pre + nm, 1 << int(b))
                if r[1] == 'ID':
                    mv = re.search(r'0x([0-9A-F]{4})_([0-9A-F]{4})', r[4])
                    if mv:
                        chk('POCKET_SYN_ID_VALUE', int(mv.group(1) + mv.group(2), 16))
                    else:
                        vbad.append('3.10.1: the ID value')
                if r[1] == 'CONFIG':
                    if not re.search(r'1 = DT, 2 = YM', r[2]) or DA.get('POCKET_SYN_MODE_DT') != 1 or DA.get('POCKET_SYN_MODE_YM') != 2:
                        vbad.append('CONFIG MODE values')
                    if '[31:16] SEQ' not in r[2] or DA.get('POCKET_SYN_CFG_SEQ_SHIFT') != 16:
                        vbad.append('CONFIG SEQ field')
        cnt['SYN'] = n
        # VOICE / SFX field offsets and window bases (3.10.3, 3.10.4)
        for title, pre, key in (('3.10.3 Voice windows', 'POCKET_SV_', 'VOICE'), ('3.10.4 SFX windows', 'POCKET_SS_', 'SFX')):
            s, n = sec(title), 0
            for r in rows(s):
                if re.fullmatch(r'\+0x[0-9A-F]{2}', r[0]) and len(r) > 1 and r[1] != '-':
                    chk(pre + r[1], int(r[0][1:], 16))
                    n += 1
            cnt[key] = n
            # the window macro (one level of macro, which evaluate() cannot nest): its text against the heading's base
            mb = re.search(r'at 0x0600_0([0-9A-F]{3}) \+ 0x40 ([vc])', s)
            mac = 'POCKET_SYN_VOICE' if key == 'VOICE' else 'POCKET_SYN_SFX'
            dv = {x[0]: (x[1], x[2]) for x in DT}
            if not mb or dv.get(mac, ('', ''))[1].lower() != ('POCKET_SYN(0x%xu+0x40u*(%s))' % (int(mb.group(1), 16), mb.group(2))).lower() \
                    or dv.get('POCKET_SYN') != ('(off)', '(0x06000000u+(off))'):
                vbad.append('%s window base / stride (%s)' % (key, dv.get(mac)))
        # FEAT bits (4.10)
        n = 0
        for r in rows(sec('4.10 FEAT')):
            if re.fullmatch(r'\d+', r[0]) and len(r) > 1 and r[1] != '-':
                chk('POCKET_FEAT_' + r[1], 1 << int(r[0]))
                n += 1
            if r[0] == '23:16' and r[1] == 'IROM':
                chk('POCKET_FEAT_IROM_SHIFT', 16)
                chk('POCKET_FEAT_IROM_MASK', 0x00FF0000)
                n += 1
        cnt['FEAT'] = n
        want = {'CRAM': 9, 'XLINK': 3, 'SYN': 20, 'VOICE': 23, 'SFX': 13, 'FEAT': 8}
        if cnt != want:
            vbad.append('row counts %s, want %s' % (cnt, want))
        res('2 the v1.3 tables == the page\'s Appendix A v1.3 lines: CRAM map (%d regions, no overlap, the curve in its '
            'window), XLINK (%d), synth registers (%d) + bits + ID, VOICE (%d) / SFX (%d) fields and windows, FEAT (%d)'
            % (cnt.get('CRAM', 0), cnt.get('XLINK', 0), cnt.get('SYN', 0), cnt.get('VOICE', 0), cnt.get('SFX', 0),
               cnt.get('FEAT', 0)), not vbad, ' '.join(vbad[:5]))

# ---- 3. board.h against pocket_map.h
pairs = [('BRD_CAUSE_' + k, 'POCKET_CAUSE_' + k) for k in 'BASV'] + \
        [('BRD_LINE_MEI', 'POCKET_MIE_MEIE'), ('BRD_LINE_MTI', 'POCKET_MIE_MTIE'), ('BRD_LINE_MSI', 'POCKET_MIE_MSIE')] + \
        [('BRD_FREG_' + k, 'POCKET_FREG_' + k) for k in ('FE4', 'FE6', 'FE8', 'FEA', 'FEC', 'FEE', 'FF0', 'FF2', 'FF4', 'FF6')] + \
        [('BRD_OPT_' + k, 'POCKET_OPT_' + k) for k in ('MODEL_MASK', 'MW_MASK', 'MW_SHIFT', 'MENU', 'JAP', 'PAL')] + \
        [('BRD_CART_RAM_BYTES', 'POCKET_RAMDP_BYTES'), ('BRD_ROM_BYTES', 'POCKET_FLASH_BYTES'),
         ('BRD_WORKSPACE_BYTES', 'POCKET_SDRAM_BYTES'), ('BRD_SAVE_BYTES', 'POCKET_BRAM_BYTES'),
         ('BRD_STREAM_MAX_WORDS', 'POCKET_GO_WORDS_MASK'), ('BRD_VS_COUNT_MASK', 'POCKET_VSCNT_MASK'),
         ('BRD_DEC_BASE_MASK', 'POCKET_DEC_BASE_MASK')]
bad = ['%s=%s %s=%s' % (b, BH.get(b), p, PM.get(p)) for b, p in pairs if BH.get(b) is None or BH.get(b) != PM.get(p)]
res('3 board.h interface constants == pocket_map.h (%d pairs)' % len(pairs), not bad, ' '.join(bad[:6]))
code = strip_c_comments(bh_txt)
lits = re.findall(r'(?<![0-9a-zA-Z_])0x(?:0[1-9aAbB][0-9a-fA-F]{6}|8000[0-9a-fA-F]{4}|[fF]{6}[0-9a-fA-F]{2})(?![0-9a-fA-F])', code)
res('3 board.h holds no board address literal and no POCKET_ name', not lits and 'POCKET_' not in code, ' '.join(lits))
res('3 board.h: BRD_CART_RAM_USER_END = the register page start ($1FE0)', BH.get('BRD_CART_RAM_USER_END') == 0x1FE0)

# ---- 4. the clock
NTSC, PAL = 53693175, 53203424
clk = {n: L.get('clk_hz') for n, L in cfg['layouts'].items()}
res('4 fwbuild.json clk_hz of every layout == NTSC %d' % NTSC, all(v == NTSC for v in clk.values()), str(clk))
if doc is not None:
    s7 = re.search(r'## 7\. Clock-following figures.*?(?=\n## )', doc, re.S).group(0)
    res('4 MCU_INTERFACE 7 names the same two clock values (CLK_HZ = PAL ? 53_203_424 : 53_693_175)',
        'CLK_HZ = PAL ? 53_203_424 : 53_693_175' in s7 and '53.693175 MHz' in s7 and '53.203424 MHz' in s7)

# ---- 5. stage-1 sources: no removed IO, no retired ms counter, no clock literal
s1 = cfg.get('s1', {})
files = set()
for key in ('sources', 'compile_only', 'probe_sources'):
    files |= set(s1.get('pocket', {}).get(key, []))
for d in ('core', os.path.join('board', 'pocket')):
    for dp, dn, fn in os.walk(os.path.join(ROOT, d)):
        if 'neorv32' in dp:
            continue
        for f in fn:
            rel = os.path.relpath(os.path.join(dp, f), ROOT).replace(os.sep, '/')
            if f.endswith(('.c', '.h', '.S')) and (rel.startswith('core/') or 's1' in f or f in ('board_impl.h',)):
                files.add(rel)
files |= {'board/board.h', 'board/clock.h'}
BAD = re.compile(r'\b(MTIME\w*|UART\w*|WDT\w*|neorv32_uart\w*|neorv32_mtime\w*|POCKET_FIO_TIME_RETIRED|ADDR_FPGIO|FPGAIO->time)\b'
                 r'|0x[fF]{6}(?:8[cC]|9[0-9a-fA-F]|[aA][0-7])(?![0-9a-fA-F])|\b53_?693_?175|\b53_?203_?424|\b53693\b|\b53203\b')
hits = []
for f in sorted(files):
    p = os.path.join(ROOT, f)
    if not os.path.exists(p):
        continue
    t = strip_c_comments(open(p, encoding='utf-8', errors='replace').read())
    for i, ln in enumerate(t.split('\n'), 1):
        if BAD.search(ln.split('//')[0]):
            hits.append('%s:%d' % (f, i))
res('5 stage-1 sources (%d files): no removed IO (MTIME/UART/WDT), no ms counter, no clock literal' % len(files), not hits, ' '.join(hits[:8]))

# ---- 6. RTL
if not a.rtl:
    print('SKIP 6 RTL comparison (give --rtl <tree with rtl/PAPRIUM>)')
else:
    txt = {}
    for rdir in (os.path.join(a.rtl, 'rtl'), os.path.join(a.rtl, 'target')):    # core_top.sv (CLK_HZ) is in target/
        for dp, dn, fn in os.walk(rdir):
            for f in fn:
                if f.endswith(('.sv', '.v', '.svh', '.vh')):
                    txt[os.path.relpath(os.path.join(dp, f), a.rtl)] = open(os.path.join(dp, f), encoding='utf-8', errors='replace').read()
    mcu = next((t for k, t in txt.items() if k.replace(os.sep, '/').endswith('PAPRIUM/mcu_core.sv')), '')
    uc = re.search(r"\.USER_CODE\s*\(\s*(?:32'h|32'd)?([0-9A-Fa-f_]+)\s*\)", mcu) or re.search(r"USER_CODE\s*(?:=>|=)\s*(?:32'h|x\")([0-9A-Fa-f_]+)", mcu)
    if not uc:      # the value through a named parameter: .USER_CODE(NAME) and localparam / parameter NAME = 32'h...
        un = re.search(r"\.USER_CODE\s*\(\s*([A-Za-z_]\w*)\s*\)", mcu)
        if un:
            uc = re.search(r"\b(?:localparam|parameter)\b[^;=]*\b%s\s*=\s*32'h([0-9A-Fa-f_]+)\s*;" % re.escape(un.group(1)), mcu)
    want_uc = PM.get('POCKET_IFACE_ID')
    res('6 RTL NEORV32 USER_CODE == POCKET_IFACE_ID %#010x' % (want_uc or 0), uc and hexnum(uc.group(1)) == want_uc,
        'found %s' % (uc.group(1) if uc else 'none (pre-v1.0 RTL)'))
    cf = re.search(r'\.CLOCK_FREQUENCY\s*\(\s*([^)]*?)\s*\)', mcu)
    res('6 RTL CLOCK_FREQUENCY is a clock expression, not a literal', cf and not re.fullmatch(r"[\d_]+", cf.group(1)),
        'found %s' % (cf.group(1) if cf else 'none'))
    ch = [m for t in txt.values() for m in re.finditer(r'CLK_HZ\s*=\s*\(?\s*PAL\s*\)?\s*\?\s*([\d_]+)\s*:\s*([\d_]+)', t)]
    res('6 RTL CLK_HZ = PAL ? %d : %d (fwbuild clk_hz)' % (PAL, NTSC),
        ch and all((int(m.group(1).replace('_', '')), int(m.group(2).replace('_', ''))) == (PAL, NTSC) for m in ch),
        '%d definitions' % len(ch))
    dec = any(re.search(r'addr\s*\[\s*6\s*:\s*2\s*\]', t) for k, t in txt.items() if re.search(r'(fpgio|mcu_core)\.sv$', k))
    res('6 RTL FPGAIO decodes addr[6:2] (32 slots)', dec)
    fio = re.sub(r'//[^\n]*', '', next((t for k, t in txt.items() if k.replace(os.sep, '/').endswith('PAPRIUM/fpgio.sv')), ''))
    rd16 = re.search(r"5'd16\s*:\s*mcu_dati\s*<=\s*\{\s*16'd0\s*,\s*(\w+)\s*\}", fio)
    rst = rd16 and re.search(r'if\s*\(\s*md_srst_st\s*\)\s*begin(.*?)\bend\b', fio, re.S)
    res('6 RTL FPGAIO slot 16 reads {16\'0, VS count} and the count clears on every reset (v1.1)',
        rd16 and rst and re.search(r'\b%s\s*<=\s*16\'d0' % rd16.group(1), rst.group(1)),
        'found %s' % (rd16.group(1) if rd16 else 'no slot 16 read (a v1.0 tree)'))
    sdcp = os.path.join(a.rtl, 'target', 'pocket', 'core_constraints.sdc')
    sdc = open(sdcp, encoding='utf-8', errors='replace').read() if os.path.exists(sdcp) else ''
    res('6 RTL SDC: false path into the VS synchroniser\'s first stage only, through xf_col (v1.1)',
        re.search(r'set_false_path\s+-to\s+\[xf_col\s+vs\s+\[get_registers\s+\{\*\|paprium_vs_tap:\*\|synch_3:vs_sync\|stage_1\[\*\]\}\]\]',
                  sdc) is not None)
    # test build 4 (the MCU fast path): with the IROM / WRAM on
    # the NEORV32's processor bus, what the MCU reads must not move
    rtlf = lambda name: re.sub(r'//[^\n]*', '', next((t for k, t in txt.items() if k.replace(os.sep, '/').endswith('PAPRIUM/' + name)), ''))
    vhdp = os.path.join(a.rtl, 'rtl', 'PAPRIUM', 'paprium_neorv32.vhd')
    vhd = re.sub(r'--[^\n]*', '', open(vhdp, encoding='utf-8', errors='replace').read()) if os.path.exists(vhdp) else ''
    if 'mcu_tcm_wram' not in re.sub(r'//[^\n]*', '', mcu):
        print('SKIP 6 RTL card-4 items (this tree has the IROM / WRAM on Wishbone: round 4 and before)')
    else:
        win = lambda g: re.search(r'%s\s*=>\s*([^,\n]+)' % g, vhd)
        wi, wd = win('MEM_TCM_IMEM_SIZE'), win('MEM_TCM_DMEM_SIZE')
        full = lambda m: m and re.sub(r'\s', '', m.group(1)) in ('16*1024*1024', '16777216')
        ii, di = win('MEM_INT_IMEM_USE'), win('MEM_INT_DMEM_USE')
        res('6 RTL card 4: the IROM / WRAM windows are the whole regions 0x00 / 0x80 (aliases kept, 3), SYSINFO unchanged '
            '(MEM_INT_*_USE false)', full(wi) and full(wd) and ii and ii.group(1).strip() == 'false' and di and di.group(1).strip() == 'false',
            'found IMEM %s DMEM %s' % (wi.group(1).strip() if wi else 'none', wd.group(1).strip() if wd else 'none'))
        rd_ = rtlf('ramdp_io.sv')
        cart = rtlf('paprium_cart.sv')
        ack = re.search(r'output\s+reg\s+mcu_ack', rd_) and re.search(r'mcu\.map\.ramdp\s*\?\s*mcu_ack_ramdp', cart) \
            and re.search(r'\.mcu_ack\s*\(\s*mcu_ack_ramdp\s*\)', cart)
        res('6 RTL card 4: RAMDP answers with its registered ack (ramdp_io mcu_ack -> paprium_cart; a constant ack reads the '
            'cell of the address a clock early: 21 of 31 c00 read-backs wrong)', bool(ack))
        mem = rtlf('memory.sv')
        lanes = all(re.search(r'\$readmemh\s*\(\s*"wram_b%d\.txt"' % i, mem) for i in range(4)) and 'wram_hi.txt' not in mem
        res('6 RTL card 4: the WRAM reads the four lane images wram_b0..b3 the firmware build writes (tools/mkimage.py)', lanes)
    # v1.2: the RTL sprite decoder (2026-10-15), when the header is v1.2 or later
    if (PM.get('POCKET_IFACE_ID', 0) & 0xFF) >= 2:
        nc = lambda name: re.sub(r'//[^\n]*', '', next((t for k, t in txt.items() if k.replace(os.sep, '/').endswith('PAPRIUM/' + name)), ''))
        hw, rf = nc('paprium_hwdec.sv'), nc('paprium_regfile.sv')
        names = ('BASE', 'STAT', 'WORDS', 'TIME', 'MARGIN', 'LATECNT')
        slots = [(PM.get('POCKET_FIO_DEC_' + n, 0) - 0x01000000) // 4 for n in names]
        rd = re.search(r"5'd17\s*,\s*5'd18\s*,\s*5'd19\s*,\s*5'd20\s*,\s*5'd21\s*,\s*5'd22\s*:\s*mcu_dati\s*<=\s*(\w+)\s*;", fio)
        wr = re.search(r"\(\s*slot\s*>=\s*5'd17\s*\)\s*&\s*\(\s*slot\s*<=\s*5'd22\s*\)", fio)
        mux = [re.search(r"3'd%d\s*:\s*fio_rdata\s*=\s*([^;]+);" % i, hw) for i in range(6)]
        keys = ('dec_base', 'stat', 'acked', 't_time', 'margin', 'latecnt')
        mux_ok = all(m and k in m.group(1) for m, k in zip(mux, keys))
        res('6 RTL FPGAIO slots 17-22 (v1.2) go to paprium_hwdec: header slots %s, read arm, write decode, read mux order'
            % slots, slots == list(range(17, 23)) and rd is not None and wr is not None and mux_ok,
            'read %s write %s mux %s' % (rd.group(1) if rd else 'none', 'yes' if wr else 'none', mux_ok))
        rblk = next((b for b in re.findall(r'if\s*\(\s*reset\s*\)\s*begin(.*?)\n\s*end\s*\n\s*else', hw, re.S) if 'qn' in b), '')
        pats = (r"\bqn\s*<=\s*5'd0", r"\bst\s*<=\s*S_IDLE", r"\bstart_pend\s*<=\s*1'b0", r"\bdec_base\s*<=\s*\d+'d0",
                r"\bmargin\s*<=\s*32'h7FFFFFFF", r"\blatecnt\s*<=\s*16'd0")
        miss = [q for q in pats if not re.search(q, rblk)]
        res('6 RTL decoder reset (v1.2): queue empty, idle, no pending START, DEC_BASE 0, MARGIN 0x7FFFFFFF, LATECNT 0',
            bool(rblk) and not miss, ' '.join(miss) if rblk else 'no paprium_hwdec reset block (a v1.1 tree)')
        rbad = []
        if not re.search(r"w_word5\s*=\s*\(\s*m_word\s*==\s*3'd5\s*\)", rf): rbad.append('word 5 decode')
        if not re.search(r"dec_f4\s*=\s*w_word5\s*&\s*m_lo", rf) or not re.search(r"dec_f6\s*=\s*w_word5\s*&\s*m_hi", rf):
            rbad.append('+14 / +16 lanes')
        if not re.search(r"dec_f2\s*=\s*act_f2", rf): rbad.append('+12')
        if re.search(r"3'd[45]\s*:\s*mcu_dati", rf): rbad.append('an MCU read arm for word 4 or 5')
        if not re.search(r"fr_f2\s*&\s*\(\s*fr_f2_v\s*==\s*16'h8000\s*\)", hw): rbad.append('START 0x8000')
        if not re.search(r"fr_f6\s*&\s*fr_f6_v\[0\]", hw): rbad.append('CLEAR bit 0')
        res('6 RTL register file (v1.2): +12, +14, +16 to the decoder, MCU reads of words 4-5 = 0, START 0x8000, CLEAR bit 0',
            not rbad, ' '.join(rbad))
    else:
        print('SKIP 6 the v1.2 decoder items (the header is v1.%d)' % (PM.get('POCKET_IFACE_ID', 0) & 0xFF))

print('ALL PASS' if ok_all else 'SOME FAIL')
sys.exit(0 if ok_all else 1)
