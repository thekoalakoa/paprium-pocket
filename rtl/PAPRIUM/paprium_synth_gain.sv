// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (block B4; the synth's blocks are listed in paprium_synth.sv's header, here B1 =
// paprium_synth_if and B2 = paprium_synth_sched) - paprium_synth_gain: the cart chip's gain chain for one wave voice:
// from the master levels, the boost slot, the voice's envelope level (through the level table T) and its two gains to
// the left and right gains of its samples, as the cart works them out before the voice's first sample (we reverse
// engineered the STM32F4's commands as close as possible, with hardware verification; the tables were worked out from
// our own study of how the cart behaves and checked on hardware).
//
// The held boost slot (the synth design's option (a) for it): with FLAGS.LEVELNZ = 0 the cart uses whatever value the
// slot last held. Within one call path only the cart's block mix writes that slot: its voice loop (a 16-bit value)
// and its SFX section's echo prefill (DT, FLAGS.SFXON 1, SFX echo 1), which stores the SFX ring's address there. So
// this block keeps the slot as {ring, 16-bit value}: every value the cart's own writers put there. Not done as the chip
// does (a remaining difference for the firmware's docs/ALLOWLIST.md, for B Jam with the synth's rows): the slot's
// content after a YM <-> DT path change (the two paths keep the slot in different places) and after other work of the
// cart ran between two blocks; reset gives 0 (the cart does not clear it).
//
// Domain (what the inputs can hold, from the chip's own writers): ENV_LEVEL 0..0x5FF (the envelope keeps it there);
// this block equals the chip for ENV_LEVEL -5..3,071 (T's whole 512 entries come in on the T port: paprium_synth_trom
// holds T[0..511], 512 x 9). Below -5 and above 3,071 the cart reads other data outside the table: not done here (T =
// 0 / 510 here). COMPAND is 0 by the firmware's docs/MCU_INTERFACE.md v1.3 3.10.3 ("the synth mixes linear"): the
// companded branch is not built. One more input of the cart's mono test is only ever stored as 0: not an input. Every
// other input is any 16-bit value; the products wrap mod 2^32 exactly as the chip's.
//
// Timing: raise v_start for one clock with the voice's inputs; hold v_level, v_gain_l / r and v_bb, and the globals,
// stable until v_done (one clock, 6 clocks after v_start). o_gl / o_gr / o_mono / o_g hold from v_done until the next
// v_start. sfx_sect (one clock, never while busy) = the block reaching its SFX section, once per block after the voice
// loop. The T port: t_addr is valid with t_rd (one clock, the clock after v_start); t_data must carry
// T[t_addr] in the next clock (an M10K with a registered address; the TABLES ROM can be shared). Clock: clk_sys only.

module paprium_synth_gain (
	input             clk,
	input             reset,

	// globals: B1 FLAGS / WMASTER / WBOOST and B2's YM path (s_ym)
	input       [5:0] g_flags,                     // FL_LEVELNZ, FL_SFXON, FL_SFXECHO
	input      [15:0] g_wm_l,                      // WMASTER.L
	input      [15:0] g_wm_r,                      // WMASTER.R
	input      [15:0] g_boost,                     // WBOOST.BOOST
	input      [15:0] g_wavemaster,                // WBOOST.WAVEMASTER
	input             s_ym,                        // the YM-DAC path now (B2)

	// one mixed voice (the cart's skip test passed: ENV_STATE, LEN and ENV_LEVEL != 0, MUTE == 0)
	input             v_start,
	input      [15:0] v_level,                     // ENV_LEVEL (s16)
	input      [15:0] v_gain_l,                    // GAIN_L
	input      [15:0] v_gain_r,                    // GAIN_R
	input       [7:0] v_bb,                        // BB (the chip tests the byte != 0)
	output reg        v_done,
	output reg [15:0] o_gl,                        // the voice's left gain
	output reg [15:0] o_gr,                        // its right gain
	output            o_mono,                      // the cart's mono case (both sides one gain)
	output     [15:0] o_g,                         // (gL + gR) >> 1 (the gain of both sides when mono)
	output     [15:0] o_m,                         // the master gain in flight: mL in clocks 3-4 after v_start, mR in clock 5

	// the block's SFX section
	input             sfx_sect,

	// T[0..511] (the level table)
	output            t_rd,
	output      [8:0] t_addr,
	input       [8:0] t_data,

	output            busy,
	output     [31:0] o_slot                       // the held slot as the chip's u32 (benches)
);

	import paprium_synth_pkg::*;

	localparam [31:0] C_RING = 32'hC01E_5800;      // the SFX ring's SDRAM address, as the cart stores it in the slot

	// ---- the held slot: {ring, value}, kept as the multiplier's operand slot + 256: 0xC01E5900, or a 17-bit value.
	// Its low 24 bits go to the multiplier; the top byte (0xC0 for the ring, else 0) adds
	// (wm x 0xC0 mod 256) << 24 = ((3 wm) mod 4) << 30 to the product mod 2^32, i.e. {wm[1] ^ wm[0], wm[0]} on bits
	// 31:30 only. s_bp = bits 16:0 of slot + 256 (each store adds the 256 as it writes, trimmed to save logic), s_ring =
	// the ring; bits 23:17 are the ring's (0x1E5900 >> 17 = 0x0F) or 0.
	localparam [23:0] C_RBP = C_RING[23:0] + 24'h00_0100;
	reg        s_ring;
	reg [16:0] s_bp = 17'h00100;                  // power-up = the reset value
	wire [15:0] s_v  = s_bp[15:0] - 16'h0100;     // the voice loop's value (o_slot, benches only)
	assign o_slot = s_ring ? C_RING : {16'd0, s_v};
	wire [23:0] bp   = {C_RBP[23:17] & {7{s_ring}}, s_bp};
	// the slot's two writers: the SFX section's prefill, else the voice loop; the ring's value + 256 = 0x5800 + 0x100
	// (C_RBP[16:0], no carry into bit 16)
	wire        st_ring  = sfx_sect & g_flags[FL_SFXON] & ~s_ym & g_flags[FL_SFXECHO];
	wire        st_voice = v_start & g_flags[FL_LEVELNZ];
	wire [15:0] s_new    = st_ring ? C_RING[15:0] : (|v_bb) ? g_boost : {1'b0, g_boost[15:1]};

	// ---- the sequence: ph[k] = the k-th clock after v_start
	reg  [5:1] ph;
	assign busy   = v_start | (|ph);

	// level / 6 toward zero for 0..3,071 (((x >> 1) * 683) >> 11, exact there: checked by our table generator) = T's
	// address 0..511; the class of the level picks the out-of-domain value
	wire        lv_neg = v_level[15];
	wire        lv_big = ~v_level[15] & ((|v_level[14:12]) | (&v_level[11:10]));
	(* multstyle = "dsp" *) wire [20:0] lv_m = v_level[11:1] * 10'd683;
	wire  [8:0] idx    = lv_m[19:11];
	assign t_rd   = ph[1];
	assign t_addr = idx;

	reg   [8:0] tr;                                // T (0..510)
	reg  [23:0] t1;                                // (wm * (slot + 256)) >> 8, the side in flight
	reg  [15:0] m;                                 // mL / mR
	reg   [8:0] a;                                 // (gain x T) >> 8, clamped, & 0x1FF
	assign o_m = m;

	// M1: wm x (slot + 256) mod 2^32
	wire [15:0] wm = ph[3] ? g_wm_r : g_wm_l;
	(* multstyle = "dsp" *) wire [39:0] p1l = wm * bp;
	wire  [1:0] p1h = p1l[31:30] + (s_ring ? {wm[1] ^ wm[0], wm[0]} : 2'd0);
	wire [31:0] p1  = {p1h, p1l[29:0]};
	// M2: WAVEMASTER x t1 mod 2^32, >> 8, clamp 0xFFFF
	(* multstyle = "dsp" *) wire [39:0] p2 = g_wavemaster * t1;
	wire [23:0] t2 = p2[31:8];
	// M3: gain x T (< 2^25: no wrap) for both sides, the side picked after the product (trimmed to save logic: no 16-bit
	// gain mux in front of the multiplier; the same q1 on every clock), >> 8, clamp 0xFFFF, & 0x1FF
	(* multstyle = "dsp" *) wire [24:0] q1l = v_gain_l * tr;
	(* multstyle = "dsp" *) wire [24:0] q1r = v_gain_r * tr;
	wire [24:0] q1 = ph[4] ? q1r : q1l;
	// M4: m x a (< 2^25), >> 8, clamp 0xFFFF, x 6 & 0xFFFF
	(* multstyle = "dsp" *) wire [24:0] q2 = m * a;
	wire [15:0] g1 = q2[24] ? 16'hFFFF : q2[23:8];
	wire [15:0] g6 = {g1[13:0], 2'b00} + {g1[14:0], 1'b0};

	assign o_mono = (o_gl == o_gr) | s_ym;
	wire [16:0] gs = {1'b0, o_gl} + {1'b0, o_gr};
	assign o_g    = gs[16:1];

	always @(posedge clk) begin
		if (reset) begin
			s_ring <= 1'b0;
			s_bp   <= 17'h00100;                // value 0
			ph     <= 5'd0;
			v_done <= 1'b0;
		end else begin
			ph     <= {ph[4:1], v_start};
			v_done <= ph[5];
			// the slot: the SFX section's prefill store, else the voice loop's
			if (st_ring | st_voice) begin
				s_ring <= st_ring;
				s_bp   <= {1'b0, s_new} + 17'h00100;
			end
		end
		// c2: T (the port's data for t_addr of c1, or the out-of-domain value)
		if (ph[2])
			tr <= lv_neg ? 9'd0 : lv_big ? 9'd510 : t_data;
		// c2 L, c3 R: M1
		t1 <= p1[31:8];
		// c3 L, c4 R: M2 + clamp
		m  <= (|t2[23:16]) ? 16'hFFFF : t2[15:0];
		// c3 L, c4 R: M3 + clamp + mask (u = q1 >> 8 <= 0x1FDFE: u > 0xFFFF is u[16])
		a  <= q1[24] ? 9'h1FF : q1[16:8];
		// c4 L, c5 R: M4 + clamp + x6
		if (ph[4]) o_gl <= g6;
		if (ph[5]) o_gr <= g6;
	end

endmodule
