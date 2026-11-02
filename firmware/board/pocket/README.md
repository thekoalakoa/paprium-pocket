# board/pocket - the Analogue Pocket board layer

| path | what |
|---|---|
| `main.c`, `appmain.h`, `cfg.h` | the 0.2.6 board entry, app header (NEORV32 + printf to the UART, off in RELEASE) and MMIO constants, as-is |
| `neorv32/` | the NEORV32 1.4.8.1-era HAL and `crt0.S` the 0.2.6 build uses (BSD-3, Stephan Nolting), as-is; `common/neorv32.ld` is the unmodified upstream script, kept for reference only |
| `include/pocket_map.h` | MCU interface v1.0 (`docs/MCU_INTERFACE.md`) as C constants: Appendix A verbatim between markers, then the map, slots, bits, option word, interrupt codes and the pocket72k layout. Board layer only (`tests/check_board.py` checks it against the doc) |
| `board_impl.h` | the Pocket's inline definitions of the board interface v1.0 (`board/board.h`, `docs/BOARD_IFACE.md`) |
| `s1_crt0.S`, `s1_trap.S`, `s1_board.c`, `s1_boot.h` | the new core (the s1 source set): crt0 (hold first, SYSINFO_CLK / USER_CODE checks before any RAM write, no IO sweep, `.bss_upper` cleared, TEST stack fill), the one trap entry (L1 closed, L2a with MEI, L2b with MEI + MTI, the flush on the way out), the board boot (rule 6.3.1); the boot steps P3-P8 of docs/BOOT_SPEC.md (`brd_boot`: boot page, interim boot, the chip's app start, MegaWire status, menu mute, the release with a bounded wait) and milestones 3-7 |
| `s1_freg.c`, `s1_freg.h` | the new core: the register accessor behind `brd_freg_wr`: the store, a shadow of every offset, the firmware decoder queue (FF4 / FF6 / `$1FF2 := 0x8000` -> `s1_decoder_start`), and in TEST images the chip-runner comparison's log (512 entries in `wram_upper`: every register store, SPTR and GO, in program order; the TEST debug save keeps it) |
| `link/legacy54k.ld` + `.json` | the 0.2.6 layout (the final 0.2.6 build's generated script, md5 33532367 as generated; only its comments and the text of its six ASSERT messages have changed since) |
| `link/pocket72k.json` -> `.ld` | the locked 0.3.0 layout; regenerate with `python -I -B tools/mkld.py board/pocket/link/pocket72k.json board/pocket/link/pocket72k.ld` |
| `boot/` | the boot cache (test build 4b, 2026-10-22). `boot_cache.c` / `.h` = the IROM stub crt0 calls (TEST and RELEASE; `fwbuild.py stubs` still compiles it alone and runs its host test); `c4b_ovl.c` + `c4b.h` = the WRAM boot overlay (below), linked on its own (`link/c4b_ovl.ld`) with `core/wavpack` |
| `link/c4b_ovl.ld` | test build 4b: the boot overlay's link (wram_upper at power-on; its scratch at the start of wram_data and at the stack floor) |
| `s1_cache4b.c`, `s1_cache4b.h` | test build 4b, TEST image only (`S1_CACHE4B_REC`, `s1_boot.h`): the boot cache's record copied to the debug save (version 8; 9 in the FW_S5 images); in the WRAM code window (`pocket72k.json` / `pocket88k.json` wcode_text) |
| `boot/c5_curve.h`, `boot/gen_c5_curve.py` | FW_S5 (test build 5 on): the synth's output curve in the overlay's packed form (488 B of two-bit steps; GENERATED, `--check` in run_all) |

Names such as `cache4a`, `c4b` and `c5` come from the hardware test builds B Jam ran on the Pocket that first carried
that code: test build 4a (the sound-cache probe), test build 4b (the boot overlay) and test build 5 (the synth build,
the first with our own song engine).

## The FW_S5 images take the boot cache (test build 5 on; s5test / s5release; pocket88k; MCU interface v1.3)

The FW_S5 images (fwbuild.json `s5test` / `s5release`: the firmware with the song engine on the synth) boot as the
boot-overlay images of test build 4b below do, with these differences (each in the file named):
- crt0's FEAT check wants test build 5's blocks: CACHE, BAR and SYNTH (docs/MCU_INTERFACE.md 21.3 item 1; SYNTH = 1
  also means no interim FIFO or MD+ block) and an IROM of at least 88 KB (`s1_boot.h` `S1_A_FEAT_*`;
  `POCKET_FEAT_CARD5` = 0x0058_0047 with GS3); the bitstreams of test builds 4 and 4a stop it (0xC2 /
  0xC3) before any XLINK access.
- The boot overlay (built for the s5 images with FW_S5) also writes the synth's output curve into CRAM CURVE
  (0x194000-0x19BFFF, index 0 at 0x198000: MCU_INTERFACE.md 3.8 / 3.10.6) on every non-warm boot, next to the SFX bank
  copy and before CACHE (`c4b_ovl.c` curve_write, `boot/c5_curve.h`: a packed form, rebuilt while it writes; equal to
  the cart chip's curve, all 16,384 entries, measured; record flag `C4B_F_CURVE`). A warm boot touches none of it (the
  CRAM keeps it).
- C6 takes the wave bank only when the boot cache made or kept it at this power-on and from the stream the game
  names (`board_bank_ok` -> `brd_bank_ok`: XLINK CACHE.VALID with the image size, and the header's ROM key word = the
  C600 stream); otherwise C6 stops before its BGM step, as the chip's does for a bad wavpack count.
- The boot writes DTOUT (MCU_INTERFACE.md 3.10.1, reset 0 = silent) with the "plain first" stand-in of decision 5:
  GAIN 1410 (x 5.51), no inversion, the DC blocker at DCK 11 (`s1_board.c`; docs/ALLOWLIST.md, row B44; estimated:
  the DT / YM-DAC balance of the cart-engine renders B Jam heard as right, on this core's YM-DAC scale; not
  established from a capture; these are the starting values (a project decision): a listening session on test build 5
  checks the DT / YM balance by ear, a level fix is a firmware swap).
- TEST: the debug save is version 9 (`dbgsave.h`): no interim audio blocks; DBG_B_SYNTH holds the synth's DIAG totals,
  the TEST assertions (A1 no write while a block runs but the DONE stores with no hold-off, each one's WBUSY measured,
  and the stores of the module starts + C6 items (the items with no arrival: the 8C's module start, C6's song_c6_init
  / song_c6_ready), whose writes that met a block are counted apart as a diagnostic, never a failure; A2 UNDERRUN <=
  the DT starts, A3 no TIMEOUT) and which failed, the synth's registers and the pass counts; DBG_B_DISP's counter 11
  folded (board_trace_fold) just before; PREV2 carries the synth's words across a Quit. The code window holds the
  debug save and the record writer (`pocket88k.json`), the IROM the stub.

## Test build 4b, the boot overlay: the first-boot unpack of the cart's sound bank (TEST and RELEASE; MCU interface v1.3)

The boot overlay (test build 4b: a firmware swap on test build 4a's bitstream) unpacks the cart's sound bank into the
1.38 MB sound-cache slot on a power-on without a good cache file, with the WavPack decoder the cart uses
(`core/wavpack`: the BSD tiny decoder, with the bank unpack around it written by our team: we reverse engineered the
STM32F4's commands as close as possible, with hardware verification), and keeps it there: the Pocket writes the
file back at the next Quit / power-off and loads it at the next power-on. Both images are v1.3 images (crt0's FEAT
check: the cache slot, the bar, the interim FIFOs, the MD+ block, 72 KB of IROM). The flow (`boot/c4b.h` in full;
MCU_INTERFACE.md 21.1):
- crt0, after its interface checks and before .data / .bss: `boot_cache_boot` (IROM). CACHE.VALID set: nothing touched
  (WARM). Else the boot overlay at 0x80006C00 (bitstream-initialised: header magic `POV1`, length, CRC-32, entry) is
  entered if its CRC matches; else nothing (GONE: crt0 has overwritten it, i.e. a reset after an unpack that failed).
- The overlay: the game's own C600 arguments read from the ROM, the WavPack stream's 32 block headers (the ROM key =
  their CRC-32); then the loaded file: CACHE_LOADED = 0x152100, LOST 0, the 256-byte header (magic `PAPRSND1`,
  format 1, sizes, samples, the stream's address / bytes / blocks / key, the bank's CRC-32, the ROM's 48 block-CRC
  words, its own CRC-32), and the bank as CRAM holds it (every WavPack block's own CRC, the tail, and the bank CRC-32
  against the header) -> PASS. Else (FIRST / HDR / KEY / BANK / SIZE / LOST; test build 4a's pattern file reads HDR)
  the old magic is cleared, the bank unpacked, checked again from CRAM, the header written last (its magic last of
  all) and read back. An unpack or
  check that fails sets nothing (no file; the next power-on unpacks again).
- Every non-warm boot then copies the SFX bank (552,748 B, the ROM's 68000 words) to CRAM 0x200000 (MCU_INTERFACE.md
  3.8), and only after it, as the power-on's last store, CACHE := VALID | 0x152100: a reset inside the copy finds VALID
  = 0 and the overlay intact, so the next boot copies the bank whole again (never WARM over a half bank). The bar (XLINK
  BAR) is lit only during an unpack (21.2: from its start through its check and the header) and put out before the SFX
  copy; a boot that keeps the file never lights it; EN = 0 again before crt0 continues. Times (estimated with the
  fast-path cycle table from the real image, by our census tool): the first boot ~19.3 s (the decoder ~15.2 s, the check
  after it ~1.4 s), a boot with the file ~1.5 s (the check) + 0.16 s (the SFX copy); on hardware not known until the
  TEST record's times. Proved on RV32 by `tests/equiv/cache4b.py` (the whole bank = the chip's; 13 planted
  bugs) on `rtlmodel.py`'s model of the first sound-cache board.

Debug save version 8 (test build 4b, the boot overlay): the block `cache` holds the boot cache's record (`boot/c4b.h`
c4b_rec_t, 16 words: what the boot found and did, the bank's CRC-32 (the chip's bank's when it is right), the header's, the
first wrong block, the samples, the decoder's CRC errors, the ROM key, the four times, the bar's W, the VDP syncs while
held), this boot's and the previous four (81 words, the size of version 7's block). `tools/dbgsave.py` reads versions 7
and 8.

## Test build 4a, the sound-cache probe (TEST image; MCU interface v1.3; replaced by test build 4b's boot cache)

Test build 4a, the first sound-cache build (B Jam's decision 1a of 2026-10-21), is the silent probe build that answers
the one question of the synth work only hardware can: does the Pocket keep a 1.38 MB nonvolatile file (data.json slot
20, `paprium_sound_cache.bin`) and load it back. Its TEST image (the probe is not in RELEASE, which stays test build 4's
RELEASE byte for byte) is the first MCU interface v1.3 image: `pocket_map.h` carries Appendix A v1.3, crt0
refuses a v1.2 bitstream (XLINK 0x40 is XCFG on test build 4's bitstream) and a v1.3 one whose FEAT lacks the cache
slot, the bar, the interim FIFOs or the MD+ block, or has less than 72 KB of IROM (stop code 0xC3, value = FEAT). In
brd_boot, with the 68000 held and interrupts off (MCU_INTERFACE.md 21.1):
- CACHE.VALID set (a reset inside the session, or the Quit's own reboot while the Pocket reads the file back): nothing
  is touched (WARM);
- otherwise the 1,384,704-byte image in CRAM (0x0900_0000 = file byte 0) is read and compared word for word (header
  `PC4A`, size 0x152100, format 1, a check word; then word k = k x 0x2B5D1C93 + 0xC4A0C4A0), kept only if CACHE_LOADED
  is the image size, XLINK LOST[31:16] is 0 and every word is right (PASS), else written again with the header last
  (FIRST: no file; SIZE: another size; LOST: CRAM writes lost in the load; BAD: words wrong); then XLINK CACHE :=
  VALID | size, so the Pocket writes the file at the next Quit / power-off. The file's md5 is then c5f245e1
  (tests/equiv/cache4a.py);
- the first-boot bar runs down from full width during the check and up during the fill, and is off before the release.
Each boot's record (kind, CACHE / CACHE_LOADED / LOST at the start, the words that differed and the first one, the check
and fill times, the bar's width W and the VDP's vertical syncs during the hold) goes to the debug save, version 7.
Proved on RV32 by `tests/equiv/cache4a.py` (12 cases, 8 planted bugs) on `rtlmodel.py`'s model of that board.

Debug save version 7 (test build 4a, the probe): the block `cache` (DBG_B_CACHE, right after `prev2`) holds the probe
boots counted, this boot's entry and the previous seven (carried, so the .sav read after a Quit, whose reboot is WARM,
still holds the session's check); the probe's module reads the old block before the boot's clear and writes the new one
right after `dbgsave_start` (the debug save's own code is unchanged: the plan row "debug aids" is at its allocation). To
make room the audio-call log keeps 128 calls (was 256). `prev2`'s chain is carried from a version-6 or -7 record (the
same layout). `tools/dbgsave.py` prints the block in plain words ("this boot: PASS: the file loaded whole ... KEPT").

The layouts are documented in `docs/LAYOUT.md`.

## The TEST debug save: `dbgsave.c`, `dbgsave.h`, `tools/dbgsave.py`

Save bytes 0x1000-0x1FFF of the 8 KB battery save (0x000-0x8FF the game's, 0x900-0xFFF 0.2.6's TEST SAT snapshot):
blocks of the new core's counters (core/sched/stats.h, the scheduler, the watchdog, the fatal record, the CPU MATE glue,
the audio feeder, the dispatcher, the stack high-water) and the two TEST logs (the ordered audio-call log, the
register-write log of the chip-runner comparison), written once at the boot and every CLK_TIM7 (102 ms) from the wheel's
TEST slot, so the .sav B Jam sends after a freeze holds its last tenth of a second. A size probe at the boot (68000
held) turns it off when the save RAM is 4 KB (0x1000 would alias the game's 0x000). RELEASE builds empty functions only.
Version 2 (with the 8 KB save of docs/STAGE1_PLAN.md question Q1): a fatal halt writes the record itself (interrupts
stay off for good, so the wheel's write never comes again: `brd_milestone(ST_MS_FATAL)` -> `dbgsave_now`), and again
every 65,536 polls while the halt runs; the boot keeps the previous session's record as the `prev` block before it
clears the region (so a Soft Reset after a freeze or a halt does not overwrite it) and carries the latest fatal halt
forward; every store is bounded to the region (a compile-time bound of the whole record and a check per store). Proved
on RV32 by `tests/equiv/fuzz_s1.py --q1`. Version 3 adds the VS counter (MCU interface v1.1), version 4 the RTL sprite
decoder's read-backs (v1.2, slots 18-22). Version 5 (2026-10-17): B Jam's two saves from the RTL sprite-decoder test
build showed that the Pocket's quit restarts the core about 0.3 s before it reads the save (the current record was a
316.704 ms boot with the menu open both times, measured; the session survived only in `prev`), and every reset clears
the decoder's slots and the counters. The boot now also carries `prev2`: the previous session's decoder block (LATECNT,
the flags, the smallest margin, the last START's words and time), its CPU MATE lateness counters (late, discarded,
aborted, abort landings, the longest call), the SFX feeder's catch-ups, the exception fields, the dispatcher's refusals
and failed jobs and the stack high-water, and the worst of those over every session chained since (each boot folds the
one before it: the largest count, the smallest margin, the flags ORed; `DBG_P2_BOOTS` sessions, `DBG_P2_DIRTY_AGE` = how
many sessions back the newest lateness sign is). So quitting is fine now, and a quit followed by quick relaunches keeps
the worst values. The block is read before the 68000 is released (one walk of the old record's block chain, then one
table) and written by the boot's write only (the periodic write steps over it); the region clear skips the words that
write rewrites, so the boot is no slower (measured in the board model: the release -0.015 / -0.021 ms with a blank
region / a version-4 record, +0.025 ms after a version-5 session against the main branch's after a version-4 one).
Record: 1,003 of 1,024 words. Version 6 (2026-10-19), TEST only: (1) the CPU MATE late counter. The save of a long
hardware play test by B Jam read "answers published late 31,629 of 36,904" while he played without a partner: the glue
counted every publish that found the stub's sticky LATE flag up (cleared only at the boot and in rare housekeeping), so
it read ~100 % while the real late rate in the co-simulations was 3-60 %. `buddy/s1_glue.c` now clears the flag just
before each ARM and counts the flag read after it (the RTL sets it in the ARM's clock and gives that event priority over
a same-clock clear), each late answer once (a second fix: also when the game's next post overtook publish's read), with
the largest lateness (TICK - D_WORD, sub cycles, from the TICK reads made before the game's next post: a post restarts
TICK) and the short-path calls (D_WORD under 1,000 sub cycles: no partner active) beside it; `late_seen` is retired (0,
its slot kept). A late answer is no lateness sign any more (expected since an earlier scheduler change; harmful only if
the game reads `$A12024` first). (2) The album recorder for B Jam's missing Blue Bar street music: the audio block's
TEST words hold, at every write, the MD+ result word (the CDDA fetch's track and playing bit) and the command word the
adapter last took, XLINK 0x14 (CDDA underruns, snoop overflows) and 0x18 (ring writes and loader words lost), the last
album call and the last play request (its command word, frame and the underruns then) and how long a requested track has
waited with playing 0 (and the session's longest); `interim/album/mdp.c` notes the calls and polls the rest
(`s1_album_poll`, called first by every write). `prev2` carries both across the quit in its version-6 layout (10 more
words: the largest lateness and the longest wait folded into the chain); a version-4 or -5 record gives part 1 and
starts the chain again. Record: 1,024 of 1,024 words. Proved on RV32 by `tests/equiv/tdiag_s1.py` (a Mega CD link stub
model from `paprium_mcd_link.sv`; the MD+ result word and XLINK's counters driven) and `fuzz_s1.py --q1`.

The save itself (question Q1; B Jam's decision: 8 KB like the cart): the game's saves keep the 0.2.x layout in
stages 1 and 2 (README.md, "Terms"), so a 0.2.x 4 KB .sav loads into 0x000-0xFFF as it is and the upper half starts at
the RAM's power-up 0; the cart's own format and its one-time conversion of 0.2.x saves came in stage 3
(docs/ALLOWLIST.md, row B11). Nothing in RELEASE writes the save outside the
game's own save commands.
`python -I -B tools/dbgsave.py Paprium.sav [--logs] [--json OUT]` prints the milestones, the freeze telemetry, the per
level CPU split, the L1 latency, the 84 window-off time, the glue / audio / dispatcher counters, the previous session
(`prev`, and from version 5 its lateness counters and the chain's worst, `prev2`; a record before version 5 gets a note
that it has none) and the logs. It reads versions 1-6; a reader older than this one stops at a version-5 record's
`prev2` block (an unknown block id), and a version-5 reader would misname a version-6 `prev2`. From version 6 it prints
the CPU MATE line as late answers ("answers armed after the original's instant N (expected since stage 1i; harmful only
if the game reads first)"), "the longest call" as wall time, and the music in plain words ("music: track 11 requested
3.20 s before this write, playing = no"); a version-5 record prints as before with its late counter labelled as the
sticky-flag count and a note. It also prints the SAT snapshot in save bytes 0x900-0xFFF in plain words (also
from a 0.2.x 4 KB save with no record): layout 2 (`interim/README.md`) the session's most crowded frame with
its true count, the latest frame of 20 or more, the session's most and its frame ends over 80, a torn copy marked;
layout 1 the last busy frame (capped at 80; "more than 80" when entry 79 links on to entry 80); for each table, the
lines the console would show over 320 px and over 20 sprites (estimated: the H40 rules on the stored table). Later
versions store a table of more than 80 posted AF02 as the chip's multiplex (entries 14-79 linking to k - 13): the reader
names it, reads "more than 80" from it in layout 1 too, and gives no line totals for it (entries 80-93 are not in the
save).
