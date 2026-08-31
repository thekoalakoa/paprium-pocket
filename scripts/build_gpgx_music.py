"""Build the music folder Genesis Plus GX wants for Paprium, from the same decoded
tracks the Pocket blob is built from.

    python scripts/build_gpgx_music.py <cdda-dir> <rom-dir> [--force]

GPGX's Paprium support substitutes the released soundtrack exactly as this port
does, but it reads MP3s from `<rom_dir>/paprium/` under 56 hardcoded names. Those
names are identical to the FILE entries in docs/paprium.cue apart from the
extension, so the cue gives the track-number mapping for free:

    cue:  FILE "02 90's Acid Dub Character Select.wav" / TRACK 01
    ->    cdda/track01.pcm  ->  <rom_dir>/paprium/02 90's Acid Dub Character Select.mp3

Why this matters beyond convenience: `paprium_load_mp3_boss()` in the core calls
mp3dec_load four times and checks NONE of the return values, unlike the main
loader. With the files missing, the boss buffers stay null and the mixer
dereferences them - the emulator crashes at the first boss spawn. Present files
are the fix.

Tracks the cue points at Blank.wav are written as silence, which is correct: the
cartridge's own music pointer table is null at those indices.

Requires ffmpeg on PATH. Input is headerless 48 kHz 16-bit stereo little-endian,
which is what scripts/build_cdda.sh emits.
"""
import os
import re
import subprocess
import sys

RATE = "48000"


def parse_cue(path):
    """[(track_number, filename), ...] in cue order."""
    out, pending = [], None
    for line in open(path, encoding='utf-8', errors='replace'):
        m = re.search(r'FILE\s+"([^"]+)"', line)
        if m:
            pending = m.group(1)
            continue
        m = re.search(r'TRACK\s+(\d+)', line)
        if m and pending is not None:
            out.append((int(m.group(1)), pending))
            pending = None
    return out


def required_names(paprium_h):
    """The MP3 filenames the core actually asks for."""
    if not os.path.exists(paprium_h):
        return None
    src = open(paprium_h, encoding='utf-8', errors='replace').read()
    return set(re.findall(r'sprintf\(name, "%s([^"]+\.mp3)"', src))


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    force = '--force' in sys.argv
    if len(args) < 2:
        raise SystemExit(__doc__)

    cdda, romdir = args[0], args[1]
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cue = os.path.join(here, 'docs', 'paprium.cue')
    outdir = os.path.join(romdir, 'paprium')
    os.makedirs(outdir, exist_ok=True)

    entries = parse_cue(cue)
    print("cue: %d tracks" % len(entries))
    print("out: %s" % outdir)
    print()

    wanted = required_names(os.path.join(
        here, '..', 'gpgx-build', 'core', 'cart_hw', 'paprium.h'))

    made, skipped, silent, missing = 0, 0, 0, []
    for num, fname in entries:
        target = os.path.join(outdir, os.path.splitext(fname)[0] + '.mp3')
        if os.path.exists(target) and not force:
            skipped += 1
            continue

        if fname.lower().startswith('blank'):
            # Correct as silence - the game has no music at these indices.
            cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i",
                   "anullsrc=r=44100:cl=stereo", "-t", "4", "-q:a", "9", target]
            silent += 1
        else:
            src = os.path.join(cdda, "track%02d.pcm" % num)
            if not os.path.exists(src):
                missing.append((num, fname))
                continue
            cmd = ["ffmpeg", "-y", "-f", "s16le", "-ar", RATE, "-ac", "2",
                   "-i", src, "-q:a", "4", target]
            made += 1

        r = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0:
            print("  FAILED  %s" % os.path.basename(target))
            continue
        print("  %-3s %s" % ("sil" if silent and fname.lower().startswith('blank') else num,
                             os.path.basename(target)))

    print()
    print("encoded %d, silence %d, already present %d" % (made, silent, skipped))
    if missing:
        print("MISSING SOURCE for %d:" % len(missing))
        for num, f in missing:
            print("  track%02d.pcm  (%s)" % (num, f))

    if wanted:
        have = {f for f in os.listdir(outdir) if f.lower().endswith('.mp3')}
        gap = sorted(wanted - have)
        print()
        print("core asks for %d files; %d present" % (len(wanted), len(wanted) - len(gap)))
        if gap:
            print("STILL MISSING - the core will fall back, and the four boss")
            print("tracks are the ones that crash it rather than fall back:")
            for f in gap:
                print("  %s" % f)
        else:
            print("every file the core asks for is present")


if __name__ == '__main__':
    main()
