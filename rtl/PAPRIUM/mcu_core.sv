

module mcu_core(

	input  clk,
	input  rst,
	output McuBus mcu,
	input  [31:0]mcu_dati,
	input  mcu_ack,
	input  irq_ext,//pocket: xram stage 2 - the 68000's mailbox post (paprium_cart), level, to mext_irq_i
	
	output MemBus wram,
	input  [15:0]wram_dato,
	
	output [31:0]gpio_o,
	input  [31:0]gpio_i,
	
	output uart_tx,
	input  uart_rx,

	output       debug_bus_ack,
	output [31:0]debug_bus_addr,
	output [31:0]debug_bus_wdata,
	output       debug_bus_we,
	output [3:0] debug_bus_target
);

//************************************************************************************* memory map
	assign mcu.map.wrom	= {mcu.addr[31:24], 24'd0} == 'h00000000;
	assign mcu.map.wram	= {mcu.addr[31:24], 24'd0} == 'h80000000;
	assign mcu.map.fpgio	= {mcu.addr[31:24], 24'd0} == 'h01000000;
	assign mcu.map.ramdp	= {mcu.addr[31:24], 24'd0} == 'h02000000;
	assign mcu.map.sdram	= {mcu.addr[31:24], 24'd0} == 'h03000000;
	assign mcu.map.flash	= {mcu.addr[31:24], 24'd0} == 'h04000000;
	assign mcu.map.bram	= {mcu.addr[31:24], 24'd0} == 'h05000000;
	assign mcu.map.sfx	= {mcu.addr[31:24], 24'd0} == 'h06000000;
	assign mcu.map.mdp	= {mcu.addr[31:24], 24'd0} == 'h07000000;
	// pocket: xram stage 1 - the Pocket SRAM, CRAM and their register block (core_top)
	assign mcu.map.xram	= {mcu.addr[31:24], 24'd0} == 'h08000000;
	assign mcu.map.xcram	= {mcu.addr[31:24], 24'd0} == 'h09000000;
	assign mcu.map.xlink	= {mcu.addr[31:24], 24'd0} == 'h0A000000;
	
	assign mcu.map.fpgio_ctrl	= mcu.map.fpgio & mcu.addr[5:2] == 0;
	assign mcu.map.fpgio_time	= mcu.map.fpgio & mcu.addr[5:2] == 1;
	assign mcu.map.fpgio_sptr	= mcu.map.fpgio & mcu.addr[5:2] == 2;
	assign mcu.map.fpgio_vols	= mcu.map.fpgio & mcu.addr[5:2] == 3;
	assign mcu.map.fpgio_volb	= mcu.map.fpgio & mcu.addr[5:2] == 4;
	
	assign mcu.map.mdp_ctrl		= mcu.map.mdp & mcu.addr[23]	== 0;
	assign mcu.map.mdp_fifo		= mcu.map.mdp & mcu.addr[23]	== 1;
//************************************************************************************* cpu core
	assign mcu.dato 		= rv_do;
	assign mcu.addr 		= rv_ad;
	assign mcu.ce			= rv_stb & rv_cyc;
	assign mcu.oe			= mcu.ce & rv_we == 0;
	assign mcu.we[0]		= mcu.ce & rv_we == 1 & rv_sel[0];
	assign mcu.we[1]		= mcu.ce & rv_we == 1 & rv_sel[1];
	assign mcu.we[2]		= mcu.ce & rv_we == 1 & rv_sel[2];
	assign mcu.we[3]		= mcu.ce & rv_we == 1 & rv_sel[3];
	assign mcu.clk			= clk;
	
	wire [3:0]rv_sel/*synthesis keep*/;
	wire [31:0]rv_ad/*synthesis keep*/;
	wire [31:0]rv_do/*synthesis keep*/;
	wire [31:0]rv_di;
	wire rv_we, rv_stb, rv_cyc, rv_ack/*synthesis keep*/;
	
	assign rv_di	= 
	mcu.map.wrom ? mcu_dati_irom :
	//mcu.map.wrom ? mcu_dati_wram :
	mcu.map.wram ? mcu_dati_wram : mcu_dati;
	
	assign rv_ack	= 
	mcu.map.wrom ? ack_wram :
	mcu.map.wram ? ack_wram : mcu_ack;

	assign debug_bus_ack = rv_stb & rv_cyc & rv_ack;
	assign debug_bus_addr = rv_ad;
	assign debug_bus_wdata = rv_do;
	assign debug_bus_we = rv_we;
	assign debug_bus_target =
		mcu.map.wrom  ? 4'h1 :
		mcu.map.wram  ? 4'h2 :
		mcu.map.fpgio ? 4'h3 :
		mcu.map.ramdp ? 4'h4 :
		mcu.map.sdram ? 4'h5 :
		mcu.map.flash ? 4'h6 :
		mcu.map.bram  ? 4'h7 :
		(mcu.map.sfx | mcu.map.mdp) ? 4'h8 :
		4'h0;
	
	
	// CLOCK_FREQUENCY drives NEORV32 SYSINFO_CLK, which the firmware reads to
	// compute UART baud divisor, MTIME tick rate, and WDT timeout. The default
	// generic is 50_000_000, but in this integration the NEORV32 is clocked from
	// MegaCD clk_sys (~53.693175 MHz NTSC). Override the generic so SYSINFO_CLK
	// matches the actual clock and the firmware's clock-derived math is correct.
	neorv32_top_stdlogic #(
		.CLOCK_FREQUENCY(53693175)
	) neorv32_inst(

		.clk_i(clk),
		.rstn_i(!rst),
		
		.wb_tag_o(),
		.wb_adr_o(rv_ad[31:0]),
		.wb_dat_i(rv_di[31:0]),
		.wb_dat_o(rv_do[31:0]),
		.wb_we_o(rv_we),
		.wb_sel_o(rv_sel[3:0]),
		.wb_stb_o(rv_stb),
		.wb_cyc_o(rv_cyc),
		.wb_lock_o(),
		.wb_ack_i(rv_ack),
		.wb_err_i(0),
		
		.gpio_o(gpio_o),
		.gpio_i(gpio_i),
		
		.uart_txd_o(uart_tx),
		.uart_rxd_i(uart_rx),
			
		.mtime_irq_i(0),
		.msw_irq_i(0),
		.mext_irq_i(irq_ext)//pocket: sticky in 1.4.8.1's irq_buf once MEIE is set; cleared at FPGAIO slot 6
	);
	
	
//******************************************
	wire [31:0]mcu_dati_wram;
	wire ack_wram;
	
	wire mcu_ce_wrom	= mcu.addr[31] == 0 & mcu.addr[30:18] == 0;
	wire mcu_ce_wram	= mcu.addr[31] == 1 & mcu.addr[30:18] == 0;
	
	mcu_wram mcu_wram_inst(
		
		.mcu(mcu),
		.mcu_dati(mcu_dati_wram),
		
		.wram(wram),
		.wram_dato(wram_dato),
		
		.ce_wrom(mcu.map.wrom),
		.ce_wram(mcu.map.wram),
		.ack(ack_wram)
		
	);
	
//****************************************** mcu rom
	
	
	wire [31:0]mcu_dati_irom;
	
	mcu_irom mcu_irom_inst(

		.clk(mcu.clk),
		.addr(mcu.addr[16:0]),//pocket: buddy_s2 - 17 bits: rom0 0x0000-0x7FFF + the extension from 0x8000
		.dato(mcu_dati_irom)
	);
		
endmodule

//************************************************************************************* wram controller


module mcu_wram(

	input  McuBus mcu,
	output [31:0]mcu_dati,
	
	output MemBus wram,
	input  [15:0]wram_dato,
	
	input ce_wrom,
	input ce_wram,
	output ack
	
);
	
	wire rom_ce					= mcu.ce & ce_wrom;
	wire ram_ce					= mcu.ce & ce_wram;
	wire wram_ce				= rom_ce | ram_ce;
		
		
	wire wram_bank 			= ce_wrom ? 0 : 1;
	assign wram.addr[23:2]	= {wram_bank, mcu.addr[17:2]};
	assign wram.addr[0]		= 1'b0;
	assign wram.dati			= wram.addr[1] == 0 ? {mcu.dato[7:0], mcu.dato[15:8]} : {mcu.dato[23:16], mcu.dato[31:24]};
	
	assign wram.we[0]			= !idle & mcu.oe == 0 & ram_ce & (wram.addr[1] == 0 ? mcu.we[0] : mcu.we[2]);
	assign wram.we[1]			= !idle & mcu.oe == 0 & ram_ce & (wram.addr[1] == 0 ? mcu.we[1] : mcu.we[3]);
	assign wram.oe				= !idle & mcu.oe == 1 & wram_ce;

	assign mcu_dati[31:16]	= idle ? mcu_dati_hi : {wram_dato[7:0], wram_dato[15:8]};
	
	reg [15:0]mcu_dati_hi;
	reg [3:0]state;
	reg idle;
	reg delay;
	
	always @(posedge mcu.clk)
	begin
		
		
		if(!wram_ce)
		begin
			state						<= 0;
			idle						<= 0;
			ack						<= 0;
			wram.addr[1]			<= 0;
			delay						<= `SRM_DELAY;
		end
			else
		if(delay)
		begin
			delay						<= 0;
		end
			else
		if(mcu.oe)
		case(state)
			0:begin
				mcu_dati[15:0]		<= {wram_dato[7:0], wram_dato[15:8]};
				wram.addr[1]		<= 1;
				ack					<= 1;
				state					<= state + 1;
			end
			1:begin
				mcu_dati_hi			<= {wram_dato[7:0], wram_dato[15:8]};
				idle					<= 1;
				state					<= state + 1;
			end
		endcase
			else
		case(state)
			0:begin
				idle 					<= 1;
				state					<= state + 1;
			end
			1:begin
				wram.addr[1]		<= 1;
				state					<= state + 1;
			end
			2:begin
				idle 					<= 0;
				state					<= state + 1;
				ack					<= 1;
			end
			3:begin
				idle 					<= 1;
				state					<= state + 1;
			end
		endcase

		
	end
	
	
endmodule

//************************************************************************************* mcu rom (optional)

// paprium: grown from 16 KB to 32 KB. The 16 KB ceiling was imposed HERE, not by
// the toolchain - neorv32.ld already allows 256 KB and mcu.map.wrom decodes a
// 16 MB region. It mattered because GCC 15 at -O2 builds krikzz's source to
// 16,344 bytes, 40 short of fitting, and -Os would have been the wrong answer:
// the MCU services the 68000 in real time and upstream attributes the elevator
// corruption to MCU starvation, so trading its speed for space aims at the part
// already suspected of missing deadlines. 32 KB costs ~13 more M10K of 62 free.
//
// pocket: buddy_s2 (hook-free CPU MATE, code in block RAM) - the IROM grows by EXT_KB KB above rom0
// without a power-of-two step. rom0 is untouched (32 KB, mcu.txt, 32 M10K in 8192x1). The extension
// is one more inferred ROM, rom_x, whose depth slices are capped (max_depth) so that every slice is a
// whole number of M10K at exactly one M10K per KB: 1024 deep (1024x32 = 4 blocks) when EXT_KB is a
// multiple of 4, 512 (512x32 = 2 blocks) when even, else 256 (256x32 = 1 block). The deepest legal
// slice keeps the slice mux short (12 KB: 3:1 instead of 12:1). The slice mux uses a registered
// select, then a 2:1 against rom0 on a registered addr[15]. Same one-clock read as rom0, so a fetch or a load
// from the extension costs the same cycles (the ack comes from mcu_wram either way). Its image is
// mcu_ext.txt (EXT_KB x 256 words, rv_cpi's mcu.txt format), written by the firmware build's image step from the
// part of mcu.bin above 32 KB. Addresses 0x8000 + EXT_KB KB .. 0xFFFF are not backed (undefined data).
// buddy_s2/sys (integration): EXT_KB = 22. The integrated image puts the brain's jump table + text at
// 0x5360-0xD2EB (rom0 tail + 21,228 B of extension); its image tables, the counting helpers and the glue
// live in the WRAM code window. 22 KB = 11 slices of 512x32 (2 M10K each), 1,300 B spare.
// (earlier sizing, superseded:) EXT_KB = 12 holds the brain + counter as measured today (39,140 B; buddy_s2 layout: 10,752 B of rom0
// above the firmware + 16,384 B of WRAM window + this); every KB the counter loses lowers it by one.
module mcu_irom #(
	parameter integer EXT_KB = 22
)(

	input  clk,
	input  [16:0]addr,
	output [31:0]dato
);

	wire [31:0]di;                                // rom0 or the extension (declared before use)
	assign dato = {di[7:0], di[15:8], di[23:16], di[31:24]};

	reg[31:0]rom[32768/4];
	
	reg [31:0]di0;
	
	always @(posedge clk)
	begin
		di0		<= rom[addr[14:2]];
	end
	
	initial
	begin
		$readmemh("mcu.txt", rom);  // pocket: bare name + SEARCH_PATH ../rtl/PAPRIUM, same idiom as 68k.v
	end

	generate if (EXT_KB > 0) begin : g_ext
		localparam integer XN = EXT_KB * 256;           // words
		localparam integer XW = (XN <= 256) ? 8 : $clog2(XN);
		reg [31:0]dix;
		reg sel_x;
		always @(posedge clk) sel_x <= addr[15];
		if (EXT_KB % 4 == 0) begin : g_d1024
			(* ramstyle = "M10K", max_depth = 1024 *) reg [31:0]rom_x[0:XN-1];
			always @(posedge clk) dix <= rom_x[addr[XW+1:2]];
			initial $readmemh("mcu_ext.txt", rom_x);
		end else if (EXT_KB % 2 == 0) begin : g_d512
			(* ramstyle = "M10K", max_depth = 512 *) reg [31:0]rom_x[0:XN-1];
			always @(posedge clk) dix <= rom_x[addr[XW+1:2]];
			initial $readmemh("mcu_ext.txt", rom_x);
		end else begin : g_d256
			(* ramstyle = "M10K", max_depth = 256 *) reg [31:0]rom_x[0:XN-1];
			always @(posedge clk) dix <= rom_x[addr[XW+1:2]];
			initial $readmemh("mcu_ext.txt", rom_x);
		end
		assign di = sel_x ? dix : di0;
	end else begin : g_noext
		assign di = di0;
	end endgenerate

endmodule
