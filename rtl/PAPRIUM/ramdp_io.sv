

module ramdp_io(
	
	input  McuBus mcu,
	input  CpuBus cpu,
	
	output [31:0]mcu_dati,
	
	output [15:0]cpu_dati,

	output        debug_ramdp_write,
	output        debug_ramdp_vector_write,
	output [10:0]debug_ramdp_addr,
	output [31:0]debug_ramdp_data,

	// 68k -> RAMDP write-path observation (diagnostic).
	// debug_cpu_we_act : the write CONDITION holds (ce_lo & addr<8192 & we strobe).
	// debug_cpu_write  : the actual byte write PULSE fires (after cpu_we_st capture).
	output        debug_cpu_we_act,
	output        debug_cpu_write
);
	
	assign cpu_dati		= cpu.addr[1] == 0 ? cpu_dati_32[15:0] : cpu_dati_32[31:16];
	
	wire mcu_ce				= mcu.ce & mcu.map.ramdp;
	wire [3:0]mcu_ramdp_we	= {mcu_ce & mcu.we[3], mcu_ce & mcu.we[2], mcu_ce & mcu.we[1], mcu_ce & mcu.we[0]};
	assign debug_ramdp_write = |mcu_ramdp_we;
	assign debug_ramdp_vector_write = debug_ramdp_write & (mcu.addr[12:2] < 11'd4);
	assign debug_ramdp_addr = mcu.addr[12:2];
	assign debug_ramdp_data = mcu.dato;
	
	wire [31:0]cpu_dati_32;
	wire [7:0]cpu_dati_lo;
	wire [3:0]cpu_we;
	
	assign cpu_we[0]		= cpu_we_ck & cpu.we_lo & cpu.addr[1] == 0;
	assign cpu_we[1]		= cpu_we_ck & cpu.we_hi & cpu.addr[1] == 0;
	assign cpu_we[2]		= cpu_we_ck & cpu.we_lo & cpu.addr[1] == 1;
	assign cpu_we[3]		= cpu_we_ck & cpu.we_hi & cpu.addr[1] == 1;
		
	wire cpu_we_ck			= cpu_we_st[2:0] == 'b011;
	wire cpu_we_act		= cpu.ce_lo & cpu.addr < 8192 & (cpu.we_lo | cpu.we_hi);

	assign debug_cpu_we_act = cpu_we_act;
	assign debug_cpu_write  = |cpu_we;
	
	reg [3:0]cpu_we_st;
	always @(posedge mcu.clk)
	begin
		cpu_we_st	<= {cpu_we_st[2:0], cpu_we_act};
	end
	
	
	ram_dp8 ram_dp_0(

		
		.clk_a(mcu.clk),
		.dati_a(mcu.dato[7:0]),
		.addr_a(mcu.addr[12:2]),
		.we_a(mcu_ce & mcu.we[0]),
		.dato_a(mcu_dati[7:0]),
		
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
		.we_a(mcu_ce & mcu.we[1]),
		.dato_a(mcu_dati[15:8]),
		
		
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
		.we_a(mcu_ce & mcu.we[2]),
		.dato_a(mcu_dati[23:16]),
		
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
		.we_a(mcu_ce & mcu.we[3]),
		.dato_a(mcu_dati[31:24]),
		
		
		.clk_b(mcu.clk),
		.dati_b(cpu.dato[15:8]),
		.addr_b(cpu.addr[12:2]),
		.we_b(cpu_we[3]),
		.dato_b(cpu_dati_32[31:24])
	);
	
endmodule
