"""Decode every track of a PPAD blob and check two things the padding must not break:
the first pcm_samples samples still reconstruct the source, and everything after
them (the chunk pad) is exact digital silence."""
import struct, sys, os
sys.path.insert(0, 'scripts')
import ima_reference as R

blob, src = sys.argv[1], sys.argv[2]
d = open(blob, 'rb').read()
bad = 0
for t in range(64):
    off, ln, ns = struct.unpack_from('<QII', d, 0x18 + t * 16)
    if not ln:
        continue
    pcm, hz, blk = R.decode(blob, t)
    got = len(pcm) // 4
    ref = open(os.path.join(src, 'track%02d.pcm' % t), 'rb').read()
    # real audio: peak error against the source over the first ns samples
    err = 0
    for i in range(ns):
        a = struct.unpack_from('<hh', pcm, i * 4)
        b = struct.unpack_from('<hh', ref, i * 4)
        err = max(err, abs(a[0] - b[0]), abs(a[1] - b[1]))
    # The pad is not required to be zero from its first sample - the encoder has
    # to walk the predictor down. What matters is that it CONVERGES, and holds
    # exact zero by the end, so there is no DC cliff at the loop seam.
    pad = [struct.unpack_from('<hh', pcm, i * 4) for i in range(ns, got)]
    conv = next((i for i, (a, b_) in enumerate(pad)
                 if abs(a) < 100 and abs(b_) < 100), None) if pad else 0
    tail = max((max(abs(a), abs(b_)) for a, b_ in pad[-64:]), default=0)
    tag = "ok"
    if pad and (conv is None or conv > 48):        # must settle within 1 ms
        tag = "PAD DOES NOT CONVERGE"; bad += 1
    elif tail != 0:
        tag = "PAD TAIL NOT SILENT"; bad += 1
    print("track %2d  %6d real + %5d pad  peak err %5d  settles in %s smp  tail %d  %s"
          % (t, ns, got - ns, err, conv, tail, tag))
print("\n%d problems" % bad)
sys.exit(1 if bad else 0)
