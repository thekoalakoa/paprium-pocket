"""Convert an OLD raw-PCM paprium.pcm into the IMA ADPCM (PPAD) blob.

    python scripts/convert_cdda_to_adpcm.py <old paprium.pcm> <new paprium.pcm>

WHY THIS EXISTS. The blob format changed to IMA ADPCM, and the core now refuses
a blob without the PPAD marker rather than streaming it as noise. Rebuilding
from scratch means re-ripping the soundtrack and re-running ffmpeg. But the old
blob is already 48 kHz stereo s16 with a track table, so it carries everything
the packer needs - no source files required, and no quality lost beyond the one
ADPCM pass that the rebuilt blob would have had anyway.

OLD FORMAT (what this reads):

    0x000  64 entries x 8 bytes: u32 start offset, u32 length, little-endian
    0x200  track data, concatenated, raw s16 stereo 48 kHz

NEW FORMAT (what this writes) is documented in build_cdda_adpcm.py, whose
encoder and padding rules this reuses verbatim - so a blob converted here is
byte-identical to one packed from the same audio.

About 17 minutes for a full 2.09 GB blob, producing about 535 MB.
"""
import os
import struct
import sys
import importlib.util

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location(
    'packer', os.path.join(HERE, 'build_cdda_adpcm.py'))
packer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packer)

NT = 64
BLK = 505


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = sys.argv[1], sys.argv[2]

    fin = open(src, 'rb')
    head = fin.read(0x200)
    if len(head) < 0x200:
        print("error: %s is too small to be a raw blob" % src)
        return 2
    if head[:4] == b'PPAD':
        print("error: %s is already a PPAD blob - nothing to convert" % src)
        return 2

    old = [struct.unpack_from('<II', head, t * 8) for t in range(NT)]
    size = os.path.getsize(src)
    accounted = sum(l for _, l in old) + 0x200
    if accounted != size:
        # Not fatal - a truncated or hand-edited blob still converts what it has -
        # but say so, because a silent partial convert is worse than a warning.
        print("warning: table accounts for %d bytes, file is %d" % (accounted, size))

    blobs = {}
    total_in = 0
    for t in range(NT):
        off, ln = old[t]
        if not ln:
            continue
        if off + ln > size:
            print("track %02d  SKIPPED - runs past end of file" % t)
            continue
        fin.seek(off)
        pcm = fin.read(ln)
        adp, ns = packer.encode_track(pcm, BLK)
        # same chunk padding as the packer, for the same reason: the fetch reads
        # fixed 4096-byte chunks and must never straddle into the next track
        if len(adp) % packer.CHUNK:
            adp += packer.SILENCE_FRAME * (
                (packer.CHUNK - len(adp) % packer.CHUNK) // 512)
        blobs[t] = (adp, ns)
        total_in += ln
        print("track %02d  %10d -> %9d bytes  (%.2fx)  %6.1f s"
              % (t, ln, len(adp), ln / max(len(adp), 1), ns / 48000.0))
        sys.stdout.flush()
    fin.close()

    hdr_len = 0x18 + NT * 16
    data_off = (hdr_len + 4095) & ~4095
    table = [(0, 0, 0)] * NT
    off = data_off
    for t in sorted(blobs):
        adp, ns = blobs[t]
        table[t] = (off, len(adp), ns)
        off += len(adp)

    with open(dst, 'wb') as f:
        f.write(b'PPAD' + struct.pack('<IIIII', 1, 48000, 2, BLK, NT))
        for t in range(NT):
            o, l, ns = table[t]
            f.write(struct.pack('<QII', o, l, ns))
        f.write(b'\0' * (data_off - f.tell()))
        for t in sorted(blobs):
            f.write(blobs[t][0])

    out = os.path.getsize(dst)
    print("\n%s  %.1f MB  (from %.1f MB, %.2fx)  %d tracks"
          % (dst, out / 2**20, total_in / 2**20,
             total_in / max(out, 1), len(blobs)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
