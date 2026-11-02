#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""q1_save.py - B Jam's question Q1 for stage 1 (his decision of 2026-10-11: the battery save 8 KB like the cart) on
RV32: the stage-1 TEST and RELEASE images (FW_S1, our new firmware) on the board model (rtlmodel.py) with the capture's
boot posts (fuzz_s1.py), run by `fuzz_s1.py --q1`. Stages are the steps of the 0.3.0 work (README.md, "Terms").
A-H below are this rig's parts; test builds 3, 4a, 4b, 5 and S3a are
firmware builds B Jam tested on his hardware.

  A  a 0.2.x 4 KB .sav loaded into the 8 KB save RAM (the upper half at its power-up 0, as the RTL leaves it): the game's
     bytes 0x000-0x8FF are unchanged after the boot and the replay; RELEASE writes nothing anywhere (0x000-0x1FFF
     unchanged); TEST writes 0.2.6's snapshot window 0x900-0xFFF (as 0.2.6 TEST did) and a valid debug record at
     0x1000-0x1FFF whose 'prev' block says "no previous record". The stage-1 layout of the game's saves is 0.2.x's, so the
     import needs no conversion (the cart's own format, and its one-time conversion,
     are stage 3: docs/ALLOWLIST.md row B11, difference D30 of our firmware audit).
  B  the same with a 4 KB save RAM (the 0.2.x RTL): the TEST image's size probe turns the debug save off and puts the
     game's byte back; 0x000-0x8FF unchanged.
  C  a fatal halt (85, event 0x400000FA) reaches the save RAM at once (tools/dbgsave.py decodes it from the .sav bytes),
     and the record is written again while the halt polls (polls >= 65,536, ~43 M model cycles in).
  D  a Soft Reset after the halt (CPU and RTL registers reset, WRAM and the save RAM kept): the new boot's record carries
     the halt in 'prev' (fatal age 1, the code); after a second Soft Reset it is still there (age 2), and the previous
     session's state reads 6 (a version-6 record; 5 before stage 1td).
  E  every record write stays inside 0x1000-0x1FFF (the block chain ends inside the region; the rest of the save RAM is
     as A says).
  F  the freeze telemetry's VS counter (MCU interface v1.1, debug save version 3; B Jam's decision of 2026-10-13): the
     record's VS count is the board's VSCNT at its write; with the 68000 silent for 6 TIM7 periods and the VDP running,
     the decoder says "68000 STOPPED, VDP alive"; with the VDP stopped
     too (rtlmodel vdp_stop), "VDP STOPPED and no 9494"; after a
     Soft Reset the new record's 'prev' carries the stopped count and the same verdict, and this session counts from 0.
  G  the carried lateness block (debug save version 5: the Pocket's quit restarts the MCU before the .sav is read, as
     B Jam found on 2026-10-17; its version-6 layout of 2026-10-19): a planted version-4 record (decoder, CPU MATE,
     feeder, exception, dispatcher and stack values all nonzero, LATE / ABORT / OVF set, a negative margin, the stack
     floor overwritten) in the save RAM; the boot's 'prev2' holds every planted word (version 6: the CPU MATE late count
     0, an older record's late_seen is the sticky-flag count and is not carried; the version-6 words 0, its blocks end
     before them), the chain has 1 session = those values, the lateness sign 1 session back,
     and the replay's writes and 10 more TIM7 periods leave the block as the boot wrote it (the periodic write steps over
     it); a Soft Reset (the quit's restart) carries
     the session's own blocks as its last write had them and folds them into the chain (2 sessions, the planted worst
     kept); two more boots with no play (quick relaunches) keep the worst, the chain counting 3 and 4 sessions and the
     sign moving back (a late CPU MATE answer is no sign from version 6: tests/equiv/tdiag_s1.py checks the version-6
     words themselves); a version-3 record carries nothing (state 3, no chain) and a version-9 one reads 0xFFFFFFFF;
     a boot over an upper half full of 0xA5 leaves the region byte for byte as a boot over zeros does (the clear skips
     only the words the boot's write and the PREV2 block rewrite: nothing of an older record stays); tools/dbgsave.py
     reads the planted version-4 record with no 'prev2' and prints the note that it has none.
  H  the SAT snapshot's layout 2 (TEST, save 0x900-0xFFF; added after B Jam's save from test build 3, of 2026-10-17,
     held a frame of more than 80 entries that only a link could show): five planted sprite tables closed by AF in the
     replay (86, 83, 86, 40 and 10 entries, each tagged in its tile field, with known H40 line overflows): the save
     holds the session's most crowded frame (the second 86: the latest of equals) with its true count 86 beside the
     capped 80, the latest frame of 20 or more (the 40) with its count, the session's most (86) and its frame ends over
     80 (3), both tables byte for byte as the thread copied them; tools/dbgsave.py reads it. Since a later stage-1 build
     the close is the chip's (the replay posts AF02): the three tables over 80 are stored as the chip's AF02 multiplex
     (entries 14-79 relinked to k - 13), so the reader prints "86 sprite pieces (over the console's 80: the chip's AF02
     multiplex ...)" and gives no line totals for them, while its line
     model on the planted 86 as composed and on the stored 40 (lines over
     320 px / over 20 sprites) equals the plan's; the same save with the layout byte cleared (a layout-1 image's write)
     reads as layout 1, "more than 80" from the AF02 relink (from entry 79's link under the close of 2026-10-17).
     The 68000 holds after each planted AF until the thread's copy of that frame has returned (the test is of the
     layout); a race replay (one table of 87, the 68000 going on as soon as the copy begins; seeds from 7 until a frame
     start lands inside the copy) checks that the save flags a copy torn exactly when a frame start came during it; the
     save is read once a copy the thread had begun has returned (bounded: in the rig's fast mode the thread can still be
     copying when the replay's last post is answered). Take race (a review finding, planted since a later merge): the
     68000 holds after a planted table of 87 until the thread has taken its request, the CPU is stopped at a point
     before the copy reads anything (the take path's first instruction, interrupts open again; ppm_snapshot_sat's
     entry), and the 68000 then posts a frame start, writes the next frame's table (tag 'H') over the cart RAM SAT and
     holds again until the copy has returned (the frame start is the one event in the window): the frame start must
     land at that point (mepc), and the save must hold the 87 flagged torn with the next frame's pieces in it (the
     frame-start count is read with the take, interrupts off; read in ppm_snapshot_sat, as before the fix, the copy
     passed unflagged).
Exit 0 = PASS, 1 = FAIL. What it measures, it measures in the model (a model written from the documents)."""
import os, random, re, struct, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import dbgsave   # noqa: E402
import fuzz_s1   # noqa: E402
from rtlmodel import NTSC, RAMDP, Stop, nm   # noqa: E402

FRAMES = 300
EV_85 = (1 << 30) | 0xFA         # 85's fatal event code


def sav_of(save):
    """the .sav bytes the Pocket writes: each 16-bit half's bytes swapped (file byte i = MCU byte i ^ 1)"""
    b = bytes(save)
    s = bytearray(len(b))
    s[0::2], s[1::2] = b[1::2], b[0::2]
    return bytes(s)


def save_026(seed):
    """a 0.2.x 4 KB save: game bytes 0x000-0x8FF and the TEST snapshot window 0x900-0xFFF, as MCU bytes"""
    r = random.Random(seed)
    return bytes(r.getrandbits(8) for _ in range(0x1000))


def replay(build, rom, recs, save, save_kb=8, seed=7):
    f = fuzz_s1.Fuzz(build, rom, recs, seed, save=save)
    f.b.save_kb = save_kb
    if save_kb != 8:
        f.b.save = bytearray(save[:save_kb * 1024])
    o = f.run()
    return f, o


# ---- G: a version-4 record as the version-4 image wrote it (board/pocket/dbgsave.c as of 2026-10-17: the block
# order and sizes of dbg_write), with planted values; MCU words, little-endian
V4_ORDER = ((1, 8), (2, 4), (3, 55), (4, 21), (5, 4), (6, 5), (7, 22), (8, 5), (9, 16), (10, 2), (11, 5), (14, 23), (15, 3),
            (16, 5), (12, 257), (13, 513))
PLANT = {
    16: {0: (1 << 16) | (1 << 20) | (1 << 21) | 3, 1: 1234, 2: (1 << 31) | 5678, 3: (-4321) & 0xFFFFFFFF, 4: 7},   # dec
    7: {4: 570, 6: 11, 7: 2, 8: 1, 17: 3, 21: 123456},          # glue: calls, discarded, aborted, abort_landings, late_seen,
                                                                # cycles_max
    8: {0: 1000, 1: 42},                                        # audio: ticks, catchups
    4: {16: 1, 17: 0x5, 18: 0x1234, 19: 0x80001000},            # sched: exc, cause, epc, tval
    9: {0: 9, 3: 4},                                            # disp: refusals, jobs_failed
    10: {0: 1500, 1: 0},                                        # stack: high-water, floor overwritten
    3: {50: 2691, 51: 3000000, 52: 3100000},                    # stats: n9494, t_last_9494, t_last_post
    5: {0: 496, 1: 14},                                         # wdog: ticks, gated
}
P2_OWN = ('dec_stat', 'dec_margin', 'dec_latecnt', 'late', 'discarded', 'aborted', 'abort_landings', 'cycles_max',
          'catchups', 'exc', 'refusals', 'jobs_failed', 'stack_hw', 'floor_ok', 'late_max', 'alb_wait_max', 'dec_words',
          'dec_time', 'calls', 'exc_first_cause', 'exc_first_epc', 'exc_first_tval', 'short_calls', 'alb_res',
          'alb_under', 'alb_lost', 'alb_calls', 'alb_wait')
P2_FOLD = P2_OWN[1:16]                  # folded by max in their chain form (dec_stat: its flags ORed); version 6 adds
                                        # the CPU MATE's largest lateness and the album's longest wait
P2_SIGN = ('dec_latecnt', 'exc', 'floor_ok')   # version 6: a late CPU MATE answer is no lateness sign
VERSION = 8                             # the stage-1 images' record version (7 since test build 4a, 8 since 4b; the
                                        # reader also reads 9, test build 5's stage-5 record, and
                                        # 10, test build S3a's: tests/equiv/dbgsave10.py)
assert VERSION in dbgsave.VERSIONS
MARGIN_X = 0x7FFFFFFF


def record_v4(version=4):
    w = []
    for bid, n in V4_ORDER:
        w.append((bid << 16) | n)
        d = [0] * n
        if bid == 1:                    # head: magic, version, writes, now, mcycle, clock, words, oracle built
            d[:8] = [dbgsave.MAGIC, version, 489, 50000000, 49000000, NTSC, 1024, 1]
        if bid == 2:                    # boot record: code 6 (68000 released) and its time (prev reads these two)
            d[1:3] = [0x06, 557632]
        for k, v in PLANT.get(bid, {}).items():
            d[k] = v
        w += d
    w.append(0xFFFF << 16)
    w += [0] * (1024 - len(w))
    return b''.join(x.to_bytes(4, 'little') for x in w)


def own_of(rec):
    """what PREV2's part 1 must hold for a record that ends a session: its blocks as decoded"""
    dc, g, a, sc, d, st = rec['dec'], rec['glue'], rec['audio'], rec['sched'], rec['disp'], rec['stack']
    return dict(dec_stat=dc['stat'], dec_margin=dc['margin'], dec_latecnt=dc['latecnt'], late=g.get('late', 0),
                discarded=g['discarded'], aborted=g['aborted'], abort_landings=g['abort_landings'],
                cycles_max=g['cycles_max'], catchups=a['catchups'], exc=sc['exc'], refusals=d['refusals'],
                jobs_failed=d['jobs_failed'], stack_hw=st['high_water_bytes'], floor_ok=st['floor_intact'],
                late_max=g.get('late_max', 0), alb_wait_max=a.get('alb_wait_max', 0),
                dec_words=dc['words'], dec_time=dc['time'], calls=g['calls'], exc_first_cause=sc['exc_first_cause'],
                exc_first_epc=sc['exc_first_epc'], exc_first_tval=sc['exc_first_tval'],
                short_calls=g.get('short_calls', 0), alb_res=a.get('alb_res', 0), alb_under=a.get('alb_xl14', 0),
                alb_lost=a.get('alb_xl18', 0), alb_calls=a.get('alb_calls', 0), alb_wait=a.get('alb_wait', 0))


def form(k, v):
    return v ^ MARGIN_X if k == 'dec_margin' else v ^ 1 if k == 'floor_ok' else v


def fold(chain, own):
    """the chain after one more session (dbgsave.h DBG_B_PREV2), written from the header's text, not from the C"""
    c = dict(chain) if chain else dict(boots=0, dirty_age=0, w_dec_flags=0, **{
        'w_' + ('dec_margin_x' if k == 'dec_margin' else 'floor_overwritten' if k == 'floor_ok' else k): 0
        for k in P2_FOLD})
    c['boots'] += 1
    c['w_dec_flags'] |= own['dec_stat'] & 0x003F0000
    for k in P2_FOLD:
        wk = 'w_' + ('dec_margin_x' if k == 'dec_margin' else 'floor_overwritten' if k == 'floor_ok' else k)
        c[wk] = max(c[wk], form(k, own[k]))
    sign = (own['dec_stat'] & 0x001F0000) or any(form(k, own[k]) for k in P2_SIGN)
    c['dirty_age'] = 1 if sign else (c['dirty_age'] + 1 if c['dirty_age'] else 0)
    return c


def chain_of(q):
    return {k: v for k, v in q.items() if k == 'boots' or k == 'dirty_age' or k.startswith('w_')}


def prev2_check(build, rom, recs, old, chk):
    """G: the carried lateness block (see the module text)"""
    sv = bytearray(old) + bytearray(0x1000)
    sv[0x1000:0x2000] = record_v4()
    rec, why = dbgsave.decode(sav_of(bytes(sv)))            # the reader on a version-4 record: no prev2, the note
    txt = dbgsave.report(rec, False) if rec else ''
    chk('G reader  a version-4 record decodes (v%s) with no prev2 and the note that it has none' % (
        rec and rec['head']['version']), rec and rec['head']['version'] == 4 and 'prev2' not in rec and
        "previous session's lateness counters (decoder late words, CPU MATE, SFX feeder): not in this record" in txt,
        why or '')
    f, o = replay(build, rom, recs, bytes(sv))
    b = f.b
    chk('G test    replay after a planted version-4 record ran clean (posts %d)' % o['posts_b'], not o['bad'],
        '; '.join(o['bad'][:3]))
    try:
        t = b.time
        while b.time < t + 10 * fuzz_s1.TIM7:               # 10 more periodic writes after the replay
            b.take()
            b.step(f.rnd.randint(500, 4000))
        rec, why = dbgsave.decode(sav_of(b.save))
        q = rec and rec.get('prev2')
        want = dict(dec_stat=PLANT[16][0], dec_margin=PLANT[16][3], dec_latecnt=7, late=0, discarded=11, aborted=2,
                    abort_landings=1, cycles_max=123456, catchups=42, exc=1, refusals=9, jobs_failed=4, stack_hw=1500,
                    floor_ok=0, late_max=0, alb_wait_max=0, dec_words=1234, dec_time=PLANT[16][2], calls=570,
                    exc_first_cause=0x5, exc_first_epc=0x1234, exc_first_tval=0x80001000, short_calls=0, alb_res=0,
                    alb_under=0, alb_lost=0, alb_calls=0, alb_wait=0)   # (late: the planted late_seen 3 is not carried)
        bad = [k for k in P2_OWN if not q or q.get(k) != want[k]]
        chk('G test    v%s record after the boot and %d writes: prev2 state %s holds the planted words (%d, its late_seen '
            'not carried)%s' % (rec and rec['head']['version'], rec['head']['writes'] if rec else 0, q and q['state'],
                                len(P2_OWN), (' (differ: %s)' % bad) if bad else ''),
            rec and rec['head']['version'] == VERSION and q and q['state'] == 4 and
            not bad, why or '')
        c1 = fold(None, want)
        cq = chain_of(q) if q else {}
        chk('G test    its chain: 1 session = the planted values in their chain form, flags %#x, sign %s back (%s)' % (
            cq.get('w_dec_flags', 0), cq.get('dirty_age'), 'equal' if cq == c1 else 'differs: %s / %s' % (cq, c1)),
            cq == c1 and c1['dirty_age'] == 1 and c1['w_dec_flags'] == 0x00310000 and c1['w_floor_overwritten'] == 1)
        pv = rec and rec.get('prev')
        chk('G test    its prev summary reads the v4 record (state %s, 9494s %s, heartbeat %s)' % (
            pv and pv['state'], pv and pv['n9494'], pv and pv['heartbeat']),
            pv and pv['state'] == 4 and pv['n9494'] == 2691 and pv['heartbeat'] == 496)
        txt = dbgsave.report(rec, False)
        chk('G test    the reader prints it: "sprite decoder late words 7 (must be 0)" and the chain line',
            'previous session (carried from its v4 record at this boot): sprite decoder late words 7 (must be 0)' in txt
            and 'worst over the 1 chained session ' in txt and 'the previous session' in txt.split('lateness sign')[-1])
        # the quit's restart: the session's last write is what the next boot carries
        sess = own_of(rec)
        chain = c1
        for k, play in ((2, 'the replayed session'), (3, 'a quick relaunch'), (4, 'a second quick relaunch')):
            b.soft_reset()
            f.fatal_t = None
            f.released_t = None
            f.boot()
            rec2, why = dbgsave.decode(sav_of(b.save))
            q2 = rec2 and rec2.get('prev2')
            chain = fold(chain, sess)
            bad = [x for x in P2_OWN if not q2 or q2.get(x) != sess[x]]
            cq = chain_of(q2) if q2 else {}
            chk('G test    boot %d after %s (its late words %d, CPU MATE calls %d late %d): prev2 state %s = its last '
                'write%s; chain %s sessions, late words worst %s, flags %#x, margin worst %s, sign %s back%s' % (
                    k, play, sess['dec_latecnt'], sess['calls'], sess['late'], q2 and q2['state'],
                    (' (differ: %s)' % bad) if bad else '', cq.get('boots'),
                    cq.get('w_dec_latecnt'), cq.get('w_dec_flags', 0),
                    dbgsave.margin_text(cq.get('w_dec_margin_x', 0) ^ MARGIN_X, str) if cq.get('w_dec_margin_x') else '-',
                    cq.get('dirty_age'), '' if cq == chain else ' (want %s)' % chain),
                q2 and q2['state'] == VERSION and not bad and cq == chain and cq['boots'] == k and cq['w_dec_latecnt'] >= 7 and
                cq['w_dec_margin_x'] >= PLANT[16][3] ^ MARGIN_X and cq['w_dec_flags'] & 0x00310000 == 0x00310000,
                why or '')
            sess = own_of(rec2)
        sv2 = bytes(b.save)
        chk('G test    game bytes 0x000-0x8FF unchanged through G', sv2[:0x900] == old[:0x900])
    except Stop:
        chk('G test    no model violation', False, '; '.join((b.violations + f.bad)[:3]))
    regions = []
    for fill in (0x00, 0xA5):
        g = fuzz_s1.Fuzz(build, rom, recs, 7, save=bytes(old) + bytes([fill]) * 0x1000)
        try:
            g.boot()
            regions.append(bytes(g.b.save[0x1000:0x2000]))
        except Stop:
            regions.append(None)
    rec, why = dbgsave.decode(sav_of(bytes(old) + regions[1])) if regions[1] else (None, 'no boot')
    chk('G test    a boot over 0xA5 garbage leaves the region as a boot over zeros does (record v%s decodes)' % (
        rec and rec['head']['version']), None not in regions and regions[0] == regions[1] and rec is not None, why or '')
    for ver, st in ((3, 3), (9, 0xFFFFFFFF)):
        sv = bytearray(old) + bytearray(0x1000)
        sv[0x1000:0x2000] = record_v4(ver)
        g = fuzz_s1.Fuzz(build, rom, recs, 7, save=bytes(sv))
        try:
            g.boot()
            rec, why = dbgsave.decode(sav_of(g.b.save))
            q = rec and rec.get('prev2')
            chk('G test    a version-%d record: prev2 state %#x, nothing carried, no chain' % (ver, q['state'] if q else 0),
                q and q['state'] == st and not any(q[k] for k in q if k != 'state'), why or '')
        except Stop:
            chk('G test    version-%d boot: no model violation' % ver, False, '; '.join((g.b.violations + g.bad)[:3]))


# ---- H: the SAT snapshot's layout 2. Planted tables: entries 4 cells x 1 row (8 lines) on lines 16-23
# (group 1) and 40-47 (group 2), the rest 1 x 1 one per 8 lines from line 64 down (no limit there). Per H40 line: more
# than 20 sprites only in group 1 when it has 21 or more; over 40 cells (320 px) in a group of 11 or more. The tile
# field carries the frame's tag and the entry index, so the save tells which frame is in which table.
SNAP_PLAN = (('A', 86, 22, 11), ('B', 83, 12, 0), ('C', 86, 21, 12), ('D', 40, 5, 11), ('E', 10, 0, 0))


def plant_table(tag, g1, g2, n):
    out = []
    for e in range(n):
        if e < g1:
            y, sz = 128 + 16, 0xC                           # 4 x 1 cells
        elif e < g1 + g2:
            y, sz = 128 + 40, 0xC
        else:
            y, sz = 128 + 64 + 8 * (e - g1 - g2), 0x0       # 1 x 1, one per 8 lines (past line 223: off screen)
        link = e + 1 if e + 1 < n else 0
        out.append((y & 0x3FF, (sz << 8) | link, ((ord(tag) - 0x40) << 7) | e, 128 + (e * 37) % 300))
    return out


def plant_want(g1, g2):
    """(lines over 320 px, lines over 20 sprites) of a planted table, from the rule above (not from the reader)"""
    return 8 * (min(g1, 20) * 4 > 40) + 8 * (min(g2, 20) * 4 > 40), 8 * (g1 > 20)


class SnapFuzz(fuzz_s1.Fuzz):
    """the replay with planted sprite tables: at a planted AF post, the 68000 first writes its table and count into cart
    RAM (as the game's compose would have left them), then holds until the thread's copy of that frame has returned (so
    no frame start drops or tears it: the test is of the layout), or with race=True only until that copy has begun (the
    next frame start may then come during it); AF's count, each copy's closed table and the frame starts during a copy
    are recorded. Since 2026-10-18: AF's snapshot bookkeeping (s1_sat_snapshot_later) runs after AF's reply, still in
    its L1, and this rig's 68000 can act between the two (the game cannot: it writes $1F18 only after the next VBlank),
    so the hold also waits for that bookkeeping (hold_af is None until it has run for the planted frame); the count
    itself is read before the reply (body_af), but the AF number the hold needs is the bookkeeping's. A copy is the
    frame's whose request it took: the AF count when the thread's take began (l3_test_work's interrupts-off section),
    not when the copy begins (the hook fix of 2026-10-18: in this rig's fast mode the thread can sit between its take
    and the copy while several frames pass; that copy, taken for an earlier frame, then begins with the planted frame's
    number and released the hold before the planted frame's own take)"""
    def __init__(self, build, *a, plan=None, race=False, **k):
        super().__init__(build, *a, **k)
        from unicorn import UC_HOOK_CODE
        self.plan, self.race, self.hold, self.afs, self.snaps = plan or {}, race, False, [], []
        self.words = {}                                             # tag -> the planted AF post's word (its mode)
        self.in_snap, self.torn_afs, self.hold_af, self.done_af = None, set(), None, None
        self.take_af = None                                         # snap_cnt_af when the thread's last take began
        self.later = self.sym['snap_later'][0]
        for name, fn in (('s1_sat_snapshot_later', self.at_af), ('ppm_snapshot_sat', self.at_snap), ('body_ae', self.at_ae),
                         ('l3_test_work', self.at_take)):
            self.b.uc.hook_add(UC_HOOK_CODE, fn, begin=self.sym[name][0], end=self.sym[name][0])
        n = 0
        for ln in open(os.path.join(build, 'main.dis')):            # the copy's end: the return from each call of it
            m = re.match(r'^\s*([0-9a-f]+):\t[0-9a-f]+\s*\tjal\t[0-9a-f]+ <ppm_snapshot_sat>\s*$', ln)
            if m:
                a = int(m.group(1), 16) + 4
                self.b.uc.hook_add(UC_HOOK_CODE, self.at_snap_end, begin=a, end=a)
                n += 1
        if not n:
            raise ValueError('H: no call of ppm_snapshot_sat in main.dis')

    def at_af(self, uc, addr, size, ud):
        self.afs.append((struct.unpack('<H', uc.mem_read(RAMDP + 0x1F18, 2))[0], self.b.rd32('snap_cnt_af')))
        if self.hold:
            self.hold_af = self.afs[-1][1]          # the planted frame's number: held until its copy is done

    def at_take(self, uc, addr, size, ud):
        self.take_af = self.b.rd32('snap_cnt_af')   # l3_test_work's entry: its interrupts-off take of the request

    def at_snap(self, uc, addr, size, ud):
        self.in_snap = self.take_af if self.take_af is not None else self.b.rd32('snap_cnt_af')
        self.snaps.append((self.b.rd32('snap_af_n'), self.in_snap, bytes(uc.mem_read(RAMDP + 0xB00, 640))))

    def at_snap_end(self, uc, addr, size, ud):
        self.done_af, self.in_snap = self.in_snap, None

    def at_ae(self, uc, addr, size, ud):
        if self.in_snap is not None:
            self.torn_afs.add(self.in_snap)

    def post_b(self, word, args, synth=False):
        p = None if synth else self.plan.get(self.i)
        if p is not None and (word >> 8) == 0xAF:
            tag, n, g1, g2 = p
            self.words[tag] = word
            for e, w in enumerate(plant_table(tag, g1, g2, max(n, 80))):
                self.b.w68_ram(0xB00 + 8 * e, struct.pack('<4H', *w))
            self.b.w68_ram(0x1F18, struct.pack('<H', n))
            self.hold, self.hold_af = True, None    # (set by at_af, after the reply: since 2026-10-18)
        super().post_b(word, args, synth)

    def side_68000(self):
        if self.hold and self.state == 'idle':
            if self.hold_af is None or (self.done_af != self.hold_af and
                                        not (self.race and self.in_snap == self.hold_af)):
                return False
            self.hold = False
        return super().side_68000()

    def drain(self):
        """the replay's drain, then (bounded) until a copy the thread had begun has returned: in the rig's fast mode the
        68000's last posts can come while the thread is still inside ppm_snapshot_sat, and the save is read after the
        run (on the Pocket the session goes on)"""
        super().drain()
        end = self.b.time + 20_000_000
        while self.in_snap is not None and self.b.time < end:
            self.b.take()
            self.b.step(self.rnd.randint(1, 48))


class TakeRace(SnapFuzz):
    """the take race (review finding F1) planted: the 68000 holds after the planted AF until the thread has taken that
    frame's request; the CPU is stopped at `at` (before the copy reads anything) and the 68000 then posts a frame start
    (`ae`: the capture's next AE record), writes the next frame's table (tag 'H') over the cart RAM SAT and holds until
    frame G's copy has returned; the frame start's L1 runs with mepc = `at`"""
    def __init__(self, build, *a, at=None, ae=None, **k):
        super().__init__(build, *a, **k)
        from unicorn import UC_HOOK_CODE
        self.at, self.ae, self.force, self.forced, self.landed = at, ae, False, False, None
        self.b.uc.hook_add(UC_HOOK_CODE, self.at_point, begin=at, end=at)
        a = self.sym['body_ae'][0]
        self.b.uc.hook_add(UC_HOOK_CODE, self.at_ae_land, begin=a, end=a)

    def at_point(self, uc, addr, size, ud):
        if self.hold and not self.forced and self.hold_af is not None and self.b.rd32('snap_cnt_af') == self.hold_af \
                and self.b.rd32('snap_later') == 0:
            self.force = self.forced = True             # the planted frame's request is taken: stop here
            uc.emu_stop()

    def at_ae_land(self, uc, addr, size, ud):
        if self.forced and self.landed is None:
            from unicorn import riscv_const as RC
            self.landed = uc.reg_read(RC.UC_RISCV_REG_MEPC)

    def side_68000(self):
        if self.force and self.state == 'idle':
            self.force = False
            for e, w in enumerate(plant_table('H', 0, 0, 80)):      # the next frame's table under the copy
                self.b.w68_ram(0xB00 + 8 * e, struct.pack('<4H', *w))
            self.post_b(self.ae[0], self.ae[1], synth=True)
            return True
        if self.hold and self.state == 'idle':          # held (after the frame start too) until frame G's copy has
            if self.hold_af is None or self.done_af != self.hold_af:   # returned: the frame start is the one event
                                                                        # in the window
                return False
            self.hold = False
        return fuzz_s1.Fuzz.side_68000(self)


def snap_check(build, rom, recs, old, chk):
    """H: the SAT snapshot's layout 2 (see the module text)"""
    afs = [i for i, r in enumerate(recs) if r[0] == 'B' and (r[1] >> 8) == 0xAF]
    if len(afs) < len(SNAP_PLAN) + 2:
        chk('H test    the replay has %d AF posts (needs %d)' % (len(afs), len(SNAP_PLAN) + 2), False)
        return
    plan = {afs[-len(SNAP_PLAN) - 2 + k]: p for k, p in enumerate(SNAP_PLAN)}
    f = SnapFuzz(build, rom, recs, 7, save=old, plan=plan)
    o = f.run()
    chk('H test    replay with %d planted tables (86, 83, 86, 40, 10 entries) ran clean (posts %d)' % (
        len(SNAP_PLAN), o['posts_b']), not o['bad'], '; '.join(o['bad'][:3]))
    sv = sav_of(f.b.save)
    s = dbgsave.snapshot(sv)
    counts = [n for n, _ in f.afs]
    planted = [p[1] for p in SNAP_PLAN]
    k0 = next((k for k in range(len(counts)) if counts[k:k + len(planted)] == planted), None)
    chk('H test    AF closed the planted counts %s (frame ends %s)' % (planted, k0), k0 is not None)
    if k0 is None or s is None:
        chk('H test    the save holds a snapshot', s is not None)
        return
    af_of = {p[0]: f.afs[k0 + k][1] for k, p in enumerate(SNAP_PLAN)}
    most = max(counts)
    crowd_af = max(af for n, af in f.afs if n == most)
    late_af = max(af for n, af in f.afs if n >= 20)
    taken = {af: (n, sat) for n, af, sat in f.snaps}
    chk('H test    layout 2 (tag S2, last byte 2): the session\'s most %d = AF\'s (%d), over 80: %d = AF\'s (%d)' % (
        s.get('most', -1), most, s.get('over80', -1), sum(1 for n in counts if n > 80)),
        s['layout'] == 2 and s['most'] == most == 86 and s['over80'] == sum(1 for n in counts if n > 80) == 3)
    c, t = s['crowded'], s['latest']
    chk('H test    crowded table = frame C (the latest of the two 86s): frame end %d (C %d, A %d), count %d capped %d, '
        'tags %s' % (c['af'], af_of['C'], af_of['A'], c['true'], c['capped'], sorted({e[2] >> 7 for e in c['sat']})),
        c['af'] == crowd_af == af_of['C'] and c['true'] == 86 and c['capped'] == 80 and
        all(e[2] == ((ord('C') - 0x40) << 7) | i for i, e in enumerate(c['sat'])))
    chk('H test    crowded table = the closed table the thread copied, byte for byte',
        c['af'] in taken and struct.pack('<320H', *[w for e in c['sat'] for w in e]) == taken[c['af']][1])
    chk('H test    latest table = frame D (frame end %d = %d, count %d capped %d), the closed table byte for byte' % (
        t['af'], af_of['D'], t['true'], t['capped']),
        t['af'] == late_af == af_of['D'] and t['true'] == 40 and t['capped'] == 40 and t['af'] in taken and
        struct.pack('<320H', *[w for e in t['sat'] for w in e]) == taken[t['af']][1] and
        all(t['sat'][i][2] == ((ord('D') - 0x40) << 7) | i for i in range(40)))
    # the close is the chip's: an AF02 table over 80 is the chip's multiplex in the cart RAM the thread copies
    # (legacy/026/mame.c chip_af_over80: entries 14-79 relinked to k - 13); AF00 / AF01 keep the links
    mux_c = (f.words.get('C', 0) & 3) == 2
    chk('H test    frame C was posted %04X: the stored table %s the chip\'s AF02 multiplex (entries 14-79 linking to '
        'k - 13), the 40 is not' % (f.words.get('C', 0), 'is' if mux_c else 'is not'),
        c['mux02'] == mux_c and not t['mux02'] and
        (not mux_c or all(c['sat'][k][1] & 0xFF == k - 13 for k in range(14, 80))))
    wc, wt = plant_want(*SNAP_PLAN[2][2:]), plant_want(*SNAP_PLAN[3][2:])
    vc = dbgsave.vdp_lines([tuple(e) for e in plant_table('C', *SNAP_PLAN[2][2:], 80)])[2:]
    chk('H test    the reader\'s line model: frame C as composed %d / %d, the stored latest %d / %d lines over 320 px / '
        'over 20 sprites (the plan: %s, %s); the stored crowded %s' % (
            vc[0], vc[1], t['lines_over_320px'], t['lines_over_20_sprites'], wc, wt,
            'not modelled (the multiplex)' if mux_c else '%s / %s' % (c['lines_over_320px'], c['lines_over_20_sprites'])),
        vc == wc == (16, 8) and (t['lines_over_320px'], t['lines_over_20_sprites']) == wt == (8, 0) and
        ((c['lines_over_320px'], c['lines_over_20_sprites']) == ((None, None) if mux_c else wc)))
    txt = '\n'.join(dbgsave.snapshot_lines(s))
    want_c = ('crowded frame (frame end %d): 86 sprite pieces (over the console\'s 80: %s); lines over 320 px / over 20 '
              'sprites not modelled' % (c['af'], dbgsave.MUX02_WORDS) if mux_c else
              'crowded frame (frame end %d): 86 sprite pieces (over the console\'s 80: 6 not in its table that frame)'
              % c['af'])
    chk('H test    the reader prints "%s" and the session line' % want_c,
        want_c in txt and 'the most sprite pieces in one frame 86; frames over the console\'s 80: 3' in txt and
        'latest busy frame (frame end %d): 40 sprite pieces' % t['af'] in txt, txt.replace('\n', ' | '))
    m = bytearray(f.b.save)
    m[0xFFF] = 0                                            # what a layout-1 image's next write leaves there
    s1 = dbgsave.snapshot(sav_of(bytes(m)))
    chk('H test    the same save with the layout byte cleared reads as layout 1: "%s"' % dbgsave.pieces(s1['last']),
        s1['layout'] == 1 and dbgsave.pieces(s1['last']).startswith('more than 80 sprite pieces'))
    chk('H test    no frame start during a planted frame\'s copy in the held replay (only during frame ends %s, under '
        '20 entries: nothing written), no table flagged torn' % sorted(f.torn_afs),
        not (f.torn_afs & set(af_of.values())) and not c['torn'] and not t['torn'])
    chk('H test    game bytes 0x000-0x8FF unchanged', bytes(f.b.save[:0x900]) == old[:0x900])
    # the race: one planted table of 87, the 68000 going on as soon as the copy has begun (the next frame start may come
    # during it); the save must flag the table torn exactly when a frame start came during its copy
    races = []
    for seed in range(7, 13):
        g = SnapFuzz(build, rom, recs, seed, save=old, plan={afs[-3]: ('F', 87, 22, 11)}, race=True)
        og = g.run()
        sg = dbgsave.snapshot(sav_of(g.b.save))
        af_f = next((af for n, af in g.afs if n == 87), None)
        cg = sg and sg['crowded']
        raced = af_f in g.torn_afs
        ok = (not og['bad'] and cg is not None and cg['af'] == af_f and cg['true'] == 87 and cg['torn'] == raced and
              sg['latest']['torn'] == (raced and sg['latest']['af'] == af_f))
        races.append((seed, raced, ok, cg and cg['torn']))
        if raced and ok:
            txt = '\n'.join(dbgsave.snapshot_lines(sg))
            chk('H race    seed %d: a frame start came during the copy of the 87-entry frame (frame end %d); the save '
                'flags it torn (bit 15 of its count) and the reader prints "TORN COPY"' % (seed, af_f),
                'crowded frame (frame end %d): 87 sprite pieces' % af_f in txt and 'TORN COPY' in txt, txt[-300:])
            break
    chk('H race    the torn flag = a frame start during the copy in every run %s (seed, raced, consistent, flag)' % races,
        all(x[2] for x in races) and any(x[1] for x in races))
    take_race_check(build, rom, recs, old, chk, afs)


def take_race_check(build, rom, recs, old, chk, afs):
    """H take race (F1, planted; see the module text)"""
    dis = open(os.path.join(build, 'main.dis')).read().splitlines()
    i = next(k for k, ln in enumerate(dis) if re.match(r'^[0-9a-f]+ <l3_test_work>:$', ln))
    take = None
    for ln in dis[i + 1:]:
        if not ln.strip():
            break
        m = re.match(r'^\s*[0-9a-f]+:\t\S+\s+\tbnez\ta0,([0-9a-f]+)', ln)
        if m:
            take = int(m.group(1), 16)                  # the take path's first instruction (interrupts open again)
            break
    k0 = afs[-3]
    ae = next(((r[1], r[2]) for r in recs[k0:] if r[0] == 'B' and (r[1] >> 8) == 0xAE), None)
    if take is None or ae is None:
        chk('H take    the take path in l3_test_work (%s) and an AE record after the planted AF (%s)' % (take, ae), False)
        return
    entry = nm(os.path.join(build, 'main.nm'))['ppm_snapshot_sat'][0]
    for name, at in (('the take path\'s first instruction %#x' % take, take), ('ppm_snapshot_sat\'s entry %#x' % entry,
                                                                              entry)):
        g = TakeRace(build, rom, recs, 7, save=old, plan={k0: ('G', 87, 22, 11)}, race=True, at=at, ae=ae)
        og = g.run()
        sg = dbgsave.snapshot(sav_of(g.b.save))
        af_g = next((af for n, af in g.afs if n == 87), None)
        cg = sg and sg['crowded']
        tags = sorted({e[2] >> 7 for e in cg['sat']}) if cg else []
        txt = '\n'.join(dbgsave.snapshot_lines(sg))
        chk('H take    a frame start at %s, after the take of frame G\'s request (87 entries, frame end %s): it landed at '
            '%s; the save keeps G (frame end %s, count %s) flagged torn (%s) with the next frame\'s pieces in it (tags %s), '
            'and the reader prints "TORN COPY"' % (name, af_g, '%#x' % g.landed if g.landed is not None else 'nowhere',
                                                    cg and cg['af'], cg and cg['true'], cg and cg['torn'], tags),
            not og['bad'] and g.landed == g.at and cg is not None and cg['af'] == af_g and cg['true'] == 87 and
            cg['torn'] and (ord('H') - 0x40) in tags and 'TORN COPY' in txt, '; '.join(og['bad'][:3]))



def verdict_of(rec):
    h, s, v = rec['head'], rec['stats'], rec.get('vs')
    return dbgsave.freeze_view(h['clk_hz'], h['now'], s['n9494'], s['t_last_9494'], v['count'] if v else None,
                               v['t_last'] if v else 0)[1]


def vs_freeze(build, rom, recs, old, chk):
    """F: the VS counter in the debug save (see the module text)"""
    from rtlmodel import FRAME_CYCLES
    f, o = replay(build, rom, recs, old)
    b = f.b
    chk('F test    replay before the freeze scenarios ran clean', not o['bad'], '; '.join(o['bad'][:3]))
    try:
        rec, why = dbgsave.decode(sav_of(b.save))
        v = rec and rec.get('vs')
        want = rec['head']['now'] // FRAME_CYCLES if rec else -1      # TIMER and VSCNT both start at the reset
        chk('F test    the record\'s VS count = VSCNT at its write (%s, the board %d..%d)' % (v and v['count'], want - 1, want),
            v is not None and want - 1 <= v['count'] <= want and v['count'] > 0, why or '')
        def run_periods(n):
            t = b.time
            while b.time < t + n * fuzz_s1.TIM7:
                b.take()
                b.step(f.rnd.randint(500, 4000))
        run_periods(6)                                  # the 68000 silent, the VDP running (the watchdog needs ~39)
        rec, why = dbgsave.decode(sav_of(b.save))
        vd = rec and verdict_of(rec)
        chk('F test    6 TIM7 periods with no 9494, VDP running -> "%s"' % vd,
            vd == '68000 STOPPED, VDP alive (a dead or paused 68000)' and f.fatal_t is None, why or '')
        b.vdp_stop()
        frozen = b.vs_count()
        run_periods(6)
        rec, why = dbgsave.decode(sav_of(b.save))
        vd = rec and verdict_of(rec)
        chk('F test    the VDP stopped too (count frozen at %d), 6 periods -> "%s"' % (frozen, vd),
            vd == 'VDP STOPPED and no 9494 (a dead VDP or its clock)' and rec['vs']['count'] == frozen and
            f.fatal_t is None, why or '')
        b.soft_reset()
        f.fatal_t = None
        f.released_t = None
        f.boot()
        rec, why = dbgsave.decode(sav_of(b.save))
        p = rec and rec.get('prev')
        pv = p and dbgsave.freeze_view(rec['head']['clk_hz'], p['now'], p['n9494'], p['t_last_9494'], p.get('vs_count'),
                                       p.get('t_last_vs', 0))[1]
        chk('F test    Soft Reset: prev v%s carries VS count %s (%d) and "%s"; this session VS %s' % (
            p and p['state'], p and p.get('vs_count'), frozen, pv, rec and rec['vs']['count']),
            p and p['state'] == VERSION and p.get('vs_count') == frozen and pv == 'VDP STOPPED and no 9494 (a dead VDP or its clock)'
            and rec['vs']['count'] <= rec['head']['now'] // FRAME_CYCLES, why or '')
        sv = bytes(b.save)
        chk('F test    game bytes 0x000-0x8FF unchanged through the freeze scenarios', sv[:0x900] == old[:0x900])
    except Stop:
        chk('F test    no model violation', False, '; '.join((b.violations + f.bad)[:3]))


def main(build_test, rom, recs_all):
    cut = next((i for i, r in enumerate(recs_all) if r[0] == 'F' and r[1] > FRAMES), len(recs_all))
    recs = recs_all[:cut]
    build_rel = os.path.join(os.path.dirname(build_test), 'release')
    res = []

    def chk(name, ok, info=''):
        res.append((name, bool(ok)))
        print('%-4s %s %s' % ('PASS' if ok else 'FAIL', name, info))

    old = save_026(11)
    # ---- A: 0.2.x import, RELEASE and TEST
    for var, build in (('release', build_rel), ('test', build_test)):
        if not os.path.exists(os.path.join(build, 'main.nm')):
            chk('A %s image built' % var, False, build)
            continue
        f, o = replay(build, rom, recs, old)
        sv = bytes(f.b.save)
        chk('A %-7s the replay ran clean (posts %d, %d records)' % (var, o['posts_b'], o['records']), not o['bad'],
            '; '.join(o['bad'][:3]))
        chk('A %-7s 0.2.x game bytes 0x000-0x8FF unchanged' % var, sv[:0x900] == old[:0x900])
        if var == 'release':
            chk('A %-7s nothing written anywhere (0x900-0x1FFF as loaded)' % var, sv[0x900:0x1000] == old[0x900:] and
                not any(sv[0x1000:]))
        else:
            n = sum(1 for i in range(0x900, 0x1000) if sv[i] != old[i])
            rec, why = dbgsave.decode(sav_of(sv))
            chk('A %-7s debug record at 0x1000 decodes (v%s), prev = none, prev2 = none' % (
                var, rec['head']['version'] if rec else '-'),
                rec is not None and rec['head']['version'] == VERSION and rec.get('prev', {}).get('state') == 0 and
                rec.get('prev2', {}).get('state') == 0 and not any(rec['prev2'].values()), why or '')
            chk('A %-7s 0x900-0xFFF: the 0.2.6 TEST snapshot window (%d bytes rewritten, as 0.2.6 TEST)' % (var, n), True)
    # ---- B: a 4 KB save RAM: the probe turns the debug save off
    if os.path.exists(os.path.join(build_test, 'main.nm')):
        f, o = replay(build_test, rom, recs, old, save_kb=4)
        sv = bytes(f.b.save)
        chk('B test    4 KB save RAM: replay clean', not o['bad'], '; '.join(o['bad'][:3]))
        chk('B test    4 KB save RAM: game bytes 0x000-0x8FF unchanged (the probed byte put back)', sv[:0x900] == old[:0x900])
        on = f.b.rd32('on') if 'on' in f.b.sym else None
        chk('B test    4 KB save RAM: the debug save is off', on == 0, 'on = %s' % on)
    # ---- C, D: the fatal halt reaches the .sav; Soft Resets keep it
    f, o = replay(build_test, rom, recs, old)
    b = f.b
    chk('C test    replay before the halt ran clean', not o['bad'], '; '.join(o['bad'][:3]))
    try:
        f.post_b(0x8500, bytes(32))
        end = b.time + 8_000_000
        while b.time < end and f.fatal_t is None:
            b.take()
            b.step(f.rnd.randint(1, 48))
        chk('C test    85 reached the fatal halt', f.fatal_t is not None)
        t_halt = b.time
        while b.time < t_halt + 2_000_000:              # (short steps: the halt's waits read TIMER, rtlmodel.py)
            b.take()
            b.step(48)
        rec, why = dbgsave.decode(sav_of(b.save))
        fat = rec and rec['fatal']
        chk('C test    the .sav holds the halt at once: event %#x' % (fat['code'] if fat else 0),
            fat and fat['code'] == EV_85, why or '')
        w1 = rec['head']['writes'] if rec else 0
        while b.time < t_halt + 64_000_000:                 # 65,536 polls: ~43 M cycles at the model's CPI 6
            b.step(48)
        rec2, why = dbgsave.decode(sav_of(b.save))
        chk('C test    the record is rewritten while the halt polls (writes %d -> %d, polls in the record %d)' % (
            w1, rec2['head']['writes'] if rec2 else 0, rec2['fatal']['polls'] if rec2 else 0),
            rec2 and rec2['head']['writes'] > w1 and rec2['fatal']['polls'] >= 65536, why or '')
        sv = bytes(b.save)
        chk('E test    the game bytes 0x000-0x8FF unchanged through the halt', sv[:0x900] == old[:0x900])
        # D: Soft Reset, the new boot's record carries the halt
        for k in (1, 2):
            b.soft_reset()
            f.fatal_t = None
            f.released_t = None
            f.boot()
            rec3, why = dbgsave.decode(sav_of(b.save))
            p = rec3 and rec3.get('prev')
            chk('D test    Soft Reset %d: prev state %s, fatal age %s, event %#x; this session no halt' % (
                k, p and p['state'], p and p['fatal_age'], p['fatal_code'] if p else 0),
                p and p['state'] == VERSION and p['fatal_age'] == k and p['fatal_code'] == EV_85 and rec3['fatal']['code'] == 0,
                why or '')
        sv = bytes(b.save)
        chk('E test    game bytes 0x000-0x8FF unchanged after both resets', sv[:0x900] == old[:0x900])
    except Stop:
        chk('C/D test  no model violation', False, '; '.join((b.violations + f.bad)[:3]))
    vs_freeze(build_test, rom, recs, old, chk)
    prev2_check(build_test, rom, recs, old, chk)
    snap_check(build_test, rom, recs, old, chk)
    ok = all(x for n, x in res)
    print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
    return 0 if ok else 1
