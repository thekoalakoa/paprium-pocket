module paprium_cart
#(parameter SFX = 1'b1)
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
	input             mem_ack
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
		32'hffffffff;

	wire mcu_ack =
		(mcu.map.flash | mcu.map.sdram) ? mcu_ack_mem :
		mcu.map.bram                    ? mcu_ack_bram :
		1'b1;

	wire [15:0] wram_dato;
	wire [15:0] wram_dati;
	wire [18:0] wram_addr;
	wire [1:0] wram_we;
	MemBus wram;

	assign wram_dati = wram.dati;
	assign wram_addr = wram.addr[18:0];
	assign wram_we = wram.we;

	mcu_core mcu_inst
	(
		.clk(clk),
		.rst(reset | ~enable),
		.mcu(mcu),
		.mcu_dati(mcu_dati),
		.mcu_ack(mcu_ack),
		.wram(wram),
		.wram_dato(wram_dato),
		.gpio_o(),
		.gpio_i(32'd0),
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
		.debug_cpu_write()
	);

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
		.snd_r(sfx_r_raw)
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
