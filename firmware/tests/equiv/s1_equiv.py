#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""s1_equiv.py - stage 1: the stage-1 firmware's host build (FW_S1, our new firmware: tests/s1/s1_ours.c on the fake
board) against the final 0.2.6 host build on one capture recorded in GPGX (the Genesis Plus GX emulator), every
68000-visible effect compared per post; the differences the stage-1 design makes on purpose are counted in their allow
category (tests/equiv/allowlist.json row), never dropped. Bnn are the allow-list rows (docs/ALLOWLIST.md).

Input stream as equivA.py: 'L' ROM, 'O' option word, 'R', 'S'; then every capture record from power-on: RAMW (type 3)
-> a raw cart-RAM write (the stage-1 side turns a write of $1FEC into the 68000's mailbox-A post, the 9494 tick);
CMD (type 2) -> the 16 argument words at $1E10, then 'P' (0.2.6: reg_cmd := word, ppm_cmd_handler(); stage 1: the
68000's $1FEA write, L1 at the next board point, the thread drained).

Compared per post (reference = 0.2.6):
  ramdp    cart RAM $0000-$1FDF, every word. Allowed: $1E4 = $FF00 (BOOT-06, row B20 / AL-06) and the C6 handler's
           $1800 / $1802 := 0 (chip 0x0801B2BA, row B10: the status/C6 protocol) until the game's next 88 rewrites them;
           the sprite words (since the sprite-values update, row B14's change of reference: tests/equiv/sprwords.py,
           s1_scope.json "sprite_words"): a word of the SAT, the DMA list or the stash, or $1F10 / $1F16 / $1F18 /
           $1F1C, may start to differ only at an AD (the SAT, $1F18), an AF (all) or a C6 ($1800 / $1802, B10, where the
           DMA list's far end overlaps the audio page), counted until both sides agree again; the chip lockstep
           (chiplock_s1.py) holds them to the chip
  regs     the register page $1FE0-$1FFF as the 68000 reads it: always differs by design (the chip's status protocol
           B10, the RTL busy B2, the finishes); counted per word, not failed
  pointer  the stream-window pointer after the post (0.2.6 sdram_ptr, stage-1 SPTR): strict, except B38 (since
           2026-10-15, MCU interface v1.2): an AF / B1 whose load list is empty starts the RTL decoder with no entry,
           which leaves SPTR where it was, while 0.2.6 rewound it to its scratch base (a B1 with loads: the reverse);
           counted, and carried while both pointers stay where that post left them (no window read follows such a post)
  volumes  the low byte of VOL_SFX / VOL_BGM (the RTL uses [7:0]; 0.2.6 stored the whole posted word): strict
  audio    the album / SFX entry points with their arguments: strict
  sdram    the 256-byte workspace granules the post changed, and their bytes: strict (diff after every post), except
           B38: 0.2.6 decoded a sprite block in the AD that loaded it, the cart's FPGA (and our RTL since 2026-10-15)
           decodes the frame's load list at the flush's START (AF / B1): the reference's AD granules are carried to the
           next flush and compared there with the stage-1 side's
           flush granules, bytes included (counted); a list an AE or
           B0 clears first is never decoded on the cart (counted; those granules leave the comparison until both sides
           hold the same bytes again)
  bram     battery save $000-$8FF strict; $900-$FFF strict in RELEASE, the 'debug' allow in TEST (snapshots)
Exit 0 = PASS, 1 = FAIL (any difference outside an allow category, or no post), 2 = setup error.
--plant KIND@N (negative controls, s1_slice.py): a difference planted on the stage-1 side only at post N, which the
comparer must report: ram = cart RAM $0100 poked before the post (-> ramdp), word = the post's low byte + 1 (-> audio
when N is an SFX post).
usage: python -I -B s1_equiv.py OUTDIR --capture CAP --rom ROM --ref EXE --new EXE [--to F] [--opt W] [--test]
       [--plant ram@N | word@N]"""
import argparse, collections, hashlib, json, mmap, os, struct, sys, time
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hostside import HostSide, runs, BRAM_N   # noqa: E402
from sprwords import SpriteWords   # noqa: E402

SDR_S1 = 0x200000          # the stage-1 side's workspace (2 MB); 0.2.6 writes nothing above it


def words(img, lo, hi):
    return struct.unpack_from('<%dH' % ((hi - lo) // 2), img, lo)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--capture', required=True)
    ap.add_argument('--rom', required=True)
    ap.add_argument('--ref', required=True, help='final 0.2.6 host build (ours_host protocol)')
    ap.add_argument('--new', required=True, help='build/s1/host/s1_ours_<variant>.exe')
    ap.add_argument('--to', type=int, default=10 ** 9)
    ap.add_argument('--opt', type=lambda s: int(s, 0), default=0)
    ap.add_argument('--test', action='store_true', help='TEST builds: BRAM $900-$FFF (snapshots) under the debug allow')
    ap.add_argument('--plant', help='negative control: ram@N or word@N (see the module text)')
    a = ap.parse_args()
    plant_kind, plant_at = (a.plant.split('@')[0], int(a.plant.split('@')[1])) if a.plant else (None, -1)
    for f in (a.capture, a.rom, a.ref, a.new):
        if not os.path.exists(f):
            print('RESULT: setup error: missing %s' % f)
            return 2
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    rom = open(a.rom, 'rb').read()
    ref, new = HostSide('ref', a.ref), HostSide('new', a.new)
    for s in (ref, new):
        s.q_load(rom)
        s.q_opt(a.opt)
        s.q_reset()
        s.q_shadow()
        s.flush()
    for s in (ref, new):
        s.k(); s.k(); s.k(); s.k()
    fails = collections.Counter()
    allowed = collections.Counter()
    regs = collections.Counter()
    first = []
    per_cmd = collections.Counter()

    def fail(kind, frame, word, info):
        fails[kind] += 1
        if len(first) < 200:
            first.append({'kind': kind, 'frame': frame, 'post': '%04X' % word, 'info': info})

    # the boot itself: cart RAM and the header after 'R'
    for s in (ref, new):
        s.q_all()
        s.flush()
    (r0, f0), (n0, g0) = ref.r_all(), new.r_all()
    boot_diff = [a_ for a_ in range(0, 0x1FE0, 2) if r0[a_:a_ + 2] != n0[a_:a_ + 2]]
    boot_ok = all(a_ == 0x1E4 for a_ in boot_diff) and struct.unpack_from('<H', n0, 0x1E4)[0] == 0xFF00
    if boot_ok:
        allowed['boot: $1E4 = $FF00 (B20, BOOT-06)'] += len(boot_diff)
    else:
        fail('boot_ramdp', -1, 0, ['$%04X %04X/%04X' % (x, struct.unpack_from('<H', r0, x)[0],
                                                       struct.unpack_from('<H', n0, x)[0]) for x in boot_diff[:12]])
    c6_window = False               # between C6 and the next 88: $1800 / $1802 may differ (the chip's C6 zeroes them)
    zoom_div = False                # stage 3 (test build S3a, row B53): the zoom
                                    # page differs from final 0.2.6 since an F5 / B6
    spr = SpriteWords()             # the sprite words, row B14's change of reference
    pend_ref = set()                # B38: the reference's AD granules not flushed yet
    div = set()                     # B38: granules a cleared list left different (out of the comparison until equal)
    ptr_div = None                  # B38: the (reference, stage-1) pointer pair an empty flush left
    capf = open(a.capture, 'rb')
    d = mmap.mmap(capf.fileno(), 0, access=mmap.ACCESS_READ)
    o, frame, nposts, nram = 0, -1, 0, 0
    prev_ptr = (None, None)
    chain = hashlib.md5(b's1_equiv')
    while o + 20 <= len(d):
        t, ln, f = struct.unpack_from('<HHI', d, o)
        po = o + 20
        o = po + ln
        if f > a.to:
            break
        if t == 1:
            frame = f
            continue
        if t == 3:
            ad, wd, v = struct.unpack_from('<HHH', d, po)
            if ad >= 0x2000:
                continue
            if wd == 2:
                off, data = ad & ~1, struct.pack('<H', v & 0xFFFF)
            else:
                off, data = ad ^ 1, bytes([v & 0xFF])
            for s in (ref, new):
                s.q_w(off, data)
            nram += 1
            continue
        if t != 2:
            continue
        wv = struct.unpack_from('<18H', d, po)
        word, cmd = wv[0], wv[0] >> 8
        args = struct.pack('<16H', *wv[2:18])
        for s in (ref, new):
            s.q_w(0x1E10, args)
            pw = word
            if s is new and nposts == plant_at and plant_kind == 'ram':
                s.q_w(0x100, bytes((0x5A, 0xA5)))
            if s is new and nposts == plant_at and plant_kind == 'word':
                pw = (word & 0xFF00) | ((word + 1) & 0xFF)
            s.q_post(pw)
            s.q_diff()
            s.q_bram(0, BRAM_N)
            s.flush()
        R = []
        for s in (ref, new):
            ram, fp, txt, au = s.r_post()
            gran = s.r_diff()
            br = s.read(BRAM_N)
            R.append([ram, fp, txt, au, [g for g in gran if g < SDR_S1], br, b''])
        # B38: the reference's sprite-block decodes move from the loading AD to the flush (the stage-1 side's START)
        if cmd == 0xAD and R[0][4] and not R[1][4]:
            pend_ref |= set(R[0][4])
            allowed['B38: a block decoded at its AD (0.2.6), at the flush (the cart, ours): granules carried'] += len(R[0][4])
            R[0][4] = []
        elif cmd in (0xAF, 0xB1) and pend_ref:
            R[0][4] = sorted(set(R[0][4]) | pend_ref)
            pend_ref = set()
        elif cmd in (0xAE, 0xB0) and pend_ref:
            allowed['B38: a load list cleared before its flush (AE / B0): never decoded on the cart'] += len(pend_ref)
            div |= pend_ref
            pend_ref = set()
        if div:
            for r in R:
                r[4] = [g for g in r[4] if g not in div]
        for s, r in zip((ref, new), R):
            for g, n in runs(r[4]):
                s.q_mem(g, n)
            s.flush()
        for s, r in zip((ref, new), R):
            r[6] = b''.join(s.read(n) for g, n in runs(r[4]))
        if div:                         # a granule left different by a cleared list: back in once both sides agree
            dl = sorted(div)
            for s in (ref, new):
                for g, n in runs(dl):
                    s.q_mem(g, n)
                s.flush()
            bx = [b''.join(s.read(n) for g, n in runs(dl)) for s in (ref, new)]
            for k, g in enumerate(dl):
                if bx[0][256 * k:256 * k + 256] == bx[1][256 * k:256 * k + 256]:
                    div.discard(g)
        nposts += 1
        per_cmd[cmd] += 1
        x, y = R
        h = hashlib.md5()
        for part in (x[0][:0x1FE0], x[3], x[6], x[5]):
            h.update(part)
        chain.update(h.digest())
        if cmd == 0xC6:
            c6_window = True
        # cart RAM below the register page: the sprite words by their start rule (sprwords.py), the rest word by word
        started, bad, differ = spr.ref_step(cmd & 0x3F, x[0], y[0])
        if started:
            allowed['B14 sprite words: started to differ at an AD / AF (update s1-sprval, chip-referenced)'] += 1
        if differ:
            allowed['B14 sprite words: differ after the post (posts)'] += 1
        if bad:
            fail('ramdp_sprite', frame, word, ['started to differ at a post that does not write them: ' + ', '.join(bad[:8])])
        # stage 3 (test build S3a, allow-list row B53): the zoom page $0200-$09FF is the chip's (core/zoom: the F5
        # rescale, job 8's save, B6's restore; chiplock_s1.py holds it to the chip): against final 0.2.6 it may start to
        # differ only at an F5 or a B6, counted until both sides agree again
        if x[0][0x200:0xA00] != y[0][0x200:0xA00]:
            if cmd in (0xF5, 0xB6) or zoom_div:
                zoom_div = True
                allowed['B53 zoom page $0200-$09FF: differs from final 0.2.6 since an F5 / B6 (the chip\'s zoom)'] += 1
            else:
                zw = [w_ for w_ in range(0x200, 0xA00, 2) if x[0][w_:w_ + 2] != y[0][w_:w_ + 2]]
                fail('ramdp_zoom', frame, word, ['started to differ at a post that is no F5 / B6: %d words from $%04X' % (
                    len(zw), zw[0])])
        else:
            zoom_div = False
        rngs = [(r0, r1) for r0, r1 in spr.ranges if x[0][r0:r1] != y[0][r0:r1]]
        if rngs:
            left = []
            for wa in (w_ for r0, r1 in rngs for w_ in range(r0, r1, 2)):
                p, q = x[0][wa:wa + 2], y[0][wa:wa + 2]
                if p == q or 0x200 <= wa < 0xA00:
                    continue
                if wa == 0x1E4 and q == b'\x00\xff':
                    allowed['$1E4 = $FF00 (B20, BOOT-06)'] += 1
                elif wa in (0x1800, 0x1802) and c6_window:
                    allowed['C6 handler: $1800 / $1802 := 0 (chip 0x0801B2BA, B10)'] += 1
                else:
                    left.append('$%04X %04X/%04X' % (wa, struct.unpack('<H', p)[0], struct.unpack('<H', q)[0]))
            if left:
                fail('ramdp', frame, word, left[:12] + (['... %d words' % len(left)] if len(left) > 12 else []))
        if cmd == 0x88:
            c6_window = False
        for wa in range(0x1FE0, 0x2000, 2):
            if x[0][wa:wa + 2] != y[0][wa:wa + 2]:
                regs['$%04X' % wa] += 1
        fx, fy = struct.unpack('<6I', x[1]), struct.unpack('<6I', y[1])
        if fx[2] != fy[2]:
            if cmd in (0xAF, 0xB1) and fy[2] == prev_ptr[1] and fx[2] != prev_ptr[0]:
                allowed['B38: an empty flush leaves SPTR (the cart\'s START with no entry), 0.2.6 rewound it'] += 1
                ptr_div = (fx[2], fy[2])
            elif cmd == 0xB1 and fx[2] == prev_ptr[0] and fy[2] != prev_ptr[1]:
                allowed['B38: a B1 with loads points the window at its decode (0.2.6 left it)'] += 1
                ptr_div = (fx[2], fy[2])
            elif ptr_div == (fx[2], fy[2]):
                allowed['B38: the pointer pair an empty flush left, carried (no window read)'] += 1
            else:
                fail('pointer', frame, word, ['%06X' % fx[2], '%06X' % fy[2]])
        else:
            ptr_div = None
        prev_ptr = (fx[2], fy[2])
        if (fx[3] & 0xFF, fx[4] & 0xFF) != (fy[3] & 0xFF, fy[4] & 0xFF):
            fail('volumes', frame, word, [fx[3], fx[4], fy[3], fy[4]])
        if x[3] != y[3]:
            fail('audio', frame, word, [x[3].hex(), y[3].hex()])
        if x[4] != y[4]:
            fail('sdram_granules', frame, word, [len(x[4]), len(y[4]), sorted(set(x[4]) ^ set(y[4]))[:8]])
        elif x[6] != y[6]:
            fail('sdram_bytes', frame, word, [len(x[6])])
        if x[5][:0x900] != y[5][:0x900]:
            fail('bram_saves', frame, word, None)
        if x[5][0x900:] != y[5][0x900:]:
            if a.test:
                allowed['TEST snapshots BRAM $900-$FFF (debug)'] += 1
            else:
                fail('bram_900', frame, word, None)
    for s in (ref, new):
        s.close()
    reasons = []
    if not nposts:
        reasons.append('no post replayed')
    if fails:
        reasons.append('%d differences outside the allow categories: %s' % (sum(fails.values()), dict(fails)))
    summ = {'plant': a.plant, 'capture': a.capture, 'rom_md5': hashlib.md5(rom).hexdigest(), 'opt': '%08X' % a.opt, 'to': a.to,
            'frames_to': frame, 'posts': nposts, 'ramw': nram, 'per_cmd': {'%02X' % k: v for k, v in sorted(per_cmd.items())},
            'ref': {'exe': a.ref, 'md5': hashlib.md5(open(a.ref, 'rb').read()).hexdigest()},
            'new': {'exe': a.new, 'md5': hashlib.md5(open(a.new, 'rb').read()).hexdigest()},
            'failures_by_kind': dict(fails), 'allowed_by_category': dict(allowed),
            'register_page_words_differing (68000 view; B10 / B2, counted)': dict(regs),
            'ref_chain_digest': chain.hexdigest(), 'wall_s': round(time.time() - t0),
            'result': 'FAIL' if reasons else 'PASS', 'fail_reasons': reasons}
    with open(os.path.join(a.out, 'mismatch.jsonl'), 'w') as fm:
        for r in first:
            fm.write(json.dumps(r) + '\n')
    open(os.path.join(a.out, 'summary.json'), 'w').write(json.dumps(summ, indent=1))
    print(json.dumps({k: summ[k] for k in ('frames_to', 'posts', 'failures_by_kind', 'allowed_by_category', 'wall_s')}))
    print('RESULT: PASS' if not reasons else 'RESULT: FAIL: ' + ' | '.join(reasons))
    return 1 if reasons else 0


if __name__ == '__main__':
    sys.exit(main())
