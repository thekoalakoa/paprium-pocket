#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""cache4b.py - the boot cache of test build 4b (board/pocket/boot: the IROM stub boot_cache.c and the WRAM boot overlay
c4b_ovl.c with core/wavpack, the WavPack library the chip also uses; MCU interface v1.3 section 21.1) on RV32: the real
TEST (and RELEASE) image on the board model of test build 4a, the sound-cache probe build (tests/equiv/rtlmodel.py
v1.3), boot by boot to the 68000's release, the save RAM and the CRAM carried between boots as the Pocket carries them
(a Quit = a Soft Reset: the power-on domain kept; a power-on = a new board: the .sav and the cache file loaded). The
ROM is paths.local.json "refs" "rom" (read in place). Test builds 4, 4a, 4b and 5 are the firmware builds B Jam ran on
his hardware (see rtlmodel.py); B1-B17 and R below are this rig's cases.

  B1  power-on, no file, the CRAM random (another core's leftovers): FIRST; THE BANK: CRAM [0x100, 0x152100) = the
      chip's bank (the cart-engine runner's after C6: the whole region, its tail included), decoded by the image's own
      code; the header (magic, format, sizes,
      samples 1,379,262, the stream ROM 0x1A0010 / 781,460 B / 32 blocks, the ROM key, the bank CRC-32, its own CRC);
      the order (the old magic cleared first, the magic written last of all the image's stores; CACHE last: written
      once, after every CRAM store of the boot, the SFX copy's included, counted in event order, not model time);
      the SFX bank in CRAM 0x200000 = the ROM's 68000 words 0x25ECA4-0x2E5BCF as little-endian halfwords; the bar on
      (only for the unpack: its stores made with EN, the SFX copy's without), rising, EN = 0 at the release; the
      record (debug save version 8, tools/dbgsave.py); the generated WavPack tables
      (read from the overlay's scratch at the decoder's open) right in exact arithmetic; the stack the boot
      path uses (measured here: every store above the overlay's stack-floor scratch).
  B2  a Soft Reset (the Quit's reboot): WARM: no CRAM store, no CACHE write, BAR only written 0; B1 carried.
  B3  power-on with B1's file loaded: PASS: no store into the image, the SFX bank copied, then CACHE (last); the bar
      never lit (21.2: the file's check runs dark); the record PASS.
  B4  the file with one bank byte flipped (block 15's samples): BANK (first wrong block 15) -> unpacked -> the bank.
  B4t the file with one tail byte flipped: BANK (the tail) -> unpacked.   B4d one directory byte: BANK block 0.
  B5  the TEST-pattern file of test build 4a (md5 c5f245e1, on
  B Jam's SD card): HDR (the magic) -> unpacked -> the bank.
  B6  a short file (CACHE_LOADED 0x151100): SIZE -> unpacked.   B7 CRAM writes lost in the load: LOST -> unpacked.
  B8  the header's CRC broken: HDR (its CRC) -> unpacked.   B9 a header for another stream (its key, CRC made good):
      KEY -> unpacked.   B10 no file but the CRAM still holds B1's image (a review finding): FIRST -> unpacked.
  B11 a reset in the middle of the unpack (the stub re-enters the overlay: crt0 has not run): the next boot FIRST,
      unpacked whole; B11b the same with B9's file loaded (it fails its check, so the boot unpacks): the next boot HDR
      (the old magic was cleared before the unpack), unpacked whole.
  B12 a ROM whose stream has one byte wrong (the decoder's block CRC fails): FIRST + FAIL, no header, no CACHE; then a
      Soft Reset: GONE (crt0 overwrote the overlay): no CRAM store, no CACHE write.   B12b the overlay's bytes changed
      in WRAM before the power-on (an unused string): the stub refuses it (GONE), nothing done.
  B13 the MCU-only restart (crt0 again, the RTL state kept: the cart's 68000-reset analogue, docs/ALLOWLIST.md row B17)
      after B1: WARM, nothing touched.   B14 the history keeps 5 (more Soft Resets).   B15 a 4 KB save RAM: FIRST, the
      bank, the save untouched (a stage-5 image converts a 0.2.x save once, since test build S3a: only the four first
      copies of ids 1-4 change, each to the cart's format, and the next boot changes nothing).
      B16 crt0's checks: a v1.2 board stops 0xC2, a v1.3 board without CACHE stops 0xC3, before any
      XLINK access.
  B17 a reset inside the SFX copy (after 50,000 of its 138,187 stores) of a boot with B1's file: CACHE not yet
      written, so the next boot is PASS again and copies the bank whole, CACHE last (a WARM boot over a half bank is
      the fault test build 4b's first order had); B17b the same on a first boot (no file): the next boot FIRST, the
      bank unpacked whole again (no file loaded: the CRAM's image is not trusted, a review finding), the SFX bank whole.
  R   the RELEASE image: B1 (the same bank, header, CACHE, SFX copy; no debug record), B2 WARM, B3 PASS.
Every boot also runs under the model's rule that no CRAM store lands in the cache image while XLINK CACHE.VALID = 1
(docs/MCU_INTERFACE.md section 3.9: the Pocket may be reading it back): a violation fails the case's 'VALID write'.
Every unpacking boot (B1, B4-B11, B17b) also runs the bar checks (a problem a review of test build 4b found: lit only
from the unpack's start, so the loaded file's check before a rejection runs dark: 'bar unpack only').
Since test build 5 (--build of a stage-5 image, s5test, our own song engine; its RELEASE twin s5release; stage numbers
are the steps of the 0.3.0 work, README.md "Terms", and the stage-1 images are the FW_S1 builds without the song
engine): the same cases on test build 5's board model
(rtlmodel's default for an image that links the stage-5 engine: FEAT CACHE, BAR, SYNTH, GS3, IROM 88), plus the
synth's output curve: on every boot that unpacks or keeps the file (B1, B3, B4-B11, B17) CRAM CURVE 0x194000-0x19BFFF
= core/tables/gen_chip_tables.py curve_full() (equal to the cart chip's curve),
its 16,384 halfword stores before CACHE (event order) and C4B_F_CURVE in the record ('curve'); a warm boot writes none
of it (B2, B13); the debug record is version 10 (from test build S3a on: the boot cache's history is no longer in it,
so the boot's own record c4b_rec is checked in WRAM only); B16: crt0 refuses test build 4's board, test build 4a's
board (FEAT 0x0048_001B),
a FEAT without SYNTH and an IROM of 72 KB.
--negative: the planted images test_bug_c4b1..13 (fwbuild.json) must each fail, in the check named for it (NEG below);
with a stage-5 --build, also s5test_bug_c5a..c (NEG5: the curve one code off, the curve not written, crt0 taking test
build 4a's FEAT bits).
Exit 0 = PASS, 1 = FAIL, 2 = setup error. What this rig measures, it measures in the model (a model written from the
documents; its times are not the hardware's: a cost script outside this tree estimates them, and the TEST record
measures them on the Pocket)."""
import argparse, decimal, hashlib, json, os, struct, subprocess, sys, zlib
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'core', 'tables'))
import gen_chip_tables   # noqa: E402
import dbgsave   # noqa: E402
import rtlmodel   # noqa: E402
from rtlmodel import Board, Stop, CRAM, CACHE_VALID, BAR_EN, BAR_PX, WRAM   # noqa: E402
from unicorn import UC_HOOK_MEM_WRITE   # noqa: E402
from unicorn import riscv_const as RC   # noqa: E402

BYTES, BANK, HDR = 0x152100, 0x152000, 0x100
BANK_MD5 = '6d994df504f6046c6a28be61500c00d0'     # the cart-music runner's bank after C6
                                                  # (from our design notes for test build 4b's boot cache)
SAMPLES, STREAM, STREAM_BYTES, BLOCKS = 1379262, 0x1A0010, 781460, 32
SFX_LO, SFX_HI = 0x25ECA4, 0x2E5BD0
SFX_CRAM, SFX_ROOM = 0x200000, 0x90000                 # MCU_INTERFACE.md 3.8 SFXBANK
SFX_CUT = 50000                                         # B17: the reset after this many of the copy's 138,187 stores
MAGIC0, MAGIC1 = 0x52504150, 0x31444E53
KIND = {'WARM': 1, 'FIRST': 2, 'PASS': 3, 'HDR': 4, 'KEY': 5, 'BANK': 6, 'SIZE': 7, 'LOST': 8, 'GONE': 9, 'NOROM': 10}
F = dict(CACHE_SET=1 << 8, UNPACKED=1 << 9, HDR_WRITTEN=1 << 10, FAIL=1 << 11, SFX=1 << 12, BAR_OFF=1 << 13,
         BAR_SEEN=1 << 14, CRCERR=1 << 15)
STOP_IFACE, STOP_FEAT = 0xC2, 0xC3
NEG = {1: ('B4', 'kind'), 2: ('B1', 'kind'), 3: ('B1', 'kind'), 4: ('B6', 'kind'), 5: ('B1', 'magic last'),
       6: ('B9', 'kind'), 7: ('B1', 'bank'), 8: ('B1', 'bar off'), 9: ('B12b', 'kind'), 10: ('B2', 'kind'),
       11: ('B1', 'VALID write'), 12: ('B1', 'CACHE last'), 13: ('B3', 'bar unpack only')}
NEG5 = {'s5test_bug_c5a': ('B1', 'curve'), 's5test_bug_c5b': ('B1', 'curve'), 's5test_bug_c5c': ('B16', 'card 4a board (s5test_bug_c5c)')}
CURVE_LO, CURVE_N = 0x194000, 16384                   # MCU_INTERFACE v1.3 3.8: the curve in CURVE_WIN (index 0 of 16,384)
F_CURVE = 1 << 27                                       # board/pocket/boot/c4b.h C4B_F_CURVE (since test build 5)
FEAT_4A, FEAT_5 = rtlmodel.FEAT_4A, rtlmodel.FEAT_5
# (test build 4b's repair of 2026-10-22: 11 = CACHE before the header, caught by the model's rule that no image store
# lands while CACHE.VALID = 1; 12 = the SFX copy after CACHE (the first commit's order), caught by the event-order
# check; 13 = the bar lit during a loaded file's check. The repair's 'CACHE last' replaces 'CACHE after', which compared
# model times that do not move inside run_to('brd_boot') and so could not fail)
C4A_MAGIC, C4A_MUL, C4A_ADD = 0x41344350, 0x2B5D1C93, 0xC4A0C4A0


def c4a_image():
    """test build 4a's TEST pattern file (board/pocket/s1_cache4a.h in that build's tree): 4 header words, then
    k * MUL + ADD"""
    w = [C4A_MAGIC, BYTES, 1, ~(C4A_MAGIC ^ BYTES ^ 1) & 0xFFFFFFFF] + \
        [(k * C4A_MUL + C4A_ADD) & 0xFFFFFFFF for k in range(4, BYTES // 4)]
    return struct.pack('<%dI' % (BYTES // 4), *w)


def sav_of(save):
    b = bytes(save)
    s = bytearray(len(b))
    s[0::2], s[1::2] = b[1::2], b[0::2]
    return bytes(s)


def tables_formula():
    D = decimal.Decimal
    decimal.getcontext().prec = 60

    def tz1(i):
        c = 0
        while i & 1:
            c, i = c + 1, i >> 1
        return c
    half = decimal.ROUND_HALF_UP
    return dict(nbits_table=bytes(i.bit_length() for i in range(256)), ones_count_table=bytes(tz1(i) for i in range(256)),
                exp2_table=bytes(int((D(2) ** (D(i) / 256) * 256).to_integral_value(rounding=half)) - 256 for i in range(256)),
                log2_table=bytes(int(((1 + D(i) / 256).ln() / D(2).ln() * 256).to_integral_value(rounding=half))
                                 for i in range(256)))


def ovl_syms(build):
    s = {}
    for ln in open(os.path.join(build, 'ovl', 'ovl.nm')):
        p = ln.split()
        if len(p) >= 3:
            s[p[-1]] = int(p[0], 16)
    return s


def is_s5(build):
    """a stage-5 image (it links the engine queue: rtlmodel's synth board)"""
    return 'song_run_one' in rtlmodel.nm(os.path.join(build, 'main.nm'))


def twin_of(build):
    """the RELEASE twin of a TEST build folder (test -> release, s5test -> s5release)"""
    return os.path.join(os.path.dirname(build), 's5release' if os.path.basename(build).startswith('s5') else 'release')


class Rig:
    def __init__(self, build, rom, only=None):
        self.build, self.rom, self.only = build, rom, only      # only: B1, B2 and that one case (the negative runs)
        self.fails, self.n = [], 0
        self.osym = ovl_syms(build)
        self.s5 = is_s5(build)                                  # stage 5: the curve, test build
                                                                # 5's board, record version 10
        self.ver = 10 if self.s5 else 8
        self.curve = b''.join(struct.pack('<H', v) for v in gen_chip_tables.curve_full(gen_chip_tables.curve_knee()))

    def chk(self, case, name, ok, info=''):
        self.n += 1
        if not ok:
            self.fails.append((case, name))
        print('%-4s %-4s %s %s' % ('PASS' if ok else 'FAIL', case, name, info), flush=True)
        return ok

    def board(self, build=None, rom=None, **k):
        k.setdefault('cram_watch', True)
        k.setdefault('cache', 0)                # a real power-on: XLINK CACHE 0 (rtlmodel's default is the warm path)
        return Board(build or self.build, rom if rom is not None else self.rom, **k)

    def boot(self, b, case='-', limit=400000, crt0=900000000):
        """crt0 (the boot cache in it) to brd_boot, then until the 68000's release (HOLD cleared); (True, None) or
        (False, boot record). A model violation is a failed check of the case: 'VALID write' for a CRAM store into the
        image while CACHE.VALID = 1 (MCU_INTERFACE.md 3.9), else 'no model violation'"""
        try:
            if not b.run_to('brd_boot', crt0):
                return False, [b.rd32('s1_boot_rec', k) for k in range(4)]
            n = 0
            while b.ctrl & 1:
                b.take()
                b.step(400)
                n += 1
                if n > limit:
                    return False, [b.rd32('s1_boot_rec', k) for k in range(4)]
        except Stop:
            v = '; '.join(b.violations[:2])
            self.chk(case, 'VALID write' if 'CACHE.VALID' in v else 'no model violation', False, v)
            return False, None
        return True, None

    def rec_words(self, b):
        return [b.rd32('c4b_rec', k) for k in range(16)]

    def record(self, b, case, test=True):
        rec, why = dbgsave.decode(sav_of(b.save))
        if not test:
            return self.chk(case, 'no debug record', rec is None, why or 'a record'), None
        if self.s5:                             # from test build S3a on: version 10 keeps no boot-cache block (the
                                                # record checks of the cache's history stay with the stage-1 images)
            self.chk(case, 'record', rec is not None and rec['head']['version'] == self.ver and 'cache' not in rec,
                     why or ('v%s, blocks %s' % (rec and rec['head']['version'], sorted(rec or {}))))
            return rec, None
        if not self.chk(case, 'record', rec is not None and rec['head']['version'] == self.ver and 'cache' in rec,
                        why or ('v%s' % (rec and rec['head']['version']))):
            return None, None
        return rec, rec['cache']

    def kind_ok(self, case, w, kind, flags_set=0, flags_clear=0, info=''):
        ok = w[0] & 0xFF == KIND[kind] and (w[0] & flags_set) == flags_set and not (w[0] & flags_clear)
        inv = {v: k for k, v in KIND.items()}
        return self.chk(case, 'kind', ok, '%s want %s, flags %#x (want +%#x -%#x), bad %#x%s' % (
            inv.get(w[0] & 0xFF, w[0] & 0xFF), kind, w[0] & 0xFF00, flags_set, flags_clear, w[6], info))

    def released(self, case, b, ok, rec):
        return self.chk(case, 'released', ok and not b.violations, '%s %s' % (rec, b.violations[:2]))

    def bank_checks(self, case, b, full=True):
        """the image a boot unpacked: the bank (md5 of the whole region), the header, the order, CACHE"""
        img = bytes(b.uc.mem_read(CRAM, BYTES))
        bank = img[HDR:]
        m = hashlib.md5(bank).hexdigest()
        self.chk(case, 'bank', m == BANK_MD5, 'CRAM [0x100, 0x152100) md5 %s (the chip\'s %s)' % (m, BANK_MD5))
        if not full:
            return img
        h = struct.unpack('<64I', img[:HDR])
        want = {0: MAGIC0, 1: MAGIC1, 2: 1, 3: HDR, 4: BYTES, 5: HDR, 6: BANK, 7: SAMPLES, 8: STREAM, 9: STREAM_BYTES,
                10: BLOCKS, 12: zlib.crc32(bank) & 0xFFFFFFFF}
        bad = [(i, hex(h[i]), hex(v)) for i, v in want.items() if h[i] != v]
        hc = zlib.crc32(img[:4 * 63]) & 0xFFFFFFFF
        self.chk(case, 'header', not bad and h[63] == hc and h[62] == 0,
                 'wrong words %s, CRC %#x (want %#x), key %#x' % (bad, h[63], hc, h[11]))
        return img

    def order_checks(self, case, b):
        lg = b.img_log
        at0 = [v for a, v in lg if a == CRAM]
        ok = len(lg) > 3 and lg[0] == (CRAM, 0) and lg[-1] == (CRAM, MAGIC0) and at0 == [0, MAGIC0]
        self.chk(case, 'magic last', ok, 'image stores %d: first %s, last %s, the magic word stores %s (want it cleared first '
                 'and written once, last of all)' % (len(lg), [hex(x) for x in lg[0]] if lg else None,
                                                    [hex(x) for x in lg[-1]] if lg else None, [hex(v) for v in at0]))
        self.cache_last(case, b)

    def cache_last(self, case, b):
        """CACHE written once (VALID | the image size) and after every CRAM store of the power-on: no store, in the image
        or the SFX bank, came after it, and the SFX copy came before it (event order: each store counts the CACHE writes
        made before it; the model's time does not move inside run_to, so times cannot order them)"""
        cw, s = b.cache_log, b.seq
        if self.s5:                                             # stage 5: the curve's stores also come before CACHE
            self.chk(case, 'curve before CACHE', s['curve'] == CURVE_N and s['curve_after_cache'] == 0,
                     'curve stores %d (want %d halfwords), after CACHE %d' % (s['curve'], CURVE_N, s['curve_after_cache']))
        self.chk(case, 'CACHE last', len(cw) == 1 and cw[0][1] == CACHE_VALID | BYTES and s['after_cache'] == 0 and
                 s['sfx'] == (SFX_HI - SFX_LO) // 4,
                 'CACHE writes %s; CRAM stores after the first: %d (in the image %d, the first at +%s); SFX-bank stores '
                 'before it %d of %d' % ([hex(v) for t, v in cw], s['after_cache'], s['after_cache_img'],
                                         None if s['first_after'] is None else hex(s['first_after']),
                                         s['sfx'] - s['sfx_after_cache'], (SFX_HI - SFX_LO) // 4))

    def watch_image(self, b, stop_sfx=None):
        """every MCU store into the CRAM window, in event order against XLINK: the image's stores [0, 0x152100) logged
        (address, value); for every store how many CACHE writes came before it (cache_last) and whether BAR.EN was on
        (bar_checks); the SFX bank's stores counted. stop_sfx = k: the CPU stops at the k-th SFX-bank store (B17)"""
        b.img_log = []
        b.seq = s = dict(after_cache=0, after_cache_img=0, first_after=None, sfx=0, sfx_after_cache=0, sfx_bar=0,
                         img_bar=0, cut=False, curve=0, curve_after_cache=0, curve_bar=0, img_first_en=None,
                         img_off_late=0)

        def hk(uc, access, addr, size, value, ud):
            o = addr - CRAM
            late = bool(b.cache_log)
            if late:
                s['after_cache'] += 1
                if s['first_after'] is None:
                    s['first_after'] = o
            on = b.bar & BAR_EN
            if o < BYTES:
                b.img_log.append((addr, value & 0xFFFFFFFF))
                s['after_cache_img'] += late
                s['img_bar'] += bool(on)
                if s['img_first_en'] is None:
                    s['img_first_en'] = bool(on)            # the old magic's clear: made dark (the bar lights after it)
                elif not on:
                    s['img_off_late'] += 1                  # an image store after the clear with the bar dark
            elif SFX_CRAM <= o < SFX_CRAM + SFX_ROOM:
                s['sfx'] += 1
                s['sfx_after_cache'] += late
                s['sfx_bar'] += bool(on)
                if stop_sfx is not None and s['sfx'] == stop_sfx:
                    s['cut'] = True
                    uc.emu_stop()
            elif CURVE_LO <= o < CURVE_LO + 2 * CURVE_N:
                s['curve'] += 1
                s['curve_after_cache'] += late
                s['curve_bar'] += bool(on)
        b.uc.hook_add(UC_HOOK_MEM_WRITE, hk, begin=CRAM, end=CRAM + rtlmodel.CRAM_BYTES - 1)

    def sfx_checks(self, case, b):
        got = bytes(b.uc.mem_read(CRAM + 0x200000, SFX_HI - SFX_LO))
        want = bytearray(SFX_HI - SFX_LO)
        want[0::2], want[1::2] = self.rom[SFX_LO + 1:SFX_HI:2], self.rom[SFX_LO:SFX_HI:2]
        return self.chk(case, 'SFX bank', got == bytes(want), 'CRAM 0x200000 + %d B = the ROM\'s 68000 words %#x-%#x: %s' % (
            SFX_HI - SFX_LO, SFX_LO, SFX_HI - 1, got == bytes(want)))

    def curve_checks(self, case, b, w):
        """stage 5: the synth's output curve in CRAM = the
chip's (gen_chip_tables.curve_full), and the record says so"""
        got = bytes(b.uc.mem_read(CRAM + CURVE_LO, 2 * CURVE_N))
        bad = [i for i in range(CURVE_N) if got[2 * i:2 * i + 2] != self.curve[2 * i:2 * i + 2]]
        return self.chk(case, 'curve', not bad and bool(w[0] & F_CURVE),
                        'CRAM %#x + 16,384 x u16 == the chip\'s curve: %d entries differ%s; C4B_F_CURVE %d' % (
                            CURVE_LO, len(bad), ' (the first %d)' % bad[0] if bad else '', int(bool(w[0] & F_CURVE))))

    def bar_checks(self, case, b, unpack=True):
        """'bar off': the last BAR write 0, EN = 0 at the release, PX never falling; 'bar unpack only' (21.2: lit only
        during a first-boot unpack): an unpacking boot lights it and makes its image stores with EN on and its SFX
        copy with EN off; a boot that keeps the file never lights it"""
        lg = [v for t, v in b.bar_log]
        on = [v & BAR_PX for v in lg if v & BAR_EN]
        ok = bool(lg) and lg[-1] == 0 and not (b.bar & BAR_EN) and all(x <= y for x, y in zip(on, on[1:]))
        self.chk(case, 'bar off', ok, '%d BAR writes, %d with EN (PX %s .. %s, never falling), the last %#x, EN at the '
                 'release %d' % (len(lg), len(on), on[:1], on[-1:], lg[-1] if lg else -1, int(bool(b.bar & BAR_EN))))
        s = b.seq
        if unpack:                                              # (a problem a review of test build 4b found: the clear
                                                                # dark, every
            ok = (bool(on) and s['img_bar'] > 0 and s['sfx_bar'] == 0 and   # image store after it lit)
                  s['img_first_en'] is False and s['img_off_late'] == 0)
        else:
            ok = not on and s['sfx_bar'] == 0
        self.chk(case, 'bar unpack only', ok, '%s: %d BAR writes with EN; image stores with EN %d, SFX-bank stores with '
                 'EN %d; the first image store (the old magic cleared) %s, image stores after it with the bar dark %d' % (
                     'an unpack' if unpack else 'no unpack (the bar must stay dark)', len(on), s['img_bar'], s['sfx_bar'],
                     {None: 'none', True: 'LIT', False: 'dark'}[s['img_first_en']], s['img_off_late']))

    def want(self, case):
        return self.only is None or self.only == case

    def run(self, test=True):
        try:
            self.cases(test)
        except Stop as e:
            self.chk('-', 'no model violation', False, str(e))
        return not self.fails

    def first_boot(self, case, test=True, **k):
        """a power-on that must unpack: the bank, header, order, CACHE, SFX, the bar (lit only from the unpack's start:
        a loaded file's check before its rejection runs dark), test build 5's curve; returns (board, image)"""
        b = self.board(**k)
        self.watch_image(b)
        ok, rec = self.boot(b, case)
        self.released(case, b, ok, rec)
        img = self.bank_checks(case, b)
        self.order_checks(case, b)
        self.bar_checks(case, b)
        if self.s5:
            self.curve_checks(case, b, self.rec_words(b))
        return b, img

    def cases(self, test):
        V = '' if test else 'R'
        # ---- B1: power-on, no file; the CRAM as another core left it (random bytes: every bank byte must be written)
        import random
        b = self.board(cram=random.Random(4).randbytes(rtlmodel.CRAM_BYTES))
        self.watch_image(b)
        tabs, stk = {}, [None]
        oa = self.osym.get('WavpackOpenFileInput')

        bcb = b.sym['boot_cache_boot']

        def deep(uc, access, addr, size, value, ud):      # stores by the stub or the overlay only (not crt0's fill)
            pc = uc.reg_read(RC.UC_RISCV_REG_PC)
            if (rtlmodel.WRAM + 0x6C00 <= pc < rtlmodel.WRAM + 0xAC00 or bcb[0] <= pc < bcb[0] + bcb[1]) and                     (stk[0] is None or addr < stk[0]):
                stk[0] = addr
        b.uc.hook_add(UC_HOOK_MEM_WRITE, deep, begin=self.osym['__ovl_stk_end'], end=b.sym['__crt0_stack_begin'][0] + 3)
        if oa and test:                         # the decoder's open: the tables are made (wvbank_unpack's first call)
            if b.run_to('boot_cache_boot', 100000):
                b.uc.ctl_remove_cache(oa, oa + 4)
                b.uc.emu_start(b.pc(), oa, count=50000000)
                for nm in ('nbits_table', 'ones_count_table', 'exp2_table', 'log2_table'):
                    tabs[nm] = bytes(b.uc.mem_read(self.osym[nm], 256))
        ok, rec = self.boot(b, V + 'B1')
        self.released(V + 'B1', b, ok, rec)
        img1 = self.bank_checks(V + 'B1', b)
        self.order_checks(V + 'B1', b)
        self.sfx_checks(V + 'B1', b)
        self.bar_checks(V + 'B1', b)
        w = self.rec_words(b)
        self.kind_ok(V + 'B1', w, 'FIRST', F['CACHE_SET'] | F['UNPACKED'] | F['HDR_WRITTEN'] | F['SFX'] | F['BAR_OFF'],
                     F['FAIL'] | F['CRCERR'], ', samples %d, bank CRC %#x, key %#x' % (w[7], w[4], w[9]))
        if self.s5:
            self.curve_checks(V + 'B1', b, w)
        self.chk(V + 'B1', 'record words', w[4] == zlib.crc32(img1[HDR:]) & 0xFFFFFFFF and w[7] == SAMPLES and
                 w[15] == STREAM and (w[14] >> 16) == BLOCKS and w[8] == 0 and w[6] & 0xFF == 0xFF,
                 'bank_crc %#x samples %d stream %#x blocks %d crc_errs %#x bad %#x' % (w[4], w[7], w[15], w[14] >> 16,
                                                                                        w[8], w[6]))
        if test:
            want = tables_formula()
            self.chk('B1', 'tables', tabs == want, 'the four generated tables (at the decoder\'s open) == their formulas: '
                     '%s' % {k: tabs.get(k) == v for k, v in want.items()})
            depth = b.sym['__crt0_stack_begin'][0] + 4 - stk[0] if stk[0] else None
            self.chk('B1', 'stack', depth is not None and depth <= 1024, 'the boot path\'s deepest store %s B below the '
                     'stack top (the stack config\'s @c4b_overlay: 1,024 B)' % depth)
            r, c = self.record(b, 'B1')
            if c:
                rep = dbgsave.report(r, False)
                self.chk('B1', 'reader', 'FIRST: no file loaded' in rep and 'the chip\'s bank' in rep and
                         c['boots'] == 1 and len(c['entries']) == 1, rep[rep.find('boot cache'):][:200])
        else:
            self.record(b, 'RB1', test=False)
        self.b1_words = w
        # ---- B2: the Quit's reboot (a Soft Reset)
        w0, c0 = b.cram_writes, len(b.cache_log)
        bl0 = len(b.bar_log)
        b.soft_reset()
        ok, rec = self.boot(b, V + 'B2')
        self.released(V + 'B2', b, ok, rec)
        self.chk(V + 'B2', 'no CRAM write', b.cram_writes == w0 and len(b.cache_log) == c0 and
                 all(v == 0 for t, v in b.bar_log[bl0:]), 'CRAM writes +%d, CACHE writes +%d, BAR writes %s' % (
                     b.cram_writes - w0, len(b.cache_log) - c0, [hex(v) for t, v in b.bar_log[bl0:]]))
        self.kind_ok(V + 'B2', self.rec_words(b), 'WARM')
        if test:
            r, c = self.record(b, 'B2')
            if c:
                self.chk('B2', 'carried', c['boots'] == 2 and [e['kind_name'] for e in c['entries']] == ['WARM', 'FIRST'],
                         str([e['kind_name'] for e in c['entries']]))
        save = save3 = bytes(b.save)
        if not test or self.want('B13'):
            self.case_b13(b, V)
        if not test or self.want('B3') or self.want('B14'):
            save3 = self.case_b3(V, save, img1, test)
        if not test:
            return
        self.later(img1, save3)

    def case_b13(self, b, V):
        # ---- B13: the MCU-only restart (crt0 again, the RTL state kept)
        w0, c0 = b.cram_writes, len(b.cache_log)
        for r_ in range(1, 32):
            b.uc.reg_write(getattr(RC, 'UC_RISCV_REG_X%d' % r_), 0)
        b.uc.reg_write(RC.UC_RISCV_REG_MIE, 0)
        b.uc.reg_write(RC.UC_RISCV_REG_MSTATUS, 0)
        b.uc.reg_write(RC.UC_RISCV_REG_PC, 0)
        b.ctrl |= 1
        ok, rec = self.boot(b, V + 'B13')
        self.released(V + 'B13', b, ok, rec)
        self.chk(V + 'B13', 'no CRAM write', b.cram_writes == w0 and len(b.cache_log) == c0, 'CRAM writes +%d, CACHE '
                 'writes +%d' % (b.cram_writes - w0, len(b.cache_log) - c0))
        self.kind_ok(V + 'B13', self.rec_words(b), 'WARM')

    def case_b3(self, V, save, img1, test):
        # ---- B3: power-on with B1's file
        b = self.board(save=save, cram=img1, cache_loaded=BYTES)
        self.watch_image(b)
        ok, rec = self.boot(b, V + 'B3')
        self.released(V + 'B3', b, ok, rec)
        self.chk(V + 'B3', 'no image store', not b.img_log and len(b.cache_log) == 1 and b.cache == CACHE_VALID | BYTES,
                 'image stores %d, CACHE %s' % (len(b.img_log), [hex(v) for t, v in b.cache_log]))
        self.cache_last(V + 'B3', b)
        self.sfx_checks(V + 'B3', b)
        self.bar_checks(V + 'B3', b, unpack=False)
        w = self.rec_words(b)
        self.kind_ok(V + 'B3', w, 'PASS', F['CACHE_SET'] | F['SFX'] | F['BAR_OFF'], F['UNPACKED'] | F['FAIL'],
                     ', bank CRC %#x, the header\'s %#x' % (w[4], w[5]))
        if self.s5:                                 # (B3's board holds only the file's image: the boot wrote the curve)
            self.curve_checks(V + 'B3', b, w)
        if test:
            r, c = self.record(b, 'B3')
            if c:
                rep = dbgsave.report(r, False)
                self.chk('B3', 'reader', 'PASS: the file loaded whole' in rep and c['boots'] == 3 and
                         [e['kind_name'] for e in c['entries']][:2] == ['PASS', 'WARM'], str([e['kind_name'] for e in c['entries']]))
        save3 = bytes(b.save)
        # ---- B14: the history keeps 5
        for i in range(6):
            b.soft_reset()
            self.boot(b, V + 'B14')
        if test:
            r, c = self.record(b, 'B14')
            if c:
                self.chk('B14', 'five kept', c['boots'] == 9 and len(c['entries']) == 5 and
                         all(e['kind_name'] == 'WARM' for e in c['entries']), 'boots %d, entries %s' % (
                             c['boots'], [e['kind_name'] for e in c['entries']]))
        return save3

    def later(self, img1, save3):
        W = self.want
        self.c_b4(img1, save3)
        for case in ('B5', 'B6', 'B7', 'B8', 'B9', 'B10', 'B11', 'B12', 'B12b', 'B15', 'B16', 'B17'):
            if W(case) or (case == 'B11' and W('B11b')) or (case == 'B17' and W('B17b')):
                getattr(self, 'c_' + case.lower())(img1, save3)

    def c_b4(self, img1, save3):
        W = self.want
        # ---- B4 / B4t / B4d: one byte wrong
        for case, at, blk in (('B4', HDR + 15 * 44100 + 1234, 15), ('B4t', HDR + SAMPLES + 10, 0xFE), ('B4d', HDR + 21, 0)):
            if not W(case):
                continue
            bad = bytearray(img1)
            bad[at] ^= 0x5A
            b, img = self.first_boot(case, save=save3, cram=bytes(bad), cache_loaded=BYTES)
            w = self.rec_words(b)
            self.kind_ok(case, w, 'BANK', F['CACHE_SET'] | F['UNPACKED'] | F['HDR_WRITTEN'])
            self.chk(case, 'first wrong', w[6] & 0xFF == blk, 'block %#x (want %#x), %d wrong, the file\'s CRC %#x' % (
                w[6] & 0xFF, blk, (w[6] >> 8) & 0xFF, w[5]))

    def c_b5(self, img1, save3):
        # ---- B5: test build 4a's pattern file
        p4a = c4a_image()
        print('     card 4a\'s pattern file: %d B, md5 %s' % (len(p4a), hashlib.md5(p4a).hexdigest()))
        b, img = self.first_boot('B5', save=save3, cram=p4a, cache_loaded=BYTES)
        w = self.rec_words(b)
        self.kind_ok('B5', w, 'HDR', F['CACHE_SET'] | F['UNPACKED'] | F['HDR_WRITTEN'], 0, ', header word %d' % ((w[6] >> 16) & 0xFF))

    def c_b6(self, img1, save3):
        # ---- B6: a short file
        short = bytearray(BYTES)
        short[:BYTES - 0x1000] = img1[:BYTES - 0x1000]
        b, img = self.first_boot('B6', save=save3, cram=bytes(short), cache_loaded=BYTES - 0x1000)
        self.kind_ok('B6', self.rec_words(b), 'SIZE', F['CACHE_SET'] | F['UNPACKED'])

    def c_b7(self, img1, save3):
        # ---- B7: CRAM writes lost
        b, img = self.first_boot('B7', save=save3, cram=img1, cache_loaded=BYTES, xl_lost=3 << 16)
        self.kind_ok('B7', self.rec_words(b), 'LOST', F['CACHE_SET'] | F['UNPACKED'])

    def c_b8(self, img1, save3):
        # ---- B8: the header's CRC broken
        bad = bytearray(img1)
        bad[4 * 62] ^= 1
        b, img = self.first_boot('B8', save=save3, cram=bytes(bad), cache_loaded=BYTES)
        w = self.rec_words(b)
        self.kind_ok('B8', w, 'HDR', F['CACHE_SET'] | F['UNPACKED'], 0, ', header word %d' % ((w[6] >> 16) & 0xFF))

    @staticmethod
    def key_file(img1):
        """B1's file with its header's ROM key changed and its CRC made good: a cache made from another stream"""
        bad = bytearray(img1)
        struct.pack_into('<I', bad, 4 * 11, struct.unpack_from('<I', bad, 4 * 11)[0] ^ 0x10000)
        struct.pack_into('<I', bad, 4 * 63, zlib.crc32(bytes(bad[:4 * 63])) & 0xFFFFFFFF)
        return bytes(bad)

    def c_b9(self, img1, save3):
        # ---- B9: a header for another stream (its key changed, its CRC made good)
        bad = self.key_file(img1)
        b, img = self.first_boot('B9', save=save3, cram=bytes(bad), cache_loaded=BYTES)
        self.kind_ok('B9', self.rec_words(b), 'KEY', F['CACHE_SET'] | F['UNPACKED'])

    def c_b10(self, img1, save3):
        # ---- B10: no file, the CRAM kept the image
        b, img = self.first_boot('B10', save=save3, cram=img1, cache_loaded=0)
        self.kind_ok('B10', self.rec_words(b), 'FIRST', F['CACHE_SET'] | F['UNPACKED'])

    def c_b11(self, img1, save3):
        # ---- B11 / B11b: a reset in the middle of the unpack
        for case, kw, kind2 in (('B11', dict(), 'FIRST'), ('B11b', dict(cram=self.key_file(img1), cache_loaded=BYTES), 'HDR')):
            if not self.want(case):
                continue
            b = self.board(save=save3, **kw)
            self.watch_image(b)
            mid = b.run_to('brd_boot', 60000000)            # about a quarter of the unpack, then the reset
            n_mid = len(b.img_log)
            b.soft_reset()
            ok, rec = self.boot(b, case)
            self.released(case, b, ok, rec)
            self.bank_checks(case, b)
            w = self.rec_words(b)
            self.kind_ok(case, w, kind2, F['CACHE_SET'] | F['UNPACKED'] | F['HDR_WRITTEN'],
                         0, ', reset after %d image stores (the overlay still running: %s)' % (n_mid, not mid))
            if self.s5:
                self.curve_checks(case, b, w)

    def c_b17(self, img1, save3):
        # ---- B17 / B17b: a reset inside the SFX copy (added by a repair after a review): CACHE must not be set yet, so
        # the next boot copies the bank whole and only then sets CACHE (never WARM over a half-copied SFX bank)
        for case, kw, kind2, fl in (('B17', dict(cram=img1, cache_loaded=BYTES), 'PASS', 0),
                                    ('B17b', dict(), 'FIRST', F['UNPACKED'] | F['HDR_WRITTEN'])):
            if not self.want(case):
                continue
            b = self.board(save=save3, **kw)
            self.watch_image(b, stop_sfx=SFX_CUT)
            mid = b.run_to('brd_boot', 900000000)
            s0, c0, held = dict(b.seq), len(b.cache_log), b.ctrl & 1
            self.chk(case, 'cut in the copy', not mid and s0['cut'] and held and c0 == 0 and b.cache == 0,
                     'stopped in the copy %s after %d SFX stores (%d image stores before), the 68000 held %d, CACHE writes '
                     'by then %d, CACHE %#x' % (s0['cut'], s0['sfx'], len(b.img_log), held, c0, b.cache))
            b.soft_reset()
            ok, rec = self.boot(b, case)
            self.released(case, b, ok, rec)
            self.sfx_checks(case, b)
            if kind2 == 'FIRST':
                self.bank_checks(case, b)
            w = self.rec_words(b)
            if self.s5:
                self.curve_checks(case, b, w)
            self.kind_ok(case, w, kind2, F['CACHE_SET'] | F['SFX'] | fl, F['FAIL'],
                         ', the reset after %d of the copy\'s %d stores' % (s0['sfx'], (SFX_HI - SFX_LO) // 4))
            self.chk(case, 'CACHE once', len(b.cache_log) == 1 and b.cache == CACHE_VALID | BYTES and
                     b.seq['sfx_after_cache'] == 0 and b.seq['after_cache'] == 0,
                     'CACHE writes %s, CRAM stores after it %d' % ([hex(v) for t, v in b.cache_log], b.seq['after_cache']))

    def c_b12(self, img1, save3):
        # ---- B12: the ROM's stream one byte wrong -> FAIL; then a Soft Reset -> GONE
        rom2 = bytearray(self.rom)
        rom2[STREAM + 20000] ^= 0x01
        b = self.board(rom=bytes(rom2), save=save3)
        ok, rec = self.boot(b, 'B12')
        self.released('B12', b, ok, rec)
        w = self.rec_words(b)
        self.kind_ok('B12', w, 'FIRST', F['UNPACKED'] | F['FAIL'], F['CACHE_SET'] | F['HDR_WRITTEN'],
                     ', crc_errs %#x, why %d' % (w[8], w[6] >> 24))
        self.chk('B12', 'no cache', b.cache == 0 and not b.cache_log and struct.unpack('<I', b.uc.mem_read(CRAM, 4))[0] == 0,
                 'CACHE %#x writes %d, the magic word %#x' % (b.cache, len(b.cache_log), struct.unpack('<I', b.uc.mem_read(CRAM, 4))[0]))
        w0 = b.cram_writes
        b.soft_reset()
        ok, rec = self.boot(b, 'B12')
        self.kind_ok('B12', self.rec_words(b), 'GONE', F['BAR_OFF'], F['UNPACKED'])
        self.chk('B12', 'gone: nothing', b.cram_writes == w0 and not b.cache_log, 'CRAM writes +%d, CACHE writes %d' % (
            b.cram_writes - w0, len(b.cache_log)))

    def c_b12b(self, img1, save3):
        # ---- B12b: the overlay changed in WRAM before the power-on (a byte of an error string, never run)
        b = self.board(save=save3)
        base = self.osym['__ovl_start']
        img_ovl = bytes(b.uc.mem_read(base, 16 + struct.unpack_from('<I', b.uc.mem_read(base + 4, 4))[0]))
        k = img_ovl.find(b'invalid WavPack')
        if k > 0:
            b.uc.mem_write(base + k, b'X')
        ok, rec = self.boot(b, 'B12b')
        self.kind_ok('B12b', self.rec_words(b), 'GONE', 0, F['UNPACKED'], ', the string at overlay +%#x' % k)
        self.chk('B12b', 'gone: nothing', b.cram_writes == 0 and not b.cache_log, 'CRAM writes %d, CACHE writes %d' % (
            b.cram_writes, len(b.cache_log)))

    def c_b15(self, img1, save3):
        # ---- B15: a 4 KB save RAM
        game = bytes((i * 37 + 11) & 0xFF for i in range(0x1000))
        b, img = self.first_boot('B15', save=game, save_kb=4)
        if not self.s5:
            self.chk('B15', 'save untouched', bytes(b.save) == game, 'save %s' % (
                'unchanged' if bytes(b.save) == game else 'CHANGED'))
            return
        # since test build S3a: the stage-5 boot converts a 0.2.x save once (interim/s1/bodies_s1.c eep_import): the
        # first copy of ids 4 / 1 / 2 / 3 (0x000 / 0x400 / 0x600 / 0x800, 0x200 / 0x100 B) becomes the cart's copy (its
        # payload scrambled, the trailer: sequence 2, the id, the XOR byte, the magic 0x3FC2); tests/equiv/eeplock.py
        # holds those bytes against the chip's own write. Here: nothing else
        # of the 4 KB save is written, and the next boot writes nothing.
        s1 = bytes(b.save)
        copies = ((4, 0x000, 0x200), (1, 0x400, 0x100), (2, 0x600, 0x100), (3, 0x800, 0x100))
        inside = set()
        for _, o, n in copies:
            inside.update(range(o, o + n))
        other = [a for a in range(0x1000) if a not in inside and s1[a] != game[a]]
        self.chk('B15', 'save: only the import', not other, '%d byte(s) changed outside the four first copies%s' % (
            len(other), (', the first at %#x' % other[0]) if other else ''))
        bad = []
        for i, o, n in copies:
            c = s1[o:o + n]
            x = 0
            for v in c:
                x ^= v
            if (struct.unpack_from('<I', c, n - 8)[0] != 2 or c[n - 4] != i or struct.unpack_from('<H', c, n - 2)[0] != 0x3FC2
                    or x != 0 or c[:n - 8] == game[o:o + n - 8]):
                bad.append(i)
        self.chk('B15', 'import: the cart\'s copies', not bad, 'ids 4 / 1 / 2 / 3: trailer (sequence 2, id, XOR 0, magic '
                 '0x3FC2) and the payload scrambled%s' % ((', wrong in ids %s' % bad) if bad else ''))
        b2 = self.board(save=s1, save_kb=4)
        ok, rec = self.boot(b2, 'B15')
        self.chk('B15', 'next boot untouched', ok and bytes(b2.save) == s1, 'released %s, save %s' % (
            ok, 'unchanged' if bytes(b2.save) == s1 else 'CHANGED'))

    def c_b16(self, img1, save3):
        # ---- B16: crt0's checks (stage 5: test build 4a's board, a FEAT without SYNTH and a 72 KB IROM refused too)
        if self.s5:
            tbl = (('v1.2 board (card 4)', dict(user_code=rtlmodel.IFACE_V12, feat=None), STOP_IFACE),
                   ('card 4a board', dict(feat=FEAT_4A), STOP_FEAT),
                   ('FEAT without SYNTH', dict(feat=FEAT_5 & ~4), STOP_FEAT),
                   ('FEAT without CACHE', dict(feat=FEAT_5 & ~1), STOP_FEAT),
                   ('FEAT IROM 72 KB', dict(feat=(FEAT_5 & ~0xFF0000) | (72 << 16)), STOP_FEAT))
        else:
            tbl = (('v1.2 board (card 4)', dict(user_code=rtlmodel.IFACE_V12, feat=None), STOP_IFACE),
                   ('FEAT without CACHE', dict(feat=0x0048001A), STOP_FEAT),
                   ('FEAT IROM 64 KB', dict(feat=0x0040001B), STOP_FEAT))
        for name, kw, code in tbl:
            for bd in (self.build, twin_of(self.build)):
                if not os.path.exists(os.path.join(bd, 'main.nm')):
                    continue
                b = self.board(build=bd, **kw)
                ok, rec = self.boot(b, 'B16')
                want = kw.get('user_code', rtlmodel.IFACE_V13) if code == STOP_IFACE else kw['feat']
                self.chk('B16', '%s (%s)' % (name, os.path.basename(bd)), not ok and rec and rec[1] == code and
                         rec[3] == want and (b.ctrl & 1) and not b.cache_log and not b.bar_log and b.cram_writes == 0,
                         'boot record %s, held %d' % ([hex(x) for x in rec] if rec else rec, b.ctrl & 1))


def rom_of():
    lp = os.path.join(ROOT, 'paths.local.json')
    cfg = (json.load(open(lp)) if os.path.exists(lp) else {}).get('refs') or {}
    rom = cfg.get('rom')
    if not rom or not os.path.isfile(rom):
        print('SETUP ERROR: paths.local.json "refs" needs rom')
        sys.exit(2)
    return open(rom, 'rb').read()


def negative5(build, rom):
    """test build 5's stage-5 plants (fwbuild.json s5test_bug_c5a..c), rebuilt every time next to the clean s5test
    image"""
    base = os.path.dirname(build)
    cmd = [sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
           '--out', os.path.dirname(os.path.dirname(base))]
    for v in NEG5:
        cmd += ['--variant', v]
    rr = subprocess.run(cmd, capture_output=True, text=True)
    if rr.returncode:
        print('SETUP ERROR: building %s failed:\n%s' % (list(NEG5), rr.stdout[-2000:] + rr.stderr[-2000:]))
        sys.exit(2)
    notes = json.load(open(os.path.join(ROOT, 'fwbuild.json')))['s1']['pocket']['variants']
    good = True
    for v, (case, name) in NEG5.items():
        print('---- %s (%s)' % (v, notes[v]['note']))
        g = Rig(os.path.join(base, v), rom, only=case)
        g.run()
        hit = (case, name) in g.fails
        print('%-4s planted %s: %s, caught by %s %s' % ('PASS' if hit else 'FAIL', v, 'failed' if g.fails else 'PASSED',
                                                        case, name), flush=True)
        good &= hit
    print('RESULT: %s' % ('PASS' if good else 'FAIL'))
    sys.exit(0 if good else 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket72k', 'test'))
    ap.add_argument('--negative', action='store_true')
    a = ap.parse_args()
    rom = rom_of()
    if a.negative:
        base = os.path.dirname(a.build)
        if is_s5(a.build):                                      # stage 5: its own three plants
            return negative5(a.build, rom)
        need = ['test_bug_c4b%d' % n for n in NEG]
        cmd = [sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
               '--out', os.path.dirname(os.path.dirname(base))]
        for v in need:
            cmd += ['--variant', v]
        rr = subprocess.run(cmd, capture_output=True, text=True)       # rebuilt every time: no stale planted image
        if rr.returncode:
            print('SETUP ERROR: building %s failed:\n%s' % (need, rr.stdout[-2000:] + rr.stderr[-2000:]))
            sys.exit(2)
        good = True
        notes = json.load(open(os.path.join(ROOT, 'fwbuild.json')))['s1']['pocket']['variants']
        for n, (case, name) in NEG.items():
            v = 'test_bug_c4b%d' % n
            print('---- %s (%s)' % (v, notes[v]['note']))
            g = Rig(os.path.join(base, v), rom, only=case)
            g.run()
            hit = (case, name) in g.fails
            print('%-4s planted %s: %s, caught by %s %s' % ('PASS' if hit else 'FAIL', v, 'failed' if g.fails else 'PASSED',
                                                            case, name), flush=True)
            good &= hit
        print('RESULT: %s' % ('PASS' if good else 'FAIL'))
        sys.exit(0 if good else 1)
    if not os.path.exists(os.path.join(a.build, 'main.nm')):
        print('SETUP ERROR: no image at %s (tools/fwbuild.py s1)' % a.build)
        sys.exit(2)
    g = Rig(a.build, rom)
    ok = g.run(test=True)
    rb = twin_of(a.build)
    if os.path.basename(a.build) in ('test', 's5test') and os.path.exists(os.path.join(rb, 'main.nm')):
        print('---- the RELEASE image (%s)' % rb)
        gr = Rig(rb, rom)
        gr.run(test=False)
        g.n += gr.n
        g.fails += gr.fails
    print('%d checks, %d failed' % (g.n, len(g.fails)))
    print('RESULT: %s' % ('PASS' if not g.fails else 'FAIL'))
    sys.exit(0 if not g.fails else 1)


if __name__ == '__main__':
    main()
