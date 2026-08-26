// ---------------------------------------------------------------------------
// Paprium CDDA ring buffer - joins the fetch side to the player.
//
// APF lands data slot reads as BRIDGE writes, which a data_loader instance
// catches and presents as a byte/word stream in the clk_sys domain. Those go in
// here 16 bits at a time; the player takes them out 32 bits at a time, one
// 32-bit word being one stereo sample {right, left}. dpram_dif's mixed-width
// support does that conversion in the RAM itself rather than in logic.
//
// Flow control is at CHUNK granularity. The fetch side counts chunks written,
// this side counts chunks drained, and each crosses to the other Gray coded. A
// chunk is tens of milliseconds of audio, so the counters step far apart and a
// three-flop synchroniser is ample - which is the whole reason for doing flow
// control on chunks rather than on samples.
//
// Buffer placement: block RAM, deliberately. The Phase 1 plan assumed memory
// would be the scarce resource and earmarked cram0/cram1 for this. Measurement
// said otherwise - the fit sits at 55% memory and 96% ALM - so spending BRAM to
// avoid a PSRAM controller's logic is the right way round.
// ---------------------------------------------------------------------------

module paprium_cdda_buf #(
	parameter CHUNK_BYTES = 4096,
	parameter NUM_CHUNKS  = 4,
	parameter CHUNK_W     = $clog2(NUM_CHUNKS),
	// One sample is 4 bytes. Ring geometry follows from the chunk shape.
	parameter SAMPLES_PER_CHUNK = CHUNK_BYTES / 4,
	parameter RING_SAMPLES      = SAMPLES_PER_CHUNK * NUM_CHUNKS,
	parameter ADDR_W            = $clog2(RING_SAMPLES)
) (
	input  wire        clk,
	input  wire        reset,

	// Write side: data_loader output, 16-bit words, already in this domain
	input  wire        wr_en,
	input  wire [ADDR_W:0] wr_addr,      // 16-bit word index within the ring
	input  wire [15:0] wr_data,

	// Chunk accounting with the fetch side (clk_74a), Gray coded
	input  wire [CHUNK_W:0] wr_chunk_gray,
	output reg  [CHUNK_W:0] rd_chunk_gray,

	// Player side
	input  wire [ADDR_W-1:0] rd_ptr,
	output wire       [31:0] rd_data,
	input  wire              sample_consumed,
	output wire [ADDR_W:0]   fill_level,

	// Cleared on a track change so stale audio is never played
	input  wire        flush
);

	// ---- the ring itself: 16-bit write port, 32-bit read port ----
	dpram_dif #(ADDR_W+1, 16, ADDR_W, 32) ring
	(
		.clock(clk),

		.address_a(wr_addr),
		.data_a(wr_data),
		.wren_a(wr_en),
		.q_a(),

		.address_b(rd_ptr),
		.data_b(32'd0),
		.wren_b(1'b0),
		.q_b(rd_data)
	);

	// ---- chunk counters ----
	function automatic [CHUNK_W:0] gray2bin(input [CHUNK_W:0] g);
		integer i;
		begin
			gray2bin[CHUNK_W] = g[CHUNK_W];
			for(i = CHUNK_W-1; i >= 0; i = i - 1)
				gray2bin[i] = gray2bin[i+1] ^ g[i];
		end
	endfunction

	wire [CHUNK_W:0] wr_chunk_sync;
	synch_3 #(.WIDTH(CHUNK_W+1)) wr_chunk_synch (
		.i(wr_chunk_gray), .o(wr_chunk_sync), .clk(clk)
	);
	wire [CHUNK_W:0] wr_chunk = gray2bin(wr_chunk_sync);

	// Position within the current chunk, and how many whole chunks the player has
	// finished. rd_chunk is the same width as wr_chunk and wraps the same way, so
	// the subtraction below stays correct across the wrap - the extra top bit is
	// what distinguishes a full ring from an empty one.
	localparam SPC_W = $clog2(SAMPLES_PER_CHUNK);

	reg [SPC_W-1:0]  rd_in_chunk;
	reg [CHUNK_W:0]  rd_chunk;

	always @(posedge clk) begin
		if(reset || flush) begin
			rd_in_chunk <= 0;
			rd_chunk    <= 0;
		end
		else if(sample_consumed) begin
			if(rd_in_chunk == SAMPLES_PER_CHUNK[SPC_W-1:0] - 1'd1) begin
				rd_in_chunk <= 0;
				rd_chunk    <= rd_chunk + 1'd1;
			end
			else rd_in_chunk <= rd_in_chunk + 1'd1;
		end

		rd_chunk_gray <= (rd_chunk >> 1) ^ rd_chunk;
	end

	// Whole chunks the fetch side is ahead by, less how far into the current one
	// the player already is. Never negative: the player cannot pass the writer,
	// because it stops when fill_level reaches zero.
	wire [CHUNK_W:0] chunks_ahead = wr_chunk - rd_chunk;

	assign fill_level = ({{(ADDR_W-CHUNK_W){1'b0}}, chunks_ahead} * SAMPLES_PER_CHUNK)
	                    - {{(ADDR_W+1-SPC_W){1'b0}}, rd_in_chunk};

endmodule
