# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""sprwords.py - the sprite-values update (B Jam's decision of 2026-10-15/16): the sprite words the game reads as data,
for the rigs that hold the stage-1 firmware (FW_S1, our new firmware) to final 0.2.6 (tests/equiv/chiplock_s1.py,
s1_equiv.py) and to the chip (chiplock_s1.py). D-numbers are the differences of our firmware audit (not in this tree);
B14 is a row of the allow-list (docs/ALLOWLIST.md); test build 4 is a firmware build B Jam tested on his hardware.

Since the update the stage-1 firmware does what the chip does for its clip rule D24 (ppm_obj_render), its whole AF frame
end (D10 and the rest of D42: modes 0-2, the second 14-entry DMA, the $1F20 stash, $1F1C), its open-frame gate D38 and
the multiplex parity H+$403, so the sprite words differ from
final 0.2.6 on purpose (allow-list B14, a change of reference):
  - the SAT ($0B00 + 8 x entry, 144 entries): pieces above or below the screen get entries, X and Y unmasked, 80+
    frames multiplexed;
  - the DMA list ($1400 + 16 x slot, 121 slots): the second 14-entry descriptor and the 80+ upload;
  - the stash $1F20-$1F8F (14 entries) and the words $1F10, $1F16, $1F18, $1F1C.
The groups and the rule are in tests/equiv/s1_scope.json "sprite_words": against final 0.2.6 a word of these groups
may START to differ only at a post of a command that writes it the chip's way (AD: the SAT and $1F18; AF: all of
them; C6: $1800 / $1802, B10, where the audio page overlaps the DMA list's far end); it is then counted, not compared,
until both sides hold the same value again. A word that starts to differ at any other post is a failure. Against the
chip (chiplock_s1.py) the words are compared after every accepted AD / AF (chip_check), with no allowance (since stage
2's repair, 2026-10-28: SAT entry 0 after an AF that leaves the table empty is held to the chip too). Every other cart-RAM word stays compared word by word
(ranges). Since test build 4 (D23 done the chip's way: the chip's attribute ADD and pose bit 29): the SAT and stash
entries are compared with the chip in all four words, the attribute word included ("chip_sat_words"; until test build
4 Y / link / X only, B14)."""
import json
import os
import struct

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))


def h16(s):
    return int(s, 16) if isinstance(s, str) else s


def u16(b, a):
    return struct.unpack_from('<H', b, a)[0]


class SpriteWords:
    def __init__(self, scope=None):
        sc = scope if isinstance(scope, dict) else json.load(open(scope or os.path.join(HERE, 's1_scope.json')))
        sw = sc['sprite_words']
        self.row = sw['row']
        self.sat = (h16(sw['sat'][0]), sw['sat'][1])
        self.stash = (h16(sw['stash'][0]), sw['stash'][1])
        self.dma = (h16(sw['dma'][0]), sw['dma'][1])
        self.words = [h16(w) for w in sw['words']]
        self.chip_sat = sw['chip_sat_entries']
        self.chip_cols = tuple(sw.get('chip_sat_words', (0, 1, 2, 3)))     # entry words compared with the chip (2 = attr)
        self.ad_words = [h16(w) for w in sw['ad_words']]
        self.af_words = [h16(w) for w in sw['af_words']]
        self.diverge_at = {k: set(h16(x) if x.startswith('0x') else x for x in v) for k, v in sw['diverge_at'].items()}
        cut = sorted([(self.sat[0], self.sat[0] + 8 * self.sat[1]), (self.dma[0], self.dma[0] + 16 * self.dma[1]),
                      (self.stash[0], self.stash[0] + 8 * self.stash[1])] + [(w, w + 2) for w in self.words])
        rng, a = [], 0
        for s, e in cut:
            if s > a:
                rng.append((a, s))
            a = max(a, e)
        rng.append((a, 0x1FE0))
        self.ranges = rng                       # cart RAM below the register page outside the sprite words
        self.reset()

    # ---- against final 0.2.6
    def reset(self):
        self.sd = {'sat': np.zeros(4 * self.sat[1], bool), 'dma': np.zeros(8 * self.dma[1], bool),
                   'stash': np.zeros(4 * self.stash[1], bool), 'words': np.zeros(len(self.words), bool)}

    def state(self):
        return {k: v.copy() for k, v in self.sd.items()}

    def restore(self, st):
        self.sd = {k: np.array(v, bool) for k, v in st.items()}

    def ref_step(self, idx, xr, yr):
        """after a post of table index idx: xr = final 0.2.6's cart RAM, yr = the stage-1 firmware's. Returns
        (started, bad, differ): where words started to differ at a post that writes them the chip's way, where they
        started at any other post (a failure), and whether any sprite word differs now"""
        may = self.diverge_at.get('%02X' % idx, ())
        started, bad, differ = [], [], False
        for name, base, nw, unit in (('sat', self.sat[0], 4 * self.sat[1], 8), ('dma', self.dma[0], 8 * self.dma[1], 16),
                                     ('stash', self.stash[0], 4 * self.stash[1], 8)):
            ne = np.frombuffer(xr, '<u2', nw, base) != np.frombuffer(yr, '<u2', nw, base)
            new = np.nonzero(ne & ~self.sd[name])[0]
            if len(new):
                if name in may:
                    started.append('%s %s' % (name, sorted({int(i) * 2 // unit for i in new})[:8]))
                else:
                    ok = [i for i in new if base + 2 * int(i) in may]
                    if ok:
                        started.append(', '.join('$%04X' % (base + 2 * int(i)) for i in ok[:8]))
                    no = [i for i in new if base + 2 * int(i) not in may]
                    if no:
                        bad.append('%s %s: %s' % (name, sorted({int(i) * 2 // unit for i in no})[:8], ', '.join(
                            '$%04X %04X/%04X' % (base + 2 * int(i), u16(xr, base + 2 * int(i)), u16(yr, base + 2 * int(i)))
                            for i in no[:4])))
            self.sd[name] = ne
            differ = differ or bool(ne.any())
        ne = np.array([xr[w:w + 2] != yr[w:w + 2] for w in self.words], bool)
        for i in np.nonzero(ne & ~self.sd['words'])[0]:
            w = self.words[i]
            (started if w in may else bad).append('$%04X %04X/%04X' % (w, u16(xr, w), u16(yr, w)))
        self.sd['words'] = ne
        return started, bad, differ or bool(ne.any())

    # ---- against the chip
    def chip_check(self, mode, pre, c, nram):
        """after an accepted AD (mode 'ad') or AF ('af'): c = the chip's cart RAM, nram = ours, pre = the chip's
        $1F10-$1F1F before the post. Returns the differences. No allowance: until stage 2 (the sprite engine) SAT
        entry 0 after an AF that left the table empty was forgiven (0.2.6's B1 clear of entry 0, D47, and the runner's power-on page); stage 2
        does D47 the chip's way, the allowance was used 0 times on every corpus, and it is retired (2026-10-28)"""
        bad = []
        for w in (self.ad_words if mode == 'ad' else self.af_words):
            if c[w:w + 2] != nram[w:w + 2]:
                bad.append('$%04X chip %04X new %04X' % (w, u16(c, w), u16(nram, w)))
        if mode != 'af':
            return bad
        d0, dn = self.dma
        for i in range(u16(pre, 6), min(max(u16(c, 0x1F16), u16(nram, 0x1F16)), dn)):   # from the pre-AF $1F16
            a = d0 + 16 * i
            if c[a:a + 16] != nram[a:a + 16]:
                bad.append('descriptor %d chip %s new %s' % (i, c[a:a + 16].hex(), nram[a:a + 16].hex()))
        for name, base, n in (('SAT', self.sat[0], self.chip_sat), ('stash', self.stash[0], self.stash[1])):
            ca = np.frombuffer(c, '<u2', 4 * n, base).reshape(n, 4)[:, self.chip_cols]  # Y, link, attr (test
                                                                                        # build 4: D23), X
            na = np.frombuffer(nram, '<u2', 4 * n, base).reshape(n, 4)[:, self.chip_cols]
            ents = [int(e) for e in np.nonzero((ca != na).any(axis=1))[0]]
            for e in ents[:6]:
                bad.append('%s %d chip %s new %s' % (name, e, ' '.join('%04X' % v for v in ca[e]),
                                                     ' '.join('%04X' % v for v in na[e])))
            if len(ents) > 6:
                bad.append('... %d %s entries' % (len(ents), name))
        return bad
