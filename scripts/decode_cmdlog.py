#!/usr/bin/env python3
"""Decode the Paprium command log captured by the paprium_cmdlog diagnostic build.

    python scripts/decode_cmdlog.py <file.log> [--all] [--sfx]

The log is 1024 big-endian 32-bit words written by rtl/PAPRIUM/paprium_cmd_log.sv:

    word 0..1022  [31:16] the 16-bit command written to cart RAM 0x1FEA
                  [15: 0] the sfx channel mask latched from 0x1E10
    word 1023     {0xC0DE, wr_idx} - where the newest entry landed

Every Paprium command is a single 16-bit write to 0x1FEA with the command in the
high byte and its parameter in the low byte (GPGX paprium_w16 / paprium_cmd).

Default output is the last 60 entries, oldest first, which is what you want after
killing a boss. --all prints the whole ring; --sfx prints only sound commands.

Two open cues, both reported on:

    0x1C  boss / large-enemy death - plays an ordinary enemy's sound instead
    0x4A  punk-TV cue - the FIRST TV in the level works, the SECOND is silent

The two TVs are in DIFFERENT levels - first in level 1, second in level 2 - so a
channel leaking across them is implausible: a level transition sits between, and
0x4A is only 4.99 s against minutes of play. Read it as a level-2 difference, not
a stuck resource.

The ring holds 1023 commands and a level fires far more than that, so a capture
cannot span both TVs. Capture ONE window instead: reach the second TV, then exit
the core promptly so its request is still in the ring.

    0x4A present in a window taken at the second TV -> the game asked and the
        sound was lost downstream. Ours, and fixable.
    0x4A absent  -> the game never asked in level 2; the divergence is in game
        state or in a command this firmware mutes, not in the audio path.
"""
import struct
import sys

CMDS = {
    0x84: "mapper",         0x88: "audio_setting",  0x8C: "music",
    0x8D: "music_setting",  0xAD: "sprite",         0xAE: "sprite_start",
    0xAF: "sprite_stop",    0xB0: "sprite_init",    0xB1: "sprite_pause",
    0xC6: "boot",           0xC9: "music_volume",   0xCA: "sfx_volume",
    0xD1: "SFX_PLAY",       0xD2: "sfx_off",        0xD3: "SFX_LOOP",
    0xD6: "music_special",  0xDA: "decoder",        0xDB: "decoder_copy",
    0xDF: "sram_read",      0xE0: "sram_write",
}

# Commands MisterPezz82's KNOWN_ISSUES.md records as muted in this firmware build
MUTED = {0x88, 0xB0}

SOUND = {0x88, 0x8C, 0x8D, 0xC9, 0xCA, 0xD1, 0xD2, 0xD3, 0xD6}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = {a for a in sys.argv[1:] if a.startswith('--')}
    if not args:
        print(__doc__)
        return 2

    data = open(args[0], 'rb').read()
    if len(data) < 4096:
        print("warning: %d bytes, expected 4096 - truncated capture?" % len(data),
              file=sys.stderr)
        data = data.ljust(4096, b'\0')

    words = struct.unpack('>1024I', data[:4096])

    hdr = words[1023]
    magic, wr_idx = hdr >> 16, hdr & 0x3FF
    if magic != 0xC0DE:
        print("header magic is %04X, expected C0DE." % magic, file=sys.stderr)
        print("The core may not have written this slot - is this the diagnostic "
              "build, and did you EXIT the core rather than soft resetting?",
              file=sys.stderr)
        if magic == 0x0000:
            return 1

    # wr_idx is where the NEXT entry goes, so the ring is oldest-first from there
    order = [(wr_idx + i) % 1023 for i in range(1023)]
    entries = [(i, words[i]) for i in order if words[i] != 0]

    if '--sfx' in flags:
        entries = [(i, w) for i, w in entries if (w >> 24) in SOUND]
    if '--all' not in flags:
        entries = entries[-60:]

    print("%d entries, newest at word %d\n" % (len(entries), (wr_idx - 1) % 1023))
    print("%-6s %-6s %-16s %-6s %s" % ("word", "cmd", "name", "param", "chanmask"))

    saw_play = []
    for idx, w in entries:
        cmd, param, mask = (w >> 24) & 0xFF, (w >> 16) & 0xFF, w & 0xFFFF
        name = CMDS.get(cmd, "?")
        note = "  <- muted in this firmware" if cmd in MUTED else ""
        print("%-6d %02X     %-16s %02X     %04X%s" % (idx, cmd, name, param, mask, note))
        if cmd in (0xD1, 0xD3):
            saw_play.append((cmd, param, mask))

    print()
    if not saw_play:
        print("No sfx_play/sfx_loop in this window. If the event happened inside it,")
        print("the cue never reached the mailbox - look at the muted commands above.")
        return 0

    ids = [p for _, p, _ in saw_play]
    print("sfx ids requested: " + " ".join("%02X" % i for i in sorted(set(ids))))

    for sid, what in ((0x1C, "boss / large-enemy death"), (0x4A, "punk-TV cue")):
        n = ids.count(sid)
        if not n:
            continue
        masks = ["%04X" % m for c, p, m in saw_play if p == sid]
        print()
        print("0x%02X (%s) requested %d time(s), mask(s): %s"
              % (sid, what, n, " ".join(masks)))
        print("  The game DID ask for it in this window. If it was not heard, the")
        print("  sound was lost downstream - in the firmware or our RTL. Ours.")
        if len(set(masks)) > 1:
            print("  NOTE: the channel masks differ between requests - sfx_play may")
            print("  only allocate within the mask.")

    if 0x1C not in ids and 0x4A not in ids:
        print()
        print("Neither 0x1C nor 0x4A appears in this window. If the event happened")
        print("inside it, the game never asked - so the divergence is in game state")
        print("or a muted command, not in the audio path. Check the window really")
        print("does cover the event: %d entries, and a level can overflow the ring."
              % len(entries))
    return 0


if __name__ == '__main__':
    sys.exit(main())
