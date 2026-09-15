# What the emulator's author was unsure about, and what it actually is

Genesis Plus GX's `core/cart_hw/paprium.h` is one of two public reverse
engineerings of the Paprium cartridge's audio (krikzz's `mega-ppm` is the other)
and the only one that annotates its own doubts. Its author marked the parts they
were unsure of, and those marks turn out to be a good map of where the real
questions are. This is every one of them, with what we have since measured.

**The governing fact, which sets how much any of it is worth.**
`paprium_music_synth()` at line 487 opens with an `#if 1` block that copies a
decoded MP3 of the released *album* into the output and returns before it ever
reaches the 26-voice loop. The keyon block that would load a voice from the wave
bank is inside `#if 0`. There is also a hard C99 error in the compiled path — a
`next:` label immediately followed by `}` at line 617 — plus `static int`
functions that return nothing and an `end:` label with no `goto`. **The music
synth in that file has never been compiled, let alone heard.** Every audio
comment in it is a reading of data, never a tested one.

The same goes for krikzz's `mega-ppm`: a reimplementation written without the
cartridge's MCU, not a dump of it. **Neither is a hardware reference.** Where
this audit cites either, it is as a map of where the questions are, never as an
answer — the player's standing rule, and one this project has paid for each time
it slipped: the 0.2.3 Boom Box row clock was GPGX's frames-per-row reading, and
it runs 20% fast against a capture.

That is not a criticism of the author. They wrote down what they did not know,
which is why this audit is possible at all.

Status key: **SOLVED** — settled against hardware captures. **REFUTED** — the
comment is wrong and we know why. **OPEN** — still unknown. **MOOT** — resolved
by reading, no measurement needed.

---

## The music command dispatch

| line | the comment | what it actually is |
|---|---|---|
| 368 | `else if( code == 0x01 ) { /* ?? */` | **REFUTED.** The dispatch loops over all four event words and word 0 is the NOTE, not an opcode. Over 210,985 events its high byte takes exactly 14 values (0x00–0x0C and 0x0E, never 0x0D) and its low byte exactly 0–7, the octave. So `0x01` here is the semitone C. Words 1–3 are 86/96/99% zero and carry the real opcodes. |
| 370, 377, 381 | `voice->volume = 255 - paprium_volume_table[arg]; /* z80 table ? */` on codes 0x01, 0x03, 0x05 | **OPEN, and partly refuted.** In word 0 these are semitones 1, 3 and 5. As real opcodes in words 1–3 they exist (0x01 ×8,058 with operands 0–255 and 0 the commonest; 0x05 ×217, wave-only) and the attenuation shape is plausible, but applying it moved Tough Guy toward the capture on both bands and Dark Rock away. Not shipped. |
| 393 | `else if( code == 0x08 ) { freq = arg; }` feeding `voice->type` | **REFUTED twice.** Its operand spans 0..70 across 30 distinct values and the rate table has six entries. And it occurs on FM (401) and PSG (157) voices that have no playback rate at all. What it really is: a **bracketed attack-time pitch effect** — 539 of 540 nonzero operands are cancelled by a later 0x08 with operand 0, it opens on the note onset 85% of the time, and on 146 matched pairs it is worth **+24.85 cents at 45–85 ms, p = 5.8e-06**, with level, duration and envelope all clean negatives. |
| 402 | `freq = 0; /* faster ? */` on code 0x0A | **REFUTED as written** — same word-0 confusion (0x0A is the semitone A#). Only 22 occurrences as a real opcode. OPEN. |
| 421 | `else if( code == 0x0E ) { /* stop ? */` | **SOLVED, the author was right.** 0x0E is the gate release, confirmed independently from the module data long before this audit. |
| — | code 0x02 → panning, uncommented | **PROBABLY RIGHT, never tested.** As a word-1..3 opcode its operands are dominated by 00/80/F0/FF, the shape of a pan. Nobody in this project has ever measured pan against hardware. OPEN. |
| — | codes with no branch at all | **14 opcodes fall off the end of the if/else chain**, 9,700 events across the corpus. Two are now decoded: `0x1A` (4,483 events, FM-exclusive) is **modulation depth**, a TL write on a modulator — harmonic slopes h2 +0.026, h3 +0.007, h4 −0.037, then h8 −0.84, h16 −1.32 dB per operand unit, where a carrier level would move every harmonic equally. `0xE0` (518, wave-exclusive) is under test. |

## The rate table — the most consequential comment in the file

| line | the comment | what it actually is |
|---|---|---|
| 560 | `_rates[] = {2,4,5,8,9,10}; /* 24000 ?, 12000, 9600, 6000, 5333-?, 4800-? */` | **UNMEASURED — two readings, no hardware.** The file's own SFX path uses {1,2,4,5,8,9}, and krikzz's `mega-ppm` (`fpga/audio_sfx.sv`) instantiates the same six clocks, 48000 down to 5333; this music table disagrees with both by a whole octave on bank type 0. But `mega-ppm` is a reimplementation, not the cartridge, so the agreement is between two readers of the same data. No capture has measured a playback rate, and pitch cannot measure one: the sample roots were measured at the nominal rate and the transposition to the written note cancels any rate error — only a bandwidth difference would show. The question marks were well placed and they stay. |
| — | the table's reachable range | Across all 94 defined programs the bank's `type` field takes **only 0, 1 and 2**, so at most three entries of any six-entry table are ever reached. |
| — | what pitch actually does | **SOLVED.** 276 hardware measurements over 22 programs and five octaves (MIDI 21–81): sounding pitch is the written pitch, median +5 cents, 83% within 25 cents. Every small-N divider law is excluded — a divider has a grid step of 1731/N cents, so an 8-cent reproducibility at 196 Hz needs N > 70. |

## Echo — live code, and the one that matters

| line | what it says | what it actually is |
|---|---|---|
| 758 | `echo_ptr = (echo_ptr+1) % (48000/6)` | **166.67 ms**, single tap, gain 0.33, **no feedback**. Live code, no `#if` guard. |
| — | the buffer | `echo_l[48000/4]` = 12,000 samples = **250 ms**, against a modulo of 8,000. **4,000 samples are never touched.** 250 ms is an abandoned earlier reading and has never been tested. |
| — | which channel | Each echoed effect goes to **one channel only** (`voice->echo & 1`), the side chosen by an alternating counter seeded from `rand()` on a stack address. The author did not know how hardware picks the side. That single-sidedness is a far more diagnostic signature than the lag. |
| — | who can echo | In *this file* the echo is written only from `paprium_sfx_voice`. **That is a fact about the emulator, not about the cartridge** — and since its music synth is dead code, it constrains nothing about whether the real synth reverberates. Our own 166 ms negative on Theme Of Paprium keyed on *discrete repeats* (cepstrum, autocorrelation, tail peak-picking) and was blind to a diffuse tail by construction, and covered only 0–55 s. **Reverb is OPEN and currently under test by deconvolution.** |

## SFX pitch modifiers — undocumented but readable

| line | code | what it is |
|---|---|---|
| 686 | `tick -= (flags & 0x8000) ? 0x800 : 0; /* tiny pitch */` | 0x800/0x10000 = ×31/32 = **−55 cents**. |
| 687 | `tick -= (flags & 0x2000) ? 0x8000 : 0; /* huge pitch */` | 0x8000/0x10000 = ×1/2 = **one octave down**. |
| — | flag 0x0100 | The author calls it "amplify"; krikzz's `mega-ppm/mcu/sfx.c` reads it as stepping the rate-table index by one with amplitude 0.90×. Two readings that disagree, neither measured on hardware. **OPEN.** |

## The wave program table

| line | the comment | what it actually is |
|---|---|---|
| 453 | commented-out read of `+0x08` | The **loop point**. Dead for 89 programs (0xFFFFFFFF) but **live for three**. |
| 455 | commented-out read of `+0x0E` | **REFUTED as a hidden root or pitch datum** — measured **zero in 94 of 94** defined programs. |
| 1799 | `/* paprium_wave_unpack(...) */` | The wave bank is **never decoded by the emulator at all**; no such function exists in the file. It only ever arrives through the `if(0)` WavPack loader at 2854. |

## Cart RAM

| line | the comment | what it actually is |
|---|---|---|
| 2001 | `0x1E10 /* 4 = crisis, 0 = normal ? */` | **REFUTED.** Measured on hardware, the crisis value is **2**, not 4. |
| 2019 | `0x1E10 /* 81 = blu pill */` | **OPEN.** Never investigated. |
| 472–473 | `ram[0x1B98/0x1B9A] = index ? 0xE0 : 0; /* L */ /* R */` | **SOLVED, and it is why our port's VU bars are always on.** The emulator writes a *constant* 0xE0 whenever any event is present. On real hardware that region is a genuine per-voice level feed — the Boom Box draws a 32-bar meter from it at 60 fps, quantised to eight levels, and it is decodable from any capture. It reports the driver's note state, not audio: it is lit at level 6.16 for a program that emits nothing. |
| 2098–2099 | `ram[0x1800] = (flags & 0x01) ? 0x80 : 0x00; /* dac */ ... /* ntsc */` | **SOLVED in meaning.** Bit 0 is the DAC flag — the DATENMEISTER-versus-YM choice in the game's audio menu. Our port does nothing with it; that is the open "VM DAC" item. |
| 2614 | `0x1800–0x1A00 return 0; /* DAC list ?? */` | Same region as above. The stub returns 0 rather than implementing it. **OPEN.** |
| 2621 | `0x1F12 /* sprite ram available ??? 0B00 or 1200 */` | Video, not audio. Out of scope here. |
| 2632–2633 | `0x1FE4 / 0x1FE6 /* DM ?? */` | Commented out entirely. **OPEN**, never exercised. |

## Dead ends, so nobody repeats them

- **The variant-diff angle yields nothing.** `paprium.h` and `paprium.h.before-winlog` are byte-identical (md5 `97ed95682401`); the only differences against `.orig` and `.render-instrumented` are this project's own instrumentation. All four are one snapshot — there is no version history recording what the author chased.
- **Line 246** `/* Slow Mood Ext. ? */` is about which MP3 filename matches a track. Irrelevant to the synth.
- **Line 800** `/* stage1 intro sound fade-out time ?? 2 seems decent */` is an SFX fade constant the author tuned by ear. Cosmetic.

## What the file gets RIGHT, worth banking

- The **pattern walk** looks wrong and is correct: its byte-swapped `[0x0B]+8` with `(index-1)*8` is algebraically identical to our `mwmm.py`'s `G + index*8`. Two independent decoders agreeing byte-for-byte on the pattern layout is real corroboration.
- `voice->program = music_ram[0x2A + ch^1]` matches our array-B reading, `^1` quirk included.
- Its **SFX** rate table `{1,2,4,5,8,9}` agrees with krikzz's reading. Corroboration between readers, not a measurement — see the rate-table section.
- `0x0E` really is the stop/gate-release.
