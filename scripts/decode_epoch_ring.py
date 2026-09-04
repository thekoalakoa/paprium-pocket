"""Decode the per-epoch delivered-word ring out of Paprium.sav.

    python scripts/decode_epoch_ring.py "D:/Saves/paprium/common/Paprium.sav"

An EPOCH is the interval between two MCU writes of sdram_ptr. On every such
write the RTL latches two counts for the epoch that just ended:

    ack   SDRAM reads that advanced the stream pointer (what the tape did)
    oe    68000 read strobes inside the window, debounced the way the real
          cartridge counts them (what the game asked for)

If the tape kept step, ack == oe. ack > oe is a double-advance: one 68000
word issued two SDRAM reads, and every tile fetched after it is shifted by a
word until the next re-point. That is the mechanism left standing after the
CRC card (bytes are right) and the onset ring (the block cache was idle while
the band formed).

Only epochs with traffic are recorded. Each is 10 bytes: ack u16, oe u16,
frame u16 (low half of the in-game frame counter), ptr u32 (the pointer that
was in force for the epoch). The ring keeps the LAST 99 active epochs.

READ CRITERIA, fixed before the capture existed (docs/PORT_PLAN.md):

    ack > oe in epochs clustered at the onset   -> desync owns the band
    ack == oe through the band                  -> look past the cursor

Byte-level detail is in the record; the verdict is in the difference column.
"""
import struct
import sys

SNAP_BASE = 0x900
HDR = 0x10
ARENA = HDR + 8 + 640
T_OFF = HDR + 8 + 640 + 1024 + 80
EP_TAG = 0xE70C0DE1
REC = 10


def swapped(b):
    s = bytearray(len(b))
    s[0::2] = b[1::2]
    s[1::2] = b[0::2]
    return bytes(s)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    d = open(sys.argv[1], 'rb').read()
    if len(d) < 0x1000:
        raise SystemExit("%s is %d bytes; expected a 4096-byte save" % (sys.argv[1], len(d)))
    b = swapped(d[SNAP_BASE:0x1000])
    if b[HDR:HDR + 4] != b'PSAT':
        raise SystemExit("no PSAT magic at 0x%X - the capture never completed" % (SNAP_BASE + HDR))
    o = b[ARENA:]

    # Locate the meta by its tag rather than trusting a hardcoded cap, so a
    # firmware built with a different PPM_EPOCH_CAP decodes or refuses - never
    # silently reads another layout's bytes as epochs.
    meta_at = None
    for cap in (99, 96, 90, 80, 64, 50):
        m = cap * REC
        if m + 32 > len(o):
            continue
        if struct.unpack('>I', o[m + 8:m + 12])[0] == EP_TAG:
            meta_at, cap_guess = m, cap
            break
    if meta_at is None:
        raise SystemExit("epoch tag 0x%08X not found - this save is not from an "
                         "epoch-ring build" % EP_TAG)

    idx_cap, seen, tag, total, worst_mism, first_mism, sum_ack, sum_oe = struct.unpack(
        '>8I', o[meta_at:meta_at + 32])
    idx = idx_cap >> 16
    cap = idx_cap & 0xFFFF
    worst = worst_mism >> 16
    mism = worst_mism & 0xFFFF
    if cap != cap_guess:
        raise SystemExit("meta says cap %d but the tag sits at the %d-epoch offset; "
                         "refusing to guess" % (cap, cap_guess))

    t = b[T_OFF:]
    frames_run = struct.unpack('>I', t[13:17])[0]

    print("epochs      : %d total this run, %d with traffic (recorded), ring holds %d"
          % (total, seen, cap))
    print("frames      : %d in-game" % frames_run)
    print()
    print("WHOLE RUN   ack %d   oe %d   diff %+d   mismatched epochs %d   worst |diff| %d"
          % (sum_ack, sum_oe, sum_ack - sum_oe, mism, worst))
    if mism:
        print("            first mismatch at in-game frame %d  (%.1f s in)"
              % (first_mism, first_mism / 60.0))
    else:
        print("            no epoch ever disagreed. The tape kept step with the game")
        print("            for the entire run.")

    n = min(seen, cap)
    if n == 0:
        raise SystemExit("no active epochs recorded - nothing to read")
    recs = [o[i * REC:(i + 1) * REC] for i in range(cap)]
    recs = (recs[idx:] + recs[:idx]) if seen >= cap else recs[:seen]

    rows = []
    for r in recs:
        ack, oe, fr = struct.unpack('>HHH', r[0:6])
        ptr = struct.unpack('>I', r[6:10])[0]
        rows.append((ack, oe, fr, ptr))

    print()
    print("LAST %d ACTIVE EPOCHS   oldest first" % len(rows))
    print("   #   frame     ptr        ack     oe   diff")
    last_fr = None
    for i, (ack, oe, fr, ptr) in enumerate(rows):
        diff = ack - oe
        flag = ""
        if diff > 0:
            flag = "  <-- OVER-ADVANCE"
        elif diff < 0:
            flag = "  <-- under"
        print("  %2d   %5d   0x%06X   %5d  %5d   %+4d%s" % (i, fr, ptr, ack, oe, diff, flag))

    ring_ack = sum(r[0] for r in rows)
    ring_oe = sum(r[1] for r in rows)
    ring_mism = sum(1 for r in rows if r[0] != r[1])
    over = [r for r in rows if r[0] > r[1]]

    print()
    print("VERDICT  (criteria fixed before this capture existed)")
    print("  ring: ack %d  oe %d  diff %+d  mismatched %d of %d"
          % (ring_ack, ring_oe, ring_ack - ring_oe, ring_mism, len(rows)))
    if not mism:
        print("  EXACT MATCH, whole run and window. The pointer advanced once per")
        print("  68000 word every time. Desync by double-advance is NOT the mechanism.")
        print("  Look past the cursor: the 68000->VDP destination and the name table.")
    elif over:
        # Contiguity: are the over-advances clustered (an onset) or scattered?
        fr = sorted(r[2] for r in over)
        span = fr[-1] - fr[0] if len(fr) > 1 else 0
        print("  OVER-ADVANCE observed in %d epoch(s) of the window, %d in the run."
              % (len(over), mism))
        print("  frames of the over-advances: %s" % ", ".join(str(x) for x in fr))
        if span and span <= 300:
            print("  -> clustered within %d frames (%.1f s): an ONSET. Desync owns the"
                  % (span, span / 60.0))
            print("     band. The fix is in cartridge.sv's request-issue path, not in")
            print("     firmware.")
        else:
            print("  -> spread over %d frames. Not clearly an onset on its own - read the"
                  % span)
            print("     ptr column: over-advances inside the background payload (ptr <")
            print("     0x9000) are the ones that reach the plane.")
    else:
        print("  Mismatches are all UNDER-advances (ack < oe). That is the toggle")
        print("  crossing losing a flip, not the double-issue path. Different bug,")
        print("  same consequence for the tiles. Report it as what it is.")
    print()
    print("  (a difference of exactly zero in every epoch while the band was on")
    print("   screen is the strong result here: it retires the whole tape theory.)")


if __name__ == '__main__':
    main()
