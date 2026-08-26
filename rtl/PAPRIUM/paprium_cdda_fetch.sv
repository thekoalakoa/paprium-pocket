// ---------------------------------------------------------------------------
// Paprium CDDA fetch - the producer half of the background-music path.
//
// Replaces MiSTer's HPS. There, the FPGA never opens a file: hps_ext forwards the
// track request over EXT_BUS and Linux (Main_MiSTer's mdplus.cpp) parses the cue,
// opens the WAV and fills a DDR3 ring. The Pocket has no such layer, so the core
// has to find its own audio.
//
// It does that by seeking inside ONE data slot. APF caps a core at 32 slots and
// Paprium has 62 tracks, so slot-per-track is impossible; repointing a slot with
// the 0x0192 openfile target command was tried at length and always answered
// "malformed path" (err 4, confirmed on hardware by timing playback against a
// duration-encoded error readout). Rather than keep guessing at an undocumented
// struct, the track index moves out of the filesystem and into the file:
//
//   /Assets/genesis/common/Paprium/paprium.pcm
//     0x000  64 entries x 8 bytes: u32 start offset, u32 length (little-endian)
//     0x200  track data, concatenated
//
// A track request reads its 8-byte header entry, then streams from that offset.
// Everything here rides on target_dataslot_slotoffset reads, which is the one
// mechanism hardware has confirmed end to end.
//
// Everything runs in the clk_74a bridge domain. Flow control with the player
// (clk_sys) is at CHUNK granularity - a chunk is tens of milliseconds, so the
// counters crossing between domains move slowly and Gray coding is ample.
// ---------------------------------------------------------------------------

module paprium_cdda_fetch #(
	parameter [15:0] SLOT_ID      = 16'd300,      // the one streaming slot
	parameter [31:0] LANDING_ADDR = 32'h30000000, // BRIDGE address the ring lives at
	parameter [31:0] HDR_ADDR     = 32'h50000000, // BRIDGE address header reads land at
	parameter        CHUNK_BYTES  = 4096,
	parameter        NUM_CHUNKS   = 4,
	parameter        CHUNK_W      = $clog2(NUM_CHUNKS),
	// Forces track 5 regardless of the request, to confirm header indexing works
	// without needing the game to change scene.
	parameter        DIAG_MODE    = 1'b0
) (
	input  wire        clk_74a,
	input  wire        reset,

	// MD+ command channel, synchronised into this domain by the caller
	input  wire        track_request,      // one-cycle pulse
	input  wire  [7:0] track_num,
	input  wire        track_loop,
	input  wire        stop_request,

	// APF target command interface
	output reg         target_dataslot_read,
	input  wire        target_dataslot_ack,
	input  wire        target_dataslot_done,
	input  wire  [2:0] target_dataslot_err,
	output wire [15:0] target_dataslot_id,
	output reg  [31:0] target_dataslot_slotoffset,
	output reg  [31:0] target_dataslot_bridgeaddr,
	output reg  [31:0] target_dataslot_length,

	// Header entry landing, from its own small data_loader
	input  wire        hdr_wr_en,
	input  wire  [2:0] hdr_wr_addr,        // byte address within the 8-byte entry
	input  wire [15:0] hdr_wr_data,

	// Chunk flow control against the player (clk_sys), Gray coded
	input  wire [CHUNK_W:0] rd_chunk_gray,
	output reg  [CHUNK_W:0] wr_chunk_gray,

	// Status back to the MD+ adapter
	output reg         playing,
	output reg   [7:0] current_track
);

	assign target_dataslot_id = SLOT_ID;

	wire [7:0] req_track = DIAG_MODE ? 8'd5 : track_num;

	// ---------------------------------------------------------------------
	// Header entry capture. data_loader delivers 16-bit words at byte addresses
	// 0,2,4,6 - the same assembly that already carries PCM samples correctly, so
	// the byte order needs no special handling here.
	// ---------------------------------------------------------------------
	reg [15:0] hdr [0:3];
	always @(posedge clk_74a) if(hdr_wr_en) hdr[hdr_wr_addr[2:1]] <= hdr_wr_data;

	wire [31:0] track_start = {hdr[1], hdr[0]};
	wire [31:0] track_len   = {hdr[3], hdr[2]};

	// ---------------------------------------------------------------------
	// Chunk flow control
	// ---------------------------------------------------------------------
	reg  [CHUNK_W:0] wr_chunk;
	wire [CHUNK_W:0] rd_chunk_sync;

	synch_3 #(.WIDTH(CHUNK_W+1)) rd_chunk_synch (
		.i(rd_chunk_gray), .o(rd_chunk_sync), .clk(clk_74a)
	);

	function automatic [CHUNK_W:0] gray2bin(input [CHUNK_W:0] g);
		integer i;
		begin
			gray2bin[CHUNK_W] = g[CHUNK_W];
			for(i = CHUNK_W-1; i >= 0; i = i - 1)
				gray2bin[i] = gray2bin[i+1] ^ g[i];
		end
	endfunction

	wire [CHUNK_W:0] rd_chunk         = gray2bin(rd_chunk_sync);
	wire [CHUNK_W:0] chunks_in_flight = wr_chunk - rd_chunk;
	wire             ring_has_room    = (chunks_in_flight < NUM_CHUNKS[CHUNK_W:0]);

	always @(posedge clk_74a) wr_chunk_gray <= (wr_chunk >> 1) ^ wr_chunk;

	// ---------------------------------------------------------------------
	// Sequencer
	// ---------------------------------------------------------------------
	localparam S_IDLE      = 4'd0,
	           S_HDR       = 4'd1,
	           S_HDR_ACK   = 4'd2,
	           S_HDR_WAIT  = 4'd3,
	           S_READ      = 4'd4,
	           S_READ_ACK  = 4'd5,
	           S_READ_WAIT = 4'd6,
	           S_ADVANCE   = 4'd7,
	           S_DONE      = 4'd8;

	reg  [3:0] state;
	reg        loop_this_track;
	reg [31:0] cursor;
	// A command counts as finished only once it has STARTED and then finished:
	// target_dataslot_done still holds the previous command's value until
	// core_bridge_cmd reaches TARG_ST_DATASLOTOP, several cycles after the request,
	// so waiting on done alone fires on that stale value. The timer is a backstop
	// against a command that is never acknowledged at all.
	reg [21:0] wait_timer;

	always @(posedge clk_74a) begin
		target_dataslot_read <= 0;

		if(reset) begin
			state         <= S_IDLE;
			wr_chunk      <= 0;
			cursor        <= 0;
			playing       <= 0;
			current_track <= 0;
			wait_timer    <= 0;
		end
		else begin
			if(stop_request) begin
				state   <= S_IDLE;
				playing <= 0;
			end

			if(track_request) begin
				current_track   <= req_track;
				loop_this_track <= track_loop;
				wr_chunk        <= 0;
				wait_timer      <= 0;
				state           <= S_HDR;
			end
			else case(state)

			S_IDLE: ;

			// Fetch this track's 8-byte header entry: entry N at file offset N*8
			S_HDR: begin
				target_dataslot_slotoffset <= {21'd0, current_track, 3'd0};
				target_dataslot_bridgeaddr <= HDR_ADDR;
				target_dataslot_length     <= 32'd8;
				target_dataslot_read       <= 1;
				state                      <= S_HDR_ACK;
			end

			S_HDR_ACK: begin
				wait_timer <= wait_timer + 1'd1;
				if(target_dataslot_ack) begin wait_timer <= 0; state <= S_HDR_WAIT; end
				else if(&wait_timer)    begin wait_timer <= 0; state <= S_IDLE;     end
			end

			S_HDR_WAIT: if(target_dataslot_done) begin
				// Length 0 means the track has no audio - one of the ten Blank.wav
				// placeholders the cue asks for, or a track the pack was missing.
				// Silence, not a hang: the MCU polls mdp_playing.
				if(target_dataslot_err != 3'd0 || track_len == 0) begin
					playing <= 0;
					state   <= S_IDLE;
				end
				else begin
					cursor  <= track_start;
					playing <= 1;
					state   <= S_READ;
				end
			end

			S_READ: if(ring_has_room) begin
				target_dataslot_slotoffset <= cursor;
				target_dataslot_bridgeaddr <= LANDING_ADDR +
				                              (wr_chunk[CHUNK_W-1:0] * CHUNK_BYTES);
				target_dataslot_length     <= CHUNK_BYTES[31:0];
				target_dataslot_read       <= 1;
				state                      <= S_READ_ACK;
			end

			S_READ_ACK: begin
				wait_timer <= wait_timer + 1'd1;
				if(target_dataslot_ack) begin wait_timer <= 0; state <= S_READ_WAIT; end
				else if(&wait_timer)    begin wait_timer <= 0; state <= S_DONE;      end
			end

			S_READ_WAIT: if(target_dataslot_done) begin
				if(target_dataslot_err != 3'd0) state <= S_DONE;
				else                            state <= S_ADVANCE;
			end

			S_ADVANCE: begin
				wr_chunk <= wr_chunk + 1'd1;
				cursor   <= cursor + CHUNK_BYTES[31:0];

				if((cursor + CHUNK_BYTES[31:0]) >= (track_start + track_len))
					state <= S_DONE;
				else
					state <= S_READ;
			end

			// Honours the play command's own loop flag ($11xx one-shot, $12xx
			// loop). MiSTer cannot: Main_MiSTer's player ignores it and takes
			// looping from cue directives, which is why that project needs
			// REM NOLOOP on tracks 12, 29, 36 and 53.
			S_DONE: begin
				if(loop_this_track) begin
					cursor <= track_start;
					state  <= S_READ;
				end
				else begin
					playing <= 0;
					state   <= S_IDLE;
				end
			end

			default: state <= S_IDLE;
			endcase
		end
	end

endmodule
