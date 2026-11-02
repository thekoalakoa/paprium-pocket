# Cart FPGA spec: what the Paprium cart's FPGA does, seen from both sides

A deliverable of the project plan ("Cart FPGA and bootloader"), written before the new-core work began and checked claim
by claim against the ROM, the cart chip's program and the cited notes in a separate review, 2026-10-11 (what the review
changed: section 18).
Companion: `docs/BOOT_SPEC.md` (power-on and reset).

**What this is.** The real cart's FPGA (an Intel MAX 10 under the epoxy) has never been read out and never will be: we
do not read out or attack the real cart. This page describes what that FPGA does as the two parties around it see it:
- the **console side**: the 68000, the Z80 bank window and VDP DMA reading and writing cart space;
- the **cart chip side**: the cart's STM32 program, whose behaviour our firmware reproduces, writing and reading the
  FPGA's registers.

The new core's RTL and board layer implement it. Every row gives the rule, how it is known, what the shipped 0.2.6
does, and what the new core does.

**The RTL sprite decoder (2026-10-15, proposed with MCU interface v1.2).** B Jam's decision ("preservation: reply at
once, sprites already done, never wait") moves the 0x80 decoder and its queue (section 9) from the firmware's board
layer into our RTL, as on the cart: the chip's own `$1FF2` / `$1FF4` / `$1FF6` writes drive it, and the firmware only
writes the decoder's output base before each start. The full behaviour, the timing contract and the choices still open
are in our decoder design notes, which are not published; docs/MCU_INTERFACE.md section 4.9 is the MCU's view. Where
this page says "the firmware queue" or "the board decodes", read "the RTL decoder" from that change on.

**How we know.** Where it matters, a statement says how it is known: "measured" (read from code or an image, or counted
in a run), "estimated" (arithmetic on measured numbers), "not known" (nobody knows), "checked" (verified in code or a
run), "read in the code" (read only), "inferred", "web source". Rows marked "proposed" are proposals for the new core: a
name, address or bit that is not frozen until the new core's RTL interface freeze.

**Conventions.** `$xxxx` = a 68000 address. `+N` = register offset N from `$1FE0`; the chip reaches `+N` at MCU address
`0x68040000+N`. `0x08xxxxxx` = a chip program address (PC). "MCU word" = what the chip writes into a register.
"68000 view" = what the console reads there. "File" = our ROM file (md5 91ccdc0b).

**Sources read** (all in place; md5 first 8):

| what | where | md5 |
|---|---|---|
| chip program (STM32 app) | the cart program (outside this tree) | - |
| ROM file | our ROM file | 91ccdc0b |
| study register list | our study file `fpga_regs.csv` | 2c4e0afa |
| chip-runner trace of every post type | our trace files `byreg.tsv`, `fifo.tsv`, `seq.tsv` | 2f32e593, c0704ef2, - |
| static scan of FPGA accesses | our scan file `static.tsv` | 710e9b90 |
| 0.2.6 RTL (a copy of the final tree) | our copy of the final 0.2.6 RTL: `cartridge.sv`, `PAPRIUM/paprium_cart.sv`, `PAPRIUM/paprium_addons.sv`; our copy of the final 0.2.6 bitstream tree, `rtl/PAPRIUM/`: `fpgio.sv`, `ramdp_io.sv`, `paprium_mcu_mem.sv` | bb6fd024, ccc5adff, 80ff9fe7; f3fcbcb2, 8fbdf7ab, 425bbff4 |
| 0.2.6 firmware | `paprium-fw/legacy/026/paprium.c` | 983f5e18 |
| census posts | our census files `posts_{solo,duo,c2}.tsv` | - |

The release worktrees were not opened; the RTL above is our working copy of the
shipped tree (paprium_cart.sv ccc5adff = the final 0.2.6 file; fpgio, ramdp_io, paprium_mcu_mem and mcu_core are
byte-identical in our copy of the third 0.2.6 test build too; checked by md5).

---

## 0. Findings first

1. **The FPGA's job, as anything around it can see, is small and now fully listed.** (checked)
   - Ten 16-bit registers at `$1FE0-$1FFF` (`+4` to `+0x16`), a read window at `$C000-$FFFF`, a busy bit, a two-key
     read path (the "views"), a block-decoder queue, two FIFO ports and four interrupt lines into the chip.
   - The chip touches the registers at **56 write sites and 24 read sites**. The study list had 56 and 17. This page
   adds **7 reads of `$1FEA` in the fatal-halt backdoor** (`0x08020BF2`, `C00`, `C0E`, `C1C`, `C2A`, `C38`, `C46`)
   (checked in our study of the cart and in a run; `xcheck.py`). Every other site in the static scan and the
   run is in the list (checked).
2. **The register map gap of our study notes (G-REGMAP) is closed** (section 4): one row per chip write, saying what our
   board does with it (window on/off,
   stream start, busy, view switch, queue, or store only).
3. **`$1FE4` is two registers at one address, and the chip reads its own side back.**
   - The heartbeat (`0x08020DFA`) reads `$1FE4` and tests bit 11, its own EEPROM-job flag; bit 11 still set at that
     check sends the chip to the fatal halt `0x400000FB` (`$1FEE = 0xAF5B`, `$1FE4 = 0x4200`) (checked). So an MCU read
     must return the stored MCU word, never the composed 68000 view (which would hide a stuck job) (checked in the code;
     inferred that the cart does the same).
   - The 68000 view is `(busy << 2) | Console bits 6, 8-10`, all other bits 0. At the game's only whole-word read
     (`$BCA22`, after C6) that is exactly 0.2.6's `0x0004 | model` (checked in the code; a decision of the project
     plan).
4. **The window comes on with the first stream: on every recorded route a DB06 at frame 174, 106 frames before the first
   AF.** Measured on all three census routes (`firstposts.py`; GPGX frame numbers). The boot is the same on all three
   (their posts agree up to frame 1149), so this is one boot seen three times, not three independent ones. AF and B1
   never write `$1FE8` (checked: `0x08018FFC`), so the "`$1FE8` = window enable" reading needs exactly that order, and
   the boot shows it.
5. **The 84 switch has no lower time bound on ours, only an upper one.** (Checked; the times are estimated.)
   - The post routines wait for `$1FEA` bit 15 *before* writing and never wait for the reply (`$B43A0`, `$B4344`).
   - After the `8400` write the 68000 returns through ROM `$B43BC` and jumps to the NOP sled at `$FF0000`: 2,048 NOPs,
     then `jmp $8200` (`$B4652-$B4692`).
   - So the first fetch at `$8200` comes about **1.075 ms** after the post write (NTSC; 1.085 ms PAL). Estimated:
     40 + 8,192 + 12 cycles at 7.670 MHz. The sled alone (8,192 + 12 cycles) is the 1.070 ms that docs/BOOT_SPEC.md
     quotes;
     an interrupt during the sled only makes the deadline later.
   - In between, the 68000 reads only ROM at `$B43BC`+ and work RAM. Our switch touches only `$2000-$7FFF` and
     `$C000-$FFFF`, so it can land at any time before ~1.07 ms.
6. **On ours the busy bit needs a hardware guard; it is not optional.** (Checked; the times are estimated.)
   - The game polls bit 2 straight after writing a DB06 post (`$7F46E` about 80 cycles = 10 us later, `$B4272` about
     120 cycles = 15 us; estimated from the instruction cycles).
   - Our interrupt can be held off by a running L1 handler (the firmware's interrupt design: AF up to 17.3k cycles =
     0.32 ms at 53.69 MHz, estimated; **measured in the system co-simulation of the first new-core firmware (the
     firmware on a simulation of the RTL): L1 entries up to 8.5 ms, all of them AD bodies** (its "D1 3.5 ms" was an AD
     body served in the same entry; D1 alone 213 us); a later change (2026-10-13) moved the sprite
     decodes out of L1: AD at most 1.16 / 1.30 ms RELEASE / TEST in the RV32 model, estimated). A stale "ready" from
     the previous stream would then be read. The RTL guard covers any length.
   - The cart's chip stops the old stream within microseconds, so the game never sees stale data there (inferred).
   - Rule: the RTL raises busy on the 68000's DA/DB/F2 post and keeps it until the chip code's next `$1FF2` or
     `$1FEA` write (section 7).
7. **The decoder queue is served in reverse push order.** The chip pushes the frame's load list last-to-first
   (`0x08019038-0x0801907A`), and our comparison test harness found the block DMAs consume the addresses in reverse
   write order (checked, the harness's finding 2). So the queue behaves as a stack, and the blocks come out in
   load-list order.
8. **FIFO B is "first chunk 0x78 words, then 0x40 per refill", and the DB06 length is in bytes.** (checked in a run)
   - `DB06 0000 4C00 0080` streamed one 128-byte chunk marked last (`$1FF2 = 0x4000`) (checked: `fifo.tsv`).
   - 970 of 1,015 solo-route DB06 posts are 0x80 bytes; the longest is 0x2000 (measured in the census).
   - On ours FIFO B stays a pointer plus a length into our SDRAM, with no refill interrupts (section 9).
9. **The FM-bank XOR window is `$2000-$7FFF`; above it the game view is the file as is.** (checked with `xorwin.py`;
   inferred where marked)
   - `$2000-$3FFF`: 32 of 32 256-byte blocks equal the plain filler after XOR 0xA8A2, 0 as is.
   - `$50E0-$7FFF`: 46 of 48 equal after XOR, 0 as is. The last 2 (`$7E00-$7FFF`) run past the reference copy's
     length, so they are not checked; nothing reads them. The `$8000` edge is (inferred) (no reader between `$7E00` and
     `$8000`).
   - Above `$8000` the game view has **one visible reader** (corrected in review; the draft said none): the boot text
     page DMAs ROM `$BC20-$C01F` to VRAM `$1000` (PC `$167A`, frame 22, after the 'SE' handshake, so in game view).
     That data looks like tiles only as is: 410 of its 2,048 nibbles are 0 as is, 67 after XOR 0xA8A2 (measured
     counts). So the cart serves the file as is there (inferred, strongly: under the other key those 32 tiles would be
     noise; not yet checked against a photo of the real text page). That is what the new core serves.
   - The boot DMA timing test (`$BC9B8`, 0xC0 words from `$8000`) reads only the VDP status afterwards (checked), so it
     does not tell the views apart.
10. **New: 0.2.6 answers 68000 reads of `$400000-$7FFFFF` with the upper half of the ROM image** when the Mega CD option
    is None (`cartridge.sv` `cart_cs_ext`, line 896) (checked). A real cart drives only `/CE0` space there (inferred).
    The eight words the game's Mega CD check compares (as listed in `paprium_addons.sv` (read in the code)) hold no
    `BO`/`WO` ID pair in the image (`upperprobe.py`) (checked), so the game sees "no CD" either way (inferred; test R12
    checks it). Invisible; the new core builds the cart's behaviour anyway (decision F-D3: no answer there with Mega CD
    = None).
11. **The chip writes `$1FE6` before it clears `$1FEA`** (e.g. DA02: `$1FE6 = 0x6008`, then `$1FEA = 0`, then
    `0xE008`) (checked: `seq.tsv`). Our register file must keep that order visible to the 68000 (one clock domain, no
    write reordering).

---

## 1. The two views (and our two states)

### 1.1 What the widely shared ROM files show (checked with `keycheck.py`, `portcheck2.py`; inferred where marked)

The flash chip holds the ROM scrambled. Each console word = flash word XOR (a base | 8 key bits from the word
address). Two bases exist: `0x8A28` (the game key) and `0x228A` (the cartridge-reader key). `0x8A28 XOR 0x228A =
0xA8A2`.

| view | when | `$0000-$1FDF` | `$1FE0-$1FFF` | `$2000-$7FFF` | `$8000-$BFFF` | `$C000-$FFFF` | `$10000-$3FFFFF` |
|---|---|---|---|---|---|---|---|
| **D** (cartridge reader, power-on) | before 'SE' (inferred) | the 8 KB boot page, repeated at the start of every 64 KB block (checked) | 32 fixed bytes, not registers (checked: the bytes; inferred: the meaning) | file as is | file as is | file as is | file XOR 0xA8A2: the game is unreadable (checked) |
| **G** (game) | after 'SE' (inferred) | RAMDP | register file | file XOR 0xA8A2 = plain FM bank (checked: the arithmetic; inferred that the cart uses it) | file as is (inferred: strong: the boot text page DMAs `$BC20-$C01F`, finding 9) | stream window when on, else ROM (file as is) | file as is |
| **M** (after 84) | mini-game (inferred) | RAMDP | not read (checked) | not read (checked) | file as is (mini-game code) (checked: GPGX) | ROM (window off) (checked: GPGX) | not read (checked) |

- "Not read" = the `$8200` program never reads there: it touches no cart register, and its only cart reads are its
  code (`$8200-$AB58`, `$CD00-$D1B3`), 5,708 68000 byte reads at `$C000-$CFB1` and 32 VDP-DMA reads at `$D0D4-$D1B2`
  (checked in our completeness review, item OUT-1, GPGX run).
- Our ROM file's first 64 KB came from view D. That is why the FM bank looks XOR'd in the file (checked in our study
  notes).

### 1.2 What switches them

| switch | evidence | how known |
|---|---|---|
| D -> G at the boot page's 'SE' handshake (`$1D14`: read `$C0001E`, need `& $FFFC = $5345`) | the only candidate in the boot code; a cartridge reader never makes that read; the cart must change what it serves, or the game would read as file XOR 0xA8A2 | (inferred) |
| G -> M at 84 | the mini-game needs `$8000-$FFFF` and `$C000-$CFB1` as the file | (inferred); which write triggers it not known |
| back to D or G at console Reset | unknown | not known |

### 1.3 Ours (the new core)

| state | when | `$0000-$1FDF` | `$1FE0-$1FFF` | `$2000-$7FFF` | `$8000-$BFFF` | `$C000-$FFFF` | `$10000-$3FFFFF` |
|---|---|---|---|---|---|---|---|
| **game** (`mini_view = 0`) | core reset (power-on, Soft Reset) | RAMDP | register file | file XOR 0xA8A2 | file | window when on, else file | file (+ Scum! words) |
| **mini** (`mini_view = 1`) | MCU writes `$1FE8 = 0` or `$1FEE = 0xAF5B` | RAMDP | register file | file | file | file (window forced off) | file |

Deliberate differences from the cart (all invisible, (checked) where stated):
- No D phase. The boot-page patches (0.2.6's, docs/ALLOWLIST.md row B3) skip the 'SE' read, and nothing reads
  `$2000-$FFFF` before that point (checked in the boot page listing). The first such read, the text page's DMA of
  `$BC20-$C01F`, comes after it, in game view (finding 9).
- No 64 KB mirroring of the boot page.
- In "mini" we keep `$10000+` readable. The mini-game never reads there (checked).
- The "game" key at `$8000-$FFFF` is taken as "file as is" (inferred, strongly: finding 9, the only reader whose data is
  seen, the boot text page's DMA of `$BC20-$C01F`, needs it).

---

## 2. ROM serving and mapping

### 2.1 Console side

| range | rule on the cart | how known | 0.2.6 | new core |
|---|---|---|---|---|
| `$000000-$001FDF` | RAMDP, 8 KB dual-port; 68000 reads and writes | (checked) | 0.2.0-0.2.5: `ramdp_io`, per-lane writes (`cpu_we[3:0]`); 0.2.6 as shipped: byte writes ignored (2026-10-11) | keep; a 68000 byte write stores the whole word (Q2, row below) |
| byte writes into RAMDP | the game's self-test `$2B83E` writes `$F2F0` to `$1F0E`, a byte 0 to `$1F0F`, and sets a flag at `$FF9986` (what it does: not known) if the word then reads `$F200` (or if `$F2F0` did not stick). So the cart either ignores byte writes or writes the whole word (the 68000 puts the byte on both halves). Never reached in 15 census runs. | (checked in the code; the cart's rule inferred) | 0.2.0-0.2.5: true byte lanes, which set the flag (measured in GPGX at the first food pickup); 0.2.6 as shipped: ignored, which passes | **whole word (decided: B Jam's decision of 2026-10-11 on docs/STAGE1_PLAN.md question Q2; built as its item C7; docs/ALLOWLIST.md row B32):** the byte lands on both halves (the 68000 drives it on both); the check passes (measured on the FX68K bench `tb_sys`: `$2B83E` reads 0000, `$FF9986` stays 0). Was "decision 5 (open): per lane". Which form the real cart uses stays not known |
| `$001FE0-$001FFF` | register file (68000 view); the RAMDP words behind it are MCU-only | (checked) | plain RAMDP words, both sides | register file (section 3); 68000 writes to RAMDP `$1FE0-$1FFF` suppressed |
| `$002000-$007FFF` | file XOR 0xA8A2 in game view; readers: the Z80 bank window only (`$4000-$50DF`, the FM patches) | (checked: the readers, census 3b; the cart's key inferred) | file as is (FM never played on the port) | XOR 0xA8A2 on the read data while `mini_view = 0` (section 2.3) |
| `$008000-$00BFFF` | ROM, the file as is in game view; read by the boot text page's DMA (`$BC20-$C01F`) and the mini-game | (checked: the readers; the key inferred, strongly, finding 9) | file | file |
| `$00C000-$00FFFF` | stream window when on, else ROM | (checked in the code) | stream when `sdram_en`, else file | section 5 |
| `$010000-$3FFFFF` | ROM | (checked) | file + Scum! overlay (docs/ALLOWLIST.md row B31) | same |
| `$200000-$20016B` during boot | the cart serves a 182-word stub (inferred); the header declares save RAM at `$200000-$20FFFF` (checked) | (inferred) | file bytes; the patched boot page never runs the copy (`jsr $10100`) | same (docs/ALLOWLIST.md row B3) |
| `$400000-$7FFFFF` | not cart space on a real cart (`/CE0` is `$000000-$3FFFFF`) (inferred) | (inferred) | ROM image upper half via `cart_cs_ext` when Mega CD = None (checked) | **F-D3: no answer when Mega CD = None** (`cart_cs_ext` gated; the console's open bus); a unit: the 0.2.6 stub exactly. docs/ALLOWLIST.md row B25, test R12 |
| `$A13000-$A130FF` (`/TIME`) | no bank logic; nothing answers | (checked: anti-SSF2 check `$81186`) | SSF2 banking suppressed (`!PAPRIUM`, `cartridge.sv:476`) | keep |
| `$C0001E` (VDP space) | the cart answers 'SE' on a read with no cart select (inferred) | (inferred) | not answered (boot patch) | same (row B3) |

### 2.2 Cart chip side (MCU bus)

| chip window | what the chip uses it for | how known | 0.2.6 | new core |
|---|---|---|---|---|
| `0x68060000` RAMDP view | everything (args, SAT, DMA list, Boom Box feed, scaling); init reads RAMDP `$1FE0-$1FEF` (bootloader page pointers) | (checked) | RAMDP `0x02000000`, MCU halfword at `+A` = 68000 word `A` | same; the page pointers become firmware variables (docs/BOOT_SPEC.md) |
| `0x68860000` (= RAMDP view + `0x800000`) | MegaWire init reads header bytes `+0x120-0x14F` and `+0x183-0x18D` in every C6, MegaWire Off included | (checked in a run); byte-order view of RAMDP (inferred, strongly) | none | RAMDP byte view: the same RAMDP with byte A at MCU byte A, alias at `0x02800000` (proposed) |
| `0x68040000` registers | section 3 | (checked) | RAMDP words | register file at `0x0B000000` + chip offset (proposed) |
| `0x6C000000` flash word view | SFX samples read in place; OTA CFI writes | (checked) | `ADDR_FLA 0x04000000` (halfword at A = 68000 word A) (checked: `paprium_mcu_mem.sv`) | same; OTA writes never issued (MegaWire update inert) |
| `0x6C800000` flash byte view | format bytes, LZO input, block tables | (checked in a run) | none (software swaps) | flash byte view alias at `0x04800000` (proposed): byte A = ROM byte A |
| `0x64000000` FIFO A port | Z80 packet into RAMDP `$1800` | (checked) | none | firmware writes RAMDP directly |
| `0x64020000` FIFO B port | window data | (checked) | none | pointer stream (section 9) |

- The flash behind the FPGA is 8 MB. The decoder queue takes 23-bit byte addresses, so the FPGA reads the MCU-only
  upper 4 MB on its own (checked: mask `0x7FFFFE` at `0x0801D20A`).
- The chip never reads `$2000-$7FFF` through any view (checked: census 3b). So the MCU views stay the file as is; the
  XOR is on the console path only.

### 2.3 The FM XOR in RTL (B Jam's decision: core circuitry, not the MCU)

- **Rule.** On a console-bus ROM read whose byte address is in `$2000-$7FFF`, while `mini_view = 0`, the data word is
  XORed with `0xA8A2` (even byte `^0xA8`, odd byte `^0xA2`). Off after 84; on again at core reset.
- **Where (0.2.6 file names).** `cartridge.sv` captures `cart_data <= scum_use ? scum_data : rom_data` (line 314).
  The new core XORs `rom_data` there when the latched `rom_addr` is in range, the read is not the stream
  (`paprium_stream_pending` clear) and `mini_view` (from the cart clock domain, synchronised) is 0.
- **Readers covered:** 68000 (never reads there), Z80 bank reads (`$4000-$50DF`), VDP DMA (never). The Z80 byte read
  takes the matching half, so even bytes get `0xA8` and odd bytes `0xA2` (checked: arithmetic).
- **Cost:** 16 XOR + a range decode + one flop, a few ALM (estimated). One LUT level on `rom_data -> cart_data`: static
  timing analysis (STA) checks it.
- **Rule for later ROM patches:** any patch inside `$2000-$7FFF` must be stored pre-XORed. None exists today: the
  lowest Scum! patch is the word at byte `$1A9FA` (`paprium_scum.sv`, `24'h00D4FD`), and the 0.2.6 boot patches' only
  ROM patch is at `$81104` (checked; corrected in review, the draft said Scum! started at `0x0BF040`).

---

## 3. The register file `$1FE0-$1FFF`

### 3.1 One line per register

"MCU w/r" = the chip's writes and reads (PCs in 3.2). "68k" = the game's accesses (PCs in 3.3). Reset = ours.

| reg | MCU w/r | 68k | meaning (how known) | reset (ours) | 0.2.6 | new core |
|---|---|---|---|---|---|---|
| `+0`/`+2` `$1FE0/2` | never | never | unused (checked) | 0 | RAMDP words | read 0; writes ignored |
| `+4` `$1FE4` | W whole word (control word); R bit 11 | R: bit 2 (4 sites), whole word once | MCU word vs 68000 status (checked) | 0 (68000 view: busy = 1 -> `0x0004 \| model`) | RAMDP `0x0004 \| opt` at reset; busy v2 in firmware | store MCU word; MCU reads it back; 68000 reads the composer (3.4) |
| `+6` `$1FE6` | W whole word; R bit 12 at init | R: bits 0-5, 8, 9, 14 | MCU status passed through (checked) | 0 (bit 12 must be 0) | RAMDP `opt >> 16` | store; both sides read it as is |
| `+8` `$1FE8` | W 1 / 0 | never | window enable (inferred: best) | 0 (window off) | `sdram_en` in fpgio, set at reset and 81 | store; side effects (section 4) |
| `+A` `$1FEA` | W 0 / 0x1234; R | W posts; R bit 15 (no timeout) | mailbox B (checked) | 0 (bit 15 clear: required) | RAMDP `reg_cmd`; `mbx_irq` latch | store; 68000 write raises the IRQ |
| `+C` `$1FEC` | W 0; R | W `0x9494` once a frame | mailbox A, the frame tick (checked) | 0 | RAMDP, no IRQ | store; 68000 write raises the IRQ |
| `+E` `$1FEE` | W `0xAF5B`; R (OTA status) | never | magic on "stop serving"; flash status read (checked: the values; inferred: what they do) | 0 | none | store; MCU read returns 0 (proposed); side effect (section 4) |
| `+10` `$1FF0` | W | never | FIFO A target (checked) | 0 | none | store only |
| `+12` `$1FF2` | W | never | stream control (checked: the values; inferred: the bits) | 0 | none | store; side effects |
| `+14` `$1FF4` | W | never | queue entry, high (checked) | 0 | none | store; queue latch |
| `+16` `$1FF6` | W | never | queue entry low / clear (checked; inferred) | 0 | none | store; queue push or clear |
| `+18`-`+1E` | never | never | unused (checked) | 0 | RAMDP | read 0 |

### 3.2 Every chip access, by PC (checked by a static scan, a run and our study of the cart; `xcheck.py`)

**`+4 $1FE4`** writes:
- `0x0801FA2E = 0x46F8` (app init);
- `0x08022CBA` (status helper `0x08022C78`, `r1 = 2`: set or clear a mask in the shadow G+0xE, store the whole word).
  Callers: bit 8 cleared at DB06 (`0x0801D478`), DA direct (`0x0801D222`), F2 (`0x08017E7E`), AE (`0x08018FDC`),
  AF/B1 (`0x08019018`), B0 and C6 init (`0x0801975E`); bit 8 set at DA direct (`0x0801D244`), F2 (`0x08017EC6`) and
  AF/B1 (`0x0801908E`); bits `0x18` cleared at 84 (`0x0801B6B4`); bit 11 = EEPROM job; bit 13 at init end
  (`0x0801FB44`); MegaWire screen `0x1000`/`0x4000`/`0x4010`/`0x4660`. Values seen in the run: `0x66F8`, `0x67F8`,
  `0x6EF8`, `0x6FF8`, `0x67E0`;
- `0x0801B68E = 0x4000` (85); `0x08020E0C = 0x4200` (heartbeat fatal `0x400000FB`); `0x08020EBA = 0x4200` (watchdog
  fatal `0x400000FA`); `0x08020E94 = 0` (watchdog reset path, 81 bit 4, never posted); `0x0801FCD2 = 0` (MCU
  self-reset).

  Read: `0x08020DFA` (heartbeat; bit 11).

**`+6 $1FE6`** writes: `0x0801FA28 = (old & 0x1000) | 0x4000` (init); `0x08022CA2` (helper, `r1 = 3`, the status layer:
entry, refusals, done, job bits; the run saw bits 15, 14, 13 and 3 in every combination). Reads: `0x0801FA06`,
`0x0801FA08` (init: bit 12 = "boot into the MegaWire screen").

**`+8 $1FE8`** writes: `0x0801D482 = 1` (DB06), `0x0801D214 = 1` (DA06/DA07 direct), `0x08017E6E = 1` (F2),
`0x0801B6C2 = 0` (84; the only 0). No reads.

**`+A $1FEA`** writes: `0x0801ACC2 = 0` (finish), `0x080226F2 = 0x1234` (MegaWire screen parks the 68000),
`0x0801FA88 = 0` (init; only if bit 12 was clear and `$1FEA` read `0x1234`). Reads: `0x0801ACB2`, `0x0801BA5E`
(dispatch), `0x0801FA36` (init), `0x080226C0` (MegaWire screen), and **new** `0x08020BF2`, `0x08020C00`,
`0x08020C0E`, `0x08020C1C`, `0x08020C2A`, `0x08020C38`, `0x08020C46` (fatal halt: one byte of "WE SUX" per poll, then
`0x0801FCC8` resets the MCU).

**`+C $1FEC`** writes: `0x0801ACD8 = 0` (after the tick), `0x0801FA40 = 0` (init). Reads: `0x0801ACCA`, `0x0801B712`.

**`+E $1FEE`** writes `0xAF5B`: `0x0801B6AA` (84, after `delay(9,600)` at `0x0801B6A2` = 0.1 ms), `0x0801B688`
(85), `0x08020E06` (heartbeat fatal), `0x08020EB4` (watchdog fatal). Reads: `0x0801F612`, `F632`, `F74A`, `F772`,
`F7C6`, `F840`, `F860`, `F890` (OTA program/erase: DQ7/DQ5 polling after a flash read).

**`+10 $1FF0`** writes: `0x0801FA20 = 0x8000` (init); `0x0801D406 = 0` then `0x0801D42A = (dst & 0x1FFF) | 0x8000`
(`0x9800`, each Z80 packet); `0x0801D516 = 0` (port-5 stop).

**`+12 $1FF2`** writes:
- `0x0801FA26 = 0x8000` (init);
- `0x0801D3DE = 0` (DB06 entry: stop), `0x0801D500 = 0` (port-6 stop, called first in every DA07);
- `0x0801C30A = 0x8000` (DA07 prelude), `0x0801D238 = 0x8000` (DA06/DA07 direct start), `0x08017EBA = 0x8000` (F2),
  `0x08019082 = 0x8000` (AF/B1 flush), `0x0801D44C = 0x8000` (DB mode 3; never posted);
- `0x0801D488`, `0x0801D48A = 0xC002` (DB06 start, written twice); `0x0801D4C6 = 0x4000` (DB06 of at most 0x78
  words: first chunk is the last);
- `0x0801D582 = 0x4002` (refill, more to come), `0x0801D548 = 0x4000` (refill, last chunk): both from EXTI 12;
- `0x0801B6EA = 1`, `0x0801BE84 = 0` (82; never posted).

**`+14 $1FF4`** writes `0x200 | addr[22:16]`: `0x08017EB0`, `0x08017EB4` (F2, same entry twice), `0x0801906C`
(AF/B1 loop), `0x0801D230` (DA direct).

**`+16 $1FF6`** writes `1` (clear): `0x08018FD2` (AE), `0x0801900C` (AF/B1), `0x08019426` (B0), `0x08019752` (C6 init),
`0x0801D216` (DA direct), `0x0801D46C` (DB06), `0x08017E70` (F2). Writes `addr[15:0] & ~1` (push): `0x08017EB2`,
`0x08017EB8` (F2), `0x08019076` (AF/B1), `0x0801D236` (DA direct).

**Write order per post** (from `seq.tsv`, the chip runner; helper writes shown as the word they store):
- DB06: `$1FE6 = 0x2008` (entry), `$1FF2 = 0`, `$1FF6 = 1`, `$1FE4` bit 8 off, `$1FE8 = 1`, `$1FF2 = 0xC002` x2,
  [`$1FF2 = 0x4000` if at most 0x78 words], FIFO-B DMA of the first chunk, `$1FEA = 0`, `$1FE6 = 0xA008`.
- DA07 (type-0x80 source): `$1FE6 = 0x2008`, `$1FF2 = 0` (`0x0801D500`), `$1FF2 = 0x8000` (prelude), `$1FE8 = 1`,
  `$1FF6 = 1`, `$1FE4` bit 8 off, `$1FF4 = 0x200 | a[22:16]`, `$1FF6 = a[15:0]`, `$1FF2 = 0x8000`, `$1FE4` bit 8 on,
  `$1FEA = 0`, `$1FE6 = 0xA008`.
- DA02: `$1FE6 = 0x2008`, `0x6008` (job queued), `$1FEA = 0`, `0xE008`, later `0xA008` (job done). No stream write.
- 84: `delay(9,600)`, `$1FEE = 0xAF5B`, `$1FE4 &= ~0x18`, `$1FE8 = 0`, RAMDP `$0006 = $8200`, watchdog disarmed,
  finish (checked: `0x0801B69E-0x0801B6D6`).
- AF/B1: `$1FF6 = 1`, `$1FE4` bit 8 off, pushes last-to-first, load count 0, `$1FF2 = 0x8000`, `$1FE4` bit 8 on.

### 3.3 Every game access (checked in our reads audit and this page's listings)

| reg | access | sites | what the game does |
|---|---|---|---|
| `$1FEA` | write post (word) | `$B43B8` (in `$B43A0`), `$B4394` (in `$B4344`) | both wait for bit 15 clear first; neither waits for the reply |
| `$1FEA` | read bit 15 | `$B4362`, `$B43B2` (every post); `$47B68`, `$55C06`, `$831F2`, `$98F28`, `$B5862` (before its own DMA descriptors); `$B41A4`, `$B422E`, `$B4536`, `$B61D4`... (job waits) | spin, **no timeout** |
| `$1FEC` | write `0x9494` | `$010E84` only, once a frame from frame 190, VDP line 225 | the music clock |
| `$1FE4` | whole word | `$BCA22` (in `$BC944`), once, after C6 | bit 6 -> model F; `& $700`, bits 9/10 -> models |
| `$1FE4` | bit 2 | `$7F46E`/`$7F486`, `$9DA96`, `$B41C0`/`$B41D6`, `$B4272` | wait while set, up to 65,534 loops (~0.5 s), then read the window anyway |
| `$1FE6` | bit 14 | `$B41B4`, `$B423E` (DA), `$B4574` (C6), `$B61DA`/`$B62D0`/`$B6340`/`$B64E4` (saves), `$7F416` (streamer skips the frame), `$34E28` (zoom fallback) | wait / skip |
| `$1FE6` | `& $300` | `$B61EA`, `$B62E0`, `$B6350`, `$B64F4` | save fails if set |
| `$1FE6` | bit 3 | `$8006A`, `$9D2DC` | song queue, music-pulse colour |
| `$1FE6` | bits 0-2, 4, 5 | 21 + 24 sites | MegaWire UI (status 0 with MegaWire Off) |
| `$1FE0/2/8/E`, `$1FF0-$1FFE` | none | static + census | - |

The boot page reads no register (checked in the boot spec's listing).

### 3.4 The `$1FE4` composer (the Console option stands in for the cart's sensing)

- **68000 read of `$1FE4`** = bit 2 `busy` (section 7) | bit 6 `opt_unknown` | bits 8-10 `opt_model`; every other bit 0.
  - Rule from the project plan (B Jam's decision of 2026-10-10): each real console shows its own Boom Box picture, so
    the game never sees the chip's `0x46F8`/`0x66F8`; 0.3.0 keeps `0x0004 | model` (checked in the code and by B Jam
    on hardware).
  - At `$BCA22` busy is 1 (no stream yet; first DB06 at frame 174), so the word equals 0.2.6's (checked: census frames).
  - The chip's bit 8 ("armed") would collide with the model bits; the composer hides it (checked in our reads audit).
  - Bits 3-5, 7, 11-15: the cart's 68000 view is not known; the game reads none of them (checked). Our rebuilt
    MegaWire page A must not depend on `$1FE4`.
- **MCU read of `$1FE4`** = the stored MCU word (the heartbeat tests bit 11) (checked: `0x08020DFA`).
- **Source of the model bits:** `paprium_opts` in `core_top.sv` (`opt_model`, today synchronised into the MCU clock as
  `mcu_opts_s`) (checked). The new core feeds the composer straight from it. The bits are live, as B Jam decided (no
  latch); the game reads them once (checked).
- **Cart:** how it senses Genesis 3, Nomad and Mega Jet is not known (candidates: VCLK, EDCLK, /YS, SL1/SR1, /M3; web
  sources, inferred). A real-hardware port would put the sensing rule here.

### 3.5 Reset values, byte lanes, ownership, ordering

- **Reset (ours):** every register 0 on core reset (power-on and Soft Reset), so `$1FEA` bit 15 = 0, `$1FEA != 0x1234`,
  `$1FE6` bit 12 = 0, window off, `mini_view = 0`, stream invalid (busy 1). (Checked: the requirements come from app
  init `0x0801F9F8-0x0801FA88`; the cart's power-on values are not known beyond those constraints.)
- **MCU-only reset:** on the cart the registers survive it (the warm path finds `0x1234`; inferred, `0x0801FA36`). Ours
  has no MCU-only reset in play; if the MegaWire code's exit needs one, the register file must not be reset by it
  (proposed).
- **MCU side:** 16-bit registers at the chip offsets; halfword stores (byte enables `0011`/`1100`) and byte stores
  honoured per lane (proposed). The chip only uses `strh`/`ldrh` (checked).
- **68000 side:** writes land only at `+A` and `+C`, always as the whole word (question Q2, as RAMDP; built,
  `paprium_regfile.sv`; was "per lane" in this draft); writes elsewhere are ignored (checked: the game writes nowhere
  else). Any 68000 write to `+A` (either lane) raises mailbox B; to `+C`, mailbox A (checked: the game uses word writes
  only).
- **Same-clock collisions:** a 68000 write and an MCU write to `+A` in one clock: the 68000 value is stored and the
  IRQ set wins over an ack (0.2.6 `mbx_irq` rule) (proposed). Cannot happen in normal play (the 68000 waits for bit 15).
- **Ordering:** one clock domain, MCU writes applied in program order, no posting buffer that reorders. The 68000 must
  never see `$1FEA = 0` with `$1FE6` older than the chip wrote before it (checked: the order, finding 11).
- **68000 read path:** same timing and clock crossing as today's RAMDP read (`paprium_cart_data` into the
  `cart_data` register in `cartridge.sv`); static timing analysis covers it (proposed).

---

## 4. Board-layer register map (closes the register-map gap of our study notes)

Every chip register write and port access, and what our board does with it. Our firmware writes the register file at
`0x0B000000 + offset` (proposed) exactly as the chip writes `0x68040000 + offset`; side effects are RTL unless marked
"firmware".

| chip write | value | cart FPGA (how known) | 0.2.6 | **new-core board** |
|---|---|---|---|---|
| `+4 $1FE4` | any | stored control word; 68000 view replaced (checked); bits 3/4, 8, 11, 13, 14 have not known FPGA effects (bit 14 may be the 68000 run line; inferred, our study notes S-B08) | RAMDP word written by firmware | **store only.** No side effect. Bit 14 not wired in the new core (decision F-D2). |
| `+6 $1FE6` | any | passed to the 68000 (checked) | RAMDP word | **store only.** |
| `+8 $1FE8` | 1 | window on (inferred) | `sdram_en = 1` at reset and at 81 | **`window_en := 1`** |
| `+8 $1FE8` | 0 | window off, maybe view switch (inferred) | 84: `sdram_en = 0` | **`window_en := 0`, `mini_view := 1`** |
| `+A $1FEA` | 0, `0x1234` | stored (checked) | `reg_cmd = cmd_resp` | **store**; no IRQ; **clears the busy guard** |
| `+C $1FEC` | 0 | stored (checked) | none | **store only.** |
| `+E $1FEE` | `0xAF5B` | not known; written only when the MCU stops serving the 68000 (84, 85, fatal) (checked) | none | **store; `window_en := 0`, `mini_view := 1`** (a superset: nothing after it reads the window in normal play) |
| `+10 $1FF0` | 0, `0x8000`, `0x9800` | FIFO-A target (checked: the values; inferred: the auto-increment) | none | **store only.** Firmware writes the packet into RAMDP at `target & 0x1FFF`, +2 per halfword, in the chip's order. |
| `+12 $1FF2` | 0 | stop / flush (inferred) | none | **`stream_valid := 0`** (busy 1); clears the busy guard |
| `+12 $1FF2` | `0x8000` | start the decoder on the queue (inferred) | none | **`stream_valid := 0`**; clears the guard. Firmware decoder hook: if the queue is not empty, decode it (pop order) into the scratch, then **GO** (pointer, length). Empty queue: stream stays invalid. |
| `+12 $1FF2` | `0xC002` | start a FIFO-B stream, refills on (inferred) | none | **`stream_valid := 0`**; clears the guard. The first FIFO-B chunk hook GOes (below). |
| `+12 $1FF2` | `0x4002`, `0x4000` | next chunk / last chunk (inferred) | none | **store only** |
| `+12 $1FF2` | `1` (82) | not known; never posted | none | **store only** |
| `+14 $1FF4` | `0x200 \| a[22:16]` | queue entry high half; `0x200` not known (checked) | none | **store**; latched as the next entry's high half |
| `+16 $1FF6` | `1` | clear the queue (inferred) | none | **queue := empty** |
| `+16 $1FF6` | even `a[15:0]` | push `{a[22:16], a[15:0]}` (inferred) | none | **push** (stack, 16 deep (proposed); the chip caps a frame at 15 loads, F2 pushes 2) |
| FIFO-A port | halfwords | into RAMDP at the target (checked) | none | firmware RAMDP stores (no RTL) |
| FIFO-B port, first chunk | DMA of up to 0x78 words from SDRAM `0xC01EA800 + src` | into the read FIFO (checked) | none | firmware hook **GO**: pointer = our workspace + `src`, length = the whole stream in words |
| FIFO-B port, refills | 0x40 words on EXTI 12 | (checked) | none | never happens (no EXTI 12) |
| RAMDP byte view `0x68860000` | reads | (inferred, strongly) | none | alias `0x02800000` (proposed) |
| flash byte view `0x6C800000` | reads | (checked) | none | alias `0x04800000` (proposed) |
| flash word view `0x6C000000` | reads; OTA writes | (checked) | `ADDR_FLA` | same; OTA inert |

Board-only registers (no cart counterpart) (proposed):

| name | where (proposed) | what |
|---|---|---|
| stream pointer | FPGAIO slot 2 (today's `sdram_ptr`) | window start in the SDRAM workspace, 21-bit byte offset |
| stream length / GO | FPGAIO slot 7 | write N > 0: remaining = N words, `stream_valid := 1`, guard cleared; write 0: `stream_valid := 0` |
| Pocket menu open | GPIO input bit 24 (from `inmenu_sys_s`, `core_top.sv:743-754` (checked)) | firmware gates the watchdog; the music mute is RTL, switched on by the firmware at boot (CTRL.MENU_MUTE_EN, docs/ALLOWLIST.md row B7) |
| Console region | one bit in the MCU option word (from `opt_jap` / `cfg_jap` in `core_top.sv` (checked); today's option word has no region bit (checked: `paprium_cart.sv:211`)) | the board boot picked the header letters `$1E0-$1E2` by region (docs/BOOT_SPEC.md BOOT-07); dropped 2026-10-16 (the letters are the cart's): no firmware reads the bit |
| MEI cause / acks | the cause register of the firmware's interrupt design | mailbox B (existing latch), mailbox A (new), CPU MATE (buddy) SEND |
| TEST counters | FPGAIO, TEST build | 84 post -> window-off time; busy-poll counts (tests R8, R9 in 15.2) |

**Proof wording for the new core** (a fix from our completeness review): "68000-visible `$1FE4` = `0x0004 | model` at
the console read, for every Console setting", not "bits = chip". The MCU-side words are compared with the chip
(docs/ALLOWLIST.md row B10).

---

## 5. The `$C000-$FFFF` window

| rule | how known | 0.2.6 | new core |
|---|---|---|---|
| A read FIFO: each read takes the next word, whatever the address. The streamer `$7F490` reads `move.l (a0)` 16 times from `$C000` and expects 16 different longs. | (checked in the code) | `stream_ptr` ignores the address (checked: `paprium_cart.sv:104-127`) | keep |
| Range `$C000-$FFFF`; the game splits loads over 16 KB into pieces that each start at `$C000` (`$B427C-$B42AA`) | (checked) | `cpu.addr[23:14] == 3` | keep |
| Reads in play are 68000 words and VDP DMA (134,048 68000 word reads, 0 byte reads, solo census) | measured (GPGX) | - | a byte read pops one word, like the FIFO (inferred) |
| A 68000 long read = two words, high word first | (checked: 68000 bus order) | per word | per word |
| Writes do nothing | (inferred) | ignored | ignored |
| Off at power-on | inferred: the 'SE' fallback reads `$C000-$CFB1` as ROM; web sources: dirty contacts give the mini-game | **on** at reset (`ppm_reset`: `sdram_en = 1`) (checked). Not invisible (corrected in review): the boot text page's DMA reads `$C000-$C01F` at frame 22, so 0.2.6 serves those 16 words from the stream (docs/BOOT_SPEC.md finding 2, AL-07) | **off** (`window_en = 0`): those 16 words come from ROM |
| On at every stream start (`$1FE8 = 1` at DB06, DA direct, F2) | (checked: the writes; inferred: the meaning) | on from reset; 81 sets it again | `window_en := 1` on `$1FE8 = 1` |
| Off at 84 | (checked: the writes; inferred: which write) | 84: `sdram_en = 0` | off on `$1FE8 = 0` or `$1FEE = 0xAF5B` |
| Each stream bounded by its length | (checked: DB06's `a2`; inferred for the decoder) | `a2` ignored | `stream_len` counts down per delivered word; at 0 the stream is invalid (busy 1) |
| What an over-read returns | not known | the next SDRAM words | the next SDRAM words (pointer keeps going) |
| Data source | FIFO B (MCU DMA from SDRAM) or the 0x80 decoder (flash) (checked) | MCU-decoded bytes in SDRAM | same as 0.2.6 (section 9) |
| Pointer advances once per *delivered* word | - | `stream_read_ack_toggle` (checked) | keep |

**First use, measured.** On the solo, duo and stage-04 census routes the first window-enabling post is DB06 at
frame 174, after only 3x 81, C6 and one DA02. The first AF is at frame 280, the first AD at 725 (measured,
`firstposts.py`). So no sprite DMA needs the window before `$1FE8 = 1`.

## 6. The 84 switch (first boot on a blank save)

- **Game** (checked: `$B458C-$B4698`): wait for VBlank; display off; clear VRAM and write a test pattern by CPU writes
  (no DMA); display on; write 2,048 NOPs and `jmp $8200` at `$FF0000`; post `8400` through `$B43A0` (no reply wait);
  `jmp $FF0000`.
- **Chip** (checked: `0x0801B69E-0x0801B6D6`): `delay(9,600 SysTick)` = 0.1 ms at 96 MHz (checked in the boot spec
  review); `$1FEE = 0xAF5B`; `$1FE4 &= ~0x18`; `$1FE8 = 0`; RAMDP `$0006 = $8200`; watchdog disarmed; finish.
- **Deadline** (estimated): the 68000 fetches `$8200` about 1.075 ms after the post write (NTSC), and reads the window
  region later still. Before that it fetches only ROM `$B43BC`-`$B43BE`, `$B4692` and work RAM.
- **Why the chip waits 0.1 ms** (inferred): if the cart switches its whole read key at 84, the 68000 must first leave
  ROM (about 40 cycles = 5 us). Ours changes only `$2000-$7FFF` and `$C000-$FFFF`, so the delay is harmless but not
  needed.
- **The new core:** 84's handler as the chip's, with the delay on the clock-following timer (100 us). Window off and XOR
  off at its `$1FEE` write. Budget: MEI latency + 0.1 ms + a few writes < 1.07 ms, so the latency must stay under ~0.95
  ms. The longest L1 handler of the firmware's interrupt design is 0.32 ms (estimated) -> margin about 0.6 ms. A TEST
  counter measures it (test R9). **Measured (system co-simulation of the first new-core firmware, 2026-10-12):** R9 =
  0.135 ms on the blank-save first boot (pass). L1 entries then ran up to 8.5 ms, all of them AD bodies (the
  co-simulation's "D1 3.5 ms" was an AD body in the same entry). A later change (2026-10-13) moved the
  sprite decodes out of L1, and the game posts 84 on mailbox B through `$B43A0`, which waits for the previous post's
  finish (checked in the ROM, `$B468C`): 84 -> window off 0.115-0.128 ms after the worst AD / D1 / B6 (RV32 model,
  estimated). A made-up 84 on mailbox A in the middle of the worst AD would still miss (0.96 / 1.04 ms model time);
  the game never posts 84 there (docs/STAGE1_PLAN.md risk 5). R9 on hardware stays the test.
- **After it:** the mini-game posts nothing and touches no register (checked). A Soft Reset is a full reboot: window
  off, game view, boot page recopied, so the game boots (the save was written before the 84).

## 7. The busy bit (`$1FE4` bit 2, 68000 view)

| item | rule | how known |
|---|---|---|
| Who drives it on the cart | the FPGA; the chip never writes bit 2 | (checked by a static scan and a run) |
| Meaning | "the window has no data ready" | (inferred: it fits every reader) |
| At rest | 1 | (checked: a 0.2.0 hardware finding, busy must be set at rest) |
| Readers | after DB06 at once (`$7F46E`, `$9DA96`, `$B4272`); after DA07 once the reply and `$1FE6` bit 14 have cleared (`$B41C0`) | (checked) |
| Timeout | 65,534 loops (~0.5 s), then the game reads the window anyway | (checked) |
| 0.2.6 | firmware v2: busy at rest; cleared through the DA/DB reply; raised when the next post's bit 15 shows | (checked: `paprium.c:265-311`), hardware-tested |

**The new core's generator (RTL):**
- `busy = guard | ~stream_valid`.
- `stream_valid`: set by GO (board, section 4); cleared by `$1FF2` writes of 0 or with bit 15 set, by the length
  reaching 0, by `window_en` falling, and by reset.
- `guard`: set when the 68000 writes `$1FEA` with a high byte of `$DA`, `$DB` or `$F2`; cleared by the chip code's next
  write to `$1FF2` or `$1FEA`, or by GO.
  - Why it is needed: our MEI can be held off longer (0.32 ms, estimated) than the game's poll delay (10-15 us,
    estimated). A stale "ready" from the last stream would be read.
  - On the cart the chip stops the old stream within microseconds, so the game sees busy at its first poll (inferred).
    The guard gives the same order of events.
  - A refused post leaves the stream untouched, as on the cart (inferred).
- Effect on the readers: busy is seen set from the post until the new stream is ready, then clear until the stream is
  read out. That is the order the cart gives, and the order v2 gives (estimated). It retires the firmware rule and the
  timer-wheel deadline that docs/ALLOWLIST.md row B2 still describes.
- Cost: two flops, a length counter and the decode of the post's high byte (estimated, a few dozen ALM). The counter
  must hold the longest stream in words: DB06 reaches 0x1000 words (0x2000 bytes, measured in the census), which a
  12-bit counter cannot hold, so at least 13 bits; DA and AF stream lengths are not measured here (test R10 measures
  them in co-simulation). Proposed: 16 bits (corrected in review; the draft said 12 bits). **Built: 21 bits**
  (docs/MCU_INTERFACE.md section 4.5: the whole 2 MB workspace in words). Measured in the system co-simulation: DA07
  GO lengths up to 4,704 words.

## 8. Bit-14 waits and mailbox ordering

- `$1FE6` bit 14 = "jobs queued", written by the chip's status layer; the FPGA passes it through (checked).
- The game spins on it after DA, C6, DF and E0, and the streamer skips a frame while it is set (`$7F416`) (checked in
  the census).
- How long it stays set is firmware (job speed, docs/ALLOWLIST.md row B9). The C6 job holds it for the game's 80 VBlank
  polls, the cart's count 94 that seeds the random numbers (since 2026-10-17, docs/ALLOWLIST.md row B34; counted on
  VSCNT).
- Board duty: ordering only (3.5). Test: R5 (15.2).

## 9. The 0x80 decoder, FIFO A and FIFO B, as the chip drives them

**Decoder queue** (checked: the protocol; inferred: the meanings):
- Clear: `$1FF6 = 1`. Entry: `$1FF4 = 0x200 | a[22:16]`, then `$1FF6 = a[15:0]` (even); `a` points at the block's 0x80
  type byte (DA direct rounds an odd address up: `(a + 1) & 0x7FFFFE` at `0x0801D20A`).
- Start: `$1FF2 = 0x8000`; then `$1FE4` bit 8 = "armed" (MCU word).
- Users: DA06/DA07 with a 0x80 source (one entry; 11 of 11 recorded DA07 sources are 0x80, census); F2 (the same entry
  twice); AF/B1 (the frame's load list, pushed last to first). AE, B0, C6 init and DB06 clear the queue.
- Served last-pushed first, i.e. in load-list order (checked: our comparison harness, finding 2).
- Format (read in GPGX's decoder; GPGX is not cart evidence. The new core's reference is the chip's own 0x80 decoder,
  which it runs from RAM through the veneer at `0x080251B0`): byte `t`; `t >> 6` = 0 literal run, 1 RLE byte, 2 copy
  from one byte back-distance, 3 zero run;
  `t & 0x3F` = length; `t = 0` ends.
- Not known: the meaning of `0x200`; what the decoder does at the end of the queue; what `$1FF2 = 0x8000` does
  with an empty queue (the DA07 prelude writes it before the type check).
- **The new core:** firmware decode at the `$1FF2 = 0x8000` hook (the chip's own unpacker per decision 7, else
  0.2.6's), synchronous, into the SDRAM scratch, then GO. Entries are popped as they are decoded, so the DA07 prelude
  finds an empty queue. The AF reply waits for the decode, as 0.2.6's does (docs/ALLOWLIST.md rows B1 / B4). An RTL
  decoder is a candidate for the synth fit (a decision of the project plan).
- The decode must finish before the game's next VBlank DMA list runs, because the game does not poll busy for sprite
  DMAs (checked: no bit-2 reader near AF). Synchronous decode guarantees it.

**FIFO B** (DB06; also DB mode 3, never posted) (checked in a run and in our study of the cart, at
`0x0801D3AC-0x0801D4CC`, `0x0801D528-0x0801D58A`):
- Stop (`$1FF2 = 0`), clear queue, bit 8 off, window on, `$1FF2 = 0xC002` twice.
- First chunk: DMA of up to 0x78 words from SDRAM `0xC01EA800 + a1`; if the stream fits, `$1FF2 = 0x4000` first.
- Each EXTI 12 (FPGA asks for more): `$1FF2 = 0x4002` and 0x40 more words; the last chunk is marked `$1FF2 = 0x4000`.
- So the real FIFO holds at least 0x78 words (inferred).
- **The new core:** pointer + length into our SDRAM workspace (GO at the first-chunk hook); no EXTI 12; the refill
  path's writes never occur.
- Rejected: a credit-counted FIFO with refill interrupts. Exact register traffic, but a refill held off by a long L1
  handler would starve a VDP DMA, and the cart cannot stall the VDP (an estimated risk).

**FIFO A** (Z80 packet; port 5) (checked): `$1FF0 = 0`, then `$1FF0 = (dst & 0x1FFF) | 0x8000` and a DMA of the packet
(0x40-0xE0 words a frame) into RAMDP from `$1800`. **The new core:** firmware writes RAMDP directly in the same order;
the register file only stores `$1FF0` for the chip-runner comparison.

**DA modes** (checked: `0x0801C2FC-0x0801C694`, `0x0801CBE4-0x0801CBF6`, run):
- Every DA07 (mode 7 only; DA02 and DA06 do not) first stops FIFO B (`$1FF2 = 0`) and writes the prelude
  `$1FF2 = 0x8000`, before it reads the source's type byte.
- Type byte outside 0x80-0x82: refused (error code `7 | mode << 8`).
- DA07 with type 0x80: the direct decoder path above (checked in the code). DA06 with type 0x80 reaches it too (checked
  in a run).
- Other 0x80-0x82 sources (e.g. the DA02 source `0x16AFC8`, type 0x81 (checked)) are MCU jobs (`$1FE6` bit 14). What
  mode 7 streams after such a job is not known: no recorded DA07 uses one (11 of 11 are 0x80).
- DA02 decodes into SDRAM and touches no window register; DB06 streams it later.

## 10. VDP DMA reads through the cart

- Sources the game uses (checked): RAMDP (SAT `$0B00`, the 14-entry upload, zoom stamps `$0200-$09FF`); the window
  `$C000` (sprite blocks, DA07 tiles, DB06 data); ROM `$8000-$817E` (the boot DMA timing test, data never compared
  (checked)); ROM `$BC20-$C01F` (the boot text page at frame 22, window still off on the cart; its last 16 words lie in
  `$C000-$C01F`, docs/BOOT_SPEC.md finding 2).
- The cart cannot stall the VDP; the data must be ready before the DMA starts. For the window that is the busy bit
  (DA/DB) or the synchronous decode (AF) (inferred).
- Ours: window DMA reads come from SDRAM port 1 (14-tick deadline); the new core adds the refresh yield
  (`sdram_yield.sv`, from the project plan). The FM XOR never applies to DMA in practice (no DMA from `$2000-$7FFF`).

## 11. Interrupts to the MCU

| chip EXTI line (handler `0x08015458`, served in this order) | source | chip action (checked) | new core |
|---|---|---|---|
| 12 | FPGA: FIFO B wants a refill | `0x0801D528(0)` | never raised |
| 13 | FPGA: probably console `/VRES` (inferred) | acknowledge only | never raised (the Pocket has no 68000-only reset) |
| 14 | 68000 write of `$1FEA` | mailbox B dispatch (`0x0801AC3C(2)`) | MEI cause bit, existing `mbx_irq` latch (set wins over ack) |
| 15 | 68000 write of `$1FEC` | mailbox A: the tick (`0x0801AC3C(1)`) | MEI cause bit, new latch |

- The chip's lines are edge interrupts with a pending bit; ours are level latches with an ack (the firmware's interrupt
  design). Both merge two writes before service into one; the game never writes twice before service (checked: the
  wait loops).
- 0.2.6: mailbox B polled by the main loop; the latch is used only by the CPU MATE (buddy) glue; `$1FEC` raises
  nothing (checked).
- MiSTer's board layer may raise line 13 on a 68000-only reset; our firmware, like the chip, only acknowledges it
  (checked).

## 12. Console probes the cart must not answer

| probe | game site | the cart | how known | 0.2.6 | new core |
|---|---|---|---|---|---|
| `$A130F3` write, then `$80100` read (anti-SSF2) | `$81186-$811AE` | no bank logic: reads stay identity | (checked) | banking suppressed | keep |
| `$A130EC`/`$A130FC` 'MA' (32X) | `$BCA2C-$BCA3A` | not answered | checked in the code; inferred for the cart | answered only with 32X Mode on (add-on stub) | keep |
| TMSS `$A14000`, `$A14101`, byte `$000120` | `$BC676`/`$BC6BC` (from RAM) | console side; the cart serves `$120` from the boot page | (checked) | TMSS-lite with the Console option | keep |
| Mega CD BIOS ID at `$400100-$40014F` | `$BC944` path | not answered (inferred) | (inferred) | stub per Mega CD unit; with None, the ROM upper half answers (no ID pair) (checked: finding 10) | stub per unit as 0.2.6; **None: not answered (F-D3)**, test R12 |
| any VDP-space read other than `$C0001E` | - | not answered | (inferred) | not answered | keep |
| `$C0001E` 'SE' | `$1D1E` | **answered** (inferred) | (inferred) | patched out (row B3) | keep patched |

## 13. B Jam's decisions built in, and where each lands

| B Jam's decision (2026-10-10) | where | this page |
|---|---|---|
| Header `$1E4 = $FF00` at boot | board boot writes RAMDP `$1E4` (not an FPGA register) | docs/BOOT_SPEC.md; the MCU byte view (2.2) then shows the same header |
| The header letters are the cart's own (the ROM file's), on every Console (B Jam's hold-B videos 2026-10-16: the same US cart prints the ROM header's region letters unchanged in a US and a JP console) | the boot page copy leaves RAMDP `$1E0-$1E3` as the ROM file's; BOOT-07's per-region switch is dropped | docs/BOOT_SPEC.md |
| FM bank unscrambled in the core circuitry, off after 84 | RTL read path | 2.3 |
| 84 switches the window back to ROM within ~1 ms | RTL on 84's writes, made as the chip makes them | 5, 6 |
| Pocket-menu-open bit gates the watchdog and mutes music | board input to the firmware | 4 (board-only registers) |
| Never read out or attack the real cart | - | all evidence is behaviour, code and the widely shared ROM files |

### 13.1 Choices for the new core that this page asks for (with recommendations)

| id | choice | recommendation | why |
|---|---|---|---|
| F-D1 | MCU addresses: register file `0x0B000000 + offset`, RAMDP byte view `0x02800000`, flash byte view `0x04800000`, stream length/GO in FPGAIO slot 7, menu bit on GPIO input bit 24, a Console-region bit in the option word | **Decided (B Jam's decision of 2026-10-11): accept**, freeze with the new core's interrupt/timer registers (the MiSTer rule) | free regions in today's 8-bit decode (checked in `mcu_core.sv`); the A23 alias follows the chip's own view split |
| F-D2 | drive the 68000 hold from `$1FE4` bit 14 (our study notes S-B08) | **Decided (B Jam's decision of 2026-10-11): no** in the new core (its meaning is a guess); revisit with the MegaWire screen in the MegaWire step | the meaning is a guess; today's `md_rst` hold is hardware-tested |
| F-D3 | `$400000-$7FFFFF` with Mega CD = None | ~~keep 0.2.6 and list it~~ **Decided (B Jam's decision of 2026-10-11, "more cart accurate the better"; confirmed again 2026-10-11, "Keep it like the cart"): the cart does not answer there when Mega CD = None**; the console core's open-bus behaviour applies, as on a real console with no Mega CD. With a unit chosen, the unit stubs answer exactly as in 0.2.6. docs/ALLOWLIST.md row B25; test R12 must show the game sees no CD on every Console setting. Built by docs/STAGE1_PLAN.md item C5 | the real cart (inferred) does not drive the expansion range; the tie-off is a few ALM |
| F-D4 | RAMDP byte lanes | **Decided (B Jam's decision of 2026-10-11, docs/STAGE1_PLAN.md question Q2): whole word** - a 68000 byte write stores the byte on both halves of its word. The emulator run reached `$2B83E`: whole word and ignore both pass, per lane fails; the cart's own choice is not known, and B Jam picked whole word ("if anything breaks, we learn we are not cart-accurate somewhere"). Built as docs/STAGE1_PLAN.md item C7; docs/ALLOWLIST.md row B32. (Was: "decision 5 of the project plan, settled by one emulator run".) | unchanged |
| F-D5 | window over-read value | **Decided (B Jam's decision of 2026-10-11): keep 0.2.6** (the pointer keeps going) until test R10 finds a game over-read; if one exists, measure the cart's value on hardware and use it. **R10 found two (2026-10-12, measured in the system co-simulation of the first new-core firmware; reproduced by the review):** the game's VDP DMA reads 128 words past a DA07 0x80 stream at the title load (GO 4,704 words, read to 4,832) and 128 past another during a stage load. The 0x80 format ends at a 0 code and carries no length, so the game's fixed DMA length (0x25C0 bytes) runs 0x100 bytes past the decoded block (0x24C0) (checked in the 0.2.6 decoder; inferred that the length is fixed). So the cart's value must now be measured on hardware (what its decoder serves past the end code) and used; the new core serves the next SDRAM words meanwhile, as 0.2.6. The window keeps serving at the pointer whatever `remaining` says, so that change is firmware-only (checked in `paprium_cart.sv`; inferred) | the cart's value is not known; no visible fault in the co-simulation runs |

## 14. Not known (kept honest)

- Which of 84's writes switches the cart's window or view; what `0xAF5B` does to the FPGA.
- What the cart serves before 'SE', and whether a console Reset returns it to view D.
- The cart's 68000 view of `$1FE4` bits 3-5, 7, 11-15; how it senses the console model.
- The decoder: `0x200`, end-of-queue behaviour, an empty-queue start; the FIFO depth; an over-read's value.
- Bus timing: when busy falls on the cart, reply times, `/DTACK` (analyser captures C3 / C7).
- Whether the cart honours byte lanes in RAMDP (ours: whole word, B Jam's decision on question Q2; the cart's own rule
  stays unknown).
- The 'SE' value's two low bits, the `$91xx` echo, the `$200000` stub (analyser capture C2a).

## 15. Tests

### 15.1 The chip-runner comparison (it must pass for the new core)

- **Reference:** the chip program run in a CPU emulator: our comparison harness's chip side (`replay.py`) for captures,
  and our cart-engine runner (driven by our `trace.py`) for scripted posts. Log every access to
  `0x68040000-0x6804001F`, the FIFO ports and the flash/header views: post index, order, offset, value, read or write.
- **Ours:** the 0.3.0 firmware in the RV32 board rig (`paprium-fw/tests/equiv/rvboard.py`) with a register-file model at
  `0x0B000000` (proposed), logging the same tuple.
- **Inputs:** every post of the solo, duo and attract captures; `synth.py`'s never-posted list (00, 84, E0, F2,
  AC/C1/F0); 82, 85; an EXTI 13 pulse (chip side only acknowledges); the blank-save first boot (E003/E004, 84).
- **Pass:** per post, the same register writes (offset, value) in the same order, and the same values returned to the
  MCU's reads of `$1FE4`, `$1FE6`, `$1FEA`, `$1FEC`. Allowed transforms, and nothing else:
  - T1 FIFO A: compare the RAMDP bytes at the `$1FF0` target after the post, not port traffic.
  - T2 FIFO B: compare (source offset, total length) and the bytes the window serves; drop the chip's EXTI-12 refill
    writes (`0x0801D548`, `0x0801D582`) and chunk DMAs after the first.
  - T3 decoder: compare the decoded bytes in pop order with the chip side's queue (docs/ALLOWLIST.md row B1).
  - T4 board-only writes (GO, pointer): checked by rule (GO follows each stream start), not against the chip.
  - T5 `$1FEE` OTA reads: none on either side (MegaWire update inert).
- **Fails on:** any extra, missing or reordered register write; an MCU read of RAMDP `$1FE0-$1FFF` outside the boot
  hand-off; a 68000-visible `$1FEA = 0` before the `$1FE6` write that precedes it.

### 15.2 RTL unit and co-simulation checks (the new core)

| # | check | pass |
|---|---|---|
| R1 | reset values on power-on and Soft Reset (with a post in flight, cache present and absent) | `$1FEA` bit 15 = 0 at the first post; `$1FE6` bit 12 = 0; window off; busy 1 |
| R2 | composer, every Console setting | 68000 `$1FE4` at `$BCA22` = 0.2.6's word; the model code at `$FF98DA` equals 0.2.6's |
| R3 | MCU reads `$1FE4` | the stored MCU word (bit 11 round trip) |
| R4 | lanes and IRQs | MCU stores per lane; 68000 writes to `+A`/`+C` as the whole word (Q2); one IRQ per 68000 write to `+A`/`+C`; set wins over ack; MCU writes raise none |
| R5 | ordering | randomised 68000 reads during MCU write bursts never see `$1FEA` newer than `$1FE6` |
| R6 | window and view | `$1FE8`/`$1FEE` rules; reads before the first `$1FE8 = 1` return the file |
| R7 | FM XOR | every console read of `$0000-$FFFF` in both states: XOR exactly on `$2000-$7FFF` in "game"; Z80 bytes = the MCU de-XOR'd image of the earlier plan |
| R8 | busy | census replay in co-sim: 0 bit-2 timeouts; 0 polls that see "ready" on a stale stream, with the worst L1 handler injected at every DA/DB post |
| R9 | 84 deadline | TEST counter from the `8400` write to window-off and XOR-off: at least 0.1 ms (the chip's delay) and at most 0.5 ms on every run (estimated budget 0.43 ms); hard fail above 1.0 ms (the sled limit is 1.07 ms). Same pass rule as docs/BOOT_SPEC.md test T-B11 |
| R10 | over-read | per DA07/DB06 in co-sim, words read vs stream length (if any read past it, the over-read value matters) |
| R11 | MCU views | RAMDP byte view and flash byte view return what the chip runner's views return at every address our firmware reads |
| R12 | probes | `$A130F3`+`$80100`, `$A130EC/FC` with 32X off, Mega CD None: game results equal 0.2.6's |

### 15.3 Hardware checks

On the Pocket (B Jam, the new core):
- Boot with each Console setting: the Boom Box picture matches 0.2.6.
- Stage start (DA loads), the shaft/elevator streamer, a zoom: no corrupt tiles, no half-second stalls.
- Blank save: the mini-game draws right and runs 10 s with the watchdog as the chip's; Soft Reset boots the game; the
  mini-game never returns.
- Pocket menu open 10 s, then closed: music muted while open, carries on after; no watchdog halt.
- With the synth: FM patches by ear (track 01 window).

On the real cart (read-only; never a blank save, never a write):
- Hold-B photos on a US and a JP console: the header letters and the `$FF00` space (docs/BOOT_SPEC.md). Done 2026-10-16:
  the letters follow the cart, the last character is a space.
- T7 Reset held at power-on (2/5/15/30 s): a cart-side 'SE' deadline.
- T8 Reset held ~8 s mid-fight: what follows the watchdog halt; with the analyser (C5b), whether `$C000` then reads ROM,
  which would mean `$1FEE` (not `$1FE8`) switches the window.
- Only if the analyser is bought: C2b (the `$1FE4` word per console), C3 (busy and reply timing), C7 (`/DTACK`).

## 16. Rows elsewhere that this page changes

Status 2026-10-13: docs/ALLOWLIST.md rows B2 and B6 were reworded and approved (allow-list review 2026-10-11);
the `pocket_map.h` block was written at the interface freeze (2026-10-11); `fpga_regs.csv` is a study
file outside this tree and still lacks the 7 fatal-path reads (this page's 3.2 is the reference). The original list:

- Allow-list **B2** still describes the firmware v2 busy rule with a timer-wheel deadline; the project plan moved busy
  into RTL on 2026-10-10 (section 7). Its scope also names RAMDP `$1FE4` bit 2, which becomes a register-file bit. For
  B Jam's allow-list review, with docs/BOOT_SPEC.md's proposed rows AL-01..10.
- Allow-list **B6** scopes the option bits as RAMDP bits; they become composer bits (same values).
- `fpga_regs.csv` (study, outside this tree) misses the 7 fatal-path `$1FEA` reads (3.2).
- `pocket_map.h` block (proposed), at the new core's interface freeze: the register file, the two byte-view aliases,
  stream length/GO, the menu bit and the region bit.

## 17. Reruns

All in our working folder, `python -I -B`, counts and booleans only.

| script | md5 (8) | args | result |
|---|---|---|---|
| `xcheck.py` | 237b4db1 | `fpga_regs.csv`, `static.tsv`, `byreg.tsv` | csv = superset of static scan and run, except 1 run-only read site (`0x08020BF2`); 6 more found in our study of the cart |
| `firstposts.py` | f3bc34dc | `posts_{solo,duo,c2}.tsv` | first window-enabling post DB06 @174 on all three; first AF @280, AD @725 |
| `xorwin.py` | 40ceb57a | ROM | 32/32 and 46/48 blocks match P after XOR, 0 as is |
| `upperprobe.py` | b593853e | ROM | 0 of 8 compared Mega CD words carry `BO`/`WO` |

Code listings read (address:length): `chipdis.py 0801B66C:A0 08022C78:50 0801D3AC:200 0801D1F0:60 08017E60:68
08018FC0:20 08018FFC:A0 0801F9F8:A0 08015458:70 0801C2C0:80 0801C670:40 0801CBE4:50 0801C6A6:30 08020B24:160
08020BE4:30 08020DF4:30 08020E8C:34 0801FCC8:14 080226E8:14`; `m68dis.py B4580:60 B4340:80 B45B2:200 7F408:B0 B4190:120
9DA80:40 2B830:50 BCA1C:20 1D10:30 1E20:80 1550:20 BC990:90`.

## 18. What the review changed (2026-10-11)

Every key claim was looked at again at its cited address (chip: `chipdis.py`; ROM: `m68dis.py`, `m68grep.py`) or run
again (`xcheck.py`, `firstposts.py`, `xorwin.py`, `upperprobe.py`, docs/BOOT_SPEC.md's `winpre.py` and `hdrreads.py`).
Held: the 7 fatal-path `$1FEA` reads (56 write and 24 read sites in all), the heartbeat's `$1FE4` read, the status
helper, 84's order and delay, app init, the post routines and the 84 sled, the busy readers and their delays, the DB06 /
DA direct / F2 / AF orders, the DA type dispatch, the EXTI order, the byte-lane self-test, the 'SE' loop and the 0.2.6
boot patches. Changed:
- Finding 9, tables 1.1, 1.3 and 2.1, section 10: the game view above `$8000` is **not** invisible. The boot text page
  DMAs `$BC20-$C01F` in game view, and its data looks like tiles only as is (measured nibble counts), so "file as is"
  there is now inferred, strongly, instead of "invisible". The XOR edge at `$8000` is checked up to `$7DFF` only.
- 5 ("Off at power-on") and 1.3: 0.2.6's window-on-at-reset is not invisible; the text page's DMA reads
  `$C000-$C01F` at frame 22 (docs/BOOT_SPEC.md finding 2). The new core serves ROM there, a listed change against 0.2.6.
- 2.3: the lowest Scum! patch is `$1A9FA`, not `0x0BF040` (checked in `paprium_scum.sv`).
- 2.1: the byte-lane flag `$FF9986` is no longer called an anti-piracy flag (its use is not known).
- 3 (finding 3): what the heartbeat does with bit 11 (the fatal halt `0x400000FB`).
- 7: the busy length counter needs at least 13 bits (DB06 reaches 0x1000 words); 16 proposed.
- Finding 4: the three census routes share one deterministic boot.
- Finding 5: the 1.070 ms sled (docs/BOOT_SPEC.md) and the 1.075 ms post-to-`$8200` time are the same event seen from
  two starting points.
- 4, 13.1: the Console-region bit for BOOT-07 is added to the board-only registers and F-D1.
- 9: the 0x80 format is labelled "read in GPGX's decoder", not "checked"; the chip's own decoder is the reference.
- 15.2 R9: the same pass rule as docs/BOOT_SPEC.md test T-B11 (0.1-0.5 ms, fail above 1.0 ms).
- Finding 10: "the game sees no CD" is inferred (R12 tests it).

## 19. Changes 2026-10-13 (new-core docs)

- 2.1 and 13.1 F-D4: the byte-lane decision is whole word (question Q2), built as docs/STAGE1_PLAN.md item C7; 0.2.6
  as shipped ignores byte writes.
- 3.5 and R4: 68000 writes to the register page are whole word (as built).
- 7: the stream length counter is 21 bits as built.
- Finding 6, 6, 4: the L1 lengths measured in the system co-simulation of the first new-core firmware (the plan's
  0.32 ms was estimated).
- F-D5: R10 found two 128-word over-reads; the cart's value now needs a hardware measurement.
- 16: status of the rows this page asked other files to change.
