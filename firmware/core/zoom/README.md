# core/zoom: the cart chip's zoom (stage 3, test build S3a)

The zoom of the cart program, written by our team from our own study of how the cart behaves: F4's
source, job 8's save of RAMDP `$0200-$09FF` and the stamps' set-up, F5's integer rescale and its copy into RAMDP, B6's
restore. The cart chip is the STM32 microcontroller on the real cartridge; RAMDP is the cart RAM that both the 68000
and the MCU see. This replaces 0.2.6's float rescale (`interim/s1/f5_s1.c`, gone) in every image of the new firmware
(FW_S5 = 0 and FW_S5 = 1, board/board.h); the 0.2.6 milestone builds keep theirs. The dispatcher (`core/dispatch`:
F4 / F5 / B6 and the job step) was already the cart chip's; these are the job bodies.

| function | cart chip routine | does |
|---|---|---|
| `job_scale_save` | 0x08022CD0 | job 8, once a session: RAMDP `$0200-$09FF` -> the save |
| `job_scale_setup` | 0x08022D34 | job 8, every time: the stamps := 0 |
| `job_rescale` = `zoom_rescale` + `zoom_copyout` | 0x08022D84, 0x08022D48 | job 9 (F5 with a session open): the rescale into the stamps, then each stamp halfword byte-swapped into RAMDP `$0200 + 2i` and cleared |
| `job_restore` | 0x08022D04 | job 10 (B6), when saved: the save -> RAMDP `$0200-$09FF` |

The rescale, as the cart does it: F5's four words are (start, end, step, row). The first stamp byte is
(start >> 1 & 3 > 1 ? 0x400 : 0) + (start >> 3) x 0x40 + (start >> 1 & 1); then (end - start) / 2 columns (a 16-bit
difference). Each column reads two 32-byte rows of the F4 source at row x 32 + (acc / 2 & ~31), acc stepping by `step`
(16 bits) before the second row and after it, and writes 32 bytes at every other stamp byte: the first row's byte when
both rows are the same row, else the first row's high nibble with the second row's low nibble. The next column starts
1, 0x3FF, 1 and -0x3C1 bytes on, in turn. Both 32-byte copies are written out in full as the cart chip has them
(chosen as the faster shape; as loops they would be ~1.2 KB smaller).

What is ours and why:
- **The buffers.** The cart chip keeps them in one block (0x200111EC: the stamps A and B, 1 KB each; 0x200119EC: the
  F4 source, 2 KB; 0x200121EC: the save, 2 KB). Ours keeps the stamps (`zoom_st`, wram_data, where 0.2.6's 2 KB F4
  buffer was) apart from the source and the save (`zoom_ss`, one 4 KB block in wram_upper in the cart chip's order,
  where 0.2.6's 4 KB work buffer was). A row read past the source's end reads the save, and a write past the stamps'
  end lands in the source and then the save, as on the cart chip (`zoom_column_slow`). Past the save the cart chip
  reads and writes its sprite engine's working RAM; ours reads 0 there and leaves the write out (`docs/ALLOWLIST.md`,
  row B53). The game's own F5 posts stay inside the source and the stamps.
- **RAMDP a word pair at a time.** The save, the restore and the copy-out move two RAMDP words per access, the same
  bytes in the same order as the cart chip's halfword loops.
- **F4's decode.** In the FW_S5 images the F4 job decodes through the cart chip's own decoders, as ours has them
  (`interim/s1/bodies_s1.c` s5_unpack: core/song's song_unpack80 / song_unpack81) straight into `zoom_ss`, in the
  order they write it, as the cart chip's job 4 does. The FW_S5 = 0 images keep 0.2.6's decoder (`legacy/026/mame.c`
  ppm_unpack_scal, the same bytes in halfword-swapped order), and `zoom_f4_order` puts them back in the decoder's order.

Checked by `tests/equiv/zoomlock.py`: the image's own code in an RV32 emulator against the cart chip's routines in the
test harness, the whole block and RAMDP `$0200-$09FF` after every call, on random cases and on the game's F4 / F5 / B6
posts.
