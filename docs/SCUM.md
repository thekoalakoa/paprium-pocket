# Scum! and the 0.2.6 menu options

0.2.6 adds eight entries to the core's settings menu. Four of them are what this project calls
**Scum!**: switches that change the game while it runs (Little-Man, Arcade Stage Select, Arcade Stage
Select 2, 6-Button). The other four change the machine the game thinks it is running on (Console,
Mega CD, 32X Mode, MegaWire), and one of those, Mega CD, is what brings the game's **CPU MATE** partner
to the Pocket. The menu shows the names without a "Scum!" prefix.

Everything is off by default. With the defaults the 68000 reads the unmodified ROM, and the Console
default (Mega Drive) is the machine every earlier release presented. The one deliberate difference is
MegaWire: off now means nothing plugged in, as on a real cartridge, where earlier releases reported a
MegaWire connected.

This page is the how and the why. The short version for players is in the README.

0.3.0 was made in numbered stages (stage 5 is the one that brought our own song engine and synth), and a "test
build" is one of the builds B Jam tested on his own Pocket along the way (test build 4 came before stage 5). Both are
named below where they changed a switch.

| Entry | Bridge | Values | Takes effect |
|---|---|---|---|
| Little-Man | `0x30` | mask: 1 Health, 2 Pills, 4 Lives (Off, Health, Pills, Lives, Health + Pills, Health + Lives, Pills + Lives, All Three) | at the game's next pad read (within a frame in play) |
| Arcade Mode (0.3.0) | `0x5C` | 0 Off, 1 On, 2 Multiplayer, 3 Stick Only (stage 5: the Grand Stick III, below) | at the next Soft Reset |
| Arcade Coins (0.3.0 stage 5) | `0x64` | 0 1 Coin 1 Credit, 1 2 Coins 1 Credit, 2 Inf. Credits (0012) | at the next Soft Reset |
| Attract Only (0.3.0 stage 5) | `0x68` | check, default off | at the next Soft Reset |
| Arcade Stage Select | `0x40` | 0 Off, 1-15 = Block 888 .. Aquaworld | at the next Soft Reset |
| Arcade Stage Select 2 | `0x48` | 0 Off, 16-24 = Blue Bar .. The Solarium, 25 = Arena | at the next Soft Reset |
| 6-Button | `0x44` | check | at the game's next pad read (within a frame in play) |
| 3-Player Mode (0.3.0) | `0x60` | check, default off | at the next Soft Reset |
| Console | `0x54` | Mega Drive 0, Genesis 1, Mega Drive 2 2, Genesis Model 2 3, Genesis 3 4, Nomad 5, Mega Jet 6, TeraDrive 8 (0.3.0), Unknown 7 | at the next Soft Reset |
| Mega CD | `0x50` | None 0, Mega-CD / Sega CD 2, Mega-CD 2 / Sega CD 2 3, Wondermega 4, Wondermega M2 / X'Eye 5, LaserActive 6, Aiwa CSD-GM1 1, CDX 7, Unknown CD 8 | at the next Soft Reset |
| 32X Mode | `0x4C` | check | at the next Soft Reset |
| MegaWire | `0x58` | check, default off | at the next Soft Reset |

The Pocket's menu is flat: no submenus, at most 16 entries, names of at most 23 characters and at most
16 choices in a list (Analogue's `interact.json` rules). That is why the stages are two lists, and why
Little-Man is one list of every combination rather than three checks.

**Little-Man** is the cheats entry. It was called Cheats while 0.2.6 was being tested; the id, the bridge
address and the values did not change, so a setting saved under the old name carries over.

---

## Scum!: the switches

### What they do

- **Little-Man, Health**: players take no damage. With it on, a player's throws do no damage to enemies: one of
  the cheat's patches sits in the game's throw-damage routine, which only throws and thrown bodies use, so a
  thrown enemy keeps all its health. Every other hit on an enemy does full damage, and enemies die as usual.
- **Little-Man, Pills**: using a Blu pill (Down + A) does not spend one.
- **Little-Man, Lives**: dying does not spend a life.
- **Arcade Mode** (0.3.0): **On** switches on the game's hidden ARCADE PAPRIUM mode (credits and friendly fire);
  **Select inserts a coin**. **Multiplayer** is On with three player slots. With Arcade Mode on, the game hides
  ORIGINAL and ARENA from its menu (the title goes straight to the district map); that is the game's rule. Read at
  boot, so Soft Reset after a change. **0.3.0 stage 5 (B Jam's decisions of 2026-10-19 and 2026-10-21):** On, Multiplayer and the new
  **Stick Only** plug a virtual **Grand Stick III** into port 1 (below), and the game runs its own arcade code from
  the stick's switches, on the unpatched ROM: On = the ARCADE switch, Multiplayer = ARCADE + 3 PLAYERS (a third
  player on Dock controller 3, in the stick's EXT socket), Stick Only = a stick with every switch off (the normal
  game, as with B Jam's own stick). **Arcade Coins** (1 Coin 1 Credit, 2 Coins 1 Credit, **Inf. Credits (0012)**)
  and **Attract Only** set the stick's other switches while Arcade is On or Multiplayer. Inf. Credits makes the game
  stop on its red 0012 screen at boot, by design: that is what the game does with that switch (B Jam's own stick
  does the same). Until stage 5 Arcade Mode was a ROM patch (adroxe's two `nop`s), a pad hook for the coin and,
  for Multiplayer, a third `nop` and the EA 4-Way Play.
- **Arcade Stage Select**, pages 1 and 2: the stage Arcade Mode starts on. 0.3.0: they only pick the stage, and
  only while Arcade Mode is On or Multiplayer (in 0.2.6 choosing a stage also switched Arcade Mode on).
  Stage 25 (Arena) plays the Arena stage under arcade rules, with three players in Multiplayer. The Pocket
  replays saved settings in a fixed order at boot, so the core cannot know which page was changed last:
  page 2 wins whenever it holds a stage. Stages are read at boot, so choose one and then use Soft Reset.
  Upgrading from 0.2.6: Arcade Mode is a new entry and starts Off, so a stage chosen in 0.2.6 waits until
  Arcade Mode is set.
- **6-Button**: X, Y, Z and Mode reach the game. On the Pocket they are X = L, Y = the Pocket's X, Z = R and Mode =
  Select, the labels `input.json` already gives those buttons. Paprium's own pad code does read a 6-button pad (on
  Genesis Plus GX all four buttons land in its pad words), but on this core, as on the MiSTer core and the
  EverDrive, they never arrive; the switch hands them to the game directly. With Arcade Mode on, Mode is handed
  over even when 6-Button is off, because it is the coin. 0.3.0: with the EA 4-Way Play present (3-Player Mode on,
  or Arcade Mode Multiplayer; below), the game reads the pads through it, and that read works on this core, so the
  switch also sets the pads themselves: on, they are six-button pads, and X, Y, Z and Mode arrive by the game's
  own read for all three players (player 3 included), so the pad hook hands over nothing while 6-Button is on.
  (Handing them over as well, as the first 0.3.0 build did, could deliver a press twice: one landing between the
  game's pad read and the hook's register read arrived from the hook in one frame and from the game's read in the
  next, so one Mode press could give two credits.) Off, they are three-button pads, as the game saw them in 0.2.6,
  and in Arcade Mode the hook hands over Mode, the coin. Without the adapter (the default) the ports were 0.2.6's
  until test build 4: the hook handed X, Y, Z and Mode over, because the game's read on the ports starts with TH already
  low and the pad model lost that first rise, so the game's six-button test failed and it saw three-button pads
  (with the hook's Z injected, B + forward and Z both did the Z action: a hybrid no real pad gives). **0.3.0 test build 4
  (B Jam's decision of 2026-10-16):** the pad model now counts that first rise, as a real six-button pad does (B Jam's CDX and
  cart show the six-button badge on port 1), so with 6-Button on the pads on the two ports are real six-button pads
  too: the game reads X, Y, Z and Mode itself on every port, the hook hands over nothing, and it runs only in
  Arcade Mode (for the coin; with 6-Button off, three-button pads, it hands over Mode as the coin). **Stage 5:** the
  hook is gone. X, Y, Z and Mode always come by the game's own read; with the Grand Stick III on, the stick is a
  twelve-button stick whatever 6-Button says, 6-Button sets the pads on port 2 and in the stick's EXT socket, and
  Select is the coin (Arcade On or Multiplayer) or the stick's Mode button (Stick Only).
- **3-Player Mode** (0.3.0): plugs the EA 4-Way Play in (below), so the game's own three-player modes work with
  three Dock controllers. Off by default. Read at boot, so Soft Reset after a change. **Stage 5:** with the Grand
  Stick III on there is no EA 4-Way Play; 3-Player Mode then puts Dock controller 3 in the stick's EXT socket (B
  Jam's decision of 2026-10-21: the cart's own three-player setup).

| Value | Stage | Value | Stage |
|---|---|---|---|
| 1 | Block 888 | 14 | Deep Storage |
| 2 | Intercom | 15 | Aquaworld |
| 3 | MTS | 16 | Blue Bar |
| 4 | Bion Mart | 17 | Powder-Zone |
| 5 | Roof-Top | 18 | Bohpal B-2 |
| 6 | Police HQ | 19 | Juvanium |
| 7 | Ice Factory | 20 | Sky Spa |
| 8 | Reformatory | 21 | Digniti KTV |
| 9 | Sanophix PU | 22 | The Vault |
| 10 | Central Park | 23 | Sanophix Labs |
| 11 | Green Cross | 24 | The Solarium |
| 12 | The Docks | 25 | Arena (the game's stage `0x1E`) |
| 13 | Golden Of Seas | | |

The names are MisterPezz82's list from the MiSTer core and match the game; they were checked on hardware.

### The EA 4-Way Play (0.3.0)

With **3-Player Mode** on, or with Arcade Mode set to Multiplayer (which needs it), the core presents an EA 4-Way
Play on the two controller ports (stage 5: only with Arcade Mode Off; with the Grand Stick III on, below, its EXT
socket gives player 3 instead), as if the adapter were plugged in before power-on (B Jam's decision of 2026-10-11; the first
0.3.0 build presented it at every boot, which is why the mini-game note below led to the switch). The game looks
for it once, at boot, so the core takes the setting only while the console is held in reset: change it, then Soft
Reset. Off (the default) gives the two controller ports as 0.2.6 wired them. Paprium supports it: it looks for one at
boot and then reads pads A, B and C through it every frame (it never reads pad D). Pad A is Dock controller 1 (or
the Pocket itself), pad B controller 2 and pad C controller 3, which counts only when it is a docked pad, so a
docked keyboard is not a player; an empty socket reads as nothing plugged in. Test build 4 (B Jam's decision of
2026-10-16): that holds for every socket and for the two ports without the adapter too: a pad answers only when its Pocket
controller is there (the Pocket's own controls or a docked pad), so a handheld Pocket has no phantom player 2,
and the Boom Box shows a controller badge only for the pads that are there, each of the type 6-Button sets. `rtl/PAPRIUM/paprium_pads.sv` is the
adapter, modelled as upstream's `fourway.sv` and Genesis Plus GX model it (the select latch is taken from port B
when its two low bits read 0).

- **Three players.** With 3-Player Mode on and Arcade Mode Off, the game's own ARENA mode takes three players (with
  Arena unlocked). In Arcade, three players need Multiplayer (or the game's map code). Original mode is always
  two.
- **Players 1 and 2.** The game reads them through the adapter instead of the ports, with the same buttons
  and the same records (Genesis Plus GX, same inputs on both machines: menus, hold-B, options, 6,000 frames of
  Original 1P and of Arena 2P play gave the same pictures and video memory frame for frame). The adapter read
  takes a few hundred more 68000 cycles a frame, and the game takes timing as randomness in two places: it seeds
  its random numbers from a video-chip status read at boot (with three-button pads that gave a 30-frame
  difference on the DATENMEISTER splash, play identical after), and it budgets some background work by the
  raster line, so long frame-exact runs drift apart after a while (the attract demo after 5,407-8,269 frames),
  as they do with 0.2.6's pad hook on.
- **The first-boot mini-game** reads port A itself and never picks a pad, so with the adapter it hears the pad the
  game picked last, pad C: Dock controller 3 plays it, and with no docked controller 3 it gets no input (Genesis
  Plus GX with an adapter: pad C drives it, pad A does not). Skip it with Soft Reset as before. A real console
  with the adapter plugged in does the same.

`fourway` in `paprium_pads` is the adapter. `core_top.sv` takes it from the two menu entries while the 68000 is
held in reset (`tap_md`), and hands the same bit to the Scum! pad hook (until stage 5). `fourway = 0` is 0.2.6's
wiring, pad 1 on port A and pad 2 on port B, with 0.2.6's pad mode.

### The Grand Stick III (0.3.0 stage 5)

The Grand Stick III is Paprium's arcade stick. The game has its own code for it: it looks for one on port 1 at boot
(`$B1DBC`), reads it every frame (`$B22C2`: the first read `$B1FC0`, with TH low, sees D3:D2 = 01 and goes on in
`$B210C`), reads its six switches once per power-on or reset (`$B5A32`) and takes its coin (`$B5924`). The coin,
the switches and the lamps never touch the cartridge chip: the 68000 reads the stick on `$A10003` itself. So a
virtual stick on port 1 (`rtl/PAPRIUM/paprium_gs3.sv`, inside `paprium_pads`) lets the game run its own arcade
code, with nothing patched.

**What it answers.** It sees only what a real stick sees: the TH line and, in the write-back, the four data lines
the console drives. The phase is the number of TH edges since the frame started; a frame starts after 1.512 ms with
no TH edge (the six-button pad's rule). Phase 0 (TH low) the ID, `$14` (D2 = 1, D3 = 0: a stick; D4 = 1: there),
D1 = 1 with a pad in the EXT socket; 1 and 2 the twelve buttons (U D L R B C, then A Start Z Y X Mode); 3 and 4 the
EXT pad's twelve; 5 status A, `$02`, D3 = a coin waiting; 6 status B, `$3F`; 7 the switches {ARCADE, INF. CREDITS,
DEMO, TWO COINS, NO HIT FX, 3 PLAYERS}; after that all 1. The rise into phase 9 carries the game's coin ACK nibble.
The ID, status A and B at rest, the timeout and the ACK rule are not known from a real stick yet (no capture); they
are parameters, and the only effect the game could see from them is when its read may start.

**The coin.** Select is the coin while Arcade is On or Multiplayer: each press adds one waiting coin (up to 7), and
the stick takes one each time the ACK nibble's bit 2 goes from 0 to 1 from one frame to the next. The game holds
the ACK for every read until its coin handler runs again, which in play is not every frame; a stick that took a
coin on every ACK would lose them (Genesis Plus GX with the game's own code: 13 coins in bursts gave 12 credits
with the edge rule, 6 with a coin per ACK). The game itself swallows the first coin after power-on or reset (its
gate `$FF98D7`), as on the cart. While the Pocket menu is open the stick's timer waits, so a pause in the middle of
a read cannot restart it (that would make a phantom credit).

**The menu, as switches** (`core_top.sv`, taken at boot with the adapter's bit, so Soft Reset after a change):

| Arcade Mode | switches | Select | EXT socket |
|---|---|---|---|
| Off | no stick: the pads as before (test build 4's, on every clock) | Mode | - |
| On | ARCADE + Arcade Coins + Attract Only | coin | Dock controller 3 with 3-Player Mode |
| Multiplayer | ARCADE + 3 PLAYERS + Arcade Coins + Attract Only | coin | Dock controller 3 |
| Stick Only | none | the stick's Mode | Dock controller 3 with 3-Player Mode |

Arcade Coins: 1 Coin 1 Credit = no switch, 2 Coins 1 Credit = TWO COINS, Inf. Credits (0012) = INF. CREDITS (the
red stop). Attract Only = DEMO. NO HIT FX is left out (it only changes the hit signal the game sends back to the
stick; nothing to see on a Pocket). With two player slots the game merges the EXT pad into player 1, as on the cart; with three, the EXT pad
is player 3. The stick is Pocket controller 1 with pad 1's buttons (A-B-C on Y-B-A, X = L, Y = X, Z = R, Mode =
Select), the EXT pad a docked controller 3 (three-button with 6-Button off).

**What replaced what.** The Scum! arcade `nop`s, the Multiplayer `nop`, the pad hook, the pad cave, its registers
and the coin stub are gone (`paprium_scum`'s table: 122 words, now 32). No firmware change: the game posts its
arcade command `810F` itself, and the chip ignores it.

**How it was checked (stage 5).** A test-only build of Genesis Plus GX with this device written into it line
for line (the RTL's rules and numbers) ran the game in every menu setting; the game's own reactions were as the
code reading says (switch decode, the 0012 stop, credits, 2 Coins 1 Credit, Attract Only, three slots, the EXT pad
as player 3). Every port read of those runs was then replayed into the RTL, clock by clock, and matched. With
Arcade Mode Off, `paprium_pads` and `paprium_scum` were compared with test build 4's on every clock. What only the real
stick can settle is its ID and status bytes, its timeout and its coin wiring.

### How: a ROM-read substitution

Nothing writes the ROM. Neither the file on the SD card nor its copy in SDRAM is ever changed. While a
switch is on, the cartridge answers some ROM reads with replacement words instead of the game's own,
the same kind of patch a Game Genie makes, done in the FPGA. Switching it off gives back the original
words, so off is the stock game byte for byte.

- `rtl/PAPRIUM/paprium_scum.sv`: the table lookup and the switch gating (until stage 5 also the pad
  registers). Its case table is generated by `scripts/scum_table.py --write`, which needs no ROM. `--check`
  confirms that your ROM holds what the table was made for at every patch site, at the flip point and in the
  cave's space (all zero padding), and refuses any Scum! word in the Hall of Fame bar tiles (below). It
  compares the patch sites against a digest, so the script and the RTL hold no copy of the game's original
  words beyond the few instructions the health cave has to run again (its compare). Stage 5: 32 words (the
  Little-Man sites and cave, the stage word), was 122.
- `rtl/cartridge.sv`: `cart_data <= scum_use ? scum_data : rom_data`. `scum_use` excludes the reads of
  the MCU's decompression stream, so the cartridge MCU's firmware always reads the real ROM. Every console
  read of the ROM is substituted, **VDP DMA included**, which is why no Scum! word may sit in anything the
  game reads as data (the 0.2.6 Hall of Fame bug, below).
- `target/pocket/core_top.sv`: the bridge registers, and one `synch_3` that brings the switches and the
  pads' {Mode, X, Y, Z} into `clk_md_107_39`, the cartridge's `clk_ram`.
- `pkg/pocket/Cores/Koala_Koa.Paprium/interact.json`: the menu.

**Timing.** `rom_addr` is latched when an SDRAM read starts and holds for the whole access, so
`paprium_scum` looks the address up one clock later into registers and the answer is ready long before
the data comes back. The only thing added to the existing read path is the multiplexer in front of
`cart_data`.

**When a switch takes effect (0.3.0).** The table works from a latched copy of the switches, and the
copy is taken only when the 68000 reads one word: `0x0B238C`, the last instruction of the game's pad read
before the hook (the flip point). No cave can be running there: both caves are leaves (the coin stub's
call tree does not reach the pad read), the game's VBlank handlers are leaves, and every path through the
pad read passes that word before the hook. So a change can never land between the words of a patched
instruction, or pull a cave out from under the 68000. 0.2.6 used the switches live, and the Pocket menu
freezes the 68000 wherever it is: had it frozen inside the pad cave and a change turned the hook off, the
68000 would have resumed in `0xFFFF` words, and the VBlank interrupt that is always pending after a menu
pause would have made that likely. Not seen on hardware; the bench that measures it is below. The price:
a change waits for the game's next pad read, every frame in play and twice in the boot routine before its
arcade test, so a stage chosen before a Soft Reset still applies. Stage 5: only the health cave is left, and the
flip point stays where it is.

### The patch sites

| Switch | ROM address | What is there | Served instead |
|---|---|---|---|
| Health | `0x02FAC4` | the compare of an object's damage against its health | `jsr $0BF000`: the health cave zeroes the damage for player objects, then runs the two instructions it replaced, so the branch after it sees the same flags |
| Health | `0x030E8A` | the health write of the game's throw-damage routine, which only throws and thrown bodies use; with Health on a player's throws do no damage to enemies | `nop ; nop` |
| Pills | `0x01A9FA` | the decrement of the player's Blu pill count | `nop ; nop` |
| Lives | `0x02A4EE` | the decrement of the player's life count | `nop` |
| Arcade (until stage 5) | `0x0B5AB8`, `0x0B5ACC` | the two branches that skip the arcade-mode command | `nop` (adroxe) |
| Arcade Multiplayer (0.3.0 from stage 1, until stage 5) | `0x0B5B1A` | the branch that skips the three-player switch | `nop` |
| Arcade (0.2.6 and 0.3.0 before test build 4: Arcade or 6-Button; until stage 5) | `0x0B2392` | the return at the end of the game's pad read | `jmp $0BF040`: the pad cave |
| Stage | `0x0B0A14` | the arcade start-stage word, `0x0001` = Block 888 | `0x00SS` (krikzz) |

Objects live at `$FF8610 + $100 × slot` in work RAM, with health in the word at `+$88`; the players are
slots 1 to `[$FF9903] - 1`, which is the game's own player test. The health cave applies that test, so
the damage routine, which every object shares, still hurts enemies. Throws are the exception: the
`0x030E8A` patch above sits in the game's throw-damage routine, so while Health is on a player's throws do
no damage to enemies.

**The health cave** (`scripts/scum_health_cave.s`) is served at `0x0BF000`, in the zero padding before the
animation data at `0x0C0000`.

**The pad cave, the coin stub and the first coin** (this and the next paragraphs) are the record of what Arcade
Mode was until stage 5, when the Grand Stick III replaced them (above); `scripts/scum_pad_cave.s` was removed then.

**The pad cave** (`scripts/scum_pad_cave.s`) was served at `0x0BF040`, after the health cave in the same zero
padding. It ORs four registers into the game's pad words (held and just-pressed, player 1 and player 2),
and in Arcade Mode a just-pressed Mode calls the game's own credit routine (adroxe's check) through the
coin stub. The registers follow it at `0x0BF0C0`-`0x0BF0CB`: a flags word (bit 0 = Arcade Mode), then P1
and P2 held, then P1 and P2 just-pressed. `0x0BF0CC`-`0x0BF0FF` is left free, and the coin stub is served
at `0x0BF100`-`0x0BF11F`. 0.2.6 served the cave at `0x11C560`, which was the Hall of Fame bug below.
A just-pressed register
latches a press edge and clears when the 68000 reads it, keeping a press that lands between the lookup
and the read for the next frame. The cave also carries a branch on flags bit 1 (a P1 Mode press as
player 2's Start, for a one-pad CPU MATE join during development); 0.2.6 holds bit 1 at 0, so it never
runs. The one-controller join still works with **6-Button** on: P1's Mode press (Select) reaches the game
(0.2.6: from the cave; 0.3.0: by the game's own six-button read, on every port since test build 4, which also leaves the
cave to Arcade Mode alone: with 6-Button on and Arcade Mode off the game runs its own unpatched pad read), and
holding Mode at character select
is the game's own way to add and steer the CPU partner
with a six-button pad and a Mega CD. Tested on hardware. That branch is not involved.

Two differences from MisterPezz82's V.06 core, which this follows:

- **Bit order.** The game's own 6-button read puts Z in bit 8, Y in 9, X in 10 and Mode in 11 (the SGDK
  layout, measured on Genesis Plus GX). V.06 injects them with X and Z swapped. Scum! follows the game.
- **The coin.** V.06 serves a coin register and calls the credit routine itself. Here the coin is
  adroxe's original check on Mode's just-pressed bit, fed by the injection. With a coin register held
  at 1 the emulator crashed; the edge latch would avoid that anyway, but the game-side check is the one
  adroxe tested.

**The coin stub (0.3.0).** The game's coin routine (`$0B5924`, run by the Grand Stick III's coin signal)
is a `link a6` routine: its prologue saves a2 and a3 and loads three pointers (a1 = `$FF98D3`, a3 =
`$FF7036`, a2 = `$FF7032`), and its credit path starts at `$0B5960`. adroxe's patch, and 0.2.6, jumped
straight to `$0B5960`. Measured on Genesis Plus GX and in a 68000 emulator on the game's own code, that
did three things the real coin never does:

- the routine cleared the stick's coin bit and set its coin latch through whatever a2 and a3 held, so
  every coin wrote two stray bytes somewhere: into cart RAM on one route, into work RAM (`$FF998A`,
  `$FF99A6`) on another;
- the coin sound tested a byte through the stale a1, so it played or not by chance (it played on one
  route, not on another);
- the routine's own `unlk a6 ; rts` then returned from the pad read's caller, the game's frame routine,
  skipping the rest of it for that frame (the frame counter missed one count per coin) and its register
  restore.

0.3.0 calls a 16-word stub, `COIN`, that enters the routine the way its own prologue does (the same
instructions) and then jumps on into the routine. The routine's own exit then restores a2/a3 and returns into
the cave. A Mode press is now exactly a Grand Stick III coin: one credit, the game's coin sound (the game
plays it while the count after the coin is at most 7), the stick's own latch, and nothing else.

**The first coin (0.3.0 test build 4).** The stub first jumped to the credit path at `$0B5960`. The routine's real coin
path goes through its first-coin gate at `$0B5950` before that (`lea $FF98D7,a0 ; tst.b (a0) ; bne $0B5960 ;
move.b #1,(a0) ; bra $0B599C`): the first coin after power-on or reset only sets `$FF98D7` and gives no credit and
no sound, and every later coin goes on to the credit path. `$FF98D7` is cleared at every boot (`$0B5A32`). So the
stub now jumps to `$0B5950`, and our coin enters the game's credit code before the gate, as a coin from the Grand
Stick III on the cart does: the first Mode press after power-on or reset is ignored, as on the cart. The gate
loads its own a0; a2 and a3 are the stub's, and the exit at `$0B5A26` is the same. The word is
`scripts/scum_table.py`'s last `COIN_STUB_CODE` word (`0x5950`, was `0x5960`), `scripts/scum_pad_cave.s`' `jmp`,
and the table entry for `0x0BF11E` in `rtl/PAPRIUM/paprium_scum.sv`.

### How the sites were found and checked

On Genesis Plus GX: a headless libretro harness that plays scripted input and diffs work RAM, then a
build of the emulator with a 68000 write watch that logs the program counter of every write to a watched
address. Checked there in both Arcade and Original modes: the cheats hold, enemies still die, the arcade
unlock shows ARCADE PAPRIUM, a Mode press adds a credit, and every stage value from `0x01` to `0x18` plus
`0x1E` starts a different stage. Then on hardware: every switch works and every stage name is right.

### Fixed in 0.3.0: the Hall of Fame name-entry bar

In 0.2.6, with **Arcade Stage Select or 6-Button on**, the blinking highlight bar on the Hall of Fame
name-entry row showed garbage in the first 24 pixels of every 64-pixel group: at the left edge, where the
initials go, and fainter over the score, the stars and the location. Little-Man alone did not do it, and
with both switches off the bar was clean.

**Cause.** The pad cave and its registers sat at `0x11C560`-`0x11C60B`, inside a 512-byte block of `0xFF`
that was taken for padding. It is not padding: it is the tile data of that bar (16 solid tiles), which
the game copies into VRAM with a VDP DMA straight from the ROM when the table is drawn. The substitution
covers DMA reads too, so the bar was built from the cave's code instead of solid tiles.

**Evidence** (Genesis Plus GX, 1,278 Hall of Fame frames): against the unmodified game, 298 frames differ,
every one of them a frame with the bar on, all inside x 0-279, y 128-143. With the cave moved elsewhere,
0 frames differ. A ROM view that has the cave's words but no hook, so the 68000 never runs the cave,
shows the same damage: it is the VDP reading the words, not the cave running. A census of every VDP DMA
from the 68000 bus in our captures, 4,250,618 of them, finds no other Scum! word ever copied.

It was there from the first Scum! build. **The fix (0.3.0)** moves the cave and its registers into the
zero padding after the health cave (`0x0BF040`, `0x0BF0C0`), which the game never reads (measured: the
whole `0x0BCFDC`-`0x0BFFFF` padding filled with a marker byte changes nothing on three routes through the
game, and no pointer in the code reaches it), and `scum_table.py --check` now refuses any Scum! word in
`0x11C560`-`0x11C75F`. The game's Hall of Fame scores, some names and the birthdays look hex-like, for
example `2CE74`: that is the game's own style, on a real cartridge too, not this bug.

**How 0.3.0 was checked** (before any hardware):

- The relocated cave against 0.2.6's, in a 68000 emulator on the game's own code from the flip point, over
  1,568 input cases (flags, both pads' held and pressed words, the partner slot, random pad words): the
  991 without a coin give the same work RAM, cart RAM, registers and commands as 0.2.6; the 577 with a
  coin give exactly what the game's own coin routine gives when entered at its top with a coin signal.
- Genesis Plus GX, the Hall of Fame name entry under the words the 0.3.0 table serves with every switch on:
  0 of 1,278 frames differ from a real cart's; 0.2.6's words, the same run: 298 frames, all on the bar.
- Genesis Plus GX, six Mode presses in Arcade Mode: one credit each, the coin sound each time, the
  routine's writes on its own variables only, the frame counter never missing a count.
- An RTL bench of `paprium_scum` replaying the 68000's own read stream around the hook (226,355 reads,
  with VBlank interrupts, Z80 reads between two 68000 bus cycles and DMA reads mixed in) while the switches
  change at random clocks: 0 instructions served from two views, 0 cave words served as plain ROM inside a
  running cave, 0 bar-tile words substituted. 0.2.6's module on the same bench: 450, 2,164 and 15,972. A
  first guard design, which took the switches on any read outside the patch words, still gave 132 and
  2,169: an interrupt, a Z80 read or the coin call can happen while a cave is running, so only a read
  where no cave can be running is safe.

---

## Console, Mega CD, 32X Mode and MegaWire

These are not substitutions. They change what the console and the cartridge report when the game checks
its hardware at boot, so a change takes effect at the next **Soft Reset**. Change the setting first, then
reset (see the known issue at the end of this section).

### Console

| Console | Region | TMSS | Expansion port |
|---|---|---|---|
| Mega Drive (default) | Japan | no | yes |
| Genesis | USA | no | yes |
| Mega Drive 2 | Japan | yes | yes |
| Genesis Model 2 | USA | yes | yes |
| Genesis 3 | USA | yes | no |
| Nomad | USA | yes | no |
| Mega Jet | Japan | yes | no |
| TeraDrive (0.3.0) | Japan | no | yes |
| Unknown | Japan | no | yes |

The game shows the console's picture in the Boom Box, uses its region (Japan gives the Japanese
cartridge's extras, such as the song titles at the start of each level), and changes a little behaviour
with the model. Unknown gives the game's "unknown" picture.

- **Region.** The console's region is the region the game sees; the menu names imply it, with no separate
  region option. The old fixed region was Japan, which is what the default, Mega Drive, still gives.
- **TMSS.** A console with TMSS expects the cartridge to write `SEGA` to its TMSS register before the video
  chip will work. On those entries the core answers the TMSS registers itself, so they boot straight
  into the game with no licence screen, and no Sega code is involved. The version register carries the
  same byte on both byte lanes, because the game treats a mismatch as a clone console.
- **No expansion port** (Genesis 3, Nomad, Mega Jet): a separate Mega CD unit is ignored, as it would be on
  the real machine. A combined unit still works, because it is the console.
- There are no PAL entries.
- **TeraDrive** (0.3.0). The game tells a TeraDrive by its 128 KB of video RAM: once per boot it switches the
  video chip's 128 KB mode on, writes VRAM `$10000` and `$0000`, and reads `$10000` back. The Pocket has 64 KB,
  so the core answers that one test with a 64-byte stand-in for the second VRAM bank
  (`rtl/upstream/nuked-md/vram_td_stub.v`, on the bank's own write strobe and data bus, off for every other
  Console value). It is **detection only**: the game uses 128 KB mode for nothing else (one 128 KB switch in
  43,472 measured frames, the test's own), so the visible result is the TeraDrive in the Boom Box. The game then
  finds 8 KB of Z80 RAM, as on this core, and reports its code B; a TeraDrive with 16 KB (code C) is not offered.
  A separate Mega CD unit is allowed with it; whether a real TeraDrive takes one is not established.

### Mega CD

| Unit | Kind | Region |
|---|---|---|
| None (default) | | |
| Mega-CD / Sega CD | separate unit | the Console's |
| Mega-CD 2 / Sega CD 2 | separate unit | the Console's |
| Wondermega | combined | Japan |
| Wondermega M2 / X'Eye | combined | the Console's: Japan shows the Wondermega M2, USA the X'Eye |
| LaserActive | combined | the Console's |
| Aiwa CSD-GM1 | combined | Japan |
| CDX | combined | USA |
| Unknown CD | separate unit | the Console's |

The core answers the game's Mega CD checks with a detection stub, `rtl/PAPRIUM/paprium_addons.sv`: the
identification words the game compares (the ID letters and model digits of each unit, not a copy of any
Sega BIOS), the gate-array registers, a program-RAM probe and its marker. Nothing of the Mega CD itself is
emulated. The game shows the unit's splash, and when it finds a Mega CD it offers **CPU MATE** in its
Options. The core drives the partner (below) with any unit except None and Unknown CD.

**TMSS per unit (0.3.0).** A combined unit is the console, so its TMSS is the unit's. Every all-in-one unit
(Wondermega, Wondermega M2 / X'Eye, LaserActive, Aiwa CSD-GM1, CDX) shows the licence screen on real hardware,
so each one now reports TMSS (0.2.6 reported none), and the core answers the TMSS check itself, as it does for
the TMSS consoles: no licence screen, no BIOS file, the game boots straight in.

The stub started from [the MiSTer Paprium team](https://github.com/thekoalakoa/Paprium_MiSTer)'s detection stubs for 32X and Mega CD.

### 32X Mode

Reads of `$A130EC`/`$A130EE` return "MARS", so the game believes a 32X is attached, and some throwable
objects become 32X boxes. Nothing of the 32X is emulated.

### MegaWire

Off is what a real cartridge reports with nothing plugged in: the game shows MODEM : NONE, no MegaWire
icon, and no MegaWire row in its Options. On is what every release before 0.2.6 reported, a connected
MegaWire: the icon, MODEM : MW4.0 and the MegaWire row. The MegaWire service itself is not emulated.

### How the options reach the game

`paprium_opts` (in `paprium_addons.sv`) turns the two lists into the hardware facts: the JP/US line, the
version nibble and the TMSS stand-in, the unit's ID words, and a "real Mega CD" flag for CPU MATE. Those
follow the menu live. The console model bits and the MegaWire status go to the cartridge MCU's GPIO input,
and the firmware copies them into the words the game reads, once, at its own reset.

Checked in an RTL unit simulation of every combination (8 consoles × 16 Mega CD values × 32X, plus
MegaWire): 272 combinations, 2,176 ID-word reads, 272 TMSS sequences, all as specified. The game's own
hardware check, run on those answers, gives the expected result in 272 of 272, and never hangs. On
hardware: all 8 consoles give the right picture and region, the TMSS consoles boot, and every Mega CD unit
gives the right picture, splash and region. 0.3.0 (TeraDrive, every combined unit with TMSS): 9 consoles, 306 combinations, the
game's check right in 306 of 306; the TeraDrive's video RAM test runs on the RTL console with the game's own code
and passes only with the TeraDrive selected.

### Known issue: rarely, a change around a Soft Reset needs a second reset

The firmware reads the Console model bits and the MegaWire status **once**, about 2 ms after a reset
starts, while everything else the options drive follows the menu live. A setting changed after that
read, but before the game's hardware check a few seconds later, gives that one boot a mixed machine,
for example the Genesis 3 picture after a change from Mega Drive to Mega Drive 2. The next reset is
clean. Changing the setting **first and then** using Soft Reset is always consistent. Separately, a Soft
Reset rarely ends on a black screen with a few pixels at the bottom edge; another Soft Reset recovers. On
the release build, Soft Resets passed across changes of mode, Console, Mega CD and MegaWire, and once
afterwards one needed a second Soft Reset. Not fixed in 0.2.6: latching the options while the cartridge
is in reset was considered and declined.

---

## CPU MATE

On a real Mega Drive with a Mega CD, Paprium can give you a computer-controlled partner. The game hands the
Mega CD's sub-CPU an AI program and the tables it needs at boot, writes the state of the stage into the
Mega CD's Word RAM on every update, and reads the partner's pad word back from a Mega CD communication
register, together with a busy flag. The Pocket has no Mega CD, so 0.2.6 provides the other end.

### Using it

1. In the core menu, set **Mega CD** to any unit except None and Unknown CD, then **Soft Reset**.
2. In the game's Options, switch **CPU MATE** on.
3. At character select, bring the partner in:
   - **Played handheld:** turn **6-Button** on in the core menu. **Hold Select** to add the partner.
     Still holding Select, move the partner's cursor with the D-pad and press **Start** to pick its
     character. Release Select to pick your own. No second controller is needed. This is the game's own
     six-button control with a Mega CD (Mode + Start, keep holding Mode; see the
     [Paprium FAQ](https://www.wafflenet.com/paprium.html#questions)), and it was tested on hardware.
   - **With a second controller on the Dock:** press **Start on controller 2**: the partner joins. Press
     it again to pick its character, then pick your own.

   From then on the partner plays by itself. A real controller 2 that is being used overrides the AI for
   a while, as the game does with a real Mega CD.

### How it works

- **The brain.** The partner's AI is a reverse-engineered emulation of the game's CPU partner, written as
  68000 source and built ahead of time into RISC-V code that runs on the cartridge's NEORV32 MCU alongside
  the firmware. The game's 68000 runs unmodified: no hooks and no extra cycles; only the data
  the Mega CD stub returns changes.
- **The timing.** The brain counts, call by call, what the original program would have cost on the
  real sub-CPU at its nominal clock. The link releases the busy flag and the answer word at exactly that
  moment: busy while the real sub-CPU would still be working, then the word. The game skips an update
  while the sub-CPU is busy, and that matters to how the partner plays, so answering early would not be
  faithful.
- **The link** (`rtl/PAPRIUM/paprium_mcd_link.sv`, `paprium_xlink.sv`): detects the game's update, keeps the
  busy flag and the answer word, follows the sub-CPU reset bit in `$A12001` (a 1-to-0 edge restarts the
  brain; the latch powers up at 1 and has no reset input) and the game's own "AI off" request, and gives
  the MCU a register page and an interrupt.
- **The view.** `rtl/PAPRIUM/paprium_snoop.sv` copies the game's writes to Word RAM, and its boot-time upload
  of the AI tables, into a mirror in the Pocket's 256 KB SRAM (`paprium_xram.sv`), which the brain reads.
  The tables are captured from the game as it runs; none ships with the core. Because the game writes the
  sub-CPU's view itself, the mirror is exactly as fresh or as stale as the real one.
- **The firmware glue** (`buddy.h`, `zz_buddy.c`, `zz_buddy_trap.c` in `patches/mega-ppm-pocket.patch`): runs
  the brain as a task at the end of a main-loop pass with no command pending. The mailbox interrupt
  pre-empts it, so the cartridge's replies to the game never wait behind the brain, and a timer-driven
  feeder keeps the eight sound-effect channels topped up while it runs.
- **Memory.** The MCU's instruction memory grew by a 22 KB extension, and a 16 KB window of the cartridge
  work RAM holds code and is write-locked. With no Mega CD unit selected nothing reaches the link, and in
  an RTL simulation the firmware handled every event on the same cycle as a build without the CPU MATE.

**The brain is not in this repository.** It's a reverse-engineered emulation of the game's CPU partner, and
it ships inside the firmware file, `little_man_firmware.bin`; the firmware build links it in from outside the
source. Built without it, the firmware is complete except for the brain: the game still offers CPU MATE
with a Mega CD unit selected, but the partner gets no input and does not move (seen in simulation, and on
hardware with 0.3.0). See [docs/firmware/README.md](firmware/README.md).

### How it was checked

- The brain's 68000 version against the original program, and its RISC-V code against the 68000
  version: 281 recorded corpora, 889,593 calls, 0 differences in the answer word, in the AI's
  variables and in its map; a 135,000-call mutation set, 0.
- The cost counter: 2,584,050 calls in closed loop at the nominal sub-CPU clock and at 5% and 10% slower,
  0 words wrong and 0 early.
- The whole core in an RTL simulation with recorded game traffic: of 1,610 updates, 1,608 answered exactly
  (one dropped at an "AI off", one across a Soft Reset), and no command from the game left unanswered.
- On hardware, through every 0.2.6 test build and the release, the tester's verdict: it plays like the
  cartridge.

### What did not work

The partner went through five versions before this one. What went wrong is the useful part:

- **A small 68000 routine of our own**, served from spare ROM space and called from the game's CPU MATE
  code. The first one chased enemies that had not spawned yet (it read inactive object slots) and punched
  the air where they would appear; it never threw. The next one read the facing flag backwards (0 is left,
  measured), and took a front-grab flag for the enemy's weight: the real throw is a rear grab with Back + B,
  and only when the enemy's weight is at most the partner's strength. Item pickups never happened, because
  a "no pickup" bit in the pad word was left set.
- **Making it smarter than the cartridge.** A few of our "improvements" were reverted: the aim is
  preservation, quirks included.
- **Running the game's original AI program on the main 68000** costs about 8,000 cycles a frame; it became
  the test reference instead.
- **A hand-written version on the main 68000, with hooks in the game's code.** Exact call for call, but any work
  inside the game's frame wait changed the game's own decisions, because the game measures how far into
  the frame it is, and the brain could not always finish before the game read the answer (as little as
  1.6 ms). Every hooked design was dropped for that, in favour of the hook-free link on the MCU. A second
  68000 for the original program does not fit the Pocket.
- **Answering as soon as the brain finished.** More responsive than the real thing, and so not the real
  thing: the real sub-CPU is sometimes still busy when the next update comes, the game then skips that
  update, and the partner's play follows from that. Answering at the counted time is what matches.
- **A lean rule for feeding the sound-effect channels** while the brain runs starved them in 3 or 4 of
  841,209 simulated runs. The feeder now follows each channel's rate.
- **The first cycle counter** was wrong on 626 of 2.58 million closed-loop calls, 20 of them early, from 13
  branch outcomes it had never seen. Fixed: 0.
- **The partner's RAM built from logic.** One version's RAM with byte enables was built from about 2,000 ALMs
  (a ninth of the device) instead of block RAM; two byte-wide RAMs fixed it.
- **Look-ahead past the goal** pinned the partner against walls, and a target scan that never completed a
  pass with two players and the partner left it with nothing to fight. Both belonged to the 68000 routines.

## Credits

The arcade unlock and the Mode-button credit are adroxe's
([Paprium-Arcade](https://github.com/adroxe/Paprium-Arcade), with a full write-up there). The arcade
start-stage word was found by krikzz. Serving patches as ROM reads, and the pad hook that injects X, Y, Z
and Mode, come from MisterPezz82's
[Paprium MiSTer core](https://github.com/MisterPezz82/Paprium_MegaDrive_MiSTer) (V.05 and V.06), as does the
stage list. The 32X and Mega CD detection stubs started from [the MiSTer Paprium team](https://github.com/thekoalakoa/Paprium_MiSTer)'s, and the CPU MATE
link's restart rule was worked out with them. The health, pill and life patches, the console options and
the CPU MATE link are new here.
