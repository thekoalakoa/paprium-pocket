// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (block B5; the synth's blocks are listed in paprium_synth.sv's header, here B4 =
// paprium_synth_gain and B10 = paprium_synth_cram) -
// paprium_synth_wave: the cart chip's 16 wave voices, sample for sample, after their gains (the firmware's
// docs/MCU_INTERFACE.md v1.3 3.10.3). We reverse engineered the STM32F4's commands as close as possible, with hardware
// verification.
//
// What one run does (start, one clock), as the cart's block mix does at this step, in voice order v = 0..15 (the
// chip's 10..25):
//   * nothing at all unless EN (FLAGS SEQON & PLAYING);
//   * a voice with ENV_STATE == 0, LEN == 0, ENV_LEVEL == 0 or MUTE != 0 is skipped: LAST_L = LAST_R = 0; POS,
//     DECLICK and the rest are left alone;
//   * else the gains: the gain chain (B4) gets the voice's ENV_LEVEL, GAIN_L / GAIN_R, BB and COMPAND and answers the
//     voice's two per-side gains; then the linear sample paths (COMPAND is always 0 in the cart's bank,
//     MCU_INTERFACE.md 3.10.3; the companded paths are not built):
//     - mono (one gain for both sides) when the two gains are equal or on the YM path (the cart's other mono switch is
//       only ever 0);
//     - a block that stays inside the sample takes a fast path with no end test, so a block that ends exactly on the
//       sample's end reads one byte past it (the bank keeps the chip's layout in CRAM, so that byte is the chip's);
//       else every sample is tested;
//     - per sample: the position moves on by STEP; at the sample's end a one-shot (LOOP = 0xFFFFFFFF) ends the voice
//       (ENV_STATE := 0, POS keeps the moved value, the rest of the block gets nothing), else the voice goes back to
//       LOOP; the signed byte there, scaled by the gain, is added to the bus (16-bit wrap, no clamp);
//     - LAST_L / LAST_R = this block's last outputs; at a one-shot end: stereo keeps the last outputs written (0 if
//       the very first sample ended), mono stores 0;
//     - declick: if DECLICK != 0, a short ramp from the old LAST is added to the block's first frames (at most 160);
//       then DECLICK := 0;
//     - POS written back.
//   Additions are mod 2^16, so the declick ramp is added in its own pass after the voice's samples (the chip's order).
//   DECLICK follows the chip on its writers' domain 0..0x7FFF (8 at a note-on, 0 here): a negative s16 value makes the
//   chip count through ~65k frames past its bus (a cart crash); here a value above 160 (as an unsigned 16-bit number)
//   ramps from 160.
//   The index is added to BASE in 22 bits (the CRAM window), the chip in 32: equal while BASE + idx < 0x400000, which
//   the chip's data keep (the bank ends at 0x1520FF; its reads past it land in the BGM ring as the chip's do).
//
// Ports (all clk_sys):
//   start / done (one clock each), en, ym (sampled at start), busy (start .. done);
//   the state RAM through B1's synth port (paprium_synth_if): hold e_rreq / e_raddr until e_rgnt, the word on e_rdata
//   in the next clock; hold e_wreq / e_waddr / e_wbe / e_wdata until e_wgnt (written at that edge). Per voice 10 reads
//   (words 8, 1, 7, 0, 2, 3, 4, 5, 6, 10) and then the writes (a skipped voice: word 6; a live one: word 0 POS, word 6
//   LAST, word 8 lane 0 ENV_STATE if it ended, word 4 lanes 2-3 DECLICK if it was not 0);
//   the gain chain (B4): g_req held with g_voice and the voice's fields until g_ack (one clock, g_l / g_r valid); a
//   request still high in its g_ack clock is not a new one;
//   CRAM port C client 0 (paprium_synth_cram, B10): cq_req held with the byte address cq_addr until cq_gnt, then
//   cq_done with c_data (the whole word). One word is cached per voice (cleared at each voice): a sample reads CRAM only
//   when its word is not the cached one, so a voice reads each word it touches once, in sample order. cq_addr is
//   valid while cq_req is high (B10 takes it only then);
//   the BGM bus (the BUS RAM's frames 0-159: [15:0] L, [31:16] R): read with bus_re / bus_ra, data on bus_rd in the
//   next clock; written with bus_we / bus_wa / bus_wd (registered) two clocks after its read. A frame is never read in
//   a clock it is written. bus_wa / bus_wd are valid while bus_we is high.
// Timing (estimated): about 30 clocks per voice for the state words, the gains and the writes, then one clock per
// sample while its word is cached plus one CRAM read per new word; the block is CRAM-read bound.
// Reset: sys_reset ends a run at once (no done); a CRAM read at the controller is swallowed by B10.
//
// Area (trimmed to save logic; every output the same on every clock where its strobe says it is valid): one position
// register (a1_pos: POS from the load, then the position of the sample in flight, then the POS written back), the
// sample's byte address taken from it (BASE + POS >> 8: a loop sets POS = LOOP << 8, so it is BASE + LOOP there), one
// 32-bit adder for both endpos (S_PREP2) and the per-sample step (S_RUN), its operand chosen by r_run (= st == S_RUN),
// the gains settled at g_ack, the multiplier fed by r_ga / r_gb alone (OLD LAST moved into them for the declick pass),
// the ramp multiplied by 32 k so both passes round / 256, the rounding as the bus adder's carry-in (LAST from the same
// adder in S_WB), one frame counter, and the fields kept only as wide as they are read.

module paprium_synth_wave (
	input             clk,
	input             reset,

	input             start,
	input             en,
	input             ym,
	output reg        done,
	output            busy,

	// the state RAM, synth side (B1)
	output            e_rreq,
	output      [7:0] e_raddr,
	input             e_rgnt,
	input      [31:0] e_rdata,
	output            e_wreq,
	output reg  [7:0] e_waddr,
	output reg  [3:0] e_wbe,
	output reg [31:0] e_wdata,
	input             e_wgnt,

	// the gain chain (B4)
	output            g_req,
	output      [3:0] g_voice,
	output     [15:0] g_level,
	output     [15:0] g_gain_l,
	output     [15:0] g_gain_r,
	output      [7:0] g_bb,
	output      [7:0] g_compand,
	input             g_ack,
	input      [15:0] g_l,
	input      [15:0] g_r,

	// CRAM port C, client 0 (B10)
	output reg        cq_req,
	output     [21:0] cq_addr,
	input             cq_gnt,
	input             cq_done,
	input      [15:0] c_data,

	// the BGM bus
	output            bus_re,
	output      [7:0] bus_ra,
	input      [31:0] bus_rd,
	output reg        bus_we,
	output reg  [7:0] bus_wa,
	output reg [31:0] bus_wd
);
	import paprium_synth_pkg::*;

	localparam [7:0] NS = 8'd160;                  // samples per block (the cart's)

	localparam [3:0] S_IDLE = 4'd0, S_LOAD = 4'd1, S_TEST = 4'd2, S_WSKIP = 4'd3, S_GAIN = 4'd4, S_PREP1 = 4'd5,
	                 S_PREP2 = 4'd6, S_RUN = 4'd7, S_DRAIN = 4'd8, S_DCK = 4'd9, S_DRAIN2 = 4'd10, S_WB = 4'd11,
	                 S_NEXT = 4'd12, S_DONE = 4'd13;
	reg  [3:0] st = S_IDLE;
	reg  [3:0] v;                                  // voice 0..15 (the chip's 10 + v)
	reg        r_ym;
	reg        r_run = 1'b0;                       // st == S_RUN, as a flop (set entering S_RUN, cleared leaving it)

	// ---- the voice's fields, as wide as they are read
	reg        r_stz, r_munz;                      // ENV_STATE == 0, MUTE != 0 (the skip test's two)
	reg  [7:0] r_bb, r_comp;
	reg [15:0] r_level, r_step, r_gainl, r_gainr, r_oldl, r_oldr;
	reg  [7:0] r_dc;                               // the declick count: DECLICK, or 160 if DECLICK > 160 (0: none)
	reg        r_lenhi;                            // LEN >= 2^24 (no 24-bit index reaches it)
	reg [23:0] r_len;                              // LEN[23:0]
	reg [23:0] r_loop;                             // LOOP[23:0]
	reg        r_one;                              // LOOP == 0xFFFFFFFF (one-shot)
	reg [21:0] r_base;

	// ---- loads: 10 words, one grant a clock; the word comes in the clock after its grant
	reg  [3:0] ld_i;                               // reads granted so far
	reg        cap_v;
	reg  [3:0] cap_i;
	function automatic [3:0] ld_word(input [3:0] i);
		case (i)
			4'd0: ld_word = VW_STATE;  4'd1: ld_word = VW_LEN;   4'd2: ld_word = VW_ENV;  4'd3: ld_word = VW_POS;
			4'd4: ld_word = VW_LOOP;   4'd5: ld_word = VW_BASE;  4'd6: ld_word = VW_STEP; 4'd7: ld_word = VW_GAIN;
			4'd8: ld_word = VW_LAST;   default: ld_word = VW_RATES2;
		endcase
	endfunction
	assign e_rreq  = (st == S_LOAD) && (ld_i < 4'd10);
	assign e_raddr = vaddr(v, ld_word(ld_i));

	// ---- the gains
	assign g_req     = (st == S_GAIN);
	assign g_voice   = v;
	assign g_level   = r_level;
	assign g_gain_l  = r_gainl;
	assign g_gain_r  = r_gainr;
	assign g_bb      = r_bb;
	assign g_compand = r_comp;
	wire [16:0] gsum   = {1'b0, g_l} + {1'b0, g_r};
	wire        g_mono = (g_l == g_r) || r_ym;    // the cart's mono test, on the answer in its g_ack clock

	// ---- per-voice constants
	reg        r_slow, r_mono;
	reg [15:0] r_ga, r_gb;                         // the multiplier's gains: L / R (mono: both g); OLD LAST in the declick pass
	reg        r_sg;                               // r_ga / r_gb hold OLD LAST (signed)
	wire [23:0] step160 = {1'b0, r_step, 7'd0} + {3'd0, r_step, 5'd0};

	// ---- stage A: a1_pos = POS (loaded), then the position of the sample in flight (A2), then the POS written back
	reg [31:0] a1_pos;
	reg  [7:0] a1_j;                               // samples computed (S_RUN); declick frame + 1 (S_DCK)
	reg        v2, end2;
	reg        stop, ended;
	// the one-word cache and its read
	reg        cv, cwait;
	reg [20:0] ctag;
	reg [15:0] cdat;

	// one adder: S_PREP2 POS + 160 STEP (endpos), S_RUN the next sample's position (POS + STEP)
	wire [31:0] n_pos = a1_pos + (r_run ? {16'd0, r_step} : {8'd0, step160});
	wire        n_chk = r_slow && (n_pos[31:8] >= r_len);          // r_slow holds !r_lenhi
	wire        n_end = n_chk && r_one;
	wire [31:0] n_p   = (n_chk && !r_one) ? {r_loop, 8'd0} : n_pos;
	wire [21:0] ad2   = r_base + a1_pos[29:8];     // A2's byte address (after a loop: BASE + LOOP, as LOOP << 8 >> 8)
	assign cq_addr = ad2;

	wire hit   = cv && (ctag == ad2[21:1]);
	wire emit  = r_run && v2 && !end2 && hit;
	wire take  = r_run && v2 && (end2 || hit);
	wire a1_go = r_run && (a1_j < NS) && !stop && (!v2 || emit);
	wire run_fin = r_run && !v2 && (stop || (a1_j == NS));
	wire [7:0] s_byte = ad2[0] ? cdat[15:8] : cdat[7:0];
	wire [7:0] frame  = a1_j - 8'd1;               // the frame of the sample in flight (S_RUN) / of the ramp step (S_DCK)

	// ---- the declick pass
	reg  [7:0] dc_k;

	// ---- stage B: B0 (the sample / ramp step), B1 (products, the bus word arrives), then the bus write
	reg        b0_v, b0_d, b1_v, b1_d;
	reg  [7:0] b0_f, b1_f;
	reg signed [13:0] b0_a;                        // a sample (s8) or 32 x the ramp factor k (k = 1..160)
	reg signed [24:0] b1_pa, b1_pb;                // the products' signs and low 24 bits
	reg [15:0] last_l, last_r;                     // the last sample's p[23:8] per side (LAST = it + its carry)
	reg        last_cl, last_cr;                   // its rounding carry
	wire signed [16:0] op_a = {r_sg & r_ga[15], r_ga};
	wire signed [16:0] op_b = {r_sg & r_gb[15], r_gb};
	wire signed [30:0] m_a  = b0_a * op_a;
	wire signed [30:0] m_b  = b0_a * op_b;
	// out = p / 256 toward zero = p[23:8] + c, c = (p < 0 and p[7:0] != 0) (a sample; the ramp's 32 k OLD / 256 = k OLD / 8);
	// one adder per side: bus + p[23:8] + c, and in S_WB 0 + LAST's p[23:8] + its c (bus_we is 0 there)
	wire        c_a = b1_pa[24] && (b1_pa[7:0] != 8'd0);
	wire        c_b = b1_pb[24] && (b1_pb[7:0] != 8'd0);
	wire        wb_sel = (st == S_WB);
	wire [15:0] add_la = wb_sel ? 16'd0 : bus_rd[15:0];
	wire [15:0] add_ra = wb_sel ? 16'd0 : bus_rd[31:16];
	wire [15:0] add_lb = wb_sel ? last_l : b1_pa[23:8];
	wire [15:0] add_rb = wb_sel ? last_r : b1_pb[23:8];
	wire        add_lc = wb_sel ? last_cl : c_a;
	wire        add_rc = wb_sel ? last_cr : c_b;
	wire b_idle = !b0_v && !b1_v && !bus_we;
	assign bus_re = b0_v;
	assign bus_ra = b0_f;

	// ---- write-back list
	reg  [1:0] wb_i;
	wire [3:0] wb_en = {r_dc != 8'd0, ended, 1'b1, 1'b1};       // DECLICK, ENV_STATE, LAST, POS
	wire [15:0] lw_l = (ended && r_mono) ? 16'd0 : bus_wd[15:0];      // S_WB, wb_i 1: bus_wd = LAST (see the adder)
	wire [15:0] lw_r = (ended && r_mono) ? 16'd0 : bus_wd[31:16];
	assign e_wreq = (st == S_WSKIP) || ((st == S_WB) && wb_en[wb_i]);
	always @(*) begin
		e_waddr = vaddr(v, VW_LAST); e_wbe = 4'b1111; e_wdata = 32'd0;
		if (st == S_WB) case (wb_i)
			2'd0: begin e_waddr = vaddr(v, VW_POS);   e_wbe = 4'b1111; e_wdata = a1_pos; end
			2'd1: begin e_waddr = vaddr(v, VW_LAST);  e_wbe = 4'b1111; e_wdata = {lw_r, lw_l}; end
			2'd2: begin e_waddr = vaddr(v, VW_STATE); e_wbe = 4'b0001; e_wdata = 32'd0; end
			2'd3: begin e_waddr = vaddr(v, VW_STEP);  e_wbe = 4'b1100; e_wdata = 32'd0; end
		endcase
	end

	assign busy = (st != S_IDLE);

	always @(posedge clk) begin
		done  <= 1'b0;
		cap_v <= 1'b0;

		// the loaded words (in the clock after their grant)
		if (cap_v) case (cap_i)
			4'd0: begin r_stz <= (e_rdata[7:0] == 8'd0); r_bb <= e_rdata[15:8]; r_munz <= (e_rdata[31:16] != 16'd0); end
			4'd1: begin r_lenhi <= (e_rdata[31:24] != 8'd0); r_len <= e_rdata[23:0]; end
			4'd2: r_level <= e_rdata[15:0];
			4'd3: a1_pos <= e_rdata;
			4'd4: begin r_one <= (e_rdata == 32'hFFFF_FFFF); r_loop <= e_rdata[23:0]; end
			4'd5: r_base <= e_rdata[21:0];
			4'd6: begin r_step <= e_rdata[15:0]; r_dc <= (e_rdata[31:16] > {8'd0, NS}) ? NS : e_rdata[23:16]; end
			4'd7: begin r_gainl <= e_rdata[15:0]; r_gainr <= e_rdata[31:16]; end
			4'd8: begin r_oldl <= e_rdata[15:0]; r_oldr <= e_rdata[31:16]; end
			default: r_comp <= e_rdata[31:24];
		endcase

		// stage B
		b1_v  <= b0_v;
		b1_d  <= b0_d;
		b1_f  <= b0_f;
		b1_pa <= {m_a[30], m_a[23:0]};
		b1_pb <= {m_b[30], m_b[23:0]};
		bus_we <= b1_v;
		bus_wa <= b1_f;
		bus_wd <= {add_ra + add_rb + {15'd0, add_rc}, add_la + add_lb + {15'd0, add_lc}};
		if (b1_v && !b1_d) begin last_l <= b1_pa[23:8]; last_cl <= c_a; last_r <= b1_pb[23:8]; last_cr <= c_b; end
		b0_v <= 1'b0;
		if (emit) begin b0_v <= 1'b1; b0_d <= 1'b0; b0_f <= frame; b0_a <= {{6{s_byte[7]}}, s_byte}; end
		if (st == S_DCK) begin b0_v <= 1'b1; b0_d <= 1'b1; b0_f <= frame; b0_a <= {1'b0, dc_k, 5'd0}; end

		// the CRAM read of A2's word
		if (cq_gnt) begin cq_req <= 1'b0; cwait <= 1'b1; end
		if (cwait && cq_done) begin cwait <= 1'b0; cv <= 1'b1; ctag <= ad2[21:1]; cdat <= c_data; end
		if (r_run && v2 && !end2 && !hit && !cq_req && !cwait) cq_req <= 1'b1;

		case (st)
			S_IDLE: if (start) begin
				r_ym <= ym;
				v    <= 4'd0;
				ld_i <= 4'd0;
				st   <= en ? S_LOAD : S_DONE;
			end
			S_LOAD: begin
				if (e_rreq && e_rgnt) begin cap_v <= 1'b1; cap_i <= ld_i; ld_i <= ld_i + 4'd1; end
				if (ld_i == 4'd10 && !cap_v) st <= S_TEST;
			end
			S_TEST: st <= (r_stz || (!r_lenhi && (r_len == 24'd0)) || (r_level == 16'd0) || r_munz) ? S_WSKIP : S_GAIN;
			S_WSKIP: if (e_wgnt) st <= S_NEXT;
			S_GAIN: if (g_ack) begin
				r_mono <= g_mono;
				r_ga   <= g_mono ? gsum[16:1] : g_l;
				r_gb   <= g_mono ? gsum[16:1] : g_r;
				r_sg   <= 1'b0;
				st     <= S_PREP1;
			end
			S_PREP1: st <= S_PREP2;
			S_PREP2: begin
				r_slow  <= !r_lenhi && (r_len < n_pos[31:8]);     // LEN < endpos: the tested path
				a1_j    <= 8'd0;
				v2      <= 1'b0;
				stop    <= 1'b0;
				ended   <= 1'b0;
				cv      <= 1'b0;
				last_l  <= 16'd0;
				last_r  <= 16'd0;
				last_cl <= 1'b0;
				last_cr <= 1'b0;
				st      <= S_RUN;
				r_run   <= 1'b1;
			end
			S_RUN: begin
				if (take && end2) begin ended <= 1'b1; stop <= 1'b1; end
				if (a1_go) begin
					v2 <= 1'b1; end2 <= n_end;
					a1_pos <= n_p; a1_j <= a1_j + 8'd1;
				end
				else if (take) v2 <= 1'b0;
				if (run_fin) begin st <= S_DRAIN; r_run <= 1'b0; end
			end
			S_DRAIN: if (b_idle) begin
				a1_j <= 8'd1;
				dc_k <= r_dc;
				r_ga <= r_oldl;
				r_gb <= r_oldr;
				r_sg <= 1'b1;
				st   <= (r_dc != 8'd0) ? S_DCK : S_WB;
				wb_i <= 2'd0;
			end
			S_DCK: begin
				a1_j <= a1_j + 8'd1;
				dc_k <= dc_k - 8'd1;
				if (dc_k == 8'd1) st <= S_DRAIN2;
			end
			S_DRAIN2: if (b_idle) begin wb_i <= 2'd0; st <= S_WB; end
			S_WB: if (!wb_en[wb_i] || e_wgnt) begin
				wb_i <= wb_i + 2'd1;
				if (wb_i == 2'd3) st <= S_NEXT;
			end
			S_NEXT: begin
				ld_i <= 4'd0;
				v    <= v + 4'd1;
				st   <= (v == 4'd15) ? S_DONE : S_LOAD;
			end
			S_DONE: begin done <= 1'b1; st <= S_IDLE; end
			default: st <= S_IDLE;
		endcase

		if (reset) begin
			st <= S_IDLE; r_run <= 1'b0; done <= 1'b0; cq_req <= 1'b0; cwait <= 1'b0; cv <= 1'b0; cap_v <= 1'b0;
			b0_v <= 1'b0; b1_v <= 1'b0; bus_we <= 1'b0; v2 <= 1'b0;
		end
	end

endmodule
