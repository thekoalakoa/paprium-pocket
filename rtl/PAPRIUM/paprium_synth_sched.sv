// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (block B2; the synth's blocks are listed in paprium_synth.sv's header; here B1 =
// paprium_synth_if, B2 = paprium_synth_sched, B9 = paprium_synth_dtplay, B10 = paprium_synth_cram) -
// paprium_synth_sched: the synth's timebase and block scheduler (the firmware's docs/MCU_INTERFACE.md v1.3 3.10.1
// STATUS / PHASE / SCHED / DIAG, 3.10.2, 3.10.5, 3.10.6).
//
// What it does, as the cart does it (we reverse engineered the STM32F4's commands as close as possible, with hardware
// verification):
//   * TIM8, the DAC trigger, at 48,000 Hz, and TIM6 at 479.52 Hz = exactly 100.1 TIM8 periods. Both come from one
//     accumulator in tenths of a sample: +480,000 per clock, a tenth each CLK_HZ; TIM8 every 10 tenths, TIM6 every
//     1,001. So the ratio is the chip's exactly at any CLK_HZ (a design decision: the console clock); a TIM8 strobe
//     that falls on a TIM6 instant counts before it (the order of our reference tests); the DT DMA position at an
//     instant is the number of TIM8 strobes with the DACs on since reset, mod 1,920. TIM8 is this block's own strobe,
//     not the core's existing dac_clocker (the synth design planned to reuse that one): dac_clocker's integer divider
//     runs at 48,000.10 Hz (+2.1 ppm, NTSC and PAL; measured when this block was repaired), so TIM8 would drift against
//     an exact TIM6 (about 6 strobes a minute) and lose the chip's 100.1 ratio; it stops neither for the menu freeze
//     nor for PHASE.RESTART; and it sits in audio_sfx's generate block, which the synth step retires. B9 (DT playback)
//     takes its strobe from tim8 here.
//   * The DT DMA (both rings, one index). The cart starts its DAC streams once, at index 0, with the first DT CONFIG
//     after power-on; every later mode change only switches the DAC channels off and on again. So the index advances on
//     TIM8 strobes while a DT mode is on, holds while YM-DAC / no mode is on, and resumes where it held; index 0 only
//     after reset (measured in our tests, in a DT -> YM case). The HOLD rests on our model of the chip's DMA: a stream
//     whose DAC channel is off gets no request from its TIM8 trigger; on the cart that is not known (it decides only
//     which stale dac_buf samples play in the <= 40 ms after a YM -> DT switch). Every switch is dated at the arrival
//     of the 88 it belongs to (CONFIG.SEQ; the strobe count at each of the last 32 arrivals is kept; a SEQ further
//     back, not yet arrived or not one since reset is dated at the write instead and counted in DIAG.TIMEOUTS).
//   * The scheduler half of the cart's CONFIG command (3.10.2) on every CONFIG write; FPEND from ARM (bit 0 stored: 1
//     at the tick, 0 when a BGM module starts).
//   * The TIM6 handler's block decision (paprium_synth_tim6) once per instant, in instant order.
//   * The order of the chip's interrupts (3.10.5): each TIM6 instant is queued with NEED = ARR at that instant and
//     serviced only once DONE has reached NEED, or in the clock its age (clk_sys cycles since its push, counted on a
//     clock the menu freeze stops) reaches TIMEOUT (counted; a DONE visible by then serves it uncounted). A serviced
//     instant that mixes starts the block engine (blk_start, the dac_buf index, YM / DT) and RUN holds until the
//     engine is done and the CRAM clients are idle (the block's dac_buf writes have landed). BUSY = RUN or a
//     serviceable head.
//
// Not the chip's (the firmware's docs/ALLOWLIST.md, row B40, atomic blocks): the chip's EXTI preempts a block; here a
// block never starts while the firmware works on an older arrival, and runs whole once it starts.
//
// Menu freeze (3.10.6, ALLOWLIST.md row B7): while freeze = 1 the tenth accumulator, TIM8, TIM6, the DT position and
// the hold-off timeout stop where they are and resume in place (queued instants are still serviced on DONE).
//
// Reset (sys_reset): the scheduler's words as before the cart's audio start-up (all 0: no block runs, MODE 0 only
// counts), queue empty, timebase at phase 0, DT DMA stopped at index 0. Clock: clk_sys only; no new clock domain.

module paprium_synth_sched #(
	parameter integer CLK_HZ = 0                   // clk in Hz (clkcheck R4: set by every instance); > 480,000
)(
	input             clk,
	input             reset,
	input             freeze,                      // Pocket menu open and CTRL.MENU_MUTE_EN (this clock)

	// ---- from B1 ----
	input      [15:0] arr,                         // arrivals so far (B1's registered count)
	input       [1:0] arr_inc,                     // arrivals counted at the last edge (0, 1, 2)
	input             cfg_wr,
	input       [1:0] g_mode,
	input             g_pal,
	input      [15:0] g_cfg_seq,
	input             arm_wr,
	input             arm_val,
	input             phase_idx_wr,
	input      [10:0] phase_idx,
	input             phase_restart,
	input      [15:0] g_done,
	input      [23:0] g_timeout,

	// ---- to B1 (STATUS, SCHED, PHASE, DIAG) ----
	output            st_busy,
	output            st_run,
	output            st_fpend,
	output            st_fill,
	output            st_cur,
	output      [3:0] st_qdepth,
	output     [11:0] st_blkcnt,
	output      [7:0] sc_cnt,
	output      [3:0] sc_nblk,
	output     [15:0] sc_half,
	output     [10:0] ph_dtidx,
	output      [6:0] ph_strobes,
	output reg        inc_incomplete,
	output reg        inc_timeout,

	// ---- the block engine (B3 envelope, then the block's mix, B4-B8) ----
	output reg        blk_start,                   // one clock
	output reg [10:0] blk_idx,                     // dac_buf entry of the block's first sample
	output reg        blk_ym,                      // the path at the block (1 = YM-DAC output stage)
	input             blk_done,                    // one clock, when the engine has finished the block
	input             cram_idle,                   // B10: nothing granted and unfinished, no request

	// ---- the timebase for the DT playback (B9) ----
	output            tim8,                        // the 48 kHz strobe (one clock)
	output            dt_run,                      // the DT DMA runs (MODE 1)
	output     [10:0] dt_idx,                      // the entry the next TIM8 strobe plays (in a tim8 clock: this one)
	output            s_ym                         // the path now (the block mix's YM / DT switch)
);
	import paprium_synth_pkg::*;

	localparam integer TENTH = 480000;              // tenths of a TIM8 period per second
	localparam [27:0] CLK28 = 28'(CLK_HZ);
	localparam [27:0] TEN28 = 28'(TENTH);
	localparam [26:0] K27   = 27'(CLK_HZ - TENTH);       // K = CLK_HZ - 480,000 > 0: sub + 480,000 >= CLK_HZ <=> sub >= K
	localparam [27:0] KNEG  = TEN28 - CLK28;        // (480,000 - CLK_HZ) mod 2^28 = 2^28 - K
	localparam integer QN = 8;                      // TIM6 queue depth (MCU_INTERFACE.md 3.10.5: at least 8)

	// ================================================================ timebase
	reg  [26:0] sub;                                // tenth-sample accumulator, 0 .. CLK_HZ - 1
	reg   [3:0] ten;                                // tenths of the current TIM8 period, 0..9
	reg   [9:0] t6c;                                // tenths of the current TIM6 period, 0..1,000
	reg   [6:0] strobes;                            // TIM8 strobes since the last TIM6 instant (PHASE.STROBES)
	reg  [10:0] pc;                                 // free-running TIM8 count mod 1,920
	reg  [24:0] ck;                                 // clk_sys cycles outside the freeze (the timeout clock)

	// Trimmed to save logic: the tick is sub >= K (one compare with a constant) and the next accumulator is ONE
	// add, sub + (tick ? 480,000 - CLK_HZ : 480,000) mod 2^27 (the operand is a constant chosen by the compare); the
	// base's add + compare + subtract + select give the same tick and the same next value for every 27-bit sub
	wire        due    = (sub >= K27);
	wire        tick   = ~freeze & ~phase_restart & due;
	wire        t8     = tick & (ten == 4'd9);
	wire        t6     = tick & (t6c == 10'd1000);
	wire [10:0] pc_inc = (pc == 11'd1919) ? 11'd0 : pc + 11'd1;
	wire [10:0] pc_nx  = t8 ? pc_inc : pc;           // the count after this clock's strobe
	wire [27:0] sub_x  = {1'b0, sub} + (due ? KNEG : TEN28);

	assign tim8 = t8;

	always @(posedge clk) begin
		if (reset) begin
			sub <= 27'd0; ten <= 4'd0; t6c <= 10'd0; strobes <= 7'd0; pc <= 11'd0; ck <= 25'd0;
		end
		else if (phase_restart) begin
			// TEST (PHASE bit 31): TIM6 and TIM8 restart together and PHASE.STROBES restarts at 0; the free-running TIM8
			// count pc (so the DT index) and the timeout clock ck run on
			sub <= 27'd0; ten <= 4'd0; t6c <= 10'd0; strobes <= 7'd0;
			if (!freeze) ck <= ck + 25'd1;
		end
		else if (!freeze) begin
			ck  <= ck + 25'd1;
			sub <= sub_x[26:0];                           // (in this branch tick = due)
			if (tick) begin
				ten <= (ten == 4'd9) ? 4'd0 : ten + 4'd1;
				t6c <= (t6c == 10'd1000) ? 10'd0 : t6c + 10'd1;
			end
			pc <= pc_nx;
			if (t6)      strobes <= 7'd0;
			else if (t8) strobes <= strobes + 7'd1;
		end
	end

	// ================================================================ the scheduler's words (the cart's)
	reg         w_path;                             // the path: 1 = YM-DAC, 0 = DT
	reg  [10:0] w_half;                             // SCHED.HALF
	reg   [2:0] w_nblk;                             // SCHED.NBLK
	reg  [11:0] w_blk;                              // STATUS.BLKCNT
	reg         w_fp;                               // STATUS.FPEND
	reg         w_cur;                              // STATUS.CUR
	reg         w_fill;                             // STATUS.FILL
	reg   [7:0] w_cnt;                              // SCHED.CNT

	// the DT DMA: index = (pc - dt_off) mod 1,920 while the DACs are on, dt_hold while they are off (0 after reset: the
	// first start programs index 0)
	reg         r_dtrun;
	reg  [10:0] dt_off, dt_hold;

	function automatic [10:0] mod_sub(input [10:0] a, input [10:0] b);   // (a - b) mod 1,920, a and b < 1,920
		reg [11:0] d;
		begin
			d = {1'b0, a} - {1'b0, b};
			mod_sub = d[11] ? (d[10:0] + 11'd1920) : d[10:0];
		end
	endfunction

	wire [10:0] live_idx = r_dtrun ? mod_sub(pc, dt_off) : dt_hold;

	// ================================================================ arrival stamps (32 x the strobe count)
	(* ramstyle = "MLAB, no_rw_check" *) reg [10:0] stamp [0:31];
	reg         st_pend;                            // two arrivals in one clock: the older one is stamped next clock
	reg   [5:0] st_n;                               // arrivals stamped since reset, saturating at 32
	reg   [4:0] st_pend_a;
	reg  [10:0] st_pend_v;
	always @(posedge clk) begin
		if (arr_inc != 2'd0)  stamp[arr[4:0]] <= pc;
		else if (st_pend)     stamp[st_pend_a] <= st_pend_v;
	end
	always @(posedge clk) begin
		if (reset) begin st_pend <= 1'b0; st_n <= 6'd0; end
		else begin
			st_pend <= (arr_inc == 2'd2) | (st_pend & (arr_inc != 2'd0));
			if (arr_inc != 2'd0) st_n <= (st_n >= 6'd31) ? 6'd32 : st_n + {4'd0, arr_inc};
			if (arr_inc == 2'd2) begin st_pend_a <= arr[4:0] - 5'd1; st_pend_v <= pc; end
		end
	end

	// ================================================================ the TIM6 queue
	(* ramstyle = "MLAB, no_rw_check" *) reg [51:0] q [0:QN-1];   // {ts[24:0], pc[10:0], need[15:0]}
	reg   [2:0] q_wp, q_rp;
	reg   [3:0] q_n;
	wire [51:0] q_head   = q[q_rp];
	wire [15:0] h_need   = q_head[15:0];
	wire [10:0] h_pc     = q_head[26:16];
	wire [24:0] h_ts     = q_head[51:27];
	wire [15:0] h_slack  = g_done - h_need;
	wire [24:0] h_age    = ck - h_ts;
	wire        h_doneok = ~h_slack[15];
	wire        h_tmo    = (h_age >= {1'b0, g_timeout});
	wire        q_full   = (q_n == QN[3:0]);
	wire        h_svc    = (q_n != 4'd0) & (h_doneok | h_tmo | q_full);

	// ================================================================ CONFIG apply (two clocks: the stamp read)
	reg         cf_go;                              // CONFIG write latched, its stamp read
	reg   [1:0] cf_mode;
	reg         cf_pal;
	reg         cf_old;                             // SEQ more than 31 arrivals back, not yet arrived, or before reset
	reg  [10:0] cf_stamp;                           // trimmed: the DMA count the apply dates from: the stamp of arrival
	                                                // SEQ, or (cf_old) the count at the apply = this clock's pc_nx
	wire [15:0] cf_dist = arr - g_cfg_seq;
	wire        cf_old_n = (cf_dist > 16'd31) | (cf_dist >= {10'd0, st_n});

	// ================================================================ the service FSM
	reg         run_blk, run_drain;
	assign st_run  = run_blk | run_drain;
	assign st_busy = st_run | h_svc;

	// Trimmed to save logic: ONE mod-1,920 subtractor shared by the three users that never share a clock: a CONFIG apply
	// (cf_go), a PHASE.DTIDX store (phase_idx_wr) and a service (svc = ... & ~hold_svc excludes both). B1 raises cfg_wr /
	// arm_wr / phase_idx_wr one clock after a store's first clock and a store's next first clock is at least two clocks
	// after that (m_ack, then m_req low), so cf_go (cfg_wr + 1) never meets phase_idx_wr. The live index keeps its own.
	wire [10:0] pidx  = (phase_idx >= 11'd1920) ? 11'd0 : phase_idx;
	wire        sh_cf = cf_go;
	wire        sh_ph = ~cf_go & phase_idx_wr;
	wire [10:0] sh_a  = sh_cf ? cf_stamp : (sh_ph ? pc : h_pc);
	wire [10:0] sh_b  = (sh_cf & (cf_mode == MODE_DT)) ? dt_hold : (sh_ph ? pidx : dt_off);
	wire [10:0] sh_d  = mod_sub(sh_a, sh_b);
	wire [10:0] d_pos = (r_dtrun & (w_half != 11'd0)) ? sh_d : 11'd0;
	wire        d_mix, d_inc, d_fp, d_cur, d_fill;
	wire [10:0] d_idx;
	wire [11:0] d_blk;
	wire  [7:0] d_cnt;

	paprium_synth_tim6 dec (
		.path(w_path), .half(w_half), .nblk(w_nblk), .blk(w_blk), .fp(w_fp), .cur(w_cur), .fill(w_fill),
		.cnt(w_cnt), .pos(d_pos),
		.mix(d_mix), .idx(d_idx), .incomplete(d_inc), .blk_o(d_blk), .fp_o(d_fp), .cur_o(d_cur), .fill_o(d_fill),
		.cnt_o(d_cnt)
	);

	// a service never shares a clock with a CONFIG / ARM / PHASE apply (the firmware writes only while BUSY = 0)
	wire        hold_svc = cfg_wr | cf_go | arm_wr | phase_idx_wr;
	wire        svc      = h_svc & ~st_run & ~hold_svc;
	wire        push     = t6 & ~(q_full & ~svc);    // dropped (and counted) only into a full queue whose head cannot be
	                                                // serviced in this clock. The queue fills only once its head has
	                                                // waited 7 TIM6 periods (14.6 ms: TIMEOUT above that and no DONE, or
	                                                // blocks that long); its head is then serviced first, so the queue is
	                                                // still full at the next push only behind a block (RUN) that spans a
	                                                // whole TIM6 period (a bench test, found when this block was repaired)
	// DIAG.TIMEOUTS (inc_timeout, one pulse a clock) counts clocks with at least one of: a dropped push, a service
	// without its DONE (on TIMEOUT, or first because the queue is full), an undated CONFIG. A service and a dropped push
	// never share a clock, and no service shares a clock with a CONFIG apply, so the only pair that can coincide (and
	// counts once) is an undated CONFIG applying in the clock of a dropped push.

	always @(posedge clk) begin
		blk_start      <= 1'b0;
		inc_incomplete <= 1'b0;
		inc_timeout    <= 1'b0;
		cf_go          <= 1'b0;

		if (reset) begin
			w_path <= 1'b0; w_half <= 11'd0; w_nblk <= 3'd0; w_blk <= 12'd0; w_fp <= 1'b0; w_cur <= 1'b0;
			w_fill <= 1'b0; w_cnt <= 8'd0;
			r_dtrun <= 1'b0; dt_off <= 11'd0; dt_hold <= 11'd0;
			q_wp <= 3'd0; q_rp <= 3'd0; q_n <= 4'd0;
			run_blk <= 1'b0; run_drain <= 1'b0;
			blk_idx <= 11'd0; blk_ym <= 1'b0;
		end
		else begin
			if (t6 & ~push) inc_timeout <= 1'b1;

			// ---- CONFIG: latch, read the stamp of arrival SEQ, then apply CONFIG's scheduler half ----
			if (cfg_wr) begin
				cf_go    <= 1'b1;
				cf_mode  <= g_mode;
				cf_pal   <= g_pal;
				cf_old   <= cf_old_n;
				cf_stamp <= cf_old_n ? pc_nx : stamp[g_cfg_seq[4:0]];   // trimmed: pc at the apply clock = pc_nx now
			end
			if (cf_go) begin
				if (cf_old) inc_timeout <= 1'b1;                     // dated at the write instead (DIAG.TIMEOUTS)
				case (cf_mode)
					MODE_DT: begin                                     // DT: HALF 960, NBLK 6, the DACs on: the index
						w_path <= 1'b0; w_half <= 11'd960; w_nblk <= 3'd6;  // resumes where it held (DT -> DT: runs on)
						w_fill <= 1'b1; w_cur <= 1'b0; w_cnt <= 8'hFF;
						r_dtrun <= 1'b1;
						if (!r_dtrun) dt_off <= sh_d;                  // (stamp or pc) - dt_hold
					end
					MODE_YM: begin                                     // YM-DAC: NTSC 800 / 5, PAL 960 / 6, the DACs off
						w_path <= 1'b1; w_half <= cf_pal ? 11'd960 : 11'd800; w_nblk <= cf_pal ? 3'd6 : 3'd5;
						w_fill <= 1'b1; w_cur <= 1'b0; w_cnt <= 8'hFF;
						r_dtrun <= 1'b0;
						if (r_dtrun) dt_hold <= sh_d;                  // (stamp or pc) - dt_off (cf_old: = live_idx)
					end
					default: begin                                     // 0 / 3: HALF 0 (TIM6 only counts), the DACs off
						w_half  <= 11'd0;
						r_dtrun <= 1'b0;
						if (r_dtrun) dt_hold <= sh_d;
					end
				endcase
			end

			// ---- ARM: FPEND := bit 0 (the cart stores 1 at the tick, 0 when a BGM module starts) ----
			if (arm_wr) w_fp <= arm_val;

			// ---- PHASE.DTIDX (TEST): the DMA index := value (values past 1,919 give 0) ----
			if (phase_idx_wr) begin
				if (r_dtrun) dt_off  <= sh_d;                          // pc - DTIDX
				else         dt_hold <= pidx;
			end

			// ---- service the head instant ----
			if (svc) begin
				q_rp <= q_rp + 3'd1;
				if (~h_doneok) inc_timeout <= 1'b1;
				w_blk <= d_blk; w_fp <= d_fp; w_cur <= d_cur; w_fill <= d_fill; w_cnt <= d_cnt;
				inc_incomplete <= d_inc;
				if (d_mix) begin
					blk_start <= 1'b1;
					blk_idx   <= d_idx;
					blk_ym    <= w_path;
					run_blk   <= 1'b1;
				end
			end

			if (push) q_wp <= q_wp + 3'd1;
			q_n <= q_n + {3'd0, push} - {3'd0, svc};

			// ---- RUN: the engine's block, then the CRAM clients drained ----
			if (run_blk & blk_done) begin run_blk <= 1'b0; run_drain <= 1'b1; end
			if (run_drain & cram_idle) run_drain <= 1'b0;
		end
	end

	always @(posedge clk) begin
		if (!reset && push) q[q_wp] <= {ck, pc_nx, arr};
	end

	// ================================================================ read-backs
	assign st_fpend   = w_fp;
	assign st_fill    = w_fill;
	assign st_cur     = w_cur;
	assign st_qdepth  = q_n;
	assign st_blkcnt  = w_blk;
	assign sc_cnt     = w_cnt;
	assign sc_nblk    = {1'b0, w_nblk};
	assign sc_half    = {5'd0, w_half};
	assign ph_dtidx   = live_idx;
	assign ph_strobes = strobes;
	assign dt_run     = r_dtrun;
	assign dt_idx     = live_idx;
	assign s_ym       = w_path;

endmodule
