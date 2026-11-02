#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""zoomlock.py - stage 3 (test build S3a, a firmware build B Jam tested on his hardware): the zoom of a BUILT IMAGE
(core/zoom) against the cart chip's own zoom routines, both in Unicorn (the CPU emulator library).

    python -I -B tests/equiv/zoomlock.py --build build/s1/pocket88k/s5release [--sweep N] [--seed S] [--capture CAP ...]
    python -I -B tests/equiv/zoomlock.py --build build/s1/pocket88k/s5release --negative

Sides:
  chip  the cart program in the audit harness (our test harness outside this tree; paths.local.json "harness_dir":
        harness.ChipSide, its boot snapshot after C6; read in place): the rescale 0x08022D84, the copy-out 0x08022D48,
        the save 0x08022CD0, the restore 0x08022D04, the set-up 0x08022D34 called directly; and the game's own F4 / F5 /
        B6 posts through its mailbox, dispatcher, job queue and decoders
        (the 16 argument words at $1E10, the post, the queue drained).
  ours  the image's code (main.elf / main.nm) in Unicorn RV32, its loadable sections at their run addresses, gp from the
        ELF, WRAM exactly 48 KB (an access past it, or any unmapped access, is a fault and fails), RAMDP at 0x02000000,
        the ROM's word and byte views at 0x04000000 / 0x04800000: zoom_rescale, zoom_copyout, job_scale_save,
        job_scale_setup, job_restore, job_rescale and job_unpack (F4), under the dispatcher's flags for the posts.
After every call or post: the chip's block 0x200111EC-0x200129EB (stamps A / B, the F4 source, the save) against ours
(zoom_st, zoom_ss) byte for byte, RAMDP $0200-$09FF word for word, and (posts) the session / saved flags.

Sweep cases (--sweep N, --seed S): random block and RAMDP contents and F5 words in four bands (the game's domain and a
margin; into the save / the source; 16-bit wraps, odd starts, zero steps; past the block). A case is classed by where
the chip's accesses fall: 'in' (rows inside the source, writes inside the stamps) and 'spill' (into the save, the source:
the chip's own block) must be exact, then the copy-out, and (3 in 10) a save / set-up / restore; 'out' (the chip reads or
writes its sprite engine's RAM past the block: ours reads 0, drops the write, docs/ALLOWLIST.md row B53) is counted,
never failed, but ours must not fault. Cases whose chip side would itself leave its SRAM are skipped (counted).
Posts (--capture, default paths.local.json "equiv"."capture_solo"; our capture format, read in place): every F4 /
F5 / B6 post, compared after each; prints the game's F5 word ranges and the furthest source / stamp byte the chip
reached.
--negative: the four planted-bug RELEASE images (s5release_bug_zoom1..4: the nibble merge, the stamp walk, the copy-out's
clear, the read past the source), rebuilt with tools/fwbuild.py, must each FAIL (a 3,000-case sweep and the posts).
Exit 0 = PASS, 1 = FAIL, 2 = setup error. The last line printed is 'RESULT: ...'."""
import argparse, collections, json, os, random, struct, subprocess, sys, time
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))

F_SAVE, F_RESTORE, F_SETUP, F_COPY, F_F5 = 0x08022CD0, 0x08022D04, 0x08022D34, 0x08022D48, 0x08022D84
CB = 0x200111EC                  # the chip's block: stamps A / B, the F4 source, the save (6 KB)
CZ = 0x2001345C                  # session, start, end, step, row, pending, saved (u16 each)
G_WR = 0x20006F3E                # the job queue's write / read indices
NEG = ['s5release_bug_zoom%d' % k for k in (1, 2, 3, 4)]


def setup_error(msg):
    print('RESULT: setup error: ' + msg)
    sys.exit(2)


class Lock:
    def __init__(self, img, rom):
        from harness import ChipSide
        from unicorn import Uc, UC_ARCH_RISCV, UC_MODE_RISCV32
        self.st, self.bad, self.rng = collections.Counter(), [], {}
        self.c = ChipSide()
        self.m, self.mu = self.c.m, self.c.m.mu
        E = open(os.path.join(img, 'main.elf'), 'rb').read()
        self.sym, ssz = {}, {}
        for ln in open(os.path.join(img, 'main.nm')):
            p = ln.split()
            if len(p) == 4:
                self.sym[p[3]], ssz[p[3]] = int(p[0], 16), int(p[1], 16)
            elif len(p) == 3:
                self.sym[p[2]] = int(p[0], 16)
        for need in ('zoom_rescale', 'zoom_copyout', 'job_scale_save', 'job_scale_setup', 'job_restore', 'job_rescale',
                     'job_unpack', 'zoom_st', 'zoom_ss', 'ppmio', '__global_pointer$'):
            if need not in self.sym:
                setup_error('symbol %s missing in %s' % (need, img))
        if ssz.get('zoom_st') != 0x800 or ssz.get('zoom_ss') != 0x1000:
            setup_error('zoom_st / zoom_ss sizes %r %r' % (ssz.get('zoom_st'), ssz.get('zoom_ss')))
        u = self.u = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
        u.mem_map(0x00000000, 0x20000)
        u.mem_map(0x80000000, 0xC000)
        u.mem_map(0x02000000, 0x2000)
        phoff, = struct.unpack_from('<I', E, 28)
        phsz, phn = struct.unpack_from('<HH', E, 42)
        for i in range(phn):
            t, off, va, pa, fs, ms, fl, al = struct.unpack_from('<8I', E, phoff + i * phsz)
            if t == 1 and fs and (va < 0x20000 or 0x80000000 <= va < 0x8000C000):
                u.mem_write(va, E[off:off + fs])
        u.mem_write(0x1FFF0, struct.pack('<I', 0x0000006F))
        rom = rom + bytes(0x800000 - len(rom)) if len(rom) < 0x800000 else rom[:0x800000]
        u.mem_map(0x04000000, 0x800000)
        u.mem_map(0x04800000, 0x800000)
        sw = bytearray(rom)
        sw[0::2], sw[1::2] = rom[1::2], rom[0::2]
        u.mem_write(0x04000000, bytes(sw))
        u.mem_write(0x04800000, rom)
        u.mem_write(self.sym['ppmio'], struct.pack('<5I', 0x02000000, 0x04000000, 0x03000000, 0x05000000, 0))

    def fail(self, kind, msg):
        self.st['mismatch_' + kind] += 1
        if len(self.bad) < 40:
            self.bad.append('%s: %s' % (kind, msg))

    # chip
    def chip_block(self):
        return bytes(self.mu.mem_read(CB, 0x1800))

    def chip_ramdp(self):
        return bytes(self.m.ramdp[0x200:0xA00])

    # ours
    def call(self, fn, *a):
        from unicorn import UcError
        from unicorn import riscv_const as RC
        u = self.u
        u.reg_write(RC.UC_RISCV_REG_SP, 0x8000BFF0)
        u.reg_write(RC.UC_RISCV_REG_RA, 0x1FFF0)
        u.reg_write(RC.UC_RISCV_REG_GP, self.sym['__global_pointer$'])
        for i, x in enumerate(a):
            u.reg_write(RC.UC_RISCV_REG_A0 + i, x & 0xFFFFFFFF)
        try:
            u.emu_start(self.sym[fn], 0x1FFF0, count=50_000_000)
        except UcError as e:
            self.st['ours_fault'] += 1
            self.fail('ours_fault', '%s %s pc %08X' % (fn, e, u.reg_read(RC.UC_RISCV_REG_PC)))
            return None
        return u.reg_read(RC.UC_RISCV_REG_A0)

    def ours_block(self):
        return bytes(self.u.mem_read(self.sym['zoom_st'], 0x800)) + bytes(self.u.mem_read(self.sym['zoom_ss'], 0x1000))

    def ours_ramdp(self):
        return bytes(self.u.mem_read(0x02000200, 0x800))

    def set_both(self, block, ramdp):
        self.mu.mem_write(CB, block)
        self.m.ramdp[0x200:0xA00] = ramdp
        self.u.mem_write(self.sym['zoom_st'], block[:0x800])
        self.u.mem_write(self.sym['zoom_ss'], block[0x800:])
        self.u.mem_write(0x02000200, ramdp)

    def compare(self, tag, what, mask=None):
        cb, ob = self.chip_block(), self.ours_block()
        if mask:
            cb = bytes(0 if k in mask else x for k, x in enumerate(cb))
            ob = bytes(0 if k in mask else x for k, x in enumerate(ob))
        if cb != ob:
            k = next(i for i in range(0x1800) if cb[i] != ob[i])
            self.fail(what, '%s block +%04X (%s) chip %02X ours %02X, %d bytes differ' % (
                tag, k, 'stamps' if k < 0x800 else 'source' if k < 0x1000 else 'save', cb[k], ob[k],
                sum(1 for i in range(0x1800) if cb[i] != ob[i])))
            return False
        cr, orr = self.chip_ramdp(), self.ours_ramdp()
        if cr != orr:
            k = next(i for i in range(0x800) if cr[i] != orr[i]) & ~1
            self.fail(what, '%s RAMDP $%04X chip %s ours %s' % (tag, 0x200 + k, cr[k:k + 2].hex(), orr[k:k + 2].hex()))
            return False
        return True


def reach(a):
    """the chip's furthest source byte read and stamp byte written for the F5 words a, and each column's offsets"""
    start, end, step, row = a
    ph = (start >> 1) & 3
    d = (0x400 if ph > 1 else 0) + (start >> 3) * 0x40 + ((start >> 1) & 1)
    acc, rmax, wmax, cols = 0, -1, -1, []
    for _ in range(((end - start) & 0xFFFF) >> 1):
        ao = row * 32 + ((acc >> 1) & ~31)
        acc = (acc + step) & 0xFFFF
        bo = row * 32 + ((acc >> 1) & ~31)
        acc = (acc + step) & 0xFFFF
        rmax, wmax = max(rmax, ao + 31, bo + 31), max(wmax, d + 62)
        cols.append((ao, bo, d))
        d += (1, 0x3FF, 1, -0x3C1)[ph]
        ph = (ph + 1) & 3
    return rmax, wmax, cols


def sweep(L, seed, n):
    r = random.Random(seed)
    sram0 = bytes(L.mu.mem_read(0x20000000, 0x20000))
    for case in range(n):
        k = r.random()
        if k < 0.55:
            s = r.randrange(0, 128)
            a = (s, r.randrange(s, 129), r.randrange(0, 129), r.randrange(0, 64))
        elif k < 0.8:
            s = r.randrange(0, 256)
            a = (s, s + r.randrange(0, 128), r.randrange(0, 1024), r.randrange(0, 128))
        elif k < 0.9:
            a = (r.choice([0, 1, 2, 3, 6, 7, 126, 127, 128]), r.choice([0, 1, 2, 127, 128, 129, 255]),
                 r.choice([0, 1, 31, 32, 63, 64, 65, 127, 128, 0x7FFF, 0xFFFF]), r.choice([0, 1, 62, 63, 64, 65, 127]))
        else:
            s = r.randrange(0, 512)
            a = (s, (s + r.randrange(0, 256)) & 0xFFFF, r.randrange(0, 0x4000), r.randrange(0, 512))
        rmax, wmax, cols = reach(a)
        cl = 'in' if rmax < 0x800 and wmax < 0x800 else 'spill' if rmax < 0x1000 and wmax < 0x1800 else 'out'
        if cl == 'out' and (CB + 0x800 + rmax >= 0x20020000 or CB + wmax >= 0x20020000):
            L.st['skipped: the chip itself would leave its SRAM'] += 1
            continue
        L.st['cases_' + cl] += 1
        L.set_both(bytes(r.randrange(256) for _ in range(0x1800)), bytes(r.randrange(256) for _ in range(0x800)))
        L.mu.mem_write(CZ + 2, struct.pack('<4H', *a))
        L.m.call(F_F5)
        L.u.mem_write(0x8000BF00, struct.pack('<4H', *a))
        if L.call('zoom_rescale', 0x8000BF00) is None:
            continue
        tag = '%s case %d F5 %s' % (cl, case, ','.join('%X' % x for x in a))
        if cl == 'out':
            mask = {d + 2 * i for ao, bo, d in cols if max(ao, bo) + 31 >= 0x1000 for i in range(32) if d + 2 * i < 0x1800}
            nb = len(L.bad)
            if L.compare(tag, 'f5_out', mask):
                L.st['out: equal inside the block'] += 1
            else:
                L.st['out: differ inside the block (B53)'] += 1
                L.st['mismatch_f5_out'] -= 1
                del L.bad[nb:]
            L.mu.mem_write(0x20000000, sram0)
            continue
        if not L.compare(tag, 'f5'):
            continue
        L.m.call(F_COPY)
        L.call('zoom_copyout')
        if not L.compare(tag, 'copyout'):
            continue
        if r.random() < 0.3:
            for f_chip, f_ours in ((F_SAVE, 'job_scale_save'), (F_SETUP, 'job_scale_setup'), (F_RESTORE, 'job_restore')):
                L.m.ramdp[0x200:0xA00] = bytes(r.randrange(256) for _ in range(0x800))
                L.u.mem_write(0x02000200, L.chip_ramdp())
                L.m.call(f_chip)
                L.call(f_ours)
                L.compare(tag, f_ours)
            L.st['cases with save / set-up / restore'] += 1
        L.st['cases_exact'] += 1


def records(path):
    import mmap
    f = open(path, 'rb')
    d = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    o, fr = 0, 0
    while o + 20 <= len(d):
        t, ln, fn = struct.unpack_from('<HHI', d, o)
        po = o + 20
        o = po + ln
        if t == 1:
            fr = fn
        elif t == 2 and ln >= 36:
            wv = struct.unpack_from('<18H', d, po)
            if (wv[0] >> 8) in (0xF4, 0xF5, 0xB6):
                yield fr, wv[0], wv[2:18]


def posts(L, caps):
    def grow(k, v):
        lo, hi = L.rng.get(k, [v, v])
        L.rng[k] = [min(lo, v), max(hi, v)]
    L.u.mem_write(0x02000000, bytes(L.m.ramdp[:0x2000]))
    blk = L.chip_block()
    L.u.mem_write(L.sym['zoom_st'], blk[:0x800])
    L.u.mem_write(L.sym['zoom_ss'], blk[0x800:])
    fl = {'session': 0, 'saved': 0}
    for path in caps:
        name = '/'.join(path.replace('\\', '/').split('/')[-3:-1])
        for f, word, args in records(path):
            hi = word >> 8
            for i, v in enumerate(args):
                L.c.w68(0x1E10 + 2 * i, v)
            L.c.post(word, deep=False)
            for _ in range(400):
                q = bytes(L.mu.mem_read(G_WR, 2))
                if (q[0] ^ q[1]) & 0xF == 0:
                    break
                L.m.run(seconds=0.0005)
            else:
                L.fail('chip_queue', '%s f%d %04X: the chip did not drain its queue' % (name, f, word))
            tag = '%s f%d %04X %s' % (name, f, word, ','.join('%X' % x for x in args[:4]))
            if hi == 0xF4:
                L.st['%s F4' % name] += 1
                src = (args[0] << 16) | args[1]
                if src > 0x800000 or L.u.mem_read(0x04800000 + (src & ~1), 1)[0] not in (0x80, 0x81):
                    L.st['%s F4 refused' % name] += 1
                    continue
                L.u.mem_write(0x8000BF00, struct.pack('<BBBBIBBBBII', 1, 4, 0, 0, 0, 0, 0, 0, 0, src, 0))
                code = L.call('job_unpack', 0x8000BF00)
                if code:
                    L.fail('f4_code', '%s: ours %r' % (tag, code))
                if not fl['saved']:
                    L.call('job_scale_save')
                    fl['saved'] = 1
                L.call('job_scale_setup')
                fl['session'] = 1
                L.compare(tag, 'f4_post')
            elif hi == 0xF5:
                L.st['%s F5' % name] += 1
                if fl['session']:
                    a = tuple(args[:4])
                    for i in range(4):
                        grow('F5 word %d' % i, a[i])
                    rmax, wmax, _ = reach(a)
                    grow('F5 furthest source byte read', rmax)
                    grow('F5 furthest stamp byte written', wmax)
                    L.u.mem_write(0x8000BF00, struct.pack('<4H', *a))
                    L.call('job_rescale', 0x8000BF00)
                    L.st['%s F5 run' % name] += 1
                L.compare(tag, 'f5_post')
            else:
                L.st['%s B6' % name] += 1
                if fl['saved']:
                    L.call('job_restore')
                    fl['saved'] = 0
                fl['session'] = 0
                L.compare(tag, 'b6_post')
            cz = struct.unpack('<7H', bytes(L.mu.mem_read(CZ, 14)))
            if (cz[0] != 0) != bool(fl['session']) or (cz[6] != 0) != bool(fl['saved']):
                L.fail('flags', '%s chip session %d saved %d, ours %d %d' % (tag, cz[0], cz[6], fl['session'], fl['saved']))


def run_one(img, rom, n, seed, caps, quiet=False):
    L = Lock(img, rom)
    t0 = time.time()
    sweep(L, seed, n)
    if caps:                        # the posts on a fresh chip side, as the game finds it after C6 (the sweep leaves
        P = Lock(img, rom)          # random blocks, RAMDP and F5 words in the chip)
        posts(P, caps)
        L.st.update(P.st)
        L.bad += P.bad
        L.rng.update(P.rng)
    fails = sum(v for k, v in L.st.items() if k.startswith('mismatch_')) + L.st['ours_fault']
    if not quiet:
        for k in sorted(L.st):
            print('  %-58s %d' % (k, L.st[k]))
        for k, v in sorted(L.rng.items()):
            print('  range %-52s %s' % (k, v))
        for b in L.bad[:12]:
            print('  BAD ' + b)
        print('  %.1f s' % (time.time() - t0))
    return fails, L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', required=True, help='an image folder (main.elf, main.nm): build/s1/pocket88k/s5release')
    ap.add_argument('--sweep', type=int, default=20000)
    ap.add_argument('--seed', type=int, default=20261028)
    ap.add_argument('--capture', action='append', help='a capture (default: paths.local.json equiv.capture_solo)')
    ap.add_argument('--negative', action='store_true', help='the four planted-bug images must each fail')
    ap.add_argument('--json')
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    loc = json.load(open(lp)) if os.path.exists(lp) else {}
    hd = os.environ.get('PAPRIUM_HARNESS_DIR') or loc.get('harness_dir')
    eq = loc.get('equiv') or {}
    if not hd or not os.path.isdir(hd):
        setup_error('paths.local.json "harness_dir" (the audit harness) missing')
    sys.path.insert(0, hd)
    caps = a.capture or [eq.get('capture_solo')]
    if not eq.get('rom') or not all(c and os.path.isfile(c) for c in caps):
        setup_error('paths.local.json "equiv" needs rom and capture_solo')
    rom = open(eq['rom'], 'rb').read()
    if not os.path.exists(os.path.join(a.build, 'main.elf')):
        setup_error('no image at %s (tools/fwbuild.py s1)' % a.build)
    if not a.negative:
        fails, L = run_one(a.build, rom, a.sweep, a.seed, caps)
        if a.json:
            json.dump({'stats': dict(L.st), 'ranges': L.rng, 'bad': L.bad}, open(a.json, 'w'), indent=1)
        print('RESULT: PASS' if not fails else 'RESULT: FAIL: %d mismatches / faults' % fails)
        return 0 if not fails else 1
    base = os.path.dirname(os.path.normpath(a.build))
    caught = []
    for v in NEG:
        cmd = [sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
               '--out', os.path.dirname(os.path.dirname(base)), '--variant', v]
        rr = subprocess.run(cmd, capture_output=True, text=True)
        if rr.returncode:
            setup_error('building %s failed: %s %s' % (v, rr.stdout[-1500:], rr.stderr[-1500:]))
        fails, L = run_one(os.path.join(base, v), rom, 3000, 7, caps, quiet=True)
        print('  %s: %d mismatches / faults (%s)' % (v, fails, L.bad[0] if L.bad else 'none'))
        caught.append(fails > 0)
    ok = all(caught)
    print('RESULT: PASS (all %d planted bugs caught)' % len(NEG) if ok else
          'RESULT: FAIL: %d of %d planted bugs not caught' % (caught.count(False), len(NEG)))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
