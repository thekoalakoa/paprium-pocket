#!/usr/bin/env python3
"""Decode the Paprium command log captured by the paprium_cmdlog diagnostic build.

    python scripts/decode_cmdlog.py <file.log> [--all] [--sfx]

4096 big-endian 32-bit words written by rtl/PAPRIUM/paprium_cmd_log.sv, as 2047
two-word entries plus a header:

    word 2n    [31:16] the 16-bit command written to cart RAM 0x1FEA
               [15: 0] the sfx channel mask latched from 0x1E10
    word 2n+1  [31:16] the flags latched from 0x1E16
               [15: 0] the volume latched from 0x1E12
    word 4095  {0xC0DE, armed, frozen, 0, wr_idx}

Every Paprium command is a single 16-bit write to 0x1FEA, command in the high byte
and parameter in the low byte (GPGX paprium_w16 / paprium_cmd).

Only AUDIO commands are logged, plus 0x88/0xB0 which upstream records as muted in
this firmware. Sprite traffic would otherwise flush the ring many times over before
level 2, and this game has no saves - one capture must survive a full playthrough.

THE FLAGS MATTER. GPGX applies per-voice effects from them, and this port
implements only the pitch pair:

    0x8000  tiny pitch   31/32 speed      implemented
    0x2000  huge pitch   half speed       implemented
    0x4000  echo         166 ms, 33%      NOT IMPLEMENTED
    0x0100  amplify      x1.25            NOT IMPLEMENTED

A cue that sounds "close but not quite right" is most likely the correct sample
played without its echo. If the log shows echo requested, that is the explanation,
and it is ours to fix in RTL - no firmware work needed.

Two open cues:

    0x1C  boss / large-enemy death - plays an ordinary enemy's sound instead
    0x4A  punk-TV cue - the first TV (level 1) works, the second (level 2) is silent
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

MUTED = {0x88, 0xB0}
SOUND = {0x88, 0x8C, 0x8D, 0xC9, 0xCA, 0xD1, 0xD2, 0xD3, 0xD6}

FLAGS = [
    (0x8000, "pitch31/32", True),
    (0x4000, "ECHO",       False),
    (0x2000, "pitchHalf",  True),
    (0x0800, "f800",       True),
    (0x0400, "f400",       True),
    (0x0100, "AMPLIFY",    False),
]

CUES = ((0x1C, "boss / large-enemy death"), (0x4A, "punk-TV cue"))


def flag_names(f):
    out = []
    for bit, name, implemented in FLAGS:
        if f & bit:
            out.append(name if implemented else name + "(unimplemented)")
    return ",".join(out) if out else "-"


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    flags = {a for a in sys.argv[1:] if a.startswith('--')}
    if not args:
        print(__doc__)
        return 2

    data = open(args[0], 'rb').read()
    if len(data) < 16384:
        print("warning: %d bytes, expected 16384 - truncated capture?" % len(data),
              file=sys.stderr)
        data = data.ljust(16384, b'\x00')

    words = struct.unpack('>4096I', data[:16384])

    hdr = words[4095]
    magic, wr_idx = hdr >> 16, hdr & 0xFFF
    armed, frozen = bool(hdr & 0x8000), bool(hdr & 0x4000)
    if magic != 0xC0DE:
        print("header magic is %04X, expected C0DE." % magic, file=sys.stderr)
        print("Is this the diagnostic build, and did you EXIT the core rather "
              "than soft resetting?", file=sys.stderr)
        if magic == 0:
            return 1

    # Entries are two words, and wr_idx is where the NEXT one goes
    order = [(wr_idx + 2 * i) % 4094 for i in range(2047)]
    entries = [(i, words[i], words[i + 1]) for i in order if words[i] != 0]

    if '--sfx' in flags:
        entries = [e for e in entries if (e[1] >> 24) in SOUND]
    if '--all' not in flags:
        entries = entries[-60:]

    if frozen:
        state = "FROZEN - a cue was seen and its window is preserved"
    elif armed:
        state = "armed, not yet frozen - a cue was seen, tail still filling"
    else:
        state = ("NOT TRIGGERED - neither 0x1C nor 0x4A was requested at any"
                 " point in the run, so the ring rolled and this is only the tail")
    print("%d entries, newest at word %d" % (len(entries), (wr_idx - 2) % 4094))
    print("capture state: %s" % state)
    print()
    print("%-6s %-4s %-15s %-5s %-6s %-6s %-5s %s"
          % ("word", "cmd", "name", "parm", "mask", "flags", "vol", "effects"))

    plays = []
    for idx, w0, w1 in entries:
        cmd, param, mask = (w0 >> 24) & 0xFF, (w0 >> 16) & 0xFF, w0 & 0xFFFF
        fl, vol = (w1 >> 16) & 0xFFFF, w1 & 0xFFFF
        note = "  <- muted in this firmware" if cmd in MUTED else ""
        print("%-6d %02X   %-15s %02X    %04X   %04X   %04X  %s%s"
              % (idx, cmd, CMDS.get(cmd, "?"), param, mask, fl, vol,
                 flag_names(fl), note))
        if cmd in (0xD1, 0xD3):
            plays.append((param, mask, fl))

    print()
    if not plays:
        print("No sfx_play/sfx_loop here. If the event happened inside this window,")
        print("the cue never reached the mailbox - see the muted commands above.")
        return 0

    ids = [p for p, _, _ in plays]
    print("sfx ids requested: " + " ".join("%02X" % i for i in sorted(set(ids))))

    for sid, what in CUES:
        rows = [(m, f) for p, m, f in plays if p == sid]
        if not rows:
            continue
        print("\n0x%02X (%s) requested %d time(s)" % (sid, what, len(rows)))
        for m, f in rows:
            print("    mask %04X  flags %04X  %s" % (m, f, flag_names(f)))
        unimpl = [n for bit, n, impl in FLAGS
                  if not impl and any(f & bit for _, f in rows)]
        if unimpl:
            print("  Requested with %s, which this port does not implement."
                  % " and ".join(unimpl))
            print("  That alone would make the cue sound close but not right, and")
            print("  it is an RTL fix - no firmware work needed.")
        else:
            print("  The game DID ask for it here. If it was not heard, or sounded")
            print("  wrong, the loss is downstream - firmware or our RTL. Ours.")

    if not any(sid in ids for sid, _ in CUES):
        print()
        print("Neither 0x1C nor 0x4A appears in this window. If the events happened")
        print("inside it, the game never asked, so the divergence is in game state")
        print("or a muted command. Check the window covers them: %d entries."
              % len(entries))
    return 0


if __name__ == '__main__':
    sys.exit(main())
