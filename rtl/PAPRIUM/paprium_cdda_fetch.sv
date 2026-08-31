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
//   /Assets/paprium/common/paprium.pcm   (built by scripts/build_cdda_adpcm.py)
//     0x00   char[4] "PPAD"
//     0x04   u32 version, u32 rate, u32 channels, u32 block_samples, u32 ntracks
//     0x18   64 entries x 16 bytes: u64 offset, u32 adpcm_bytes, u32 pcm_samples
//     0x1000 IMA ADPCM track data, concatenated
//
// The audio is IMA ADPCM, decoded in paprium_cdda_buf. THE MAGIC IS CHECKED
// BEFORE THE TABLE IS EVER WALKED: an older raw-PCM paprium.pcm parsed as this
// format yields arbitrary 64-bit offsets, and streaming from those plays as
// noise. No magic means no table walk, no reads, and a silent player - see
// S_MAGIC. That is the whole reason the probe exists.
//
// A track request reads its 16-byte table entry, then streams from that offset.
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
	input  wire  [4:0] hdr_wr_addr,        // byte address within the read (max 24)
	input  wire [15:0] hdr_wr_data,

	// Chunk flow control against the player (clk_sys), Gray coded
	input  wire [CHUNK_W:0] rd_chunk_gray,
	output reg  [CHUNK_W:0] wr_chunk_gray,

	// Status back to the MD+ adapter
	output reg         playing,
	output reg   [7:0] current_track
);

	assign target_dataslot_id = SLOT_ID;

	wire [7:0] req_track = track_num;

	// In DIAG_MODE the AUDIO comes from a fixed known-good track, not from the
	// requested one. The ten indices the scene might be asking for are exactly the
	// ones whose header length is 0, and a zero-length entry streams nothing - so
	// sourcing the bursts from the requested track would answer "silence" for
	// precisely the cases the diagnostic exists to name. The reported number stays
	// the REQUESTED one; only the bytes fed to the ring come from here.
	localparam [7:0] DIAG_SRC = 8'd5;
	wire [7:0] hdr_track = DIAG_MODE ? DIAG_SRC : current_track;

	// DIAG_MODE reports the REQUESTED track number as two audible bursts: tens
	// seconds, a pause, then units seconds. Track 41 plays 4s, pauses, plays 1s.
	// Counting two small numbers beats counting up to 62 seconds, and the whole
	// point is to learn which index a scene asks for - nobody has measured it.
	// 192000 bytes/s over 4096-byte chunks is 46.875 chunks per second.
	localparam [15:0] DIAG_CPS = 16'd47;
	wire  [3:0] diag_tens = (current_track >= 8'd60) ? 4'd6 :
	                        (current_track >= 8'd50) ? 4'd5 :
	                        (current_track >= 8'd40) ? 4'd4 :
	                        (current_track >= 8'd30) ? 4'd3 :
	                        (current_track >= 8'd20) ? 4'd2 :
	                        (current_track >= 8'd10) ? 4'd1 : 4'd0;
	wire  [7:0] diag_ones = current_track - (diag_tens * 8'd10);
	reg   [1:0] diag_phase;
	reg  [15:0] diag_chunks;
	reg  [26:0] diag_gap;
	wire [15:0] diag_target = (diag_phase == 2'd0) ? ({12'd0, diag_tens} * DIAG_CPS)
	                                               : ({8'd0,  diag_ones} * DIAG_CPS);

	// ---------------------------------------------------------------------
	// Header entry capture. data_loader delivers 16-bit words at byte addresses
	// 0,2,4,6 - the same assembly that already carries PCM samples correctly, so
	// the byte order needs no special handling here.
	// ---------------------------------------------------------------------
	reg [15:0] hdr [0:11];
	// target_dataslot_done says the COMMAND finished, but the bytes reach these
	// registers through data_loader, which has a FIFO and a 24-cycle write pipeline.
	// Sampling on done alone can read the entry before its last word has landed and
	// take a stale offset, so count the four words in.
	reg  [3:0] hdr_count;
	// Pulsed when a new header read is issued. Without it the word count from the
	// magic probe would still be standing when the table entry lands, and
	// S_HDR_WAIT would accept the entry before its own words had arrived.
	reg        hdr_clr;

	always @(posedge clk_74a) begin
		if(track_request | hdr_clr) hdr_count <= 0;
		else if(hdr_wr_en) begin
			hdr[hdr_wr_addr[4:1]] <= hdr_wr_data;
			if(hdr_count < 4'd12) hdr_count <= hdr_count + 1'd1;
		end
	end

	// ---- the 24-byte file header, valid after the S_MAGIC read ----
	// data_loader hands back little-endian 16-bit words, so hdr[0][7:0] is byte 0.
	// "PPAD" is 50 50 41 44, which is word 0 = 0x5050 and word 1 = 0x4441.
	wire        ppad_magic = (hdr[0] == 16'h5050) && (hdr[1] == 16'h4441);
	wire [31:0] f_version  = {hdr[3],  hdr[2]};
	wire [31:0] f_rate     = {hdr[5],  hdr[4]};
	wire [31:0] f_chans    = {hdr[7],  hdr[6]};
	wire [31:0] f_blk      = {hdr[9],  hdr[8]};
	wire [31:0] f_ntracks  = {hdr[11], hdr[10]};

	// Every field the decoder hardcodes is checked, not just the magic. A blob with
	// the right magic but a different block size would frame at the wrong stride and
	// decode as noise - exactly the failure this gate exists to prevent.
	wire blob_valid = ppad_magic
	               && (f_version == 32'd1)
	               && (f_rate    == 32'd48000)
	               && (f_chans   == 32'd2)
	               && (f_blk     == 32'd505)
	               && (f_ntracks >= 32'd64);

	// ---- a track's 16-byte table entry, valid after the S_HDR read ----
	wire [31:0] hdr_start  = {hdr[1], hdr[0]};   // offset, low 32 bits
	wire [31:0] hdr_off_hi = {hdr[3], hdr[2]};   // offset, high 32 - must be zero
	wire [31:0] hdr_len    = {hdr[5], hdr[4]};   // adpcm bytes, a multiple of 4096
	wire [31:0] hdr_smpls  = {hdr[7], hdr[6]};   // true sample count; see S_HDR_WAIT

	// Latched once the entry is complete. Streaming off the live wires would let a
	// later header read shift end-of-track under a track already playing.
	reg [31:0] track_start;
	reg [31:0] track_len;

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
	localparam S_MAGIC      = 4'd10,
	           S_MAGIC_ACK  = 4'd11,
	           S_MAGIC_WAIT = 4'd12,
	           S_IDLE      = 4'd0,
	           S_HDR       = 4'd1,
	           S_HDR_ACK   = 4'd2,
	           S_HDR_WAIT  = 4'd3,
	           S_READ      = 4'd4,
	           S_READ_ACK  = 4'd5,
	           S_READ_WAIT = 4'd6,
	           S_ADVANCE   = 4'd7,
	           S_DONE      = 4'd8,
	           S_DIAG_GAP  = 4'd9;

	reg  [3:0] state;
	reg        loop_this_track;
	reg [31:0] cursor;
	// A command counts as finished only once it has STARTED and then finished:
	// target_dataslot_done still holds the previous command's value until
	// core_bridge_cmd reaches TARG_ST_DATASLOTOP, several cycles after the request,
	// so waiting on done alone fires on that stale value. The timer is a backstop
	// against a command that is never acknowledged at all.
	reg [21:0] wait_timer;

	// The blob is probed once and the verdict kept. blob_checked separates "not
	// looked yet" from "looked, and it is not a PPAD blob" - without it a bad blob
	// would be re-probed on every single track change.
	reg blob_checked;
	reg blob_ok;

	always @(posedge clk_74a) begin
		target_dataslot_read <= 0;
		hdr_clr              <= 0;

		if(reset) begin
			state         <= S_IDLE;
			wr_chunk      <= 0;
			cursor        <= 0;
			playing       <= 0;
			current_track <= 0;
			wait_timer    <= 0;
			diag_phase    <= 0;
			diag_chunks   <= 0;
			diag_gap      <= 0;
			blob_checked  <= 0;
			blob_ok       <= 0;
		end
		else begin
			// A stop arriving mid-readout would truncate a burst and give a
			// believable wrong count, so DIAG_MODE defers it until the two bursts
			// have finished. They stop themselves after ~17 s at worst, and a new
			// track_request restarts the readout regardless.
			if(stop_request && !(DIAG_MODE && (state != S_IDLE))) begin
				state   <= S_IDLE;
				playing <= 0;
			end

			if(track_request) begin
				current_track   <= req_track;
				loop_this_track <= track_loop;
				wr_chunk        <= 0;
				wait_timer      <= 0;
				diag_phase      <= 0;
				diag_chunks     <= 0;
				diag_gap        <= 0;
				// Raised here rather than after the header lands, so it spans the
				// WHOLE readout. core_top uses it to suppress a stop that would
				// otherwise mute the player mid-burst.
				if(DIAG_MODE) playing <= 1;
				// The blob is vetted ONCE. It cannot change without the core being
				// relaunched, and re-probing on every track change would add a
				// round trip to each scene transition for no new information.
				if(!blob_checked)    state <= S_MAGIC;
				else if(blob_ok)     state <= S_HDR;
				else begin
					// No usable blob. Report not-playing and issue nothing at all;
					// the MCU polls mdp_playing and carries on without music.
					playing <= 0;
					state   <= S_IDLE;
				end
			end
			else case(state)

			S_IDLE: ;

			// ---- vet the blob before trusting a single byte of its table ----
			S_MAGIC: begin
				target_dataslot_slotoffset <= 32'd0;
				target_dataslot_bridgeaddr <= HDR_ADDR;
				target_dataslot_length     <= 32'd24;   // magic plus the five u32
				target_dataslot_read       <= 1;
				hdr_clr                    <= 1;
				state                      <= S_MAGIC_ACK;
			end

			S_MAGIC_ACK: begin
				wait_timer <= wait_timer + 1'd1;
				if(target_dataslot_ack) begin wait_timer <= 0; state <= S_MAGIC_WAIT; end
				else if(&wait_timer) begin
					// The slot never answered - no file loaded, most likely. Treat
					// that as "no blob" rather than retrying forever; the game must
					// not stall waiting for music it is never going to get.
					wait_timer   <= 0;
					blob_checked <= 1;
					blob_ok      <= 0;
					playing      <= 0;
					state        <= S_IDLE;
				end
			end

			S_MAGIC_WAIT: if(target_dataslot_done && (hdr_count >= 4'd12)) begin
				blob_checked <= 1;
				if(target_dataslot_err != 3'd0 || !blob_valid) begin
					blob_ok <= 0;
					playing <= 0;
					state   <= S_IDLE;
				end
				else begin
					blob_ok <= 1;
					state   <= S_HDR;
				end
			end

			// This track's 16-byte table entry: entry N at 0x18 + N*16.
			S_HDR: begin
				target_dataslot_slotoffset <= 32'h18 + {20'd0, hdr_track, 4'd0};
				target_dataslot_bridgeaddr <= HDR_ADDR;
				target_dataslot_length     <= 32'd16;
				target_dataslot_read       <= 1;
				hdr_clr                    <= 1;
				state                      <= S_HDR_ACK;
			end

			S_HDR_ACK: begin
				wait_timer <= wait_timer + 1'd1;
				if(target_dataslot_ack) begin wait_timer <= 0; state <= S_HDR_WAIT; end
				else if(&wait_timer)    begin wait_timer <= 0; state <= S_IDLE;     end
			end

			S_HDR_WAIT: if(target_dataslot_done && (hdr_count >= 4'd8)) begin
				// Length 0 means the track has no audio - one of the ten Blank.wav
				// placeholders the cue asks for, or a track the pack was missing.
				// Silence, not a hang: the MCU polls mdp_playing.
				//
				// hdr_off_hi guards the u64 offset: cursor is 32 bits, so a blob
				// over 4 GB would silently wrap and stream from the wrong place.
				// Refuse rather than play the wrong track.
				//
				// hdr_len is the PADDED byte count. build_cdda_adpcm.py rounds every
				// track up to a whole 4096-byte chunk with silence frames, so the
				// fixed-size reads below can never straddle into the next track's
				// data - that straddle is what would sound like noise. hdr_smpls is
				// the true sample count; the pad it excludes is digital silence, so
				// running into it is quiet rather than wrong. See the note in
				// docs/CDDA_DESIGN.md about tightening the seam to sample exactness.
				if(target_dataslot_err != 3'd0 || hdr_len == 0 || hdr_smpls == 0
				   || hdr_off_hi != 0) begin
					playing <= 0;
					state   <= S_IDLE;
				end
				else begin
					track_start <= hdr_start;
					track_len   <= hdr_len;
					cursor      <= hdr_start;
					playing     <= 1;
					state       <= S_READ;
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

				if(DIAG_MODE) begin
					diag_chunks <= diag_chunks + 1'd1;

					// What is being measured is the length of the burst, not the
					// length of the source, so a short source wraps rather than
					// ending the burst early.
					if((cursor + CHUNK_BYTES[31:0]) >= (track_start + track_len))
						cursor <= track_start;
					else
						cursor <= cursor + CHUNK_BYTES[31:0];

					if((diag_chunks + 1'd1) >= diag_target) begin
						if(diag_phase == 2'd0) state <= S_DIAG_GAP;
						else                   state <= S_DONE;
					end
					else state <= S_READ;
				end
				else begin
					cursor <= cursor + CHUNK_BYTES[31:0];

					if((cursor + CHUNK_BYTES[31:0]) >= (track_start + track_len))
						state <= S_DONE;
					else
						state <= S_READ;
				end
			end

			// The pause between the two bursts. Producing nothing for ~1.8 s at
			// 74.25 MHz; the ring drains in about 85 ms and the rest is silence.
			// playing stays high so the MCU does not see the track end mid-readout.
			S_DIAG_GAP: begin
				diag_gap <= diag_gap + 1'd1;
				if(&diag_gap) begin
					diag_gap    <= 0;
					diag_phase  <= 2'd2;
					diag_chunks <= 0;
					state       <= S_READ;
				end
			end

			// Honours the play command's own loop flag ($11xx one-shot, $12xx
			// loop). MiSTer cannot: Main_MiSTer's player ignores it and takes
			// looping from cue directives, which is why that project needs
			// REM NOLOOP on tracks 12, 29, 36 and 53.
			S_DONE: begin
				// DIAG_MODE never loops: the readout is two bursts, then quiet.
				if(loop_this_track && !DIAG_MODE) begin
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
