# Classify every 0x1FE4 (reg_status_1) busy poll in a GPGX winlog by the command that preceded it,
# whether the game waited for the response (0x1FEA reads) first, and the poll run length.
# Usage: python scripts/busy_polls.py vdp-capture/winlog-boot-allcmds.bin   (needs kinds 9+12; kind 17 for non-DA/DB commands)
import struct, sys
path = sys.argv[1]
data = open(path, 'rb').read()
n = len(data) // 8
recs = [struct.unpack_from('<BBHI', data, i*8) for i in range(n)]
LINES = 262
def t(stamp): return (stamp >> 16) * LINES + (stamp & 0xFFFF)   # in scanlines
def fmt(stamp): return "f%5d/v%3d" % (stamp >> 16, stamp & 0xFFFF)
CMDK = {17: 'other', 4: 'DA', 3: 'DB', 5: 'AF', 11: 'AE'}
last_cmd = None          # (name, word, stamp)
resp_wait = 0            # 0x1FEA reads since last command
runs = []                # each: dict
cur = None
i = 0
pending9 = None
for k, pad, addr, stamp in recs:
    if k in CMDK:
        if k == 17: name = "%02X" % pad; word = addr
        elif k == 4: name = "DA"; word = addr
        elif k == 3: name = "DB"; word = addr
        else: name = CMDK[k]; word = 0
        last_cmd = (name, word, stamp)
        resp_wait = 0
        cur = None
        continue
    if k == 8:
        resp_wait += 1
        continue
    if k == 9 and addr == 0x1FE4:
        pending9 = stamp; continue
    if k == 12 and pending9 is not None:
        pc = (pad << 16) | addr
        st = pending9; pending9 = None
        if cur and cur['pc'] == pc:
            cur['n'] += 1; cur['last'] = st
        else:
            cur = dict(pc=pc, n=1, first=st, last=st, cmd=last_cmd, resp=resp_wait)
            runs.append(cur)
        continue
    pending9 = None
print("records", n, "frames", recs[-1][3] >> 16)
print("%-10s %-11s %6s  %-22s %8s  %s" % ("PC", "first", "reads", "preceding cmd", "dt(us)", "1FEA-wait"))
from collections import Counter
bysite = Counter()
for r in runs:
    c = r['cmd']
    if c: cname = "%s %04X @%s" % (c[0], c[1], fmt(c[2])); dt = (t(r['first']) - t(c[2])) * 63.5
    else: cname = "(none)"; dt = -1
    bysite[(r['pc'], c[0] if c else None)] += 1
    if r['n'] > 1 or (c and c[0] not in ('DA', 'DB')) or r['resp']:
        print("%06X %-11s %6d  %-22s %8.0f  %s" % (r['pc'], fmt(r['first']), r['n'], cname, dt, r['resp']))
print()
print("polls by (site, preceding cmd):")
for (pc, c), v in sorted(bysite.items()): print("  %06X after %-5s : %d" % (pc, c, v))
