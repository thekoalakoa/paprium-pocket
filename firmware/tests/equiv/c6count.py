#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""c6count.py - the C6 hold (docs/ALLOWLIST.md row B34, the cart's way since 2026-10-17) on the RV32 board model: the
game's own boot count.

The game waits for C6 in a loop ($B4468-$B458A, verified in our study of the game's code): count = 14; it posts C600
($B4344 waits for $1FEA bit 15 clear, writes the 14 argument words at $1E10, then the command), reads $1FEA right after
the write and then once per VBlank START (it waits on the VDP status VB bit: if set until it clears, then until it
sets); while $1FEA bit 15 or $1FE6 bit 14 is set it adds 1 and waits again; on a clear read it leaves with the count,
and $80F2A keeps the low byte ($FF9B38), which $8102E hands to the random-number seeding. The cart gives 94 (B Jam's
three CDX power-ons, matched on all 256 attract demos; 95 once).

This rig boots a stage-1 image (FW_S1, our new firmware) on tests/equiv/rtlmodel.py (interrupts at random instruction
boundaries, seeded), replays a capture's records up to its C600 post with the game's protocol (each post waits for $1FEA
bit 15 clear; the capture's RAM writes at once), at the capture's times (frame x 896,040 + cy MCLK; the model's clock is
the master clock), with the modelled VDP's VBlank starts on the capture's frame starts and its VS starts (VSCNT) 37,572
MCLK after them (measured in the Nuked-MD emulator: NTSC V28, 10.99 lines), then plays the game's C6 loop against the
image: a read 672 MCLK after the C600 write (the 68000's 96 cycles from the write to the read, estimated from the game's
code), then one at each VBlank start after it + 300 MCLK ($1FE6 100 MCLK after $1FEA). It prints the count byte the game
would keep, and with a TEST image the hold's record (core/dispatch/jobs.c
c6_hold_test: the case, the end, the VS starts counted when the set-up ended).

--phase P (MCLK after the VBlank start, repeatable) moves the VDP's frames so that the C600 write lands P after a
VBlank start (the posts keep their own spacing); 'capture' (the default) = as recorded. The phases that matter: a
first read between a VBlank start and its VS start (-672 < P < 36,900: the first VS start then belongs to the VBlank
before the reads, so the hold spans one more), and the edges around both. Within a few tens of MCLK of either edge the
answer depends on the firmware's loop pass and the game's exact first-read time (estimated at 672): those phases are a
boundary, not a test (the steps there are 1-4 instructions, ~6-24 MCLK, so the model resolves the rest).
--negative: the planted images test_bug_c6a (no hold: count = our set-up's) and test_bug_c6b (no case check: 93 for a
write inside a VBlank before its VS start) must fail; the clean image must pass (built first with fwbuild --images-only).
Exit 0 = every run gave 94 (and every planted image failed where it must), 1 = a difference, 2 = setup error.
usage: python -I -B tests/equiv/c6count.py --build build/s1/pocket72k/test [--capture CAP] [--rom ROM] [--seed S]
                                           [--phase P ...] [--negative]
The board and the game's loop are models (rtlmodel from the documents; the loop from our study of the game's code);
the count 94 is the value measured on the cart."""
import argparse, json, mmap, os, random, struct, subprocess, sys, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
import rtlmodel   # noqa: E402
from rtlmodel import Board, Stop, FRAME_CYCLES   # noqa: E402

VS_LAG = 37572                  # VBlank start -> VS start, MCLK (Nuked-MD NTSC V28, measured)
VBLANK = 38 * 3420              # the VB status bit is set for 38 lines (224-261)
POLL0 = 672                     # the C600 write -> the game's first read of $1FEA: 96 68000 cycles x 7 MCLK ($B4394-$B4536:
                                # the write's end, movem 36, unlk 12, rts 16, movea.l abs 20, movea 4, the read in move.w 8)
POLL = 300                      # a VBlank start -> the game's read of $1FEA (its wait loop, nop, move.w)
POLL_FE6 = 100                  # its read of $1FE6 after $1FEA
COUNT_START = 14
CART_COUNT = 94
TIMEOUT = 960                   # the game's own limit ($B453E): past it, the red 00F0 screen


def boot_records(path):
    """the capture's records up to and with the C600 post: ('W', off, data) | ('B', word, args, t_cap)"""
    out = []
    with open(path, 'rb') as fh, mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) as d:
        o = 0
        while o + 20 <= len(d):
            t, ln, f, vl, _z, cy, pc68 = struct.unpack_from('<HHIHHII', d, o)
            po = o + 20
            o = po + ln
            if t == 3:
                ad, wd, v = struct.unpack_from('<HHH', d, po)
                if ad >= 0x1FE0:
                    continue
                out.append(('W', ad & ~1, struct.pack('<H', v & 0xFFFF)) if wd == 2 else ('W', ad ^ 1, bytes([v & 0xFF])))
            elif t == 2:
                wv = struct.unpack_from('<18H', d, po)
                out.append(('B', wv[0], struct.pack('<16H', *wv[2:18]), f * FRAME_CYCLES + cy))
                if wv[0] == 0xC600:
                    return out
    raise ValueError('no C600 post in %s' % path)


def run(build, rom, recs, seed, phase):
    """one boot to the game's C6 exit; returns a dict (count, byte, phase, hold record, polls)"""
    rnd = random.Random(seed)
    b = Board(build, rom, opt=0, seed=seed)

    fine = [0]                                      # model time until which steps stay short (the case check)

    def until(t, cond=None):
        while b.time < t or (cond is not None and not cond()):
            b.take()
            b.step(rnd.randint(1, 4) if b.time < fine[0] else rnd.randint(1, 48))
            if b.time - t > 300_000_000:
                raise Stop()

    if not b.run_to('brd_boot', 200_000):
        raise Stop()
    n = 0
    while b.ctrl & 1:                               # until the 68000's release
        b.take()
        b.step(400)
        n += 1
        if n > 300000:
            raise Stop()
    posts = [r for r in recs if r[0] == 'B']
    t6 = posts[-1][3]                               # the C600's capture time
    ph = t6 % FRAME_CYCLES if phase == 'capture' else int(phase)
    base = b.time + 2_000_000 - posts[0][3]         # the first post 2,000,000 MCLK after the release
    vb0 = base + t6 - ph                            # a VBlank start (ph before the C600's capture time)
    first_vs = vb0 + VS_LAG - FRAME_CYCLES * ((vb0 + VS_LAG - b.time) // FRAME_CYCLES)
    if first_vs <= b.time:
        first_vs += FRAME_CYCLES
    b.vs_align(first_vs)
    for r in recs:                                  # the boot's RAM writes (before the first post) at once
        if r[0] == 'W':
            b.w68_ram(r[1], r[2])
            continue
        _, word, args, tc = r
        until(base + tc, lambda: not (b.r68(0x0A) & 0x8000))   # the game waits for bit 15 clear, then writes
        b.w68_ram(0x1E10, args)
        b.w68_post_b(word)
    tw = b.time                                     # the C600 write
    fine[0] = tw + POLL0 + VS_LAG + 20000           # the firmware's case check reads TIMER and VSCNT in a tight loop
                                                    # to post + 38,244: steps of 1-4 instructions there (the model's
                                                    # time inside a step is approximate: rtlmodel.py)
    vb_next = lambda t: vb0 + FRAME_CYCLES * ((t - vb0) // FRAME_CYCLES + 1)
    count, t, polls = COUNT_START, tw + POLL0, []
    while True:
        until(t)
        busy = bool(b.r68(0x0A) & 0x8000)
        if not busy:
            until(t + POLL_FE6)
            busy = bool(b.r68(0x06) & 0x4000)
        polls.append(round((t - vb0) / FRAME_CYCLES, 3))
        if not busy:
            break
        count += 1
        if count > TIMEOUT:
            break
        t = vb_next(t) + POLL
    rec = b.rd32('c6_hold_test') if 'c6_hold_test' in b.sym else None
    return dict(count=count, byte=count & 0xFF, phase=ph, write_phase=(tw - vb0) % FRAME_CYCLES,
                hold=None if rec is None else dict(case=rec & 0xFF, end=(rec >> 8) & 0xFF, edges=rec >> 16),
                polls=len(polls), first=polls[:2], last=polls[-2:], violations=b.violations[:3])


def inputs(a):
    loc = json.load(open(os.path.join(ROOT, 'paths.local.json'))) if os.path.exists(os.path.join(ROOT, 'paths.local.json')) else {}
    eq = loc.get('equiv', {})
    cap, rom = a.capture or eq.get('capture_solo'), a.rom or eq.get('rom')
    if not cap or not rom or not os.path.exists(cap) or not os.path.exists(rom):
        print('SETUP ERROR: --capture / --rom (or paths.local.json "equiv" capture_solo / rom)')
        sys.exit(2)
    return cap, open(rom, 'rb').read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket72k', 'test'))
    ap.add_argument('--capture')
    ap.add_argument('--rom')
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--phase', action='append', help="MCLK after a VBlank start for the C600 write, or 'capture'")
    ap.add_argument('--negative', action='store_true')
    ap.add_argument('--json')
    a = ap.parse_args()
    cap, rom = inputs(a)
    recs = boot_records(cap)
    phases = a.phase or ['capture']
    t0 = time.time()
    if a.negative:
        base = os.path.dirname(a.build)
        need = ['test_bug_c6a', 'test_bug_c6b']
        cmd = [sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
               '--out', os.path.dirname(os.path.dirname(base))]
        for v in need:
            cmd += ['--variant', v]
        rr = subprocess.run(cmd, capture_output=True, text=True)
        if rr.returncode:
            print('SETUP ERROR: building %s failed:\n%s' % (need, rr.stdout[-2000:] + rr.stderr[-2000:]))
            sys.exit(2)
        ok = True
        for v, ph, want in (('test_bug_c6a', 'capture', 'not 94'), ('test_bug_c6b', '20000', 'not 94'),
                            ('test_bug_c6b', 'capture', '94')):
            try:
                r = run(os.path.join(base, v), rom, recs, a.seed, ph)
            except Stop:
                r = dict(byte=None)
            hit = (r['byte'] == CART_COUNT) == (want == '94')
            ok &= hit
            print('%-4s %-13s phase %-8s count byte %s (expected %s)' % ('PASS' if hit else 'FAIL', v, ph, r['byte'], want))
        print('RESULT: %s (%.0f s)' % ('PASS' if ok else 'FAIL', time.time() - t0))
        sys.exit(0 if ok else 1)
    ok, out = True, []
    for ph in phases:
        try:
            r = run(a.build, rom, recs, a.seed, ph)
        except Stop:
            r = dict(byte=None, phase=ph, violations=['the model stopped'])
        out.append(r)
        good = r['byte'] == CART_COUNT and not r.get('violations')
        ok &= good
        print('%-4s %s seed %d: C600 written %s MCLK after a VBlank start (VS start at %d): count %s, byte %s; polls %s, '
              'first %s, last %s (frames from that VBlank start); hold %s %s' % (
                  'PASS' if good else 'FAIL', os.path.basename(a.build), a.seed, r.get('write_phase'), VS_LAG, r.get('count'),
                  r['byte'], r.get('polls'), r.get('first'), r.get('last'), r.get('hold'), r.get('violations') or ''), flush=True)
    if a.json:
        json.dump(out, open(a.json, 'w'), indent=1)
    print('RESULT: %s (%d run(s), %.0f s)' % ('PASS' if ok else 'FAIL', len(phases), time.time() - t0))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
