// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (the integration) - paprium_synth_bus: the synth's BUS RAM, the two mixing buses of a block
// (the BGM bus, 160 frames, and the SFX bus, 80 frames, as the cart mixes them; we reverse engineered the STM32F4's
// commands as close as possible, with hardware verification) as one 256 x 32 memory: word = one pair {R s16 [31:16],
// L s16 [15:0]}, BGM frame f at word f (0..159), SFX frame i at word 160 + i (160..239); words 240-255 unused ("bus
// RAM" in the synth design).
//
// One write port and one read port, one clock: an M10K in simple dual-port mode. The blocks that use it (B5, B6, B7,
// B8; the synth's blocks are listed in paprium_synth.sv's header) run one at a time inside a block and never read a
// word in the clock they write it (B5: "a frame is never read in a clock it is written"; B6: "a pair is read only after
// the last write of it is granted"; B7 reads only in P2 / P4 and writes only in P1 / P3; B8 only reads), so the
// mixed-port read-during-write mode is never used (no_rw_check). In simulation a read of the word written in the same
// clock returns garbage, so a bench catches any path that would rely on the M10K's undefined read-during-write value
// (paprium_synth_sram's rule).
module paprium_synth_bus (
	input             clk,
	input             we,
	input       [7:0] wa,
	input      [31:0] wd,
	input       [7:0] ra,
	output reg [31:0] rd
);
	(* ramstyle = "M10K, no_rw_check" *) reg [31:0] mem [0:255];
	always @(posedge clk) begin
		if (we) mem[wa] <= wd;
		rd <= mem[ra];
		// synthesis translate_off
		if (we && wa == ra) rd <= ~mem[ra] ^ 32'hA5A5_5A5A;   // the M10K's read-during-write is undefined
		// synthesis translate_on
	end
endmodule
