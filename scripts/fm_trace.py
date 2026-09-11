"""Read paprium_fmlog.bin - what Paprium's uploaded Z80 sound driver actually did.

    python scripts/fm_trace.py ../vdp-capture/paprium_fmlog.bin

Produced by scripts/apply_gpgx_fmlog.py. Three questions, in order of what they
settle:

  1. Does the Z80 driver run at all? No records of kind 40 means the YM2612 is
     never touched from the Z80 side, and Paprium's FM path is not running in
     the emulator - which would explain why nobody has heard it outside real
     hardware.
  2. If it runs, are PATCHES being written? Registers 0x30-0x8F are the four
     operators' DT/MUL, TL, RS/AR, AM/D1R, D2R and SL/RR - 24 registers per
     channel. A burst of those is an instrument being loaded, and the bytes ARE
     the patch. That matters because no static FM patch table exists anywhere in
     the cartridge (see the FM localisation note in docs/PORT_PLAN.md), so
     patches arriving here means they are reachable from data we already have.
  3. Where did the bytes come from? Kind 41 logs every Z80 read of the 68000
     bank window in the patch region (Z80 $C000-$DFFF = bank offset
     0x4000-0x5FFF), resolved to the 68000 address it landed on.

The YM2612 has two register parts of 3 channels each; ports 0/1 address and
write part 1, ports 2/3 part 2. A register write is an address byte followed by
a data byte on the matching port pair, which is what gets reassembled here.
"""
import os
import struct
import sys
from collections import Counter, defaultdict

REC = struct.Struct('<BBHI')

OPREGS = range(0x30, 0x90)          # 4 operators x 6 register banks


def name(reg):
    if reg == 0x22: return 'LFO'
    if reg in (0x24, 0x25, 0x26, 0x27): return 'timer/ch3'
    if reg == 0x28: return 'KEY ON/OFF'
    if reg == 0x2A: return 'DAC data'
    if reg == 0x2B: return 'DAC enable'
    if 0x30 <= reg < 0x40: return 'DT/MUL   (patch)'
    if 0x40 <= reg < 0x50: return 'TL       (patch)'
    if 0x50 <= reg < 0x60: return 'RS/AR    (patch)'
    if 0x60 <= reg < 0x70: return 'AM/D1R   (patch)'
    if 0x70 <= reg < 0x80: return 'D2R      (patch)'
    if 0x80 <= reg < 0x90: return 'SL/RR    (patch)'
    if 0x90 <= reg < 0xA0: return 'SSG-EG'
    if 0xA0 <= reg < 0xA8: return 'frequency'
    if 0xA8 <= reg < 0xB0: return 'ch3 frequency'
    if 0xB0 <= reg < 0xB4: return 'algorithm/feedback'
    if 0xB4 <= reg < 0xB8: return 'pan/AMS/FMS'
    return 'other'


def read(path):
    b = open(path, 'rb').read()
    n = len(b) // 8
    return [REC.unpack_from(b, i * 8) for i in range(n)]


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '../vdp-capture/paprium_fmlog.bin'
    if not os.path.exists(path):
        raise SystemExit('no such log: ' + path)
    recs = read(path)
    kinds = Counter(r[0] for r in recs)
    print('%s: %d records  (%s)' % (
        os.path.basename(path), len(recs),
        ', '.join('kind %d x %d' % (k, v) for k, v in sorted(kinds.items()))))

    if not kinds.get(40):
        print('')
        print('NO YM2612 WRITES FROM THE Z80.')
        print('The sound driver is not driving the FM chip in this run.')
    else:
        # reassemble register writes from the address/data port pairs
        pend = {0: None, 1: None}
        writes = []
        for kind, port, val, stamp in recs:
            if kind != 40:
                continue
            part = 0 if port < 2 else 1
            if port in (0, 2):
                pend[part] = val & 0xFF
            elif pend[part] is not None:
                writes.append((part, pend[part], val & 0xFF, stamp))

        ports = Counter(r[1] for r in recs if r[0] == 40)
        print('')
        print('YM2612: %d raw port writes  (%s)' % (
            kinds[40], ', '.join('port %d x %d' % (k, v) for k, v in sorted(ports.items()))))
        print('        %d reconstructed register writes' % len(writes))
        if kinds[40] and len(writes) * 4 < kinds[40]:
            print('        NOTE: far fewer pairs than raw writes - the log is mostly')
            print('        address selects whose data bytes were filtered at the source.')
        byname = Counter(name(r) for _p, r, _v, _s in writes)
        for k, v in sorted(byname.items(), key=lambda x: -x[1]):
            print('   %-20s %7d' % (k, v))

        patch = [w for w in writes if w[1] in OPREGS]
        print('')
        if not patch:
            print('NO PATCH REGISTERS WRITTEN (0x30-0x8F).')
            print('The driver plays notes but never loads an instrument here.')
        else:
            # a patch upload is a burst of operator writes close together in time
            bursts = []
            cur = [patch[0]]
            for w in patch[1:]:
                if w[3] - cur[-1][3] > 20000:      # Z80 cycles
                    bursts.append(cur)
                    cur = []
                cur.append(w)
            bursts.append(cur)
            full = [b for b in bursts if len(b) >= 20]
            print('%d operator-register writes in %d bursts, %d of them >= 20 writes'
                  % (len(patch), len(bursts), len(full)))
            for b in full[:3]:
                chans = sorted(set((p * 3) + (r & 3) for p, r, _v, _s in b if (r & 3) != 3))
                print('   burst at cycle %d: %d writes, channels %s'
                      % (b[0][3], len(b), chans))
                print('      ' + ' '.join('%02X=%02X' % (r, v) for _p, r, v, _s in b[:24]))

    reads = [r for r in recs if r[0] == 41]
    print('')
    if not reads:
        print('No bank-window reads in the patch region (offset 0x4000-0x5FFF).')
    else:
        addrs = Counter(((p << 16) | a) for _k, p, a, _s in reads)
        print('%d bank reads in the patch region, %d distinct addresses'
              % (len(reads), len(addrs)))
        lo = min(addrs), max(addrs)
        print('   68000 address range 0x%06X .. 0x%06X' % (min(addrs), max(addrs)))
        for a, c in addrs.most_common(6):
            print('   0x%06X  x%d' % (a, c))

    banks = [r for r in recs if r[0] == 42]
    if banks:
        w = Counter(r[2] for r in banks)
        print('')
        print('%d bank-register writes, windows: %s' % (
            len(banks), ', '.join('0x%06X' % (k << 15) for k, _ in w.most_common(6))))


if __name__ == '__main__':
    main()
