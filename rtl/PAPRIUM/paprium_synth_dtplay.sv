// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (block B9) - paprium_synth_dtplay: the DT playback (DT = the cart's own DAC path, the game's
// DATENMEISTER sound mode, beside YM; the firmware's docs/MCU_INTERFACE.md v1.3 sections 3.8 DACBUF_L / R, 3.10.1 DTOUT
// and DIAG.UNDERRUN, 3.10.6; bare section numbers below are that document's). The synth's blocks B1-B10 are listed in
// paprium_synth.sv's header; here B1 = paprium_synth_if, B2 = paprium_synth_sched, B10 = paprium_synth_cram.
//
// What it does, as the cart does it (we reverse engineered the STM32F4's commands as close as possible, with hardware
// verification):
//   * In DT mode the cart's two DAC channels play the dac_buf rings, one entry per TIM8 strobe, round and round over
//     1,920 entries. The code each strobe converts is the entry the DMA index points at, its bits 11:0 (the DAC
//     ignores bits 15:12). The entry is read once per strobe at B2's index (dt_idx: the entry this strobe plays; the
//     index moves after it), so both channels play the same index, as the cart's two streams do (they never drift: no
//     L / R resync in any of our 179 test runs).
//   * The strobe is B2's own TIM8 (tim8; a design decision: the console clock, the chip's 100.1
//     ratio to TIM6) and the index is B2's DT DMA index (it holds while YM-DAC / no mode is on and resumes where it
//     held). Outside DT (MODE 0 / 2) the cart's DAC outputs are off, and the output is 0.
//   * A strobe converts the entry the DMA moves at that same strobe (entry k at strobe k): that is the reference our
//     tests compare against, and what this block does.
//     (On the part, the DAC is documented to load DOR from
//     DHR at a trigger and only then request the next DMA item, which would play every item
//     one trigger later (a web source, not checked against RM0090 here): a constant 21 us shift of the whole DT
//     stream; whether it happens is not known.)
//
// The read: a one-entry prefetch on port E client 0 of B10 (the first-ranked client: it waits only for the one E
// operation in flight; measured on the synth's first version: request -> data <= 82 clocks against the 1,119-clock
// sample). As soon as the
// index the next strobe plays (dt_idx) is not the buffered one, the block reads DACBUF_L[i] then DACBUF_R[i] (two
// single halves; the rings are 0xF00 bytes apart, so no pair) and holds them with their index. A strobe plays the
// buffered pair when its index matches; else it counts an underrun (DIAG.UNDERRUN) and plays its own entry the
// moment that entry arrives ("late", less than a sample), or loses it if the next strobe comes first (a strobe whose
// entry is buffered but comes while the stand-in still works on the last sample, 4 clocks, waits the same way: only an
// index jump - PHASE, TEST - can bring that within 4 clocks of a late entry). The first strobe after a DT start is
// such an underrun whenever it comes before the first pair is in (up to the two reads' latency; measured on the unit
// bench when this block was checked: always within 9 clocks of dt_run rising, sometimes up to 41): it plays the chip's
// code less than a sample late, and DIAG.UNDERRUN counts it (TEST telemetry, never 68000-visible).
// What a strobe plays: entry k is read right after the strobe (or the late take) of entry k-1, L then R, so a strobe
// plays what its entry held up to one sample before it. That is the chip's code whenever the entry's dac_buf write
// landed before that read. With blocks mixed in zero time at their TIM6 instant (as in our reference tests) it always
// is: the chip's blocks write only the half the DMA is not in, so never the entry the next strobe plays (margin >= 1
// entry; measured at 9 DMA positions in our tests, 1 at pos 1,919, the last entry of the upper half; the other
// positions follow from the half rule, inferred). Our blocks land after B2's hold-off
// (at most a TIMEOUT, 5 ms, after the instant) plus the block's own time to that entry's write,
// so the contract is: every entry's write lands before the take of the entry before it. In steady state the chip's
// nearest write at a decision is at least 860 entries (17.9 ms) ahead of the DMA (measured: no hazard writes in our
// reference replays), so a TIMEOUT + block + write time under about 17.9 ms keeps every code the chip's. NOT so right
// after a DT CONFIG (DT -> DT or YM -> DT) with the DMA in the upper half: the chip then mixes block 0 of half 0 at
// once, only 1,920 - pos entries ahead (down to 1; measured with our margin script when this block was checked), and
// until our block lands the DMA plays the old dac_buf content where the chip plays the new block. That span is B2 / B8
// / firmware latency, not this block's; this block's prefetch adds about one entry per channel and late block
// (estimated; a hold-off sweep on the bench measured 2-19 such prefetch codes among 13-265 stale codes). No row of the
// firmware's docs/ALLOWLIST.md covers it yet. The buffer is dropped whenever the DMA is off (dt_run = 0), and a read in
// flight then is discarded, so a DT restart never plays an entry read before the YM / MODE 0 period; and the firmware
// writes the DT CONFIG only after synth_begin (BUSY = 0, 3.10.5), so every block of an instant before the 88 has landed
// by then. Mode switches take effect at the firmware's CONFIG write, not at the 88's arrival (B2 dates the index at the
// arrival, so from the write on every strobe plays the chip's entry; before it the old mode's output goes on, the
// firmware's latency, at most a TIMEOUT). That latency is a difference from the chip's played stream as well, with no
// allow-list row yet.
//
// The analogue stand-in (the synth design's decision 5, "plain first"; DTOUT, the board layer, no chip field): per
// played sample and channel x = code - 2047 (s13); if DCK != 0 a one-pole DC blocker (the cart's coupling capacitor)
// with its state lp kept to 16 fraction bits: x := x - round(lp), then lp += (x_in * 2^16 - lp) >>> DCK (arithmetic
// shift, round = half up); y = (x * GAIN) >>> 8 (GAIN Q8.8 unsigned), negated if INVERT, saturated to s16. GAIN 0 is
// silence. lp holds while DCK = 0, outside DT and in the freeze; it is 0 after reset. DTOUT is sampled once per sample
// (when its codes are taken), so both channels of a sample use one value. One multiplier and one DC-blocker front half
// serve both channels (L, then R; trimmed to save logic: the codes and the states rotate through the one front half).
//
// Menu freeze (3.10.6; the firmware's docs/ALLOWLIST.md, row B7): B2's tim8 and index stop, the output is 0, and the
// held sample and lp resume in place when the menu closes (the prefetched entry stays: the DMA is still in its half).
// Reset (sys_reset): output 0, lp 0, nothing buffered, no request (B10 swallows the done of a read granted before).
// Clock: clk_sys only; no new clock domain.

module paprium_synth_dtplay (
	input                    clk,
	input                    reset,
	input                    freeze,               // Pocket menu open and CTRL.MENU_MUTE_EN (this clock)

	// ---- from B2 ----
	input                    tim8,                 // the 48 kHz strobe (one clock; B2 holds it in the freeze)
	input                    dt_run,               // the DT DMA runs (MODE 1)
	input             [10:0] dt_idx,               // the entry the next strobe plays (in a tim8 clock: this one)

	// ---- from B1 ----
	input             [20:0] g_dtout,              // DTOUT: [15:0] GAIN Q8.8, [16] INVERT, [20:17] DCK

	// ---- B10 port E client 0 (single-half reads) ----
	output reg               q_req,
	output reg        [21:0] q_addr,               // CRAM byte address (3.8 DACBUF_L / DACBUF_R + 2 x index)
	input                    q_gnt,
	input                    q_done,
	input             [31:0] q_data,               // [15:0] for a single half

	// ---- to the core's audio sum (paprium_cart sfx_l / sfx_r) and B1 ----
	output signed     [15:0] dt_l,
	output signed     [15:0] dt_r,
	output reg               inc_underrun,         // one clock: a strobe whose entry was not buffered (DIAG.UNDERRUN)

	// ---- observation (benches only; nothing in the shell reads them) ----
	output reg               o_play,               // one clock: a sample's codes were taken (on time or late)
	output reg        [10:0] o_play_idx,
	output reg        [11:0] o_code_l,
	output reg        [11:0] o_code_r,
	output reg               o_late,               // the sample taken now belongs to an earlier strobe
	output reg               o_lost                // one clock: a late sample was given up (the next strobe or a DMA stop came first)
);
	import paprium_synth_pkg::*;

	// ================================================================ the prefetch
	localparam [2:0] R_IDLE = 3'd0, R_LREQ = 3'd1, R_LWAIT = 3'd2, R_RREQ = 3'd3, R_RWAIT = 3'd4;
	reg   [2:0] r_st;
	reg  [10:0] r_tag;                              // the index being read
	reg         r_kill;                             // the DMA went off while it was out: discard it
	reg  [11:0] r_l;                                // the DAC takes bits 11:0 only (DHR12R)
	reg         b_ok;                               // the buffer holds the pair of b_tag
	reg  [10:0] b_tag;
	reg  [11:0] b_l, b_r;
	reg         pend;                               // the last strobe's entry is still to come (late)
	reg  [10:0] pend_idx;

	wire [10:0] want  = pend ? pend_idx : dt_idx;
	wire        need  = dt_run & ~(b_ok & (b_tag == want));
	wire [21:0] a_l   = CR_DACBUF_L + {10'd0, want, 1'b0};
	wire [21:0] a_r   = CR_DACBUF_R + {10'd0, r_tag, 1'b0};

	reg   [3:0] s_v;                                // the stand-in's stages in use (below)
	wire        busy    = |s_v;                     // a sample is still in the stand-in: the next one waits (late)
	wire        strobe  = tim8 & dt_run;
	wire        hit     = b_ok & (b_tag == dt_idx) & ~busy;
	wire        late_ok = dt_run & pend & b_ok & (b_tag == pend_idx) & ~busy;   // a DMA stop gives it up (o_lost)
	wire        take    = (strobe & hit) | (~strobe & late_ok);   // the codes of a sample are taken this clock
	wire [10:0] take_idx = strobe ? dt_idx : pend_idx;

	always @(posedge clk) begin
		inc_underrun <= 1'b0;
		o_lost       <= 1'b0;
		if (reset) begin
			r_st <= R_IDLE; r_kill <= 1'b0; q_req <= 1'b0; b_ok <= 1'b0; pend <= 1'b0;
		end
		else begin
			// ---- the read FSM (one single-half read at a time; a granted read always finishes) ----
			case (r_st)
				R_IDLE: if (need) begin
					q_req  <= 1'b1;
					q_addr <= a_l;
					r_tag  <= want;
					r_kill <= 1'b0;
					r_st   <= R_LREQ;
				end
				R_LREQ: if (q_gnt) begin q_req <= 1'b0; r_st <= R_LWAIT; end
				R_LWAIT: if (q_done) begin
					r_l <= q_data[11:0];
					if (r_kill | ~dt_run) r_st <= R_IDLE;
					else begin q_req <= 1'b1; q_addr <= a_r; r_st <= R_RREQ; end
				end
				R_RREQ: if (q_gnt) begin q_req <= 1'b0; r_st <= R_RWAIT; end
				R_RWAIT: if (q_done) begin
					if (~r_kill & dt_run) begin b_l <= r_l; b_r <= q_data[11:0]; b_tag <= r_tag; b_ok <= 1'b1; end
					r_st <= R_IDLE;
				end
				default: r_st <= R_IDLE;
			endcase
			if (!dt_run) begin
				b_ok   <= 1'b0;
				pend   <= 1'b0;
				o_lost <= pend;                               // a late entry that never came before the DMA stopped
				if (r_st != R_IDLE) r_kill <= 1'b1;
			end
			// ---- the strobe ----
			else if (strobe) begin
				if (hit) begin
					pend   <= 1'b0;
					o_lost <= pend;                               // an older late entry (only after an index jump)
				end
				else begin
					inc_underrun <= 1'b1;
					o_lost       <= pend;                     // an older late entry never came
					pend         <= 1'b1;
					pend_idx     <= dt_idx;
				end
			end
			else if (late_ok) pend <= 1'b0;
		end
	end

	// ================================================================ the analogue stand-in (DTOUT)
	// stage 0 (take): codes latched; stage 1: L through the DC blocker and the multiplier; stage 2: R the same, L's
	// product shifted / negated / saturated; stage 3: R's, then both outputs change together.
	reg  [20:0] dto;                                // DTOUT as of the take: both channels of a sample use one value
	wire [15:0] gain = dto[15:0];
	wire        inv  = dto[16];
	wire  [3:0] dck  = dto[20:17];

	// s_v (declared above): [0] codes in, [1] L in the multiplier, [2] R, [3] out
	// One front half serves both channels: it works on c_a / lp_a, L at s_v[0] and R at s_v[1]. At s_v[0] c_a takes R's
	// code; at each step lp_a takes the other state and lp_b the new one, so between samples lp_a = L and lp_b = R.
	reg  [11:0] c_a, c_b;                           // c_a: the code the front half works on (L at s_v[0], R at s_v[1])
	reg signed [27:0] lp_a, lp_b;                   // the DC blocker states, Q11.16 + sign (between samples: lp_a L, lp_b R)
	reg signed [12:0] xm;                           // the multiplier's input (trimmed: |x - round(lp)| <= 4,095, 13 bits)
	reg signed [28:0] pr;                           // the product (trimmed: |xm * GAIN| < 2^28, 29 bits)
	reg signed [15:0] y_l, y_r, y_ln;

	// one channel's front half: x = code - 2047, the DC blocker, its new state
	// Trimmed to save logic (the state 30 -> 28 bits, exact): with X = x_in * 2^16 in [-2047 * 2^16, 2^27], every step
	// lp' = lp + floor((X - lp) / 2^k), k = 1..15, lands between lp and X (never past X), and below X by at least half the
	// gap when X > lp; from lp = 0 (reset) lp therefore stays in [-2047 * 2^16, 2^27 - 1] = 28 bits signed (bits 29:28
	// of the 30-bit state are always copies of bit 27). X - lp needs 29 bits, (X - lp) >>> k (k >= 1) and the new state
	// fit 28, round(lp) is taken on 29 bits; so every value below equals the 30-bit one.
	function automatic signed [12:0] fx(input [11:0] code, input signed [27:0] lp, input [3:0] k);
		reg signed [12:0] x;                        // trimmed: x and the result in 13 bits (|x - round(lp)| <= 4,095)
		reg signed [28:0] lr;
		begin
			x  = $signed({1'b0, code}) - 13'sh07FF;
			lr = ($signed({lp[27], lp}) + 29'sh0000_8000) >>> 16;   // round(lp), half up (29 bits: lp + 2^15 can pass 2^27)
			fx = (k == 4'd0) ? x : (x - lr[12:0]);
		end
	endfunction
	function automatic signed [27:0] flp(input [11:0] code, input signed [27:0] lp, input [3:0] k);
		reg signed [13:0] x;
		reg signed [28:0] l, d, n;
		begin
			x   = $signed({2'b00, code}) - 14'sh07FF;
			l   = $signed({lp[27], lp});
			d   = ($signed({{15{x[13]}}, x}) <<< 16) - l;   // 29 bits: |X - lp| < 2^28
			n   = (k == 4'd0) ? l : (l + (d >>> k));
			flp = n[27:0];                              // the new state fits 28 bits (above)
		end
	endfunction
	// the back half: >>> 8, negate if INVERT, saturate to s16
	function automatic signed [15:0] fy(input signed [28:0] p, input ng);
		reg signed [21:0] q;
		begin
			q = {p[28], p[28:8]};
			if (ng) q = -q;
			fy = (q > 22'sh00_7FFF) ? 16'sh7FFF : (q < 22'sh3F_8000) ? 16'sh8000 : q[15:0];
		end
	endfunction

	always @(posedge clk) begin
		o_play <= 1'b0;
		if (reset) begin
			s_v <= 4'd0; lp_a <= 28'sd0; lp_b <= 28'sd0; y_l <= 16'sd0; y_r <= 16'sd0;
		end
		else begin
			s_v <= {s_v[2:0], take};
			if (take) begin
				c_a <= b_l; c_b <= b_r; dto <= g_dtout;
				o_play <= 1'b1; o_play_idx <= take_idx; o_code_l <= b_l; o_code_r <= b_r;
				o_late <= ~strobe;
			end
			if (s_v[0]) c_a <= c_b;
			if (s_v[0] | s_v[1]) begin xm <= fx(c_a, lp_a, dck); lp_a <= lp_b; lp_b <= flp(c_a, lp_a, dck); end
			if (s_v[1] | s_v[2]) pr <= xm * $signed({1'b0, gain});
			if (s_v[2]) y_ln <= fy(pr, inv);
			if (s_v[3]) begin y_l <= y_ln; y_r <= fy(pr, inv); end
			if (!dt_run) begin y_l <= 16'sd0; y_r <= 16'sd0; end
		end
	end

	assign dt_l = (dt_run & ~freeze) ? y_l : 16'sd0;
	assign dt_r = (dt_run & ~freeze) ? y_r : 16'sd0;

endmodule
