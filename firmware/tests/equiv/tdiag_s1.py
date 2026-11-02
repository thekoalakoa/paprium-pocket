#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""tdiag_s1.py - the TEST debug save's version 6 (2026-10-19: the CPU MATE late counter and the album recorder; and a
fix the same day) on the
stage-1 TEST image (FW_S1, our new firmware) in the RV32 board model (tests/equiv/rtlmodel.py; the 68000 side is
fuzz_s1.py's: the solo capture). What it measures, it measures in the model (the firmware runs as built; the board
around it is a model). J, M, W and F below are this rig's sections; test builds 4a and 4b are firmware builds B Jam
tested on his hardware.

    python -I -B tests/equiv/tdiag_s1.py [--build build/s1/pocket72k/test] [--frames 600] [--seeds 3,5,7,11] [--no-forced]
    python -I -B tests/equiv/tdiag_s1.py --negative [late|disc|tick]
        a planted image (rebuilt first; runs in order, stopping at the first that catches it):
          late  test_bug_late (GLUE_BUG 1): the LATE flag not cleared before each ARM, as before 2026-10-19: J2 must
                fail (section J on the seeds; J3 may fail with it: an on-time ARM's TICK reading is no lateness);
          disc  test_bug_disc (GLUE_BUG 2): a late ARM whose publish read finds the game's next post already in is not
                counted, as in the version of 2026-10-19: F1 (else J2 or W1 on the seeds) must fail, every other
                check pass;
          tick  test_bug_tick (GLUE_BUG 3): late_max takes a TICK read
          made after a newer post, as in the version of 2026-10-19: F2 (else
                J3 or W2 on the seeds) must fail, every other check pass.

Each seed of the sweep runs sections J, M and W on one board (the replay, the album scenario, the whole run, the quit); then
one more board (seed 3) runs section J with the races of section F placed in it.
J  the CPU MATE late counter (buddy/s1_glue.c late_note and publish) against the Mega CD link stub as paprium_mcd_link.sv
   runs it (LinkBoard below, a model written from that file): a post starts the 12.5 MHz sub-cycle tick (its origin
   shifted by a random -jitter/4..+jitter sub cycles a post, as HOLD would shift it, so that the brain's answers land on
   both sides of D_WORD: in this rig every call takes the brain's short word-0000 path, D_WORD 465); an ARM latches
   D_WORD / D_BUSY and, with the tick already at D_WORD or past it, sets the sticky LATE flag and counts (the RTL's
   late_count); the release comes at D_BUSY, at once for an ARM past
   it, and TICK freezes there; a post restarts TICK and the post count;
   LCLR clears flags; BUSY is honest only with option D on. The sub CPU posts again at random once BUSY is down
   (fuzz_s1: as soon as one model step after the release, a stress; the game posts once a gameplay pass). The model
   follows each ARM to its fate (the glue's own counters, watched as they are written: published, discarded, arm_lost,
   the late count, late_max) and each TICK read with the post count at that read. After the replay, settled (the sub
   silent until no call is left in flight, and a debug-save write after it):
     J1 a fair test: brain calls, late ARMs and on-time ARMs; every ARM taken has one fate, the firmware's published
        count is the ARMs it published, and each one it discarded was overtaken (the game's next post came before its
        publish read: the answer was delivered, then publish was preempted past the release and the next post);
     J2 the firmware's late count == the stub's late ARMs (the RTL's own count), each late ARM counted once, an on-time
        one never (the overtaken ones on the discard path: since the fix);
     J3 its largest lateness == the largest (TICK read after a late ARM - D_WORD) over the reads with no post since that
        ARM (a read after a newer post is the newer post's tick and must be left out: since the fix), and that is the
        true largest, the tick at the ARM - D_WORD (exact: that ARM is past D_BUSY, so TICK froze at its tick) - unless
        the true largest answer's own reading came after the game's next post: then nothing the firmware can read holds
        it (TICK restarts at a post), the check prints it as NOT READABLE and late_max must be the largest readable,
        below it; each late answer published read TICK once, none on the discard path; no read below the tick at its
        ARM; an ARM past D_BUSY reads it exactly;
     J4 its short-path count == the published ARMs with D_WORD under 1,000 sub cycles; the retired late_seen stays 0;
     J5 the debug save's glue block (version 6) holds the same words, and the reader prints them as late answers.
M  the album recorder (interim/album/mdp.c album_call / s1_album_poll) against the MD+ adapter's result word and XLINK's
   CDDA counters as paprium_mdp_adapter.sv / paprium_xlink.sv present them (modelled: the result word is {track, 7'b0,
   playing}, the track taken at the request; underruns climb at 48 kHz while a requested track does not play; the rig's
   MD+ block is RAM, so the command read-back is the last word written). The album is switched on in the model (mdp_on 1:
   the rig has no MD+ ids, so the init fails, which M0 checks first). Then: 8C8B (play 11, loop) with playing 0 for about
   a second (M1: the record shows track 11 requested that long ago, still waiting, the underruns since); playing 1 (M2:
   the wait frozen at the first write that saw it); 8D08 (M3: the stop as the last call, the play kept); 8C0B (play 11
   once) left silent for 1.5 s (M4: a longer wait, the session's longest); 8D08 again (M5: a stop ends that wait
   'without playing'); then 8C8B silent once more, settled as J was, and:
   Each step starts with the game's frame tick (9494 on $1FEC; the game posts it every frame while it plays): it feeds
   the cart's watchdog (core/wdog: 39 counted TIM7 ticks with no 9494 = a fatal halt). Before test build 4b
   (2026-10-22) M had none: J's last replayed tick to the end of W's settling is ~4.6 s, so the watchdog halted the MCU
   in every J+M run, inside M6 or W's settling depending on how many ticks the rig's random Pocket-menu opens gated
   (measured on seed 3: test build 4a's image 45.2 TIM7 periods after the last 9494 with 7 gated ticks, test build
   4b's 41.2 with 3); W0 failed only when a call was in flight at that instant (test build 4b's seed 3: 0.86 ms after
   an ARM), else it passed by luck.
W  the whole run to the quit (J and M: ~1,700-1,900 brain calls a seed, where the races show on their own): W1, W2, W3
   = J2, J3, J4 over every ARM (W3 with every ARM's fate); W0: settled, and no fatal halt in the whole run. Then the
   Pocket's quit (a Soft Reset, M6): the next boot's
   prev2 holds the album words and the CPU MATE words of the last write before it, the chain the longest wait and the
   largest lateness, no lateness sign for the late answers, and the reader prints 'music (previous session): track 11
   requested ...'.
F  the two races placed on purpose (section_f), so that each net is exercised on every run whatever the seed: on late
   ARMs past D_BUSY (released at once), F_N posts just before the firmware's first LSTAT read after the ARM (F1: each
   answer discarded and counted once) and F_N just before its TICK read, which then reads the newer post's 0 (F2: each
   counted once and published, none in late_max). J1-J5 hold on that board too.
Exit 0 = PASS, 1 = FAIL (with --negative: the planted fault caught by its own checks, everything else as above), 2 = setup
error."""
import argparse, gc, os, random, struct, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import dbgsave                                           # noqa: E402
import fuzz_s1                                           # noqa: E402
import rtlmodel                                          # noqa: E402
from rtlmodel import Stop, LS_SEND, LS_LATE, LS_BUSY, LS_ARMED, MDP   # noqa: E402

SUB_HZ = 12_500_000
SHORT_DWORD = 1000                                      # buddy/s1_glue.h S1_SHORT_DWORD
MDP_RES, MDP_CMD = MDP + 0x3F7FC, MDP + 0x3F7FE         # interim/album/mdp.c: the MD+ block at ADDR_MDP + 0x3F7F6
GLUE = dict(sends=2, calls=4, published=5, discarded=6, ignored_halted=9, late_seen=17, arm_lost=18, late=22, late_max=23,
            short_calls=24)                             # s1_glue_stats_t words
FATES = {5: 'published', 6: 'discarded', 18: 'arm_lost'}
SEEDS = (3, 5, 7, 11)
F_SEED, F_N = 3, 3                                     # section F: its board's seed, the races of each kind
NEG = {'late': dict(image='test_bug_late', target=('J2',), allowed=('J3',), sections='J',
                    what='the LATE flag not cleared before each ARM (GLUE_BUG 1)'),
       'disc': dict(image='test_bug_disc', target=('F1', 'J2', 'W1'), allowed=(), sections='JM',
                    what='a late ARM overtaken before its publish read not counted (GLUE_BUG 2)'),
       'tick': dict(image='test_bug_tick', target=('F2', 'J3', 'W2'), allowed=(), sections='JM',
                    what='late_max from a TICK read after a newer post (GLUE_BUG 3)')}


def sav_of(save):
    b = bytes(save)
    s = bytearray(len(b))
    s[0::2], s[1::2] = b[1::2], b[0::2]
    return bytes(s)


class LinkBoard(rtlmodel.Board):
    """rtlmodel's board with XLINK's option-D link as paprium_mcd_link.sv / paprium_xlink.sv run it (a model; see the
    module text) and the album's MD+ result word and XLINK 0x14 / 0x18 as the adapter and the CDDA player give them"""
    jitter = 0
    seed = 1
    quiet = False                           # the sub CPU posts no more (a rig's settled reading)
    force = (0, 0)                          # section F: (overtaken, stale) forced races still to place

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.lk_rnd = random.Random(LinkBoard.seed * 7919 + 1)
        self.link_reset()
        self.lk_arms = []
        self.f_left = list(LinkBoard.force)
        self.f_pending = None               # 'over' / 'stale': the forced post waits for the firmware's next read
        self.alb = dict(track=0, playing=0, starve_t=None, und0=0, xl18=(5 << 16) | 2, snoop=0, writes=[])
        from unicorn import UC_HOOK_MEM_WRITE
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self.mdp_w, begin=MDP_CMD, end=MDP_CMD + 1)
        self.glue_base = self.sym['s1_glue_stats'][0]
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self.glue_w, begin=self.glue_base + 4 * 5, end=self.glue_base + 4 * 25 - 1)

    def link_reset(self):                   # the cartridge reset (shell_reset): the stub's own registers
        self.lk_run = self.lk_armed = False
        self.lk_t0 = self.lk_frozen = 0
        self.lk_dw = self.lk_db = 0
        self.d_word = self.d_busy = self.pend = 0
        self.late_count = 0

    def soft_reset(self):
        super().soft_reset()
        self.link_reset()

    def lk_tick(self):
        if not self.lk_run:
            return self.lk_frozen
        return min(0xFFFFFF, max(0, (self.time - self.lk_t0) * SUB_HZ // self.sysinfo_clk))

    def lk_update(self):
        if self.lk_run and self.lk_armed and self.lk_tick() >= self.lk_db:
            self.lk_frozen = max(self.lk_db, self.lk_arms[-1]['tick'])   # the release clock: tick = D_BUSY, or the ARM's
            self.lk_run = self.lk_armed = False
            self.ls &= ~(LS_BUSY | LS_ARMED)

    def step(self, n):
        super().step(n)
        self.lk_update()

    def send(self, forced=False):
        if self.quiet:
            return
        self.lk_update()
        super().send()                      # posts, send pending + busy, CAUSE.S (rtlmodel)
        if not (self.lctrl & 1):
            self.ls &= ~LS_BUSY             # busy <= on: honest BUSY only with option D on
        # (a forced post, section F: no shift, so a TICK read at once reads 0; the jitter's sequence untouched)
        shift = self.lk_rnd.randint(-self.jitter // 4, self.jitter) if self.jitter and not forced else 0
        self.lk_run, self.lk_armed, self.lk_frozen = True, False, 0
        self.lk_t0 = self.time + shift * self.sysinfo_clk // SUB_HZ

    def xl_w(self, uc, off, size, value, ud):
        self.lk_update()
        if off == 0x24:
            self.ls &= ~(value & 0xF)
        elif off == 0x28:
            self.d_word = value & 0xFFFFFF
        elif off == 0x2C:
            self.d_busy = value & 0xFFFFFF
        elif off == 0x30:
            self.pend = value & 0xFFFF
        elif off == 0x34:
            if not self.lk_run:             # no timer running: the RTL ignores it
                self.lk_arms.append(dict(t=self.time, ignored=True))
                return
            t = self.lk_tick()
            late = t >= self.d_word
            self.lk_armed, self.lk_dw, self.lk_db = True, self.d_word, self.d_busy
            self.ls |= LS_ARMED
            if late:
                self.ls |= LS_LATE          # set in the ARM's clock: an event wins over a same-clock clear
                self.late_count += 1
            self.lk_arms.append(dict(t=self.time, tick=t, dw=self.d_word, db=self.d_busy, late=late, posts=self.posts_s,
                                     reads=[], fate=None, counted=0, max_w=[], forced=None))
            self.f_pending = None
            if late and t >= self.d_busy and not self.quiet and (self.f_left[0] or self.f_left[1]):
                # section F: this late ARM is released at once (past D_BUSY), so BUSY is down and the sub may post; the
                # post is placed just before the firmware's next LSTAT read (overtaken: the discard path) or its TICK
                # read (stale: the newer post's tick)
                k = 0 if self.f_left[0] else 1
                self.f_left[k] -= 1
                self.f_pending = self.lk_arms[-1]['forced'] = ('over', 'stale')[k]
            self.lk_update()
        else:
            super().xl_w(uc, off, size, value, ud)

    def xl_r(self, uc, off, size, ud):
        self.lk_update()
        if (off == 0x20 and self.f_pending == 'over') or (off == 0x38 and self.f_pending == 'stale'):
            self.f_pending = None
            self.send(forced=True)          # the forced post (section F)
        if off == 0x20:
            return (self.ls & 0xFF) | (min(self.late_count, 255) << 8) | ((self.posts_s & 0xFFFF) << 16)
        if off == 0x38:
            v = self.lk_tick() & 0xFFFFFF
            if self.lk_arms and not self.lk_arms[-1].get('ignored'):
                self.lk_arms[-1]['reads'].append((v, self.posts_s))     # with the post count at the read
            return v
        if off == 0x14:
            return (self.alb['snoop'] << 16) | self.underruns_now()
        if off == 0x18:
            return self.alb['xl18']
        return super().xl_r(uc, off, size, ud)

    def glue_w(self, uc, access, addr, size, value, ud):
        """the glue's counters as the firmware writes them, given to the latest ARM: its fate (the publish that wrote it
        ends with exactly one of published / discarded / arm_lost; run_call's own discards come with no ARM pending and
        are not an ARM's), the late count's increments, late_max's stores. 0 = crt0's clear at a boot: no event."""
        k = (addr - self.glue_base) >> 2
        if size != 4 or value == 0 or not self.lk_arms:
            return
        a = self.lk_arms[-1]
        if k in FATES:
            if a.get('fate') is None:
                a['fate'], a['fate_posts'] = FATES[k], self.posts_s
        elif k == 22 and not a.get('ignored'):
            a['counted'] += 1
        elif k == 23 and not a.get('ignored'):
            a['max_w'].append(value)

    # ---- the album side
    def underruns_now(self):
        a = self.alb
        if a['starve_t'] is None:
            return a['und0']
        return min(0xFFFF, a['und0'] + (self.time - a['starve_t']) * 48000 // self.sysinfo_clk)

    def set_playing(self, on):
        a = self.alb
        if on and a['starve_t'] is not None:
            a['und0'], a['starve_t'] = self.underruns_now(), None
        a['playing'] = 1 if on else 0
        self.res_write()

    def res_write(self):
        self.uc.mem_write(MDP_RES, struct.pack('<H', (self.alb['track'] << 8) | self.alb['playing']))

    def mdp_w(self, uc, access, addr, size, value, ud):
        """the firmware's MD+ command write: the adapter's request (paprium_mdp_adapter.sv), the fetch's track at once"""
        v = value & 0xFFFF
        a = self.alb
        a['writes'].append((self.time, self.vs_count(), v))
        if v >> 8 in (0x11, 0x12):
            a['track'], a['playing'] = v & 0xFF, 0
            a['und0'], a['starve_t'] = self.underruns_now(), self.time    # the ring flushed: it starves until it plays
        elif v >> 8 == 0x13:
            a['playing'] = 0
            a['und0'], a['starve_t'] = self.underruns_now(), None         # paused: not counted (cdda_play)
        self.res_write()


class Rig:
    def __init__(self, build, rom, recs, seed):
        fuzz_s1.Board = LinkBoard
        LinkBoard.seed = seed
        self.seed = seed
        self.f = fuzz_s1.Fuzz(build, rom, recs, seed)
        self.b = self.f.b
        self.res = []
        self.stats = {}

    def chk(self, name, ok, info=''):
        self.res.append((name.split()[0], bool(ok)))
        print('%-4s s%-2d %s %s' % ('PASS' if ok else 'FAIL', self.seed, name, info), flush=True)

    def glue(self):
        return {k: self.b.rd32('s1_glue_stats', w) for k, w in GLUE.items()}

    def run_for(self, cycles):
        """the 68000 side (fuzz_s1: the waits, the sub CPU's posts) and the MCU for this many model cycles"""
        f, b = self.f, self.b
        end = b.time + cycles
        while b.time < end:
            f.side_68000()
            b.take()
            b.step(f.rnd.randint(1, 48))

    def settle(self):
        """the sub CPU silent until no brain call is in flight (no send pending, every call taken run, the latest ARM's
        publish ended), then two TIM7 periods so that a debug-save write follows the last change; the sub posts again
        afterwards. Returns the periods it took (None: still busy after 40)."""
        b = self.b
        b.quiet = True
        self.run_for(3 * fuzz_s1.TIM7)
        n = 3
        while n < 40:
            g = self.glue()
            arms = [a for a in b.lk_arms if not a.get('ignored')]
            if not (b.ls & LS_SEND) and g['sends'] == g['calls'] + g['ignored_halted'] and \
                    not (arms and arms[-1]['fate'] is None):
                break
            self.run_for(fuzz_s1.TIM7)
            n += 1
        self.run_for(2 * fuzz_s1.TIM7)
        b.quiet = False
        return n if n < 40 else None

    def post(self, word, wait=60_000_000):
        """one B post from the 68000, then until it and its job are done (bit 14 clear)"""
        f, b = self.f, self.b
        f.post_b(word, bytes(32))
        end = b.time + wait
        while b.time < end and f.state != 'idle':
            f.side_68000()
            b.take()
            b.step(f.rnd.randint(1, 48))
        return f.state == 'idle'

    def frame_tick(self, wait=60_000_000):
        """the game's frame tick: 9494 on $1FEC (A) once the A mailbox is free, then until it is finished; it feeds the
        cart's watchdog (section M; see the docstring)"""
        f, b = self.f, self.b
        end = b.time + wait
        while b.time < end and f.cur_a is not None and f.cur_a.get('fin') is None:
            f.side_68000()
            b.take()
            b.step(f.rnd.randint(1, 48))
        f.post_a(0x9494)
        while b.time < end and f.cur_a.get('fin') is None:
            f.side_68000()
            b.take()
            b.step(f.rnd.randint(1, 48))
        return f.cur_a.get('fin') is not None

    def record(self):
        rec, why = dbgsave.decode(sav_of(self.b.save))
        return rec, why


def analyse(b):
    """the stub model's view of every ARM so far against what the firmware did with it (see LinkBoard.glue_w)"""
    arms = [a for a in b.lk_arms if not a.get('ignored')]
    late = [a for a in arms if a['late']]
    o = dict(arms=arms, late=late, ignored=len(b.lk_arms) - len(arms))
    o['pub'] = [a for a in arms if a['fate'] == 'published']
    o['disc'] = [a for a in arms if a['fate'] == 'discarded']
    o['lost'] = [a for a in arms if a['fate'] == 'arm_lost']
    o['nofate'] = [a for a in arms if a['fate'] is None]
    o['not_overtaken'] = [a for a in o['disc'] if a['fate_posts'] == a['posts']]
    o['over_late'] = [a for a in o['disc'] if a['late']]
    o['miscount'] = [a for a in arms if a['counted'] != (1 if a['late'] else 0)]
    o['late_short'] = [a for a in late if a['counted'] < 1]
    o['late_twice'] = [a for a in late if a['counted'] > 1]
    o['ontime_counted'] = [a for a in arms if not a['late'] and a['counted']]
    valid, stale = [], 0
    for a in late:
        rs = [v for v, p in a['reads'] if p == a['posts']]
        stale += sum(1 for v, p in a['reads'] if p != a['posts'])
        if rs:
            valid.append((a, rs[0]))
    o['stale'] = stale
    o['stale_arms'] = sum(1 for a in late if any(p != a['posts'] for v, p in a['reads']))
    o['want_fw'] = max([(v - a['dw']) & 0xFFFFFF for a, v in valid] or [0])
    o['true_max'] = max([a['tick'] - a['dw'] for a in late] or [0])
    # the true largest answer's own lateness is unreadable when its TICK read came after the game's next post (TICK
    # restarts at a post: nothing the firmware reads afterwards holds it), or it went the discard path (no read)
    tops = [a for a in late if a['tick'] - a['dw'] == o['true_max']]
    rd = [a for a in tops if any(a is x for x, v in valid)]
    tm = (rd or tops or [None])[0]
    o['true_readable'] = bool(rd)
    o['true_exact'] = bool(tm and tm['tick'] >= tm['db'])
    o['true_arm'] = tm
    o['below'] = [a for a, v in valid if v < a['tick']]
    o['frozen'] = [(a, v) for a, v in valid if a['tick'] >= a['db']]
    o['frozen_bad'] = [a for a, v in o['frozen'] if v != a['tick']]
    o['run_ahead'] = max([v - a['tick'] for a, v in valid] or [0])
    o['reads_bad'] = [a for a in late if len(a['reads']) != (1 if a['fate'] == 'published' else 0)]
    o['short_pub'] = sum(1 for a in o['pub'] if a['dw'] < SHORT_DWORD)
    dws = sorted(a['dw'] for a in arms)
    o['dws'] = (dws[0], dws[len(dws) // 2], dws[-1]) if dws else (0, 0, 0)
    return o


def count_checks(rg, tag, g, o):
    """the count, the largest lateness and the fates against the stub model (J1-J4, or W1-W3 over the whole run)"""
    b = rg.b
    if tag == 'J':
        rg.chk('J1 a fair test: %d calls, %d ARMs taken (%d ignored), %d late and %d on time (the stub\'s late_count %d); '
               'fates: published %d (the firmware\'s %d), discarded after the ARM %d (overtaken by the game\'s next post '
               'before the publish read: %d), ARM lost %d, none %d' % (
                   g['calls'], len(o['arms']), o['ignored'], len(o['late']), len(o['arms']) - len(o['late']), b.late_count,
                   len(o['pub']), g['published'], len(o['disc']), len(o['disc']) - len(o['not_overtaken']),
                   len(o['lost']), len(o['nofate'])),
               g['calls'] >= 20 and o['late'] and len(o['late']) < len(o['arms']) and b.late_count == len(o['late']) and
               not o['nofate'] and not o['lost'] and g['published'] == len(o['pub']) and not o['not_overtaken'])
    n2 = 'J2' if tag == 'J' else 'W1'
    rg.chk('%s %sthe firmware\'s late count %d == the stub\'s late ARMs %d (late_count %d); each late ARM counted once '
           '(%d not, %d twice), no on-time ARM counted (%d); %d of them overtaken before their publish read, counted on '
           'the discard path' % (n2, 'the whole run to the quit (J and M): ' if tag == 'W' else '', g['late'],
                                 len(o['late']), b.late_count, len(o['late_short']), len(o['late_twice']),
                                 len(o['ontime_counted']), len(o['over_late'])),
           g['late'] == len(o['late']) == b.late_count and not o['miscount'])
    n3 = 'J3' if tag == 'J' else 'W2'
    tm = o['true_arm']
    if not tm:
        rel, ok_true = '(no late ARM)', g['late_max'] == 0
    elif o['true_readable']:
        rel = ('== the true largest, the tick at the ARM - D_WORD %d (that ARM past D_BUSY, so exact: %s)' % (
            o['true_max'], 'yes' if o['true_exact'] else 'NO'))
        ok_true = g['late_max'] == o['true_max'] and o['true_exact']
    else:
        rel = ('; the true largest, %d sub cycles, was NOT READABLE: that answer\'s %s (TICK restarts at a post; nothing '
               'read later holds it), so the largest readable stands and is below it' % (
                   o['true_max'], 'publish read came after the game\'s next post (no TICK read)' if tm['fate'] ==
                   'discarded' else 'TICK read came after the game\'s next post (read %s, the newer post\'s)' %
                   [v for v, p in tm['reads']]))
        ok_true = g['late_max'] <= o['true_max']
    rg.chk('%s its largest lateness %d sub cycles (%.1f us) == the largest TICK read with no post since its late ARM - '
           'D_WORD %d (%d reads after a newer post, on %d late ARMs, left out) %s; each late answer published read TICK '
           'once and none on the discard path: %s; no read below its ARM\'s tick: %s; %d ARMs past D_BUSY read their '
           'frozen tick exactly: %s; the others read a running tick, up to %d sub cycles later in this model\'s steps' % (
               n3, g['late_max'], g['late_max'] / 12.5, o['want_fw'], o['stale'], o['stale_arms'], rel,
               'yes' if not o['reads_bad'] else '%d not' % len(o['reads_bad']),
               'yes' if not o['below'] else '%d below' % len(o['below']), len(o['frozen']), not o['frozen_bad'],
               o['run_ahead']),
           g['late_max'] == o['want_fw'] and ok_true and not o['reads_bad'] and not o['below'] and not o['frozen_bad'])
    n4 = 'J4' if tag == 'J' else 'W3'
    rg.chk('%s short-path calls %d == published ARMs with D_WORD under %d sub cycles %d (D_WORD min %d, median %d, max %d); '
           'the retired late_seen %d%s' % (
               n4, g['short_calls'], SHORT_DWORD, o['short_pub'], o['dws'][0], o['dws'][1], o['dws'][2], g['late_seen'],
               '' if tag == 'J' else '; fates: published %d (the firmware\'s %d), discarded after the ARM %d (all '
               'overtaken: %s), ARM lost %d, none %d' % (len(o['pub']), g['published'], len(o['disc']),
                                                         'yes' if not o['not_overtaken'] else 'NO', len(o['lost']),
                                                         len(o['nofate']))),
           g['short_calls'] == o['short_pub'] and g['late_seen'] == 0 and
           (tag == 'J' or (not o['nofate'] and not o['lost'] and g['published'] == len(o['pub']) and
                           not o['not_overtaken'])))


def section_j(rg):
    f, b = rg.f, rg.b
    o = f.run()
    rg.chk('J0 replay ran clean (%d B posts, %d SENDs, %d brain calls)' % (o['posts_b'], o['sends'], o['brain_calls']),
           not o['bad'], '; '.join(o['bad'][:3]))
    per = rg.settle()
    g = rg.glue()
    o = analyse(b)
    count_checks(rg, 'J', g, o)
    rg.stats['j_true'] = (g['late_max'], o['true_max'], o['true_readable'])
    rec, why = rg.record()
    gl = rec and rec['glue']
    same = gl and all(gl.get(k) == g[k] for k in ('late', 'late_max', 'short_calls', 'calls', 'published', 'late_seen'))
    txt = dbgsave.report(rec, False) if rec else ''
    rg.chk('J5 settled (the sub silent %s TIM7 periods): the debug save (v%s) holds the glue words (late %s of %s '
           'published, late_max %s, short %s) and the reader prints them as late answers' % (
               per, rec and rec['head']['version'], gl and gl.get('late'), gl and gl.get('published'),
               gl and gl.get('late_max'), gl and gl.get('short_calls')),
           per and rec and rec['head']['version'] in (6, 7, 8) and same and   # 7: test build 4a, 8: 4b
                                                                              # (the glue block unchanged)
           ('answers armed after the original\'s instant %d' % g['late']) in txt and 'v5 counter' not in txt, why or '')


def whole_run(rg):
    """W: at the end of section M, before the quit: settled, the counts over every ARM of the run"""
    b = rg.b
    per = rg.settle()
    g = rg.glue()
    o = analyse(b)
    count_checks(rg, 'W', g, o)
    rg.stats = dict(arms=len(o['arms']), late=len(o['late']), over_late=len(o['over_late']), stale=o['stale'],
                    stale_arms=o['stale_arms'], late_max=g['late_max'], true_max=o['true_max'], settle=per,
                    disc=len(o['disc']), fw_late=g['late'], stub=b.late_count, readable=o['true_readable'],
                    j_true=rg.stats.get('j_true'))
    if per is None:
        rg.chk('W0 settled before the quit', False, 'a call still in flight after 40 TIM7 periods')
    ft = rg.f.fatal_t
    rg.chk('W0 no fatal halt in the whole run (the watchdog fed by the frame ticks of section M): %s' % (
        'none' if ft is None else 'a halt at %d (fatal_rec %#010x)' % (ft, rg.b.rd32('fatal_rec', 0))), ft is None)


def section_f(rg, n):
    """F (since the fix of 2026-10-19): the two races placed on purpose, on late ARMs past D_BUSY (released at once, so
    the sub may post at once): n posts just before the firmware's first LSTAT read after the ARM (overtaken: publish
    takes the discard path) and n just before its TICK read (stale: TICK is the newer post's). In the hardware the
    game's next post comes a pass later and such a post would need the thread preempted that long (estimated); here they
    are the fuzz rig's stress, placed so that each net is exercised on every run whatever the seed. After the replay
    (section J's checks hold with them), settled:"""
    b = rg.b
    arms = [a for a in b.lk_arms if not a.get('ignored')]
    over = [a for a in arms if a['forced'] == 'over']
    stale = [a for a in arms if a['forced'] == 'stale']
    o_ok = [a for a in over if a['fate'] == 'discarded' and a['counted'] == 1]
    rg.chk('F1 %d of %d late ARMs overtaken by a post placed before the firmware\'s publish read: each discarded and '
           'counted once (fates %s, counted %s)' % (len(o_ok), n, [a['fate'] for a in over], [a['counted'] for a in over]),
           len(over) == n and len(o_ok) == n)
    s_hit = [a for a in stale if any(p != a['posts'] for v, p in a['reads'])]
    s_vals = [[(v - a['dw']) & 0xFFFFFF for v, p in a['reads'] if p != a['posts']] for a in stale]
    s_cnt = [a for a in stale if a['counted'] == 1 and a['fate'] == 'published']
    g = rg.glue()
    rg.chk('F2 %d of %d late ARMs whose TICK read a post placed before it reached (the newer post\'s tick: as a lateness '
           '%s): each counted once and published, none in late_max (%d; its stores on them %s; the largest readable %d)'
           % (len(s_hit), n, s_vals, g['late_max'], [a['max_w'] for a in stale], analyse(b)['want_fw']),
           len(stale) == n and len(s_hit) == n and len(s_cnt) == n and not any(a['max_w'] for a in stale) and
           g['late_max'] == analyse(b)['want_fw'] and g['late_max'] < 0x800000)


def section_m(rg):
    f, b = rg.f, rg.b
    clk = b.sysinfo_clk
    rec, why = rg.record()
    a = rec and rec['audio']
    on = b.uc.mem_read(b.sym['mdp_on'][0], 1)[0]
    rg.chk('M0 the rig\'s album init failed (no MD+ ids): mdp_on %d; the record\'s last album call %s' % (
        on, a and '%#06x' % (a['alb_calls'] >> 16)),
        on == 0 and a and (a['alb_calls'] >> 16) & dbgsave.ALB_OFF and not (a['alb_res'] & 1), why or '')
    b.uc.mem_write(b.sym['mdp_on'][0], b'\x01')             # the album on (the model's MD+ answers)
    b.alb['snoop'] = 3
    # M1: play 11 (loop), playing stays 0 (each step: the game's frame tick first, the watchdog fed)
    n0 = len(b.alb['writes'])
    ok = rg.frame_tick() and rg.post(0x8C8B)
    rg.run_for(int(1.0 * clk))
    w = [x for x in b.alb['writes'][n0:] if x[2] == 0x120B]
    f_req = w[-1][1] if w else None
    rec, why = rg.record()
    a = rec and rec['audio']
    fr = rec and rec['vs']['count']
    txt = dbgsave.report(rec, False) if rec else ''
    wt = a and a['alb_wait'] & 0x3FFFFFFF
    rg.chk('M1 8C8B -> 0x120B written at frame %s; a second later the record: result %s, calls %s, play frame %s, wait %s '
           '(waiting %s) for %s frames since the request at its write (frame %s), underruns %s / at the request %s' % (
               f_req, a and '%#010x' % a['alb_res'], a and '%#010x' % a['alb_calls'], a and a['alb_play_f'], wt,
               a and bool(a['alb_wait'] & dbgsave.ALB_WAITING), fr is not None and f_req is not None and fr - f_req, fr,
               a and a['alb_xl14'] & 0xFFFF, a and a['alb_play_und']),
           ok and w and a and a['alb_res'] == (0x120B << 16) | 0x0B00 and a['alb_calls'] == 0x120B120B and
           abs(a['alb_play_f'] - f_req) <= 1 and a['alb_wait'] & dbgsave.ALB_WAITING and abs(wt - (fr - f_req)) <= 1 and
           a['alb_wait_max'] == wt and wt >= 50 and a['alb_xl14'] >> 16 == 3 and
           a['alb_xl14'] & 0xFFFF > a['alb_play_und'] > 0 and a['alb_xl18'] == b.alb['xl18'], why or '')
    rg.chk('M1 reader: "music: track 11 requested %.2f s before this write, playing = no" and the request\'s line' % (
        wt / dbgsave.FRAME_HZ[53693175] if wt else 0),
        ('music: track 11 requested %s before this write, playing = no' % dbgsave.secs(wt, rec)) in txt and
        'the last play request: play track 11, looped (0x120b)' in txt and 'playing still 0' in txt)
    w1 = wt
    # M2: the track plays
    b.set_playing(True)
    t_on = b.vs_count()
    rg.run_for(3 * fuzz_s1.TIM7)
    rec, why = rg.record()
    a = rec and rec['audio']
    wt = a and a['alb_wait']
    rg.chk('M2 playing 1 from frame %d: the wait frozen at %s frames (no waiting bit), within a write period after it '
           '(%d frames from the request), the result %s' % (t_on, wt, t_on - f_req, a and '%#06x' % (a['alb_res'] & 0xFFFF)),
           a and not (wt & 0xC0000000) and t_on - f_req <= wt <= t_on - f_req + 8 and a['alb_res'] & 0xFFFF == 0x0B01 and
           a['alb_wait_max'] == wt and 'it played within' in dbgsave.report(rec, False), why or '')
    # M3: a stop
    ok = rg.frame_tick() and rg.post(0x8D08)
    rg.run_for(2 * fuzz_s1.TIM7)
    rec, why = rg.record()
    a = rec and rec['audio']
    rg.chk('M3 8D08: the last call %s (stop), the play request kept %s, the result %s' % (
        a and '%#06x' % (a['alb_calls'] >> 16), a and '%#06x' % (a['alb_calls'] & 0xFFFF),
        a and '%#06x' % (a['alb_res'] & 0xFFFF)),
        ok and a and a['alb_calls'] == 0x1300120B and a['alb_res'] == (0x1300 << 16) | 0x0B00 and
        not (a['alb_wait'] & 0xC0000000), why or '')
    # M4: play once, silent for 1.5 s: the session's longest wait
    n0 = len(b.alb['writes'])
    ok = rg.frame_tick() and rg.post(0x8C0B)
    rg.run_for(int(1.5 * clk))
    w = [x for x in b.alb['writes'][n0:] if x[2] == 0x110B]
    f_req2 = w[-1][1] if w else None
    rec, why = rg.record()
    a = rec and rec['audio']
    wt = a and a['alb_wait'] & 0x3FFFFFFF
    rg.chk('M4 8C0B (play once) silent 1.5 s: calls %s, wait %s frames (waiting), the session\'s longest %s (> M1\'s %s)' % (
        a and '%#010x' % a['alb_calls'], wt, a and a['alb_wait_max'], w1),
        ok and w and a and a['alb_calls'] == 0x110B110B and a['alb_wait'] & dbgsave.ALB_WAITING and
        a['alb_wait_max'] == wt > w1 and abs(a['alb_play_f'] - f_req2) <= 1, why or '')
    # M5: a stop before it played
    ok = rg.frame_tick() and rg.post(0x8D08)
    rg.run_for(2 * fuzz_s1.TIM7)
    rec, why = rg.record()
    a = rec and rec['audio']
    rg.chk('M5 8D08 while waiting: the wait %#010x marked "stopped without playing", the longest kept %s' % (
        a and a['alb_wait'], a and a['alb_wait_max']),
        ok and a and a['alb_wait'] & 0xC0000000 == 0x40000000 and 'stopped after' in dbgsave.report(rec, False) and
        a['alb_wait_max'] >= a['alb_wait'] & 0x3FFFFFFF, why or '')
    # M6: requested again, silent; W: the whole run's CPU MATE counts, settled; then the Pocket's quit
    ok = rg.frame_tick() and rg.post(0x8C8B)
    rg.run_for(int(0.6 * clk))
    whole_run(rg)
    last, why = rg.record()
    b.soft_reset()
    f.fatal_t = None
    f.released_t = None
    f.boot()
    rec, why2 = rg.record()
    q = rec and rec.get('prev2')
    la, lg = last['audio'], last['glue']
    want = dict(alb_res=la['alb_res'], alb_under=la['alb_xl14'], alb_lost=la['alb_xl18'], alb_calls=la['alb_calls'],
                alb_wait=la['alb_wait'], alb_wait_max=la['alb_wait_max'], late=lg['late'], late_max=lg['late_max'],
                short_calls=lg['short_calls'], calls=lg['calls'])
    bad = [k for k in want if not q or q.get(k) != want[k]]
    rg.chk('M6 quit after 8C8B silent 0.6 s and the settling: prev2 (state %s) = the last write\'s album and CPU MATE '
           'words%s (wait %s frames, waiting %s, late %s, late_max %s, short %s)' % (
               q and q['state'], (' (differ: %s)' % bad) if bad else '', q and q['alb_wait'] & 0x3FFFFFFF,
               q and bool(q['alb_wait'] & dbgsave.ALB_WAITING), q and q['late'], q and q['late_max'],
               q and q['short_calls']),
           ok and q and q['state'] == last['head']['version'] and q['state'] in (6, 7, 8) and not bad and   # 7: build 4a, 8: 4b
           q['alb_wait'] & dbgsave.ALB_WAITING,
           why or why2 or '')
    rg.chk('M6 the chain: 1 session, its longest wait %s == the session\'s %s, its largest lateness %s == %s, CPU MATE late '
           '%s; no lateness sign (dirty age %s): a late answer is none' % (
               q and q['w_alb_wait_max'], la['alb_wait_max'], q and q['w_late_max'], lg['late_max'], q and q['w_late'],
               q and q['dirty_age']),
           q and q['boots'] == 1 and q['w_alb_wait_max'] == la['alb_wait_max'] and q['w_late_max'] == lg['late_max'] and
           q['w_late'] == lg['late'] and lg['late'] > 0 and q['dirty_age'] == 0)
    txt = dbgsave.report(rec, False) if rec else ''
    rg.chk('M6 reader: "music (previous session): track 11 requested ... before its last write, playing = no", its CPU MATE '
           'as late answers, the chain\'s longest wait',
           'music (previous session): track 11 requested %s before its last write, playing = no' % dbgsave.secs(
               q['alb_wait'] & 0x3FFFFFFF, rec) in txt and
           'its CPU MATE: calls %d, answers armed after the original\'s instant %d' % (lg['calls'], lg['late']) in txt and
           'the longest wait for a requested track to play' in txt and 'v5 counter' not in txt)


def run_seed(build, rom, recs, seed, sections):
    """one board: section J, then (M) the album scenario with W and the quit, or (F) the forced races"""
    LinkBoard.force = (F_N, F_N) if 'F' in sections else (0, 0)
    rg = Rig(build, rom, recs, seed)
    try:
        section_j(rg)
        if 'F' in sections:
            section_f(rg, F_N)
        if 'M' in sections:
            section_m(rg)
    except Stop:
        rg.chk('X0 no model violation', False, '; '.join((rg.b.violations + rg.f.bad)[:3]))
    return rg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--build', default=os.path.join(ROOT, 'build', 's1', 'pocket72k', 'test'))
    ap.add_argument('--frames', type=int, default=600)
    ap.add_argument('--seeds', default=','.join(str(s) for s in SEEDS), help='comma-separated: the sweep')
    ap.add_argument('--seed', type=int, help='one seed (instead of --seeds)')
    ap.add_argument('--no-forced', action='store_true', help='leave out the forced-race run (section F)')
    ap.add_argument('--jitter', type=int, default=4000, help='sub cycles: the spread of the stub timer\'s origin a post')
    ap.add_argument('--negative', nargs='?', const='late', choices=sorted(NEG),
                    help='a planted image (late: test_bug_late, the default; disc: test_bug_disc; tick: test_bug_tick)')
    a = ap.parse_args()
    seeds = [a.seed] if a.seed is not None else [int(x) for x in a.seeds.split(',') if x.strip()]
    build = a.build
    neg = NEG[a.negative] if a.negative else None
    if neg:
        base = os.path.dirname(build)
        build = os.path.join(base, neg['image'])
        cmd = [sys.executable, '-I', '-B', os.path.join(ROOT, 'tools', 'fwbuild.py'), 's1', '--images-only',
               '--out', os.path.dirname(os.path.dirname(base)), '--variant', neg['image']]
        rr = subprocess.run(cmd, capture_output=True, text=True)
        if rr.returncode:
            print('SETUP ERROR: building %s failed:\n%s' % (neg['image'], rr.stdout[-2000:] + rr.stderr[-2000:]))
            sys.exit(2)
        print('planted: %s, %s; caught by %s' % (neg['image'], neg['what'], ' or '.join(neg['target'])), flush=True)
    if not os.path.exists(os.path.join(build, 'main.nm')):
        print('SETUP ERROR: no image at %s (tools/fwbuild.py s1)' % build)
        sys.exit(2)
    cap, rom = fuzz_s1.inputs()
    recs = fuzz_s1.load_capture(cap, a.frames)
    LinkBoard.jitter = a.jitter
    if neg and neg['sections'] == 'J':
        runs = [(s, 'J') for s in seeds]
    elif neg:                               # the forced races first: they catch a missing net on any seed
        runs = [(F_SEED, 'JF')] + [(s, 'JM') for s in seeds]
    else:
        runs = [(s, 'JM') for s in seeds] + ([] if a.no_forced else [(F_SEED, 'JF')])
    results = []
    for s, sec in runs:
        rg = run_seed(build, rom, recs, s, sec)
        fails = [n for n, ok in rg.res if not ok]
        results.append((s, sec, fails, rg.stats))
        st = rg.stats
        jt = st.get('j_true')
        print('seed %d (%s): %s%s%s' % (
            s, '+'.join(sec), 'every check passes' if not fails else 'FAIL %s' % ', '.join(fails),
            ('; after the replay late_max %d, the true largest %d (%s)' % (
                jt[0], jt[1], 'readable' if jt[2] else 'NOT readable: its TICK read came after the game\'s next post')
             if jt else ''),
            ('; the whole run to the quit: %d ARMs, %d late (firmware %d, stub %d), %d of them overtaken before their '
             'publish read, %d TICK reads after a newer post (on %d late ARMs), late_max %d, the true largest %d (%s)' % (
                 st['arms'], st['late'], st['fw_late'], st['stub'], st['over_late'], st['stale'], st['stale_arms'],
                 st['late_max'], st['true_max'], 'readable' if st['readable'] else 'NOT readable'))
            if 'arms' in st else ''), flush=True)
        del rg
        gc.collect()
        if neg and any(n in neg['target'] for n in fails):
            break
    if neg:
        caught = [(s, sec) for s, sec, f, _ in results if any(n in neg['target'] for n in f)]
        other = [(s, sec, [n for n in f if n not in neg['target'] + neg['allowed']]) for s, sec, f, _ in results]
        other = [x for x in other if x[2]]
        ok = bool(caught) and not other
        print('NEGATIVE %s: %s by %s%s; other checks failing: %s' % (
            neg['image'], 'caught' if caught else 'NOT caught', '/'.join(neg['target']),
            (' on seed %d (%s)' % (caught[0][0], '+'.join(caught[0][1]))) if caught else '', other or 'none'))
    else:
        over = [(s, st.get('over_late', 0)) for s, sec, _, st in results if 'M' in sec]
        stale = [(s, st.get('stale', 0)) for s, sec, _, st in results if 'M' in sec]
        print('INFO the sweep\'s own races (not forced): late ARMs overtaken by the game\'s next post before their publish '
              'read %d (by seed %s), TICK reads after a newer post %d (by seed %s)' % (
                  sum(n for _, n in over), over, sum(n for _, n in stale), stale), flush=True)
        ok = all(not f for _, _, f, _ in results)
    print('RESULT: %s' % ('PASS' if ok else 'FAIL'))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
