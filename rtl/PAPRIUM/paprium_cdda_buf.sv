// ---------------------------------------------------------------------------
// Paprium CDDA ring buffer - joins the fetch side to the player.
//
// APF lands data slot reads as BRIDGE writes, which a data_loader instance
// catches and presents as a byte/word stream in the clk_sys domain. Those go in
// here 16 bits at a time.
//
// THE RING NOW HOLDS COMPRESSED IMA FRAMES, NOT PCM. A paprium_ima_decode
// instance sits between the RAM and the player and turns 512-byte frames into
// 505 stereo samples each. See docs/CDDA_DESIGN.md.
//
// Why the decoder is on this side: holding PCM instead would mean a 4096-byte
// fetch expands to 16,160 bytes, so four chunks is ~50 M10K against 14 spare.
// Holding compressed frames keeps the same 16 KB ring and raises buffering from
// 0.085 s to 0.337 s, and cuts SD fetch bandwidth 4x as well.
//
// The player is unchanged. It still sees "a 32-bit stereo sample, and a
// fill_level that is zero when there is nothing to play". Its rd_ptr is a purely
// sequential counter that nothing else consumes - it went only to this module -
// so it is accepted and ignored rather than removed, to keep core_top's wiring
// identical.
//
// Flow control with the fetch side is still at CHUNK granularity, but counted in
// BYTES CONSUMED BY THE DECODER rather than samples emitted, because a chunk is
// now 4096 compressed bytes rather than 1024 samples. A chunk is tens of
// milliseconds either way, so the Gray-coded counters still step far apart.
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
	// Kept for interface compatibility with the player and core_top. The ring is
	// sized in bytes now; these describe the PCM the decoder produces.
	parameter SAMPLES_PER_CHUNK = CHUNK_BYTES / 4,
	parameter RING_SAMPLES      = SAMPLES_PER_CHUNK * NUM_CHUNKS,
	parameter ADDR_W            = $clog2(RING_SAMPLES),
	// Ring in bytes: same physical RAM, addressed a byte at a time for the decoder
	parameter RING_BYTES        = CHUNK_BYTES * NUM_CHUNKS,
	parameter BADDR_W           = $clog2(RING_BYTES)
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

	// Player side. rd_ptr is accepted and ignored - see the header note.
	input  wire [ADDR_W-1:0] rd_ptr,
	output wire       [31:0] rd_data,
	input  wire              sample_consumed,
	output wire [ADDR_W:0]   fill_level,

	// Cleared on a track change so stale audio is never played
	input  wire        flush
);

	// ---- the ring: 16-bit write port, 8-bit read port for the decoder ----
	reg  [BADDR_W-1:0] rd_byte;
	wire [7:0]         ring_byte;

	dpram_dif #(ADDR_W+1, 16, BADDR_W, 8) ring
	(
		.clock(clk),

		.address_a(wr_addr),
		.data_a(wr_data),
		.wren_a(wr_en),
		.q_a(),

		.address_b(rd_byte),
		.data_b(8'd0),
		.wren_b(1'b0),
		.q_b(ring_byte)
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

	localparam CB_W = $clog2(CHUNK_BYTES);

	reg [CB_W-1:0]  rd_in_chunk;    // bytes consumed within the current chunk
	reg [CHUNK_W:0] rd_chunk;

	// Whole chunks the fetch side is ahead by, in bytes, less how far into the
	// current one the decoder has read. Never negative: the decoder is stalled
	// when this reaches zero.
	wire [CHUNK_W:0]   chunks_ahead = wr_chunk - rd_chunk;
	wire [BADDR_W+1:0] bytes_avail  =
	        ({{(BADDR_W+2-CHUNK_W-1){1'b0}}, chunks_ahead} << CB_W)
	      - {{(BADDR_W+2-CB_W){1'b0}}, rd_in_chunk};

	// ---- feed the decoder ------------------------------------------------
	// dpram_dif registers its read, so a byte is valid the cycle AFTER the
	// address is presented. byte_pending tracks that one-cycle latency; without
	// it the decoder would latch the previous byte and the whole stream shifts
	// by one, which decodes at full amplitude and sounds like noise.
	wire dec_byte_ready;
	reg  byte_pending;

	wire can_feed = dec_byte_ready & (bytes_avail != 0) & ~byte_pending;

	always @(posedge clk) begin
		if(reset | flush) begin
			rd_byte      <= {BADDR_W{1'b0}};
			rd_in_chunk  <= {CB_W{1'b0}};
			rd_chunk     <= {(CHUNK_W+1){1'b0}};
			byte_pending <= 1'b0;
		end
		else begin
			byte_pending <= can_feed;

			if(can_feed) begin
				rd_byte <= rd_byte + 1'd1;      // wraps naturally at RING_BYTES
				if(rd_in_chunk == CHUNK_BYTES[CB_W-1:0] - 1'd1) begin
					rd_in_chunk <= {CB_W{1'b0}};
					rd_chunk    <= rd_chunk + 1'd1;
				end
				else rd_in_chunk <= rd_in_chunk + 1'd1;
			end
		end

		rd_chunk_gray <= (rd_chunk >> 1) ^ rd_chunk;
	end

	// ---- the decoder -----------------------------------------------------
	wire [15:0] dec_l, dec_r;
	wire        dec_valid;

	paprium_ima_decode decoder (
		.clk(clk),
		.reset(reset),
		// A track change lands the fetch side on a frame boundary, so resyncing
		// the decoder here is exactly right - it must not carry a half-decoded
		// frame's predictor across a seek.
		.frame_start(flush),
		.byte_data(ring_byte),
		.byte_valid(byte_pending),
		.byte_ready(dec_byte_ready),
		.pcm_l(dec_l),
		.pcm_r(dec_r),
		.sample_valid(dec_valid),
		.sample_ack(sample_consumed)
	);

	// The player expects {right, left} in one 32-bit word, and reads it the cycle
	// after it moves its pointer. The decoder holds a sample until acked, so this
	// is already stable.
	assign rd_data = {dec_r, dec_l};

	// The player only ever tests fill_level for zero, and counts an underrun when
	// it wanted a sample and found none. Reporting "one sample is ready" is both
	// literally true and exactly the condition it needs; a byte count would let it
	// consume while the decoder was still mid-frame.
	assign fill_level = {{ADDR_W{1'b0}}, dec_valid};

endmodule
