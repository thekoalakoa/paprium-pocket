// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (the synth's first version) - paprium_synth_sram: the synth's state RAM, used by the
// synth's MCU interface block (paprium_synth_if).
//
// 256 x 32, one write port with byte lanes and one read port, one clock: an M10K in simple dual-port mode. The arbiter
// (paprium_synth_if) never reads the word it writes in the same clock, so the mixed-port read-during-write mode is
// never used (no_rw_check). In simulation a read of the word written in the same clock returns garbage, so a bench
// catches any path that would rely on the M10K's undefined read-during-write value.
module paprium_synth_sram (
	input             clk,
	input             we,
	input       [7:0] wa,
	input       [3:0] be,
	input      [31:0] wd,
	input       [7:0] ra,
	output reg [31:0] rd
);
	(* ramstyle = "M10K, no_rw_check" *) reg [3:0][7:0] mem [0:255];
	always @(posedge clk) begin
		if (we) begin
			if (be[0]) mem[wa][0] <= wd[7:0];
			if (be[1]) mem[wa][1] <= wd[15:8];
			if (be[2]) mem[wa][2] <= wd[23:16];
			if (be[3]) mem[wa][3] <= wd[31:24];
		end
		rd <= mem[ra];
		// synthesis translate_off
		if (we && wa == ra) rd <= ~mem[ra] ^ 32'h5A5A_A5A5;   // the M10K's read-during-write is undefined
		// synthesis translate_on
	end
endmodule
