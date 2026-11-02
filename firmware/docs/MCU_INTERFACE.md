# MCU interface v1.3: the first new-core firmware's interface, plus the sound cache, the first-boot bar and the synth

Paprium 0.3.0, stage 1, the new-core stage ("new core, same game": a new firmware core, the game unchanged). Drafted on
2026-10-11 and checked against the cart-RTL, platform, firmware and test designs and against the RTL in a review that
wrote this v1.0 (what the review changed: section 15). **Design only: nothing here is built.** Companion: `docs/STAGE1_PLAN.md` (the work order
that builds it).

This page is the cart MCU's hardware interface as the first 0.3.0 FPGA fit freezes it: the NEORV32 set-up, the memory
map, the interrupt lines and their latches, the timer, the register blocks, the option word and every reset value. It
follows a rule made for the MiSTer port: interrupt and timer registers are frozen and versioned before the logic that
uses them. Stages 2, 3 and 4b (the sprite engine; the unpackers, zoom, saves and MegaWire; the boot cache's first-boot
unpack) change the firmware only (`update_mif`), so anything not frozen here cannot change until the synth's fit (stage
5).

**Status (2026-10-11).** v1.0 is the freeze. The two rows that were open are closed by B Jam's answers
(docs/STAGE1_PLAN.md section 11): question Q1 = an 8 KB battery RAM like the cart's (section 3.6), question Q4 = the
"options at reset" latch built dormant behind CTRL bit 5 (section 4.1). They were folded in when the interface was
frozen (section 16); no meaning changed, so the version stays v1.0. Nothing else changes without a version bump
(section 1).

**v1.1 (2026-10-13; B Jam's decision of 2026-10-13: "build the optional VS counter").** One register added in a
reserved slot, the minor bump section 1 allows: FPGAIO slot 16 **VSCNT**, a 16-bit count of the VDP's vertical syncs
for the TEST build's freeze telemetry (section 4.8; docs/STAGE1_PLAN.md). USER_CODE becomes 0x5049_0101. Every v1.0
slot, bit, address and reset value keeps its meaning (section 17). Firmware built for v1.1 refuses a v1.0 bitstream
(its minor is lower); v1.0 firmware runs on a v1.1 bitstream unchanged.

**v1.2 (2026-10-15, proposed: it needs B Jam's yes, from the RTL sprite-decoder design).** B Jam's decision of
2026-10-15 ("preservation: reply at once, sprites already done, never wait"): the cart FPGA's sprite decoder and its
load-list queue move into the RTL, as on the cart. The register file now acts on the chip's own decoder writes (`$1FF2`
START / STOP, `$1FF4` / `$1FF6` push and clear, section 3.4), and six FPGAIO slots are added in reserved space (17-22,
section 4.9): the decoder's output base, which the firmware writes before each START, and five TEST read-backs.
USER_CODE becomes 0x5049_0102. Every v1.1 slot, bit and reset value keeps its meaning (section 19). Firmware built for
v1.2 refuses a v1.1 bitstream: with the decoder in the RTL a v1.1 bitstream would never decode a sprite block.

**The MCU fast path (test build 4, 2026-10-16; B Jam's request: "the MCU fast path"): timing only.** The IROM and the
WRAM move onto the NEORV32's processor bus (tightly coupled, the way its own IMEM / DMEM sit there), RAMDP answers with
a registered ack, and the SDRAM / flash windows run only the 16-bit halves an access touches. Every register, bit,
value, address, alias, lock rule and reset value is unchanged, and so is USER_CODE (v1.2: 0x5049_0102): only the cycle
figures change.
They are measured on the RTL in section 20 and replace the figures of the design before the fast path in sections 2, 3,
6.2 and 9 (marked "fast path"; the change was test build 4, which B Jam tested on his hardware).

**v1.3 (2026-10-21, frozen before the synth work; B Jam's go of 2026-10-21: "go with all 7 stage-5 recommendations ...
Start M0 and card 4a").** The MiSTer rule says the cache registers are frozen
before test build 4a and the synth registers before the synth RTL; v1.3 freezes both at once, before either is
built. **Design only: nothing in v1.3 is built yet.** What it adds (section 21 is the record; every v1.2 slot, bit,
address and reset value keeps its meaning, the interim rows retire as v1.0 announced them, finding 14):
- **FPGAIO:** slot 14 **STAMP_A** (TIMER when CAUSE.A was last set; reserved for it since v1.0), slot 23 **FEAT** (what
  this bitstream carries: cache slot, bar, synth, the interim audio blocks, IROM size; 4.10), CAUSE bit 4 **BLK** (the
  synth finished its queued blocks) with its enable CTRL bit 6 **BLKIE** (4.1, 4.2).
- **XLINK 0x40-0x48** (power-on domain, next to the CRAM controller): **CACHE** (the sound-cache slot's valid flag and
  size, power-on reset only), **CACHE_LOADED** (bytes the Pocket loaded into the cache window at this power-on) and
  **BAR** (the first-boot bar) (3.9). Test builds 4a and 4b, the two sound-cache test builds, need exactly these, plus
  the board contract in 21.1-21.2.
- **Region 0x06, the synth** (3.10): the global registers incl. **SEQ / DONE / SEQLAT** (the arrival-order hold-off),
  the 16 wave-voice windows and the 8 SFX-channel windows, at the chip's field types; the CRAM die-0 map the synth and
  the firmware share (3.8); the IROM at 88 KB on the synth fit (3.1, B Jam's decision 2).
- USER_CODE becomes **0x5049_0103**. Firmware built for v1.3 refuses a v1.2 bitstream (minor) and checks FEAT for the
  blocks it drives (section 1). The Grand Stick III options (decision 6) add no MCU-visible register (21.4).

**How we know.** Where it matters, a statement says how it is known: "measured" (read from a run, a report or a file),
"estimated" (arithmetic on measured numbers), "not known" (nobody knows), "checked" (in the code or in a run), "read in
the code only", "inferred". Rows marked "proposed" were draft proposals; in v1.0 every proposed row below is accepted
(frozen) unless it says open.

**Authority.** The project plan's locked and dated decisions, then `docs/CART_FPGA_SPEC.md` (decisions F-D1..F-D5 as
committed: F-D3 = the cart's behaviour) and `docs/BOOT_SPEC.md`, then our study notes. The RTL base is the 0.2.6
release worktree (read only; its MCU files equal the final 0.2.6 build tree's copy except comments, checked with diff).
Source md5s and reruns are in section 14.

---

## 0. Findings first

1. **EXT_KB = 40 alone breaks the IROM.** (Measured in Icarus.) The 0.2.6 `mcu_irom` selects the extension with
   `addr[15]` only and indexes it with `addr[15:2]`. With a 40 KB extension, 10,240 of 18,432 words read wrong: the
   whole extension, including the brain's upper part (0x8000-0xD2EB) and everything above 0x10000, which reads rom0.
   Fix: select = `addr[16] | addr[15]`, index = `{addr[16], addr[14:2]}`. The draft (our bench's `mcu_irom_v1.sv`) reads
   all 18,432 words right. `docs/LAYOUT.md`'s "the 17-bit address already reaches 0x11FFF" is true for the port, not
   for the module. Checked again in the review (`mcu_core.sv` lines 312-331): at EXT_KB = 40, `XW = $clog2(10240) =
   14`, so the index `addr[XW+1:2]` takes in `addr[15]`, the select bit; at EXT_KB = 22 it was 13 and correct.
2. **The "2:1 select" is a 2:1 select plus the extension's own depth mux.** (Checked in the generate block; the ALM
   figures are estimated.) The 0.2.6 generate
   picks 1024-deep slices when EXT_KB is a multiple of 4, so 40 KB would be a 10:1 mux (no ALM back). 2048-deep slices
   divide 10,240 words evenly: 5 slices x 8 M10K = 40 M10K, a 5:1 depth mux. Total ~35-50 ALM against 92.7 today
   (measured), so about -43..-58 ALM.
3. **The CPU MATE brain uses none of the registers that change.** (Measured by a static scan of `brain.bin` and
   `cf.bin`.)
   Its only MMIO bases are RAMDP (0x0200_0000, halfword view), the flash word view (0x040x_xxxx), the SRAM
   (0x0801_xxxx-0x0803_xxxx) and WRAM (0x8000_xxxx). No FPGAIO, no NEORV32 IO, no XLINK. So every v1.0 change is
   brain-neutral as long as those four windows keep their 0.2.6 meaning. (A linear scan: base pointers handed in by the
   glue are not seen. The glue is rebuilt anyway.)
4. **The WRAM write path can lose its decode by design, at no cycle cost.** (Checked in the code; the cycles are
   estimated.) Today the store
   strobe fires in the first cycle of the access, so the region decode and the lock function sit on a half-cycle path
   into the negative-edge RAM (the path that failed timing in the fitter seed-6 build). Registering the write-select in
   cycle 0 and writing half 0 in cycle 1 keeps the ack in cycle 3, so a store stays 12 cycles (estimated; a GHDL run
   must confirm it). This is the "registered bank bit" the project plan asks for. Checked again in the review
   (`mcu_core.sv` lines 186-189, `memory.sv` lines 145-151): `wram.we` is combinational from `ram_ce` (the region
   decode) while `idle` is 0 in the first cycle, and the RAM writes on the negative edge through `LOCK_MAP[addr[13:9]]`.
5. **NEORV32 1.4.8.1 re-latches a level interrupt the clock after it is taken.** (Checked in
   `neorv32_cpu_control.vhd` lines 1389-1391.) `irq_buf` = enable AND (irq_buf OR line) AND NOT ack. A handler that
   acks its source must then clear and set its `mie` bit, or it re-enters once with nothing to do. The 0.2.6 glue
   already does this for MEI (`zz_buddy.c` lines 510-512). v1.0 makes it a rule for all three lines (section 6.3).
   Checked again in the review: `irq_buf <= mie AND (irq_buf OR line) AND NOT irq_ack`, so the buffer re-latches one
   clock after the ack while the line is still high.
6. **Decision F-D1 keeps the GPIO unit** (menu bit on GPIO input bit 24; B Jam's decision of 2026-10-11). The platform
   lever "GPIO -> FPGAIO option slot" (-5..-12 ALM, estimated) is given up. MTIME, UART and WDT still go (-161 ALM of
   measured entity rows).
7. **The ms counter goes, and 0.2.6 code reads it.** (Checked with grep.) `FPGAIO->time` is read by the VU (`paprium.c`
   796, 811), the MD+ shim's timeout (`mdp.c` 136-142) and C6's printf timing (`paprium.c` 413-428); the glue reads
   `BUD_FPGAIO_TIME` and MTIME. All move to the new timer in the new-core firmware.
8. **Every 0.2.6 MCU access to RAMDP 0x02001FE0-0x02001FFF must move to the register file.** (Checked.) The 68000 no
   longer sees those RAMDP cells (docs/CART_FPGA_SPEC.md section 2.1). Affected: the legacy `ppm_ramdp` fields
   `reg_status_1`, `reg_status_2`, `reg_cmd` and the glue's `BUD_RAMDP_REGCMD` (0x02001FEA). The RTL does not alias
   them (proposed); a check on the test rig catches stragglers (docs/CART_FPGA_SPEC.md section 15.1).
9. **Two clock literals bypass `CLK_FREQ`, and two more are clock-derived.** (Checked.) `mcu_core.sv:99` passes 53693175
   to the NEORV32 `CLOCK_FREQUENCY` generic; `paprium_cdda_play.sv:138` compares with a literal 1118. Both become clock
   expressions. Checked again in the review: the album counter runs 0..1118, a period of 1,119 clocks (47,983 Hz), and
   `CLK_FREQ/48000` truncates to 1118, so the NTSC logic is identical when the compare literal is replaced (not the
   period). The platform audit adds `paprium_cdda_play.sv:85` (`mute_ctr` 2685000, ~50 ms) and `paprium_mcd_link.sv:84`
   (`DIV` 2147727 = clk_md / 50); docs/STAGE1_PLAN.md item M6 covers all of them.
10. **Battery RAM size must be chosen now.** (Checked in our study and the code.) The chip's save layout runs to 0xAE0;
    the 0.2.6 TEST debug region is 0x900-0xFFF (1,776 B, `mame.c` lines 1620-1680). A 4 KB BRAM leaves 1,280 B
    (0xB00-0xFFF) for TEST debug after stage 3 (the unpackers, saves, zoom and MegaWire), and stage 3 changes the
    firmware only. **B Jam's decision of
    2026-10-11 (docs/STAGE1_PLAN.md question Q1): 8 KB**, like the cart's EEPROM (the recommendation was 4 KB).
11. **The decoder queue does not need RTL.** (Checked in docs/CART_FPGA_SPEC.md section 9.) Only the MCU pushes it and
    only the MCU pops it. A 16-deep RTL stack would cost ~150-200 ALM (estimated). **Frozen:** the queue lives in the
    firmware board layer's register accessor; the RTL does not even store `$1FF0`/`$1FF4`/`$1FF6` (section 3.4; the
    cart-RTL and firmware designs agree). The chip-runner test compares the register writes the accessor logs.
12. **Decision F-D3 is the cart's behaviour** (no answer at `$400000-$7FFFFF` when Mega CD = None). An uncommitted
    working-copy edit in paprium-fw had turned it back to "keep 0.2.6"; B Jam's request for this run ("Keep it like
    the cart") and the allow-list review of 2026-10-11 both say the cart. The review restores the cart wording (the old diff is kept
    in our notes). Nothing on this page depends on F-D3; the RTL item is docs/STAGE1_PLAN.md item C5.
13. **Four drafts used three slot maps; v1.0 has one.** The firmware design had assumed CAUSE in FPGAIO slot 6, MSI in
    8 and the counter in 9-11; the cart-RTL design put a post timestamp and a stream status at `0x0B000020/24`. v1.0
    keeps the first draft's slot map (section 4), drops the two `0x0B000020/24` words (STAMP_B and the GO read-back give
    the same numbers) and puts the two board-control enables from the platform design in CTRL bits 4 and 5.

**v1.3 findings (frozen with v1.3, 2026-10-21).**

14. **The synth fit changes the meaning of region 0x06, and section 1's rule calls that a major change.** (Checked on
    this page.) Region 0x06 goes from the interim audio_sfx FIFOs to the synth; region 0x07 (MD+ / EverDrive stub) and
    FPGAIO slots 3 / 4 (VOL_SFX, VOL_BGM) go. v1.0 already marked every one of them "interim ... unchanged until stage
    5" (rows 0x06, 0x07, slots 3-4), so v1.3 treats their retirement as announced, not as a change of a frozen meaning,
    and stays a minor version. What makes it safe is **FEAT** (4.10): a v1.3 image reads which audio block the
    bitstream carries and stops (68000 held) when it is not the one it drives. The one gap: a v1.0-v1.2 image cannot
    read FEAT, so it would run on a synth bitstream and write interim registers that are gone; no package ever pairs
    them (a test build's images reach its bitstream only through the `update_mif` step of its final fit check, from the
    firmware commit the build names). The alternative, USER_CODE major 2 on the synth bitstreams, costs nothing in RTL
    and closes the gap too; it is listed as an open question (section 13).
15. **The cache registers belong in the power-on domain, which is XLINK's, not FPGAIO's.** (Checked in test build 4's
    RTL of 2026-10-19.) FPGAIO resets on every reset (`md_srst`); the cache's valid flag must survive Reset Enter,
    because the Pocket reads the slot back while the MCU reboots (docs/BOOT_SPEC.md and section 21.1). `paprium_xlink`
    (core_top, `xmem_reset` = PLL lock only) already sits next to the CRAM controller, the APF data loaders and the
    datatable writer that the cache slot uses. So v1.3 puts CACHE / CACHE_LOADED / BAR at XLINK 0x40-0x48 (XLINK now
    decodes `addr[6:2]`), and FPGAIO slots 24-31 stay reserved (v1.0-v1.2 had pencilled the cache registers into FPGAIO
    23-31).
16. **CRAM keeps its contents across core loads, so "the header looks good" is not proof the file was loaded.**
    (Checked: the `paprium_cram.sv` header says "the CRAM keeps power across core loads".) With the file deleted, a
    later boot without a power cycle could still find the previous session's bank in CRAM and skip the unpack (B Jam's
    hardware check "delete the file and it unpacks once more" would then fail). **CACHE_LOADED** counts the bytes the
    Pocket actually wrote into the cache window at this power-on; the firmware trusts the CRAM only when it equals the
    file size.
17. **File byte i lands at MCU byte 0x0900_0000 + i.** (Checked by reading `data_loader.sv` and the `paprium_cram.sv`
    port B lanes only; the sound-cache build's simulation must confirm it, test I10.) With `bridge_endian_little` = 0
    the loader byte-reverses each big-endian bridge word and writes the low 16 bits first, so CRAM word 2k = {file byte
    4k+1, file byte 4k} and word 2k+1 = {4k+3, 4k+2}; port B maps MCU byte b to CRAM word b/2, low byte for even b.
    Little-endian on both sides, no swap.
18. **The chip's audio memory is one contiguous SDRAM area, so v1.3 keeps its layout.** (From our study of the cart.)
    The wave bank region (0x152000 B), the BGM echo ring and the SFX echo ring sit back to back; the CRAM map (3.8)
    keeps those three at the same distances, so any read past a sample's end that runs past the bank reads what the
    chip would read there.
19. **The 88 configuration restarts the DT DMA on any changed configuration byte, not only on a mode change.**
    (From our study of the cart.) Its only early exit is "same byte as last time"; a byte that changes only bit 2 or 3
    still re-runs the whole body (both DMA rings restarted at index 0 in DT). So a CONFIG write applies the scheduler
    side effects every time, and the firmware writes CONFIG exactly when the chip's body would run (3.10.2).
20. **The DT curve's out-of-table window is exactly 0x30000 bytes.** (Estimated.) v1.3 reserves that whole window in
    CRAM with the curve at its own place, so decision 3c can go either way (clamp, or the window placed in CRAM)
    without a refit: CONFIG bit 3 DTWIN (3.10.2).
21. **The synth state fits the planned 256 x 32 state RAM only with the chip's byte-valued fields stored as bytes.**
    (From our study of the cart; the word counts are estimated.) At the chip's own types a voice needs 15
    words and a channel 9 (304 words, a second M10K). The envelope rates, the voice state and the SFX format and
    rate only ever hold byte values, so v1.3 stores those as u8: 11 words a voice, 8 a channel, 240 in all. Every value their writers can produce is kept
    exactly; the synth's fuzz tests stay inside that domain.

---

## 1. Scope, version and ownership

**Version register.** The NEORV32 SYSINFO `USER_CODE` word (MCU 0xFFFF_FFE4, read-only) holds the interface version
(proposed): `0x5049_MMmm` ('P','I', major, minor). v1.0 = 0x5049_0100; v1.1 (FPGAIO slot 16 VSCNT added) =
0x5049_0101; v1.2 (the RTL sprite decoder, slots 17-22; proposed) = **0x5049_0102**; v1.3 (the synth step: STAMP_A,
FEAT, CAUSE.BLK, the XLINK cache / bar registers, the synth in region 0x06, the 88 KB IROM; frozen 2026-10-21) =
**0x5049_0103**. 0.2.6 reads 0. Cost 0 ALM (a SYSINFO constant).
- crt0 checks it before anything else. Major must equal the firmware's; minor must be at least the firmware's. On a
  mismatch the firmware keeps the 68000 held and stops (TEST: a boot-milestone code). This also stops a pocket72k image
  running on a 0.2.6 bitstream (docs/LAYOUT.md warns it would corrupt itself).
- A minor bump may add registers in reserved slots and bits. A major bump changes any existing meaning.
- **v1.3 adds two rules (finding 14).** (1) Rows marked *interim* in v1.0 (region 0x06's audio_sfx FIFOs, region 0x07,
  FPGAIO slots 3-4) may retire at a minor bump; FEAT (4.10) says which are present. (2) From v1.3 crt0 also reads FEAT
  right after USER_CODE: every FEAT bit the image needs must be 1 (an image that drives the interim FIFOs needs SFXFIFO,
  a synth image needs SYNTH, a cache image needs CACHE), and the IROM size (FEAT[23:16]) must be at least the image's
  layout; otherwise it holds the 68000 and stops, as for a version mismatch.

**Ownership.**

| part | owner | where it is specified |
|---|---|---|
| NEORV32 set-up, memory map, FPGAIO, interrupt lines, timer, option word, MCU side of the register file and byte views, resets of all of these | **this page** | sections 2-8 |
| register file storage, the 68000 view (`$1FE4` composer, busy, window, view switch, FM XOR), the stream engine behind SPTR/GO | cart RTL | docs/CART_FPGA_SPEC.md sections 2-10 |
| level code, scheduler, status layer, job queue, decoder queue and FIFO-A target (board accessor), clock figures in code | firmware | the firmware's interrupt design (our notes); this page sections 6-7 for the rules it must obey; docs/STAGE1_PLAN.md track W |
| console-side RTL (vram_alt, SDRAM yield, video, TeraDrive stub, HOF, Arcade Mode, menu mute hook) | other items of the first 0.3.0 fit | the project plan; docs/STAGE1_PLAN.md tracks V and F |
| v1.3: the synth's MCU side (region 0x06), the CRAM die-0 map, the cache slot's XLINK registers and board contract, the first-boot bar, STAMP_A, FEAT, CAUSE.BLK | **this page** (frozen); built by the RTL items of the synth step (the cache slot and bar for test build 4a; the synth items) | sections 3.8-3.10, 4, 21 |
| v1.3: the synth's logic (blocks B1-B10, the chip functions it follows sample for sample) | the synth RTL items | the synth's design notes (not published) |

---

## 2. NEORV32 configuration

NEORV32 1.4.8.1 (`neorv32_top_stdlogic`), RV32IM + Zicsr, classic Wishbone, no internal IMEM/DMEM, bootloader off
(checked in `mcu_core.sv` and `neorv32_top_stdlogic.vhd`). The MCU fast path: the IROM / WRAM tightly coupled
on the processor bus (last row, section 20); everything else in this table is unchanged.

| generic / port | 0.2.6 (checked) | v1.0 | why | ALM |
|---|---|---|---|---|
| `CLOCK_FREQUENCY` | literal 53693175 | `` `CLK_FREQ `` (proposed) | one clock value (section 7); SYSINFO_CLK (0xFFFF_FFE0) then reports it | 0 |
| `USER_CODE` | 0 | 0x5049_0100 (proposed) | interface version (section 1) | 0 |
| `CPU_EXTENSION_RISCV_C/A/U/E`, `PMP_USE`, `Zifencei` | off | off | RV32C costs ALM (an earlier design that used it was rejected) | 0 |
| `CPU_EXTENSION_RISCV_M`, `FAST_MUL_EN`, `FAST_SHIFT_EN` | on (3 DSP) | on | | 0 |
| `IO_MTIME_USE` | true (106.4 ALM) | **false** | replaced by the FPGAIO timer (section 4.3); `mtime_irq_i` becomes live | -106 |
| `IO_UART_USE` | true, TX unconnected (29.3) | **false** | no printf on the Pocket; TEST printf only in host builds | -29 |
| `IO_WDT_USE` | true, unused (25.6) | **false** | the chip's watchdog is firmware on the timer | -26 |
| `IO_GPIO_USE` | true (16.8) | **true** | F-D1: the option word and the menu bit stay on GPIO input | 0 |
| `mext_irq_i` | `mbx_irq` | CAUSE OR (section 4.2) | | in 4.2 |
| `mtime_irq_i` | 0 | timer level (section 4.3) | | in 4.3 |
| `msw_irq_i` | 0 | MSIP (section 4.4) | | in 4.4 |
| `gpio_i` | option word | option word v1.0 (section 5) | | +1..+3 |
| bus timeout | 127 cycles (`bus_timeout_c`) | unchanged | every region must ack well inside it | 0 |
| IROM / WRAM | on Wishbone (`mcu_wram`, `mcu_irom`) | **fast path: tightly coupled** - `MEM_TCM_IMEM_SIZE` / `MEM_TCM_DMEM_SIZE` = 16 MB (the whole regions 0x00 / 0x80, aliases kept) on the `tcm_*` ports; `MEM_INT_*_USE` stay false, so SYSINFO reads as before | fetch 2 cycles instead of 4, load / store 5 instead of 10 / 12 (section 20) | ~-76 (estimated) |

ALM figures are measured entity rows of a fit with CPU MATE at fitter seed 4; the fitter re-packs, so the net is
estimated.

**CSR facts the firmware relies on** (checked in 1.4.8.1): `mcycle`/`mcycleh` count every clock except in sleep (no WFI
in v1.0); `time`/`timeh` read 0 once MTIME is gone (do not use them); mcause codes MEI 0x8000000B, MTI 0x80000007, MSI
0x80000003; `mie` bits MEIE 11, MTIE 7, MSIE 3, FIRQ0-3 16-19 (stay 0).

**Removed units leave holes, not quiet addresses** (read in `neorv32_wishbone.vhd` and `neorv32_top.vhd` only):
0xFFFF_xxxx never reaches Wishbone (the gateway's boot-ROM test), so a load or store to the old MTIME
(0xFFFF_FF90-9C), UART (0xFFFF_FFA0-A4) or WDT addresses gets no ack and ends in the CPU's bus-timeout access fault.
The new-core firmware must hold no such access: TEST `printf` is compiled out on the Pocket board, and the glue's
MTIME reads go to TIMER. The rvboard model (our RV32 board simulator) should fault on them too.

---

## 3. Memory map

The region decode stays `addr[31:24]` (checked in `mcu_core.sv` lines 29-41). Access costs are measured with our RV32
cycle bench unless marked.

| region | MCU range | v1.0 contents | width / view | cost (cycles) | change from 0.2.6 |
|---|---|---|---|---|---|
| 0x00 | 0x0000_0000-0x0001_1FFF | IROM 72 KB (3.1) | 32-bit, read-only | fetch 4, load 10; fast path: fetch 2, load 5 | 54 -> 72 KB, select fixed |
| 0x00 | 0x0000_0000-0x0001_5FFF | v1.3, the synth fit (FEAT IROM = 88): IROM 88 KB (3.1) | 32-bit, read-only | as the fast path | 72 -> 88 KB (decision 2); test build 4a  keeps 72 |
| 0x01 | 0x0100_0000-0x0100_007F | FPGAIO, 32 slots (4) | 32-bit registers | 10 (measured: +1 for the registered read); fast path: 7 | slots 7-15 new, 16 VSCNT (v1.1), 17-22 the sprite decoder (v1.2), 14 STAMP_A and 23 FEAT (v1.3), 24-31 reserved, slot 1 retired |
| 0x02 | 0x0200_0000-0x0200_1FFF | RAMDP 8 KB, halfword view (3.3) | MCU halfword at +A = 68000 word A | 9; fast path: 7 (registered ack) | `$1FE0-$1FFF` cells become MCU-only |
| 0x02 | 0x0280_0000-0x0280_1FFF | RAMDP **byte view** (3.3) | MCU byte A = 68000 byte A; read-only | 9; fast path: 7 | new (F-D1) |
| 0x03 | 0x0300_0000-0x031F_FFFF | SDRAM workspace 2 MB (SDRAM byte 8 MB +) | byte-native | 18-21 (max 30); fast path: word 15, byte / half 11 (mean, no port-1 load) | unchanged |
| 0x04 | 0x0400_0000-0x047F_FFFF | flash word view: the 8 MB ROM image in SDRAM | halfword at A = 68000 word A | 18-21; fast path: word 15, byte / half 11 | unchanged |
| 0x04 | 0x0480_0000-0x04FF_FFFF | flash **byte view** (3.5) | byte A = ROM byte A; read-only | 18-21; fast path: word 15, byte / half 11 | new (F-D1) |
| 0x05 | 0x0500_0000-0x0500_1FFF | battery save 8 KB (3.6) | byte lanes (RMW) | own ack | 4 -> 8 KB (docs/STAGE1_PLAN.md question Q1) |
| 0x06 | 0x0600_0000-0x0600_0FFF | FEAT.SFXFIFO (test builds 4 and 4a): audio_sfx FIFOs (interim). FEAT.SYNTH (v1.3, the synth fit): **the synth** (3.10) | synth: 32-bit registers, byte lanes honoured | 9; synth: registered, ~7-9 (at the fast-path costs, estimated) | v1.3: the synth replaces the FIFOs on the synth fit (finding 14) |
| 0x07 | 0x0700_0000 / 0x0780_0000 | MD+ block / EverDrive FIFO stub (interim; FEAT.MDP) | | 9 | gone from the synth fit (FEAT.MDP = 0: unassigned) |
| 0x08 | 0x0800_0000-0x0803_FFFF | Pocket SRAM 256 KB (3.7) | byte-native, whole-word reads | lw 14 | map defined |
| 0x09 | 0x0900_0000-0x093F_FFFF | CRAM die 0, words 0x000000-0x1FFFFF (3.8) | 16-bit halves | <= 80 a word | v1.3: a fixed map (3.8), shared with the cache slot and the synth |
| 0x0A | 0x0A00_0000-0x0A00_007F | XLINK register block (3.9) | 32-bit | 1-clock ack | v1.3: decodes `addr[6:2]`; 0x40-0x48 the cache slot and the bar |
| 0x0B | 0x0B00_0000-0x0B00_001F | cart register file, MCU side (3.4) | 16-bit registers at the chip offsets; `+4`, `+6`, `+A`, `+C` stored, the rest act on write and read 0 | ~10 (estimated) | new (F-D1) |
| 0x80 | 0x8000_0000-0x8000_BFFF | WRAM 48 KB (3.2) | byte lanes | load 10, store 12; fast path: load 5, store 5 | 32 -> 48 KB, write path, lock |
| 0xFF | 0xFFFF_FF80-0xFFFF_FFFF | NEORV32 internal IO: GPIO, SYSINFO | | 8-9 | MTIME, UART, WDT gone |
| others | 0x0C-0x7F, 0x81-0xFE | unassigned | | ack at once, read 0xFFFF_FFFF, writes ignored (checked in `paprium_cart.sv` lines 155-169): 9; fast path: 6 | 0x0C-0x0F kept free for v1.x |

Aliasing (unchanged rule): each region repeats above its decoded size. Firmware uses only the ranges above.

### 3.1 IROM, 72 KB (locked 2026-10-10)

| range | bytes | holds | built as |
|---|---|---|---|
| 0x0000-0x535F | 21,344 | crt0 (reset vector at 0), `.text` | rom0: 8,192 x 32 (`mcu.txt`), 32 M10K at 8192x1 |
| 0x5360-0xD2EB | 32,652 | CPU MATE brain, bytes fixed (the new-core brain: md5 b9a76592, with the counter fix; 0.2.6: 1b64e14d) | rom0 tail + extension |
| 0xD2EC-0x11FFF | 19,732 | `.text_hi`, `.rodata`, `.data` image | extension: 10,240 x 32 (`mcu_ext.txt`), 5 slices of 2048x32 = 40 M10K |
| 0x12000-0x1FFFF | - | not backed: reads undefined, never used | - |

- **Select and index (proposed; measured in the draft):** `sel_x <= addr[16] | addr[15]` (registered with the M10K
  address); extension index `{addr[16], addr[14:2]}`; output `sel_x ? ext : rom0`. Fetch and load stay one clock, so 4 /
  10 cycles as today. The MCU fast path: the same `mcu_irom` answers on the processor bus (`mcu_tcm_irom`, registered
  ack the clock after the request): fetch 2, load 5 (section 20).
- **Images:** unchanged format (`mcu.txt` 8,192 words; `mcu_ext.txt` 10,240 words, 16 words a line). The
  `update_mif` route must be proved again once on the first new-core fit: `mkmif.py` output = the Quartus db mifs byte
  for byte, as was done for 0.2.6.
- **Alternative (not taken):** explicit 32 KB (8192-deep) + 8 KB (2048-deep) extension arrays: a 3:1 select overall,
  ~10-15 ALM less, but two image files and a new `mkmif` mapping.
- Read-only: a store to region 0x00 is acked and dropped (checked in `mcu_wram`).

**v1.3: 88 KB on the synth fit** (B Jam's decision 2, 2026-10-21; test build 4a keeps 72 KB; FEAT[23:16]
says which):

| range | bytes | holds | built as |
|---|---|---|---|
| 0x0000-0xD2EB | as 72 KB | crt0 / `.text`, the brain hole 0x5360-0xD2EB (bytes fixed) | rom0 32 KB + extension slices 0-2 |
| 0xD2EC-0x15FFF | 36,116 | `.text_hi`, `.rodata`, `.data` image | extension: 14,336 x 32 (`mcu_ext.txt`), 7 slices of 2048x32 (7 M10K each at 2Kx5, 49 M10K; measured slice geometry) |
| 0x16000-0x1FFFF | - | not backed: reads undefined, never used | - |

- Select and index are the 72 KB formulas unchanged: `sel_x = addr[16] | addr[15]`, extension index
  `{addr[16], addr[14:2]}` (0x8000-0xFFFF -> 0x0000-0x1FFF, 0x10000-0x15FFF -> 0x2000-0x37FF); only the depth mux grows
  from 5 to 7 slices (one more level on `tcm_irom_out`, +0.3..+0.8 ns, estimated).
- Image: `mcu_ext.txt` grows to 14,336 words (16 a line); `mkmif.py` and the final fit check's tools learn the 7-slice
  geometry (a later option, one 2Kx5 array instead of slices, would need them worked out again).
- The firmware links `pocket88k` for it (a new layout, `board/pocket/link/`); its crt0 refuses FEAT IROM < 88.
- From 0.3.0 the bitstream's IROM image holds only a boot stub; the firmware's IROM image arrives in the firmware file
  (Fafrium, `docs/FAFRIUM.md`) and the stub copies it in before the firmware starts. Until then the IROM takes word
  stores; from the firmware's start on it is read-only, as above. Section 22 has the details.

### 3.2 WRAM, 48 KB

Layout (locked, `board/pocket/link/pocket72k.json`):

| range | KB | region | written by | lock |
|---|---|---|---|---|
| 0x0000-0x181F | 0-6 | `wram_data`: hot `.data`/`.bss`, glue `.noinit` | firmware | never |
| 0x1820-0x2ABF | 6-10 | `brain_data` (fixed by the brain link) | brain | never |
| 0x2AC0-0x2BFF | 10 | `wram_sched`: scheduler state, timer wheel (not cleared by crt0) | firmware | never |
| 0x2C00-0x6BFF | 11-26 | code window: `cf.bin` at 0x2C00, image tables 0x4110-0x4647, glue, spill | bitstream | **always** (constant) |
| 0x6C00-0xABFF | 27-42 | `wram_upper`: synth state, scaling buffers, extra `.bss`, WRAM-ROM, boot overlay | firmware / bitstream | per WLOCK bit (proposed) |
| 0xAC00-0xBFFF | 43-47 | stack, top 0x8000_BFFC | firmware | WLOCK must leave it 0 (firmware rule) |
| 0xC000-0xFFFF | 48-63 | not backed | - | **always** (constant): stores dropped, loads undefined |

The MCU fast path (checked in `memory.sv` and `mcu_core.sv`): four byte lanes of 12,288 words
(`ram_b0`..`ram_b3`, rising edge) behind `mcu_tcm_wram` on the processor bus; lane i = MCU byte 4 x word + i; images
`wram_b0.txt`..`wram_b3.txt` (12,288 lines each, the same bytes as the pair below, which the firmware build still
writes); the same lock rule, decided in the request clock on a full-cycle path. Load 5, store 5 (section 20). The rest
of this subsection is the design before the fast path.

Physical (proposed): 24,576 words x 16 (two byte arrays `ram_lo`/`ram_hi`, negative-edge M10K as today), word address
`addr[15:1]` (today `[14:1]`, `paprium_cart.sv` line 224). Quartus builds it as 3 depth slices of 8192x1: 48 M10K, +16
(measured geometry, 1 M10K per KB). Images `wram_hi.txt`/`wram_lo.txt` grow to 24,576 lines each (docs/LAYOUT.md).

**Write path (proposed; it takes the decode off the half-cycle path, finding 4).**
- Today (checked in `mcu_core.sv` lines 181-257): `idle` starts at 0, so half 0 is written in cycle 0, with `we` built
  from the region decode (`addr[31:24] == 0x80`) and `LOCK_MAP[addr[13:9]]`; half 1 is written in cycle 3 with the ack.
- v1.0: in cycle 0 register `wsel = store & region-is-WRAM & ~lock(addr[15:10])`; write half 0 in cycle 1
  (`wsel & state == 1 & lanes`), half 1 in cycle 3 (`wsel & state == 3 & lanes`); the ack stays in cycle 3. Reads are
  untouched. What remains on the half-cycle path: `wsel`, the lanes and Quartus's slice decode on `addr[15:14]` (one
  LUT).
- The read side keeps one depth-mux level (3:1 instead of 2:1, select registered with the address at the negative edge
  by the RAM itself).

**Lock map (proposed):** `lock(k) = CONST(k) | (27 <= k <= 47 ? WLOCK[k-27] : 0)` for KB k = `addr[15:10]`.
- `CONST` = KB 11-26 (the window, as 0.2.6's `LOCK_MAP 0x07FFF800`) and KB 48-63 (unbacked).
- WLOCK (FPGAIO slot 15) is write-1-to-set and sticky until reset, so the firmware chooses its WRAM-ROM extent per
  build without a refit. A locked store is acked and dropped, as today.
- Alternative (not taken): a constant 48-bit map. It must then be a subset of every future WRAM-ROM extent, because a
  lock over data would drop real stores.

### 3.3 RAMDP (68000 cart RAM `$0000-$1FFF`)

- **Halfword view 0x0200_0000** (unchanged; checked in `ramdp_io.sv`): MCU halfword at +A = 68000 word A; byte lanes
  per `we[3:0]`; 9 cycles. The 68000 side writes through the 2-sample strobe filter (`cpu_we_st == 011`).
  The MCU fast path: a registered ack (second bus clock; the store still writes once, in the first): 7 cycles.
  The earlier design's constant ack read the word at the address the bus showed a clock BEFORE the access, right only
  while the fetch was slow (section 20).
- **`$1FE0-$1FFF` on the MCU side (proposed):** plain RAMDP cells that the 68000 never sees in v1.0 (it sees the
  register file). MCU reads return what the MCU last wrote there. Nothing should use them: the boot hand-off block is a
  board constant (docs/BOOT_SPEC.md section 3), and the test rig fails on any MCU read there (docs/CART_FPGA_SPEC.md
  section 15.1).
- **Byte view 0x0280_0000 (proposed; decision F-D1 chose the address):** `addr[23] = 1` selects it. Read = the same
  RAMDP word with the bytes of each halfword swapped, so MCU byte A = 68000 byte A (the chip's 0x6886_0000 view). Stores
  through it are dropped (the chip only reads it: MegaWire init's header reads, docs/CART_FPGA_SPEC.md section 2.2).
  Covers all 8 KB, including the hidden `$1FE0-$1FFF` cells.
- Timing: the swap is one 2:1 choice per bit with a registered select; it should merge into the AND stage of the
  `mcu_dati` mux (estimated). A path to watch in static timing analysis (STA). Fallback if a fitter seed fails there:
  drop the swap in RTL and swap in the board accessor (the address stays reserved).

### 3.4 Cart register file, MCU side (0x0B00_0000 + chip offset; decision F-D1)

The chip's `strh`/`ldrh` to 0x6804_0000 + off map to 0x0B00_0000 + off. 16-bit registers; a word access covers the
pair `{reg[off+2], reg[off]}` (the RAMDP lane order); halfword stores (`sel` 0011 / 1100) and byte stores are honoured
per lane on the four stored registers (docs/CART_FPGA_SPEC.md section 3.5). Writes take effect at the access's first
bus cycle, in program order; nothing is posted (the 68000 must never see `$1FEA = 0` before the `$1FE6` write the chip
made first, docs/CART_FPGA_SPEC.md finding 11). Read data and ack are registered (section 9). Storage and every
68000-side effect belong to the cart RTL (`paprium_regfile.sv`, docs/STAGE1_PLAN.md items C1-C3); this table is what
the MCU sees.

**Only the registers something reads are stored** (`$1FE4`, `$1FE6`, `$1FEA`, `$1FEC`): the chip reads only those
(and `$1FEE`'s OTA status, which reads 0 here; checked in docs/CART_FPGA_SPEC.md section 3.2). The other offsets act on
write and are not stored; the board accessor keeps a firmware shadow of every write and logs it for the chip-runner
test (docs/CART_FPGA_SPEC.md section 15.1), so that test sees the same write sequence.

| off | MCU addr | reg | reset | MCU write | MCU read | RTL side effect (cart RTL) | levels that use it |
|---|---|---|---|---|---|---|---|
| +0, +2 | 0x0B00_0000/02 | unused | - | dropped | 0 | - | none |
| +4 | 0x0B00_0004 | `$1FE4` control word | 0 | store | **the stored MCU word** (heartbeat tests bit 11) | none; the 68000 reads the composer `busy<<2 \| model` | boot (app init 0x46F8), L1/L3 via the status layer, L2a (heartbeat read, fatal 0x4200) |
| +6 | 0x0B00_0006 | `$1FE6` status | 0 | store | stored | none; the 68000 reads it as is | boot (app init, MegaWire bits 0-2), L1/L3 status layer |
| +8 | 0x0B00_0008 | `$1FE8` window | - | act, not stored | 0 | bit 0 = 1: `window_en := 1`; 0: `window_en := 0`, `mini_view := 1` | L1 (DB06, DA direct, F2, 84) |
| +A | 0x0B00_000A | `$1FEA` mailbox B | 0 | store; clears the busy guard; raises no IRQ | the last value written by either side | 68000 write: CAUSE.B set; guard set if high byte DA/DB/F2 | L1 (read post, write 0 at finish), boot (warm-path read) |
| +C | 0x0B00_000C | `$1FEC` mailbox A | 0 | store; no IRQ | the last value written by either side | 68000 write: CAUSE.A set | L1 (read, and the write 0 after the tick in the first new-core firmware; L2b in the FW_S5 firmware) |
| +E | 0x0B00_000E | `$1FEE` | - | act, not stored | **0** (OTA status polls see no flash; docs/CART_FPGA_SPEC.md section 3.1) | 0xAF5B: `window_en := 0`, `mini_view := 1` | L1 (84, 85), L2a (fatal paths) |
| +10 | 0x0B00_0010 | `$1FF0` FIFO-A target | - | dropped (firmware shadow) | 0 | none: the firmware writes RAMDP itself | L1 / L2b (packet), boot |
| +12 | 0x0B00_0012 | `$1FF2` stream control | - | act, not stored | 0 | 0, or bit 15 set: `stream_valid := 0`, guard cleared; 0x4000 / 0x4002 / 1: no effect. v1.2: 0x8000 = decoder START, 0 or bits 15:14 = 11 = decoder STOP (4.9) | L1 |
| +14 | 0x0B00_0014 | `$1FF4` queue high | - | v1.2: latched (the next push's address bits 22:16, 4.9) | 0 | none | L1 |
| +16 | 0x0B00_0016 | `$1FF6` queue low / clear | - | v1.2: odd = decoder CLEAR, even = PUSH (4.9) | 0 | none | L1 |
| +18..+1E | 0x0B00_0018-1E | unused | - | dropped | 0 | - | none |

Firmware hooks (board layer, not RTL): after the first FIFO-B chunk, the board points the stream and writes SPTR
then GO (section 4.5). v1.2: the sprite-block decoder is RTL (4.9): the firmware writes the chip's decoder sequence and,
before each START, the output base DEC_BASE (slot 17); the RTL loads SPTR, decodes and GOes by itself. FIFO A and FIFO B
ports have no MCU address: the firmware writes RAMDP and the stream engine directly (docs/CART_FPGA_SPEC.md section 9).
Ordering rule from the firmware design: a job's SPTR/GO stores come before the status write that clears `$1FE6` bit 14
(the reply's `$1FEA` write has already cleared the guard, so a stale `stream_valid` must stay invisible behind bit 14;
the game reads bit 14 before bit 2 after every DA, checked).

### 3.5 SDRAM workspace and flash views

- **Workspace 0x03** (unchanged; checked in `paprium_mcu_mem.sv`): 2 MB at SDRAM byte 8 MB; two 16-bit SDRAM accesses
  per 32-bit MCU access on port 2; no execute-in-place.
- **Flash word view 0x0400_0000** (unchanged): `{2'b00, addr[22:2], 0}`; writable (the boot patch at `$81104` is
  written into the image).
- **Flash byte view 0x0480_0000 (proposed; decision F-D1 chose the address):** `addr[23]` latched with the base address
  in state 0; each 16-bit half is byte-swapped as it is captured into `mcu_dati` (a registered capture, so no new path
  into the CPU). Byte A = ROM byte A. Stores through it are dropped (`mem_wrl`/`mem_wrh` gated). Users: the chip's
  unpackers and block tables (stage 3: the unpackers, zoom, saves and MegaWire).

### 3.6 Battery save 0x05

**8 KB** (B Jam's decision of 2026-10-11, docs/STAGE1_PLAN.md question Q1: "replicate the cart", like its M24C64),
`paprium_backup`, MCU port with read-modify-write byte lanes, host port to the APF save slot (big-endian file; checked
for the 4 KB module). Cost +4 M10K, an 8 KB `.sav`, and a one-time import that accepts 0.2.x's 4 KB files. The game
cannot see the EEPROM size; only the `.sav` file can. Contents by firmware step (erratum 2026-10-13: this paragraph said
"0x900-0xFFF the TEST debug region" for stages 1 and 2 (the new core and the sprite engine); the new-core code uses the
upper half from question Q1 on, 2026-10-12, the first batch of errata):
- 0x000-0x8FF: the game's saves in the 0.2.x layout (stages 1 and 2, the new core and the sprite engine). A 0.2.x 4 KB
  `.sav` loads into 0x000-0xFFF as it is; the upper half starts at the RAM's power-up 0.
- 0x900-0xFFF: 0.2.6's TEST snapshot window and trap record (TEST images only, written by the 0.2.6 bodies the new
  core still runs).
- **0x1000-0x1FFF: the new-core TEST debug save** (`board/pocket/dbgsave.h`, decoded by `tools/dbgsave.py`; a size
  probe at boot turns it off when the RAM is 4 KB). RELEASE writes nothing above 0x0FFF.
- From stage 3 (the unpackers, saves, zoom and MegaWire) on: the chip's format to 0xAE0, the rest of the lower half
  reserved; the debug save stays in the upper half.

### 3.7 Pocket SRAM 0x08 (MegaWire run-in-place; loader kept)

No RTL change from 0.2.6 (checked in `paprium_xram.sv` and `core_top.sv` line 1396). B Jam's decision at stage 0
(the skeleton stage of the 0.3.0 work) keeps `xram_data_loader` (+109..+135 ALM, measured; the plan had listed deleting
it as a lever). **Test build S3b, the MegaWire code (2026-10-27):** code fetched from SRAM needs the NEORV32 Wishbone
gateway fix (the SRAM fetch bench, an RTL simulation: the 1.4.8.1 gateway of test build 5 loses a store or a load when
an SRAM prefetch is cancelled by a return to the IROM / WRAM; the fix rides the refit made for the console-reset
change).

| SRAM bytes | use | lock |
|---|---|---|
| 0x00000-0x0FFFF | **SRAM image**: from 0.3.0 the core's boot stub copies it from the Little-Man Firmware file (docs/FAFRIUM.md; before that, an APF data slot loaded it through bridge 0x4000_0000 + offset): the 64-byte header, then the MegaWire code and rodata (run in place) | XCFG bit 16 (MCU stores below 0x10000 dropped), set by read-modify-write after the image check |
| 0x10000-0x12001 | CPU MATE (buddy) PRG capture window + cursor | buddy (unchanged) |
| 0x12002-0x17FFF | free | - |
| 0x18000-0x18BFF | CPU MATE's rate hash (`buddy/buddy.h`) | - |
| 0x18C00-0x1D897 | MegaWire RAM (19,608 B: the task's step state and the information block's buffer 112 B, TEST counters 12 B, then the chip's task block 444 + 4 B, driver block 4,416 B, EEPROM record 96 + 4 B, USART3 TX buffer 1,108 B, E7 staging 256 B, RX ring 8,192 B; then the A858 screen's two packed pages and its and the text's state; `core/mw/mw.h`), cleared once a boot after the image check | - |
| 0x1D898-0x1FFFF | free (cold-pack data) | - |
| 0x20000-0x3FFFF | buddy Word RAM mirror | buddy (unchanged) |

- Run in place: instruction fetch from 0x08 is allowed; loads always read the whole word (NEORV32 does not drive
  `wb_sel_o` on a fetch, `paprium_xram.sv` lines 81-86). Costs (measured by the SRAM fetch bench on test build 5's
  xram path with the gateway fix, no snoop traffic; clk_sys cycles): from IROM code lw / lh / lb 20.0, sw 14.9 back to
  back, sh / sb 8.0; code fetched from SRAM: an ALU instruction 17, a taken branch / jal 35, lw SRAM data 36, sw / sh /
  sb SRAM 32.8 / 25.9 / 25.9, lw RAMDP / XLINK 23.0, a flash word 31.4; +4.6-9.0 a class under back-to-back CPU MATE
  snoop traffic. (The v1.0 text's "lw 14" and "~3.5x IROM" are superseded: ALU code runs 8.5x slower from SRAM.) Rule:
  nothing on a reply path runs from SRAM; the trap vector stays in IROM; the MegaWire task runs in the thread (L3).
- Image header (64 B at SRAM 0x0, `board/pocket/s3_sram.c`): magic 'PMW3', version 0x00010002, length (4-aligned,
  0x44..0x10000), the CRC-32 (IEEE) of the hot part [0x40, hot end), the link id (a number the build derives from the
  link's objects, the same in the header and in the IROM's check, so a file from another build is refused), the hot end
  (an offset) and the CRC-32 of the cold part [hot end, length). The hot part is the MegaWire task's code; the cold part
  (the A858 screen, the cart program's text, page A) is reached only through the screen. The firmware calls into the
  image only after the check: magic, version, link id, length and hot end, and the hot part's CRC-32 (computed from the
  IROM in whole-word loads with a 16-entry table, the same result as bytewise; the SRAM fetch bench measured 39.15 ms
  for 30,032 B bytewise). Any failure: the MegaWire code does not run this boot (the MegaWire behaviour of the reference
  build: test build 5, the synth build B Jam tested on hardware, which this firmware is compared with). Until 0.3.0's
  firmware file the check also asked for XLINK LOADED >= length / 2 (a file came in at this power-on) and LOST[15:0] =
  0. From 0.3.0 the image comes inside the firmware file: the boot stub copies it into SRAM after checking the whole
  file, the APF loader writes nothing there and LOADED reads 0, so the check no longer reads either count (section 22).
  The cold part's CRC-32 is checked right after it (`s3_sram_cold_ok`); a refusal leaves the task running and the A858
  screen uncalled. The check is the thread's first work after the 68000's release (`core/mw/mw_boot.c`), not a step of
  the boot, so the 68000 starts at test build 5's time; until it has passed, the MegaWire gates take test build 5's
  paths (the game's first MegaWire post is C6, 169 frames after its start). Measured in the rig model (our RV32
  model of the board running the firmware images, priced at the fast path's measured cycle costs): the release at
  230,762 TEST / 141,348 RELEASE cycles (test build 5: 227,892 / 141,558;
  TEST's +2,870: the boot's first block interrupt lands just before the release here and just after it on test build
  5, so its main-loop pass runs first); on the RV32 board model the check (both parts and the RAM clear) ends 20.7 /
  19.7 ms after the release. Earlier (the rig model): a check before the release held the 68000 to 1,130,642 / 967,022
  cycles bytewise, past the VDP's first VS (C6 one VS later), and to 425,983 / 330,455 with a faster CRC; at that
  release the rig's game frames stood 198K cycles later against its VS count, and the C6 hold came out one game VBlank
  shorter than test build 5's in every TEST run. On the board the VDP makes no sync while CTRL.HOLD holds the
  console (`core_top.sv`: md_board's ext_reset is the hold), so the VS count and the game's frames both start at the
  release there.
- XCFG is a plain read-write register: every XCFG write keeps bit 16 by read-modify-write (measured on the SRAM fetch
  bench: a write that leaves it out unlocks the image area).
- XCFG resets at power-on only, so the lock and the image survive a Soft Reset (APF loads data slots at core start).
  Whether another APF reset reloads the slot (open item O7, section 13) is a hardware check; the image check runs at
  every boot either way.

### 3.8 CRAM 0x09

Unchanged (checked in `paprium_cram.sv`): die 0 words 0x000000-0x1FFFFF through port B (two non-atomic halves, aged so
a 32-bit access stays far under the 127-cycle bus timeout). XCFG CRAM fields must stay 0 (defaults): at the maximum
setting port B waits 356-428 clocks (measured in simulation). The album ring (0x200000+) and the echo line (0x210000+)
are outside the MCU window. The sound-cache registers are frozen separately, before test build 4a (done:
v1.3, 3.9).

**v1.3: the die-0 map inside the MCU window** (byte offsets from 0x0900_0000 = CRAM die-0 byte addresses; CRAM word
w holds bytes 2w (low byte) and 2w+1; the MCU, the APF cache slot (21.1) and the synth (3.10) all use these
addresses; finding 17). The controller resets at power-on only, so every region keeps its contents across resets and,
the CRAM staying powered, possibly across core loads (finding 16).

| bytes (offset) | name | holds | written by | read by | from |
|---|---|---|---|---|---|
| 0x000000-0x0000FF | HDR | the sound-cache file's 256-byte header (format: test build 4b's boot overlay's, `board/pocket/boot/c4b.h`; any footer goes inside it: the BGM ring follows the bank directly) | APF load / MCU (4b, last) | MCU, APF flush | 4a |
| 0x000100-0x1520FF | BANK | the wave bank region: CRAM byte 0x100 + i = bank byte i (directory 4 KB, samples, tail; 1,384,448 B) | APF load / MCU (4b unpack) | synth (VOICE BASE), MCU (directory) | 4a (4a: a test pattern) |
| 0x152100-0x15C0FF | BGMRING | the BGM echo ring: 256 blocks x 40 pairs {L, R} s16 | synth (every block, any mode) | synth (DT prefill) | synth |
| 0x15C100-0x1610FF | SFXRING | the SFX echo ring: 256 blocks x 20 pairs {L, R} s16 | synth | synth | synth |
| 0x161100-0x16FFFF | - | free | - | - | - |
| 0x170000-0x170EFF | DACBUF_L | the chip's dac_buf_L: 1,920 x u16 (DT 12-bit codes; YM: curve >> 4 in L only) | synth (at the chip's indexes) | synth (DT playback), MCU (the $1880 copy: L[6i], L[6i+3]) | synth |
| 0x170F00-0x171DFF | DACBUF_R | the chip's dac_buf_R: 1,920 x u16 | synth | synth (DT playback) | synth |
| 0x172000-0x17FFFF | - | free | - | - | - |
| 0x180000-0x1AFFFF | CURVE_WIN | the curve's window (finding 20). The output curve (16,384 x u16) is at **0x194000-0x19BFFF, centre (index 0) 0x198000** | MCU at boot: the curve always; the rest of the window only if decision 3c picks the window placed in CRAM (CONFIG.DTWIN) | synth (curve[x] at 0x198000 + 2x) | synth |
| 0x1B0000-0x1DFFFF | - | firmware only, not part of the v1.3 block (Appendix A stays as frozen): MWTEXT (`POCKET_CRAM_MWTEXT`, after the block in `pocket_map.h`), added with the MegaWire code (test build S3b): the cart program, unpacked from the player's ROM (its 0x81 block at ROM 0x101A18) the first time the MegaWire code needs its text (the A858 screen); never shipped, rebuilt on the Pocket (`core/mw/mw_text.c`) | MCU | MCU | MegaWire |
| 0x1E0000-0x1FFFFF | - | free | - | - | - |
| 0x200000-0x28FFFF | SFXBANK | the SFX bank (552,748 B): CRAM halfword 0x200000 + 2k = the 68000 word at the bank's ROM start + 2k (written from the flash word view, 3.5) | MCU at boot (~0.14 s) | synth (SFX PTR / BASE) | synth |
| 0x290000-0x2FFFFF | - | free | - | - | - |
| 0x300000-0x3BFFFF | MODSTORE | reserved: the decoded music modules (594,544 B) if the SDRAM census (a count of the game's SDRAM writes) finds the chip's bank area not free | MCU | MCU | synth (fall-back) |
| 0x3C0000-0x3FFFFF | - | reserved; die word 0x1FFFFF is never accessed (header note above) | - | - | - |

- Byte order: every region is little-endian u16 / u32 at its chip offsets, as the chip's ARM reads them; the SFX bank
  is 68000 words as values (the chip's SFX mix reads them as 16-bit flash words, high byte first, checked).
- Nothing in the synth's map overlaps the cache image, so the Pocket's flush ([0, CACHE.SIZE)) never reads a ring.
- Test build 4a (FEAT.SFXFIFO): only HDR / BANK are used (the probe pattern); audio_sfx's own
  echo line stays at die word 0x210000, outside the window, as in test build 4.

### 3.9 XLINK 0x0A

Unchanged (checked in `paprium_xlink.sv`): XCFG, ID 'XRM2', diagnostics, option-D registers (LSTAT, LCLR, D_WORD,
D_BUSY, PEND, ARM, TICK, LCTRL). One new internal tap (proposed): `posts_s[0]` (bit 0 of the synchronised post count)
is routed to FPGAIO as the SEND event source (section 4.2). No MCU-visible change.

**v1.3: the sound-cache slot and the first-boot bar** (finding 15). XLINK decodes `addr[6:2]` (32 word slots,
0x0A00_0000-0x0A00_007F); offsets 0x00-0x3C keep their meaning (the 0x18 LOST word's high half, "CRAM ring writes
lost", now counts every CRAM port-A write lost, i.e. the cache load's). Reserved offsets read 0 and ignore writes,
XLINK's own rule. Present when FEAT.CACHE / FEAT.BAR (4.10); a v1.3 board without them reads 0 there (a v1.2 board's
`addr[5:0]` decode aliases XLINK 0x00-0x3C there).

| off | address | name | bits | reset | read | write | used by |
|---|---|---|---|---|---|---|---|
| 0x40 | 0x0A00_0040 | CACHE (v1.3) | [31] VALID, [22:0] SIZE | **0, at power-on only** (`xmem_reset`); kept across every reset | {VALID, 8'0, SIZE} | while VALID = 0: SIZE := [22:0] and VALID := [31]; while VALID = 1: ignored (one-shot until the next power-on) | boot (test build 4a's probe; test build 4b's boot overlay) |
| 0x44 | 0x0A00_0044 | CACHE_LOADED (v1.3) | [22:0] | 0 at power-on only | 4 x (32-bit APF bridge writes that landed in the cache window, bridge 0x6000_0000-0x603F_FFFF, since power-on), saturating at 0x7FFFFF | ignored | boot (the probe's and the boot overlay's check) |
| 0x48 | 0x0A00_0048 | BAR (v1.3) | [31] EN, [10:0] PX; read-only [26:16] W | 0 on every reset (`od_reset` = `sys_reset`) | {EN, 4'0, W[10:0], 5'0, PX[10:0]} | EN := [31], PX := [10:0] | first-boot unpack (the boot overlay) |
| 0x4C-0x7C | 0x0A00_004C-7C | reserved v1.x | - | - | 0 | ignored | - |

- **CACHE** drives the cache slot's size word in the APF datatable (21.1): `VALID ? SIZE : 0`, so the Pocket writes the
  file back at shutdown only once the firmware has set it, with exactly SIZE bytes. Firmware rule: write CACHE once per
  power-on, with VALID = 1 and SIZE = the image size, after the whole image (header last) is in CRAM; never write the
  cache image's CRAM bytes while VALID = 1 (the Pocket may be reading them back while the MCU reboots). SIZE must not
  exceed 0x152100 (the HDR + BANK regions, 3.8).
- **CACHE_LOADED** is the proof that the file came in at this power-on (finding 16): the firmware accepts the CRAM image
  only if CACHE_LOADED equals the image size and XLINK LOST[31:16] is 0. 0 = no file (first boot).
- **BAR** (EN = 1): the RTL overlays white (RGB 0xFFFFFF) on the last 4 active lines of every frame of the core's
  video output, from the first active pixel for PX pixels (PX >= W lights the whole line). W = the number of active
  pixels in the last complete active line (0 before the first line). The firmware computes PX = bytes done x W /
  bytes total per chunk. EN = 0: no overlay, the picture is the core's.
- **From 0.3.0 (the bitstreams that load the firmware from a file, section 22):** XLINK 0x4C is FAFRIUM, a read-only
  word that only the boot stub reads (bit 0 = 1 unless the firmware file's last load was exactly 256 KB). It reads 0
  once the firmware has started, so for the firmware it is still a reserved word that reads 0, as in the table above.
  BAR = EN | PX 2047 (0x8000_07FF) is the stub's refusal screen: the core then draws every active dot plain red. The
  firmware's own bar never sets PX to 2047.

### 3.10 Region 0x06: the synth (v1.3, FEAT.SYNTH)

The synth does the cart chip's per-block and per-sample audio work: the block schedule, the wave voices' envelope
and mix, the SFX channels' mix, the output stage and the DT playback. Written by our team: we reverse engineered the
STM32F4's commands as close as possible, with hardware verification. The firmware keeps everything per tick or per
command (the sequencer, note and program maths, the pan gains, the masters and fades, the SFX start, the Z80
packet) and reaches the synth only through this region. The logic belongs to
the synth's RTL; this section is what the MCU sees, frozen. With FEAT.SFXFIFO instead (test builds 4 and
4a) the region is the interim audio_sfx block, unchanged.

- **Address:** 0x0600_0000-0x0600_0FFF, `addr[11:2]` decoded, aliases above: globals 0x000-0x3FF, voice windows
  0x400-0x7FF (3.10.3), SFX windows 0x800-0x9FF (3.10.4), 0xA00-0xFFF reserved. Reserved words read 0, writes ignored.
- **Access:** word, halfword and byte loads and stores; a store writes only its byte lanes (a halfword store at +2 is
  bits 31:16); a load returns the whole word. Writes take effect in program order at the access's first bus cycle,
  nothing posted. Registered read data and ack (section 9); an access waits at most ~2 clocks behind the synth's own
  use of its state RAM: ~7-9 cycles at the fast-path costs (estimated).
- **Clock:** clk_sys only; no new clock domain and no new crossing.

#### 3.10.1 Global registers

| off | name | bits | reset | read | write |
|---|---|---|---|---|---|
| 0x000 | ID | [31:0] | constant | 0x5335_0001 ('S' '5', map revision 1) | ignored |
| 0x004 | CONFIG | [1:0] MODE (0 = before the first 88 configuration, 1 = DT, 2 = YM, 3 = as 0), [2] PAL, [3] DTWIN, [31:16] SEQ | 0 | {SEQ of the last write, 12'0, DTWIN, PAL, MODE} | every write applies 3.10.2 |
| 0x008 | FLAGS | [0] SEQON, [1] PLAYING, [2] SFXON, [3] BGMECHO, [4] SFXECHO, [5] LEVELNZ | 0 | value | value |
| 0x00C | WMASTER | [15:0] L, [31:16] R | 0 | value | value |
| 0x010 | WBOOST | [15:0] BOOST, [31:16] WAVEMASTER | 0 | value | value |
| 0x014 | SMASTER | [15:0] L, [31:16] R | 0 | value | value |
| 0x018 | SMCFG | [15:0] SFXMASTER | 0 | value | value |
| 0x01C | ECHOB | [15:0] GAIN (s16), [23:16] DELAY, [31:24] INDEX | 0 | value; INDEX as the synth advances it | value |
| 0x020 | ECHOS | as ECHOB | 0 | as ECHOB | value |
| 0x024 | ARM | [0] | - | 0 | 1 = frame_pending := 1 (the tick's write, YM) |
| 0x028 | SEQ | [15:0] ARR, [31:16] DONE | 0 | value (3.10.5) | ignored |
| 0x02C | DONE | [15:0] | 0 | {16'0, DONE} | DONE := [15:0] (synth_end, 3.10.5) |
| 0x030 | STATUS | [0] BUSY, [1] RUN, [2] FPEND, [3] FILL, [4] CUR, [8:5] QDEPTH, [27:16] BLKCNT | 0 | value | ignored |
| 0x034 | PHASE | [10:0] DTIDX, [22:16] STROBES, [31] RESTART | 0 | {0, STROBES, 5'0, DTIDX} | **TEST only:** DTIDX := [10:0]; [31] = 1 restarts TIM6 and TIM8 together (our comparison test with the cart-engine runner aligns the runner on this event) |
| 0x038 | YMFILT | [15:0] A, [31:16] B (s16) | 0 | value | value |
| 0x03C | DTOUT | [15:0] GAIN (Q8.8), [16] INVERT, [20:17] DCK | 0 (silent) | value | value |
| 0x040 | DIAG | [7:0] INCOMPLETE, [15:8] TIMEOUTS, [23:16] WBUSY, [31:24] UNDERRUN | 0 | saturating counts | any write clears all four |
| 0x044 | TIMEOUT | [23:0] clk_sys cycles | CLK_HZ / 200 (5 ms: 268,465 NTSC, section 7) | value | value |
| 0x048 | SEQLAT | [15:0] B, [31:16] A | 0 | the arrival number of the last 68000 write to `$1FEA` ([15:0]) and to `$1FEC` ([31:16]) | ignored |
| 0x04C | SCHED | [7:0] CNT, [11:8] NBLK, [31:16] HALF | 0 | value | ignored |
| 0x050-0x3FC | - | reserved | - | 0 | ignored |

- **DTOUT** (the stand-in, decision 5 "plain first"): per DT sample x = code - 2047; if DCK != 0, a one-pole DC blocker
  x := x - lp with lp += (x - lp) >> DCK (the cart's coupling capacitor; DCK from a capture); y = x x GAIN / 256,
  negated if INVERT; y goes into the core's audio sum where test build 4 has the album and the cart SFX pair.
  GAIN 0 is silence. A filter, if B Jam's ear asks for one, is a later v1.x in the reserved bits.
- **DIAG:** INCOMPLETE = DT halves the chip counts as incomplete, TIMEOUTS = instants serviced on TIMEOUT (3.10.5), WBUSY = MCU writes while RUN = 1, UNDERRUN = DT playback
  reads not served by their sample. TEST telemetry; RELEASE never needs them.
- **STATUS:** FPEND, FILL and CUR are the scheduler's frame-pending flag and its fill and current halves (3.10.2);
  BLKCNT = the blocks mixed, mod 4,096. **PHASE.DTIDX** is the DT DMA position.

#### 3.10.2 CONFIG: the scheduler half of the 88 configuration

A write applies, to the synth's scheduler, what the cart chip's 88 configuration writes for its mode, exactly (from our
study of the cart):

| MODE / PAL | HALF | NBLK | other words | DT rings |
|---|---|---|---|---|
| 1 DT (either PAL) | 960 | 6 | fill 1, cur 0, cnt 0xFF | both restart at index 0, dated at arrival SEQ |
| 2 YM, PAL 0 | 800 | 5 | one more word := 1, fill 1, cur 0, cnt 0xFF | stopped |
| 2 YM, PAL 1 | 960 | 6 | fill 1, cur 0, cnt 0xFF | stopped |
| 0 / 3 | 0 (TIM6 only counts, no block) | unchanged | - | stopped |

- **Every write applies it**, also with MODE and PAL unchanged: the chip re-runs the body for any changed
  configuration byte (finding 19). The firmware runs its own version of the chip's 88 configuration and writes CONFIG
  exactly when that body runs (the chip's "same byte as last time" exit stays in the firmware), with the masters, the
  frame rate, the C9 volume, the raw-pitch flag and the PSG cache it writes itself (WBOOST, SMCFG, firmware state).
- **SEQ ([31:16])** names the arrival the write belongs to (3.10.5). A DT restart is dated at that arrival's time: the
  synth keeps the sample time of at least the last 32 arrivals, so the DMA phase after an 88 is the chip's whatever the
  firmware's latency (an older SEQ restarts at the write, counted in DIAG.TIMEOUTS; the engine queue is shorter).
- **dac_buf is not cleared** (the chip's 40 ms of stale buffer after a DT start and the one stale YM packet after a YM
  start are kept, as the chip has them).
- **DTWIN ([3])**, not a bit of the 88 configuration byte: 0 = a DT curve index past the 16,384-entry table is
  clamped to the table ends (see docs/ALLOWLIST.md, row B41, pending a gameplay measurement); 1 = it reads
  CURVE_WIN (3.8) at 0x198000 + 2 x index, as the chip reads its own flash there. YM indexes are clamped by the
  chip itself, so DTWIN does not matter in YM.

#### 3.10.3 Voice windows: VOICE[v], v = 0..15 = the chip's voice 10 + v, at 0x0600_0400 + 0x40 v

Field offsets inside the window.

| off | name | type | written by |
|---|---|---|---|
| +0x00 | POS | u32 (24.8) | MCU (0 on a note-on or program change); the synth (each block) |
| +0x04 | LEN | u32 | MCU (0 for an empty directory entry) |
| +0x08 | LOOP | u32 (0xFFFF_FFFF = one-shot) | MCU |
| +0x0C | BASE | u32, [21:0] = a CRAM byte offset, [31:22] read 0 | MCU |
| +0x10 | STEP | u16 (8.8) | MCU |
| +0x12 | DECLICK | s16 | MCU (8 on a note-on); the synth (0 after the ramp) |
| +0x14 | GAIN_L | u16 | MCU |
| +0x16 | GAIN_R | u16 | MCU |
| +0x18 | LAST_L | s16 | the synth |
| +0x1A | LAST_R | s16 | the synth |
| +0x1C | ENV_LEVEL | s16 | the synth (envelope, stopped-mode decay); MCU (init) |
| +0x1E | ENV_CNT | u16 | the synth |
| +0x20 | ENV_STATE | u8 (the chip's u16, values 0-7) | MCU (1 note-on, 6 soft release, 7 hard off); the synth |
| +0x21 | BB | u8 | MCU |
| +0x22 | MUTE | u16 | MCU |
| +0x24 | AR | u8 (the chip's u16, from a program byte) | MCU |
| +0x25 | HOLD | u8 | MCU |
| +0x26 | DR | u8 | MCU |
| +0x27 | SL | u8 | MCU |
| +0x28 | SUS | u8 | MCU |
| +0x29 | D2R | u8 | MCU |
| +0x2A | RR | u8 | MCU |
| +0x2B | COMPAND | u8 | MCU: always 0 (0 of 256 directory entries set the flag, measured); the synth mixes linear |
| +0x2C-0x3F | - | reserved | - |

GAIN_L and GAIN_R are the two sides of the voice's pan gain; BB is the voice's boost flag. The u8 fields hold every
value their chip writers produce (finding 21). The firmware reads ENV_LEVEL (the Boom Box feed) only inside
synth_begin / synth_end (3.10.5).

#### 3.10.4 SFX windows: SFX[c], c = 0..7 = the chip's channel c, at 0x0600_0800 + 0x40 c

| off | name | type | written by |
|---|---|---|---|
| +0x00 | PTR | u32, [21:0] = an even CRAM byte offset (3.8 SFXBANK), [31:22] read 0 | MCU (start); the synth (advances) |
| +0x04 | BASE | u32, [21:0] as PTR | MCU |
| +0x08 | POS | u32 | MCU (0 at a start); the synth |
| +0x0C | LEN | u32 | MCU |
| +0x10 | FORMAT | u8 (the chip's u16) | MCU |
| +0x11 | RATE | u8 (the chip's u16) | MCU |
| +0x12 | ID | u16 | MCU (start); the synth (0 at the end of a one-shot) |
| +0x14 | GAIN_L | u16 | MCU |
| +0x16 | GAIN_R | u16 | MCU |
| +0x18 | LOOP | u8 | MCU |
| +0x19 | FILT | u8 (bits 2:0 used) | MCU |
| +0x1A | Y | s16 | MCU (start); the synth |
| +0x1C | DELAY | u16 | MCU (start); the synth (counts down while ID != 0) |
| +0x1E-0x3F | - | reserved | - |

FORMAT 1 = 8-bit samples, else 4-bit; ID 0 = a free channel; Y is the channel's filter state.
The chip's other channel fields (the start serial, level, pan, retrigger and fade counters) stay in firmware;
the chip's re-check of the start serial after a mix always passes with atomic blocks (see docs/ALLOWLIST.md, row B40). A RATE
outside 1-5 makes the chip decode nothing and mix its stale buffer; whether any record has one is not known (the
synth's SFX item counts the records; if one exists, the synth reproduces the stale-buffer behaviour). The firmware
reads POS, LEN and ID (the SFX channel pick) only inside synth_begin / synth_end.

#### 3.10.5 Order: arrivals, DONE, the hold-off, BUSY and CAUSE.BLK

The chip mixes a block at a TIM6 instant M with every mailbox that arrived before M already served (its mailbox
interrupt outranks the mixer); the cart-engine runner does the same in zero time. The synth reproduces that order
whatever the firmware's latency:
- **ARR** counts the 68000's writes to `$1FEA` and `$1FEC` (the same filtered pulses that set CAUSE.B and CAUSE.A),
  16 bits, wrapping. The write that makes ARR = n is **arrival n**; SEQLAT holds the numbers of the last B and the last
  A arrival, so L1 can tag what it serves and tell which came first.
- Every TIM6 instant is queued (at least 8 deep) with **NEED** = ARR at that instant. The head instant is serviced
  (its scheduler decision taken and, if it gives one, its block mixed) only when DONE - NEED (mod 2^16, as a signed
  16-bit number) >= 0, or once it has waited TIMEOUT (serviced anyway, DIAG.TIMEOUTS + 1).
- **The firmware's part.** synth_begin(n): wait until STATUS.BUSY = 0 (at most one block, ~0.67 ms worst, estimated);
  then every write of arrival n's body; synth_end(n): DONE := n. DONE moves in arrival order and only forward;
  DONE = n means arrivals 1..n are done, so an arrival L1 never saw on its own (two writes merged into one CAUSE level)
  is covered by the next one's DONE. A post with no audio effect gets its DONE as soon as nothing older is pending.
- **BUSY** = RUN or (QDEPTH > 0 and the head serviceable). Once the firmware has read BUSY = 0 while it works on
  arrival n, no block can start before DONE moves: every newer instant has NEED >= n > DONE. That is what lands the
  firmware's writes between the right two blocks.
- **CAUSE.BLK** (4.2) is set on every 1 -> 0 edge of BUSY. With CTRL.BLKIE = 1 it raises MEI, so the firmware can wait
  for the synth without spinning (acknowledge BLK, then read BUSY again: rules 6.3.2-3).
- Logic-owned fields (VOICE POS, DECLICK, LAST_*, ENV_*; SFX PTR, POS, ID, Y, DELAY; ECHO* INDEX; YMFILT; STATUS) are
  read, and every field written, only between synth_begin and synth_end. A write while RUN = 1 is applied at once and
  counted (DIAG.WBUSY); the running block may see either value (rule 6.3.8 forbids it).
- **The tick** builds the Z80 packet, reading DACBUF_L[6i] and [6i+3] from CRAM, before its synth_end, as the chip's
  TIM14 packet precedes its TIM6 mix. The FM / PSG meters of voices 0-9 stay in firmware and decay lazily: at each
  synth_begin it applies (BLKCNT - its last BLKCNT) blocks of the chip's per-block rule.

#### 3.10.6 Menu freeze, reset, and what the synth touches

- **Pocket menu** (CTRL.MENU_MUTE_EN = 1 and the menu open): TIM6 and TIM8 stop (the DT position, the TIM6 phase and
  the hold-off timeout with them), the DT output is 0, and all of it resumes where it stopped when the menu closes
  (see docs/ALLOWLIST.md, row B7; B Jam's decision of 2026-10-09). The firmware's L2b holds the song tick meanwhile
  (option bit 24).
- **Every reset** (`sys_reset`): every global register goes to its reset value above (CONFIG 0, so no block runs; the
  queue empty, ARR = DONE = 0). The VOICE and SFX windows (the state RAM) are **not** reset: the firmware writes every
  field before it first writes CONFIG MODE 1 / 2 or a FLAGS bit. The CRAM regions are kept (3.8); the firmware writes
  their power-on content at every boot (the curve, the SFX bank from the ROM, the rings, dac_buf: what
  the chip's dac_buf holds at power-on is still to be measured).
- **DT playback:** at each TIM8 strobe with MODE = 1 the synth reads DACBUF_L / R at DTIDX and sends them through
  DTOUT; MODE 0 / 2 output 0 (in YM the console's Z80 plays the packet).
- **Memory:** the synth writes only BGMRING, SFXRING and DACBUF_L / R, and reads BANK, SFXBANK, CURVE_WIN and those
  three (3.8). It never touches SDRAM (the VDP-DMA deadline) or SRAM.

---

## 4. FPGAIO v1.3 (0x0100_0000, slot = `addr[6:2]`)

0.2.6 decodes `addr[5:2]` (16 slots; checked in `mcu_core.sv` lines 42-46). v1.0 decodes `addr[6:2]` (32 slots) so
slots 16-31 can carry v1.x registers (the sound-cache registers were planned there) without a major bump. v1.1 takes
slot 16 (VSCNT, 4.8), v1.2 slots 17-22 (the sprite decoder, 4.9), v1.3 slot 14 (STAMP_A, 4.6) and slot 23 (FEAT,
4.10); the cache registers went to XLINK instead (finding 15). Every slot has registered read data and a
registered ack held until the request drops, like XLINK (section 9). A write takes effect once, in the first bus cycle.

| slot | address | name | bits | reset (every reset) | read | write | used by |
|---|---|---|---|---|---|---|---|
| 0 | 0x0100_0000 | CTRL | [7:0] R/W, [15:8] R | 0x09 (4.1) | `{16'0, CAUSE.B, LSTAT[6:0], ctrl[7:0]}` | byte 0 -> `ctrl[7:0]` (read-modify-write: bits 0, 4, 5 live here) | boot; legacy glue |
| 1 | 0x0100_0004 | (TIME_MS, retired) | - | - | 0xFFFF_FFFF | ignored | nothing (a tree check refuses references) |
| 2 | 0x0100_0008 | SPTR | [20:0] | 0 | live stream pointer (proposed) | byte offset into the workspace (even) | L1 |
| 3 | 0x0100_000C | VOL_SFX | [7:0] | 0xFF | 0xFFFF_FFFF | audio_sfx volume (interim) | interim, the synth fit removes it (v1.3: live only with FEAT.SFXFIFO; otherwise ignored) |
| 4 | 0x0100_0010 | VOL_BGM | - | - | 0xFFFF_FFFF | ignored: no RTL consumer (checked) | interim |
| 5 | 0x0100_0014 | DIAG | - | - | stream count in a diagnostic RTL variant only; 0xFFFF_FFFF in the release fit | ignored | diagnostic fits |
| 6 | 0x0100_0018 | IRQCLR (legacy) | [0] | - | 0xFFFF_FFFF | bit 0 = 1 acks CAUSE.B | 0.2.6 glue only |
| 7 | 0x0100_001C | STREAM_GO | [31], [20:0] | 0 | `{valid, 10'0, remaining[20:0]}` | N > 0: `remaining := N` words, `valid := 1`, guard cleared; 0: `valid := 0` (bits 31:21 of the write ignored) | L1; TEST (stream status, hardware test R10) |
| 8 | 0x0100_0020 | CAUSE | [3:0]; v1.3 [4:0] | 0 | `{V, S, A, B}` (4.2); v1.3 `{BLK, V, S, A, B}` | write 1 to clear (bits 0, 1, 2, 3; v1.3 also 4) | L1, boot |
| 9 | 0x0100_0024 | MSIP | [0] | 0 | MSIP | `MSIP := bit 0` | L1 sets, L2b clears |
| 10 | 0x0100_0028 | TIMER | [31:0] | 0 | cycle count at `CLK_FREQ` | ignored | all levels |
| 11 | 0x0100_002C | TCMP | [31:0] | 0 | value | value | L2a; wheel inserts (MIE off) |
| 12 | 0x0100_0030 | TCTRL | [0] TEN | 0 | TEN | `TEN := bit 0` | L2a; wheel |
| 13 | 0x0100_0034 | STAMP_B | [31:0] | 0 | TIMER when CAUSE.B was last set | ignored | L1, TEST (hardware test R9, MEI latency per post) |
| 14 | 0x0100_0038 | STAMP_A (v1.3) | [31:0] | 0 | TIMER when CAUSE.A was last set (4.6) | ignored | L1 (the urgent song-tick deadline, FW_S5), TEST |
| 15 | 0x0100_003C | WLOCK | [20:0] = KB 27..47 | 0 | mask | write 1 to set; sticky until reset | boot |
| 16 | 0x0100_0040 | VSCNT (v1.1) | [15:0] | 0 | `{16'0, count}`: VDP vertical syncs since the reset, wrapping (4.8) | ignored | TEST freeze telemetry |
| 17 | 0x0100_0044 | DEC_BASE (v1.2) | [20:0] | 0 | value (bit 0 reads 0) | the next START's output base, a workspace byte offset | L1, before each START (4.9) |
| 18 | 0x0100_0048 | DEC_STAT (v1.2) | [21:0] | 0 | [4:0] depth, [9:5] entries left, [10] RUN, [11] DONE, [16] OVF, [17] BADTYPE, [18] D0, [19] PRE, [20] LATE, [21] ABORT | 1 clears bits 16-21 | TEST (4.9) |
| 19 | 0x0100_004C | DEC_WORDS (v1.2) | [20:0] | 0 | words written since the last START | ignored | TEST |
| 20 | 0x0100_0050 | DEC_TIME (v1.2) | [31], [23:0] | 0 | {valid, clk_sys cycles from the last START to its GO} | ignored | TEST |
| 21 | 0x0100_0054 | DEC_MARGIN (v1.2) | [31:0] | 0x7FFF_FFFF | the smallest (first window read after a START) - (its GO), signed | any write: 0x7FFF_FFFF | TEST |
| 22 | 0x0100_0058 | DEC_LATECNT (v1.2) | [15:0] | 0 | window words read during a run at or past the decoded end, saturating | any write clears | TEST |
| 23 | 0x0100_005C | FEAT (v1.3) | [31:0] | constant | what this bitstream carries (4.10); never 0xFFFF_FFFF | ignored | crt0 (section 1), TEST |
| 24-31 | 0x0100_0060-7C | reserved v1.x | - | - | 0xFFFF_FFFF | ignored | - |

Slots 2 and 7 are decoded by the stream engine in `paprium_cart.sv` (where slot 2 lives today); their read-back is
routed to the FPGAIO read mux.

### 4.1 CTRL (slot 0)

| bit | name | R/W | at configuration | on every reset (v1.0) | 0.2.6 | effect in v1.0 |
|---|---|---|---|---|---|---|
| 0 | HOLD (`md_rst`) | R/W | 1 | **1 (BOOT-01)** | not reset | 1 = 68000 held (`paprium_md_reset` -> a `synch_3` into clk_md -> `md_reset_effective`, docs/STAGE1_PLAN.md item S1). With the MegaWire code (test build S3b on): the A858 screen also holds the console with it while the cart's MegaWire code loads pages A / B ($1FE4 bit 14 cleared) and releases it when the chip sets the bit again (`core/mw/mw_screen.c`; docs/BOOT_SPEC.md section 8: on the cart the bit holds the 68000, here the whole console restarts from reset on page A) |
| 1 | (exit) | R/W | 0 | 0 | kept | none (not connected) |
| 2 | (sdram_en) | R/W | 0 | 0 | opened the `$C000` window | **none**: the window follows `$1FE8`/`$1FEE` (docs/CART_FPGA_SPEC.md section 5) |
| 3 | RSTSEEN | R/W | 0 | 1 | set on reset | a flag only; the firmware may clear it |
| 4 | MENU_MUTE_EN | R/W | 0 | 0 | kept (no effect) | 1 = while the Pocket menu is open, the album pauses in place and the cart SFX pair is forced to 0 (docs/STAGE1_PLAN.md item F1). The new-core firmware sets it at boot (a decision of the project plan). v1.3 with FEAT.SYNTH: the synth's TIM6 / TIM8 freeze and its DT output is 0 instead (3.10.6) |
| 5 | OPT_AT_RESET_EN | R/W | 0 | 0 | kept (no effect) | **Built dormant (B Jam's decision of 2026-10-11, docs/STAGE1_PLAN.md question Q4):** 1 = Console / Mega CD option changes pass to the console only during a reset (the second fix proposed in our study of the reset issues seen on the 0.2.6 hardware); 0 = 0.2.6's live options. The new-core firmware leaves it 0; if it is never switched on, the release fit removes it |
| 6 | BLKIE (v1.3) | R/W | 0 | 0 | kept (no effect) | 1 = CAUSE.BLK takes part in `mext_irq_i` (4.2); 0 = BLK still latches but raises nothing. Meaningful with FEAT.SYNTH only |
| 7 | - | R/W | 0 | 0 | kept | none |
| 14:8 | LSTAT | R | - | - | same | `{sbrq, sres, busy, late, AI off, restart, send}` from XLINK |
| 15 | CAUSE.B | R | - | - | `mbx_irq` | mirror of CAUSE bit 0 |

Reset is taken from `md_srst` (= the cart's `reset` = sys_reset, registered once, as today's `md_srst_st`). Because
bits 4 and 5 reset to 0, an "options at reset" latch driven by bit 5 is transparent while the reset runs, so the next
boot always takes the options set before it.

### 4.2 CAUSE (slot 8): the MEI sources

| bit | name | set by (level latch) | cleared by | 0.2.6 |
|---|---|---|---|---|
| 0 | B: mailbox B | any 68000 write to `$1FEA` (either lane), through `ramdp_io`'s filtered write pulse, `cpu.addr[12:1] == 0xFF5` | W1C bit 0 (or slot 6 bit 0) | `mbx_irq` in `paprium_cart.sv` (moves here) |
| 1 | A: mailbox A | any 68000 write to `$1FEC`, same pulse, `cpu.addr[12:1] == 0xFF6` | W1C bit 1 | none (new; the same synchroniser as bit 0) |
| 2 | S: CPU MATE (buddy) SEND | a change of `posts_s[0]` (XLINK's synchronised post count, bit 0): one event per post | W1C bit 2 | polled `ctrl[8]` (LSTAT send pending) |
| 3 | V: console reset (EXTI 13) | a 68000-only console reset: on the Pocket core_top's Console Reset (one pulse per accepted press; the RTL holds the 68000 in reset while V is pending); on MiSTer its board | W1C bit 3 | none |
| 4 | BLK: synth block done (v1.3) | every 1 -> 0 edge of the synth's STATUS.BUSY (3.10.5): the queued blocks are done and none is serviceable; never set without FEAT.SYNTH | W1C bit 4 | none |
| 7:5 | reserved (v1.x) | - | - | - |

- `mext_irq_i = B | A | S | V | (BLK & CTRL.BLKIE)`, a level held until acked. (v1.0-v1.2: `B | A | S | V`.)
- A set and a clear of the same bit in one clock: **the set wins** (0.2.6 rule).
- All latches reset to 0 on every reset.
- S uses the post count, not the sticky "send pending" flag, so a post is never lost to the clear-flag round trip
  through clk_md. The firmware still clears LSTAT flags with LCLR as today; restart and AI-off stay polled by L3 (as
  0.2.6's main loop polls them).
- The chip's lines are edge interrupts with a pending bit; ours are level latches with an ack. Both merge two events
  before service into one (docs/CART_FPGA_SPEC.md section 11).

### 4.3 The timer (slots 10-12): replaces MTIME and the ms counter

- TIMER: a 32-bit up-counter at the MCU clock (`CLK_FREQ`), +1 every clock, wrapping (80.0 s NTSC). Reset to 0 on
  every reset (proposed), so boot timing is repeatable.
- TCMP: 32-bit compare. TCTRL bit 0 = TEN.
- `mtime_irq_i <= TEN & ~(TIMER - TCMP)[31]` (registered): a level while the counter has reached or passed the
  compare, within half the wrap (40.0 s NTSC). A compare written in the past fires at once, so a deadline is never
  lost. The level falls within 2 clocks of a TCMP or TCTRL write.
- Ack = write a later TCMP or clear TEN. The firmware keeps at most a few deadlines in a wheel (L2a in the firmware's
  interrupt design) and programs the earliest.
- The firmware's time base: µs to cycles with the build-time clock value (section 7). Millisecond users (the 0.2.6 VU,
  MD+ shim, glue calibration) read TIMER through a board function.
- ALM (estimated): the counter, compare, subtractor and flop ~40-60, against MTIME 106.4 and the ms counter (most of
  fpgio's 42.0) removed: the platform's -48..-88 for this swap.

### 4.4 MSIP (slot 9)

`msw_irq_i = MSIP`. L1 sets it when it queues deadline work (brain call, song tick); L2b clears it when nothing is left.
Reset 0. Cost +1..+3 ALM (estimated in the firmware's interrupt design).

### 4.5 Stream pointer and GO (slots 2, 7; decision F-D1)

- SPTR: the window's start, a 21-bit byte offset into the 2 MB workspace (today's `stream_ptr`, `paprium_cart.sv`
  lines 127-142). It advances by 2 per delivered word. v1.0 adds a read-back of the live pointer (proposed).
- GO: `remaining` is **21 bits** (proposed; up to the whole 2 MB workspace in words). docs/CART_FPGA_SPEC.md proposed
  16 bits and measured at least 13 (DB06 reaches 0x1000 words); DA and AF lengths are not measured (hardware test
  R10), so v1.0 takes the safe width (+5 flops).
- Order rule: the firmware writes SPTR, then GO. `valid` falls on GO = 0, on a `$1FF2` write of 0 or with bit 15
  set, when `remaining` reaches 0, when `window_en` falls, and on reset (docs/CART_FPGA_SPEC.md section 7).

### 4.6 Stamps (slot 13; slot 14 STAMP_A from v1.3)

STAMP_B holds TIMER at the clock CAUSE.B was set. It gives the hardware 84-deadline test (docs/CART_FPGA_SPEC.md test R9
and docs/BOOT_SPEC.md test T-B11: the firmware reads TIMER at its own `$1FEE` write and subtracts STAMP_B) and the MEI
latency per post for the TEST counters. Cost +18..+23 ALM (estimated). It replaces the cart-RTL draft's `0x0B000020`
post timestamp.

STAMP_A (TIMER at CAUSE.A) would make the synth step's urgent song-tick deadline exact (`TCMP = STAMP_A + offset`).
The first new-core firmware has no song tick, and the synth step needs a new fit anyway, so slot 14 is reserved and
STAMP_A is added there as a later v1.x if the synth step's co-simulation shows L1 latency matters (saves ~18-22 ALM
now).

**v1.3: STAMP_A is in slot 14.** The FW_S5 firmware design needs it (`brd_now()` at the tick's L1 entry is late by any
L1 work queued ahead, AD up to ~0.7 ms at the fast-path speed), so it is no longer optional. STAMP_A holds TIMER at the
clock CAUSE.A was last set, exactly as STAMP_B does for CAUSE.B (same set pulse, same clock); a later `$1FEC` write
overwrites it. Reset 0 on every reset. The tick's urgent finish is armed from it: `TCMP = STAMP_A + 1.8 ms` (section 7
row). Every v1.3 bitstream carries it, test build 4a's included (cost +18..+22 ALM, estimated as for
STAMP_B).

### 4.7 WLOCK (slot 15), proposed

Bits 0-20 lock WRAM KB 27-47 (section 3.2). Write 1 to set; no way to clear except a reset. Reset 0. The firmware sets
it after crt0 has cleared `.bss` and the boot overlay has run, and never over the stack. Cost +10..+18 ALM
(estimated). Accepted over a constant 48-bit map: each build picks its WRAM-ROM extent without a refit.

### 4.8 VSCNT (slot 16, v1.1): the VS counter

Added 2026-10-13 (B Jam's decision of 2026-10-13: build the optional VS counter) so the TEST freeze telemetry can tell a
dead VDP from a dead 68000: both stop the 9494 post, only a dead VDP (or its clock) stops the vertical sync.

- **Read:** `{16'0, count[15:0]}`, the number of VDP vertical syncs (frames) since the last reset, wrapping at 65,536
  (18.2 min NTSC). Never 0xFFFF_FFFF, so a read tells a v1.1 bitstream from a v1.0 one, whose slot 16 is reserved.
  Writes are ignored.
- **Reset:** 0 at configuration and on every reset (`md_srst`, like TIMER). A sync that starts during the reset is
  not counted after it.
- **What counts:** every start of the VDP's VS pulse (md_board `vdp_vsync2`, active low) as clk_md samples it, one per
  frame. Pulses closer than 6 clk_md (~56 ns) are not guaranteed separately (the VDP's are 16.7 ms apart).
- **Path (checked in the RTL):** core_top `paprium_vs_tap` samples VS on clk_md and flips a one-bit level `vs_tog` at
  each start; it crosses into clk_sys through a `synch_3` (the only new crossing of v1.1, section 9), and fpgio counts
  every change. Latency from the VS edge to the count: 74-93 ns (measured in our VS bench, any clock phase; the read
  adds its own 2 clk_sys).
- **Firmware:** `brd_vs_count()` (board interface v1.1). The TEST debug save extends it to 32 bits and keeps, beside
  the MCU heartbeat and the 9494 count, the count and the board time it last moved. **Since 2026-10-17:** the C6
  hold reads it in TEST and RELEASE alike (core/dispatch/jobs.c; see docs/ALLOWLIST.md, row B34): the C6 job keeps
  `$1FE6` bit 14 for the game's 80 VBlank polls, counted as VS starts (a VS start comes 37,572 MCLK = 10.99 lines
  after the VBlank start, measured on Nuked-MD, NTSC 224 lines). It is a job's length, not a reply: no post waits on
  it.
- Cost +10..+20 ALM (estimated, docs/STAGE1_PLAN.md section 5.1); 0 M10K.

### 4.9 The sprite decoder (v1.2, slots 17-22; proposed): the cart FPGA's 0x80 decoder and load-list queue

Added 2026-10-15 (B Jam's decision of 2026-10-15, "preservation": the chip replies to AF at once and its FPGA decodes
the frame's sprite blocks itself, so the game never waits). The full behaviour (the chip's writes, the queue, the
decoder, the timing contract, the RTL integration) is in our sprite-decoder design notes, which are not published;
this section is what the MCU sees.

- **Register file (3.4), the chip's offsets:** `$1FF4` (+0x14) latches the next entry's high half (bits 6:0 = address
  bits 22:16; the 0x200 flag the chip always sets is ignored). `$1FF6` (+0x16) odd = CLEAR (queue emptied, a run in
  progress aborted), even = PUSH `{HI[6:0], v[15:1], 0}` (a 23-bit even ROM byte address: the type byte 0x80 of a
  stream). `$1FF2` (+0x12) 0x8000 = START: with entries queued, any run is aborted, SPTR := DEC_BASE, and the entries
  are decoded last-pushed first into the workspace from DEC_BASE, contiguous; then GO(words decoded - words the window
  delivered since START) as a slot-7 write would; with no entry, no decoder effect. 0 or bits 15:14 = 11 = STOP (a run
  aborted). The earlier stream rules of `$1FF2` (stream invalid, guard cleared) stay. MCU reads of +0x10..+0x16 stay 0.
- **Slot 17 DEC_BASE:** the firmware writes it before each START with entries (the scratch base for AF / B1 / F2, the
  DA's destination for DA06 / DA07), the board-only write the chip-runner test's log tags as `S1_LOG_DECB`.
- **Slots 18-22:** read-backs for the TEST debug save and the long-play test report; RELEASE never reads them. No
  interrupt (the chip has none for its FPGA's decoder).
- **Reset:** every reset clears the queue, the run, HI, DEC_BASE and the slots (DEC_MARGIN to 0x7FFF_FFFF).
- **Firmware:** `brd_dec_base()` (board interface v1.2); the flush, F2 and DA direct handlers write the chip's queue
  sequence and finish at once.
- Cost ~350-450 ALM + 1 M10K (estimated).

### 4.10 FEAT (slot 23, v1.3): what this bitstream carries

A read-only constant (RTL parameters), so one firmware rule can tell test build 4a's bitstream from the
synth fit, and a MiSTer board without a cache slot from the Pocket (finding 14, section 1 rule 2). A v1.0-v1.2 bitstream
reads 0xFFFF_FFFF here (a reserved slot); FEAT itself is never 0xFFFF_FFFF.

| bit | name | 1 means | test build 4a | synth fit (test build 5) |
|---|---|---|---|---|
| 0 | CACHE | the APF sound-cache slot (21.1) with XLINK CACHE / CACHE_LOADED (3.9) | 1 | 1 |
| 1 | BAR | the first-boot bar, XLINK BAR (3.9) | 1 | 1 |
| 2 | SYNTH | region 0x06 is the synth (3.10); CAUSE.BLK and CTRL.BLKIE live; the 3.8 synth regions in use | 0 | 1 |
| 3 | SFXFIFO | region 0x06 is the interim audio_sfx FIFO block and FPGAIO slot 3 VOL_SFX is live | 1 | 0 |
| 4 | MDP | region 0x07 is the interim MD+ block / EverDrive stub | as built (the album's control path; the cache-slot RTL item decides) | 0 |
| 5 | ALBUM | the interim album path (APF slot 300, its CRAM ring at die word 0x200000) | 0 (removed: it shares CRAM port A) | 0 |
| 6 | GS3 | the virtual Grand Stick III is built (informational: nothing MCU-visible, 21.4) | 0 | 1 |
| 15:7 | - | reserved, 0 | 0 | 0 |
| 23:16 | IROM | the IROM size in KB (72 or 88, 3.1) | 72 | 88 |
| 31:24 | - | reserved, 0 | 0 | 0 |

SYNTH and SFXFIFO are never both 1. Cost ~1-3 ALM (a constant on the read mux).

---

## 5. The option word (GPIO input, 0xFFFF_FF80)

| bit | 0.2.6 (checked in `paprium_cart.sv` line 211) | v1.0 | source (`core_top.sv`) | read by |
|---|---|---|---|---|
| 6 | `$1FE4` bit 6 | same | `mcu_opts[0]` (`opt_mcu_sync`) | boot |
| 10:8 | `$1FE4` bits 8-10 | same | `mcu_opts[3:1]` | boot |
| 18:16 | MegaWire option, 3 copies (7 = On) | same | `mcu_opts[4]` | boot (status bits 0-2), in the builds without the MegaWire port only. The 0.3.0 firmware (the builds with the port, FW_MW) never reads these bits, and the 0.3.0 Pocket menu has no MegaWire row (B Jam's decision of 2026-11-01) |
| **24** | 0 | **MENU: Pocket menu open** (F-D1) | `inmenu_sys_s` (`settings_sync`, already on clk_sys, `core_top.sv` 743-754) | L2a (watchdog gate); the first new-core firmware's music mute is RTL (CTRL.MENU_MUTE_EN); in the FW_S5 firmware L2b pauses the song tick |
| **25** | 0 | **JAP: Console region is Japan** (bit number proposed; decision F-D1 decided "a bit") | `opt_jap`, added to `opt_mcu_sync` (width 5 -> 6) | none since 2026-10-17 (docs/BOOT_SPEC.md BOOT-07, the header letters by region, dropped 2026-10-16: the letters are the cart's) |
| **26** | 0 | **PAL build** (proposed): constant from the `PAL` parameter, 0 in every Pocket v1.0 build | parameter | boot (frame-based figures; later the sprite composer's 50 Hz frame skip) |
| other | 0 | 0, reserved | - | - |

- The option bits are live (no latch: B Jam's decision of 2026-10-09). The game reads them once at boot.
- MENU is 1 at the boot after a Soft Reset chosen from the open menu (the 68000 stays paused until it closes;
  docs/BOOT_SPEC.md section 6). The watchdog is not armed then anyway (docs/BOOT_SPEC.md BOOT-16).
- Cost +1..+3 ALM (one more synchroniser bit; the menu bit is already synchronised).

---

## 6. Interrupt model (the firmware's interrupt design on these registers)

### 6.1 Lines and levels

| level | NEORV32 line, priority | source | what runs | `mie` open while it runs | registers it uses |
|---|---|---|---|---|---|
| **L1** | MEI, 1 (top) | CAUSE: B, A, S (V on MiSTer) | read the post, gate, reply, set status bits, queue jobs; sprite replies; on 9494: the chip head and (first new-core firmware) the empty tick inline; on S: brain pending; raise MSIP | none (MIE = 0 throughout) | CAUSE, register file (+A, +C read; +4/+6 via the status layer; +8/+12/+14/+16/+E writes), SPTR, GO, MSIP, TIMER, STAMP_B, TCMP/TCTRL (wheel insert), XLINK LCLR |
| **L2a** | MTI, 2 | `TEN & TIMER >= TCMP` | the wheel: urgent song-tick promotion (finishes the tick + Z80 packet), the chip's watchdog/heartbeat (gated by MENU); with the MegaWire code (FW_MW): it only counts MegaWire's TIM7-rate task due (`mw_due`), the thread runs it once per counted tick (L3; a late one late, not dropped) | MEIE | TIMER, TCMP, TCTRL, GPIO[24], register file +4 (bit 11), +E/+4 (fatal) |
| **L2b** | MSI, 3 | MSIP | brain call first, then the song tick in slices, then packet + `$1880` copy + Boom Box feed + held posts (FW_S5; the first new-core firmware runs the interim music path) | MEIE, MTIE | MSIP, TIMER (slice budget), register file +C (finish), GPIO[24] (mute), RAMDP |
| **L3** | thread | - | the chip's 16-slot job queue: unpacks, C6, saves, zoom; with the MegaWire code (FW_MW): first the SRAM image's check (after the release), then MegaWire's TIM7-rate task below the CPU MATE brain call, one of the chip's own steps a thread step, none starting while the game's sprite frame is open (AE taken, AF not yet; for up to 33.4 ms after the thread first sees it open, CLK_MW_SPRITE_MAX) or a post waits in mailbox B (checked with MIE off, the step entered with MIE off; a step running when AE comes ends, the next waits for the AF or the 33.4 ms; a frame open longer, as the game keeps some, no longer holds the task), and the A858 screen's steps; idle polls LSTAT (restart, AI off) | all | register file via the status layer (MIE-off section), SDRAM, BRAM, SRAM (cold pack), XLINK |
| boot | - (MIE = 0) | - | hold, checks, init, enable, release | none until the end | CTRL, SYSINFO, GPIO, CAUSE, XLINK LCLR, WLOCK, XCFG bit 16, register file (app init) |

FIRQ0-3: none used. WDT and UART are gone; GPIO's pin-change FIRQ1 exists and stays disabled.

**v1.3 (the FW_S5 firmware; B Jam's decision of 2026-10-15: the brain never slows the game).** The lines and priorities
are unchanged; what runs on them changes in the FW_S5 firmware: L1 also reads SEQLAT (and, at the 9494, STAMP_A), does
each post's 68000-visible part and finishes at once, and appends the music body, tagged with its arrival number, to an
ordered engine queue; L2b drains that queue in arrival order, each item inside synth_begin / synth_end (3.10.5), and
runs the CPU MATE brain call only below every engine item; L2a's urgent rule finishes a late tick 1.8 ms after its 9494
(from STAMP_A). CAUSE.BLK (MEI, with CTRL.BLKIE) is the synth's "done" event if L2b chooses to wait on it.

### 6.2 Latency figures

- Measured (with our RV32 cycle bench): trap entry 14 cycles, `mret` 13; a full round trip saving 16 caller-saved
  registers ~380-400 (estimated from those).
- L1 waits only for another L1 handler and short MIE-off sections: longest AF <= 17.3k cycles = 0.32 ms (estimated in
  the firmware's interrupt design). That is the figure docs/CART_FPGA_SPEC.md uses for the busy guard and the 84
  deadline. **Measured in the system co-simulation of the first new-core firmware (the firmware running on a
  simulation of the RTL; 2026-10-12, images with the 0.2.6 bodies in L1):** L1 entries up to 8.5 ms, all of them AD
  bodies (the co-simulation credits an entry to its first post, so its "D1 3.5 ms" and "B6 3.1 ms" were AD bodies; D1
  alone 213 us); post-to-acknowledge up to 101 us in play. A later change (2026-10-13) moved the sprite
  decodes out of L1: AD at most 1.16 / 1.30 ms RELEASE / TEST, every other body <= 0.24 ms at the hardware CPI (RV32
  model, fuzz case FZ12). The busy guard is RTL and covers any length; the game posts 84 on mailbox B after the
  previous post's finish, so the 84 budget holds (docs/STAGE1_PLAN.md risk 5).
- FPGAIO and register-file accesses cost one cycle more than 0.2.6's constant-ack slots (measured: 10 instead of 9;
  fast path: 7).
- The MCU fast path (measured, section 20): an MSI taken at a 2-nop MIE window 22 -> 13 cycles to the handler's first
  instruction, raised by an MSIP store during an ALU stream 28 -> 17, during WRAM loads 33 -> 20, during flash loads
  44 -> 30, during a div 64 -> 56; the same instruction boundary (mepc) in every case. An ecall round trip with a
  3-instruction handler 38 -> 26.

### 6.3 Rules every handler obeys (frozen with v1.0)

1. **Acknowledge before enable (boot).** With the 68000 held (CTRL.HOLD = 1): write CAUSE = 0xF (W1C), write XLINK
   LCLR for the send/late flags, clear MSIP, TEN = 0; then set `mie` = MEIE | MTIE | MSIE (it was 0, so `irq_buf` is
   empty); then `mstatus.MIE` = 1; **releasing the 68000 is the last step** (BOOT-02, BOOT-03). Every CAUSE source is a
   68000 action, so no real post can arrive before the release.
2. **Acknowledge before release (runtime).** A handler W1C-acks a cause bit before the write that lets the same source
   post again. Mailbox B: ack B before the finish write `$1FEA = 0` (otherwise a post that follows the finish at once
   is lost). CPU MATE (buddy): ack S before the brain's answer is published.
3. **Flush after ack.** After acking a level (W1C, a later TCMP or TEN = 0, MSIP = 0), clear and set that line's `mie`
   bit before `mret` or before re-opening it. 1.4.8.1's `irq_buf` caught the level again right after entry (finding 5).
   L2a and L2b mask their own bit while they run, so re-setting it at exit is the flush.
4. **Tolerate an empty cause.** An MEI entry with CAUSE = 0 returns at once (a race the rules above make rare, not
   impossible).
5. **Wheel edits are atomic.** TCMP/TCTRL writes and the wheel's state change together inside an MIE-off section (L1
   already runs with MIE = 0).
6. **Nothing on a reply path runs from SRAM, SDRAM or CRAM.** `mtvec` and every handler entry are in IROM or the
   WRAM code window.
7. **No WFI** in v1.0 (`mcycle` stops in sleep, and the TEST per-level counters use it).
8. **(v1.3) The synth is written in arrival order, between its blocks.** Every region 0x06 write and every read of a
   logic-owned field happens between synth_begin (STATUS.BUSY = 0 seen) and synth_end (DONE := that arrival); DONE
   only moves forward, one arrival or more at a time, in arrival order; the CRAM bytes of the cache image are never
   written while XLINK CACHE.VALID = 1 (3.9, 3.10.5).

---

## 7. Clock-following figures (B Jam's decision of 2026-10-10)

**One value.** The RTL's only clock number is today's `` `CLK_FREQ `` in `paprium_defs.sv` (53,693,175). The first
new-core fit (docs/STAGE1_PLAN.md item M6) makes it one `core_top` parameter, `CLK_HZ = PAL ? 53_203_424 : 53_693_175`
(and `CLK_MD_HZ = 2 * CLK_HZ`), passed down; `` `CLK_FREQ `` is derived from it or retired, and a `clkcheck` lint
refuses any other clock literal. v1.0 feeds the NEORV32 generic from it (finding 9). The firmware gets the same number
at build time (`fwbuild.json` per layout, e.g. `"clk_hz": 53693175`), `tests/check_board.py` compares it with the RTL
value when the RTL path is given, and crt0 checks `SYSINFO_CLK == BOARD_CLK_HZ` at boot (mismatch: hold the 68000, stop;
TEST: a milestone code). No NTSC literal in code. A PAL build changes one parameter and its firmware's `clk_hz`.

**Rule.** What the chip times by its own clock, ours times in microseconds and converts with `BOARD_CLK_HZ`. What the
chip times by the console frame, ours counts in frames (9494 posts).

| figure | basis | µs | cycles NTSC (53.693175 MHz) | cycles PAL (53.203424 MHz) | label |
|---|---|---|---|---|---|
| 1 ms (board ms, buddy `BUDDY_MS_CYCLES`) | clock | 1,000 | 53,693.175 | 53,203.424 | estimated; replaces the literal 53693 in `buddy.h:132` |
| 84's `delay(9,600 SysTick)` | clock | 100 | 5,369 | 5,320 | the chip's delay at 96 MHz (checked); estimated |
| TIM7 period: heartbeat, watchdog, MegaWire task | clock | 102,103.75 | 5,482,275 | 5,432,269 | inferred: PSC 979, ARR 5000 at a 48 MHz timer clock (our map of the chip) |
| watchdog trip, > 40 TIM7 ticks | clock | ~4,084,000 | - | - | the count checked, the clock inferred |
| urgent song-tick promotion after the 9494 | time target | 737.5 | 39,600 | 39,239 | estimated (in the firmware's interrupt design) |
| Z80 reads `$1800` after VBlank | console time | 3,000-3,400 | 161k-183k | 159.5k-181.3k | measured range, estimated conversion |
| TIMER wrap / compare horizon | - | 79.99 s / 40.0 s | 2^32 / 2^31 | 80.73 s / 40.36 s | estimated |
| 0.2.6 busy spin (132,056 cycles), `PPM_BUSY_PULSE_LOOPS` | - | - | retired | - | busy is RTL now (docs/CART_FPGA_SPEC.md section 7) |
| album 48 kHz divider (`paprium_cdda_play`) | clock | - | 1118 (47,983 Hz) | 1108 (47,974 Hz) | checked; becomes `` `CLK_FREQ/48000 `` |
| SFX `dac_clocker` 48 kHz | clock | - | from `` `CLK_FREQ `` already | same | checked |
| 9494 tick, YM-DAC 5 blocks a frame (6 PAL), D602 every 4th frame, the sprite composer's 50 Hz (PAL) frame skip | frame | - | follow the frame | follow the frame | the project plan's rule |
| v1.3: the synth's TIM8 (48 kHz sample strobe) | clock | 20.83 | 1,118.6 (the `dac_clocker` fraction) | 1,108.4 | checked, as the SFX `dac_clocker` row; decision 4: the console clock |
| v1.3: the synth's TIM6 (479.52 Hz = 100.1 TIM8 periods, the chip's ratio) | clock | 2,085.4 | 111,972.6 | 110,951.3 | the chip's ratio, read in the code only (APB timers); estimated conversion |
| v1.3: the synth's hold-off TIMEOUT reset value (CLK_HZ / 200) | clock | 5,000 | 268,465 | 266,017 | estimated (integer division in RTL) |
| v1.3: urgent song-tick finish after the 9494, `TCMP = STAMP_A + figure` (FW_S5) | time target | 1,800 | 96,648 | 95,766 | estimated (the Z80 reads ~3.0 ms after the 9494) |

Proof: tests/check_clock.py (test T23) runs the firmware at both clock values; every time figure must match in µs, every
frame figure must follow the frame.

---

## 8. Reset behaviour

Today one reset envelope covers power-on, the core's Soft Reset and any other APF reset: `sys_reset` on clk_sys resets
the NEORV32 and the cart block (checked in our 0.2.6 reset notes). v1.0 keeps that and adds the rows marked "proposed".

| item | at bitstream load | every reset (sys_reset) | firmware restart (MCU self-reset, unreachable in play) | label |
|---|---|---|---|---|
| NEORV32 (PC 0, CSRs, `mie` = 0, `mcycle` = 0) | reset | reset | crt0 re-run | checked |
| IROM | bitstream | unchanged | unchanged | checked |
| WRAM contents (code window, WRAM-ROM, overlay leftovers) | bitstream images | **not reset**; crt0 copies `.data`, clears `.bss` only | same | checked |
| constant lock (KB 11-26, 48-63) | on | on | on | proposed |
| WLOCK | 0 | 0 | kept | proposed |
| CTRL | 0x01 | **0x09** (HOLD = 1, RSTSEEN = 1; MENU_MUTE_EN, OPT_AT_RESET_EN = 0) | firmware writes HOLD = 1 first | frozen (0.2.6: not reset) |
| 68000 hold during a Soft Reset, before `sys_reset` reaches clk_sys | - | `shell_reset` (clk_md, the reset's first clock) also drives `md_reset_effective`, so the 68000 is held from the first clock; HOLD takes over when `shell_reset` falls (docs/STAGE1_PLAN.md item S1). With the Pocket menu closed, one bus cycle the 68000 was already starting may still start: at most one, within 0.25 us of the request, never a write (docs/BOOT_SPEC.md test T-B7; B Jam's decision of 2026-10-13; measured worst 148 ns) | - | frozen; 0.2.6 left a 0.65-0.92 ms window (a finding of the project plan) |
| CAUSE, MSIP, TCMP, TCTRL, STAMP_B, GO (`valid`, `remaining`) | 0 | 0 | firmware acks and clears | frozen |
| VSCNT (v1.1) | 0 | 0 | keeps counting | frozen (v1.1) |
| decoder queue, run, HI, DEC_BASE, DEC_STAT / WORDS / TIME / LATECNT (v1.2) | 0 | 0 (DEC_MARGIN 0x7FFF_FFFF) | kept | proposed v1.2 |
| STAMP_A, CAUSE.BLK, CTRL.BLKIE (v1.3) | 0 | 0 | firmware acks and clears | frozen v1.3 |
| FEAT (v1.3) | constant | constant | constant | frozen v1.3 |
| XLINK CACHE, CACHE_LOADED (v1.3) | 0 | **kept** (power-on only: the Pocket reads the cache back while the MCU reboots) | kept | frozen v1.3 |
| XLINK BAR (v1.3) | 0 | 0 (`od_reset`) | firmware clears EN | frozen v1.3 |
| synth global registers (v1.3, 3.10.1) | reset values | reset values (CONFIG 0: no block; queue empty; ARR = DONE = 0; TIMEOUT = CLK_HZ / 200) | kept | frozen v1.3 |
| synth VOICE / SFX windows (v1.3, the state RAM) | undefined | **not reset**: the firmware writes every field before CONFIG MODE 1 / 2 or a FLAGS bit | kept | frozen v1.3 |
| CRAM v1.3 regions (cache image, rings, dac_buf, curve, SFX bank) | undefined (or the last core's) | not reset (power-on controller) | kept | frozen v1.3 |
| TIMER | 0 | 0 | keeps counting | proposed |
| SPTR (`stream_ptr`) | 0 | 0 | kept | checked |
| register file, `window_en`, `mini_view`, `stream_valid`, guard | 0 | 0 (docs/CART_FPGA_SPEC.md section 3.5, docs/BOOT_SPEC.md BOOT-08..13) | kept, like the cart's MCU-only reset (inferred) | proposed |
| RAMDP (incl. the hidden `$1FE0-$1FFF` cells) | undefined | not reset; the boot recopies `$0000-$1FDF` | kept | checked |
| battery save (BRAM) | APF slot load | not reset | kept | checked |
| VOL_SFX | 0xFF | 0xFF | kept | checked |
| XLINK XCFG (incl. the SRAM lock), xram / CRAM controllers, CRAM init | power-on only | **kept** | kept | checked |
| XLINK option-D registers, LSTAT flags (`restart` = 1), post count | power-on | reset (`od_reset` / `shell_reset`) | kept | checked |
| SRAM, CRAM, SDRAM contents | APF / undefined | not reset | kept | checked |
| SDRAM controller, port-2 `ack2` | init | not reset. **v1.0: `paprium_mcu_mem` resets `mem_req` to `mem_ack`** (not to 0), so no stray port-2 access is launched by a reset. **Erratum (as built, 2026-10-11, which the review of the reset items agreed):** the reset leaves the request alone (`mem_req`, the write enables, address and data), so an access the MCU had already requested finishes as requested inside the reset (<= ~64 clk_sys; every reset lasts >= 0.6 ms) and `req2 == ack2` when the MCU starts; the `mem_req <= mem_ack` form was benched and can still launch one stray read when an access completes on the clock the reset starts (the project plan's rule: every handshake the boot depends on is resynchronised) | - | checked in `paprium_mcu_mem.sv` lines 40-47 and `sdram.sv` lines 131-210. Today's mismatch costs one stray **read** (the write enables reset to 0), finished within tens of clk_ram ticks, far inside the ~0.6-0.9 ms `shell_reset` envelope (3 steps of 2^15 clk_md, checked in `core_top.sv` lines 796-820), so it was not a hazard on this core; the change is the rule, plus an assertion in the reset sim |
| GPIO option word | live | live | live | checked |

**MCU self-reset (docs/BOOT_SPEC.md, row AL-03).** The chip's WE SUX backdoor, the watchdog reset path (81 bit 4) and
the update end reset the MCU only; the cart keeps its FPGA state. v1.0 has no RTL self-reset: the firmware restart sets
HOLD, masks interrupts and jumps to the reset vector, and the RTL state stays (cart-like). The allow-list row for it
(docs/ALLOWLIST.md, row B17; docs/BOOT_SPEC.md, row AL-03) said "maps to our full cart reset"; the firmware design reads
that as "hold the 68000 and restart the firmware", which leaves the RTL state as the cart leaves its FPGA state. That
row now says so (proposed at the allow-list review of 2026-10-13). All three paths are unreachable in play.

---

## 9. Timing notes (what is registered, what to watch)

- **No new clock domain, no new SDRAM port.** Every v1.0 register is on clk_sys. The only new crossing is mailbox A,
  which reuses `$1FEA`'s filtered pulse (from the firmware's interrupt design). S uses `posts_s`, already registered
  from clk_md in XLINK (related clocks, timed by static timing analysis).
- **Registered read data + ack** for FPGAIO and the register file (the XLINK pattern). They then enter the
  `mcu_dati` / `rv_di` mux as registered sources, as the platform rule asks. Recommended: one block serves both regions
  0x01 and 0x0B as a single mux input (proposed).
- **WRAM write path** (0.2.6's worst clk_sys path: +0.746 ns at fitter seed 4 of an earlier 0.2.x fix build, -0.105
  ns at seed 6 of the final 0.2.6 build): decode and lock leave the half-cycle path (3.2). Watch it in all 6 seeds.
- **WRAM read path:** half-cycle (negative-edge RAM to the posedge capture); depth mux 3:1 instead of 2:1, one LUT
  either way. Watch.
- **The MCU fast path:** both WRAM half-cycle paths and the Wishbone round trip for the IROM / WRAM are gone.
  New full-cycle paths: the processor-bus address (the CPU's PC / data address through the bus switch) into the IROM /
  WRAM M10K and, through the lock map, into the WRAM's byte write enables; the M10K read data (gated, ORed) into the
  CPU. The fit check's timing queries (`queries.tcl`) name these instead of the WRAM half-cycle rows; the RAMDP arm
  reads a registered ack now.
- **IROM:** the extension mux shrinks from 11:1 to 5:1 + 2:1 with registered selects: easier.
- **RAMDP byte view:** one choice per bit on the RAMDP read path (3.3). Watch; fallback is a firmware swap.
- **Flash byte view:** at the registered capture of `mem_dout`, on the MCU port-2 crossing that the existing SDC
  exceptions cover. Check the exception still matches the new cells.
- **`mtime_irq_i`** is registered after the 32-bit subtractor; `mext_irq_i` is an OR of flops.
- **VSCNT (v1.1): one new crossing, one bit.** `paprium_vs_tap`'s `vs_tog` (clk_md, a level that flips once a frame)
  into the first stage of its `synch_3` on clk_sys: a false path into that stage only (SDC block VS, through `xf_col`,
  so an empty match is a critical warning); the later stages and the 16-bit counter are timed on clk_sys. No multi-bit
  value crosses.
- **CTRL.HOLD:** `ctrl[0]` drove a marginal clk_sys -> clk_md crossing (a finding of the project plan; fitter seed 5
  failed hold on it). v1.0 passes it through a `synch_3` into clk_md with a false path on the first stage (from the
  platform design), which
  removes that path; the 68000 release then moves by ~3 clk_md (~28 ns) once per boot. Nothing in the boot is timed
  against the MCU at that scale (the first post is ~2.8 s later), so the "no change in when the MCU sees the game"
  rule is not touched.
- **Register-file and byte-view arms:** keep the read data registered, and serve regions 0x01 and 0x0B from one
  registered block, so `mcu_dati -> rv_di` gains at most one registered input (clk_sys headroom ~+0.7 ns).
- **v1.3: no new clock domain, no new crossing.** STAMP_A's capture is a copy of STAMP_B's; CAUSE.BLK is one more
  flop in the `mext_irq_i` OR (BUSY's edge, registered in the synth). Region 0x06's read data is registered like
  FPGAIO's and enters `mcu_dati` as one more registered source. XLINK's cache / bar words sit in the xmem block on
  clk_sys (`xmem_reset` / `od_reset`); the datatable size word and the flush read path cross to clk_74a inside the APF
  bridge logic, as the save slot's do today (board side, the cache-slot RTL item). The 88 KB IROM adds one depth-mux
  level to `tcm_irom_out` (+0.3..+0.8 ns, estimated, on today's +6.2 ns). All new synth logic is on clk_sys, inside
  its +2.5..+3.8 ns; the synth fit's timing check adds query rows for the synth's CRAM read, its DSP path, the dac_buf
  port and the 7-slice IROM.

---

## 10. What MiSTer's board layer must provide

MiSTer shares the cart NEORV32 (~1,376 ALM there) but has no Pocket SRAM, CRAM or APF, and may run with or without the
brain (checked in our study). To run the same chip-exact core firmware, their board must give:

1. An RV32IM core with Zicsr and the same interrupt model: three level lines with MEI > MTI > MSI, and either
   1.4.8.1's `irq_buf` behaviour or one that is safe under rule 6.3.3. Every MMIO access acked well under 127 cycles.
2. SYSINFO `USER_CODE` = 0x5049_01xx and `CLOCK_FREQUENCY` = their MCU clock, with the firmware built for the same
   value. The MCU clock must not be below 53.69 MHz (the CPU budget assumes it).
3. FPGAIO v1.0 at their chosen base with the same slot meanings: CTRL.HOLD (68000 hold), CTRL.MENU_MUTE_EN (their
   OSD's mute, or no effect), SPTR, STREAM_GO, CAUSE (B, A; S only with a brain; V on a 68000-only console reset, which
   MiSTer has), MSIP, TIMER/TCMP/TCTRL, STAMP_B.
4. The cart register file with CART_FPGA_SPEC's 68000-side rules (composer, busy, window, view switch, FM XOR) and the
   MCU side of 3.4, at their chosen base.
5. RAMDP 8 KB with the halfword view and the byte view; the flash word view and byte view of the 8 MB ROM; an SDRAM
   (or other) workspace of at least 2 MB the stream engine reads; an 8 KB save RAM.
6. The option word bits: model (6, 8-10), MegaWire (16-18), region (25), PAL (26), and MENU (24) = their OSD-open
   signal if their OSD pauses the 68000, else 0.
7. On-chip code memory for the resident firmware (IROM, 41 KB of firmware room around the brain hole, or without it)
   and WRAM data in the same layout (the brain data and code window only if they keep the brain).
8. A home for the MegaWire code and its 13.9 KB of RAM that can run in place (their SDRAM or DDR is an option only
   if fetch never sits on a reply path), with the same image header.
9. Their own linker script and boot (no SRAM loader, no cache slot) through the board layer; the chip-exact core has no
   board addresses (`tests/check_tree.py`).
10. The tests: the allow-list, the replay hashes and the comparison harness at each step (the project plan's MiSTer
    rule).

**v1.3 additions for a MiSTer board.**
11. USER_CODE 0x5049_0103 and **FEAT** (4.10) with their own bits: CACHE = 0 and BAR = 0 (no APF slot: the bank is
    unpacked at every boot, or their own cache), SYNTH = 1 if they build our synth, IROM = their code memory in KB.
12. **STAMP_A** (FPGAIO slot 14) beside STAMP_B, and **CAUSE.BLK / CTRL.BLKIE** if SYNTH = 1.
13. With SYNTH = 1: region 0x06 as 3.10 at their chosen base, and a 4 MB memory the synth reads with the 3.8 map (the
    bank, the SFX bank, the curve window, the rings, dac_buf), written by their MCU at boot; their audio clock follows
    the console clock (decision 4) or their own stand-in, and their OSD freeze maps to CTRL.MENU_MUTE_EN. PAL runs here
    for real (see docs/ALLOWLIST.md, row B36): `CONFIG.PAL` = 1 gives the chip's 960 / 6 YM schedule.
14. Without the synth (their own audio): SYNTH = 0, SFXFIFO = 0; the FW_S5 firmware's synth calls then go through
    their board layer (the core reaches the board only through `board/board.h`, `tests/check_tree.py`).

---

## 11. Work items for the platform RTL

The work items, their estimates, proofs and order are in `docs/STAGE1_PLAN.md` (track M for this page, track C for the
cart side of the register file). The first draft numbered its items P1-P14; they map to docs/STAGE1_PLAN.md's items as
follows:

| draft | STAGE1_PLAN | what |
|---|---|---|
| P1, P11 (RTL part) | M1 | NEORV32 generics: clock from the clock parameter, `USER_CODE`, MTIME / UART / WDT off, IRQ inputs |
| P2, P4, P10 (FPGAIO part) | M2 | FPGAIO v1.0 (slots, CAUSE, MSIP, timer, STAMP_B, WLOCK, CTRL bits 4-5, resets), mailbox-A latch, SEND tap |
| P3 | M3 | WRAM 48 KB with the registered write-select and the lock map |
| P5 | M4 | IROM 72 KB, 2048-deep slices, fixed select and index |
| P9 | M5 | option word bits 24-26 |
| P11 (clock), the platform design's clock item | M6 | clock-following RTL dividers and the `clkcheck` lint |
| P12 | M7 | SRAM image route (no RTL change) |
| P6 | C1 | register-file MCU port (merged with the cart-RTL register file) |
| P7, P8 | C6 | RAMDP and flash byte views |
| P10 (hold) | S1 | 68000 hold on every reset (with `shell_reset` and the HOLD synchroniser) |
| P13 | X2 | benches and the rvboard v1.0 model |
| P14 | M8 | `pocket_map.h` v1.0 and `tests/check_board.py` |

**Sum for this page's items (estimated, against the final 0.2.6, without counting docs/STAGE1_PLAN.md's items twice):**
M1-M5 about **-141..-14 ALM** (MTIME / UART / WDT out -140..-161; FPGAIO v1.0 with one stamp and WLOCK +64..+133;
WRAM +10..+25; mailbox A +3..+8; IROM -43..-58; option word +1..+3) and **+34 M10K** (WRAM +16, IROM +18: 253 -> 287
before vram_alt's +2). The register port (C1) and the byte views (C6) are counted in track C.

## 12. Tests that prove the interface

| # | layer | check | pass |
|---|---|---|---|
| I1 | Icarus unit benches | every FPGAIO slot, the register-file port, WRAM lock and depth, IROM 18,432 words, both byte views | 0 mismatches against the tables in sections 3-5 |
| I2 | our GHDL cycle bench on the first new-core RTL | fetch 4, load 10, store 12 (IROM, WRAM, window); FPGAIO / register file ~10; trap entry 14, `mret` 13 | equal to 0.2.6 except the +1 on registered slots |
| I3 | GHDL interrupt fuzz | random post / SEND / timer phases against the rules of 6.3 | no lost event; no double entry with rule 6.3.3; nesting MEI > MTI > MSI |
| I4 | the RV32 board model (rvboard) v1.0 | the firmware test rig's MMIO model replays I1's sequences | model = RTL |
| I5 | brain | the CART-TIMED test suite on the new-core image; brain bytes in IROM | bit-exact words; bytes = `brain.bin` |
| I6 | clock (T23) | firmware at 53.693175 and 53.203424 MHz | time figures equal in µs; frame figures follow the frame |
| I7 | hardware (B Jam) | menu 10 s (T2); blank-save 84 deadline from STAMP_B (docs/CART_FPGA_SPEC.md test R9 / docs/BOOT_SPEC.md test T-B11: 0.1-0.5 ms, fail > 1.0 ms); boot milestones; per-level max cycles from TIMER / `mcycle` | pass per item; numbers measured |
| I8 | fit, every seed | the WRAM write and read paths, the RAMDP read path, `ctrl[0]`, `mkmif` identity | the fit check's timing gate and `sta_xcheck`; no regression on those paths |
| I9 | VS bench (v1.1) | VSCNT against the VS edges driven, any clock phase; reset value; wrap; planted bugs | every edge counted once, in order, within the latency window; 0 after every reset; mutants caught |
| I10 | cache-slot RTL simulation for test build 4a (v1.3) | APF bridge writes of a known file into 0x6000_0000+, then MCU reads through 0x0900_0000; the flush reads back through the bridge; CACHE one-shot and its datatable word; CACHE_LOADED; a reset mid-flush | file byte i = MCU byte i = flushed byte i (finding 17); CACHE and CACHE_LOADED survive `sys_reset`, clear only at power-on; datatable = VALID ? SIZE : 0; LOST[31:16] = 0 |
| I11 | bar simulation for test build 4a (v1.3) | BAR EN / PX against the video output, both H modes, W read-back | lit pixels = min(PX, W) on the last 4 active lines only; EN = 0 leaves every pixel unchanged |
| I12 | FPGAIO v1.3 bench | STAMP_A against CAUSE.A sets (as I1 does STAMP_B), FEAT constant, CAUSE.BLK set / W1C / BLKIE gating, slots 24-31 | as the tables in 4, 4.1, 4.2, 4.10 |
| I13 | the synth's register bench (v1.3) | every 3.10 register and window field through the real MCU port: reset values, byte lanes, read-back, reserved words | 0 mismatches against 3.10 |
| I14 | the synth's scheduler bench and its comparison with the chip (v1.3) | the TIM6 / DMA-index / block sequence against the runner's TIM6 log after a PHASE restart; random DONE delays 0-5 ms; CONFIG dated by SEQ | the same block -> instant -> dac_buf address sequence; delays change no block |
| I15 | firmware board model (v1.3) | `tests/equiv/rtlmodel.py` grows region 0x06, XLINK 0x40-0x48 and FEAT from this page (not from the RTL); the firmware test rigs run on it | model = I12-I14 on the same sequences |
| I16 | doc and header (every commit) | `tests/check_board.py`: this page's Appendix A against its own v1.3 tables (FPGAIO, CTRL, CAUSE, XLINK, synth registers and windows, CRAM map, FEAT), and the header's version subset against `pocket_map.h` | ALL PASS, its v1.3 planted mistakes caught |

---

## 13. Decisions and open items

**Resolved at the freeze (by the review, from the specs, the project plan and the five designs):**
- Decoder queue and FIFO-A target: firmware board accessor; the RTL stores only `$1FE4/6/A/C` (section 3.4).
- STREAM_GO: 21 bits (the whole 2 MB workspace in words; DA / AF lengths are not measured, so the safe width).
- Stamps: STAMP_B in slot 13 now; STAMP_A reserved (slot 14) for the synth step.
- WRAM lock: sticky WLOCK for KB 27-47.
- IROM: one 40 KB extension in 2048-deep slices; image files unchanged.
- The ms counter (slot 1) is retired; the firmware uses TIMER (`mdp.c` gets an `FW_S1` guard so its timeout still
  fires).
- GPIO stays (F-D1); the option word is GPIO input bits 6, 8-10, 16-18, 24-26.
- Board-control enables MENU_MUTE_EN and OPT_AT_RESET_EN: CTRL bits 4 and 5.
- Port-2 handshake: `mem_req <= mem_ack` on reset (the project plan's rule). As built: the reset leaves the request
  alone (section 8 erratum).
- HOLD crossing: `synch_3` into clk_md.

**B Jam's decisions of 2026-10-11 (docs/STAGE1_PLAN.md section 11), folded in at the freeze:**
- Q1 battery RAM: **8 KB** (sections 3, 3.6).
- Q4 the "options at reset" latch behind CTRL bit 5: **built dormant** (section 4.1).

**B Jam's decision of 2026-10-13 (v1.1):** build the optional VS counter into the first new-core fit: FPGAIO slot 16
VSCNT (section 4.8), read by the TEST freeze telemetry.

**Proposed 2026-10-15 (v1.2), needs B Jam's yes:** the sprite decoder in RTL (section 4.9) on his decision of the same
day; slots 17-22 (the planned sound-cache registers keep 23-31).

**Open (not decisions).**
- O1 CPI after the WRAM write-path change: estimated unchanged; GHDL must measure it.
- O2 SRAM fetch cost and correctness: measured by the SRAM fetch bench (3.7; needs the gateway fix); MegaWire's 10 Hz
  task level: the thread (L3), since test build S3b.
- O3 RAMDP byte-view and register-file read-path timing: not known until a fit; the byte-view fallback is a
  firmware swap.
- O5 TIM7 clock (48 MHz) is inferred; the watchdog period is that figure until the chip's clock tree is known.
- O7 Whether another APF reset reloads data slots (the SRAM image) is not known (docs/BOOT_SPEC.md section 6).
- O8 MiSTer: their clock, their OSD-pause equivalent for MENU, and whether they keep the brain.

**v1.3 (2026-10-21), resolved at the freeze (from our design notes and studies for the synth step and B Jam's
decisions of 2026-10-21):**
- STAMP_A in FPGAIO slot 14 (no longer optional: the FW_S5 firmware design needs it).
- The "block done" event as CAUSE bit 4 BLK with its own enable, CTRL bit 6 BLKIE (the firmware decides whether it
  waits on it or spins on STATUS.BUSY).
- The cache slot's registers in XLINK 0x40-0x44 (power-on domain), the bar at XLINK 0x48 (finding 15), and
  CACHE_LOADED added (finding 16).
- The synth map (3.10): the synth study's register list with exact fields, plus SCHED, the DTOUT layout (decision 5),
  CONFIG.SEQ (the dated DT restart) and CONFIG.DTWIN (decision 3c either way, finding 20); the window fields at the
  chip's types, byte-valued ones as bytes (finding 21).
- The CRAM die-0 map (3.8), keeping the chip's audio SDRAM layout (finding 18); the cache image is HDR + BANK only.
- FEAT, and the interim retirement rule instead of a major bump (finding 14; alternative below).
- IROM 88 KB on the synth fit (decision 2), same select and index.

**v1.3 open (none changes a frozen row):**
- O9 USER_CODE major 2 on the synth bitstreams instead of FEAT alone (finding 14): closes the v1.0-v1.2-image gap at
  no RTL cost; v1.3 as frozen keeps the version at 1.3.
- O10 (the gameplay measurement) the DT curve range in gameplay decides docs/ALLOWLIST.md row B41 (clamp) or DTWIN = 1
  with the window placed in CURVE_WIN; the stale boost term (an open item of the
  synth study); dac_buf at power-on; the module store (SDRAM census, else MODSTORE).
- O11 (the synth's SFX item) any SFX record with a rate outside 1-5 (3.10.4).
- O12 (test build 4a, on hardware) whether the Pocket rewrites an unchanged 1.38 MB slot at every exit
  and how long it takes; whether 0x0184 is needed (not in v1.3).
- O13 (the cache-slot RTL item) whether test build 4a keeps the MD+ block (FEAT.MDP), and the bar's line
  count if 4 is too thin on the Pocket.

**Not in this page.** The 68000 side of the register file, busy, window, view switch, FM XOR and stream engine
(docs/CART_FPGA_SPEC.md, cart RTL); every console-side item of the first new-core fit (vram_alt, SDRAM yield, video
constraint, TeraDrive stub, HOF, Arcade Mode); the synth's logic (its RTL and design notes); the Grand Stick III RTL
and its menu (21.4, `paprium_gs3`, the RTL tree's `interact.json`); the cache file's format (test build 4b's boot
overlay, `board/pocket/boot/c4b.h`); the firmware's level code.

---

## 14. Reruns and sources

Reruns of the first draft (in our working folders; `python -I -B`):

| run | command | result |
|---|---|---|
| brain MMIO scan | `python -I -B tools/mmio_scan.py <brain dir>/brain.bin 0` (and `cf.bin`) | lui bases: RAMDP, flash word view, SRAM, WRAM; no x0-relative IO access. Counts and addresses only |
| IROM, 0.2.6 module | Icarus 12, our bench `tb_all.sv` + `mcu_irom_026.sv` (the 0.2.6 module, cut out unchanged), synthetic images | 10,240 of 18,432 words wrong |
| IROM, v1.0 draft | same bench + `mcu_irom_v1.sv` | 0 of 18,432 wrong |

The review's re-reads (the 0.2.6 release worktree, read only): `mcu_irom` index width at EXT_KB = 40; `mcu_wram` write
strobe and `paprium_wram`'s negative-edge lock; `paprium_mcu_mem` reset vs `sdram.sv` port-2 grant and the
`shell_reset` envelope in `core_top.sv`; `neorv32_cpu_control.vhd` `irq_buf`; `paprium_cdda_play.sv` divider;
`fpgio.sv` CTRL bits; `ramdp_io.sv` 68000 lanes. Results are in the findings above and in docs/STAGE1_PLAN.md section 3.

The brain finding (only RAMDP, the flash word view, SRAM and WRAM) has two independent measurements: the first draft's
static scan and the firmware design's objdump of the pocket72k RELEASE ELF (0 CSR instructions, 0 x0-relative IO
accesses).

Sources (md5, first 8): `mcu_core.sv` 0a71937f, `fpgio.sv` f3fcbcb2, `memory.sv` de0c8719, `ramdp_io.sv` 8fbdf7ab,
`paprium_mcu_mem.sv` 425bbff4, `paprium_cart.sv` cc32db18, `paprium_xlink.sv` a7131e66, `paprium_xram.sv` 951141f6,
`paprium_mcd_link.sv` ff32b756, `paprium_cdda_play.sv` 34a903ee, `paprium_defs.sv` 6518fa2d, `structs.sv` 72bf3d0a,
`core_top.sv` 7fe7cad5, `sdram.sv` a09cef25, `neorv32_cpu_control.vhd` 8f49b331, `neorv32_wishbone.vhd` f392233e,
`neorv32_top.vhd` e370107a; LAYOUT.md ce5fc79a; BUDGET.md 982a4e64; `pocket_map.h` 213a48c5; `zz_buddy.c` 297a7da9;
`mame.c` e264b0ca.

---

## 15. What the review changed from the first draft

- Section 3.4: only `$1FE4/6/A/C` are stored (the cart-RTL design); `+8`, `+E`, `+12` act on write and read 0;
  `+10/+14/+16` are dropped (the decoder queue and FIFO-A target are firmware). The draft stored all of them.
- Section 4: STAMP_A moved to a reserved slot (v1.1, for the synth step); CTRL bits 4 (MENU_MUTE_EN) and 5
  (OPT_AT_RESET_EN) added from the platform design; GO read-back spelled out as the TEST stream status (replaces the
  cart-RTL draft's `0x0B000020/24` words).
- Section 8: port-2 handshake resynchronised by RTL (`mem_req <= mem_ack`) instead of an assertion only; `shell_reset`
  holds the 68000 from a Soft Reset's first clock; the HOLD path gets a synchroniser (section 9).
- Findings: the IROM, WRAM, `irq_buf` and divider findings re-read in the RTL (they hold); the clock-literal list
  extended; the F-D3 conflict resolved (the cart's behaviour, restored in paprium-fw); the slot-map conflict between
  the drafts resolved (finding 13).
- Decisions: six of the draft's seven resolved at the freeze (section 13); battery RAM stays with B Jam.
- Section 11: the work items moved to docs/STAGE1_PLAN.md, with a map of the draft's P-numbers.

---

## 16. Freeze record (2026-10-11)

- The two open rows closed with B Jam's answers: Q1 = 8 KB battery RAM (map row 0x05 now `0x0500_0000-0x0500_1FFF`,
  section 3.6, section 10 item 5), Q4 = the latch built dormant (CTRL bit 5, section 4.1; Appendix A comment). No
  register, bit or address moved; the version stays v1.0.
- `board/pocket/include/pocket_map.h` carries Appendix A verbatim between two markers, plus the map, slot, bit, option
  and layout constants of sections 2-5; `tests/check_board.py` compares the header with this page (Appendix A define for
  define; the section 3 map, the section 4 slot table, 4.1 CTRL bits, 4.2 CAUSE bits, section 5 option bits, section 2
  interrupt codes, section 7 clock values) and, given an RTL tree (`--rtl`), with the RTL's USER_CODE, clock parameter
  and FPGAIO decode.
- `board/board.h` (board interface v1.0, `docs/BOARD_IFACE.md`) is what the core sees of this page.

---

## 17. v1.1 record (2026-10-13)

- Added: FPGAIO slot 16 VSCNT (section 4.8), its reset row (section 8), its crossing (section 9), test I9, and
  `POCKET_FIO_VSCNT` in Appendix A; USER_CODE 0x5049_0101 (section 1). Slot 14 (STAMP_A) stays reserved, now for a
  later v1.x; slots 17-31 stay reserved for the planned sound-cache registers.
- Unchanged: every other slot, bit, address, width and reset value of v1.0 (an unchanged copy of the v1.0 per-slot
  bench run on the v1.1 RTL differs from v1.0 only in slot 16, which reads 0 instead of 0xFFFF_FFFF).
- Firmware: `pocket_map.h` and `board.h` (board interface v1.1: `brd_vs_count`), `S1_A_IFACE_MINOR` = 1 (crt0 then
  refuses a v1.0 bitstream), the TEST debug save version 3 (the VS block), `tools/dbgsave.py`, the board model
  (`tests/equiv/rtlmodel.py`), `tests/check_board.py`.

---

## 18. Errata to the v1.0 text (documentation only, 2026-10-13)

No register, bit, slot, address or reset value changed; these rows now say what the first new-core RTL and firmware do.
- 3.6: the new-core TEST debug save is 0x1000-0x1FFF (was "0x900-0xFFF").
- 6.2: L1 lengths measured in the system co-simulation (the 0.32 ms figure was estimated).
- 8: the port-2 request is left alone by a reset (was `mem_req <= mem_ack`); the 68000 hold row says what
  docs/BOOT_SPEC.md test T-B7 allows with the menu closed.
- 8, 13: the rewording of docs/ALLOWLIST.md row B17 is proposed at the allow-list review.
- 3.1: the new-core images link the new-core brain (md5 b9a76592: the 0.2.6 brain with a cycle-counter fix in nine
  immediates; same size, same place; cf.bin and rodata.bin unchanged). paprium-fw pins it as fwbuild.json s1.brain.

---

## 19. v1.2 record (2026-10-15, proposed)

- Added: the register file's decoder actions on +0x12 / +0x14 / +0x16 (section 3.4), FPGAIO slots 17-22 (sections 4,
  4.9), their reset row (section 8), and `POCKET_FIO_DEC_*` in Appendix A; USER_CODE 0x5049_0102 (section 1).
- Unchanged: every v1.1 slot, bit, address, width and reset value; `$1FF2`'s earlier stream rules.
- Firmware: `pocket_map.h` and `board.h` (board interface v1.2: `brd_dec_base`), `S1_A_IFACE_MINOR` = 2 (crt0 then
  refuses a v1.1 bitstream), the TEST debug save version 4 (the decoder block), `tools/dbgsave.py`, the board model
  (`tests/equiv/rtlmodel.py`: the decoder with its timing), `tests/check_board.py`. The firmware decoder stand-in is
  gone (paprium-fw, when the RTL decoder came in).
- RTL: `paprium_hwdec.sv` and its hooks (in our decoder design notes), not in this tree.

---

## 20. The MCU fast path (test build 4, 2026-10-16; timing only)

B Jam's decision of 2026-10-16: this change is test build 4, after the RTL sprite decoder's (test build 3) and the
sprite-values firmware update, with its own fit and 60-minute soak (a long warm play-and-pause test). Design: our speed
study. Built on an RTL branch of its own; its proofs are below. In the tables of this page, "fast path" labels its
figures and "before" the earlier design's.

**What changed (checked in the RTL).** (a1) `mcu_tcm_irom` / `mcu_tcm_wram` in `mcu_core.sv` sit on the NEORV32's
processor bus (`neorv32_top.vhd`: `MEM_TCM_IMEM_SIZE` / `MEM_TCM_DMEM_SIZE`, the `tcm_*` ports; `paprium_neorv32.vhd`
sets both to the whole 16 MB regions); `mcu_wram` is gone; `paprium_wram` is four byte lanes on the rising edge.
(RAMDP) `ramdp_io` gives a registered ack held while the request lasts; the store still writes in the first bus clock
only. (a3) `paprium_mcu_mem` runs only the 16-bit halves of the access's byte lanes (`McuBus.sel`; a fetch = all
four). Two 1.4.8.1 facts found on the way, measured in the fast-path bench: during an instruction fetch the bus switch
shows the DATA port's last byte enables (the fetch port is read-only), and it drove the access source `p_bus_src_o` =
data in IDLE even when it granted a fetch there, so the Wishbone tag called such fetches data accesses.
`neorv32_busswitch.vhd` now drives the source from the selected port in every state (only the gateway's tag reads
it), and `mcu_core` takes a fetch's lanes from the tag.

**What did not change.** Every value the MCU reads or writes, the memory map and its aliases, the lock rule, WLOCK,
SYSINFO (FEATURES and sizes as before: `MEM_INT_*_USE` false), USER_CODE, the IRQ lines, priorities and the 1.4.8.1
`irq_buf` rule (6.3 rule 3 still applies), the reset sequence, the images' bytes (the WRAM's as four files).

**Cycle table (measured in RTL simulation: the tree's own paprium_cart, sdram.sv on clk_ram = 2 x clk, the GHDL
netlist of the tree's NEORV32; our cycle bench's programs adapted to the new-core WRAM lock; cycles per instruction or
unit).**

| class | before | fast path | | class | before | fast path |
|---|---|---|---|---|---|---|
| ALU reg / imm | 4 | 2 | | load / store RAMDP | 9 | 7 |
| shift (barrel) | 4 | 4 | | load FPGAIO / register file | 10 | 7 |
| branch not taken / taken | 4 / 8 | 3 / 6 | | unmapped (constant ack) | 9 | 6 |
| jal / jalr | 8 / 12 | 6 / 8 | | lw / sw SDRAM or flash window | 17.8 | 15.1 |
| call + ret | 16 | 12 | | lh / lb / sh / sb SDRAM or flash | 17.8 | 11.0 |
| load WRAM / IROM | 10 | 5 | | mul / div | 8 / 41 | 8 / 41 |
| store WRAM | 12 | 5 | | csrr mcycle | 4 | 3 |
| load + dependent ALU (WRAM) | 14 | 7 | | MSI entry (pending, MIE window) | 22 | 13 |

Real sequences: camera-pin test 122 -> 69, scroll tracker 124.5 -> 72.1, 16-slot census 924 -> 558, 16-word copy
680 -> 385, T1-row lookup 82.75 -> 49.4 cycles an iteration (x1.66-1.77). The 0.2.6 0x80 unpack loop on a synthetic
stream (4,101 bytes flash -> SDRAM window): 302,036 -> 185,058 cycles (x1.63; a1 alone 218,290), output checked.
SDRAM figures are means without port-1 traffic; the refresh moves single accesses by +3 as before.

**Proofs.** RAMDP: the cycle bench's 31 c00 read-backs right with the registered ack, 21 wrong with a constant ack on
the fast path (the power-up sentinel of another cell). Exactness: 34 programs (the cycle bench's suites, traps, unpack,
8 random-access programs over every deterministic region, aliases, lock window and byte views) give the earlier
design's stored values and external Wishbone transactions exactly; a full-system co-simulation boot and a replay of
its recorded bus traffic into the earlier MCU were also run (in our notes). `tests/check_board.py --rtl` checks the
fast-path items (the windows, the registered RAMDP ack, the lane images) on an RTL tree that has them.

**The replay is one-way (measured).** A recording made on the fast path replays exactly on the earlier MCU (every
transaction and interrupt entry), but a recording made on the earlier MCU replays on the fast path only up to the first
interrupt that a `mie` / `mstatus` write unmasks while it is pending (71 % of a 1,140-frame boot, then trap entry
#37,762): the fast path dispatches the next instruction at once, so its EXECUTE can come before `irq_buf` latches the
new `mie`, and the trap lands ONE instruction later (same interrupt, cause and handler; 6.3 rule 3). That can reorder an
MCU register access around a handler (there: the l2b_msi loop's MSIP clear before the timer handler's TIMER accesses
instead of after; both orders are race-free). Timing, not values; the firmware's wake-up hand-offs are checked with
"taken now or one instruction later" at every boundary (our interleaving models), which covers it.

---

## 21. v1.3: the cache slot, the bar, the synth contract, Grand Stick III, the record

Sources: our design notes for the synth step (every recommendation in them decided as recommended: B Jam's decision of
2026-10-21), our study notes on the synth, the firmware, the budget, the Grand Stick III and the boot cache, and the
RTL of test build 4 as of 2026-10-19 (read only).

### 21.1 The sound-cache slot: the board contract (test builds 4a and 4b; the cache-slot RTL item)

- **data.json** (the RTL tree's `pkg/pocket/Cores/Koala_Koa.Paprium/data.json`): the cache slot replaces the 0.2.6 music slot
  (id 300) as the third slot (index 2), so its size is datatable word 5: `{"name": "Sound cache", "id": 20, "required":
  false, "parameters": "0x02", "nonvolatile": true, "filename": "paprium_sound_cache.bin", "extensions": ["bin"],
  "address": "0x60000000", "size_maximum": "0x400000"}`. No `deferload` (the Pocket's own loading bar then counts it),
  no `size_exact`. Parameters 0x02 = core-specific: the file is
  `/Saves/paprium/Koala_Koa.Paprium/paprium_sound_cache.bin` (APF documentation); its name does not follow the ROM's.
- **Load** (setup, `sys_reset` held, the MCU not running): bridge 0x6000_0000 + i -> CRAM die-0 byte i (finding 17)
  through CRAM port A-write (the CDDA `data_loader` of test build 4 and the builds before it, reused with a 22-bit byte
  address, WRITE_MEM_CLOCK_DELAY 24); CACHE_LOADED counts it, XLINK LOST[31:16] counts any write lost.
- **Flush** (Quit, power-off, sleep: Reset Enter first, then the Pocket reads the nonvolatile slots): the bridge read
  mux serves 32'h6xxxxxxx from CRAM port A-read through a handshake on `a_rd_done` with a sequential prefetch (the
  stock `data_unloader` assumes a fixed latency; CRAM's varies). The MCU reboots meanwhile; CACHE keeps the size.
- **Datatable:** word 5 = CACHE.VALID ? CACHE.SIZE : 0, written all the time, alternating with the save's word 3. So a
  first session that ends before the image is complete writes no file (the Pocket creates one only for a non-zero
  size).
- **Firmware flow** (68000 held by CTRL.HOLD throughout, the watchdog gated off: locked decisions of the project plan):
  1. CACHE.VALID = 1: a warm reset or a flush in progress; touch nothing in the image.
  2. Else, if CACHE_LOADED = the image size, LOST[31:16] = 0 and the image checks (test build 4a: the
     probe pattern; test build 4b's boot overlay: header, version, ROM key, block and bank CRCs): CACHE := VALID | size.
  3. Else a first boot: test build 4a writes the pattern, test build 4b's boot overlay unpacks the bank with the bar
     (21.2), the header last; then CACHE := VALID | size.
- **Image size** 0x152100 (HDR + BANK, 3.8). Test build 4a's pattern has the same size, so B Jam's
  stopwatch test of that build times the real file.

### 21.2 The first-boot bar (test builds 4a and 4b)

XLINK BAR (3.9); the overlay itself is core_top video logic (the last 4 active lines, white, from the left). The
firmware lights it only during a first-boot unpack, while the 68000 is held and the picture is black, and writes
EN = 0 before it releases the 68000. Cost +10..+30 ALM (estimated).

### 21.3 The synth contract in one list (3.10 is the reference)

1. crt0: FEAT.SYNTH = 1 and FEAT IROM >= the layout, else stop (section 1).
2. Boot, before CONFIG / FLAGS: every VOICE and SFX field written; CRAM: the curve (always), the SFX bank, the rings and
   dac_buf at their power-on content; CURVE_WIN beyond the table only with DTWIN = 1.
3. Every mailbox arrival gets a DONE, in arrival order; each music body runs inside synth_begin / synth_end.
4. CONFIG exactly when the chip's 88 configuration runs, tagged with the 88's arrival; ARM at the tick.
5. The tick builds the Z80 packet (DACBUF_L[6i], [6i+3]) before its synth_end; the FM / PSG meters decay by BLKCNT.
6. Logic-owned fields are read only inside synth_begin / synth_end; nothing is written while RUN = 1.
7. The menu freeze is the RTL's (CTRL.MENU_MUTE_EN); L2b holds the song tick (option bit 24).

### 21.4 Grand Stick III (decision 6: B Jam's decision of 2026-10-21): nothing MCU-visible

The virtual stick (`paprium_gs3` inside `paprium_pads`, port 1) answers the game's own reader ($B1FC0 -> $B210C); the
game posts 810F itself and the chip ignores it, so the firmware does not change and nothing on this page does
(the RTL has its own item for it). For the interface review of the synth step, the Pocket menu as decided (the live
menu spec is the RTL tree's `interact.json` and its `docs/SCUM.md`, written with the Grand Stick III RTL; see
docs/ALLOWLIST.md, row B43):

| menu item | choices (decided 2026-10-21) | what the stick reports (the 6-bit switch byte the game reads at boot / reset) |
|---|---|---|
| Arcade Mode | Off / On / Multiplayer / **Stick Only** | Off: no stick on port 1 (the ports as before, as on test build 4). On: ARCADE MODE. Multiplayer: ARCADE MODE + 3 players, the stick's EXT socket = Dock controller 3, no 4-Way Play with the stick on (decision 6a). Stick Only: the stick with every switch off, like B Jam's own |
| Arcade Coins | 1 Coin 1 Credit / 2 Coins 1 Credit / **Inf. Credits (0012)** | TWO-COINS off / on; INF. CREDITS = the game's deliberate red 0012 stop (halts by design, as on his stick) |
| Attract Only | check | DEMO |
| NO HIT FX | not offered (nothing to see on a Pocket) | always off |

Select is the coin only while Arcade Mode is On or Multiplayer; the coin is taken on the ACK bit's 0 -> 1 edge (the
game's first coin is swallowed by its own gate); the stick's idle timer is held while the Pocket menu is open (a menu
pause mid-read would make a phantom credit). The Scum! Arcade / Arc3P words, the pad hook, the cave, the
coin stub and the press latches go (the Scum! table 122 -> 32 words); Little-Man, Stage Select and the flip point
stay. Wire values (ID, status A / B at rest, timeout) are not known until the cheap probes (decision 6c) are run, the
analyser only if they are inconclusive. How the Coins / Attract items combine with Stick Only is inferred by the Grand
Stick III RTL work.

### 21.5 Which bitstream carries what

| bitstream | USER_CODE | FEAT (4.10) | IROM | region 0x06 | XLINK 0x40-0x48 |
|---|---|---|---|---|---|
| test build 4, the fast-path build (0.3.0-s1c4, stage 1: the new core) | 0x5049_0102 | slot reads 0xFFFF_FFFF | 72 | audio_sfx FIFOs | aliases of XLINK 0x00-0x08 (XCFG, ID, SNOOP: `addr[5:0]` decode): a v1.3 image never runs there (USER_CODE) |
| test build 4a, the first sound-cache build (0.3.0-s5c4a), and test build 4b, the boot overlay (its firmware swap) | 0x5049_0103 | CACHE, BAR, SFXFIFO (+ MDP as built) | 72 | audio_sfx FIFOs | CACHE, CACHE_LOADED, BAR |
| the budget fit (numbers only, never staged) | 0x5049_0103 | SYNTH and whatever else that fit carries | 88 | the synth | as built |
| test build 5, the synth build (0.3.0-s5c5) | 0x5049_0103 | CACHE, BAR, SYNTH, GS3 | 88 | the synth | CACHE, CACHE_LOADED, BAR |

### 21.6 v1.3 record (2026-10-21)

- **Added:** FPGAIO slot 14 STAMP_A (4.6) and slot 23 FEAT (4.10), CTRL bit 6 BLKIE (4.1), CAUSE bit 4 BLK (4.2), XLINK
  0x40-0x48 CACHE / CACHE_LOADED / BAR and the `addr[6:2]` decode (3.9), region 0x06 the synth (3.10), the CRAM die-0
  map (3.8), the 88 KB IROM (3.1), the board contract (21.1-21.2), the section 7 rows, the section 8 rows, tests
  I10-I16, the MiSTer items 11-14 and `POCKET_*` v1.3 lines in Appendix A; USER_CODE 0x5049_0103 (section 1).
- **Unchanged:** every v1.2 slot, bit, address, width and reset value; the region decode and its aliases (XLINK's
  0x40-0x7F were unused aliases).
- **Retired as v1.0 announced** (FEAT says so): region 0x06's FIFOs, region 0x07 and FPGAIO slots 3-4 on the synth
  bitstreams; the album path from test build 4a on.
- **Allow-list rows added with it** (`docs/ALLOWLIST.md`, `tests/equiv/allowlist.json`): B39 (decision 3a, engine posts
  answered at once), B40 (3b, atomic synth blocks), B41 (3c, the DT curve clamp: pending the gameplay
  measurement), B42 (3d, the DT sample-and-hold at the I2S crossing), B43 (decision 6, Grand Stick III).
- **Firmware:** nothing built. `board/pocket/include/pocket_map.h` stays v1.2 (USER_CODE 0x5049_0102, what
  test build 4 and its images carry) until the first v1.3 image (test build 4a's) adopts Appendix A's
  v1.3 lines; `tests/check_board.py` checks those lines against this page's own tables from now on, and the header
  against its version's subset.

## 22. The firmware as a file (0.3.0, Analogue Pocket): what exists before the firmware starts

From 0.3.0 the firmware is not compiled into the bitstream. It is one file, Fafrium (released as Little-Man Firmware,
`little_man_firmware.bin` on the SD card); `docs/FAFRIUM.md` describes the file, its checks and its tools. The
bitstream's IROM image holds only a boot stub (`board/pocket/fafrium/fafrium_stub.S`, at most 2 KB at 0x0) and its
WRAM image is all zero. The stub checks the file, copies it into place and starts the firmware.

**For the firmware nothing in sections 1-21 changes.** When the firmware's `crt0` runs, IROM, WRAM, the Pocket SRAM
and the bus map are exactly as on a bitstream with the firmware built in, USER_CODE is still 0x5049_0103 (v1.3) and
FEAT is the bitstream's. What follows exists only while the stub runs, from power-on until the stub's GO; the RTL
behind it is `paprium_mcu_mem.sv`, `mcu_core.sv`, `cartridge.sv`, `paprium_xlink.sv` and `core_top.sv` of the
Pocket tree.

| what | while the stub runs (before GO) | once the firmware runs (from GO) |
|---|---|---|
| boot view, MCU 0x0380_0000-0x0387_FFFF | the Pocket SDRAM from byte 0x0100_0000: the firmware file in the first 256 KB (where the ROM loader puts the Fafrium data slot, bridge 0x1100_0000), the stub's scratch from 0x0384_0000 | closed: the addresses map as in 3.5 again |
| IROM, region 0x00 | takes 32-bit word stores (the stub copies the file's IROM section in); a byte store to 0x7FF is GO | read-only (3.1) |
| WRAM code window 0x2C00-0x6BFF | open for stores (the stub copies the file's WRAM section in) | locked, as always (3.2) |
| XLINK FAFRIUM, 0x0A00_004C (read only) | bit 0 = 1 unless the Fafrium slot's last load ended exactly at byte 256 KB (the core's length mark: 1 at power-on, no reset changes it); the stub refuses the file when it is 1 | reads 0 |
| XLINK BAR | the stub keeps BAR at EN \| PX 2047 when it refuses a file: the core draws every active dot plain red, the 68000 stays held | the firmware's own use (3.9); PX never 2047 |
| the cart's reset | masked: a Soft Reset or the Quit's Reset Enter does not stop the stub's copy (a new load of the file still restarts the stub) | as in section 8 |

- **GO and the restart.** GO is the stub's last store. From the next clock the core holds the cart in reset, closes
  the boot view, restarts the APF-load reset envelope once and then releases the MCU into the firmware's own `crt0`
  from a real reset. IROM read-only, the code window locked and the boot view closed are power-on flags: no reset
  undoes them, so a Soft Reset after GO reboots the firmware directly, at no extra cost.
- **A cut copy never runs.** The stub's finisher (run from the boot view's scratch) writes IROM [0, 0x800), the
  stub's own place, last. Its first store there sets a power-on flag; a reset of the MCU between that store and GO
  holds the MCU in reset until the bitstream is loaded again, so a half-written IROM never runs.
- **The MegaWire SRAM image.** The file's SRAM section is the build's SRAM image (3.7); the stub copies it into the
  Pocket SRAM. The APF loader then writes nothing into SRAM, so XLINK LOADED reads 0: the firmware's image check no
  longer reads LOADED or LOST (3.7) and keeps its header, link id and CRC-32 checks.
- **Checks and versions.** The stub compares the file's epoch, MCU interface (0x5049_0103), FEAT and clock words with
  its own values and refuses a file that does not match; the kind word (TEST or RELEASE, with or without the CPU MATE
  brain, and the firmware version) is information only, so one bitstream takes every kind. The epoch changes only
  with an RTL change the firmware can see, never for a firmware-only release (B Jam's decision of 2026-10-30).
- **Start-up cost** (measured in a simulation of the core's logic, no sound-cache file): about 146 ms more black screen
  after the Pocket's loading bar than with the firmware built in (the stub's check and copy of the 256 KB file), and
  the loading bar itself runs about 0.06 s longer for the extra 256 KB (estimated from the simulated load rate; the
  Pocket's own rate is not known until it runs on a Pocket).

---

## Appendix A. `pocket_map.h` v1.3 block (docs/STAGE1_PLAN.md item M8; v1.3 lines tagged, for the FW_S5 firmware)

```c
/* MCU interface v1.3 (the first new-core firmware's lines plus the synth step's). SYSINFO USER_CODE =
   POCKET_IFACE_ID. Lines tagged v1.N arrived in v1.N; a v1.2 header holds exactly the untagged, v1.1 and v1.2 lines
   (tests/check_board.py). */
#define POCKET_IFACE_ID         0x50490103u   /* 'P' 'I' major 1 minor 3 */
#define POCKET_SYSINFO_CLK      0xFFFFFFE0u
#define POCKET_SYSINFO_USER     0xFFFFFFE4u

#define POCKET_FIO(slot)        (0x01000000u + 4u * (slot))   /* slot = addr[6:2] */
#define POCKET_FIO_CTRL         POCKET_FIO(0)    /* [0] HOLD, [3] RSTSEEN, [4] MENU_MUTE_EN, [5] OPT_AT_RESET_EN,
                                                    [14:8] LSTAT, [15] CAUSE.B; write byte 0 read-modify-write */
#define POCKET_FIO_SPTR         POCKET_FIO(2)
#define POCKET_FIO_VOL_SFX      POCKET_FIO(3)    /* interim */
#define POCKET_FIO_IRQCLR       POCKET_FIO(6)    /* legacy: bit 0 = ack CAUSE.B */
#define POCKET_FIO_GO           POCKET_FIO(7)    /* W: words [20:0], 0 = stop; R: {valid, 10'0, remaining[20:0]} */
#define POCKET_FIO_CAUSE        POCKET_FIO(8)    /* R: {V,S,A,B}; W1C */
#define POCKET_FIO_MSIP         POCKET_FIO(9)
#define POCKET_FIO_TIMER        POCKET_FIO(10)
#define POCKET_FIO_TCMP         POCKET_FIO(11)
#define POCKET_FIO_TCTRL        POCKET_FIO(12)   /* bit 0 TEN */
#define POCKET_FIO_STAMP_B      POCKET_FIO(13)
#define POCKET_FIO_STAMP_A      POCKET_FIO(14)   /* v1.3: R TIMER when CAUSE.A was last set (4.6) */
#define POCKET_FIO_WLOCK        POCKET_FIO(15)   /* bits 0-20 = WRAM KB 27-47, write 1 to set */
#define POCKET_FIO_VSCNT        POCKET_FIO(16)   /* v1.1: R {16'0, VDP vertical syncs since reset, wrapping} */
#define POCKET_FIO_DEC_BASE     POCKET_FIO(17)   /* v1.2: the decoder's next output base, workspace byte offset [20:0] */
#define POCKET_FIO_DEC_STAT     POCKET_FIO(18)   /* v1.2: R depth, run, flags; W 1 clears flags 16-21 */
#define POCKET_FIO_DEC_WORDS    POCKET_FIO(19)   /* v1.2: R words written since the last START */
#define POCKET_FIO_DEC_TIME     POCKET_FIO(20)   /* v1.2: R {valid, cycles START -> GO} */
#define POCKET_FIO_DEC_MARGIN   POCKET_FIO(21)   /* v1.2: R min (first window read - GO), signed; W resets */
#define POCKET_FIO_DEC_LATECNT  POCKET_FIO(22)   /* v1.2: R window words read ahead of the decode; W clears */
#define POCKET_FIO_FEAT         POCKET_FIO(23)   /* v1.3: R what this bitstream carries (4.10), constant */
#define POCKET_CTRL_HOLD        (1u << 0)
#define POCKET_CTRL_RSTSEEN     (1u << 3)
#define POCKET_CTRL_MENU_MUTE   (1u << 4)
#define POCKET_CTRL_OPT_AT_RST  (1u << 5)        /* built dormant (B Jam's decision of 2026-10-11, STAGE1_PLAN.md Q4) */
#define POCKET_CTRL_BLKIE       (1u << 6)        /* v1.3: CAUSE.BLK takes part in the MEI line */
#define POCKET_CAUSE_B          (1u << 0)
#define POCKET_CAUSE_A          (1u << 1)
#define POCKET_CAUSE_S          (1u << 2)
#define POCKET_CAUSE_V          (1u << 3)
#define POCKET_CAUSE_BLK        (1u << 4)        /* v1.3: the synth's BUSY fell (3.10.5); W1C */

#define POCKET_RAMDP_BV_BASE    0x02800000u      /* byte view, read-only */
#define POCKET_FLASH_BV_BASE    0x04800000u      /* byte view, read-only */
#define POCKET_FREG_BASE        0x0B000000u      /* + chip offset 0x00-0x1E; stored: 0x04, 0x06, 0x0A, 0x0C */

#define POCKET_OPT_MENU         (1u << 24)
#define POCKET_OPT_JAP          (1u << 25)
#define POCKET_OPT_PAL          (1u << 26)

/* ---- v1.3 (the synth step): FEAT bits (4.10) ---- */
#define POCKET_FEAT_CACHE       (1u << 0)        /* v1.3: the sound-cache slot, XLINK CACHE / CACHE_LOADED */
#define POCKET_FEAT_BAR         (1u << 1)        /* v1.3: the first-boot bar, XLINK BAR */
#define POCKET_FEAT_SYNTH       (1u << 2)        /* v1.3: region 0x06 = the synth (3.10); CAUSE.BLK live */
#define POCKET_FEAT_SFXFIFO     (1u << 3)        /* v1.3: region 0x06 = the interim audio_sfx FIFOs; VOL_SFX live */
#define POCKET_FEAT_MDP         (1u << 4)        /* v1.3: region 0x07 = the interim MD+ block / EverDrive stub */
#define POCKET_FEAT_ALBUM       (1u << 5)        /* v1.3: the interim album path (APF slot 300) */
#define POCKET_FEAT_GS3         (1u << 6)        /* v1.3: the virtual Grand Stick III (nothing MCU-visible) */
#define POCKET_FEAT_IROM_SHIFT  16u              /* v1.3: FEAT[23:16] = the IROM size in KB (72 or 88) */
#define POCKET_FEAT_IROM_MASK   0x00FF0000u      /* v1.3 */

/* ---- v1.3: XLINK 0x40-0x48, the sound-cache slot and the first-boot bar (3.9) ---- */
#define POCKET_XL(off)          (0x0A000000u + (off))   /* v1.3: XLINK decodes addr[6:2] */
#define POCKET_XL_CACHE         POCKET_XL(0x40)  /* v1.3: [31] VALID, [22:0] SIZE; power-on reset only, one-shot */
#define POCKET_XL_CACHE_LOADED  POCKET_XL(0x44)  /* v1.3: R bytes the Pocket loaded into the cache window */
#define POCKET_XL_BAR           POCKET_XL(0x48)  /* v1.3: [31] EN, [10:0] PX; R [26:16] W (active width) */
#define POCKET_CACHE_VALID      (1u << 31)       /* v1.3 */
#define POCKET_CACHE_SIZE_MASK  0x007FFFFFu      /* v1.3 */
#define POCKET_CACHE_IMAGE_MAX  0x152100u        /* v1.3: HDR + BANK (3.8) */
#define POCKET_CACHE_BRIDGE     0x60000000u      /* v1.3: the slot's APF bridge address (21.1) */
#define POCKET_BAR_EN           (1u << 31)       /* v1.3 */
#define POCKET_BAR_PX_MASK      0x000007FFu      /* v1.3 */
#define POCKET_BAR_W_SHIFT      16u              /* v1.3 */

/* ---- v1.3: the CRAM die-0 map (3.8): MCU address = 0x09000000 + CRAM byte ---- */
#define POCKET_CR(off)          (0x09000000u + (off))   /* v1.3 */
#define POCKET_CRAM_HDR         POCKET_CR(0x000000)     /* v1.3: the cache image's header */
#define POCKET_CRAM_HDR_BYTES   0x100u                  /* v1.3 */
#define POCKET_CRAM_BANK        POCKET_CR(0x000100)     /* v1.3: the wave bank */
#define POCKET_CRAM_BANK_BYTES  0x152000u               /* v1.3 */
#define POCKET_CRAM_BGMRING     POCKET_CR(0x152100)     /* v1.3: 256 x 40 x {L,R} */
#define POCKET_CRAM_BGMRING_BYTES 0xA000u               /* v1.3 */
#define POCKET_CRAM_SFXRING     POCKET_CR(0x15C100)     /* v1.3: 256 x 20 x {L,R} */
#define POCKET_CRAM_SFXRING_BYTES 0x5000u               /* v1.3 */
#define POCKET_CRAM_DACBUF_L    POCKET_CR(0x170000)     /* v1.3: 1,920 x u16 */
#define POCKET_CRAM_DACBUF_L_BYTES 0xF00u               /* v1.3 */
#define POCKET_CRAM_DACBUF_R    POCKET_CR(0x170F00)     /* v1.3: 1,920 x u16 */
#define POCKET_CRAM_DACBUF_R_BYTES 0xF00u               /* v1.3 */
#define POCKET_CRAM_CURVE_WIN   POCKET_CR(0x180000)     /* v1.3: the curve's window */
#define POCKET_CRAM_CURVE_WIN_BYTES 0x30000u            /* v1.3 */
#define POCKET_CRAM_CURVE       POCKET_CR(0x194000)     /* v1.3: the curve, 16,384 x u16 */
#define POCKET_CRAM_CURVE_CTR   POCKET_CR(0x198000)     /* v1.3: curve index 0 */
#define POCKET_CRAM_SFXBANK     POCKET_CR(0x200000)     /* v1.3: the SFX bank as 68000 words */
#define POCKET_CRAM_SFXBANK_BYTES 0x90000u              /* v1.3: reserved (552,748 B used) */
#define POCKET_CRAM_MODSTORE    POCKET_CR(0x300000)     /* v1.3: reserved fall-back for the decoded modules */
#define POCKET_CRAM_MODSTORE_BYTES 0xC0000u             /* v1.3 */

/* ---- v1.3: the synth, region 0x06 (3.10; FEAT.SYNTH) ---- */
#define POCKET_SYN(off)         (0x06000000u + (off))   /* v1.3: addr[11:2] decoded */
#define POCKET_SYN_ID           POCKET_SYN(0x000)       /* v1.3: R 0x53350001 */
#define POCKET_SYN_CONFIG       POCKET_SYN(0x004)       /* v1.3: [1:0] MODE, [2] PAL, [3] DTWIN, [31:16] SEQ */
#define POCKET_SYN_FLAGS        POCKET_SYN(0x008)       /* v1.3 */
#define POCKET_SYN_WMASTER      POCKET_SYN(0x00C)       /* v1.3 */
#define POCKET_SYN_WBOOST       POCKET_SYN(0x010)       /* v1.3 */
#define POCKET_SYN_SMASTER      POCKET_SYN(0x014)       /* v1.3 */
#define POCKET_SYN_SMCFG        POCKET_SYN(0x018)       /* v1.3 */
#define POCKET_SYN_ECHOB        POCKET_SYN(0x01C)       /* v1.3: [15:0] GAIN, [23:16] DELAY, [31:24] INDEX */
#define POCKET_SYN_ECHOS        POCKET_SYN(0x020)       /* v1.3 */
#define POCKET_SYN_ARM          POCKET_SYN(0x024)       /* v1.3: W bit 0 = frame_pending */
#define POCKET_SYN_SEQ          POCKET_SYN(0x028)       /* v1.3: R [15:0] ARR, [31:16] DONE */
#define POCKET_SYN_DONE         POCKET_SYN(0x02C)       /* v1.3: W DONE (synth_end) */
#define POCKET_SYN_STATUS       POCKET_SYN(0x030)       /* v1.3 */
#define POCKET_SYN_PHASE        POCKET_SYN(0x034)       /* v1.3: TEST only */
#define POCKET_SYN_YMFILT       POCKET_SYN(0x038)       /* v1.3 */
#define POCKET_SYN_DTOUT        POCKET_SYN(0x03C)       /* v1.3: [15:0] GAIN Q8.8, [16] INVERT, [20:17] DCK */
#define POCKET_SYN_DIAG         POCKET_SYN(0x040)       /* v1.3 */
#define POCKET_SYN_TIMEOUT      POCKET_SYN(0x044)       /* v1.3 */
#define POCKET_SYN_SEQLAT       POCKET_SYN(0x048)       /* v1.3: R [15:0] last B arrival, [31:16] last A */
#define POCKET_SYN_SCHED        POCKET_SYN(0x04C)       /* v1.3: R [7:0] CNT, [11:8] NBLK, [31:16] HALF */
#define POCKET_SYN_ID_VALUE     0x53350001u             /* v1.3 */
#define POCKET_SYN_MODE_DT      1u                      /* v1.3: CONFIG.MODE */
#define POCKET_SYN_MODE_YM      2u                      /* v1.3 */
#define POCKET_SYN_CFG_PAL      (1u << 2)               /* v1.3 */
#define POCKET_SYN_CFG_DTWIN    (1u << 3)               /* v1.3 */
#define POCKET_SYN_CFG_SEQ_SHIFT 16u                    /* v1.3 */
#define POCKET_SYN_FL_SEQON     (1u << 0)               /* v1.3: FLAGS */
#define POCKET_SYN_FL_PLAYING   (1u << 1)               /* v1.3 */
#define POCKET_SYN_FL_SFXON     (1u << 2)               /* v1.3 */
#define POCKET_SYN_FL_BGMECHO   (1u << 3)               /* v1.3 */
#define POCKET_SYN_FL_SFXECHO   (1u << 4)               /* v1.3 */
#define POCKET_SYN_FL_LEVELNZ   (1u << 5)               /* v1.3 */
#define POCKET_SYN_ST_BUSY      (1u << 0)               /* v1.3: STATUS */
#define POCKET_SYN_ST_RUN       (1u << 1)               /* v1.3 */
#define POCKET_SYN_VOICE(v)     POCKET_SYN(0x400u + 0x40u * (v))   /* v1.3: v = 0..15 = the chip's voice 10 + v */
#define POCKET_SYN_SFX(c)       POCKET_SYN(0x800u + 0x40u * (c))   /* v1.3: c = 0..7 */
#define POCKET_SV_POS           0x00u            /* v1.3: VOICE field offsets (3.10.3) */
#define POCKET_SV_LEN           0x04u            /* v1.3 */
#define POCKET_SV_LOOP          0x08u            /* v1.3 */
#define POCKET_SV_BASE          0x0Cu            /* v1.3 */
#define POCKET_SV_STEP          0x10u            /* v1.3 */
#define POCKET_SV_DECLICK       0x12u            /* v1.3 */
#define POCKET_SV_GAIN_L        0x14u            /* v1.3 */
#define POCKET_SV_GAIN_R        0x16u            /* v1.3 */
#define POCKET_SV_LAST_L        0x18u            /* v1.3 */
#define POCKET_SV_LAST_R        0x1Au            /* v1.3 */
#define POCKET_SV_ENV_LEVEL     0x1Cu            /* v1.3 */
#define POCKET_SV_ENV_CNT       0x1Eu            /* v1.3 */
#define POCKET_SV_ENV_STATE     0x20u            /* v1.3: u8 */
#define POCKET_SV_BB            0x21u            /* v1.3: u8 */
#define POCKET_SV_MUTE          0x22u            /* v1.3 */
#define POCKET_SV_AR            0x24u            /* v1.3: u8 x 7: AR HOLD DR SL SUS D2R RR */
#define POCKET_SV_HOLD          0x25u            /* v1.3 */
#define POCKET_SV_DR            0x26u            /* v1.3 */
#define POCKET_SV_SL            0x27u            /* v1.3 */
#define POCKET_SV_SUS           0x28u            /* v1.3 */
#define POCKET_SV_D2R           0x29u            /* v1.3 */
#define POCKET_SV_RR            0x2Au            /* v1.3 */
#define POCKET_SV_COMPAND       0x2Bu            /* v1.3: u8, always 0 */
#define POCKET_SS_PTR           0x00u            /* v1.3: SFX field offsets (3.10.4) */
#define POCKET_SS_BASE          0x04u            /* v1.3 */
#define POCKET_SS_POS           0x08u            /* v1.3 */
#define POCKET_SS_LEN           0x0Cu            /* v1.3 */
#define POCKET_SS_FORMAT        0x10u            /* v1.3: u8 */
#define POCKET_SS_RATE          0x11u            /* v1.3: u8 */
#define POCKET_SS_ID            0x12u            /* v1.3 */
#define POCKET_SS_GAIN_L        0x14u            /* v1.3 */
#define POCKET_SS_GAIN_R        0x16u            /* v1.3 */
#define POCKET_SS_LOOP          0x18u            /* v1.3: u8 */
#define POCKET_SS_FILT          0x19u            /* v1.3: u8 */
#define POCKET_SS_Y             0x1Au            /* v1.3 */
#define POCKET_SS_DELAY         0x1Cu            /* v1.3 */
```
