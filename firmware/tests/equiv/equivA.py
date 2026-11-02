#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""equivA.py - rig (a) of stage 0 (the tree's first step): several HOST builds of the cart firmware on one capture
recorded in GPGX (the Genesis Plus GX emulator), every 68000-visible effect compared per post against the first side
(the reference).

Input stream (the same for every side, as rvcost.py / rvlock4.py feed the RV32 images): 'L' ROM, 'O' option word,
'R' = ppm_reset(), 'S'; then every capture record in order from power-on: RAMW (type 3) -> raw cart-RAM write
(68000 word A = MCU halfword A, byte A -> MCU byte A^1; addresses >= $2000 dropped); CMD (type 2) -> the record's 16
argument words written to $1E10 (forced, as rvlock does; mismatches against the replayed RAM are counted), then 'P'
(reg_cmd := word; ppm_cmd_handler()). Nothing is skipped (no boot snapshot: both sides are ours).

Per post, every side vs the reference:
  ramdp     the 8 KB RAMDP after the post ($0000-$1FDF cart RAM + $1FE0-$1FFF registers): the whole 68000 view
  fpgaio    the 24-byte FPGAIO block (ctrl incl. md_rst/sdram_en, ms time, sdram_ptr = stream-window pointer, volumes,
            stream_cnt)
  printf    the printf text the post produced (TEST builds; RELEASE compiles it out)
  audio     the audio entry points called (sfx_play/loop/stop, mdp_*) with their argument and $1E10-$1E15
  sdram     the 256-byte SDRAM granules the post changed (list) AND their new contents (the $C000 stream tape the
            68000 DMAs from is SDRAM at sdram_ptr). By default the diff is taken after every post EXCEPT 0xAD (69 % of
            posts; an 8 MB scan costs ~1 ms per side): an AD's SDRAM changes are compared, cumulatively, at the next
            non-AD post (the frame's AF). The 68000 reads the stream window only after AF/DA/DB, never between ADs.
            --sdram-every-post restores the per-AD diff.
  bram      battery RAM $000-$FFF after the post (saves $000-$8FF; TEST snapshot window $900-$FFF)
Per AF (internal, not 68000-visible, reported apart): the 'G' globals block (slots, handles, unpack/stream state).
Checkpoints (start, every --full-every AFs, end): whole SDRAM 8 MB, flash 8 MB (ppm_reset patches the ROM), BRAM 64 KB.

Allow masks per side (--side NAME=EXE[@MASK]): none (default; any difference is a failure), mw ($1FE6 bits 0-2 =
the MegaWire field, item G1 / D01 of the plan's old allow-list),
debug (printf text and BRAM $900-$FFF = TEST-only debug output).
A masked difference is COUNTED in its allow category, never dropped.

Output OUTDIR: summary.json, frames.csv (per frame: posts, reference effect digest chained from power-on, mismatch
counts per side), mismatch.jsonl (first 200 per side), log.

--expect FILE:RUN checks the FIRST side's chained effect digest against a committed expected file (e.g.
expected/host_final026.json:test_solo) at every frame mark the replay reached (and posts/AFs/end digest on a full
run); the ROM md5 and the option word must be the ones the file was made with (else exit 2).

Exit status (the rig fails loudly): 0 = PASS; 1 = FAIL: any per-post or checkpoint difference outside the side's
allow mask, a 'G' globals difference at an AF, an argument block that differs from the replayed RAM, an --expect
digest mismatch, or no post replayed; 2 = setup error (bad arguments, --expect file does not fit the inputs, a single
side without --expect or --record). '--informational globals|args' counts those two kinds without failing.
The last line printed is 'RESULT: PASS' or 'RESULT: FAIL: <reasons>'; summary.json carries 'result' and 'fail_reasons'.
usage: python -I -B equivA.py OUTDIR --capture CAP --rom ROM --side ref=EXE --side new=EXE[@mask] ... [--to F]
                                     [--opt WORD] [--full-every N] [--expect FILE:RUN] [--record]
                                     [--informational globals|args]
"""
import argparse, hashlib, json, os, struct, sys, time, collections
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hostside import HostSide, runs, SDR_SPAN, OFF_FLASH, BRAM_N   # noqa: E402

REG = lambda a: ('vectors' if a < 0x200 else 'ram0200' if a < 0xB00 else 'SAT' if a < 0xF80 else 'obj' if a < 0x1380
                 else 'pad1380' if a < 0x1400 else 'dmalist' if a < 0x1B90 else 'audio1B90' if a < 0x1C00 else
                 'net1C00' if a < 0x1E10 else 'args' if a < 0x1F10 else 'regs1F10' if a < 0x1F20 else
                 'stash1F20' if a < 0x1FE0 else 'reg%04X' % a)


def word_diffs(a, b):
    """differing 68000 word addresses between two RAMDP images (MCU halfword at A = 68000 word at A)"""
    if a == b:
        return []
    out = []
    for i in range(0, 0x2000, 64):
        if a[i:i + 64] != b[i:i + 64]:
            for j in range(i, i + 64, 2):
                if a[j:j + 2] != b[j:j + 2]:
                    out.append(j)
    return out


class Cmp:
    def __init__(self, name, mask):
        self.name, self.mask = name, mask
        self.n = collections.Counter()           # failures per kind
        self.allowed = collections.Counter()     # masked differences per allow category
        self.regions = collections.Counter()
        self.first = []
        self.posts_bad = 0
        self.frames_bad = set()

    def fail(self, kind, f, w, info):
        self.n[kind] += 1
        if len(self.first) < 200:
            self.first.append({'kind': kind, 'frame': f, 'post': '%04X' % w, 'info': info})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('out')
    ap.add_argument('--capture', required=True)
    ap.add_argument('--rom', required=True)
    ap.add_argument('--side', action='append', required=True)
    ap.add_argument('--to', type=int, default=10 ** 9)
    ap.add_argument('--opt', type=lambda s: int(s, 0), default=0)
    ap.add_argument('--full-every', type=int, default=2000)
    ap.add_argument('--sdram-every-post', action='store_true',
                    help='SDRAM diff after AD posts too (default: AD changes are compared at the next non-AD post)')
    ap.add_argument('--expect', metavar='FILE:RUN',
                    help='check the first side\'s chained digest against FILE["runs"][RUN] at every frame mark reached')
    ap.add_argument('--record', action='store_true', help='one side, nothing compared: only record its digests')
    ap.add_argument('--informational', action='append', default=[], choices=('globals', 'args'),
                    help='count this kind of difference without failing (default: it fails)')
    a = ap.parse_args()
    if len(a.side) < 2 and not (a.expect or a.record):
        ap.error('one side compares nothing: add a second --side, --expect FILE:RUN, or --record')
    os.makedirs(a.out, exist_ok=True)
    t0 = time.time()
    rom = open(a.rom, 'rb').read()
    exp = None
    if a.expect:
        efile, _, erun = a.expect.rpartition(':')
        try:
            exp = json.load(open(efile))['runs'][erun]
        except (OSError, KeyError, ValueError) as e:
            ap.error('--expect %s: %r' % (a.expect, e))
        if exp.get('rom_md5') != hashlib.md5(rom).hexdigest() or exp.get('opt') != '%08X' % a.opt:
            ap.error('--expect %s was made with ROM %s opt %s, not ROM %s opt %08X' % (
                a.expect, exp.get('rom_md5'), exp.get('opt'), hashlib.md5(rom).hexdigest(), a.opt))
    sides, cmps = [], []
    for k, s in enumerate(a.side):
        name, rest = s.split('=', 1)
        exe, mask = (rest.split('@') + ['none'])[:2]
        sides.append(HostSide(name, exe))
        if k:
            cmps.append(Cmp(name, set(mask.split('+'))))
    prov = {'capture': a.capture, 'capture_md5_head': hashlib.md5(open(a.capture, 'rb').read(1 << 20)).hexdigest(),
            'rom_md5': hashlib.md5(rom).hexdigest(), 'opt': '%08X' % a.opt, 'to': a.to,
            'sides': {s.name: {'exe': s.exe, 'md5': hashlib.md5(open(s.exe, 'rb').read()).hexdigest()} for s in sides},
            'masks': {c.name: sorted(c.mask) for c in cmps}}
    log = open(os.path.join(a.out, 'log.txt'), 'w')

    def say(*x):
        m = ' '.join(str(y) for y in x)
        print(m, flush=True)
        log.write(m + '\n')
        log.flush()

    say('equivA', json.dumps(prov))
    for s in sides:
        s.q_load(rom)
        s.q_opt(a.opt)
        s.q_reset()
        s.q_shadow()
        s.flush()
    for s in sides:
        s.k(); s.k(); s.k(); s.k()

    ck = {'n': 0, 'bad': []}

    def checkpoint(tag):
        """whole SDRAM, flash, BRAM 64 KB, and RAMDP/FPGAIO, every side vs the reference"""
        res = []
        for s in sides:
            s.q_mem(0, SDR_SPAN)
            s.q_mem(OFF_FLASH, len(rom))
            s.q_bram(0, 0x10000)
            s.q_all()
            s.flush()
        for s in sides:
            sd = s.read(SDR_SPAN)
            fl = s.read(len(rom))
            br = s.read(0x10000)
            rd, fp = s.r_all()
            res.append((hashlib.md5(sd).hexdigest(), hashlib.md5(fl).hexdigest(), hashlib.md5(br).hexdigest(),
                        hashlib.md5(rd + fp).hexdigest(), br, rd, fp))
        ck['n'] += 1
        out = {'tag': tag, 'ref': res[0][:4]}
        for c, r in zip(cmps, res[1:]):
            for k, nm in enumerate(('sdram', 'flash', 'bram64k', 'ramdp+fpgaio')):
                if r[k] != res[0][k]:
                    if nm == 'ramdp+fpgaio' and 'mw' in c.mask and r[6] == res[0][6]:
                        left = [wa for wa in word_diffs(res[0][5], r[5]) if not (wa == 0x1FE6 and
                                (struct.unpack_from('<H', res[0][5], wa)[0] ^ struct.unpack_from('<H', r[5], wa)[0]) & ~7 == 0)]
                        if not left:
                            c.allowed['checkpoint_1FE6_megawire_field'] += 1
                            continue
                    if nm == 'bram64k' and 'debug' in c.mask:
                        b0, b1 = res[0][4], r[4]
                        if b0[:0x900] == b1[:0x900] and b0[0x1000:] == b1[0x1000:]:
                            c.allowed['checkpoint_bram_snapshot'] += 1
                            continue
                    ck['bad'].append((tag, c.name, nm))
                    c.fail('checkpoint_' + nm, -1, 0, tag)
        return out

    cps = [checkpoint('after_reset')]
    say('checkpoint after reset:', json.dumps(cps[-1]))

    import mmap
    capf = open(a.capture, 'rb')
    d = mmap.mmap(capf.fileno(), 0, access=mmap.ACCESS_READ)
    o, nbytes = 0, len(d)
    frame = -1
    nposts = nram = naf = argmis = nsd = 0
    mirror = bytearray(0x2000)
    chain = hashlib.md5(b'equivA')
    ffr = open(os.path.join(a.out, 'frames.csv'), 'w')
    ffr.write('frame,posts,ref_digest,' + ','.join('bad_' + c.name for c in cmps) + '\n')
    fposts = 0
    fbad = collections.Counter()
    glob_bad = collections.Counter()
    per_cmd = collections.Counter()
    fdig = {}                                   # frame -> chained reference digest (16 hex) after its posts

    def end_frame():
        if frame >= 0:
            fdig[frame] = chain.hexdigest()[:16]
            ffr.write('%d,%d,%s,%s\n' % (frame, fposts, fdig[frame], ','.join(str(fbad[c.name]) for c in cmps)))

    # initial mirror = the reference's RAMDP after reset
    sides[0].q_all(); sides[0].flush(); mirror[:] = sides[0].r_all()[0]
    while o + 20 <= nbytes:
        t, ln, f = struct.unpack_from('<HHI', d, o)
        po = o + 20
        o = po + ln
        if f > a.to:
            break
        if t == 1:
            end_frame()
            frame, fposts = f, 0
            fbad = collections.Counter()
            continue
        if t == 3:
            ad, wd, v = struct.unpack_from('<HHH', d, po)
            if ad >= 0x2000:
                continue
            if wd == 2:
                off, data = ad & ~1, struct.pack('<H', v & 0xFFFF)
            else:
                off, data = ad ^ 1, bytes([v & 0xFF])
            mirror[off:off + len(data)] = data
            for s in sides:
                s.q_w(off, data)
            nram += 1
            continue
        if t != 2:
            continue
        wv = struct.unpack_from('<18H', d, po)
        word = wv[0]
        cmd = word >> 8
        args = struct.pack('<16H', *wv[2:18])
        if bytes(mirror[0x1E10:0x1E30]) != args:
            argmis += 1
        dodiff = a.sdram_every_post or cmd != 0xAD
        for s in sides:
            s.q_w(0x1E10, args)
            s.q_post(word)
            if dodiff:
                s.q_diff()
            s.q_bram(0, BRAM_N)
            if cmd == 0xAF:
                s.q_globals()
            s.flush()
        R = []
        for s in sides:
            ram, fp, txt, au = s.r_post()
            gran = s.r_diff() if dodiff else ()
            br = s.read(BRAM_N)
            gl = s.r_globals() if cmd == 0xAF else None
            R.append([ram, fp, txt, au, gran, br, gl, None])
        # SDRAM contents of the changed granules (one more round trip, only when something changed)
        need = [bool(r[4]) for r in R]
        if any(need):
            for s, r in zip(sides, R):
                for g, n in runs(r[4]):
                    s.q_mem(g, n)
                s.flush()
            for s, r in zip(sides, R):
                r[7] = b''.join(s.read(n) for g, n in runs(r[4]))
        else:
            for r in R:
                r[7] = b''
        nposts += 1
        fposts += 1
        per_cmd[cmd] += 1
        mirror[:] = R[0][0]
        ref = R[0]
        h = hashlib.md5()
        h.update(ref[0]); h.update(ref[1]); h.update(ref[2]); h.update(ref[3])
        h.update(struct.pack('<%dI' % len(ref[4]), *ref[4])); h.update(ref[7]); h.update(ref[5])
        nsd += dodiff
        chain.update(h.digest())
        for c, r in zip(cmps, R[1:]):
            bad = False
            if r[0] != ref[0]:
                wd_ = word_diffs(ref[0], r[0])
                left = []
                for wa in wd_:
                    x = struct.unpack_from('<H', ref[0], wa)[0]
                    y = struct.unpack_from('<H', r[0], wa)[0]
                    if wa == 0x1FE6 and 'mw' in c.mask and (x ^ y) & ~7 == 0:
                        c.allowed['ramdp_1FE6_megawire_field'] += 1
                        continue
                    left.append((wa, x, y))
                if left:
                    bad = True
                    for wa, x, y in left:
                        c.regions[REG(wa)] += 1
                    c.fail('ramdp', frame, word, ['$%04X %s %04X/%04X' % (wa, REG(wa), x, y) for wa, x, y in left[:12]] +
                           (['... %d words' % len(left)] if len(left) > 12 else []))
            if r[1] != ref[1]:
                bad = True
                c.fail('fpgaio', frame, word, [struct.unpack('<6I', ref[1]), struct.unpack('<6I', r[1])])
            if r[2] != ref[2]:
                if 'debug' in c.mask:
                    c.allowed['printf_text'] += 1
                else:
                    bad = True
                    c.fail('printf', frame, word, [ref[2][:160].decode('latin-1'), r[2][:160].decode('latin-1')])
            if r[3] != ref[3]:
                bad = True
                c.fail('audio', frame, word, [ref[3].hex(), r[3].hex()])
            if r[4] != ref[4]:
                bad = True
                c.fail('sdram_granules', frame, word, [len(ref[4]), len(r[4]), sorted(set(ref[4]) ^ set(r[4]))[:8]])
            elif r[7] != ref[7]:
                bad = True
                c.fail('sdram_bytes', frame, word, [len(ref[7])])
            if r[5] != ref[5]:
                if r[5][:0x900] != ref[5][:0x900]:
                    bad = True
                    c.fail('bram_saves', frame, word, None)
                if r[5][0x900:] != ref[5][0x900:]:
                    if 'debug' in c.mask:
                        c.allowed['bram_snapshot_900'] += 1
                    else:
                        bad = True
                        c.fail('bram_snapshot_900', frame, word, None)
            if r[6] is not None and r[6] != ref[6]:
                glob_bad[c.name] += 1
            if bad:
                c.posts_bad += 1
                c.frames_bad.add(frame)
                fbad[c.name] += 1
        if cmd == 0xAF:
            naf += 1
            if a.full_every and naf % a.full_every == 0:
                cps.append(checkpoint('af%d_frame%d' % (naf, frame)))
        if nposts % 50000 == 0:
            say('frame %d posts %d afs %d wall %.0f s fails %s' % (frame, nposts, naf, time.time() - t0,
                {c.name: sum(c.n.values()) for c in cmps}))
    end_frame()
    ffr.close()
    cps.append(checkpoint('end_frame%d' % frame))
    summ = {'provenance': prov, 'frames_to': frame, 'posts': nposts, 'ramw': nram, 'afs': naf,
            'arg_block_mismatch_vs_replayed_ram': argmis, 'posts_with_sdram_diff': nsd,
            'sdram_every_post': a.sdram_every_post, 'per_cmd': {'%02X' % k: v for k, v in sorted(per_cmd.items())},
            'ref_chain_digest': chain.hexdigest(), 'checkpoints': cps, 'checkpoint_failures': ck['bad'],
            'wall_s': round(time.time() - t0), 'sides': {}}
    for c in cmps:
        summ['sides'][c.name] = {'mask': sorted(c.mask), 'posts_with_failure': c.posts_bad,
                                 'frames_with_failure': len(c.frames_bad), 'failures_by_kind': dict(c.n),
                                 'allowed_by_category': dict(c.allowed), 'ramdp_failure_words_by_region': dict(c.regions),
                                 'globals_differ_at_AF (internal, not 68000-visible)': glob_bad[c.name]}
    # ---- the verdict: every difference nobody allowed is a failure
    reasons = []
    if not nposts:
        reasons.append('no post replayed (capture empty or --to before the first post): nothing was compared')
    for c in cmps:
        if c.n:
            reasons.append('side %s: %d posts fail, failures by kind %s' % (c.name, c.posts_bad, dict(c.n)))
        if glob_bad[c.name]:
            if 'globals' in a.informational:
                c.allowed['globals_at_AF (informational)'] += glob_bad[c.name]
                summ['sides'][c.name]['allowed_by_category'] = dict(c.allowed)
            else:
                reasons.append('side %s: the G globals block differs at %d AFs' % (c.name, glob_bad[c.name]))
    if argmis and 'args' not in a.informational:
        reasons.append('%d posts: the capture\'s argument block differs from the replayed RAM (the replay left the recording)' % argmis)
    if exp is not None:
        marks = sorted((int(k), v) for k, v in exp['ref_chain_digest_16_at_frame'].items() if int(k) <= frame)
        bad = ['%d: %s, expected %s' % (k, fdig.get(k), v) for k, v in marks if fdig.get(k) != v]
        full = frame == exp['frames_to']
        if full:
            for k, mine in (('posts', nposts), ('afs', naf), ('ref_chain_digest_end', chain.hexdigest())):
                if exp.get(k) != mine:
                    bad.append('%s %s, expected %s' % (k, mine, exp.get(k)))
        summ['expect'] = {'file_run': a.expect, 'marks_checked': len(marks), 'full_run_checked': full, 'mismatches': bad}
        if not marks:
            reasons.append('--expect %s: no frame mark within the replayed frames (0..%d): nothing was checked' % (a.expect, frame))
        if bad:
            reasons.append('--expect %s: the first side\'s digest differs at %d of %d marks (%s)' % (
                a.expect, len(bad), len(marks), '; '.join(bad[:3])))
    summ['result'] = 'FAIL' if reasons else 'PASS'
    summ['fail_reasons'] = reasons
    with open(os.path.join(a.out, 'mismatch.jsonl'), 'w') as fm:
        for c in cmps:
            for x in c.first:
                fm.write(json.dumps(dict(side=c.name, **x)) + '\n')
    open(os.path.join(a.out, 'summary.json'), 'w').write(json.dumps(summ, indent=1))
    say(json.dumps({k: summ[k] for k in ('frames_to', 'posts', 'afs', 'ref_chain_digest', 'checkpoint_failures', 'wall_s')}))
    say(json.dumps(summ['sides'], indent=1))
    if 'expect' in summ:
        say('expect:', json.dumps(summ['expect']))
    say('RESULT: PASS' if not reasons else 'RESULT: FAIL: ' + ' | '.join(reasons))
    for s in sides:
        s.close()
    return 1 if reasons else 0


if __name__ == '__main__':
    sys.exit(main())
