#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""mkld.py - generate the Pocket linker script for a layout JSON (board/pocket/link/pocket72k.json).

    python -I -B tools/mkld.py <layout.json> <out.ld>
    python -I -B tools/mkld.py <layout.json> --check <existing.ld>     (exit 1 if regenerating would change it)

The script keeps the NEORV32 section recipe that the 0.2.6 legacy54k.ld uses (.text.boot first, the two .rodata
statements, .data with the small-data groups and __global_pointer$, crt0's symbols) and changes only where things go:

  irom_lo   .text (everything not listed for irom_hi)                       crt0 must start at 0x0
  brain     .brain_irom at its fixed address, ASSERTed to end exactly at brain_end
  irom_hi   .text_hi (the "irom_hi_text" input sections), .rodata, and the .data load image
  WRAM      .data/.bss/.noinit in wram_data; .bss_noclear ("sched_noclear") in wram_sched, NOT cleared by crt0;
            .wram_text (cf.bin first, then the glue, then the "wcode_text" input sections) at cf_base in wcode;
            .bss_upper (input sections .bss_upper.*, and the whole .bss / .sbss of the "upper_bss_objects",
            excluded from .bss: pocket88k's song engine state) in wram_upper, cleared by the new firmware's crt0
            (board/pocket/s1_crt0.S); nothing of 0.2.6 goes there. The stack top is at stack_begin.
Every boundary is a MEMORY region, so an overflow is a link error, and ASSERTs pin the fixed addresses."""
import json, sys

NL = '\n'


def h(x):
    return int(x, 0)


def gen(lay):
    R = {r['name']: (h(r['lo']), h(r['hi'])) for r in lay['regions']}
    for need in ('irom_lo', 'brain', 'irom_hi', 'wram_data', 'brain_data', 'wram_sched', 'wcode', 'wram_upper', 'stack'):
        assert need in R, need
    rom_top = 1024 * (lay['irom']['rom0_kb'] + lay['irom']['ext_kb'])
    wram_top = h(lay['wram']['base']) + 1024 * lay['wram']['kb']
    assert R['irom_lo'][0] == 0 and R['irom_lo'][1] == R['brain'][0] and R['brain'][1] == R['irom_hi'][0]
    assert R['irom_hi'][1] == rom_top, (hex(R['irom_hi'][1]), hex(rom_top))
    assert R['stack'][1] == wram_top
    order = ['wram_data', 'brain_data', 'wram_sched', 'wcode', 'wram_upper', 'stack']
    for x, y in zip(order, order[1:]):
        assert R[x][1] == R[y][0], (x, y)
    assert h(lay['brain_end']) == R['brain'][1]
    assert h(lay['cf_base']) == R['wcode'][0]
    sb = h(lay['stack_begin']); assert R['stack'][0] < sb < R['stack'][1] and sb % 4 == 0
    rod = lay.get('rodata_region', 'irom_lo'); dld = lay.get('data_load_region', 'irom_lo')
    assert rod in ('irom_lo', 'irom_hi') and dld in ('irom_lo', 'irom_hi')

    def mem(name, attr, lohi):
        lo, hi = lohi
        return '  %-10s (%s) : ORIGIN = 0x%08X, LENGTH = 0x%X' % (name, attr, lo, hi - lo)

    def lines(xs, ind='    '):
        return ''.join(ind + x + NL for x in xs)

    hi_text = lay.get('irom_hi_text', [])
    wc_text = lay.get('wcode_text', [])
    noclear = lay.get('sched_noclear', [])
    upper = lay.get('upper_bss_objects', [])
    ex = ('EXCLUDE_FILE(%s) ' % ' '.join(upper)) if upper else ''     # (it applies to the one pattern after it)
    up_lines = ''.join('    %s(.sbss .sbss.* .bss .bss.* COMMON)' % o + NL for o in upper)
    sram_mem, sram_sec = '', ''
    sr = lay.get('sram')
    if sr:      # MegaWire: the SRAM image (it goes into the Little-Man Firmware file, tools/mkfafrium.py) and the
                # MegaWire RAM, docs/MCU_INTERFACE.md section 3.7
        il, ih = h(sr['img'][0]), h(sr['img'][1]); rl, rh = h(sr['ram'][0]), h(sr['ram'][1])
        assert il == 0x08000000 and ih <= 0x08010000 and ih <= rl < rh <= 0x08020000, sr
        sram_mem = NL + mem('sram_img', 'rx', (il, ih)) + NL + mem('sram_ram', 'rw', (rl, rh))
        sram_sec = f"""
  /* MegaWire: the SRAM image, carried in the Little-Man Firmware file (docs/MCU_INTERFACE.md section 3.7): its
     64-byte header (magic, version, length, the hot part's CRC-32, link id, the hot end, the cold part's CRC-32;
     tools/mkimage.py --sram fills length and both CRC-32s) at the image's start, then the listed input sections (code
     and rodata run in place): the hot part, then the cold part, both checked by the thread's first work after the
     68000's release (core/mw/mw_boot.c, board/pocket/s3_sram.c). Before .text so that .text's wildcards do not take
     them. */
  .sram_hdr 0x{il:08X} :
  {{
    KEEP(*(.sram_hdr))
  }} > sram_img
  .sram_text :
  {{
    PROVIDE(__sram_text_start = .);
{lines(sr['text'])}    . = ALIGN(4);
    PROVIDE(__sram_hot_end = .);
{lines(sr.get('cold', []))}    . = ALIGN(4);
    PROVIDE(__sram_img_end = .);
  }} > sram_img
  /* the MegaWire RAM: never loaded, cleared by the MegaWire init that the image's check lets run */
  .sram_bss (NOLOAD) :
  {{
    PROVIDE(__sram_bss_start = .);
    *(.sram_bss .sram_bss.*)
    . = ALIGN(4);
    PROVIDE(__sram_bss_end = .);
  }} > sram_ram
  PROVIDE(__sram_hot_off = ABSOLUTE(__sram_hot_end) - 0x{il:08X});   /* the header's hot end: an offset, so no data
                                                                          word there equals a function's address */
  ASSERT(SIZEOF(.sram_text) == 0 || (ADDR(.sram_hdr) == 0x{il:08X} && SIZEOF(.sram_hdr) == 64),
         "paprium-fw: an SRAM image needs its 64-byte header at its start")
"""
    src = f"""/* ################################################################################################# */
/* # << NEORV32 - RISC-V GCC Linker Script >>                                                      # */
/* # ********************************************************************************************* # */
/* # BSD 3-Clause License                                                                          # */
/* #                                                                                               # */
/* # Copyright (c) 2020, Stephan Nolting. All rights reserved.                                     # */
/* #                                                                                               # */
/* # Redistribution and use in source and binary forms, with or without modification, are          # */
/* # permitted provided that the following conditions are met:                                     # */
/* #                                                                                               # */
/* # 1. Redistributions of source code must retain the above copyright notice, this list of        # */
/* #    conditions and the following disclaimer.                                                   # */
/* #                                                                                               # */
/* # 2. Redistributions in binary form must reproduce the above copyright notice, this list of     # */
/* #    conditions and the following disclaimer in the documentation and/or other materials        # */
/* #    provided with the distribution.                                                            # */
/* #                                                                                               # */
/* # 3. Neither the name of the copyright holder nor the names of its contributors may be used to  # */
/* #    endorse or promote products derived from this software without specific prior written      # */
/* #    permission.                                                                                # */
/* #                                                                                               # */
/* # THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS   # */
/* # OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF               # */
/* # MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE    # */
/* # COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,     # */
/* # EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE # */
/* # GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED    # */
/* # AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING     # */
/* # NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED  # */
/* # OF THE POSSIBILITY OF SUCH DAMAGE.                                                            # */
/* # ********************************************************************************************* # */
/* # The NEORV32 Processor - https://github.com/stnolting/neorv32              (c) Stephan Nolting # */
/* ################################################################################################# */

/* Copyright (C) 2014-2020 Free Software Foundation, Inc.
   Copying and distribution of this script, with or without modification,
   are permitted in any medium without royalty provided the copyright
   notice and this notice are preserved.  */

/* paprium-fw: GENERATED by tools/mkld.py from board/pocket/link/{lay['name']}.json - edit the JSON, not this file.
   Layout {lay['name']}: IROM {lay['irom']['rom0_kb'] + lay['irom']['ext_kb']} KB (rom0 {lay['irom']['rom0_kb']} KB + extension {lay['irom']['ext_kb']} KB), brain hole 0x{R['brain'][0]:04X}-0x{R['brain'][1] - 1:04X},
   WRAM {lay['wram']['kb']} KB. See docs/LAYOUT.md. */
/* Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later) */

OUTPUT_FORMAT("elf32-littleriscv", "elf32-littleriscv", "elf32-littleriscv")
OUTPUT_ARCH(riscv)
ENTRY(_start)

MEMORY
{{
{mem('irom_lo', 'rx', R['irom_lo'])}
{mem('brain', 'rx', R['brain'])}
{mem('irom_hi', 'rx', R['irom_hi'])}
{mem('wram_data', 'rw', R['wram_data'])}
{mem('wram_sched', 'rw', R['wram_sched'])}
{mem('wcode', 'rx', R['wcode'])}
{mem('wram_upper', 'rw', R['wram_upper'])}{sram_mem}
}}
/* brain_data 0x{R['brain_data'][0]:08X}-0x{R['brain_data'][1] - 1:08X} is the brain's own (fixed by its link): no output section may use it.
   stack 0x{R['stack'][0]:08X}-0x{R['stack'][1] - 1:08X}: crt0 loads sp from __crt0_stack_begin. */

SECTIONS
{{
  __crt0_stack_begin = 0x{sb:08X};
  __stack_floor = 0x{R['stack'][0]:08X};

  /* the WRAM code window: the brain's counting helpers (cf.bin, linked at 0x{R['wcode'][0]:08X} when the brain was built)
     first, then the glue. Before .text so that these input sections are taken here, not by .text's wildcards. */
  .wram_text :
  {{
    PROVIDE(__wram_text_start = .);
    KEEP(*(.wram_cf))
    . = ALIGN(4);
    *zz_buddy.c.o(.text .text.* .rodata .rodata.* .srodata .srodata.*)
    *zz_buddy_brain.c.o(.text .text.* .rodata .rodata.* .srodata .srodata.*)
    *zz_buddy_trap.c.o(.text.zz_buddy_trap .text.zz_buddy_call)
    *s1_glue.c.o(.text .text.* .rodata .rodata.* .srodata .srodata.*)
{lines(wc_text)}    . = ALIGN(4);
    PROVIDE(__wram_text_end = .);
  }} > wcode

  /* firmware code listed for the IROM above the brain. Before .text so that .text's wildcards do not take it. */
  .text_hi :
  {{
    PROVIDE(__text_hi_start = .);
{lines(hi_text)}    . = ALIGN(4);
    PROVIDE(__text_hi_end = .);
  }} > irom_hi
{sram_sec}
  .text :
  {{
    PROVIDE(__text_start = .);
    PROVIDE(__textstart = .);
    PROVIDE_HIDDEN (__rela_iplt_start = .);
    *(.rela.iplt)
    PROVIDE_HIDDEN (__rela_iplt_end = .);
    *(.rela.plt)
    KEEP(*(.text.boot)); /* crt0: start-up code at the beginning of the IROM */
    KEEP (*(SORT_NONE(.init)))
    *(.text.unlikely .text.*_unlikely .text.unlikely.*)
    *(.text.exit .text.exit.*)
    *(.text.startup .text.startup.*)
    *(.text.hot .text.hot.*)
    *(SORT(.text.sorted.*))
    *(.text .stub .text.* .gnu.linkonce.t.*)
    *(.gnu.warning)
    KEEP (*(SORT_NONE(.fini)))
    KEEP (*crtbegin.o(.ctors))
    KEEP (*crtbegin?.o(.ctors))
    KEEP (*(EXCLUDE_FILE (*crtend.o *crtend?.o ) .ctors))
    KEEP (*(SORT(.ctors.*)))
    KEEP (*(.ctors))
    KEEP (*crtbegin.o(.dtors))
    KEEP (*crtbegin?.o(.dtors))
    KEEP (*(EXCLUDE_FILE (*crtend.o *crtend?.o ) .dtors))
    KEEP (*(SORT(.dtors.*)))
    KEEP (*(.dtors))
    . = ALIGN(4);
    PROVIDE (__etext = .);
    PROVIDE (_etext = .);
    PROVIDE (etext = .);
  }} > irom_lo

  /* read-only data */
  .rodata         : {{ *(.rodata .rodata.* .gnu.linkonce.r.*) }} > {rod}
  .rodata1        : {{ *(.rodata1) }} > {rod}
  .rodata_arrays :
  {{
    PROVIDE_HIDDEN (__init_array_start = .);
    KEEP (*(SORT_BY_INIT_PRIORITY(.init_array.*) SORT_BY_INIT_PRIORITY(.ctors.*)))
    KEEP (*(.init_array EXCLUDE_FILE (*crtbegin.o *crtbegin?.o *crtend.o *crtend?.o ) .ctors))
    PROVIDE_HIDDEN (__init_array_end = .);
    PROVIDE_HIDDEN (__fini_array_start = .);
    KEEP (*(SORT_BY_INIT_PRIORITY(.fini_array.*) SORT_BY_INIT_PRIORITY(.dtors.*)))
    KEEP (*(.fini_array EXCLUDE_FILE (*crtbegin.o *crtbegin?.o *crtend.o *crtend?.o ) .dtors))
    PROVIDE_HIDDEN (__fini_array_end = .);
    . = ALIGN(4);
  }} > {rod}

  /* initialised read/write data: runs in WRAM, its image sits in the IROM, crt0 copies it */
  .data :
  {{
    __DATA_BEGIN__ = .;
    __SDATA_BEGIN__ = .;
    *(.sdata2 .sdata2.* .gnu.linkonce.s2.*)
    *(.data .data.* .gnu.linkonce.d.*)
    SORT(CONSTRUCTORS)
    *(.srodata.cst16) *(.srodata.cst8) *(.srodata.cst4) *(.srodata.cst2) *(.srodata .srodata.*)
    *(.sdata .sdata.* .gnu.linkonce.s.*)
    PROVIDE_HIDDEN (__tdata_start = .);
    *(.tdata .tdata.* .gnu.linkonce.td.*)
    . = ALIGN(4);
    _edata = .; PROVIDE (edata = .);
    . = .;
  }} > wram_data AT > {dld}

  .sbss2          : {{ *(.sbss2 .sbss2.* .gnu.linkonce.sb2.*) }} > wram_data
  .tbss           : {{ *(.tbss .tbss.* .gnu.linkonce.tb.*) *(.tcommon) }} > wram_data

  /* .bss objects whose initial contents are never read: in the scheduler gap, NOT cleared by crt0 (outside
     __bss_start..__BSS_END__). Before .bss so that .bss's wildcards do not take them. */
  .bss_noclear (NOLOAD) :
  {{
    PROVIDE(__bss_noclear_start = .);
{lines(noclear)}    . = ALIGN(4);
    PROVIDE(__bss_noclear_end = .);
  }} > wram_sched

  .bss (NOLOAD) :
  {{
    __bss_start = .;
    *(.dynsbss)
    *({ex}.sbss {ex}.sbss.* {ex}.gnu.linkonce.sb.*)
    *(.scommon)
    *(.dynbss)
    *({ex}.bss {ex}.bss.* {ex}.gnu.linkonce.b.*)
    PROVIDE_HIDDEN (__preinit_array_start = .);
    KEEP (*(.preinit_array))
    PROVIDE_HIDDEN (__preinit_array_end = .);
    *(COMMON)
    . = ALIGN(. != 0 ? 32 / 8 : 1);
    . = ALIGN(32 / 8);
    __BSS_END__ = .;
    __global_pointer$ = MIN(__SDATA_BEGIN__ + 0x800,
                            MAX(__DATA_BEGIN__ + 0x800, __BSS_END__ - 0x800));
    _end = .; PROVIDE (end = .);
  }} > wram_data

  /* the buddy glue's state: not cleared by crt0 (zz_buddy.c clears it at the first event of a boot) */
  .noinit (NOLOAD) :
  {{
    *(.noinit.zz_buddy)
    *(.noinit .noinit.*)
    . = ALIGN(16);
    PROVIDE(__noinit_end = .);
  }} > wram_data

  /* the s1 images: .bss objects placed in wram_upper (input sections .bss_upper.*); the s1 crt0 clears them */
  .bss_upper (NOLOAD) :
  {{
    PROVIDE(__bss_upper_start = .);
    *(.bss_upper .bss_upper.*)
{up_lines}    . = ALIGN(4);
    PROVIDE(__bss_upper_end = .);
  }} > wram_upper

  /* the CPU MATE brain (rodata + text, assembled for 0x{R['brain'][0]:X}): bytes never relinked */
  .brain_irom 0x{R['brain'][0]:X} :
  {{
    PROVIDE(__brain_irom_start = .);
    KEEP(*(.brain_irom .brain_irom.*))
    . = ALIGN(4);
    PROVIDE(__brain_irom_end = .);
  }} > brain

  ASSERT(__brain_irom_start == 0x{R['brain'][0]:X} && __brain_irom_end == 0x{R['brain'][1]:X},
         "paprium-fw: the brain must fill 0x{R['brain'][0]:X}-0x{R['brain'][1] - 1:X} exactly (bytes unchanged)")
  ASSERT(ADDR(.wram_text) == 0x{R['wcode'][0]:08X}, "paprium-fw: cf.bin must sit at the code window's start")
  ASSERT(ADDR(.text) == 0, "paprium-fw: crt0 (.text.boot) must start the IROM")
  ASSERT(__noinit_end <= 0x{R['wram_data'][1]:08X}, "paprium-fw: firmware data runs into the brain's data")
  ASSERT(__wram_text_end <= 0x{R['wcode'][1]:08X}, "paprium-fw: the code window overflows")
  ASSERT(__bss_upper_start % 4 == 0 && __bss_upper_end % 4 == 0, "paprium-fw: .bss_upper must be word-aligned (crt0 clears it by words)")

  /* debug sections (not loaded) */
  .stab          0 : {{ *(.stab) }}
  .stabstr       0 : {{ *(.stabstr) }}
  .comment       0 : {{ *(.comment) }}
  .gnu.build.attributes : {{ *(.gnu.build.attributes .gnu.build.attributes.*) }}
  .debug          0 : {{ *(.debug) }}
  .line           0 : {{ *(.line) }}
  .debug_srcinfo  0 : {{ *(.debug_srcinfo) }}
  .debug_sfnames  0 : {{ *(.debug_sfnames) }}
  .debug_aranges  0 : {{ *(.debug_aranges) }}
  .debug_pubnames 0 : {{ *(.debug_pubnames) }}
  .debug_info     0 : {{ *(.debug_info .gnu.linkonce.wi.*) }}
  .debug_abbrev   0 : {{ *(.debug_abbrev) }}
  .debug_line     0 : {{ *(.debug_line .debug_line.* .debug_line_end) }}
  .debug_frame    0 : {{ *(.debug_frame) }}
  .debug_str      0 : {{ *(.debug_str) }}
  .debug_loc      0 : {{ *(.debug_loc) }}
  .debug_macinfo  0 : {{ *(.debug_macinfo) }}
  .debug_pubtypes 0 : {{ *(.debug_pubtypes) }}
  .debug_ranges   0 : {{ *(.debug_ranges) }}
  .debug_macro    0 : {{ *(.debug_macro) }}
  .debug_addr     0 : {{ *(.debug_addr) }}
  .gnu.attributes 0 : {{ KEEP (*(.gnu.attributes)) }}
  /DISCARD/ : {{ *(.note.GNU-stack) *(.gnu_debuglink) *(.gnu.lto_*) }}

  /* symbols for crt0 */
  PROVIDE(__crt0_upper_bss_start = __bss_upper_start);
  PROVIDE(__crt0_upper_bss_end   = __bss_upper_end);
  PROVIDE(__crt0_bss_start   = __bss_start);
  PROVIDE(__crt0_bss_end     = __BSS_END__);
  PROVIDE(__crt0_copy_data_src_begin = LOADADDR(.data));
  PROVIDE(__crt0_copy_data_dst_begin = __DATA_BEGIN__);
  PROVIDE(__crt0_copy_data_dst_end   = __DATA_BEGIN__ + SIZEOF(.data));
}}
"""
    return src


def main():
    lay = json.load(open(sys.argv[1]))
    src = gen(lay)
    if len(sys.argv) > 3 and sys.argv[2] == '--check':
        cur = open(sys.argv[3], 'rb').read().decode()
        if cur != src:
            print('DIFFERS: regenerate with tools/mkld.py', sys.argv[1], sys.argv[3])
            sys.exit(1)
        print('OK', sys.argv[3], 'is what', sys.argv[1], 'generates')
        return
    open(sys.argv[2], 'w', newline=NL).write(src)
    print('wrote', sys.argv[2])


if __name__ == '__main__':
    main()
