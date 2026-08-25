`ifndef PAPRIUM_DEFS_SV
`define PAPRIUM_DEFS_SV

`define CLK_FREQ 53_693_175
// MEM_TIME is the fixed wait the MCU/CPU *_io state machines hold before
// capturing port-3 read data. On the original board this matched a real flash
// chip's fixed access time. On MiSTer the shared SDRAM port-3 round trip is
// longer and variable, so this is raised to safely exceed the wrapper's
// completion latency (boot-validation value; the proper fix is a completion
// handshake so this can return to a small number).
`define MEM_TIME 48
`define SRM_DELAY 0

`endif
