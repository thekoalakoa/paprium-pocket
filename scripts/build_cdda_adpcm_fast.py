#!/usr/bin/env python3
"""Parallel drop-in for build_cdda_adpcm.py. Same PPAD blob, byte for byte.

    python scripts/build_cdda_adpcm_fast.py <pcm-dir> <output.adp> [--block=505] [--jobs=N]
    python scripts/build_cdda_adpcm_fast.py --selftest

<pcm-dir> holds track01.pcm .. track62.pcm from build_cdda.sh - headerless
48 kHz stereo 16-bit little-endian - exactly as for the reference packer.

WHY: the reference packer visits every sample in pure Python on a single core,
so packing the full soundtrack (about a billion channel-samples) takes ten-plus
minutes while the other cores idle. Nothing about the format needs that:

  * TRACKS are independent. Each starts from fresh encoder state and the blob is
    just the tracks laid end to end behind a table, so they can be encoded in any
    order, on any core, and stitched at the end.

  * The two CHANNELS of a track are independent too. IMA keeps a separate
    predictor and step index per channel, and the MS-IMA block layout is a plain
    alternation of 4-byte units - L header, R header, L nibble group, R nibble
    group, ... - so a finished track is the 4-byte interleave of two per-channel
    streams. That doubles the number of jobs and halves the longest one.

So this packer encodes every (track, channel) pair in its own process, longest
first, interleaves the halves, and then writes the header, table and padding the
same way the reference does. The per-sample arithmetic is the reference
encoder's, inlined into one tight loop rather than a method call per sample,
which is worth a few times on its own - it beats the reference even at --jobs=1.

ANY NUMBER OF CORES. The bytes written never depend on how many processes ran
or which finished first: each job is deterministic and the blob is assembled in
track order afterwards, so --jobs=1 on a single core and --jobs=64 on a
workstation produce the same file. The default is one process per CPU this
process may use. Memory is the only thing that scales with the job count: a
worker holds one channel of one track (about 50 MB for the longest) and the
parent holds the encoded streams (about 540 MB for the full soundtrack). On a
machine with many cores and little RAM, lower --jobs.

`--selftest` checks the inlined encoder against the reference implementation in
build_cdda_adpcm.py (same directory) on synthetic tracks covering the awkward
cases - shorter than one block, exactly one block, a partial final block,
full-scale steps that hit the predictor clamps, digital silence, an empty
track - and then packs a small track set end to end through both scripts.
"""
import multiprocessing
import os
import struct
import sys
import time
from array import array

STEP = [
    7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,
    88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,
    544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,
    2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,
    10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,
    32767]
INDEX = [-1,-1,-1,-1,2,4,6,8,-1,-1,-1,-1,2,4,6,8]

# Identical to the reference: the fetch reads fixed 4096-byte chunks, and a
# silence frame is pred 0, index 0, all-zero nibbles.
CHUNK = 4096
SILENCE_FRAME = struct.pack('<hBB', 0, 0, 0) * 2 + b'\0' * 504
NT = 64


def default_jobs():
    """One process per CPU this process may actually use (affinity and cgroup
    limits included where Python can see them), never fewer than one."""
    n = None
    usable = getattr(os, 'process_cpu_count', None)      # Python 3.13+
    if usable is not None:
        n = usable()
    if not n:
        n = os.cpu_count()
    return n or 1


def encode_channel(ch, blk):
    """Encode ONE channel of a track.

    ch:  array('h') of that channel's samples, host byte order.
    blk: samples per block (block_samples); blk - 1 must be a multiple of 8.

    Returns the channel's half of the MS-IMA stream: per block, 4 header bytes
    (s16 seed predictor, u8 step index, u8 zero) followed by (blk-1)/2 nibble
    bytes. Interleaving two of these in 4-byte units gives the reference's block.

    Same rules as the reference: the predictor is re-seeded from the block's
    first sample (which is why blocks are seekable), the step index carries
    across blocks, and samples past the end of the source encode toward zero
    rather than holding the last value.
    """
    n = len(ch)
    out = bytearray()
    ap = out.append
    step_table = STEP
    index_table = INDEX
    idx = 0
    for pos in range(0, n, blk):
        pred = ch[pos]                       # seed: first REAL sample of the block
        ap(pred & 0xFF)
        ap((pred >> 8) & 0xFF)
        ap(idx)
        ap(0)
        seg = ch[pos + 1:pos + blk]          # the blk-1 encoded samples
        if len(seg) != blk - 1:
            # only the final, partial block: past the end of the source the
            # reference encodes toward zero rather than holding the last value
            seg = seg + array('h', bytes(2 * (blk - 1 - len(seg))))
        it = iter(seg)
        for s0, s1 in zip(it, it):           # two samples -> one nibble byte
            # ---- low nibble ----
            step = step_table[idx]
            diff = s0 - pred
            if diff < 0:
                code = 8
                diff = -diff
            else:
                code = 0
            delta = step >> 3
            if diff >= step:
                code |= 4
                diff -= step
                delta += step
            step >>= 1
            if diff >= step:
                code |= 2
                diff -= step
                delta += step
            step >>= 1
            if diff >= step:
                code |= 1
                delta += step
            if code & 8:
                pred -= delta
                if pred < -32768:
                    pred = -32768
            else:
                pred += delta
                if pred > 32767:
                    pred = 32767
            idx += index_table[code]
            if idx < 0:
                idx = 0
            elif idx > 88:
                idx = 88
            lo = code
            # ---- high nibble ----
            step = step_table[idx]
            diff = s1 - pred
            if diff < 0:
                code = 8
                diff = -diff
            else:
                code = 0
            delta = step >> 3
            if diff >= step:
                code |= 4
                diff -= step
                delta += step
            step >>= 1
            if diff >= step:
                code |= 2
                diff -= step
                delta += step
            step >>= 1
            if diff >= step:
                code |= 1
                delta += step
            if code & 8:
                pred -= delta
                if pred < -32768:
                    pred = -32768
            else:
                pred += delta
                if pred > 32767:
                    pred = 32767
            idx += index_table[code]
            if idx < 0:
                idx = 0
            elif idx > 88:
                idx = 88
            ap(lo | (code << 4))
    return bytes(out)


def channel_of(pcm, chan):
    """One channel of interleaved s16le stereo bytes as an array('h') in host
    byte order, plus the frame count. Copies just that channel out once, so a
    worker holds about a quarter of its file rather than several copies of it."""
    frames = len(pcm) // 4
    ch = array('h')
    if frames:
        ch.frombytes(memoryview(pcm)[:frames * 4].cast('h')[chan::2].tobytes())
    if sys.byteorder != 'little':
        ch.byteswap()
    return frames, ch


def interleave(left, right):
    """Two per-channel streams (256 bytes per block) -> one MS-IMA track stream
    (512 bytes per block): alternate 4-byte units, left first."""
    if len(left) != len(right):
        raise ValueError("channel streams differ in length")
    out = bytearray(len(left) * 2)
    for k in range(4):
        out[k::8] = left[k::4]
        out[4 + k::8] = right[k::4]
    return bytes(out)


def encode_track_fast(pcm, blk):
    """Single-process equivalent of the reference encode_track(): used by the
    self-test, and handy for anyone who wants the fast encoder without a pool."""
    frames, left = channel_of(pcm, 0)
    _, right = channel_of(pcm, 1)
    return interleave(encode_channel(left, blk), encode_channel(right, blk)), frames


def _encode_job(args):
    """Pool worker: one channel of one track. Reads the file itself so only the
    small argument tuple crosses the process boundary on the way in."""
    path, track, chan, blk = args
    with open(path, 'rb') as f:
        pcm = f.read()
    size = len(pcm)
    frames, ch = channel_of(pcm, chan)
    del pcm
    return track, chan, frames, size, encode_channel(ch, blk)


def write_blob(dst, halves, sizes, blk, quiet=False):
    """Header, table, padding and data laid out exactly as the reference writes
    them, streamed one track at a time so nothing is held twice.

    halves: {(track, chan): (frames, stream)} - consumed as it goes.
    sizes:  {track: source byte length}, only for the per-track report."""
    order = sorted({t for t, _ in halves})
    table = [(0, 0, 0)] * NT
    hdr_len = 0x18 + NT * 16
    data_off = (hdr_len + 4095) & ~4095
    off = data_off
    for t in order:
        frames, left = halves[(t, 0)]
        n = len(left) * 2                    # the interleaved track
        # every track is padded to a whole fetch chunk with silence frames, so
        # a fixed 4096-byte read can never run into the next track's data
        n_padded = n + (CHUNK - n % CHUNK if n % CHUNK else 0)
        table[t] = (off, n_padded, frames)
        off += n_padded
    with open(dst, 'wb') as f:
        f.write(b'PPAD' + struct.pack('<IIIII', 1, 48000, 2, blk, NT))
        for t in range(NT):
            o, l, ns = table[t]
            f.write(struct.pack('<QII', o, l, ns))
        f.write(b'\0' * (data_off - f.tell()))
        for t in order:
            n_l, left = halves.pop((t, 0))
            n_r, right = halves.pop((t, 1))
            if n_l != n_r:
                raise RuntimeError("track %02d: channel frame counts differ" % t)
            adp = interleave(left, right)
            del left, right
            f.write(adp)
            if len(adp) % CHUNK:
                f.write(SILENCE_FRAME * ((CHUNK - len(adp) % CHUNK) // 512))
            if not quiet:
                print("  track%02d  %8d -> %8d bytes  (%.2fx)  %6.1f s"
                      % (t, sizes[t], len(adp), sizes[t] / max(len(adp), 1),
                         n_l / 48000.0))
            del adp


def pack(src, dst, blk=505, jobs=None, quiet=False):
    """Pack every track??.pcm in src into the PPAD blob dst.
    Returns (tracks, jobs, processes, encode seconds, source bytes)."""
    tracks = []
    for t in range(1, NT):
        p = os.path.join(src, "track%02d.pcm" % t)
        if os.path.isfile(p):
            tracks.append((t, p, os.path.getsize(p)))
    if not tracks:
        raise SystemExit("error: no track??.pcm files in %s" % src)

    # Longest first: the longest single job bounds the wall time, so it must not
    # be the one left running alone at the end.
    todo = [(p, t, c, blk)
            for t, p, _ in sorted(tracks, key=lambda x: -x[2]) for c in (0, 1)]
    procs = max(1, min(jobs or default_jobs(), len(todo)))

    t0 = time.time()
    halves, sizes = {}, {}
    with multiprocessing.Pool(procs) as pool:
        for t, c, frames, size, stream in pool.imap_unordered(_encode_job, todo, chunksize=1):
            halves[(t, c)] = (frames, stream)
            sizes[t] = size
    t_encode = time.time() - t0

    write_blob(dst, halves, sizes, blk, quiet)
    return len(tracks), len(todo), procs, t_encode, sum(sizes.values())


def selftest():
    import contextlib, io, math, random, shutil, tempfile
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    try:
        import build_cdda_adpcm as ref
    except ImportError:
        print("self-test needs the reference build_cdda_adpcm.py next to this script, in %s" % here)
        return 2

    rng = random.Random(1234)
    blk = 505

    def pcm(frames):
        return b''.join(struct.pack('<hh', l, r) for l, r in frames)

    def noise(n):
        return pcm([(rng.randint(-32768, 32767), rng.randint(-32768, 32767)) for _ in range(n)])

    cases = {
        'noise, 3 blocks + partial': noise(3 * blk + 123),
        'sine-ish, exactly 4 blocks': pcm([(int(12000 * math.sin(i / 7.0)),
                                            int(9000 * math.sin(i / 11.0 + 1)))
                                           for i in range(4 * blk)]),
        # full-scale square wave: forces the predictor clamps at both rails
        'full-scale square': pcm([((32767 if (i // 37) % 2 else -32768),
                                   (-32768 if (i // 23) % 2 else 32767))
                                  for i in range(2 * blk + 7)]),
        'shorter than a block': noise(77),
        'exactly one block': noise(blk),
        'silence (Blank.wav)': b'\0' * 192000,
        'single frame': struct.pack('<hh', -5, 9),
        'empty': b'',
    }
    # an odd trailing byte count, which the reference truncates to whole frames
    cases['trailing partial frame'] = cases['noise, 3 blocks + partial'] + b'\x01\x02\x03'

    bad = 0
    print("encoder vs reference encode_track():")
    for name, data in cases.items():
        want, want_n = ref.encode_track(data, blk)
        got, got_n = encode_track_fast(data, blk)
        ok = want == got and want_n == got_n
        bad += not ok
        print("  %-30s %7d frames  %8d bytes  %s"
              % (name, want_n, len(want), "ok" if ok else "MISMATCH"))

    # End to end: a small track set through both packers - a gap in the
    # numbering, an empty track, tracks that do and do not need chunk padding,
    # and the highest track number the table holds.
    tmp = tempfile.mkdtemp(prefix='ppad-selftest-')
    try:
        src = os.path.join(tmp, 'cdda')
        os.mkdir(src)
        files = {1: cases['noise, 3 blocks + partial'], 2: b'',
                 5: cases['silence (Blank.wav)'], 7: noise(8 * blk),
                 8: cases['trailing partial frame'], 63: noise(77)}
        for t, data in files.items():
            with open(os.path.join(src, 'track%02d.pcm' % t), 'wb') as f:
                f.write(data)
        want_path = os.path.join(tmp, 'ref.pcm')
        got_path = os.path.join(tmp, 'fast.pcm')
        argv = sys.argv
        try:
            sys.argv = [argv[0], src, want_path]
            with contextlib.redirect_stdout(io.StringIO()):
                rc = ref.main()
        finally:
            sys.argv = argv
        pack(src, got_path, blk, jobs=2, quiet=True)
        with open(want_path, 'rb') as f:
            want = f.read()
        with open(got_path, 'rb') as f:
            got = f.read()
        ok = rc == 0 and want == got
        bad += not ok
        print("blob vs reference main() (%d tracks, 2 processes): %d bytes  %s"
              % (len(files), len(want), "ok" if ok else "MISMATCH"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\nself-test: %d problems" % bad)
    return 1 if bad else 0


def main():
    if '--selftest' in sys.argv[1:]:
        return selftest()

    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    blk = 505
    jobs = None
    for a in sys.argv[1:]:
        if a.startswith('--block'):
            blk = int(a.split('=')[1]) if '=' in a else 505
        elif a.startswith('--jobs'):
            jobs = int(a.split('=')[1]) if '=' in a else None
    if (blk - 1) % 8:
        print("error: block_samples-1 must be a multiple of 8 (got %d)" % blk)
        return 2
    if len(args) != 2:
        print(__doc__)
        return 2
    src, dst = args

    t0 = time.time()
    ntracks, njobs, procs, t_encode, total_in = pack(src, dst, blk, jobs)
    out = os.path.getsize(dst)
    print("\n%s  %.1f MB  (from %.1f MB, %.2fx)"
          % (dst, out / 2**20, total_in / 2**20, total_in / max(out, 1)))
    print("encoded %d tracks as %d jobs on %d processes in %.1f s (%.1f s total)"
          % (ntracks, njobs, procs, t_encode, time.time() - t0))
    return 0


if __name__ == '__main__':
    sys.exit(main())
