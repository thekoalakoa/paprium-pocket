#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""fwelf.py - minimal ELF32 little-endian reader for the firmware tools (no toolchain needed).

    sections(path) -> [dict(name, type, flags, addr, off, size, lma, nobits, exec, alloc)]
    symbols(path)  -> [dict(name, value, size, type, bind, shndx, section)]   (.symtab only)
    load_bytes(path, addr, n) -> bytes at run address addr (from the section that holds it), or None
    relocations(path) -> [dict(off, type, sym, value, addend, section)]: the relocation records the linker kept in an ELF
                         linked with --emit-relocs (SHT_RELA sections of allocated sections only; off = the run address
                         patched, value = the symbol's value, so the patched-in target is value + addend)

type: 'FUNC', 'OBJECT', 'NOTYPE', 'SECTION', 'FILE'; bind: 'LOCAL', 'GLOBAL', 'WEAK'."""
import struct

_STT = {0: 'NOTYPE', 1: 'OBJECT', 2: 'FUNC', 3: 'SECTION', 4: 'FILE'}
_STB = {0: 'LOCAL', 1: 'GLOBAL', 2: 'WEAK'}
_CACHE = {}


def _read(path):
    if path not in _CACHE:
        E = open(path, 'rb').read()
        assert E[:4] == b'\x7fELF' and E[4] == 1 and E[5] == 1, 'not an ELF32 little-endian file: ' + path
        _CACHE[path] = E
    return _CACHE[path]


def _shdrs(E):
    e_shoff, = struct.unpack_from('<I', E, 32)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', E, 46)
    sh = [struct.unpack_from('<10I', E, e_shoff + i * e_shentsize) for i in range(e_shnum)]
    stro = sh[e_shstrndx][4]

    def name(o):
        return E[stro + o:E.index(b'\0', stro + o)].decode()
    return sh, name


def sections(path):
    E = _read(path)
    sh, name = _shdrs(E)
    e_phoff, = struct.unpack_from('<I', E, 28)
    e_phentsize, e_phnum = struct.unpack_from('<HH', E, 42)
    ph = [struct.unpack_from('<8I', E, e_phoff + i * e_phentsize) for i in range(e_phnum)]
    out = []
    for s in sh:
        nm, typ, flags, addr, off, size = name(s[0]), s[1], s[2], s[3], s[4], s[5]
        lma = addr
        if typ != 8 and flags & 2:
            for p in ph:
                if p[0] == 1 and p[1] <= off < p[1] + p[4]:
                    lma = p[3] + (off - p[1])
        out.append(dict(name=nm, type=typ, flags=flags, addr=addr, off=off, size=size, lma=lma, nobits=(typ == 8),
                        alloc=bool(flags & 2), exec=bool(flags & 4), link=s[6], info=s[7]))
    return out


def symbols(path):
    E = _read(path)
    secs = sections(path)
    out = []
    for s in secs:
        if s['type'] != 2:                         # SHT_SYMTAB
            continue
        strtab = secs[s['link']]
        for i in range(s['size'] // 16):
            st_name, st_value, st_size, st_info, st_other, st_shndx = struct.unpack_from('<IIIBBH', E, s['off'] + 16 * i)
            o = strtab['off'] + st_name
            nm = E[o:E.index(b'\0', o)].decode(errors='replace')
            sec = secs[st_shndx]['name'] if 0 < st_shndx < len(secs) else None
            out.append(dict(name=nm, value=st_value, size=st_size, type=_STT.get(st_info & 15, str(st_info & 15)),
                            bind=_STB.get(st_info >> 4, str(st_info >> 4)), shndx=st_shndx, section=sec))
    return out


def load_bytes(path, addr, n):
    E = _read(path)
    for s in sections(path):
        if s['alloc'] and not s['nobits'] and s['addr'] <= addr and addr + n <= s['addr'] + s['size']:
            o = s['off'] + addr - s['addr']
            return E[o:o + n]
    return None


def relocations(path):
    E = _read(path)
    secs = sections(path)
    out = []
    for s in secs:
        if s['type'] != 4:                         # SHT_RELA
            continue
        tgt = secs[s['info']] if 0 < s['info'] < len(secs) else None
        if not tgt or not tgt['alloc']:
            continue                               # debug info and the like
        symtab = secs[s['link']]
        for i in range(s['size'] // 12):
            r_off, r_info, r_add = struct.unpack_from('<IIi', E, s['off'] + 12 * i)
            si = r_info >> 8
            st_value, = struct.unpack_from('<I', E, symtab['off'] + 16 * si + 4)
            out.append(dict(off=r_off, type=r_info & 0xFF, sym=si, value=st_value, addend=r_add, section=tgt['name']))
    return out
