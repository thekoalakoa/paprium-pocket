# Build reference: fit and timing gates

Tell the variants apart by **M10K**, not ALM: cmdlog is always **308** (the 16 KB
ring), shipping is **294**. ALM alone does not distinguish them, and mistaking one
for the other already caused a gate to be set on the wrong baseline.

## Measured builds

| variant  | build             | ALM    | M10K | slack  | TNS    | boots? |
|----------|-------------------|--------|------|--------|--------|--------|
| shipping | `61d1ddd3` CURRENT| 16,900 | 294  | -2.539 | -1,201 | YES |
| shipping | remap (reverted)  | 16,900 | 294  | -2.539 | -1,201 | boots, but cell-room floor breaks - see PORT_PLAN |
| shipping | 6-btn tied off    | 18,051 | 294  | -2.666 | -1,559 | YES |
| cmdlog   | budget capture    | 18,117 | 308  | ?      | ?      | YES |
| cmdlog   | sticky counters   | 18,141 | 308  | ?      | ?      | YES |
| cmdlog   | Probe B v1        | 18,209 | 308  | -2.957 | -2,844 | **NO - garbage at boot** |
| cmdlog   | Probe B v2        | 18,283 | 308  | -2.576 | -1,204 | **YES - valid capture** |
| shipping | ima1 seed default | 18,181 | 294  | -3.789 | -2,099 | not tried - fails both gates |
| shipping | ima1 seed 3       | 18,186 | 294  | -2.750 | -1,584 | not tried - fails setup |
| shipping | ima1 seed 5       | 18,194 | 294  | -2.596 | -1,428 | **YES - IMA ADPCM shipping** |
| shipping | ima1 seed 7       | 18,190 | 294  | -2.867 | -3,647 | not tried - fails both gates |

The two `?` rows had their reports overwritten before `scripts/archive_fit.sh`
existed. Archive every build from now on.

**Probe B v2 is the first cmdlog build with archived timing that is confirmed to
boot** - it produced a valid 1,243-entry capture. So a cmdlog is now judged against
a cmdlog, not a borrowed shipping-variant threshold. Note it passed the agreed
gate on timing while sitting 142 ALM over the old proxy ceiling, which is what
retired ALM as a gate.

**A passing gate is not a passing build.** The remap row above cleared every timing
criterion identically to shipping and still broke the cell-room floor - because the
fault was firmware placement, which timing cannot see. Smoke is a separate hurdle,
never implied by the numbers.

## Install rule

**Hard:**

- M10K = 308 for a cmdlog build (the variant fingerprint)
- worst slack >= about **-2.60**   **LESS NEGATIVE IS BETTER**

      -2.50  PASSES   (less negative than -2.60)
      -2.90  FAILS    (more negative than -2.60)

  Written out because it has been inverted twice in this project. "<= -2.67" reads
  naturally as a threshold and admits -3.0, which is Probe-B-v1 class - a bitstream
  that glitched at boot. The comparison is on the number line, not on badness.
- TNS >= about -1,600
- smoke in order: **boot -> cell room -> INTERCOM**. Garbage at boot, pull it

**Advisory:**

- **ALM. Log it, do not gate on it.** Do not override a timing fail because ALM
  looks low, and do not block a timing pass because ALM is over a proxy ceiling.

### Seed spread is wider than 0.55 ns - measured

The ima1 sweep, one tree, four fitter seeds:

    default  -3.789   hold -0.112
    seed 3   -2.750   hold +0.056
    seed 5   -2.596   hold +0.004
    seed 7   -2.867   hold -0.001

**1.19 ns of setup spread on identical RTL**, against the 0.25-0.55 ns assumed
before. So a single bad fit is not evidence that a change broke timing - at 98%
occupancy the placement is the dominant term, and the critical paths it produces
(VDP prescaler -> 68000, mcu_mem -> SDRAM address) are in logic nobody touched.

Two consequences worth keeping:

- **Do not conclude "the change cost 1.2 ns" from one fit.** Re-seed first.
- **Do not grind seeds either.** Three or four is data; ten is a lottery ticket
  with a 25-minute draw. If none land, shrink the logic.

Hold is part of the gate, not a footnote: seeds default and 7 fail hold in the
FAST corner (0C) while passing it in the slow one. Read the multicorner summary,
not just the slow model.

### A firmware-only change must CHANGE THE BITSTREAM

`scripts/build_mcu.sh` compiles to `build_output/mcu/mcu.txt` and **does not
install it**. It prints `rtl/PAPRIUM/mcu.txt` as a "reference build for
comparison", which reads like confirmation and is not. Quartus reads
`rtl/PAPRIUM/mcu.txt` (`$readmemh` in `mcu_core.sv`), so a build after
`build_mcu.sh` alone uses the OLD firmware.

    cp build_output/mcu/mcu.txt rtl/PAPRIUM/mcu.txt      # or the build is a no-op

This cost a whole 25-minute fit, and the failure is invisible to the timing gate:
ALM, M10K, setup and hold all came back **identical to shipping**, which is
exactly what "firmware-only, no RTL touched" is supposed to look like. It was
also exactly what "nothing changed at all" looks like.

**So gate a firmware-only change on TWO conditions, not one:**

    fit metrics identical to the reference   -> no RTL moved        (necessary)
    bitstream md5 DIFFERENT from reference   -> the firmware got in (necessary)

Identical metrics AND an identical bitstream means the build is void. Check the
hash before installing; the timing report cannot tell you.

### Why ALM is advisory

It was only ever a stand-in, adopted because no booting cmdlog had archived timing.
Probe B v2 *is* that missing report, and it shows the proxy and the thing it stood
for disagreeing: ALM 142 over the ceiling, while slack and TNS sit on top of
shipping's rather than the broken build's.

At ~99% occupancy ALM is not a monotonic function of RTL size. Measured twice:

- Removing the 0xDB counters **raised** ALM by 74 (18,209 -> 18,283)
- Tying off `cfg_6btn` **raised** ALM by 1,151 while verifiably removing the logic
  (`JCNT` and `JTMR` appear zero times in that build)

So chasing a hundred-odd ALMs by deleting a comparator is not a meaningful
intervention. Timing is what separated the build that failed to boot from the ones
that did, and timing is what to gate on.

**Never gate against Probe B v1.** It is the failure, not the reference.


## The boot threshold, measured

Three shipping-variant bitstreams have now been run on hardware, which brackets
where a build stops working:

| build | worst setup | boots? |
|---|---|---|
| `61d1ddd3` shipping | **-2.539** | **YES** |
| ratestep2 seed 2 | **-2.715** | **NO - glitches at boot** |
| Probe B v1 (cmdlog) | -2.957 | NO - garbage at boot |

`ima1` seed 5 booted and ran clean at **-2.596 with 4 ps of gate margin**, which
moves the known-good edge down from -2.539. The boundary is now between **-2.596
and -2.715**. Note what that margin is worth: 4 ps is not confidence, it is a
number that happened to land on the right side. It booted; that is evidence about
-2.596, not about thin margins in general.

**So the boundary is between -2.539 and -2.715**, and the earlier `-2.67` gate sat
*inside* that untested band. It has been tightened to **-2.60**, which is inside
the region where a build is known to work rather than inside the region where we
had never looked.

Seed 2 was installed deliberately, against the gate and against the reviewer's
advice, as a listen test - the reasoning being that "does the fix work" and "can we
ship it" are separate questions. It did not boot, so it answered neither. The gate
was right and the shortcut bought nothing.

Two things follow:

- **A near-miss is not a soft miss.** -2.715 is 0.045 outside the old gate and
  still does not run.
- **The remaining seeds need to reach about -2.54, not -2.67.** That is a much
  narrower target than the seed spread so far (-2.961 to -2.715) has hit.


## Process: the gate predicts, hardware decides

**Every seed gets a boot test.** A boot is about two minutes with the card already
to hand, and it is authoritative where the gate is only a prediction - one that has
been wrong in both directions:

- it passed Probe B v2 (-2.576), which worked
- its -2.67 line sat inside the band where builds turn out not to run

So the numbers are still archived first, and still reported, but they no longer
block a boot test. The gate's job is to set expectation and to catch a build that
is obviously far out (Probe-B-v1 class), not to decide on the tester's behalf what
is worth two minutes.

Order per seed:

1. `archive_fit.sh <label>` - report AND bitstream, before anything overwrites them
2. install, keeping `61d1ddd3` one command from restore
3. boot -> cell room -> doorway
4. if it boots, do the listen; if not, restore and record the slack against the
   boot threshold table above

Each non-booting seed narrows the threshold, which is worth having on its own -
seed 2 at -2.715 is what turned "somewhere below -2.539" into a real bound.

**Shipping is a separate decision.** A build that boots and sounds right is a
candidate; the timing numbers inform how much confidence it carries, but the
tester's hardware is what says whether it works.


## The slack gate is a WARNING, not proof - measured

Two builds of identical RTL, differing by 0.014 ns, gave opposite results on
hardware:

| build | worst setup | hold | TNS | boots? |
|---|---|---|---|---|
| ratestep2 s4 | **-2.701** | +0.045 | -879 | **YES** |
| ratestep2 s2 | **-2.715** | +0.065 | -1,286 | **NO** |

14 picoseconds cannot be the difference between a working and a broken core. What
differs is **which paths fail**, not the single worst number - s4's TNS is far
better (-879 vs -1,286), so fewer paths miss even though its worst one misses by
about the same.

**So worst-case slack is a weak predictor.** Use it to catch a build that is
obviously far out - Probe-B-v1 class - and to set expectation. Do not use it to
conclude a core will run, and do not use it to refuse a two-minute boot test.
**Smoke is what counts.**

This also retires the idea of tuning the threshold. -2.67 was too loose, -2.60 was
proposed, and s4 at -2.701 boots - so no single number on this axis separates the
two populations.

### And a lucky fit is not a shipping candidate

s4 boots and sounds right, but it is one place-and-route out of four that happened
to land well, on RTL whose other three seeds sit at -2.72, -2.96 and -2.98. A build
that depends on a seed is not reproducible in any meaningful sense. If the firmware
form of the same fix lands at identity with 61d1ddd3, that is the copy to keep.
