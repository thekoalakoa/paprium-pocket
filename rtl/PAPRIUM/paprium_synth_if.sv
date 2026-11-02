// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (block B1, in the synth's first version; the synth's blocks are listed in paprium_synth.sv's
// header) - paprium_synth_if: region 0x06 with FEAT.SYNTH, the synth's MCU interface (the firmware's
// docs/MCU_INTERFACE.md v1.3 section 3.10, frozen 2026-10-21).
//
// MCU side: the global registers (3.10.1), the 16 voice windows (3.10.3) and the 8 SFX windows (3.10.4) at the chip's
// field types, 0x0600_0000-0x0600_0FFF, addr[11:2] decoded, aliases above; reserved words read 0 and ignore writes.
// Word, halfword and byte stores write only their lanes; a load returns the whole word. Registered read data and a
// registered ack held until the request drops (the FPGAIO / XLINK pattern): a global register answers in one clock, a
// window word in two (read) or one (write) once the state RAM port is free. The MCU waits at most MCU_AGE clocks behind
// the synth's own use of the state RAM; after that it goes first and the synth's port stalls (e_rgnt / e_wgnt low).
//
// Engine side (the mixer blocks B2-B9):
//   * every global field as a wire (g_*), the CONFIG / ARM / PHASE / DONE strobes, ARR / DONE / SEQLAT;
//   * the logic-owned globals written back: ECHOB / ECHOS INDEX (advanced once a block, as the cart does) and YMFILT
//     A / B (the YM output stage's two filter states);
//   * the state RAM through a request / grant port: a read granted at clock t (e_rgnt) gives e_rdata in clock t+1
//     only; a write is done at the clock it is granted (e_wgnt), lanes e_wbe. A requester holds its request until it
//     is granted. A read is not granted in the clock a write to the same word is (no read-during-write case reaches
//     the M10K), so a read always sees every write granted before it;
//   * the B2 scheduler's read-backs (STATUS, SCHED, PHASE) and its DIAG events in; CAUSE.BLK (post_blk) out, a pulse
//     one clock after every 1 -> 0 edge of st_busy.
//
// Reset (sys_reset, every reset): every global register to its reset value (CONFIG 0, so no block runs; ARR = DONE = 0;
// TIMEOUT = CLK_HZ / 200, 5 ms). The state RAM is NOT reset (3.10.6): the firmware writes every field before it first
// writes CONFIG MODE 1 / 2 or a FLAGS bit. Clock: clk_sys only; no new clock domain.

module paprium_synth_if #(
	parameter integer CLK_HZ  = 0,               // clk in Hz, from core_top (clkcheck R4: set by every instance)
	parameter integer MCU_AGE = 2                  // clocks an MCU state-RAM access may wait behind the synth
)(
	input             clk,
	input             reset,

	// ---- MCU (paprium_cart: mcu.ce & mcu.map.sfx, mcu.addr[11:0], mcu.we, mcu.dato) ----
	input             m_req,                       // held until m_ack, low for >= 1 clock between accesses
	input      [11:0] m_addr,
	input       [3:0] m_we,                        // store lanes; 0 = a load
	input      [31:0] m_wdata,
	output reg [31:0] m_rdata,
	output reg        m_ack,

	// ---- arrivals: the 68000's writes to $1FEA (B) and $1FEC (A), the pulses that set CAUSE.B / CAUSE.A ----
	input             post_b,
	input             post_a,
	output     [15:0] arr,                         // arrivals so far, wrapping
	output reg  [1:0] arr_inc,                     // this clock's arrivals (0, 1; 2 never from one 68000)

	// ---- to the scheduler (B2) ----
	output reg        cfg_wr,                      // a CONFIG write: apply CONFIG's scheduler half (3.10.2)
	output      [1:0] g_mode,
	output            g_pal,
	output            g_dtwin,
	output     [15:0] g_cfg_seq,                   // the arrival the CONFIG write belongs to
	output reg        arm_wr,                      // ARM lane 0 written: FPEND := arm_val (since the second step: the
	output reg        arm_val,                     // cart stores 1 at the tick, 0 at a BGM start; 3.10.1 says 1 only)
	output reg        phase_idx_wr,                // PHASE lanes 0 / 1 written (TEST): DTIDX := phase_idx
	output     [10:0] phase_idx,
	output reg        phase_restart,               // PHASE bit 31 written 1 (TEST): TIM6 and TIM8 restart
	output     [15:0] g_done,
	output     [23:0] g_timeout,
	input             st_busy,
	input             st_run,
	input             st_fpend,
	input             st_fill,
	input             st_cur,
	input       [3:0] st_qdepth,
	input      [11:0] st_blkcnt,
	input       [7:0] sc_cnt,
	input       [3:0] sc_nblk,
	input      [15:0] sc_half,
	input      [10:0] ph_dtidx,
	input       [6:0] ph_strobes,
	input             inc_incomplete,              // DIAG events (pulses)
	input             inc_timeout,
	input             inc_underrun,
	output reg        post_blk,                    // -> fpgio CAUSE.BLK

	// ---- globals for the mixer ----
	output      [5:0] g_flags,
	output     [15:0] g_wm_l, g_wm_r,               // WMASTER.L, WMASTER.R
	output     [15:0] g_boost, g_wavemaster,        // WBOOST.BOOST, WBOOST.WAVEMASTER
	output     [15:0] g_sm_l, g_sm_r,               // SMASTER.L, SMASTER.R
	output     [15:0] g_sfxmaster,                  // SMCFG.SFXMASTER
	output     [15:0] g_echob_gain,                 // ECHOB.GAIN (s16)
	output      [7:0] g_echob_delay, g_echob_index, // ECHOB.DELAY, ECHOB.INDEX
	output     [15:0] g_echos_gain,                 // ECHOS.GAIN (s16)
	output      [7:0] g_echos_delay, g_echos_index, // ECHOS.DELAY, ECHOS.INDEX
	output     [15:0] g_ymf_a, g_ymf_b,             // YMFILT.A, YMFILT.B (s16)
	output     [20:0] g_dtout,                      // DTOUT: [15:0] GAIN Q8.8, [16] INVERT, [20:17] DCK
	input             e_echob_idx_we,
	input       [7:0] e_echob_idx,
	input             e_echos_idx_we,
	input       [7:0] e_echos_idx,
	input             e_ymf_we,
	input      [15:0] e_ymf_a,
	input      [15:0] e_ymf_b,

	// ---- the state RAM, synth side ----
	input             e_rreq,
	input       [7:0] e_raddr,
	output            e_rgnt,
	output     [31:0] e_rdata,
	input             e_wreq,
	input       [7:0] e_waddr,
	input       [3:0] e_wbe,
	input      [31:0] e_wdata,
	output            e_wgnt
);
	import paprium_synth_pkg::*;

	localparam integer TMO_I = CLK_HZ / 200;
	localparam [23:0] TIMEOUT_RST = TMO_I[23:0];

	// ================================================================ globals
	reg  [1:0]  r_mode;
	reg         r_pal, r_dtwin;
	reg  [15:0] r_seq;
	reg  [5:0]  r_flags;
	reg  [31:0] r_wmaster, r_wboost, r_smaster;
	reg  [15:0] r_smcfg;
	reg  [15:0] r_echob_gain, r_echos_gain;
	reg  [7:0]  r_echob_delay, r_echob_index, r_echos_delay, r_echos_index;
	reg  [15:0] r_arr, r_done, r_seqlat_a, r_seqlat_b;
	reg  [15:0] r_ymf_a, r_ymf_b;
	reg  [20:0] r_dtout;
	reg  [7:0]  d_incomplete, d_timeouts, d_wbusy, d_underrun;
	reg  [23:0] r_timeout;
	reg         busy_q;
	reg  [10:0] r_phase_idx;

	assign g_mode        = r_mode;
	assign g_pal         = r_pal;
	assign g_dtwin       = r_dtwin;
	assign g_cfg_seq     = r_seq;
	assign g_flags       = r_flags;
	assign g_wm_l        = r_wmaster[15:0];
	assign g_wm_r        = r_wmaster[31:16];
	assign g_boost       = r_wboost[15:0];
	assign g_wavemaster  = r_wboost[31:16];
	assign g_sm_l        = r_smaster[15:0];
	assign g_sm_r        = r_smaster[31:16];
	assign g_sfxmaster   = r_smcfg;
	assign g_echob_gain  = r_echob_gain;
	assign g_echob_delay = r_echob_delay;
	assign g_echob_index = r_echob_index;
	assign g_echos_gain  = r_echos_gain;
	assign g_echos_delay = r_echos_delay;
	assign g_echos_index = r_echos_index;
	assign g_ymf_a       = r_ymf_a;
	assign g_ymf_b       = r_ymf_b;
	assign g_dtout       = r_dtout;
	assign g_done        = r_done;
	assign g_timeout     = r_timeout;
	assign arr           = r_arr;

	// ================================================================ the MCU access
	// ---- the window access waiting for the state RAM ----
	reg         mp_busy;                           // a window access is pending
	// Trimmed to save logic: mp_age counts 0 .. MCU_AGE and stops there, so it needs only clog2(MCU_AGE + 1) bits (2 for
	// MCU_AGE 2)
	localparam integer AGW = (MCU_AGE < 2) ? 1 : $clog2(MCU_AGE + 1);
	reg [AGW-1:0] mp_age;
	reg         mp_rq;                             // a read was granted last clock: its data is on ram_q now
	wire        mp_old  = (mp_age >= MCU_AGE[AGW-1:0]);

	// first clock of an access: decode; a global register is served at once, a window word goes to the RAM arbiter
	wire        first   = m_req & ~m_ack & ~mp_busy;
	wire  [9:0] wi      = m_addr[11:2];
	wire        is_glob = (m_addr[11:10] == 2'b00);
	wire        is_vwin = (m_addr[11:10] == 2'b01);
	wire        is_swin = (m_addr[11:9]  == 3'b100);
	wire  [3:0] vv      = m_addr[9:6];
	wire  [2:0] sc      = m_addr[8:6];
	wire  [3:0] ww      = m_addr[5:2];
	wire        win_ok  = (is_vwin & (ww < VW_N)) | (is_swin & (ww < SW_N));
	wire  [7:0] win_a   = is_vwin ? vaddr(vv, ww) : saddr(sc, ww);
	wire [31:0] win_m   = is_vwin ? vmask(ww) : smask(ww);
	wire        wr      = (m_we != 4'b0000);
	wire  [3:0] gw      = (first & is_glob) ? m_we : 4'b0000;   // a global store's lanes, its first clock only
	// Trimmed to save logic: no we / address / lane registers for the pending window access: the NEORV32 classic Wishbone
	// gateway holds m_addr, m_we and m_wdata from the access's first clock until its ack (neorv32_wishbone.vhd: ctrl.adr /
	// wdat / sel / we change only in IDLE; stb = cyc stay high through BUSY / CANCELED)
	wire        mp_wr   = wr;
	wire  [7:0] mp_a    = win_a;
	wire  [3:0] mp_be   = m_we;

	function automatic [31:0] merge(input [31:0] old, input [31:0] nw, input [3:0] lanes);
		merge = {lanes[3] ? nw[31:24] : old[31:24], lanes[2] ? nw[23:16] : old[23:16],
		         lanes[1] ? nw[15:8]  : old[15:8],  lanes[0] ? nw[7:0]   : old[7:0]};
	endfunction

	wire [31:0] cfg_rd    = {r_seq, 12'd0, r_dtwin, r_pal, r_mode};
	wire [31:0] echob_rd  = {r_echob_index, r_echob_delay, r_echob_gain};
	wire [31:0] echos_rd  = {r_echos_index, r_echos_delay, r_echos_gain};
	wire [31:0] phase_rd  = {1'b0, 8'd0, ph_strobes, 5'd0, ph_dtidx};
	wire [31:0] ymf_rd    = {r_ymf_b, r_ymf_a};
	// an MCU store meets the synth's write of the same register in one clock (only if the firmware breaks rule 6.3.8):
	// the synth's value first, the MCU's lanes over it
	wire [31:0] echob_bs  = {e_echob_idx_we ? e_echob_idx : r_echob_index, r_echob_delay, r_echob_gain};
	wire [31:0] echos_bs  = {e_echos_idx_we ? e_echos_idx : r_echos_index, r_echos_delay, r_echos_gain};
	wire [31:0] ymf_bs    = e_ymf_we ? {e_ymf_b, e_ymf_a} : ymf_rd;
	wire [31:0] cfg_nw    = merge(cfg_rd, m_wdata, gw);
	wire [31:0] echob_nw  = merge(echob_bs, m_wdata, gw);
	wire [31:0] echos_nw  = merge(echos_bs, m_wdata, gw);
	wire [31:0] ymf_nw    = merge(ymf_bs, m_wdata, gw);
	wire [31:0] phase_nw  = merge(phase_rd, m_wdata, gw);
	wire [31:0] done_nw   = merge({16'd0, r_done}, m_wdata, gw);
	wire [31:0] dtout_nw  = merge({11'd0, r_dtout}, m_wdata, gw);
	wire [31:0] tmo_nw    = merge({8'd0, r_timeout}, m_wdata, gw);
	wire [31:0] flags_nw  = merge({26'd0, r_flags}, m_wdata, gw);
	wire [31:0] smcfg_nw  = merge({16'd0, r_smcfg}, m_wdata, gw);

	reg  [31:0] glob_rd;
	always @(*) begin
		// Trimmed to save logic: glob_rd reaches m_rdata only when is_glob (wi[9:8] = 0), so the decode needs wi[7:0] only
		case ({2'b00, wi[7:0]})
			RG_ID:      glob_rd = SYNTH_ID;
			RG_CONFIG:  glob_rd = cfg_rd;
			RG_FLAGS:   glob_rd = {26'd0, r_flags};
			RG_WMASTER: glob_rd = r_wmaster;
			RG_WBOOST:  glob_rd = r_wboost;
			RG_SMASTER: glob_rd = r_smaster;
			RG_SMCFG:   glob_rd = {16'd0, r_smcfg};
			RG_ECHOB:   glob_rd = echob_rd;
			RG_ECHOS:   glob_rd = echos_rd;
			RG_SEQ:     glob_rd = {r_done, r_arr};
			RG_DONE:    glob_rd = {16'd0, r_done};
			RG_STATUS:  glob_rd = {4'd0, st_blkcnt, 7'd0, st_qdepth, st_cur, st_fill, st_fpend, st_run, st_busy};
			RG_PHASE:   glob_rd = phase_rd;
			RG_YMFILT:  glob_rd = ymf_rd;
			RG_DTOUT:   glob_rd = {11'd0, r_dtout};
			RG_DIAG:    glob_rd = {d_underrun, d_wbusy, d_timeouts, d_incomplete};
			RG_TIMEOUT: glob_rd = {8'd0, r_timeout};
			RG_SEQLAT:  glob_rd = {r_seqlat_a, r_seqlat_b};
			RG_SCHED:   glob_rd = {sc_half, 4'd0, sc_nblk, sc_cnt};
			default:    glob_rd = 32'd0;           // ARM and the reserved words
		endcase
	end


	// ================================================================ the state RAM arbiter
	// Trimmed to save logic: no store-data / mask registers. The NEORV32 classic Wishbone gateway (neorv32_wishbone.vhd:
	// ctrl.adr / wdat / sel / we change only in IDLE; stb = cyc stay high through BUSY / CANCELED) holds address, data and
	// lanes from an access's first clock until its ack, so the store data is m_wdata in the write's own clock, masked by
	// the word's mask, which follows from mp_a (amask = the inverse of vaddr / saddr; win_ok keeps reserved words out of
	// mp_a).
	wire [31:0] mp_msk  = amask(mp_a);
	wire        m_wpend = mp_busy & mp_wr & ~mp_rq;
	wire        m_rpend = mp_busy & ~mp_wr & ~mp_rq;
	// write port: the synth first, unless the MCU has waited MCU_AGE clocks (or an aged MCU read of the same word
	// needs this clock)
	assign e_wgnt  = e_wreq & ~(m_wpend & mp_old) & ~(m_rpend & mp_old & (e_waddr == mp_a));
	wire   m_wgo   = m_wpend & ~e_wgnt;
	wire   ram_we  = e_wgnt | m_wgo;
	wire  [7:0] ram_wa = e_wgnt ? e_waddr : mp_a;
	wire  [3:0] ram_be = e_wgnt ? e_wbe : mp_be;
	wire [31:0] ram_wd = e_wgnt ? e_wdata : (m_wdata & mp_msk);
	// read port: the same rule, and never the word being written in this clock
	assign e_rgnt  = e_rreq & ~(m_rpend & mp_old) & ~(ram_we & (ram_wa == e_raddr));
	// Trimmed to save logic: while m_rpend, no MCU write goes (m_wpend = 0), so ram_we = e_wgnt and ram_wa = e_waddr
	// whenever it is
	// set: the same test as ~(ram_we & (ram_wa == mp_a)), sharing e_wgnt's own compare
	wire   m_rgo   = m_rpend & ~e_rgnt & ~(e_wgnt & (e_waddr == mp_a));
	wire  [7:0] ram_ra = e_rgnt ? e_raddr : mp_a;
	wire [31:0] ram_q;
	assign e_rdata = ram_q;

	paprium_synth_sram sram (
		.clk(clk), .we(ram_we), .wa(ram_wa), .be(ram_be), .wd(ram_wd), .ra(ram_ra), .rd(ram_q)
	);

	// ================================================================ registers
	always @(posedge clk) begin
		cfg_wr        <= 1'b0;
		arm_wr        <= 1'b0;
		phase_idx_wr  <= 1'b0;
		phase_restart <= 1'b0;
		arr_inc       <= {1'b0, post_b} + {1'b0, post_a};
		busy_q        <= st_busy;
		post_blk      <= busy_q & ~st_busy;

		if (reset) begin
			r_mode <= 2'd0; r_pal <= 1'b0; r_dtwin <= 1'b0; r_seq <= 16'd0;
			r_flags <= 6'd0; r_wmaster <= 32'd0; r_wboost <= 32'd0; r_smaster <= 32'd0; r_smcfg <= 16'd0;
			r_echob_gain <= 16'd0; r_echob_delay <= 8'd0; r_echob_index <= 8'd0;
			r_echos_gain <= 16'd0; r_echos_delay <= 8'd0; r_echos_index <= 8'd0;
			r_arr <= 16'd0; r_done <= 16'd0; r_seqlat_a <= 16'd0; r_seqlat_b <= 16'd0;
			r_ymf_a <= 16'd0; r_ymf_b <= 16'd0; r_dtout <= 21'd0;
			d_incomplete <= 8'd0; d_timeouts <= 8'd0; d_wbusy <= 8'd0; d_underrun <= 8'd0;
			r_timeout <= TIMEOUT_RST; r_phase_idx <= 11'd0;
			busy_q <= 1'b0; post_blk <= 1'b0; arr_inc <= 2'd0; arm_val <= 1'b0;
		end
		else begin
			// arrivals (B before A if ever both)
			case ({post_a, post_b})
				2'b01: begin r_arr <= r_arr + 16'd1; r_seqlat_b <= r_arr + 16'd1; end
				2'b10: begin r_arr <= r_arr + 16'd1; r_seqlat_a <= r_arr + 16'd1; end
				2'b11: begin r_arr <= r_arr + 16'd2; r_seqlat_b <= r_arr + 16'd1; r_seqlat_a <= r_arr + 16'd2; end
				default: ;
			endcase

			// the synth's own writes first; an MCU store in the same clock wins on the lanes it writes
			if (e_echob_idx_we) r_echob_index <= e_echob_idx;
			if (e_echos_idx_we) r_echos_index <= e_echos_idx;
			if (e_ymf_we) begin r_ymf_a <= e_ymf_a; r_ymf_b <= e_ymf_b; end

			// DIAG (saturating)
			if (inc_incomplete & (d_incomplete != 8'hFF)) d_incomplete <= d_incomplete + 8'd1;
			if (inc_timeout    & (d_timeouts   != 8'hFF)) d_timeouts   <= d_timeouts   + 8'd1;
			if (inc_underrun   & (d_underrun   != 8'hFF)) d_underrun   <= d_underrun   + 8'd1;
			if (first & wr & st_run & (d_wbusy != 8'hFF)) d_wbusy <= d_wbusy + 8'd1;

			if (gw != 4'b0000) case ({2'b00, wi[7:0]})   // trimmed: gw != 0 only when is_glob (wi[9:8] = 0)
				RG_CONFIG:  begin
					r_mode <= cfg_nw[1:0]; r_pal <= cfg_nw[2]; r_dtwin <= cfg_nw[3]; r_seq <= cfg_nw[31:16];
					cfg_wr <= 1'b1;
				end
				RG_FLAGS:   r_flags   <= flags_nw[5:0];
				RG_WMASTER: r_wmaster <= merge(r_wmaster, m_wdata, gw);
				RG_WBOOST:  r_wboost  <= merge(r_wboost, m_wdata, gw);
				RG_SMASTER: r_smaster <= merge(r_smaster, m_wdata, gw);
				RG_SMCFG:   r_smcfg   <= smcfg_nw[15:0];
				RG_ECHOB:   begin
					r_echob_gain <= echob_nw[15:0]; r_echob_delay <= echob_nw[23:16]; r_echob_index <= echob_nw[31:24];
				end
				RG_ECHOS:   begin
					r_echos_gain <= echos_nw[15:0]; r_echos_delay <= echos_nw[23:16]; r_echos_index <= echos_nw[31:24];
				end
				RG_ARM:     if (gw[0]) begin arm_wr <= 1'b1; arm_val <= m_wdata[0]; end
				RG_DONE:    r_done <= done_nw[15:0];
				RG_PHASE:   begin
					if (gw[1:0] != 2'b00) begin phase_idx_wr <= 1'b1; r_phase_idx <= phase_nw[10:0]; end
					if (gw[3] & m_wdata[31]) phase_restart <= 1'b1;
				end
				RG_YMFILT:  begin r_ymf_a <= ymf_nw[15:0]; r_ymf_b <= ymf_nw[31:16]; end
				RG_DTOUT:   r_dtout   <= dtout_nw[20:0];
				RG_DIAG:    begin d_incomplete <= 8'd0; d_timeouts <= 8'd0; d_wbusy <= 8'd0; d_underrun <= 8'd0; end
				RG_TIMEOUT: r_timeout <= tmo_nw[23:0];
				default: ;
			endcase
		end
	end

	assign phase_idx = r_phase_idx;

	// the MCU handshake and the window path
	always @(posedge clk) begin
		if (!m_req) begin
			m_ack   <= 1'b0;
			m_rdata <= 32'd0;
		end

		if (reset) begin
			mp_busy <= 1'b0; mp_rq <= 1'b0; mp_age <= {AGW{1'b0}};
			m_ack   <= 1'b0; m_rdata <= 32'd0;
		end
		else if (mp_busy) begin
			if (mp_rq) begin                                   // the read's data is on ram_q in this clock
				mp_rq   <= 1'b0;
				mp_busy <= 1'b0;
				if (m_req) begin m_ack <= 1'b1; m_rdata <= ram_q & mp_msk; end
			end
			else if (m_wgo) begin
				mp_busy <= 1'b0;
				if (m_req) begin m_ack <= 1'b1; m_rdata <= 32'd0; end
			end
			else if (m_rgo) mp_rq <= 1'b1;
			else if (!mp_old) mp_age <= mp_age + {{(AGW-1){1'b0}}, 1'b1};
		end
		else if (first) begin
			if (is_glob | ~win_ok) begin                       // a global register or a reserved word: at once
				m_ack   <= 1'b1;
				m_rdata <= (is_glob & ~wr) ? glob_rd : 32'd0;
			end
			else begin
				mp_busy <= 1'b1;
				mp_age  <= {AGW{1'b0}};
				mp_rq   <= 1'b0;
			end
		end
	end

endmodule

