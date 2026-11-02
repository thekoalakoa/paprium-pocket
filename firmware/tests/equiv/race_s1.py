#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""race_s1.py - the lost wake-up R1 of the stage-1 scheduler (in the builds from 2026-10-15 until its fix of
2026-10-18), planted, on the stage-1 TEST / RELEASE image (FW_S1, our new firmware) in the RV32 board model
(tests/equiv/rtlmodel.py; the 68000 side is fuzz_s1.py's: the solo capture, seed 1). The board is a model. L1, L2b and
L2c are the scheduler's levels (core/sched/sched.h).

    python -I -B tests/equiv/race_s1.py [--build build/s1/pocket72k/test] [--mode window|after|both] [--pc 0x...]
    python -I -B tests/equiv/race_s1.py --negative [--all]   the same image with the fix left out (test_bug_r1
                                                        or release_bug_r1: SCHED_BUG 9, rebuilt first) must lose the
                                                        planted job at both ends of the window (--all: at every
                                                        boundary), one fresh replay a plant

The race (core/sched/sched.c l2b_msi, core/dispatch/jobs.c l3_job; the rig freezes seen in a check run, attract TEST at
frame 4,425 and Arena at frame 175; found by a scheduler audit): an L2c pass calls l3_job, which reads the queue's
indices, finds nothing and returns 0. A job that an L1 post queues after that read, before the pass stores l2c_active =
0, raises MSIP; the nested L2b (MSI is open in L2c) clears MSIP, finds the pass running and leaves it alone. Before the
fix the pass then returned 0 and left too: the job stayed queued with MSIP clear and the 68000 spun on $1FE6 bit 14 for
good. The fix: the nested L2b says so (l2c_missed) and the pass looks again before it leaves.

The plant (version 3 of our race plant, with the window of the audit's version 4): after the capture's first unpack job has run,
the replay's 68000 waits, and at each boundary of
  window : l3_job from the instruction after its q_wr load (the second lbu) through its 'nothing queued' ret, and
           l2b_msi's 'sw zero, l2c_active' after the jal (l2c_active = 1; at the store, l3_job returned 0; a
           register-only instruction the compiler puts between the jal and the store, li / lui / mv / addi, is a
           boundary of the same state: a stage-5 s5test build has `li a5,8` there), or
  after  : the instructions after that store up to the csrc of MSI (l2c_active = 0, l3_job returned 0: the window is
           closed; the control),
in turn, one boundary per look, with the 68000's B mailbox free and bit 14 clear (the queue empty), it posts the same
DA02 again, as the game does once bit 14 clears. The MCU runs one instruction a step from the end of each unpack job to
its next look (a pending interrupt is taken at the first boundary it can be: the plant's L1 at that boundary, checked
by its mepc, and the MSI the L1 raises right after the L1's mret), and in steps of 1-48 instructions inside a job body.
  'ran'  : job_unpack entered for the planted job, and bit 14 clear again after it;
  'lost' : the planted job not started LOST_WAIT model cycles after the plant, with the queue not empty, MSIP clear and
           bit 14 set (the freeze: nothing will run it unless the 68000 posts again).
PASS: every plant landed at its boundary and ran (and the rig's other checks, fuzz_s1's FZ1-FZ14, raised nothing); with
--negative: every plant landed and was lost. --negative plants only in an L2b that interrupted no other L2b (the race's
own case): a lower L2b that has just run a job loops once more and finds the planted one, so a plant above it shows
nothing about the fix (in one layout of the MegaWire port the first eligible boundary of s5release_bug_r1 fell there). Exit 0 = PASS, 1 = FAIL, 2 = setup error."""
import argparse, json, os, re, struct, subprocess, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import fuzz_s1                                           # noqa: E402
import rtlmodel                                          # noqa: E402
from rtlmodel import Stop                                # noqa: E402
from unicorn import UC_HOOK_CODE                         # noqa: E402
from unicorn import riscv_const as RC                    # noqa: E402

FRAMES = 400                    # the solo capture's first unpack jobs come near frame 170; the plants follow them
LOST_WAIT = 20_000_000          # model cycles: a planted job not started this long after its plant is lost (one that is
                                # not lost starts within ~7,000 cycles; a DA02 job takes ~1.3 M)
FINE_AFTER = 50_000             # model cycles of one-instruction steps after a plant (v3), then 1-48 again
PLANT_WAIT = 50_000_000         # model cycles: no plant this long after the last event (the 68000 paused): 'not planted'
NEG_VARIANT = {'test': 'test_bug_r1', 'release': 'release_bug_r1',
               's5test': 's5test_bug_r1', 's5release': 's5release_bug_r1'}     # (stage 5: FW_S5, our own
                                                                               # song engine, pocket88k)


def functions(dis):
    """main.dis -> {name: [(addr, text), ...]}"""
    out, cur = {}, None
    for ln in open(dis):
        m = re.match(r'^([0-9a-f]{8}) <([^>]+)>:', ln)
        if m:
            cur = out.setdefault(m.group(2), [])
            continue
        m = re.match(r'^\s*([0-9a-f]+):\t[0-9a-f]+\s*\t(.*)$', ln)
        if m and cur is not None:
            cur.append((int(m.group(1), 16), m.group(2).strip()))
    return out


STORE_EQ = {}                   # build -> the register-only boundaries between `jal l3_job` and the store (plant_points)


def plant_points(build):
    """(window boundaries in order, the store's boundary, control boundaries, job_unpack's return sites)"""
    f = functions(os.path.join(build, 'main.dis'))
    lj = f['l3_job']
    addrs = [x[0] for x in lj]
    loads = [i for i, (a, t) in enumerate(lj) if t.startswith('lbu')]
    win, empty = [], None
    for a, t in lj[loads[1] + 1:]:                      # after the q_wr load, through the queue test's branch
        win.append(a)
        m = re.match(r'(bnez|beqz)\t(\w+),([0-9a-f]+)', t)
        if m:
            empty = a + 4 if m.group(1) == 'bnez' else int(m.group(3), 16)
            break
    if empty is None:
        raise ValueError('l3_job: no queue test after the q_wr load')
    for a, t in lj[addrs.index(empty):]:                # the 'nothing queued' path to its return
        if a not in win:
            win.append(a)
        if t.startswith('ret') or t.startswith('jr\tra'):
            break
    l2b = f['l2b_msi']
    store, after, pre = None, [], []
    for i, (a, t) in enumerate(l2b):
        if re.match(r'jal\t[0-9a-f]+ <l3_job>', t):
            j = i + 1
            while j < len(l2b) and len(pre) < 3 and re.match(r'(li|lui|mv|addi)\t', l2b[j][1]):
                pre.append(l2b[j][0])         # register-only: the same state as at the store
                j += 1
            a2, t2 = l2b[j]
            if not (t2.startswith('sw\tzero') and 'l2c_active' in t2):
                raise ValueError('l2b_msi: the instruction after jal l3_job is not the l2c_active store: %s' % t2)
            store = a2
            for a3, t3 in l2b[j + 1:]:
                after.append(a3)
                if t3.startswith('csrc\tmie'):
                    break
            break
    if store is None:
        raise ValueError('l2b_msi: no call of l3_job')
    win += pre
    win.append(store)
    STORE_EQ[build] = set(pre)
    rets = [a + 4 for fn in f.values() for a, t in fn if re.match(r'jal\t[0-9a-f]+ <job_unpack>', t)]
    L2B_RET[build] = [a + 4 for fn in f.values() for a, t in fn if re.match(r'jal\t[0-9a-f]+ <l2b_msi>', t)]
    return win, store, after, rets


L2B_RET = {}                    # build -> the return sites of l2b_msi's calls (the trap entry's)


class RaceFuzz(fuzz_s1.Fuzz):
    def __init__(self, build, rom, recs, plan, store):
        super().__init__(build, rom, recs, 1)
        self.rnd.random = lambda: 0.99      # no random extras (SENDs, extra A words, menus): the replay is the capture's
        self.plan, self.store = list(plan), store
        self.store_eq = STORE_EQ.get(build, set()) | {store}
        self.k = 0                          # the plant being made
        self.res = []
        self.cur = None                     # the pending plant: dict(mode, pc, t, landed, ran_t)
        self.unpacks = 0
        self.paused = False                 # from the first unpack job on, the 68000 makes only the plants
        self.fine = False
        self.done = False
        self.idle_t = None                  # when the plants began, or the last one resolved
        self.verbose = False
        self.l2c = self.sym['l2c_active'][0]
        self.l2b_depth = 0                  # the L2b levels open now (l2b_msi entered, not yet returned)
        self.only_l2b = False               # --negative: plant only at L2b depth 1
        self.b.uc.hook_add(UC_HOOK_CODE, self.at_l2b, begin=self.sym['l2b_msi'][0], end=self.sym['l2b_msi'][0])
        for a in L2B_RET.get(build, []):
            self.b.uc.hook_add(UC_HOOK_CODE, self.at_l2b_ret, begin=a, end=a)
        self.b.uc.hook_add(UC_HOOK_CODE, self.at_unpack, begin=self.sym['job_unpack'][0], end=self.sym['job_unpack'][0])
        self.b.uc.hook_add(UC_HOOK_CODE, self.at_l1, begin=self.sym['l1_mei'][0], end=self.sym['l1_mei'][0])

    def at_unpack(self, uc, addr, size, ud):
        self.unpacks += 1
        if self.da02 is not None and not self.paused:
            self.paused, self.idle_t = True, self.b.time    # a DA02 has been posted and a job runs: the plants begin
        self.fine = False                   # a job body: the rig's own steps
        if self.cur is not None and self.cur['ran_t'] is None and self.cur['t'] is not None:
            self.cur['ran_t'] = self.b.time

    def at_unpack_ret(self, uc, addr, size, ud):
        if not self.fine:                   # the job's end: one instruction a step to its next look (the step stops
            self.fine = True                # here, before this instruction; the next one-instruction step runs it)
            uc.emu_stop()

    def at_l2b(self, uc, addr, size, ud):
        self.l2b_depth += 1

    def at_l2b_ret(self, uc, addr, size, ud):
        self.l2b_depth = max(0, self.l2b_depth - 1)

    def at_l1(self, uc, addr, size, ud):
        if self.cur is not None and self.cur['t'] is not None and self.cur['landed'] is None:
            self.cur['landed'] = uc.reg_read(RC.UC_RISCV_REG_MEPC)

    def eligible(self):
        b = self.b
        if self.da02 is None or self.unpacks < 1 or self.inject:
            return False
        if b.r68(0x0A) != 0 or (b.r68(0x06) & 0x4000):
            return False
        if self.cur_a is not None and self.cur_a.get('fin') is None:
            return False
        return self.state in ('idle', 'wait14')

    def side_68000(self):
        b = self.b
        if self.cur is None and self.k < len(self.plan) and b.pc() == self.plan[self.k][1] and self.eligible() and \
                (not self.only_l2b or self.l2b_depth == 1):
            mode, pc = self.plan[self.k]
            act = struct.unpack('<I', bytes(b.uc.mem_read(self.l2c, 4)))[0]
            a0 = b.uc.reg_read(RC.UC_RISCV_REG_A0)
            if act == (1 if mode == 'window' else 0) and (a0 == 0 if (mode == 'after' or pc in self.store_eq) else True):
                if self.state == 'wait14':
                    self.state = 'idle'             # bit 14 is clear: the 68000 is done waiting
                self.cur = dict(mode=mode, pc=pc, t=b.time, landed=None, ran_t=None, frame=self.i, q=list(self.q_idx()))
                self.post_b(0xDA02, self.da02, synth=True)      # the L1 is taken at this boundary (the take below)
                self.fine = True
                return True
        if self.paused and self.state == 'idle' and not self.inject:
            return False                    # the 68000 spins: nothing but the plants from here
        return super().side_68000()

    def watch(self):
        b, c = self.b, self.cur
        if c is None:
            if self.paused and b.time - self.idle_t > PLANT_WAIT:
                mode, pc = self.plan[self.k]
                self.res.append(dict(mode=mode, pc=pc, t=None, landed=None, ran_t=None, frame=self.i, q=list(self.q_idx()),
                                     result='not planted', state=dict(q=list(self.q_idx()), msip=b.msip,
                                                                      bit14=bool(b.r68(0x06) & 0x4000))))
                self.done = True
            return
        if c['ran_t'] is not None:
            if not (b.r68(0x06) & 0x4000) and self.state in ('idle', 'wait14'):
                self.res.append(dict(c, result='ran', start_after=c['ran_t'] - c['t']))
                if self.verbose:
                    print('  plant %d %s %#x ran (t %d)' % (self.k, c['mode'], c['pc'], b.time), file=sys.stderr, flush=True)
                self.cur = None
                self.idle_t = b.time
                self.k += 1
                if self.k >= len(self.plan):
                    self.done = True
            return
        if b.time - c['t'] > FINE_AFTER:
            self.fine = False
        if b.time - c['t'] > LOST_WAIT:
            w, r = self.q_idx()
            frozen = ((w ^ r) & 0xF) != 0 and not b.msip and bool(b.r68(0x06) & 0x4000)
            self.res.append(dict(c, result='lost' if frozen else 'other', state=dict(q=[w, r], msip=b.msip,
                                                                                         bit14=bool(b.r68(0x06) & 0x4000))))
            self.done = True

    def run(self, wdog=False):
        b = self.b
        try:
            self.boot()
            n = 0
            while not self.done:
                n += 1
                if self.verbose and n % 200_000 == 0:
                    print('  t %d record %d/%d state %s paused %d fine %d pc %#x plant %d unpacks %d' % (
                        b.time, self.i, len(self.recs), self.state, self.paused, self.fine, b.pc(), self.k, self.unpacks),
                        file=sys.stderr, flush=True)
                self.side_68000()
                b.take()
                self.checkpoint_checks()
                self.fz13_check()
                self.watch()
                if self.done:
                    break
                b.step(1 if self.fine else self.rnd.randint(1, 48))
                if (b.time & 0x3FFF) < 300:
                    b.sfx_check()
                if not self.paused and self.i >= len(self.recs) and self.state == 'idle':
                    break                   # the capture ran out before its first unpack job
        except Stop:
            self.stopped = True
        return self.res


def run_plan(build, rom, recs, plan, store, rets, verbose=False, only_l2b=False):
    f = RaceFuzz(build, rom, recs, plan, store)
    f.verbose = verbose
    f.only_l2b = only_l2b
    for a in rets:
        f.b.uc.hook_add(UC_HOOK_CODE, f.at_unpack_ret, begin=a, end=a)
    t0 = time.time()
    res = f.run()
    return f, res, time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket72k', 'test'))
    ap.add_argument('--mode', choices=('window', 'after', 'both'), default='both')
    ap.add_argument('--pc', help='plant at this one boundary (hex)')
    ap.add_argument('--negative', action='store_true')
    ap.add_argument('--all', action='store_true', help='--negative: every window boundary, not only its two ends')
    ap.add_argument('--json')
    ap.add_argument('--verbose', action='store_true')
    a = ap.parse_args()
    cap, rom = fuzz_s1.inputs()
    build = a.build
    if a.negative:
        base, v = os.path.split(os.path.normpath(a.build))
        if v not in NEG_VARIANT:
            print('SETUP ERROR: --negative takes the test, release, s5test or s5release image (got %s)' % v)
            sys.exit(2)
        v = NEG_VARIANT[v]
        cmd = [sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
               '--out', os.path.dirname(os.path.dirname(base)), '--variant', v]
        rr = subprocess.run(cmd, capture_output=True, text=True)         # rebuilt every time: a stale image tests old
        if rr.returncode:                                                # sources
            print('SETUP ERROR: building %s failed:' % v + chr(10) + rr.stdout[-2000:] + rr.stderr[-2000:])
            sys.exit(2)
        build = os.path.join(base, v)
    if not os.path.exists(os.path.join(build, 'main.dis')):
        print('SETUP ERROR: no image at %s (tools/fwbuild.py s1)' % build)
        sys.exit(2)
    win, store, after, rets = plant_points(build)
    if a.pc:
        pc = int(a.pc, 16)
        if pc not in win + after:
            print('SETUP ERROR: %#x is not a boundary of the window %s or the control %s' % (
                pc, ['%#x' % x for x in win], ['%#x' % x for x in after]))
            sys.exit(2)
        plan = [('window' if pc in win else 'after', pc)]
    elif a.negative:
        plan = [('window', x) for x in (win if a.all else (win[0], store))]
    else:
        plan = ([('window', x) for x in win] if a.mode in ('window', 'both') else []) + \
               ([('after', x) for x in after] if a.mode in ('after', 'both') else [])
    recs = fuzz_s1.load_capture(cap, FRAMES)
    if a.negative:                          # a lost plant freezes the replay: one fresh replay a plant
        res, bad, wall = [], [], 0.0
        for x in plan:
            f, r1, w1 = run_plan(build, rom, recs, [x], store, rets, a.verbose, only_l2b=True)
            res += r1
            wall += w1
    else:
        f, res, wall = run_plan(build, rom, recs, plan, store, rets, a.verbose)
    print('race_s1 %s: window %s, control %s; %d plants planned' % (
        os.path.basename(build), ' '.join('%#x' % x for x in win), ' '.join('%#x' % x for x in after), len(plan)))
    for r in res:
        print('  %-6s %#07x: %-4s (landed at %s, %s; capture record %d, queue %s)' % (
            r['mode'], r['pc'], r['result'], '%#x' % r['landed'] if r['landed'] is not None else 'nowhere',
            ('started %d cycles after the plant' % r['start_after']) if r['result'] == 'ran' else
            'queue %s MSIP %s bit 14 %s' % (r['state']['q'], r['state']['msip'], int(r['state']['bit14'])),
            r['frame'], r['q']))
    bad = list(f.bad)
    landed = all(r['landed'] == r['pc'] for r in res)
    if a.negative:
        ok = len(res) == len(plan) and all(r['result'] == 'lost' for r in res) and landed
        why = ('the planted job was lost at %d of %d boundaries (the fix left out: the freeze)' % (
            sum(r['result'] == 'lost' for r in res), len(plan))) if ok else 'expected lost, got %s' % (
            [r['result'] for r in res] or 'no plant')
    else:
        ok = len(res) == len(plan) and all(r['result'] == 'ran' for r in res) and landed and not bad
        why = ('%d of %d plants ran' % (sum(r['result'] == 'ran' for r in res), len(plan))) + \
              ('' if landed else '; a plant did not land at its boundary') + ('' if not bad else '; rig: ' + '; '.join(bad[:3]))
    print('%s (%.0f s)' % (why, wall))
    if a.json:
        json.dump(dict(build=build, window=win, after=after, plan=plan, res=res, bad=bad, wall_s=round(wall, 1)),
                  open(a.json, 'w'), indent=1, default=str)
    print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
