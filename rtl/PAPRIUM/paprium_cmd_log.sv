// ---------------------------------------------------------------------------
// Paprium mailbox command logger - diagnostic build only.
//
// Every Paprium cartridge command is a single 16-bit write by the 68000 to cart
// RAM offset 0x1FEA, with the command in the high byte and its parameter in the
// low byte (GPGX `paprium_w16` / `paprium_cmd`, paprium.h:2658/2074). The MCU
// polls that location; nothing in this port's RTL decodes it, so the only way to
// learn what the game actually asks for is to watch the write go past.
//
// Note this is NOT the MD+ protocol paprium_mdp_adapter.sv decodes ($11xx/$12xx).
// That is the CDDA overlay this port added. These are Paprium's own commands.
//
// What it is for: the boss / large-enemy death cue plays an ordinary enemy's
// sound instead of sample 0x1C. Three explanations survive, and they need
// different fixes:
//
//   0xD11C logged at the kill  -> requested correctly, so we play the wrong
//                                 sample. Ours, and fixable.
//   a different 0xD1nn         -> the game asked for the ordinary sound; the
//                                 divergence is earlier, in game state.
//   no 0xD1 near the kill      -> the cue arrives by a path our firmware mutes
//                                 (0xD3 sfx_loop, or 0x88 audio_setting).
//
// Every command is logged, not just 0xD1, because "which commands fire around
// the event" is the question - and 0x88/0xB0 are already suspected of being
// muted in this firmware build.
//
// Layout, 1024 words of 32 bits = 4096 bytes, read back through its own APF data
// slot (never the save slot - that is the player's progress):
//
//   word 0 .. 1022 : ring of commands, oldest overwritten
//                    [31:16] the 16-bit command word written to 0x1FEA
//                    [15: 0] the channel mask latched from 0x1E10
//   word 1023      : {16'hC0DE, 6'd0, wr_idx} - where the newest entry landed
//
// The mask matters because sfx_play takes it as the set of channels it may
// allocate from, and sfx.c evicts the oldest channel within that mask.
// ---------------------------------------------------------------------------

module paprium_cmd_log (
	input  wire        clk,
	input  wire        reset,

	// 68k -> cart RAM write, as seen by ramdp_io
	input  wire        cpu_wr,       // one-cycle pulse, any byte lane
	input  wire [12:0] cpu_addr,     // byte address within the 8 KB cart RAM
	input  wire [15:0] cpu_data,     // the 16-bit value being written

	// APF read-back port. data_unloader only supports byte-wide reads - its
	// apf_bridge_write_data[31-WORD_SIZE:0] slice degenerates at 32 bits - so the
	// word is served a byte at a time, most significant first, which makes a
	// hexdump of the file read as the 32-bit values directly.
	input  wire [11:0] read_addr,
	output reg   [7:0] read_data
);

	// Byte offsets, halved because a 16-bit write is addressed by cpu_addr[12:1]
	localparam [11:0] A_CMD  = 12'hFF5;   // 0x1FEA >> 1 - the command dispatch
	localparam [11:0] A_MASK = 12'hF08;   // 0x1E10 >> 1 - sfx channel mask

	wire [11:0] wr_word = cpu_addr[12:1];

	wire hit_cmd  = cpu_wr & (wr_word == A_CMD);
	wire hit_mask = cpu_wr & (wr_word == A_MASK);

	// The mask is written just before the command, so latching it and pairing it
	// with the next command word is enough - no ordering games needed.
	reg [15:0] last_mask;

	reg [9:0]  wr_idx;

	reg        mem_we;
	reg [9:0]  mem_waddr;
	reg [31:0] mem_wdata;

	always @(posedge clk) begin
		mem_we <= 1'b0;

		if(reset) begin
			wr_idx    <= 10'd0;
			last_mask <= 16'd0;
		end
		else begin
			if(hit_mask) last_mask <= cpu_data;

			if(hit_cmd) begin
				mem_we    <= 1'b1;
				mem_waddr <= wr_idx;
				mem_wdata <= {cpu_data, last_mask};

				// 0..1022; word 1023 is the header
				wr_idx <= (wr_idx == 10'd1022) ? 10'd0 : wr_idx + 1'd1;
			end
		end
	end

	// The header is rewritten on the cycle after each entry, so a capture taken at
	// any moment names the newest entry. Costs one extra write per command, which
	// is nothing at command rates.
	reg        hdr_we;
	always @(posedge clk) hdr_we <= mem_we;

	wire        ram_we    = mem_we | hdr_we;
	wire [9:0]  ram_waddr = hdr_we ? 10'd1023 : mem_waddr;
	wire [31:0] ram_wdata = hdr_we ? {16'hC0DE, 6'd0, wr_idx} : mem_wdata;

	// Written as a plain inferred dual-port RAM: one write port, one registered
	// read port, no read-during-write games. 1024 x 32 = 32 Kbit.
	reg [31:0] mem[1024];

	always @(posedge clk) if(ram_we) mem[ram_waddr] <= ram_wdata;

	reg [31:0] rd_word;
	reg  [1:0] rd_sel;
	always @(posedge clk) begin
		rd_word <= mem[read_addr[11:2]];
		rd_sel  <= read_addr[1:0];
	end

	always @(*) begin
		case(rd_sel)
			2'd0: read_data = rd_word[31:24];
			2'd1: read_data = rd_word[23:16];
			2'd2: read_data = rd_word[15:8];
			2'd3: read_data = rd_word[7:0];
		endcase
	end

endmodule
