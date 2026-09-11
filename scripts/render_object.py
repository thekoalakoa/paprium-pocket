#!/usr/bin/env python3
# Render Paprium animation objects to PNG.
#
# Verified foundation (do not re-derive):
#   blk_file = 0x2E5BD0, container 0x170000 entry 479.  BE32 there = 12327 blocks,
#   ppm_max_gfx_block = 12326.  ppm_block_addr(n) = blk_file + BE32(ROM, blk_file+4n).
#   Every one of the 12326 blocks unpacks with the 0x80 codec to exactly 0x200 bytes
#   = 16 tiles, matching PPM_BLOCK_CACHE_BASE + idx*0x200 in mame.c.
#
# Byte-order model, from the C:
#   ppmio.flash[i] == ROM[i^1]  and  ppm_unpack reads packed_data[src^1], so reading
#   the ROM in NATURAL order is already correct -> unpack80() below returns the
#   logical byte stream.  ppm_unpack WRITES unpacked_data[dst^1], so the sdram ARRAY
#   is byte-swapped; the 68000/VDP window un-swaps it again, therefore VRAM (and
#   hence tile pixels) sees the natural stream.  No swap on tile bytes.
#   The anim blob on disk was written in natural order too, but the MCU reads its
#   structs straight out of the swapped sdram array, so struct byte k of a record at
#   blob offset D is blob[(D+k)^1].  That read scores 727/727 on the flipPosX
#   identity and 100% on "offset + w*h <= 16 tiles".
#
# Layout facts read out of ppm_obj_render (mame.c ~1900-2050):
#   * posX/posY ACCUMULATE across the sprite list; each record's posX/posY is a
#     delta from the previous sprite, not an absolute.  The accumulation happens
#     BEFORE the blockNum==0 test, so blank records still move the cursor.
#   * size lower nibble: w = ((size>>2)&3)+1, h = (size&3)+1, in tiles.
#   * tiles come from block bytes [offset*0x20, (offset+w*h)*0x20) and are laid out
#     COLUMN-MAJOR (Mega Drive sprite convention) - confirmed by rendering four ways.
#   * satEntry->attrs takes (attrs & 0xf8) << 8, i.e. attrs bit3 = hflip,
#     bit4 = vflip, bits5-6 = palette line, bit7 = priority.  Those are then XOR'd
#     with the OBJECT's runtime attrs, which we cannot know statically; this render
#     uses objAttr = 0.
#
# Palette is NOT known.  Colour index 0 is transparent; 1..15 are drawn as a
# monotone dark->white ramp, tinted per palette LINE only so that a sprite built
# from two different palettes still reads as two materials.  Colours are therefore
# meaningless - shape is what this render asserts.

# Usage:  python scripts/render_object.py 0xDE 0xE0 ...
#   PAPRIUM_ROM and PAPRIUM_ANIM_BLOB must point at your own copies; neither is
#   in this repository. PNGs land in build_output/objrender/ (gitignored) - they
#   are game art and must not be committed.
#
# Identifying an object by eye takes minutes here. Inferring one from the shape
# of its animation list cost most of a day and was wrong three times: 0x33-0x3D
# are food and hearts, and the dropped weapons are 0xDC knife, 0xDE electric
# stick and 0xE0 pipe.

import os, sys, struct, zlib, collections

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paprium_data

OUT  = os.environ.get('PAPRIUM_RENDER_OUT') or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'build_output', 'objrender')
ROM  = paprium_data.rom()
BLOB = paprium_data.anim_blob()

BLK    = 0x2E5BD0
NBLK   = struct.unpack_from('>I', ROM, BLK)[0]          # 12327
MAXBLK = NBLK - 1                                       # 12326
SCALE  = 4                                              # nearest-neighbour upscale
FS     = 2                                              # font pixel scale (5x7 -> 10x14)
MAXW   = 1500                                           # wrap poses past this width

def block_addr(n): return BLK + struct.unpack_from('>I', ROM, BLK + 4*n)[0]

_bcache = {}
def unpack80(src):
    """ppm_unpack case 0x80 in natural ROM order (the ^1 in the C cancels the
       flash word-swap).  Returns the logical output stream."""
    if ROM[src] != 0x80:
        raise ValueError('block magic 0x%02X at 0x%06X' % (ROM[src], src))
    s = src + 1
    out = bytearray()
    while True:
        code = ROM[s]; s += 1
        if code == 0: break
        cnt, op = code & 0x3f, code >> 6
        if op == 0:   out += ROM[s:s+cnt]; s += cnt
        elif op == 1: out += bytes([ROM[s]]) * cnt; s += 1
        elif op == 2:
            d = ROM[s]; s += 1; ca = len(out) - d
            for _ in range(cnt): out.append(out[ca]); ca += 1
        else:         out += b'\0' * cnt
    return bytes(out)

def block(n):
    if n not in _bcache:
        if not (1 <= n <= MAXBLK):
            _bcache[n] = None
        else:
            try:    _bcache[n] = unpack80(block_addr(n))
            except Exception: _bcache[n] = None
    return _bcache[n]

# ---------------------------------------------------------------- anim blob ---
def w32(o):  # the MCU's word order, as supplied and independently confirmed
    return (BLOB[o+2] << 24) | (BLOB[o+3] << 16) | (BLOB[o] << 8) | BLOB[o+1]
def sb(v):   return v - 256 if v > 127 else v
def g(D, k): return BLOB[(D + k) ^ 1]

NOBJ = w32(0)

def anims_of(obj):
    """list of animation byte-offsets for object number obj (1-based table)."""
    base = w32((obj + 1) * 4)
    out, i = [], 0
    while True:
        a = w32(base + 4*i)
        if a == 0xFFFFFFFF: break
        out.append(a); i += 1
        if i > 512: raise RuntimeError('runaway anim list obj %d' % obj)
    return out

def frames_of(a):
    """(frames, loop_target).  frames = [(sprdata_offset, flags)]"""
    fr, o = [], a
    while True:
        v = w32(o); o += 4
        fr.append((v & 0xFFFFFF, (v >> 24) & 0x7F))
        if not (v & 0x80000000): break
        if len(fr) > 512: raise RuntimeError('runaway frame list @0x%06X' % a)
    return fr, w32(o)

def sprites_of(D):
    """decode ppm_spr_data_hdr at blob offset D -> (flags, [records])"""
    flags, count = g(D, 0), g(D, 1)
    recs = []
    for r in range(count):
        o = 2 + 8*r
        recs.append(dict(posY=sb(g(D,o+0)), posX=sb(g(D,o+1)), flipPosX=sb(g(D,o+2)),
                         size=g(D,o+3), blockNum=g(D,o+4) | (g(D,o+5) << 8),
                         offset=g(D,o+6), attrs=g(D,o+7)))
    return flags, recs

def placed(D):
    """[(x, y, w, h, rec)] with the cumulative posX/posY ppm_obj_render builds.
       Blank (blockNum==0) records still advance the cursor, so they stay in the
       walk but are dropped from the returned list."""
    _, recs = sprites_of(D)
    x = y = 0
    out = []
    for r in recs:
        x += r['posX']; y += r['posY']            # objAttr flip bit assumed clear
        if not r['blockNum']: continue
        wt = ((r['size'] >> 2) & 3) + 1; ht = (r['size'] & 3) + 1
        out.append((x, y, wt, ht, r))
    return out

# ------------------------------------------------------------------- pixels ---
def sprite_pixels(rec, wt, ht):
    """wt*8 x ht*8 list of rows of colour indices; None if the block is missing."""
    d = block(rec['blockNum'])
    if d is None: return None
    off = rec['offset']
    need = (off + wt*ht) * 32
    if need > len(d): return None
    hflip = bool(rec['attrs'] & 0x08)
    vflip = bool(rec['attrs'] & 0x10)
    W, H = wt*8, ht*8
    px = [[0]*W for _ in range(H)]
    for k in range(wt*ht):
        t   = d[(off+k)*32 : (off+k+1)*32]
        col, row = k // ht, k % ht          # COLUMN-major: down a column, then across
        for ty in range(8):
            for tx in range(8):
                b = t[ty*4 + (tx >> 1)]
                v = (b >> 4) if (tx & 1) == 0 else (b & 0xF)   # high nibble = left
                px[row*8 + ty][col*8 + tx] = v
    if hflip: px = [r[::-1] for r in px]
    if vflip: px = px[::-1]
    return px

# -------------------------------------------------------------------- paint ---
BG_A, BG_B  = (26, 26, 34), (38, 38, 50)      # 8px checker = one tile
CELL_BG     = (14, 14, 20)
SEP         = (70, 70, 92)
TEXT        = (232, 232, 240)
DIM         = (150, 150, 170)
ORIGIN      = (120, 40, 40)
WARN        = (255, 120, 120)
HDRBG       = (10, 10, 14)
PAL_TINT    = [(1.00,1.00,1.00), (0.78,0.87,1.00), (0.80,1.00,0.84), (1.00,0.84,0.76)]

def ramp(idx, pal):
    if idx == 0: return None
    v = 20 + 235 * (idx - 1) / 14.0
    t = PAL_TINT[pal & 3]
    return (min(255,int(v*t[0])), min(255,int(v*t[1])), min(255,int(v*t[2])))

FONT = {
 'A':["01110","10001","10001","11111","10001","10001","10001"],
 'B':["11110","10001","10001","11110","10001","10001","11110"],
 'C':["01110","10001","10000","10000","10000","10001","01110"],
 'D':["11110","10001","10001","10001","10001","10001","11110"],
 'E':["11111","10000","10000","11110","10000","10000","11111"],
 'F':["11111","10000","10000","11110","10000","10000","10000"],
 'G':["01110","10001","10000","10111","10001","10001","01111"],
 'H':["10001","10001","10001","11111","10001","10001","10001"],
 'I':["11111","00100","00100","00100","00100","00100","11111"],
 'J':["00111","00010","00010","00010","00010","10010","01100"],
 'K':["10001","10010","10100","11000","10100","10010","10001"],
 'L':["10000","10000","10000","10000","10000","10000","11111"],
 'M':["10001","11011","10101","10101","10001","10001","10001"],
 'N':["10001","11001","10101","10011","10001","10001","10001"],
 'O':["01110","10001","10001","10001","10001","10001","01110"],
 'P':["11110","10001","10001","11110","10000","10000","10000"],
 'Q':["01110","10001","10001","10001","10101","10010","01101"],
 'R':["11110","10001","10001","11110","10100","10010","10001"],
 'S':["01111","10000","10000","01110","00001","00001","11110"],
 'T':["11111","00100","00100","00100","00100","00100","00100"],
 'U':["10001","10001","10001","10001","10001","10001","01110"],
 'V':["10001","10001","10001","10001","10001","01010","00100"],
 'W':["10001","10001","10001","10101","10101","11011","10001"],
 'X':["10001","10001","01010","00100","01010","10001","10001"],
 'Y':["10001","10001","01010","00100","00100","00100","00100"],
 'Z':["11111","00001","00010","00100","01000","10000","11111"],
 '0':["01110","10001","10011","10101","11001","10001","01110"],
 '1':["00100","01100","00100","00100","00100","00100","01110"],
 '2':["01110","10001","00001","00010","00100","01000","11111"],
 '3':["11111","00010","00100","00010","00001","10001","01110"],
 '4':["00010","00110","01010","10010","11111","00010","00010"],
 '5':["11111","10000","11110","00001","00001","10001","01110"],
 '6':["00110","01000","10000","11110","10001","10001","01110"],
 '7':["11111","00001","00010","00100","01000","01000","01000"],
 '8':["01110","10001","10001","01110","10001","10001","01110"],
 '9':["01110","10001","10001","01111","00001","00010","01100"],
 ' ':["00000"]*7,
 '-':["00000","00000","00000","11111","00000","00000","00000"],
 ':':["00000","00100","00100","00000","00100","00100","00000"],
 '.':["00000","00000","00000","00000","00000","01100","01100"],
 ',':["00000","00000","00000","00000","01100","00100","01000"],
 '#':["01010","01010","11111","01010","11111","01010","01010"],
 '>':["01000","00100","00010","00001","00010","00100","01000"],
 '<':["00010","00100","01000","10000","01000","00100","00010"],
 '(':["00010","00100","01000","01000","01000","00100","00010"],
 ')':["01000","00100","00010","00010","00010","00100","01000"],
 '/':["00001","00010","00010","00100","01000","01000","10000"],
 '=':["00000","00000","11111","00000","11111","00000","00000"],
 '+':["00000","00100","00100","11111","00100","00100","00000"],
 '!':["00100","00100","00100","00100","00100","00000","00100"],
 '?':["01110","10001","00001","00010","00100","00000","00100"],
 '*':["00000","10101","01110","11111","01110","10101","00000"],
}
CW, CH = 6*FS, 8*FS      # advance width / line height

class Img:
    def __init__(self, w, h, bg=(0,0,0)):
        self.w, self.h = w, h
        self.buf = bytearray(bg * (w*h))
    def px(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = (y*self.w + x)*3
            self.buf[i:i+3] = bytes(c)
    def rect(self, x, y, w, h, c):
        c = bytes(c)
        for yy in range(max(0,y), min(self.h, y+h)):
            i = (yy*self.w + max(0,x))*3
            n = min(self.w, x+w) - max(0,x)
            if n > 0: self.buf[i:i+n*3] = c*n
    def text(self, x, y, s, c, scale=FS):
        for ch in s.upper():
            gl = FONT.get(ch)
            if gl:
                for r in range(7):
                    row = gl[r]
                    for k in range(5):
                        if row[k] == '1':
                            self.rect(x + k*scale, y + r*scale, scale, scale, c)
            x += 6*scale
    def save(self, path):
        raw = bytearray()
        for y in range(self.h):
            raw.append(0)
            raw += self.buf[y*self.w*3:(y+1)*self.w*3]
        def chunk(t, d):
            return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t+d) & 0xffffffff)
        png = (b'\x89PNG\r\n\x1a\n'
               + chunk(b'IHDR', struct.pack('>IIBBBBB', self.w, self.h, 8, 2, 0, 0, 0))
               + chunk(b'IDAT', zlib.compress(bytes(raw), 9))
               + chunk(b'IEND', b''))
        open(path, 'wb').write(png)

# --------------------------------------------------------------- one anim ----
def render_anim(obj, ai, aoff, log):
    frames, loop = frames_of(aoff)

    # collapse consecutive identical sprite-data offsets -> held poses
    poses = []
    for D, fl in frames:
        if poses and poses[-1][0] == D: poses[-1][1] += 1; poses[-1][2].add(fl)
        else: poses.append([D, 1, {fl}])

    # common bbox across every pose so relative motion between poses is visible
    minx = miny = 10**6; maxx = maxy = -10**6; any_spr = False
    for D, _, _ in poses:
        for x, y, wt, ht, r in placed(D):
            any_spr = True
            minx = min(minx, x); miny = min(miny, y)
            maxx = max(maxx, x + wt*8); maxy = max(maxy, y + ht*8)
    if not any_spr:
        minx = miny = 0; maxx = maxy = 16
    minx = min(minx, 0); miny = min(miny, 0)          # always include the origin
    maxx = max(maxx, 1); maxy = max(maxy, 1)
    minx -= 2; miny -= 2; maxx += 2; maxy += 2
    bw, bh = maxx - minx, maxy - miny

    cw, chh = bw*SCALE, bh*SCALE
    lab = CH + 4                                       # per-cell label strip
    pad = 8
    per_row = max(1, (MAXW - pad) // (cw + pad))
    rows = (len(poses) + per_row - 1) // per_row
    hdr  = CH*2 + 12
    W = pad + per_row*(cw + pad)
    H = hdr + rows*(chh + lab + pad) + pad

    im = Img(W, H, HDRBG)
    im.rect(0, 0, W, hdr, HDRBG)
    flagset = sorted(set().union(*[p[2] for p in poses]))
    im.text(pad, 4, 'OBJ 0X%02X   ANIM %d OF %d   AT 0X%06X' % (obj, ai, NANIM[obj], aoff), TEXT)
    l2 = '%d FRAMES  %d POSES  LOOP>0X%06X' % (len(frames), len(poses), loop)
    l2 += '  FLAGS ' + ','.join('%02X' % f for f in flagset)
    if loop == 0: l2 += '   (LOOP TARGET 0 = STOP DRAWING)'
    im.text(pad, 4 + CH, l2, DIM)

    empties = []
    for pi, (D, hold, fls) in enumerate(poses):
        cx = pad + (pi % per_row)*(cw + pad)
        cy = hdr + (pi // per_row)*(chh + lab + pad)
        # checkerboard on the 8px tile grid, aligned to the object origin
        im.rect(cx, cy, cw, chh, CELL_BG)
        for gy in range(bh):
            for gx in range(bw):
                if (((gx + minx) // 8) + ((gy + miny) // 8)) & 1:
                    im.rect(cx + gx*SCALE, cy + gy*SCALE, SCALE, SCALE, BG_B)
                else:
                    im.rect(cx + gx*SCALE, cy + gy*SCALE, SCALE, SCALE, BG_A)
        # origin crosshair (the object's own posX/posY)
        ox, oy = cx + (0 - minx)*SCALE, cy + (0 - miny)*SCALE
        im.rect(ox - 3*SCALE, oy, 6*SCALE, 1, ORIGIN)
        im.rect(ox, oy - 3*SCALE, 1, 6*SCALE, ORIGIN)

        nz = tot = 0; miss = 0
        for x, y, wt, ht, r in placed(D):
            px = sprite_pixels(r, wt, ht)
            if px is None: miss += 1; continue
            pal = (r['attrs'] >> 5) & 3
            for yy in range(ht*8):
                row = px[yy]
                for xx in range(wt*8):
                    v = row[xx]; tot += 1
                    if v == 0: continue
                    nz += 1
                    c = ramp(v, pal)
                    im.rect(cx + (x + xx - minx)*SCALE, cy + (y + yy - miny)*SCALE, SCALE, SCALE, c)
        if tot and nz == 0: empties.append(pi)
        im.rect(cx, cy + chh, cw, 1, SEP)
        lc = WARN if (tot and nz == 0) or miss else DIM
        txt = 'P%d X%d' % (pi, hold)
        if miss: txt += ' MISSBLK%d' % miss
        if tot and nz == 0: txt += ' EMPTY!'
        im.text(cx + 2, cy + chh + 3, txt, lc, FS)

    path = os.path.join(OUT, 'obj%02X_anim%d.png' % (obj, ai))
    im.save(path)

    # ---- text log, so the render can be checked without looking at it ----
    log.append('obj 0x%02X anim %d @0x%06X: %d frames, %d poses, loop->0x%06X%s'
               % (obj, ai, aoff, len(frames), len(poses), loop,
                  '  [loop=0 => STOP]' if loop == 0 else ''))
    for pi, (D, hold, fls) in enumerate(poses):
        pl = placed(D)
        nz = tot = 0
        for x, y, wt, ht, r in pl:
            px = sprite_pixels(r, wt, ht)
            if px is None: continue
            for row in px:
                for v in row:
                    tot += 1
                    if v: nz += 1
        blks = sorted(set(r['blockNum'] for *_, r in pl))
        log.append('    P%-2d hold=%-2d spr=%-2d @0x%06X blocks=%s  ink=%d/%d (%.0f%%)%s'
                   % (pi, hold, len(pl), D,
                      (str(blks[:6]) + ('...' if len(blks) > 6 else '')),
                      nz, tot, (100.0*nz/tot if tot else 0),
                      '  <<< EMPTY' if (tot and nz == 0) else ('  <<< NO SPRITES' if not tot else '')))
    return len(poses), len(frames), loop, empties

# ------------------------------------------------------------------- main ----
os.makedirs(OUT, exist_ok=True)
TARGETS = ([int(a, 0) for a in sys.argv[1:]]
           or [0xDC, 0xDE, 0xE0])      # the dropped weapons, by default
NANIM = {}
for o in TARGETS: NANIM[o] = len(anims_of(o))

def main():
    log = []
    log.append('anim blob objects = %d ; blk_file = 0x%06X ; blocks = %d (max index %d)'
               % (NOBJ, BLK, NBLK, MAXBLK))
    log.append('tile order: COLUMN-major, natural byte order, high nibble = left pixel')
    log.append('')
    nfiles = 0
    for o in TARGETS:
        al = anims_of(o)
        log.append('=== OBJECT 0x%02X : %d animation(s) ===' % (o, len(al)))
        for ai, aoff in enumerate(al):
            render_anim(o, ai, aoff, log)
            nfiles += 1
        log.append('')
    txt = '\n'.join(log)
    open(os.path.join(OUT, 'render_log.txt'), 'w').write(txt)
    print(txt)
    print('\nwrote %d PNGs to %s' % (nfiles, OUT))

if __name__ == '__main__':
    main()
