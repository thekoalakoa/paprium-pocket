#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""mw_oracle.py - the MegaWire port (core/mw) against the cart's chip, tick by tick and post by post, with no module.

    python -I -B tests/equiv/mw_oracle.py [--host <mw_host.exe>] [--runner DIR] [--rom FILE] [--ticks N] [--json OUT]
                                          [--plan full|sweep] [--plant 1|2] [--expect-fail]

The chip side is the cart-engine runner (our test harness outside this tree: Unicorn, the CPU emulator library, running
the cart's program; paths.local.json "equiv": "chip_runner",
"rom"; read in place, nothing copied): its boot snapshot (3 x 810E, C600, the clock trim) with the ADC reading 0 on
the detect pin, as the model's ADC does (a real cart's empty-pin reading is not measured; any value outside 31..60
takes the same path). Our side is tests/s1/mw_host.c with the port's own sources (fwbuild s1 builds it:
build/s1/host/mw_host.exe, the default --host). Both start from the chip's state at the snapshot (the MegaWire
blocks, the MegaWire byte, 81 bit 3, the $1FE6 shadow), then run the same steps. After every step the oracle compares
  - every cart RAM word the step wrote, with its value (the chip: stores to RAMDP inside the TIM7 handler for a tick,
    inside the post for a post; ours: the words a step changed from a fill pattern);
  - a tick: every $1FE6 store, in order (the status helper); a post: the MegaWire bits of $1FE6 after it (the chip's
    dispatcher stores $1FE6 itself around every post, bits 13 / 15, measured: those stores are not the body's);
  - the MegaWire blocks byte for byte: the task block MW (+0 = the MegaWire byte), the driver block DRV, the EEPROM
    record and the E7 staging;
and before every step the MegaWire bits of the $1FE6 shadow (0-2, 4, 5: only MegaWire code writes them) must be equal;
the other bits (the job steps' bit 14, the music's) are then taken from the chip, which the harness does not run.
Masked, and counted with their byte extents (an allow-list row each): B51 the server name (ours), B49
the network text not built yet (the request line, the HTTP request and its length), B50 the driver's two pointer
words (offsets into our MegaWire RAM where the chip keeps its addresses). B49's HTTP request has no fixed size: the
chip writes L bytes at DRV+0x865 and L into its 16-bit length word DRV+0x107A, and L grows with the game packet
(measured: 167 + 2 x the packet length for type 0x24). So that mask is the chip's own extent: DRV+0x865 up to the
largest L the chip has written since its request buffer (DRV+0x865-0x1064) was last all zero (a later, shorter request
leaves the longer one's tail there). The B49 masks are one-sided: the port builds no network text, so in a B49 range
our bytes may only keep what they held (the chip's own, from the seed) or be cleared (the port's init); a byte the port
wrote there is a difference too. A report names the offsets in the chip's network-text areas, not their bytes.
The gates of the posts (core/dispatch/disp.c) are not run here: the chip's post goes through its mailbox, ours runs
the body after the same gates (the A4 body is MW+1 := the low byte; the chip's A4 post must store nothing else); the
gates run on RV32 in tests/equiv/mwboot.py.
Steps (about 4,070 ticks, ~407 s of the cart's time): idle ticks; the A4 posts the game sends (A480, A481 AUTO, A482
FORCED) and a re-init (A401: bit 7 clear), each + 70 ticks; more A4 words (A482, A400, A481, A4C1 with RESTORE, A480)
at other spacings; the attract mode's pair, which the game posts with no module too (A9, then E7 with a packet of the
attract's shape: type 0x24, 13 bytes, our own filler bytes) and the ticks to the task's give-up (451 ticks in state 3:
$1C10 = 0x2485, $1FE6 bit 5); a second pair; an E7 accepted INSIDE state 3 (it stays pending, $1FE6 bit 4 set, until
the next A9); the second give-up; A6 (the result taken); then E7 packets that end in state 2: length 0, the 0x40
flag, the MegaWire menu's types with a wrong length (0x82, 0x83, 0x84) and an unknown type 0x90 (each an error
result), the menu's 0x83 network record with its right length (copied, result 1), and another game packet; then the
MegaWire menu's scan (0x82, length 1: task state 4) and sign-in (0x84, length 0x20, our own filler: state 6, its 'B'
message staged at MW+0x22) with no module, each to its give-up after 451 ticks ($1C10 = 0x8292 / 0x848D) and A6; then the
length sweep (--plan sweep runs only this part, after 20 idle ticks): game packets of types 0x00-0x3F at 1-251 bytes,
each A9, E7, 8 ticks (state 3 step 1 builds the request), a re-init (A401); and a stale tail: a 251-byte request, the
give-up, A6, then a 40-byte request with no re-init between them.
--plant 1 / 2 (with --expect-fail: the B49 mask's own negative controls): after the chip has written a request, flip
the chip's byte just past the mask's extent (1: the strict compare must see it, so the mask ends at the chip's L) or
our byte at the mask's start (2: the one-sided rule must see it).
Exit 0 when every step matches, 1 otherwise (--expect-fail: 0 only when a difference was found, for the planted-bug
harnesses mw_host_bug1..3 and the plants); prints SKIP and exits 0 with no runner or ROM."""
import argparse, json, os, struct, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
MW, DRV, EEP, E7B = 0x20006D70, 0x200100AC, 0x20012A6C, 0x200134EC
MWN, DRVN, EEPN, E7BN = 0x1BC, 0x1140, 0x64, 0x100
G = 0x20006F2C
TIM7, TIM7_RET = 0x08015400, 0x08015414
RAMDP, FE6 = 0x68060000, 0x68040006
MWB = 0x0037                                    # the $1FE6 bits only MegaWire code writes: 0-2 status, 4 E7, 5 result
# allow-list B51: the server name 0x08020EFC writes at DRV+0x1086 is ours (www.koalakoa.com, 16
# characters and a NUL) where the cart's is 25 characters: the bytes that change are +0x1086-+0x109E
B51_DRV = ((0x1086, 0x109F, 'B51 server name'),)
# allow-list B49: not built yet (mw.h): the request line 0x08020EFC writes at DRV+0x10B6 (36 B at the init) and the
# HTTP request 0x08020F8C writes at DRV+0x865 (L bytes) with its 16-bit length L at +0x107A (the cart's network text;
# read only by the AT stack). The request's mask is the chip's own extent (B49_REQ, set per step from the chip's L)
B49_LINE = (0x10B6, 0x10DA, 'B49 request line')
B49_LEN = (0x107A, 0x107C, 'B49 its length')
B49_BUF = (0x865, 0x1065)                       # the chip's request buffer (2,048 B): ours never writes in it
B49_REQ = 'B49 HTTP request'
# allow-list B50: the two pointer words (each side's own reference to the reply buffer DRV+0x65)
B50_DRV = ((0x106C, 0x1070, 'B50 pointer +106C'), (0x1070, 0x1074, 'B50 pointer +1070'))
FIXED = B51_DRV + (B49_LINE, B49_LEN) + B50_DRV
ONE_SIDED = ((B49_LINE[0], B49_LINE[1], B49_LINE[2]), (B49_LEN[0], B49_LEN[1], B49_LEN[2]),
             (B49_BUF[0], B49_BUF[1], B49_REQ))  # the port never writes a byte here (it builds no network text)


def local():
    try:
        return json.load(open(os.path.join(ROOT, 'paths.local.json')))
    except OSError:
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default=os.path.join(ROOT, 'build', 's1', 'host', 'mw_host' + ('.exe' if os.name == 'nt' else '')))
    ap.add_argument('--runner')
    ap.add_argument('--rom')
    ap.add_argument('--ticks', type=int, default=120)
    ap.add_argument('--json')
    ap.add_argument('--plan', choices=('full', 'sweep'), default='full')
    ap.add_argument('--plant', type=int, choices=(1, 2), help='B49 mask control: flip our byte past (1) / inside (2) it')
    ap.add_argument('--expect-fail', action='store_true', help='a planted-bug harness: exit 0 only if a step differs')
    a = ap.parse_args()
    L = local().get('equiv', {})
    runner = a.runner or L.get('chip_runner')
    if not runner or not os.path.isdir(runner):
        print('SKIP: no chip runner (paths.local.json "equiv": "chip_runner")')
        return 0
    if not os.path.isfile(a.host):
        print('SETUP ERROR: no harness %s (tools/fwbuild.py s1 builds it)' % a.host)
        return 2
    sys.path.insert(0, runner)
    import cartmcu
    from cartmcu import Machine
    rom = a.rom or cartmcu.ROM_PATH             # the ROM the runner itself checks (md5) and serves to the chip
    if not os.path.isfile(rom):
        print('SKIP: no ROM')
        return 0
    from host68k import Host
    from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE

    m = Machine(verbose=0)
    m.load_state(os.path.join(runner, 'snap', 'boot.pkl'))
    m.verbose = 0
    h = Host.__new__(Host)
    h.m = m; h.verbose = 0; h.log = []
    st = {'in': False, 'exc': None, 'w': [], 's': [], 'done': 0, 'posting': False, 'pw': [], 'ps': []}

    def exc_now():
        return m.active[-1][0] if m.active else None

    def mem(addr, n):
        return bytes(m.mu.mem_read(addr, n))

    def code(uc, addr, size, ud):
        if addr == TIM7 and not st['in']:
            st['in'] = True; st['exc'] = exc_now(); st['w'] = []; st['s'] = []
            st['fe6'] = struct.unpack('<H', mem(G + 0x10, 2))[0]   # the shadow and 81 bit 3 as the tick starts
            st['f81'] = mem(G + 0xB, 1)[0]
        elif st['in'] and addr == TIM7_RET and exc_now() == st['exc']:
            st['in'] = False; st['done'] += 1
            st['blk'] = (mem(MW, MWN), mem(DRV, DRVN), mem(EEP, EEPN), mem(E7B, E7BN))     # at the handler's return

    def wr(uc, access, addr, size, value, ud):
        if st['in']:
            if exc_now() != st['exc']:
                return
            w, s = st['w'], st['s']
        elif st['posting']:
            w, s = st['pw'], st['ps']
        else:
            return
        if RAMDP <= addr < RAMDP + 0x2000 and size == 2:
            w.append((addr - RAMDP, value & 0xFFFF))
        elif addr == FE6 and size == 2:
            s.append(value & 0xFFFF)

    m.mu.hook_add(UC_HOOK_CODE, code, begin=0x08015400, end=0x08015416)
    m.mu.hook_add(UC_HOOK_MEM_WRITE, wr, begin=0x68040000, end=0x68061FFF)
    h.start_vblank(59.922743)

    host = subprocess.Popen([a.host], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
    tx = open(a.json + '.tx', 'w') if a.json else None     # what the harness was sent (to replay a failure)
    ours = {'sh': 0}

    def send(line):
        if tx:
            tx.write(line + '\n'); tx.flush()
        host.stdin.write(line + '\n'); host.stdin.flush()

    def host_step(cmd):
        send(cmd)
        w, s, d = {}, [], {}
        while True:
            ln = host.stdout.readline()
            if not ln:
                raise SystemExit('mw_host ended (rc %s) at "%s"' % (host.poll(), cmd))
            p = ln.split()
            if p[0] == 'E':
                break
            if p[0] == 'W':
                w[int(p[1], 16)] = int(p[2], 16)
            elif p[0] == 'S':
                s.append(int(p[1], 16))
            elif p[0] == 'D':
                d[p[1]] = bytes.fromhex(p[2]) if len(p) > 2 else b''
        if s:
            ours['sh'] = s[-1]
        return w, s, d['mw'], d['drv'], d['eep'], d['e7b']

    def seed():
        ours['drv'] = mem(DRV, DRVN)            # what ours holds after the seed (the one-sided B49 rule's start)
        send('rom ' + rom.replace('\\', '/'))
        send('set mw 0 ' + mem(MW, MWN).hex())
        send('set drv 0 ' + mem(DRV, DRVN).hex())
        send('set eep 0 ' + mem(EEP, EEPN).hex())
        send('set e7b 0 ' + mem(E7B, E7BN).hex())
        send('f81 %d' % mem(G + 0xB, 1)[0])
        ours['sh'] = struct.unpack('<H', mem(G + 0x10, 2))[0]
        send('fe6 %04X' % ours['sh'])

    b49 = {'lmax': 0}                           # the largest request length the chip wrote since its buffer was clear

    def masks(cdrv):
        """the masks for this step: the fixed ones and B49's request at the chip's own extent"""
        lo, hi = B49_BUF
        if not any(cdrv[lo:hi]):
            b49['lmax'] = 0
        ln = struct.unpack('<H', cdrv[B49_LEN[0]:B49_LEN[0] + 2])[0]
        b49['lmax'] = min(max(b49['lmax'], ln), hi - lo)
        return FIXED + (((lo, lo + b49['lmax'], B49_REQ),) if b49['lmax'] else ())

    def text_area(i):
        """a DRV offset where the chip keeps network text: a report names the offset, not the byte"""
        return B49_BUF[0] <= i < B49_BUF[1] or 0x1086 <= i < 0x10F6

    def mask_drv(b, ms):
        b = bytearray(b)
        for lo, hi, _ in ms:
            b[lo:hi] = bytes(hi - lo)
        return bytes(b)

    seed()
    names = [n for _, _, n in FIXED] + [B49_REQ]
    rep = {'steps': 0, 'ticks': 0, 'posts': 0, 'diffs': [], 'writes_compared': 0, 'stores_compared': 0,
           'masked': {n: {'steps': 0, 'offsets': []} for n in names}, 'plants': 0,
           'coverage': {'chip_states_seen': [], 'e7_in_state3': 0, 'results_1c10': {}, 'post_replies': {}, 'post_fe6': {},
                        'request_len': []}}
    cov = rep['coverage']

    def count_masked(x, y, ms):                 # a masked difference is counted, never dropped (allow-list rule)
        for lo, hi, n in ms:
            offs = [i for i in range(lo, hi) if x[i] != y[i]]
            if offs:
                m_ = rep['masked'][n]
                m_['steps'] += 1
                m_['offs'] = m_.get('offs', set()) | set(offs)
                m_['offsets'] = [min(m_['offs']), max(m_['offs']), len(m_['offs'])]

    def plant(cdrv, odrv):
        """--plant (the comparator's own negative controls), once the chip has written a request: 1 = the chip's byte
           just past the mask's extent changed (the strict compare must see it: the mask ends at the chip's L), 2 =
           our byte at the mask's start changed (the one-sided rule must see it)"""
        if not a.plant or not b49['lmax'] or B49_BUF[0] + b49['lmax'] >= B49_BUF[1]:
            return cdrv, odrv
        c, o = bytearray(cdrv), bytearray(odrv)
        if a.plant == 1:
            c[B49_BUF[0] + b49['lmax']] ^= 0x5A
        else:
            o[B49_BUF[0]] ^= 0x5A
        rep['plants'] += 1
        return bytes(c), bytes(o)

    def compare(tag, c, o):
        cw, cs, cmw, cdrv, ceep, ce7 = c
        ow, os_, omw, odrv, oeep, oe7 = o
        rep['steps'] += 1
        rep['writes_compared'] += len(cw)
        rep['stores_compared'] += len(cs)
        if cmw[2] not in cov['chip_states_seen']:
            cov['chip_states_seen'].append(cmw[2])
        if 0x1C10 in cw:
            k = '%04X' % cw[0x1C10]
            cov['results_1c10'][k] = cov['results_1c10'].get(k, 0) + 1
        bad = []
        if cw != ow:
            ks = sorted(set(cw) | set(ow))
            bad.append('RAMDP ' + ' '.join('$%04X chip %s ours %s' % (k, '%04X' % cw[k] if k in cw else '-',
                                                                    '%04X' % ow[k] if k in ow else '-')
                                            for k in ks if cw.get(k) != ow.get(k))[:400])
        ms = masks(cdrv)
        prev, ours['drv'] = ours['drv'], odrv
        cdrv, odrv = plant(cdrv, odrv)
        count_masked(cdrv, odrv, ms)
        for lo, hi, n in ONE_SIDED:             # the port writes no network text: in a B49 range ours keeps what it held
            offs = [i for i in range(lo, hi) if odrv[i] not in (prev[i], 0)]    # (the chip's, from the seed) or is
            if offs:                                                            # cleared (its init): never a new byte
                bad.append('DRV %s: ours wrote %d B, +%X-+%X' % (n, len(offs), offs[0], offs[-1]))
        if cs != os_:
            bad.append('$1FE6 chip %s ours %s' % (['%04X' % x for x in cs], ['%04X' % x for x in os_]))
        for name, x, y in (('MW', cmw, omw), ('DRV', mask_drv(cdrv, ms), mask_drv(odrv, ms)), ('EEP', ceep, oeep), ('E7B', ce7, oe7)):
            if x != y:
                offs = [i for i in range(len(x)) if x[i] != y[i]]
                bad.append('%s +%s (%d B, +%X-+%X)' % (name, ','.join(
                    ('%X(%02X/%02X)' % (i, x[i], y[i])) if name != 'DRV' or not text_area(i) else '%X' % i
                    for i in offs[:12]), len(offs), offs[0], offs[-1]))
        if bad:
            rep['diffs'].append({'step': tag, 'what': bad})
        return not bad

    def bits(tag, chip_sh):
        """before a step: the MegaWire bits of both shadows equal; then ours takes the chip's other bits"""
        if (chip_sh ^ ours['sh']) & MWB:
            rep['diffs'].append({'step': tag, 'what': ['$1FE6 MegaWire bits before the step: chip %04X ours %04X' % (
                chip_sh & MWB, ours['sh'] & MWB)]})
        ours['sh'] = chip_sh
        send('fe6 %04X' % chip_sh)

    def chip_tick():
        n = st['done']
        while st['done'] == n:
            m.run(seconds=0.5, until=lambda mm: st['done'] != n)
        w = {}
        for adr, v in st['w']:
            w[adr] = v
        return (w, list(st['s'])) + st['blk']

    def ticks(n, tag):
        for i in range(n):
            c = chip_tick()
            t = '%s tick %d' % (tag, i)
            bits(t, st['fe6'])
            send('f81 %d' % st['f81'])
            compare(t, c, host_step('tick'))
            rep['ticks'] += 1

    def chip_post(word, args, tag):
        """the real post through the chip's mailbox; its RAMDP words and $1FE6 stores (no tick, no VBlank inside)"""
        n0, v0 = st['done'], h.vbl_count
        bits(tag, struct.unpack('<H', mem(G + 0x10, 2))[0])
        st['pw'], st['ps'], st['posting'] = [], [], True
        ok = h.post(word, args)
        st['posting'] = False
        if not ok:
            raise SystemExit('the chip did not finish the post of %04X' % word)
        if st['done'] != n0 or h.vbl_count != v0:
            raise SystemExit('a TIM7 tick or a VBlank ran inside the post of %04X: rerun' % word)
        rep['posts'] += 1
        k = '%04X' % word
        cov['post_replies'].setdefault(k, []).append('%04X' % m.reg68(0x1FEA))
        w = {}
        for adr, v in st['pw']:
            w[adr] = v
        return ((w, list(st['ps']), mem(MW, MWN), mem(DRV, DRVN), mem(EEP, EEPN), mem(E7B, E7BN)),
                struct.unpack('<H', mem(G + 0x10, 2))[0])

    def post_a4(word, n):
        tag = 'post %04X' % word
        sh0 = struct.unpack('<H', mem(G + 0x10, 2))[0]
        c, sh = chip_post(word, (), tag)
        if c[0] or (sh ^ sh0) & MWB or c[2][1] != (word & 0xFF):    # the chip's A4: MW+1 := the low byte, nothing else
            rep['diffs'].append({'step': tag, 'what': ['the chip\'s A4 wrote %s, $1FE6 %04X -> %04X, MW+1 %02X' % (
                c[0], sh0, sh, c[2][1])]})
        rep['steps'] += 1
        send('req %02X' % (word & 0xFF))
        ticks(n, 'after %04X' % word)

    def post(word, args, cmd, tag):
        sh0 = struct.unpack('<H', mem(G + 0x10, 2))[0]
        c, sh = chip_post(word, args, tag)
        if (sh & 0x0200) and not (sh0 & 0x0200):    # a refusal ($1FE6 bit 9): the plan sends only accepted posts
            rep['diffs'].append({'step': tag, 'what': ['the chip refused the post (a plan error: the harness runs bodies)']})
        o = host_step(cmd)
        cov['post_fe6'].setdefault(tag.split()[0], []).append(['%04X' % x for x in c[1]])
        compare(tag, (c[0], [sh & MWB]) + c[2:], (o[0], [ours['sh'] & MWB]) + o[2:])

    def a9(tag):
        post(0xA900, (), 'a9', 'A9 ' + tag)

    def a6(tag):
        post(0xA600, (), 'a6', 'A6 ' + tag)

    def e7(pkt, tag):
        if mem(MW, MWN)[2] == 3:
            cov['e7_in_state3'] += 1
        post(0xE700, pkt, 'e7 ' + ' '.join('%04X' % x for x in pkt), 'E7 ' + tag)

    def packet(t, n, fill=0x11):
        """an E7 packet as the game stores it at $1E10: type << 8, the length, then n bytes (our own filler)"""
        b = bytes((fill + i) & 0xFF for i in range(n)) + (b'\0' if n & 1 else b'')
        return (t << 8, n) + tuple((b[i] << 8) | b[i + 1] for i in range(0, len(b), 2))

    def request_len():
        return struct.unpack('<H', mem(DRV + B49_LEN[0], 2))[0]

    def request(typ, n, tag, fill, reinit=True):
        """A9, E7 with a game packet, 8 ticks (state 3 step 1 builds the request); the chip's length L recorded"""
        a9('before ' + tag)
        ticks(3, 'after A9 ' + tag)
        s0 = mem(MW, MWN)[2]
        e7(packet(typ, n, fill), tag)
        ticks(8, 'after E7 ' + tag)
        ln = request_len()
        tail = sum(1 for x in mem(DRV + B49_BUF[0] + ln, B49_BUF[1] - B49_BUF[0] - ln) if x) if ln else 0
        cov['request_len'].append({'tag': tag, 'type': typ, 'n': n, 'state_before': s0, 'state': mem(MW, MWN)[2],
                                   'L': ln, 'chip_bytes_past_L': tail})
        if s0 != 2:                             # the plan wants each request built: the E7 must find state 2
            rep['diffs'].append({'step': 'E7 ' + tag, 'what': ['plan error: the chip was in task state %d at the E7' % s0]})
        if reinit:
            post_a4(0xA401, 20)

    # the length sweep: game packet types (below 0x80, no 0x40 flag) at 1-251 bytes, each followed by a re-init
    SWEEP = ((0x24, 13), (0x24, 40), (0x24, 80), (0x24, 120), (0x24, 160), (0x24, 200), (0x24, 251), (0x21, 16),
             (0x22, 1), (0x25, 81), (0x27, 129), (0x28, 2), (0x00, 1), (0x01, 251), (0x3F, 251))
    if a.plan == 'sweep':
        ticks(20, 'idle')
        for typ, n in SWEEP:
            request(typ, n, 'sweep %02X/%d' % (typ, n), 0x41)
    else:
        full_plan(a, ticks, post_a4, a9, a6, e7, packet)
        post_a4(0xA401, 20)                     # step 6's game packet left state 3: a re-init first
        for typ, n in SWEEP:
            request(typ, n, 'sweep %02X/%d' % (typ, n), 0x41)
        # a stale tail: a long request, its give-up, then a shorter one with no re-init between them
        request(0x24, 251, 'stale 251', 0x61, reinit=False)
        ticks(470, 'after stale 251 (to the give-up)')
        a6('stale')
        ticks(3, 'after A6 stale')
        request(0x24, 40, 'stale 40 (no re-init)', 0x71)
    host.stdin.close(); host.wait()
    ok = not rep['diffs']
    print('mw_oracle: %d steps (%d ticks, %d posts), %d RAMDP words and %d $1FE6 stores compared, %d steps differ -> %s' % (
        rep['steps'], rep['ticks'], rep['posts'], rep['writes_compared'], rep['stores_compared'], len(rep['diffs']),
        'PASS' if ok else 'FAIL'))
    for n, m_ in rep['masked'].items():
        o_ = m_['offsets']
        m_.pop('offs', None)
        print('   masked %-20s differs on %d steps, bytes %s' % (n, m_['steps'], ('+%X-+%X (%d)' % tuple(o_)) if o_ else 'none'))
    rl = cov['request_len']
    print('   B49 request length L (the chip\'s DRV+0x107A) per packet: %s' % ', '.join(
        '%s L=%d%s' % (r['tag'].split(' ', 1)[1], r['L'], '' if r['L'] == 167 + 2 * r['n'] else ' (not 167+2n)') for r in rl))
    print('   B49 request: largest L %d (the mask ends at DRV+0x%X); chip bytes past L at the stale case: %s' % (
        max([r['L'] for r in rl] or [0]), B49_BUF[0] + max([r['L'] for r in rl] or [0]) - 1,
        [r['chip_bytes_past_L'] for r in rl if r['tag'].startswith('stale')]))
    if a.plant:
        print('   plant %d applied on %d steps' % (a.plant, rep['plants']))
    print('   coverage: chip task states %s, E7 inside state 3 %d, $1C10 results %s' % (
        sorted(cov['chip_states_seen']), cov['e7_in_state3'], cov['results_1c10']))
    for d in rep['diffs'][:10]:
        print('  ', d['step'], '|', ' | '.join(d['what'])[:600])
    if a.json:
        json.dump(rep, open(a.json, 'w'), indent=1)
    if a.expect_fail:
        print('expect-fail: %s' % ('caught (a step differs)' if not ok else 'NOT CAUGHT'))
        return 0 if not ok else 1
    return 0 if ok else 1


def full_plan(a, ticks, post_a4, a9, a6, e7, packet):
    """steps 1-6 of the plan (the module docstring)"""
    # 1: idle, the game's A4 posts and a re-init
    ticks(a.ticks, 'idle')
    for word in (0xA480, 0xA481, 0xA482, 0xA401):
        post_a4(word, 70)
    # 2: more A4 words at other spacings (RESTORE, profile OFF with a re-init)
    for word, n in ((0xA482, 40), (0xA400, 90), (0xA481, 33), (0xA4C1, 29), (0xA480, 61)):
        post_a4(word, n)
    # 3: the attract mode's pairs (no module): state 3, the give-up after 451 ticks
    pkt = packet(0x24, 13, 0x01)                # the attract's shape: type 0x24, 13 bytes
    for k, n in ((1, 470), (2, 30)):
        a9('#%d' % k)
        ticks(3, 'after A9 #%d' % k)
        e7(pkt, 'attract #%d' % k)
        ticks(n, 'after E7 attract #%d' % k)
    a9('#3 (state 3)')
    ticks(5, 'after A9 #3')
    # 4: an E7 accepted inside state 3 (pending, bit 4 set, until the next A9), then the second give-up
    e7(packet(0x24, 13, 0x51), 'B inside state 3')
    ticks(50, 'after E7 B (state 3)')
    a9('#4 (clears E7 B)')
    ticks(380, 'after A9 #4 (to the give-up)')
    # 5: A6 takes the result
    a6('#1')
    ticks(4, 'after A6 #1')
    # 6: packets that end in state 2: errors, the 0x40 flag, the menu's record, then a game packet again
    for p, tag, n in ((packet(0x24, 0), 'length 0', 6), (packet(0x64, 5), '0x40 flag', 6),
                      (packet(0x82, 2), '0x82 length 2', 6), (packet(0x83, 5), '0x83 length 5', 6),
                      (packet(0x84, 3), '0x84 length 3', 6), (packet(0x90, 4), 'type 0x90', 6),
                      (packet(0x83, 0x37, 0x21), '0x83 record (length 0x37)', 6), (packet(0x25, 9, 0xA1), 'game 0x25', 20)):
        e7(p, tag)
        ticks(n, 'after E7 ' + tag)
    a9('#5')
    ticks(5, 'after A9 #5')
    a6('#2')
    ticks(3, 'after A6 #2')
    # 7: the MegaWire menu's scan and sign-in packets with their right lengths, no module: states 4 and 6, the driver's
    # op (7 / 4) never done, the give-up after 451 ticks, A6 (first the game packet of step 6 to its own give-up)
    ticks(450, 'to the game 0x25 give-up')
    a6('#3 (the game 0x25 give-up)')
    ticks(4, 'after A6 #3')
    for p, tag in ((packet(0x82, 1, 0x0C), 'scan 0x82 (state 4)'), (packet(0x84, 0x20, 0x41), 'sign-in 0x84 (state 6)')):
        e7(p, tag)
        ticks(470, 'after E7 ' + tag + ' (to the give-up)')
        a6(tag)
        ticks(4, 'after A6 ' + tag)


if __name__ == '__main__':
    sys.exit(main())
