// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (block B3; the synth's blocks are listed in paprium_synth.sv's header) - paprium_synth_env:
// the cart chip's wave envelope, once per block, for the 16 wave voices (the chip's voices 10-25 = VOICE[0..15], the
// firmware's docs/MCU_INTERFACE.md v1.3 3.10.3).
//
// It is the wave half of the cart's envelope pass, which runs right before every block is mixed (we reverse engineered
// the STM32F4's commands as close as possible, with hardware verification):
//
//   * the stopped-mode decay, while FLAGS.PLAYING = 0: each voice's level is stepped down every block while it is not
//     0. The same pass also decays the cart's voices 0-9 and, while playing, moves the FM meters of voices 0-5: those
//     are the firmware's (MCU_INTERFACE.md 3.10.5, lazily by BLKCNT), not built here.
//   * the envelope, only with FLAGS.SEQON and FLAGS.PLAYING: per voice, on its state (ENV_STATE 0-7; a value above 7
//     does nothing), the attack, the hold, the decay to the sustain level, the sustain, the second decay, the release
//     and a fast fade, each on the voice's own rate fields (window words 9 and 10, u8 each).
//
// Every store is the chip's own: the same field, only when the chip stores it (the state RAM's byte lanes): ENV_LEVEL
// = lanes 1:0 and ENV_CNT = lanes 3:2 of window word 7, ENV_STATE = lane 0 of word 8 (the cart's store of the state
// also writes its high byte, always 0: the window has no such byte). Nothing else in a window is read or written
// except the read-only rate words 9 / 10. ENV_LEVEL in the state RAM is what the gain chain (B4) reads next and what the
// firmware's Boom Box feed reads back through B1 (only between synth_begin and synth_end, 3.10.5).
//
// Engine side: `start` (one clock) runs the envelope of one block with the FLAGS bits of that clock (blocks are atomic:
// the firmware never writes FLAGS or a window while a block runs, rule 6.3.8; the start latches them anyway); `done` is
// high for the one clock after the 16th voice's last store is granted, and busy = 1 from the clock after start up to
// that clock (busy is 0 again while done is 1). A start while busy is ignored (the scheduler starts a block only while
// RUN = 0). With PLAYING = 1 and SEQON = 0 the chip leaves the wave voices alone: done comes in the next clock.
//
// State RAM side: B1's synth port (paprium_synth_if e_*). One access at a time, held until granted: a read granted in
// clock t has its data on rdata in clock t+1 only; a write is done in the clock it is granted. Per voice (ADSR): read
// word 8 (the state), word 7 (level, cnt) and the rate word the state needs (9 = AR | HOLD | DR | SL for states 1-3,
// else 10 = SUS | D2R | RR), then at most two writes (word 7 with the stored lanes, word 8 lane 0): 4-6 clocks a voice,
// so at most 16 x 6 + 1 = 97 clocks from start to done without stalls. Decay: read word 7, write it if level != 0:
// 2-3 clocks a voice. A read of a window word while a block runs gives its value before or after this
// block's envelope, never a half-made one (one store per word).
//
// Reset (sys_reset): idle, no request. Clock: clk_sys only.

module paprium_synth_env (
	input             clk,
	input             reset,

	input             start,                       // one clock: the envelope of one block (B2's blk_start)
	input             seqon,                       // FLAGS[0] (SEQON)
	input             playing,                     // FLAGS[1] (PLAYING)
	output            busy,
	output reg        done,                        // one clock: the 16 voices are finished

	// the state RAM (paprium_synth_if's synth port)
	output            rreq,
	output     [7:0]  raddr,
	input             rgnt,
	input      [31:0] rdata,
	output            wreq,
	output     [7:0]  waddr,
	output     [3:0]  wbe,
	output     [31:0] wdata,
	input             wgnt
);
	import paprium_synth_pkg::*;

	localparam [2:0] S_IDLE = 3'd0,
	                 S_R8   = 3'd1,                // read word 8 (ENV_STATE)
	                 S_R7   = 3'd2,                // read word 7 (ENV_LEVEL, ENV_CNT)
	                 S_RR   = 3'd3,                // read the rate word (9 or 10)
	                 S_CMP  = 3'd4,                // the rate word (ADSR) or word 7 (decay) is on rdata: compute
	                 S_W7   = 3'd5,                // write word 7 (the lanes the chip stores)
	                 S_W8   = 3'd6;                // write word 8 lane 0 (ENV_STATE)

	reg   [2:0] fsm;
	reg         adsr;                              // this block: 1 = the ADSR, 0 = the stopped-mode decay
	reg   [3:0] v;                                 // the voice
	reg         cap8, cap7;                        // rdata holds word 8 / word 7 in this clock
	reg   [2:0] st;                                // the voice's state, 0-7 ...
	reg         st_big;                            // ... or above 7 (the chip's switch does nothing)
	reg  [15:0] lev;                               // ENV_LEVEL (s16)
	reg  [15:0] cnt;                               // ENV_CNT (u16)
	reg   [1:0] st_lanes;                          // {cnt stored, level stored}
	reg         st_store;                          // ENV_STATE stored

	assign busy  = (fsm != S_IDLE);
	assign rreq  = (fsm == S_R8) | (fsm == S_R7) | (fsm == S_RR);
	assign raddr = (fsm == S_R8) ? vaddr(v, VW_STATE)
	             : (fsm == S_R7) ? vaddr(v, VW_ENV)
	             : vaddr(v, (st == 3'd1 || st == 3'd2 || st == 3'd3) ? VW_RATES1 : VW_RATES2);
	assign wreq  = (fsm == S_W7) | (fsm == S_W8);
	assign waddr = (fsm == S_W7) ? vaddr(v, VW_ENV) : vaddr(v, VW_STATE);
	assign wbe   = (fsm == S_W7) ? {st_lanes[1], st_lanes[1], st_lanes[0], st_lanes[0]} : 4'b0001;
	// trimmed to save logic: the word-8 store writes lane 0 only (wbe 0001), so lanes 3:1 carry word 7's bytes in both
	// stores
	assign wdata = {cnt, lev[15:8], (fsm == S_W7) ? lev[7:0] : {5'd0, st}};

	// ---------------------------------------------------------------- the chip's arithmetic
	// In S_CMP: ADSR: lev / cnt / st are the voice's, rdata the rate word; decay: rdata is word 7.
	// Rate word bytes: 9 = {SL, DR, HOLD, AR}, 10 = {COMPAND, RR, D2R, SUS}.
	wire  [7:0] b0 = rdata[7:0], b1 = rdata[15:8], b2 = rdata[23:16], b3 = rdata[31:24];
	wire [15:0] dlev = rdata[15:0];                // decay: the level read
	// one 17-bit adder: level + the operand of the state (the chip's 16-bit result is sum[15:0]; state 7 uses sum[16:1])
	// trimmed to save logic: a subtraction is the adder's own: level + ~{0, byte} + 1 (carry-in), so no separate
	// negations; the constants -8 / -1 (decay) and -63 / -64 (state 7) are ~8 / ~1 / ~63 / ~64 + 1
	reg   [7:0] obyte;
	reg         osub;
	wire [16:0] opb  = {{9{osub}}, {8{osub}} ^ obyte};
	wire [15:0] alev = adsr ? lev : dlev;
	wire [16:0] sum  = {alev[15], alev} + opb + {16'd0, osub};
	wire [15:0] s16  = sum[15:0];
	wire [15:0] half = sum[16:1];                  // state 7: (level + sign - 0x40) >> 1 = level / 2 - 0x20 (toward zero)
	// x 6 of the rate the state compares with: HOLD (2), SL (3), SUS (4)
	wire  [7:0] mrate = (st == 3'd2) ? b1 : (st == 3'd3) ? b3 : b0;
	wire [10:0] m6   = {1'b0, mrate, 2'b00} + {2'b00, mrate, 1'b0};
	wire [15:0] cnt1 = cnt + 16'd1;
	wire        cnt_ge  = (cnt1[15:11] != 5'd0) | (cnt1[10:0] >= m6);                // cnt >= rate x 6 (unsigned)
	wire        s_le_m6 = s16[15] | ((s16[14:11] == 4'd0) & (s16[10:0] <= m6));      // s16 <= SL x 6 (signed)
	wire        s_le_0  = s16[15] | (s16 == 16'd0);                                    // s16 <= 0
	wire        s_le_5fe = s16[15] | (s16 <= 16'h05FE);                                // s16 <= 0x5FE
	wire        h_le_0  = half[15] | (half == 16'd0);                                  // t <= 0

	always @(*) begin
		obyte = 8'd0; osub = 1'b0;
		if (!adsr) begin
			osub = 1'b1; obyte = ($signed(dlev) > 16'sd7) ? 8'd8 : 8'd1;          // - 8 / - 1
		end
		else case (st)
			3'd1:    obyte = b0;                                              // + AR
			3'd3:    begin osub = 1'b1; obyte = b2; end                       // - DR
			3'd5:    begin osub = 1'b1; obyte = b1; end                       // - D2R
			3'd6:    begin osub = 1'b1; obyte = b2; end                       // - RR
			3'd7:    begin osub = 1'b1; obyte = lev[15] ? 8'd63 : 8'd64; end  // + sign - 0x40
			default: ;
		endcase
	end

	// the new fields and which of them the chip stores
	reg  [15:0] n_lev, n_cnt;
	reg   [2:0] n_st;
	reg   [1:0] n_lanes;                           // {cnt, level}
	reg         n_store;
	// trimmed to save logic: which fields the chip stores (n_lanes / n_store) is decided as before; the new VALUES are
	// chosen only where they are stored. A field whose lanes are off is never written, and lev / cnt / st are reloaded
	// from the state RAM before the next voice reads them, so its value is free there (no "keep the old value" input).
	always @(*) begin
		n_lanes = 2'b00; n_store = 1'b0;
		if (!adsr)
			n_lanes = {1'b0, (dlev != 16'd0)};
		else if (!st_big) case (st)
			3'd0: n_lanes = 2'b01;
			3'd1: begin
				if (b0 == 8'd0) n_lanes = 2'b01;
				else if (b0 != 8'hFF && s_le_5fe) n_lanes = 2'b01;
				else begin n_lanes = 2'b11; n_store = 1'b1; end
			end
			3'd2, 3'd4: begin n_lanes = 2'b10; n_store = cnt_ge; end
			3'd3: begin
				n_lanes = 2'b01;
				if (s_le_m6) begin n_lanes = 2'b11; n_store = 1'b1; end
			end
			3'd5, 3'd6: begin
				n_lanes = 2'b01;
				if (s_le_0) begin n_lanes = 2'b11; n_store = 1'b1; end
			end
			default: begin n_lanes = 2'b01; n_store = h_le_0; end                            // state 7
		endcase
	end
	// the values (used only where stored): level 0 (state 0, 5 / 6 at the end, 7 at the end), 0x5FF (state 1 at AR 0,
	// AR 0xFF or the top), SL x 6 (state 3 at the end), level / 2 - 0x20 (state 7), else s16 (decay, attack, 3 / 5 / 6);
	// count +1 in 2 / 4, else 0 (it is stored only as 0 there); state +1 from 1-4, else 0
	wire l_zero = adsr & ((st == 3'd0) | (((st == 3'd5) | (st == 3'd6)) & s_le_0) | ((st == 3'd7) & h_le_0));
	wire l_max  = adsr & (st == 3'd1) & ~((b0 != 8'd0) & (b0 != 8'hFF) & s_le_5fe);
	wire l_sl   = adsr & (st == 3'd3) & s_le_m6;
	wire l_half = adsr & (st == 3'd7);
	always @(*) begin
		n_lev = l_zero ? 16'd0 : l_max ? 16'h05FF : l_sl ? {5'd0, m6} : l_half ? half : s16;
		n_cnt = ((st == 3'd2) | (st == 3'd4)) ? cnt1 : 16'd0;
		n_st  = (st[2] & (st[1] | st[0])) ? 3'd0 : st + 3'd1;
	end

	// ---------------------------------------------------------------- the voice sequence
	always @(posedge clk) begin
		done <= 1'b0;
		cap8 <= 1'b0;
		cap7 <= 1'b0;
		if (cap8) begin st <= rdata[2:0]; st_big <= (rdata[7:3] != 5'd0); end
		if (cap7) begin lev <= rdata[15:0]; cnt <= rdata[31:16]; end

		if (reset) begin
			fsm <= S_IDLE;
			v   <= 4'd0;
		end
		else case (fsm)
			S_IDLE: if (start) begin
				v    <= 4'd0;
				adsr <= playing;
				if (!playing)     fsm <= S_R7;         // the stopped-mode decay
				else if (seqon)   fsm <= S_R8;         // the ADSR
				else              done <= 1'b1;        // playing, sequencer off: nothing to do
			end
			S_R8: if (rgnt) begin cap8 <= 1'b1; fsm <= S_R7; end
			S_R7: if (rgnt) begin cap7 <= adsr; fsm <= adsr ? S_RR : S_CMP; end
			S_RR: if (rgnt) fsm <= S_CMP;
			S_CMP: begin
				lev <= n_lev; cnt <= n_cnt; st <= n_st;          // trimmed: in the decay cnt / st are not stored (free)
				st_lanes <= n_lanes;
				st_store <= n_store;
				if (n_lanes != 2'b00) fsm <= S_W7;
				else if (n_store)     fsm <= S_W8;
				else                  fsm <= nxt(v);
				if (n_lanes == 2'b00 && !n_store) v <= v + 4'd1;
				if (n_lanes == 2'b00 && !n_store && v == 4'd15) done <= 1'b1;
			end
			S_W7: if (wgnt) begin
				if (st_store) fsm <= S_W8;
				else begin fsm <= nxt(v); v <= v + 4'd1; if (v == 4'd15) done <= 1'b1; end
			end
			S_W8: if (wgnt) begin fsm <= nxt(v); v <= v + 4'd1; if (v == 4'd15) done <= 1'b1; end
			default: fsm <= S_IDLE;
		endcase
	end

	// after voice x: the next voice's first read, or idle after the 16th
	function automatic [2:0] nxt(input [3:0] x);
		nxt = (x == 4'd15) ? S_IDLE : (adsr ? S_R8 : S_R7);
	endfunction

endmodule
