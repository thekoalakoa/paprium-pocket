// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (block B7; the synth's blocks are listed in paprium_synth.sv's header, here B2 =
// paprium_synth_sched and B10 = paprium_synth_cram) -
// paprium_synth_echo: the synth's echo rings (the firmware's docs/MCU_INTERFACE.md v1.3 3.8 BGMRING / SFXRING, 3.10.1
// FLAGS / ECHOB / ECHOS).
//
// What it does, as the cart does it (we reverse engineered the STM32F4's commands as close as possible, with hardware
// verification): the four echo steps of every mixed block, each one a PHASE that the block sequencer starts in the
// cart's order:
//   P1 (phase 0) the BGM bus before the wave voices: on the YM-DAC path (input ym) or with FLAGS.BGMECHO 0, all 160
//      pairs 0. Else the ring prefill: the ring block DELAY blocks behind INDEX (8 bits), its 40 pairs {L, R}, each
//      side scaled by ECHOB.GAIN, each pair written to four bus pairs (held x4).
//   P2 (phase 1) the BGM ring write after the wave voices, in every mode, echo on or off: INDEX + 1, 0 past 0xFF
//      (ECHOB.INDEX written back once, e_echob_idx_we); then the ring block INDEX gets bus pairs 0, 4, .., 156 (the
//      pair at 4j, both halves as they are).
//   P3 (phase 2) the SFX bus before the channels: with FLAGS.SFXON 0, on the YM-DAC path, or with FLAGS.SFXECHO 0, all
//      80 pairs 0. Else the SFX ring prefill, as P1 with 20 pairs and ECHOS.GAIN, held x4.
//   P4 (phase 3) the SFX ring write after the channels, only with FLAGS.SFXON 1: ECHOS.INDEX + 1, 0 past 0xFF (written
//      back); the block gets SFX bus pairs 0, 4, .., 76. With FLAGS.SFXON 0 the phase does nothing (the cart skips the
//      channels and the ring write: index and ring unchanged).
// The cart keeps both indexes in 16 bits, always 0..255, and in our reference vectors they never change between two
// blocks and never exceed 0xFF (measured in our echo test runs), so the 8-bit INDEX is exact. DELAY is used only
// through & 0xFF (3.10.1). Echo switch values other than 0 / 1 are outside what the cart ever writes there, and the
// interface cannot hold them (the FLAGS bit is value == 1).
//
// Memories:
//   * BUS RAM (the block's two buses): word = one pair {R [31:16], L [15:0]}
//     (s16 each); BGM pair i at word BUS_BGM + i (i < 160), SFX pair i at BUS_SFX + i (i < 80); both bases multiples
//     of 4. Request / grant port as B1's state RAM: hold b_rreq / b_raddr until b_rgnt (sampled in that clock); the
//     word is on b_rdata in the NEXT clock only; hold b_wreq / b_waddr / b_wdata until b_wgnt (the write is done at
//     that clock's edge). Back-to-back requests keep the request up with the next address after a grant.
//   * CRAM through B10 (paprium_synth_cram): E client 1 = the ring reads (rq_*, a pair), E client 2 = the ring writes
//     (wq_*, a pair). A ring pair is the CRAM byte address CR_BGMRING + 160 b + 4 j (CR_SFXRING + 80 b + 4 j): L at +0
//     (bits 15:0), R at +2 (bits 31:16). A request is held until its grant (one clock), then dropped; a read ends with
//     rq_done and e_data in that clock.
//
// Ordering (B10's contract: two accesses of one word are ordered only when the second is raised after the first's
// q_gnt): every ring read of P1 / P3 has returned before the phase's done, and ring writes are raised only in P2 / P4,
// so a block's prefill read of a ring word comes before any later write of it (delay 255 reads the very block P2
// rewrites). The sequencer (S10) starts each phase only after the step before it is done: P1 after the envelope
// (B3), P2 after the wave voices (B5: their port-C reads of samples past the bank end land in BGMRING block 0, which P2
// rewrites when the BGM index wraps: B5's done must follow its last read's data), P3 after P2, the channels (B6)
// after P3, P4 after B6, the output stage (B8) after P4. start only while busy = 0. done (one clock) = every bus write
// of the phase granted (P1 / P3) or every ring write granted (P2 / P4: handed to the controller; B2 waits for B10's
// idle before the block counts as finished).
//
// Not the chip's: nothing beyond the block's atomicity (the firmware's docs/ALLOWLIST.md, row B40); the firmware writes
// ECHOB / ECHOS only between blocks (3.10.5).
//
// Reset (sys_reset): back to idle, no request held. Clock: clk_sys only; no new clock domain.

module paprium_synth_echo #(
	parameter [7:0] BUS_BGM = 8'd0,                // BUS RAM word of BGM pair 0 (160 words; a multiple of 4)
	parameter [7:0] BUS_SFX = 8'd160               // BUS RAM word of SFX pair 0 (80 words; a multiple of 4)
)(
	input             clk,
	input             reset,

	// ---- the block sequencer ----
	input             start,                       // one clock, only while busy = 0
	input       [1:0] phase,                       // with start: 0 P1, 1 P2, 2 P3, 3 P4
	input             ym,                          // with start: the block's path is YM-DAC (B2 blk_ym)
	output reg        done,                        // one clock: the phase is finished
	output            busy,

	// ---- B1 globals ----
	input       [5:0] g_flags,
	input      [15:0] g_echob_gain,                // ECHOB.GAIN (s16)
	input       [7:0] g_echob_delay,               // ECHOB.DELAY & 0xFF
	input       [7:0] g_echob_index,               // ECHOB.INDEX
	input      [15:0] g_echos_gain,                // ECHOS.GAIN (s16)
	input       [7:0] g_echos_delay,               // ECHOS.DELAY & 0xFF
	input       [7:0] g_echos_index,               // ECHOS.INDEX
	output reg        e_echob_idx_we,
	output      [7:0] e_echob_idx,
	output reg        e_echos_idx_we,
	output      [7:0] e_echos_idx,

	// ---- BUS RAM (request / grant) ----
	output reg        b_rreq,
	output      [7:0] b_raddr,
	input             b_rgnt,
	input      [31:0] b_rdata,
	output reg        b_wreq,
	output      [7:0] b_waddr,
	output     [31:0] b_wdata,
	input             b_wgnt,

	// ---- B10 port E: client 1 (ring reads), client 2 (ring writes); pairs ----
	output reg        rq_req,
	output     [21:0] rq_addr,
	input             rq_gnt,
	input             rq_done,
	input      [31:0] e_data,
	output reg        wq_req,
	output     [21:0] wq_addr,
	output     [31:0] wq_wdata,
	input             wq_gnt
);
	import paprium_synth_pkg::*;
	localparam [3:0] RA_HI = CR_BGMRING[21:18];     // = CR_SFXRING[21:18] = 4'h5; both rings end below 0x180000

	localparam [3:0] S_IDLE = 4'd0, S_ZERO = 4'd1, S_RRD = 4'd2, S_ML = 4'd3, S_MR = 4'd4, S_MW = 4'd5,
	                 S_PUT = 4'd6, S_BRD = 4'd7, S_BDAT = 4'd8, S_CWR = 4'd9;

	reg  [3:0]  st = S_IDLE;
	reg         sfx;                               // this phase works on the SFX bus / ring
	reg  [7:0]  ba;                                // BUS RAM word (read or write)
	reg  [15:0] ra;                                // CRAM pair address [17:2]; [21:18] = RA_HI (both rings)
	reg  [31:0] dat;                               // the pair in flight: ring read -> {R', L'}, bus read -> ring
	reg  signed [31:0] p;                          // the product (one multiplier: L, then R)
	reg  [7:0]  nidx;                              // the new INDEX (P2 / P4)

	assign busy        = (st != S_IDLE);
	assign b_raddr     = ba;
	assign b_waddr     = ba;
	assign b_wdata     = dat;
	assign rq_addr     = {RA_HI, ra, 2'b00};
	assign wq_addr     = {RA_HI, ra, 2'b00};
	assign wq_wdata    = dat;
	assign e_echob_idx = nidx;
	assign e_echos_idx = nidx;

	wire        sel_sfx = phase[1];
	wire [7:0]  idx     = sel_sfx ? g_echos_index : g_echob_index;
	wire [7:0]  dly     = sel_sfx ? g_echos_delay : g_echob_delay;
	// one 8-bit subtractor: P1 / P3 read (INDEX - DELAY) & 0xFF; P2 / P4 write INDEX - 0xFF = INDEX + 1, 0 past 0xFF
	wire [7:0]  blk     = idx - (dly | {8{phase[0]}});
	// ring block base: b x 160 (BGM) or b x 80 (SFX) = (b x 5) << 5 / << 4, plus the ring's CRAM offset
	wire [10:0] b5      = {3'd0, blk} + {1'b0, blk, 2'b00};
	// one 20-bit adder for the CRAM pair address [21:2]: in S_IDLE the ring block base (the ring's offset + b5 << 3 /
	// << 2 pairs), in every other state ra + 1 (the next pair)
	wire        ra_ld   = (st == S_IDLE);
	wire [15:0] ra_a    = ra_ld ? (sel_sfx ? CR_SFXRING[17:2] : CR_BGMRING[17:2]) : ra;
	wire [15:0] ra_b    = ra_ld ? (sel_sfx ? {3'd0, b5, 2'd0} : {2'd0, b5, 3'd0}) : 16'd1;
	wire [15:0] ra_n    = ra_a + ra_b;
	wire        prefill = ~ym & (sel_sfx ? (g_flags[FL_SFXON] & g_flags[FL_SFXECHO]) : g_flags[FL_BGMECHO]);
	wire [7:0]  b0      = sel_sfx ? BUS_SFX : BUS_BGM;
	wire [7:0]  blast   = sfx ? (BUS_SFX + 8'd79) : (BUS_BGM + 8'd159);   // the bus's last pair
	wire [7:0]  ba_n    = ba + ((st == S_CWR) ? 8'd4 : 8'd1);   // the next bus word
	wire        ba_hi   = (ba[7:2] == blast[7:2]);    // in the bus's last group of four (blast[1:0] = 3)

	// (gain x v) / 256 toward zero: the low 16 bits of (p + (p < 0 ? 255 : 0)) >> 8, which is p[23:8] plus the carry
	// out of p[7:0] + 255 (p < 0 and p[7:0] != 0): one 16-bit increment
	wire signed [15:0] gain = sfx ? g_echos_gain : g_echob_gain;
	wire signed [15:0] mx   = dat[15:0];             // L in S_ML, R in S_MR (S_ML swaps the halves)
	wire        [15:0] pr   = p[23:8] + {15'd0, p[31] & (|p[7:0])};

	always @(posedge clk) begin
		done           <= 1'b0;
		e_echob_idx_we <= 1'b0;
		e_echos_idx_we <= 1'b0;
		p              <= gain * mx;
		if (reset) begin
			st     <= S_IDLE;
			b_rreq <= 1'b0;
			b_wreq <= 1'b0;
			rq_req <= 1'b0;
			wq_req <= 1'b0;
		end
		else case (st)
			S_IDLE: if (start) begin
				sfx <= sel_sfx;
				ba  <= b0;
				ra  <= ra_n;
				dat <= 32'd0;
				if (!phase[0]) begin
					// P1 / P3: zero the bus, or prefill it from the ring
					if (prefill) begin st <= S_RRD; rq_req <= 1'b1; end
					else begin st <= S_ZERO; b_wreq <= 1'b1; end
				end
				else if (!sel_sfx || g_flags[FL_SFXON]) begin
					// P2 / P4: the index moves on, then the ring block it names gets the bus pairs 0, 4, ..
					nidx           <= blk;                // phase[0] = 1: INDEX + 1
					e_echob_idx_we <= ~sel_sfx;
					e_echos_idx_we <= sel_sfx;
					st             <= S_BRD;
					b_rreq         <= 1'b1;
				end
				else done <= 1'b1;                     // P4 with FLAGS.SFXON 0: nothing (the chip skips it)
			end

			S_ZERO: if (b_wgnt) begin
				if (ba_hi && ba[1:0] == 2'd3) begin b_wreq <= 1'b0; st <= S_IDLE; done <= 1'b1; end
				else ba <= ba_n;
			end

			S_RRD: begin
				if (rq_gnt) rq_req <= 1'b0;
				if (rq_done) begin dat <= e_data; st <= S_ML; end
			end

			S_ML: begin dat <= {dat[15:0], dat[31:16]}; st <= S_MR; end   // p := gain x L; R to the low half
			S_MR: begin dat[31:16] <= pr; st <= S_MW; end   // L' parked high; p := gain x R
			S_MW: begin dat <= {pr, dat[31:16]}; st <= S_PUT; b_wreq <= 1'b1; end   // {R', L'}

			S_PUT: if (b_wgnt) begin
				if (ba_hi && ba[1:0] == 2'd3) begin b_wreq <= 1'b0; st <= S_IDLE; done <= 1'b1; end
				else begin
					ba <= ba_n;
					if (ba[1:0] == 2'd3) begin         // four copies written: the next ring pair
						b_wreq <= 1'b0;
						ra     <= ra_n;
						rq_req <= 1'b1;
						st     <= S_RRD;
					end
				end
			end

			S_BRD: if (b_rgnt) begin b_rreq <= 1'b0; st <= S_BDAT; end
			S_BDAT: begin dat <= b_rdata; wq_req <= 1'b1; st <= S_CWR; end

			S_CWR: if (wq_gnt) begin
				wq_req <= 1'b0;
				if (ba_hi) begin st <= S_IDLE; done <= 1'b1; end
				else begin
					ba     <= ba_n;
					ra     <= ra_n;
					b_rreq <= 1'b1;
					st     <= S_BRD;
				end
			end

			default: st <= S_IDLE;
		endcase
	end

endmodule
