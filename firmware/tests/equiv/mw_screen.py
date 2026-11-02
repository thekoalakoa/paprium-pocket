#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""mw_screen.py - stage 3, test build S3b (the MegaWire port): the A858 MegaWire screen (core/mw/mw_screen.c, with
core/mw/mw_text.c and page A core/mw/mw_page_a.c) against the cart's chip, with no module.

The chip side is the cart's own program in the audit harness (our test harness outside this tree; paths.local.json
"harness_dir"; its post-boot state), the
way the game's Options pad code reaches it: A858 posted, then the main loop's screen calls 0x080225F8 one by one with
each call's SysTick waits passing as chip time (its interrupts and TIM7 run in them), for --seconds. Its page pointers
(G+0x188 / +0x18C) name OUR pages, packed as its loader expects (page A from tools/mkpagea.py, page B the ROM's font at
0x126200): the cart's own pages are not in the ROM. Our side is tests/s1/mw_host.c (fwbuild's s1 program mw_host) run
from the chip's state just before the post (the MegaWire blocks, $1FE4, $1FEA), with the same TIM7 period.
Compared: the $1FE4 stores (values in order, and their times), the 68000's hold and its release (ours: the board's hold
at the bit-14 clear and set, docs/BOOT_SPEC.md section 8), the park word $1FEA = 0x1234 and its time, the music and SFX
stops (the ready words) and the screen state's walk; at the end, RAMDP $0000-$17FF (the pages), $1E10-$1E8F (the lines),
the driver block's access point and password (DRV+0..0x36), the record flag MW+0xC and the call count MW+8. Times match
within --tol-ms; the call count within 3 (ours unpacks the screen's text
from the cart program between calls, docs/MCU_INTERFACE.md section 3.8).
Only CRC-32s of the page / line bytes are printed: page B and the lines are the cart's bytes.
--plant 1 / 2 (with --expect-fail): our page A one byte off / the 68000 released 10 ms late; each must be caught.
    python -I -B tests/equiv/mw_screen.py --host build/s1/host/mw_host.exe [--seconds 3] [--json OUT]
Exit 0 = every check passed, 1 = a difference, 2 = setup error; SKIP lines when no harness or ROM is configured."""
import argparse, json, os, struct, subprocess, sys, zlib
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import mkpagea   # noqa: E402

G, MW, DRV, EEP = 0x20006F2C, 0x20006D70, 0x200100AC, 0x20012A6C
SREADY, SFXREADY = 0x2000C164, 0x20012BD4
FONT = 0x126200


def local():
    p = os.path.join(ROOT, 'paths.local.json')
    return json.load(open(p)) if os.path.exists(p) else {}


def lits(b):
    """the cart's 0x80 packing: literal runs of up to 63 bytes, then the end code"""
    out = bytearray([0x80])
    for i in range(0, len(b), 63):
        ch = b[i:i + 63]
        out.append(len(ch))
        out += ch
    out.append(0)
    return bytes(out)


def bytes68(ramdp, lo, hi):
    """the 68000's bytes of RAMDP [lo, hi) from the chip's little-endian halfword view"""
    out = bytearray()
    for a in range(lo, hi, 2):
        h = ramdp[a] | ramdp[a + 1] << 8
        out += bytes((h >> 8, h & 0xFF))
    return bytes(out)


def chip_side(hdir, page_a, seconds, plant):
    sys.path.insert(0, hdir)
    sys.path.insert(0, os.path.join(hdir, 'chip'))
    import harness
    from unicorn import UC_HOOK_MEM_WRITE
    import unicorn.arm_const as A
    c = harness.ChipSide()
    m = c.m
    mu = m.mu
    hz = m.sysclk()
    rom = None
    r32 = lambda a: struct.unpack('<I', bytes(mu.mem_read(a, 4)))[0]
    r16 = lambda a: struct.unpack('<H', bytes(mu.mem_read(a, 2)))[0]
    return c, m, mu, hz, rom, r32, r16, harness, UC_HOOK_MEM_WRITE, A


def run(a):
    L = local()
    hdir = a.harness or L.get('harness_dir')
    if not hdir or not os.path.isdir(hdir):
        print('SKIP: no audit harness (paths.local.json "harness_dir")')
        return 0
    if not os.path.isfile(a.host):
        print('SETUP ERROR: no harness %s (tools/fwbuild.py s1 builds it)' % a.host)
        return 2
    img = mkpagea.build()[0]
    page_a = b''.join(struct.pack('>H', w) for w in img)
    c, m, mu, hz, _rom, r32, r16, harness, HOOK_W, A = chip_side(hdir, page_a, a.seconds, a.plant)
    romp = a.rom or L.get('equiv', {}).get('rom')
    rom = open(romp, 'rb').read() if romp and os.path.isfile(romp) else None
    if rom is None:
        print('SKIP: no ROM (paths.local.json "equiv": "rom")')
        return 0
    if a.plant == 1:
        page_a = page_a[:0x210] + bytes([page_a[0x210] ^ 1]) + page_a[0x211:]
    pa, pb = lits(page_a), lits(rom[FONT:FONT + 0x1000])
    mu.mem_write(0xC0700000, pa)
    mu.mem_write(0xC0710000, pb)
    mu.mem_write(G + 0x188, struct.pack('<I', 0xC0700000))
    mu.mem_write(G + 0x18C, struct.pack('<I', 0xC0710000))
    before = dict(mw=bytes(mu.mem_read(MW, 0x1BC)), drv=bytes(mu.mem_read(DRV, 0x1140)), eep=bytes(mu.mem_read(EEP, 0x64)),
                  fe4=m.reg68(0x1FE4), ram=bytes68(bytes(m.ramdp), 0, 0x1FE0))
    now = lambda: (m.cycles + m.skipped) / hz
    ev = []

    def fw(uc, access, addr, size, value, ud):
        off = addr - harness.FPGA
        v = value & ((1 << (8 * size)) - 1)
        if off == 4 and size == 2:
            ev.append((now(), 'FE4', v))
        elif off == 0xA and size == 2:
            ev.append((now(), 'FEA', v))
    mu.hook_add(HOOK_W, fw, begin=harness.FPGA + 4, end=harness.FPGA + 0xB)

    def sw(uc, access, addr, size, value, ud):
        ev.append((now(), {SREADY: 'SREADY', SFXREADY: 'SFXREADY', MW + 0x10: 'STATE'}[addr], value & 0xFFFF))
    for ad in (SREADY, SFXREADY, MW + 0x10):
        mu.hook_add(HOOK_W, sw, begin=ad, end=ad)
    t0 = now()
    r = c.post(0xA858, timed=True, deep=False)
    fea_after = m.reg68(0x1FEA)
    REGS = [getattr(A, 'UC_ARM_REG_' + x) for x in m.CPU_REGS]
    calls = 0
    while now() - t0 < a.seconds:
        if r16(MW + 0x10) == 0:
            m.run(seconds=0.01)
            continue
        saved = [mu.reg_read(x) for x in REGS]
        s0 = m.skipped
        m.call(0x080225F8)
        for x, v in zip(REGS, saved):
            try:
                mu.reg_write(x, v)
            except Exception:       # noqa: BLE001 (a register the model will not take back)
                pass
        m.halted = False
        dt = m.skipped - s0
        m.skipped = s0
        m.run(cycles=dt)
        calls += 1
        if m.fault:
            print('SETUP ERROR: the chip faulted %s' % (m.fault,))
            return 2
    ramdp = bytes(m.ramdp)
    chip = dict(ok=r['ok'], calls=calls,
                ev=[(round((t - t0) * 1e3, 3), k, v) for t, k, v in ev if t >= t0],
                state=r16(MW + 0x10), cnt=r32(MW + 8), home=r32(MW + 0xC),
                sready=r32(SREADY), sfxready=r16(SFXREADY),
                c_pages=zlib.crc32(bytes68(ramdp, 0, 0x1800)) & 0xFFFFFFFF,
                c_lines=zlib.crc32(bytes68(ramdp, 0x1E10, 0x1E90)) & 0xFFFFFFFF,
                c_drv=zlib.crc32(bytes(mu.mem_read(DRV, 0x37))) & 0xFFFFFFFF)
    # ours
    host = subprocess.Popen([a.host], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)

    def send(line, wait=True):
        host.stdin.write(line + '\n')
        host.stdin.flush()
        out = []
        if not wait:
            return out
        while True:
            ln = host.stdout.readline()
            if not ln:
                raise SystemExit('mw_host ended (rc %s) at "%s"' % (host.poll(), line))
            if ln.strip() == 'E':
                return out
            out.append(ln.split())
    send('rom %s' % romp, wait=False)
    for blk, n in (('mw', 0x1BC), ('drv', 0x1140), ('eep', 0x64)):
        for k in range(0, n, 0x200):
            send('set %s %x %s' % (blk, k, before[blk][k:k + 0x200].hex()), wait=False)
    for k in range(0, 0x1FE0, 0x200):
        send('ram %x %s' % (k, before['ram'][k:k + 0x200].hex()), wait=False)
    send('ready 1', wait=False)
    send('fe4 %x' % before['fe4'], wait=False)
    send('fea %x' % fea_after, wait=False)
    send('a858')
    out = send('scr %d' % int(a.seconds * 1000))
    host.stdin.close()
    host.wait()
    oev, z, cc = [], None, None
    for p in out:
        if p[0] in ('S4', 'FA', 'H', 'ST') and len(p) == 3:
            oev.append((int(p[2]) / 1e3, p[0], int(p[1], 16) if p[0] in ('S4', 'FA') else int(p[1])))
        elif p[0] == 'Z':
            z = [int(x) for x in p[1:]]
        elif p[0] == 'C':
            cc = [int(x, 16) for x in p[1:]]
    if a.plant == 2:                                # planted: the release 10 ms late
        oev = [(t + 10.0, k, v) if (k == 'H' and v == 0) else (t, k, v) for t, k, v in oev]
    bad = []
    tol = a.tol_ms
    cfe4 = [(t, v) for t, k, v in chip['ev'] if k == 'FE4']
    ofe4 = [(t, v) for t, k, v in oev if k == 'S4']
    if [v for _, v in cfe4] != [v for _, v in ofe4]:
        bad.append('$1FE4 stores: chip %s ours %s' % (['%04X' % v for _, v in cfe4], ['%04X' % v for _, v in ofe4]))
    for (tc, vc), (to, vo) in zip(cfe4, ofe4):
        if abs(tc - to) > tol:
            bad.append('$1FE4 %04X at %.3f ms, ours %.3f ms' % (vc, tc, to))
    # the hold: bit 14 cleared -> held, set -> released (ours: the board's hold)
    c_hold = [(t, 0 if v & 0x4000 else 1) for t, v in cfe4]
    c_hold = [x for i, x in enumerate(c_hold) if i == 0 or x[1] != c_hold[i - 1][1]]
    o_hold = [(t, v) for t, k, v in oev if k == 'H']
    if [v for _, v in c_hold if True] != [v for _, v in o_hold]:
        bad.append('the hold: chip (bit 14) %s ours %s' % (c_hold, o_hold))
    for (tc, vc), (to, vo) in zip(c_hold, o_hold):
        if abs(tc - to) > tol:
            bad.append('hold %d at %.3f ms (bit 14), ours %.3f ms' % (vc, tc, to))
    cfea = [(t, v) for t, k, v in chip['ev'] if k == 'FEA' and v == 0x1234]
    ofea = [(t, v) for t, k, v in oev if k == 'FA']
    if [v for _, v in cfea] != [v for _, v in ofea] or any(abs(x[0] - y[0]) > tol for x, y in zip(cfea, ofea)):
        bad.append('the park word: chip %s ours %s' % (cfea, ofea))
    cst = [v for t, k, v in chip['ev'] if k == 'STATE']
    ost = [v for t, k, v in oev if k == 'ST']
    cst = [v for i, v in enumerate(cst) if i == 0 or v != cst[i - 1]]
    if cst and cst[0] == 1:
        cst = cst[1:]                               # the A858 post itself (ours: the "a858" command)
    if cst != ost:
        bad.append('the screen state walk: chip %s ours %s' % (cst, ost))
    if z is None or cc is None:
        bad.append('no end record from mw_host')
    else:
        if (z[0], z[1]) != (chip['sready'], chip['sfxready']):
            bad.append('the ready words: chip %d / %d ours %d / %d' % (chip['sready'], chip['sfxready'], z[0], z[1]))
        if abs(z[2] - chip['cnt']) > 3:
            bad.append('the call count MW+8: chip %d ours %d' % (chip['cnt'], z[2]))
        if z[3] != chip['home']:
            bad.append('MW+0xC: chip %d ours %d' % (chip['home'], z[3]))
        for nm, cv, ov in (('RAMDP $0000-$17FF (the pages)', chip['c_pages'], cc[0]),
                           ('RAMDP $1E10-$1E8F (the lines)', chip['c_lines'], cc[1]),
                           ('DRV+0..0x36 (access point, password)', chip['c_drv'], cc[2])):
            if cv != ov:
                bad.append('%s: CRC chip %08X ours %08X' % (nm, cv, ov))
    if chip['state'] != (ost[-1] if ost else 1):
        bad.append('the screen state at the end: chip %d ours %s' % (chip['state'], ost[-1:] or [1]))
    res = dict(chip={k: v for k, v in chip.items() if k != 'ev'}, chip_ev=[e for e in chip['ev'] if e[1] != 'FEA' or e[2] == 0x1234],
               ours_ev=oev, ours_end=z, ours_crc=cc, bad=bad, plant=a.plant)
    if a.json:
        json.dump(res, open(a.json, 'w'), indent=1)
    print('chip: A858 reply ok %s, %d screen calls in %.1f s, state %d, MW+8 %d, MW+0xC %d, ready %d / %d' % (
        chip['ok'], calls, a.seconds, chip['state'], chip['cnt'], chip['home'], chip['sready'], chip['sfxready']))
    print('chip events (ms after the post): %s' % ['%.1f %s %04X' % e for e in res['chip_ev']])
    print('ours events (ms):                %s' % ['%.1f %s %X' % e for e in oev])
    print('CRCs pages / lines / DRV: chip %08X %08X %08X ours %s' % (
        chip['c_pages'], chip['c_lines'], chip['c_drv'], ' '.join('%08X' % x for x in (cc or []))))
    for b in bad:
        print('DIFF', b)
    if a.expect_fail:
        print('PLANT %d %s' % (a.plant, 'CAUGHT' if bad else 'NOT CAUGHT'))
        return 0 if bad else 1
    print('PASS' if not bad else 'FAIL')
    return 0 if not bad else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default=os.path.join(ROOT, 'build', 's1', 'host', 'mw_host.exe'))
    ap.add_argument('--harness')
    ap.add_argument('--rom')
    ap.add_argument('--seconds', type=float, default=3.0)
    ap.add_argument('--tol-ms', type=float, default=1.0)
    ap.add_argument('--plant', type=int, choices=(1, 2))
    ap.add_argument('--expect-fail', action='store_true')
    ap.add_argument('--json')
    sys.exit(run(ap.parse_args()))


if __name__ == '__main__':
    main()
