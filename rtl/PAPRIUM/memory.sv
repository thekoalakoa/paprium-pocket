// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)


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
//
// pocket: the second step of our 0.2.x CPU MATE work (code in block RAM) - part of the CPU MATE's code lives
// in this RAM's unused middle, loaded with the bitstream: wram_hi.txt / wram_lo.txt (16,384 bytes each, one hex byte
// per line; ram_hi = the MCU's EVEN bytes, ram_lo = the ODD bytes, see mcu_wram's byte swap), written by
// the firmware build's image step; all zero outside the code window, i.e. today's power-up contents. Nothing in
// the core clears this RAM (no reset path), crt0 touches only .data/.bss, so the code survives every
// MCU / soft reset and is reloaded only with the bitstream. As a guard, MCU writes into the code
// window are dropped: LOCK_MAP bit k = 1 locks the k-th KB of the 32 KB (byte addr[14:10], i.e. word
// addr[13:9]; every alias above 32 KB maps onto the same cells). A runaway store or a stack overflow
// then cannot damage the code that the next reset would run. Default: KB 11..26 = the code window
// 0x2C00-0x6BFF (that step's layout; 0x6C00-0x7FFF stays the stack: the firmware's own worst case is
// 4,240 B, the 0xF5 stamp rescale with its 4 KB local buffer). LOCK_MAP = 0 restored the old behaviour (0.2.x).
//
// pocket: 0.3.0 new core (the firmware's docs/MCU_INTERFACE.md v1.0 section 3.2) - 48 KB: 24,576 words, word address
// addr[15:1] of the MCU's 64 KB alias (KB 48-63 are not backed: mcu_wram drops every store there, loads are
// undefined). The lock left this module: mcu_wram decides each store in its first clock (the constant window KB 11-26,
// KB 48-63, and FPGAIO WLOCK for KB 27-47) and drives `we` from flops, so nothing here sits between the address and
// the write enable. Images wram_lo.txt / wram_hi.txt: 24,576 lines each (a shorter file fills the start). Layout
// (the firmware's pocket72k): data 0x0000-0x2BFF, code window 0x2C00-0x6BFF, upper data 0x6C00-0xABFF, stack to 0xBFFF.
//
// pocket: test build 4 (the 0.3.0 hardware test build of the MCU fast path, part of the new core) - four byte lanes of
// 12,288 words (48 KB), rising edge, on the NEORV32's processor bus through mcu_tcm_wram (mcu_core.sv), which drives
// the byte write enables (already gated by the region and the lock) and the word address addr[15:2] of the MCU's 64 KB
// alias. Lane i holds MCU byte 4 x word + i (RISC-V little-endian: data bits 8i+7:8i). Same 48 KB and the same bytes as
// the 16-bit version it replaces (ram_hi = the even bytes = lanes 0 / 2, ram_lo = the odd bytes = lanes 1 / 3); the
// negative edge is gone with mcu_wram (the processor bus registers the read like neorv32_dmem). Images wram_b0.txt ..
// wram_b3.txt: 12,288 lines each, one hex byte a line, line k = MCU byte 4k + i (the firmware's tools/mkimage.py and
// this repository's scripts/firmware/mkimage.py write them; a shorter file fills the start). no_rw_check: a store's
// clock never uses the read data (mcu_tcm_wram gates it with the read flag), so Quartus needs no read-during-write
// logic.
module paprium_wram
(
	input         clk,
	input  [13:0] addr,   // 32-bit word address (12,288 words backed = 48 KB; 12,288-16,383 = KB 48-63, not backed)
	input  [31:0] dati,
	input  [3:0]  we,     // byte lanes: we[i] writes dati[8i+7:8i]; already gated by mcu_tcm_wram
	output [31:0] dato
);

	localparam integer WORDS = 12288;

	(* ramstyle = "no_rw_check" *) reg [7:0] ram_b0 [WORDS];
	(* ramstyle = "no_rw_check" *) reg [7:0] ram_b1 [WORDS];
	(* ramstyle = "no_rw_check" *) reg [7:0] ram_b2 [WORDS];
	(* ramstyle = "no_rw_check" *) reg [7:0] ram_b3 [WORDS];
	reg [7:0] q0, q1, q2, q3;

	always @(posedge clk)
	begin
		if (we[0]) ram_b0[addr] <= dati[7:0];
		if (we[1]) ram_b1[addr] <= dati[15:8];
		if (we[2]) ram_b2[addr] <= dati[23:16];
		if (we[3]) ram_b3[addr] <= dati[31:24];
		q0 <= ram_b0[addr];
		q1 <= ram_b1[addr];
		q2 <= ram_b2[addr];
		q3 <= ram_b3[addr];
	end

	assign dato = {q3, q2, q1, q0};

	initial
	begin
		$readmemh("wram_b0.txt", ram_b0);   // pocket: bare names, SEARCH_PATH as mcu.txt (test build 4: four byte lanes)
		$readmemh("wram_b1.txt", ram_b1);
		$readmemh("wram_b2.txt", ram_b2);
		$readmemh("wram_b3.txt", ram_b3);
	end

endmodule
