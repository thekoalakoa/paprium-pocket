# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""hostside.py - one host-built cart firmware as a replay side (stage 0, the tree's first step), over the pipe protocol
of the audit harness (our test harness outside this tree that runs a firmware build against the cart chip's program).

Protocol (the harness's ours_host.c, + 'O' from paprium-fw): L R W w P M D S A G B O Q. Requests are buffered and sent
together with the next request that wants a reply, so several sides run concurrently (send to all, then read all).
"""
import struct
import subprocess

SDR_SPAN = 0x800000
OFF_FLASH = 0x1000000          # 'M' offsets are relative to ADDR_SDR (0x3000000): ADDR_FLA = +0x1000000
BRAM_N = 0x1000                # saves 0x000-0x8FF + the TEST snapshot window 0x900-0xFFF (mame.c SNAP_BOOT/SNAP_BASE)


class HostSide:
    def __init__(self, name, exe):
        self.name, self.exe = name, exe
        self.p = subprocess.Popen([exe], stdin=subprocess.PIPE, stdout=subprocess.PIPE, bufsize=1 << 20)
        self.out = bytearray()
        self.rd = self.p.stdout.read

    # ---- raw
    def q(self, b):
        self.out += b

    def flush(self):
        if self.out:
            self.p.stdin.write(self.out)
            self.p.stdin.flush()
            self.out = bytearray()

    def read(self, n):
        b = self.rd(n)
        if len(b) != n:
            raise RuntimeError('%s died (wanted %d, got %d)' % (self.name, n, len(b)))
        return b

    def k(self):
        assert self.read(1) == b'k'

    # ---- requests (q_* queue only; the caller flushes and reads)
    def q_load(self, rom):
        self.q(b'L' + struct.pack('<I', len(rom)) + rom)

    def q_opt(self, w):
        self.q(b'O' + struct.pack('<I', w))

    def q_reset(self):
        self.q(b'R')

    def q_shadow(self):
        self.q(b'S')

    def q_w(self, off, data):          # raw RAMDP write at MCU byte offset, no reply
        self.q(b'w' + struct.pack('<HH', off, len(data)) + data)

    def q_post(self, word):
        self.q(b'P' + struct.pack('<H', word))

    def r_post(self):
        head = self.read(0x2000 + 24 + 4)
        n = struct.unpack_from('<I', head, 0x2018)[0]
        tail = self.read(n + 4)
        txt = tail[:n]
        na = struct.unpack_from('<I', tail, n)[0]
        au = self.read(8 * na) if na else b''
        return head[:0x2000], head[0x2000:0x2018], txt, au

    def q_diff(self):
        self.q(b'D')

    def r_diff(self):
        c = struct.unpack('<I', self.read(4))[0]
        return struct.unpack('<%dI' % c, self.read(4 * c)) if c else ()

    def q_mem(self, off, n):
        self.q(b'M' + struct.pack('<II', off, n))

    def q_bram(self, off, n):
        self.q(b'B' + struct.pack('<II', off, n))

    def q_all(self):
        self.q(b'A')

    def r_all(self):
        b = self.read(0x2000 + 24)
        return b[:0x2000], b[0x2000:]

    def q_globals(self):
        self.q(b'G')

    def r_globals(self):
        n = struct.unpack('<I', self.read(4))[0]
        return self.read(n)

    def close(self):
        try:
            self.q(b'Q')
            self.flush()
            self.p.wait(10)
        except Exception:
            self.p.kill()


def runs(gran):
    """merge 256-byte granule offsets into (start, length) runs"""
    out = []
    for g in gran:
        if out and out[-1][0] + out[-1][1] == g:
            out[-1][1] += 256
        else:
            out.append([g, 256])
    return out
