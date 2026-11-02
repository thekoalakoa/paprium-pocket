#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""dbgsave10.py - since test build S3a (a firmware build B Jam tested on his hardware): the stage-5 TEST image's debug
save version 10 (board/pocket/dbgsave.h; core/trace/tdiag.h) on RV32 (tests/equiv/rtlmodel.py's board of test build 5,
warm default). The stage-5 images are the FW_S5 builds with our own song engine.

The board model's DIAG reads a planted value; the image boots to the 68000's release, runs on for two and a half TIM7
periods (the periodic writes and the heartbeat), its record is decoded with tools/dbgsave.py, then a Soft Reset (the Pocket's Quit) boots it
again. Checked:
  V1  the record is version 10 with exactly its blocks (head, stats, sched, wdog, fatal, glue, synth, disp, stack, prev,
      vs, dec, prev2): no milestones, level counters, assertions, boot cache history or logs;
  V2  the synth's TIMEOUTs = the planted DIAG count; exceptions, refusals, failed jobs, the CPU MATE counters and the
      fatal record 0; the stack floor intact; the periodic writes came (writes >= 3) and the MCU heartbeat moved;
  V3  after the Soft Reset, PREV carries the first session's last write (its writes, board time, heartbeat) and PREV2
      its lateness signs (TIMEOUTs) and the chain's worst, with the lateness sign (DIRTY_AGE 1) only when TIMEOUTs > 0;
  V4  a record of another version left in the region (version
  9's head, as test build S2 leaves it) is named in PREV / PREV2
      STATE and nothing is carried (no chain);
  V5  the reader (tools/dbgsave.py report) prints the v10 lines.
Exit 0 = PASS, 1 = FAIL, 2 = setup error. The board is a model (its timing estimated)."""
import argparse, json, os, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import rtlmodel   # noqa: E402
import dbgsave    # noqa: E402

BLOCKS = {'head', 'stats', 'sched', 'wdog', 'fatal', 'glue', 'synth', 'disp', 'stack', 'prev', 'vs', 'dec', 'prev2'}
CASES = (('clean', 0, False), ('timeouts', 3 << 8, False), ('old v9', 0, True))
TIM7_MS = 102.4


def sav(save):
    s = bytearray(len(save))
    s[0::2], s[1::2] = bytes(save)[1::2], bytes(save)[0::2]
    return bytes(s)


def boot(b, out, name, ms_after):
    if not b.run_to('brd_boot', 900000000):
        out('FAIL', name, 'boot', 'brd_boot not reached (boot record %s)' % [b.rd32('s1_boot_rec', j) for j in range(4)])
        return False
    n = 0
    while b.ctrl & 1 and n < 400000:
        b.take()
        b.step(400)
        n += 1
    t0 = b.time
    while b.time - t0 < ms_after * 53693.175 and n < 2000000:
        b.take()
        b.step(400)
        n += 1
    return True


def run_case(build, rom, name, diag, old9, out):
    r0 = rtlmodel.Board.sy_r

    def sy_r(self, uc, off, size, ud):
        if off & 0xFFC == 0x040:
            return diag
        return r0(self, uc, off, size, ud)
    rtlmodel.Board.sy_r = sy_r
    try:
        b = rtlmodel.Board(build, rom)
        if old9:                                # a version-9 record's head in the region (as test build S2 leaves it)
            head = struct.pack('<9I', (1 << 16) | 8, dbgsave.MAGIC, 9, 7, 1234, 5678, 53693175, 1024, 0)
            for i, x in enumerate(head):
                b.save[0x1000 + i] = x
        recs = []
        for k in range(2):
            if k:
                b.soft_reset()
            if not boot(b, out, name, TIM7_MS * 2.5 if not k else 1.0):
                return
            rec, why = dbgsave.decode(sav(b.save))
            if rec is None:
                out('FAIL', name, 'V1', why)
                return
            recs.append(rec)
    finally:
        rtlmodel.Board.sy_r = r0
    rec, rec2 = recs
    out('PASS' if rec['head']['version'] == 10 and set(rec) == BLOCKS else 'FAIL', name, 'V1',
        'version %d, blocks %s' % (rec['head']['version'], sorted(rec)))
    to = (diag >> 8) & 0xFF
    z = dict(exc=rec['sched']['exc'], refusals=rec['disp']['refusals'], jobs_failed=rec['disp']['jobs_failed'],
             discarded=rec['glue']['discarded'], aborted=rec['glue']['aborted'], late=rec['glue']['late'],
             fatal=rec['fatal']['code'])
    ok = (rec['synth']['timeouts'] == to and not any(z.values()) and rec['stack']['floor_intact'] == 1 and
          rec['head']['writes'] >= 3 and rec['wdog']['ticks'] >= 1)
    out('PASS' if ok else 'FAIL', name, 'V2', 'timeouts %d (want %d), zeros %s, floor %d, writes %d, heartbeat %d' % (
        rec['synth']['timeouts'], to, z, rec['stack']['floor_intact'], rec['head']['writes'], rec['wdog']['ticks']))
    p, q = rec2['prev'], rec2['prev2']
    if old9:
        p1, q1 = rec['prev'], rec['prev2']
        ok = (p1['state'] == 9 and q1['state'] == 9 and q1['boots'] == 0 and p1['writes'] == 0 and p1['heartbeat'] == 0)
        out('PASS' if ok else 'FAIL', name, 'V4', 'first boot over a v9 head: prev state %d writes %d, prev2 state %d '
            'boots %d' % (p1['state'], p1['writes'], q1['state'], q1['boots']))
    ok = (p['state'] == 10 and p['writes'] == rec['head']['writes'] and p['now'] == rec['head']['now'] and
          p['heartbeat'] == rec['wdog']['ticks'] and q['state'] == 10 and q['timeouts'] == to and
          q['w_timeouts'] == to and q['boots'] == 1 and q['dirty_age'] == (1 if to else 0) and q['w_exc'] == 0 and
          q['w_floor_overwritten'] == 0)
    out('PASS' if ok else 'FAIL', name, 'V3', 'prev state %d writes %d / %d now %d / %d heartbeat %d / %d; prev2 state %d '
        'timeouts %d worst %d boots %d dirty_age %d' % (p['state'], p['writes'], rec['head']['writes'], p['now'],
                                                        rec['head']['now'], p['heartbeat'], rec['wdog']['ticks'],
                                                        q['state'], q['timeouts'], q['w_timeouts'], q['boots'],
                                                        q['dirty_age']))
    rep = dbgsave.report(rec2, False)
    want = ('debug save v10', 'freeze telemetry:', 'lateness signs:', 'CPU MATE:', 'previous session (v10 record',
            'worst over the 1 chained session', 'the newest session with a lateness sign')
    miss = [w for w in want if w not in rep]
    sign = ('the previous session' if to else 'none in the chain')
    out('PASS' if not miss and sign in rep.split('the newest session with a lateness sign')[-1] else 'FAIL', name, 'V5',
        'missing %s' % miss if miss else 'reader lines present, sign: %s' % sign)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket88k', 's5test'))
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    rom = ((json.load(open(lp)) if os.path.exists(lp) else {}).get('refs') or {}).get('rom')
    if not rom or not os.path.isfile(rom) or not os.path.exists(os.path.join(a.build, 'main.nm')):
        print('SETUP ERROR: paths.local.json "refs" "rom" and a built stage-5 TEST image (%s)' % a.build)
        sys.exit(2)
    rom = open(rom, 'rb').read()
    res = []

    def out(v, case, chk, info):
        res.append(v)
        print('%-4s %-9s %s %s' % (v, case, chk, info), flush=True)
    for name, diag, old9 in CASES:
        run_case(a.build, rom, name, diag, old9, out)
    bad = res.count('FAIL')
    print('%d checks, %d failed' % (len(res), bad))
    print('RESULT: %s' % ('PASS' if not bad and len(res) >= 13 else 'FAIL'))
    sys.exit(1 if bad or len(res) < 13 else 0)


if __name__ == '__main__':
    main()
