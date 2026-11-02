#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""gen_chip_tables.py - the cart chip's start-up tables and its output curve, generated.

    python -I -B gen_chip_tables.py                 # (re)write chip_tables.h / chip_tables.c next to this file
    python -I -B gen_chip_tables.py --out DIR       # write them into DIR instead
    python -I -B gen_chip_tables.py --bin-dir DIR   # also write raw little-endian images of the tables
    python -I -B gen_chip_tables.py --mif DIR       # also write the curve knee as a Quartus .mif (11-bit words)

No value here comes from the cart program's bytes. The tables were worked out from our own study of how the cart
behaves and checked on hardware. The cart chip is the STM32 microcontroller on the real cartridge. The tables: two
pan tables, the level table T, the three sample expansion (companding) tables of the wave voices and the sound
effects, and the output soft-clip curve.

The arithmetic is done at 60 digits (Python's decimal module), so the result does not depend on the host's math
library; the generator stops if a rounding comes too close to call.

The level table T is not written into the image: chip_tables.c gets the RAM array and chip_level_init, which the
firmware runs at power-on. build() runs that same loop here and stops unless it gives the exact table entry for entry;
tests/equiv/leveltab.py checks the firmware's RAM against it.
"""
import argparse
import os
import sys
from decimal import Decimal, getcontext, ROUND_CEILING, ROUND_FLOOR

getcontext().prec = 60
HERE = os.path.dirname(os.path.abspath(__file__))
MARGIN_GATE = Decimal('1e-30')
_margins = {}


def _note_margin(name, d):
    """distance of d from the nearest integer; keep the smallest per table"""
    frac = d - d.to_integral_value(rounding=ROUND_FLOOR)
    dist = min(frac, 1 - frac)
    if name not in _margins or dist < _margins[name]:
        _margins[name] = dist


def _ceil(name, d):
    if d != d.to_integral_value():
        _note_margin(name, d)
    return int(d.to_integral_value(rounding=ROUND_CEILING))


def _floor(name, d):
    if d != d.to_integral_value():
        _note_margin(name, d)
    return int(d.to_integral_value(rounding=ROUND_FLOOR))


def _tdiv(a, b):
    """C integer division: truncates toward zero"""
    q = abs(a) // abs(b)
    return q if (a >= 0) == (b >= 0) else -q


def _s16(v):
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


# --------------------------------------------------------------------------------------------- pan tables
def pan_table(shift, sub, top):
    """one pan table (A or B)"""
    t = [0] * 256
    for r in range(128):
        t[127 - r] = ((r >> shift) - sub) & 0xFF
    t[0] = t[1] = 0xFF
    for m in range(128):
        t[255 - m] = ((top * (m + 1)) >> 7) & 0xFF
    t[255] = 0
    t[128] = top
    return t


# --------------------------------------------------------------------------------------------- level table T
def level_table():
    """the level table T"""
    t = [0] * 512
    for n in range(0, -255, -1):
        v = _ceil('level_T', (Decimal(n) / 64).exp() * 256)
        t[255 + n] = 255 if v > 255 else (0 if v < 0 else v)
    t[0] = t[1] = 0
    for j in range(256):
        t[256 + j] = 255 + j
    return t


LEVEL_STEP = 2114190000                    # chip_level_init's CHIP_LEVEL_STEP


def level_table_int():
    """chip_level_init's loop, as the firmware runs it; also its largest error against the exact table"""
    t, x, err = [0] * 512, 256 << 23, Decimal(0)
    for k in range(255, 1, -1):
        err = max(err, abs(Decimal(x) / (1 << 23) - (Decimal(k - 255) / 64).exp() * 256))
        c = (x + (1 << 23) - 1) >> 23
        t[k] = 255 if c > 255 else c
        x = (x * LEVEL_STEP) >> 31
    for j in range(256):
        t[256 + j] = 255 + j
    return t, err


# --------------------------------------------------------------------------------------------- companding tables
def expand_tables():
    """the sample expansion (companding) tables: the wave voices', the 8-bit and the 4-bit sound effects'"""
    x = [0] * 256
    for n in range(0, -127, -1):
        e = _ceil('expand', (Decimal(n) / 32).exp() * 32768)
        v = e - _tdiv(-472 * n, 100)
        x[255 + n] = 32767 if v > 32767 else (0 if v < 0 else v)
    x[128] = 0
    x[255] = 0x7FFF
    if not x[254] > 29999:
        raise SystemExit('chip sanity check X[254] > 29999 fails (the chip would hang here)')
    for j in range(127):
        x[127 - j] = _s16(-x[128 + j])
    x[0] = -32768
    s4 = [_s16(_tdiv(x[16 * j] * 150, 100)) for j in range(16)]
    s4[7] = _s16(-s4[9])
    s4[8] = 0
    for j in range(1, 7):
        s4[7 - j] = _s16(-s4[9 + j])
    s4[1] = _s16(-s4[15])
    s4[0] = s4[1]
    wave = [_s16(_tdiv(v * 10, 426)) for v in x]
    sfx8 = [_s16(_tdiv(_tdiv(v * 10, 426) * 110, 100)) for v in x]
    sfx4 = [_s16(_tdiv(_tdiv(v * 10, 426) * 110, 100)) for v in s4]
    return wave, sfx8, sfx4


# --------------------------------------------------------------------------------------------- output curve
CURVE_KNEE_N = 2464        # the stored part of the curve
CURVE_PLATEAU = 1951


def _tanh(z):
    e = (2 * z).exp()
    return (e - 1) / (e + 1)


def curve_F(m):
    """one entry of the soft-clip curve's positive half"""
    if 2 * m + 1 <= 1024:
        q = 2 * m + 1
    else:
        z = (Decimal(2 * m + 1) - 1024) / 1024
        q = _floor('curve', 1024 + 1024 * _tanh(z))
    return (61 * q) >> 6


def curve_knee():
    knee = [curve_F(m) for m in range(CURVE_KNEE_N)]
    # every entry after the stored part has the plateau value
    for m in range(CURVE_KNEE_N, 8193):
        if curve_F(m) != CURVE_PLATEAU:
            raise SystemExit('curve plateau claim fails at m=%d' % m)
    if knee[-1] == CURVE_PLATEAU:
        raise SystemExit('curve knee length is not minimal')
    return knee


def curve_full(knee):
    """all 16,384 entries (index 8192 = input 0), through the same rule as chip_out_curve()"""
    out = []
    for idx in range(16384):
        x = idx - 8192
        m = -x if x < 0 else x
        f = knee[m] if m < CURVE_KNEE_N else CURVE_PLATEAU
        out.append(2047 - f if x < 0 else 2047 + f)
    return out


# --------------------------------------------------------------------------------------------- writers
def c_array(ctype, name, vals, per_line, fmt):
    lines = ['const %s %s[%d] = {' % (ctype, name, len(vals))]
    for i in range(0, len(vals), per_line):
        lines.append('    ' + ', '.join(fmt(v) for v in vals[i:i + per_line]) + ',')
    lines.append('};')
    return '\n'.join(lines)


HEADER = """/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* chip_tables.h - GENERATED by gen_chip_tables.py, do not edit.
 *
 * The cart chip's start-up tables and its output soft-clip curve (see gen_chip_tables.py and README.md). The tables
 * were worked out from our own study of how the cart behaves and checked on hardware.
 */
#ifndef CHIP_TABLES_H
#define CHIP_TABLES_H

#include <stdint.h>

/* the two pan tables (an odd-looking entry is the cart chip's own value, kept) */
extern const uint8_t  chip_pan_A[256];
extern const uint8_t  chip_pan_B[256];

/* the level table T, built in working RAM at power-on by chip_level_init (the firmware's boot); the image holds
 * the loop, not the table */
extern uint16_t chip_level_T[512];
#define CHIP_LEVEL_STEP     2114190000u     /* the loop's step */
void chip_level_init(void);

/* the sample expansion (companding) tables of the wave voices and the sound effects */
extern const int16_t  chip_wave_expand[256];
extern const int16_t  chip_sfx8_expand[256];
extern const int16_t  chip_sfx4_expand[16];

/* the output soft-clip curve: 16,384 x 12-bit, index 8192 = input 0; only a part of it is stored */
#define CHIP_CURVE_KNEE_N   %(KNEE_N)d
#define CHIP_CURVE_PLATEAU  %(PLATEAU)d
extern const uint16_t chip_out_curve_knee[CHIP_CURVE_KNEE_N];

/* the curve's entry idx, idx = 0..16383 (callers keep it in range) */
static inline uint16_t chip_out_curve(unsigned idx)
{
    int x = (int)idx - 8192;
    unsigned m = (unsigned)(x < 0 ? -x : x);
    unsigned f = m < CHIP_CURVE_KNEE_N ? chip_out_curve_knee[m] : CHIP_CURVE_PLATEAU;
    return (uint16_t)(x < 0 ? 2047 - f : 2047 + f);
}

#endif
"""


LEVEL_C = """/* the level table T, built at power-on with integers only, no floating point (gen_chip_tables.py runs this
   loop against the exact table; tests/equiv/leveltab.py checks the firmware's RAM). wram_upper: crt0 clears it after
   the boot overlay, and the boot calls this after that clear on every MCU start */
uint16_t chip_level_T[512] __attribute__((section(".bss_upper")));

#ifndef CHIP_LEVEL_BUG
#define CHIP_LEVEL_BUG 0
#endif
void chip_level_init(void)
{
    uint32_t x = 256u << 23, c, k;
    for (k = 255u; k >= 2u; k--) {
#if CHIP_LEVEL_BUG == 1
        c = (x + (1u << 22)) >> 23;                 /* planted (tests/equiv/leveltab.py): a wrong rounding */
#else
        c = (x + ((1u << 23) - 1u)) >> 23;
#endif
        chip_level_T[k] = (uint16_t)(c > 255u ? 255u : c);
        x = (uint32_t)(((uint64_t)x * CHIP_LEVEL_STEP) >> 31);
    }
    chip_level_T[0] = chip_level_T[1] = 0u;
    for (k = 0u; k < 256u; k++)
        chip_level_T[256u + k] = (uint16_t)(255u + k);
}"""


def write_c(out_dir, tabs):
    h = HEADER % {'KNEE_N': CURVE_KNEE_N, 'PLATEAU': CURVE_PLATEAU}
    parts = ['/* Copyright (C) 2026 Marsupial Solutions LLC',
             '   SPDX-License-Identifier: GPL-3.0-or-later */',
             '/* chip_tables.c - GENERATED by gen_chip_tables.py, do not edit. See chip_tables.h. */',
             '#include "chip_tables.h"', '']
    parts.append(c_array('uint8_t', 'chip_pan_A', tabs['pan_A'], 16, lambda v: '%3d' % v))
    parts.append('')
    parts.append(c_array('uint8_t', 'chip_pan_B', tabs['pan_B'], 16, lambda v: '%3d' % v))
    parts.append('')
    parts.append(LEVEL_C)
    parts.append('')
    parts.append(c_array('int16_t', 'chip_wave_expand', tabs['wave_expand'], 16, lambda v: '%4d' % v))
    parts.append('')
    parts.append(c_array('int16_t', 'chip_sfx8_expand', tabs['sfx8_expand'], 16, lambda v: '%4d' % v))
    parts.append('')
    parts.append(c_array('int16_t', 'chip_sfx4_expand', tabs['sfx4_expand'], 16, lambda v: '%4d' % v))
    parts.append('')
    parts.append(c_array('uint16_t', 'chip_out_curve_knee', tabs['curve_knee'], 16, lambda v: '%4d' % v))
    parts.append('')
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, 'chip_tables.h'), 'w', newline='\n') as fh:
        fh.write(h)
    with open(os.path.join(out_dir, 'chip_tables.c'), 'w', newline='\n') as fh:
        fh.write('\n'.join(parts))


def write_bins(bin_dir, tabs):
    import struct
    os.makedirs(bin_dir, exist_ok=True)
    spec = [('pan_A', 'B'), ('pan_B', 'B'), ('level_T', 'H'), ('wave_expand', 'h'), ('sfx8_expand', 'h'),
            ('sfx4_expand', 'h'), ('curve_knee', 'H'), ('curve_full', 'H')]
    for name, code in spec:
        v = tabs[name]
        with open(os.path.join(bin_dir, name + '.bin'), 'wb') as fh:
            fh.write(struct.pack('<%d%s' % (len(v), code), *v))


def write_mif(mif_dir, knee):
    os.makedirs(mif_dir, exist_ok=True)
    lines = ['-- GENERATED by gen_chip_tables.py: output curve knee F(m), m = 0..%d (11 bits)' % (len(knee) - 1),
             'WIDTH=11;', 'DEPTH=%d;' % len(knee), 'ADDRESS_RADIX=DEC;', 'DATA_RADIX=DEC;', 'CONTENT BEGIN']
    lines += ['  %d : %d;' % (a, v) for a, v in enumerate(knee)]
    lines.append('END;')
    with open(os.path.join(mif_dir, 'chip_out_curve_knee.mif'), 'w', newline='\n') as fh:
        fh.write('\n'.join(lines) + '\n')


def build():
    wave, sfx8, sfx4 = expand_tables()
    knee = curve_knee()
    tabs = {'pan_A': pan_table(2, 0x1F, 0xE0), 'pan_B': pan_table(3, 0x3F, 0xC0), 'level_T': level_table(),
            'wave_expand': wave, 'sfx8_expand': sfx8, 'sfx4_expand': sfx4, 'curve_knee': knee,
            'curve_full': curve_full(knee)}
    ti, err = level_table_int()
    if ti != tabs['level_T'] or err > Decimal('3e-5'):
        raise SystemExit('level_T: chip_level_init\'s integer loop does not give the exact table (largest error %s)' % err)
    _margins['level_T fixed point error'] = err
    for name, d in _margins.items():
        if name.endswith('error'):
            continue
        if d < MARGIN_GATE:
            raise SystemExit('%s: a rounding argument is within %s of an integer' % (name, d))
    return tabs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=HERE)
    ap.add_argument('--bin-dir')
    ap.add_argument('--mif')
    a = ap.parse_args()
    tabs = build()
    write_c(a.out, tabs)
    if a.bin_dir:
        write_bins(a.bin_dir, tabs)
    if a.mif:
        write_mif(a.mif, tabs['curve_knee'])
    for name, d in sorted(_margins.items()):
        if name.endswith('error'):
            print('chip_level_init\'s integer loop == the exact level table; its largest fixed-point error %.3e' % d)
            continue
        print('min distance of a rounding argument from an integer, %-8s %.3e' % (name, d))
    print('wrote', os.path.join(a.out, 'chip_tables.c'), 'and chip_tables.h')


if __name__ == '__main__':
    main()
