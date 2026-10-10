"""Split the Paprium MCU firmware ELF (linked with paprium_mcu.ld) into the four block-RAM init files that the RTL
reads with $readmemh (rtl/PAPRIUM/mcu_core.sv and memory.sv).

    python mkimage.py <main.elf> <out dir> [--ext-kb 22] [--objdump riscv-none-elf-objdump]

  mcu.txt      rom0, bytes 0x0000-0x7FFF of the rom image (krikzz's bin_to_verilog format: 16 words a line,
               each word = 4 bytes in address order, upper-case hex; mcu_core swaps them back)
  mcu_ext.txt  the IROM extension, bytes 0x8000.., padded to ext_kb x 256 words
  wram_hi.txt  WRAM even bytes (cell k = MCU byte 2k), 16,384 lines of 2 hex digits
  wram_lo.txt  WRAM odd bytes  (cell k = MCU byte 2k+1); zero outside the WRAM code window
The rom image is the ELF's load image of .text .rodata .data (at its LMA) .ext_text .brain_irom. Every file is
written with CRLF line ends on every platform, so the md5s match the shipped images byte for byte.
Also writes rom.bin, wcode.bin (the two load images) and image.json (sizes, md5s, sections)."""
import os, sys, subprocess, argparse, json, hashlib, struct

ap = argparse.ArgumentParser()
ap.add_argument('elf')
ap.add_argument('out')
ap.add_argument('--ext-kb', type=int, default=22)
ap.add_argument('--objdump', default='riscv-none-elf-objdump', help='for the section list in image.json only')
a = ap.parse_args()
os.makedirs(a.out, exist_ok=True)

WCODE_LO, WCODE_HI = 0x80002C00, 0x80006C00          # the WRAM code window (paprium_mcu.ld: wcode)


def sections(elf):
    try:
        r = subprocess.run([a.objdump, '-h', elf], capture_output=True, text=True, check=True).stdout.split('\n')
    except (OSError, subprocess.CalledProcessError):
        return {}
    s = {}
    for ln in r:
        p = ln.split()
        if len(p) >= 6 and p[0].isdigit():
            s[p[1] + ('' if p[1] not in s else '#2')] = dict(size=int(p[2], 16), vma=int(p[3], 16), lma=int(p[4], 16))
    return s


S = sections(a.elf)

# the load image from the PT_LOAD program headers (by physical = load address), not objcopy -j: the NEORV32 script
# has two output sections named .rodata, and a multi-section objcopy dump zero-fills the first
E = open(a.elf, 'rb').read()
assert E[:4] == b'\x7fELF' and E[4] == 1 and E[5] == 1, 'ELF32 little-endian expected'
e_phoff, = struct.unpack_from('<I', E, 28)
e_phentsize, e_phnum = struct.unpack_from('<HH', E, 42)
rom = bytearray()
wc = bytearray()
wbase = None
for i in range(e_phnum):
    p_type, p_off, p_vaddr, p_paddr, p_filesz, p_memsz, p_flags, p_align = struct.unpack_from(
        '<8I', E, e_phoff + i * e_phentsize)
    if p_type != 1 or p_filesz == 0:
        continue
    data = E[p_off:p_off + p_filesz]
    if p_paddr < 0x80000000:
        if len(rom) < p_paddr + p_filesz:
            rom.extend(b'\0' * (p_paddr + p_filesz - len(rom)))
        rom[p_paddr:p_paddr + p_filesz] = data
    elif WCODE_LO <= p_paddr < WCODE_HI:
        wbase = p_paddr if wbase is None else min(wbase, p_paddr)
        o = p_paddr - WCODE_LO
        if len(wc) < o + p_filesz:
            wc.extend(b'\0' * (o + p_filesz - len(wc)))
        wc[o:o + p_filesz] = data
    else:
        sys.exit(f'load segment at {p_paddr:#x} is neither rom nor the WRAM code window')
if wc:
    wbase = WCODE_LO
rom = bytes(rom)
open(os.path.join(a.out, 'rom.bin'), 'wb').write(rom)
open(os.path.join(a.out, 'wcode.bin'), 'wb').write(bytes(wc))
ROM0, EXT = 0x8000, 1024 * a.ext_kb
if len(rom) > ROM0 + EXT:
    sys.exit(f'rom image {len(rom)} B > rom0 + extension {ROM0 + EXT} B')


def words_txt(b, nwords=None):
    b = b + b'\0' * (-len(b) % 4)
    if nwords is not None:
        b = b + b'\0' * (4 * nwords - len(b))
    w = [b[i:i + 4].hex().upper() for i in range(0, len(b), 4)]
    # krikzz's bin_to_verilog layout, byte for byte: CRLF between lines, the last line ends in one space
    return '\r\n'.join(' '.join(w[i:i + 16]) for i in range(0, len(w), 16)) + ' '


def write(name, text):
    with open(os.path.join(a.out, name), 'wb') as f:
        f.write(text.encode('ascii'))


write('mcu.txt', words_txt(rom[:ROM0]))
write('mcu_ext.txt', words_txt(rom[ROM0:], 256 * a.ext_kb) if a.ext_kb else '')
wram = bytearray(0x8000)
if wc:
    off = wbase - 0x80000000
    assert 0x2C00 <= off and off + len(wc) <= 0x6C00, (hex(off), len(wc))
    wram[off:off + len(wc)] = wc
write('wram_hi.txt', ''.join(f'{wram[2 * k]:02X}\r\n' for k in range(0x4000)))
write('wram_lo.txt', ''.join(f'{wram[2 * k + 1]:02X}\r\n' for k in range(0x4000)))
rep = dict(rom_bytes=len(rom), rom0_used=min(len(rom), ROM0), ext_used=max(0, len(rom) - ROM0), ext_bytes=EXT,
           wram_code_bytes=len(wc), wram_code_base=hex(wbase) if wbase else None,
           md5_rom=hashlib.md5(rom).hexdigest(), md5_wcode=hashlib.md5(bytes(wc)).hexdigest(),
           sections={k: v for k, v in S.items() if v['size']})
with open(os.path.join(a.out, 'image.json'), 'w', newline='\n') as f:
    json.dump(rep, f, indent=1)
print(json.dumps({k: v for k, v in rep.items() if k != 'sections'}))
