// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)


module mcu_core #(
	parameter integer CLK_HZ = 0,    //pocket: 0.3.0 new core - clk in Hz, from core_top; SYSINFO_CLK reports it
	parameter integer IROM_KB = 72   //pocket: 0.3.0 synth step - the IROM (the MCU's code memory) in KB: 72, or 88 on
	                                 //  the synth fit (the firmware's docs/MCU_INTERFACE.md v1.3 section 3.1), from
	                                 //  FEAT[23:16] (paprium_cart): rom0 32 KB + an extension of IROM_KB - 32 KB (mcu_irom EXT_KB)
)(

	input  clk,
	input  rst,
	output McuBus mcu,
	input  [31:0]mcu_dati,
	input  mcu_ack,
	input  irq_ext,//pocket: new core - FPGAIO (fpgio.sv) CAUSE OR {V, S, A, B} (a level until acked), to mext_irq_i
	input  irq_tmr,//pocket: new core - FPGAIO timer level, to mtime_irq_i (MTIME is off)
	input  irq_sw, //pocket: new core - FPGAIO MSIP, to msw_irq_i

	// pocket: test build 4 (the 0.3.0 hardware test build of the MCU fast path) - the WRAM (the MCU's working RAM) is
	// inside this block now (mcu_tcm_wram, tightly coupled): the MemBus port and paprium_cart's paprium_wram instance
	// are gone
	input  [20:0]wlock,//pocket: new core - FPGAIO WLOCK: bit k locks WRAM KB 27 + k (mcu_tcm_wram)

	output [31:0]gpio_o,
	input  [31:0]gpio_i,

	output       debug_bus_ack,
	output [31:0]debug_bus_addr,
	output [31:0]debug_bus_wdata,
	output       debug_bus_we,
	output [3:0] debug_bus_target,

	// Fafrium (the cart firmware file): a power-on flag, no reset port (only a bitstream load clears it)
	output       fw_go     // the boot stub's GO store was seen: the firmware is in place (core_top restarts the cart)
);

	// Fafrium: fw_go is set by the boot stub's GO (mcu_tcm_irom: a byte store to 0x7FF while fw_go = 0), its last
	// store. Before it the IROM takes word stores and the WRAM code window is writable; from it on both are locked
	// exactly as before (core_top holds the cart in reset from the next clock, and its fw_done closes the boot view)
	reg  fw_go_q   = 1'b0;
	wire irom_go;
	// Fafrium: the finisher's guard. fw_fin_q is set by the first word store into IROM [0, 0x800) before GO: only the boot
	// stub's finisher stores there (the stub's payload pass stores from 0x800 on; the firmware never stores to the IROM),
	// so from that store on the stub at the reset vector is being overwritten. Any reset of the MCU between it and GO (a
	// new load's envelope, the cart's enable) sets fw_hold_q, and from then the NEORV32 is held in reset until a
	// bitstream load: a cut finisher never runs a half-written IROM; the cart stays as in a refusal (the 68000 held by
	// CTRL.HOLD's reset value). Both are power-on flags. On every boot that reaches GO fw_hold_q stays 0, so the CPU's
	// reset is rst exactly as before
	reg  fw_fin_q  = 1'b0;
	reg  fw_hold_q = 1'b0;
	wire irom_fin;
	always @(posedge clk) begin
		if (irom_go) fw_go_q <= 1'b1;
		if (irom_fin) fw_fin_q <= 1'b1;
		if (rst & fw_fin_q & ~fw_go_q) fw_hold_q <= 1'b1;
	end
	wire rst_cpu = rst | fw_hold_q;
	assign fw_go   = fw_go_q;

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
	// pocket: xram step 1 - the Pocket SRAM, CRAM (the Pocket's cellular RAM) and their register block (core_top)
	assign mcu.map.xram	= {mcu.addr[31:24], 24'd0} == 'h08000000;
	assign mcu.map.xcram	= {mcu.addr[31:24], 24'd0} == 'h09000000;
	assign mcu.map.xlink	= {mcu.addr[31:24], 24'd0} == 'h0A000000;
	// pocket: 0.3.0 new core - the cart register file (paprium_regfile), 0x0B000000 + the offset from $1FE0
	assign mcu.map.regs	= {mcu.addr[31:24], 24'd0} == 'h0B000000;
	
	// pocket: 0.3.0 new core (MCU_INTERFACE.md v1.0 section 4) - FPGAIO slot = addr[6:2] (32 slots; 0.2.6: addr[5:2]).
	// Slot 1 (the ms counter) is retired; fpgio.sv decodes every slot itself, these name the ones used outside it
	assign mcu.map.fpgio_ctrl	= mcu.map.fpgio & mcu.addr[6:2] == 0;
	assign mcu.map.fpgio_sptr	= mcu.map.fpgio & mcu.addr[6:2] == 2;
	assign mcu.map.fpgio_vols	= mcu.map.fpgio & mcu.addr[6:2] == 3;
	assign mcu.map.fpgio_volb	= mcu.map.fpgio & mcu.addr[6:2] == 4;
	
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
	// pocket: test build 4 - the access's byte lanes, loads too (paprium_mcu_mem's half-skip). NEORV32 1.4.8.1 sets them
	// by size for every data access; during an instruction fetch its bus switch shows the DATA port's last byte enables
	// (the fetch port is read-only), so a fetch (Wishbone tag bit 2) reads the whole word
	assign mcu.sel			= rv_src ? 4'b1111 : rv_sel;
	assign mcu.clk			= clk;
	
	wire [3:0]rv_sel/*synthesis keep*/;
	wire [31:0]rv_ad/*synthesis keep*/;
	wire [31:0]rv_do/*synthesis keep*/;
	wire [31:0]rv_di;
	wire rv_we, rv_stb, rv_cyc, rv_ack/*synthesis keep*/;
	wire rv_src;   // pocket: test build 4 - 1 = the Wishbone access is an instruction fetch

	// pocket: test build 4 - the processor-internal bus to the tightly coupled IROM and WRAM
	wire        tcm_re, tcm_we;
	wire [3:0]  tcm_ben;
	wire [31:0] tcm_addr, tcm_wdata, tcm_i_rdata, tcm_d_rdata;
	wire        tcm_i_ack, tcm_d_ack;
	
	// pocket: test build 4 - the IROM and the WRAM answer on the processor-internal bus (mcu_tcm_irom / mcu_tcm_wram
	// below), so only the other regions reach Wishbone: rv_di / rv_ack are paprium_cart's mux alone
	assign rv_di	= mcu_dati;
	assign rv_ack	= mcu_ack;

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
	// pocket: 0.3.0 new core (the clock-following change) - the value is core_top's CLK_HZ, not a literal
	// pocket: 0.3.0 new core (MCU_INTERFACE.md v1.0 section 2) - the processor is configured in paprium_neorv32.vhd:
	// MTIME, UART and WDT off, GPIO kept, SYSINFO USER_CODE = the interface version. Only naturals cross into VHDL.
	// v1.1 (2026-10-13): FPGAIO slot 16 VSCNT added; every v1.0 register keeps its address and meaning.
	// v1.2 (2026-10-15, the sprite-decoder step): the cart FPGA's decoder: +14 / +16 act (the load-list queue), +12 =
	// 0x8000 starts it, FPGAIO slots 17-22 (DEC_BASE and its monitors); every v1.1 register keeps its address and meaning.
	// v1.3 (2026-10-21, the synth step, from test build 4a on, the first sound-cache test build): FPGAIO slot 14 STAMP_A
	// and slot 23 FEAT, CAUSE bit 4 BLK with CTRL bit 6 BLKIE, XLINK 0x40-0x48 (CACHE, CACHE_LOADED, BAR; XLINK decodes
	// addr[6:2]); every v1.2 register keeps its address and meaning (MCU_INTERFACE.md v1.3 section 21.6). A v1.2 image
	// runs here (minor 3 >= 2); a v1.3 image refuses v1.2.
	localparam integer IFACE_ID = 32'h5049_0103;   // MCU interface v1.3: 'P', 'I', major 1, minor 3
	// synthesis translate_off
	initial if (CLK_HZ <= 0) $fatal(1, "mcu_core: CLK_HZ is not set");
	// synthesis translate_on
	paprium_neorv32 #(
		.CLOCK_FREQUENCY(CLK_HZ),
		.USER_CODE(IFACE_ID)
	) neorv32_inst(

		.clk_i(clk),
		.rstn_i(!rst_cpu),   // Fafrium: rst, or held after a cut finisher (fw_hold_q)
		
		.wb_adr_o(rv_ad[31:0]),
		.wb_dat_i(rv_di[31:0]),
		.wb_dat_o(rv_do[31:0]),
		.wb_we_o(rv_we),
		.wb_sel_o(rv_sel[3:0]),
		.wb_stb_o(rv_stb),
		.wb_cyc_o(rv_cyc),
		.wb_ack_i(rv_ack),
		.wb_err_i(1'b0),
		.wb_src_o(rv_src),   // pocket: test build 4
		
		.gpio_o(gpio_o),
		.gpio_i(gpio_i),
		
		.mtime_irq_i(irq_tmr),
		.msw_irq_i(irq_sw),
		.mext_irq_i(irq_ext),//pocket: 1.4.8.1's irq_buf re-latches a level after the ack: flush mie (MCU_INTERFACE.md 6.3)

		// pocket: test build 4 - the tightly coupled IROM and WRAM
		.tcm_re_o(tcm_re),
		.tcm_we_o(tcm_we),
		.tcm_ben_o(tcm_ben),
		.tcm_addr_o(tcm_addr),
		.tcm_wdata_o(tcm_wdata),
		.tcm_i_rdata_i(tcm_i_rdata),
		.tcm_i_ack_i(tcm_i_ack),
		.tcm_d_rdata_i(tcm_d_rdata),
		.tcm_d_ack_i(tcm_d_ack)
	);
	
	
//****************************************** pocket: test build 4 - the tightly coupled IROM and WRAM

	mcu_tcm_irom #(.EXT_KB(IROM_KB - 32)) irom_tcm_inst(   // pocket: test build 5 (the synth build): 88 KB (EXT_KB 56, 7 slices)
		.clk(clk),
		.re(tcm_re),
		.we(tcm_we),
		.ben(tcm_ben),          // Fafrium
		.addr(tcm_addr),
		.wdata(tcm_wdata),      // Fafrium
		.wlocked(fw_go_q),      // Fafrium: stores dropped from GO on, as before
		.rdata(tcm_i_rdata),
		.ack(tcm_i_ack),
		.go(irom_go),           // Fafrium
		.fin(irom_fin)          // Fafrium
	);

	mcu_tcm_wram wram_tcm_inst(
		.clk(clk),
		.re(tcm_re),
		.we(tcm_we),
		.ben(tcm_ben),
		.addr(tcm_addr),
		.wdata(tcm_wdata),
		.wlock(wlock),
		.cw_open(~fw_go_q),     // Fafrium: the code window takes stores only before GO
		.rdata(tcm_d_rdata),
		.ack(tcm_d_ack)
	);

endmodule

//************************************************************************************* tightly coupled IROM / WRAM

// pocket: test build 4 (0.3.0 new core, the MCU fast path; the first design of our MCU speed study) - the IROM and the
// WRAM on the NEORV32's processor-internal bus, the way its own neorv32_imem / neorv32_dmem sit there: the request (re
// or we, one clock, the address, byte enables and write data on the bus in that clock) is answered by a registered ack
// in the next clock, and the read data is gated to 0 outside a read (the processor bus ORs every slave's read data).
// Before the fast path every fetch and every IROM / WRAM access was a Wishbone transaction through the gateway and
// mcu_wram's state machine: fetch 4 cycles an instruction, load 10, store 12 (measured on our RV32 cycle bench).
// Here: ALU 2, load 5, store 5 (measured in our speed study on the stock IMEM / DMEM with the same protocol; test
// build 4 re-measures it on this RTL).
// What the MCU reads and writes is unchanged: the same storage and images, the same select and index, the same
// windows and aliases (the whole regions 0x00 and 0x80: MEM_TCM_IMEM_SIZE / MEM_TCM_DMEM_SIZE in paprium_neorv32.vhd),
// the same lock rule. mcu_wram is gone; mcu_irom below is unchanged.

// The IROM, region 0x00: mcu_irom (rom0 + the 40 KB extension, mcu.txt / mcu_ext.txt), read on every rising edge from
// the bus address, aliasing every 128 KB through addr[16:0] as before. A store is acked and dropped, as before.
// Fafrium: before GO (wlocked = 0) a WORD store writes the IROM (rom0 or the extension, the stored order of dato below),
// any other store is dropped as before; a byte store to 0x7FF (byte lane 3 of word 0x1FF) is GO; a word store into
// [0, 0x800) (only the stub's finisher makes one) also raises fin (mcu_core's fw_fin_q). From GO on every
// store is acked and dropped exactly as before. The read port, its select and its index are unchanged.
module mcu_tcm_irom #(
	parameter integer EXT_KB = 40
)(
	input         clk,
	input         re,
	input         we,
	input  [3:0]  ben,      // Fafrium
	input  [31:0] addr,
	input  [31:0] wdata,    // Fafrium
	input         wlocked,  // Fafrium
	output [31:0] rdata,
	output reg    ack,
	output        go,       // Fafrium
	output        fin       // Fafrium: a word store into IROM [0, 0x800) before GO (the finisher's: mcu_core fw_fin_q)
);

	wire sel = addr[31:24] == 8'h00;
	wire wr  = we & sel & ~wlocked & (ben == 4'b1111);
	assign go = we & sel & ~wlocked & (ben == 4'b1000) & (addr[16:2] == 15'h01FF);
	assign fin = wr & (addr[16:11] == 6'd0);
	wire [31:0] dato;
	reg rd;

	initial begin
		ack = 1'b0;
		rd = 1'b0;
	end

	mcu_irom #(.EXT_KB(EXT_KB)) mcu_irom_inst(

		.clk(clk),
		.addr(addr[16:0]),//pocket: the 0.2.x CPU MATE work - 17 bits: rom0 0x0000-0x7FFF + the extension from 0x8000
		.we(wr),          // Fafrium
		.dati(wdata),     // Fafrium
		.dato(dato)
	);

	always @(posedge clk)
	begin
		rd		<= re & sel;
		ack		<= (re | we) & sel;
	end

	assign rdata = rd ? dato : 32'd0;

endmodule

// The WRAM, region 0x80: paprium_wram (memory.sv), 48 KB as four byte lanes of 12,288 words on the rising edge, word
// address addr[15:2] of the 64 KB alias (KB 48-63 not backed: loads undefined, stores dropped by the lock).
// The lock (MCU_INTERFACE.md 3.2), unchanged: KB k = addr[15:10]; KB 11-26 (the code window) and KB 48-63 always
// locked, KB 27-47 by FPGAIO WLOCK bit k-27; a locked store is acked and dropped. It is decided in the request clock
// and gates the RAM's byte write enables there: a full-cycle path now (bus address -> lock map -> M10K write enable).
// The half-cycle paths before the fast path, into and out of the negative-edge RAM (the write path of fitter seed 6,
// MCU_INTERFACE.md finding 4), are gone.
module mcu_tcm_wram (
	input         clk,
	input         re,
	input         we,
	input  [3:0]  ben,
	input  [31:0] addr,
	input  [31:0] wdata,
	input  [20:0] wlock,
	input         cw_open,  // Fafrium: 1 = the code window (KB 11-26) takes stores (only before the boot stub's GO)
	output [31:0] rdata,
	output reg    ack
);

	wire sel = addr[31:24] == 8'h80;
	// the lock map by KB of the 64 KB alias: {KB 63..48, KB 47..27, KB 26..11, KB 10..0}
	wire [63:0] lock_map = {16'hFFFF, wlock, {16{~cw_open}}, 11'd0};
	wire wok = we & sel & ~lock_map[addr[15:10]];   // a store that writes
	wire [31:0] dato;
	reg rd;

	initial begin
		ack = 1'b0;
		rd = 1'b0;
	end

	paprium_wram wram_inst(
		.clk(clk),
		.addr(addr[15:2]),
		.dati(wdata),
		.we(wok ? ben : 4'b0000),
		.dato(dato)
	);

	always @(posedge clk)
	begin
		rd		<= re & sel;
		ack		<= (re | we) & sel;
	end

	assign rdata = rd ? dato : 32'd0;

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
// pocket: the second step of our 0.2.x CPU MATE work - the IROM grew by EXT_KB KB above rom0 (EXT_KB = 22:
// 11 slices of 512x32, select on a registered addr[15], index addr[XW+1:2]). That index is only right while the
// extension stays below 32 KB: at EXT_KB = 40, XW = $clog2(10240) = 14 pulls the select bit addr[15] into the index,
// and an address with addr[16] = 1 read rom0. 10,240 of 18,432 words read wrong (measured in Icarus).
//
// pocket: 0.3.0 new core (MCU_INTERFACE.md v1.0 section 3.1) - IROM 72 KB:
//   0x00000-0x07FFF  rom0, 32 KB, 8192 x 32 (mcu.txt), 32 M10K at 8192x1, as before
//   0x08000-0x11FFF  one 40 KB extension, 10,240 x 32 (mcu_ext.txt, 16 words a line as before)
//   0x12000-0x1FFFF  not backed: reads are undefined, and the firmware never goes there
// Select and index are fixed for an extension above 32 KB: sel_x = addr[16] | addr[15], registered with
// the block-RAM address; index = {addr[16], addr[14:2]} (0x08000 -> word 0, 0x10000 -> word 8192). Both
// hold for any extension up to 64 KB. The extension is built in 2048-deep slices (2048x32 = 8 M10K at
// 2048x4): 5 slices = 40 M10K, a 5:1 slice mux, then the 2:1 against rom0 (0.2.6: 11:1 + 2:1). Same
// one-clock read as rom0, so a fetch or a load costs the same cycles (the ack comes from mcu_wram).
// pocket: test build 4 - unchanged; mcu_tcm_irom above wraps it on the processor bus (the ack comes from there now).
// pocket: synth step (test build 5, the synth build; MCU_INTERFACE.md v1.3 3.1, B Jam's decision 2 of 2026-10-21) -
// IROM 88 KB: EXT_KB = 56 (mcu_core's IROM_KB - 32,
// from FEAT[23:16]): the extension is 0x08000-0x15FFF, 14,336 x 32 (mcu_ext.txt, 16 words a line), 7 slices of 2048x32
// (7 M10K each at 2Kx5: 49, was 35), a 7:1 slice mux then the 2:1 against rom0; select and index unchanged (they hold
// for any extension up to 64 KB). 0x16000-0x1FFFF are not backed. Test builds 4a / 4b keep 72 KB (EXT_KB = 40).
// The CPU MATE brain keeps 0x5360-0xD2EB (rom0 tail + extension) with its bytes unchanged.
module mcu_irom #(
	parameter integer EXT_KB = 40                  // a multiple of 8 (whole 2048-deep slices), at most 64
)(

	input  clk,
	input  [16:0]addr,
	input  we,           // Fafrium: write the word dati at addr (the boot stub, before GO)
	input  [31:0]dati,
	output [31:0]dato
);

	localparam integer XN = EXT_KB * 256;          // extension words

	wire [31:0]di;                                 // rom0 or the extension
	assign dato = {di[7:0], di[15:8], di[23:16], di[31:24]};

	// Fafrium: the stored order is dato's (a CPU word w is kept as {w[7:0], w[15:8], w[23:16], w[31:24]}, as in the image files)
	wire [31:0]wd = {dati[7:0], dati[15:8], dati[23:16], dati[31:24]};

	(* ramstyle = "no_rw_check" *) reg[31:0]rom[32768/4];
	
	reg [31:0]di0;
	
	always @(posedge clk)
	begin
		di0		<= rom[addr[14:2]];
		if (we & ~(addr[16] | addr[15])) rom[addr[14:2]] <= wd;   // Fafrium
	end
	
	initial
	begin
		$readmemh("mcu.txt", rom);  // pocket: bare name + SEARCH_PATH ../rtl/PAPRIUM, same idiom as 68k.v
	end

	wire [13:0]xi = {addr[16], addr[14:2]};       // extension word index
	reg  [31:0]dix;
	reg  sel_x;

	(* ramstyle = "M10K, no_rw_check", max_depth = 2048 *) reg [31:0]rom_x[0:XN-1];

	always @(posedge clk)
	begin
		sel_x	<= addr[16] | addr[15];
		dix		<= rom_x[xi];
		if (we & (addr[16] | addr[15])) rom_x[xi] <= wd;   // Fafrium
	end

	initial
	begin
		$readmemh("mcu_ext.txt", rom_x);
	end

	assign di = sel_x ? dix : di0;

	// synthesis translate_off
	initial
	begin
		if (EXT_KB % 8 != 0 || EXT_KB < 8 || EXT_KB > 64)
			$fatal(1, "mcu_irom: EXT_KB = %0d, must be a multiple of 8 from 8 to 64", EXT_KB);
	end
	// synthesis translate_on

endmodule
