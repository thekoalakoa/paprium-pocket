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
	// Diagnostic: report openfile's outcome by how long music plays. Audio is the only
	// output channel proven to work end to end, so the readout rides on it:
	//
	//   continuous music  openfile acked and returned 0 - it worked
	//   ~1s then silence  err 1   (created and opened)
	//   ~2s then silence  err 2   (slot undefined)
	//   ~3s then silence  err 3   (file not found - the path is wrong)
	//   ~4s then silence  err 4   (malformed path)
	//   ~5s then silence  err 5   (general error)
	//   silence at once   never acknowledged - APF is not offering openfile at all
	//
	// Track 1 plays throughout either way; only the DURATION carries the answer.
	// Old meaning: skip the openfile step and stream whatever file data.json already
	// names for the slot. A deferload slot is declared to the core with its file, just
	// not preloaded, so target reads should work against it untouched. Hearing track 01
	// over everything proves reads, ring, player and mix all work and isolates the
	// fault to openfile; still-silence rules openfile out entirely.
	parameter        DIAG_MODE = 1'b0
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
	// No storage at all. The struct is a pure function of the track number and the
	// word index, so it is computed on demand.
	//
	// This started as an inferred array (which did not infer, costing ~500 ALMs in
	// flops), then a dpram_dif (correct area, M10K). Both were wrong for a subtler
	// reason: M10K registers its address, so data arrives a cycle after APF presents
	// bridge_addr. data_unloader gets away with a slow path because it PRE-FETCHES
	// and has the word waiting; a plain RAM read does not. APF therefore sampled the
	// previous word and saw "ts/genesis/..." - no leading slash - which is exactly
	// the "malformed path" (err 4) the hardware reported.
	//
	// Computing it combinationally is zero-latency, zero-storage, and cannot drift
	// out of step with the requested track.
	localparam PARAM_WORDS = 11;                 // 43-byte path rounds to 11 words
	localparam PARAM_AW    = 7;                  // struct spans 0x108 bytes

	// "/Assets/genesis/common/Paprium/track" - 35 bytes, then NN, ".pcm", NUL.
	// Held as a constant; only the two digit bytes differ between tracks.
	localparam [8*36-1:0] PATH_PREFIX =
		"/Assets/genesis/common/Paprium/track";

	// From the LATCHED track, not the live input: APF reads the struct while the
	// openfile command runs, and the path must not shift under it.
	// DIAG_MODE forces track 5 regardless of what the game asked for. That separates
	// two hypotheses the symptoms cannot: if openfile works, track 5 plays and the
	// fault is that track_num never varies; if track 1 still plays, openfile is the
	// fault. cue track 05 is "31 Bad Dudes vs Paprium", unmistakable against
	// track 1 which is "02 90's Acid Dub Character Select".
	wire [7:0] pt = DIAG_MODE ? 8'd5 : current_track;
	wire [3:0] tens = (pt >= 8'd60) ? 4'd6 :
	                  (pt >= 8'd50) ? 4'd5 :
	                  (pt >= 8'd40) ? 4'd4 :
	                  (pt >= 8'd30) ? 4'd3 :
	                  (pt >= 8'd20) ? 4'd2 :
	                  (pt >= 8'd10) ? 4'd1 : 4'd0;
	wire [7:0] ones = pt - (tens * 8'd10);

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
		// Only a non-zero size counts. A deferload slot that is not loaded can report
		// 0, and taking that as gospel made the first S_ADVANCE evaluate
		// 0 + CHUNK >= 0 as end-of-track: one chunk fetched, playing dropped, silence.
		else if(dataslot_update && dataslot_update_id == SLOT_ID
		        && dataslot_update_size != 0) begin
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
	           S_DONE      = 4'd7,
	// A command is only finished once it has STARTED and then finished. done stays
	// asserted from the previous command until core_bridge_cmd reaches
	// TARG_ST_DATASLOTOP, several cycles after the request, so waiting on done alone
	// fires on a stale value: every read after the first would "complete" instantly
	// with nothing written, and the player would drain an untouched ring as silence.
	           S_OPEN_ACK  = 4'd8,
	           S_READ_ACK  = 4'd9;

	reg  [3:0] state;
	reg        loop_this_track;
	reg [31:0] cursor;
	// If a command is never acknowledged - an APF that does not offer openfile, say -
	// waiting forever is silence with no way back. ~56 ms at 74 MHz, far longer than
	// any SD access, then carry on regardless: a wrong track is better than no audio
	// and says plainly what happened.
	reg [21:0] wait_timer;

	// Diagnostic capture: did the command start, and what did it report
	reg        saw_ack;
	reg  [2:0] open_err;
	// wr_chunk is the ring pointer and wraps at NUM_CHUNKS, so it cannot count a
	// duration. This one is absolute, reset per track.
	reg [15:0] chunks_done;
	// 3 seconds of audio per error code. One second per unit was too fine for hand
	// timing: readings spread 0.45 s across a 1.02 s unit, straddling err 3 and 4.
	// 48 kHz stereo is 192000 bytes/s, so 144
	// chunks of 4096 is 3.07 s, and the codes land 3 s apart.
	wire [15:0] diag_limit = saw_ack ? ({13'd0, open_err} * 16'd144) : 16'd1;

	always @(posedge clk_74a) begin
		target_dataslot_read     <= 0;
		target_dataslot_openfile <= 0;

		if(reset) begin
			state         <= S_IDLE;
			wr_chunk      <= 0;
			cursor        <= 0;
			playing       <= 0;
			current_track <= 0;
			wait_timer    <= 0;
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
				saw_ack         <= 0;
				open_err        <= 0;
				chunks_done     <= 0;
				state           <= S_PARAM;
			end
			else case(state)

			S_IDLE: ;

			// Write the path, then flags = 0 and size = 0: the file must exist
			// already, so neither create nor resize is wanted.
			// Nothing to stage any more - the struct is computed on demand. One
			// cycle here lets current_track settle before openfile reads the path.
			S_PARAM: state <= S_OPEN;

			S_OPEN: begin
				target_dataslot_openfile <= 1;

				state                    <= S_OPEN_ACK;
			end

			S_OPEN_ACK: begin
				wait_timer <= wait_timer + 1'd1;
				if(target_dataslot_ack)  begin wait_timer <= 0; saw_ack <= 1; state <= S_OPEN_WAIT; end
				else if(&wait_timer)     begin wait_timer <= 0; playing <= 1; state <= S_READ; end
			end

			// openfile has finished. Whatever it reported, stream the slot as it now
			// stands rather than going quiet: the bypass build proved reads work
			// without openfile, so a failure stays audible and which track plays says
			// plainly whether openfile did anything at all.
			S_OPEN_WAIT: if(target_dataslot_done) begin
				open_err <= target_dataslot_err;
				playing <= 1;
				state   <= S_READ;
			end

			S_READ: if(ring_has_room) begin
				target_dataslot_slotoffset <= cursor;
				target_dataslot_length     <= CHUNK_BYTES[31:0];
				target_dataslot_read       <= 1;
				state                      <= S_READ_ACK;
			end

			S_READ_ACK: begin
				wait_timer <= wait_timer + 1'd1;
				if(target_dataslot_ack)  begin wait_timer <= 0; state <= S_READ_WAIT; end
				else if(&wait_timer)     begin wait_timer <= 0; state <= S_DONE;      end
			end

			S_READ_WAIT: if(target_dataslot_done) begin
				if(target_dataslot_err != 3'd0) state <= S_DONE;
				else                            state <= S_ADVANCE;
			end

			S_ADVANCE: begin
				wr_chunk    <= wr_chunk + 1'd1;
				chunks_done <= chunks_done + 1'd1;
				cursor   <= cursor + CHUNK_BYTES[31:0];

				// Diagnostic builds cut the track short to spell out the error code;
				// diag_limit is 0 for err 0, which means "do not cut it short".
				if(DIAG_MODE && (diag_limit != 0) && (chunks_done + 1'd1 >= diag_limit))
					state <= S_DONE;
				else if(track_bytes_valid && (cursor + CHUNK_BYTES[31:0] >= track_bytes))
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
	// Word of the struct APF is currently addressing, computed on the spot.
	wire [6:0]  param_widx = bridge_addr[PARAM_AW+1:2];
	wire [31:0] param_q    = (param_widx < PARAM_WORDS[6:0]) ? path_word(param_widx)
	                                                         : 32'd0;

	assign param_rd_data = bridge_endian_little
	                     ? param_q
	                     : {param_q[7:0], param_q[15:8], param_q[23:16], param_q[31:24]};

endmodule
