# The allow-list

The 0.3.0 testing rule: **zero differences from the cart chip's program, except the ones written on one list.** That
list is `tests/equiv/allowlist.json`. This page is the same list in plain words, one row per entry, for B Jam's review:
he says yes or no to each. The JSON is what the tests use; if this page and the JSON ever disagree, the JSON is right
and this page is the bug (`tests/check_tree.py` rule 6 fails when they name different rows).

First written 2026-10-13.

**How to read it.** The 0.3.0 work was done in numbered stages (`docs/STAGE1_PLAN.md`): 0 = the 0.2.6 firmware moved
into this tree; 1 = the new firmware's own start-up, scheduler, dispatcher and board layer (the FW_S1 builds, "the
stage-1 images"); 2 = the sprite engine; 3 = the unpackers, saves, zoom and MegaWire; 4 = the sound bank cache; 5 = the
music: our own song engine and synth (the FW_S5 builds s5test / s5release, "the stage-5 images"). The "from stage"
column says from which stage a row applies. The firmware builds B Jam tested on his own hardware are named test build 4,
test build 5 (the first with our own song engine) and the stage-2 and stage-3 test builds S2, S3a, S3b and S3c.
Decision numbers (decision 3a, decision 6) are the items of B Jam's list of seven decisions of 2026-10-21; Q1-Q7 are the
seven questions of docs/STAGE1_PLAN.md section 11, which B Jam answered on 2026-10-11; D-numbers (D43 ...) and G-numbers
(G1 ...) are the ids of the old copies' items (section 4). How a status is known is said in words: measured (seen in a
run, a capture or a file), estimated (worked out from measured numbers) or not known (nobody knows yet). A "lockstep"
runs ours and the cart chip side by side and compares them after every step; the "cart-music runner" is our test harness
that plays the music as the cart's chip does. DT = Datenmeister, the music mode with the cart's own DAC; YM = the
console's YM2612.

**What changed 2026-10-13.** The completeness check (2026-10-10) found three different copies of this list in our
planning notes and several decisions that were on none of them. The three copies (a short list in the plan, a list in
the study notes, a row of the study's test matrix) were already marked superseded; every item on them is mapped to a
row below (section 4). The later decisions are now rows: the TeraDrive stub, the unscrambled FM bank, the watchdog gate, the
Scum! and Hall of Fame ROM changes, Arcade Mode Multiplayer, the rebuilt MegaWire screen, 3-Player Mode, whole-word
byte writes, the 8 KB save, TMSS on every all-in-one Mega CD unit, the menu music mute, and Mega CD None not answering
`$400000-$7FFFFF`. The "outside the chip" list (the parts of a real cart that are not the chip program: bootloader,
FPGA, EEPROM, sound output stage, MegaWire module) is a different list and stays where it is, the plan's table "Cart
FPGA and bootloader" (not in this tree).

**What changed 2026-10-21 (stage 5).** B Jam's seven decisions for the song engine and the synth ("go with all 7
stage-5 recommendations, including Stick Only and Inf. Credits (0012)") add five rows, in section 0 below: decision 3's
four (a, b and d approved; c only if a gameplay measurement shows the game never reads past the curve) and decision 6's
Grand Stick III. B31 now points at the Grand Stick III row for its Arcade parts.
The interface they rely on is `docs/MCU_INTERFACE.md` v1.3.

**What changed 2026-10-24 (the firmware of test build 5).** Decision 5's DT analogue stand-in is now its own row, B44,
approved under decision 5 (its values are estimated, and B Jam's listening session on test build 5 checks them by ear).
B41's condition is met: the gameplay measurement found the game never reads past the curve, so B41 reads approved.

**What changed 2026-10-27 (stage 2's first commit).** B Jam's answers of 2026-10-26 (after test build 5) are written in.
B Jam accepted test build 5's eight possible differences as they are: two are new rows (B45, the YM / Datenmeister
switch; B46, the Boom Box feed's last eight words), four are sentences under the rows they belong to (B9 the song start,
B39 commands sent together and the rare command orders, B40 the Boom Box bars), and B44 (the Datenmeister stand-in) is
marked as confirmed by B Jam's ear on test build 5.
B Jam approved B26, B28, B29, B35, B36 and B38 as written and retired B30 (its path left with test build 5). Two corrections
of ours: B14 no longer counts D49 as different (our sprite code has used the same slot table as the cart chip since
0.2.6's cache fix; stage 2's proof still has to show it), and B47 is the row the chip comparison's MegaWire transforms never had
(section 2b).

---

**What changed 2026-10-27 (B Jam's answers of 21:28).** B Jam approved B1, B4, B10, B12, B17 and B27 as written:
B1 is retired (B38 replaces it), B4 keeps only DA02, the 0x81 / 0x82 DA07 jobs and DB, B10 and B12 keep their split of
the two `$1FE6` bits, B17 keeps its reworded rule and B27 the watchdog halt. B Jam also asked whether those two `$1FE6`
bits can now be compared strictly with the chip. On the stage-5 images they already are: the music engine sets them as
the chip does, and test build 5's music lockstep held them equal to the chip in all 238 of its runs (and 41 checking runs).
The chip comparison of the stage-1 build keeps its two masks, because that build has no music engine, so it sets
neither bit, as 0.2.6 did.

**What changed 2026-10-27 (stage 2, the sprite engine).** The sprite engine now does exactly what the cart chip's
does. B14 no longer lists any sprite difference from the cart chip: it only counts where 0.2.6 drew differently.
New row B48 (B Jam approved it 2026-10-28, below): a sprite-slot count the game never asks for is kept to the game's own
maximum, as test build 5 already did.

**What changed 2026-10-28 (B Jam's answer of 12:07, and stage 2's repair).** B Jam approved B48: a sprite-slot count above 53
stays at 53, test build 5's limit, since the game never asks for more (on the cart such a count would make the sprite code
read and clear part of the first sound-effect channel's memory). New row B52 for B Jam's review, of the same kind: an
object number the game never uses (256 or more) makes the cart chip read its own working memory past a 256-entry list;
ours reads 0 there. The chip comparison no longer forgives anything in the sprite table: its last allowance (sprite
entry 0 after an empty frame, left over from 0.2.6) was never used since stage 2 and is gone.

**What changed 2026-10-29 (B Jam's answers, stage 3).** B Jam approved B53 (the zoom corner past the chip's zoom memory),
B54 (the unpack stream type the game never uses) and the rest of B52 (object numbers 268 and up) as they are; the game
reaches none of the three. B Jam also decided B55: after an early Console Reset ours stays black for a shorter time
than B Jam's cart, and that stays.

**What changed 2026-10-30 (stage 3, test build S3a: the check of every command against the cart chip).** Two new rows for
B Jam's review, both about things the game never does. B56: where the sprite animation data sits in our working memory
(the data itself equals the chip's in every byte). B57: a zoom command fed something other than a zoom picture; the cart
chip then writes past its zoom memory into its own sprite memory; ours stops at the end of the zoom memory. B Jam
approved both the same day ("Approved"). The same check also corrected a line of B12: the four words at cart RAM
$1C00-$1C0F that the cart chip's main loop writes after each Boom Box update (a running count and three of its own
memory addresses; ours writes zeros there) are written every time that loop goes round, not only after the commands
the row named before. Measured since: the game never reads those words and behaves the same whatever they hold; B Jam
approved that line as it is (2026-10-30). One more row, B58,
also something the game never does: a sprite upload list that nobody clears grows past the end of the cart memory
the cart chip may write; the chip writes on, ours stops writing there instead of crashing. B Jam approved it the same
day ("Approve B58 as a difference from the chip; the game never reaches it"). The same day B Jam kept test build S3a's slower start-up (the save slot table read from the player's ROM: about 95 ms at power-on, 90 ms at a Soft Reset) without a speed-up; it is written under B34.

**What changed 2026-10-31 (our MegaWire port joined to this firmware).** The check of every command against the
cart chip now also compares the MegaWire commands. The chip runs its MegaWire work about ten times a second from a timer,
and some commands leave work for its next run; so where that work is waiting, both sides are now compared after their
next run, not in the middle (a stricter comparison: nothing is left out). One new row, B59, which B Jam approved the same
day ("Thats fine allow"): the MegaWire menu's restart command (AA58) restarts the MegaWire code a moment later on ours
than on the cart, and ours does not save the MegaWire record to the cart's memory. The game sends that command only from
its MegaWire menu, which needs a MegaWire module plugged into the cart, so the Pocket never sees it. B Jam also allowed
one thing the check of the hidden MegaWire screen (the Options pad code) shows only because our model of the cart chip
lacks the two screen pages a real cart keeps in memory: that model stops at the screen, a real cart and ours show it.

## 0. Stage 5: B Jam's decisions 3, 5 and 6 (2026-10-21) and test build 5's eight possible differences (2026-10-26), now rows

| id | what is different | compared with | from stage | status |
|---|---|---|---|---|
| **B39** | Decision 3a. The music and sound posts (88, 8C, 8D, 8E, C9, CA, D0-D6) are answered at once; their work then runs in the order the posts arrived, together with the frame tick. The cart's chip does the work first and answers after it, so ours answers up to about 0.1 ms sooner. The music itself is the same as the cart-music runner's, block for block: every post's effect starts at the same mix block. A post whose work writes something the 68000 can read (a gameplay measurement checks each one) is not covered: it answers after its work, as on the cart. **Test build 5 (B Jam's yes of 2026-10-26, possible difference 3):** when the game sends several music commands at once, a later one can take effect one 2 ms step later than in our ideal model of the cart. **Not a difference (possible difference 7):** the command orders the game never sends are done exactly as the cart chip does them (a fade-out arriving while a new song is still being set up: the fade is dropped and the new song plays) | the chip, the cart-music runner | 5 | **approved** 2026-10-21. Measured: those posts cost the chip 159-755 instructions; estimated: 2-8 us each. test build 5's burst sentence **approved** 2026-10-26 |
| **B40** | Decision 3b. The synth mixes each 3.33 ms block whole. On the cart a post can cut into a block half-way and change a voice there; on ours (as in the cart-music runner) it takes effect from the next block. **Test build 5 (B Jam's yes of 2026-10-26, possible differences 4 and 5):** the Boom Box bars update whole between two sound blocks, and each frame's music work runs in one piece; on the cart the chip's timer can cut a bar update in two (at most one bar step, for one update) or fall between the two halves of a frame's music work | the chip (the runner does as ours) | 5 | **approved** 2026-10-21. Where a post lands inside a block on the cart is not known. test build 5's Boom Box sentence **approved** 2026-10-26 |
| **B41** | Decision 3c. In Datenmeister mode, a loud moment that pushes the output curve's index past the end of its table reads the table's last value on ours; the chip reads whatever lies past the table in its own memory | the chip | 5 | **approved** 2026-10-21, on B Jam's condition that the gameplay measurement (heavy sound effects over music) shows the game never gets there; the condition is met (2026-10-22): measured, the largest index in gameplay is 3,838 of 8,191 over 168.7 million samples a channel, and music alone never comes near (18 tracks, codes 193-3,839) |
| **B42** | Decision 3d. Datenmeister samples are made on the console's clock (decision 4) and the Pocket's audio output picks them up on its own clock, so about once in a long while one sample is repeated or skipped (a few parts per million) | the chip, a capture at the jack | 5 | **approved** 2026-10-21. How often is not known (ppm-level) |
| **B43** | Decision 6. A virtual Grand Stick III on controller port 1 answers the game's own stick reader, so the game runs its own arcade code on the unchanged ROM. The Pocket menu stands in for the stick's switches: Arcade Mode Off / On / Multiplayer / **Stick Only** (a stick with every switch off, like B Jam's); Arcade Coins 1 Coin 1 Credit / 2 Coins 1 Credit / **Inf. Credits (0012)** (stops on the game's red 0012 screen by design, as B Jam's stick does); Attract Only; no NO HIT FX (nothing to see on a Pocket); Select is the coin, only while Arcade Mode is on. With the stick on, its EXT socket is Dock controller 3 and there is no 4-Way Play. The Scum! Arcade words, pad hook, cave and coin stub go; Little-Man, Stage Select and the flip point stay. Still unknown: the stick's own wire values (how long the game's read takes each frame) until the cheap probes | the game's own code with a real stick (modelled), and B31 | 5 | **decided** 2026-10-21 (decision 6 a-c). The game's reactions checked by running the game's own code in a CPU emulator; the stick itself modelled |
| **B44** | Decision 5, the DT analogue stand-in. The Datenmeister music leaves the synth as the cart chip's exact DAC codes; what the cart's DAC and its wiring then do to the sound (its volume next to the YM music, a low cut, its polarity) is not reproduced. Ours is the plain stand-in B Jam chose: one volume for every Console setting, a DC blocker (3.7 Hz), no polarity flip, no filter. The volume (x 5.5) is an educated guess from the cart-engine recordings he heard as right in both modes; the captures could not settle the volume or the polarity | B Jam's ear (listening session A on test build 5), a capture at the jack | 5 | **approved** 2026-10-21 (decision 5: plain first). The values are estimated, not from a capture: session A on test build 5 checks the DT / YM balance by ear against B Jam's cart (a change is a firmware swap). Also on test build 5's list of accepted differences. **Confirmed by B Jam's ear on test build 5** (2026-10-26: "audio works great both ym and dt options") and accepted as it is (possible difference 8) |
| **B45** | test build 5's possible difference 1, the YM / Datenmeister switch. When the music switches mode (or Datenmeister restarts), up to about 0.25 ms (a few samples) of the old mode can play in the new one: the chip sets up the new mode's first sound block at once, ours a moment later, after the switch command has finished. The cart does something like this itself. The game cannot see it | the chip, the cart-music runner | 5 | **approved** 2026-10-26 (B Jam accepted all eight). Measured: 0.13-0.25 ms in the switch scenarios (the 2 of the 175 comparison runs of test build 5 that are not exact); a Datenmeister restart at the worst moment 0.21 ms |
| **B46** | test build 5's possible difference 6. The Boom Box's last 8 data words hold zeros on ours; on the cart they hold leftover bytes from the chip's own memory. The first 56 words (all that the chip works out) are compared exactly. We know of nothing that shows the last 8 | the chip, the cart-music runner | 5 | **approved** 2026-10-26 (B Jam accepted all eight) |

## 1. Stage-1 rows for B Jam's review (asked before his hardware test of stage 1)

These are new rows, or old rows with new wording. Each one is something stage 1 does on purpose that a comparison
would otherwise call a failure. **B Jam's answer of 2026-10-26 (after test build 5):** B26, B28, B29, B35, B36 and B38
approved as written, B30 retired (its path left with test build 5). B10, B17, B27 and B34 keep the status they had. **B
Jam's answer of 2026-10-27:** B10, B17 and B27 approved as written.

| id | what is different | compared with | from stage | why it stays |
|---|---|---|---|---|
| **B10** | Split. The status bits the 68000 reads stay compared with the chip from stage 1, except two: "music playing" (`$1FE6` bit 3) and the *set* half of bit 13 (the synth's frame work done). Only the cart's music engine writes those, and it arrives in stage 5. Until then stage 1 sets neither, as 0.2.6 did; they move to B12 | the chip | 1 | Doing them as the chip does needs the song engine. Keeping bit 3 clear matters: the game only posts a waiting song while bit 3 is clear. Approved as written 2026-10-27. Since test build 5 the stage-5 images set both bits as the chip does (test build 5's music lockstep: equal to the chip in 238 / 238 runs); the chip comparison of the stage-1 build keeps the two masks, as that build has no music engine |
| **B17** | Reworded. When the chip would reset only its MCU (the "WE SUX" backdoor, the watchdog with 81 bit 4, the end of a MegaWire update), ours holds the 68000 and restarts the firmware; the FPGA side (registers, window, FM view) keeps its state, as the cart's FPGA does. The old text said "our full cart reset" | the chip | 1 | No game code reaches any of the three. Approved as written 2026-10-27 |
| **B26** | The blank-save first boot's 84 now does what the chip does: after its 0.1 ms wait it turns the stream window and the FM game view off, points the 68000's reset vector at the mini-game (`$0006 := $8200`) and switches the watchdog off. 0.2.6 only turned the window off | 0.2.6 | 1 | It is what the chip does. Measured in the system simulation: window off 0.135 ms after the game's 8400 (the limit is 1.07 ms) **Approved 2026-10-26.** |
| **B27** | The watchdog can now stop the cart MCU: with the Pocket menu closed, if the game stops its once-a-frame tick for about 4 seconds, the MCU halts, as the real cart does. 0.2.6 had no watchdog | 0.2.6 | 1 | It is what the chip does (decided 2026-10-10). The menu stops it counting (B7); the mini-game's 84 switches it off. On a TEST image a halt writes the debug save, so a freeze log shows which side stopped first. Approved as written 2026-10-27 |
| **B28** | A word the chip does not know now gets the chip's answer: the "refused" status bit and its trace count. 0.2.6 printed "unknown" and did nothing. Mailbox A words other than the frame tick now go through the chip's mailbox A table too (0.2.6 never served mailbox A) | 0.2.6 | 1 | It is what the chip does. The game never sends an unknown word: all 37 commands it can send have a handler **Approved 2026-10-26.** |
| **B29** | Streams the cart's FPGA decodes itself (DA06 / DA07 from a 0x80-type source) are answered at once and decoded behind the busy bit, without the "job running" bit, as the chip does. 0.2.6 held the mailbox while it decoded. Since 2026-10-15 our FPGA does that decode (B38) | 0.2.6 (bits: the chip) | 1 | The chip's order. measured in the system simulation: 1,492 streams in 1,980 frames, none cut short, and the game played on to gameplay **Approved 2026-10-26.** |
| **B30** | The sound-effect feeder and the Boom Box bars run on a timer instead of 0.2.6's main loop. What the game asks for (which effect, which song) is compared strictly; the moment each sample is pushed is not | 0.2.6 | 1 to 4 | Stage 1 has no main loop. Goes away with the album in stage 5. Measured: no underruns in the buffer model; in the system simulation 3 one-tick gaps in 825 frames and 16 in 1,980, each under 0.1 ms **Retired 2026-10-26: the path left with test build 5.** |
| **B34** | Boot length before C6 only. **The cart's way since 2026-10-17 (B Jam's decision of 2026-10-16):** the game counts the frames it waits for C6 and starts its random-number table there; our C6 job now holds the "job running" bit for the game's 80 VBlank polls, counted on the video chip's own frames, so the game keeps count 94, the cart's (measured from B Jam's three CDX power-ons; 95 once). Still different: the time before the game asks for C6 (ours holds the 68000 until the MCU is ready), and a Pocket menu opened during the 1.3 s hold (the 68000 pauses, the video chip does not). **Test build S3a (B Jam's decision of 2026-10-30):** the start-up also reads the save slot table from the player's ROM while the 68000 waits (the cart reads it from its own memory and spends no such time): measured in the simulator, the game starts 95 ms later after power-on than on test build 5, with every picture of the start-up the same, and a Soft Reset waits 90 ms longer than before (98.8 against 8.7 ms). No speed-up is built. **From 0.3.0 the firmware is its own file** (B Jam's decision of 2026-10-29): after the Pocket's loading bar our core first checks the 256 KB firmware file and copies it into place, and only then starts the firmware. Measured in the simulator, that is about 0.15 s more black screen than with the firmware built in (146 ms against 0.8 ms), and the loading bar runs about 0.06 s longer for the extra file (an estimate: the Pocket's own load speed is not known yet). A Soft Reset costs nothing extra | the chip, timed | 1 | Proven on the RV32 board model with the game's own loop: count 94 at the recorded post time and 7 more, TEST and RELEASE, and at 60 post times across a frame (`tests/equiv/c6count.py`). Was: the game left its C6 wait 54 frames after asking (count 67-68). Test build S3a's start-up: **approved by B Jam on 2026-10-30** |
| **B35** | Stage 5: a frame tick that arrives while the previous song tick is still running. The chip skips that frame's sequencer step; ours finishes the tick under a deadline. Both keep the frame's sound packet | the cart's music engine | 5 | The two CPUs differ. Counted in the stage-5 comparison, never hidden **Approved 2026-10-26.** |
| **B36** | The PAL branches are there, as the chip has them, but never run on the Pocket (every Pocket build is NTSC) | the chip | all | Checked in the cart-music runner's PAL mode; MiSTer runs them **Approved 2026-10-26.** |
| **B38** | New (2026-10-15, with MCU interface v1.2: B Jam's "preservation" decision of 2026-10-15). The cart chip's sprite decoder hand-off is done as the chip does it: the same writes as the chip's list the frame's sprite blocks for the FPGA, our FPGA (the new RTL decoder) decodes them, and the reply to the game comes at once, as on the cart. What still differs from the cart: our FPGA puts the decoded words in our SDRAM workspace, where 0.2.6 put the same bytes (where the cart keeps them is not known), the firmware tells it where (one extra board write before each start), and a frame with nothing to load leaves the window pointer where it was (0.2.6 moved it back; the game reads nothing there then). Compared by what the game reads through the window, and the window may never be read before its block is decoded | the chip, 0.2.6 | 1 | It is the cart's own order, with the decode in hardware so the game never waits for it; B1 (the old "ours decodes in the MCU") is retired with it. B Jam's yes was needed for this row and for interface v1.2's six new registers (`docs/MCU_INTERFACE.md` section 4.9) **Approved 2026-10-26.** |

## 2. B Jam's decisions, now written on the list

B Jam decided these already. They are listed so a comparison does not call them failures.

| id | what is different | compared with | from stage | decided |
|---|---|---|---|---|
| **B5** | The MegaWire diagnostic screen is our rebuild from B Jam's photo: its drawing program and font were in the cart's bootloader, whose contents are not known | B Jam's photo | 3 | rebuild decided 2026-10-10 |
| **B7** | The Pocket menu: while it is open the music pauses where it is (and resumes there), the cart's sound effects are silent, and the watchdog does not count. Stage 5 pauses the song tick too. **Changed 2026-10-13:** the music part is live from stage 1, not stage 5 (a firmware-only change can turn it off without a refit: `CTRL.MENU_MUTE_EN`) | the chip | 1 | B Jam, 2026-10-09; measured in simulation (music pauses and resumes at the same place) |
| **B13** | Console-side stubs and options: TeraDrive (answers the game's video-RAM test, so the Boom Box shows the TeraDrive), the Mega CD units, TMSS on every all-in-one Mega CD unit (four units' Boom Box codes gain the TMSS bit against 0.2.6), 32X, 3-Player Mode (an EA 4-Way Play, there only when 3-Player Mode is On or Arcade Mode is Multiplayer; off, the controller ports are 0.2.6's) and 6-Button. Test build 4 (B Jam's decision 2026-10-16): 6-Button is a real six-button pad on the direct ports too (the game's own probe finds it; no B+forward-as-Z hybrid), an empty port reads as empty (no phantom player-2 pad), and each 4-Way Play slot reports its own pad, empty when no controller is there, so the Boom Box badges follow the controllers. Reworded 2026-10-13 for what stage 1 builds | the game's own checks | 1 | TeraDrive 2026-10-10; Arcade Off / On / Multiplayer 2026-10-10; 3-Player Mode 2026-10-11; TMSS per unit 2026-10-11 |
| **B24** | The FM instrument bank is served unscrambled to the sound CPU until the mini-game's 84, as the cart's circuitry does | 0.2.6 | 1 | B Jam, 2026-10-10 ("core circuitry") |
| **B25** | With Mega CD = None the cartridge no longer answers `$400000-$7FFFFF` (0.2.6 served the top half of the ROM there); the game still sees no Mega CD on every Console setting | 0.2.6 | 1 | B Jam, 2026-10-11 ("Keep it like the cart") |
| **B31** | The Scum! switches, as the cartridge serves them: Little-Man, Arcade Mode (On, and Multiplayer with three player slots), both stage-select pages, the 6-Button hook (test build 4: it no longer adds X / Y / Z / Mode on the two direct ports, where 6-Button is now a real six-button pad; the Arcade coin on Mode stays), the Hall of Fame fix (the switches' code moved out of the bar's tile data) and the Arcade coin (one credit and the game's coin sound per press). With every switch off the game's own bytes are served. Test build 4: our coin enters the game's first-coin gate, so the first coin after power-on or reset is ignored, as the cart with a Grand Stick III does (until test build 4 it counted). **Stage 5 (B43):** Arcade Mode and the coin move to the virtual Grand Stick III; the Arcade words, pad hook, cave and coin stub go, Little-Man, Stage Select and the flip point stay | the game's own code | 1 | Scum! 0.2.6; Hall of Fame move 2026-10-09; Arcade Mode 2026-10-10; coin sound 2026-10-11; first-coin gate 2026-10-16 (test build 4); Grand Stick III 2026-10-21 (B43) |
| **B32** | A byte the 68000 writes into cart RAM is stored on both halves of the word ("whole word"). 0.2.6 ignores such a byte; 0.2.0-0.2.5 stored only that byte, which tripped the game's cartridge check. What a real cart does is not known; whole word and ignore both pass the check | 0.2.6 | 1 | B Jam, 2026-10-11 (question Q2) |
| **B33** | The battery save is 8 KB, the size of the cart's EEPROM; the `.sav` file is 8 KB and a 0.2.x 4 KB save loads into its lower half. The game cannot see the size. Taking an 8 KB `.sav` back to 0.2.6 is untested | 0.2.6 | 1 | B Jam, 2026-10-11 (question Q1) |

## 2b. Added 2026-10-27 (stage 2's first commit), for B Jam's information

| id | what is different | compared with | from stage | status |
|---|---|---|---|---|
| **B47** | Our version of the cart chip's MegaWire work with no module attached (its start-up, its timer task, the A6 / A9 commands) comes in stage 3. Until then the chip comparison leaves out the status writes that code makes and counts them; the status words the game reads stay equal after every command, so the game sees no difference. The row was missing: the comparison already did this since stage 1 | the chip | 1 to 2 | the plan's stage 3. measured since stage 1 (the chip comparison): the words the game reads equal after every command |
| **B48** | The game can ask the sprite engine for up to 53 VRAM slots (EC $35). The cart chip's command check would also take 54 to 128, but its slot table ends at 53: above that the chip ages nothing, and a later smaller count makes it read and clear part of the first sound-effect channel's memory (working memory, not the ROM, so it cannot be read from the player's ROM). Ours keeps such a count to 53, as test build 5 already did. The game never asks for more than 53 (all 24 places in its code that send this command ask for 1 to 53) | the chip | 2 | **approved** 2026-10-28 (B Jam: "since the game never asks for more"); test build 5 had the same rule without a row |

## 2c. Added 2026-10-28 (stage 2's repair), B Jam's decision

| id | what is different | compared with | from stage | status |
|---|---|---|---|---|
| **B52** | Each sprite names an object (the game has 241, numbered 0 to 240). When the game queues a next animation, the cart chip checks it against that object's animation count, looked up in a 256-entry list. For an object number of 256 or more it reads past the end of the list, into its own working memory, and takes or drops the queued animation depending on whatever byte is there. B Jam chose to do what the chip does: ours now reads the same bytes for object numbers 256 to 267 (the chip keeps three of its own values there, and ours holds the same ones). From 268 on the chip's bytes are other live memory ours does not keep in the chip's order, so ours reads 0 and drops the animation there. Measured on 515,910 such commands: 1,364 differ, all at 268 or above, none at 256-267. The game never does this | the chip | 2 (256-267 as the chip from stage 3) | **decided** 2026-10-28 (do what the chip does); the part from 268 on **approved** 2026-10-29 (never reached in play) |

## 2d. Added 2026-10-28 (stage 3, test build S3a), B Jam's decision

| id | what is different | compared with | from stage | status |
|---|---|---|---|---|
| **B53** | The intro's SEGA CD zoom and the other zooms. From stage 3 the zoom works as the cart chip's (F4, F5, B6): the scaled logo the game copies out of cart memory `$0200-$09FF` is the chip's, and B6 puts back what was there before the zoom, as the cart does (0.2.6 never did). So that memory is now checked against the cart chip, not against 0.2.6. One corner the game never uses: a zoom step whose rows would reach past the chip's zoom memory (more than 4 KB on) makes the cart chip read and write its own sprite memory there; ours reads 0 and writes nothing. Measured on all 860 zoom steps of the recorded games: they reach at most byte 2,047 of 2,048, so they all match the chip in every byte | the chip | 3 | as the chip; the corner past the chip's zoom memory **approved** 2026-10-29 (the same kind as B48 / B52: the chip's own working memory, not the ROM; never reached in play) |
| **B54** | A corner of the unpacking the game never uses. The cart chip's unpack command accepts a stream type (0x82) that it then copies nothing from; afterwards it swaps the bytes of a length left over from earlier work (it depends on how often the chip's main loop has run). Ours writes nothing. Measured: no stream in the game is of that type (every unpack the recorded games ask for, all 53 music entries and all 12,326 sprite blocks are of the two other types), so the game never reaches it | the chip | 3 | **approved** 2026-10-29 |

## 2e. Added 2026-10-29 (stage 3, test build S3a), B Jam's decision

| id | what is different | compared with | from stage | status |
|---|---|---|---|---|
| **B55** | After a Console Reset early in the boot the screen stays black for a shorter time than on B Jam's cart. Measured here for presses 3.9 and 4.0 s after power-on (about 3.4 s into the fake licence): about 2 s black (120-126 frames). B Jam's cart, pressed 3.9-4.0 s into its fake licence: about 6.5 s (392 frames). A press at B Jam's cart's exact point (about half a second later here) was not run, so the black there is not measured. We think the cart's chip is still busy with its start-up work at that moment while ours already has the sound from the boot cache, but that is our reading, not a measurement. In both, the NX terminal then comes about half a second before a normal start. Measured on the current firmware up to shortly after the terminal (frame 460); that the game then goes on as after a normal start (to frame 680) was measured on the two earlier firmware builds only (test build S3c's and the one of stage 3's unpack step), which give the same pictures as the current one up to frame 460. Where a Reset locks and where it restarts stay the cart's | B Jam's cart (his video capture F3) | 3 | **approved** 2026-10-29 ("Keep our console resets no need to chase cart accuracy for that") |

## 2f. Added 2026-10-30 (stage 3, test build S3a), B Jam's decision

| id | what is different | compared with | from stage | status |
|---|---|---|---|---|
| **B56** | Where the sprite animation data sits. At start-up (C6) the cart chip unpacks the game's animation data at the start of its own memory; ours unpacks it at the place 0.2.6 used, a little further in. The data itself, the per-object animation counts and the sprite block list equal the chip's in every byte (measured). The game never reads that memory directly, only through the commands that name their own places | the chip | 3 | **approved by B Jam on 2026-10-30** ("Approved") |
| **B57** | A zoom command fed something that is not a zoom picture. The cart chip's zoom start-up command (F4) accepts any packed picture; one that unpacks to more than its 4 KB zoom memory makes the chip write on into its own sprite memory. Ours writes the same bytes into the zoom memory and stops at its end (before this check, ours wrote on over its own memory and could crash). Measured: every zoom the game starts (29 in the recorded games, 4 pictures) unpacks to exactly 2 KB, inside the zoom memory, so the game never reaches this | the chip | 3 | **approved by B Jam on 2026-10-30** ("Approved") |

## 2g. Added 2026-10-30 (stage 3, test build S3a), B Jam's decision

| id | what is different | compared with | from stage | status |
|---|---|---|---|---|
| **B58** | A sprite upload list nobody clears. Each frame the game asks the cart for a short list of sprite uploads and clears the list after the console has done them, so it never holds more than 17. If a list were never cleared it would grow on, past the end of the cart memory the cart chip is allowed to write; the cart chip then writes on into the cart's own hardware (what that hardware does with it is not known), and ours used to crash there. Now ours writes nothing past that end; everything else about the list stays as the cart does it. Found by the check of every command; the game never does this (measured on the recorded games) | the chip | 3 | **approved by B Jam on 2026-10-30** ("Approve B58 as a difference from the chip; the game never reaches it") |

## 2h. Added 2026-10-31 (our MegaWire port joined to this firmware), B Jam's decision

| id | what is different | compared with | from stage | status |
|---|---|---|---|---|
| **B59** | The MegaWire menu's restart command. When the game sends it (AA58), the cart chip restarts its MegaWire code at once and saves the MegaWire record (the network name and password it would have stored) to the cart's memory. Ours restarts the MegaWire code at its next regular run, at most about a tenth of a second later, and saves no record (that part is not built). Measured with the check of every command against the cart chip: the command and everything after it behave the same, except for the record the cart saves. The game sends this command only from its MegaWire menu, which needs a MegaWire module plugged into the cart; the Pocket never has one | the chip | 3 | **approved by B Jam on 2026-10-31** ("Thats fine allow") |

## 2i. Added 2026-10-27 / 28 (test build S3b: B Jam's answers on the MegaWire server name and on two more rows, 2026-10-28)

| id | what is different | compared with | from stage | status |
|---|---|---|---|---|
| **B49** | The MegaWire's network text is not built yet: the request line around the server name (36 bytes), the web request the cart writes for a game message such as the attract-mode one (or for the MegaWire menu's sign-in message, the same memory) (167 bytes plus two for each byte of the message: 193 for the attract message, at most 669, and what is left of a longer earlier request, since the cart does not clear that memory in between) and its two-byte length. Only a module would ever read them. The text is the cart's own, so it is never typed into our source; when the module part is built it will be read from the player's ROM at start-up. The comparison leaves exactly these bytes out, sized by the cart's own length for each request, and counts them; our side must not write there at all | the chip | 3 | approved by B Jam on 2026-10-28 (his decisions of 2026-10-27 and 2026-10-28), incl. the sign-in request's server name |
| **B50** | Two pointers inside the MegaWire's memory hold a position in our own MegaWire memory, where the cart's chip holds its own memory address. They point at the same bytes, and those bytes are compared; only code on the MCU reads the pointers, the game cannot | the chip | 3 | **approved** 2026-10-28 |
| **B51** | The MegaWire server name is ours, www.koalakoa.com, where the cart names its own server (B Jam's answer of 2026-10-27). It is the name the MegaWire start-up stores for the module (25 bytes of chip memory; only the module would ever read it). The bytes our music engine reads just past the end of its note table, where the cart's chip happens to keep its server name, are not covered here: they are the cart's own bytes, read from the player's copy of the game at start-up (B Jam's decision of 2026-10-30), and compared exactly. Everything else of the MegaWire is compared exactly, except the two rows below and B59 (the MegaWire menu's restart) | the chip | 3 | **approved** 2026-10-27; narrowed 2026-10-31 to the start-up's name only |

## 3. Approved earlier, unchanged

| id | what is different | compared with | from stage | status |
|---|---|---|---|---|
| **A1** | Debug output of TEST builds (and, from stage 1, the debug save in the upper half of the 8 KB `.sav`, `0x1000-0x1FFF`; RELEASE writes nothing there) | TEST against RELEASE | 0 | applied in stage 0; the stage-1 save range corrected 2026-10-13 |
| **A2** | The MegaWire status bits against the old test3 build (a 0.2.6 test build; test3 wrote a fixed 7) | test3 | 0 | measured, the only test3 difference |
| **A3** | How the RISC-V and the PC print text (a harness detail, not a firmware difference) | host against RV32 | 0 | measured |
| **A4** | The album and the sound-effect feeder are compared at the call (which effect, which argument), not inside | 0.2.6 | 0 to 4 | measured equal at the call |
| **A5** | The Boom Box bars and the millisecond clock the PC-side harness cannot produce | host against board | 0 to 1 | measured |
| **B1** | The cart's FPGA decodes sprite blocks; ours decodes them in the MCU. Compared by what reaches the video chip. **Proposed for retirement on 2026-10-15**: our FPGA decodes them too (B38) | the chip | all | 0.2.0; retired 2026-10-27 (B Jam's yes): B38 replaces it |
| **B2** | The busy bit the game polls is made in our FPGA logic (the cart's FPGA makes it too); only the order of its changes is compared | the chip | 1 | B Jam, 2026-10-11 |
| **B3** | Our boot-page and ROM patches (the cart's bootloader and FPGA do the real thing; their contents are not known) | the chip | all | in force |
| **B4** | Our stream path for DA / DB / F2: compared by the bytes the game reads through the window | the chip | all | in force; narrowed 2026-10-15, approved 2026-10-27: F2 and the 0x80 DA06 / DA07 streams are under B38; B4 keeps DA02, the 0x81 / 0x82 DA07 jobs and DB |
| **B6** | The Console option stands in for the cart's own console sensing in the word the game reads once at boot; MegaWire On is a labelled difference, but only in the builds without the MegaWire port: from test build S3b, On runs our MegaWire port as Off does (B Jam's MegaWire decision, updated 2026-10-27: On looks exactly like the cart), so that part is compared exactly there | the chip | all | B Jam, 2026-10-11; the MegaWire part narrowed 2026-10-28 (stricter) |
| **B8** | Random values in the music engine: injected in tests, matched in play | the cart's music engine | 5 | plan |
| **B9** | How long replies and jobs take (measured separately; our DA job is slower, so DA loads still pause the frame until a faster job lands) | the chip, timed | 1 | measured separately; stage 5's song start (B39's queue: 0.6-2.8 ms after the estimated cart time, no real song start in B Jam's captures differs) **approved** 2026-10-26 |
| **B11** | Saves in the cart's own format plus a one-time import of 0.2.x saves. **Built in stage 3 (test build S3a):** the game's saves are kept as the cart keeps them (two copies of each, the same checks, the same scrambling, the same choice of which copy to read and which to overwrite), equal to what the cart chip's save routines do in every test case; the list of where each save goes is read from the player's game ROM when the core starts. A save made with 0.2.x (or test build S2) is converted once, the first time test build S3a starts with it, into what the cart would have written; after that it is never touched again. Still different: the cart's save chip is slow to write, ours is instant | the chip | 3 | locked; built in stage 3 |
| **B12** | The album and the sound rows not yet done as the chip does them (until stage 5), now also the two status bits from B10. **D31 and the sound-effect laws as the chip's (2026-10-17, B Jam's decisions of 2026-10-16):** a sound loops only when the game sets the loop flag at its start (no more D3 re-arm), the flag no longer slows a looped sound by 1/32, D1 and D3 volumes follow the chip's level table (the punk TV 5 dB quieter, as the cart), D2 with a step fades and then stops. Equal to the cart program frame by frame in six scripted cases. **The sound-effect channels as the chip's (2026-10-19, after the Block 888 cell alarm B Jam found):** a sound takes the channel the chip gives it (a free one of its mask, else the quietest or furthest along, never one outside the mask; 0.2.6 put it on channel 0, where the exit's stop never reached it), the echo voice and the two-sided spread the game asks for, the retrigger, the start delay and the 0x0100 rate step as the chip does them, and D5 leaves the channels alone. Equal to the cart program frame by frame on seven corpora, the Block 888 runs and the six cases. Still ours: the filter on the echo and spread voices, the pan law, D5's echo itself (the RTL has none), and when the mixer's blocks fall (the RTL's lowest rate is the chip's 4,800 Hz since test build 4: 48,000 / 10, the RTL of 2026-10-19). **Stage 3 (test build S3a):** 83, the game's check of the console's frame time at the boot, now measures and refuses as the cart chip does (equal to the chip in all 195 test cases); the chip then also fine-tunes its own clock, which ours does not need (it runs on the console's clock), so that part stays here. **Corrected 2026-10-30:** the four words at cart RAM $1C00-$1C0F (a running count and three of the chip's own memory addresses, which ours leaves at zero) are written by the cart chip's main loop every time it goes round, after its Boom Box update, not only after the commands this row named before. They are leftover bytes of the chip's own memory: its Boom Box update copies 64 words but fills only 56. Measured: the game never reads them and behaves the same whatever they hold (not known only for code a real cart supplies from outside the game's ROM), **approved by B Jam on 2026-10-30** | the chip | 0 to 4 | the plan; the two `$1FE6` bits from B10 approved 2026-10-27: on the stage-5 images they are the chip's (B10) |
| **B14** | Sprites. **Since stage 2 (2026-10-27) every sprite rule works as the cart chip's** (core/sprite): the restart rule (D19), the 50 Hz skip (D39, which never runs on the Pocket's 60 Hz), B1 leaving SAT entry 0 alone (D47), the AD index refusal (D48), the slot layout at every slot count (D49, Arena and 3-player Arcade's EC $34 included), and even the frame end the game never asks for (AF03 over 80 entries). Nothing about sprites differs from the cart chip in anything the game sends (B48 and B52 are two inputs it never sends), and the chip comparison holds every sprite word to the chip with no allowance. The row stays only so the comparison with 0.2.6 can count where 0.2.6 drew differently (the cart's flicker in 80+ scenes, the cart's palette lines, entries above and below the screen) | 0.2.6 (the chip strict) | 1 | a change of reference only; no chip difference |
| **B15** | Every Pocket reset type equals a power cycle | the chip | 1 | B Jam, 2026-10-11 |
| **B16** | No 68000-only console Reset on the Pocket | the chip | 1 | B Jam, 2026-10-11 |
| **B18** | The warm-start path and the "boot into the MegaWire screen" bit never happen on ours | the chip | 1 | B Jam, 2026-10-11 |
| **B19** | A MegaWire update never writes the ROM | the chip | 3 | B Jam, 2026-10-11 |
| **B20** | Header bytes `$1E4 = $FF00` (as both real sources hold); the hold-B line shows the ROM's own digits and letters on every Console: the letters belong to the cart (B Jam's pink US cart prints the ROM header's region letters unchanged in a US CDX and a JP LaserActive), so the per-Console letter switch (BOOT-07) is gone | 0.2.6 | 1 | B Jam, 2026-10-11; BOOT-07 dropped 2026-10-16 |
| **B21** | The stream window is off from reset (0.2.6 had it on), so the boot text page's last tile comes from the ROM | 0.2.6 | 1 | B Jam, 2026-10-11 |
| **B22** | The protection view (the cart's guard against reading its ROM out) and the boot stub are not served; the boot patches stand in | the chip | 1 | B Jam, 2026-10-11 |
| **B23** | The bootloader's hand-off block comes from our board layer | the chip | 1 | B Jam, 2026-10-11 |

## 4. Where the three old copies went

The three old copies were in our planning notes (not in this tree); their items are named here by their old ids
(D-numbers from our firmware audit, G-numbers from the plan's list).

| old copy said | row now |
|---|---|
| D43, sprite blocks decoded by the MCU | B1 (since 2026-10-15: B38) |
| D44, the busy line (v2 timing) | B2 (now made in FPGA logic) |
| D45, boot-page patches | B3, B22 |
| D46, our stream path | B4, B29 |
| the A858 MegaWire pages | B5 |
| the Console model and MegaWire bits (G1) | B6 |
| the Pocket menu pause (G4) | B7 |
| random values (G9) | B8 |
| reply and job timing (G10) | B9, B34 |
| the completeness check's deliberate differences: reset behaviour on the Pocket; the busy bit's source; MegaWire On; boot length; song-tick overlap; PAL; the 83 trim; the stream path; the menu mute; our boot patches | B15-B18; B2; B6; B34; B35; B36; B12; B4; B7; B3 |
| the later decisions on no copy: TeraDrive stub; unscrambled FM bank; watchdog gate; Scum! / Hall of Fame ROM changes; Arcade Mode Multiplayer; rebuilt MegaWire screen | B13; B24; B7 and B27; B31; B13 and B31; B5 |
| added since: 3-Player Mode; whole-word byte writes; 8 KB save; TMSS on all-in-one units; menu music mute; Mega CD None not answering | B13; B32; B33 and A1; B13; B7; B25 |

## 5. Not on this list on purpose

- **The "MegaWire 4.0" logo in the no-input intro.** It is not a difference: it is the game's own credit screen, and
  B Jam's original cart shows it with no MegaWire attached (2026-10-13). Nothing to allow.
- **Anything a real cart does that its ROM image does not show** (bootloader timing, the FPGA's own decoder, EEPROM
  behaviour, the sound output stage): the "outside the chip" list in the plan (not in this tree).
