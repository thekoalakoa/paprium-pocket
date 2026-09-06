# Count 0xDA/0xDB posts that follow another 0xDA/0xDB with no other command between them (kinds 3/4/5/11/17).
# Usage: python scripts/backtoback_posts.py <winlog.bin>...
import struct, sys, glob
LINES = 262
for path in sys.argv[1:]:
    data = open(path, 'rb').read(); n = len(data)//8
    recs = [struct.unpack_from('<BBHI', data, i*8) for i in range(n)]
    kinds = set(r[0] for r in recs)
    # command stream: DA(4) DB(3) AF(5) AE(11) other(17)
    prev = None; b2b = []; total = 0; gap_min = None
    for k, pad, addr, stamp in recs:
        if k not in (3, 4, 5, 11, 17): continue
        name = {3:'DB',4:'DA',5:'AF',11:'AE'}.get(k, "%02X" % pad)
        if k in (3, 4):
            total += 1
            if prev and prev[0] in ('DA', 'DB'):
                b2b.append((name, prev[0], stamp, ((stamp>>16)-(prev[1]>>16))*LINES + (stamp&0xFFFF)-(prev[1]&0xFFFF)))
        prev = (name, stamp)
    print("%-32s recs %7d frames %5d kinds %s" % (path.split('/')[-1], n, recs[-1][3]>>16, sorted(kinds)))
    print("   DA/DB posts %d; back-to-back after another DA/DB with nothing between: %d" % (total, len(b2b)))
    from collections import Counter
    c = Counter((a, b) for a, b, s, d in b2b)
    for (a, b), v in c.items():
        ds = [d for x, y, s, d in b2b if (x, y) == (a, b)]
        print("      %s after %s : %d  (gap lines min %d max %d)" % (a, b, v, min(ds), max(ds)))
