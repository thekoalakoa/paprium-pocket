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
    0xDF: "sram_read",      0xE0: "sram_write",  0xEC: "VRAM_BUDGET",
    0xF7: "[ch7 snapshot]",   # synthetic, not a Paprium command
}

MUTED = {0x88, 0xB0}
SOUND = {0x88, 0x8C, 0x8D, 0xC9, 0xCA, 0xD1, 0xD2, 0xD3, 0xD6}

FLAGS = [
    (0x8000, "pitch31/32", True),
    (0x4000, "ECHO",       True),
    (0x2000, "pitchHalf",  True),
    (0x0800, "f800",       True),
    (0x0400, "f400",       True),
    (0x0100, "AMPLIFY?",   True),   # rendered as x1.25 gain per GPGX - see PORT_PLAN,
                                    # hardware suggests this reading is wrong
]

CUES = ((0x1C, "boss / large-enemy death"), (0x4A, "punk-TV cue"))


def flag_names(f):
    out = []
    for bit, name, implemented in FLAGS:
        if f & bit:
            out.append(name if implemented else name + "(unimplemented)")
    return ",".join(out) if out else "-"


# SDRAM WORKSPACE OFFSETS, not 68000 addresses. ppm_unpack writes to
# ppmio.sdram[dest_addr], and cmd_F2 passes the SAME value as both the unpack
# destination and FPGAIO->sdram_ptr - so dst and the stream pointer index one
# space. The 68000 window is simply "wherever sdram_ptr currently is".
#
# BEING IN THE STAGING RANGE IS NOT A COLLISION. 0x9000 + n*0x200 is exactly
# where blocks are supposed to land, cmd_F2 parks the pointer at 0x9000 on
# purpose, and the freeze probe proved the game wants the pointer left on the
# decoded bytes. A hit only matters if it is the WRONG KIND of write.
STAGE_LO   = 0x9000
BLOCK_SZ   = 0x200
CAP_SLOTS  = 49                       # the shipped budget cap
STAGE_CAP  = STAGE_LO + CAP_SLOTS * BLOCK_SZ - 1     # 0xF1FF


def classify(a):
    """-> (slot n or None, aligned?, verdict)"""
    if a < STAGE_LO:
        return None, None, ("private / decoder scratch - only interesting if "
                            "sdram_ptr is left here while the VDP still consumes")
    if a > STAGE_CAP:
        return None, None, "outside the %d-block arena - pointer moved off staging" % CAP_SLOTS
    off = a - STAGE_LO
    n, aligned = off // BLOCK_SZ, (off % BLOCK_SZ == 0)
    if not aligned:
        return n, False, "** UNALIGNED - can smear two blocks **"
    return n, True, "normal block unpack (rebuild of slot %d)" % n


def dest_report(entries):
    """0xDA/0xDB destination analysis.

    0xDA:  dst = cmd_args[0]                    bare 16-bit into a vu32
    0xDB:  dst = swapshorts(cmd_args_long[0])   32-bit, halves swapped

    swapshorts is (val >> 16) | (val << 16), so 0xDB is printed BOTH ways and the
    data picks the endianness - the right one clusters on 0x9xxx/0xAxxx/0xBxxx,
    the wrong one looks like noise.
    """
    rows = [(i, c, m, v) for i, c, m, v in entries if c in (0xDA, 0xDB)]
    if not rows:
        return

    print()
    print("%-6s %-5s %-11s %-8s %-4s %-6s %s"
          % ("word", "cmd", "raw", "dest", "n", "algn", "verdict"))
    unaligned, slots = 0, {}
    for i, c, m, v in rows:
        if c == 0xDA:
            cand = [("%04X" % m, m)]
        else:
            cand = [("%04X %04X" % (m, v), (m << 16) | v),
                    ("%04X %04X" % (m, v), (v << 16) | m)]
        for raw, d in cand:
            a = d & 0xFFFFF
            n, al, why = classify(a)
            print("%-6d %02X    %-11s %05X    %-4s %-6s %s"
                  % (i, c, raw, a, "-" if n is None else n,
                     "-" if al is None else ("yes" if al else "NO"), why))
            if n is not None and not al:
                unaligned += 1
            if n is not None and al:
                slots[n] = slots.get(n, 0) + 1

    print()
    if unaligned:
        print("  %d UNALIGNED destination(s) inside staging. That is the corruption"
              % unaligned)
        print("  path: an unpack straddling two 16-tile blocks smears patterns the")
        print("  VDP may still be showing. decoder_ram / a private unpack buffer is")
        print("  the next cut - NOT a bigger cache.")
    else:
        print("  Every in-range destination is 0x200-aligned - all of them read as")
        print("  'rebuild block n', which is the happy path. DEST COLLISION IS DEAD.")
        print("  The residual squares are then better explained by LRU pressure: 49")
        print("  blocks where the scene wants more. Next experiment is REMAP, not a")
        print("  bigger cap - slots 49-52 to block indices 50-53 (tiles 800-863,")
        print("  0x6400-0x6BFF) by dropping the two-range special case for x+1.")
    if slots:
        hot = sorted(slots.items(), key=lambda kv: -kv[1])[:6]
        print()
        print("  slots rebuilt most: " + ", ".join("n=%d x%d" % kv for kv in hot))
        print("  A slot rebuilt repeatedly while still on-screen would be the true")
        print("  collision case; that needs slot liveness, which the 68000-side")
        print("  logger cannot see. Correlate against when the squares appear.")


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

    # Sticky counters, deliberately not cleared by reset - a mid-run reset can
    # rewind the ring, and these survive it.
    w94, w93 = words[4094], words[4093]
    ec_cnt, ec_peak = w94 >> 16, w94 & 0xFFFF
    ec_last, any_cnt = w93 >> 16, w93 & 0xFFFF
    print("counters: mailbox commands seen=%d   0xEC seen=%d   peak=%d   last=%d"
          % (any_cnt, ec_cnt, ec_peak, ec_last))
    if any_cnt == 0:
        print("  Zero commands of ANY kind - the snoop never saw the mailbox.")
        print("  That is a wiring/build fault, not a fact about the game.")
    elif ec_cnt == 0:
        print("  The snoop was alive (%d commands) and 0xEC NEVER fired." % any_cnt)
        print("  So the VRAM budget is not renegotiated during play, and the 53")
        print("  clamp cannot be the elevator's cause. This line is closed.")
    elif ec_peak > 0x35:
        print("  PEAK %d EXCEEDS THE 0x35 CLAMP - the budget was truncated." % ec_peak)
    else:
        print("  Peak %d is inside the 53 clamp, never truncated." % ec_peak)
    print()

    w92 = words[4092]
    pitch_cnt, sfx_cnt = w92 >> 16, w92 & 0xFFFF
    if sfx_cnt or pitch_cnt:
        # In DEST_ONLY these are 0xDA/0xDB seen and unaligned-destination count.
        # A capture whose entries are 0xDA/0xDB is in that mode.
        dest_mode = any(((w >> 24) & 0xFF) in (0xDA, 0xDB)
                        for w in words[:4090:2] if w)
        if dest_mode:
            w91 = words[4091]
            db_bad, db_cnt = w91 >> 16, w91 & 0xFFFF
            print("0xDA/0xDB seen=%d" % sfx_cnt)
            print("  unaligned_da = %d   (0xDA only - no endian question; this alone"
                  % pitch_cnt)
            print("                       can decide the branch)")
            print("  0xDB seen    = %d,  unaligned_db = %d" % (db_cnt, db_bad))
            print("                       counted only on the reconstruction that")
            print("                       lands in 0x9000-0xF1FF; neither in range -> 0")
            if db_cnt == 0:
                print("  NOTE: 0xDB never fired. unaligned_db = 0 is UNINFORMATIVE,")
                print("        not clean - the branch rests on unaligned_da alone.")
            print()
            if pitch_cnt:
                print("  Off-grid unpacks DID happen. An unaligned write straddles two")
                print("  16-tile blocks and smears patterns the VDP may still show -")
                print("  buffer reuse. Next cut is a private unpack buffer")
                print("  (decoder_ram), NOT more cache slots.")
            elif db_bad:
                print("  0xDA is clean but 0xDB has %d off-grid destination(s). If that"
                      % db_bad)
                print("  survives discarding the wrong half-swap, the COPY path is dirty")
                print("  rather than the decode - look at 0xDB before adding cache.")
            else:
                print("  Every destination seen was 0x200-aligned%s."
                      % (" (0xDA only - 0xDB never fired)" if db_cnt == 0 else ""))
                print("  Destination collision is dead, and the residual squares point")
                print("  at LRU pressure - the remap experiment (slots 49-52 to tiles")
                print("  800-863), not a bigger cap.")
            print()
            hdr = words[4095]
            magic, wr_idx = hdr >> 16, hdr & 0xFFF
            armed, frozen = bool(hdr & 0x8000), bool(hdr & 0x4000)
            order = [(wr_idx + 2 * i) % 4094 for i in range(2047)]
            ent = [(i, words[i], words[i + 1]) for i in order if words[i] != 0]
            dest_report([(i, (w0 >> 24) & 0xFF, w0 & 0xFFFF, w1 & 0xFFFF)
                         for i, w0, w1 in ent if (w0 >> 24) in (0xDA, 0xDB)])
            return 0
        print("sfx commands (0xD1/0xD3) seen=%d   of which HALF-PITCH (0x2000)=%d"
              % (sfx_cnt, pitch_cnt))
        if pitch_cnt == 0:
            print("  The game NEVER asked for half pitch. So the deeper big-enemy")
            print("  death is not the 0x2000 flag, and our pitch path is not at")
            print("  fault - look at the sfx id and the table's own rate field.")
        else:
            print("  Half pitch WAS requested %d time(s). If the deep death still" % pitch_cnt)
            print("  sounds normal, the flag is reaching the mailbox and being lost")
            print("  downstream - ours to fix in RTL.")
        print()

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
        state = ("FROZEN - either the ring filled once (LOG_ALL) or a cue was"
                 " seen and its window preserved")
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
    snaps = []
    budgets = []
    for idx, w0, w1 in entries:
        cmd, param, mask = (w0 >> 24) & 0xFF, (w0 >> 16) & 0xFF, w0 & 0xFFFF
        fl, vol = (w1 >> 16) & 0xFFFF, w1 & 0xFFFF

        if cmd == 0xF7:
            empty, ch_vol, wr = param & 1, mask & 0x7FF, w1 & 0xFFFF
            snaps.append((idx, ch_vol, empty, wr))
            print("%-6d --   ch7 state       vol=%03X  fifo=%s  pcm_words=%d"
                  % (idx, ch_vol, "EMPTY" if empty else "fed ", wr))
            continue

        note = "  <- muted in this firmware" if cmd in MUTED else ""
        print("%-6d %02X   %-15s %02X    %04X   %04X   %04X  %s%s"
              % (idx, cmd, CMDS.get(cmd, "?"), param, mask, fl, vol,
                 flag_names(fl), note))
        if cmd == 0xEC:
            budgets.append((idx, vol))
        if cmd in (0xD1, 0xD3):
            plays.append((param, mask, fl))

    if budgets:
        # cmd_EC_vram_budget reads the block count from cmd_args[1] = 0x1E12,
        # which this logger records in the vol column.
        from collections import Counter
        vals = [b for _, b in budgets]
        print()
        print("VRAM block budget (0xEC), %d request(s):" % len(budgets))
        for v, n in sorted(Counter(vals).items()):
            over = "  <- OVER THE 0x35 CLAMP, silently truncated" if v > 0x35 else ""
            print("  %3d blocks (0x%02X)  x%d%s" % (v, v, n, over))
        hi = max(vals)
        print()
        if hi > 0x35:
            print("  The game asked for %d blocks and mame.c gave it 53, so %d blocks"
                  % (hi, hi - 0x35))
            print("  never got resident tiles. That is exactly the reported symptom:")
            print("  wrong tiles as background blocks, sprites drawing stale frames.")
            print()
            print("  53 is not a safety margin - it is precisely VRAM under mega-ppm's")
            print("  slot mapping ((x + (x<=0x30 ? 1 : 0x4b)) << 4):")
            print("    slots 0-48  -> tiles 16-799")
            print("    slots 49-52 -> tiles 1984-2047, ending at the last tile")
            print("  So the number cannot just be raised. Asking for more than 53")
            print("  means the game expects a different VRAM arrangement than")
            print("  mega-ppm reconstructs - a denser or variable-size allocator.")
            print("  THAT mismatch is the bug, not the constant.")
        else:
            print("  Peak was %d blocks, inside the 53 clamp - never truncated in this"
                  % hi)
            print("  run, so the clamp is NOT the cause. Confirm the capture actually")
            print("  reached the elevator before concluding; a short run proves nothing.")

    dest_report([(i, (w0 >> 24) & 0xFF, w0 & 0xFFFF, w1 & 0xFFFF)
                 for i, w0, w1 in entries if (w0 >> 24) in (0xDA, 0xDB)])

    if snaps:
        vols = [v for _, v, _, _ in snaps]
        starved = sum(1 for _, _, e, _ in snaps if e)
        first_wr, last_wr = snaps[0][3], snaps[-1][3]
        print()
        print("channel 7 (the punk-TV cue lands here):")
        print("  %d snapshots, volume %03X..%03X, FIFO seen empty %d time(s)"
              % (len(snaps), min(vols), max(vols), starved))
        print("  PCM words pushed across the window: %d" % (last_wr - first_wr))
        if max(vols) == 0:
            print("  Volume register NEVER left zero - the ramp is not reaching")
            print("  the hardware. Firmware or the vol write path, not the game.")
        elif last_wr == first_wr:
            print("  Volume took the ramp but NO PCM arrived - the channel was")
            print("  configured and never fed. The sample stopped and did not loop.")
        else:
            print("  Volume took the ramp AND samples kept arriving - the channel")
            print("  was playing, so look at the mixer path rather than the source.")

    print()
    if not plays:
        print("No sfx_play/sfx_loop here. If the event happened inside this window,")
        print("the cue never reached the mailbox - see the muted commands above.")
        return 0

    ids = [p for p, _, _ in plays]
    print("sfx ids requested: " + " ".join("%02X" % i for i in sorted(set(ids))))

    # With LOG_ALL the useful question is usually "which commands appear at all",
    # so summarise the distribution and flag the ones this firmware mutes.
    from collections import Counter
    dist = Counter(((w0 >> 24) & 0xFF) for _, w0, _ in entries if (w0 >> 24) != 0xF7)
    if len(dist) > 10:
        print()
        print("command distribution (LOG_ALL capture):")
        for c, n in dist.most_common():
            mark = "  <- MUTED in this firmware" if c in MUTED else ""
            print("  %02X %-16s %5d%s" % (c, CMDS.get(c, "?"), n, mark))

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
