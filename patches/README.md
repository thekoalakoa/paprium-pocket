# Firmware patches against krikzz/mega-ppm

`mega-ppm-pocket.patch` applies to a clean clone of
[krikzz/mega-ppm](https://github.com/krikzz/mega-ppm) and produces the firmware
this core ships in `rtl/PAPRIUM/mcu.txt`.

```bash
git clone https://github.com/krikzz/mega-ppm.git repos/mega-ppm
cd repos/mega-ppm && git apply ../../paprium-pocket/patches/mega-ppm-pocket.patch
cd ../../paprium-pocket && ./scripts/build_mcu.sh
```

`build_mcu.sh` installs into `rtl/PAPRIUM/mcu.txt` itself and reports whether the
firmware actually changed. It used to only print that path as a "reference build
for comparison", which cost a full Quartus fit built against stale firmware - see
docs/BUILD_REFERENCE.md.

The patch is kept here rather than the built binary alone because GPLv3 asks that
a distributed binary come with its corresponding source, and `mcu.txt` is a
compiled work. This is the source of our changes to it.

## What it contains

**`sfx.c` — re-arm a channel that has already finished (ours).**
`sfx_player_update()` skips any channel with `size == 0`, so the loop restart at
the bottom of its own loop is unreachable once a sample has ended. `sfx_play()`
clears `looped`, and the game enables looping *later* — the punk-TV cue starts at
volume 0 and is only looped and ramped up as the player approaches, by which time
the 4.99 s sample has run out and the channel is dead. Measured on hardware:
29,920 PCM words pushed (exactly the sample length), FIFO empty, then the volume
ramp climbing 0x00 → 0xC0 with nothing playing.

**This is a general fix, not a punk-TV one.** It re-arms *any* channel that has
already ended when looping is enabled on it, so every cue the game starts quiet and
loops up by proximity benefits. Confirmed on hardware: **all** punk TVs now play,
not only the two used to find the bug — and the looping area ambience (`0x4B`, the
subway trains) was broken the same way and is fixed by the same change.

**`mame.c` — real LZO decoder for format `0x81` (ported from Genesis Plus GX).**
Stock mega-ppm carries MAME's reverse-engineered heuristic, whose loop terminates
on `!= 0x11 // unconfirmed end code`. It mis-decodes and corrupts the subway among
other areas. Ported from GPGX's `paprium_decoder_lzo`, adjusting the cursors:
GPGX's `size` is the absolute output position, which here is `dest_addr`, so its
`lz = size - lz` becomes `copy_addr = dest_addr - lz`. krikzz fixed this privately
for MisterPezz82; the public tree still ships the broken version.

**`mame.c` — first-level door fix (krikzz's, re-applied).**
Object 107's sprite 4 is the Block 888 door and composes with palette bit `0x2000`
set, rendering in the wrong colours. Reported by MisterPezz82 as
"object 107 sprite 4, `attr &= ~0x2000`" and shipped in their V.05.

**`paprium.c` / `mdp.c` / `mdp.h` — one-shot music cues.**
`cmd_8C_bgm_play` treats bit 7 of its argument as "loop", and stock mega-ppm calls
`mdp_stop()` when it is clear — so Stage Clear, Continue, Game Over, High Score
and Ending are silent. Captured on hardware: `cmd_8C` track `0x35` (53) with bit 7
clear at the end of a stage, and 53 is one of the tracks the cue sheet marks
`REM NOLOOP`. Adds `mdp_play_once()`, sending MD+ `$11xx` (`MDP_CMD_PLAY_S`),
which this core's `paprium_mdp_adapter` already decodes as `track_loop = 0`.

**`paprium.c` — implement `0x88 audio_setting` (ours).**
Stock mega-ppm maps it to `cmd_unknown_muted` with the comment "set audio config",
so the game writes its audio configuration and reads back stale memory. GPGX
implements it (`paprium_audio_setting`): the DAC selection — the in-game "VM DAC"
option, choosing the YM2612 DAC over the cartridge's own — and the NTSC bit are
stored at cart RAM `0x1800`/`0x1801` for the game to read back. Observed on
hardware firing five times during boot with arguments `0x02` and `0x0A`.

GPGX's byte indices transcribe verbatim, which is correct rather than lucky:
`ramdp_io.sv` places a 68000 byte at address A into MCU byte `A^1`, and GPGX's
`ram[]` carries the same relationship, so the two agree.

**`paprium.c` — Boom Box VU bars (ours).**
Cart RAM `0x1B98..0x1BFF` is a per-voice stereo level feed: 26 voices of
`{u16 L, u16 R}` = 104 bytes, ending exactly at `0x1C00`. On hardware the
cartridge's music engine rewrites it every row with "does this voice have a
pattern this row" — GPGX's interpreter does the same at `paprium.h:472-473`
(`index ? 0xE0 : 0`) — and the Boom Box draws its 26-bar graph straight from it,
one bar per voice. Confirmed against a hardware capture: the graph has 26 bars.

This core substitutes CDDA and never sequences the module, so **nothing wrote
that window at all** and the game drew its bars out of uninitialised cart RAM —
they sat permanently lit. The neighbouring `0x1802..0x19FF` fill in
`cmd_88_audio_cfg` stops at `0x1A00` and never reached it.

Rather than smear one playback level across 26 identical columns, the bars are
driven from the module `cmd_8C_bgm_play` **already unpacks and then discards**,
so they show the real per-voice arrangement at the module's own tempo, and cost
no RTL. MWMM header `0x07` is frames per row (1..6 across the 52 modules), so a
row lasts `0x07/60` s; verified on hardware — Stage Clear is 105 rows with
`0x07`=3, giving 5.25 s, matching a Boom Box capture exactly.

The row tick lives in `ppm_start()`'s loop, which runs far faster than 60 Hz, so
at most one row advances per call and a carried millisecond remainder keeps the
grid from drifting. `cmd_8D` parks the bars on stop.

**`mame.c` / `mame.h` — dropped weapons spin forever instead of settling (ours).**
An enemy drops a knife `0xDC`, electric stick `0xDE` or pipe `0xE0`. It should
land and take its ground pose; instead it kept spinning. `PPM_CHAIN_ONLY_AT_END`
(0.2.1) takes a queued follow-up only at a TERMINAL end (loop target 0), and
measured across 12 minutes of captured play that fires on **0 of 821** queue
requests — every animation the game ever arms a follow-up on loops. In practice
the rule is "never chain". Turning it off lands the items and regresses the
character walk-in to moonwalking; both confirmed on hardware, in both directions.

What separates the two cases is WHEN the game arms the queue, relative to the
animation it arms it on:

| | animation | ends at frame | queue armed at | on an end |
|---|---|---|---|---|
| weapon fall `anim 8` | 25 frames, loops to index 1 | 49, 73, 97 | **49** | **11 of 11** |
| player walk-in `anim 9` | 49 frames, loops to index 1 | 49, 97, 145 | 5, 17, 18, 19, 80, 116 | **0 of 31** |

The game arms `nextAnim` **on the frame the animation finishes** when it means
"switch now", and mid-cycle when it is only a standing fallback it will resolve
itself with a later direct `setAnim`. So `PPM_CHAIN_FRESH_QUEUE` takes a queued
follow-up at a looping end only when the queue was armed at that end. This
firmware detects the end one call LATER than Genesis Plus GX does — it keeps the
frame just drawn and advances at the top of the next call — hence
`PPM_CHAIN_FRESH_WINDOW 1`; the result is identical for any window from 0 to 4,
and the nearest a walk-in arming ever comes to an end is 17 frames.

Verified by replaying this firmware's own `ppm_obj_render` against four winlog
captures, 5,558 object episodes: **11 of 11 weapon chains fire, 0 chains out of
`anim 09`.** Then on hardware: items settle and stir, walk-ins keep walking, no
despawn change.

**That was only one of the three places the game arms a queue (0.2.5).** Users
reported knives `0xDC`, chains `0xDD`, neon sticks `0xDE` and pipes `0xE0` still
spinning when the PLAYER is knocked down, and the reason is that a window around
an end catches exactly one arming pattern. Measured over 721,736 object records:

| where the queue is armed | what it means | age when the animation ends |
|---|---|---|
| **AT-LOAD** — the same call as `setAnim(N)` | "play this, then that" | the animation's whole length |
| **AT-END** — on the frame it finishes | "switch now" | 0 or 1 |
| **MID** — mid-cycle | character: a transient the game resolves itself; item: a handover it never returns to | 2 and up |

AT-LOAD can therefore *never* satisfy a window of 1: the end is a whole animation
away by construction. It is not a corner case either — item `0xE3` uses it for its
ground stir (35 armings), and so does the player's own idle fidget, `obj 01 anim
02`: 30 frames, queued back to the stance, after which the game leaves the object
alone for 212 to 1,067 draws. This port loops that fidget about 22 times instead
of playing it once. `PPM_CHAIN_QUEUE_AT_LOAD` remembers one bit — was the queue
armed on the draw that loaded this animation — and chains at that animation's end.

`PPM_CHAIN_STALE_QUEUE` is then the safety net under both, because the reported
case is a drop path no capture contains, and a rule that only fires on a pattern
nobody has measured is a guess. What separates the two MID cases is how long the
game leaves the queue standing, and the separation is clean:

| | queue reaches an animation end at age | queue lifetime | how it ends |
|---|---|---|---|
| characters `01`/`02`/`03` | 2 to **41**, and 1,946 of 1,950 at 33 or less | ≤ 42 draws | the game sets `anim` itself |
| dropped items | 48 to 255 | 82 to 458 draws | never — the object is gone first |

The whole character tail above 28 is one animation (`3A`), whose queue the game
always resolves by draw 42; nothing at all lands between 42 and 47. The threshold
sits at **64**, half again above every character queue ever measured and below
every item handover, so a weapon dropped by ANY path settles at the next end past
that age whatever its arming looked like. What justifies a net this wide is the
hardware record: turning chaining off at looping ends entirely settled every
weapon and moonwalked the walk-in, and the ends that regression fired on are all
at ages 2 to 47 — exactly what this threshold excludes.

This is NOT the frame clock refuted below. That one counted frames since the
animation started and fired without an end; this one counts draws since the QUEUE
was armed and fires only at an end. The walk-in `anim 09` is untouched by it in a
way the measurement makes explicit: across 64 armings its queue stands for 1 to 3
draws and **never reaches an animation end at all**.

Replaying `ppm_obj_render` against all five captures, 6,688 object episodes: 45
weapon/item chains, and no chain out of `anim 09` except the one at-end chain
0.2.4 already took and hardware confirmed. One more implementation bug went with
it: `queue_age` lives in a per-SLOT handle and was not reset when a new object
took the slot, so a weapon created with its follow-up already armed inherited the
previous tenant's age and could never chain.

**The game's animation protocol**, decoded from `setAnim` at ROM `0x031024` and
worth having written down: bit 14 of the argument QUEUES (writes `+0x02`), a plain
value SETS NOW (writes `+0x00`, raises `+0x0A`, clears `+0x02` to `0xFFFF`), and
bit 15 forces a restart. It never writes `+0x04`, so `objID` bit 15 marks object
creation only. A corollary this firmware relies on: the game never changes `anim`
without raising `reset` in the same call.

**Refuted first, recorded so they are not retried.** The frame-word flag bits
(bits 24-30) are a VRAM streaming hint — their low nibble is the count of
graphics blocks a pose adds that the previous pose did not, matching 24,764 of
24,893 pose boundaries (99.48%); "weapons 0/1/2, characters 3-7" is only sprite
size. `obj_data+0x06` is mutable nibble-packed game state and the knife carries
`0000` in one drop and `2233` in another. Movement while armed is backwards — the
player's walk moved 0.0% of samples and the knife 13.2%. Matching Genesis Plus GX
is not an option either: it chains at every looping end and therefore moonwalks
the walk-in as well, proved by matching its logged graphics blocks against the
ROM's per-frame art. And "chain only for the object's spawn animation" fails
because a dropped knife is not spawned falling — it is created on the ground at
`anim 1` and the game calls `setAnim(8)` when it is knocked loose; 38 of 42
weapon objects spawn already grounded.

**A frame clock was tried first and is wrong.** Waiting N frames for the game to
set the animation itself fires on that same 295-frame walk-in and puts the
character back into its sliding standing pose — the exact bug 0.2.1 fixed. So was
`PPM_CHAIN_TARGET_TERMINAL` (0.2.3), which required the QUEUED animation to be
terminal: it shipped, changed nothing on hardware, and was reverted. Both are
recorded here so they are not tried again.

## Not yet re-applied

- **Field-wise sprite attribute composition** — MisterPezz82's V.04/V.05 change,
  explicitly recorded in their own notes as harmless but *not* an elevator fix.
  Low value, so not carried over.

## Build notes

- `-march=rv32im_zicsr_zifencei`: GCC 15 split CSR and FENCE.I out of the base ISA.
  krikzz's Makefile says plain `rv32im` because his compiler folded them in.
- Built at `-O2`. MisterPezz82 used `-Os` to fit 16 KB; this core grew its IMEM to
  32 KB instead, because the MCU services the 68000 in real time and upstream
  attributes the elevator corruption to MCU starvation — trading its speed for
  space aims at the part already suspected of missing deadlines.
