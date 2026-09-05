"""Per-frame sprite-stream membership from a GPGX window log (kinds 13/14).

    python scripts/analyze_stream.py ../vdp-capture/winlog-boot-stream.bin [--frames A:B] [--all]

Ground truth for the retail VRAM stream contract: for every frame, how many
0xAD objects paprium_sprite was called for, how many returned early and why,
how many sprites were streamed, the bytes they cost, and the tile cursor's
maximum (0x200-based, so 16 = an empty frame). Compare with the Pocket's
onset ring under --stream (byte 1 = cursor max tile, byte 0 = sprites
streamed) on the same scene.

Frames come from the stamp's high 16 bits (paprium_audio ticks).
"""
import struct, sys
from collections import Counter, defaultdict

def main():
    path = sys.argv[1]
    lo, hi = 0, 1 << 30
    if '--frames' in sys.argv:
        a, b = sys.argv[sys.argv.index('--frames') + 1].split(':')
        lo, hi = int(a), int(b)
    show_all = '--all' in sys.argv
    raw = open(path, 'rb').read()
    n = len(raw) // 8
    frames = defaultdict(lambda: {'obj': 0, 'walked': 0, 'noframe': 0, 'empty': 0, 'tile0': 0, 'cap94': 0,
                                  'spr': 0, 'bytes': 0, 'cursor': 16, 'count_sum': 0, 'sizes': Counter(), 'blocks': Counter(), 'ofs_max': 0})
    kinds = Counter()
    for i in range(n):
        kind, pad, addr, stamp = struct.unpack_from('<BBHI', raw, i * 8)
        kinds[kind] += 1
        fr = stamp >> 16
        if kind == 14:
            f = frames[fr]
            if pad == 1: f['obj'] += 1; f['noframe'] += 1
            elif pad == 2: f['obj'] += 1; f['empty'] += 1
            elif pad == 3: f['obj'] += 1; f['walked'] += 1; f['count_sum'] += addr >> 8
            elif pad == 4: f['tile0'] += 1
            elif pad == 5: f['cap94'] += 1
        elif kind == 15:
            f = frames[fr]
            f['blocks'][addr] += 1
            if pad * 2 > f['ofs_max']: f['ofs_max'] = pad * 2
        elif kind == 13:
            f = frames[fr]
            sx, sy = (pad >> 2) + 1, (pad & 3) + 1
            f['spr'] += 1
            f['bytes'] += sx * sy * 0x20
            f['sizes'][(sx, sy)] += 1
            end = addr + sx * sy
            if end > f['cursor']: f['cursor'] = end
    print('records:', n, dict(sorted(kinds.items())))
    keys = sorted(k for k in frames if lo <= k <= hi)
    if not keys:
        print('no sprite records in range'); return
    print('frames with sprite activity:', len(keys), 'range', keys[0], '..', keys[-1])
    cur = [frames[k]['cursor'] for k in keys]
    spr = [frames[k]['spr'] for k in keys]
    print('cursor max tile: min %d  median %d  max %d' % (min(cur), sorted(cur)[len(cur) // 2], max(cur)))
    print('sprites streamed/frame: min %d  median %d  max %d' % (min(spr), sorted(spr)[len(spr) // 2], max(spr)))
    tot = Counter()
    for k in keys:
        for name in ('obj', 'walked', 'noframe', 'empty', 'tile0', 'cap94', 'spr'):
            tot[name] += frames[k][name]
    print('totals:', dict(tot))
    print()
    print('frame  obj walk nofr empty tile0 cap94 | spr  bytes  cursor | list count sum | sizes')
    last = None
    for k in keys:
        f = frames[k]
        row = (f['obj'], f['walked'], f['noframe'], f['empty'], f['tile0'], f['cap94'], f['spr'], f['bytes'], f['cursor'], f['count_sum'])
        if not show_all and row == last:
            continue
        last = row
        sizes = ' '.join('%dx%d:%d' % (a, b, c) for (a, b), c in sorted(f['sizes'].items()))
        print('%5d  %3d %4d %4d %5d %5d %5d | %3d %6d  %6d | %14d | %s' % ((k,) + row + (sizes,)))
        if f['blocks']:
            bl = ' '.join('%d:%d' % (b, c) for b, c in sorted(f['blocks'].items()))
            print('       blocks(block:sprites) %s   ofs max %d' % (bl, f['ofs_max']))

if __name__ == '__main__':
    main()
