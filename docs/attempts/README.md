# Attempts that did not work, kept so they are not repeated

Each file is a diff that was built, fitted and rejected, with the numbers that
rejected it. They are here rather than deleted because the expensive part was
finding out, and because two of them were tried on reasoning that sounded right.

## stream-ptr-readback.patch.txt

**What:** make the live stream pointer readable by the MCU, so a per-frame audit
could say whether the 68000's DMA consumed exactly what the MCU unpacked. Aimed
at the elevator tile corruption (MisterPezz82 #8).

**Why it was rejected: it will not close timing, and area is not the reason.**

    read-back, combinational   seed 5  -2.774    seed 6  -3.040   seed 7  -2.911
    read-back, registered      seed 5  -4.026
    no-SFX variant + read-back seed 5  -2.959    ALM 90%, M10K 82%
    shipping, no read-back     seed 5  -2.596    ALM 98%, M10K 95%

`-2.715` is recorded in BUILD_REFERENCE.md as glitching at boot, so every one of
these is unusable.

**The last row is the important one.** Dropping the whole SFX mixer freed 1,600
ALMs and 40 M10K - 98% to 90% - and setup did **not** improve. So the failure is
not congestion, and no amount of freed area fixes it. That also refutes, without
building it, the plan to strip CDDA for headroom: if 1,600 ALMs buy nothing, the
~169-ALM IMA decoder buys nothing, and the cost would have been music.

**Two mechanisms were proposed for the cost and both were wrong:**

1. "It is placement luck, 77 cells cannot cost 0.2 ns" - refuted by three seeds
   clustering, which is data rather than spread by this project's own rule
2. "It is mux levels between the counter and the read bus, a flop stage breaks
   the path" - refuted by the registered version being 1.25 ns **worse**

No third mechanism is offered. What the five fits support is only that this design
has no headroom for a bus tap, which BUILD_REFERENCE.md said before any of it.

**If this is ever revived:** the firmware side is still in `mame.c`, guarded by
`PPM_SAT_SNAPSHOT` and compiled out - `snap_sptr_mismatch` / `_last` / `_worst`,
audited once per frame at `0xAF`, with `decode_sat_snapshot.py` already able to
read and interpret it including the "landed exactly where the MCU finished" case.
Only the RTL read path is missing. But prefer an approach that does not add a bus
tap at 98%: comparing what the MCU *unpacked* against what the scene should
contain is firmware-only and sidesteps the wall entirely.
