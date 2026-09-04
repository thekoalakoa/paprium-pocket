# The 0xDA payload CRC snapshot

A diagnostic for elevator issue #8. It hashes what each `0xDA` decompression
actually put in memory, so the same hash can be taken in Genesis Plus GX and the
two compared byte-for-byte.

**Why this and not more pointer checks.** The choreography, destinations, sources
and expanded lengths all measure correct. A wrong *unpack* - right source, right
destination, wrong bytes - fits every one of those measurements. This is the one
firmware-observable thing left in the stream path.

## Layout

In the snapshot arena (the 1024 bytes reclaimed from the unused object-table dump),
at `SNAP_OFF_ARENA = 8 + 640` within the save window.

    records, 16 bytes x 48, at arena + 0:
      +0   u32 src      the unpack source
      +4   u32 len      expanded length, ppm_unpack's return
      +8   u32 crc      CRC32 of the payload
      +12  u32 dst      the unpack destination

    meta, 20 bytes, at arena + 768:
      +0   u16 n        records written
      +2   u16 cap      48
      +4   u32 fence_crc
      +8   u32 fence_len   0x8000
      +12  u32 tag         0xC2C1C2C1
      +16  u32 fence_age   in-game frames since the fence was taken

`fence_age` is a **u32 at +16**, not packed into the fence field. The meta is 20
bytes, not 16; a reader expecting 16 will misparse.

The tag is **`0xC2C1C2C1`**. The original draft said `0xC2C1CRC1`, which is not a
valid hex literal - `R` is not a hex digit. Both sides use `0xC2C1C2C1`.

## The hash

IEEE, polynomial `0xEDB88320`, init and final xor `0xFFFFFFFF`, table-driven.

    per record: ppmio.sdram[dst + i]  for i in [0, min(len, 0x8000))
    fence:      ppmio.sdram[0 + i]    for i in [0, 0x8000)

**No `^1` byte swapping.** The unpacker writes with `^1` internally; the CRC reads
the bytes as they sit so the GPGX twin over `decoder_ram` needs no compensation.

## The fence is throttled, deliberately

32 KB is roughly 3 ms of table-driven CRC on this MCU. `ppm_snapshot_sat` runs on
every qualifying frame, so taking the fence there unconditionally would add about
18% to the frame budget of a processor that services the 68000 in real time - it
would starve the exact scene being measured.

    taken once per 60 in-game frames
    plus a refresh right after any 0xDA whose payload expanded inside [0, 0x8000)

In practice the refresh means the fence usually lines up exactly with the last
payload hashed, and `fence_age` says when it does not.

Per-record CRCs are not throttled: there are ~51 `0xDA` calls in a run, so the cost
is occasional and bounded.

## The fence is not a second opinion on big payloads

Payloads land at `dst = 0` and the largest measured expands to exactly `0x8000`,
which is the whole fenced region. **For a full-size chunk the fence and that
record's CRC hash the same bytes**, so they will agree trivially - that is one
measurement reported twice, not two that corroborate each other.

The fence earns its keep on **smaller** payloads, where it covers the region beyond
what the last unpack wrote and can therefore catch something else having changed
it. Read it that way, and treat the per-record CRC against GPGX as the real fork.

## The GPGX twin

Same algorithm over `decoder_ram[dst .. dst+len)` and a fence over
`decoder_ram[0, 0x8000)`. Same table, same tag, same print format.

## Reading it

| Result | Meaning |
|---|---|
| CRCs match | The payload is byte-correct. #8 leaves the stream path; next is 68000 -> VDP DMA and the name table |
| CRCs differ | The unpack is wrong. Still firmware, and the decompressor is the suspect |
| Rows of zeros | Print them. A suppressed zero has hidden a finding in this project before - `dst = 0` was the answer to the previous card |
