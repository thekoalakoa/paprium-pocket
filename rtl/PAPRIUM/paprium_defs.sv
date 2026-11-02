// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)
`ifndef PAPRIUM_DEFS_SV
`define PAPRIUM_DEFS_SV

// pocket: 0.3.0 new core (the clock-following change) - `CLK_FREQ is retired. The clock value is the CLK_HZ / CLK_MD_HZ
// parameter pair of core_top, passed down; scripts/clkcheck.py refuses a clock literal elsewhere.
// MEM_TIME is the fixed wait the MCU/CPU *_io state machines hold before
// capturing port-3 read data. On the original board this matched a real flash
// chip's fixed access time. On MiSTer the shared SDRAM port-3 round trip is
// longer and variable, so this is raised to safely exceed the wrapper's
// completion latency (boot-validation value; the proper fix is a completion
// handshake so this can return to a small number).
`define MEM_TIME 48
`define SRM_DELAY 0

`endif
