// ---------------------------------------------------------------------------
// Paprium CDDA ring buffer, CRAM edition (xram stage 1).
//
// The same module as paprium_cdda_buf - same parameters, same ports to core_top,
// the fetch side and the player - with the 16-M10K dpram_dif ring replaced by
// 16 KB of the Pocket's cellular PSRAM behind paprium_cram's port A. Kept as it
// was on purpose:
//   - the chunk accounting with the fetch side (wr_chunk_gray in through synch_3,
//     rd_chunk_gray out), counted in bytes delivered to the decoder, so the
//     producer still never overwrites an unread chunk;
//   - the decoder sees the same bytes in the same order through the same
//     handshake: a byte is presented the clock after it is taken (byte_pending),
//     like the old registered M10K read;
//   - fill_level / rd_data / flush keep their meaning.
//
// New: whole 16-bit words are read from CRAM ahead of the decoder into an
// 8-byte FIFO, and a word is fetched only if it lies inside what the fetch side
// has committed (bytes_avail, consumer-relative, minus what is already in the
// FIFO). One read is in flight at a time; a read that was issued before a flush
// or a reset is dropped when it returns. A CRAM read takes ~9-30 clocks against
// ~1,118 clocks per output sample, so the FIFO is full whenever the ring holds
// data and the PCM sequence cannot change.
//
// FLUSH_GUARD (default 1): after a flush, the decoder is held until the
// synchronised wr_chunk has gone back to 0. The M10K ring does not do this: its
// flush resets the read side at once, but the fetch side's wr_chunk reset
// arrives several clocks later through two clock crossings, and in between
// bytes_avail reads the old track's count, so the first frame header after a
// track change can come from the old track's bytes (seen in simulation; whether
// it is audible on hardware is not established). FLUSH_GUARD = 0 keeps the old
// rule. The guard also lasts at least FLUSH_HOLD clocks (xram review, finding
// 2): a flush that finds the old track's wr_chunk at 0 (mod 8) would otherwise
// let go at once, and an old chunk completing inside the lag (wr_chunk 0 -> 1)
// would then be read as the new track's first bytes. The lag from the flush to
// the fetch side's reset showing here is ~8-10 clk_sys (the toggle through
// synch_3 into clk_74a, the fetch FSM, its Gray register, synch_3 back), so 16
// covers it (an estimate from the RTL, not a measurement).
//
// All of this is in clk_sys; the only clock crossing is the existing Gray pair.
// ---------------------------------------------------------------------------

module paprium_cdda_buf_cram #(
	parameter CHUNK_BYTES = 4096,
	parameter NUM_CHUNKS  = 4,
	parameter CHUNK_W     = $clog2(NUM_CHUNKS),
	parameter SAMPLES_PER_CHUNK = CHUNK_BYTES / 4,
	parameter RING_SAMPLES      = SAMPLES_PER_CHUNK * NUM_CHUNKS,
	parameter ADDR_W            = $clog2(RING_SAMPLES),
	parameter RING_BYTES        = CHUNK_BYTES * NUM_CHUNKS,
	parameter BADDR_W           = $clog2(RING_BYTES),
	parameter [21:0] RING_BASE_W = 22'h200000,     // CRAM die word address of ring byte 0
	parameter FLUSH_GUARD       = 1,
	parameter FLUSH_HOLD        = 16                // clocks the guard lasts at least (<= 31)
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

	// Player side. rd_ptr is accepted and ignored, as before.
	input  wire [ADDR_W-1:0] rd_ptr,
	output wire       [31:0] rd_data,
	input  wire              sample_consumed,
	output wire [ADDR_W:0]   fill_level,

	input  wire        flush,

	// paprium_cram port A
	output reg         cr_wr,
	output reg  [21:0] cr_waddr,
	output reg  [15:0] cr_wdata,
	output reg         cr_rd,
	output reg  [21:0] cr_raddr,
	input  wire        cr_rd_done,
	input  wire [15:0] cr_rdata
);

	// ---- landing writes go straight to CRAM (one clock of register) ----
	always @(posedge clk) begin
		cr_wr    <= wr_en;
		cr_waddr <= RING_BASE_W + {{(22-ADDR_W-1){1'b0}}, wr_addr};
		cr_wdata <= wr_data;
	end

	// ---- chunk counters (unchanged) ----
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

	reg [CB_W-1:0]  rd_in_chunk;
	reg [CHUNK_W:0] rd_chunk;

	wire [CHUNK_W:0]   chunks_ahead = wr_chunk - rd_chunk;
	wire [BADDR_W+1:0] bytes_avail  =
	        ({{(BADDR_W+2-CHUNK_W-1){1'b0}}, chunks_ahead} << CB_W)
	      - {{(BADDR_W+2-CB_W){1'b0}}, rd_in_chunk};

	// ---- flush guard ----
	reg       flush_wait = 1'b0;
	reg [4:0] flush_hold = 5'd0;
	always @(posedge clk) begin
		if (reset) begin
			flush_wait <= 1'b0;
			flush_hold <= 5'd0;
		end
		else if (flush) begin
			flush_wait <= (FLUSH_GUARD != 0);
			flush_hold <= FLUSH_HOLD[4:0];
		end
		else if (flush_hold != 5'd0) flush_hold <= flush_hold - 1'd1;
		else if (wr_chunk == 0)      flush_wait <= 1'b0;
	end

	// ---- prefetch: words from CRAM into an 8-byte FIFO ----
	reg  [7:0]          fq [0:7];
	reg  [2:0]          fq_head;                 // next byte to give the decoder
	reg  [3:0]          fq_n;                    // bytes in the FIFO
	reg  [BADDR_W-2:0]  pf_word;                 // next ring word to fetch
	reg                 rd_out   = 1'b0;         // a CRAM read is outstanding (cleared ONLY by its done)
	reg                 rd_stale = 1'b0;         // ...and its data must be dropped (flush/reset since)

	wire       can_fetch = ~flush_wait & ~rd_out & ~cr_rd & (fq_n <= 4'd6) &
	                       ({{(BADDR_W-2){1'b0}}, fq_n} + 4'd2 <= bytes_avail);

	// ---- feed the decoder (same handshake as the M10K version) ----
	wire dec_byte_ready;
	reg  byte_pending;
	reg  [7:0] ring_byte;

	wire can_feed = dec_byte_ready & (fq_n != 4'd0) & ~byte_pending & ~flush_wait;

	always @(posedge clk) begin
		cr_rd <= 1'b0;

		if (cr_rd_done) rd_out <= 1'b0;

		if(reset | flush) begin
			rd_in_chunk  <= {CB_W{1'b0}};
			rd_chunk     <= {(CHUNK_W+1){1'b0}};
			byte_pending <= 1'b0;
			fq_head      <= 3'd0;
			fq_n         <= 4'd0;
			pf_word      <= {(BADDR_W-1){1'b0}};
			// a read still in flight (or being issued) returns into a buffer it no longer belongs to
			rd_stale     <= (rd_out & ~cr_rd_done) | cr_rd;
		end
		else begin
			byte_pending <= can_feed;

			if (can_fetch) begin
				cr_rd    <= 1'b1;
				cr_raddr <= RING_BASE_W + {{(22-BADDR_W+1){1'b0}}, pf_word};
				rd_out   <= 1'b1;
			end
			if (cr_rd_done) rd_stale <= 1'b0;

			begin : fifo_upd
				reg [3:0] n;
				n = fq_n;
				if (can_feed) begin
					ring_byte <= fq[fq_head];
					fq_head   <= fq_head + 1'd1;
					n = n - 1'd1;
					if(rd_in_chunk == CHUNK_BYTES[CB_W-1:0] - 1'd1) begin
						rd_in_chunk <= {CB_W{1'b0}};
						rd_chunk    <= rd_chunk + 1'd1;
					end
					else rd_in_chunk <= rd_in_chunk + 1'd1;
				end
				if (cr_rd_done & ~rd_stale) begin
					fq[fq_head + fq_n[2:0]]        <= cr_rdata[7:0];     // even byte first
					fq[fq_head + fq_n[2:0] + 3'd1] <= cr_rdata[15:8];
					pf_word <= pf_word + 1'd1;                          // wraps at the ring size
					n = n + 4'd2;
				end
				fq_n <= n;
			end
		end

		rd_chunk_gray <= (rd_chunk >> 1) ^ rd_chunk;
	end

	// ---- the decoder (unchanged) ----
	wire [15:0] dec_l, dec_r;
	wire        dec_valid;

	paprium_ima_decode decoder (
		.clk(clk),
		.reset(reset),
		.frame_start(flush),
		.byte_data(ring_byte),
		.byte_valid(byte_pending),
		.byte_ready(dec_byte_ready),
		.pcm_l(dec_l),
		.pcm_r(dec_r),
		.sample_valid(dec_valid),
		.sample_ack(sample_consumed)
	);

	assign rd_data    = {dec_r, dec_l};
	assign fill_level = {{ADDR_W{1'b0}}, dec_valid};

endmodule
