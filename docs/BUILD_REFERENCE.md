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
- worst slack >= about -2.67   **LESS NEGATIVE IS BETTER**

      -2.50  PASSES   (less negative than -2.67)
      -2.90  FAILS    (more negative than -2.67)

  Written out because it has been inverted twice in this project. "<= -2.67" reads
  naturally as a threshold and admits -3.0, which is Probe-B-v1 class - a bitstream
  that glitched at boot. The comparison is on the number line, not on badness.
- TNS >= about -1,600
- smoke in order: **boot -> cell room -> INTERCOM**. Garbage at boot, pull it

**Advisory:**

- **ALM. Log it, do not gate on it.** Do not override a timing fail because ALM
  looks low, and do not block a timing pass because ALM is over a proxy ceiling.

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
