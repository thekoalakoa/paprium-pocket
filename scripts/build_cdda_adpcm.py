#!/usr/bin/env python3
"""Pack per-track PCM into the IMA ADPCM blob (`PPAD`) the core streams.

    python scripts/build_cdda_adpcm.py <pcm-dir> <output.adp> [--block=505]

<pcm-dir> holds track01.pcm .. track62.pcm from build_cdda.sh - headerless
48 kHz stereo 16-bit little-endian.

WHY: the raw blob is 2.09 GB, which makes the music impractical to distribute or
rebuild. IMA ADPCM is a flat 4 bits per sample against 16, so 4:1 with no content
dependence: about 535 MB. Nothing else changes - the play path stays a 48 kHz
stereo 16-bit consumer, and only the file format moves.

FORMAT. Deliberately NOT the old layout, so a stale `paprium.pcm` cannot be
mistaken for a valid file - the magic makes it fail loudly instead of playing
noise:

    0x00  char[4]  "PPAD"
    0x04  u32      version = 1
    0x08  u32      sample rate = 48000
    0x0C  u32      channels = 2
    0x10  u32      block_samples   samples per channel per IMA block
    0x14  u32      ntracks = 64
    0x18  ntracks x 16 bytes:
              u64  byte offset of the track's first block
              u32  adpcm byte length
              u32  pcm sample count per channel
    ...   padded to a 4096-byte boundary
    data  IMA blocks, each self-contained

EVERY BLOCK IS SELF-CONTAINED - it carries its own predictor and step index per
channel, so a seek only has to land on a block boundary. That matters because the
core seeks by byte offset into one data slot; mid-block resume would need decoder
state the fetch path has no way to reconstruct.

Block layout is MS-IMA (WAV-style), per block:
    per channel: s16 predictor, u8 step index, u8 reserved   (4 bytes)
    then interleaved nibble groups, 4 bytes per channel at a time

`block_samples - 1` MUST be a multiple of 8. The first sample of each block lives
in the header as the seed predictor and is not encoded; the remainder are encoded
in groups of 8 per channel (4 bytes). Getting this wrong produces one extra sample
per block, which decodes at full amplitude but drifts a sample per block against
the source - it sounds plausible and measures as noise.
"""
import os, struct, sys

STEP = [
    7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,
    88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,
    544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,
    2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,
    10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,
    32767]
INDEX = [-1,-1,-1,-1,2,4,6,8,-1,-1,-1,-1,2,4,6,8]


def clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


class Enc:
    """One channel of IMA state."""
    def __init__(self):
        self.pred = 0
        self.idx = 0

    def encode(self, sample):
        step = STEP[self.idx]
        diff = sample - self.pred
        code = 0
        if diff < 0:
            code = 8
            diff = -diff
        delta = 0
        tmp = step
        for bit in (4, 2, 1):
            if diff >= tmp:
                code |= bit
                diff -= tmp
                delta += tmp
            tmp >>= 1
        delta += step >> 3
        self.pred = clamp(self.pred - delta if code & 8 else self.pred + delta,
                          -32768, 32767)
        self.idx = clamp(self.idx + INDEX[code], 0, 88)
        return code


# The fetch reads in fixed 4096-byte chunks = 8 frames; see paprium_cdda_fetch.sv.
CHUNK = 4096
# pred 0, index 0, then 504 zero nibble-bytes. IMA nibble 0 gives diff = step>>3,
# which is 0 at step 7, so the predictor never moves: exact digital silence.
SILENCE_FRAME = struct.pack('<hBB', 0, 0, 0) * 2 + b'\0' * 504


def encode_track(pcm, block_samples):
    """pcm: bytes of interleaved s16 stereo. -> (adpcm bytes, sample count)"""
    n = len(pcm) // 4                       # frames (one sample per channel)
    out = bytearray()
    enc = (Enc(), Enc())
    pos = 0
    while pos < n:
        take = min(block_samples, n - pos)
        # a block starts by SEEDING the state from the first sample of each
        # channel, which is what makes it self-contained and seekable
        hdr = bytearray()
        first = struct.unpack_from('<2h', pcm, pos * 4)
        for c in (0, 1):
            enc[c].pred = first[c]
            hdr += struct.pack('<hBB', enc[c].pred, enc[c].idx, 0)
        body = bytearray()
        # samples 1..block_samples-1, in groups of 8 per channel (4 bytes each).
        # The bound is block_samples, NOT take: every block must come out exactly
        # 512 bytes. The decoder frames the stream by counting bytes, so a short
        # final block would slide every following frame and decode as noise. The
        # j < take guard below already substitutes the held predictor, so the pad
        # is a flat continuation, and pcm_samples records where the real audio ends.
        i = 1
        while i < block_samples:
            for c in (0, 1):
                nib = []
                for k in range(8):
                    j = i + k
                    # Past the end of the source, encode toward ZERO rather than
                    # holding the last predictor. A held predictor leaves a DC step
                    # for the rest of the block and then a cliff down to the silence
                    # frames, which is an audible thump at every track end.
                    s = struct.unpack_from('<h', pcm, (pos + j) * 4 + c * 2)[0] \
                        if j < take else 0
                    nib.append(enc[c].encode(s))
                for k in range(0, 8, 2):
                    body.append(nib[k] | (nib[k + 1] << 4))
            i += 8
        out += hdr + body
        pos += take
    return bytes(out), n


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    blk = 505          # 1 + 8*63; see the block_samples note above
    for a in sys.argv[1:]:
        if a.startswith('--block'):
            blk = int(a.split('=')[1]) if '=' in a else 505
    if (blk - 1) % 8:
        print("error: block_samples-1 must be a multiple of 8 (got %d)" % blk)
        return 2
    if len(args) != 2:
        print(__doc__)
        return 2
    src, dst = args

    NT = 64
    table = [(0, 0, 0)] * NT
    blobs = {}
    total_in = 0
    for t in range(1, NT):
        p = os.path.join(src, "track%02d.pcm" % t)
        if not os.path.isfile(p):
            continue
        pcm = open(p, 'rb').read()
        total_in += len(pcm)
        adp, ns = encode_track(pcm, blk)
        blobs[t] = (adp, ns)
        print("  track%02d  %8d -> %8d bytes  (%.2fx)  %6.1f s"
              % (t, len(pcm), len(adp), len(pcm) / max(len(adp), 1), ns / 48000.0))

    hdr_len = 0x18 + NT * 16
    data_off = (hdr_len + 4095) & ~4095
    off = data_off
    for t in sorted(blobs):
        adp, ns = blobs[t]
        # the true sample count, so the player stops on the last REAL sample -
        # the final block pads to a multiple of 8 and would otherwise emit a few
        # stray samples at every track end
        # Pad to a whole CHUNK so the fetch's fixed 4096-byte reads never straddle
        # into the NEXT track's data - that is what would play as noise. The pad is
        # whole silence frames (pred 0, index 0, all-zero nibbles decodes to a flat
        # zero), so overrunning into it is silent rather than wrong.
        if len(adp) % CHUNK:
            adp = adp + SILENCE_FRAME * ((CHUNK - len(adp) % CHUNK) // 512)
            blobs[t] = (adp, ns)     # the PADDED bytes are what gets written
        table[t] = (off, len(adp), ns)
        off += len(adp)

    with open(dst, 'wb') as f:
        f.write(b'PPAD' + struct.pack('<IIIII', 1, 48000, 2, blk, NT))
        for t in range(NT):
            o, l, ns = table[t]
            f.write(struct.pack('<QII', o, l, ns))
        f.write(b'\0' * (data_off - f.tell()))
        for t in sorted(blobs):
            f.write(blobs[t][0])

    out = os.path.getsize(dst)
    print("\n%s  %.1f MB  (from %.1f MB, %.2fx)"
          % (dst, out / 2**20, total_in / 2**20, total_in / max(out, 1)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
