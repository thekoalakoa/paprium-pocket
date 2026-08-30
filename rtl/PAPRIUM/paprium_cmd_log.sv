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
// SOUND COMMANDS ONLY, and a deep ring, because the two events of interest are in
// DIFFERENT LEVELS and this game has no save - reaching the second punk TV means
// playing level 1 and most of level 2, so one capture has to survive an enormous
// number of commands. Sprite traffic (0xAD/0xAE/0xAF) dominates by orders of
// magnitude and would flush the ring many times over before the second TV; audio
// commands are comparatively rare, so filtering to them is what makes a single
// playthrough enough. 0x88 and 0xB0 are kept despite 0xB0 being a sprite command,
// because both are recorded upstream as muted in this firmware build.
//
// Layout, 4096 words of 32 bits = 16384 bytes, read back through its own APF data
// slot (never the save slot - that is the player's progress):
//
//   TWO words per entry, 2047 entries:
//     word 2n   : [31:16] the 16-bit command word written to 0x1FEA
//                 [15: 0] the channel mask latched from 0x1E10
//     word 2n+1 : [31:16] the flags latched from 0x1E16
//                 [15: 0] the volume latched from 0x1E12
//   word 4095   : {16'hC0DE, armed, frozen, 2'd0, wr_idx}
//                 armed  - 0x1C or 0x4A was seen at least once
//                 frozen - logging stopped after its tail, so the window is kept
//
// The FLAGS are why this is two words. GPGX applies per-voice effects from them -
// echo (0x4000), amplify (0x100) and two pitch shifts (0x8000, 0x2000) - and this
// port implements only the pitch pair. A cue that is "close but not quite right"
// is most likely the same sample without its echo, so knowing which flags the game
// asks for is the difference between guessing and knowing.
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

	// paprium: channel-7 state, logged as synthetic entries. The mailbox capture
	// proved the REQUEST for the punk-TV cue is correct, so the open question is
	// what the channel does with it: does the volume register actually take the
	// ramp, and does the MCU keep feeding samples after the first 4.99 s pass?
	input  wire [10:0] ch7_vol,
	input  wire        ch7_empty,
	input  wire        ch7_wr,      // pulses per PCM word pushed by the MCU

	// APF read-back port. data_unloader only supports byte-wide reads - its
	// apf_bridge_write_data[31-WORD_SIZE:0] slice degenerates at 32 bits - so the
	// word is served a byte at a time, most significant first, which makes a
	// hexdump of the file read as the 32-bit values directly.
	input  wire [13:0] read_addr,
	output reg   [7:0] read_data
);

	// Byte offsets, halved because a 16-bit write is addressed by cpu_addr[12:1]
	localparam [11:0] A_CMD  = 12'hFF5;   // 0x1FEA >> 1 - the command dispatch
	localparam [11:0] A_MASK = 12'hF08;   // 0x1E10 >> 1 - sfx channel mask

	wire [11:0] wr_word = cpu_addr[12:1];

	localparam [11:0] A_VOL   = 12'hF09;  // 0x1E12 >> 1 - volume
	localparam [11:0] A_FLAGS = 12'hF0B;  // 0x1E16 >> 1 - flags

	// LOG_ALL: capture EVERY command, not just audio. Needed for questions that are
	// not about sound - grunt names that do not vary, and the muted 0xB0/0xD6 that
	// GPGX implements - where the point is seeing what fires around an event.
	//
	// With the filter off, sprite traffic (0xAD/0xAE/0xAF) fills 2047 entries in
	// seconds, so the ring must NOT wrap: it fills once from boot and freezes,
	// giving boot plus the first enemies. Dedup still applies and buys back a lot,
	// since sprite commands repeat heavily.
	//
	// Set to 0 to restore the audio-only filter used for the punk-TV work.
	localparam LOG_ALL = 1'b0;

	// BUDGET_ONLY: log just 0xEC, which sets the VRAM block budget. It fires a
	// handful of times per level, so one capture survives all the way to the
	// elevator - where LOG_ALL fills from boot and stops long before.
	//
	// The budget arrives in cmd_args[1] (cart RAM 0x1E12), which this logger
	// already records as the `vol` field. mame.c clamps it at 0x35 = 53, and that
	// is exactly VRAM: slots 0-48 map to tiles 16-799, slots 49-52 to 1984-2047.
	// A request above 53 means the game expects a VRAM layout other than the one
	// mega-ppm reconstructs, which would explain the elevator artefacts.
	localparam BUDGET_ONLY = 1'b0;

	// DEST_ONLY (Probe B): log 0xDA and 0xDB destinations, plus 0xEC as a rare
	// SCENE MARKER - the budget changes per scene and fires only a handful of
	// times per level, so it costs almost no ring and shows which entries belong
	// to INTERCOM rather than boot or the cell room. Frame markers (0xAE/0xAF)
	// would be better still but fire 60x a second and would drown the commands
	// being measured.
	//
	// No dedup here: every occurrence carries its own destination, so collapsing
	// repeats on (cmd,param) would throw the data away.
	localparam DEST_ONLY = 1'b0;

	// DMA_ONLY: is INTERCOM fill-bound or slot-bound?
	//
	// dma_budget (0x1F12) and dma_total (0x1F10) are GAME-written - the firmware
	// never assigns either, it only reads them in ppm_obj_frame_end to derive
	// dma_remaining = budget - total. So both are visible to this 68000-side snoop,
	// and the frame's starting headroom is (budget - total) words.
	//
	// Each block costs 0x110 words: 0x100 payload (512 bytes = 16 tiles, matching
	// the DMA entry's 0x0100-word length) plus 0x10 for the entry's own register
	// writes. So blocks fillable per frame = (budget - total) / 0x110.
	//
	// A real NTSC vblank moves roughly 3,800 words, i.e. 13-14 blocks - so a 53-slot
	// refill cannot happen in one frame. If the measured ceiling is near that, the
	// shaft is FILL-bound and the four blocks cap-at-49 costs were never going to
	// matter. A ceiling far above 14,416 means the units are wrong, not the budget
	// generous.
	//
	// dma_remaining itself is MCU-written and invisible here; it is only ever
	// budget - total, so it is reconstructed rather than snooped.
	localparam DMA_ONLY = 1'b0;

	wire [7:0] cmd_hi = cpu_data[15:8];
	wire keep_audio =
		   (cmd_hi == 8'h88)   // audio_setting  (muted in this firmware)
		|| (cmd_hi == 8'h8C)   // music
		|| (cmd_hi == 8'h8D)   // music_setting
		|| (cmd_hi == 8'hB0)   // sprite_init    (muted in this firmware)
		|| (cmd_hi == 8'hC9)   // music_volume
		|| (cmd_hi == 8'hCA)   // sfx_volume
		|| (cmd_hi == 8'hD1)   // sfx_play
		|| (cmd_hi == 8'hD2)   // sfx_off
		|| (cmd_hi == 8'hD3)   // sfx_loop
		|| (cmd_hi == 8'hD6);  // music_special

	// 0xF2 is logged too: it is the third pointer-mover (sdram_ptr = 0x9000, and
	// it unpacks to 0x9000/0x9200). Muting it changed nothing on hardware, so it
	// is back to stock and measured rather than suppressed.
	wire keep = DMA_ONLY    ? (cmd_hi == 8'hEC)        // fences only; DMA is snooped below
	          : DEST_ONLY   ? ((cmd_hi == 8'hDA) | (cmd_hi == 8'hDB)
	                         | (cmd_hi == 8'hF2) | (cmd_hi == 8'hEC))
	          : BUDGET_ONLY ? (cmd_hi == 8'hEC)
	                        : (LOG_ALL | keep_audio);

	wire hit_raw   = cpu_wr & (wr_word == A_CMD) & keep;

	// Two mechanisms, both learned the hard way from a capture that filled and
	// flushed the events it was built to catch.
	//
	// 1. DEDUP against the last four logged commands. Paprium implements a volume
	//    fade as one command PER STEP - D3/D6/D3 cycling continuously - which
	//    buried both cues. It is compared on (cmd,param) ONLY: the volume changes
	//    every step, and so does the mask (0025, 0024, 0023 ...), so including
	//    either would defeat the dedup entirely. The first of each run keeps its
	//    mask, which is what the eviction analysis needs.
	//
	// 2. FREEZE after the first cue of interest plus a long tail. Triggering on
	//    EITHER 0x1C or 0x4A matters: the big enemy is killed early and the TV
	//    comes later, so arming on the first of them and running on for 1024 more
	//    entries captures the whole sequence between them. Freezing on the TV
	//    alone would never fire in the case we most suspect - the cue never being
	//    requested at all.
	localparam [7:0] TRIG_A = 8'h1C;   // boss / large-enemy death
	localparam [7:0] TRIG_B = 8'h4A;   // punk-TV cue
	localparam [10:0] POST_ENTRIES = 11'd1024;

	wire [7:0] cmd_par = cpu_data[7:0];
	wire is_play = (cmd_hi == 8'hD1) || (cmd_hi == 8'hD3);

	reg [15:0] prev0, prev1, prev2, prev3;
	wire dup = (cpu_data == prev0) | (cpu_data == prev1)
	         | (cpu_data == prev2) | (cpu_data == prev3);

	reg        armed, frozen;
	reg [10:0] post_cnt;

	// NO_DEDUP: dedup is four 16-bit comparators feeding the write decision - the
	// same shape of cost that pushed the DMA logger's TNS to -4,872. It exists so a
	// LONG capture survives Paprium's per-step volume fades. The single-kill run is
	// three grunts and one fat enemy then exit, which cannot fill 1023 entries, so
	// it buys nothing here and is bypassed.
	localparam NO_DEDUP = 1'b1;

	wire hit_cmd = hit_raw & (BUDGET_ONLY | DEST_ONLY | NO_DEDUP | ~dup) & ~frozen;

	// Channel-7 snapshots, emitted on CHANGE rather than on a timer: the volume
	// register changing and the FIFO running dry are both rare, so this stays
	// sparse and cannot flood the ring the way the fade traffic did. Logged as
	// command 0xF7, which is not a real Paprium command, so the decoder can tell
	// them apart from mailbox traffic.
	localparam [7:0] SNAP_CMD = 8'hF7;

	reg [10:0] ch7_vol_d;
	reg        ch7_empty_d;
	reg [15:0] ch7_wr_cnt;

	wire ch7_changed = (ch7_vol != ch7_vol_d) | (ch7_empty != ch7_empty_d);
	localparam SNAP_ON = 1'b0;
	wire hit_snap    = ch7_changed & ~frozen & ~hit_cmd & SNAP_ON;
	// dma_total 0x1F10 -> word 0xF88, dma_budget 0x1F12 -> word 0xF89
	localparam [11:0] A_DMA_TOTAL  = 12'hF88;
	localparam [11:0] A_DMA_BUDGET = 12'hF89;
	reg [15:0] last_dtot, last_dbud;
	wire hit_dtot = cpu_wr & (wr_word == A_DMA_TOTAL);
	wire hit_dbud = cpu_wr & (wr_word == A_DMA_BUDGET);

	// SAMPLED, not change-detected. Comparing cpu_data against the last latched
	// value put two 16-bit comparators AND a third write-path arbiter in the same
	// cycle as the write decision: TNS went to -4,872 against Probe B v2's -1,204,
	// worse than the build that failed to boot.
	//
	// Instead emit one row per `beat` wrap. The beat is 20 bits at ~53.7 MHz, so
	// that is roughly one sample per frame - which is the natural rate anyway,
	// since dma_remaining is recomputed once per frame in ppm_obj_frame_end. The
	// write data comes from registers latched on a previous cycle, so nothing
	// combinational from cpu_data reaches the write path.
	//
	// Sampling at beat==0 keeps it off the header ticks, which fire at &beat.
	wire hit_dma  = DMA_ONLY & ~frozen & (beat == 20'd0);

	wire hit_mask  = cpu_wr & (wr_word == A_MASK);
	wire hit_vol   = cpu_wr & (wr_word == A_VOL);
	wire hit_flags = cpu_wr & (wr_word == A_FLAGS);

	// The mask is written just before the command, so latching it and pairing it
	// with the next command word is enough - no ordering games needed.
	reg [15:0] last_mask;
	reg [15:0] last_vol;
	reg [15:0] last_flags;

	// RING HALVED to 2048 words. At 4096 the logger used ~12 M10K and the variant
	// sat at 308/308 - completely full - so the fitter had no room and three
	// successive additions failed timing, the last with a NEGATIVE hold slack.
	// Halving frees ~6 blocks.
	//
	// 2048 words = 1023 entries. At the beat sample rate of ~1 row/frame that is
	// ~17 s of tail, and the ring wraps, so the tail is what survives - which is
	// the elevator. LOG_ALL captures needed depth; a sampled DMA capture does not.
	reg [10:0] wr_idx;

	reg [15:0] ec_cnt, ec_peak, ec_last, any_cmd_cnt;
	// Word 4092 counters, repurposed by mode:
	//   DEST_ONLY : {unaligned_cnt, trk_cnt} - 0xDA/0xDB seen, and how many landed
	//               inside staging WITHOUT 0x200 alignment. An unaligned unpack
	//               straddles two 16-tile blocks and smears patterns the VDP may
	//               still be showing - the corruption case. Sticky, so it survives
	//               a ring wrap and a mid-run reset.
	//   otherwise : {pitch_cnt, sfx_cnt}     - sfx commands, and half-pitch ones
	reg [15:0] sfx_cnt, pitch_cnt;
	wire       sfx_cmd = any_cmd & (DEST_ONLY ? ((cmd_hi == 8'hDA) | (cmd_hi == 8'hDB))
	                                          : ((cmd_hi == 8'hD1) | (cmd_hi == 8'hD3)));

	// Staging runs 0x9000..0xF1FF at the shipped 49-block cap. 0x9000 is itself on
	// the 0x200 grid, so once the range is required, `dest[8:0] != 0` IS the
	// off-grid test.
	//
	// 0xDA and 0xDB MUST be counted separately. 0xDA's destination is cmd_args[0],
	// a bare 16-bit word - no endian question, and this is the number that can
	// decide the branch on its own. 0xDB's is swapshorts(cmd_args_long[0]), so it
	// has two reconstructions, and judging it on half a 32-bit value would read as
	// unaligned nearly every time - a false positive pushing us to the
	// private-buffer path wrongly.
	//
	// The endianness resolves itself in hardware: for a 32-bit reconstruction to
	// land in 0x9000..0xF1FF one half must be ZERO, so the in-range one identifies
	// itself. If neither lands in range, 0xDB contributes nothing.
	wire        da_in_stage  = (last_mask >= 16'h9000) & (last_mask <= 16'hF1FF);
	wire        da_unaligned = da_in_stage & (|last_mask[8:0]);

	// 0xDB has NO sticky counter. It needs two 32-bit reconstructions and four
	// 16-bit range compares, which cost ~68 ALMs and pushed TNS from -1,559 to
	// -2,844 on a build already at 99% - the core failed to boot. unaligned_da
	// decides the branch on its own, and 0xDB rows still reach the ring, so the
	// two-endian analysis happens in the decoder where it is free.
	wire       any_cmd = cpu_wr & (wr_word == A_CMD);
	wire       ec_cmd  = any_cmd & (cmd_hi == 8'hEC);

	reg        mem_we;
	reg [10:0] mem_waddr;
	reg [31:0] mem_wdata;

	always @(posedge clk) begin
		mem_we <= 1'b0;

		if(reset) begin
			wr_idx      <= 12'd0;
			ch7_vol_d   <= 11'd0;
			ch7_empty_d <= 1'b1;
			ch7_wr_cnt  <= 16'd0;
			last_mask  <= 16'd0;
			last_vol   <= 16'd0;
			last_flags <= 16'd0;
			prev0      <= 16'hFFFF;
			prev1      <= 16'hFFFF;
			prev2      <= 16'hFFFF;
			prev3      <= 16'hFFFF;
			armed      <= 1'b0;
			frozen     <= 1'b0;
			post_cnt   <= 11'd0;
		end
		else begin
			if(any_cmd) any_cmd_cnt <= any_cmd_cnt + 1'd1;
			if(sfx_cmd) begin
				sfx_cnt <= sfx_cnt + 1'd1;
				// DEST_ONLY: 0xDA off-grid only. Otherwise: half pitch.
				if(DEST_ONLY ? (da_unaligned & (cmd_hi == 8'hDA)) : last_flags[13])
					pitch_cnt <= pitch_cnt + 1'd1;
			end

			if(ec_cmd) begin
				ec_cnt  <= ec_cnt + 1'd1;
				ec_last <= last_vol;
				if(last_vol > ec_peak) ec_peak <= last_vol;
			end

			ch7_vol_d   <= ch7_vol;
			ch7_empty_d <= ch7_empty;
			if(ch7_wr) ch7_wr_cnt <= ch7_wr_cnt + 1'd1;

			if(hit_dtot)  last_dtot  <= cpu_data;
			if(hit_dbud)  last_dbud  <= cpu_data;

			if(hit_mask)  last_mask  <= cpu_data;
			if(hit_vol)   last_vol   <= cpu_data;
			if(hit_flags) last_flags <= cpu_data;

			if(hit_cmd) begin
				prev3 <= prev2;
				prev2 <= prev1;
				prev1 <= prev0;
				prev0 <= cpu_data;

				if(is_play & ((cmd_par == TRIG_A) | (cmd_par == TRIG_B)))
					armed <= 1'b1;

				if(armed) begin
					if(post_cnt == POST_ENTRIES - 1'd1) frozen <= 1'b1;
					else post_cnt <= post_cnt + 1'd1;
				end

				mem_we    <= 1'b1;
				mem_waddr <= wr_idx;
				mem_wdata <= {cpu_data, last_mask};
				// second word follows on the next cycle
				snd_wdata <= {last_flags, last_vol};

				// entries are two words; 0..4093, word 4095 is the header.
				// In LOG_ALL the ring fills ONCE and stops - wrapping would discard
				// the boot sequence, which is the part being examined.
				if(wr_idx >= 11'd2040) begin
					if(LOG_ALL) frozen <= 1'b1;
					wr_idx <= 12'd0;
				end
				else wr_idx <= wr_idx + 2'd2;
			end
			else if(hit_dma) begin
				mem_we    <= 1'b1;
				mem_waddr <= wr_idx;
				//  [31:24] 0xF8 marker   [15:0] dma_total
				mem_wdata <= {8'hF8, 8'd0, last_dtot};
				//  [31:16] dma_budget    [15:0] unused
				snd_wdata <= {last_dbud, 16'd0};
				wr_idx <= (wr_idx >= 11'd2040) ? 11'd0 : wr_idx + 2'd2;
			end
			else if(hit_snap) begin
				mem_we    <= 1'b1;
				mem_waddr <= wr_idx;
				//  [31:24] 0xF7 marker   [23:16] fifo_empty   [15:0] volume
				mem_wdata <= {SNAP_CMD, 7'd0, ch7_empty, 5'd0, ch7_vol};
				//  [31:16] unused        [15:0]  PCM words pushed so far
				snd_wdata <= {16'd0, ch7_wr_cnt};

				wr_idx <= (wr_idx >= 11'd2040) ? 11'd0 : wr_idx + 2'd2;
			end
		end
	end

	// Cycle after the command word: the flags/volume word. Cycle after that: the
	// header, so a capture taken at any moment names the newest entry.
	reg [31:0] snd_wdata;
	reg        snd_we, hdr_we, hdr1_we, hdr2_we, hdr3_we;
	always @(posedge clk) begin
		snd_we  <= mem_we;
		hdr_we  <= snd_we;
		hdr1_we <= hdr_we;
		hdr2_we <= hdr1_we;
		hdr3_we <= hdr2_we;
	end

	// The counters must also reach RAM when the ring is silent - in BUDGET_ONLY a
	// whole run can log nothing, which is exactly the case being diagnosed. Tick
	// them out periodically so an empty ring still carries a verdict.
	reg [19:0] beat;
	reg        beat_tick, beat_tick2, beat_tick3;
	always @(posedge clk) begin
		beat       <= beat + 1'd1;
		beat_tick  <= &beat;
		beat_tick2 <= beat_tick;
		beat_tick3 <= beat_tick2;
	end
	wire hdr1_any = hdr1_we | beat_tick;
	wire hdr2_any = hdr2_we | beat_tick2;
	wire hdr3_any = hdr3_we | beat_tick3;

	wire        ram_we    = mem_we | snd_we | hdr_we | hdr1_any | hdr2_any | hdr3_any;
	wire [10:0] ram_waddr = hdr3_any ? 11'd2044
	                      : hdr2_any ? 11'd2045
	                      : hdr1_any ? 11'd2046
	                      : hdr_we ? 11'd2047
	                      : snd_we ? (mem_waddr + 1'd1)
	                               : mem_waddr;
	wire [31:0] ram_wdata = hdr3_any ? {pitch_cnt, sfx_cnt}
	                      : hdr2_any ? {ec_last, any_cmd_cnt}
	                      : hdr1_any ? {ec_cnt, ec_peak}
	                      : hdr_we ? {16'hC0DE, armed, frozen, 3'd0, wr_idx}
	                      : snd_we ? snd_wdata
	                               : mem_wdata;

	// Written as a plain inferred dual-port RAM: one write port, one registered
	// read port, no read-during-write games. 4096 x 32 = 128 Kbit, affordable at
	// 246/308 RAM blocks.
	reg [31:0] mem[2048];

	always @(posedge clk) if(ram_we) mem[ram_waddr] <= ram_wdata;

	reg [31:0] rd_word;
	reg  [1:0] rd_sel;
	always @(posedge clk) begin
		rd_word <= mem[read_addr[12:2]];
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
