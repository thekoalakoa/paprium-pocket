#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""check_images.py - the skeleton's milestone checks on built firmware (read-only on the build tree).

    python -I -B tests/check_images.py m1 [--build DIR]
        Milestone 1: build/pocket/legacy54k/{test,release} == tests/expected/final026.json, file for file (md5).
    python -I -B tests/check_images.py layout --layout pocket72k [--build DIR] [--brain-dir DIR]
        Milestone 2 (any layout, both variants), against the legacy54k build of the same variant:
        0. if tests/expected/<layout>_026.json exists: the image md5s equal that pin
        1. brain: rom.bin[brain] == brain.bin (bytes unchanged at 0x5360-0xD2EB)
        2. code window: cf.bin at 0x80002C00, 64 zero bytes, rodata.bin at 0x80004110 (== the legacy build's bytes)
        3. image files: line counts / 16 words a line / CRLF / trailing space for the layout's sizes, and decoding them
           gives back rom.bin (zero-padded) and the WRAM init (code window, zero elsewhere); the four WRAM byte
           lanes wram_b0..b3 (the images of the RTL since test build 4, a firmware build B Jam tested on his
           hardware) hold exactly the bytes of wram_hi / wram_lo
        4. symbols vs legacy54k: every symbol present in both, with the same size; WRAM data symbols (.data, .bss,
           .noinit, the not-cleared lists) at the SAME addresses; only code/rodata addresses may move
        5. placement: every firmware code/rodata symbol inside the layout's firmware IROM regions (kind "rom"), none in
           the brain hole
    python -I -B tests/check_images.py s1 [--build DIR] [--brain-dir DIR]
        The stage-1 images (FW_S1, our new firmware: every fwbuild.json s1 variant): brain bytes (the stage-1 brain,
        md5s pinned in fwbuild.json s1.brain: with the brain's cycle-counter fix that the three-player-slot
        recordings of docs/STAGE1_PLAN.md item X3 found) and the code window's fixed bytes unchanged, the
        stage-1 crt0 at 0 and its trap entry in irom_lo, nothing of the 0.2.6 start-up linked (dummy handler, UART);
        test and release link no byte of the weak hook defaults (core/sched/sched_stubs.c, core/dispatch/disp_stubs.c):
        every hook has its owner's definition (the probe images keep the skeleton's). The stage-5 images
        (s5test / s5release, FW_S5: our own song engine and synth): no object of the interim audio linked (interim/s1
        audio_s1 / sfx_s1 / vu_s1, interim/album), none of its leftovers (the interim volume and SFX FIFO hooks, the
        0.2.6 8C unpack for the VU), and the synth's fields (core/sched/s5_mirror.c) and the main-loop pass's entries
        linked. Since test build 5: the boot cache's stub linked in both, TEST's debug save in s5test (version 9:
        board/pocket/dbgsave.h) with none of the interim audio's record parts it carried in stage 1 (the album poll, the
        audio-call log, the audio stats), and no record writer in s5release (an earlier step had the whole debug save
        out while its record still carried the interim audio block,
        so its check named dbgsave_start among the leftovers).
The brain directory comes from --brain-dir, then PAPRIUM_BRAIN_DIR or paths.local.json "brain_dir" (m1 / layout: the
0.2.6 brain) or PAPRIUM_BRAIN_DIR_S1 or paths.local.json "brain_dir_s1" (s1: the stage-1 brain), as tools/fwbuild.py."""
import argparse, hashlib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import fwbudget   # noqa: E402  (its map reader)
CFG = json.load(open(os.path.join(ROOT, 'fwbuild.json')))
md5 = lambda b: hashlib.md5(b).hexdigest()
rd = lambda p: open(p, 'rb').read()
ok_all = True


def res(name, ok, info=''):
    global ok_all
    ok_all &= bool(ok)
    print('%-4s %s %s' % ('PASS' if ok else 'FAIL', name, info))


def nm(path):
    out = {}
    for ln in open(path):
        p = ln.split()
        if len(p) == 4:
            out[p[3]] = (int(p[0], 16), int(p[1], 16), p[2])
        elif len(p) == 3:
            out[p[2]] = (int(p[0], 16), 0, p[1])
    return out


def m1(a):
    exp = json.load(open(os.path.join(HERE, 'expected', 'final026.json')))['legacy54k']
    for v, files in exp.items():
        d = os.path.join(a.build, 'pocket', 'legacy54k', v)
        for fn, m in files.items():
            p = os.path.join(d, fn if fn == 'main.elf' else os.path.join('img', fn))
            got = md5(rd(p)) if os.path.exists(p) else 'missing'
            res('m1 %-7s %-11s' % (v, fn), got == m, got)


def decode_words(txt, nwords):
    assert txt.endswith(' ')
    lines = txt[:-1].split('\r\n')
    ok = all(len(l.split(' ')) == 16 for l in lines) and '\n' not in txt.replace('\r\n', '')
    b = b''.join(bytes.fromhex(w) for l in lines for w in l.split(' '))
    return ok, len(lines), b


def layout(a):
    L = CFG['layouts'][a.layout]
    lay = json.load(open(os.path.join(ROOT, *L['regions'].split('/'))))
    R = {r['name']: (int(r['lo'], 0), int(r['hi'], 0)) for r in lay['regions']}
    bdir = a.brain_dir or os.environ.get('PAPRIUM_BRAIN_DIR') or json.load(open(os.path.join(ROOT, 'paths.local.json')))['brain_dir']
    brain, cf, ro = (rd(os.path.join(bdir, f)) for f in ('brain.bin', 'cf.bin', 'rodata.bin'))
    pinf = os.path.join(HERE, 'expected', '%s_026.json' % a.layout)
    pins = json.load(open(pinf))[a.layout] if os.path.exists(pinf) else {}
    for v in sorted(CFG['variants']):
        d = os.path.join(a.build, 'pocket', a.layout, v)
        ref = os.path.join(a.build, 'pocket', 'legacy54k', v)
        if v in pins:
            bad = [fn for fn, m in pins[v].items() if md5(rd(os.path.join(d, 'img', fn))) != m]
            res('%s %s 0 images == the pin in tests/expected/%s_026.json' % (a.layout, v, a.layout), not bad, ' '.join(bad))
        rom, wc = rd(os.path.join(d, 'img', 'rom.bin')), rd(os.path.join(d, 'img', 'wcode.bin'))
        b0, b1 = R['brain']
        res('%s %s 1 brain bytes 0x%X-0x%X == brain.bin' % (a.layout, v, b0, b1 - 1), rom[b0:b1] == brain and b1 - b0 == len(brain), md5(rom[b0:b1])[:8])
        rwc = rd(os.path.join(ref, 'img', 'wcode.bin'))
        n = 0x80004110 - 0x80002C00
        res('%s %s 2 window: cf.bin, 64 zero, rodata.bin' % (a.layout, v),
            wc[:len(cf)] == cf and wc[len(cf):n] == bytes(n - len(cf)) and wc[n:n + len(ro)] == ro)
        res('%s %s 2 window cf+pad+tables == legacy54k' % (a.layout, v), wc[:n + len(ro)] == rwc[:n + len(ro)])
        # 3. image formats and round trip
        rk, ek, wk = L['rom0_kb'], L['ext_kb'], L['wram_kb']
        t0 = open(os.path.join(d, 'img', 'mcu.txt'), newline='').read()
        t1 = open(os.path.join(d, 'img', 'mcu_ext.txt'), newline='').read()
        ok0, n0, d0 = decode_words(t0, rk * 256)
        ok1, n1, d1 = decode_words(t1, ek * 256)
        res('%s %s 3 mcu.txt %d lines, mcu_ext.txt %d lines (16 words, CRLF, trailing space)' % (a.layout, v, n0, n1),
            ok0 and ok1 and n0 == rk * 16 and n1 == ek * 16)
        res('%s %s 3 decode mcu.txt + mcu_ext.txt == rom.bin + zero pad' % (a.layout, v),
            (d0 + d1)[:len(rom)] == rom and not any((d0 + d1)[len(rom):]) and len(d0 + d1) == 1024 * (rk + ek))
        hi = open(os.path.join(d, 'img', 'wram_hi.txt'), newline='').read()
        lo = open(os.path.join(d, 'img', 'wram_lo.txt'), newline='').read()
        hl, ll = hi.split('\r\n'), lo.split('\r\n')
        res('%s %s 3 wram_hi/lo %d + %d lines, CRLF' % (a.layout, v, len(hl) - 1, len(ll) - 1),
            hl[-1] == '' and ll[-1] == '' and len(hl) - 1 == wk * 512 and len(ll) - 1 == wk * 512)
        w = bytearray(1024 * wk)
        w[0::2] = bytes(int(x, 16) for x in hl[:-1]); w[1::2] = bytes(int(x, 16) for x in ll[:-1])
        o = 0x2C00
        res('%s %s 3 decode wram == wcode.bin at 0x2C00, zero elsewhere' % (a.layout, v),
            w[o:o + len(wc)] == wc and not any(w[:o]) and not any(w[o + len(wc):]))
        # since test build 4: the same WRAM bytes as four byte lanes (wram_b<i> line k = byte 4k + i), the RTL's images
        lanes = [open(os.path.join(d, 'img', 'wram_b%d.txt' % i), newline='').read().split('\r\n') for i in range(4)]
        wl = bytearray(1024 * wk)
        shape = all(x[-1] == '' and len(x) - 1 == wk * 256 for x in lanes)
        if shape:
            for i in range(4):
                wl[i::4] = bytes(int(x, 16) for x in lanes[i][:-1])
        res('%s %s 3 wram_b0..b3 %d lines each, CRLF, == the bytes of wram_hi/lo' % (a.layout, v, wk * 256),
            shape and wl == w)
        # 4. symbols vs the legacy build
        S, Sr = nm(os.path.join(d, 'main.nm')), nm(os.path.join(ref, 'main.nm'))
        common = sorted(set(S) & set(Sr))
        only = sorted(set(S) ^ set(Sr))
        size_diff = [n for n in common if S[n][1] != Sr[n][1]]
        data = [n for n in common if Sr[n][0] >= 0x80000000 and not (0x80002C00 <= Sr[n][0] < 0x80006C00) and Sr[n][2] in 'bBdDsSgG']
        moved = [n for n in data if S[n][0] != Sr[n][0]]
        res('%s %s 4 symbols: %d common, same sizes' % (a.layout, v, len(common)), not size_diff, ' '.join(size_diff[:8]))
        res('%s %s 4 WRAM data symbols at the same addresses' % (a.layout, v), not moved, '%d checked; moved: %s' % (len(data), ' '.join(moved[:8])))
        print('     symbols only in one build (linker-script names): %s' % ' '.join(only))
        # 5. placement
        code = [n for n in S if S[n][0] < 0x80000000 and S[n][2] in 'tTrR' and not n.startswith('__brain')]
        romreg = [r['name'] for r in lay['regions'] if r['kind'] == 'rom']
        bad = [n for n in code if not any(R[k][0] <= S[n][0] < R[k][1] for k in romreg)]
        inbrain = [n for n in code if b0 <= S[n][0] < b1]
        res('%s %s 5 %d firmware code/rodata symbols in the firmware IROM regions (%s), none in the brain hole' % (a.layout, v, len(code), '/'.join(romreg)),
            not bad and not inbrain, ' '.join((bad + inbrain)[:8]))


def lanes_match(d, wk):
    """since test build 4: img/wram_b0..b3 (line k of wram_b<i> = MCU byte 4k + i) hold exactly the bytes of
    img/wram_hi / wram_lo"""
    rdl = lambda f: open(os.path.join(d, 'img', f), newline='').read().split('\r\n')
    hl, ll = rdl('wram_hi.txt'), rdl('wram_lo.txt')
    lanes = [rdl('wram_b%d.txt' % i) for i in range(4)]
    if not all(x[-1] == '' and len(x) - 1 == wk * 256 for x in lanes) or len(hl) - 1 != wk * 512 or len(ll) - 1 != wk * 512:
        return False
    w, wl = bytearray(1024 * wk), bytearray(1024 * wk)
    w[0::2] = bytes(int(x, 16) for x in hl[:-1]); w[1::2] = bytes(int(x, 16) for x in ll[:-1])
    for i in range(4):
        wl[i::4] = bytes(int(x, 16) for x in lanes[i][:-1])
    return w == wl


def s1(a):
    """stage-1 images (build/s1/<layout>/<variant>): the fixed bytes kept, the 0.2.6 start-up gone, the layout kept"""
    sc = CFG['s1']
    lname = sc['layout']
    L = CFG['layouts'][lname]
    lay = json.load(open(os.path.join(ROOT, *L['regions'].split('/'))))
    R = {r['name']: (int(r['lo'], 0), int(r['hi'], 0)) for r in lay['regions']}
    bdir = a.brain_dir or os.environ.get('PAPRIUM_BRAIN_DIR_S1') or json.load(open(os.path.join(ROOT, 'paths.local.json'))).get('brain_dir_s1')
    brain, cf, ro = (rd(os.path.join(bdir, f)) for f in ('brain.bin', 'cf.bin', 'rodata.bin'))
    pin = sc['brain']['files']
    got = {f: md5(b) for f, b in zip(('brain.bin', 'cf.bin', 'rodata.bin'), (brain, cf, ro))}
    bad = ['%s %s (pin %s)' % (f, got[f][:8], pin[f]['md5'][:8]) for f in got if got[f] != pin[f]['md5']]
    res('s1 the brain directory holds the stage-1 brain (fwbuild.json s1.brain md5s)', not bad, ' '.join(bad))
    for v, V in sorted(sc['pocket']['variants'].items()):
        vl = V.get('layout', lname)                     # stage 5: the s5 variants link at pocket88k
        VL = CFG['layouts'].get(vl) or sc.get('layouts', {})[vl]
        VR = {r['name']: (int(r['lo'], 0), int(r['hi'], 0))
              for r in json.load(open(os.path.join(ROOT, *VL['regions'].split('/'))))['regions']}
        d = os.path.join(a.build, 's1', vl, v)
        if not os.path.exists(os.path.join(d, 'main.nm')):
            if V.get('on_demand'):
                continue                    # built only when named (tools/fwbuild.py s1 --variant V)
            res('s1 %s built' % v, False, 'missing (tools/fwbuild.py s1)')
            continue
        rom, wc = rd(os.path.join(d, 'img', 'rom.bin')), rd(os.path.join(d, 'img', 'wcode.bin'))
        b0, b1 = VR['brain']
        n = 0x80004110 - 0x80002C00
        S = nm(os.path.join(d, 'main.nm'))
        if V.get('nobrain'):                # zeros of the same sizes in the brain's place
            zb, zc, zr = bytes(len(brain)), bytes(len(cf)), bytes(len(ro))
            ok = rom[b0:b1] == zb and wc[:len(cf)] == zc and wc[len(cf):n] == bytes(n - len(cf)) and wc[n:n + len(ro)] == zr
        else:
            ok = rom[b0:b1] == brain and wc[:len(cf)] == cf and wc[len(cf):n] == bytes(n - len(cf)) and wc[n:n + len(ro)] == ro
        gone = [x for x in ('__crt0_dummy_trap_handler', 'neorv32_uart_printf', 'ppm_start', 'buddy_trap') if x in S]
        start = S.get('_start', (None,))[0] == 0 and S.get('s1_trap_entry', (1 << 20,))[0] < VR['irom_lo'][1]
        res('s1 %-10s the four WRAM lanes (card 4) == the bytes of wram_hi / wram_lo' % v, lanes_match(d, VL['wram_kb']))
        res('s1 %-10s %s, crt0 at 0, trap entry in irom_lo, no 0.2.6 start-up' % (
            v, 'brain hole and window zero (no brain)' if V.get('nobrain') else 'brain bytes == brain.bin, window == cf/pad/rodata'),
            ok and start and not gone, ' '.join(gone))
        if v in ('test', 'release'):
            stubs = ['%s %d B' % (isec, size) for osec, isec, addr, size, obj in fwbudget.parse_map(os.path.join(d, 'main.map'))
                     if obj in ('sched_stubs.c.o', 'disp_stubs.c.o')]
            res('s1 %-10s no weak hook default linked (sched_stubs.c, disp_stubs.c): every hook has its owner' % v,
                not stubs, ' '.join(stubs[:6]))
        if v in ('s5test', 's5release'):        # stage 5: the interim audio retired, the synth's fields linked
            objs = set(obj for osec, isec, addr, size, obj in fwbudget.parse_map(os.path.join(d, 'main.map')) if size)
            interim = sorted(objs & {'audio_s1.c.o', 'sfx_s1.c.o', 'vu_s1.c.o', 'mdp.c.o', 'everdrive.c.o', 'sfx.c.o'})
            left = [x for x in ('s1_board_vol', 's1_board_sfx', 'ppm_bgm_addr', 's1_vu_start', 'mdp_init', 'sfx_level_init',
                                'audio_tick_slice', 's1_album_poll', 's1_au_log', 's1_audio_stats')
                    if x in S]
            need = [x for x in ('s5_mirror_in', 's5_mirror_out', 's5_mirror_pass_in', 'board_item_pass',
                                'board_pass_bracket', 'board_synth_put', 'sched_pass_post', 'disp_s5_pass',
                                'boot_cache_boot') if x not in S]
            if v == 's5test':                   # from test build S3a on: TEST's debug save
                                                # version 10, no boot-cache record in it
                need += [x for x in ('dbgsave_start', 'prev_take') if x not in S]
            if 's1_cache4b_record' in S:        # no record writer in either (RELEASE never had one)
                left.append('s1_cache4b_record')
            res('s1 %-10s no interim audio linked (objects / leftovers), the synth\'s fields and the pass linked (F4)' % v,
                not interim and not left and not need and 's5_mirror.c.o' in objs,
                ' '.join(interim + left + ['missing ' + x for x in need]))


ap = argparse.ArgumentParser()
ap.add_argument('what', choices=('m1', 'layout', 's1'))
ap.add_argument('--build', default=os.path.join(ROOT, 'build'))
ap.add_argument('--layout', default='pocket72k')
ap.add_argument('--brain-dir')
a = ap.parse_args()
{'m1': m1, 'layout': layout, 's1': s1}[a.what](a)
print('ALL PASS' if ok_all else 'SOME FAIL')
sys.exit(0 if ok_all else 1)
