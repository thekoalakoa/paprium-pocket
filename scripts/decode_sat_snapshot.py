"""Decode the on-hardware sprite-list snapshot out of Paprium.sav.

    python scripts/decode_sat_snapshot.py "D:/Saves/paprium/common/Paprium.sav"

Written by the PPM_SAT_SNAPSHOT diagnostic firmware (mcu/mame.c). It parks the
sprite list this firmware builds at ramdp 0xB00, plus the object table the 68000
hands us at 0xF80, in battery-backed RAM, which the Pocket persists to the .sav.

    0x900  'PBOT' + u16 boot counter      control marker
    0x910  'PSAT' + u16 sat_count         the capture
    0x918  80 x ppm_sat_item   (640 B)
    0xB98  64 x ppm_intf_obj   (1024 B)

BYTE ORDER, the hard-won part: the two halves are NOT stored the same way.

  - the magic and counters are written byte-by-byte (b[0]='P', b[1]='S', ...) and
    come back byte-swapped within each 16-bit word, because ramdp_io.sv maps the
    MCU byte index to the 68000 address XOR 1
  - the sprite and object payloads are memcpy'd as whole structs and keep the
    68000's own big-endian layout, so they read straight

Confirmed by scoring: read raw, 56 of 76 entries land on screen; read swapped,
2 do. Do not "fix" one to match the other.

The VDP walks the SAT as a LINKED LIST from entry 0 via the link field, so entries
that are not reachable are never drawn - which matters, because stale off-screen
entries sitting at X=0 look like sprite masks but are inert if the chain skips
them.
"""
import struct
import sys


def load(path):
    d = open(path, 'rb').read()
    if len(d) < 0x1000:
        raise SystemExit("%s is %d bytes; expected a 4096-byte save" % (path, len(d)))
    return d[0x900:0x1000]


def swapped(b):
    s = bytearray(len(b))
    s[0::2] = b[1::2]
    s[1::2] = b[0::2]
    return bytes(s)


def sprite(b, i):
    e = b[0x18 + i * 8: 0x18 + i * 8 + 8]
    return {
        'n': i,
        'y': (struct.unpack('>H', e[0:2])[0] & 0x3FF) - 128,
        'sx': ((e[2] >> 2) & 3) + 1,
        'sy': (e[2] & 3) + 1,
        'link': e[3],
        'attr': struct.unpack('>H', e[4:6])[0],
        'x': (struct.unpack('>H', e[6:8])[0] & 0x1FF) - 128,
    }


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    b = load(sys.argv[1])
    hdr = swapped(b)

    boot = hdr[0:4] == b'PBOT'
    print("boot marker : %s" % ("present, boot #%d" % struct.unpack('>H', hdr[4:6])[0]
                                if boot else "ABSENT"))
    if hdr[0x10:0x14] != b'PSAT':
        raise SystemExit("no capture in this save - play a busy scene and exit "
                         "through the Pocket menu")
    count = struct.unpack('>H', hdr[0x14:0x16])[0]
    print("capture     : sat_count %d at the busiest frame" % count)
    print()

    ents = [sprite(b, i) for i in range(80)]
    live = [e for e in ents if not (e['y'] == -128 and e['x'] == -128 and e['attr'] == 0)]

    # The VDP only draws what the link chain reaches.
    chain, i, seen = [], 0, set()
    while i not in seen and len(chain) < 80:
        seen.add(i)
        chain.append(ents[i])
        if ents[i]['link'] == 0:
            break
        i = ents[i]['link']

    print("DRAWN SPRITES - walking the link chain from entry 0 (%d reached)" % len(chain))
    print("   n     Y     X   size   tile   pri  pal   note")
    for e in chain:
        t = e['attr'] & 0x7FF
        note = ""
        if e['x'] == -128:
            note = "X=0, masks lower-priority sprites on these lines"
        elif 1984 <= t <= 2047:
            note = "tile in slots 49-52 (cap-53 range)"
        print("  %3d  %4d  %4d   %dx%d  0x%03X    %d    %d   %s"
              % (e['n'], e['y'], e['x'], e['sx'], e['sy'], t,
                 (e['attr'] >> 15) & 1, (e['attr'] >> 13) & 3, note))

    onscreen = [e for e in chain if -32 < e['x'] < 320 and -32 < e['y'] < 240]
    p1 = sum(1 for e in onscreen if e['attr'] & 0x8000)
    print()
    print("  on screen %d   priority 1: %d   priority 0: %d"
          % (len(onscreen), p1, len(onscreen) - p1))

    def band(lo, hi):
        return sum(1 for e in onscreen if lo <= (e['attr'] & 0x7FF) <= hi)
    print("  tiles  16- 799 (low slots)      : %d" % band(16, 799))
    print("  tiles 800-1983 (non-slot)       : %d" % band(800, 1983))
    print("  tiles 1984-2047 (slots 49-52)   : %d" % band(1984, 2047))

    masks = [e for e in chain if e['x'] == -128]
    print()
    print("  sprite masks IN the chain: %d   (stale X=0 entries outside it: %d, inert)"
          % (len(masks), sum(1 for e in live if e['x'] == -128) - len(masks)))

    print()
    print("OBJECT TABLE - what the 68000 asked the cartridge to draw")
    print("   n   anim   objID    attrs    posX  posY  pri  pal")
    shown = 0
    for i in range(64):
        o = b[0x298 + i * 16: 0x298 + i * 16 + 16]
        if len(o) < 16:
            break
        anim, nxt, objid, f6, attrs, ctr, px, py = struct.unpack('>8H', o)
        if objid == 0 and attrs == 0 and px == 0 and py == 0:
            continue
        shown += 1
        if shown <= 24:
            print("  %3d  %5d  0x%04X  0x%04X  %5d %5d   %d    %d"
                  % (i, anim, objid, attrs, px - 128, py - 128,
                     (attrs >> 15) & 1, (attrs >> 13) & 3))
    print("  -> %d objects present" % shown)


if __name__ == '__main__':
    main()
