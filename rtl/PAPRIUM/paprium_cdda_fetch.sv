// ---------------------------------------------------------------------------
// Paprium CDDA fetch - the producer half of the background-music path.
//
// Replaces MiSTer's HPS. There, Linux reads WAV tracks named by a .cue and fills
// a DDR3 ring buffer. Here the core drives APF directly:
//
//   0x0192 openfile  points the streaming data slot at /Assets/genesis/common/
//                    Paprium/trackNN.pcm, NN from mdp_track_num
//   0x0180 read      pulls CHUNK bytes at a time into the BRIDGE landing address,
//                    where a data_loader instance catches the writes and puts
//                    them in the ring buffer
//
// One slot, repointed per track: APF allows a core only 32 data slots and Paprium
// has 62 tracks, so slot-per-track is not an option. See docs/CDDA_DESIGN.md.
//
// Everything here is in the clk_74a bridge domain. Flow control with the player
// (clk_sys) is at CHUNK granularity - a chunk is tens of milliseconds of audio,
// so the counters crossing between domains change slowly and a Gray-coded pair
// of synchronisers is ample.
//
// Assets are headerless 48 kHz 16-bit stereo little-endian PCM, so there is no
// RIFF parsing: the file is sample data from byte 0.
// ---------------------------------------------------------------------------

module paprium_cdda_fetch #(
	parameter [15:0] SLOT_ID      = 16'd300,      // deferload slot in data.json
	parameter [31:0] LANDING_ADDR = 32'h30000000, // BRIDGE address the ring lives at
	parameter [31:0] PARAM_ADDR   = 32'h40000000, // BRIDGE address of the param struct
	parameter        CHUNK_BYTES  = 4096,
	parameter        NUM_CHUNKS   = 4,
	parameter        CHUNK_W      = $clog2(NUM_CHUNKS),
	// Diagnostic: skip the openfile step and stream whatever file data.json already
	// names for the slot. A deferload slot is declared to the core with its file, just
	// not preloaded, so target reads should work against it untouched. Hearing track 01
	// over everything proves reads, ring, player and mix all work and isolates the
	// fault to openfile; still-silence rules openfile out entirely.
	parameter        SKIP_OPENFILE = 1'b0
) (
	input  wire        clk_74a,
	input  wire        reset,

	// MD+ command channel, synchronised into this domain by the caller
	input  wire        track_request,      // one-cycle pulse
	input  wire  [7:0] track_num,
	input  wire        track_loop,
	input  wire        stop_request,

	// Slot size, latched from APF's data slot update for our slot
	input  wire        dataslot_update,
	input  wire [15:0] dataslot_update_id,
	input  wire [31:0] dataslot_update_size,

	// APF target command interface
	output reg         target_dataslot_read,
	output reg         target_dataslot_openfile,
	input  wire        target_dataslot_ack,
	input  wire        target_dataslot_done,
	input  wire  [2:0] target_dataslot_err,
	output wire [15:0] target_dataslot_id,
	output reg  [31:0] target_dataslot_slotoffset,
	output wire [31:0] target_dataslot_bridgeaddr,
	output reg  [31:0] target_dataslot_length,
	output wire [31:0] target_buffer_param_struct,

	// Param struct readback to the bridge (same clock domain)
	input  wire        bridge_rd,
	input  wire        bridge_endian_little,
	input  wire [31:0] bridge_addr,
	output wire [31:0] param_rd_data,

	// Chunk flow control against the player (clk_sys), Gray coded
	input  wire [CHUNK_W:0] rd_chunk_gray,
	output reg  [CHUNK_W:0] wr_chunk_gray,

	// Status back to the MD+ adapter
	output reg         playing,
	output reg   [7:0] current_track
);

	assign target_dataslot_id         = SLOT_ID;
	assign target_buffer_param_struct = PARAM_ADDR;

	// ---------------------------------------------------------------------
	// Param struct: 256-byte null-terminated path at 0x000, flags at 0x100,
	// size at 0x104. APF reads it when openfile starts. Held in a small block
	// RAM rather than registers - 264 bytes of flops would be absurd.
	// ---------------------------------------------------------------------
	// Instantiated rather than inferred. An inferred array here did NOT become
	// block RAM - the write sits inside the main sequencer's always block, which
	// is enough to defeat inference - and 66 words of flops plus a 66-way 32-bit
	// read mux cost over 500 ALMs on a device that had 743 spare. dpram_dif is the
	// same primitive paprium_backup uses, so this is guaranteed M10K.
	localparam PARAM_WORDS = 66;                 // 0x108 bytes
	localparam PARAM_AW    = 7;                  // 128 words, covers the struct

	wire [31:0] param_q;
	reg  [31:0] param_wdata;
	reg         param_we;
	reg   [6:0] param_idx;   // declared here: the RAM instance below uses it
	// param_we and param_wdata register on the same edge that param_idx advances,
	// so the write address has to be captured with them or it lands one word late
	reg   [6:0] param_waddr;

	dpram_dif #(PARAM_AW, 32, PARAM_AW, 32) param_ram
	(
		.clock(clk_74a),

		.address_a(param_waddr[PARAM_AW-1:0]),
		.data_a(param_wdata),
		.wren_a(param_we),
		.q_a(),

		.address_b(bridge_addr[PARAM_AW+1:2]),
		.data_b(32'd0),
		.wren_b(1'b0),
		.q_b(param_q)
	);

	// "/Assets/genesis/common/Paprium/track" - 35 bytes, then NN, ".pcm", NUL.
	// Held as a constant and written into param_ram a word at a time on a track
	// change; only the two digit bytes ever differ between tracks.
	localparam [8*36-1:0] PATH_PREFIX =
		"/Assets/genesis/common/Paprium/track";

	wire [3:0] tens = (track_num >= 8'd60) ? 4'd6 :
	                  (track_num >= 8'd50) ? 4'd5 :
	                  (track_num >= 8'd40) ? 4'd4 :
	                  (track_num >= 8'd30) ? 4'd3 :
	                  (track_num >= 8'd20) ? 4'd2 :
	                  (track_num >= 8'd10) ? 4'd1 : 4'd0;
	wire [7:0] ones = track_num - (tens * 8'd10);

	// Byte i of the path, counting from the start of the string. Verilog packs a
	// string literal with its FIRST character in the MOST significant bits, so
	// indexing has to run backwards through PATH_PREFIX; building the word with a
	// plain concatenation instead would silently reverse every group of four.
	function automatic [7:0] path_byte(input integer i);
		begin
			if      (i < 36)  path_byte = PATH_PREFIX[8*(36-i)-1 -: 8];
			else if (i == 36) path_byte = 8'h30 + {4'd0, tens};   // tens digit
			else if (i == 37) path_byte = 8'h30 + ones[3:0];      // ones digit
			else if (i == 38) path_byte = ".";
			else if (i == 39) path_byte = "p";
			else if (i == 40) path_byte = "c";
			else if (i == 41) path_byte = "m";
			else              path_byte = 8'h00;                  // NUL and padding
		end
	endfunction

	// Word w of the struct, byte 0 of the path in bits [7:0] of word 0
	function automatic [31:0] path_word(input integer w);
		begin
			path_word = {path_byte(4*w+3), path_byte(4*w+2),
			             path_byte(4*w+1), path_byte(4*w)};
		end
	endfunction

	// ---------------------------------------------------------------------
	// Track length. APF reports slot size through dataslot_update; openfile on
	// a new file re-reports it. Until one arrives the length is unknown and the
	// stream runs until a read errors, which is the safe fallback.
	// ---------------------------------------------------------------------
	reg [31:0] track_bytes;
	reg        track_bytes_valid;

	always @(posedge clk_74a) begin
		if(reset) begin
			track_bytes       <= 0;
			track_bytes_valid <= 0;
		end
		else if(track_request) track_bytes_valid <= 0;   // new file, size unknown again
		else if(dataslot_update && dataslot_update_id == SLOT_ID) begin
			track_bytes       <= dataslot_update_size;
			track_bytes_valid <= 1;
		end
	end

	// ---------------------------------------------------------------------
	// Chunk flow control. wr_chunk counts chunks written, rd_chunk chunks the
	// player has finished. Both cross domains Gray coded; at CHUNK granularity
	// they step tens of milliseconds apart, so a two-flop synchroniser is far
	// more margin than needed.
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

	wire [CHUNK_W:0] rd_chunk  = gray2bin(rd_chunk_sync);
	wire [CHUNK_W:0] chunks_in_flight = wr_chunk - rd_chunk;
	wire             ring_has_room    = (chunks_in_flight < NUM_CHUNKS[CHUNK_W:0]);

	always @(posedge clk_74a) wr_chunk_gray <= (wr_chunk >> 1) ^ wr_chunk;

	assign target_dataslot_bridgeaddr =
		LANDING_ADDR + (wr_chunk[CHUNK_W-1:0] * CHUNK_BYTES);

	// ---------------------------------------------------------------------
	// Main sequencer
	// ---------------------------------------------------------------------
	localparam S_IDLE      = 4'd0,
	           S_PARAM     = 4'd1,
	           S_OPEN      = 4'd2,
	           S_OPEN_WAIT = 4'd3,
	           S_READ      = 4'd4,
	           S_READ_WAIT = 4'd5,
	           S_ADVANCE   = 4'd6,
	           S_DONE      = 4'd7;

	reg  [3:0] state;
	reg        loop_this_track;
	reg [31:0] cursor;

	always @(posedge clk_74a) begin
		target_dataslot_read     <= 0;
		param_we                 <= 0;
		target_dataslot_openfile <= 0;

		if(reset) begin
			state         <= S_IDLE;
			wr_chunk      <= 0;
			cursor        <= 0;
			playing       <= 0;
			current_track <= 0;
			param_idx     <= 0;
		end
		else begin
			// A stop or a new track always wins over whatever is in flight
			if(stop_request) begin
				state   <= S_IDLE;
				playing <= 0;
			end

			if(track_request) begin
				current_track   <= track_num;
				loop_this_track <= track_loop;
				cursor          <= 0;
				wr_chunk        <= 0;
				param_idx       <= 0;
				state           <= S_PARAM;
			end
			else case(state)

			S_IDLE: ;

			// Write the path, then flags = 0 and size = 0: the file must exist
			// already, so neither create nor resize is wanted.
			S_PARAM: begin
				param_we    <= 1;
				param_waddr <= param_idx;
				param_wdata <= (param_idx < 7'd11)
				                        ? path_word(param_idx)
				                        : 32'd0;
				if(param_idx == PARAM_WORDS-1) begin
					if(SKIP_OPENFILE) playing <= 1;
					param_idx <= 0;
					state     <= SKIP_OPENFILE ? S_READ : S_OPEN;
				end
				else param_idx <= param_idx + 1'd1;
			end

			S_OPEN: begin
				target_dataslot_openfile <= 1;

				state                    <= S_OPEN_WAIT;
			end

			S_OPEN_WAIT: if(target_dataslot_done) begin
				// err 3 = file not found. A missing track is silence, not a
				// hang: the MCU polls mdp_playing and would wait forever.
				if(target_dataslot_err != 3'd0) begin
					playing <= 0;
					state   <= S_IDLE;
				end
				else begin
					playing <= 1;
					state   <= S_READ;
				end
			end

			S_READ: if(ring_has_room) begin
				target_dataslot_slotoffset <= cursor;
				target_dataslot_length     <= CHUNK_BYTES[31:0];
				target_dataslot_read       <= 1;
				state                      <= S_READ_WAIT;
			end

			S_READ_WAIT: if(target_dataslot_done) begin
				if(target_dataslot_err != 3'd0) state <= S_DONE;
				else                            state <= S_ADVANCE;
			end

			S_ADVANCE: begin
				wr_chunk <= wr_chunk + 1'd1;
				cursor   <= cursor + CHUNK_BYTES[31:0];

				if(track_bytes_valid && (cursor + CHUNK_BYTES[31:0] >= track_bytes))
					state <= S_DONE;
				else
					state <= S_READ;
			end

			// End of file. Looping restarts the cursor; a one-shot drops
			// playing so the firmware's poll sees the track finish.
			//
			// Note this honours the play command's own loop flag ($11xx one
			// shot, $12xx loop). MiSTer could not - Main_MiSTer's MD+ player
			// ignores it and takes looping from cue directives, which is why
			// that project needs REM NOLOOP on tracks 12/29/36/53. Those four
			// are the ones to check on hardware here.
			S_DONE: begin
				if(loop_this_track) begin
					cursor <= 0;
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

	// ---------------------------------------------------------------------
	// Param struct readback. APF reads the struct over the bridge while the
	// openfile command runs. The RAM's own registered output is the read data -
	// core_top only selects this into bridge_rd_data for PARAM_ADDR, so there is
	// nothing to gate here.
	// ---------------------------------------------------------------------
	// The bridge is big-endian unless bridge_endian_little says otherwise, and every
	// other read path in this shell swaps for it - data_unloader.sv:200 is the
	// reference. Returning raw words reversed each group of four path bytes, which is
	// a garbled path and an openfile that always answers "file not found".
	assign param_rd_data = bridge_endian_little
	                     ? param_q
	                     : {param_q[7:0], param_q[15:8], param_q[23:16], param_q[31:24]};

endmodule
