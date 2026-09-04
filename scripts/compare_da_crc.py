"""Compare the 0xDA payload CRCs the hardware recorded against the GPGX twin.

    python scripts/compare_da_crc.py <Paprium.sav> <rom.bin>

Reads the CRC record array out of the on-hardware snapshot (the same 16-byte
records decode_sat_snapshot.py prints), runs tools/da-twin/da_twin over the
same source addresses, and diffs length and CRC per record.

The twin decompresses straight out of the ROM using the decoders lifted from
Genesis Plus GX. Because the unpack is a pure function of the compressed bytes
at src, this needs no gameplay reproduction - any capture from any scene can be
checked against it.

ROM byte order is not assumed. The twin is run both ways and whichever
convention actually decodes is reported; if neither does, that is said plainly
rather than picking the less-bad one.
"""
import struct
import subprocess
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
TWIN = os.path.join(HERE, '..', 'tools', 'da-twin', 'da_twin.exe')

# The save carries a 16-byte boot header at 0x900; the snapshot proper starts
# at 0x910, and the CRC record array sits 8 + 640 into that. The tag check
# below is what actually validates this - do not adjust the constant to make
# the tag pass, find out why it moved.
SNAP_BASE = 0x910
ARENA = SNAP_BASE + 8 + 640


def swapped(b):
    out = bytearray(b)
    out[0::2], out[1::2] = b[1::2], b[0::2]
    return bytes(out)


def records(save_path):
    d = open(save_path, 'rb').read()
    if len(d) != 4096:
        raise SystemExit("%s is %d bytes; expected a 4096-byte save" % (save_path, len(d)))
    o = swapped(d[ARENA:])
    n, cap = struct.unpack('>HH', o[768:772])
    fence_crc, fence_len, tag, fence_age = struct.unpack('>4I', o[772:788])
    if tag != 0xC2C1C2C1:
        raise SystemExit("tag is 0x%08X, not 0xC2C1C2C1 - this save was not written "
                         "by a CRC-card build, or the arena moved" % tag)
    rows = []
    for i in range(min(n, cap)):
        src, ln, crc, dst = struct.unpack('>4I', o[i * 16:(i + 1) * 16])
        rows.append((src, ln, crc, dst))
    return rows, n, cap, fence_crc, fence_len, fence_age


def run_twin(rom, srcs, swap):
    args = [TWIN, rom] + (['--swap'] if swap else [])
    inp = ''.join('%X\n' % s for s in srcs)
    p = subprocess.run(args, input=inp, capture_output=True, text=True)
    out = {}
    for line in p.stdout.splitlines():
        f = line.split()
        if len(f) == 3 and f[1] != 'FAIL':
            out[int(f[0], 16)] = (int(f[1]), int(f[2], 16))
        elif len(f) >= 2:
            out[int(f[0], 16)] = None
    return out


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    save, rom = sys.argv[1], sys.argv[2]
    if not os.path.exists(TWIN):
        raise SystemExit("%s is not built. Run:\n"
                         "  gcc -O2 -o tools/da-twin/da_twin.exe tools/da-twin/da_twin.c" % TWIN)

    rows, n, cap, fence_crc, fence_len, fence_age = records(save)
    srcs = sorted({r[0] for r in rows})
    print("hardware records : %d (array capacity %d)" % (n, cap))
    print("distinct sources : %d" % len(srcs))
    if n >= cap:
        print("  NOTE: the array is FULL, so 0xDA calls after the %dth were not" % cap)
        print("        recorded. Absence of a record below is not absence of a call.")

    # Decide the ROM byte order from which convention actually decodes, rather
    # than assuming. A wrong convention does not produce subtly wrong output -
    # it walks off the end of the image or hits an unknown type byte.
    best = None
    for swap in (False, True):
        got = run_twin(rom, srcs, swap)
        ok = sum(1 for s in srcs if got.get(s))
        print("twin, %-14s: %d of %d sources decoded" %
              ('byteswapped' if swap else 'as-is', ok, len(srcs)))
        if best is None or ok > best[1]:
            best = (got, ok, swap)
    got, ok, swap = best
    if ok == 0:
        raise SystemExit("\nNeither byte order decodes any source. Either the ROM is not the\n"
                         "image the cartridge runs, or the source addresses are not ROM\n"
                         "offsets. Nothing can be concluded about #8 from this run.")
    print()

    print("PER-RECORD COMPARISON")
    print("    #        src        dst       hw len   twin len      hw crc     twin crc  verdict")
    match = mismatch = missing = 0
    bad = []
    for i, (src, ln, crc, dst) in enumerate(rows):
        t = got.get(src)
        if not t:
            v = 'NO-DECODE'
            missing += 1
            tl, tc = 0, 0
        else:
            tl, tc = t
            if tl == ln and tc == crc:
                v = 'match'
                match += 1
            else:
                v = 'MISMATCH'
                mismatch += 1
                bad.append((i, src, dst, ln, tl, crc, tc))
        print("  %3d  0x%08X  0x%06X  %9d  %9d  0x%08X  0x%08X  %s"
              % (i, src, dst, ln, tl, crc, tc, v))

    print()
    print("  match %d   mismatch %d   no-decode %d   of %d" % (match, mismatch, missing, len(rows)))
    print()
    if mismatch == 0 and missing == 0:
        print("VERDICT  Every payload the hardware unpacked is byte-identical to the")
        print("         reference decoder over the same ROM bytes. The MCU unpack is")
        print("         correct, and #8 is NOT a decompression fault. It leaves the")
        print("         stream path for 68000->VDP DMA and the name table.")
    elif mismatch:
        print("VERDICT  %d payload(s) differ from the reference. The unpack is wrong" % mismatch)
        print("         and #8 is still firmware. Smallest failing record first:")
        for i, src, dst, ln, tl, c, tc in sorted(bad, key=lambda r: min(r[3], r[4]))[:3]:
            print("           #%d src 0x%08X dst 0x%06X  len %d vs %d" % (i, src, dst, ln, tl))
        print("         Reproduce one in isolation with tools/da-twin/da_twin and")
        print("         step the firmware decoder against it.")
    else:
        print("VERDICT  Inconclusive: %d source(s) would not decode at all." % missing)
        print("         Fix that before drawing any conclusion from the ones that did.")

    print()
    print("FENCE     0x%08X over [0, 0x%X), age %d frames" % (fence_crc, fence_len, fence_age))
    last0 = [i for i, r in enumerate(rows) if r[3] == 0]
    if last0:
        i = last0[-1]
        if rows[i][1] == fence_len and rows[i][2] == fence_crc:
            print("  The fence equals record #%d, the last payload that filled the whole" % i)
            print("  region. The fence refreshes immediately after such an unpack, so")
            print("  this is ONE measurement reported twice - it is not corroboration")
            print("  and it says nothing about whether the region drifted afterwards.")
        else:
            print("  The fence DIFFERS from record #%d (0x%08X), the last full-region"
                  % (i, rows[i][2]))
            print("  payload. Something wrote into [0, 0x%X) after the unpack." % fence_len)
            print("  That is a real finding: track down the writer.")


if __name__ == '__main__':
    main()
