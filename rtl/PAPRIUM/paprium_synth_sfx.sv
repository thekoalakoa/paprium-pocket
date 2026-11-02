// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (block B6; the synth's blocks are listed in paprium_synth.sv's header, here B1 =
// paprium_synth_if, B7 = paprium_synth_echo, B8 = paprium_synth_out, B10 = paprium_synth_cram) - paprium_synth_sfx:
// the cart chip's SFX channels, one block at a time (the firmware's docs/MCU_INTERFACE.md v1.3 3.10.4, the SFX
// windows). It does what the cart's chip does (we reverse engineered the STM32F4's commands as close as possible, with
// hardware verification; the tables were worked out from our own study of how the cart behaves and checked on
// hardware):
//   * the block's channel loop: channels 0..7 in order; a channel with ID 0 is skipped; one with DELAY != 0 only
//     counts it down (DELAY - 1); one with DELAY 0 is mixed, 80 samples, with the SFX masters (SMASTER.L / R and
//     SMCFG);
//   * a mixed channel:
//     - LEN <= POS (u32): nothing is mixed, then the end rule below;
//     - up to 80 samples (fewer at the sound's end) come from 16-bit words read at PTR, PTR += 2 per word; FORMAT 1 =
//       8-bit samples, else 4-bit, each through its sample-expansion table (sfx8 / sfx4); RATE 1..5 sets how many times
//       each byte / nibble is held. A RATE outside 1..5 decodes nothing (the cart then mixes stale samples; here 0: see
//       the domain note);
//     - the channel's gains GAIN_L / GAIN_R with the masters; mono (one gain for both sides) when the two gains are
//       equal or on the YM path (the cart's other mono switch is only ever 0: not built);
//     - each sample through the channel's filter (FILT & 7 = 1-5: a smoothing filter of five strengths, else none),
//       then its gain, added to the bus (16-bit wrap, no clamp);
//     - Y := the filter's state, POS moves on; at the end LOOP != 0 starts the sound again (POS := 0, PTR := BASE),
//       else ID := 0.
//     The cart's re-check of the sound's start serial always passes with atomic blocks (the firmware's
//     docs/ALLOWLIST.md, row B40).
// Not here (other blocks): the SFX bus zeroing / echo prefill and the SFX ring write (B7), the output stage (B8).
//
// Domain (measured with our SFX-table script): all 127 records of the cart's SFX table give a RATE
// in 1..5, and the cart's SFX start, RATE's only writer, adds at most 1 and caps it at 5, so a RATE outside 1..5 never
// reaches the mixer with ID != 0; such a RATE here mixes x = 0 (= the chip with a zero scratch).
//
// Ports. A block's caller (the block sequencer of the integration) pulses `start` after the SFX bus is zeroed /
// prefilled; `done` pulses once every state-RAM and bus write of the block has been granted. Nothing is done when
// `sfx_on` (FLAGS.SFXON) is 0: then the chip runs no channel work at all (delays do not
// count).
//   * the state RAM through B1's engine port (paprium_synth_if): hold e_rreq / e_raddr until e_rgnt, the word on
//     e_rdata in the next clock; hold e_wreq / e_waddr / e_wbe / e_wdata until e_wgnt;
//   * the SFX bank through B10 port C client 1 (paprium_synth_cram): hold cq_req / cq_addr (a CRAM byte address =
//     PTR) until cq_gnt, the word on c_data in the cq_done clock; one read at a time, prefetched one word ahead; the
//     bank is never written by the synth, so no read order matters (B10's contract);
//   * the SFX bus = 80 pairs {R, L} s16 (pair i = sample i, L and R) at BUS RAM
//     words BUS_SFX + i of the shared BUS RAM (the integration's; word = {R [31:16], L [15:0]}, the layout B7 / B8
//     use), on a
//     port shaped as B1's: hold b_rreq / b_raddr until b_rgnt, the word on b_rdata in the next clock; hold
//     b_wreq / b_waddr / b_wdata until b_wgnt. A pair is read only after the last write of it is granted.
// One shared 19 x 18 signed multiplier (the masters, the channel gains, the /3 and /5 of the filters as
// v x 0xAAAB >> 17 and v x 0xCCCD >> 18, exact for every v the filters meet: checked by our reciprocal script, and
// the outputs), registered (a DSP block; the standalone map counts it). Clock: clk_sys only. Reset (sys_reset): back to
// idle, every request dropped (B10 swallows the done of a CRAM read granted before).
// Area trims, to save logic (every output equal on every clock it is read): T1 the sample tables live in port B of the
// shell's TABLES ROM (paprium_synth_trom) instead of a ROM in logic; T2 e_wdata / b_wdata / cq_addr are selects of
// the fields they carry, not registers; T3 one adder and one comparator, time-shared, make the three POS / LEN tests.

module paprium_synth_sfx #(
	parameter [7:0] BUS_SFX = 8'd160            // BUS RAM word of SFX pair 0 (80 words; B7 / B8 use the same base)
)(
	input             clk,
	input             reset,

	input             start,
	output reg        done,
	output            busy,
	input             sfx_on,                      // FLAGS.SFXON
	input             ym,                          // the YM-DAC path (B2's s_ym)
	input      [15:0] g_sm_l,                      // SMASTER.L
	input      [15:0] g_sm_r,                      // SMASTER.R
	input      [15:0] g_sfxmaster,                 // SMCFG.SFXMASTER

	// the state RAM, synth side (B1)
	output reg        e_rreq,
	output reg  [7:0] e_raddr,
	input             e_rgnt,
	input      [31:0] e_rdata,
	output reg        e_wreq,
	output reg  [7:0] e_waddr,
	output reg  [3:0] e_wbe,
	output     [31:0] e_wdata,
	input             e_wgnt,

	// CRAM port C, client 1 (B10)
	output reg        cq_req,
	output     [21:0] cq_addr,
	input             cq_gnt,
	input             cq_done,
	input      [15:0] c_data,

	// the SFX bus (BUS RAM)
	output reg        b_rreq,
	output reg  [7:0] b_raddr,
	input             b_rgnt,
	input      [31:0] b_rdata,
	output reg        b_wreq,
	output reg  [7:0] b_waddr,
	output     [31:0] b_wdata,
	input             b_wgnt,

	// the sample-expansion tables: port B of the shell's TABLES ROM (paprium_synth_trom), the entry two clocks later
	output      [8:0] rom_sa,
	input signed [10:0] rom_q
);
	import paprium_synth_pkg::*;

	// ---------------------------------------------------------------- the sample-expansion tables (the TABLES ROM)
	// 0..255 = sfx8, 256..271 = sfx4: the cart's sample-expansion tables, in port B of the shell's TABLES
	// ROM (an M10K with its address and output registered: rom_q is the entry of rom_sa two clocks later). rom_a is the
	// byte / nibble of the word in use; the address goes out in the clock before S_ROM (the last S_X clock, with the
	// new word's part 0 when S_X takes one), so rom_q holds that entry in S_FILT, the one clock that reads it, as the
	// one-clock ROM in logic did (rom_sa: after the decode's registers below).
	reg  [8:0] rom_a;

	// ---------------------------------------------------------------- the multiplier (registered)
	reg signed [18:0] ma;
	reg signed [17:0] mb;
	reg signed [36:0] mp;
	always @(posedge clk) mp <= ma * mb;

	// the clamp of a u16 x u16 product (>> 8, at most 0xFFFF)
	function automatic [15:0] clamp16(input signed [36:0] p);
		clamp16 = (p[31:24] != 8'd0) ? 16'hFFFF : p[23:8];
	endfunction
	// (p / 256) toward zero, truncated to 16 bits
	function automatic [15:0] div256(input signed [36:0] p);
		reg signed [36:0] t;
		begin
			t = p + (p[36] ? 37'sd255 : 37'sd0);
			div256 = t[23:8];
		end
	endfunction

	// ---------------------------------------------------------------- states
	localparam [4:0]
		S_IDLE  = 5'd0,  S_GM1  = 5'd1,  S_GM2  = 5'd2,  S_GM3  = 5'd3,
		S_CH    = 5'd4,  S_RW   = 5'd5,  S_RD   = 5'd6,  S_DLYW = 5'd7,
		S_PREP  = 5'd8,  S_GL2  = 5'd9,  S_GL3  = 5'd10, S_X    = 5'd11,
		S_ROM   = 5'd12, S_FILT = 5'd13, S_DIV  = 5'd14, S_ML   = 5'd15,
		S_MR    = 5'd16, S_WB   = 5'd17, S_WW   = 5'd18,
		S_WR    = 5'd20, S_WRW  = 5'd21, S_NEXT = 5'd22, S_FIN  = 5'd23;

	reg  [4:0]  st;
	reg  [2:0]  ch;
	reg  [3:0]  rw;                                 // the window word being read
	reg  [1:0]  wi;                                 // the write being made at the channel's end (0..3)

	// the channel's fields
	reg  [21:0] f_ptr, f_base;
	reg  [31:0] f_pos, f_len;
	reg         f_fmt8;
	reg  [7:0]  f_rate;
	reg  [15:0] f_gl, f_gr;
	reg  [7:0]  f_loop;
	reg  [2:0]  f_filt;
	reg signed [15:0] y;

	reg  [15:0] gml, gmr;                           // the block's masters
	reg  [15:0] gl, gr;                             // the channel's gains
	wire [16:0] gsum = {1'b0, gl} + {1'b0, gr};
	reg         mono;

	reg  [6:0]  n;                                  // samples of this call, 1..80
	reg  [6:0]  i;                                  // the sample
	reg         ended;

	// the decode: the word in use, its part (byte / nibble) and the hold count
	wire        rate_ok = (f_rate >= 8'd1) && (f_rate <= 8'd5);
	wire  [2:0] h0 = f_rate[2:0];                   // the hold of parts 0 / 2
	wire  [2:0] h1 = (f_rate == 8'd3) ? 3'd2 : f_rate[2:0];   // parts 1 / 3
	wire  [4:0] gw = f_fmt8 ? ({2'b0, h0} + {2'b0, h1}) : ({1'b0, h0, 1'b0} + {1'b0, h1, 1'b0});   // samples per word
	reg  [15:0] wcur;
	reg  [1:0]  part;
	reg  [2:0]  hc;
	reg         need;                               // the next sample starts a new word

	// the fetcher (one word ahead)
	reg         fen;                                // fetching for this call
	reg         fpend;                              // a read is out (granted or not)
	reg  [7:0]  fstart;                             // the first sample of the next word to fetch
	reg  [15:0] wnext;
	reg         wnv;

	// the TABLES ROM address: the new word's part 0 when the sample takes one (need), else the part in use
	wire  [8:0] rom_an = f_fmt8 ? {1'b0, wnext[15:8]} : {5'b10000, wnext[15:12]};
	assign rom_sa = need ? rom_an : rom_a;

	// the bus pair being mixed
	reg  [31:0] busv;
	reg         bnext, bvalid;
	reg  [15:0] ol;

	// the filter's input
	wire signed [15:0] x = rate_ok ? {{5{rom_q[10]}}, rom_q} : 16'sd0;
	wire signed [18:0] xe = {{3{x[15]}}, x};
	wire signed [18:0] ye = {{3{y[15]}}, y};
	wire signed [18:0] v1 = xe + ye;
	wire signed [18:0] v2 = xe + (ye <<< 1);
	wire signed [18:0] v3 = xe + (ye <<< 1) + ye;
	wire signed [18:0] v4 = xe + (ye <<< 2);
	wire signed [18:0] v5 = xe + (ye <<< 3) - ye;
	wire signed [18:0] t1 = v1 + (v1[18] ? 19'sd1 : 19'sd0);
	wire signed [18:0] t3 = v3 + (v3[18] ? 19'sd3 : 19'sd0);
	wire signed [18:0] t5 = v5 + (v5[18] ? 19'sd7 : 19'sd0);
	wire signed [18:0] vd = (f_filt == 3'd2) ? v2 : v4;
	wire        [18:0] vmag = vd[18] ? -vd : vd;
	reg                vneg;

	// the multiplier's operands by state (combinational into the registered product)
	always @(*) begin
		ma = 19'sd0;
		mb = 18'sd0;
		case (st)
			S_GM1:  begin ma = {3'b0, g_sm_l}; mb = {2'b0, g_sfxmaster}; end
			S_GM2:  begin ma = {3'b0, g_sm_r}; mb = {2'b0, g_sfxmaster}; end
			S_PREP: begin ma = {3'b0, gml};    mb = {2'b0, f_gl}; end
			S_GL2:  begin ma = {3'b0, gmr};    mb = {2'b0, f_gr}; end
			S_FILT: begin ma = vmag;           mb = (f_filt == 3'd2) ? 18'sh0AAAB : 18'sh0CCCD; end
			S_ML:   begin ma = ye;             mb = {2'b0, mono ? gsum[16:1] : gl}; end
			S_MR, S_WB, S_WW: begin ma = ye;   mb = {2'b0, gr}; end   // held while S_WB / S_WW wait for the bus
			default: ;
		endcase
	end

	// the ROM address: the byte / nibble of the word in use
	always @(*) begin
		if (f_fmt8) rom_a = {1'b0, part[0] ? wcur[7:0] : wcur[15:8]};
		else case (part)
			2'd0: rom_a = {5'b10000, wcur[15:12]};
			2'd1: rom_a = {5'b10000, wcur[11:8]};
			2'd2: rom_a = {5'b10000, wcur[7:4]};
			default: rom_a = {5'b10000, wcur[3:0]};
		endcase
	end

	wire [2:0] hlen = part[0] ? h1 : h0;
	wire       plast = f_fmt8 ? part[0] : (part == 2'd3);

	// the POS / LEN tests: one adder and one comparator, time-shared by state:
	//   S_RD of the LOOP word (the channel's last read): f_pos >= f_len, kept in f_le (LEN <= POS: nothing mixed);
	//   S_PREP: f_len >= f_pos + 80 (a u32 add that wraps, as the cart's) -> n = 80, else LEN - POS;
	//   S_WW: the new POS f_pos + n and its end test f_pos + n >= f_len.
	wire        cmp_sw = (st == S_PREP);
	wire  [6:0] pos_k  = cmp_sw ? 7'd80 : (st == S_WW) ? n : 7'd0;
	wire [31:0] pos_s  = f_pos + {25'd0, pos_k};
	wire [31:0] cmp_a  = cmp_sw ? f_len : pos_s;
	wire [31:0] cmp_b  = cmp_sw ? pos_s : f_len;
	wire        pos_ge = (cmp_a >= cmp_b);
	reg         f_le;

	// the state-RAM write data, a select of the fields it carries: DELAY - 1 in S_DLYW (the DELAY word's low half is
	// kept in f_gl, which a mixed channel loads again before any use), else the channel's end write wi; the bus pair
	// (the multiplier holds y x gR while S_WW waits); the CRAM address = PTR (it moves only at the read's done, after
	// the grant). Each is read only while its request is up, and every field it selects is steady then.
	wire        rew = ended && (f_loop != 8'd0);
	assign e_wdata = (st == S_DLYW) ? {16'd0, f_gl - 16'd1} :
	                 (wi == 2'd0) ? {10'd0, rew ? f_base : f_ptr} :
	                 (wi == 2'd1) ? (rew ? 32'd0 : f_pos) :
	                 (wi == 2'd2) ? {y, 16'd0} : 32'd0;
	assign b_wdata = {busv[31:16] + (mono ? ol : div256(mp)), busv[15:0] + ol};
	assign cq_addr = f_ptr;

	assign busy = (st != S_IDLE);

	always @(posedge clk) begin
		done <= 1'b0;

		// ---- the fetcher: words ceil(n / G), one ahead of the decode
		if (cq_req && cq_gnt) cq_req <= 1'b0;
		if (fpend && cq_done) begin
			fpend  <= 1'b0;
			wnext  <= c_data;
			wnv    <= 1'b1;
			f_ptr  <= f_ptr + 22'd2;
			fstart <= fstart + {3'd0, gw};
		end
		else if (fen && !fpend && !wnv && (fstart < {1'b0, n})) begin
			fpend   <= 1'b1;
			cq_req  <= 1'b1;
		end

		// ---- the bus read handshake: data in the clock after the grant
		bnext <= 1'b0;
		if (b_rreq && b_rgnt) begin b_rreq <= 1'b0; bnext <= 1'b1; end
		if (bnext) begin busv <= b_rdata; bvalid <= 1'b1; end

		case (st)
			S_IDLE: if (start) begin
				if (sfx_on) st <= S_GM1;
				else begin done <= 1'b1; end
				ch <= 3'd0;
			end
			// the block's masters: SMASTER.L / .R with SMCFG, clamped
			S_GM1: st <= S_GM2;
			S_GM2: begin gml <= clamp16(mp); st <= S_GM3; end
			S_GM3: begin gmr <= clamp16(mp); st <= S_CH; end

			// ---- a channel: FMT (ID) first, then DELAY, then the rest
			S_CH: begin
				rw      <= SW_FMT;
				e_rreq  <= 1'b1;
				e_raddr <= saddr(ch, SW_FMT);
				st      <= S_RW;
			end
			S_RW: if (e_rgnt) begin e_rreq <= 1'b0; st <= S_RD; end
			S_RD: begin
				// the word of e_raddr's read is on e_rdata now
				case (rw)
					SW_FMT:   begin f_fmt8 <= (e_rdata[7:0] == 8'd1); f_rate <= e_rdata[15:8]; end
					SW_DELAY: f_gl   <= e_rdata[15:0];        // kept for the countdown write (e_wdata in S_DLYW)
					SW_PTR:   f_ptr  <= e_rdata[21:0];
					SW_BASE:  f_base <= e_rdata[21:0];
					SW_POS:   f_pos  <= e_rdata;
					SW_LEN:   f_len  <= e_rdata;
					SW_GAIN:  begin f_gl <= e_rdata[15:0]; f_gr <= e_rdata[31:16]; end
					default:  begin f_loop <= e_rdata[7:0]; f_filt <= e_rdata[10:8]; y <= e_rdata[31:16];
					                f_le <= pos_ge; end         // f_pos >= f_len (POS and LEN are loaded)
				endcase
				st <= S_RW;
				e_rreq <= 1'b1;
				case (rw)
					SW_FMT: if (e_rdata[31:16] == 16'd0) begin e_rreq <= 1'b0; st <= S_NEXT; end
					        else begin rw <= SW_DELAY; e_raddr <= saddr(ch, SW_DELAY); end
					SW_DELAY: if (e_rdata[15:0] != 16'd0) begin
						// count the delay down (as the cart does)
						e_rreq  <= 1'b0;
						e_wreq  <= 1'b1;
						e_waddr <= saddr(ch, SW_DELAY);
						e_wbe   <= 4'b0011;
						st      <= S_DLYW;
					end
					else begin rw <= SW_PTR; e_raddr <= saddr(ch, SW_PTR); end
					SW_PTR:  begin rw <= SW_BASE; e_raddr <= saddr(ch, SW_BASE); end
					SW_BASE: begin rw <= SW_POS;  e_raddr <= saddr(ch, SW_POS); end
					SW_POS:  begin rw <= SW_LEN;  e_raddr <= saddr(ch, SW_LEN); end
					SW_LEN:  begin rw <= SW_GAIN; e_raddr <= saddr(ch, SW_GAIN); end
					SW_GAIN: begin rw <= SW_LOOP; e_raddr <= saddr(ch, SW_LOOP); end
					default: begin e_rreq <= 1'b0; st <= S_PREP; end
				endcase
			end
			S_DLYW: if (e_wgnt) begin e_wreq <= 1'b0; st <= S_NEXT; end

			// ---- the call: the length rule, the gains
			S_PREP: begin
				// mp <= gml x GAIN_L in this clock (the operand mux)
				if (f_le) begin
					ended <= 1'b1;
					n     <= 7'd0;
					wi    <= 2'd0;
					st    <= S_WR;
				end
				else begin
					ended <= 1'b0;
					n     <= pos_ge ? 7'd80 : f_len[6:0] - f_pos[6:0];   // pos_ge = f_len >= f_pos + 80 here
					st    <= S_GL2;
				end
			end
			S_GL2: begin gl <= clamp16(mp); st <= S_GL3; end      // mp <= gmr x GAIN_R in this clock
			S_GL3: begin
				gr     <= clamp16(mp);
				mono   <= (gl == clamp16(mp)) | ym;
				i      <= 7'd0;
				need   <= 1'b1;
				part   <= 2'd0;
				hc     <= 3'd0;
				fstart <= 8'd0;
				fen    <= rate_ok;
				st     <= S_X;
			end

			// ---- a sample
			S_X: begin
				if (!rate_ok) st <= S_ROM;                       // no word: x = 0
				else if (!need) st <= S_ROM;
				else if (wnv) begin
					wcur <= wnext;
					wnv  <= 1'b0;
					need <= 1'b0;
					part <= 2'd0;
					hc   <= 3'd0;
					st   <= S_ROM;
				end
			end
			S_ROM: st <= S_FILT;                                  // rom_q <= the byte / nibble's value
			S_FILT: begin
				case (f_filt)
					3'd1: begin y <= t1[16:1]; st <= S_ML; end
					3'd3: begin y <= t3[17:2]; st <= S_ML; end
					3'd5: begin y <= t5[18:3]; st <= S_ML; end
					3'd2, 3'd4: begin vneg <= vd[18]; st <= S_DIV; end   // mp <= |v| x reciprocal
					default: begin y <= x; st <= S_ML; end
				endcase
			end
			S_DIV: begin
				if (f_filt == 3'd2) y <= vneg ? -$signed(mp[32:17]) : $signed(mp[32:17]);
				else                y <= vneg ? -$signed(mp[33:18]) : $signed(mp[33:18]);
				st <= S_ML;
			end
			S_ML: begin                                       // mp <= y x (mono ? g : gL); read the bus pair
				b_rreq   <= 1'b1;
				b_raddr  <= BUS_SFX + {1'b0, i};
				bvalid   <= 1'b0;
				st       <= S_MR;
			end
			S_MR: begin ol <= div256(mp); st <= S_WB; end     // mp <= y x gR
			S_WB: if (bvalid) begin
				b_wreq   <= 1'b1;
				b_waddr  <= BUS_SFX + {1'b0, i};
				st       <= S_WW;
			end
			S_WW: if (b_wgnt) begin
				b_wreq <= 1'b0;
				// the next sample's part / hold
				if (hc + 3'd1 >= hlen) begin
					hc <= 3'd0;
					if (plast) need <= 1'b1;
					else part <= part + 2'd1;
				end
				else hc <= hc + 3'd1;
				if (i + 7'd1 == n) begin
					fen   <= 1'b0;
					f_pos <= pos_s;                        // f_pos + n
					ended <= pos_ge;                       // f_pos + n >= f_len
					wi    <= 2'd0;
					st    <= S_WR;
				end
				else begin
					i  <= i + 7'd1;
					st <= S_X;
				end
			end

			// ---- the channel's writes: PTR, POS, Y, and ID when a one-shot ends
			S_WR: begin
				e_wreq <= 1'b1;
				case (wi)                               // e_wdata: the select above
					2'd0: begin e_waddr <= saddr(ch, SW_PTR); e_wbe <= 4'b1111; end
					2'd1: begin e_waddr <= saddr(ch, SW_POS); e_wbe <= 4'b1111; end
					2'd2: begin e_waddr <= saddr(ch, SW_LOOP); e_wbe <= 4'b1100; end
					default: begin e_waddr <= saddr(ch, SW_FMT); e_wbe <= 4'b1100; end
				endcase
				st <= S_WRW;
			end
			S_WRW: if (e_wgnt) begin
				e_wreq <= 1'b0;
				if (wi == 2'd2 && ended && f_loop == 8'd0) begin wi <= 2'd3; st <= S_WR; end
				else if (wi == 2'd2 || wi == 2'd3) st <= S_NEXT;
				else begin wi <= wi + 2'd1; st <= S_WR; end
			end

			S_NEXT: begin
				if (ch == 3'd7) st <= S_FIN;
				else begin ch <= ch + 3'd1; st <= S_CH; end
			end
			S_FIN: begin done <= 1'b1; st <= S_IDLE; end
			default: st <= S_IDLE;
		endcase

		if (reset) begin
			st      <= S_IDLE;
			done    <= 1'b0;
			e_rreq  <= 1'b0;
			e_wreq  <= 1'b0;
			cq_req  <= 1'b0;
			b_rreq <= 1'b0;
			b_wreq <= 1'b0;
			fen     <= 1'b0;
			fpend   <= 1'b0;
			wnv     <= 1'b0;
			bnext   <= 1'b0;
			bvalid  <= 1'b0;
		end
	end

endmodule
