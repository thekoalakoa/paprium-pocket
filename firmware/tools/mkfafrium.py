#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""mkfafrium.py - Fafrium, the cart firmware file (docs/FAFRIUM.md), and the boot stub the bitstream carries for it.

The file ships as little_man_firmware.bin (its public name is Little-Man Firmware), which is the default output name
of `make`. Its firmware version (1.0 to start with) is written into the header's kind word as information.
The MCU is the cart's NEORV32 soft CPU in the core; IROM is its code memory, WRAM its working RAM, and SRAM the
Pocket's SRAM chip. RTL is the core's hardware description (rtl/PAPRIUM in the core's tree).

    python -I -B tools/mkfafrium.py stub --out DIR [--gcc-bin DIR] [--install RTL_PAPRIUM_DIR]
    python -I -B tools/mkfafrium.py make --img DIR [--sram FILE] [--out FILE] [--kind test|release] [--brain]
                                         [--version MAJOR.MINOR] [--build HEX] [--json FILE]
    python -I -B tools/mkfafrium.py check FILE --img DIR [--sram FILE]
    python -I -B tools/mkfafrium.py show FILE
    python -I -B tools/mkfafrium.py bad FILE KIND OUT          (a planted-fault copy for the benches; KIND in BADS)
    python -I -B tools/mkfafrium.py memorder FILE --out DIR
    python -I -B tools/mkfafrium.py leak FILE --elf ELF [--elf ELF ...] [--sram-elf ELF] [--json OUT] [--keep DIR]

stub:  builds board/pocket/fafrium/fafrium_stub.S (RV32I + Zicsr, linked at 0x0) and writes the six bitstream images of a
       Fafrium bitstream: mcu.txt = the stub in IROM [0, STUB_LEN) and zeros to 32 KB, mcu_ext.txt = 56 KB of zeros,
       wram_b0..b3.txt = 48 KB of zeros, in the text form the RTL's $readmemh reads (16 words a line, CRLF, the last
       line ending in a space; the WRAM lanes one byte a line, CRLF). Writes stub.elf / stub.bin / stub.dis /
       stub.json into --out; --install copies the six images into an RTL tree's rtl/PAPRIUM. Refuses a stub that does
       not fit STUB_LEN, a finisher that holds an absolute address (it is linked twice, at 0x0 and at 0x1000, and its
       words must be the same) or a CRC table that is not the CRC-32 table.
make:  the Fafrium file from one firmware build: its six images (the variant's img/ folder: mcu.txt, mcu_ext.txt,
       wram_b0..b3.txt) and, if the build has one, the MegaWire SRAM code (sram.bin from the same build). Every WRAM
       byte outside the window 0x2C00-0xABFF must be zero (the stub leaves those at the bitstream's 0). The kind word
       (0x20) gets the kind bits (bit 0 TEST, bit 1 the CPU MATE brain linked) and the firmware version (--version,
       default FW_VERSION below: bits 31-24 the major number, bits 23-16 the minor one). --out defaults to
       little_man_firmware.bin, the name the Pocket loads.
check: the file against the images (and the SRAM code) byte for byte, with both CRCs; exit 1 on any difference.
show:  the header, decoded, with the kind bits and the firmware version read from the kind word.
bad:   planted-fault copies for the RTL benches.
memorder: the file in memory order, as the stub places it. irom.bin is the IROM from 0x0000_0000 (88 KB). wram.bin
       is the whole WRAM from 0x8000_0000 (48 KB): the window from the file and zeros elsewhere. sram.bin is the Pocket
       SRAM from 0x0800_0000, as long as the SRAM section. The file bytes that the stub does not place go to header.bin
       (bytes 0x00-0x7F) and tail.bin (the zero fill, the end word and anything past the file's length).
       memorder.json lists each part with its address or file offset and its md5.
leak:  the leak guard (tools/leakguard.py, with its references from paths.local.json) on that memory-order copy. Every
       raw hit is a 12-byte window equal to a reference. It is mapped to its IROM, WRAM or SRAM address, where it must
       lie in a place that the guard's ELF method allows in the build's ELFs. Pass --elf for main.elf and, if the build
       has one, for ovl/ovl.elf; pass --sram-elf for the ELF of the SRAM code. The allowed places are:
         - the brain's own bytes: .brain_irom, and cf.bin and rodata.bin at the start of .wram_text, each found by an
           exact byte compare;
         - a code section, when the reference is one of the brain files (the ELF method scans code only against the
           other references);
         - a window over an allowed table (tools/leak_allow.json, matched exactly in the ELF and in the file) whose
           other bytes are all zero. This is the guard's rule for built sections (the linker's fill, or a zero byte
           beside the table): B Jam's decision of 2026-10-30.
       A hit anywhere else, and any hit in header.bin or tail.bin, is reported with its place and symbol. Exit status:
       0 = no hit outside those places, 1 = hits, 2 = setup error (no references, or a missing ELF).
"""
import argparse, hashlib, json, os, re, shutil, struct, subprocess, sys, tempfile, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STUB_SRC = os.path.join(ROOT, 'board', 'pocket', 'fafrium', 'fafrium_stub.S')

# the format (docs/FAFRIUM.md); the stub holds the same values (fafrium_stub.S)
MAGIC, ENDW = 0x52464146, 0x444E4546    # 'FAFR', 'FEND' (little-endian words as the MCU reads them)
HVER, HLEN, FLEN = 0x00800001, 0x80, 0x40000
LAYOUT = 0x00583001                     # IROM 88 KB, WRAM 48 KB, platform 1 = Analogue Pocket
EPOCH = 0x46410001                      # the bitstream's firmware epoch (fafrium_stub.S EPOCH)
IFACE, FEAT, CLKHZ = 0x50490103, 0x00580047, 53693175
IROM_LEN, W_DST, W_LEN = 0x16000, 0x80002C00, 0x8000
S_DST, S_MAX = 0x08000000, 0x10000
S_OFF = HLEN + IROM_LEN + W_LEN
KIND_TEST, KIND_BRAIN = 1, 2
# The firmware version goes into the kind word as information: bits 31-24 the major number, bits 23-16 the minor one.
# The stub does not read the kind word, so the version never decides whether a file starts (the epoch, the MCU
# interface, FEAT and the clock do that).
FW_VERSION = '1.0'
VER_SHIFT = 16
OUT_NAME = 'little_man_firmware.bin'    # the file name the Pocket loads (data.json's slot "Little-Man Firmware")
STUB_LEN = 0x800
IROM0_WORDS, EXT_WORDS, WRAM_LINES = 8192, 14336, 12288
IMAGES = ('mcu.txt', 'mcu_ext.txt', 'wram_b0.txt', 'wram_b1.txt', 'wram_b2.txt', 'wram_b3.txt')
BADS = ('magic', 'hcrc', 'hver', 'flen', 'layout', 'sect', 'slen', 'epoch', 'iface', 'feat', 'clk', 'pcrc', 'sram',
        'pad', 'endw', 'short', 'long', 'zero',
        'rsv', 'rsvlast', 'fill', 'filllast', 'l2x', 'lmag', 'l8', 'ltail')


def crc_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8):
            c = (c >> 1) ^ 0xEDB88320 if c & 1 else c >> 1
        t.append(c)
    return t


def md5b(b):
    return hashlib.md5(b).hexdigest()


# ---------------------------------------------------------------- the images

def read_words(p, n):
    w = [int(x, 16) for x in open(p).read().split()]
    if len(w) != n:
        sys.exit('mkfafrium: %s has %d words, not %d' % (p, len(w), n))
    return w


def read_images(d):
    w0 = read_words(os.path.join(d, 'mcu.txt'), IROM0_WORDS)
    wx = read_words(os.path.join(d, 'mcu_ext.txt'), EXT_WORDS)
    irom = b''.join(struct.pack('>I', w) for w in w0 + wx)        # the stored order = the bytes in memory order
    lanes = [read_words(os.path.join(d, 'wram_b%d.txt' % k), WRAM_LINES) for k in range(4)]
    wram = bytes(lanes[k][i] for i in range(WRAM_LINES) for k in range(4))
    md5 = {n: md5b(open(os.path.join(d, n), 'rb').read()) for n in IMAGES}
    return irom, wram, md5


def read_sram(p):
    if not p:
        return b''
    s = open(p, 'rb').read()
    if len(s) % 4 or len(s) > S_MAX:
        sys.exit('mkfafrium: the SRAM code %s is %d B: it must be 4-aligned and at most %d B' % (p, len(s), S_MAX))
    return s


def swap16(b):
    a = bytearray(b)
    a[0::2], a[1::2] = b[1::2], b[0::2]
    return bytes(a)


# ---------------------------------------------------------------- the file

def sections(slen):
    return [(0, IROM_LEN, HLEN), (W_DST, W_LEN, HLEN + IROM_LEN), (S_DST, slen, S_OFF)]


def header(payload, slen, kind, build, epoch):
    h = struct.pack('<IIIIIIIIIIII', MAGIC, HVER, FLEN, LAYOUT, epoch, IFACE, FEAT, CLKHZ, kind, build, 3,
                    zlib.crc32(payload))
    for s in sections(slen):
        h += struct.pack('<III', *s)
    h += bytes(0x7C - len(h))
    return h + struct.pack('<I', zlib.crc32(h))


def logical(irom, wram, sram, kind=0, build=0, epoch=EPOCH):
    """the file as the MCU reads it (little-endian words); on disk it is swap16() of this"""
    lo, hi = W_DST - 0x80000000, W_DST - 0x80000000 + W_LEN
    if any(wram[:lo]) or any(wram[hi:]):
        sys.exit('mkfafrium: the image has non-zero WRAM bytes outside 0x%04X-0x%04X' % (lo, hi - 1))
    if len(irom) != IROM_LEN:
        sys.exit('mkfafrium: the IROM image is %d B, not %d' % (len(irom), IROM_LEN))
    body = irom + wram[lo:hi] + sram
    payload = body + bytes(FLEN - HLEN - 4 - len(body)) + struct.pack('<I', ENDW)
    assert len(payload) == FLEN - HLEN
    return header(payload, len(sram), kind, build, epoch) + payload


NAMES = ('magic', 'hver', 'flen', 'layout', 'epoch', 'iface', 'feat', 'clk', 'kind', 'build', 'nsect', 'pcrc')


def parse(lg):
    d = dict(zip(NAMES, struct.unpack('<IIIIIIIIIIII', lg[:48])))
    d['sections'] = [struct.unpack('<III', lg[0x30 + 12 * i:0x3C + 12 * i]) for i in range(3)]
    d['hcrc'] = struct.unpack('<I', lg[0x7C:0x80])[0]
    d['hcrc_ok'] = zlib.crc32(lg[:0x7C]) == d['hcrc']
    d['endw'] = struct.unpack('<I', lg[FLEN - 4:FLEN])[0] if len(lg) >= FLEN else None
    d['pcrc_ok'] = len(lg) == FLEN and zlib.crc32(lg[HLEN:FLEN]) == d['pcrc']
    d['bytes'] = len(lg)
    d['kind_name'] = ('TEST' if d['kind'] & KIND_TEST else 'RELEASE') + \
        (', CPU MATE brain linked' if d['kind'] & KIND_BRAIN else ', no brain')
    d['version'] = '%d.%d' % (d['kind'] >> 24, (d['kind'] >> VER_SHIFT) & 0xFF)
    return d


def version_bits(v):
    """'MAJOR.MINOR' -> the version's bits of the kind word (bits 31-24 the major number, 23-16 the minor one)"""
    m = re.fullmatch(r'(\d+)\.(\d+)', v)
    if not m or int(m.group(1)) > 255 or int(m.group(2)) > 255:
        sys.exit('mkfafrium: --version wants MAJOR.MINOR, each 0-255, not %r' % v)
    return (int(m.group(1)) << 24) | (int(m.group(2)) << VER_SHIFT)


def show(d):
    out = {}
    for k, v in d.items():
        if isinstance(v, bool) or v is None:
            out[k] = v
        elif isinstance(v, int):
            out[k] = '%08x' % v
        elif k == 'sections':
            out[k] = [['%08x' % x for x in s] for s in v]
        else:
            out[k] = v
    return json.dumps(out, indent=1)


# ---------------------------------------------------------------- the stub

def local_gcc_bin():
    p = os.path.join(ROOT, 'paths.local.json')
    v = os.environ.get('PAPRIUM_RISCV_BIN') or (json.load(open(p)).get('riscv_bin') if os.path.exists(p) else None)
    return v


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit('mkfafrium: %s failed:\n%s%s' % (cmd[0], r.stdout, r.stderr))
    return r.stdout


def words_text(words):
    lines = [' '.join('%08X' % w for w in words[i:i + 16]) for i in range(0, len(words), 16)]
    return ('\r\n'.join(lines) + ' ').encode('ascii')


def lanes_text(data):
    return [''.join('%02X\r\n' % data[4 * i + k] for i in range(len(data) // 4)).encode('ascii') for k in range(4)]


def build_stub(gcc_bin, out, base):
    g = lambda n: os.path.join(gcc_bin, 'riscv-none-elf-' + n + ('.exe' if os.name == 'nt' else ''))
    elf = os.path.join(out, 'stub_%x.elf' % base)
    run([g('gcc'), '-march=rv32i_zicsr', '-mabi=ilp32', '-nostdlib', '-nostartfiles', '-Wl,--no-relax',
         '-Wl,-Ttext=0x%x' % base, '-Wl,-e,_start', '-Wl,--build-id=none', '-I', out, '-o', elf, STUB_SRC])
    binf = elf[:-4] + '.bin'
    run([g('objcopy'), '-O', 'binary', '-j', '.text', elf, binf])
    syms = {}
    for line in run([g('nm'), elf]).splitlines():
        m = re.match(r'([0-9a-fA-F]+) \w (\S+)', line)
        if m:
            syms[m.group(2)] = int(m.group(1), 16)
    return elf, open(binf, 'rb').read(), syms, g


def cmd_stub(a):
    gcc_bin = a.gcc_bin or local_gcc_bin()
    if not gcc_bin:
        sys.exit('mkfafrium: no toolchain: --gcc-bin, PAPRIUM_RISCV_BIN or paths.local.json riscv_bin')
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, 'crc_tab.inc'), 'w', newline='\n') as f:
        for c in crc_table():
            f.write('    .word   0x%08X\n' % c)
    elf, stub, syms, g = build_stub(gcc_bin, a.out, 0)
    _, stub2, _, _ = build_stub(gcc_bin, a.out, 0x1000)
    if len(stub) > STUB_LEN:
        sys.exit('mkfafrium: the stub is %d B, more than STUB_LEN %d B' % (len(stub), STUB_LEN))
    f0, f1 = syms['fin_begin'], syms['fin_end']
    if stub[f0:f1] != stub2[f0:f1]:
        sys.exit('mkfafrium: the finisher holds an absolute address (its words differ when linked at 0x1000)')
    tb, t = syms['crc_tab'], crc_table()
    if any(int.from_bytes(stub[tb + 4 * i:tb + 4 * i + 4], 'little') != t[i] for i in range(256)):
        sys.exit('mkfafrium: the stub\'s table is not the CRC-32 table')
    with open(os.path.join(a.out, 'stub.dis'), 'w', newline='\n') as f:
        f.write(run([g('objdump'), '-d', elf]))
    shutil.copyfile(elf, os.path.join(a.out, 'stub.elf'))
    with open(os.path.join(a.out, 'stub.bin'), 'wb') as f:
        f.write(stub)
    irom = stub + bytes(IROM0_WORDS * 4 - len(stub))
    w0 = [int.from_bytes(irom[4 * i:4 * i + 4], 'big') for i in range(IROM0_WORDS)]   # the stored order (dato swaps)
    imgs = {'mcu.txt': words_text(w0), 'mcu_ext.txt': words_text([0] * EXT_WORDS)}
    for k, b in enumerate(lanes_text(bytes(WRAM_LINES * 4))):
        imgs['wram_b%d.txt' % k] = b
    for n, b in imgs.items():
        with open(os.path.join(a.out, n), 'wb') as f:
            f.write(b)
    info = {'stub_bytes': len(stub), 'stub_len': STUB_LEN, 'stub_md5': md5b(stub), 'stub_crc32': '%08x' % zlib.crc32(stub),
            'fin_begin': f0, 'fin_end': f1, 'fin_bytes': f1 - f0, 'crc_tab': tb, 'refuse': syms['refuse'],
            'images_md5': {n: md5b(b) for n, b in imgs.items()}}
    with open(os.path.join(a.out, 'stub.json'), 'w', newline='\n') as f:
        json.dump(info, f, indent=1)
    print(json.dumps(info, indent=1))
    if a.install:
        for n, b in imgs.items():
            with open(os.path.join(a.install, n), 'wb') as f:
                f.write(b)
        print('installed the six images into', a.install)


# ---------------------------------------------------------------- make / check / show / bad

def cmd_make(a):
    irom, wram, md5 = read_images(a.img)
    sram = read_sram(a.sram)
    kind = (KIND_TEST if a.kind == 'test' else 0) | (KIND_BRAIN if a.brain else 0) | version_bits(a.version)
    lg = logical(irom, wram, sram, kind, int(a.build, 16), int(a.epoch, 16))
    disk = swap16(lg)
    with open(a.out, 'wb') as f:
        f.write(disk)
    d = parse(lg)
    info = {'file': os.path.basename(a.out), 'bytes': len(disk), 'md5': md5b(disk), 'payload_crc32': '%08x' % d['pcrc'],
            'header_crc32': '%08x' % d['hcrc'], 'logical_md5': md5b(lg), 'kind': '%08x' % kind,
            'kind_name': d['kind_name'], 'version': d['version'], 'build': a.build,
            'epoch': a.epoch, 'images_md5': md5, 'sram_bytes': len(sram), 'sram_md5': md5b(sram),
            'irom_md5': md5b(irom), 'wram_md5': md5b(wram)}
    if a.json:
        with open(a.json, 'w', newline='\n') as f:
            json.dump(info, f, indent=1)
    print(json.dumps(info, indent=1))


def cmd_check(a):
    lg = swap16(open(a.file, 'rb').read())
    irom, wram, _ = read_images(a.img)
    sram = read_sram(a.sram)
    d = parse(lg)
    print(show(d))
    want = logical(irom, wram, sram, d['kind'], d['build'], int(a.epoch, 16))   # the bitstream's epoch, not the file's
    ok = lg == want and d['hcrc_ok'] and d['pcrc_ok']
    if not ok and len(lg) == len(want):
        diff = [i for i in range(len(lg)) if lg[i] != want[i]]
        print('differing bytes:', len(diff), 'first at 0x%05X' % diff[0] if diff else '')
    print('CHECK', 'PASS (the file = the images byte for byte)' if ok else 'FAIL')
    sys.exit(0 if ok else 1)


def cmd_show(a):
    print(show(parse(swap16(open(a.file, 'rb').read()))))


def rehdr(lg):
    lg[0x7C:0x80] = struct.pack('<I', zlib.crc32(bytes(lg[:0x7C])))


def recrc(lg):
    """both CRCs made right again (a well-formed file whose other bytes are wrong)"""
    lg[0x2C:0x30] = struct.pack('<I', zlib.crc32(bytes(lg[HLEN:FLEN])))
    rehdr(lg)


def cmd_bad(a):
    lg = bytearray(swap16(open(a.file, 'rb').read()))
    k = a.kind
    slen = struct.unpack('<I', lg[0x4C:0x50])[0]
    word = {'hver': 0x04, 'flen': 0x08, 'layout': 0x0C, 'epoch': 0x10, 'iface': 0x14, 'feat': 0x18, 'clk': 0x1C,
            'sect': 0x38, 'slen': 0x4C}
    if k == 'magic':
        lg[0] ^= 0x01
    elif k == 'hcrc':
        lg[0x24] ^= 0x10                          # the build word: the header CRC no longer matches
    elif k in word:
        off = word[k]
        v = struct.unpack('<I', lg[off:off + 4])[0]
        v = v + 4 if k in ('sect', 'slen') else v + 1
        if k == 'slen':
            v = S_MAX + 4                         # the SRAM code longer than its room
        lg[off:off + 4] = struct.pack('<I', v)
        rehdr(lg)                                 # a well-formed header of another version / layout
    elif k == 'pcrc':
        lg[HLEN + 0x9000] ^= 0x40                 # one IROM bit
    elif k == 'sram':
        lg[S_OFF + slen // 2] ^= 0x01             # one bit of the SRAM code
    elif k == 'pad':
        lg[S_OFF + slen + 0x100] ^= 0x80          # one bit of the zero fill
    elif k == 'endw':
        lg[FLEN - 4:FLEN] = bytes(4)              # no end word (the CRC fails too)
    elif k == 'short':
        lg = lg[:FLEN - 0x1000]                   # the last 4 KB missing
    elif k == 'long':
        lg = lg + bytes(range(256)) * 4           # 1 KB after a good file (it wraps onto the header)
    elif k == 'zero':
        lg = bytearray(len(lg))                   # all zero
    elif k in ('rsv', 'rsvlast'):                 # a reserved header word not zero, the header CRC made right
        lg[0x54 if k == 'rsv' else 0x7B] = 0x01 if k == 'rsv' else 0x80
        rehdr(lg)
    elif k in ('fill', 'filllast'):               # a zero-fill byte not zero (the first / the last), both CRCs right
        lg[S_OFF + slen if k == 'fill' else FLEN - 5] = 0x01
        recrc(lg)
    elif k == 'l2x':
        lg = lg + lg                              # the good file twice (512 KB)
    elif k == 'lmag':
        lg = lg + lg[:4]                          # 256 KB + 4 B: the extra word is the magic
    elif k == 'l8':
        lg = lg + lg[:8]                          # 256 KB + 8 B: its own first 8 bytes again
    elif k == 'ltail':
        lg = lg + lg[:4] + bytes(range(256)) * 4  # 256 KB + 1 KB + 4 B: the magic, then other bytes over the header
    else:
        sys.exit('bad: kind? one of ' + ' '.join(BADS))
    disk = swap16(bytes(lg))
    with open(a.out, 'wb') as f:
        f.write(disk)
    print('bad', k, len(disk), md5b(disk))


# ---------------------------------------------------------------- the file in memory order, and the leak guard on it

def memorder(lg):
    """The parts of the file in memory order, as a list of (name, address or None, file offset of byte 0 or None,
    bytes): first what the stub places, then what it does not. The section places are the format's (FAFRIUM.md);
    the SRAM length is the file's own when it is a valid one."""
    slen = struct.unpack('<I', lg[0x4C:0x50])[0] if len(lg) >= 0x50 else 0
    if slen % 4 or slen > S_MAX:
        slen = 0
    pad = lambda b, n: bytes(b[:n]) + bytes(max(0, n - len(b)))
    irom = pad(lg[HLEN:HLEN + IROM_LEN], IROM_LEN)
    lo = W_DST - 0x80000000
    wram = bytes(lo) + pad(lg[HLEN + IROM_LEN:S_OFF], W_LEN) + bytes(WRAM_LINES * 4 - lo - W_LEN)
    sram = pad(lg[S_OFF:S_OFF + slen], slen)
    return [('irom', 0x00000000, HLEN, irom), ('wram', 0x80000000, None, wram), ('sram', S_DST, S_OFF, sram),
            ('header', None, 0, bytes(lg[:HLEN])), ('tail', None, S_OFF + slen, bytes(lg[S_OFF + slen:]))]


def write_memorder(lg, out):
    os.makedirs(out, exist_ok=True)
    info = []
    for name, addr, off, b in memorder(lg):
        with open(os.path.join(out, name + '.bin'), 'wb') as f:
            f.write(b)
        info.append({'part': name, 'file': name + '.bin', 'address': None if addr is None else '%08x' % addr,
                     'file_offset': off, 'bytes': len(b), 'md5': md5b(b)})
    with open(os.path.join(out, 'memorder.json'), 'w', newline='\n') as f:
        json.dump(info, f, indent=1)
    return info


def cmd_memorder(a):
    print(json.dumps(write_memorder(swap16(open(a.file, 'rb').read()), a.out), indent=1))


SRAM_SPAN = (S_DST, S_DST + 0x01000000)          # the Pocket SRAM region (0x08xx_xxxx)


def elf_view(paths, sram):
    """The sections and symbols of the build's ELFs, by run address. The SRAM region comes from the SRAM code's ELF
    only, and every other address from the image's ELFs only."""
    sys.path.insert(0, HERE)
    import fwelf   # noqa: E402
    secs, syms = [], []
    for p, is_sram in [(x, False) for x in paths] + ([(sram, True)] if sram else []):
        if not os.path.isfile(p):
            raise FileNotFoundError(p)
        keep = lambda x: (SRAM_SPAN[0] <= x < SRAM_SPAN[1]) == is_sram
        secs += [dict(s, elf=p) for s in fwelf.sections(p) if s['alloc'] and s['size'] and keep(s['addr'])]
        syms += [dict(x, elf=p) for x in fwelf.symbols(p) if x['type'] in ('OBJECT', 'FUNC') and x['size'] > 0
                 and keep(x['value'])]
    syms.sort(key=lambda x: x['value'])
    return secs, syms


def classify(hits, parts, secs, syms, allow, brain, rv32refs):
    """For each raw hit of the guard on the memory-order parts: (allowed, why, part, address or file offset, symbol)."""
    import bisect
    mem = {name: (addr, b) for name, addr, _, b in parts}
    placed = [(addr, b) for _, addr, _, b in parts if addr is not None]

    def membytes(lo, n):
        for addr, b in placed:
            if addr <= lo and lo + n <= addr + len(b):
                return b[lo - addr:lo - addr + n]
        return None

    # The allowed tables: an allow entry's symbol, linked with exactly its size, whose bytes in the FILE match the
    # entry's hash.
    size_of = {'u8': 1, 'u16': 2, 'u32': 4, 's8': 1, 's16': 2, 's32': 4}
    objs = []
    for e in allow:
        for sy in syms:
            if sy['name'] == e['symbol'] and sy['size'] == e['count'] * size_of[e['elem']]:
                b = membytes(sy['value'], sy['size'])
                if b is not None and hashlib.sha256(b).hexdigest() == e['values_sha256']:
                    objs.append((sy['value'], sy['value'] + sy['size'], e['symbol']))
    # The brain's own bytes, each found by an exact byte compare in the FILE: .brain_irom equal to the brain.bin of
    # either brain directory, and cf.bin and rodata.bin at the start of .wram_text. In a no-brain image .brain_irom is
    # zero, so it is not a brain span and holds no hit.
    bspans = []
    for s in secs:
        raw = membytes(s['addr'], s['size']) or b''
        if s['name'] == '.brain_irom' and any(raw == v for v in brain.get('brain.bin', [])):
            bspans.append((s['addr'], s['addr'] + s['size'], '.brain_irom'))
        if s['name'] == '.wram_text':
            for cf in brain.get('cf.bin', []):
                if raw.startswith(cf):
                    bspans.append((s['addr'], s['addr'] + len(cf), 'cf.bin'))
                    for ro in brain.get('rodata.bin', []):
                        k = raw.find(ro)
                        if k >= len(cf) and not any(raw[len(cf):k]):
                            bspans.append((s['addr'] + k, s['addr'] + k + len(ro), 'rodata.bin'))
                    break
    execs = [(s['addr'], s['addr'] + s['size']) for s in secs if s['exec']]
    starts = [sy['value'] for sy in syms]

    def sym_at(x):
        best = None
        for j in range(bisect.bisect_right(starts, x) - 1, max(-1, bisect.bisect_right(starts, x) - 200), -1):
            sy = syms[j]
            if sy['value'] <= x < sy['value'] + sy['size'] and (best is None or sy['size'] < best['size']):
                best = sy
        return best['name'] if best else '(no symbol)'

    def sec_at(x):
        for s in secs:
            if s['addr'] <= x < s['addr'] + s['size']:
                return s
        return None

    out = []
    for h in hits:
        part, n = h['part'], h['len']
        base, b = mem[part]
        if base is None:
            out.append((False, 'file bytes the stub does not place', part, h['addr'], '-'))
            continue
        a0 = base + h['addr']
        w = b[h['addr']:h['addr'] + n]
        sym = sym_at(a0)
        sec = sec_at(a0)
        if any(lo <= a0 and a0 + n <= hi for lo, hi, _ in bspans):
            out.append((True, 'the brain\'s own bytes', part, a0, sym))
        elif h['ref'] in rv32refs and any(lo <= a0 and a0 + n <= hi for lo, hi in execs):
            out.append((True, 'code, against a brain file (the ELF method scans code only against the others)', part, a0, sym))
        # A window over an allowed table is allowed when its other bytes are all zero
        # (B Jam's decision of 2026-10-30).
        elif any(lo < a0 + n and a0 < hi for lo, hi, _ in objs) and \
                all(w[i] == 0 or any(lo <= a0 + i < hi for lo, hi, _ in objs) for i in range(n)):
            out.append((True, 'an allowed table (its bytes and zero bytes only)', part, a0, sym))
        elif sec is None:
            out.append((False, 'outside every ELF section', part, a0, sym))
        else:
            data = not sec['exec'] and a0 + n <= sec['addr'] + sec['size']
            out.append((False, '%s, %s' % (sec['name'], 'data: the image\'s own bytes' if data else 'code or across sections'),
                        part, a0, sym))
    return out, objs, bspans


def cmd_leak(a):
    lg = swap16(open(a.file, 'rb').read())
    parts = memorder(lg)
    guard = os.path.join(HERE, 'leakguard.py')
    loc_p = os.path.join(ROOT, 'paths.local.json')
    loc = json.load(open(loc_p)) if os.path.exists(loc_p) else {}
    bdirs = [os.environ.get('PAPRIUM_BRAIN_DIR') or loc.get('brain_dir'), os.environ.get('PAPRIUM_BRAIN_DIR_S1') or loc.get('brain_dir_s1')]
    try:
        secs, syms = elf_view(list(a.elf), a.sram_elf)
    except FileNotFoundError as e:
        print('SETUP ERROR: no ELF %s' % e)
        sys.exit(2)
    work = a.keep or tempfile.mkdtemp(prefix='fafleak_')
    try:
        write_memorder(lg, work)
        cmd = [sys.executable, '-I', '-B', guard, '--no-tree', '--no-built', '--json', os.path.join(work, 'guard.json')]
        for name, _, _, _ in parts:
            cmd += ['--extra-section', os.path.join(work, name + '.bin')]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 2 or not os.path.exists(os.path.join(work, 'guard.json')):
            print(r.stdout + r.stderr)
            print('SETUP ERROR: the leak guard could not run')
            sys.exit(2)
        rep = json.load(open(os.path.join(work, 'guard.json')))
    finally:
        if not a.keep:
            shutil.rmtree(work, ignore_errors=True)
    hits = [dict(h, part=os.path.basename(h['elf'])[:-4]) for h in rep['hits'] + rep.get('allowed_hits', [])]
    cfg = json.load(open(os.path.join(HERE, 'leakguard.json')))
    rv32 = {k for k, r in cfg['references'].items() if r['rv32']}
    rv32 |= {k + ' (16-bit swapped)' for k in rv32}
    man = json.load(open(os.path.join(ROOT, 'fwbuild.json')))
    brain = {}                                    # the brain files of both brain directories, for the exact compares
    for fn in man['brain']['files']:
        if cfg.get('brain_rv32', True):
            rv32 |= {fn, 's1 ' + fn}
        for d in bdirs:
            p = os.path.join(d or '', fn)
            if d and os.path.isfile(p):
                brain.setdefault(fn, []).append(open(p, 'rb').read())
    allow = json.load(open(os.path.join(HERE, 'leak_allow.json'))).get('entries', [])
    res, objs, bspans = classify(hits, parts, secs, syms, allow, brain, rv32)
    out = [dict(ref=h['ref'], ref_offset=h['ref_offset'], len=h['len'], allowed=ok, why=why, part=part,
                at=('%08x' % at) if part not in ('header', 'tail') else '+%x' % at, symbol=sym)
           for h, (ok, why, part, at, sym) in zip(hits, res)]
    bad = [x for x in out if not x['allowed']]
    summ = {}
    for x in out:
        key = '%s | %s | %s %s' % ('allowed' if x['allowed'] else 'HIT', x['why'], x['part'], x['symbol'])
        summ[key] = summ.get(key, 0) + 1
    info = {'file': os.path.basename(a.file), 'md5': md5b(open(a.file, 'rb').read()),
            'parts': [(n, None if ad is None else '%08x' % ad, len(b), md5b(b)) for n, ad, _, b in parts],
            'references': rep['references'], 'raw_hits': len(out), 'outside': len(bad),
            'allowed_tables': ['%s [%08X, %08X)' % (s, lo, hi) for lo, hi, s in objs],
            'brain_parts': ['%s [%08X, %08X)' % (s, lo, hi) for lo, hi, s in bspans],
            'by_place': summ, 'hits': out}
    if a.json:
        with open(a.json, 'w', newline='\n') as f:
            json.dump(info, f, indent=1)
    print('leak: %s, %d raw hits in memory order; allowed tables %s; brain parts %s' % (
        info['file'], len(out), info['allowed_tables'] or 'none', info['brain_parts'] or 'none (a no-brain file)'))
    for k in sorted(summ, key=lambda k: (k.startswith('allowed'), -summ[k], k)):
        print('  %6d  %s' % (summ[k], k))
    print('LEAK', 'PASS (0 hits outside the allowed places)' if not bad else
          'FAIL: %d hits outside the allowed places' % len(bad))
    sys.exit(1 if bad else 0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('stub')
    p.add_argument('--out', required=True)
    p.add_argument('--gcc-bin')
    p.add_argument('--install')
    p = sub.add_parser('make')
    p.add_argument('--img', required=True)
    p.add_argument('--sram')
    p.add_argument('--out', default=OUT_NAME, help='default: %s, the name the Pocket loads' % OUT_NAME)
    p.add_argument('--kind', default='release', choices=('release', 'test'))
    p.add_argument('--brain', action='store_true')
    p.add_argument('--version', default=FW_VERSION, help='the firmware version, MAJOR.MINOR (default %s)' % FW_VERSION)
    p.add_argument('--build', default='0')
    p.add_argument('--epoch', default='%x' % EPOCH)
    p.add_argument('--json')
    p = sub.add_parser('check')
    p.add_argument('file')
    p.add_argument('--img', required=True)
    p.add_argument('--sram')
    p.add_argument('--epoch', default='%x' % EPOCH, help='the target bitstream\'s epoch (default: this tree\'s)')
    p = sub.add_parser('show')
    p.add_argument('file')
    p = sub.add_parser('bad')
    p.add_argument('file')
    p.add_argument('kind', choices=BADS)
    p.add_argument('out')
    p = sub.add_parser('memorder')
    p.add_argument('file')
    p.add_argument('--out', required=True)
    p = sub.add_parser('leak')
    p.add_argument('file')
    p.add_argument('--elf', action='append', required=True, help='the build\'s main.elf (and ovl/ovl.elf if it has one)')
    p.add_argument('--sram-elf', help='the ELF of the SRAM code')
    p.add_argument('--json')
    p.add_argument('--keep', help='write the memory-order copy here and keep it (default: a temporary directory)')
    a = ap.parse_args()
    {'stub': cmd_stub, 'make': cmd_make, 'check': cmd_check, 'show': cmd_show, 'bad': cmd_bad,
     'memorder': cmd_memorder, 'leak': cmd_leak}[a.cmd](a)


if __name__ == '__main__':
    main()
