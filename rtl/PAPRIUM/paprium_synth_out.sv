// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (block B8; the synth's blocks are listed in paprium_synth.sv's header; here B1 =
// paprium_synth_if, B2 = paprium_synth_sched, B9 = paprium_synth_dtplay, B10 = paprium_synth_cram) - paprium_synth_out:
// the cart chip's output stage, the last part of a block (the firmware's docs/MCU_INTERFACE.md v1.3 3.8, 3.10.1
// YMFILT, 3.10.2 DTWIN). We reverse engineered the STM32F4's commands as close as possible, with hardware
// verification; the tables were worked out from our own study of how the cart behaves and checked on hardware.
//
// What it does, per SFX frame i = 0..79 (the SFX bus runs at 24 kHz, so each SFX frame serves BGM frames 2i and
// 2i + 1):
//   YM-DAC: the left BGM and SFX lanes are summed and clamped, passed through the YM path's two filter states A / B
//     (A for BGM frame 2i, B for 2i + 1) and looked up in the output curve; the results go to dac_buf_L[idx + 2i] and
//     dac_buf_L[idx + 2i + 1]. The R lanes are not read and dac_buf_R is not written. Here A / B go back to B1 in one
//     YMFILT write-back at the end of the block (blocks are atomic: the firmware's docs/ALLOWLIST.md, row B40).
//   DT (otherwise): each lane's BGM and SFX frames are mixed and looked up in the output curve, with no clamp (index
//     -49,152 .. +49,150), to dac_buf_L / R[idx + 2i + h]. A / B untouched.
// The curve is CRAM CURVE_WIN (3.8; CRAM = the Pocket's cellular RAM): index x at byte 0x198000 + 2x.
//   DTWIN = 1: x as computed, i.e. the chip's own flash window, as the MCU copied it.
//   DTWIN = 0: x clamped to the 16,384-entry table, -8,192 .. +8,191 (ALLOWLIST.md row B41, approved; our
//     synth preparation runs measured the game's largest DT index at 3,838). One clamp for both modes: in YM the chip's
//     states never leave -8,191 .. +8,191 from the power-on 0 (the clamp above; the cart stores them nowhere else), so
//     it changes nothing there; it only defines a YMFILT the MCU might write outside the chip's range (the table ends,
//     not CRAM outside the table).
// Outputs land at the chip's indexes: dac_buf_L / R entry idx + n at CRAM 0x170000 / 0x170F00 + 2 (idx + n), written
// as word pairs {entry idx + 2i + 1 [31:16], entry idx + 2i [15:0]} (idx is even: B2 gives HALF x fill + 160 x cnt).
// The chip writes L[2i], R[2i], L[2i + 1], R[2i + 1]; with atomic blocks only the final contents can be seen.
//
// Interfaces:
//   start (one clock, idle only) with idx / ym / dtwin / ymf_a / ymf_b sampled then; done (one clock) after the block's
//     last dac_buf write is granted (B10's idle then covers the controller drain, B2 waits for it); busy = not idle.
//   ymf_we (one clock, YM blocks only, the clock before done): A / B after the block -> B1 e_ymf_we / e_ymf_a /
//     e_ymf_b, so YMFILT already reads them in the clock done is seen.
//   The bus RAM read port: hold b_rreq / b_raddr until b_rgnt (sampled in the same clock); the word is on b_rdata in the
//     NEXT clock only (the state RAM's rule). Word = {R s16 [31:16], L s16 [15:0]}; BGM frame f (0..159) at word
//     BUS_BGM + f, SFX frame i (0..79) at word BUS_SFX + i. The block reads each word once, in frame order, and reads
//     the bus only (it is complete when start comes).
//   B10 port C client 2 (the curve): one read at a time, raised after the previous one's q_done; B10 port E client 3
//     (dac_buf pair writes): one at a time, raised after the previous one's q_gnt. The block's reads (CURVE_WIN) and
//     writes (DACBUF) never touch one word, so B10's raise-order rule has nothing to order here.
// Reset: back to idle at once, requests dropped (B10 finishes an operation already at the controller).
// Cost per block (estimated, controller times excluded): YM 80 x (3 bus reads, 2 curve reads, 1 pair write), DT 80 x
// (3, 4, 2): about 14 + 2 x (C read) clocks per YM frame pair, 18 + 4 x (C read) per DT one. No DSP, no RAM.
// Register trims, to save logic (every request / done / ymf_we on the same clock as before, every field the same
// whenever its consumer reads it):
//   T1: ymf_a_o / ymf_b_o are fa / fb (B1 takes them only under ymf_we, when fa / fb hold the block's final A / B).
//   T2: eq_wdata is pl, or pr in S_ER (B10 reads it only while eq_req is high; pl / pr do not move then).
//   T3: eq_addr is DAC_L, or DAC_R in S_ER, + 2 (idx + 2i) (B10 reads it only while eq_req is high).

module paprium_synth_out #(
	parameter [7:0] BUS_BGM = 8'd0,              // bus word of BGM frame 0
	parameter [7:0] BUS_SFX = 8'd160             // bus word of SFX frame 0
)(
	input             clk,
	input             reset,

	input             start,
	input      [10:0] idx,
	input             ym,
	input             dtwin,
	input      [15:0] ymf_a,
	input      [15:0] ymf_b,
	output            busy,
	output reg        done,

	output reg        ymf_we,
	output     [15:0] ymf_a_o,
	output     [15:0] ymf_b_o,

	output reg        b_rreq,
	output reg  [7:0] b_raddr,
	input             b_rgnt,
	input      [31:0] b_rdata,

	output reg        cq_req,
	output reg [21:0] cq_addr,
	input             cq_gnt,
	input             cq_done,
	input      [15:0] c_data,

	output reg        eq_req,
	output     [21:0] eq_addr,
	output     [31:0] eq_wdata,
	input             eq_gnt
);

	localparam [21:0] CURVE_CTR = 22'h198000;    // MCU_INTERFACE.md 3.8: curve index 0
	localparam [21:0] DAC_L     = 22'h170000;    // dac_buf_L entry 0
	localparam [21:0] DAC_R     = 22'h170F00;    // dac_buf_R entry 0

	localparam [3:0] S_IDLE = 4'd0, S_SFX = 4'd1, S_SFXD = 4'd2, S_BGM = 4'd3, S_BGMD = 4'd4, S_CREQ = 4'd5,
	                 S_CGNT = 4'd6, S_CDONE = 4'd7, S_EL = 4'd8, S_ER = 4'd9, S_FIN = 4'd10;

	reg   [3:0] st = S_IDLE;
	reg  [10:0] r_idx;
	reg         r_ym, r_win;
	reg  [15:0] fa, fb;                          // the YM filter states A / B
	reg   [6:0] it;                              // SFX frame i
	reg         h;                               // BGM frame 2i + h
	reg         side;                            // DT: 0 = the L lanes, 1 = the R lanes (YM: always 0)
	reg  [31:0] sfx, bgm;                        // the bus words of SFX frame i and BGM frame 2i + h
	reg  [31:0] pl, pr;                          // the L / R pairs being built: [15:0] frame 2i, [31:16] frame 2i + 1

	assign busy = (st != S_IDLE);
	assign eq_wdata = (st == S_ER) ? pr : pl;  // T2: the L pair, then (DT) the R pair
	assign ymf_a_o = fa;                       // T1: read by B1 only under ymf_we
	assign ymf_b_o = fb;

	// ---- the curve index of the current sample (all on unsigned vectors with explicit sign extension) ----
	// YM: x = the signed 16-bit sum BGM_L + SFX_L, clamped as the chip does; A or B := (state + x) / 2 toward zero
	wire [15:0] y_sum = bgm[15:0] + sfx[15:0];
	wire signed [15:0] y_s = y_sum;
	wire [15:0] y_x = (y_s < -16'sh1FFF) ? 16'hE002 :           // -0x1FFE
	                  (y_s >  16'sh1FFF) ? 16'h1FFE : y_sum;
	wire [15:0] y_st = h ? fb : fa;
	wire [16:0] y_t  = {y_st[15], y_st} + {y_x[15], y_x};
	wire [16:0] y_tr = y_t + {16'd0, y_t[16]};                  // + the sign bit, then an arithmetic shift by 1
	wire [15:0] y_n  = y_tr[16:1];                              // fits 16 bits: |state + x| <= 40,958
	// DT: lane / 2 toward zero + the SFX lane
	wire [15:0] d_b  = side ? bgm[31:16] : bgm[15:0];
	wire [15:0] d_s  = side ? sfx[31:16] : sfx[15:0];
	wire [16:0] d_br = {d_b[15], d_b} + {16'd0, d_b[15]};
	wire [16:0] d_h  = {d_br[16], d_br[16:1]};
	wire [16:0] d_i  = d_h + {d_s[15], d_s};                    // -49,152 .. +49,150
	// the index, the B41 clamp, the CRAM byte address
	wire [16:0] c_ix = r_ym ? {y_n[15], y_n} : d_i;
	wire signed [16:0] c_ixs = c_ix;
	wire [16:0] c_ic = r_win ? c_ix :
	                   (c_ixs < -17'sh2000) ? 17'h1E000 :        // -8,192
	                   (c_ixs >  17'sh1FFF) ? 17'h01FFF : c_ix;  // +8,191
	wire [21:0] c_addr = CURVE_CTR + {{4{c_ic[16]}}, c_ic, 1'b0};

	// the value this sample stores: YM curve >> 4, DT the curve word
	wire [15:0] c_val = r_ym ? {4'd0, c_data[15:4]} : c_data;
	// the pair's first entry, idx + 2i
	wire [10:0] e_pos = r_idx + {3'd0, it, 1'b0};
	assign eq_addr = ((st == S_ER) ? DAC_R : DAC_L) + {10'd0, e_pos, 1'b0};   // T3

	always @(posedge clk) begin
		done   <= 1'b0;
		ymf_we <= 1'b0;
		if (reset) begin
			st     <= S_IDLE;
			b_rreq <= 1'b0;
			cq_req <= 1'b0;
			eq_req <= 1'b0;
		end
		else case (st)
			S_IDLE: if (start) begin
				r_idx   <= idx;
				r_ym    <= ym;
				r_win   <= dtwin;
				fa      <= ymf_a;
				fb      <= ymf_b;
				it      <= 7'd0;
				h       <= 1'b0;
				side    <= 1'b0;
				b_rreq  <= 1'b1;
				b_raddr <= BUS_SFX;
				st      <= S_SFX;
			end
			S_SFX: if (b_rgnt) begin b_rreq <= 1'b0; st <= S_SFXD; end
			S_SFXD: begin
				sfx     <= b_rdata;
				b_rreq  <= 1'b1;
				b_raddr <= BUS_BGM + {it, 1'b0};
				st      <= S_BGM;
			end
			S_BGM: if (b_rgnt) begin b_rreq <= 1'b0; st <= S_BGMD; end
			S_BGMD: begin bgm <= b_rdata; st <= S_CREQ; end
			S_CREQ: begin
				cq_req  <= 1'b1;
				cq_addr <= c_addr;
				if (r_ym) begin
					if (h) fb <= y_n;
					else   fa <= y_n;
				end
				st <= S_CGNT;
			end
			S_CGNT: if (cq_gnt) begin cq_req <= 1'b0; st <= S_CDONE; end
			S_CDONE: if (cq_done) begin
				case ({side, h})
					2'b00: pl[15:0]  <= c_val;
					2'b01: pl[31:16] <= c_val;
					2'b10: pr[15:0]  <= c_val;
					default: pr[31:16] <= c_val;
				endcase
				if (!r_ym && !side) begin                // DT: the R lanes of the same BGM frame next
					side <= 1'b1;
					st   <= S_CREQ;
				end
				else begin
					side <= 1'b0;
					if (!h) begin                         // BGM frame 2i + 1 next
						h       <= 1'b1;
						b_rreq  <= 1'b1;
						b_raddr <= BUS_BGM + {it, 1'b1};
						st      <= S_BGM;
					end
					else begin                            // the L pair (YM: this sample completes it)
						h        <= 1'b0;
						eq_req   <= 1'b1;
						st       <= S_EL;
					end
				end
			end
			S_EL: if (eq_gnt) begin
				if (!r_ym) begin                          // DT: the R pair
					st       <= S_ER;
				end
				else begin
					eq_req <= 1'b0;
					st     <= S_ER;
				end
			end
			// S_ER: the frame pair is done (YM arrives here with nothing outstanding; DT waits for the R pair's grant)
			S_ER: if (r_ym || eq_gnt) begin
				eq_req <= 1'b0;
				if (it == 7'd79) begin
					ymf_we  <= r_ym;
					st      <= S_FIN;
				end
				else begin
					it      <= it + 7'd1;
					b_rreq  <= 1'b1;
					b_raddr <= BUS_SFX + {1'b0, it + 7'd1};
					st      <= S_SFX;
				end
			end
			// done one clock after ymf_we: once done is seen, YMFILT already reads A / B
			S_FIN: begin done <= 1'b1; st <= S_IDLE; end
			default: st <= S_IDLE;
		endcase
	end

endmodule
