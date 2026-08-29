# Paprium SFX bank — identifications

The cartridge holds **127 sound effects** as raw PCM in ROM at `0x25ECA4`
(553 KB, 5333–48000 Hz, 4-bit and 8-bit). `scripts/dump_sfx.py` extracts them all;
the id in each filename is what the game requests via mailbox command `0xD1`.

Nothing labels them, so this is built by ear against hardware and against captures
from `scripts/decode_cmdlog.py`. Recorded because it is hard-won and easy to lose.

| id | length | identification | how established |
|---|---|---|---|
| `0x4A` | 4.99 s | **Punk-TV cue** — the working TV's broadcast | by ear; confirmed by hardware once the loop fix landed |
| `0x4B` | 4.55 s | **Area ambience** — subway trains passing | by ear; log shows it looping on ch6 with positional volume/pan the whole level |
| `0x3D` | 3.07 s | **Crowd fleeing in fear** | by ear |
| `0x08` | 0.81 s | **Something breaking** — e.g. the door at the start | by ear |
| `0x1C` | 2.15 s | *believed* big / fat enemy death on original hardware | by ear from the dump — **but the game never requests it**, see below |

## The big-enemy death is unresolved

`0x1C` does **not appear in any capture** — three runs, one spanning boot to exit.
The game never asks for it, so this is not a playback fault.

What the game *does* fire at that moment is a cluster of five rare sounds in
immediate succession, the only multi-sound event before the first TV:

    word 174   0x0D   0.20 s
    word 176   0x13   0.16 s
    word 178   0x3A   0.30 s
    word 180   0x20   0.71 s   (24 kHz)
    word 184   0x0D   0.20 s

~1.57 s of material against `0x1C`'s 2.15 s, which fits the hardware description
of "shortened and different but same flow". They land on different channels, so
the real cue is probably layered rather than sequential.

Two possibilities remain:

1. The death cue is a **composite** and this port plays it correctly — `0x1C` is
   then simply a sample this scene does not use.
2. Hardware really does play `0x1C`, and this port takes a different game branch -
   which would put the cause upstream of audio entirely.

## Reading a capture

`decode_cmdlog.py` prints the id, channel mask and flags for every request. The id
maps straight to a dump filename: `0x3D` -> `sfx_061_0x3D_9600Hz_4bit_3.07s.wav`.

Useful signal: **rare ids are events, common ids are texture.** In a full
playthrough `0x40` fired 170 times and `0x7D` 79 - footsteps and hits. Anything
requested once or twice is a distinct event worth identifying.
