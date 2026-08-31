# Paprium CDDA on the Pocket — design

Paprium's background music is not FM. The MCU issues MD+ commands and something
else plays CD-quality audio. On MiSTer that "something else" is Linux: the HPS
reads WAV tracks named by a `.cue` and fills a 64 KB ring buffer in DDR3, which
`mdp_audio.sv` drains at 44.1 or 48 kHz. The Pocket has no HPS, so the producer
side has to be rebuilt. The consumer side ports almost unchanged.

## The contract to satisfy

`paprium_mdp_adapter.sv` already decodes the MCU's MD+ writes into a small
command set. Whatever we build has to answer exactly this and nothing more:

| Signal | Direction | Meaning |
|---|---|---|
| `mdp_track_request` + `mdp_track_num[7:0]` + `mdp_track_loop` | in | play track N once (`$11xx`) or looped (`$12xx`) |
| `mdp_stop_request` + `mdp_fade_sectors[7:0]` | in | stop, fading over N sectors at 75 sectors/s (`$13xx`) |
| `mdp_resume_request` | in | unpause (`$14`) |
| `mdp_volume[7:0]` + `mdp_volume_request` | in | set volume (`$15xx`) |
| `mdp_playing`, `mdp_current_track[7:0]` | out | status, read back through the MD+ result register |

Track numbers run 1..62 (`docs/paprium.cue` in the MiSTer repo). Sample rate is
**48 kHz** — Paprium's tracks are authored at 48 k, not Redbook 44.1 k, and
playing them at 44.1 k runs the music ~8% slow.

## Why the obvious approach does not work

APF exposes asynchronous SD reads to the core: target command **0x0180 data slot
read** takes a slot id, a byte offset into the file, a BRIDGE destination
address, and a length, and answers with ack / done / err
(`target/pocket/core_bridge_cmd.v:80-92`). A slot marked **`deferload: true`** in
`data.json` is declared to the core — id and size — but not preloaded, which is
exactly the streaming primitive we need. `Mazamars312/openfpga-pcengine-cd` uses
this to stream PC Engine CD audio, so the mechanism is proven on real hardware.

The obvious mapping is one data slot per track. **That does not fit: APF allows a
maximum of 32 data slots**, and Paprium has 62 tracks.

The way out is target command **0x0192 data slot openfile**, which repoints an
existing slot at an arbitrary file at runtime. Its parameter struct lives in core
memory, and APF reads it when the command starts:

| Offset | Length | Field |
|---|---|---|
| 0x000 | 256 | full path + filename, null-terminated |
| 0x100 | 4 | flags — bit 0 create-if-missing, bit 1 resize, rest reserved |
| 0x104 | 4 | desired size, for resize |

Result 0 = opened, 3 = file not found. Files must live under `Assets` or `Saves`
in a platform folder declared in `core.json`. So: **one deferload slot, repointed
per track.**

## Asset format — decided by what keeps RTL small

Two decisions fall out of building the path string in hardware.

**Numeric filenames.** Composing `/Assets/genesis/common/Paprium/01 Theme of
Paprium.wav` in RTL means a 2 KB filename ROM holding 52 human titles, and it
breaks the moment someone's files are named slightly differently. Instead the
core expects tracks numbered **by cue track number**:

```
/Assets/genesis/common/Paprium/track01.pcm
...
/Assets/genesis/common/Paprium/track62.pcm
```

The path is then a constant prefix plus two ASCII digits derived from
`mdp_track_num` — a handful of LUTs, no ROM, and no dependence on how anyone
titled their rip. Note this is indexed by **track**, not by source file: the cue
maps 62 tracks onto 53 unique files, so a few source files get emitted twice
under different track numbers. That duplication costs disk, not logic.

**Raw PCM, not WAV.** A WAV header is 44 bytes only in the canonical case; real
files carry `LIST`/`INFO` chunks and the data chunk moves. Parsing RIFF in RTL is
a state machine that exists purely to skip bytes. Since the assets need a
preparation pass anyway, that pass emits **headerless 48 kHz 16-bit stereo
little-endian PCM** and the streamer reads from offset 0. This is the same data
MiSTer's HPS puts in the ring buffer after it strips the header — we are moving
the strip from run time to prep time.

A `scripts/` tool should do the conversion: decode source audio, resample to
48 kHz stereo, resolve the cue's track-to-file mapping, and write `trackNN.pcm`.

## Modules

```
mdp_track_request ──> paprium_cdda_fetch ──0x0192 openfile──> APF
   (clk_sys)              (clk_74a)       ──0x0180 read────> APF
                                                              │
                                          bridge writes ──────┘
                                                 │
                                    data_loader (mask 4'h3)
                                                 │  (CDC to clk_sys)
                                          paprium_cdda_buf
                                            (2 x 8 KB BRAM)
                                                 │
                                          paprium_cdda_play ──> mix in core_top
                                            (48 kHz, fade,
                                             volume, pause)
```

### `paprium_cdda_fetch` — the producer (new)

A plain state machine. No soft CPU: the PC Engine CD core drives its dataslot
interface from a VexRiscv, which we cannot afford next to the NEORV32 already in
the Paprium MCU, and do not need — our access pattern is "sequential reads from
one file at increasing offsets".

- Latches slot size from `dataslot_update` / `dataslot_update_id`, which gives
  the track length and therefore end-of-track without probing.
- On `mdp_track_request`: write the path string into the param-struct BRAM,
  issue `openfile`, wait for done, check err (3 = missing track — go idle with
  `mdp_playing` low rather than hanging the MCU).
- Then issue `dataslot_read` in fixed chunks into the half of the buffer the
  player is not draining, advancing the file cursor.
- At end of file: if `mdp_track_loop`, reset the cursor to 0 and continue;
  otherwise drain and drop `mdp_playing`.

The param struct is 264 bytes of BRAM that APF reads over the bridge at
`target_buffer_param_struct`. Note the comment at `core_bridge_cmd.v:96` — that
buffer is *not* implemented there, so this module has to provide it and map it.

### `paprium_cdda_buf` — the landing buffer (new)

Double-buffered, `2 x 8 KB` to start. 8 KB is ~43 ms of 48 kHz stereo, so the
fetch side has that long to complete a read before the player runs dry.
**The real APF read latency is unknown and is the main risk in this design** —
it depends on the SD card, cluster fragmentation, and APF's 16-fragment cache.
Both the chunk size and the buffer depth are parameters, and the module carries
a saturating **underrun counter** so a hardware run answers the question
directly instead of us guessing.

Buffer placement is deliberately BRAM first. `2 x 8 KB` is ~13 M10K blocks,
which we may not be able to spare — M10K is the scarcest resource in this port.
If the fit says no, the fallback is `cram0`/`cram1`, the two cellular PSRAM
chips this core currently ties off entirely
(`target/pocket/core_top.sv:267-290`); that trades 13 M10K for a PSRAM
controller we would have to bring in. Measure first.

### `paprium_cdda_play` — the consumer (port of `mdp_audio.sv`)

MiSTer's `mdp_audio.sv` is 266 lines and almost all of it is platform-neutral.
Keep: the 48 kHz consume divider (53.69 MHz / 1119 = 47983 Hz), the fade engine
(`$13xx` ramps 255 to 0 over `fade_sectors` sectors at 75 sectors/s, ~2808
clocks per step), the volume multiply, pause/resume, and the ~50 ms track-start
mute that hides the initial buffer fill. Replace: the DDRAM master and the 64 KB
ring-pointer protocol, which become reads from `paprium_cdda_buf`.

The internal 256-sample FIFO in that module can go — it exists to smooth DDR3
burst latency, and our buffer already is that smoothing.

### `core_top` mix

`core_top.sv` already sums `paprium_sfx_l/r` into the audio path with three
guard bits and a hard clip, sized deliberately to leave room for this. CDDA joins
as a third term. MiSTer gives CDDA **~+10 dB** against Paprium's loud cart SFX
(`cdda_mult = 294/256`, versus 93/256 for ordinary MD+ content) — carry that
constant over rather than rediscovering it, since it was set by A/B recording
against real hardware.

## Open questions for the hardware loop

1. **APF read latency** — sets the buffer depth. Instrument with the underrun
   counter and shrink the buffer to whatever actually works.
2. **Does `openfile` stall audio?** It runs while the player drains the other
   buffer half. If a track change audibly gaps, the fix is to open the next
   track speculatively or to widen the buffer.
3. **M10K budget** — decides BRAM versus CRAM for the buffer.
4. **`bridge_endian_little`** — `data_loader.sv` already handles the bridge's
   endianness for ROM loading; confirm 16-bit PCM samples come out the right way
   round rather than assuming.

---

# IMA ADPCM (`PPAD`) - format and decoder placement

The raw blob is 2.09 GB, which makes the music impractical to distribute or
rebuild. IMA ADPCM is a flat 4 bits per sample against 16 - 4:1 with no content
dependence - so about 535 MB. **Only the file changes**: the play path stays a
48 kHz stereo 16-bit consumer.

## Format

    0x00  char[4]  "PPAD"          magic, so a stale paprium.pcm fails LOUDLY
    0x04  u32      version = 1
    0x08  u32      sample rate = 48000
    0x0C  u32      channels = 2
    0x10  u32      block_samples = 505
    0x14  u32      ntracks = 64
    0x18  64 x 16 bytes: u64 offset, u32 adpcm_bytes, u32 pcm_samples
    0x1000 data, IMA blocks

The magic matters: the old layout starts with the track table at `0x000`, so a
stale `.pcm` parsed as `PPAD` would read audio bytes as offsets and stream noise.

## Block geometry - why 505

`block_samples - 1` must be a multiple of 8: the first sample of a block is the
header's seed predictor and is not encoded, and the rest are encoded eight at a
time. 505 is the WAV-standard answer for a 512-byte stereo block:

    505 samples -> 504 encoded/channel -> 4 hdr + 252 nibbles = 256 B/channel
    stereo frame = 512 bytes            4096-byte fetch = EXACTLY 8 frames

A first attempt used 256 and produced one extra sample per block. It decoded at
full amplitude and sounded plausible while drifting a sample per block, measuring
-2.9 dB SNR. **A layout mismatch does not sound like mild ADPCM, it sounds like
noise** - so the stereo order is stated identically here and in the packer:

    L header (4B), R header (4B), then alternating L 4 bytes / R 4 bytes

Every block is self-contained, carrying its own predictor and step index per
channel, so a seek need only land on a 512-byte boundary. Mid-block resume would
need decoder state the fetch path cannot reconstruct.

Stop on the table's `pcm_samples`, not on the byte length: the final block pads to
a multiple of 8 and would otherwise emit stray samples at every track end.

## Where the decoder goes - decided by M10K, not preference

    decode on the WRITE side (ring holds PCM)
        4096 B IMA = 8 frames = 4040 samples = 16,160 B PCM
        4 chunks = 64,640 B = 505 Kbit = ~50 M10K, against 14 spare   IMPOSSIBLE

    decode on the READ side (ring holds IMA)
        same 16 KB ring now holds 16,160 samples = 0.337 s, up from 0.085 s
        4x the buffering for no extra memory                          CHOSEN

So the ring stores compressed blocks and the decoder sits between it and the
player. Fetch bandwidth also drops 4x, which is free headroom on the SD path.

**Registered, not combinational.** Nibble arithmetic must not land on the 48 kHz
sample path - the same mistake as the `srate+1` adder in front of the `aclk` mux,
which cost 0.4 ns of setup and four seeds' worth of grief. 48 kHz x 2 channels is
96k updates/second; there is no throughput pressure, only depth.

Measured on 20 s of Intercom: **3.95x, SNR 37.9 dB**, judged indistinguishable by
ear against the source.
