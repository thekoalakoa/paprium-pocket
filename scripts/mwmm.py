#!/usr/bin/env python3
"""Structural decoder for Paprium's MWMM music modules.

    python scripts/mwmm.py <moduledir>     # parse every trackNN.mwmm and self-check

Modules come out of scripts/dump_music.py. This reads the layer ABOVE the header
that dump_music already decoded: the pattern/order machinery that actually holds
the music. It does NOT claim to decode event semantics - what an 8-byte event
record means is still open, and that is the project's outstanding synth problem.

    0x00  "WMMM"
    0x04  00 01              version, constant across all 52
    0x06  BE xx              xx varies (03/04/05)
    0x08  npos               order-list positions per voice
    0x0A  xx
    0x0B  rows per bar
    0x0C  04 00 00 00
    0x10  26 bytes  array A - volume, 0x10 in every module
    0x2A  26 bytes  array B - per-voice program; all zero in 38 of the 52
    0x44  26 bytes  array C - zero in every module
    0x5E  26 bytes  array D - pan, 0x80 in every module
    0x78  32 bytes  TITLE,     XOR 0xA5
    0x98  32 bytes  COMPOSER,  XOR 0xA5
    0xB8  32 bytes  COMMENT,   XOR 0xA5   <-- previously mis-read as sequence data
    0xD8  order list: u16 big-endian ABSOLUTE file offsets, VOICE-MAJOR,
          26 voices x npos positions
    then  the patterns themselves, each starting at an offset named by the order
          list. A pattern is G one-byte rows, each an INDEX into that pattern's
          own event table, followed by the table: 8 bytes per record, with index
          0 reserved as the null event (so a zero row means "nothing here").

G is constant within a module and is one of 48, 64, 96, 128 or 256. It is solved
per module as the value that makes max(grid index) == nevents-1 for the most
patterns, then checked exhaustively: NO pattern anywhere may carry an index past
the end of its own event table.

That check is the reason to trust this. Across all 52 modules it parses 2,525
patterns with ZERO out-of-range indices - a wrong G, a wrong stride or a wrong
base would break that immediately, and does when any of them is perturbed.

The comment field is worth reading. It holds the composers' own notes, rotating
over about fifteen jokes, and one of them names the tracker: "Pushing Wavemelon
To The Limit". Which is presumably what the four M's in WMMM are doing.

Derived from a commercial ROM. The modules stay local and gitignored; this
script does not.
"""
import glob, os, struct

import sys
MODDIR = None                       # set by load_all() or the CLI
HDR   = 0xD8
EVSZ  = 8

def txt(b):
    return ''.join(chr(x ^ 0xA5) for x in b).split('\x00')[0].rstrip()

class Mod:
    def __init__(self, n, path):
        self.n, self.path = n, path
        d = self.d = open(path, 'rb').read()
        assert d[:4] == b'WMMM'
        self.title    = txt(d[0x78:0x98])
        self.composer = txt(d[0x98:0xB8])
        self.comment  = txt(d[0xB8:0xD8])
        self.vol  = list(d[0x10:0x2A]);  self.prog = list(d[0x2A:0x44])
        self.unk  = list(d[0x44:0x5E]);  self.pan  = list(d[0x5E:0x78])
        self.hdr  = list(d[0x06:0x10])
        for k in range(1, (len(d) - HDR) // 2):
            w = struct.unpack('>%dH' % k, d[HDR:HDR + 2 * k])
            if HDR + 2 * k == min(w) and max(w) <= len(d):
                self.order = list(w); break
        else:
            raise ValueError('no order list')
        self.npos = len(self.order) // 26
        assert len(self.order) % 26 == 0
        self.pts  = sorted(set(self.order))
        self.ends = self.pts[1:] + [len(d)]
        self.G    = self._solve_G()
        self.rowsperbar = d[0x0B]
        self.pat = {}                              # offset -> (grid, [events])
        for a, b in zip(self.pts, self.ends):
            G  = self.G
            g  = d[a:a + G]
            ev = [d[a + G + i * EVSZ: a + G + (i + 1) * EVSZ]
                  for i in range((b - a - G) // EVSZ)]
            self.pat[a] = (g, ev)

    def _solve_G(self):
        from collections import Counter
        c = Counter()
        for a, b in zip(self.pts, self.ends):
            size = b - a
            for G in range(0, size + 1, 8):
                ne = (size - G) // EVSZ
                if ne >= 1 and (max(self.d[a:a + G]) if G else 0) == ne - 1:
                    c[G] += 1
        return c.most_common(1)[0][0]

    def voice_order(self, v):
        return self.order[v * self.npos:(v + 1) * self.npos]

    def rows(self, off):
        """G one-byte event indices for one pattern."""
        return list(self.pat[off][0])

    def event(self, off, idx):
        ev = self.pat[off][1]
        return ev[idx] if 0 <= idx < len(ev) else None

    def timeline(self, v):
        """[(absolute_row, event_bytes)] for voice v over the whole song."""
        out = []
        for p, off in enumerate(self.voice_order(v)):
            for r, i in enumerate(self.rows(off)):
                if i:
                    e = self.event(off, i)
                    if e: out.append((p * self.G + r, bytes(e)))
        return out

def load_all(moddir=None):
    out = []
    for f in sorted(glob.glob(os.path.join(moddir or MODDIR, 'track*.mwmm'))):
        out.append(Mod(int(os.path.basename(f)[5:7]), f))
    return out

def verify(moddir=None):
    bad = ok = exact = 0; slack = {}
    for m in load_all(moddir):
        for off in m.pts:
            g, ev = m.pat[off]
            hi = max(g) if g else 0
            if hi >= len(ev): bad += 1; slack.setdefault(m.n, []).append((off, hi, len(ev)))
            else: ok += 1
            if hi == len(ev) - 1: exact += 1
    print("patterns whose every grid index is a valid event slot : %d" % ok)
    print("patterns with an OUT-OF-RANGE grid index (model fails): %d" % bad)
    print("patterns where max(index) == nevents-1 exactly        : %d" % exact)
    for k, v in list(slack.items())[:10]: print("   trk %d %s" % (k, v[:4]))

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    verify(sys.argv[1])
