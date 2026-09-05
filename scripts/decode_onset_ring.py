"""Decode the per-frame load-refusal ring out of Paprium.sav.

    python scripts/decode_onset_ring.py "D:/Saves/paprium/common/Paprium.sav"

The elevator band is a TIMED event: a few background tiles look misplaced, then
roughly half a second later the squares fill in. A whole-run refusal total
cannot see that. 737 refusals spread evenly over 27809 frames and 737 refusals
packed into thirty frames read identically in a sticky counter and mean
opposite things.

So the firmware keeps the last PPM_ONSET_FRAMES in-game frames in a ring, two
bytes each:

    byte 0   high nibble  load refusals that frame   (saturates at 15)
             low  nibble  loads that succeeded       (saturates at 15)
    byte 1   whole blocks still affordable at the END of the frame,
             i.e. dma_remaining / 0x110 - the quantity the refusal test
             actually reads. 0 means the next load cannot be paid for.

The tester quits shortly after the band appears, so the tail of the ring IS
the onset window.

READING IT. The ring alone has no baseline - all eight seconds of it sit near
the event. The baseline is the whole-run sticky rate, which the same capture
carries, and the comparison below is against that. A spike confined to the
ring says budget starvation is the mechanism. A ring rate that matches the
run rate says the block cache was behaving normally while the band formed, and
the fault is downstream of it - 68000->VDP destination or the name table.
"""
import struct
import sys

# The save carries a 16-byte boot marker at 0x900 and the snapshot proper
# (b[0] = 'P','S','A','T' in mcu/mame.c) at 0x910. The whole region is stored
# 16-bit byte-swapped, which is why the magic reads 'SPTA' in a hex dump - so
# the swap is applied ONCE here and every offset below is then the same number
# that appears in mcu/mame.c. Swapping per-field is how the two scripts would
# drift apart.
SNAP_BASE = 0x900
HDR = 0x10                      # boot marker, ahead of the snapshot
ARENA = HDR + 8 + 640
T_OFF = HDR + 8 + 640 + 1024 + 80
RING_TAG = 0xB0D5E701


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
        raise SystemExit("no PSAT magic at 0x%X - the capture never completed"
                         % (SNAP_BASE + HDR))
    o = b[ARENA:]

    # Find the meta by walking candidate ring sizes rather than hardcoding one,
    # so a firmware built with a different PPM_ONSET_FRAMES still decodes instead
    # of silently reporting another layout's bytes as frame data.
    meta_at = None
    for frames in (480, 400, 340, 256, 200):
        m = frames * 2
        if m + 24 > len(o):
            continue
        if struct.unpack('>I', o[m + 8:m + 12])[0] == RING_TAG:
            meta_at, cap_guess = m, frames
            break
    if meta_at is None:
        raise SystemExit("ring tag 0x%08X not found - this save is not from an "
                         "onset-ring build (a CRC-card save will land here)" % RING_TAG)

    idx_cap, seen, tag, budget_worst, starved, loads_ok = struct.unpack(
        '>6I', o[meta_at:meta_at + 24])
    idx = idx_cap >> 16
    cap = idx_cap & 0xFFFF
    budget = budget_worst >> 16
    worst = budget_worst & 0xFFFF
    if cap != cap_guess:
        raise SystemExit("meta says cap %d but the tag was found at the %d-frame "
                         "offset; refusing to guess" % (cap, cap_guess))

    # Whole-run totals, for the baseline. t[] layout from mcu/mame.c.
    t = b[T_OFF:]
    frames_run = struct.unpack('>I', t[13:17])[0]

    print("ring        : %d frames (%.1f s at 60 Hz), %d committed this run"
          % (cap, cap / 60.0, seen))
    print("dma_budget  : %d  -> %d blocks per frame affordable from full"
          % (budget, budget // 0x110))
    if seen < cap:
        print("  the run was SHORTER than the ring; only %d cells are real." % seen)
    n = min(seen, cap)
    if n == 0:
        raise SystemExit("no frames committed - nothing to read")

    # Rotate oldest-first. The MCU leaves it unrotated on purpose: doing it there
    # would cost time inside the frame being measured.
    cells = [o[i * 2:i * 2 + 2] for i in range(cap)]
    if seen >= cap:
        cells = cells[idx:] + cells[:idx]
    else:
        cells = cells[:seen]

    refuse = [c[0] >> 4 for c in cells]
    loads = [c[0] & 0xF for c in cells]
    afford = [c[1] for c in cells]

    ring_refuse = sum(refuse)
    ring_frames = len(cells)
    ring_rate = ring_refuse / float(ring_frames)
    run_rate = starved / float(frames_run) if frames_run else 0.0

    print()
    print("WHOLE RUN   frames %d   refusals %d   loads %d   -> %.4f refusals/frame"
          % (frames_run, starved, loads_ok, run_rate))
    print("LAST %-6d frames %d   refusals %d   loads %d   -> %.4f refusals/frame"
          % (ring_frames, ring_frames, ring_refuse, sum(loads), ring_rate))
    print("worst single frame in the whole run : %d refusals" % worst)

    # Timeline. One character per frame, newest at the right.
    print()
    print("TIMELINE  oldest -> newest, one column per frame")
    print("  refusals  . = 0  1-9 = count  + = 10 or more")
    print("  loads     . = 0  1-9 = count  + = 10 or more   (successful block loads)")
    print("  afford    # = 0 blocks payable   : = 1-2   . = 3 or more")
    print("            (on a PPM_LIST_ORDER_VRAM build this byte is instead the highest tile the stream reached, /1, saturating at 255)")

    def band(vals, f):
        return ''.join(f(v) for v in vals)

    def rf(v):
        return '.' if v == 0 else ('+' if v >= 10 else str(v))

    def af(v):
        return '#' if v == 0 else (':' if v <= 2 else '.')

    W = 120
    start = 0
    while start < ring_frames:
        chunk = slice(start, min(start + W, ring_frames))
        lo = start - ring_frames
        print()
        print("  frame %+d .. %+d  (relative to the last frame before quit)"
              % (lo, min(start + W, ring_frames) - ring_frames - 1))
        print("  ref  " + band(refuse[chunk], rf))
        print("  ld   " + band(loads[chunk], rf))
        print("  aff  " + band(afford[chunk], af))
        start += W

    # Verdict. The comparison that matters is ring rate against run rate, not
    # ring rate against zero - the whole ring sits inside the suspect window.
    print()
    print("VERDICT")
    if run_rate <= 0:
        print("  The run recorded no refusals at all, so there is no baseline and")
        print("  no starvation anywhere. Budget is not the mechanism in this run.")
    else:
        ratio = ring_rate / run_rate
        print("  last %d frames run at %.2fx the whole-run refusal rate."
              % (ring_frames, ratio))
        if ratio >= 3.0:
            print("  REFUSALS SPIKE in the onset window. Budget starvation is the")
            print("  live mechanism: ppm_vram_load_block returns 0, the block never")
            print("  loads, and the plane renders stale tiles. Next step is the")
            print("  dma_budget the game set for this room against what the scene")
            print("  actually asks for.")
        elif ratio <= 1.5:
            print("  REFUSALS ARE FLAT. The block cache was behaving normally while")
            print("  the band formed, so starvation is NOT the mechanism and another")
            print("  slot or budget knob will not fix it. Look past the block cache:")
            print("  68000->VDP destination and the name table.")
        else:
            print("  Between 1.5x and 3x - not a spike and not flat. Inconclusive on")
            print("  its own. Say so rather than picking a side: check whether the")
            print("  elevated frames are contiguous in the timeline above (an onset)")
            print("  or scattered (ordinary scrolling load pressure).")

    busy = [(i - ring_frames, loads[i], afford[i]) for i in range(ring_frames) if loads[i]]
    if busy:
        print()
        print("  frames with any load, (frame, loads, blocks left after):")
        print("    " + "  ".join("(%d, %d, %d)" % f for f in busy))
    starve_frames = sum(1 for v in afford if v == 0)
    print()
    print("  frames ending with ZERO blocks affordable : %d of %d (%.1f%%)"
          % (starve_frames, ring_frames, 100.0 * starve_frames / ring_frames))
    print("  This is the direct reading of the refusal test's own input, and it")
    print("  does not depend on any load having been ATTEMPTED that frame - a")
    print("  frame can be starved and record no refusal simply because nothing")
    print("  asked. Trust this line over the refusal count where they disagree.")


if __name__ == '__main__':
    main()
