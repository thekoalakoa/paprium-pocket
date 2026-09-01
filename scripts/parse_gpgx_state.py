"""Pull the VDP register set and the sprite attribute table out of a Genesis Plus GX
savestate.

This exists so the VDP capture needs no compiler and no debugger build: play to the
scene in RetroArch with the Paprium-capable GPGX core, save a state, and run this on
the .state file.

    python scripts/parse_gpgx_state.py cellroom.state
    python scripts/parse_gpgx_state.py rooftop.state --sat-all

Layout comes from the source in gpgx-build/core, and is anchored on the version
string rather than on computed offsets, so a RetroArch container or compression in
front of the payload does not matter:

    state.c        16-byte version "GENPLUS-GX 1.7.6", then
                   work_ram[0x10000], zram[0x2000], zstate(1), zbank(4),
                   io_reg[0x10], then vdp_context_save()
    vdp_ctrl.c     sat[0x400], vram[0x10000], cram[0x80], vsram[0x80], reg[0x20]

Register decode (Mega Drive, mode 5):

    reg 2   plane A   (v & 0x38) << 10
    reg 3   window    (v & 0x3E) << 10
    reg 4   plane B   (v & 0x07) << 13
    reg 5   SAT       (v & 0x7F) << 9
    reg 13  hscroll   (v & 0x3F) << 10
    reg 17  window H  bit 7 = right of centre, low 5 bits = units of 16 px
    reg 18  window V  bit 7 = below centre,    low 5 bits = units of 8 px
"""
import sys
import zlib

VERSION = b"GENPLUS-GX 1.7.6"

WORK_RAM = 0x10000
ZRAM     = 0x2000
ZSTATE   = 1
ZBANK    = 4
IO_REG   = 0x10

SAT_SZ   = 0x400
VRAM_SZ  = 0x10000
CRAM_SZ  = 0x80
VSRAM_SZ = 0x80
REG_SZ   = 0x20

PLANE_SIZES = {0: 32, 1: 64, 2: 64, 3: 128}   # reg 16 nibble -> cells



def unswap(buf):
    """Undo GPGX's native-endian 16-bit VRAM storage.

    vdp_ctrl.c writes VRAM through `uint16 *p = (uint16 *)&vram[index]`, so on a
    little-endian host every 16-bit word is byte-swapped relative to the layout a
    Mega Drive actually sees. Reading it as big-endian scrambles BOTH tile pattern
    bytes and nametable/SAT words.

    This cost a wrong conclusion: the sprite tables looked like garbage, and that
    was written up as "GPGX does not render the scene, so its sprite output is not
    evidence". Undoing the swap, the same captures hold coherent sprite lists.
    """
    out = bytearray(len(buf))
    out[0::2] = buf[1::2]
    out[1::2] = buf[0::2]
    return bytes(out)

def load(path):
    """Return the raw state payload, whatever RetroArch wrapped it in."""
    raw = open(path, 'rb').read()
    if VERSION in raw:
        return raw, "raw"
    try:
        d = zlib.decompress(raw)
        if VERSION in d:
            return d, "zlib"
    except zlib.error:
        pass
    for skip in range(0, min(len(raw), 4096)):          # RASTATE-style container
        try:
            d = zlib.decompress(raw[skip:])
            if VERSION in d:
                return d, "zlib+%d" % skip
        except zlib.error:
            continue
    raise SystemExit(
        "could not find a GENPLUS-GX 1.7.6 payload in %s.\n"
        "Is it a Genesis Plus GX state? If RetroArch compressed it with something\n"
        "other than zlib, turn savestate compression off and re-save." % path)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    sat_all = '--sat-all' in sys.argv
    if not args:
        raise SystemExit(__doc__)

    blob, how = load(args[0])
    base = blob.index(VERSION) + 16
    vdp = base + WORK_RAM + ZRAM + ZSTATE + ZBANK + IO_REG

    sat_cache = unswap(blob[vdp:vdp + SAT_SZ])
    vram = unswap(blob[vdp + SAT_SZ: vdp + SAT_SZ + VRAM_SZ])
    reg_off = vdp + SAT_SZ + VRAM_SZ + CRAM_SZ + VSRAM_SZ
    reg = blob[reg_off:reg_off + REG_SZ]

    if len(reg) < REG_SZ or len(vram) < VRAM_SZ:
        raise SystemExit("state is truncated - got %d bytes after the anchor" % (len(blob) - base))

    print("file      : %s  (payload: %s)" % (args[0], how))
    print()

    planeA  = (reg[2] & 0x38) << 10
    window  = (reg[3] & 0x3E) << 10
    planeB  = (reg[4] & 0x07) << 13
    satbase = (reg[5] & 0x7F) << 9
    hscroll = (reg[13] & 0x3F) << 10

    w, h = PLANE_SIZES[reg[16] & 3], PLANE_SIZES[(reg[16] >> 4) & 3]
    map_bytes = w * h * 2

    print("VDP registers")
    print("  reg  2 = 0x%02X   plane A  0x%04X" % (reg[2], planeA))
    print("  reg  3 = 0x%02X   window   0x%04X" % (reg[3], window))
    print("  reg  4 = 0x%02X   plane B  0x%04X" % (reg[4], planeB))
    print("  reg  5 = 0x%02X   SAT      0x%04X" % (reg[5], satbase))
    print("  reg 13 = 0x%02X   hscroll  0x%04X" % (reg[13], hscroll))
    print("  reg 16 = 0x%02X   plane size %dx%d cells = 0x%X bytes" % (reg[16], w, h, map_bytes))
    print("  reg 17 = 0x%02X   window H %s of column %d  (x = %d px)"
          % (reg[17], "right" if reg[17] & 0x80 else "left", reg[17] & 0x1F, (reg[17] & 0x1F) * 16))
    print("  reg 18 = 0x%02X   window V %s of row %d     (y = %d px)"
          % (reg[18], "below" if reg[18] & 0x80 else "above", reg[18] & 0x1F, (reg[18] & 0x1F) * 8))
    print("  reg 12 = 0x%02X   %s, %s" % (reg[12],
        "40 cell" if reg[12] & 0x81 else "32 cell",
        "interlace" if (reg[12] >> 1) & 3 else "no interlace"))
    print()

    print("VRAM occupancy of the things the allocator must avoid")
    regions = [("plane A", planeA, map_bytes), ("plane B", planeB, map_bytes),
               ("window", window, map_bytes), ("SAT", satbase, 0x280),
               ("hscroll", hscroll, 0x400)]
    for name, addr, size in sorted(regions, key=lambda r: r[1]):
        print("  %-8s 0x%04X - 0x%04X   (tiles %4d - %4d)"
              % (name, addr, addr + size - 1, addr // 32, (addr + size - 1) // 32))
    print()
    print("  16-tile allocator blocks are 0x200 bytes. A block at tile N covers")
    print("  0x%X*N .. 0x%X*N+0x1FF - compare against the ranges above." % (32, 32))
    print()

    print("Sprite attribute table, read from VRAM at 0x%04X" % satbase)
    print("  slot   Y     X    size  link  tile   pri  pal  flip")
    shown = 0
    for i in range(80):
        e = vram[satbase + i * 8: satbase + i * 8 + 8]
        if len(e) < 8:
            break
        y = ((e[0] << 8) | e[1]) & 0x3FF
        sz = e[2]
        link = e[3] & 0x7F
        attr = (e[4] << 8) | e[5]
        x = ((e[6] << 8) | e[7]) & 0x1FF
        tile = attr & 0x7FF
        pri = (attr >> 15) & 1
        pal = (attr >> 13) & 3
        flip = ("H" if (attr >> 11) & 1 else "-") + ("V" if (attr >> 12) & 1 else "-")

        if not sat_all and y == 0 and x == 0 and tile == 0:
            continue
        print("   %3d  %4d  %4d   %dx%d   %3d  0x%03X   %d    %d   %s"
              % (i, y - 128, x - 128, ((sz >> 2) & 3) + 1, (sz & 3) + 1,
                 link, tile, pri, pal, flip))
        shown += 1
        if link == 0 and not sat_all:
            print("   (link 0 - end of the sprite list)")
            break
    if shown == 0:
        print("   (no live entries)")
    print()
    print("  Y and X are screen coordinates: the table stores them offset by 128.")
    print("  pri 1 = in front of both planes. A player drawn behind scenery while")
    print("  pri 1 would NOT be a priority problem - look for a window plane instead.")


if __name__ == '__main__':
    main()
