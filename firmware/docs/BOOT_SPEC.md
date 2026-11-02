# Boot spec: power-on and reset (0.3.0)

The power-on and reset behaviour that our new-core boot code (firmware start-up) and board layer (RTL reset, 68000
hold, register-file reset values, window and FM view) implement. Written 2026-10-11 as a deliverable of the project
plan ("Cart FPGA and bootloader") and checked claim by claim against the ROM, the cart chip's program and the cited
notes in a separate review (what the review changed: section 12). Companion: `docs/CART_FPGA_SPEC.md`
(the registers themselves), `tests/equiv/allowlist.json`, `docs/CENSUS.md`.

**How we know.** Where it matters, a statement says how it is known: "measured" (counted in a run or read from a
file), "estimated" (arithmetic on measured numbers), "not known" (nobody knows), "checked" (verified in code or a run),
"read in the code" (read only), "inferred", "web source".

**Sources.** The ROM (md5 91ccdc0b) and the cart program, read in place. Our study notes (the S-xxx ids below are
their rows). "0.2.6" means the final 0.2.6 firmware (`legacy/026/paprium.c` here, byte-identical build) and the final
0.2.6 RTL. Census = our GPGX watch runs made before the new-core work (solo, duo, menu tours; GPGX runs the real boot
page and game code, its cart MCU is a model). Evidence and reruns are in our working notes.

**Two different "first boots".** *Blank-save first boot*: no valid save, the game ends in 84 and the mini-game (section
4). *Bank-cache first boot*: the boot overlay's WavPack unpack of the cart's sound bank while the 68000 is held (section
1, step P2). This spec says which one each time.

---

## Findings first

1. **The JP options follow the console already. They do not need the cart's header letters.** (Checked in the code.)
   - The game reads the console's version register itself: `$BCA04-$BCA0C` sets model-word bit 11 when `$A10001`
     bit 7 is 0 (a Japanese console), and `$8103E` stores that word at `$FF98DA`.
   - Every JP-feature site (`$81134`, `$7C6E6`, `$975F4`, `$8930E`; `$36212`, `$36CDC`, `$4A702` alone) tests that
     bit, ORed with "`$1E0` is a lone 'J'". One more, the language default at `$80F3A`, runs before the decode, so on a
     cold boot it sees only the letter (checked); which text a player sees first is not known.
   - So B Jam's US cart in his JP LaserActive gives JP options with no change to the header. It does not show that the
     cart rewrites the letters. Our core already sets the version register from the Console setting (0.2.6
     `paprium_opts`), so JP features follow the Console setting today.
   - The letters only change the hold-B line (and turn JP features on everywhere if the first letter is a lone 'J').
     **Settled 2026-10-16 (B Jam's hold-B videos, measured):** the same pink US cart prints the ROM header's region
     letters unchanged in a US CDX and in a JP LaserActive, so the letters belong to the cart, not the console.
     BOOT-07's per-region switch is dropped; the line shows the ROM file's own digits and letters (since 2026-10-17).
   - Correction to the study: "`$FF98DA` bit 3" is the JP-console bit, not a game flag.

2. **0.2.6 opens the `$C000` window at reset. The cart keeps it closed until the first stream, and one boot read lands
   in it.** (Measured and checked.)
   - The boot page's text splash DMAs ROM `$BC20-$C01F` to VRAM `$1000` (PC `$167A`, frame 22). Its last 16 words are
     inside the window range.
   - In 4 of 4 census runs this is the only access to `$C000-$FFFF` (16 words, nothing else) before the first stream
     post (DA02 + DB06, frame 174).
   - 0.2.6 sets `sdram_en = 1` in `ppm_reset`, so those 16 words come from the stream at pointer 0 (stale SDRAM after a
     Soft Reset). The cart serves ROM there (inferred, strongly). The new core serves ROM.
   - Which ROM view: this DMA runs after the 'SE' point, so it is a game-view read of `$BC20-$C01F`. Its data looks
     like tiles only as is (410 of 2,048 nibbles 0 as is, 67 after XOR 0xA8A2; counts measured in the review), so the
     cart serves the file as is there (inferred, strongly). docs/CART_FPGA_SPEC.md finding 9 builds on this.
   - Whether the tile (VRAM `$13E0-$13FF`) is on screen: not known.

3. **The game reads very little cart state before its first post.** (Measured in 4 census runs.)
   - In `$0100-$01FF` only `$01E4` (splash, frame 21) and `$01E0` (region test, frame 169).
   - In the register page: `$1FEA` first at the first post's wait (PC `$B43B2`, frame 169), `$1FE6` in the C6 wait
     (frame 169), `$1FE4` once for the console model (PC `$BCA22`, frame 173).
   - So what must be right at the release is short: the boot page with its patches, `$1E0-$1E5`, `$1FEA` bit 15
     clear, `$1FE6` bit 12 clear, the `$1FE4` model bits, window off.

4. **`$1E4 = $FF00` changes one visible thing: the hold-B line ends in a space, not 'S'.** (Checked.) The other three
   readers (`$152E` splash, `$9234E` text id, `$B8ADC` palette) treat `$FF00` and the ROM file's `$2020` alike.

5. **Every reset type must reset the 68000 hold and the register file.** (Checked by reading the RTL; measured in
   simulation, as a finding of the project plan asked.)
   In 0.2.6 the hold and window bits (`fpgio` ctrl) reset only at FPGA configuration. After a Soft Reset the paused game
   resumes for 0.65-0.92 ms (~90 %) or restarts on the old RAMDP (8-11 %) before the reset envelope catches it.

6. **84 has a hard 1.07 ms deadline and no reply wait.** (Checked; the times are estimated.) The game posts 8400 and
   jumps straight into a 2,048-NOP sled in work RAM (`$B468C` -> `$FF0000`). The sled is 1.070 ms (8,204 cycles);
   counted from the post write it is about 1.075 ms (8,244 cycles, docs/CART_FPGA_SPEC.md finding 5); then the 68000
   runs `$8200`. An interrupt during the sled only makes it later. The chip acts after its 0.1 ms delay.

7. **On ours the mini-game has exactly one way in: the blank-save 84.** (Checked.) The 'SE' fallback is unreachable with
   the boot patches. No chip path writes `$8200` except 84. Every Scum! patch address is at or above `$1A9FA`, so Scum!
   cannot touch the boot page, the 'SE' code, the window range or the FM bank.

8. **Ten allow-list rows are proposed** (section 8). Today's list has only docs/ALLOWLIST.md rows B3 (boot patches), B6
   (option bits) and B7 (menu) for this area.

---

## 1. Power-on to the game's first post

One table for every reset type (section 6 says what differs). "Board" = our RTL + firmware start-up.

| # | step | evidence | 0.2.6 today | new core |
|---|---|---|---|---|
| P0 | Reset asserted. The 68000 is held; the register file, window, FM view and mailbox latches take their reset values. | cart: how it keeps the 68000 off RAMDP at power-on is not known (analyser capture C1, section 10) | Console reset envelope (`md_reset`, `sys_reset`); the MCU hold bit is not reset (configuration value only) | Hold reset value = held, applied by every reset type (BOOT-01). Register file all 0 (BOOT-08..11). |
| P1 | MCU start-up: crt0 (stack, `.data`, `.bss`), board init. | chip: the bootloader sets clock, flash wait states, VTOR (checked: absent from the app) | crt0 + `main` + `ppm_reset` | Our crt0; no bootloader; clock values from the build-time clock (BOOT-15). |
| P2 | *(sound-cache firmware only)* bank-cache check; on a bank-cache first boot the WavPack unpack (26-30 s, bar). | the firmware's interrupt design (estimated) | none (album) | Not in the first new-core firmware. When it lands it runs here, 68000 still held, watchdog not armed, so the C6 timeout cannot fire. |
| P3 | Boot page copy ROM `$0000-$1FDF` -> RAMDP. | the page is not in the flash chip (checked on hardware); its source on the cart not known | `memcpy` 8,192 B incl. `$1FE0-$1FFF` | 8,160 B; `$1FE0-$1FFF` is the register file (BOOT-04). |
| P4 | Boot patches, ROM patch, header. | the 0.2.6 boot patches (checked) | 4 RAMDP words + ROM `$81104`; header left as the ROM file (`$2020`) | Same patches (BOOT-05); `$1E4 = $FF00` (BOOT-06); the letters stay the ROM file's (BOOT-07 dropped 2026-10-16). |
| P5 | App init (the chip's routine at 0x0801F980, done as the chip does it): reads the hand-off block, `$1FE6` bit 12, `$1FEA`; writes `$1FE4`, `$1FE6`, `$1FEC`, `$1FF0`, `$1FF2`. | (checked) | none (`ppm_reset` writes `$1FE4 = 0004\|model`, `$1FE6 = MegaWire option`, `$1FEA = 0`) | App init as the chip does it (BOOT-14), then the board writes the MegaWire option status into `$1FE6` bits 0-2 (the first new-core firmware only; with the MegaWire code, MW init runs as the chip's does). |
| P6 | Interrupts on, stale mailbox latches cleared, then **release** (last step). | (inferred) | `ppm_md_rst(0)` after `mdp_init` (unbounded wait) | BOOT-02, BOOT-03. |
| P7 | 68000 at `$200`: SR `$2300`; TMSS 'SEGA' if the version nibble is not 0; Z80 bus; SSP; clears `$FF0000-$FFFFFD`; `jmp $1504`. A console Reset (ports already set up) skips the TMSS/Z80 part but still clears RAM. | (checked, `$200-$268`) | same | same |
| P8 | `$1504`: `$1F86` (run-once constructors), `$1D42`: VDP registers, clear CRAM/VSRAM/VRAM. | (checked) | same | same |
| P9 | `$1E28` 'SE' loop: up to 60,001 reads of `$C0001E`; needs `(word & $FFFC) == $5345`; on a hit writes `$9100` there. No hit -> `jmp $8200`. | checked; 198 cycles a try, 1.55 s worst case (estimated) | patched: reads VDP status `$C00004`, test inverted, passes on try 1 | same as 0.2.6 (BOOT-05) |
| P10 | `$1E4E` stub copy: 182 words `$200000` -> `$FF1100`, each word echoed as `$91hh`, `$91ll`; then `$91FF`, `$9100`; VBlank wait; pad ports. | (checked) | runs; the echo lands on VDP register 17 (ends at 0); the copy holds whatever the core serves at `$200000` | same |
| P11 | `$158A` Z80 reset and clear (twice; the `$AFA5` skip at `$1526` is never true after `$200`). | (checked) | same | same |
| P12 | Splash: `$152E` reads `$1E4`. `$FF00` or `$2020` -> text page `$15D2` (147 NTSC frames, estimated); else logo `$18AA`. The text page DMAs ROM `$BC20-$C01F` to VRAM `$1000`. | checked; DMA measured in the census, frame 22 | text page; DMA tail reads the open window | text page; DMA tail reads ROM (BOOT-12) |
| P13 | `$154C`: `$FF5880 = $AFA6`, `$FF5882 = 0`; `$1560` `jsr $FF1120` (the stub must jump into the game and never return). | checked; stub content not known | patched to `jsr $10100` | same as 0.2.6 |
| P14 | Game `$B4468`: 810E x 3, each waiting for `$1FEA` bit 15 clear **with no timeout**; then C600 + 14 words; then one poll a frame while `$1FEA` bit 15 or `$1FE6` bit 14 is set; count from 14, give up past 960 (15.8 s) -> error screen. The count seeds the random table. | checked; frame 169 (measured in the census) | reg_cmd = 0 at reset | register file `$1FEA` = 0 at reset (BOOT-08); since 2026-10-17: the C6 job holds `$1FE6` bit 14 for the game's 80 polls (count byte 94, the cart's; see docs/ALLOWLIST.md, row B34; core/dispatch/jobs.c) |
| P15 | `$80F40` language default from `$1E0` (model word not decoded yet). `$81012` hold-B check. `$81038` model decode: `$1FE4` read once (`$BCA22`), version register -> bit 11, VDP PAL bit -> bit 10. | checked; frame 173 (measured) | `$1FE4 = 0004 \| model` | same composition (BOOT-10) |
| P16 | First stream DA02 + DB06 (frame 174); first 9494 (frame 190); 8802 (192); A400 at 240; with B not held also the terminal's A48x (A480 in GPGX at 386; correction 2026-10-16, from B Jam's hold-B videos: held B skips the A48x at `$97798`, not the boot A400). | measured in the census, GPGX | window already on | window turned on by the first stream start (BOOT-12) |
| P17 | Intro (no input): text page, NX TERMINAL (ROM / SRAM / MODEM / SUB-CPU status), WaterMelon logo, then the scaled tech-logo sequence (Datenmeister, 80MHDC, **MegaWire 4.0**, EXPS, SCALR, NEURAL ...), then the PAPRIUM title. **The "MegaWire 4.0" logo is the game's own credit screen, not a MegaWire status: it shows with MegaWire Off and "MODEM NONE" on the terminal, and B Jam's original cart shows it with no MegaWire attached** (section 13). | measured in a co-simulation (the firmware on a simulation of the RTL), frames 740-1100; seen by B Jam on hardware 2026-10-13 | same | same |

---

## 2. Rules

Each row: the rule, its evidence, what 0.2.6 does today, what the new core does.

### 2.1 Hold and release

| id | rule | evidence | 0.2.6 today | new core |
|---|---|---|---|---|
| BOOT-01 | The 68000 is held from the first cycle of every reset until the board releases it. The hold's reset value is "held" and every reset type applies it. | the 68000 must not run before RAMDP holds the boot page (inferred); cart method not known | `fpgio` ctrl[0] = 1 only at configuration; `ppm_reset` sets it as its first action; old game runs briefly after a Soft Reset (a finding of the project plan, measured in simulation) | Reset value 1 on power-on and on `sys_reset`; the firmware still writes it first. 0-1 ALM; ctrl[0] is a marginal crossing, so the change needs the fit's sweep over fitter seeds. Built (docs/STAGE1_PLAN.md item S1, `shell_reset` holds from the reset's first clock): with the menu closed one bus cycle the 68000 was already starting may still start, within 0.25 us, never a write (test T-B7 as worded 2026-10-13). |
| BOOT-02 | The release is the last step. Every wait before it is bounded. | a finding of the project plan (checked) | `mdp_init`'s EverDrive FIFO wait has no timeout, before the release | Bounded (the album shim, while it exists); on a timeout release anyway, flag it. TEST builds count milestones (MCU reset done, 68000 released, first post seen, C6 seen) into the save's debug area. |
| BOOT-03 | No post from the previous session survives. Mailbox latches (`$1FEA`, `$1FEC` interrupts) are cleared by the reset and again just before the release. | (inferred) | `$1FEA` polled; the 0.2.6 latch is in `paprium_cart` | Latches reset by every reset type; cleared before interrupts are enabled. |

### 2.2 Boot page, patches, header

| id | rule | evidence | 0.2.6 today | new core |
|---|---|---|---|---|
| BOOT-04 | Copy ROM `$0000-$1FDF` into RAMDP on every reset type, from the ROM image. Never copy ROM `$1FE0-$1FFF` into anything the 68000 reads there. | a cartridge reader sees the ROM file's bytes at `$0000-$1FDF` outside the header (checked in our study notes); the 68000 sees registers at `$1FE0-$1FFF` (checked for the chip) | 8,192 B copied, then three words overwritten | 8,160 B; the register file answers `$1FE0-$1FFF`. |
| BOOT-05 | Apply the 0.2.6 boot patches before the release: RAMDP `$1D1C = $0004`, `$1D2C \|= $0100`, `$1562 = $0001`, `$1564 = $0100`; ROM image `$81104 = $4E71`. docs/ALLOWLIST.md row B3. | (checked) | yes, every reset | Same, every reset type (idempotent on the ROM image). Option for later, only after an analyser capture (C2a, section 10): answer 'SE' and serve our own stub in RTL; not in the first new-core firmware. |
| BOOT-06 | RAMDP `$1E4-$1E5 = $FF00`. | both real sources hold `$FF00` (checked in our study notes); B Jam's decision of 2026-10-10: yes | `$2020` (the ROM file's edit) | `$FF00`. Visible change: hold-B line ends in a space. |
| BOOT-07 | **Dropped 2026-10-16** (B Jam's hold-B videos: the letters belong to the cart). RAMDP `$1E0-$1E3` and `$0100-$01DF` stay as the ROM file's; no Console setting changes them. Was: `letters[region]` by the Console region (option word bit 25, which no firmware reads now). | B Jam's decision of 2026-10-16; finding 1 (checked); B Jam's hold-B videos (measured) | the ROM's letters | the ROM file's letters (core/boot/bootpage.c, since 2026-10-17) |

### 2.3 Register page at the release

The 68000 view of `$1FE0-$1FFF` is the register file (docs/CART_FPGA_SPEC.md). While 0.2.6 modules remain, their
writes to the RAMDP struct fields `reg_status_1`/`reg_status_2`/`reg_cmd` (`$1FE4`/`$1FE6`/`$1FEA`) must land in the
register file (the board register map). Values at the moment of the release:

| id | rule | evidence | 0.2.6 today | new core |
|---|---|---|---|---|
| BOOT-08 | `$1FEA = 0`. Bit 15 must be clear: the first post waits on it with no timeout. Never `$1234`. | checked (`$B43A0`, app init 0x0801FA36) | `reg_cmd = 0` in `ppm_reset` | Register reset value 0; nothing writes it before the release. |
| BOOT-09 | `$1FE6` bit 12 = 0 (no "boot into the MegaWire screen", job 12). Bits 0-2 = MegaWire status. | app init 0x0801FA06-0x0801FA74 (checked); who sets bit 12 on a cart is not known | `opt >> 16` = 0 or 7, bit 12 always 0 (checked) | Reset 0; app init leaves `$4000`, then `$C000`; the board then writes the option status into bits 0-2 through the same shadow the status helper uses, so later status writes keep them (the first new-core firmware; with the MegaWire code, MW init as the chip does it). Bit 14 at the release is harmless: the first `$1FE6` read is ~2.8 s later. |
| BOOT-10 | `$1FE4` as the 68000 reads it = bit 2 busy (1 at rest) \| Console model bits 6, 8, 9, 10. | a decision of the project plan | `0x0004 \| model` written at reset | Composed by the register file (bit 2 from the stream engine). App init's MCU word `0x46F8`/`0x66F8` is never seen in bits 6, 8-10. |
| BOOT-11 | `$1FEC = 0`; `$1FEE`, `$1FF0-$1FF6` = 0 before app init writes them. | checked (app init) | ROM bytes left in plain RAMDP words (no game reader) | Register reset values. |
| BOOT-12 | Window off at the release, stream pointer reset. It turns on only at the first stream start (`$1FE8 = 1`: DB06, DA direct, F2). | chip writes `$1FE8 = 1` only at stream starts (checked); finding 2 (measured) | `sdram_en = 1` at reset and at 81 | Off at reset; on at whichever of our DA/DB/F2 paths first points the window (docs/ALLOWLIST.md row B4; the game's first window read follows the first DB06, measured in the census). 81 no longer touches it. |
| BOOT-13 | FM game view at the release: reads of `$2000-$7FFF` by the 68000, Z80 and VDP DMA return ROM XOR `0xA8A2` per word. Off after 84 until the next reset. | our study notes S-F02/S-F04 (checked); B Jam's decision (core circuitry) | no XOR anywhere (FM never played) | Reset value = game view (nothing reads `$2000-$7FFF` before the first Z80 patch load, measured in the census; the protection-view reader, the 'SE' fallback, is unreachable). If the RTL 'SE' option is ever built, start in the protection view and switch at 'SE'. |

### 2.4 What app init expects, and the start-up around it

| id | rule | evidence | 0.2.6 today | new core |
|---|---|---|---|---|
| BOOT-14 | App init (0x0801F980) reads: RAMDP `$0108` (dummy), the hand-off block (chip: RAMDP `$1FE0-$1FEF`, MCU side), `$1FE6` bit 12, `$1FEA` (`$1234` = warm path). It writes `$1FF0 = $8000`, `$1FF2 = $8000`, `$1FE6 = (old & $1000) \| $4000`, `$1FE4 = $46F8`, `$1FEA = 0` only on the warm path, `$1FEC = 0`; then `$1FE6` bit 15 and `$1FE4` bit 13 through the status helper. | (checked) | none | As the chip does it (its register writes belong to the chip status protocol, docs/ALLOWLIST.md row B10). The dummy read and VTOR/clock set-up are plumbing and go. The hand-off read becomes a read of the board block (section 3). |
| BOOT-15 | Clocks, flash wait states and the vector table are ours. Every time-based boot figure (84's 0.1 ms delay, bounds in BOOT-02, the watchdog) comes from the one build-time clock value. | the project plan's "clock-following timers" rule | NEORV32 crt0; ms counter from `CLK_FREQ` | Same rule; no NTSC literal. |
| BOOT-16 | Watchdog (as the chip's): disarmed at app start; armed by 81 and then the first 9494 (frames 169 / 190); disarmed by 84 and A858; gated off while the Pocket menu is open and during the bank-cache first boot. | checked in the chip's code (and in our firmware audit's corrected entry for the chip's watchdog) | none | As the chip's, with the gate. The bank-cache gate is harmless but never needed: nothing arms the watchdog before the game's 81, and the unpack runs before it (found in our completeness review). With the menu closed it can now halt the MCU about 4 s after the game stops its frame tick (docs/ALLOWLIST.md row B27). |
| BOOT-17 | The firmware can read "Pocket menu open" from the first new-core firmware on. | a fix from our completeness review | the core already has `osnotify_inmenu` (pauses the 68000/Z80, mutes YM/PSG); the MCU cannot see it | New bit on the MCU bus, from the existing `inmenu` synchroniser. |

---

## 3. The hand-off block

On a cart the bootloader leaves four longs in RAMDP `$1FE0-$1FEF` (MCU side only; the 68000 sees registers there). App
init copies them to its state (+0x180..+0x18F) and the MegaWire page loaders use the copies (checked). On ours there
is no bootloader, so the board layer supplies the block. It is plumbing the game cannot see.

```c
/* board layer, read once by app init where the chip reads RAMDP $1FE0-$1FEF */
typedef struct {
    uint32_t w1fe0;   /* copied, never used by the app (checked): 0 */
    uint32_t w1fe4;   /* copied, never used by the app (checked): 0 */
    uint32_t page_a;  /* MegaWire page A: our address of a packed page (byte 0x80 + 0x80-format stream) */
    uint32_t page_b;  /* MegaWire page B (font), same form */
} board_handoff;
const board_handoff *board_get_handoff(void);
```

| rule | evidence | needed from |
|---|---|---|
| A board constant (IROM or the cold pack), not RAMDP: no MCU-only words under the register file, nothing for a 68000 post to clobber. | design choice; the chip reads it only at app init (checked) | the new core |
| Each page starts with byte `0x80` and decodes with our 0x80 decoder, which decodes as the chip's at 0x080251B0 does. Page A decodes to at most `0x800` B (vectors, then code from `$200`), page B to at most `0x1000` B (to RAMDP `$0800`). The loaders keep their rules: the `0x80` check, the caps, the rev16 copy, code before vectors, the "..." at `$1E10-$1E14`, the fatal codes on failure. | page loaders 0x08020CC4 / 0x08020D6C (checked) | the MegaWire code |
| The first new-core firmware ships `page_a = page_b = 0`. A build check refuses to enable the A858 path done as the chip does it (the one the MegaWire code brings) while either is 0 (a zero pointer fails the `0x80` check and halts the MCU). | checked (loader); A858 stays the legacy path until the MegaWire code | the new core, the MegaWire code |
| The pages are our rewrite of the MegaWire screen (docs/ALLOWLIST.md row B5), packed by our build tool. Where they live (the SRAM MegaWire load route) was an open item of the project plan. | the project plan | the MegaWire code |

---

## 4. Blank-save first boot: 84, the mini-game, and the Soft Reset after it

| step | evidence | 0.2.6 today | new core |
|---|---|---|---|
| No valid save: DF reads fail, NO SAVES FOUND, language, E003/E004, SAVING... SUCCESS!, then `$976F8` -> `$B458C`. | checked; GPGX 84 at frame 787 (measured in our completeness review) | same | same (save format per docs/ALLOWLIST.md row B11, from stage 3, which brought the saves in the cart's own format) |
| `$B458C`: VDP reg 1 = `$54`, 2,048 NOPs at `$FF0000` + `jmp $8200`, post 8400 (`$B468C`), `jmp $FF0000`. No reply wait. Sled 1.070 ms. | checked; estimated | same | same |
| Chip 84: delay 0.1 ms, `$1FEE = $AF5B`, `$1FE4 &= ~$18`, `$1FE8 = 0`, RAMDP `$0006 = $8200`, watchdog disarmed. | (checked) | `sdram_en = 0` only | 84's writes as the chip makes them. |
| **Window off and FM view off before the sled ends.** Requirement: <= 0.5 ms after the 68000's 8400 write (target, 2x margin), hard limit 1.07 ms. The mini-game then reads `$C000-$CFB1` (5,708 CPU reads) and `$D0D4-$D1B2` (32 DMA reads) as ROM. | measured in GPGX in our completeness review; B Jam's decision (~1 ms) | works on hardware (0.2.6) | Driven by 84's writes as the chip makes them (`$1FE8 = 0`; `$AF5B` also forces the window off). Which write the cart uses: not known, invisible. Both stay off until the next reset. Keep the chip's 0.1 ms delay first: on the cart it most likely lets the 68000 leave ROM (`$B4692`) before the key view flips (inferred); ours flips only `$2000-$7FFF` and the window, so earlier would be safe, but we keep the chip's order. |
| The mini-game never returns and never touches the cart registers; it posts nothing for ~29 s. The watchdog must not trip. | checked by a scan, and in our completeness review | no watchdog | 84 disarms it (BOOT-16). |
| `$0006 = $8200` makes a 68000-only reset re-enter the mini-game. | (checked) | not written | Written, as the chip does. Invisible on the Pocket (no 68000-only reset). MiSTer: as a cart would, presumably (inferred). |
| The save was written before 84, so a power cycle boots the game. | checked (order) | Soft Reset boots the game (Pocket docs "First boot") | Soft Reset = full reset (section 6): boot page recopied, `$0006` back to `$0200`, window and view reset, game boots, mini-game never returns. |

Never test this on the real cart: it needs a blank save.

---

## 5. Hold-button screens at power-on

The game reads pad 1 (`$FF7028`) after the C6 wait, so a button must still be held about 2.8 s after power-on
(frame ~173 in GPGX, measured; ours may differ, the allow-list's "boot length" row).

| button | check | what it reads from the cart | 0.2.6 today | new core |
|---|---|---|---|---|
| B | `$81012`: pad word == B alone; clears `$FF98D8` | Terminal line `$9725C`: 4 hex digits of ROM `$1000A` (game view, file as is), RAMDP `$1E0`, `$1E1`, `$1E2` as raw bytes (NOT'd only for the terminal's text encoding), a fixed four-character text (in the game code; the cart cannot change it), then a space if RAMDP `$1E4 == $FF00`, else 'S' (`$972DC`). Also skips the terminal's A48x post (`$9777C` -> `$9BEF2`; the boot A400 at `$81124` is posted either way: corrected 2026-10-16, from B Jam's hold-B videos) and the Mega CD start (`$81054` -> `$9C9D0`). (Checked.) | the ROM file's version digits + its region letters + the fixed text + `S` | the ROM file's digits + the ROM file's letters + the fixed text + space (the widely shared ROM file prints the same line as B Jam's black JP cart; his pink US and purple EU carts print other digits and letters, measured 2026-10-16) |
| A | `$80CB0`: pad word == A | nothing from the boot set-up; picture `$B6CB6` drawn with ordinary AD posts (read in the code) | as the game | same |
| C | `$80CBC`: pad word == C | same, picture `$B69CA` (read in the code) | as the game | same |
| Start | intro screens skip on Start ($922A2 ... $BA59C) (read in the code) | nothing from the cart | as the game | same |

---

## 6. Reset types on the Pocket, and what each must leave

All three go through one reset envelope in today's core (`core_top`: `~reset_n`, the "Soft Reset (mini game)" action at
bridge `0xF0000000`, PLL lock, data-slot loading) (checked). A 68000-only reset (console Reset button) does not exist on
the Pocket.

| item | power-on (core load) | core Soft Reset | any other APF reset | evidence |
|---|---|---|---|---|
| 68000 | held until P6 | held from the reset's first cycle (BOOT-01) | same | the new core fixes this finding of the project plan |
| Register file, window, FM view, mailbox latches, busy bit | reset values | reset values | reset values | BOOT-03, 08-13 |
| RAMDP | undefined -> boot page | previous session -> boot page; every word the game reads before writing it is set (sections 1-2) | same | census reads (measured) |
| ROM image in SDRAM | fresh from APF | kept (incl. the `$81104` NOP; patch re-applied, idempotent) | kept, or fresh if APF reloads the slot | checked (0.2.6) |
| Save (BRAM) | loaded from SD | kept | kept; if APF reloads the slots, an unsaved in-session write may be lost: APF behaviour, not known | (inferred) |
| MCU | crt0 cold | crt0 cold | crt0 cold | (checked) |
| WRAM code window | from the bitstream | kept (write-locked) | kept | docs/LAYOUT.md |
| SDRAM controller and its request toggles | init | not reset today | not reset today | the project plan's rule: resynchronise every toggle handshake the boot depends on, on every reset |
| Bank cache (the sound-cache builds) | `cache_valid` = 0, check/unpack | `cache_valid` kept (power-on-only), no unpack | as Soft Reset | the firmware's interrupt design; docs/MCU_INTERFACE.md section 21.1 |
| Pocket menu | closed | the reset is chosen from the open menu: the 68000 stays paused (`pause_req`) until it closes; the MCU boots meanwhile; the C6 count cannot advance while the 68000 is paused | same | checked (core_top pause path); inferred: the menu is still open at the reset |

**Same end state for all three:** at the release, sections 1-2 hold exactly, whatever happened before (mid-stream,
after 84, during the boot itself, two resets in a row).

**Since 2026-10-27: a fourth type, Console Reset** (the Pocket menu action at bridge
`0xF0000004`): the console's own 68000-only Reset, none of the above. core_top presses md_board's `reset_button` alone
(no SRES, no RAM clear, no MCU reset), raises CAUSE.V (the chip's EXTI13) and holds the 68000 (`ext_vres`: its RESET and
HALT only) until the firmware has written the warm vector page (RAMDP `$0000-$00FF` = the boot page's vectors with the
reset PC `$00010100`; core/boot/bootpage.c `boot_warm_page`, called by L1 before it acknowledges V) and the button pulse
has ended. Kept: work RAM, Z80 RAM (the Z80 itself held by the console until the game writes `$A11200`), RAMDP
`$0100-$1FDF`, the VDP, the register file, the MCU and every chip state (C6 is not run again: the chip's one-shot). The
game then decides by itself: a lock before its first entry (`$80B78` loops on `$FF5880`), the NX terminal after it, a
lock during a zoom (F5 stamps under the boot vectors). The chip only acknowledges EXTI13, so the board answers none of
the warm path's posts (810E, C600). A press while the 68000 is held anyway (power-on, a load, Soft Reset, the boot
hold) is dropped; from the open menu the 68000 is reset at once and starts once the menu closes. Allow-list rows AL-01
/ AL-02 (docs/ALLOWLIST.md rows B15 / B16) stay until this Console Reset passes on hardware (test build S3c; a project
decision).

---

## 7. Copy protection at boot

| rule | evidence | 0.2.6 today | new core |
|---|---|---|---|
| The boot page's copy protection is its own 'SE' timeout (60,001 tries, ~1.55 s, then `jmp $8200`). A plain ROM copy or a pass-through device that forwards only cart-select cycles never answers 'SE', so it gets the mini-game. | checked in the code; the time estimated; the pass-through inferred; "threshold" from a web source (wafflenet) | bypassed by the patches | same |
| There is no cart-side timer to reproduce. The chip has no 'SE' constant, no FPGA `+0x1E` register and no `$200000` code; its only `$8200` write is in 84. A cart-side time window (the cart stops answering 'SE' some time after power-on) is not known. | checked (a search of the chip's constants); B Jam's to-do N2/T7 (section 10) | none | none. If N2 finds a window, it goes on the outside list only: our 68000 is never late. |
| In a cartridge reader's view the whole 4 MB reads under the other key, the boot page repeats every 64 KB and `$1FE0-$1FFF` reads 32 fixed bytes. None of it is served by ours. | checked in our study notes | n/a | n/a (allow-list row AL-08) |
| Scum! must never trip it: all Scum! patches are at or above `$1A9FA` (0.2.6 RTL) (checked). | (checked) | holds | holds; keep the rule "no ROM or RAMDP patch in `$0000-$FFFF` beyond the 0.2.6 boot patches" in the Scum!/HOF code review |

---

## 8. Allow-list rows proposed (for B Jam's allow-list review)

**Approved: B Jam's decision of 2026-10-11** (allow-list review: "do all recommended, more cart accurate the better").
In `tests/equiv/allowlist.json` as B15-B24 (AL-01..AL-10, in order), with B2 / B6 reworded as docs/CART_FPGA_SPEC.md
section 16 asked, and B25 for its decision F-D3.

| id | difference | why it stays | evidence | needed from |
|---|---|---|---|---|
| AL-01 | Every Pocket reset type equals a power cycle. The cart has a power-on and a 68000-only console Reset; the Pocket has neither distinction. | platform | checked (core_top) | the new core |
| AL-02 | Console Reset (68000-only) does not exist on the Pocket. On a cart: EXTI13 acknowledged only by the app; what the FPGA/bootloader does is not known. MiSTer's board layer follows B Jam's Reset test. | platform | checked (the chip); B Jam's test T5 (section 10) | the new core |
| AL-03 | MCU self-reset (0x0801FCC8 from "WE SUX" 0x08020C4C, the watchdog with 81 bit 4 0x08020EA4, the update end 0x08022BF4) maps to our full cart reset. The cart resets the MCU only and keeps the FPGA state. Unreachable in play: no game code sends "WE SUX", the game posts only 810E/810F, the update is inert. | unreachable | checked (callers); 81 posts measured in the census | the new core |
| AL-04 | The warm path (`$1FEA == $1234` at app init) and `$1FE6` bit 12 ("boot into the MegaWire screen") never occur on ours: both registers reset to 0 on every reset. The chip's checks stay. | unreachable | (checked) | the new core |
| AL-05 | MegaWire update: the NOR erase/program routines (0x0801F5C4, 0x0801F688, 0x0801F81C) report failure and never write the ROM image; the bootloader's app re-install has no counterpart. | must never write the ROM | checked in the code; the re-install inferred | the MegaWire code |
| AL-06 | Header `$1E4 = $FF00` (cart-exact by two real sources) against the ROM file's `$2020` and 0.2.6. The letters are the ROM file's own (BOOT-07 dropped 2026-10-16). A change of reference against the final 0.2.6 firmware and test3 (an earlier 0.2.6 test build). | cart-exact | checked in our study notes | the new core |
| AL-07 | Window off from reset (cart) against 0.2.6's on: the splash DMA tail (`$C000-$C01F` -> VRAM `$13E0-$13FF`) differs from the final 0.2.6 firmware and test3 (an earlier 0.2.6 test build), and 0.2.6's stream pointer has moved 16 words before the first stream post sets it. | cart-exact | finding 2 | the new core |
| AL-08 | Copy-protection view, 'SE' answer and the `$200000` stub are not served; the 0.2.6 boot patches stand in (extends B3). | no source | (checked) | the new core |
| AL-09 | Hand-off block from the board, not a bootloader; RAMDP `$0108` dummy read dropped. No game-visible effect. | plumbing | (checked) | the new core |
| AL-10 | FM game view (XOR on `$2000-$7FFF`, off after 84): the Z80's patch reads differ from the final 0.2.6 firmware and test3 (an earlier 0.2.6 test build) by design. Listed as missing in the completeness report. | cart-exact | checked in our study notes; B Jam's decision | the new core |

---

## 9. Tests

**Simulation (the new-core RTL + RV32 firmware, board mode), every reset type of section 6** plus these cases: mid-DA/DB
stream; right after 84 with the mini-game running; during the 2.8 s boot itself; two resets 50 ms apart; menu held open
0, 5 and 20 s after choosing Soft Reset; with every Console value and each combined Mega CD unit.

| # | check | pass |
|---|---|---|
| T-B1 | `$1FEA` at the game's first read (PC `$B43B2`) | bit 15 = 0, every case |
| T-B2 | `$1FE6` at app init's read and at the first post | bit 12 = 0; bits 0-2 = MegaWire option |
| T-B3 | Window at the release and at the splash DMA (PC `$167A`) | off; right after that DMA, VRAM `$1000-$13FF` equals ROM `$BC20-$C01F` word for word |
| T-B4 | `$1E4` at `$152E`; `$1E0-$1E2` at `$BC412` | `$FF00`; the ROM file's letters on every Console |
| T-B5 | RAMDP `$0000-$1FDF` at the release | equals ROM except exactly the 4 patch words and `$1E0-$1E5` |
| T-B6 | `$1FE4` at `$BCA22` | `0004 \| model` for every Console value (model = 0 for a combined unit) |
| T-B7 | 68000 bus cycles between the Soft Reset request (`btn_reset`, the request as the core sees it) and the release | **Menu open** (how the core's Soft Reset is given): 0. **Menu closed:** at most ONE bus cycle may start after the request, it starts within 0.25 us of it, and it is never a write (B Jam's decision of 2026-10-13; was "0", then the proposed 0.15 us). Why not 0: a cycle the 68000 is already starting still starts (its own reset latency, not the core's). Measured on the RTL of 2026-10-12 (review, 24 phases): menu open 0 in 24; menu closed 0 in 16, one cycle in 8 at 9-148 ns, 0 RAM writes, 0 acknowledged writes. Reading of "never a write": 2 of those 8 cycles (37 and 111 ns) START as write cycles and are cut by the reset before any acknowledge, so nothing is written; the test counts that as a pass. If B Jam means "the cycle is never a write cycle at all", the current RTL fails it in 2 of 24 phases: B Jam to confirm the reading. From the APF bridge write rather than `btn_reset` add 64-73 ns (worst estimated 221 ns, inside 0.25 us) |
| T-B8 | MCU posts seen before the first 810E | 0 (no stale latch) |
| T-B9 | Watchdog | not armed before 81 + first 9494; gated with the menu bit |
| T-B10 | Bounded waits: inject an album/EverDrive stall | release within the bound; TEST milestone shows the stall |
| T-B11 | Blank-save first boot: 8400 write -> window off and FM view off | >= 0.1 ms (the chip's delay) and <= 0.5 ms; fail above 1.0 ms (limit 1.07 ms); same rule as docs/CART_FPGA_SPEC.md test R9; mini-game frames equal the 0.2.6 capture for 10 s; no fatal through 30 s |
| T-B12 | Soft Reset after T-B11, three times, then a power cycle | the game boots each time, no NO SAVES FOUND, no mini-game |
| T-B13 | Hand-off | read once at app init; a build with the MegaWire code refuses A858 with a zero page pointer |
| T-B14 | Region | JP features iff the version register says Japan, as 0.2.6 (no header change needed) |
| T-B15 | Replay rigs | strict except the rows of section 8 |

**Hardware (B Jam, Pocket only):** power-on x3; Soft Reset x10, including straight after Console and Mega CD changes
(the Soft Reset black-screen question); blank save -> mini-game 10 s -> Soft Reset into the game, mini-game never
returns; hold B at power-on: the line ends in a space; menu open 10 s during the boot.

---

## 10. What B Jam's to-do items settle

| item | settles | effect on this spec |
|---|---|---|
| Hold-B photo on a US console and on a JP console (same cart) | whether the cart rewrites `$1E0-$1E2` by console; the last character confirms `$1E4 = $FF00` on his cart | Done 2026-10-16: it does not (BOOT-07 dropped); the last character is a space on all three of his carts |
| Reset held at power-on, released after 2, 5, 15, 30 s (N2/T7) | a cart-side 'SE' time window | outside list only (section 7) |
| Console Reset mid-game on a Model 1 (T5) | the 68000-only reset outcome (game reboots / mini-game after ~1.5 s / crash) | AL-02 and MiSTer's board layer |
| Reset held ~8 s mid-fight (N3/T8, optional) | what the cart shows after the watchdog halt; if the mini-game then draws right, `$1FEE`/`$1FE4` switch the window | none for the Pocket (84 writes all three) |
| Power-on videos x3 with 60 s of attract (N6/T11) | boot length and the C6 frame count | Done 2026-10-16: count byte 94 (95 once), measured by matching all 256 attract demos; the C6 hold as the chip's since 2026-10-17 (docs/ALLOWLIST.md row B34) |
| MegaWire screen video (T4) | page A/B behaviour and exit; whether entry looks like a 68000 reset (`$1FE4` bit 14 reading, S-B08) | section 3 pages, the MegaWire code |
| Consoles list, TMSS on his Model 1 (N4) | model decode predictions | Console table, not boot |
| Only with the analyser: C1, C2a, C2b | whether the cart holds /VRES at power-on and for how long; the 'SE' value and timing, the stub, the echo's effect; the header and boot page as served | BOOT-01 (cart side), BOOT-05 option, BOOT-07 |

Never on the real cart: a blank save, EEPROM writes, debug ports, the MegaWire update.

---

## 11. Not known (and harmless for the first new-core firmware)

- How a cart keeps the 68000 off RAMDP at power-on, and how long (C1).
- Where the cart's boot page comes from (bootloader flash or FPGA RAM initialisation).
- The 'SE' protocol: who answers, the two masked bits, what the `$91xx` echo does, whether 'SE' switches the key view;
  the 364-byte stub.
- Whether the cart rewrites `$1E0-$1E5` per console (photos).
- Who sets `$1FE6` bit 12 on a cart, and when.
- What the bootloader does after an MCU reset (recopy the page? re-install the app?).
- Which of 84's three writes switches the cart's window.
- Whether `$1FE4` bit 14 is the cart's "let the 68000 run" switch (our study notes, S-B08); the new core keeps an
  explicit board hold.
- Whether the splash tile that 0.2.6 reads from the stream (finding 2) was ever visible.

---

## 12. What the review changed (2026-10-11)

Every key claim was looked at again at its cited address (ROM: `m68dis.py`, `m68grep.py`; chip: `chipdis.py`) or run
again (`winpre.py` over watch_solo, watch_duo, tour_s0, tour_x1; `hdrreads.py`). Held: the version-register decode at
`$BCA04` and the JP-feature sites (finding 1), the splash DMA source and length (`$1668-$167A`: `$BC20`, `$200` words,
VRAM `$1000`), the census reads before the first post, the four `$1E4` readers, the 'SE' loop (60,001 tries, 198
cycles each), the stub copy (182 words), the boot entry at `$200`, the C6 wait, 84, app init, the page loaders, the
0.2.6 boot patches and 0.2.6's reset routine, `fpgio`'s configuration-only `ctrl`, and the lowest Scum! patch
(`$1A9FA`).
Changed:
- Finding 2: which ROM view the text page's DMA reads, with the tile evidence (measured nibble counts).
- Finding 6: the 1.070 ms sled and the 1.075 ms post-to-`$8200` time are one event from two starting points.
- BOOT-01: the hold's reset-value change needs the sweep over fitter seeds that a finding of the project plan asks for
  (marginal crossing).
- Section 8: the AL rows wait for B Jam's allow-list review instead of being numbered here.
- T-B11: the same pass rule as docs/CART_FPGA_SPEC.md test R9.

---

## 13. Known cart behaviour, not faults

Things a tester may take for a fault. Each is what the real cart does too; do not chase them.

| what is seen | why it is right | evidence |
|---|---|---|
| The no-input intro shows a **"MegaWire 4.0"** logo (among Datenmeister, 80MHDC, EXPS, SCALR, NEURAL) even with MegaWire Off and "MODEM : NONE" on the terminal | It is the game's own credit screen in the tech-logo sequence, not a MegaWire status. B Jam's original cart shows it with no MegaWire attached | measured on hardware by B Jam, 2026-10-13 (his original cart, no MegaWire); seen in the new-core co-simulation (frames 900-920) |
| The hold-B terminal line ends in a space, not 'S' | `$1E4 = $FF00` (BOOT-06), as both real sources hold | checked; B Jam's decision of 2026-10-10: yes |
| A blank save starts the PAAAAAP mini-game after "SAVING... SUCCESS!" | The game's own first-boot path (section 4); a Soft Reset then boots the game | checked; never test on the real cart |
| With 3-Player Mode On (or Arcade Mode = Multiplayer) the first-boot mini-game listens to controller 3 only, and attract demos drift | The game reads the adapter as a real console with an EA 4-Way Play attached would present it (docs/STAGE1_PLAN.md question Q3) | measured in GPGX and the pad bench (docs/STAGE1_PLAN.md track F); that real hardware with the adapter does the same is inferred |

## 14. Changes 2026-10-13 (new-core docs)

- T-B7 reworded per B Jam (menu closed: at most one cycle, within 0.25 us, never a write), with the measured basis and
  the one reading B Jam must confirm; BOOT-01's new-core column says what was built.
- P17 and section 13: the "MegaWire 4.0" intro logo recorded as known cart behaviour (B Jam's hardware check).
- BOOT-16: the bank-cache gate never needed; the watchdog halt is a listed difference (docs/ALLOWLIST.md row B27).
