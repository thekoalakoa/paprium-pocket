#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_tools.py - the static checks fail when they must (negative tests on a real build).

    python -I -B tests/check_tools.py [--layout pocket72k] [--variant test]

Runs tools/fwstack.py and tools/fwbudget.py on build/pocket/<layout>/<variant> with the real configs (must PASS) and
with one thing broken at a time (each must FAIL):
  stack  1. the stack region shrunk to 1 B under the gated worst chain
         2. the dispatcher's indirect call left unresolved (its 'indirect' entry removed)
  budget 3. one module's cap 1 B under its measured size
         4. an attribution rule removed (bytes become unattributed)
         5. a 0.3.0 allocation over its placement's room
and the same tools on the stage-1 image build/s1/<layout>/<variant> (FW_S1, our new firmware) with its own configs (SKIP
when it is not built): tools/stack_s1.json (scheme s1, gated) and the stage-1 rows of tools/budget.json:
  stack  6. the stack region shrunk to 1 B under the s1 scheme's worst chain
         7. the fatal-halt switch left unresolved (its 'indirect' entry removed)
  budget 8. the stage-1 dispatcher's cap 1 B under its measured size
         9. the stage-1 scheduler's rule removed (its bytes become unattributed)
        10. the stage-1 watchdog over its 0.3.0 allocation (its plan row's budget 1 B under the measured size)
and, on every image the stack check runs on here (the 0.2.6 layout, the stage-1 image and the stage-5 images
build/s1/pocket88k/s5test and s5release, FW_S5 with our own song engine, when built), the address-taken check still
catches a real function pointer:
  stack 11. a function whose address the code builds and stores or passes (from the image's own report), treated as
            covered by nothing (fwstack.py --uncover), fails naming it
        12. a function whose address a data word holds (a handler table), treated the same way, fails naming it (SKIP
            on the 0.2.6 image, which installs every handler from code and holds no function pointer in a data word)
        13. main.rel.elf (the linker's relocation records) missing fails
        14. another image's main.rel.elf in its place fails (not the same link)
Configs are modified in a temporary directory; the tree is not touched."""
import argparse, copy, json, os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
T = os.path.join(ROOT, 'tools')
ap = argparse.ArgumentParser()
ap.add_argument('--layout', default='pocket72k')
ap.add_argument('--variant', default='test')
a = ap.parse_args()
build = os.path.join(ROOT, 'build', 'pocket', a.layout, a.variant)
man = json.load(open(os.path.join(ROOT, 'fwbuild.json')))
lay_path = os.path.join(ROOT, *man['layouts'][a.layout]['regions'].split('/'))
stack = json.load(open(os.path.join(T, 'stack.json')))
bud = json.load(open(os.path.join(T, 'budget.json')))
lay = json.load(open(lay_path))
tmp = tempfile.mkdtemp(prefix='chk_')
ok_all = True


def run(tool, cfgflag, cfg, layout=None, bdir=None, js=None, extra=()):
    p = os.path.join(tmp, 'cfg.json')
    json.dump(cfg, open(p, 'w'))
    cmd = [sys.executable, '-I', '-B', os.path.join(T, tool), bdir or build, cfgflag, p] + (['--json', js] if js else []) + list(extra)
    if tool == 'fwstack.py':
        lp = os.path.join(tmp, 'lay.json')
        json.dump(layout or lay, open(lp, 'w'))
        cmd += ['--layout', lp]
    else:
        cmd += ['--variant', a.variant]
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout


def expect(name, rc, want_fail, out, must=None):
    global ok_all
    good = (rc != 0) == want_fail and (must is None or must in out)
    ok_all &= good
    lines = out.splitlines()
    k = next((i for i, ln in enumerate(lines) if ln.startswith('errors')), None)
    tail = [ln for ln in (lines[k + 1:] if k is not None else []) if ln.startswith('  ')]
    tail = tail or [ln for ln in lines if 'OVER by' in ln]
    print('%-4s %-62s rc %d%s' % ('PASS' if good else 'FAIL', name, rc, ('  | ' + tail[0].strip()[:90]) if tail and want_fail else ''))


def taken_controls(tag, cfg, bdir, layout=None):
    """11-14 on one image: a real code-taken and a real data-taken function left uncovered fail; the relocation
    records missing or from another link fail"""
    jp = os.path.join(tmp, 'taken.json')
    rc, out = run('fwstack.py', '--config', cfg, layout, bdir=bdir, js=jp)
    if rc:
        expect('stack%s: real config passes (taken controls)' % tag, rc, False, out)
        return
    at = json.load(open(jp))['address_taken']
    code = sorted(n for n, w in at.items() if any(not x.startswith('data ') for x in w))
    data = sorted(n for n, w in at.items() if any(x.startswith('data ') for x in w))
    for kind, names in (('builds and passes / stores', code), ('holds in a data word', data)):
        if not names:
            # the 0.2.6 image installs every handler from code: it holds no function pointer in a data word (the
            # stage-1 and stage-5 images and tests/check_fwstack_exact.py cover that kind)
            print('SKIP stack%s: no function whose address the code %s in this image (%d address-taken functions)'
                  % (tag, kind, len(at)))
            continue
        n = names[0]
        rc, out = run('fwstack.py', '--config', cfg, layout, bdir=bdir, extra=['--uncover', n])
        expect('stack%s: %s (its address the code %s) uncovered fails' % (tag, n, kind), rc, True, out,
               must='address taken but not covered by any indirect-call target set: %s ' % n)
    d2 = os.path.join(tmp, 'norel')
    shutil.rmtree(d2, ignore_errors=True)
    os.makedirs(d2)
    for fn in ('main.elf', 'main.dis'):
        shutil.copyfile(os.path.join(bdir, fn), os.path.join(d2, fn))
    rc, out = run('fwstack.py', '--config', cfg, layout, bdir=d2)
    expect('stack%s: no main.rel.elf (no relocation records) fails' % tag, rc, True, out, must='no main.rel.elf')
    return d2


rc, out = run('fwstack.py', '--config', stack)
expect('stack: real config passes', rc, False, out)
nr = taken_controls('', stack, build)
# the gated scheme's worst chain, from the JSON report
jp = os.path.join(tmp, 's.json')
subprocess.run([sys.executable, '-I', '-B', os.path.join(T, 'fwstack.py'), build, '--config', os.path.join(T, 'stack.json'),
                '--layout', lay_path, '--json', jp], capture_output=True)
rep = json.load(open(jp))
worst = max(s['worst']['bytes'] for s in rep['schemes'] if s['gate'])
L2 = copy.deepcopy(lay)
for r in L2['regions']:
    if r['kind'] == 'stack':
        r['lo'] = hex(int(r['hi'], 0) - (worst - 1))
rc, out = run('fwstack.py', '--config', stack, L2)
expect('stack: region %d B (gated worst %d B) fails' % (worst - 1, worst), rc, True, out)
S2 = copy.deepcopy(stack)
S2['indirect'].pop('ppm_cmd_handler')
rc, out = run('fwstack.py', '--config', S2)
expect('stack: unresolved indirect call in ppm_cmd_handler fails', rc, True, out)

rc, out = run('fwbudget.py', '--budget', bud)
expect('budget: real config passes', rc, False, out)
B2 = copy.deepcopy(bud)
m = next(m for m in B2['modules'] if m['name'].startswith('legacy: sprite engine'))
m['cap']['irom'] = (3628 if a.variant == 'test' else 3416) - 1      # the measured sizes (docs/BUDGET.md)
rc, out = run('fwbudget.py', '--budget', B2)
expect('budget: sprite engine cap 1 B under its size fails', rc, True, out)
B3 = copy.deepcopy(bud)
next(m for m in B3['modules'] if m['name'].startswith('lib:'))['rules'] = [{'obj': '^nothing$'}]
rc, out = run('fwbudget.py', '--budget', B3)
expect('budget: libc bytes unattributed fails', rc, True, out)
B4 = copy.deepcopy(bud)
B4['plan']['placements']['irom']['bytes'] = sum(m['budget'] for m in B4['plan']['modules'] if m['placement'] == 'irom') - 1
rc, out = run('fwbudget.py', '--budget', B4)
expect('budget: 0.3.0 IROM allocations 1 B over the room fails', rc, True, out)

# the stage-1 image
s1b = os.path.join(ROOT, 'build', 's1', man['s1']['layout'], a.variant)
if not os.path.exists(os.path.join(s1b, 'main.map')):
    print('SKIP stage-1 negatives (no %s: tools/fwbuild.py s1)' % s1b)
else:
    s1stack = json.load(open(os.path.join(ROOT, *man['s1']['pocket']['stack_config'].split('/'))))
    jp = os.path.join(tmp, 's1stack.json')
    rc, out = run('fwstack.py', '--config', s1stack, bdir=s1b, js=jp)
    expect('stack s1: real config passes', rc, False, out)
    worst = max(s['worst']['bytes'] for s in json.load(open(jp))['schemes'] if s['gate'])
    L3 = copy.deepcopy(lay)
    for r in L3['regions']:
        if r['kind'] == 'stack':
            r['lo'] = hex(int(r['hi'], 0) - (worst - 1))
    rc, out = run('fwstack.py', '--config', s1stack, L3, bdir=s1b)
    expect('stack s1: region %d B (gated s1 worst %d B) fails' % (worst - 1, worst), rc, True, out)
    S3 = copy.deepcopy(s1stack)
    S3['indirect'].pop('fatal_halt')
    rc, out = run('fwstack.py', '--config', S3, bdir=s1b)
    expect('stack s1: unresolved switch in fatal_halt fails', rc, True, out)
    nr1 = taken_controls(' s1', s1stack, s1b)
    if nr1:
        shutil.copyfile(os.path.join(build, 'main.rel.elf'), os.path.join(nr1, 'main.rel.elf'))
        rc, out = run('fwstack.py', '--config', s1stack, bdir=nr1)
        expect("stack s1: the 0.2.6 image's main.rel.elf in its place fails (not the same link)", rc, True, out,
               must='is not the same link as main.elf')
    # the stage-5 images (pocket88k), when built
    for v in ('s5test', 's5release'):
        s5b = os.path.join(ROOT, 'build', 's1', 'pocket88k', v)
        if not os.path.exists(os.path.join(s5b, 'main.rel.elf')):
            print('SKIP stage-5 %s taken controls (not built)' % v)
            continue
        l5 = json.load(open(os.path.join(ROOT, 'board', 'pocket', 'link', 'pocket88k.json')))
        nr5 = taken_controls(' %s' % v, s1stack, s5b, l5)
        if nr5:
            shutil.copyfile(os.path.join(s1b, 'main.rel.elf'), os.path.join(nr5, 'main.rel.elf'))
            rc, out = run('fwstack.py', '--config', s1stack, l5, bdir=nr5)
            expect("stack %s: the stage-1 image's main.rel.elf in its place fails (not the same link)" % v, rc, True,
                   out, must='is not the same link as main.elf')
    jb = os.path.join(tmp, 's1bud.json')
    rc, out = run('fwbudget.py', '--budget', bud, bdir=s1b, js=jb)
    expect('budget s1: real config passes', rc, False, out)
    used = {r['name']: r['used'] for r in json.load(open(jb))['today']}
    B5 = copy.deepcopy(bud)
    m = next(m for m in B5['modules'] if m['name'].startswith('stage 1: dispatcher'))
    m['cap'] = dict(m['cap'], irom=used[m['name']]['irom'] - 1)
    rc, out = run('fwbudget.py', '--budget', B5, bdir=s1b)
    expect('budget s1: stage-1 dispatcher cap 1 B under its size fails', rc, True, out)
    B6 = copy.deepcopy(bud)
    next(m for m in B6['modules'] if m['name'].startswith('stage 1: scheduler'))['rules'] = [{'obj': '^nothing$'}]
    rc, out = run('fwbudget.py', '--budget', B6, bdir=s1b)
    expect('budget s1: stage-1 scheduler bytes unattributed fails', rc, True, out)
    B7 = copy.deepcopy(bud)
    w = next(m for m in B7['plan']['modules'] if m['name'].startswith('watchdog'))
    w['budget'] = sum(used[x].get('irom', 0) + used[x].get('wcode', 0) for x in w['measured_by']) - 1
    rc, out = run('fwbudget.py', '--budget', B7, bdir=s1b)
    expect('budget s1: stage-1 watchdog 1 B over its 0.3.0 allocation fails', rc, True, out)
print('ALL PASS' if ok_all else 'SOME FAIL')
sys.exit(0 if ok_all else 1)
