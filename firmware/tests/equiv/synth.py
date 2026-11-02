#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""synth.py - stage 0 (the tree's first step: the 0.2.6 firmware moved in): the command handlers the three captures
never post (00, 84, E0, F2, the AC/C1/F0 aliases, unknown words), posted synthetically into a booted game, on THREE sides at once: the reference host build (final
0.2.6), the paprium-fw host build, and the paprium-fw RV32 image in rvboard's call mode. Then the capture continues, so
any state the synthetic posts left behind is compared on every later post.

Sequence: replay CAPTURE from power-on to --at (default 3600, in stage $18 after its start at 3551), post the list
below (each with its own 16 argument words; unlisted words keep the value in RAM), then replay on to --to.
Per post: RAMDP 8 KB, FPGAIO 24 B (time 0 on all three), printf text (RV32: arguments formatted with C rules), audio
log, BRAM $000-$FFF, SDRAM (host 'D' diff every post + RV32 written granules; union contents). Checkpoints at the end.
Exit status (the rig fails loudly): 0 = PASS; 1 = FAIL: any difference of NEW or RV32 against REF on any post, an RV32
fault (boot included), the end checkpoints not equal on all three, the synthetic list not posted (--at past the
capture's end), or no post at all; 2 = bad arguments. The last line printed is 'RESULT: PASS' or 'RESULT: FAIL: ...'.
usage: python -I -B synth.py OUTDIR --ref EXE --new EXE --build POCKET_BUILD --capture CAP --rom ROM [--at F] [--to F]
"""
import argparse, json, mmap, os, struct, sys, time, collections, hashlib
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hostside import HostSide, runs, SDR_SPAN, OFF_FLASH, BRAM_N   # noqa: E402
import rvboard   # noqa: E402

# (word, {arg index: value}, what)
SYNTH = [
    (0x00AA, {}, 'cmd_00 0xAA -> reply 00FF'),
    (0x0055, {}, 'cmd_00 other -> reply 0'),
    (0xE004, {1: 0x0200}, 'save write slot 4 (0x200 B from RAMDP $0200)'),
    (0xE001, {1: 0x0300}, 'save write slot 1 (0x100 B from $0300)'),
    (0xE002, {1: 0x0400}, 'save write slot 2'),
    (0xE003, {1: 0x0500}, 'save write slot 3'),
    (0xE005, {1: 0x0600}, 'save write, slot 5 = no copy'),
    (0xDF04, {0: 0x1C10}, 'save read slot 4 back into $1C10'),
    (0xDF01, {0: 0x1D00}, 'save read slot 1 into $1D00'),
    (0xDF00, {0: 0x1D00}, 'save read slot 0 = no copy'),
    (0x8400, {}, 'cmd_84 sdram_en = 0'),
    (0xC100, {}, 'C1 = alias of 81 (D25): sdram_en = 1'),
    (0xF201, {0: 1}, 'F2 unpack block 1 to the scratch, pointer'),
    (0xF201, {0: 500}, 'F2 block 500'),
    (0xF201, {0: 12326}, 'F2 block 12326 (the last)'),
    (0xAC28, {}, 'AC = EC alias, refused by the gate (D08)'),
    (0xF000, {}, 'F0 = alias of B0 (D20)'),
    (0xEC28, {}, 'EC $28 (budget back)'),
    (0x8E00, {}, 'unknown: 8E'),
    (0x9000, {}, 'unknown: 90'),
    (0xFF12, {}, 'unknown: FF'),
    (0x8100, {}, '81 (D25)'),
]

# Stage 1 (our new firmware, FW_S1; the chip lockstep, tests/equiv/chiplock_s1.py). Two lists, each entry (word,
# {arg index: value}, what, mailbox). SYNTH_S1_MID is posted INTO a booted game on the chip, the stage-1 host build and final 0.2.6, and the
# capture then continues with every field compared: SYNTH with the arguments the game itself always gives (the E0 key
# 0xBEEF in argument 0, EC's (0, n)), so the chip's gates accept them as 0.2.6 does, plus 82 and mailbox-A words.
def _game_args(w, sets):
    """the arguments the game always gives: E0's key 0xBEEF in argument 0, EC's (0, n)"""
    out = dict(sets)
    if w >> 8 == 0xE0:
        out[0] = 0xBEEF
    elif w == 0xEC28:
        out.update({0: 0x0000, 1: 0x0028})
    return out


SYNTH_S1_MID = [(w, _game_args(w, sets), what + (' (+ the game BEEF key)' if w >> 8 == 0xE0 else
                                                   ' (+ the game (0, n))' if w == 0xEC28 else ''), 'B')
                for w, sets, what in SYNTH] + [
    (0x8201, {}, '82 low bit 1: $1FF2 := 1', 'B'),
    (0x8200, {}, '82 low bit 0: $1FF2 := 0', 'B'),
    (0x8180, {}, 'mailbox A: 81 (low byte dropped)', 'A'),
    (0x9C80, {}, 'mailbox A: index 1C, default refusal (bit 10)', 'A'),
    (0xDA80, {}, 'mailbox A: DA, queue full -> 5 else 7', 'A'),
    (0x9400, {}, 'mailbox A: no request bit (7): finish only', 'A'),
]

# SYNTH_S1_TAIL is posted after the capture's last frame: the chip's refusal forms (every gate of the dispatcher, which
# works as the chip's, that no capture reaches; 0.2.6 acted on several of them, which allow-list row B28 covers, so only
# the chip-referenced fields are compared from here on), a second C6, EXTI 13 (the console reset line, MiSTer only:
# the chip just acknowledges, so it must write nothing; the Pocket board has no such source), then 85, the fatal post
# that stops both MCUs (nothing can follow it).
SYNTH_S1_TAIL = [
    (0x8700, {}, 'index 07: default refusal (2)', 'B'),
    (0xBF00, {}, 'index 3F, above the table: default refusal', 'B'),
    (0x9A00, {}, 'DA without arguments: refusal 7', 'B'),
    (0xDA03, {0: 0x9000, 1: 0x0016, 2: 0xAFC8}, 'DA mode 3: refusal 7', 'B'),
    (0xAC00, {}, 'EC without arguments: refusal 7', 'B'),
    (0xEC00, {0: 0x0000, 1: 0x0081}, 'EC a1 above 0x80: refusal 7', 'B'),
    (0xB200, {}, 'F2 without arguments: refusal 7', 'B'),
    (0x8600, {}, 'C6 without arguments: refusal 7', 'B'),
    (0xD000, {0: 0x0001}, 'D0 low byte 0: refusal 7', 'B'),
    (0xD005, {0: 0x001A}, 'D0 voice above 0x19: refusal 7', 'B'),
    (0xD101, {0: 0x0100, 1: 0x0080, 2: 0x0080, 3: 0x0000}, 'D1 a0 low byte 0: refusal 7', 'B'),
    (0x9101, {}, 'D1 without arguments', 'B'),
    (0xD300, {0: 0x0001}, 'D3 low byte 0: refusal 7', 'B'),
    (0x9301, {}, 'D3 without arguments: refusal 7', 'B'),
    (0xD502, {0: 0x0001}, 'D5 low byte 2: refusal 7', 'B'),
    (0xD608, {0: 0x0001}, 'D6 sub-command 8: refusal 7', 'B'),
    (0xDF00, {0: 0x1E00}, 'DF destination above 0x1DFF: refusal 7', 'B'),
    (0xE004, {0: 0x1234, 1: 0x0800}, 'E0 without the BEEF key: refusal 7', 'B'),
    (0xE700, {0: 0x0000, 1: 0x00FC}, 'E7 length above 0xFB: refusal 7', 'B'),
    (0xA400, {}, 'A4 without arguments: accepted', 'B'),
    (0xE400, {0: 0x0000}, 'A4 with arguments: refusal 7', 'B'),
    (0xA600, {}, 'A6', 'B'),
    (0xA900, {}, 'A9', 'B'),
    (0xAA00, {}, 'AA low byte not 0x58: refusal 7', 'B'),
    (0xF600, {0: 0x0000}, 'B6 with arguments: refusal 7', 'B'),
    (0xB500, {}, 'F5 without arguments: refusal 7', 'B'),
    (0xB400, {}, 'F4 without arguments: refusal 7', 'B'),
    (0xF400, {0: 0x0090, 1: 0x0000}, 'F4 source above 8 MB: refusal 7', 'B'),
    (0x9B00, {}, 'DB without arguments: refusal 7', 'B'),
    (0xDB07, {0: 0x0000, 1: 0x9000, 2: 0x0080}, 'DB mode 7: refusal 7', 'B'),
    (0xDB06, {0: 0x0000, 1: 0xFF00, 2: 0x2000}, 'DB06 past the workspace: refusal 7', 'B'),
    (0x9F00, {}, 'DF without arguments: refusal 7', 'B'),
    (0xA000, {}, 'E0 without arguments: refusal 7', 'B'),
    (0x0042, {}, 'no request bit (15): finish only', 'B'),
    (0xC600, {}, 'a second C6 (with the arguments in RAM): completes, no job', 'B'),
    (0x0000, {}, 'EXTI 13 pulse on the chip (console reset line): acknowledge only', 'EXTI13'),
    (0x8500, {}, '85: the fatal halt ($1FEE := 0xAF5B, $1FE4 := 0x4000)', 'B'),
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--ref', required=True)
    ap.add_argument('--new', required=True)
    ap.add_argument('--build', required=True)
    ap.add_argument('--capture', required=True)
    ap.add_argument('--rom', required=True)
    ap.add_argument('--at', type=int, default=3600)
    ap.add_argument('--to', type=int, default=6000)
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    rom = open(a.rom, 'rb').read()
    hosts = [HostSide('ref', a.ref), HostSide('new', a.new)]
    for h in hosts:
        h.q_load(rom); h.q_opt(0); h.q_reset(); h.q_shadow(); h.flush()
    for h in hosts:
        for _ in range(4):
            h.k()
    img = rvboard.Image(a.build)
    bd = rvboard.Board(img, rom, 0, 'call')
    ok, _ = bd.boot()
    if not ok:
        open(os.path.join(a.out, 'summary.json'), 'w').write(json.dumps(
            {'result': 'FAIL', 'fail_reasons': ['RV32 boot fault: %s' % bd.fault]}, indent=1, default=str))
        print('RESULT: FAIL: RV32 boot fault: %s' % bd.fault)
        for h in hosts:
            h.close()
        return 1
    bd.gran = set()
    fails = collections.Counter()
    first = []
    rows = []
    stats = {'posts': 0, 'synth_posts': 0}

    def post(word, args, f, tag):
        for h in hosts:
            h.q_w(0x1E10, args); h.q_post(word); h.q_diff(); h.q_bram(0, BRAM_N); h.flush()
        bd.w68(0x1E10, args)
        bd.w68(0x1FEA, struct.pack('<H', word))
        okp = bd.post()
        rv = [bd.mem(rvboard.RAMDP, 0x2000), bd.fpgaio24(), ''.join(bd.pf).encode('latin-1'), bytes(bd.au),
              set(bd.gran), bd.mem(rvboard.BRM, BRAM_N)]
        H = []
        for h in hosts:
            ram, fp, txt, au = h.r_post()
            H.append([ram, fp, txt, au, set(h.r_diff()), h.read(BRAM_N)])
        G = sorted(rv[4] | H[0][4] | H[1][4])
        sd = []
        if G:
            rr = runs(G)
            for h in hosts:
                for g, n in rr:
                    h.q_mem(g, n)
                h.flush()
            for h in hosts:
                sd.append(b''.join(h.read(n) for g, n in rr))
            sd.append(b''.join(bd.mem(rvboard.SDR + g, n) for g, n in rr))
        else:
            sd = [b'', b'', b'']
        sides = {'ref': H[0][:4] + [sd[0], H[0][5]], 'new': H[1][:4] + [sd[1], H[1][5]], 'rv32': rv[:4] + [sd[2], rv[5]]}
        bad = []
        names = ('ramdp', 'fpgaio', 'printf', 'audio', 'sdram', 'bram')
        for other in ('new', 'rv32'):
            for k, nm in enumerate(names):
                if sides[other][k] != sides['ref'][k]:
                    bad.append('%s:%s' % (other, nm))
        if not okp:
            bad.append('rv32:fault %s' % bd.fault)
        for b in bad:
            fails[b] += 1
        stats['posts'] += 1
        if tag:
            ref = sides['ref']
            rows.append({'frame': f, 'post': '%04X' % word, 'what': tag, 'reply': '%04X' % struct.unpack_from('<H', ref[0], 0x1FEA)[0],
                         '1FE4': '%04X' % struct.unpack_from('<H', ref[0], 0x1FE4)[0], '1FE6': '%04X' % struct.unpack_from('<H', ref[0], 0x1FE6)[0],
                         'sdram_ptr': '%X' % struct.unpack_from('<I', ref[1], 8)[0], 'ctrl': '%X' % struct.unpack_from('<I', ref[1], 0)[0],
                         'printf': ref[2].decode('latin-1')[:80], 'sdram_granules': len(G), 'bram_md5': hashlib.md5(ref[5]).hexdigest()[:8],
                         'differences': bad})
            stats['synth_posts'] += 1
        elif bad and len(first) < 50:
            first.append({'frame': f, 'post': '%04X' % word, 'bad': bad})
        return okp

    capf = open(a.capture, 'rb')
    d = mmap.mmap(capf.fileno(), 0, access=mmap.ACCESS_READ)
    o, n = 0, len(d)
    injected = False
    frame = -1
    while o + 20 <= n:
        t, ln, f = struct.unpack_from('<HHI', d, o)
        po = o + 20
        o = po + ln
        if f > a.to:
            break
        if t == 1:
            frame = f
            if f >= a.at and not injected:
                cur = bd.mem(rvboard.RAMDP + 0x1E10, 32)
                for word, sets, what in SYNTH:
                    w16 = list(struct.unpack('<16H', cur))
                    for i, v in sets.items():
                        w16[i] = v
                    post(word, struct.pack('<16H', *w16), f, what)
                injected = True
            continue
        if t == 3:
            ad, wd, v = struct.unpack_from('<HHH', d, po)
            if ad >= 0x2000:
                continue
            off, data = (ad & ~1, struct.pack('<H', v & 0xFFFF)) if wd == 2 else (ad ^ 1, bytes([v & 0xFF]))
            bd.w68(off, data)
            for h in hosts:
                h.q_w(off, data)
            continue
        if t == 2:
            wv = struct.unpack_from('<18H', d, po)
            if not post(wv[0], struct.pack('<16H', *wv[2:18]), f, None):
                break
    # end checkpoint: SDRAM, flash, BRAM 64 KB, RAMDP on all three
    res = {}
    for h in hosts:
        h.q_mem(0, SDR_SPAN); h.q_mem(OFF_FLASH, len(rom)); h.q_bram(0, 0x10000); h.q_all(); h.flush()
    for h in hosts:
        res[h.name] = [hashlib.md5(h.read(SDR_SPAN)).hexdigest(), hashlib.md5(h.read(len(rom))).hexdigest(),
                       hashlib.md5(h.read(0x10000)).hexdigest(), hashlib.md5(h.r_all()[0]).hexdigest()]
    res['rv32'] = [hashlib.md5(bd.mem(rvboard.SDR, SDR_SPAN)).hexdigest(), hashlib.md5(bd.mem(rvboard.FLA, len(rom))).hexdigest(),
                   hashlib.md5(bd.mem(rvboard.BRM, 0x10000)).hexdigest(), hashlib.md5(bd.mem(rvboard.RAMDP, 0x2000)).hexdigest()]
    summ = {'at': a.at, 'to': frame, 'posts': stats['posts'], 'synth_posts': stats['synth_posts'], 'failures': dict(fails),
            'end_checkpoint_equal': res['ref'] == res['new'] == res['rv32'], 'end_checkpoint': res,
            'rv32_fault': bd.fault, 'synth_rows': rows, 'first_capture_post_failures': first, 'wall_s': round(time.time() - t0)}
    reasons = []
    if not stats['posts']:
        reasons.append('no post at all: nothing was compared')
    if stats['synth_posts'] != len(SYNTH):
        reasons.append('%d of %d synthetic posts made (--at %d past the end of the replay?)' % (
            stats['synth_posts'], len(SYNTH), a.at))
    if fails:
        reasons.append('differences against REF: %s' % dict(fails))
    if not summ['end_checkpoint_equal']:
        reasons.append('end checkpoints differ (SDRAM / flash / BRAM / RAMDP md5s: %s)' % res)
    if bd.fault is not None and not any(k.startswith('rv32:fault') for k in fails):
        reasons.append('RV32 fault: %s' % bd.fault)
    summ['result'] = 'FAIL' if reasons else 'PASS'
    summ['fail_reasons'] = reasons
    open(os.path.join(a.out, 'summary.json'), 'w').write(json.dumps(summ, indent=1))
    print(json.dumps({k: v for k, v in summ.items() if k not in ('synth_rows', 'end_checkpoint', 'fail_reasons')}, indent=1))
    for r in rows:
        print(r['post'], r['reply'], r['1FE4'], r['1FE6'], r['sdram_ptr'], r['ctrl'], r['sdram_granules'], r['bram_md5'], repr(r['printf']), r['differences'], r['what'])
    print('RESULT: PASS' if not reasons else 'RESULT: FAIL: ' + ' | '.join(reasons))
    for h in hosts:
        h.close()
    return 1 if reasons else 0


if __name__ == '__main__':
    sys.exit(main())
