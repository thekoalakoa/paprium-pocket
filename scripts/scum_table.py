"""The Scum! patch table - every word the cartridge substitutes on a ROM read when a
Scum! switch is on - and the generator for its case table in
rtl/PAPRIUM/paprium_scum.sv.

    python scripts/scum_table.py --write     regenerate the table in paprium_scum.sv (needs no ROM)
    python scripts/scum_table.py --check     check your ROM: the patch sites, the caves' space and
                                             the stage word are what this table was made for
    python scripts/scum_table.py --rom OUT   write a statically patched COPY for an emulator test
                                             (all switches on); local only

Addresses are 68000 byte addresses. --check and --rom need PAPRIUM_ROM (see paprium_data.py).
The ROM and any patched copy are game data: never commit them. This file and the table it
writes carry no original game words at the patch sites: --check compares them with a SHA-256
digest instead. Background in docs/SCUM.md.
"""
import hashlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paprium_data

HEALTH_CAVE = 0x0BF000      # zero padding before the 0x0C0000 animation container (scum_health_cave.s)
PAD_CAVE = 0x11C560
STAGE_WORD = 0x0B0A14       # arcade start stage (krikzz), 0x0001 = Block 888

# players take no damage: the jsr replaces the two instructions of the damage-vs-health
# decision; the cave zeroes d3 (the damage) for object slots 1..[$FF9903]-1 (objects are
# $FF8610 + $100*slot, the game's own player test) and then redoes the two instructions,
# so the following branch sees the same flags
HEALTH_CAVE_CODE = [
    0x200A,                     # move.l  a2,d0
    0x0280, 0x00FF, 0xFFFF,     # andi.l  #$FFFFFF,d0
    0x0480, 0x00FF, 0x8710,     # subi.l  #$FF8710,d0      offset from slot 1
    0x6516,                     # bcs.s   .go
    0xE088,                     # lsr.l   #8,d0
    0x5280,                     # addq.l  #1,d0            slot
    0x0C80, 0x0000, 0x00FF,     # cmpi.l  #$FF,d0
    0x620A,                     # bhi.s   .go
    0xB039, 0x00FF, 0x9903,     # cmp.b   $FF9903.l,d0     slot < player count?
    0x6402,                     # bcc.s   .go
    0x7600,                     # moveq   #0,d3            player: no damage
    0x302A, 0x0088,             # .go: move.w $88(a2),d0
    0xB640,                     # cmp.w   d0,d3
    0x4E75,                     # rts
]

# pad hook: Pezz V.06's injection into the game's pad words, in the game's own bit
# order (Z=bit 8, Y=9, X=10, Mode=11); then adroxe's Mode-press credit in Arcade Mode.
# The cave also has a one-pad CPU MATE join on flags bit 1, which 0.2.6 holds at 0
PAD_CAVE_CODE = [   # assembled from scripts/scum_pad_cave.s (vasm -m68000 -Fbin)
    0x4E5E, 0x3039, 0x0011, 0xC604, 0x8179, 0x00FF, 0x7028, 0x3039,
    0x0011, 0xC608, 0x8179, 0x00FF, 0x702A, 0x3039, 0x0011, 0xC606,
    0x8179, 0x00FF, 0x7038, 0x3039, 0x0011, 0xC60A, 0x8179, 0x00FF,
    0x703A, 0x0839, 0x0000, 0x0011, 0xC601, 0x6712, 0x3039, 0x00FF,
    0x702A, 0x0240, 0x0800, 0x6706, 0x4EB9, 0x000B, 0x5960, 0x0839,
    0x0001, 0x0011, 0xC601, 0x6724, 0x3039, 0x00FF, 0x702A, 0x0240,
    0x0800, 0x6718, 0x4A79, 0x00FF, 0x8810, 0x6610, 0x0079, 0x0080,
    0x00FF, 0x7038, 0x0079, 0x0080, 0x00FF, 0x703A, 0x4E75,
]


def _seq(base, words):
    return [(base + 2 * i, w) for i, w in enumerate(words)]


# (group, note, [(address, word)]). The RTL enables each group from its switch;
# G_HOOK is on with Arcade Mode or 6-Button
GROUPS = [
    ('G_HEALTH', 'players take no damage (jsr to the slot test); specials cost no health',
     _seq(0x02FAC4, [0x4EB9, HEALTH_CAVE >> 16, HEALTH_CAVE & 0xFFFF]) +
     _seq(0x030E8A, [0x4E71, 0x4E71]) +
     _seq(HEALTH_CAVE, HEALTH_CAVE_CODE)),
    ('G_PILLS', 'Blu pills are never spent: the decrement becomes nop',
     _seq(0x01A9FA, [0x4E71, 0x4E71])),
    ('G_LIVES', 'lives are never spent: the decrement becomes nop',
     _seq(0x02A4EE, [0x4E71])),
    ('G_ARCADE', 'arcade mode (adroxe): the two branches that skip the 0x810F arcade command become nop',
     _seq(0x0B5AB8, [0x4E71]) + _seq(0x0B5ACC, [0x4E71])),
    ('G_HOOK', 'pad hook: 0x0B2392 jmp to the pad cave at 0x11C560',
     _seq(0x0B2392, [0x4EF9, PAD_CAVE >> 16, PAD_CAVE & 0xFFFF]) +
     _seq(PAD_CAVE, PAD_CAVE_CODE)),
    # no CPU MATE group: the partner runs on the cartridge MCU (docs/SCUM.md)
]
REGS = [('arcade_w', 0x11C600), ('p1_held_w', 0x11C604), ('p2_held_w', 0x11C606),
        ('p1_press_w', 0x11C608), ('p2_press_w', 0x11C60A)]
# The pad cave and its registers sit in 512 bytes of 0xFF. They are not free space: they are
# the Hall of Fame name-entry bar's tile data, which the game copies with a VDP DMA, and the
# substitution covers DMA reads (the 0.2.6 known issue, docs/SCUM.md)
PAD_BLOCK = (0x11C560, 0x11C760)
HEALTH_BLOCK = (HEALTH_CAVE, HEALTH_CAVE + 2 * len(HEALTH_CAVE_CODE))
# SHA-256 of the original words at every patch site outside the two caves, in table order
SITES_SHA256 = '3a0c884f04f80c54ce963ab4c377ea98ccd03594ef1c2c1dd1f203238e8485fe'


def _in(a, block):
    return block[0] <= a < block[1]


def site_words(rom):
    return b''.join(rom[a:a + 2] for _, _, words in GROUPS for a, _ in words
                    if not _in(a, PAD_BLOCK) and not _in(a, HEALTH_BLOCK))


def check(rom):
    seen = set()
    for _, _, words in GROUPS:
        for a, _ in words:
            assert a % 2 == 0 and a not in seen, hex(a)
            seen.add(a)
            if _in(a, PAD_BLOCK):
                assert rom[a:a + 2] == b'\xff\xff', 'pad cave word 0x%06X is not 0xFFFF' % a
            if _in(a, HEALTH_BLOCK):
                assert rom[a:a + 2] == b'\x00\x00', 'health cave word 0x%06X is not zero padding' % a
    for _, a in REGS:
        assert rom[a:a + 2] == b'\xff\xff' and a not in seen, hex(a)
    assert rom[STAGE_WORD:STAGE_WORD + 2] == b'\x00\x01', 'stage word'
    assert hashlib.sha256(site_words(rom)).hexdigest() == SITES_SHA256, \
        'the patch sites do not hold the words this table was made for: a different ROM revision?'
    return len(seen) + len(REGS) + 1


def table():
    out = []
    for g, note, words in GROUPS:
        out.append('\t\t// %s' % note)
        for a, w in words:
            out.append("\t\t24'h%06X: begin g = %-9s w = 16'h%04X; end   // 0x%06X"
                       % (a >> 1, g + ';', w, a))
    out.append('\t\t// registers the pad cave reads (also inside the Hall of Fame bar tiles)')
    for sig, a in REGS:
        out.append("\t\t24'h%06X: begin g = G_REG;    w = %s; end   // 0x%06X" % (a >> 1, sig, a))
    out.append('\t\t// arcade start stage (krikzz): 0x0001 = Block 888')
    out.append("\t\t24'h%06X: begin g = G_STAGE;  w = {8'h00, stage_byte}; end   // 0x%06X"
               % (STAGE_WORD >> 1, STAGE_WORD))
    return '\n'.join(out) + '\n'


def main():
    n = sum(len(words) for _, _, words in GROUPS) + len(REGS) + 1
    if '--write' in sys.argv:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'rtl', 'PAPRIUM',
                         'paprium_scum.sv')
        s = open(p, newline='').read()
        i = s.index('\n', s.index('// @@scum-table-begin')) + 1
        j = s.index('\t\t// @@scum-table-end')
        open(p, 'w', newline='\n').write(s[:i] + table() + s[j:])
        print('wrote %d words into %s' % (n, os.path.normpath(p)))
        return
    rom = open(paprium_data.rom_path(), 'rb').read()
    check(rom)
    if '--rom' in sys.argv:
        out = sys.argv[sys.argv.index('--rom') + 1]
        r = bytearray(rom)
        for _, _, words in GROUPS:
            for a, w in words:
                r[a:a + 2] = w.to_bytes(2, 'big')
        open(out, 'wb').write(r)
        print('static all-on copy (registers left 0xFFFF) ->', out)
    else:
        print('ok: %d words; the patch sites, the caves and the stage word match this table' % n)


if __name__ == '__main__':
    main()
