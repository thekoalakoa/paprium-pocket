// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step - paprium_synth: the cart chip's per-block / per-sample audio work in logic (the
// firmware's docs/MCU_INTERFACE.md v1.3 section 3.10), region 0x06 with FEAT.SYNTH. paprium_cart instantiates it
// (parameter SYNTH) in place of the interim audio_sfx FIFOs; its CRAM clients go out to paprium_cram ports C and E in
// core_top.
//
// The synth was built in ten steps. The first (this file's first version) builds the two blocks every later one runs
// through:
//   B1  paprium_synth_if   - the MCU interface: the global registers, the voice / SFX windows (state RAM), ARR / DONE,
//                            CAUSE.BLK;
//   B10 paprium_synth_cram - the CRAM clients on ports C and E (one operation at a time per port, the DT playback read
//                            first).
//
// The second step adds B2 paprium_synth_sched (the TIM8 / TIM6 timebase, the DT DMA index, the chip's block decision
// once per TIM6 instant, the arrival-order hold-off, BUSY / RUN / CAUSE.BLK).
//
// The ninth step adds B9 paprium_synth_dtplay (the DT playback: dac_buf_L / R at B2's index on every TIM8 strobe in DT,
// the DAC's 12-bit code, the DTOUT stand-in, DIAG.UNDERRUN) on E client 0; dt_l / dt_r are its output.
//
// The tenth step (the integration) wires the block engine that B2's blk_start runs, in the order the cart mixes a
// block (we reverse engineered the STM32F4's commands as close as possible, with hardware verification). Every mixed
// block runs these steps, one after another:
//   1. B3 paprium_synth_env      the wave envelope (and the stopped-mode decay);
//   2. B7 phase 0 (P1)           the BGM bus zeroed, or prefilled from the BGM ring;
//   3. B5 paprium_synth_wave     the 16 wave voices, each through B4 paprium_synth_gain for its two gains;
//   4. B7 phase 1 (P2)           the BGM ring write and ECHOB.INDEX + 1;
//   5. B7 phase 2 (P3)           the SFX section: the SFX bus zeroed or prefilled; B4 copies the section's store to its
//                                held boost word here (sfx_sect);
//   6. B6 paprium_synth_sfx      the 8 SFX channels;
//   7. B7 phase 3 (P4)           the SFX ring write and ECHOS.INDEX + 1;
//   8. B8 paprium_synth_out      the output stage: the YM filter pair or the DT curve, dac_buf at the block's index;
//                                its done is the block's end (blk_done), and B2 then holds RUN until B10 is idle.
// Each step starts in the clock after the one before it is done, so the steps never overlap: B3 / B5 / B6 share B1's
// one state-RAM port, B5 / B6 / B7 / B8 the BUS RAM (paprium_synth_bus: BGM frame f at word f, SFX frame i at word
// 160 + i, the layout all four blocks take), and the order B10 needs holds by construction (P2's ring writes are
// raised after B5's done, which follows its last sample read: the cart's wave over-read past the bank end reads
// BGMRING block 0 before the block rewrites it). B4's level table T[0..511] is port A of paprium_synth_trom, the
// TABLES ROM (one M10K, 512 x 20, after two logic-saving trims), whose port B holds B6's sample-expansion tables
// (sfx8 / sfx4); B4's own mono result (o_mono / o_g) is not used: B5 makes the same test itself (the contracts of the
// third and fourth steps). The blocks' logic-owned globals go back to B1: ECHOB / ECHOS INDEX from B7, YMFILT from B8
// (the clock before B8's done). Blocks are atomic (the firmware's docs/ALLOWLIST.md, row B40): the firmware writes a
// window or a global only between synth_begin and synth_end (MCU_INTERFACE.md v1.3 3.10.5), and B2 starts a block only
// while RUN = 0. The main-loop pass (a project decision): B2 moves STATUS.BLKCNT in the very clock it starts a block
// (RUN = 1 from that clock until the block's writes are done, BUSY = 1 in the service clock too), so a pass that reads
// STATUS, the 16 ENV_LEVEL words, then STATUS again and retries when BUSY = 1 or BLKCNT moved sees one whole block or
// none.

module paprium_synth #(
	parameter integer CLK_HZ = 0                 // clk in Hz, from core_top through paprium_cart
)(
	input             clk,
	input             reset,                       // sys_reset

	// MCU (region 0x06)
	input             m_req,
	input      [11:0] m_addr,
	input       [3:0] m_we,
	input      [31:0] m_wdata,
	output     [31:0] m_rdata,
	output            m_ack,
	input             post_b,                      // the 68000's $1FEA write (CAUSE.B's pulse)
	input             post_a,                      // the 68000's $1FEC write (CAUSE.A's pulse)
	output            post_blk,                    // -> fpgio CAUSE.BLK
	input             freeze,                      // the Pocket menu is open and CTRL.MENU_MUTE_EN (3.10.6)

	// the DT output (B9)
	output signed [15:0] dt_l,
	output signed [15:0] dt_r,

	// paprium_cram port C (stream reads) and port E
	output            c_rd,
	output     [20:0] c_raddr,
	input             c_rd_done,
	input      [15:0] c_rdata,
	output            e_wr,
	output     [21:0] e_waddr,
	output            e_wpair,
	output     [31:0] e_wdata,
	output            e_rd,
	output     [21:0] e_raddr,
	output            e_rpair,
	input             e_rd_done,
	input      [31:0] e_rdata,
	input             e_wbusy
);
	import paprium_synth_pkg::*;

	// ---- B1
	wire [15:0] arr, g_done, g_cfg_seq, g_wm_l, g_wm_r, g_boost, g_wavemaster, g_sm_l, g_sm_r, g_sfxmaster;
	wire [15:0] g_echob_gain, g_echos_gain, g_ymf_a, g_ymf_b;
	wire  [7:0] g_echob_delay, g_echob_index, g_echos_delay, g_echos_index;
	wire  [1:0] arr_inc, g_mode;
	wire        cfg_wr, g_pal, g_dtwin, arm_wr, arm_val, phase_idx_wr, phase_restart;
	wire [10:0] phase_idx;
	wire [23:0] g_timeout;
	wire  [5:0] g_flags;
	wire [20:0] g_dtout;
	wire        e_rgnt, e_wgnt;
	wire [31:0] s_rdata;
	// B2's read-backs and its engine / playback side
	wire        st_busy, st_run, st_fpend, st_fill, st_cur, inc_incomplete, inc_timeout;
	wire  [3:0] st_qdepth, sc_nblk;
	wire [11:0] st_blkcnt;
	wire  [7:0] sc_cnt;
	wire [15:0] sc_half;
	wire [10:0] ph_dtidx, blk_idx, dt_idx;
	wire  [6:0] ph_strobes;
	wire        blk_start, blk_ym, tim8, dt_run, s_ym, cram_idle;
	wire        blk_done;
	// B9's E client 0
	wire        b9_req, b9_underrun;
	wire [21:0] b9_addr;
	// the engine's state-RAM port (B3 / B5 / B6, one at a time)
	wire        s_rreq, s_wreq;
	wire  [7:0] s_raddr, s_waddr;
	wire  [3:0] s_wbe;
	wire [31:0] s_wdata;
	// the logic-owned globals (B7, B8)
	wire        echob_idx_we, echos_idx_we, ymf_we;
	wire  [7:0] echob_idx, echos_idx;
	wire [15:0] ymf_a_o, ymf_b_o;

	paprium_synth_if #(.CLK_HZ(CLK_HZ)) b1 (
		.clk(clk), .reset(reset),
		.m_req(m_req), .m_addr(m_addr), .m_we(m_we), .m_wdata(m_wdata), .m_rdata(m_rdata), .m_ack(m_ack),
		.post_b(post_b), .post_a(post_a), .arr(arr), .arr_inc(arr_inc),
		.cfg_wr(cfg_wr), .g_mode(g_mode), .g_pal(g_pal), .g_dtwin(g_dtwin), .g_cfg_seq(g_cfg_seq), .arm_wr(arm_wr),
		.arm_val(arm_val), .phase_idx_wr(phase_idx_wr), .phase_idx(phase_idx), .phase_restart(phase_restart),
		.g_done(g_done), .g_timeout(g_timeout),
		// the scheduler's read-backs (B2)
		.st_busy(st_busy), .st_run(st_run), .st_fpend(st_fpend), .st_fill(st_fill), .st_cur(st_cur),
		.st_qdepth(st_qdepth), .st_blkcnt(st_blkcnt), .sc_cnt(sc_cnt), .sc_nblk(sc_nblk), .sc_half(sc_half),
		.ph_dtidx(ph_dtidx), .ph_strobes(ph_strobes),
		.inc_incomplete(inc_incomplete), .inc_timeout(inc_timeout), .inc_underrun(b9_underrun), .post_blk(post_blk),
		.g_flags(g_flags), .g_wm_l(g_wm_l), .g_wm_r(g_wm_r), .g_boost(g_boost), .g_wavemaster(g_wavemaster),
		.g_sm_l(g_sm_l), .g_sm_r(g_sm_r), .g_sfxmaster(g_sfxmaster), .g_echob_gain(g_echob_gain),
		.g_echob_delay(g_echob_delay), .g_echob_index(g_echob_index), .g_echos_gain(g_echos_gain),
		.g_echos_delay(g_echos_delay), .g_echos_index(g_echos_index), .g_ymf_a(g_ymf_a), .g_ymf_b(g_ymf_b),
		.g_dtout(g_dtout),
		// the logic-owned globals (B7 / B8)
		.e_echob_idx_we(echob_idx_we), .e_echob_idx(echob_idx), .e_echos_idx_we(echos_idx_we), .e_echos_idx(echos_idx),
		.e_ymf_we(ymf_we), .e_ymf_a(ymf_a_o), .e_ymf_b(ymf_b_o),
		// the state RAM's synth port (B3 / B5 / B6)
		.e_rreq(s_rreq), .e_raddr(s_raddr), .e_rgnt(e_rgnt), .e_rdata(s_rdata),
		.e_wreq(s_wreq), .e_waddr(s_waddr), .e_wbe(s_wbe), .e_wdata(s_wdata), .e_wgnt(e_wgnt)
	);

	// ---- B2: the timebase and the block scheduler

	paprium_synth_sched #(.CLK_HZ(CLK_HZ)) b2 (
		.clk(clk), .reset(reset), .freeze(freeze),
		.arr(arr), .arr_inc(arr_inc), .cfg_wr(cfg_wr), .g_mode(g_mode), .g_pal(g_pal), .g_cfg_seq(g_cfg_seq),
		.arm_wr(arm_wr), .arm_val(arm_val), .phase_idx_wr(phase_idx_wr), .phase_idx(phase_idx),
		.phase_restart(phase_restart), .g_done(g_done), .g_timeout(g_timeout),
		.st_busy(st_busy), .st_run(st_run), .st_fpend(st_fpend), .st_fill(st_fill), .st_cur(st_cur),
		.st_qdepth(st_qdepth), .st_blkcnt(st_blkcnt), .sc_cnt(sc_cnt), .sc_nblk(sc_nblk), .sc_half(sc_half),
		.ph_dtidx(ph_dtidx), .ph_strobes(ph_strobes), .inc_incomplete(inc_incomplete), .inc_timeout(inc_timeout),
		.blk_start(blk_start), .blk_idx(blk_idx), .blk_ym(blk_ym), .blk_done(blk_done), .cram_idle(cram_idle),
		.tim8(tim8), .dt_run(dt_run), .dt_idx(dt_idx), .s_ym(s_ym)
	);

	// ---- the block engine: the steps of a block in the cart's order, one at a time (header)
	localparam [3:0] E_IDLE = 4'd0, E_ENV = 4'd1, E_P1 = 4'd2, E_WAVE = 4'd3, E_P2 = 4'd4, E_P3 = 4'd5,
	                 E_SFX = 4'd6, E_P4 = 4'd7, E_OUT = 4'd8;
	reg   [3:0] es = E_IDLE;
	reg  [10:0] r_idx;
	reg         r_ym;
	reg         env_start, wave_start, sfx_start, echo_start, out_start, sfx_sect;
	reg   [1:0] echo_phase;
	wire        env_done, wave_done, sfx_done, echo_done, out_done;

	always @(posedge clk) begin
		env_start  <= 1'b0;
		wave_start <= 1'b0;
		sfx_start  <= 1'b0;
		echo_start <= 1'b0;
		out_start  <= 1'b0;
		sfx_sect   <= 1'b0;
		if (reset) es <= E_IDLE;
		else case (es)
			E_IDLE: if (blk_start) begin r_idx <= blk_idx; r_ym <= blk_ym; env_start <= 1'b1; es <= E_ENV; end
			E_ENV:  if (env_done)  begin echo_start <= 1'b1; echo_phase <= 2'd0; es <= E_P1; end
			E_P1:   if (echo_done) begin wave_start <= 1'b1; es <= E_WAVE; end
			E_WAVE: if (wave_done) begin echo_start <= 1'b1; echo_phase <= 2'd1; es <= E_P2; end
			E_P2:   if (echo_done) begin echo_start <= 1'b1; echo_phase <= 2'd2; sfx_sect <= 1'b1; es <= E_P3; end
			E_P3:   if (echo_done) begin sfx_start <= 1'b1; es <= E_SFX; end
			E_SFX:  if (sfx_done)  begin echo_start <= 1'b1; echo_phase <= 2'd3; es <= E_P4; end
			E_P4:   if (echo_done) begin out_start <= 1'b1; es <= E_OUT; end
			E_OUT:  if (out_done)  es <= E_IDLE;
			default: es <= E_IDLE;
		endcase
	end
	assign blk_done = (es == E_OUT) & out_done;

	wire use_env  = (es == E_ENV);
	wire use_wave = (es == E_WAVE);
	wire use_sfx  = (es == E_SFX);
	wire use_echo = (es == E_P1) | (es == E_P2) | (es == E_P3) | (es == E_P4);
	wire use_out  = (es == E_OUT);

	// the state-RAM port: the running step's requests only
	wire        b3_rreq, b3_wreq, b5_rreq, b5_wreq, b6_rreq, b6_wreq;
	wire  [7:0] b3_raddr, b3_waddr, b5_raddr, b5_waddr, b6_raddr, b6_waddr;
	wire  [3:0] b3_wbe, b5_wbe, b6_wbe;
	wire [31:0] b3_wdata, b5_wdata, b6_wdata;
	assign s_rreq  = (use_env & b3_rreq) | (use_wave & b5_rreq) | (use_sfx & b6_rreq);
	assign s_raddr = use_env ? b3_raddr : use_wave ? b5_raddr : b6_raddr;
	assign s_wreq  = (use_env & b3_wreq) | (use_wave & b5_wreq) | (use_sfx & b6_wreq);
	assign s_waddr = use_env ? b3_waddr : use_wave ? b5_waddr : b6_waddr;
	assign s_wbe   = use_env ? b3_wbe   : use_wave ? b5_wbe   : b6_wbe;
	assign s_wdata = use_env ? b3_wdata : use_wave ? b5_wdata : b6_wdata;

	// the BUS RAM: B5 reads / writes it directly (a registered read, its writes two clocks after the read); B6 / B7 /
	// B8 through request / grant, granted in the clock they ask while their step runs
	wire        b5_bre, b5_bwe, b6_brq, b6_bwq, b7_brq, b7_bwq, b8_brq;
	wire  [7:0] b5_bra, b5_bwa, b6_bra, b6_bwa, b7_bra, b7_bwa, b8_bra;
	wire [31:0] b5_bwd, b6_bwd, b7_bwd, bus_rd;
	wire        bus_we = (use_wave & b5_bwe) | (use_sfx & b6_bwq) | (use_echo & b7_bwq);
	wire  [7:0] bus_wa = use_wave ? b5_bwa : use_sfx ? b6_bwa : b7_bwa;
	wire [31:0] bus_wd = use_wave ? b5_bwd : use_sfx ? b6_bwd : b7_bwd;
	wire  [7:0] bus_ra = use_wave ? b5_bra : use_sfx ? b6_bra : use_echo ? b7_bra : b8_bra;
	wire        b5_bre_u = b5_bre;                 // B5 reads every clock it asks; the RAM reads every clock anyway

	paprium_synth_bus bus (.clk(clk), .we(bus_we), .wa(bus_wa), .wd(bus_wd), .ra(bus_ra), .rd(bus_rd));

	// ---- B3: the wave envelope
	paprium_synth_env b3_env (
		.clk(clk), .reset(reset), .start(env_start), .seqon(g_flags[FL_SEQON]), .playing(g_flags[FL_PLAYING]),
		.busy(), .done(env_done),
		.rreq(b3_rreq), .raddr(b3_raddr), .rgnt(use_env & e_rgnt), .rdata(s_rdata),
		.wreq(b3_wreq), .waddr(b3_waddr), .wbe(b3_wbe), .wdata(b3_wdata), .wgnt(use_env & e_wgnt)
	);

	// ---- B4 + its level table: one voice's gains for B5 (v_start = the rising edge of B5's g_req)
	wire        g_req, g_ack, t_rd;
	wire  [3:0] g_voice;
	wire [15:0] g_level, g_gain_l, g_gain_r, g_l, g_r;
	wire  [7:0] g_bb, g_compand;
	wire  [8:0] t_addr, t_data;
	reg         g_req_q = 1'b0;
	always @(posedge clk) g_req_q <= ~reset & g_req;
	wire        v_start = g_req & ~g_req_q;

	paprium_synth_gain b4 (
		.clk(clk), .reset(reset),
		.g_flags(g_flags), .g_wm_l(g_wm_l), .g_wm_r(g_wm_r), .g_boost(g_boost), .g_wavemaster(g_wavemaster),
		.s_ym(s_ym),
		.v_start(v_start), .v_level(g_level), .v_gain_l(g_gain_l), .v_gain_r(g_gain_r), .v_bb(g_bb),
		.v_done(g_ack), .o_gl(g_l), .o_gr(g_r), .o_mono(), .o_g(), .o_m(),
		.sfx_sect(sfx_sect),
		.t_rd(t_rd), .t_addr(t_addr), .t_data(t_data),
		.busy(), .o_slot()
	);
	wire  [8:0] b6_sa;                             // B6's sample-table address (TABLES ROM port B)
	wire signed [10:0] b6_sq;
	paprium_synth_trom trom (.clk(clk), .rd(t_rd), .addr(t_addr), .q(t_data), .sa(b6_sa), .sq(b6_sq));

	// ---- B10: C clients 0 wave samples (B5), 1 SFX words (B6), 2 the curve (B8); E clients 0 DT playback (B9),
	// 1 ring reads (B7), 2 ring writes (B7), 3 dac_buf writes (B8)
	wire  [2:0] cq_gnt, cq_done;
	wire  [3:0] eq_gnt, eq_done;
	wire [15:0] c_data;
	wire  [7:0] c_byte;
	wire [31:0] e_data;
	wire        b5_cq, b6_cq, b8_cq, b7_rq, b7_wq, b8_eq;
	wire [21:0] b5_cqa, b6_cqa, b8_cqa, b7_rqa, b7_wqa, b8_eqa;
	wire [31:0] b7_wqd, b8_eqd;

	paprium_synth_cram #(.NC(3), .NE(4)) b10 (
		.clk(clk), .reset(reset),
		.cq_req({b8_cq, b6_cq, b5_cq}), .cq_addr({b8_cqa, b6_cqa, b5_cqa}), .cq_gnt(cq_gnt), .cq_done(cq_done),
		.c_data(c_data), .c_byte(c_byte),
		.eq_req({b8_eq, b7_wq, b7_rq, b9_req}), .eq_we(4'b1100), .eq_pair(4'b1110),
		.eq_addr({b8_eqa, b7_wqa, b7_rqa, b9_addr}), .eq_wdata({b8_eqd, b7_wqd, 32'd0, 32'd0}),
		.eq_gnt(eq_gnt), .eq_done(eq_done), .e_data(e_data), .idle(cram_idle),
		.c_rd(c_rd), .c_raddr(c_raddr), .c_rd_done(c_rd_done), .c_rdata(c_rdata),
		.e_wr(e_wr), .e_waddr(e_waddr), .e_wpair(e_wpair), .e_wdata(e_wdata), .e_rd(e_rd), .e_raddr(e_raddr),
		.e_rpair(e_rpair), .e_rd_done(e_rd_done), .e_rdata(e_rdata), .e_wbusy(e_wbusy)
	);

	// ---- B5: the 16 wave voices
	paprium_synth_wave b5 (
		.clk(clk), .reset(reset), .start(wave_start), .en(g_flags[FL_SEQON] & g_flags[FL_PLAYING]), .ym(r_ym),
		.done(wave_done), .busy(),
		.e_rreq(b5_rreq), .e_raddr(b5_raddr), .e_rgnt(use_wave & e_rgnt), .e_rdata(s_rdata),
		.e_wreq(b5_wreq), .e_waddr(b5_waddr), .e_wbe(b5_wbe), .e_wdata(b5_wdata), .e_wgnt(use_wave & e_wgnt),
		.g_req(g_req), .g_voice(g_voice), .g_level(g_level), .g_gain_l(g_gain_l), .g_gain_r(g_gain_r), .g_bb(g_bb),
		.g_compand(g_compand), .g_ack(g_ack), .g_l(g_l), .g_r(g_r),
		.cq_req(b5_cq), .cq_addr(b5_cqa), .cq_gnt(cq_gnt[0]), .cq_done(cq_done[0]), .c_data(c_data),
		.bus_re(b5_bre), .bus_ra(b5_bra), .bus_rd(bus_rd), .bus_we(b5_bwe), .bus_wa(b5_bwa), .bus_wd(b5_bwd)
	);

	// ---- B7: the echo rings (P1-P4)
	paprium_synth_echo #(.BUS_BGM(8'd0), .BUS_SFX(8'd160)) b7 (
		.clk(clk), .reset(reset), .start(echo_start), .phase(echo_phase), .ym(r_ym), .done(echo_done), .busy(),
		.g_flags(g_flags), .g_echob_gain(g_echob_gain), .g_echob_delay(g_echob_delay), .g_echob_index(g_echob_index),
		.g_echos_gain(g_echos_gain), .g_echos_delay(g_echos_delay), .g_echos_index(g_echos_index),
		.e_echob_idx_we(echob_idx_we), .e_echob_idx(echob_idx), .e_echos_idx_we(echos_idx_we), .e_echos_idx(echos_idx),
		.b_rreq(b7_brq), .b_raddr(b7_bra), .b_rgnt(use_echo & b7_brq), .b_rdata(bus_rd),
		.b_wreq(b7_bwq), .b_waddr(b7_bwa), .b_wdata(b7_bwd), .b_wgnt(use_echo & b7_bwq),
		.rq_req(b7_rq), .rq_addr(b7_rqa), .rq_gnt(eq_gnt[1]), .rq_done(eq_done[1]), .e_data(e_data),
		.wq_req(b7_wq), .wq_addr(b7_wqa), .wq_wdata(b7_wqd), .wq_gnt(eq_gnt[2])
	);

	// ---- B6: the 8 SFX channels
	paprium_synth_sfx #(.BUS_SFX(8'd160)) b6 (
		.clk(clk), .reset(reset), .start(sfx_start), .done(sfx_done), .busy(), .sfx_on(g_flags[FL_SFXON]), .ym(s_ym),
		.g_sm_l(g_sm_l), .g_sm_r(g_sm_r), .g_sfxmaster(g_sfxmaster),
		.e_rreq(b6_rreq), .e_raddr(b6_raddr), .e_rgnt(use_sfx & e_rgnt), .e_rdata(s_rdata),
		.e_wreq(b6_wreq), .e_waddr(b6_waddr), .e_wbe(b6_wbe), .e_wdata(b6_wdata), .e_wgnt(use_sfx & e_wgnt),
		.cq_req(b6_cq), .cq_addr(b6_cqa), .cq_gnt(cq_gnt[1]), .cq_done(cq_done[1]), .c_data(c_data),
		.b_rreq(b6_brq), .b_raddr(b6_bra), .b_rgnt(use_sfx & b6_brq), .b_rdata(bus_rd),
		.b_wreq(b6_bwq), .b_waddr(b6_bwa), .b_wdata(b6_bwd), .b_wgnt(use_sfx & b6_bwq),
		.rom_sa(b6_sa), .rom_q(b6_sq)
	);

	// ---- B8: the output stage
	paprium_synth_out #(.BUS_BGM(8'd0), .BUS_SFX(8'd160)) b8 (
		.clk(clk), .reset(reset), .start(out_start), .idx(r_idx), .ym(r_ym), .dtwin(g_dtwin), .ymf_a(g_ymf_a),
		.ymf_b(g_ymf_b), .busy(), .done(out_done),
		.ymf_we(ymf_we), .ymf_a_o(ymf_a_o), .ymf_b_o(ymf_b_o),
		.b_rreq(b8_brq), .b_raddr(b8_bra), .b_rgnt(use_out & b8_brq), .b_rdata(bus_rd),
		.cq_req(b8_cq), .cq_addr(b8_cqa), .cq_gnt(cq_gnt[2]), .cq_done(cq_done[2]), .c_data(c_data),
		.eq_req(b8_eq), .eq_addr(b8_eqa), .eq_wdata(b8_eqd), .eq_gnt(eq_gnt[3])
	);

	// ---- B9: the DT playback ----
	paprium_synth_dtplay b9 (
		.clk(clk), .reset(reset), .freeze(freeze),
		.tim8(tim8), .dt_run(dt_run), .dt_idx(dt_idx), .g_dtout(g_dtout),
		.q_req(b9_req), .q_addr(b9_addr), .q_gnt(eq_gnt[0]), .q_done(eq_done[0]), .q_data(e_data),
		.dt_l(dt_l), .dt_r(dt_r), .inc_underrun(b9_underrun),
		.o_play(), .o_play_idx(), .o_code_l(), .o_code_r(), .o_late(), .o_lost()
	);

	wire unused_ok = &{1'b0, c_byte, g_voice, g_compand, b5_bre_u, eq_done[3:2]};

endmodule
