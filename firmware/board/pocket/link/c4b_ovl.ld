/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* board/pocket/link/c4b_ovl.ld - the WRAM boot overlay (board/pocket/boot/c4b.h), linked on its own by
   tools/fwbuild.py (fwbuild.json s1.overlay) and placed in the WRAM image by tools/mkimage.py --wram-blob.

   ovl  0x80006C00-0x8000ABFF (wram_upper, 16 KB): the 16-byte header (boot_overlay_hdr: magic, length, CRC-32,
        entry; tools/fwbuild.py writes it after the link), the code (the entry first) and its rodata. Bitstream-
        initialised, read and executed in place; nothing in it is ever written (no .data: a reset in the middle
        re-enters the same bytes, and the stub checks their CRC).
   scr  0x80000000-0x800014DF: the overlay's .bss (its tables and buffers), at the start of wram_data, which crt0
        makes afresh after the overlay returns; tools/fwbuild.py checks that it ends at or below the main image's
        __BSS_END__ (so it never reaches .noinit, where the boot record lives).
   stk  0x8000AC00-0x8000B9FF: the decoder's context and sample buffer (IBSS_ATTR, -DWVPK_OVERLAY) at the floor of
        the stack region; the overlay runs on crt0's stack from 0x8000BFFC (its deepest chain ~0.7 KB, measured with
        -fstack-usage) and refuses to start if sp is not 512 B clear of this; crt0 fills the region afterwards (TEST).
   Linked without relaxation and with -msmall-data-limit=0: no gp (the main image's gp is live in crt0). */
OUTPUT_ARCH(riscv)
ENTRY(c4b_ovl_main)
MEMORY
{
  ovl (rx) : ORIGIN = 0x80006C00, LENGTH = 0x4000
  scr (rw) : ORIGIN = 0x80000000, LENGTH = 0x14E0
  stk (rw) : ORIGIN = 0x8000AC00, LENGTH = 0x0E00
}
SECTIONS
{
  .ovl_hdr :
  {
    __ovl_start = .;
    LONG(0) LONG(0) LONG(0) LONG(0)
  } > ovl
  .text :
  {
    KEEP(*(.text.c4b_entry))
    *(.text .text.*)
  } > ovl
  .rodata :
  {
    *(.rodata .rodata.* .srodata .srodata.*)
    . = ALIGN(4);
    __ovl_end = .;
  } > ovl
  .data : { *(.data .data.* .sdata .sdata.*) } > ovl
  .bss (NOLOAD) :
  {
    __ovl_bss_start = .;
    *(.bss .bss.* .sbss .sbss.* COMMON)
    . = ALIGN(4);
    __ovl_bss_end = .;
  } > scr
  .bss_stk (NOLOAD) :
  {
    __ovl_stk_start = .;
    *(.bss_stk .bss_stk.*)
    . = ALIGN(4);
    __ovl_stk_end = .;
  } > stk
  ASSERT(SIZEOF(.data) == 0, "c4b overlay: no .data (its image must not change while it runs)")
  ASSERT(__ovl_start == 0x80006C00, "c4b overlay: the header must start wram_upper")
  /DISCARD/ : { *(.comment) *(.note .note.*) *(.riscv.attributes) *(.eh_frame) }
}
