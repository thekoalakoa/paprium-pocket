"""Decode the sprite-chain EVENT LOG out of a Paprium.sav.

    python scripts/decode_event_log.py <Paprium.sav>

The SAT snapshot describes one frame, and every question that actually blocked
the sprite investigation is a question about time - was the figure ever on the
chain this boot, did it leave before or after the relink pass first wrote, does
it leave on a frame the pass touched at all. Four captures and four theories went
by without answering any of them, because a single frame structurally cannot.

This capture logs an entry every time a sprite entry LEAVES the reachable link
chain, and again when it comes back:

    frame   the frame number, counting from the first in-game frame
    node    the SAT entry that left or rejoined
    prev    the entry that pointed to it last frame
    ->      where that entry points NOW, i.e. what it was rerouted to
    pass    whether the relink pass wrote links on that frame

The column that decides it is `pass`. A node leaving on a frame the pass did not
touch is the game rerouting its own list. A node leaving on a frame the pass
wrote is ours, and the frame number says whether it was the first one.
"""
import struct
import sys

F_JOINED, F_WROTE, F_BAILED = 0x01, 0x02, 0x04


def swapped(b):
    s = bytearray(len(b))
    s[0::2] = b[1::2]
    s[1::2] = b[0::2]
    return bytes(s)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    raw = open(sys.argv[1], 'rb').read()[0x900:0x1000]
    b = swapped(raw)

    if b[0x10:0x14] != b'PEVT':
        raise SystemExit("no event log in that save - this is the PEVT capture, "
                         "built with PPM_EVENT_LOG 1")

    h = b[0x10:]
    frames = struct.unpack('>H', h[4:6])[0]
    total = struct.unpack('>H', h[6:8])[0]
    stored = h[8]
    satcnt = h[9]
    writes = struct.unpack('>H', h[10:12])[0]
    bails = struct.unpack('>H', h[12:14])[0]
    maxgrp = h[14]
    geom = h[15]

    print("in-game frames logged : %d" % frames)
    print("sat_count at exit     : %d" % satcnt)
    print("relink wrote links on : %d frames" % writes)
    print("relink stood down on  : %d frames" % bails)
    print("largest mask group    : %d%s" % (maxgrp,
          ("   first mask %dx%d" % (((geom >> 2) & 3) + 1, (geom & 3) + 1)) if maxgrp else ""))
    print("chain events          : %d seen, %d stored%s"
          % (total, stored, "" if total <= stored else "  (BUFFER FULL - the")
          )
    if total > stored:
        print("                        earliest %d are kept, which is the onset)" % stored)
    print()

    if not stored:
        print("No entry ever left or rejoined the chain while in game.")
        print("Whatever is missing was never linked in the first place.")
        return

    # Everything the firmware wrote a BYTE at a time - header fields and event
    # records alike - reads correctly out of the swapped copy. Only the SAT block,
    # which is a memcpy of 16-bit words, wants the raw one. Getting this backwards
    # is how a whole afternoon went to "scrambled" tile and CRAM decodes once.
    ev = b[0x10 + 16 + 640:]
    print("   frame  node  prev   prev now ->  tile   pass wrote?  what")
    firstwrite = None
    for i in range(stored):
        e = ev[i * 8: i * 8 + 8]
        fr = struct.unpack('>H', e[0:2])[0]
        node, prev, newlink, flags = e[2], e[3], e[4], e[5]
        tile = struct.unpack('>H', e[6:8])[0]
        wrote = bool(flags & F_WROTE)
        if wrote and firstwrite is None:
            firstwrite = fr
        print("  %6d   %3d   %3s   %10s  0x%03X   %-11s %s"
              % (fr, node, "-" if prev == 0xFF else prev,
                 "-" if newlink == 0xFF else newlink, tile,
                 "YES" if wrote else "no",
                 "rejoined" if flags & F_JOINED else "LEFT THE CHAIN"))

    left_clean = [i for i in range(stored)
                  if not (ev[i * 8 + 5] & (F_JOINED | F_WROTE))]
    print()
    print("VERDICT")
    if not left_clean:
        print("  every departure happened on a frame the relink pass wrote.")
        print("  the pass is the cause; look at the first one above.")
    else:
        print("  %d entries left the chain on frames the pass did NOT write."
              % len(left_clean))
        print("  the game reroutes its own list, so a missing sprite is not")
        print("  automatically ours. Check whether the one you care about is in")
        print("  that set before changing anything in the pass.")


if __name__ == '__main__':
    main()
