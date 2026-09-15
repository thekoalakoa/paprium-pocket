#!/usr/bin/env python3
"""Both Paprium container decoders, ported from Genesis Plus GX `paprium.h`.

    type byte 0x80 -> paprium_decoder_lz_rle  (paprium.h:817)
    type byte 0x81 -> paprium_decoder_lzo     (paprium.h:866)
    dispatch       -> paprium_decoder_type    (paprium.h:1052)

Byte order is PLAIN file order: GPGX stores the ROM byte-swapped and compensates
with `cart.rom[src^1]`, which cancels out when you read the .md file directly.

The 0x81 port is the one already inside scripts/dump_music.py (52/52 modules).
The 0x80 port is new here; it is checked against the sprite/animation container
at ROM 0x0C0000, which decodes to 518,174 bytes, and against all 328 type-0x80
assets indexed by the two "ARRR" directories - 366/366 compressed assets in the
cartridge decode without error.

    decode(rom_bytes, offset) -> (decoded_bytes, offset_just_past_the_stream)

`cap` bounds the output and `limit` bounds the source, so a speculative decode
at a wrong offset fails fast instead of eating the machine.
"""



class DecErr(Exception):
    pass


def lz_rle(d, src, cap=1 << 24, limit=None):
    """paprium_decoder_lz_rle. src points PAST the 0x80 type byte."""
    if limit is None:
        limit = len(d)
    out = bytearray()
    s = src
    while True:
        if s >= limit:
            raise DecErr("ran off end at %X" % s)
        t = d[s]; s += 1
        code = t >> 6
        ln = t & 0x3F
        if code == 0 and ln == 0:
            break
        rle = lz = 0
        if code == 1:
            rle = d[s]; s += 1
        elif code == 2:
            lz = len(out) - d[s]; s += 1
            if lz < 0:
                raise DecErr("lz back-ref before start")
        if len(out) + ln > cap:
            raise DecErr("output over cap (%d)" % cap)
        if code == 0:
            if s + ln > limit:
                raise DecErr("literal run off end")
            out += d[s:s + ln]; s += ln
        elif code == 1:
            out += bytes([rle]) * ln
        elif code == 2:
            for _ in range(ln):
                out.append(out[lz]); lz += 1
        else:
            out += b"\x00" * ln
    return bytes(out), s


def lzo(d, src, cap=1 << 24, limit=None):
    """paprium_decoder_lzo. src points PAST the 0x81 type byte."""
    if limit is None:
        limit = len(d)
    out = bytearray()
    s, state = src, 0
    while True:
        if s >= limit:
            raise DecErr("ran off end at %X" % s)
        c = d[s]; s += 1
        if c & 0x80:
            raw = c & 3; ln = ((c >> 5) & 3) + 5
            lz = ((c >> 2) & 7) + (d[s] << 3) + 1; s += 1
        elif c & 0x40:
            raw = c & 3; ln = ((c >> 5) & 1) + 3
            lz = ((c >> 2) & 7) + (d[s] << 3) + 1; s += 1
        elif c & 0x20:
            ln = c & 0x1F
            if ln == 0:
                ex = 0
                while True:
                    ln = d[s]; s += 1
                    if ln:
                        break
                    ex += 255
                    if s >= limit:
                        raise DecErr("len chain off end")
                ln += ex + 31
            ln += 2
            c = d[s]; s += 1
            raw = c & 3; lz = (c >> 2) + (d[s] << 6) + 1; s += 1
        elif c & 0x10:
            ln = c & 7
            if ln == 0:
                ex = 0
                while True:
                    ln = d[s]; s += 1
                    if ln:
                        break
                    ex += 255
                    if s >= limit:
                        raise DecErr("len chain off end")
                ln += ex + 7
            ln += 2
            lz = ((c >> 3) & 1) << 14
            c = d[s]; s += 1
            raw = c & 3; lz += (c >> 2) + (d[s] << 6) + 16384; s += 1
            if lz == 16384:
                return bytes(out), s
        else:
            if state == 0:
                raw = c & 0x0F
                if raw == 0:
                    ex = 0
                    while True:
                        raw = d[s]; s += 1
                        if raw:
                            break
                        ex += 255
                        if s >= limit:
                            raise DecErr("raw chain off end")
                    raw += ex + 15
                raw += 3; ln = 0; state = 4; lz = 0
            elif state < 4:
                raw = c & 3; lz = ((c >> 2) & 3) + (d[s] << 2) + 1; s += 1; ln = 2
            else:
                raw = c & 3; lz = ((c >> 2) & 3) + (d[s] << 2) + 2049; s += 1; ln = 3
        state = raw if ln > 0 else 4
        if len(out) + ln + raw > cap:
            raise DecErr("output over cap (%d)" % cap)
        if ln > 0:
            p = len(out) - lz
            if p < 0:
                raise DecErr("lz back-ref before start")
            for _ in range(ln):
                out.append(out[p]); p += 1
        if s + raw > limit:
            raise DecErr("literal run off end")
        out += d[s:s + raw]; s += raw


def decode(d, off, cap=1 << 24, limit=None):
    """Decode a container whose first byte is the decoder type. Returns (bytes, end_src)."""
    t = d[off]
    if t == 0x80:
        return lz_rle(d, off + 1, cap, limit)
    if t == 0x81:
        return lzo(d, off + 1, cap, limit)
    raise DecErr("not a container: type byte %02X" % t)
