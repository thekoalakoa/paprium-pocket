#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""leakguard.py - numeric-literal leak guard: no chip, ROM, sub-CPU or brain values typed into this tree as numbers.

    python -I -B tools/leakguard.py [--allow FILE] [--extra PATH ...] [--extra-section FILE ...] [--no-tree]
                                    [--no-built] [--json OUT]

What it scans (tools/leakguard.json):
  sources  every tracked or new (not ignored) .c .h .S .s .ld .py .json file. Each file is split into code and
           comment/string text; in each, NUMERIC LITERAL RUNS are found: hex, decimal, binary, octal (C), with C
           suffixes and Python underscores, negatives as two's complement, consecutive literals separated only by
           commas, spaces, brackets and assembler data directives (.byte/.half/.word ...; comments between them are
           skipped). Every 8 consecutive values of a run are encoded as u8, u16 LE, u16 BE, u32 LE and u32 BE (where
           the values fit; 12 values for u8) and looked up in the references. Weak windows are skipped (fewer than 5
           different values, steps of at most 2 different sizes, mostly zero bytes): they match any counter table.
  built    the ELF sections of every Pocket build: build/pocket/*/*/main.elf, the images of the new firmware
           build/s1/*/*/main.elf (fwbuild.json "s1", built with FW_S1) and, from test build 4b on, their WRAM boot
           overlays
           build/s1/*/*/ovl/ovl.elf, over fwbuild.json's top-level layouts and its s1.layouts. The pocket88k layout
           holds every s5 image (s5test, s5release and their variants, built with FW_S5). A no-brain image is scanned
           whole. Data sections are scanned in 12-byte windows against
           every reference, code sections in 16-byte windows against the non-RV32 references (the brain files are
           RV32 code too). The brain's own bytes (.brain_irom; cf.bin and the image tables at the start of .wram_text)
           come from outside the tree by design and are excluded after an exact byte compare.
References (read in place and md5-checked, from paths.local.json "refs", "brain_dir" and, when set, "brain_dir_s1"):
the ROM (plain and 16-bit swapped), the cart program image, the sub-CPU program (plain and swapped), brain.bin,
cf.bin, rodata.bin, and, when "brain_dir_s1" is set, the files of the brain the s1 images link that differ from
those (brain.bin, which has the cycle-counter fix).
Allow-list (tools/leak_allow.json): hits inside an exactly matching definition of an allowed table are allowed
(symbol, place, element type, count and values hash all equal). In a built section, a window that overlaps such an
object is allowed too when every byte of it is inside an allowed object or zero (the linker's fill, or a zero byte
beside the table). B Jam's decision of 2026-10-30 approved that zero-byte rule; see that file.

--extra PATH adds files or directories outside the tree to the source scan, --extra-section FILE a raw binary scanned
like a built data section, --extra-elf FILE a linked ELF scanned like a build (all three for the positive controls in
tests/check_leakguard.py).
Exit status: 0 = no hit outside the allow-list; 1 = hits (each printed with file:line or ELF address and the reference
offset), or an allow entry whose symbol exists but does not match exactly; 2 = setup error (a reference missing or
with the wrong md5, no build to scan, bad config).
Stage numbers are the steps of the 0.3.0 work (README.md, "Terms")."""
import argparse, fnmatch, hashlib, json, os, re, struct, subprocess, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fwelf   # noqa: E402

ENC = (('u8', '<B', 1), ('u16le', '<H', 2), ('u16be', '>H', 2), ('u32le', '<I', 4), ('u32be', '>I', 4))
ELEM = {'u8': ('<B', 1), 'u16': ('<H', 2), 'u32': ('<I', 4), 's8': ('<b', 1), 's16': ('<h', 2), 's32': ('<i', 4)}
LIT = re.compile(r'(?<![\w.$#@\'"])(-?)(0[xX][0-9a-fA-F]+(?:_[0-9a-fA-F]+)*|0[bB][01]+(?:_[01]+)*|0[oO][0-7]+(?:_[0-7]+)*'
                 r'|\d+(?:_\d+)*)([uUlL]{0,3})(?![\w.])')
CODE_SEP = re.compile(r'(?:[\s,{}\[\]()\\]|\.(?:byte|2byte|4byte|8byte|half|hword|short|word|long|int|quad|dword|value'
                      r'|dc\.[bwl])\b)*')
TEXT_SEP = re.compile(r'[\s,;:|/*#{}\[\]()\\=-]*')
CPP = r'(?:include|define|undef|if|ifdef|ifndef|elif|else|endif|error|warning|pragma|line)\b'
REGION = {
    'c': re.compile(r'(?P<c>//[^\n]*|/\*.*?\*/)|(?P<s>"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\')', re.S),
    'asm': re.compile(r'(?P<c>//[^\n]*|/\*.*?\*/|#(?!\s*' + CPP + r')[^\n]*)|(?P<s>"(?:\\.|[^"\\\n])*")', re.S),
    'py': re.compile(r'(?P<c>#[^\n]*)|(?P<s>[rRbBuUfF]{0,2}(?:\'\'\'.*?\'\'\'|""".*?"""|\'(?:\\.|[^\'\\\n])*\'|"(?:\\.|[^"\\\n])*"))',
                     re.S),
    'json': re.compile(r'(?P<s>"(?:\\.|[^"\\])*")', re.S),
}


class Setup(Exception):
    pass


def views(text, lang):
    """(code view, text view): same length as text, newlines kept. Code view: comments -> spaces, strings -> NUL
    (a string breaks a run). Text view: only comment and string text, code -> NUL."""
    code, txt = list(text), ['\0' if ch != '\n' else '\n' for ch in text]
    for m in REGION[lang].finditer(text):
        a, b = m.span()
        fill = ' ' if m.groupdict().get('c') is not None else '\0'
        for i in range(a, b):
            ch = text[i]
            if ch == '\n':
                continue
            code[i] = fill
            txt[i] = ch
    return ''.join(code), ''.join(txt)


def lit_value(sign, body, lang):
    b = body.replace('_', '')
    if b[:2].lower() in ('0x', '0b', '0o'):
        v = int(b, 0)
    elif lang in ('c', 'asm') and len(b) > 1 and b[0] == '0':
        v = int(b, 8) if all(c in '01234567' for c in b) else int(b, 10)
    else:
        v = int(b, 10)
    return -v if sign else v


def literal_runs(view, sep, lang):
    """[[(value, offset), ...], ...]: maximal runs of literals separated only by `sep`"""
    runs, cur, prev_end = [], [], None
    for m in LIT.finditer(view):
        if cur and not sep.fullmatch(view, prev_end, m.start()):
            runs.append(cur)
            cur = []
        cur.append((lit_value(m.group(1), m.group(2), lang), m.start()))
        prev_end = m.end()
    if cur:
        runs.append(cur)
    return runs


def weak(vals, W):
    if len(set(vals)) < W['min_distinct_values']:
        return True
    return len({vals[i + 1] - vals[i] for i in range(len(vals) - 1)}) < W['min_distinct_steps']


def encode(vals, fmt, size):
    lo, hi = -(1 << (8 * size - 1)), (1 << (8 * size)) - 1
    if any(v < lo or v > hi for v in vals):
        return None
    mask = (1 << (8 * size)) - 1
    return b''.join(struct.pack(fmt, v & mask) for v in vals)


def strong_bytes(w, W):
    """enough different bytes, and not a ramp once the zero padding at either end is stripped (a hex-digit string
    after a NUL pad is a ramp)"""
    s = w.strip(b'\0')
    if len(set(s)) < (W['min_distinct_bytes_u8'] if len(w) <= 12 else W['min_distinct_bytes_wide']):
        return False
    return len({s[i + 1] - s[i] for i in range(len(s) - 1)}) >= W['min_distinct_steps']


def source_files(root, exts):
    out = subprocess.run(['git', '-C', root, 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                         capture_output=True)
    if out.returncode:
        raise Setup('git ls-files failed in %s' % root)
    files = sorted(set(f for f in out.stdout.decode('utf-8', 'replace').split('\0') if f))
    return [(f, os.path.join(root, f)) for f in files if os.path.splitext(f)[1] in exts and os.path.isfile(os.path.join(root, f))]


def c_arrays(code, symbol):
    """[(body_start, body_end, line)] of `symbol[...] = { ... }` definitions in a C code view"""
    out = []
    for m in re.finditer(r'\b%s\s*\[[^\]]*\]\s*=\s*\{' % re.escape(symbol), code):
        depth, i = 1, m.end()
        while i < len(code) and depth:
            depth += {'{': 1, '}': -1}.get(code[i], 0)
            i += 1
        out.append((m.end(), i - 1, code.count('\n', 0, m.start()) + 1))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--allow', default=os.path.join(HERE, 'leak_allow.json'))
    ap.add_argument('--config', default=os.path.join(HERE, 'leakguard.json'))
    ap.add_argument('--extra', action='append', default=[], help='file or directory outside the tree, scanned as sources')
    ap.add_argument('--extra-section', action='append', default=[], help='raw binary file, scanned as a built data section')
    ap.add_argument('--extra-elf', action='append', default=[], help='linked ELF outside the tree, scanned like a build')
    ap.add_argument('--no-tree', action='store_true', help='do not scan the tree\'s sources')
    ap.add_argument('--no-built', action='store_true', help='do not scan the built ELF sections')
    ap.add_argument('--json', help='write the full report here')
    a = ap.parse_args()
    t0 = time.time()
    try:
        cfg = json.load(open(a.config))
        allow = json.load(open(a.allow))
        loc_p = os.path.join(ROOT, 'paths.local.json')
        loc = json.load(open(loc_p)) if os.path.exists(loc_p) else {}
        man = json.load(open(os.path.join(ROOT, 'fwbuild.json')))
        W = cfg['window']
        exts = cfg['sources']['extensions']
        # ---------------- references (read in place, md5-checked)
        refs = []      # (name, bytes, rv32)
        rl = loc.get('refs') or {}
        for k, r in cfg['references'].items():
            p = os.environ.get('PAPRIUM_REF_' + k.upper()) or rl.get(k)
            if not p or not os.path.isfile(p):
                raise Setup('reference %s (%s) not found: set paths.local.json "refs".%s' % (k, r['what'], k))
            d = open(p, 'rb').read()
            if hashlib.md5(d).hexdigest() != r['md5']:
                raise Setup('reference %s: md5 %s, expected %s (%s)' % (k, hashlib.md5(d).hexdigest(), r['md5'], p))
            refs.append((k, d, r['rv32']))
            if r.get('swap16'):
                n = len(d) & ~1
                sw = bytearray(n)
                sw[0::2], sw[1::2] = d[1:n:2], d[0:n:2]
                refs.append((k + ' (16-bit swapped)', bytes(sw), r['rv32']))
        bdir = os.environ.get('PAPRIUM_BRAIN_DIR') or loc.get('brain_dir')
        brain = {}
        for fn, info in man['brain']['files'].items():
            p = os.path.join(bdir or '', fn)
            if not bdir or not os.path.isfile(p):
                raise Setup('brain file %s not found (paths.local.json "brain_dir")' % fn)
            d = open(p, 'rb').read()
            if hashlib.md5(d).hexdigest() != info['md5']:
                raise Setup('brain file %s: md5 differs from fwbuild.json' % fn)
            brain[fn] = d
            refs.append((fn, d, bool(cfg.get('brain_rv32', True))))
        # the brain the s1 images link (fwbuild.json s1.brain, with the cycle-counter fix), when configured: its files
        # that differ from the 0.2.6 ones are references too (cf.bin and rodata.bin are the same bytes)
        bdir1 = os.environ.get('PAPRIUM_BRAIN_DIR_S1') or loc.get('brain_dir_s1')
        if bdir1:
            for fn, info in man['s1']['brain']['files'].items():
                p = os.path.join(bdir1, fn)
                if not os.path.isfile(p):
                    raise Setup('stage-1 brain file %s not found (paths.local.json "brain_dir_s1")' % fn)
                d = open(p, 'rb').read()
                if hashlib.md5(d).hexdigest() != info['md5']:
                    raise Setup('stage-1 brain file %s: md5 differs from fwbuild.json s1.brain' % fn)
                if d != brain[fn]:
                    refs.append(('s1 ' + fn, d, bool(cfg.get('brain_rv32', True))))
        # ---------------- allow entries
        entries = allow.get('entries', [])
        for e in entries:
            for k in ('id', 'symbol', 'path_glob', 'elem', 'count', 'values_sha256'):
                if k not in e:
                    raise Setup('allow entry %r lacks %s' % (e.get('id'), k))
            if e['elem'] not in ELEM:
                raise Setup('allow entry %s: elem %s unknown' % (e['id'], e['elem']))
    except Setup as e:
        print('SETUP ERROR: %s' % e)
        return 2

    cand = {}            # 8-byte prefix -> [(window, scope, info)]
    ncand = 0

    def add(w, scope, info):
        nonlocal ncand
        cand.setdefault(w[:8], []).append((w, scope, info))
        ncand += 1

    allowed_spans = []   # (path, start, end)
    allow_status = {e['id']: [] for e in entries}
    errors = []
    stats = {'files': 0, 'literals_in_runs': 0, 'runs_long_enough': 0, 'source_windows': 0, 'section_bytes': 0,
             'section_windows': 0}
    # ---------------- sources
    try:
        srcs = [] if a.no_tree else source_files(ROOT, exts)
    except Setup as e:
        print('SETUP ERROR: %s' % e)
        return 2
    for x in a.extra:
        x = os.path.abspath(x)
        if os.path.isdir(x):
            for dp, _, fns in os.walk(x):
                for fn in sorted(fns):
                    if os.path.splitext(fn)[1] in exts:
                        srcs.append((os.path.join(dp, fn).replace('\\', '/'), os.path.join(dp, fn)))
        elif os.path.isfile(x):
            srcs.append((x.replace('\\', '/'), x))
    for rel, p in srcs:
        lang = exts[os.path.splitext(p)[1]]
        text = open(p, 'rb').read().decode('utf-8', 'replace')
        code, txt = views(text, lang)
        stats['files'] += 1
        # allow-list spans: definitions of an allowed symbol (C only), checked exactly
        if lang == 'c':
            for e in entries:
                for b0, b1, line in c_arrays(code, e['symbol']):
                    vals = [lit_value(m.group(1), m.group(2), lang) for m in LIT.finditer(code, b0, b1)]
                    fmt, size = ELEM[e['elem']]
                    w = encode(vals, fmt, size)
                    place_ok = fnmatch.fnmatch(rel, e['path_glob'])
                    ok = place_ok and len(vals) == e['count'] and w is not None and hashlib.sha256(w).hexdigest() == e['values_sha256']
                    allow_status[e['id']].append({'where': '%s:%d' % (rel, line), 'matches': ok, 'count': len(vals),
                                                  'place_ok': place_ok})
                    if ok:
                        allowed_spans.append((rel, b0, b1))
                    else:
                        errors.append('allow entry %s: %s:%d defines %s but it is not the allowed table (%s)' % (
                            e['id'], rel, line, e['symbol'], 'place' if not place_ok else
                            'count %d, expected %d' % (len(vals), e['count']) if len(vals) != e['count'] else 'values differ'))
        for kind, view, sep in (('code', code, CODE_SEP), ('text', txt, TEXT_SEP)):
            for run in literal_runs(view, sep, lang):
                if len(run) < min(W['values'], W['values_u8']):
                    continue
                stats['runs_long_enough'] += 1
                stats['literals_in_runs'] += len(run)
                vals = [v for v, _ in run]
                for name, fmt, size in ENC:
                    n = W['values_u8'] if size == 1 else W['values']
                    for s in range(len(run) - n + 1):
                        ch = vals[s:s + n]
                        if weak(ch, W):
                            continue
                        w = encode(ch, fmt, size)
                        if w is None or not strong_bytes(w, W):
                            continue
                        o0, o1 = run[s][1], run[s + n - 1][1]
                        add(w, 'all', {'src': rel, 'line': text.count('\n', 0, o0) + 1, 'in': kind, 'as': name,
                                       'values': n, 'span': (o0, o1)})
                        stats['source_windows'] += 1
    # ---------------- built sections
    elfs = []
    if not a.no_built:
        for lay in sorted(man['layouts']):
            for var in sorted(man['variants']):
                p = os.path.join(ROOT, 'build', 'pocket', lay, var, 'main.elf')
                if os.path.isfile(p):
                    elfs.append(('%s/%s' % (lay, var), p))
        for lay in sorted(set(man['layouts']) | set(man.get('s1', {}).get('layouts', {}))):   # incl. pocket88k
            for var in sorted(man.get('s1', {}).get('pocket', {}).get('variants', {})):   # the new firmware's images
                p = os.path.join(ROOT, 'build', 's1', lay, var, 'main.elf')
                if os.path.isfile(p):
                    elfs.append(('s1/%s/%s' % (lay, var), p))
                p = os.path.join(ROOT, 'build', 's1', lay, var, 'ovl', 'ovl.elf')   # test build 4b: the WRAM boot
                                                                                    # overlay
                if os.path.isfile(p):
                    elfs.append(('s1/%s/%s/ovl' % (lay, var), p))
        if not elfs:
            print('SETUP ERROR: no Pocket build to scan (run tools/fwbuild.py all, or pass --no-built)')
            return 2
    elfs += [(os.path.abspath(x).replace(os.sep, '/'), x) for x in a.extra_elf]
    built_allowed = []   # (elf, lo, hi)
    S = cfg['sections']
    for tag, p in elfs:
        syms = fwelf.symbols(p)
        for e in entries:
            fmt, size = ELEM[e['elem']]
            for sy in syms:
                if sy['name'] != e['symbol']:
                    continue
                b = fwelf.load_bytes(p, sy['value'], sy['size']) or b''
                ok = sy['size'] == e['count'] * size and hashlib.sha256(b).hexdigest() == e['values_sha256']
                allow_status[e['id']].append({'where': '%s %s @%08X' % (tag, e['symbol'], sy['value']), 'matches': ok,
                                              'bytes': sy['size']})
                if ok:
                    built_allowed.append((tag, sy['value'], sy['value'] + sy['size']))
                else:
                    errors.append('allow entry %s: %s links %s (%d B) but it is not the allowed table' % (
                        e['id'], tag, e['symbol'], sy['size']))
        for s in fwelf.sections(p):
            if not s['alloc'] or s['nobits'] or not s['size'] or s['name'] == '.brain_irom':
                continue
            raw = open(p, 'rb').read()[s['off']:s['off'] + s['size']]
            spans = [(0, len(raw))]
            if s['name'] == '.wram_text':
                # the brain's parts linked from outside: cf.bin at the start, the image tables after the pad
                cf, ro = brain['cf.bin'], brain['rodata.bin']
                k = raw.find(ro)
                if tag.endswith('_nobrain') and not any(raw[:len(cf)]):
                    spans = [(0, len(raw))]                 # a no-brain image: no brain bytes, all of it is ours
                elif not raw.startswith(cf) or k < len(cf) or any(raw[len(cf):k]):
                    errors.append('%s .wram_text does not start with cf.bin, zero pad, rodata.bin' % tag)
                    continue
                else:
                    spans = [(k + len(ro), len(raw))]
            data = not s['exec']
            n = S['data_window_bytes'] if data else S['code_window_bytes']
            scope = 'all' if data else 'non_rv32'
            for x0, x1 in spans:
                stats['section_bytes'] += x1 - x0
                for i in range(x0, x1 - n + 1):
                    w = raw[i:i + n]
                    if strong_bytes(w, W):
                        add(w, scope, {'elf': tag, 'section': s['name'], 'addr': s['addr'] + i, 'len': n})
                        stats['section_windows'] += 1
    for x in a.extra_section:
        raw = open(x, 'rb').read()
        n = S['data_window_bytes']
        stats['section_bytes'] += len(raw)
        for i in range(len(raw) - n + 1):
            w = raw[i:i + n]
            if strong_bytes(w, W):
                add(w, 'all', {'elf': os.path.abspath(x).replace('\\', '/'), 'section': '(raw)', 'addr': i, 'len': n})
                stats['section_windows'] += 1
    # ---------------- lookup: slide every reference once over the 8-byte prefixes
    hits = []
    seen = set()
    for rname, d, rv32 in refs:
        get = cand.get
        for i in range(len(d) - 7):
            c = get(d[i:i + 8])
            if c is None:
                continue
            for w, scope, info in c:
                if (scope == 'non_rv32' and rv32) or d[i:i + len(w)] != w:
                    continue
                key = (rname, i, json.dumps(info, sort_keys=True))
                if key in seen:
                    continue
                seen.add(key)
                hits.append(dict(ref=rname, ref_offset=i, **info))
    # ---------------- allow-list: a hit is allowed only inside an exactly matching definition (a built window: or made
    # of such objects' bytes and zero bytes)
    tagp = dict(elfs)

    def built_ok(h):
        objs = [(lo, hi) for t, lo, hi in built_allowed if t == h['elf']]
        a0, n = h['addr'], h['len']
        if not any(lo < a0 + n and a0 < hi for lo, hi in objs):
            return False
        if any(lo <= a0 and a0 + n <= hi for lo, hi in objs):
            return True
        w = fwelf.load_bytes(tagp[h['elf']], a0, n) or b''
        return len(w) == n and all(w[i] == 0 or any(lo <= a0 + i < hi for lo, hi in objs) for i in range(n))
    bad, ok_hits = [], []
    for h in hits:
        if 'src' in h:
            al = any(r == h['src'] and b0 <= h['span'][0] and h['span'][1] < b1 for r, b0, b1 in allowed_spans)
        else:
            al = built_ok(h)
        (ok_hits if al else bad).append(h)
    st = {}
    for e in entries:
        found = allow_status[e['id']]
        st[e['id']] = ('not in the tree (matches nothing)' if not found else
                       '; '.join('%s %s' % (f['where'], 'matches' if f['matches'] else 'DOES NOT MATCH') for f in found))
    rep = {'stats': stats, 'candidate_windows': ncand, 'references': [(n, hashlib.md5(d).hexdigest()[:8], len(d)) for n, d, _ in refs],
           'elfs': [t for t, _ in elfs], 'hits': bad, 'allowed_hits': ok_hits, 'allow_entries': st, 'errors': errors,
           'wall_s': round(time.time() - t0, 1)}
    print('leakguard: %d source files (%d runs of >= %d literals, %d windows); %d section bytes of %s (%d windows); '
          '%d references; %.1f s' % (stats['files'], stats['runs_long_enough'], W['values'], stats['source_windows'],
                                     stats['section_bytes'], ', '.join(rep['elfs']) or 'no ELF', stats['section_windows'],
                                     len(refs), time.time() - t0))
    per = {}
    for t, _ in elfs:
        k = t.split('/')[1] if t.startswith('s1/') else (t.split('/')[0] if '/' in t and ':' not in t else 'extra')
        per[k] = per.get(k, 0) + 1
    print('built ELFs scanned: %d (%s)' % (len(elfs), ', '.join('%s %d' % kv for kv in sorted(per.items())) or 'none'))
    for e in entries:
        print('allow %-10s %s %d x %s: %s' % (e['id'], e['symbol'], e['count'], e['elem'], st[e['id']]))
    for h in ok_hits[:20]:
        print('ALLOWED %s' % h)
    for h in bad[:60]:
        where = ('%s:%d (%s, as %s)' % (h['src'], h['line'], h['in'], h['as'])) if 'src' in h else \
                ('%s %s @%08X (%d B)' % (h['elf'], h['section'], h['addr'], h['len']))
        print('HIT %s == %s +0x%X' % (where, h['ref'], h['ref_offset']))
    if len(bad) > 60:
        print('... %d hits in all' % len(bad))
    for e in errors:
        print('ERROR %s' % e)
    if a.json:
        json.dump(rep, open(a.json, 'w', newline='\n'), indent=1, default=list)
    fail = bool(bad or errors)
    print('RESULT: %s' % ('FAIL: %d hits outside the allow-list, %d allow-list errors' % (len(bad), len(errors)) if fail else
                          'PASS (0 hits outside the allow-list)'))
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
