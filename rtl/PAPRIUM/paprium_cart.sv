// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)
// pocket: words used in the pocket comments of this file. "new core" = the first step of the 0.3.0 work, which built
// the new cart register file and MCU interface v1.0 (the firmware's docs/STAGE1_PLAN.md); "sprite decoder" = the cart
// FPGA's sprite decoder (paprium_hwdec), added in that step; "synth step" = the 0.3.0 step that moved the cart chip's
// audio work into logic (paprium_synth). "Test build N" = a 0.3.0 hardware test build that B Jam ran on the Pocket:
// 4 = the MCU fast path, 4a = the first sound-cache build, 5 = the synth build, S3c = a test build of the MegaWire
// step. "xram step 1 / 2" = the two steps of our Pocket SRAM / CRAM work (paprium_xlink.sv). FPGAIO = the MCU's
// register block in the FPGA (fpgio.sv); RAMDP = the cart RAM that both the 68000 and the MCU see; MCU_INTERFACE /
// MCU interface vN = the firmware's docs/MCU_INTERFACE.md.
module paprium_cart
#(parameter SFX = 1'b1, parameter CMDLOG = 1'b0,
  parameter SYNTH = 1'b0,          // pocket: synth step - region 0x06 is the synth (paprium_synth, FEAT.SYNTH) instead of audio_sfx
  parameter integer CLK_HZ = 0,   // pocket: new core - clk's frequency in Hz, from core_top
  parameter [31:0] FEAT = 32'd0)  // pocket: synth step (MCU interface v1.3) - FPGAIO FEAT (slot 23), from core_top
(
	input             clk,
	input             reset,
	input             enable,

	input      [23:1] cart_addr,
	input      [15:0] cart_data_wr,
	input             cart_cs,
	input             cart_oe,
	input             cart_lwr,
	input             cart_uwr,
	input             cart_time,
	input             stream_read_ack_toggle, // legacy clk_ram ack; stream pointer follows 68k read cadence

	output     [15:0] cart_data,
	output            mailbox_cs,
	output            stream_cs,
	output     [24:1] stream_addr,
	output            md_reset,
	output            mini_view,   // pocket: new core - the 84 view switch (paprium_regfile), this clock; cartridge.sv synchronises it
	output            opt_at_reset_en,   // new core: fpgio CTRL bit 5 (this clock), the dormant option latch
	input             console_reset,     // pocket: test build S3c - core_top's Console Reset, a one-clock pulse: sets CAUSE.V
	output            cause_v,           // pocket: test build S3c - CAUSE.V pending (this clock): core_top holds the 68000 meanwhile

	// MD+ adapter: Paprium MCU BGM requests -> core's native MD+ engine
	output            mdp_track_request,
	output      [7:0] mdp_track_num,
	output            mdp_track_loop,
	output            mdp_stop_request,
	output      [7:0] mdp_fade_sectors,
	output            mdp_resume_request,
	output      [7:0] mdp_volume,
	output            mdp_volume_request,
	output            mdp_active,
	input             mdp_playing,
	input       [7:0] mdp_current_track,

	// Paprium MCU-driven cart SFX PCM engine
	output signed [15:0] sfx_l,
	output signed [15:0] sfx_r,
	// pocket: new core, the Pocket-menu music mute - FPGAIO CTRL bit 4 (MENU_MUTE_EN), this clock; core_top pauses the
	// album and zeroes sfx_l/sfx_r while the Pocket menu is open and this bit is set
	output            menu_mute_en,

	// MCU -> RAMDP debug taps
	output            dbg_ramdp_write,
	output     [10:0] dbg_ramdp_addr,
	output     [31:0] dbg_ramdp_data,

	// paprium: mailbox command log read-back (diagnostic builds only)
	input      [13:0] cmdlog_read_addr,
	output      [7:0] cmdlog_read_data,

	// Paprium battery-backup save RAM (HPS cartridge save interface)
	input      [14:0] save_addr,
	input      [15:0] save_di,
	output     [15:0] save_do,
	input             save_wr,
	output            save_change,

	output     [24:1] mem_addr,
	output     [15:0] mem_din,
	input      [15:0] mem_dout,
	output            mem_wrl,
	output            mem_wrh,
	output            mem_req,
	input             mem_ack,

	// pocket: xram step 1 - the MCU's windows on the Pocket SRAM (0x08), CRAM (0x09) and
	// their register block (0x0A). Served in core_top on this clock (no crossing); the ack
	// is held until the request drops, like paprium_mcu_mem's
	output            xb_req,
	output      [1:0] xb_region,     // 0 SRAM, 1 CRAM, 2 registers
	output     [23:0] xb_addr,
	output      [3:0] xb_sel,
	output            xb_wr,
	output     [31:0] xb_wdata,
	input      [31:0] xb_rdata,
	input             xb_ack,

	// pocket: 0.2.6 - OSD options for the firmware: {MegaWire, $1FE4 bit 10, 9, 8, 6}; new core:
	// {PAL build, Console region is Japan, Pocket menu open, MegaWire, $1FE4 bit 10, 9, 8, 6}
	input       [7:0] mcu_opts,

	// pocket: xram step 2 - option-D status (paprium_xlink LSTAT[7:0] less 'armed'); read back
	// with the mailbox interrupt latch in the FPGAIO ctrl word [15:8]
	input       [6:0] link_status,
	// pocket: new core - bit 0 of XLINK's synchronised buddy post count (posts_s[0], this clock): every
	// change is one post, FPGAIO CAUSE.S
	input             link_post,
	// pocket: new core (MCU interface v1.1) - core_top's paprium_vs_tap, this clock: flips once per VDP vertical sync,
	// FPGAIO VSCNT (slot 16)
	input             vs_tog,

	// pocket: the SFX echo line's CRAM port (paprium_cram port E in core_top, this clock)
	input             echo_ready,
	output            echo_wr,
	output     [12:0] echo_wslot,
	output     [31:0] echo_wdata,
	output            echo_rd,
	output     [12:0] echo_rslot,
	input             echo_rd_done,
	input      [31:0] echo_rdata,

	// pocket: synth step (SYNTH) - the synth's CRAM clients on paprium_cram ports C and E (core_top, this clock); 0 /
	// unused without it
	output            syn_c_rd,
	output     [20:0] syn_c_raddr,
	input             syn_c_rd_done,
	input      [15:0] syn_c_rdata,
	output            syn_e_wr,
	output     [21:0] syn_e_waddr,
	output            syn_e_wpair,
	output     [31:0] syn_e_wdata,
	output            syn_e_rd,
	output     [21:0] syn_e_raddr,
	output            syn_e_rpair,
	input             syn_e_rd_done,
	input      [31:0] syn_e_rdata,
	input             syn_e_wbusy,
	output            fw_go,         // Fafrium: the boot stub's GO (mcu_core, a power-on flag) -> core_top
	input             fw_done        // Fafrium: core_top's power-on flag (the cart reset after GO seen): boot view off
);

	McuBus mcu;
	CpuBus cpu;

	assign cpu.dato = cart_data_wr;
	assign cpu.addr = {cart_addr, 1'b0};
	assign cpu.as = cart_cs;
	assign cpu.oe = cart_oe;
	assign cpu.we_hi = cart_uwr;
	assign cpu.we_lo = cart_lwr;
	assign cpu.ce_hi = 0;
	assign cpu.ce_lo = enable & cart_cs;
	assign cpu.tim = enable & cart_time;
	assign cpu.vclk = 0;
	assign cpu.map.ramdp = cpu.ce_lo & (cpu.addr < 24'h002000);
	assign cpu.map.sdram = 0;
	assign cpu.map.flash = 0;

	assign mailbox_cs = cpu.map.ramdp;
	// Paprium's decompression streaming window is BYTE 0xC000-0xFFFF. Here cpu.addr
	// is a byte address ({cart_addr,1'b0}), so byte 0xC000-0xFFFF == cpu.addr[23:14]==3.
	// (The MegaCD core used cpu.addr[23:13]==3, but there cpu.addr was a WORD address;
	// porting that expression verbatim wrongly selected byte 0x6000-0x7FFF, redirecting
	// real flash reads to the empty workspace -> garbage/crash once flash is touched.)
	// pocket: new core - the window follows the register file ($1FE8 / $1FEE: window_en & ~mini_view), not ctrl[2]
	assign stream_cs = enable & cart_cs & cart_oe & reg_stream_win &
	                   (cpu.addr[23:14] == 10'd3);

	// Advance the stream pointer once per DELIVERED word, not per raw bus strobe.
	// stream_read_ack_toggle flips exactly once per completed stream SDRAM read
	// (cartridge.sv: paprium_stream_read_ack). The cycle-accurate VDP can glitch
	// cart_cs/cart_oe within one DMA word; keying off the combinational stream_cs
	// falling edge double-counted those glitches and desynced the stream (-> tile
	// pixel noise while resident font/UI stayed clean). This matches mega-ppm's
	// sdram_io.sv, which increments on a registered read-completion.
	reg [20:0] stream_ptr;
	reg        stream_ack_d = 0;
	wire       fpgio_sptr_wr;   // pocket: new core - FPGAIO slot 2 written (first bus clock only)
	wire       dec_sptr_load;   // pocket: sprite decoder - paprium_hwdec's START: the window points at the decoder's base
	wire [20:0] dec_sptr_val;
	always @(posedge clk) begin
		stream_ack_d <= stream_read_ack_toggle;

		if(reset) begin
			stream_ptr <= 0;
			stream_ack_d <= 0;
		end
		else if(fpgio_sptr_wr)   // pocket: new core - FPGAIO slot 2, once per store (the slot acks in 2 clocks)
			stream_ptr <= mcu.dato[20:0];
		else if(dec_sptr_load)   // pocket: sprite decoder - a firmware SPTR write wins a same-clock decoder load
			stream_ptr <= dec_sptr_val;
		else if(stream_read_ack_toggle != stream_ack_d)
			stream_ptr <= stream_ptr + 2'd2;
	end

	assign stream_addr = 24'h400000 + {{4{1'b0}}, stream_ptr[20:1]};
	wire word_delivered = stream_read_ack_toggle != stream_ack_d;   // pocket: new core - the pointer's step, for remaining

	wire [31:0] mcu_dati_fpgio;
	wire [31:0] mcu_dati_ramdp;
	wire [31:0] mcu_dati_mem;
	wire [31:0] mcu_dati_sfx;
	wire [31:0] mcu_dati_bram;
	wire [15:0] cpu_dati_ramdp;
	wire mcu_ack_mem;
	wire mcu_ack_bram;
	wire mcu_ack_ramdp;   // pocket: test build 4 - RAMDP's registered ack (was the constant 1)
	// pocket: new core - FPGAIO v1.0: registered ack, the three IRQ lines, the WRAM lock mask. ctrl[2] (0.2.6's
	// sdram_en) no longer opens the window (the register file's window does), so its wire is gone
	wire mcu_ack_fpgio;
	wire irq_ext, irq_tmr, irq_sw;
	wire [20:0] wlock;
	// pocket: new core - the cart register file (paprium_regfile)
	wire [31:0] mcu_dati_regs;
	wire        mcu_ack_regs;
	wire        mcu_ack_sfx;     // pocket: synth step - the synth's registered ack (SYNTH); 1 (at once) for the interim FIFOs
	wire        syn_post_blk;    // pocket: synth step - the synth's BUSY fell (FPGAIO CAUSE.BLK); 0 without it
	wire [15:0] reg_cpu_dati;
	wire        reg_cpu_page;
	wire        reg_stream_win;
	wire        cpu_we_strobe;
	wire        reg_post_a;          // a 68000 write to $1FEC: mailbox A (FPGAIO CAUSE.A)
	wire        reg_post_b;          // a 68000 write to $1FEA: mailbox B (FPGAIO CAUSE.B, STAMP_B)
	wire [31:0] reg_stream_status;   // {valid, 10'd0, remaining}: the STREAM_GO read-back (FPGAIO slot 7)
	// pocket: sprite decoder - the cart FPGA's decoder (paprium_hwdec)
	wire        dec_f2, dec_f4, dec_f6;
	wire [15:0] dec_f2_v, dec_f4_v, dec_f6_v;
	wire        dec_go;
	wire [20:0] dec_go_len;
	wire        fio_dec_wr;
	wire  [2:0] fio_dec_wslot, fio_dec_rslot;
	wire [31:0] fio_dec_rdata;
	wire        p2d_valid, p2d_we, p2d_take, p2d_flush, p2d_rd_done, p2d_wr_done, p2d_busy;
	wire  [1:0] p2d_lanes;
	wire [24:1] p2d_addr;
	wire [15:0] p2d_wdata, p2d_rdata;

	wire [31:0] mcu_dati =
		mcu.map.fpgio ? mcu_dati_fpgio :
		mcu.map.ramdp ? mcu_dati_ramdp :
		mcu.map.regs  ? mcu_dati_regs :   // pocket: new core
		(mcu.map.flash | mcu.map.sdram) ? mcu_dati_mem :
		mcu.map.bram  ? mcu_dati_bram :
		// pocket: synth step (test build 5) - region 0x07 (the MD+ block) is gone: unassigned, it reads 0xFFFF_FFFF (FEAT.MDP
		// = 0)
		mcu.map.sfx   ? mcu_dati_sfx :
		(mcu.map.xram | mcu.map.xcram | mcu.map.xlink) ? xb_rdata :   // pocket: xram step 1
		32'hffffffff;

	wire mcu_ack =
		mcu.map.fpgio                   ? mcu_ack_fpgio :   // pocket: new core - registered ack
		mcu.map.ramdp                   ? mcu_ack_ramdp :   // pocket: test build 4 - registered ack (ramdp_io)
		(mcu.map.flash | mcu.map.sdram) ? mcu_ack_mem :
		mcu.map.bram                    ? mcu_ack_bram :
		mcu.map.regs                    ? mcu_ack_regs :   // pocket: new core - registered ack
		mcu.map.sfx                     ? mcu_ack_sfx :    // pocket: synth step - the synth's registered ack (1 without it)
		(mcu.map.xram | mcu.map.xcram | mcu.map.xlink) ? xb_ack :   // pocket: xram step 1
		1'b1;

	// pocket: xram step 1
	assign xb_req    = mcu.ce & (mcu.map.xram | mcu.map.xcram | mcu.map.xlink);
	assign xb_region = mcu.map.xcram ? 2'd1 : mcu.map.xlink ? 2'd2 : 2'd0;
	assign xb_addr   = mcu.addr[23:0];
	assign xb_sel    = mcu.we;   // store lanes; a load always reads the whole word (paprium_xram)
	assign xb_wr     = (mcu.we != 4'd0);
	assign xb_wdata  = mcu.dato;
	// pocket-end

	// pocket: test build 4 - the WRAM (paprium_wram) is inside mcu_core now, tightly coupled to the NEORV32

	// pocket: new core - the mailbox posts, FPGAIO CAUSE.B and CAUSE.A. xram step 2's mailbox latch (mbx_irq)
	// moved into fpgio as CAUSE.B with the same set term: ramdp_io's filtered 68000 write pulse at $1FEA. Mailbox A
	// copies it at $1FEC. The integration takes both from the cart register file (reg_post_b / reg_post_a): there
	// they are cpu_we_ck & (either strobe) & the address, the same pulse as cpu_wr_pulse & the address
	wire cpu_wr_pulse;

	mcu_core #(.CLK_HZ(CLK_HZ), .IROM_KB({24'd0, FEAT[23:16]})) mcu_inst   // pocket: synth step - the IROM size FEAT reports (test build 5: 88)
	(
		.clk(clk),
		.rst(reset | ~enable),
		.mcu(mcu),
		.mcu_dati(mcu_dati),
		.mcu_ack(mcu_ack),
		.irq_ext(irq_ext),     // pocket: new core - FPGAIO CAUSE OR
		.irq_tmr(irq_tmr),     // pocket: new core - FPGAIO timer level
		.irq_sw(irq_sw),       // pocket: new core - FPGAIO MSIP
		.wlock(wlock),         // pocket: new core - FPGAIO WLOCK
		.gpio_o(),
		// pocket: 0.2.6 - GPIO_INPUT ($FFFFFF80): [18:16] the $1FE6 MegaWire status (7 = plugged
		// and signed in, 0 = none), [10:8] and [6] the console's $1FE4 model bits. ppm_reset copies
		// the low half into $1FE4 (with busy) and the high half into $1FE6.
		// pocket: new core (MCU_INTERFACE v1.0 section 5) - [24] MENU (the Pocket menu is open), [25] JAP
		// (the Console region is Japan), [26] PAL (a PAL build); live, no latch
		.gpio_i({5'd0, mcu_opts[7:5], 5'd0, {3{mcu_opts[4]}}, 5'd0, mcu_opts[3:1], 1'b0, mcu_opts[0], 6'd0}),
		.debug_bus_ack(),
		.debug_bus_addr(),
		.debug_bus_wdata(),
		.debug_bus_we(),
		.debug_bus_target(),
		.fw_go(fw_go)         // Fafrium
	);

	fpgio #(.FEAT(FEAT)) fpgio_inst   // pocket: new core - FPGAIO v1.0; synth step - v1.3 (STAMP_A, FEAT, CAUSE.BLK)
	(
		.mcu(mcu),
		.md_srst(reset),
		.link_status(link_status),
		.post_b(reg_post_b),
		.post_a(reg_post_a),
		.post_s(link_post),
		.post_v(console_reset),   // pocket: test build S3c - console reset (EXTI 13): core_top's Console Reset
		.post_blk(syn_post_blk),  // pocket: synth step (v1.3) - CAUSE.BLK: the synth's BUSY fall (0 without the synth, FEAT.SYNTH 0)
		.vs_tog(vs_tog),          // pocket: new core (v1.1) - VSCNT
		.sptr(stream_ptr),
		.stream_status(reg_stream_status),   // pocket: new core - the register file's GO read-back
		.dec_rdata(fio_dec_rdata),           // pocket: sprite decoder - v1.2 slots 17-22
		.mcu_dati(mcu_dati_fpgio),
		.mcu_ack(mcu_ack_fpgio),
		.sptr_wr(fpgio_sptr_wr),
		.dec_wr(fio_dec_wr),
		.dec_wslot(fio_dec_wslot),
		.dec_rslot(fio_dec_rslot),
		.md_rst(md_reset),
		.exit(),
		.sdram_en(),              // pocket: new core - ctrl[2] no longer opens the window
		.menu_mute_en(menu_mute_en),   // pocket: new core - the Pocket-menu music mute, CTRL bit 4, out to core_top
		.opt_at_reset_en(opt_at_reset_en),   // pocket: new core - CTRL bit 5 (the dormant option latch)
		.irq_ext(irq_ext),
		.cause_v(cause_v),        // pocket: test build S3c
		.irq_tmr(irq_tmr),
		.irq_sw(irq_sw),
		.wlock(wlock),
		.debug_ctrl_write(),
		.debug_ctrl_value()
	);

	ramdp_io ramdp_inst
	(
		.mcu(mcu),
		.cpu(cpu),
		.mcu_dati(mcu_dati_ramdp),
		.mcu_ack(mcu_ack_ramdp),   // pocket: test build 4
		.cpu_dati(cpu_dati_ramdp),
		.debug_ramdp_write(dbg_ramdp_write),
		.debug_ramdp_vector_write(),
		.debug_ramdp_addr(dbg_ramdp_addr),
		.debug_ramdp_data(dbg_ramdp_data),
		.debug_cpu_we_act(),
		.debug_cpu_write(cpu_wr_pulse),
		.reg_cpu_dati(reg_cpu_dati),
		.reg_cpu_page(reg_cpu_page),
		.cpu_we_strobe(cpu_we_strobe)
	);

	// pocket: new core - the cart register file $1FE0-$1FFF: storage, both views, the busy bit, the window and
	// the 84 view switch (the firmware's docs/CART_FPGA_SPEC.md sections 3-7)
	paprium_regfile regfile_inst
	(
		.clk(clk),
		.reset(reset | ~enable),
		.mcu(mcu),
		.cpu(cpu),
		.cpu_we_ck(cpu_we_strobe),
		.model(mcu_opts[3:0]),
		.word_delivered(word_delivered),
		.dec_go(dec_go),                 // pocket: sprite decoder
		.dec_go_len(dec_go_len),
		.mcu_dati(mcu_dati_regs),
		.mcu_ack(mcu_ack_regs),
		.cpu_dati(reg_cpu_dati),
		.cpu_page(reg_cpu_page),
		.stream_win(reg_stream_win),
		.window_en(),
		.mini_view(mini_view),
		.busy(),
		.stream_status(reg_stream_status),
		.post_a(reg_post_a),
		.post_b(reg_post_b),
		.dec_f2(dec_f2),                 // pocket: sprite decoder
		.dec_f4(dec_f4),
		.dec_f6(dec_f6),
		.dec_f2_v(dec_f2_v),
		.dec_f4_v(dec_f4_v),
		.dec_f6_v(dec_f6_v)
	);

	// pocket: sprite decoder - the cart FPGA's sprite decoder and load-list queue: the chip's +12 / +14 / +16
	// writes queue a frame's blocks, a START decodes them from the ROM image into the workspace at DEC_BASE (where
	// 0.2.6's firmware decoder put them) through port 2, and its GO makes the stream valid. The window is unchanged
	paprium_hwdec hwdec_inst
	(
		.clk(clk),
		.reset(reset | ~enable),
		.fr_f2(dec_f2),
		.fr_f4(dec_f4),
		.fr_f6(dec_f6),
		.fr_f2_v(dec_f2_v),
		.fr_f4_v(dec_f4_v),
		.fr_f6_v(dec_f6_v),
		.fio_wr(fio_dec_wr),
		.fio_wslot(fio_dec_wslot),
		.fio_wdata(mcu.dato),
		.fio_rslot(fio_dec_rslot),
		.fio_rdata(fio_dec_rdata),
		.sptr(stream_ptr),
		.word_delivered(word_delivered),
		.fw_sptr_wr(fpgio_sptr_wr),
		.sptr_load(dec_sptr_load),
		.sptr_val(dec_sptr_val),
		.go(dec_go),
		.go_len(dec_go_len),
		.p2_valid(p2d_valid),
		.p2_we(p2d_we),
		.p2_lanes(p2d_lanes),
		.p2_addr(p2d_addr),
		.p2_wdata(p2d_wdata),
		.p2_take(p2d_take),
		.p2_flush(p2d_flush),
		.p2_rd_done(p2d_rd_done),
		.p2_rdata(p2d_rdata),
		.p2_wr_done(p2d_wr_done),
		.p2_busy(p2d_busy)
	);

	// paprium: snoop the 68k's writes to the command mailbox. CMDLOG is a
	// localparam at the top level, so this whole block folds away in shipping.
	// (cpu_wr_pulse is declared above the mcu_core instance. xram step 2's mbx_irq latch is FPGAIO CAUSE.B now.)

	// Channel-7 taps from audio_sfx, declared here because the logger below is
	// elaborated before the sfx instance that drives them.
	wire [10:0] ch7_vol;
	wire        ch7_empty;
	wire        ch7_wr;

	generate
		if(CMDLOG) begin : cmdlog_on
			paprium_cmd_log cmdlog_inst
			(
				.clk(clk),
				.reset(reset),
				.cpu_wr(cpu_wr_pulse),
				.cpu_addr(cpu.addr[12:0]),
				.cpu_data(cpu.dato),
				.ch7_vol(ch7_vol),
				.ch7_empty(ch7_empty),
				.ch7_wr(ch7_wr),
				.read_addr(cmdlog_read_addr),
				.read_data(cmdlog_read_data)
			);
		end
		else begin : cmdlog_off
			assign cmdlog_read_data = 8'd0;
		end
	endgenerate

	assign cart_data = cpu_dati_ramdp;

	paprium_mcu_mem mem_inst
	(
		.clk(clk),
		.reset(reset | ~enable),
		.boot(~fw_done),                 // Fafrium
		.mcu(mcu),
		.mcu_ack(mcu_ack_mem),
		.mcu_dati(mcu_dati_mem),
		.mem_addr(mem_addr),
		.mem_din(mem_din),
		.mem_dout(mem_dout),
		.mem_wrl(mem_wrl),
		.mem_wrh(mem_wrh),
		.mem_req(mem_req),
		.mem_ack(mem_ack),
		.dec_valid(p2d_valid),           // pocket: sprite decoder - paprium_hwdec, port 2's second client
		.dec_we(p2d_we),
		.dec_lanes(p2d_lanes),
		.dec_addr(p2d_addr),
		.dec_wdata(p2d_wdata),
		.dec_take(p2d_take),
		.dec_flush(p2d_flush),
		.dec_rd_done(p2d_rd_done),
		.dec_rdata(p2d_rdata),
		.dec_wr_done(p2d_wr_done),
		.dec_busy(p2d_busy)
	);

	paprium_backup backup_inst
	(
		.clk(clk),
		.reset(reset | ~enable),
		.mcu(mcu),
		.mcu_dati(mcu_dati_bram),
		.mcu_ack(mcu_ack_bram),
		.bram_change(save_change),
		.save_addr(save_addr),
		.save_di(save_di),
		.save_do(save_do),
		.save_wr(save_wr)
	);

// paprium: SFX is switchable so a diagnostic bitstream can trade it for the ~700 ALMs
// needed to fit while a graphics-path fix is being validated on hardware. The cartridge
// PCM engine has nothing to do with the stream window, so dropping it changes nothing
// about what such a build proves. SFX=1 is the shipping configuration.
generate
// pocket: synth step (SYNTH) - the synth takes region 0x06 (MCU_INTERFACE v1.3 3.10); the interim FIFOs are not built
if(SYNTH) begin : synth_on
	wire signed [15:0] dt_l, dt_r;

	paprium_synth #(.CLK_HZ(CLK_HZ)) synth_inst
	(
		.clk(clk),
		.reset(reset | ~enable),
		.m_req(mcu.ce & mcu.map.sfx),
		.m_addr(mcu.addr[11:0]),
		.m_we(mcu.we),
		.m_wdata(mcu.dato),
		.m_rdata(mcu_dati_sfx),
		.m_ack(mcu_ack_sfx),
		.post_b(reg_post_b),
		.post_a(reg_post_a),
		.post_blk(syn_post_blk),
		.freeze(mcu_opts[5] & menu_mute_en),   // pocket: synth step - the menu freeze (MCU_INTERFACE 3.10.6): menu open, CTRL bit 4
		.dt_l(dt_l),
		.dt_r(dt_r),
		.c_rd(syn_c_rd),
		.c_raddr(syn_c_raddr),
		.c_rd_done(syn_c_rd_done),
		.c_rdata(syn_c_rdata),
		.e_wr(syn_e_wr),
		.e_waddr(syn_e_waddr),
		.e_wpair(syn_e_wpair),
		.e_wdata(syn_e_wdata),
		.e_rd(syn_e_rd),
		.e_raddr(syn_e_raddr),
		.e_rpair(syn_e_rpair),
		.e_rd_done(syn_e_rd_done),
		.e_rdata(syn_e_rdata),
		.e_wbusy(syn_e_wbusy)
	);

	assign sfx_l = enable ? dt_l : 16'sd0;
	assign sfx_r = enable ? dt_r : 16'sd0;
	assign ch7_vol    = 11'd0;
	assign ch7_empty  = 1'b1;
	assign ch7_wr     = 1'b0;
	assign echo_wr    = 1'b0;   // no echo line: audio_sfx is not built
	assign echo_wslot = 13'd0;
	assign echo_wdata = 32'd0;
	assign echo_rd    = 1'b0;
	assign echo_rslot = 13'd0;
end
else if(SFX) begin : sfx_on
	SndCk snd;
	wire signed [15:0] sfx_l_raw;
	wire signed [15:0] sfx_r_raw;
	reg  [7:0]         sfx_volume = 8'hff;
	reg                sfx_started = 0;

	dac_clocker snd_48000
	(
		.clk(clk),
		.rst(reset | ~enable),
		.rate(16'd48000),
		.ck_base(CLK_HZ),
		.dac_clk(snd.clk),
		.next_sample(snd.next_sample),
		.phase(snd.phase)
	);

	audio_sfx sfx_inst
	(
		.mcu(mcu),
		.snd(snd),
		.mcu_dati_sfx(mcu_dati_sfx),
		.snd_l(sfx_l_raw),
		.snd_r(sfx_r_raw),
		.dbg_ch7_vol(ch7_vol),
		.dbg_ch7_empty(ch7_empty),
		.dbg_ch7_wr(ch7_wr),

		.echo_ready(echo_ready),         // pocket: the echo line in CRAM
		.echo_wr(echo_wr),
		.echo_wslot(echo_wslot),
		.echo_wdata(echo_wdata),
		.echo_rd(echo_rd),
		.echo_rslot(echo_rslot),
		.echo_rd_done(echo_rd_done),
		.echo_rdata(echo_rdata)
	);

	always @(posedge clk) begin
		if(reset | ~enable) begin
			sfx_volume <= 8'hff;
			sfx_started <= 0;
		end
		else begin
			if(mcu.ce & mcu.map.fpgio_vols & mcu.we[0])
				sfx_volume <= mcu.dato[7:0];
			if(mcu.ce & mcu.map.sfx & (mcu.we != 0))
				sfx_started <= 1;
		end
	end

	assign sfx_l = (enable & sfx_started & (sfx_volume != 0)) ? sfx_l_raw : 16'sd0;
	assign sfx_r = (enable & sfx_started & (sfx_volume != 0)) ? sfx_r_raw : 16'sd0;
end
else begin : sfx_off
	assign mcu_dati_sfx = 32'd0;
	assign sfx_l        = 16'sd0;
	assign sfx_r        = 16'sd0;
	assign echo_wr      = 1'b0;   // pocket: the echo line in CRAM
	assign echo_wslot   = 13'd0;
	assign echo_wdata   = 32'd0;
	assign echo_rd      = 1'b0;
	assign echo_rslot   = 13'd0;
end
// pocket: synth step - without the synth: its ack is the interim region's (at once), no CAUSE.BLK, no CRAM client
if(!SYNTH) begin : synth_off
	assign mcu_ack_sfx  = 1'b1;
	assign syn_post_blk = 1'b0;
	assign syn_c_rd     = 1'b0;
	assign syn_c_raddr  = 21'd0;
	assign syn_e_wr     = 1'b0;
	assign syn_e_waddr  = 22'd0;
	assign syn_e_wpair  = 1'b0;
	assign syn_e_wdata  = 32'd0;
	assign syn_e_rd     = 1'b0;
	assign syn_e_raddr  = 22'd0;
	assign syn_e_rpair  = 1'b0;
end
endgenerate
// paprium-end

	// pocket: synth step (test build 5; MCU interface v1.3 21.5) - the interim MD+ block (paprium_mdp_adapter,
	// region 0x07: the album's command channel) is out of the build: test build 5 plays the cart's own music on the synth
	// and FEAT.MDP = 0, so region 0x07 is unassigned (the mcu_dati / mcu_ack muxes above: 0xFFFF_FFFF, ack at once) and no
	// MD+ command goes out (nothing consumes one: the album path went with test build 4a). The module file stays listed,
	// unreachable
	assign mdp_track_request  = 1'b0;
	assign mdp_track_num      = 8'd0;
	assign mdp_track_loop     = 1'b0;
	assign mdp_stop_request   = 1'b0;
	assign mdp_fade_sectors   = 8'd0;
	assign mdp_resume_request = 1'b0;
	assign mdp_volume         = 8'd0;
	assign mdp_volume_request = 1'b0;
	assign mdp_active         = 1'b0;
	/* verilator lint_off UNUSEDSIGNAL */
	wire   mdp_unused         = &{1'b0, mdp_playing, mdp_current_track};   // the MD+ status inputs: nothing reads them now
	/* verilator lint_on UNUSEDSIGNAL */

endmodule
