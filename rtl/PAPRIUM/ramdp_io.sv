// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)


module ramdp_io(
	
	input  McuBus mcu,
	input  CpuBus cpu,
	
	output [31:0]mcu_dati,
	output reg   mcu_ack,   // pocket: test build 4 - registered: the second bus clock of the access, held until it ends

	output [15:0]cpu_dati,

	output        debug_ramdp_write,
	output        debug_ramdp_vector_write,
	output [10:0]debug_ramdp_addr,
	output [31:0]debug_ramdp_data,

	// 68k -> RAMDP write-path observation (diagnostic).
	// debug_cpu_we_act : the write CONDITION holds (ce_lo & addr<8192 & either strobe).
	// debug_cpu_write  : the store PULSE fires (after cpu_we_st capture; either strobe, register page included).
	output        debug_cpu_we_act,
	output        debug_cpu_write,

	// pocket: 0.3.0 new core - the 68000 sees the cart register file at $1FE0-$1FFF (paprium_regfile), not RAMDP (the cart
	// RAM that both the 68000 and the MCU see). Its view and page flag are registered on this clock like the RAM read;
	// 68000 writes there leave RAMDP alone (the cells behind it are MCU-only). debug_cpu_write stays the ungated pulse,
	// page included (cmdlog, mailbox)
	input  [15:0]reg_cpu_dati,
	input        reg_cpu_page,
	output       cpu_we_strobe
);
	
	assign cpu_dati		= reg_cpu_page ? reg_cpu_dati : cpu.addr[1] == 0 ? cpu_dati_32[15:0] : cpu_dati_32[31:16];
	wire cpu_page_w		= cpu.addr[12:5] == 8'hFF;   // pocket: 0.3.0 new core
	
	// pocket: 0.3.0 new core (the firmware's docs/MCU_INTERFACE.md 3.3) - addr[23] = 1 is the RAMDP byte view
	// (0x0280_0000, the chip's 0x6886_0000): the same RAM read with the two bytes of each halfword swapped, so MCU byte A
	// = 68000 byte A. Read only: a store through it is dropped. addr[23] = 0 is the halfword view, unchanged
	wire mcu_bv				= mcu.addr[23];
	wire mcu_ce				= mcu.ce & mcu.map.ramdp;
	// pocket: test build 4 (the 0.3.0 hardware test build of the MCU fast path, part of the new core) - the registered
	// ack. The MCU port reads its M10K on every rising edge from mcu.addr, and before the fast path paprium_cart acked
	// RAMDP with the constant 1: the word the CPU got was the one at the address the bus showed in the clock BEFORE the
	// access's bus clock. That was right only because the 1.4.8.1 gateway copies the processor bus's address while idle,
	// and the slow Wishbone fetch left the data address there a clock early. With the IROM / WRAM tightly coupled the
	// fetch address shows there instead, and 21 of the 31 c00 read-backs of our RV32 cycle bench fail (measured in our MCU
	// speed study). Now: the ack comes in the access's second bus clock (registered, held while the request lasts, as
	// FPGAIO's), so the word read is the one at the access's own address (registered at the end of its first clock); a
	// store writes in the first clock only, once, as before. Cost: +1 clock a RAMDP access.
	wire mcu_first			= mcu_ce & ~mcu_ack;          // the access's first bus clock
	wire mcu_ce_w			= mcu_first & ~mcu_bv;
	initial mcu_ack = 1'b0;
	always @(posedge mcu.clk)
		mcu_ack			<= mcu_ce;
	wire [3:0]mcu_ramdp_we	= {mcu_ce_w & mcu.we[3], mcu_ce_w & mcu.we[2], mcu_ce_w & mcu.we[1], mcu_ce_w & mcu.we[0]};
	wire [31:0]mcu_ram_q;
	assign mcu_dati			= mcu_bv ? {mcu_ram_q[23:16], mcu_ram_q[31:24], mcu_ram_q[7:0], mcu_ram_q[15:8]} : mcu_ram_q;
	assign debug_ramdp_write = |mcu_ramdp_we;
	assign debug_ramdp_vector_write = debug_ramdp_write & (mcu.addr[12:2] < 11'd4);
	assign debug_ramdp_addr = mcu.addr[12:2];
	assign debug_ramdp_data = mcu.dato;
	
	wire [31:0]cpu_dati_32;
	wire [7:0]cpu_dati_lo;
	wire [3:0]cpu_we;
	
	// pocket: 0.3.0 new core (B Jam's choice for 68000 byte writes: the whole word) - a 68000 write into cart RAM writes
	// the whole word whichever byte strobe it carries. The 68000 puts a byte on both halves of the data bus, so a byte
	// write stores the byte in both halves of its word, as the game's own byte-lane self-test ($2B83E) expects of the
	// cart; 0.2.x's per-lane writes failed it and set the copy-protection flag $FF9986. This replaces 0.2.6's
	// ignore rule (92e0b62: byte writes dropped). 0.2.6's Scum! coin path made two stray cart byte writes per coin
	// ($0F80, $0FD0), which this rule would store; the new core's Scum! coin stub (part of its Hall of Fame bar fix) makes
	// none, so this rule ships only together with that fix
	wire cpu_we_word		= cpu.we_lo | cpu.we_hi;
	assign cpu_we[0]		= cpu_we_ck & ~cpu_page_w & cpu_we_word & cpu.addr[1] == 0;
	assign cpu_we[1]		= cpu_we_ck & ~cpu_page_w & cpu_we_word & cpu.addr[1] == 0;
	assign cpu_we[2]		= cpu_we_ck & ~cpu_page_w & cpu_we_word & cpu.addr[1] == 1;
	assign cpu_we[3]		= cpu_we_ck & ~cpu_page_w & cpu_we_word & cpu.addr[1] == 1;
		
	wire cpu_we_ck			= cpu_we_st[2:0] == 'b011;
	wire cpu_we_act		= cpu.ce_lo & cpu.addr < 8192 & (cpu.we_lo | cpu.we_hi);

	assign debug_cpu_we_act = cpu_we_act;
	assign debug_cpu_write  = cpu_we_ck & (cpu.we_lo | cpu.we_hi);   // pocket: 0.3.0 new core - |cpu_we without the page gate
	assign cpu_we_strobe    = cpu_we_ck;
	
	reg [3:0]cpu_we_st;
	always @(posedge mcu.clk)
	begin
		cpu_we_st	<= {cpu_we_st[2:0], cpu_we_act};
	end
	
	
	ram_dp8 ram_dp_0(

		
		.clk_a(mcu.clk),
		.dati_a(mcu.dato[7:0]),
		.addr_a(mcu.addr[12:2]),
		.we_a(mcu_ramdp_we[0]),
		.dato_a(mcu_ram_q[7:0]),
		
		.clk_b(mcu.clk),
		.dati_b(cpu.dato[7:0]),
		.addr_b(cpu.addr[12:2]),
		.we_b(cpu_we[0]),
		.dato_b(cpu_dati_32[7:0])
	);
	
	
	ram_dp8 ram_dp_1(
		
		.clk_a(mcu.clk),
		.dati_a(mcu.dato[15:8]),
		.addr_a(mcu.addr[12:2]),
		.we_a(mcu_ramdp_we[1]),
		.dato_a(mcu_ram_q[15:8]),
		
		
		.clk_b(mcu.clk),
		.dati_b(cpu.dato[15:8]),
		.addr_b(cpu.addr[12:2]),
		.we_b(cpu_we[1]),
		.dato_b(cpu_dati_32[15:8])
	);
	
	
	ram_dp8 ram_dp_2(

		.clk_a(mcu.clk),
		.dati_a(mcu.dato[23:16]),
		.addr_a(mcu.addr[12:2]),
		.we_a(mcu_ramdp_we[2]),
		.dato_a(mcu_ram_q[23:16]),
		
		.clk_b(mcu.clk),
		.dati_b(cpu.dato[7:0]),
		.addr_b(cpu.addr[12:2]),
		.we_b(cpu_we[2]),
		.dato_b(cpu_dati_32[23:16])
	);
	
	ram_dp8 ram_dp_3(
		
		.clk_a(mcu.clk),
		.dati_a(mcu.dato[31:24]),
		.addr_a(mcu.addr[12:2]),
		.we_a(mcu_ramdp_we[3]),
		.dato_a(mcu_ram_q[31:24]),
		
		
		.clk_b(mcu.clk),
		.dati_b(cpu.dato[15:8]),
		.addr_b(cpu.addr[12:2]),
		.we_b(cpu_we[3]),
		.dato_b(cpu_dati_32[31:24])
	);
	
endmodule
