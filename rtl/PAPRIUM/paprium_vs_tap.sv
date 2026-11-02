// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 new core (the firmware's docs/MCU_INTERFACE.md v1.1) - the clk_md side of the VS counter (part of the
// firmware's freeze telemetry; B Jam, 2026-10-13). Instantiated once in core_top; the count itself is FPGAIO slot 16
// (FPGAIO = the MCU's register block in the FPGA, fpgio.sv; slot 16 = its register VSCNT).
//
// The VDP's vertical sync (md_board vdp_vsync2, active low, a clk_md signal that is a mux of two VDP latches) is
// sampled once on clk_md, and every start of a sync pulse (a falling edge as clk_md sees it) flips vs_tog. vs_tog is a
// level that moves at most once a frame (16.7 ms NTSC; a sync pulse lasts ~190 us), so one bit crosses into the MCU
// clock and no multi-bit value ever does: a three-stage synch_3 on clk_sys carries it (its entity attribute keeps the
// stages in flops), and fpgio counts the changes of the synchronised level. A change caught early or late by the
// first stage moves the count by one MCU clock, never adds or loses one. Two VS starts closer than ~4 clk_sys would
// merge; the VDP's are 16.7 ms apart.
//
// SDC (target/pocket/core_constraints.sdc, block VS): false path into the first stage only,
// *|paprium_vs_tap:*|synch_3:vs_sync|stage_1[*], through xf_col so an empty match is a critical warning; the later
// stages and the counter stay timed on clk_sys.
module paprium_vs_tap (
	input  wire clk_md,      // the VDP's clock (clk_md_107_39)
	input  wire vs_n,        // VDP vertical sync, active low (md_board vdp_vsync2), clk_md
	input  wire clk_sys,     // the MCU's clock (clk_sys_53_69)
	output wire vs_tog_s     // clk_sys: flips once per VS start
);

	reg vs_q;
	reg vs_qq;
	reg vs_tog;
	initial begin       // the configuration values: no sync pulse seen yet
		vs_q   = 1'b1;
		vs_qq  = 1'b1;
		vs_tog = 1'b0;
	end

	always @(posedge clk_md) begin
		vs_q  <= vs_n;
		vs_qq <= vs_q;
		if (vs_qq & ~vs_q) vs_tog <= ~vs_tog;
	end

	/* verilator lint_off UNUSEDSIGNAL */
	wire vs_rise, vs_fall;   // synch_3's edge pulses: not used (fpgio detects the change itself)
	/* verilator lint_on UNUSEDSIGNAL */
	synch_3 vs_sync (.i(vs_tog), .o(vs_tog_s), .clk(clk_sys), .rise(vs_rise), .fall(vs_fall));

endmodule
