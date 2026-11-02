#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_stack_su.py - cross-check tools/fwstack.py's frame sizes against GCC's own -fstack-usage.

    python -I -B tests/check_stack_su.py [--layout pocket72k] [--variant test]

Recompiles every pocket source of fwbuild.json with the build's exact options plus -fstack-usage into a scratch
directory, then:
  1. the objects are byte-identical to the build's (the flag only writes .su files; it does not change code), and
  2. for every C function GCC reports (.su, 'static' or 'bounded'), fwstack's frame (deepest stack-pointer offset,
     read from objdump's listing of our own linked image) is equal. Functions the link dropped (--gc-sections) or
     inlined away are listed, not failed; a 'dynamic' frame in a linked function fails.
Needs a build of that layout/variant (tools/fwbuild.py)."""
import argparse, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import fwbuild   # noqa: E402
import fwstack   # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--layout', default='pocket72k')
ap.add_argument('--variant', default='test')
a = ap.parse_args()
CFG = fwbuild.CFG
P = fwbuild.local_paths()
bdir = fwbuild.check_brain(P['brain_dir'])
pc = CFG['pocket']
gcc = fwbuild.tool(P['riscv_bin'], pc['prefix'] + 'gcc')
env = fwbuild.env_with(os.path.dirname(gcc))
build = os.path.join(ROOT, 'build', 'pocket', a.layout, a.variant)
if not os.path.exists(os.path.join(build, 'main.dis')):
    sys.exit('check_stack_su: no build at %s (run tools/fwbuild.py pocket first)' % build)
opts = pc['cc_opts'] + CFG['variants'][a.variant]['defines']
incs = sum((['-I', fwbuild.rp(d)] for d in pc['include']), [])
tmp = tempfile.mkdtemp(prefix='su_')
su = {}
same = diff = 0
try:
    for s in pc['sources']:
        base = os.path.basename(s)
        o = os.path.join(tmp, base + '.o')
        extra = ['-Wa,-I' + bdir] if base in CFG['brain']['users'] else []
        r = subprocess.run([gcc, '-c'] + opts + incs + extra + ['-fstack-usage', fwbuild.rp(s), '-o', o], env=env,
                           capture_output=True, text=True, cwd=tmp)
        if r.returncode:
            sys.exit('compile failed: %s\n%s' % (s, r.stderr[-2000:]))
        ref = os.path.join(build, 'obj', base + '.o')
        # objcopy-modified objects (paprium.c.o: two symbols globalised) are compared after the same objcopy
        if base + '.o' in pc['objcopy']:
            subprocess.run([fwbuild.tool(os.path.dirname(gcc), pc['prefix'] + 'objcopy')] + pc['objcopy'][base + '.o'] + [o], env=env, check=True)
        if open(o, 'rb').read() == open(ref, 'rb').read():
            same += 1
        else:
            diff += 1
            print('OBJECT DIFFERS: %s' % base)
        sf = os.path.join(tmp, base + '.su')
        if os.path.exists(sf):
            for ln in open(sf):
                m = re.match(r'^(.*):(\d+):(\d+):(\S+)\t(\d+)\t(\S+)', ln.rstrip('\n'))
                if m:
                    su[m.group(4)] = (int(m.group(5)), m.group(6), base)
finally:
    shutil.rmtree(tmp, ignore_errors=True)

cfg = json.load(open(os.path.join(ROOT, 'tools', 'stack.json')))
an = fwstack.Analyzer(os.path.join(build, 'main.elf'), os.path.join(build, 'main.dis'), cfg)
an.add_falls()
eq = ne = gone = 0
bad = []
for name, (n, q, src) in sorted(su.items()):
    f = an.fns.get(name)
    if f is None:
        cands = [g for g in an.fns if g.split('.')[0] == name and g not in su]   # foo.constprop.0 etc., unless GCC lists it itself
        f = an.fns[cands[0]] if len(cands) == 1 else None
    if f is None:
        gone += 1
        continue
    if q.startswith('dynamic'):
        bad.append('%s: GCC says dynamic (%s)' % (name, q))
    if f.frame == n:
        eq += 1
    else:
        ne += 1
        bad.append('%-34s gcc %5d  fwstack %5d  (%s)' % (name, n, f.frame, src))
print('objects: %d identical to the build, %d differ (-fstack-usage must not change code)' % (same, diff))
print('functions: %d frames equal GCC -fstack-usage, %d differ, %d in .su but not in the link (inlined or gc-ed)' % (eq, ne, gone))
for b in bad:
    print('  ' + b)
ok = diff == 0 and not bad
print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
sys.exit(0 if ok else 1)
