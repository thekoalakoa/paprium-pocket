#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""eeplock.py - test build S3a (a firmware build B Jam tested on his hardware): the saves of a BUILT stage-5 IMAGE
(FW_S5, our own song engine; interim/s1/bodies_s1.c save_boot, job_eep_read, job_eep_write: the cart's own format)
against the cart chip's own save jobs, both in Unicorn (the CPU emulator library).

    python -I -B tests/equiv/eeplock.py --build build/s1/pocket88k/s5release [--fuzz N] [--seed S] [--sav FILE ...]

Sides:
  chip  the cart program in the audit harness (our test harness outside this tree; paths.local.json "harness_dir":
        harness.ChipSide, its boot
        snapshot after C6, its 8 KB I2C EEPROM model): the read job 0x0801A734 and the write job 0x0801A86C called
        directly (the slot id, the cart RAM address 0x68060000 + offset, the key 0x8C543FC4, as the job step passes them);
  ours  the image's code (main.elf / main.nm) in Unicorn RV32 with the board's regions mapped (the ROM's views, the cart
        RAM, the 2 MB workspace, the 8 KB battery save, the register file, WRAM 48 KB): save_boot once (the slot table
        from the ROM: the cart program's packed block unpacked), then job_eep_read / job_eep_write on a job slot in WRAM.
After every job: the return value, the whole 8 KB save == the chip's EEPROM, the cart RAM == the chip's, and the
chip's zoom stamps 0x200111EC (its save scratch, 2 KB) == ours' zoom_st.
Cases: (V) the validator: blank saves (0xFF, 0x00), one copy bad, both bad, a wrong id / magic / XOR, sequence numbers
0, 1, 0xFFFFFFFE, 0xFFFFFFFF and ties, built from the chip's own written copies; (S) a run of writes and reads of
every id (1-4, 9, and 0 / 5 / 255, which the table lacks); (F) --fuzz N random saves and jobs; (I) the one-time
import: a 0.2.x save (ids 4 at 0x000, 1-3 at 0x400 / 0x600 / 0x800, plain; synthetic, or each --sav FILE, a Pocket .sav
read only) through ours' save_boot, against the chip's write job making the same records on a blank EEPROM: the first
copies equal the chip's and every id reads back the chip's bytes; a second save_boot (the next boot) changes nothing,
and a blank save is left as it is. (N) the note table's tail: after save_boot, ours' song_note_tail == the chip's 12
bytes after its note table (read in the comparison harness), and ours' note lookup == the chip's own
for every pitch 0..1807 (the top ones read the tail). Exit 0 = PASS, 1 = FAIL, 2 = setup error. The last line printed is 'RESULT: ...'."""
import argparse, json, os, random, struct, sys
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
F_READ, F_WRITE = 0x0801A734, 0x0801A86C
CHIP_RAMDP, CB = 0x68060000, 0x200111EC
KEY = 0x8C543FC4
FLASH, FLASH_BV, RAMDP, SDRAM, BRAM, FREG = 0x04000000, 0x04800000, 0x02000000, 0x03000000, 0x05000000, 0x0B000000
JOB = 0x8000BE00                 # ours: a job slot (20 B, the chip's layout from +0x14) in free WRAM
LAYOUT = {}                      # id -> (first copy, second copy, size): read from the chip's own table in the harness
                                 # (its flash at 0x0802E2A4) to place the test's corruptions; ours reads its own from the
                                 # player's ROM; this file holds none of it


def setup_error(msg):
    print('RESULT: setup error: ' + msg)
    sys.exit(2)


class Chip:
    def __init__(self):
        from harness import ChipSide
        self.c = ChipSide()
        self.m = self.c.m
        tab = bytes(self.m.mu.mem_read(0x0802E2A4, 8 * 32))
        for i in range(32):
            sid, off, n = struct.unpack_from('<HHH', tab, 8 * i)
            if not sid:
                break
            LAYOUT.setdefault(sid, []).append((off, n))
        for sid in list(LAYOUT):
            (a, n), (b, _) = LAYOUT[sid][:2]
            LAYOUT[sid] = (a, b, n)

    def load(self, eep, ram):
        self.m.eeprom[:] = eep
        self.m.ramdp[:] = ram

    def job(self, write, sid, off):
        return self.m.call(F_WRITE if write else F_READ, (sid, CHIP_RAMDP + (off & ~1), KEY)) & 0xFFFFFFFF

    def state(self):
        return bytes(self.m.eeprom), bytes(self.m.ramdp), bytes(self.m.mu.mem_read(CB, 0x800))


class Ours:
    def __init__(self, img, rom):
        from unicorn import Uc, UC_ARCH_RISCV, UC_MODE_RISCV32
        E = open(os.path.join(img, 'main.elf'), 'rb').read()
        self.sym = {}
        for ln in open(os.path.join(img, 'main.nm')):
            p = ln.split()
            if len(p) >= 3:
                self.sym[p[-1]] = int(p[0], 16)
        for need in ('save_boot', 'job_eep_read', 'job_eep_write', 'zoom_st', '__global_pointer$'):
            if need not in self.sym:
                setup_error('symbol %s missing in %s' % (need, img))
        u = self.u = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
        u.mem_map(0x00000000, 0x20000)
        u.mem_map(0x80000000, 0xC000)
        for base, n in ((RAMDP, 0x2000), (SDRAM, 0x200000), (BRAM, 0x2000), (FREG, 0x1000), (0x01000000, 0x1000)):
            u.mem_map(base, n)
        rom = rom + bytes(0x800000 - len(rom)) if len(rom) < 0x800000 else rom[:0x800000]
        u.mem_map(FLASH, 0x800000)
        u.mem_map(FLASH_BV, 0x800000)
        sw = bytearray(rom)
        sw[0::2], sw[1::2] = rom[1::2], rom[0::2]
        u.mem_write(FLASH, bytes(sw))
        u.mem_write(FLASH_BV, rom)
        phoff, = struct.unpack_from('<I', E, 28)
        phsz, phn = struct.unpack_from('<HH', E, 42)
        for i in range(phn):
            t, off, va, pa, fs, ms, fl, al = struct.unpack_from('<8I', E, phoff + i * phsz)
            if t == 1 and fs and (va < 0x20000 or 0x80000000 <= va < 0x8000C000):
                u.mem_write(va, E[off:off + fs])
        u.mem_write(0x1FFF0, struct.pack('<I', 0x0000006F))

    def call(self, fn, *a):
        from unicorn import riscv_const as RC
        u = self.u
        u.reg_write(RC.UC_RISCV_REG_SP, 0x8000BDF0)
        u.reg_write(RC.UC_RISCV_REG_RA, 0x1FFF0)
        u.reg_write(RC.UC_RISCV_REG_GP, self.sym['__global_pointer$'])
        for i, x in enumerate(a):
            u.reg_write(RC.UC_RISCV_REG_A0 + i, x & 0xFFFFFFFF)
        u.emu_start(self.sym[fn], 0x1FFF0, count=400_000_000)
        return u.reg_read(RC.UC_RISCV_REG_A0)

    def load(self, eep, ram):
        self.u.mem_write(BRAM, bytes(eep))
        self.u.mem_write(RAMDP, bytes(ram))

    def boot(self):
        return self.call('save_boot')

    def note_freq(self, p):
        return self.call('note_freq', p) & 0xFFFF

    def job(self, write, sid, off):
        slot = bytearray(20)
        slot[0] = 1                                         # +0x14 fail_en
        slot[1] = 7 if write else 5                         # +0x15 type
        slot[2] = sid & 0xFF                                # +0x16 E0's id
        struct.pack_into('<I', slot, 4, off)                # +0x18 DF's destination
        slot[8] = sid & 0xFF                                # +0x1C DF's id
        struct.pack_into('<I', slot, 12, off)               # +0x20 E0's source
        struct.pack_into('<I', slot, 16, KEY)               # +0x24 the key
        self.u.mem_write(JOB, bytes(slot))
        return self.call('job_eep_write' if write else 'job_eep_read', JOB) & 0xFFFFFFFF

    def state(self):
        u = self.u
        return bytes(u.mem_read(BRAM, 0x2000)), bytes(u.mem_read(RAMDP, 0x2000)), bytes(u.mem_read(self.sym['zoom_st'], 0x800))


class Lock:
    def __init__(self, chip, ours):
        self.c, self.o, self.n, self.bad = chip, ours, 0, []

    def load(self, eep, ram):
        self.c.load(eep, ram)
        self.o.load(eep, ram)
        # the scratch: ours' zoom stamps := the chip's (the test's own chip-side copies, chip_copy, wrote the chip's)
        self.o.u.mem_write(self.o.sym['zoom_st'], bytes(self.c.m.mu.mem_read(CB, 0x800)))

    def job(self, tag, write, sid, off):
        a, b = self.c.job(write, sid, off), self.o.job(write, sid, off)
        ce, cr, cz = self.c.state()
        oe, orr, oz = self.o.state()
        self.n += 1
        d = []
        if (a != 0) != (b != 0):
            d.append('result chip %d ours %d' % (a, b))
        if ce != oe:
            k = [i for i in range(0x2000) if ce[i] != oe[i]]
            d.append('save: %d bytes differ from %#x' % (len(k), k[0]))
        if cr[:0x1FE0] != orr[:0x1FE0]:
            k = [i for i in range(0x1FE0) if cr[i] != orr[i]]
            d.append('cart RAM: %d bytes differ from %#x' % (len(k), k[0]))
        if cz != oz:
            k = [i for i in range(0x800) if cz[i] != oz[i]]
            d.append('zoom stamps (the scratch): %d bytes differ from %#x' % (len(k), k[0]))
        if d and len(self.bad) < 30:
            self.bad.append('%s %s id %d at %#x: %s' % (tag, 'E0' if write else 'DF', sid, off, '; '.join(d)))
        return a, not d


def chip_copy(lock, sid, payload, eep=None):
    """the chip's own copy of payload for id sid (its write job on a blank save); returns the bytes of its first copy"""
    c = lock.c
    ram = bytearray(0x2000)
    ram[0x100:0x100 + len(payload)] = payload
    c.load(bytes(eep) if eep else bytes([0xFF]) * 0x2000, bytes(ram))
    c.job(True, sid, 0x100)
    a, b, n = LAYOUT[sid]
    return bytes(c.m.eeprom[a:a + n])


def reseal(rec, seq=None, sid=None, magic=None, fix_xor=True):
    r = bytearray(rec)
    n = len(r)
    if seq is not None:
        struct.pack_into('<I', r, n - 8, seq & 0xFFFFFFFF)
    if sid is not None:
        r[n - 4] = sid & 0xFF
    if magic is not None:
        struct.pack_into('<H', r, n - 2, magic)
    if fix_xor:
        r[n - 3] = 0
        x = 0
        for v in r:
            x ^= v
        r[n - 3] = x
    return bytes(r)


def case_v(lock, rng):
    """the validator and both jobs' choice of copy"""
    out = []
    for fill in (0xFF, 0x00):
        lock.load(bytes([fill]) * 0x2000, bytes(0x2000))
        for sid in (1, 2, 3, 4, 9, 5):
            out.append(lock.job('V blank%02X' % fill, False, sid, 0x1C00))
        lock.load(bytes([fill]) * 0x2000, bytes(rng.randrange(256) for _ in range(0x2000)))
        for sid in (1, 4, 9):
            out.append(lock.job('V blank%02X' % fill, True, sid, 0x0200 + 0x10 * sid))
            out.append(lock.job('V blank%02X' % fill, False, sid, 0x1800))
            out.append(lock.job('V blank%02X' % fill, True, sid, 0x0300))
            out.append(lock.job('V blank%02X' % fill, False, sid, 0x1900))
    for sid in (1, 4, 9):
        a, b, n = LAYOUT[sid]
        p1 = bytes(rng.randrange(256) for _ in range(n))
        p2 = bytes(rng.randrange(256) for _ in range(n))
        r1, r2 = chip_copy(lock, sid, p1), chip_copy(lock, sid, p2)
        forms = [('both ok 2/3', reseal(r1, 2), reseal(r2, 3)), ('both ok 3/2', reseal(r1, 3), reseal(r2, 2)),
                 ('tie 5/5', reseal(r1, 5), reseal(r2, 5)), ('top FFFFFFFE/1', reseal(r1, 0xFFFFFFFE), reseal(r2, 1)),
                 ('near top FFFFFFFD/FFFFFFFE', reseal(r1, 0xFFFFFFFD), reseal(r2, 0xFFFFFFFE)),
                 ('seq 0 / ok', reseal(r1, 0), reseal(r2, 7)), ('seq FFFFFFFF / ok', reseal(r1, 0xFFFFFFFF), reseal(r2, 7)),
                 ('bad xor / ok', reseal(r1, 4, fix_xor=False)[:-3] + bytes([r1[-3] ^ 1]) + r1[-2:], reseal(r2, 3)),
                 ('wrong id / ok', reseal(r1, 4, sid=sid + 1), reseal(r2, 3)),
                 ('wrong magic / ok', reseal(r1, 4, magic=0x3FC3), reseal(r2, 3)),
                 ('ok / both bad', reseal(r1, 6), reseal(r2, 9, magic=0)), ('both bad', reseal(r1, 0), reseal(r2, 2, sid=0))]
        for tag, x, y in forms:
            for write in (False, True):
                eep = bytearray([0xFF]) * 0x2000
                eep[a:a + n], eep[b:b + n] = x, y
                lock.load(bytes(eep), bytes(rng.randrange(256) for _ in range(0x2000)))
                out.append(lock.job('V %s' % tag, write, sid, 0x0400))
                out.append(lock.job('V %s then' % tag, False, sid, 0x1A00))
    return out


def case_s(lock, rng):
    """a run of writes and reads of every id, the save kept between jobs"""
    out = []
    lock.load(bytes([0xFF]) * 0x2000, bytes(0x2000))
    for k in range(60):
        sid = rng.choice((1, 2, 3, 4, 9, 0, 5, 255))
        off = rng.randrange(0, 0x1DFF)
        if rng.random() < 0.5:
            ram = bytes(rng.randrange(256) for _ in range(0x2000))
            lock.c.m.ramdp[:] = ram
            lock.o.u.mem_write(RAMDP, ram)
        out.append(lock.job('S run %d' % k, rng.random() < 0.5, sid, off))
    return out


def case_f(lock, rng, n):
    out = []
    for k in range(n):
        eep = bytearray(rng.randrange(256) for _ in range(0x2000))
        sid = rng.choice((1, 2, 3, 4, 9))
        a, b, sz = LAYOUT[sid]
        if rng.random() < 0.7:                              # a chip-made copy in one or both places
            rec = chip_copy(lock, sid, bytes(rng.randrange(256) for _ in range(sz)))
            if rng.random() < 0.6:
                eep[a:a + sz] = reseal(rec, rng.choice((1, 2, 3, 0xFFFFFFFE, rng.randrange(1, 1 << 32))))
            if rng.random() < 0.6:
                eep[b:b + sz] = reseal(rec, rng.choice((1, 2, 3, 0xFFFFFFFD, rng.randrange(1, 1 << 32))))
        lock.load(bytes(eep), bytes(rng.randrange(256) for _ in range(0x2000)))
        out.append(lock.job('F %d' % k, rng.random() < 0.5, sid, rng.randrange(0, 0x1E00)))
    return out


def old_save(rng):
    """a synthetic 0.2.x save: id 4's 0x200 B at 0x000, ids 1-3's 0x100 B at 0x400 / 0x600 / 0x800 (id 2 left blank)"""
    s = bytearray(0x2000)
    s[0x000:0x200] = bytes(rng.randrange(256) for _ in range(0x200))
    s[0x400:0x500] = bytes(rng.randrange(256) for _ in range(0x100))
    s[0x800:0x900] = bytes(rng.randrange(256) for _ in range(0x100))
    s[0x200:0x400] = bytes(rng.randrange(256) for _ in range(0x200))       # 0.2.x left these alone: kept as they are
    return bytes(s)


def case_i(lock, saves):
    """the one-time import: ours' save_boot on a 0.2.x save against the chip's write job making the same records on a
    blank EEPROM. Checked: each non-blank 0.2.x slot's first copy == the chip's, every byte outside the imported copies
    left as it was (a blank slot too), the next boot changes nothing, and each id's read gives the chip's cart RAM bytes
    (the save outside the first copies differs by design: the chip's starts blank, ours keeps the 0.2.x bytes)"""
    out = []
    o, c = lock.o, lock.c
    for tag, s in saves:
        o.load(s, bytes(0x2000))
        o.boot()
        e1 = bytes(o.u.mem_read(BRAM, 0x2000))
        o.boot()                                            # the next boot (a Soft Reset, the Quit's reboot)
        e2 = bytes(o.u.mem_read(BRAM, 0x2000))
        nextboot = e1 == e2
        chip_e = bytearray([0xFF]) * 0x2000
        took = []
        for sid in (4, 1, 2, 3):
            a, b, n = LAYOUT[sid]
            blk = s[a:a + n]
            if all(x == 0 for x in blk) or all(x == 0xFF for x in blk):
                continue
            chip_copy(lock, sid, blk, eep=chip_e)
            chip_e[:] = c.m.eeprom
            took.append(sid)
        firsts = all(e1[LAYOUT[k][0]:LAYOUT[k][0] + LAYOUT[k][2]] == bytes(chip_e[LAYOUT[k][0]:LAYOUT[k][0] + LAYOUT[k][2]])
                     for k in took)
        mask = bytearray(0x2000)
        for k in took:
            mask[LAYOUT[k][0]:LAYOUT[k][0] + LAYOUT[k][2]] = bytes([1]) * LAYOUT[k][2]
        rest = all(e1[i] == s[i] for i in range(0x2000) if not mask[i])
        reads = []
        for sid in (1, 2, 3, 4):
            c.load(bytes(chip_e), bytes(0x2000))
            o.load(e1, bytes(0x2000))
            ra, rb = c.job(False, sid, 0x1000), o.job(False, sid, 0x1000)
            cr, orr = bytes(c.m.ramdp[:0x1FE0]), bytes(o.u.mem_read(RAMDP, 0x1FE0))
            reads.append((ra != 0) == (rb != 0) and cr == orr)
        ok = nextboot and firsts and rest and all(reads)
        msg = ('I %s: imported ids %s; their first copies equal the chip ones %s, the rest of the save kept %s, the next '
               'boot changed nothing %s, reads of ids 1-4 equal the chip ones %s' % (tag, took, firsts, rest, nextboot, reads))
        if not ok:
            lock.bad.append(msg)
        print(('PASS ' if ok else 'FAIL ') + msg, flush=True)
        out.append((1, ok))
    return out


F_NOTE_FREQ, CHIP_NOTE_TAIL = 0x0801AB10, 0x0802E430


def case_n(lock):
    """(N): after save_boot (done by the caller), ours' note tail == the chip's flash bytes, and the note lookup at
    every pitch whose reads stay inside the table and its 12-byte tail == the chip's"""
    o, c = lock.o, lock.c
    lock.o.load(bytes([0xFF]) * 0x2000, bytes(0x2000))
    o.boot()
    tail = bytes(o.u.mem_read(o.sym['song_note_tail'], 12))
    ok = tail == bytes(c.m.mu.mem_read(CHIP_NOTE_TAIL, 12))
    if not ok:
        lock.bad.append('the note tail differs from the chip\'s 12 bytes after its note table')
    n = 0
    for p in range(0, 113 * 16):
        a, b = o.note_freq(p), c.m.call(F_NOTE_FREQ, (p,)) & 0xFFFF
        n += 1
        if a != b:
            ok = False
            if len(lock.bad) < 20:
                lock.bad.append('note_freq(%d): ours %d, the chip %d' % (p, a, b))
    return ok, n


def sav_mcu(path):
    raw = open(path, 'rb').read()
    b = bytearray(raw)
    b[0::2], b[1::2] = raw[1::2], raw[0::2]                  # the .sav swaps each 16-bit half
    b = bytes(b[:0x2000]) + bytes(max(0, 0x2000 - len(b)))
    return b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket88k', 's5release'))
    ap.add_argument('--fuzz', type=int, default=300)
    ap.add_argument('--seed', type=int, default=20261029)
    ap.add_argument('--sav', action='append', default=[])
    ap.add_argument('--negative', action='store_true')
    a = ap.parse_args()
    lp = os.path.join(ROOT, 'paths.local.json')
    loc = json.load(open(lp)) if os.path.exists(lp) else {}
    hd = os.environ.get('PAPRIUM_HARNESS_DIR') or loc.get('harness_dir')
    romf = (loc.get('equiv') or {}).get('rom') or (loc.get('refs') or {}).get('rom')
    if not hd or not os.path.isdir(hd) or not romf or not os.path.exists(romf):
        setup_error('paths.local.json "harness_dir" and the ROM ("equiv" rom)')
    if not os.path.exists(os.path.join(a.build, 'main.nm')):
        setup_error('no built image at %s' % a.build)
    sys.path.insert(0, hd)
    rom = open(romf, 'rb').read()
    if a.negative:                                      # the planted image must differ from the chip
        import subprocess
        base = os.path.dirname(os.path.normpath(a.build))
        rr = subprocess.run([sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
                             '--out', os.path.dirname(os.path.dirname(base)), '--variant', 's5release_bug_eep'],
                            capture_output=True, text=True)
        if rr.returncode:
            setup_error('building s5release_bug_eep failed:\n%s' % (rr.stdout + rr.stderr)[-2000:])
        lock = Lock(Chip(), Ours(os.path.join(base, 's5release_bug_eep'), rom))
        lock.o.load(bytes([0xFF]) * 0x2000, bytes(0x2000))
        lock.o.boot()
        res = case_v(lock, random.Random(a.seed)) + case_s(lock, random.Random(a.seed))
        n = sum(1 for x in res if not x[1])
        print('%-4s s5release_bug_eep: %d of %d jobs differ from the chip%s' % ('PASS' if n else 'FAIL', n, len(res),
                                                                           (' (e.g. %s)' % lock.bad[0]) if lock.bad else ''))
        print('RESULT: %s' % ('PASS' if n else 'FAIL'))
        sys.exit(0 if n else 1)
    rng = random.Random(a.seed)
    lock = Lock(Chip(), Ours(a.build, rom))
    lock.o.load(bytes([0xFF]) * 0x2000, bytes(0x2000))
    lock.o.boot()
    n_tab = None
    if 'eep_n' in lock.o.sym:
        n_tab = struct.unpack('<I', bytes(lock.o.u.mem_read(lock.o.sym['eep_n'], 4)))[0]
    print('eeplock %s: ours read %s copies from the ROM\'s slot table' % (os.path.basename(os.path.normpath(a.build)), n_tab))
    res = case_v(lock, rng)
    nv = len(res)
    res += case_s(lock, rng)
    ns = len(res) - nv
    res += case_f(lock, rng, a.fuzz)
    saves = [('synthetic %d' % k, old_save(rng)) for k in range(3)] + [('blank 0x00', bytes(0x2000))]
    saves += [('sav %s' % os.path.basename(p), sav_mcu(p)) for p in a.sav]
    ni = len(res)
    res += case_i(lock, saves)
    nt_ok, nt_n = case_n(lock)
    bad = [x for x in res if not x[1]]
    for b in lock.bad:
        print('DIFFER ' + b)
    print('eeplock: %d validator cases, %d run jobs, %d fuzz jobs, %d import checks; %d jobs succeeded on the chip; %d '
          'differ' % (nv, ns, a.fuzz, len(res) - ni, sum(1 for x in res if x[0]), len(bad)))
    print('eeplock: the note table\'s tail read from the ROM == the chip\'s 12 bytes, note_freq == the chip\'s 0x0801AB10 '
          'at %d pitches: %s' % (nt_n, 'equal' if nt_ok else 'DIFFERENT'))
    ok = not bad and not lock.bad and n_tab == 10 and nt_ok
    print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
