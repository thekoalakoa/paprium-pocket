

module ram_dp8(

	input clk_a,
	input [7:0]dati_a,
	input [10:0]addr_a,
	input we_a,
	output reg [7:0]dato_a,
	
	input clk_b,
	input [7:0]dati_b,
	input [10:0]addr_b,
	input we_b,
	output reg [7:0]dato_b
);

	
	reg [7:0]ram[2048];
	integer init_i;
	initial begin
		// Debug build sentinel: unwritten RAMDP reads as A5A5 instead of stale/zero data.
		for (init_i = 0; init_i < 2048; init_i = init_i + 1) ram[init_i] = 8'hA5;
	end
	
	always @(posedge clk_a)
	begin
	
		dato_a 			<= we_a ? dati_a : ram[addr_a];
		
		if(we_a)
		begin
			ram[addr_a] <= dati_a;
		end
	end
	
	always @(posedge clk_b)
	begin
	
		dato_b 			<= we_b ? dati_b : ram[addr_b];
		
		if(we_b)
		begin
			ram[addr_b] <= dati_b;
		end
	end
	
endmodule


module ram_dp16(

	input clk_a,
	input [15:0]dati_a,
	input [15:0]addr_a,
	input we_a,
	output reg [15:0]dato_a,
	
	input clk_b,
	input [15:0]dati_b,
	input [15:0]addr_b,
	input we_b,
	output reg [15:0]dato_b
);

	
	reg [15:0]ram[65536];

	always @(posedge clk_a)
	begin

		dato_a 			<= we_a ? dati_a : ram[addr_a];

		if(we_a)
		begin
			ram[addr_a] <= dati_a;
		end
	end

	always @(posedge clk_b)
	begin

		dato_b 			<= we_b ? dati_b : ram[addr_b];

		if(we_b)
		begin
			ram[addr_b] <= dati_b;
		end
	end

endmodule


// On-chip replacement for the Paprium MCU work-RAM (WRM).
//
// On the original Paprium board WRM is a 512 KB asynchronous 16-bit SRAM with
// single-cycle, combinational reads. The mcu_wram state machine in mcu_core.sv
// is built around that behaviour: it presents an address and reads the data
// back within the same clock the address is driven. The MiSTer port has no such
// SRAM, so this module emulates it with on-chip block RAM.
//
// To match the async-SRAM single-cycle read timing without modifying the
// mcu_wram state machine, the RAM is clocked on the NEGATIVE edge: the address
// presented at a rising edge is latched half a cycle later and its data is
// available at the next rising edge, exactly as a combinational async read
// appears to the rising-edge state machine.
//
// Size: 16 K x 16 = 32 KB. The firmware uses WRAM only for .data/.bss
// (0x00000-0x0145C) at the bottom and a stack near 0x3FFFC at the top, with no
// heap (verified: the MCU firmware performs no dynamic allocation). The full
// 512 KB SRAM address space is aliased into 32 KB via the low word-address bits
// (addr[13:0]); the .bss/.data cluster maps to the bottom (ends ~0x145C) and the
// stack to the top (0x3FFFC -> 0x7FFC), leaving ~27 KB of unused middle that is
// never accessed, so there is no collision. WROM fetches (read-only, data
// sourced from the internal IROM) also alias-read this RAM harmlessly and never
// write it. 32 KB (32 M10K) is paired with the reclaimed PCM RAM so the design
// fits the device's 553 M10K blocks.
module paprium_wram
(
	input         clk,
	input  [13:0] addr,   // 16-bit word address (16K words = 32 KB)
	input  [15:0] dati,
	input  [1:0]  we,     // we[1] = lower byte (D[7:0]), we[0] = upper byte (D[15:8])
	output [15:0] dato
);

	reg [7:0] ram_lo [16384];
	reg [7:0] ram_hi [16384];
	reg [15:0] dout;

	always @(negedge clk)
	begin
		if (we[1]) ram_lo[addr] <= dati[7:0];
		if (we[0]) ram_hi[addr] <= dati[15:8];
		dout <= {ram_hi[addr], ram_lo[addr]};
	end

	assign dato = dout;

endmodule
