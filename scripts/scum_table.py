# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""The Scum! patch table - every word the cartridge substitutes on a ROM read when a
Scum! switch is on - and the generator for its case table in
rtl/PAPRIUM/paprium_scum.sv.

    python scripts/scum_table.py --write     regenerate the table in paprium_scum.sv (needs no ROM)
    python scripts/scum_table.py --check     check your ROM: the patch sites, the cave's space,
                                             the flip point and the stage word are what this
                                             table was made for
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

# The health cave lives in the zero padding before the 0x0C0000 animation container, which
# the game never reads (measured on GPGX routes, docs/SCUM.md). Nothing may go in
# 0x11C560-0x11C75F: that block is the Hall of Fame name-entry bar's tile data, which the
# game copies with a VDP DMA, and the core substitutes DMA reads too (the 0.2.6 known issue).
# 0.3.0 synth step: Arcade Mode is a virtual Grand Stick III in port 1 (paprium_pads /
# paprium_gs3), and the game runs its own arcade code from the stick's switches and coin.
# So the arcade nops (0x0B5AB8, 0x0B5ACC), the Multiplayer nop (0x0B5B1A), the pad hook
# (0x0B2392), the pad cave (0x0BF040) and its registers (0x0BF0C0), and the coin stub
# (0x0BF100) are gone, and scripts/scum_pad_cave.s with them: 122 words became 32
HEALTH_CAVE = 0x0BF000      # scum_health_cave.s
STAGE_WORD = 0x0B0A14       # arcade start stage (krikzz), 0x0001 = Block 888
# The flip point: the pad read's last instruction (movem.l -$c(a6),d2/a2-a3 at 0x0B238C;
# before the hook, while there was one). paprium_scum takes a new set of switches only on a
# served read of this word, where no cave can be running: the health cave is a leaf and the
# VBlank handlers are leaves. So a switch change can never land inside a patched instruction
# or inside a cave, even when the Pocket menu froze the 68000 in one
FLIP_POINT = 0x0B238C
HOF_BAR = (0x11C560, 0x11C760)

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

def _seq(base, words):
    return [(base + 2 * i, w) for i, w in enumerate(words)]


# (group, note, [(address, word)]). The RTL enables each group from its switch
GROUPS = [
    ('G_HEALTH', "players take no damage (jsr to the slot test); a player's throws do no damage to enemies (two nops)",
     _seq(0x02FAC4, [0x4EB9, HEALTH_CAVE >> 16, HEALTH_CAVE & 0xFFFF]) +
     _seq(0x030E8A, [0x4E71, 0x4E71]) +
     _seq(HEALTH_CAVE, HEALTH_CAVE_CODE)),
    ('G_PILLS', 'Blu pills are never spent: the decrement becomes nop',
     _seq(0x01A9FA, [0x4E71, 0x4E71])),
    ('G_LIVES', 'lives are never spent: the decrement becomes nop',
     _seq(0x02A4EE, [0x4E71])),
    # no arcade, Multiplayer or pad-hook group: the synth step's Grand Stick III (above)
    # no CPU MATE group: the partner runs on the cartridge MCU (docs/SCUM.md)
]
# the zero padding the cave space must be (checked word by word)
HEALTH_BLOCK = (HEALTH_CAVE, HEALTH_CAVE + 2 * len(HEALTH_CAVE_CODE))
# SHA-256 of the original words at every patch site outside the cave, in table order
# (since the 0.3.0 synth step: the eight words at 0x02FAC4, 0x030E8A, 0x01A9FA, 0x02A4EE; the digest of test build 4,
# the 0.3.0 hardware test build of the MCU fast path, covered
# its 14 words, these eight + the arcade, Multiplayer and hook sites)
SITES_SHA256 = 'c34466859043a650a8a4a76f4c20b9483e900221b03a87f1961cec1c5a07138a'
# SHA-256 of the original words of the flip-point instruction (three words at FLIP_POINT)
FLIP_SHA256 = 'fa2d669c7ce2fd0f655ca98d46d383f0443b12c5dc1be90542a28e353f5ba75a'


def _in(a, block):
    return block[0] <= a < block[1]


def site_words(rom):
    return b''.join(rom[a:a + 2] for _, _, words in GROUPS for a, _ in words
                    if not _in(a, HEALTH_BLOCK))


def scum_words():
    """Every address the RTL answers for (patch words and the stage word)."""
    return [a for _, _, words in GROUPS for a, _ in words] + [STAGE_WORD]


def check(rom):
    seen = set()
    for _, _, words in GROUPS:
        for a, _ in words:
            assert a % 2 == 0 and a not in seen, hex(a)
            seen.add(a)
    assert STAGE_WORD not in seen and FLIP_POINT not in seen
    # the Hall of Fame bar tiles: never again
    bad = [a for a in scum_words() + [FLIP_POINT] if _in(a, HOF_BAR)]
    assert not bad, 'Scum! word(s) inside the Hall of Fame bar tiles 0x11C560-0x11C75F: ' + \
        ' '.join('0x%06X' % a for a in bad)
    # every word the cave takes over must be zero padding
    for a in seen:
        if _in(a, HEALTH_BLOCK):
            assert rom[a:a + 2] == b'\x00\x00', 'cave word 0x%06X is not zero padding' % a
    assert rom[STAGE_WORD:STAGE_WORD + 2] == b'\x00\x01', 'stage word'
    assert hashlib.sha256(site_words(rom)).hexdigest() == SITES_SHA256, \
        'the patch sites do not hold the words this table was made for: a different ROM revision?'
    assert hashlib.sha256(rom[FLIP_POINT:FLIP_POINT + 6]).hexdigest() == FLIP_SHA256, \
        'the flip point is not the pad read\'s last instruction before the hook'
    return len(seen) + 1


def table():
    out = []
    for g, note, words in GROUPS:
        out.append('\t\t// %s' % note)
        for a, w in words:
            out.append("\t\t24'h%06X: begin g = %-9s w = 16'h%04X; end   // 0x%06X"
                       % (a >> 1, g + ';', w, a))
    out.append('\t\t// arcade start stage (krikzz): 0x0001 = Block 888')
    out.append("\t\t24'h%06X: begin g = G_STAGE;  w = {8'h00, stage_byte}; end   // 0x%06X"
               % (STAGE_WORD >> 1, STAGE_WORD))
    out.append('\t\t// the flip point (never substituted): new switches are taken on a served read here')
    out.append("\t\t24'h%06X: begin g = G_FLIP;   w = 16'h0000; end   // 0x%06X" % (FLIP_POINT >> 1, FLIP_POINT))
    return '\n'.join(out) + '\n'


def main():
    n = sum(len(words) for _, _, words in GROUPS) + 1
    if '--write' in sys.argv:
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'rtl', 'PAPRIUM',
                         'paprium_scum.sv')
        s = open(p, newline='').read()
        i = s.index('\n', s.index('// @@scum-table-begin')) + 1
        j = s.index('\t\t// @@scum-table-end')
        open(p, 'w', newline='\n').write(s[:i] + table() + s[j:])
        print('wrote %d words and the flip point into %s' % (n, os.path.normpath(p)))
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
        print('static all-on copy (registers left zero) ->', out)
    else:
        print('ok: %d words; the patch sites, the cave, the flip point and the stage word match this table; '
              'nothing in the Hall of Fame bar tiles' % n)


if __name__ == '__main__':
    main()
