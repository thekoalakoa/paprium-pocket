# core/sprite: the cart chip's sprite engine

The sprite engine of the cart program, written by our team from our own study of how the cart behaves,
with one function for each routine of the cart chip. The cart chip
is the STM32 microcontroller on the real cartridge. This engine replaces 0.2.6's (legacy/026/mame.c) in every image
of the new firmware (FW_S5 = 0 and FW_S5 = 1, board/board.h); the 0.2.6 milestone builds keep theirs. It is
board-independent: RAMDP (the cart RAM that both the 68000 and the MCU see), the flash word view and the workspace
come through `board/board.h`.

| file | cart chip routine | does |
|---|---|---|
| `spr.h` | - | the state in the cart chip's fields (handles 0x2000FB1C, the slot count H+$402, anims per object H+$404, the block directory H+$504, the load count 0x20010028 and list 0x200136F0, the countdowns 0x200129EC, id -> block 0x20012AD4, lists A / B / C), the slot -> VRAM id table 0x08025DB8 as its formula, the routines |
| `spr_board.h` | - | the memory views, the 32-bit RAMDP view, the frame-rate word the 50 Hz skip reads (G+0x08), the RAMDP offsets |
| `spr_compose.c` | the composer (RAM 0x20002F9C, flash 0x0802F02C) | the pose budget pre-check and pre-load pass, the frame advance (the queue, the 50 Hz skip, the terminal end), the attribute ADD and pose bit 29, the X clip, the miss path (its gate and 15-load cap, the claim from A, B, the related block, C, the drop), the claim's DMA descriptor |
| `spr_cache.c` | the aging 0x08017FDC, the EC worker 0x08017EE0 | the aging as the loop the cart chip's chains unroll; EC grow / shrink and the list rebuild; the sparse block -> id index that answers every read of the cart chip's 16 KB table 0x20008164 |
| `spr_frame.c` | AD 0x080194BC, the frame end 0x080190B8 | the restart rule, the queue move, the ready flag; the end mark, entry 79's link, the two DMAs, `$1F1C` and the `$1F20` stash; the multiplex above 80 entries (modes 0-2) |
| `spr_posts.c` | AE 0x08018FBC, B0 0x0801940C, the flush 0x08018FFC, F2's table read 0x08017E84, C6's sprite init 0x08019734 | the engine halves of the posts (core/dispatch writes their register sequences and keeps the engine flag, the open frame and the AE count), the block-table read, the C6 hand-over |

What is ours and why:
- **The aging is a loop.** The cart chip unrolls it into one chain per slot count (a jump table at 0x08025838); the
  loop walks the same slots in the same order with the same results.
- **The block -> id table is a sparse index** (256 bucket heads + 128 nodes, 768 B, wram_upper). An id holds at most
  one block and a block sits in at most one id, so every read the cart chip makes gets the same value; the cart chip's
  16 KB table does not fit the MCU's RAM.
- **EC is kept to $35.** The gate admits counts up to $80; above $35 the cart chip reads past its 56-byte slot table
  into the next table and past its arrays (into the first SFX channel's record). The game never posts more than $35
  (docs/ALLOWLIST.md, row B48, approved).
- **An objID of 256 or more** (`spr_frames`; spr.h's state order). The cart chip looks a queued anim up in its
  256-byte anims-per-object table with the record's whole objID, so for such an objID it reads its own RAM after the
  table. B Jam's decision of 2026-10-28: for these objIDs ours reads that RAM the way the cart chip does. Ours gives
  the cart chip's bytes for objIDs 256-267 (the block directory as the cart chip's 16-bit view address and as the C6
  long, the load count); from 268 on the cart chip reads other live state and ours reads 0 (the rest of
  docs/ALLOWLIST.md, row B52). The game's objects are 0-240, and in every recorded game a larger objID came only with
  the restart flag, whose path masks it first.
- **The flush's list is handed to core/dispatch as ROM offsets** (`spr_load_list`), read from the block table where
  the cart chip's flush reads it; core/dispatch pushes the entries last to first, as the cart chip does.
- **RAMDP pairs are stored as 32-bit words** (the SAT entries, the descriptors, the end mark, the stash), as the
  engine of test build 5 stored them: the same words with the same values; the 68000 waits on busy for the whole
  post. The stash's 28 copies are written out, not looped, as test build 5's close does: as a loop they cost AF 5.7 us
  of reply and put solo frames over the 8 ms meter of our timing test, which test build 5 keeps under (measured).
- C6's anim set-up (0x080195E0: the unpack, the byte swap, the counts) is the cart chip's in the FW_S5 images:
  `spr_c6_begin` (the sprite init's resets, the table cleared), the container decoded by the cart chip's 0x80
  decoder and the whole 512 KB swapped (interim/s1/bodies_s1.c job_setup), then `spr_c6_count` (the counts with the
  cart chip's rounding of an object's start, its 0x201 cap, the directory check and the trace codes 0x16-0x1B); the
  table, the directory and the container equal the cart chip's after C6 (tests/equiv/c6sprite.py). The FW_S5 = 0
  images keep 0.2.6's ppm_setup_data and `spr_c6`.

Proofs: the lockstep with the cart chip (`tests/equiv/chiplock_s1.py`, which runs the cart chip's program and ours
side by side, on every corpus: the sprite words after every accepted AD and AF), the unit lockstep against the cart
chip's own sprite routines run in an emulator (every engine field after every call; the aging at every slot count,
every EC pair, the AF frame end on every count and mode, F2 on every block number; the game's own setAnim run against
each side's record), the GPGX closed loop (the game's 68000 reading the record words the firmware wrote: its AD stream
never leaves the cart chip's), a set of runs on the RV32 board model and a co-simulation of the RTL and the firmware.
