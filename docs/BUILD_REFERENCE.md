# Build reference: fit and timing gates

```
Reference points. CORRECTED - an earlier version of this file mislabelled a
shipping-variant build as a working cmdlog, and a gate was nearly set on it.

Tell the variants apart by M10K: cmdlog is ALWAYS 308 (the 16 KB ring); shipping
is 294. ALM alone does not distinguish them.

  variant   build              ALM      M10K  slack    TNS      boots?
  -------   -----------------  -------  ----  -------  -------  ------
  shipping  61d1ddd3 CURRENT   16,900   294   -2.539   -1,201   YES
  shipping  6-btn tied off     18,051   294   -2.666   -1,559   YES
  cmdlog    budget capture     18,117   308   ?        ?        YES
  cmdlog    sticky counters    18,141   308   ?        ?        YES
  cmdlog    Probe B v1         18,209   308   -2.957   -2,844   NO - garbage at boot

THERE IS NO ARCHIVED TIMING FOR ANY CMDLOG BUILD THAT BOOTED. The two '?' rows had
their reports overwritten before scripts/archive_fit.sh existed.

GATE for the next cmdlog build, until a real cmdlog report exists:

  ALM / M10K    <= 18,141 / 308
  worst slack   no worse than about -2.67
  TNS           no worse than about -1,600
  ambiguous     slack/TNS nearer -2.9 / -2,800 -> DO NOT INSTALL, even if ALM is fine
  will not close-> drop unaligned_da; every 0xDA dest is in the rows anyway

The -2.67 / -1,600 thresholds come from a SHIPPING-variant build, so they are
probably stricter than a cmdlog build needs - a cmdlog carries 14 more M10K and
~90 more ALMs. Erring strict is the safe direction: the cost of being too strict is
dropping a counter, the cost of being too loose is another core that will not boot.

Never gate against Probe B v1. It is the failure, not the reference.
```
