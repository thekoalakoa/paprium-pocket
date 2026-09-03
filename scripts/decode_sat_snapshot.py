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
    # Byte 6/7 used to be the relink pass reporting itself. The pass is gone -
    # composing on 0xAD instead of batching at 0xAF put the masks where the game
    # means them, so there is nothing left to relink. What sits here now is the
    # one open question: how often ppm_obj_render silently dropped an object
    # because its animation index exceeded the max we computed for it.
    animover = struct.unpack('>H', hdr[0x16:0x18])[0]
    print("anim-over drops : %d" % animover)
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

    # ORPHANS: in the table, on screen, but not reachable through the chain, so
    # the VDP never draws them. Added 2026-09-02 - the subway capture had a whole
    # 48x96 character sitting in entries 14-19 that nothing in the old output
    # mentioned, because every view walked the chain and the chain is exactly what
    # had lost them. A sprite the game wrote and the hardware never drew is the
    # single most important thing a capture can say.
    reached = set(e['n'] for e in chain)
    orphans = [e for e in ents[:max(count + 4, 1)]
               if e['n'] not in reached and -64 < e['x'] < 320 and -64 < e['y'] < 224]
    if orphans:
        print()
        print("ORPHANED - written to the table, on screen, NOT in the chain, NEVER DRAWN")
        print("   n     Y     X   size   tile   pri   link")
        for e in orphans:
            print("  %3d  %4d  %4d   %dx%d  0x%03X    %d    ->%d"
                  % (e['n'], e['y'], e['x'], e['sx'], e['sy'], e['attr'] & 0x7FF,
                     (e['attr'] >> 15) & 1, e['link']))

    masks = [e for e in chain if e['x'] == -128]
    print()
    print("  sprite masks IN the chain: %d   (stale X=0 entries outside it: %d, inert)"
          % (len(masks), sum(1 for e in live if e['x'] == -128) - len(masks)))

    # The three checks a relink capture has to pass, printed as a verdict so a
    # capture is read the same way every time instead of by eye. Reachable short
    # of composed is the subway failure: the game wrote sprites the chain cannot
    # get to, and because it only writes link topology once per scene, they stay
    # unreachable for the rest of the level.
    # Sticky run totals past the owner map.
    t = swapped(b[8 + 640 + 1024 + 80 + 0x10:])
    hits = struct.unpack('>H', t[0:2])[0]

    # Dispatch counters, in the bytes the (broken, unused) owner map had.
    d = swapped(b[8 + 640 + 1024 + 0x10:])
    ae, af, ad, refresh = struct.unpack('>IIII', d[0:16])

    print()
    print("COMMAND DISPATCH (whole run)")
    print("  0xAE frame start : %d" % ae)
    print("  0xAF frame end   : %d" % af)
    print("  0xAD sprite draw : %d" % ad)
    print("  ppm_dma_refresh  : %d" % refresh)

    print()
    print("WHOLE RUN (sticky, not just this frame)")
    print("  objects dropped by the anim-over early-out : %d" % hits)
    if hits:
        print("  last one: objID 0x%02X asked for anim %d, we had max %d"
              % (t[2], t[3], t[4]))
        print("  -> that return IS firing. Compare the objID against what")
        print("     failed to show its destroyed sprite.")
    else:
        print("  -> it never fired. If a destructible still stayed whole, the")
        print("     early-out is NOT the cause and the suspect was wrong.")

    # The two silent returns in ppm_block_load. Both mean "the block never
    # arrived", and a sprite whose graphics never arrived draws with whatever
    # tiles are already there - which is why a destroyed pillar can keep looking
    # intact rather than disappearing.
    starved = struct.unpack('>H', t[5:7])[0]
    noslot = struct.unpack('>H', t[7:9])[0]
    print("  block loads refused, out of DMA budget    : %d" % starved)
    print("  block loads refused, every slot in use    : %d" % noslot)
    ok = struct.unpack('>I', t[9:13])[0]
    frames = struct.unpack('>I', t[13:17])[0]
    print("  block loads that SUCCEEDED                : %d" % ok)
    print("  in-game frames (tick inside frame_start)  : %d" % frames)
    # NEVER announce a conclusion from a counter that might not have been compiled
    # in. Twice now a #if that could not see its own #define produced a zero, and
    # this script read the zero as hardware behaviour - once declaring that a
    # command was not dispatched when it fires 30,585 times a run.
    #
    # frames and ppm_dma_refresh are counted in mame.c; 0xAE/0xAF/0xAD in
    # paprium.c. If one file's counters are all zero while the other's are not,
    # that is an instrument fault, not a measurement.
    if ae and not frames:
        print("  -> 0xAE IS dispatched %d times but the tick inside" % ae)
        print("     ppm_obj_frame_start never incremented - INSTRUMENT FAULT in")
        print("     mame.c, not a hardware finding.")
    elif not ae and frames:
        print("  -> INSTRUMENT FAULT, not a finding: the paprium.c counters are")
        print("     all zero while mame.c's are not, so they were compiled out.")
        print("     0xAE dispatch was measured at 30,585 on deb45ef5. Do not read")
        print("     these zeros as behaviour; fix the build and re-run.")
    elif not ae and not frames:
        print("  -> every counter is zero. Either the capture is not from a")
        print("     snapshot build, or nothing ran. Check the bitstream md5.")

    # A refusal count with no denominator is unreadable: 1176 is healthy against
    # forty thousand loads and alarming against twelve hundred. Two ratios, so the
    # number means something.
    total = ok + starved
    if total:
        print("  refusal rate      : %.1f%%  (%d of %d attempts)"
              % (100.0 * starved / total, starved, total))
    if frames:
        print("  refusals per frame: %.3f     loads per frame: %.2f"
              % (starved / float(frames), ok / float(frames)))
    if noslot:
        print("  -> slot pressure, which is what PPM_VRAM_SAFE_SLOTS caps.")
        print("     That is a DIFFERENT bug from budget starvation.")

    # Stream pointer audit. The MCU unpacks blocks to 0x9000, 0x9200, ... and sets
    # the 68000's read cursor to 0x9000; the RTL advances it two bytes per
    # delivered word. After a frame is drained the two should agree exactly.
    mism = struct.unpack('>H', t[17:19])[0]
    last = struct.unpack('>i', t[19:23])[0]
    worst = struct.unpack('>i', swapped(b[8 + 640 + 1024 + 16 + 0x10:])[0:4])[0]

    print()
    print("STREAM POINTER AUDIT")
    print("  frames where it did not land where expected : %d" % mism)
    if mism:
        print("  last delta  : %+d bytes" % last)
        print("  worst delta : %+d bytes" % worst)
        print()
        # A STEADY SMALL LAG IS NOT DESYNC. The 68000 can still be draining the
        # window when 0xAF runs, so on a busy frame the pointer legitimately sits
        # a few words short of where the MCU finished. That reads as a mismatch
        # every frame with a small, unchanging delta. Desync that could explain #8
        # is a delta that GROWS, or steps of 0x200, and only in the car.
        if abs(worst) <= 16 and abs(worst) - abs(last) <= 4:
            print("  -> steady lag of a few words, not growing. That is DMA still")
            print("     in flight when 0xAF ran, which is expected on a busy frame.")
            print("     NOT desync. Do not read this as the cause of anything.")
        elif worst and abs(worst) % 0x200 == 0:
            print("  -> worst is %+d = %+d whole block(s). A wrong block was queued,"
                  % (worst, worst // 0x200))
            print("     not a counting fault.")
        elif abs(worst) > abs(last) * 2 and abs(worst) > 16:
            print("  -> the delta GROWS. That is the signature that would explain")
            print("     garbage accumulating through a level. Check it is confined")
            print("     to the elevator before believing it.")
        elif abs(worst) <= 8:
            print("  -> %+d bytes, one or two words: a lost or double-counted read"
                  % worst)
            print("     acknowledgement.")
    else:
        print("  -> the pointer landed exactly where the MCU finished, every frame.")
        print("     If garbage still grew in this run, desync is NOT the story:")
        print("     look at which bytes were unpacked, or whether the background")
        print("     path comes through this window at all.")

    # Eviction audit - the firmware-only question for the elevator corruption.
    e = swapped(b[8 + 640 + 1024 + 16 + 0x10:])
    ev_live = struct.unpack('>I', e[0:4])[0]
    ev_worst = struct.unpack('>H', e[4:6])[0]
    ev_reload = struct.unpack('>H', e[6:8])[0]

    print()
    print("VRAM SLOT EVICTIONS")
    print("  slots taken from a block that held real art : %d" % ev_live)
    print("  worst in a single frame                     : %d" % ev_worst)
    print("  evicted then fetched back (thrash)          : %d" % ev_reload)
    if frames:
        print("  per frame                                   : %.2f" % (ev_live / float(frames)))
    print()
    print("  A slot is evicted when nobody REQUESTED its block that frame. Sprites")
    print("  are re-requested every frame so they are safe; background tiles are")
    print("  not - the game DMAs the plane's name table, and nothing calls the")
    print("  block loader for them again. So a background block ages at usage 0,")
    print("  becomes the preferred victim, and its slot is overwritten while the")
    print("  plane is still showing it.")
    if ev_live == 0:
        print("  -> NOTHING was evicted. That mechanism is dead for this scene;")
        print("     the wrong tiles came from somewhere else entirely.")
    elif ev_reload > ev_live // 4:
        print("  -> heavy thrash: much of what was thrown away had to be fetched")
        print("     back. The slot budget is short for this scene, which is a")
        print("     different fault from a one-way eviction.")

    print()
    print("VERDICT")
    print("  relink        REMOVED - sprites compose on 0xAD, nothing edits the list")
    # Reachable short of composed is NOT automatically our bug, and saying so was
    # a mistake worth not repeating. The 2026-09-02 rooftop capture has 4->8 past
    # entries 5,6,7 and 8->11 past 9,10 - the same "predecessor rewired past a run"
    # shape that was read as evidence in the subway - while the relink pass had
    # STOOD DOWN and written nothing at all. The game bypasses its own entries,
    # typically HUD it is hiding. So this line reports; it does not judge.
    print("  reachability  %d reachable vs %d composed%s"
          % (len(chain), count,
             "" if len(chain) >= count
             else "   (%d unlinked - the game does this itself; judge by what they are)"
                  % (count - len(chain))))
    blank = [e for e in orphans if (e['attr'] & 0x7FF) == 0]
    print("  orphans       %d on screen, %d of them blank"
          % (len(orphans), len(blank)))
    if orphans:
        print("                a blank orphan is inert. One carrying real art is a")
        print("                sprite the game drew and the VDP will not - compare")
        print("                against what you saw on screen before calling it.")

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
