module paprium_cart
#(parameter SFX = 1'b1, parameter CMDLOG = 1'b0)
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

	// pocket: xram stage 1 - the MCU's windows on the Pocket SRAM (0x08), CRAM (0x09) and
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

	// pocket: 0.2.6 - OSD options for the firmware: {MegaWire, $1FE4 bit 10, 9, 8, 6}
	input       [4:0] mcu_opts,

	// pocket: xram stage 2 - option-D status (paprium_xlink LSTAT[7:0] less 'armed'); read back
	// with the mailbox interrupt latch in the FPGAIO ctrl word [15:8]
	input       [6:0] link_status,

	// pocket: the SFX echo line's CRAM port (paprium_cram port E in core_top, this clock)
	input             echo_ready,
	output            echo_wr,
	output     [12:0] echo_wslot,
	output     [31:0] echo_wdata,
	output            echo_rd,
	output     [12:0] echo_rslot,
	input             echo_rd_done,
	input      [31:0] echo_rdata
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
	assign stream_cs = enable & cart_cs & cart_oe & sdram_en &
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
	always @(posedge clk) begin
		stream_ack_d <= stream_read_ack_toggle;

		if(reset) begin
			stream_ptr <= 0;
			stream_ack_d <= 0;
		end
		else if(mcu.ce && (mcu.we != 0) && mcu.map.fpgio_sptr)
			stream_ptr <= mcu.dato[20:0];
		else if(stream_read_ack_toggle != stream_ack_d)
			stream_ptr <= stream_ptr + 2'd2;
	end

	assign stream_addr = 24'h400000 + {{4{1'b0}}, stream_ptr[20:1]};

	wire [31:0] mcu_dati_fpgio;
	wire [31:0] mcu_dati_ramdp;
	wire [31:0] mcu_dati_mem;
	wire [31:0] mcu_dati_mdp;
	wire [31:0] mcu_dati_sfx;
	wire [31:0] mcu_dati_bram;
	wire [15:0] cpu_dati_ramdp;
	wire mcu_ack_mem;
	wire mcu_ack_bram;
	wire sdram_en;

	wire [31:0] mcu_dati =
		mcu.map.fpgio ? mcu_dati_fpgio :
		mcu.map.ramdp ? mcu_dati_ramdp :
		(mcu.map.flash | mcu.map.sdram) ? mcu_dati_mem :
		mcu.map.bram  ? mcu_dati_bram :
		mcu.map.mdp   ? mcu_dati_mdp :
		mcu.map.sfx   ? mcu_dati_sfx :
		(mcu.map.xram | mcu.map.xcram | mcu.map.xlink) ? xb_rdata :   // pocket: xram stage 1
		32'hffffffff;

	wire mcu_ack =
		(mcu.map.flash | mcu.map.sdram) ? mcu_ack_mem :
		mcu.map.bram                    ? mcu_ack_bram :
		(mcu.map.xram | mcu.map.xcram | mcu.map.xlink) ? xb_ack :   // pocket: xram stage 1
		1'b1;

	// pocket: xram stage 1
	assign xb_req    = mcu.ce & (mcu.map.xram | mcu.map.xcram | mcu.map.xlink);
	assign xb_region = mcu.map.xcram ? 2'd1 : mcu.map.xlink ? 2'd2 : 2'd0;
	assign xb_addr   = mcu.addr[23:0];
	assign xb_sel    = mcu.we;   // store lanes; a load always reads the whole word (paprium_xram)
	assign xb_wr     = (mcu.we != 4'd0);
	assign xb_wdata  = mcu.dato;
	// pocket-end

	wire [15:0] wram_dato;
	wire [15:0] wram_dati;
	wire [18:0] wram_addr;
	wire [1:0] wram_we;
	MemBus wram;

	assign wram_dati = wram.dati;
	assign wram_addr = wram.addr[18:0];
	assign wram_we = wram.we;

	// pocket: xram stage 2 - interrupt on the 68000's mailbox post (gate_report item 10). Set by
	// ramdp_io's write pulse to RAMDP $1FEA (reg_cmd), cleared by an MCU write of bit 0 = 1 to
	// FPGAIO slot 6 (0x01000018; slot 5 is a diagnostic build's stream_cnt). A level into the
	// NEORV32's mext_irq_i: 1.4.8.1 buffers it only while MEIE is set, and the shipping firmware
	// never sets MEIE, so it is unaffected. A set and a clear in the same clock: the set wins.
	reg  mbx_irq = 1'b0;   // set and cleared below, after cpu_wr_pulse is declared

	mcu_core mcu_inst
	(
		.clk(clk),
		.rst(reset | ~enable),
		.mcu(mcu),
		.mcu_dati(mcu_dati),
		.mcu_ack(mcu_ack),
		.irq_ext(mbx_irq),
		.wram(wram),
		.wram_dato(wram_dato),
		.gpio_o(),
		// pocket: 0.2.6 - GPIO_INPUT ($FFFFFF80): [18:16] the $1FE6 MegaWire status (7 = plugged
		// and signed in, 0 = none), [10:8] and [6] the console's $1FE4 model bits. ppm_reset copies
		// the low half into $1FE4 (with busy) and the high half into $1FE6.
		.gpio_i({13'd0, {3{mcu_opts[4]}}, 5'd0, mcu_opts[3:1], 1'b0, mcu_opts[0], 6'd0}),
		.uart_tx(),
		.uart_rx(1'b1),
		.debug_bus_ack(),
		.debug_bus_addr(),
		.debug_bus_wdata(),
		.debug_bus_we(),
		.debug_bus_target()
	);

	paprium_wram wram_inst
	(
		.clk(clk),
		.addr(wram_addr[14:1]),
		.dati(wram_dati),
		.we(wram_we),
		.dato(wram_dato)
	);

	fpgio fpgio_inst
	(
		.mcu(mcu),
		.md_srst(reset),
		.link_status({mbx_irq, link_status}),
		.mcu_dati(mcu_dati_fpgio),
		.md_rst(md_reset),
		.exit(),
		.sdram_en(sdram_en),
		.debug_ctrl_write(),
		.debug_ctrl_value()
	);

	ramdp_io ramdp_inst
	(
		.mcu(mcu),
		.cpu(cpu),
		.mcu_dati(mcu_dati_ramdp),
		.cpu_dati(cpu_dati_ramdp),
		.debug_ramdp_write(dbg_ramdp_write),
		.debug_ramdp_vector_write(),
		.debug_ramdp_addr(dbg_ramdp_addr),
		.debug_ramdp_data(dbg_ramdp_data),
		.debug_cpu_we_act(),
		.debug_cpu_write(cpu_wr_pulse)
	);

	// paprium: snoop the 68k's writes to the command mailbox. CMDLOG is a
	// localparam at the top level, so this whole block folds away in shipping.
	wire cpu_wr_pulse;

	// pocket: xram stage 2 - the mailbox interrupt latch (see mbx_irq above)
	wire mbx_irq_clr = mcu.ce & mcu.map.fpgio & (mcu.addr[5:2] == 4'd6) & mcu.we[0] & mcu.dato[0];
	always @(posedge clk) begin
		if (reset | ~enable) mbx_irq <= 1'b0;
		else if (cpu_wr_pulse & (cpu.addr[12:1] == 12'hFF5)) mbx_irq <= 1'b1;
		else if (mbx_irq_clr) mbx_irq <= 1'b0;
	end

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
		.mcu(mcu),
		.mcu_ack(mcu_ack_mem),
		.mcu_dati(mcu_dati_mem),
		.mem_addr(mem_addr),
		.mem_din(mem_din),
		.mem_dout(mem_dout),
		.mem_wrl(mem_wrl),
		.mem_wrh(mem_wrh),
		.mem_req(mem_req),
		.mem_ack(mem_ack)
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
if(SFX) begin : sfx_on
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
		.ck_base(`CLK_FREQ),
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
endgenerate
// paprium-end

	paprium_mdp_adapter mdp_adapter_inst
	(
		.clk(clk),
		.reset(reset | ~enable),
		.mcu(mcu),
		.mcu_dati(mcu_dati_mdp),
		.mdp_playing(mdp_playing),
		.mdp_current_track(mdp_current_track),
		.mdp_track_request(mdp_track_request),
		.mdp_track_num(mdp_track_num),
		.mdp_track_loop(mdp_track_loop),
		.mdp_stop_request(mdp_stop_request),
		.mdp_fade_sectors(mdp_fade_sectors),
		.mdp_resume_request(mdp_resume_request),
		.mdp_volume(mdp_volume),
		.mdp_volume_request(mdp_volume_request),
		.mdp_active(mdp_active)
	);

endmodule
