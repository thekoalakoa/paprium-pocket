// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (part of block B2, paprium_synth_sched; the synth's blocks are listed in paprium_synth.sv's
// header) - paprium_synth_tim6: the cart chip's TIM6 block decision, one TIM6 instant at a time (combinational): the
// scheduler half of the cart's TIM6 interrupt, with the block itself (its envelope and mix) replaced by "mix = 1 at
// this index" (the block runs atomically after the decision, the firmware's docs/ALLOWLIST.md, row B40). We reverse
// engineered the STM32F4's commands as close as possible, with hardware verification.
//
// The scheduler's words (16 bits each in the cart):
//   path  0 = cart-DAC (DT) path, 1 = YM-DAC path (CONFIG writes 0 or 1 only)
//   half  HALF: 0 (before the first CONFIG), 800 (YM NTSC) or 960 (DT, YM PAL)
//   nblk  NBLK: 0, 5 or 6
//   blk   BLKCNT, blocks mixed mod 4,096
//   fp    FPEND (the tick sets it; a BGM module start and this decision clear it)
//   cur   CUR, the half the DMA was last seen in
//   fill  FILL, the half the blocks fill
//   cnt   blocks of this half / frame (0..NBLK, or 0xFF after a CONFIG)
// pos = the DT DMA position (0..1,919) at this instant, 0 when HALF = 0 or the DMA is stopped. The cart reads both
// rings' positions and applies its CONFIG again if they are more than 32 apart; here both rings are one index, so that
// branch cannot be taken and is not built (the cart's own condition is false for equal positions).
//
// Domain (what the scheduler can hold): path 0 / 1, half in {0, 800, 960}, nblk in {0, 5, 6}, cnt 8 bits (the chip's
// u16 never leaves 0..NBLK or 0xFF), fill / cur / fp 0 / 1, pos 0..1,919. Inside it every output equals the chip's.
//
// Clock: none (pure function); paprium_synth_sched registers the result.

module paprium_synth_tim6 (
	input             path,
	input      [10:0] half,
	input       [2:0] nblk,
	input      [11:0] blk,
	input             fp,
	input             cur,
	input             fill,
	input       [7:0] cnt,
	input      [10:0] pos,

	output reg        mix,                         // a block (its envelope and mix) runs at this instant
	output reg [10:0] idx,                         // the block's first dac_buf entry: HALF x fill + 160 x cnt
	output reg        incomplete,                  // DIAG.INCOMPLETE + 1: a DT half left incomplete
	output reg [11:0] blk_o,
	output reg        fp_o,
	output reg        cur_o,
	output reg        fill_o,
	output reg  [7:0] cnt_o
);

	wire [7:0]  nb8 = {5'd0, nblk};

	// HALF x fill + 160 x cnt (cnt < NBLK <= 6 whenever a block is mixed; the chip's 32-bit sum, < 1,920 here)
	function automatic [10:0] bidx(input [10:0] h, input f, input [7:0] c);
		bidx = (f ? h : 11'd0) + {c[3:0], 7'd0} + {2'd0, c[3:0], 5'd0};
	endfunction

	reg        c1;
	reg  [7:0] k1;

	always @(*) begin
		mix = 1'b0; idx = 11'd0; incomplete = 1'b0;
		blk_o = blk; fp_o = fp; cur_o = cur; fill_o = fill; cnt_o = cnt;
		c1 = 1'b0; k1 = cnt;
		if (!path) begin
			// ---- the DT path ----
			// the half the DMA is in: pos >= HALF, unsigned
			c1 = (pos >= half);
			k1 = cnt;
			if (cur != c1) begin
				// a half change with fewer than NBLK blocks counts as incomplete
				if (cnt < nb8) incomplete = 1'b1;
				cur_o  = c1;
				fill_o = (pos < half);
				k1     = 8'd0;
			end
			cnt_o = k1;
			if (half == 11'd0) begin
				// HALF = 0 only counts
				if (k1 < nb8) cnt_o = k1 + 8'd1;
			end
			else if (k1 < nb8) begin
				// a block of this half
				mix   = 1'b1;
				idx   = bidx(half, fill_o, k1);
				cnt_o = k1 + 8'd1;
				blk_o = blk + 12'd1;
			end
		end
		else begin
			// ---- the YM-DAC path ----
			k1 = cnt;
			if (fp && (cnt < nb8)) begin
				// the old frame's next block (FPEND stays)
				if (half != 11'd0) begin
					mix   = 1'b1;
					idx   = bidx(half, fill, cnt);
					cnt_o = cnt + 8'd1;
					blk_o = blk + 12'd1;
				end
				else cnt_o = cnt + 8'd1;
			end
			else begin
				if (fp) begin
					// the new frame starts at dac_buf_L[0]
					fp_o = 1'b0; cur_o = 1'b0; fill_o = 1'b0; k1 = 8'd0;
				end
				cnt_o = k1;
				if (k1 < nb8) begin
					if (half != 11'd0) begin
						mix   = 1'b1;
						idx   = bidx(half, fill_o, k1);
						blk_o = blk + 12'd1;
					end
					cnt_o = k1 + 8'd1;
				end
			end
		end
	end

endmodule
