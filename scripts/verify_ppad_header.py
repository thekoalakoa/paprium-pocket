"""Model the RTL's header parsing byte-for-byte and check it against a blob the
packer actually wrote. Catches an off-by-one in the table base or a word index
before a 40-minute fit does."""
import struct, sys

blob = sys.argv[1]
d = open(blob, 'rb').read()

def words(buf, base, n):
    """What data_loader hands the RTL: little-endian 16-bit words, word i at base+2i."""
    return [struct.unpack_from('<H', buf, base + 2 * i)[0] for i in range(n)]

# ---- S_MAGIC: 24 bytes at slotoffset 0 ----
h = words(d, 0, 12)
ppad_magic = (h[0] == 0x5050) and (h[1] == 0x4441)
f = lambda lo: (h[lo + 1] << 16) | h[lo]
f_version, f_rate, f_chans, f_blk, f_ntracks = f(2), f(4), f(6), f(8), f(10)
blob_valid = (ppad_magic and f_version == 1 and f_rate == 48000
              and f_chans == 2 and f_blk == 505 and f_ntracks >= 64)
print("S_MAGIC  word0=%04X word1=%04X magic=%s" % (h[0], h[1], ppad_magic))
print("         version=%d rate=%d chans=%d blk=%d ntracks=%d -> blob_valid=%s"
      % (f_version, f_rate, f_chans, f_blk, f_ntracks, blob_valid))
assert blob_valid, "RTL would reject this blob"

# ---- S_HDR: 16 bytes at 0x18 + N*16 ----
bad = 0
for n in range(64):
    off = 0x18 + n * 16
    e = words(d, off, 8)
    g = lambda lo: (e[lo + 1] << 16) | e[lo]
    hdr_start, hdr_off_hi, hdr_len, hdr_smpls = g(0), g(2), g(4), g(6)
    ref_off, ref_len, ref_ns = struct.unpack_from('<QII', d, off)
    ok = (hdr_start == (ref_off & 0xFFFFFFFF) and hdr_off_hi == (ref_off >> 32)
          and hdr_len == ref_len and hdr_smpls == ref_ns)
    if not ok:
        print("  track %2d MISMATCH rtl=(%X,%X,%d,%d) ref=(%X,%d,%d)"
              % (n, hdr_start, hdr_off_hi, hdr_len, hdr_smpls, ref_off, ref_len, ref_ns))
        bad += 1
    if ref_len:
        if ref_len % 4096:
            print("  track %2d len %d is not a whole 4096-byte chunk" % (n, ref_len))
            bad += 1
        if ref_off % 4096:
            print("  track %2d offset %X is not chunk aligned" % (n, ref_off))
            bad += 1
        # the RTL refuses a track whose frames cannot hold its stated samples
        frames = ref_len // 512
        if frames * 505 < ref_ns:
            print("  track %2d claims %d samples but only %d frames" % (n, ref_ns, frames))
            bad += 1
        if ref_off + ref_len > len(d):
            print("  track %2d runs past end of file" % n)
            bad += 1
print("S_HDR    64 entries checked at 0x18 + N*16, %d problems" % bad)

# ---- the mute path: an old raw-PCM blob must be rejected, not parsed ----
fake = b'\x00\x11\x22\x33' + b'\xAB' * 60
h2 = words(fake, 0, 12)
print("stale .pcm: word0=%04X word1=%04X -> magic=%s (must be False)"
      % (h2[0], h2[1], (h2[0] == 0x5050 and h2[1] == 0x4441)))
sys.exit(1 if bad else 0)
