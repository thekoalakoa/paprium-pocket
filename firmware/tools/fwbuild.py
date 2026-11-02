#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""fwbuild.py - build paprium-fw from ONE source tree for both targets (manifest: fwbuild.json).

    python -I -B tools/fwbuild.py pocket [--variant test|release ...] [--layout legacy54k|pocket72k ...] [--out DIR]
    python -I -B tools/fwbuild.py host   [--variant test|release ...] [--out DIR]
    python -I -B tools/fwbuild.py stubs  [--out DIR]            (new code not linked yet: RV32IM objects + host unit test)
    python -I -B tools/fwbuild.py s1     [--out DIR] [--clk-hz N]  (the new firmware: its images, board interface host
                                                                    tests, RV32IM checks)
    python -I -B tools/fwbuild.py all    [--out DIR]            (pocket for every variant and layout, host for every
                                                                 variant, stubs, then s1)
    python -I -B tools/fwbuild.py paths                          (show the resolved toolchains and brain directory)

pocket -> <out>/pocket/<layout>/<variant>/: obj/*.o, main.elf, main.map, main.nm (nm -n -S), main.dis, size.txt,
          img/{mcu.txt, mcu_ext.txt, wram_hi.txt, wram_lo.txt, wram_b0..b3.txt, rom.bin, wcode.bin, image.json}, md5.txt,
          layout.txt / layout.json (tools/fwsize.py: sizes per section, used/free per region),
          objects.txt (tools/fwobjs.py: bytes per object and per tree area, from the map), build.log,
          stack.txt / stack.json (tools/fwstack.py: static stack bound per interrupt level and nesting chain) and
          budget.txt / budget.json (tools/fwbudget.py: size per module against its cap and the 0.3.0 allocation).
          The build FAILS when the checked stack scheme (the one tools/stack.json marks "gate") or a size budget is
          over, or when either check cannot bound something (tools/stack.json, tools/budget.json).
host   -> <out>/host/<variant>/ours_host.exe (+ build.log): the 'ours' side of the audit harness (our comparison test
          harness, kept outside this tree: paths.local.json "harness_dir")
s1     -> the new 0.3.0 firmware: the "s1" source set of fwbuild.json, every compile with -DFW_S1=1
          -DBRD_CLK_HZ=<clk_hz> (the layout's clock value, or --clk-hz); the 0.2.6 source set never sees either define.
          Outputs: <out>/s1/<layout>/<variant>/ (its Pocket images, the same outputs as pocket; variants test, release,
          probe = test + the scheduler probe for the RV32 fuzz test tests/equiv/fuzz_sched.py, and the planted-bug
          probes), <out>/s1/host/<test>.exe (built, run; exit 1 on a failure) and <out>/s1/rv32/*.o (compile checks).
          --variant picks s1 variants by name. Variants marked
          "on_demand" (the brain-less images for the RTL tree, the fuzz tests' planted bugs) are built only when named;
          --images-only builds the named images without the host tests. A "nobrain" variant links zero files of the
          brain's sizes in the brain's place (no brain directory needed): the same layout and code as the brain build,
          and the glue finds no brain (buddy/s1_glue.c). A variant whose "budget" is null skips the size budget (the
          planted-bug images). The s1 images link their own brain build (fwbuild.json s1.brain: the 0.2.6 brain with
          a cycle-counter fix), not the 0.2.6 one. From test build 4b on, every s1 image but the scheduler probes also
          gets the WRAM boot overlay
          (fwbuild.json s1.overlay; board/pocket/boot/c4b.h), compiled and linked on its own into <variant>/ovl/
          (ovl.elf, ovl.map, ovl.dis, ovl.nm, ovl.img = the 16-byte header + the bytes, ovl.txt) and placed in the WRAM
          image by mkimage.py --wram-blob; the build FAILS when it outgrows its room, uses gp, calls out of itself,
          or its scratch reaches the main image's .noinit (its .bss must end at or below __BSS_END__).
Default <out> = <repo>/build.

Where the tools and the brains are (first match wins):
  1. environment: PAPRIUM_RISCV_BIN (dir holding riscv-none-elf-gcc), PAPRIUM_HOST_BIN (dir holding the host gcc),
     PAPRIUM_BRAIN_DIR (dir holding the 0.2.6 brain.bin, cf.bin, rodata.bin: the 0.2.6 source sets),
     PAPRIUM_BRAIN_DIR_S1 (dir holding the brain the s1 source set links)
  2. <repo>/paths.local.json  {"riscv_bin": ..., "host_bin": ..., "brain_dir": ..., "brain_dir_s1": ...}
     (not tracked: machine-specific)
  3. PATH (toolchains only)
The brain files are checked against the md5s in fwbuild.json ("brain", "s1"."brain") before anything is compiled.
Stage numbers are the steps of the 0.3.0 work (README.md, "Terms")."""
import argparse, hashlib, json, os, re, shutil, struct, subprocess, sys, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import fwsize   # noqa: E402
import fwobjs   # noqa: E402
import mkld     # noqa: E402
import fwelf    # noqa: E402

CFG = json.load(open(os.path.join(ROOT, 'fwbuild.json')))
EXE = '.exe' if os.name == 'nt' else ''


def md5f(p):
    return hashlib.md5(open(p, 'rb').read()).hexdigest()


def rp(p):
    return os.path.join(ROOT, *p.split('/'))


def local_paths():
    loc = {}
    p = os.path.join(ROOT, 'paths.local.json')
    if os.path.exists(p):
        loc = json.load(open(p))
    out = {}
    for key, env in (('riscv_bin', 'PAPRIUM_RISCV_BIN'), ('host_bin', 'PAPRIUM_HOST_BIN'), ('brain_dir', 'PAPRIUM_BRAIN_DIR'),
                     ('brain_dir_s1', 'PAPRIUM_BRAIN_DIR_S1')):
        out[key] = os.environ.get(env) or loc.get(key)
    return out


def tool(bindir, name):
    if bindir:
        p = os.path.join(bindir, name + EXE)
        if os.path.exists(p):
            return p
    p = shutil.which(name)
    if not p:
        sys.exit(f'fwbuild: cannot find {name} (set it in paths.local.json or the environment; see tools/fwbuild.py)')
    return p


class Log:
    def __init__(self, path):
        self.f = open(path, 'w', newline='\n')

    def run(self, cmd, env, capture=False, quiet=False):
        self.f.write('$ ' + ' '.join('"%s"' % c if ' ' in c else c for c in cmd) + '\n')
        r = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if r.stdout and not capture:
            self.f.write(r.stdout)
        if r.stderr and not (quiet and not r.returncode):      # quiet: a repeat whose messages are already logged
            self.f.write(r.stderr)
        self.f.flush()
        if r.returncode:
            sys.stderr.write(r.stderr[-4000:])
            sys.exit(f'fwbuild: command failed ({r.returncode}): {cmd[0]} ... (log: {self.f.name})')
        return r.stdout


def env_with(bindir):
    e = dict(os.environ)
    if bindir:
        e['PATH'] = bindir + os.pathsep + e.get('PATH', '')
    return e


def brain_files(s1=False):
    """the brain pin: fwbuild.json "s1"."brain" for the s1 source set, the top-level "brain" (0.2.6) otherwise"""
    return CFG['s1']['brain']['files'] if s1 else CFG['brain']['files']


def check_brain(bdir, s1=False):
    if not bdir or not os.path.isdir(bdir):
        if s1:
            sys.exit('fwbuild: stage-1 brain directory not set or missing (PAPRIUM_BRAIN_DIR_S1 or paths.local.json '
                     '"brain_dir_s1"); fwbuild.json s1.brain says where it comes from')
        sys.exit('fwbuild: brain directory not set or missing (PAPRIUM_BRAIN_DIR or paths.local.json "brain_dir"); '
                 'tools/extract_brain.py recovers it from a shipped 0.2.6 image set')
    for fn, d in brain_files(s1).items():
        p = os.path.join(bdir, fn)
        if not os.path.exists(p):
            sys.exit(f'fwbuild: {p} missing')
        m = md5f(p)
        if m != d['md5'] or os.path.getsize(p) != d['bytes']:
            sys.exit(f'fwbuild: {p} md5 {m} / {os.path.getsize(p)} B, expected {d["md5"]} / {d["bytes"]} B'
                     + (' (the stage-1 brain pin, fwbuild.json s1.brain)' if s1 else ''))
    return os.path.abspath(bdir)


def zero_brain(out):
    """a build without the CPU MATE brain: zero files of the brain's sizes (fwbuild.json s1.brain) in its place, so the
    layout and every other byte are the brain build's; the s1 glue (buddy/s1_glue.c) sees no brain and disables
    itself"""
    d = os.path.join(out, 'nobrain')
    os.makedirs(d, exist_ok=True)
    for fn, info in brain_files(s1=True).items():
        with open(os.path.join(d, fn), 'wb') as f:
            f.write(bytes(info['bytes']))
    return os.path.abspath(d)


def layout_cfg(lname):
    """a layout by name: the top-level ones, then the s1 set's own (fwbuild.json s1.layouts: pocket88k, the s5
    variants'), so the 0.2.6 source sets never build at them"""
    return CFG['layouts'].get(lname) or CFG['s1'].get('layouts', {})[lname]


def layout_ld(lname, out):
    L = layout_cfg(lname)
    if 'ld_json' in L:
        # generated: the committed .ld must equal what the JSON generates (no hand edits drift in)
        lay = json.load(open(rp(L['ld_json'])))
        src = mkld.gen(lay)
        cur = open(rp(L['ld']), 'rb').read().decode() if os.path.exists(rp(L['ld'])) else None
        if cur != src:
            sys.exit(f'fwbuild: {L["ld"]} is not what {L["ld_json"]} generates: run tools/mkld.py {L["ld_json"]} {L["ld"]}')
    p = os.path.join(out, os.path.basename(L['ld']))
    shutil.copyfile(rp(L['ld']), p)
    return p


def build_overlay(out, P, opts_extra):
    """test build 4b: the WRAM boot overlay (fwbuild.json s1.overlay; board/pocket/boot/c4b.h): its own compile (the
    overlay's options + the image's defines), its own link (board/pocket/link/c4b_ovl.ld), then the 16-byte header
    (magic, length, CRC-32 of the bytes after it, entry offset) written over the linker's 16 zero bytes ->
    <out>/ovl/ovl.img.
    Checks that fail the build: the image past its room, a load section outside its room, any gp use (crt0's gp is the
    main image's), a jal / j target outside the overlay, .data present. Returns its facts for build_pocket."""
    oc, pc = CFG['s1']['overlay'], CFG['pocket']
    gcc = tool(P['riscv_bin'], pc['prefix'] + 'gcc')
    bindir = os.path.dirname(gcc)
    tb = lambda n: tool(bindir, pc['prefix'] + n)
    env = env_with(bindir)
    od = os.path.join(out, 'ovl')
    os.makedirs(os.path.join(od, 'obj'), exist_ok=True)
    log = Log(os.path.join(od, 'build.log'))
    opts = oc['cc_opts'] + opts_extra
    incs = []
    for d in oc['include']:
        incs += ['-I', rp(d)]
    objs = []
    for s in oc['sources']:
        o = os.path.join(od, 'obj', os.path.basename(s) + '.o')
        log.run([gcc, '-c'] + opts + incs + [rp(s), '-o', o], env)
        objs.append(o)
    elf = os.path.join(od, 'ovl.elf')
    log.run([gcc] + opts + ['-T', rp(oc['ld'])] + objs + oc['ld_opts'] + ['-o', elf, '-Wl,-Map,' + os.path.join(od, 'ovl.map')], env)
    dis = log.run([tb('objdump'), '-d', elf], env, capture=True)
    open(os.path.join(od, 'ovl.dis'), 'w', newline='\n').write(dis)
    open(os.path.join(od, 'ovl.nm'), 'w', newline='\n').write(log.run([tb('nm'), '-n', '-S', elf], env, capture=True))
    base, room = int(oc['base'], 0), int(oc['room'])
    sym = {s['name']: s['value'] for s in fwelf.symbols(elf)}
    end = sym['__ovl_end']
    secs = [s for s in fwelf.sections(elf) if s['alloc'] and s['size']]
    for s in secs:
        if not s['nobits'] and not (base <= s['addr'] and s['addr'] + s['size'] <= base + room):
            sys.exit('fwbuild: overlay section %s at %#x (+%d) is outside its room' % (s['name'], s['addr'], s['size']))
        if s['name'] in ('.data', '.sdata'):
            sys.exit('fwbuild: the overlay has a %s section (its image must not change while it runs)' % s['name'])
    if end - base > room:
        sys.exit('fwbuild: the overlay is %d B, its room %d B' % (end - base, room))
    body = bytearray(end - base)
    for s in secs:
        if not s['nobits'] and s['addr'] < end:
            body[s['addr'] - base:s['addr'] - base + s['size']] = fwelf.load_bytes(elf, s['addr'], s['size'])
    bad = [ln for ln in dis.split('\n') if re.search(r'\tgp\b|,gp\b|\(gp\)', ln)]
    if bad:
        sys.exit('fwbuild: the overlay uses gp (%d instructions, e.g. %s)' % (len(bad), bad[0].strip()))
    for ln in dis.split('\n'):
        m = re.search(r'\t(jal|j)\t(?:\w+,)?([0-9a-f]+) <', ln)
        if m and not (base <= int(m.group(2), 16) < end):
            sys.exit('fwbuild: the overlay jumps out of itself: ' + ln.strip())
    entry = sym[oc['entry']] - base
    crc = zlib.crc32(bytes(body[16:])) & 0xFFFFFFFF
    body[0:16] = struct.pack('<4I', int(oc['magic'], 0), len(body) - 16, crc, entry)
    img = os.path.join(od, 'ovl.img')
    open(img, 'wb').write(bytes(body))
    facts = dict(img=img, base=base, room=room, bytes=len(body), free=room - len(body), crc=crc, entry=entry,
                 md5=hashlib.md5(bytes(body)).hexdigest(), bss=(sym['__ovl_bss_start'], sym['__ovl_bss_end']),
                 stk=(sym['__ovl_stk_start'], sym['__ovl_stk_end']), text=sum(s['size'] for s in secs if s['exec']))
    open(os.path.join(od, 'ovl.txt'), 'w', newline='\n').write(
        'card-4b WRAM boot overlay (MEASURED, %s):\n  %#x-%#x: %d of %d B (%d free), code %d B, entry +%#x, CRC-32 %08x, '
        'md5 %s\n  scratch .bss %#x-%#x (%d B), .bss_stk %#x-%#x (%d B)\n' % (
            os.path.basename(out), base, base + len(body) - 1, len(body), room, room - len(body), facts['text'], entry,
            crc, facts['md5'], facts['bss'][0], facts['bss'][1], facts['bss'][1] - facts['bss'][0], facts['stk'][0],
            facts['stk'][1], facts['stk'][1] - facts['stk'][0]))
    return facts


def build_pocket(variant, lname, out, P, sset=None):
    """one Pocket image set. sset = None: the 0.2.6 source set (fwbuild.json "pocket"), exactly as this tree first
    built it.
    sset = a dict (build_s1): sources, include, extra compile options, the stack config and the budget variant"""
    pc = CFG['pocket']
    L = layout_cfg(lname)
    if sset:                        # the s1 source set: its own brain pin (s1.brain), or zeros of its sizes
        bdir = zero_brain(out) if sset.get('nobrain') else check_brain(P['brain_dir_s1'], s1=True)
    else:
        bdir = check_brain(P['brain_dir'])
    gcc = tool(P['riscv_bin'], pc['prefix'] + 'gcc')
    bindir = os.path.dirname(gcc)
    tb = lambda n: tool(bindir, pc['prefix'] + n)
    env = env_with(bindir)
    os.makedirs(os.path.join(out, 'obj'), exist_ok=True)
    log = Log(os.path.join(out, 'build.log'))
    opts = pc['cc_opts'] + (sset['opts'] if sset else CFG['variants'][variant]['defines'])
    incs = []
    for d in (sset['include'] if sset else pc['include']):
        incs += ['-I', rp(d)]
    objs = []
    for s in (sset['sources'] if sset else pc['sources']):
        src = rp(s)
        o = os.path.join(out, 'obj', os.path.basename(s) + '.o')
        extra = ['-Wa,-I' + bdir] if os.path.basename(s) in CFG['brain']['users'] else []
        sopts = opts
        if sset and s in sset.get('no_extra', ()):
            # the moved 0.2.6 sources compile as 0.2.6 compiled them: without the s1 set's extra warnings
            sopts = [x for x in opts if x not in sset.get('extra', ())]
        if sset and any(s.startswith(pfx) for pfx in sset.get('os_prefixes', ())):
            # a variant's "os" sources (the s5 variants' song engine, docs/BUDGET.md 4's -Os convention) at -Os
            sopts = ['-Os' if x == '-O2' else x for x in sopts]
        log.run([gcc, '-c'] + sopts + incs + extra + [src, '-o', o], env)
        objs.append(o)
    for name, args in ({} if sset else pc['objcopy']).items():
        log.run([tb('objcopy')] + args + [os.path.join(out, 'obj', name)], env)
    ld = layout_ld(lname, out)
    elf = os.path.join(out, 'main.elf')
    lopts = []
    if 'ld_json' in L and json.load(open(rp(L['ld_json']))).get('sram'):
        # MegaWire: the SRAM image's link id (board/pocket/s3_sram.c), the same number in its header and in the IROM's
        # check: 30 bits of the CRC-32 of this link's objects, with bits 30 and 11 set (never a 12-bit immediate, far
        # from gp, so the value never changes an instruction's length)
        # the brain's object is left out (its bytes sit in their fixed hole either way): a build with the brain and its
        # no-brain twin share the id and the SRAM image, so the image built with the RTL's no-brain images also runs
        # on the bitstream update_mif puts the brain into
        crc = 0
        for o in objs:
            if os.path.basename(o) not in CFG['brain']['users'] and os.path.basename(o)[:-2] not in CFG['brain']['users']:
                crc = zlib.crc32(open(o, 'rb').read(), crc)
        lopts = ['-Wl,--defsym=__sram_link_id=0x%08x' % ((crc & 0x3FFFFFFF) | 0x40000800)]
    log.run([gcc] + opts + ['-T', ld] + objs + lopts + ['-o', elf, '-Wl,-Map,' + os.path.join(out, 'main.map')], env)
    # the same link again, keeping the linker's relocation records (--emit-relocs), for the stack check only
    # (tools/fwstack.py: a function's address counts as taken only where the code builds it as an address). main.elf and
    # every image stay as they were; the stack check refuses a main.rel.elf whose loaded bytes differ from main.elf's.
    log.run([gcc] + opts + ['-T', ld] + objs + lopts + ['-o', os.path.join(out, 'main.rel.elf'), '-Wl,--emit-relocs'], env,
            quiet=True)
    size = log.run([tb('size'), '-A', elf], env, capture=True)
    open(os.path.join(out, 'size.txt'), 'w', newline='\n').write(
        ''.join(ln + '\n' for ln in size.splitlines() if not any(k in ln for k in ('debug', 'comment', 'attributes'))))
    open(os.path.join(out, 'main.dis'), 'w', newline='\n').write(log.run([tb('objdump'), '-d', elf], env, capture=True))
    open(os.path.join(out, 'main.nm'), 'w', newline='\n').write(log.run([tb('nm'), '-n', '-S', elf], env, capture=True))
    cmd = [sys.executable, '-I', '-B', os.path.join(HERE, 'mkimage.py'), elf, os.path.join(out, 'img'),
           '--rom0-kb', str(L['rom0_kb']), '--ext-kb', str(L['ext_kb']), '--wram-kb', str(L['wram_kb']),
           '--objdump', tb('objdump')]
    for lo, hi in L['wram_init']:
        cmd += ['--wram-init', '%s:%s' % (lo, hi)]
    sram_lay = json.load(open(rp(L['ld_json']))).get('sram') if 'ld_json' in L else None
    if sram_lay:                    # the SRAM image (MegaWire): it goes into the Little-Man Firmware
                                    # file (tools/mkfafrium.py, docs/FAFRIUM.md); docs/MCU_INTERFACE.md section 3.7
        cmd += ['--sram', '%s:%s' % tuple(sram_lay['img'])]
    ovl = sset.get('overlay') if sset else None
    if ovl:                         # test build 4b: the WRAM boot overlay, in its own init range (wram_upper at
                                    # power-on)
        cmd += ['--wram-init', '%#x:%#x' % (ovl['base'], ovl['base'] + ovl['room']), '--wram-blob', '%#x:%s' % (ovl['base'], ovl['img'])]
        msym = {s['name']: s['value'] for s in fwelf.symbols(elf)}
        if ovl['bss'][1] > msym['__BSS_END__']:
            sys.exit('fwbuild: the overlay scratch ends at %#x, past the main image\'s __BSS_END__ %#x (it would reach '
                     '.noinit)' % (ovl['bss'][1], msym['__BSS_END__']))
        if ovl['stk'][0] < msym['__stack_floor'] or ovl['stk'][1] + int(CFG['s1']['overlay']['stack_clear']) > msym['__crt0_stack_begin']:
            sys.exit('fwbuild: the overlay scratch at the stack floor leaves too little stack above it')
    log.run(cmd, env)
    if ovl:
        shutil.copyfile(ovl['img'], os.path.join(out, 'img', 'ovl.img'))
    md5 = {}
    for fn in ('mcu.txt', 'mcu_ext.txt', 'wram_hi.txt', 'wram_lo.txt', 'wram_b0.txt', 'wram_b1.txt', 'wram_b2.txt',
               'wram_b3.txt', 'rom.bin', 'wcode.bin', 'image.json') + (('ovl.img',) if ovl else ()) + \
              (('sram.bin',) if sram_lay and os.path.getsize(os.path.join(out, 'img', 'sram.bin')) else ()):   # wram_b*: the newer
        md5[fn] = md5f(os.path.join(out, 'img', fn))                                                     # RTL's WRAM lanes
    open(os.path.join(out, 'md5.txt'), 'w', newline='\n').write(''.join('%s *img/%s\n' % (v, k) for k, v in md5.items()))
    lay = json.load(open(rp(L['regions'])))
    rows, regrep = fwsize.report(elf, lay)
    open(os.path.join(out, 'layout.txt'), 'w', newline='\n').write(fwsize.fmt(rows, regrep, 'layout %s, variant %s' % (lname, variant)) +
        (open(os.path.join(out, 'ovl', 'ovl.txt')).read() if ovl else ''))
    json.dump(dict(layout=lname, variant=variant, sections=rows, regions=regrep, md5=md5),
              open(os.path.join(out, 'layout.json'), 'w', newline='\n'), indent=1)
    otxt, oarea = fwobjs.report(os.path.join(out, 'main.map'), os.path.join(ROOT, 'fwbuild.json'))
    open(os.path.join(out, 'objects.txt'), 'w', newline='\n').write(otxt)
    # static checks that fail the build: stack bound per level / nesting chain, size budget per module
    checks = [('fwstack.py', 'stack', (sset['stack_args'] + ['--layout', rp(L['regions'])]) if sset else [])]
    if not sset or sset['budget_variant']:
        checks.append(('fwbudget.py', 'budget', ['--variant', sset['budget_variant'] if sset else variant]))
    for chk, rep, extra in checks:
        r = subprocess.run([sys.executable, '-I', '-B', os.path.join(HERE, chk), out] + extra +
                           ['--txt', os.path.join(out, rep + '.txt'), '--json', os.path.join(out, rep + '.json')],
                           capture_output=True, text=True)
        if r.returncode:
            sys.stderr.write(r.stdout[-3000:] + r.stderr[-2000:])
            sys.exit('fwbuild: %s FAILED for %s/%s (report: %s)' % (chk, lname, variant, os.path.join(out, rep + '.txt')))
    nwarn = sum(1 for ln in open(os.path.join(out, 'build.log')) if ': warning:' in ln)
    print('pocket %-9s %-7s mcu %s  mcu_ext %s  wram_hi %s  wram_lo %s  (%d warnings) -> %s' % (
        lname, variant, md5['mcu.txt'][:8], md5['mcu_ext.txt'][:8], md5['wram_hi.txt'][:8], md5['wram_lo.txt'][:8], nwarn, out))
    return md5


def build_host(variant, out, P):
    hc = CFG['host']
    cc = tool(P['host_bin'], hc['cc'])
    env = env_with(os.path.dirname(cc))
    os.makedirs(out, exist_ok=True)
    log = Log(os.path.join(out, 'build.log'))
    incs = []
    for d in hc['include']:
        incs += ['-I', rp(d)]
    exe = os.path.join(out, hc['exe'])
    log.run([cc] + hc['cc_opts'] + CFG['variants'][variant]['defines'] + incs + [rp(s) for s in hc['sources']] + ['-o', exe], env)
    print('host   %-7s -> %s (md5 %s)' % (variant, exe, md5f(exe)[:8]))
    return exe


def build_stubs(out, P):
    """new code that no image links yet: RV32IM objects (size, warnings) + the host unit test of the testable parts"""
    sc, pc = CFG['stubs'], CFG['pocket']
    gcc = tool(P['riscv_bin'], pc['prefix'] + 'gcc')
    env = env_with(os.path.dirname(gcc))
    os.makedirs(os.path.join(out, 'obj'), exist_ok=True)
    log = Log(os.path.join(out, 'build.log'))
    incs = []
    for d in sc['include']:
        incs += ['-I', rp(d)]
    objs = []
    for s in sc['sources']:
        o = os.path.join(out, 'obj', os.path.basename(s) + '.o')
        log.run([gcc, '-c'] + pc['cc_opts'] + ['-Wextra'] + incs + [rp(s), '-o', o], env)
        objs.append(o)
    sz = log.run([tool(os.path.dirname(gcc), pc['prefix'] + 'size')] + objs, env, capture=True)
    open(os.path.join(out, 'size.txt'), 'w', newline='\n').write(sz)
    print('stubs (RV32IM, not linked):\n' + sz.rstrip())
    cc = tool(P['host_bin'], CFG['host']['cc'])
    henv = env_with(os.path.dirname(cc))
    exe = os.path.join(out, 'stub_tests' + EXE)
    log.run([cc, '-O1', '-Wall', '-Wextra'] + incs + [rp(s) for s in sc['host_test']] + ['-o', exe], henv)
    r = subprocess.run([exe], capture_output=True, text=True, env=henv)
    print(r.stdout.rstrip())
    if r.returncode:
        sys.exit('fwbuild: stub tests failed')


def s1_defines(clk_hz):
    """-DFW_S1=1 and the one clock value, as a plain integer (the assembler reads it too: s1_crt0.S)"""
    sc = CFG['s1']
    hz = int(clk_hz or CFG['layouts'][sc['layout']]['clk_hz'])
    return sc['defines'] + ['-DBRD_CLK_HZ=%d' % hz], hz


def s1_variant_layout(variant):
    """the layout an s1 variant links at: its own "layout" (the s5 variants: pocket88k) or the set's"""
    return CFG['s1']['pocket']['variants'][variant].get('layout', CFG['s1']['layout'])


def build_s1_pocket(variant, out, P, clk_hz=None):
    """one s1 Pocket image set (fwbuild.json s1.pocket): the s1 sources (+ the variant's own), the layout's
    linker script, the s1 stack config (tools/stack_s1.json, whose scheme fails the build when over) and the size
    budget"""
    sp = CFG['s1']['pocket']
    defs, hz = s1_defines(clk_hz)
    V = sp['variants'][variant]
    sset = dict(sources=sp['sources'] + sp.get('variant_sources', {}).get(V.get('sources_as', variant), []),
                include=sp['include'], opts=sp.get('cc_extra', []) + defs + V['defines'], extra=sp.get('cc_extra', []),
                no_extra=sp.get('no_extra', []), nobrain=V.get('nobrain', False), os_prefixes=V.get('os', []),
                stack_args=['--config', rp(sp['stack_config'])], budget_variant=V['budget'])
    if '-DS1_PROBE=1' not in V['defines']:      # test build 4b: the WRAM boot overlay (not in the scheduler probes),
                                                # from test build 5 on in the s5
        sset['overlay'] = build_overlay(out, P, defs + V['defines'])         # images too (FW_S5: the curve)
    return build_pocket(variant, s1_variant_layout(variant), out, P, sset)


def build_s1(out, P, clk_hz=None, variants=None, images_only=False):
    """the s1 set: the Pocket images, the host tests (built and run) and the RV32IM compile checks"""
    sc, pc = CFG['s1'], CFG['pocket']
    defs, hz = s1_defines(clk_hz)
    os.makedirs(out, exist_ok=True)
    for v in (variants or sorted(k for k, V in sc['pocket']['variants'].items() if not V.get('on_demand'))):
        build_s1_pocket(v, os.path.join(out, s1_variant_layout(v), v), P, clk_hz)
    if images_only:
        return
    log = Log(os.path.join(out, 'build.log'))
    # RV32IM compile checks (not linked)
    gcc = tool(P['riscv_bin'], pc['prefix'] + 'gcc')
    env = env_with(os.path.dirname(gcc))
    rdir = os.path.join(out, 'rv32')
    os.makedirs(rdir, exist_ok=True)
    incs = []
    for d in sc['pocket']['include']:
        incs += ['-I', rp(d)]
    objs = []
    for s in sc['pocket'].get('compile_only', []):
        o = os.path.join(rdir, os.path.basename(s) + '.o')
        log.run([gcc, '-c'] + pc['cc_opts'] + sc['pocket'].get('cc_extra', []) + defs + incs + [rp(s), '-o', o], env)
        objs.append(o)
    if objs:
        sz = log.run([tool(os.path.dirname(gcc), pc['prefix'] + 'size')] + objs, env, capture=True)
        open(os.path.join(rdir, 'size.txt'), 'w', newline='\n').write(sz)
    # host tests
    hc = sc['host']
    cc = tool(P['host_bin'], CFG['host']['cc'])
    henv = env_with(os.path.dirname(cc))
    hdir = os.path.join(out, 'host')
    os.makedirs(hdir, exist_ok=True)
    hincs = []
    for d in hc['include']:
        hincs += ['-I', rp(d)]
    def host_link(name, srcs, vdefs=(), reuse=None, incs=None):
        """compile each source (the moved 0.2.6 ones with -w: their warnings are 0.2.6's), then link; reuse = (an
        object dir, the path prefixes to rebuild): every other source's object is taken from that dir; incs = a
        program's own include list (-I flags) in place of the s1 host's"""
        odir = os.path.join(hdir, 'obj_' + name)
        os.makedirs(odir, exist_ok=True)
        objs_h = []
        for x in srcs:
            if reuse and not any(x.startswith(pfx) for pfx in reuse[1]):
                objs_h.append(os.path.join(reuse[0], os.path.basename(x) + '.o'))
                continue
            o = os.path.join(odir, os.path.basename(x) + '.o')
            quiet = ['-w'] if x in hc.get('no_extra', ()) else []
            log.run([cc, '-c'] + hc['cc_opts'] + quiet + defs + list(vdefs) + (hincs if incs is None else incs)
                    + [rp(x), '-o', o], henv)
            objs_h.append(o)
        exe_h = os.path.join(hdir, name + EXE)
        log.run([cc] + objs_h + ['-o', exe_h], henv)
        return exe_h
    for name, srcs in hc.get('programs', {}).items():
        pvars, pdefs, pincs = hc.get('program_variants', {'': []}), [], None
        if isinstance(srcs, dict):              # a program with its own include list, defines and variants
            pvars = srcs.get('variants', {'': []})
            pdefs = list(srcs.get('defines', [])) + list(srcs.get('cc_extra', []))
            pincs = []
            for d in srcs['include']:
                pincs += ['-I', rp(d)]
            srcs = srcs['sources']
        for vname, vdefs in pvars.items():
            nm = name + ('_' + vname if vname else '')
            print('s1 host %-14s built -> %s' % (nm, host_link(nm, srcs, pdefs + list(vdefs), incs=pincs)))
    for name, srcs in hc['tests'].items():
        exe = host_link(name, srcs, hc.get('test_defines', {}).get(name, ()))
        r = subprocess.run([exe], capture_output=True, text=True, env=henv)
        log.f.write(r.stdout + r.stderr)
        print('s1 host %-14s %s' % (name, (r.stdout.strip().splitlines() or ['(no output)'])[-1]))
        if r.returncode:
            sys.stderr.write(r.stdout[-3000:] + r.stderr[-2000:])
            sys.exit('fwbuild: s1 host test %s failed (clock %d Hz; log: %s)' % (name, hz, log.f.name))
    for name, neg in hc.get('negative', {}).items():
        # only the sources the planted bug lives in are rebuilt; the rest are the clean test's objects (built above)
        exe = host_link(name, hc['tests'][neg['test']],
                        list(hc.get('test_defines', {}).get(neg['test'], ())) + list(neg.get('defines', [])),
                        reuse=(os.path.join(hdir, 'obj_' + neg['test']), neg.get('rebuild', ())))
        r = subprocess.run([exe], capture_output=True, text=True, env=henv)
        log.f.write(r.stdout[-2000:] + r.stderr[-1000:])
        caught = r.returncode == 1 and 'FAIL ' in r.stdout          # a failed check, not a crash
        print('s1 host %-14s %s' % (name, 'caught (exit %d): %s' % (r.returncode, neg.get('note', '')) if caught else 'NOT CAUGHT'))
        if not caught:
            sys.exit('fwbuild: the planted bug of %s was not caught (log: %s)' % (name, log.f.name))
    nwarn = sum(1 for ln in open(os.path.join(out, 'build.log')) if ': warning:' in ln)
    print('s1 (clock %d Hz): %d RV32 compile checks, %d host tests, %d warnings -> %s' % (hz, len(objs), len(hc['tests']), nwarn, out))
    if nwarn:
        sys.exit('fwbuild: the stage-1 source set must compile without warnings (log: %s)' % log.f.name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('target', choices=('pocket', 'host', 'stubs', 's1', 'all', 'paths'))
    ap.add_argument('--variant', action='append', choices=sorted(set(CFG['variants']) | set(CFG['s1']['pocket']['variants'])))
    ap.add_argument('--layout', action='append', choices=sorted(CFG['layouts']))
    ap.add_argument('--out', default=os.path.join(ROOT, 'build'))
    ap.add_argument('--clk-hz', type=int, help='s1 only: build at this clock instead of the layout clk_hz (clock test)')
    ap.add_argument('--images-only', action='store_true', help='s1 only: the named Pocket images, no host tests')
    a = ap.parse_args()
    P = local_paths()
    if a.target == 'paths':
        print(json.dumps(P, indent=1))
        return
    variants = a.variant or sorted(CFG['variants'])
    layouts = a.layout or sorted(CFG['layouts'])
    if a.target in ('pocket', 'all'):
        for ln in layouts:
            for v in variants:
                build_pocket(v, ln, os.path.join(a.out, 'pocket', ln, v), P)
    if a.target in ('host', 'all'):
        for v in variants:
            build_host(v, os.path.join(a.out, 'host', v), P)
    if a.target in ('stubs', 'all'):
        build_stubs(os.path.join(a.out, 'stubs'), P)
    if a.target in ('s1', 'all'):
        build_s1(os.path.join(a.out, 's1'), P, a.clk_hz, a.variant if a.target == 's1' else None,
                 a.images_only and a.target == 's1')


if __name__ == '__main__':
    main()
