# Census: what the game posts and reads (made before the new-core work)

The census our project plan asked for before the new-core work began (gap G22 of our project plan's list, plus gaps G2
and G8 of that list, and open questions 5, 7 and 8 of the firmware design; these numbers are those documents' own,
which are not in this tree): what the
game really posts and reads, measured on the recorded game runs and the 68000 code. Written 2026-10-10.

**How we know.** "measured" = counted in a run or scan here; "estimated" = arithmetic on measured numbers; "not known"
= nobody has a number; "checked in the code" = verified in code.

**Sources.** Our GPGX captures of the game (solo route 72,422 frames, duo route 59,553, stage $04 control 9,551), the
same movies replayed through a census build of GPGX that logs every cart-window access, scripted menu tours of the
retail ROM, the chip program in our comparison harness, and static scans of the ROM's 68000 code, the chip image and
the Z80 driver. The tools, the raw tables and the reruns are in our working notes (every number, input md5 and
command). Nothing from the ROM or the chip image is included in this tree.

GPGX runs the game's real 68000 code, but its cart MCU is a model (instant replies, bit 14 never set, MegaWire status
7). The numbers below are about what the 68000 does; where the model matters, it says so.

---

## The answers

| # | question | answer | how known |
|---|---|---|---|
| 1 | Mailbox-A ($1FEC) posts other than 9494 | **None, ever.** One writer: `move.w #$9494,$1fec.w` at 0x010E84, the end of the VBlank handler. One post a frame from frame 190, at VDP line 225 (82-115 us into VBlank). | measured; checked in the code |
| 2 | Highest sprite block number | **12,326**, the last block of the ROM's table (12,327 blocks). The related-block index reaches 12,308. Nothing reaches 16,384, so the 768-byte sparse map is exact. | measured (exhaustive) |
| 3a | 68000 readers of RAMDP $1B20-$1B87 | **Yes, but only when MegaWire status is not 0.** The MegaWire submenu reads the block every frame. With status 0 (a real cart with nothing plugged in, 0.3.0 Off) no reader can run. | measured; checked in the code |
| 3b | Readers of the FM patch bank $4000-$50DF | **Only the Z80 driver.** No 68000 access, and no de-XOR anywhere in the 68000, chip or Z80 code. Who de-XORs on the cart is not known. 0.3.0 can de-XOR it once at boot. | measured; checked in the code |
| 4 | Engine posts that land mid-tick | On the chip, **12 per route**, all at scene changes. **D602 comes every 4th frame, not every frame**, 3.6-7.5 ms after the 9494. The held-D602 risk of gap G8 is about 1 post in 10,000. | measured; the windows estimated |
| 5 | Other items of the census | **The game spins on $1FE6 bit 14 after DA, C6 and save reads.** Reply-first does not unfreeze DA loads; only a faster DA job does. The Z80's packet read time cannot be measured in GPGX. | measured |

---

## 1. Mailbox A ($1FEC)

| run | 9494 posts | frames | any other word or byte write | writer |
|---|---|---|---|---|
| solo route | 72,232 | 72,422 | 0 | 0x010E84 |
| duo route | 59,363 | 59,553 | 0 | 0x010E84 |
| stage $04 control | 9,361 | 9,551 | 0 | 0x010E84 |
| retail-ROM tours (boot, menus, Options, MegaWire submenu, ORIGINAL; status 0 and 7) | all | - | 0 | 0x010E84 |

- **Exactly one post per frame from frame 190.** Frames 0-189 have none: the boot page runs until frame 169, and the
  game's first posts (810E, C600) are at frame 169. Measured.
- **Always at VDP line 225**, 82-115 us after VBlank starts. Measured.
- The VBlank handler writes $F1 to Z80 RAM $0040 (the Z80's frame cue) just before it posts the 9494. (Checked in the
  code.)
- **Static check (checked in the code):**
  - No other instruction names $1FEC.
  - 405 sites load the register-page base (the pointer at ROM $AF840 = $1FE0), and none of them writes +$C.

**For 0.3.0:** mailbox A carries only the frame tick. A one-word latch is enough. The chip's mailbox-A table is only
ever entered at index 0x14.

## 2. Sprite block numbers (open question 7 of the firmware design)

**Exhaustive scan of the anim container** (the container the chip unpacks at C6). It covers:
- 241 objects;
- 17,401 animations;
- 5,167 sprite records;
- 28,871 pieces.

| | range | >= 16,384 |
|---|---|---|
| block number (block->id writes and reads) | 1 .. 12,326 | 0 |
| related-block index `uxth(num + (size >> 4) - 9)` (the read at 0x0802F25A), 5,560 pieces | 1 .. 12,308 | 0, and it never wraps |
| blocks drawn on the routes (GPGX) | max 12,315 | 0 |

- **Every index the game data can produce falls inside the chip's 16 KB table.** So a map that returns 0 for a
  missing key returns what the chip returns.
- **Open 7 is closed.**
  - A u16 key is enough.
  - The 128 nodes cover the at most 54 ids in use.

## 3a. The MegaWire block $1B20-$1B87 (open question 8 of the firmware design)

**How the 68000 reaches it (checked in the code):**
- The A4 post routine (0x09BEF2) stores `$1B20` in work RAM $FF7014.
- The game posts A400 at frame 240 of every boot, so the pointer is always set (measured).
- 28 sites read through it:

| reader | what | reachable |
|---|---|---|
| screen 13, 0x08237A (+ 0x0814B4, 0x09BF46, 0x09C006, 0x09BB4C) | the MegaWire submenu: connection status, access point, account, error code | only through the Options row MEGAWIRE, which the game shows only when `$1FE6 & 7` is not 0 |
| screen 10, 0x0967E8 (+ 0x0960E8, 0x095B3C) | the "NX TERMINAL" online hub | **never.** The main-menu builder (0x0894DA-0x089596) only adds ARCADE, ORIGINAL, ARENA and OPTIONS (checked in the code) |
| 0x0B5D5C | stamps the block's long at $1B28 into the save block's 16-entry table | only from screen 10 |

**Measured reads (68000 data reads of $1B20-$1B87):**

| run | MegaWire status | reads |
|---|---|---|
| solo and duo routes | 7 | 0 (menus not visited) |
| status-0 tour: boot, terminal ("MODEM : NONE"), main menu (no icon), all 10 Options rows (no MEGAWIRE row), ORIGINAL into gameplay | **0** | **0** |
| MegaWire submenu, cursor over every item, ~300 frames | 7 | 1,100: $1B30, $1B32, $1B38-$1B3D, $1B49-$1B4B, $1B6A, $1B83, every frame |

**What the chip writes there (measured in our comparison harness after its boot):**
- All 52 words are 0, except $1B32 = the ROM's version word (ROM $1000A, which core/mw/mw_task.c stores at its +0x162)
  and $1B84 = 0x2201.
- The writer is the TIM7 MegaWire task (0x08021728, about 9.8 Hz).
- It only writes while an 81 post has set bit 3. The game's 810E at boot sets it, so it always runs.
- 0.2.6 never writes the block. So with MegaWire On, 0.2.6's submenu decodes whatever bytes the boot page left there:
  "????@??", "[02]MISC. ERROR", access point "??" (GPGX shows the same).
- The boot page's own code also occupies part of this range. It never ran on any measured boot.

**For 0.3.0:**
- **Off** (default, status 0): no reader runs. Writing the block as the chip does is cart-exact and invisible.
- **On** (status 7, a labelled difference): the submenu reads the block every frame. Publishing the block as the chip
  does would make it show the chip's no-module values, not 0.2.6's text.
- **Question for B Jam** (below).

## 3b. The FM patch bank $4000-$50DF (gap G2)

**Measured on every replay and tour:**
- **68000:** 0 data reads and 0 writes in $4000-$50DF. In fact the 68000 never touches $2000-$BFFF as data at all.
- **Z80:** 0 bank reads and 0 writes there.
- **VDP DMA:** the only reads there come from GPGX's own sprite staging (it builds sprite DMAs from cart RAM $2000
  up). The cart and our core use the $C000 window for that, so this is not a game reader.
- **The Z80 bank is 0.** The Z80 reads $1800 and $1880-$193F through the bank window. So its patch load at Z80
  $C000 + 32 x program reads 68000 $4000 + 32 x program.
  - GPGX never asks the Z80 to load a patch, so that read itself is not exercised there.
- **No DA source points into the range** (lowest 0x16AFC8).

**Static (checked in the code):**
- No 0xA8A2/0xA2A8 key in the 68000 code.
- The chip image has no key, and no pointer to flash+0x4000 or RAMDP+0x4000.
- The Z80 driver XORs only with $40.
- The bank exists only once in the ROM, in XOR form.

**So the only reader is the Z80 driver,** and nothing in the 68000 code, the chip program or the driver unscrambles
the bank. On the cart it must be the bootloader (never read out) or the cart FPGA: not known.

**For 0.3.0:**
- The MCU de-XORs the 4,320 bytes once at boot, in the image the Z80 reads (0 ALM). Nothing else is affected.
- Two things to check in the new core and the synth step (inferred):
  - on our core, the Z80's bank read of 68000 $4000-$50DF goes to the SDRAM ROM image (`paprium_cart.sv` decodes
    only $0000-$1FFF as RAMDP and $C000-$FFFF as the stream);
  - the MCU can write that region.

## 4. Mid-tick posts and D602 (open question 5 of the firmware design, gap G8)

**Chip tick:** the whole tick runs in the EXTI handler at the 9494 (measured in our census of the cart chip, track 01):

| | instructions | time at 96 MHz, 1 IPC (inferred) |
|---|---|---|
| tick, mean | 2.6k | ~27 us |
| tick, max | 8.0k | ~83 us |
| whole EXTI work of a frame (tick + posts), max | 9.5k | ~100 us |

Time from the latest 9494 to each mailbox-B post (measured in GPGX). Counts at or under each bound:

| route | posts | n | <= 83 us | <= 160 us | <= 0.5 ms | <= 1.0 ms | <= 1.7 ms | <= 2.85 ms | median |
|---|---|---|---|---|---|---|---|---|---|
| solo | engine | 16,305 | **12** | 24 | 34 | 482 | 522 | 1,988 | 3.83 ms |
| solo | D602 | 11,778 | 0 | 0 | 0 | 1 | 1 | 1 | 3.83 ms |
| duo | engine | 12,780 | **12** | 23 | 33 | 61 | 514 | 1,982 | 3.92 ms |
| duo | D602 | 8,506 | 0 | 0 | 0 | 1 | 1 | 1 | 3.92 ms |
| stage $04 | engine | 2,767 | 11 | 22 | 34 | 51 | 81 | 92 | 4.10 ms |

**Engine posts** are 88, C9, CA, 8C, 8D, 8E and D0-D6, including the no-argument forms 95/96. The 30 clock-trim
posts (83) come only at boot, ~0.36 ms after the 9494.

- **On the chip:**
  - The posts inside the tick are 8802 (11) and D240 (1). The game posts them 1-2 lines after the 9494 at scene
    changes.
  - Each waits at most ~0.1 ms on the cart.
- **Under the firmware's interrupt design** (the tick runs in L2b, after a pending brain call):
  - 522 engine posts per solo route land within 1.7 ms. 425 of them are SFX D178; the rest are scene-change
    8C/8D/95/96/C9/CA/D6.
  - 1,988 land within 2.85 ms.
- **D602 (measured):**
  - It comes **every 4th frame during play** (11,686 of 11,777 gaps are 4 frames), always from the same call,
    straight after AE (99.7 %).
  - It lands at VDP lines 15-42: 3.63 ms (p01) / 3.83 ms (median) / 7.48 ms (max) after the 9494.
  - Its $1E10 level is 0 on every post: no crisis was captured.
- **Gap G8 (estimated):** with the urgent promotion, our tick and packet finish by 9494 + ~2.87 ms (the interrupt
  design's estimate).
  - So D602 is held in about 1 frame in 10,000.
  - The held-post rule matters at scene changes and for SFX posts in the 1-3 ms band.
- **Caveat:** GPGX replies at once, so on a cart (and on ours) posts land a little later in the frame. These counts
  are an upper bound close to the 9494. The latest post seen was 15.75 ms into a 16.68 ms frame.

## 5. Other measurements of the census

**Which posts make the game wait for $1FE6 bit 14 (gap G10; measured, frames 0-4,000):**

| post | the 68000 afterwards |
|---|---|
| DA02, DA07 | spins until bit 14 clears (0x0B4234-0x0B4246, 0x0B41AA-0x0B41BC); 16 of 17 DA posts |
| C600 | spins at 0x0B4574 |
| DF (save read) | polls at 0x0B61DA/0x0B61EA and 0x0B6340/0x0B6350 |
| 8C, F4, F5, B6, DB and every other command | no $1FE6 read before its next action (F4 / F5: the zoom state machine does read bit 14 later, at 0x034E28, and falls back after 128 frames; not a wait at the post. Added 2026-10-13 from the commands sweep of our completeness review, read in the code) |
| AE | the window streamer checks bit 14 at 0x07F416 |

- **Reply-first ends the frame freeze for 8C, F4 and F5, but not for DA:**
  - The game waits for the DA job itself.
  - So a DA load freezes the frame for as long as our job runs.
  - Only a faster job (the ROM-direct stream for modes 6/7, word-wide SDRAM access) brings it to the cart's
    ~0.65 ms.
  - This corrects the plan's "loads should no longer freeze the frame" for DA.
- **Engine posts during the 8C job:** every 8C is followed 29-32 us later by 9600, 9500 and C9FF, while the 8C unpack
  job is still running. The chip serves them at once, so ours must not queue them behind the job.
- **Job posts per route** (solo; duo within 5):

| post | count | note |
|---|---|---|
| DA | 68 | 53 DA02, 15 DA07 |
| DB06 | 1,015 | 45 come 84 us after a DA02, i.e. straight after the wait |
| 8C | 11 | |
| C6 | 1 | |
| F4 | 4 | |
| F5 | 137 | every 2 frames in zoom scenes |
| B6 | 12 | |
| DF | 4 | |

**Other items:**
- **Z80 packet read time (gaps G16, G17): not known.** GPGX's MCU model never sends packets, so its Z80 driver reads
  $1800 at random lines every 1-2 frames. The synth step's co-simulation with real packets has to measure it.
- **rand (gap G9):** no recorded D602 carries a crisis level. Tests of the synth step need a low-health capture.
- **Boot (measured):**
  - The 68000 runs the boot page from RAMDP until frame 169.
  - 810E x 3 and C600 come at frame 169, 8802 at 192, A400 at 240.
  - The 9494 starts at frame 190.
- **Chip at rest after boot (measured in our comparison harness):** $1FE4 = 0x66F8, $1FE6 = 0xA000. Gap G1 stays
  closed by the project plan's decision on the 68000's `$1FE4` view (docs/CART_FPGA_SPEC.md section 3.4).

---

## For B Jam

1. **MegaWire On look.**
   - With MegaWire On, the MegaWire submenu reads the cart's MegaWire info block every frame.
   - 0.2.6 never fills that block, so the submenu decodes leftover boot bytes ("????@??", "[02]MISC. ERROR").
   - A real cart fills it. With no module it is almost all zeros.
   - Doing what the cart does changes what the On submenu shows. Should On keep 0.2.6's look, or show what the cart
     chip publishes?
   - Off (the default) looks the same either way.

## Changes this suggests to the plan

- **The new core:** mailbox A as a one-word tick latch. The held-post slot is needed for scene changes and SFX, not for
  D602.
- **The new core:** the 8C job must not delay the 9600/9500/C9FF posts that follow it.
- **The new core and stage 3 (the unpackers, the zoom, the saves and MegaWire):** the DA job's own speed is what decides
  the load freeze. Measure our DA time against the chip's ~0.65 ms first (gap G10).
- **The sprite-engine step:** the sparse block map, as designed, with no special case.
- **The MegaWire step:** publish the MegaWire block as the chip does (gated on 81 bit 3). Under the rule that we match
  the chip it is required, and with Off it is invisible. The On look is B Jam's call.
- **The synth step:**
  - FM bank: de-XOR at boot by the MCU, after the two RTL checks in 3b.
  - Measure the Z80 packet read time in the co-simulation.
  - Get a crisis capture.
