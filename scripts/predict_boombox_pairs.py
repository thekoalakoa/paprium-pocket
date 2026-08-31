"""Predict what each Boom Box N / N+0x80 pair should sound like on SHIPPING
firmware, so an identical-sounding pair can be told apart from a refutation.

SFX table: ROM 0x25ECA4, 8-byte rows, big-endian:
    u32 ptr, u8 type, u8 size_hi, u16 size_lo
    type >> 4  = rate index into DIV
    type & 3   = depth (1 = 8-bit, 2 = 4-bit)

sfx.c on shipping does:  sr = (type>>4)&7;  if (sr < 5) sr++;
so a row already at index 5 CANNOT step, and N+0x80 must sound identical to N.
"""
import struct, sys

rom = open(sys.argv[1], 'rb').read()
BASE = 0x25ECA4
DIV = [1, 2, 4, 5, 8, 9]
RATE = [48000 // d for d in DIV]

rows = []
for n in range(0x7F):
    off = BASE + n * 8
    ptr, typ, shi, slo = struct.unpack_from('>IBBH', rom, off)
    size = (shi << 16) | slo
    rows.append((n, ptr, typ, size))

print("rate index distribution across the 127 live rows:")
hist = {}
for n, ptr, typ, size in rows:
    if not size:
        continue
    hist[(typ >> 4) & 7] = hist.get((typ >> 4) & 7, 0) + 1
for k in sorted(hist):
    r = RATE[k] if k < len(RATE) else '?'
    tag = '  <- SATURATED, N+0x80 will sound IDENTICAL' if k >= 5 else ''
    print("  index %d = %-5s Hz : %3d rows%s" % (k, r, hist[k], tag))

print()
print("the four pairs PORT_PLAN suggests:")
for n in (0x1A, 0x7D, 0x00, 0x1C):
    _, ptr, typ, size = rows[n]
    ri = (typ >> 4) & 7
    if not size:
        print("  %02X / %02X   EMPTY ROW - silence, not a valid test" % (n, n | 0x80))
        continue
    nxt = ri + 1 if ri < 5 else ri
    verdict = ("IDENTICAL (already slowest)" if nxt == ri
               else "%d Hz -> %d Hz, audibly deeper" % (RATE[ri], RATE[nxt]))
    print("  %02X / %02X   rate idx %d  depth %d  %d bytes  -> %s"
          % (n, n | 0x80, ri, typ & 3, size, verdict))

print()
print("best pairs to actually use (largest rate drop, non-empty, longest sample):")
cand = []
for n, ptr, typ, size in rows:
    ri = (typ >> 4) & 7
    if size > 8000 and ri < 5:
        cand.append((RATE[ri] - RATE[ri + 1], n, ri, size))
cand.sort(reverse=True)
for drop, n, ri, size in cand[:6]:
    print("  %02X / %02X   %5d Hz -> %5d Hz  (drop %5d)  %6d bytes"
          % (n, n | 0x80, RATE[ri], RATE[ri + 1], drop, size))

print()
print("rows that CANNOT step (expect identical, and that is the fix working):")
sat = [n for n, ptr, typ, size in rows if size and ((typ >> 4) & 7) >= 5]
print("  " + (', '.join('%02X' % n for n in sat[:24]) if sat else 'none'))
print("  %d rows total" % len(sat))
