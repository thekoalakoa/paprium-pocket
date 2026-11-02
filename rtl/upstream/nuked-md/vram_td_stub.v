// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 new core - TeraDrive detection stub: a tiny "bank 2" of VRAM for the game's 128 KB test.
//
// Paprium asks once per boot whether the console has 128 KB of VRAM ($BC81C, run from $BC944 with the display
// off): it turns the VDP's 128 KB mode on, writes $5A02 to VRAM $10000 and $A501 to $0000, reads $10000 back and
// turns the mode off again. Only a TeraDrive passes; the game then reports code B (8 KB of Z80 RAM) and shows the
// TeraDrive in the Boom Box. In 128 KB mode the VDP puts the high byte of each word on a second VRAM bank, on the
// RD bus, with its own write strobe WE1 and the shared RAS1 / CAS1 / OE1 and row / column address on AD.
//
// This is NOT a second 64 KB bank (that costs 64 M10K the device does not have). It is a 64-byte store that
// answers that bank's random port only, at the same clock edges as vram.v's random port (row at RAS fall, column at
// CAS fall, a transfer cycle = OE low at RAS fall, the write on every clock of ~RAS & ~CAS & ~WE with the address
// held before the edge, the read through a one-clock row register as vram_ip's registered address gives). Its index
// is {col[7], row[3:0], col[0]}: in 128 KB mode the VDP puts A9-A2 on AD at RAS and {A16, A15-A10, A1} at CAS
// (measured on an md_board bench running the game's own test: it writes VRAM $10000 at row 0 / column $80 and $0000
// at row 0 / column 0), so the index is the byte address {A16, A5-A1} of the word: VRAM $00000-$0003F and $10000-$1003F,
// aliased every 64 bytes. The game's test uses $0000 and $10000 only (and nothing in the game uses
// 128 KB mode outside the test: 1 VR write in 43,472 GPGX frames, in our TeraDrive study). There is no serial port:
// SD is never driven (the test runs with the display off). A real TeraDrive's bank 2 also answers every bank-1
// read on RD; the VDP does not use RD in 64 KB mode (checked on a TeraDrive bench: a 64 KB workload with and without
// the stub).
//
// en = 0 (every Console value but TeraDrive): the store is never written and RD is never driven, so md_board's RD
// is exactly the 0.2.6 expression.
// pocket-end

module vram_td_stub
	(
	input            MCLK,
	input            en,          // td_en: Console = TeraDrive, no combined Mega CD unit
	input            RAS,
	input            CAS,
	input            WE,          // WE1 (bank 2)
	input            OE,
	/* verilator lint_off UNUSEDSIGNAL */
	input      [7:0] AD,          // row / column address (the index uses AD[7], AD[3:0])
	/* verilator lint_on UNUSEDSIGNAL */
	input      [7:0] RD_i,        // write data (the VDP drives RD)
	output reg [7:0] RD_o,
	output           RD_d         // 0 = driving RD
	);

	// only the address bits the index uses are kept: row A5-A2, column A16 and A1
	reg  [3:0] row, row_q;
	reg        col7, col0;
	reg        dt, o_RAS, o_cas, o_valid;
	// pocket: 0.3.0 synth step (test build 5, the hardware test build of the synth; one of the M10K savings, a project
	// decision) - the 64 x 8 store in an MLAB, not an M10K: the same write and registered read (the attribute only
	// places it; RD_o is still the read register)
	(* ramstyle = "MLAB" *) reg  [7:0] mem [0:63];

	integer i;
	initial begin
		for (i = 0; i < 64; i = i + 1) mem[i] = 8'd0;
		RD_o = 8'd0;
		row = 4'd0; row_q = 4'd0; col7 = 1'b0; col0 = 1'b0;
		dt = 1'b0; o_RAS = 1'b1; o_cas = 1'b0; o_valid = 1'b0;
	end

	wire       cas = ~RAS & ~CAS;
	wire       wr  = cas & ~WE;
	wire       rd  = cas & ~OE & ~dt;
	wire [5:0] wi  = {col7, row, col0};     // the write: the address held before the edge
	wire [5:0] ri  = {col7, row_q, col0};   // the read: the row the RAM saw one clock earlier

	assign RD_d = ~o_valid;

	always @(posedge MCLK) begin
		if (en & wr) mem[wi] <= RD_i;
		if (en & rd) begin
			RD_o    <= mem[ri];
			o_valid <= 1'b1;
		end
		else if (~en | CAS | OE) o_valid <= 1'b0;

		row_q <= row;
		if (o_RAS & ~RAS) begin
			dt  <= ~OE;
			row <= AD[3:0];
		end
		if (~o_cas & cas) {col7, col0} <= {AD[7], AD[0]};
		o_RAS <= RAS;
		o_cas <= cas;
	end

endmodule
