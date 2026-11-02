// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// ---------------------------------------------------------------------------
// Paprium CDDA player - the consumer half of the background-music path.
//
// Ported from MisterPezz82's rtl/mdp_audio.sv. Everything musical is kept
// verbatim, because those constants were arrived at by A/B recording against
// real hardware and are not worth rediscovering:
//
//   - the 48 kHz consume divider (53.693 MHz / 1119 = 47983 Hz). Paprium's
//     tracks are authored at 48 k, not Redbook 44.1 k; playing them at 44.1 k
//     runs the music ~8% slow and flat.
//   - the $13xx fade: 255 steps over `fade_sectors` sectors at 75 sectors/s,
//     which works out at ~2808 clocks per step.
//   - the ~50 ms track-start mute that hides the initial buffer fill.
//
// pocket: 0.3.0 new core (the clock-following change) - the three counts follow the clock parameter
// CLK_HZ (core_top) instead of NTSC literals. At NTSC the divider (compare
// CLK_HZ/48000 = 1118, period 1119) and the fade step (CLK_HZ/19125 rounded up
// = 2808) are the same numbers as before; the mute becomes CLK_HZ/20 =
// 2,684,658 clocks instead of 2,685,000 (6 us shorter). PAL: 1108 (47,974 Hz),
// 2782, 2,660,171.
//
// What is NOT ported is the memory side. MiSTer reads a 64 KB ring buffer in
// DDR3 through a burst master, and buffers that behind a 256-sample M10K FIFO
// to smooth DDR3 latency. Here the ring buffer already IS block RAM
// (paprium_cdda_buf, filled by paprium_cdda_fetch from the APF data slot), so
// the FIFO would be a buffer in front of a buffer. This module reads the ring
// directly and exports its read pointer so the fetch side knows how much space
// it has.
//
// One stereo sample is one 32-bit ring word: {right[15:0], left[15:0]}, which
// is the byte order raw little-endian 16-bit stereo PCM already arrives in.
// ---------------------------------------------------------------------------

module paprium_cdda_play #(
	// clk's frequency in Hz (core_top's CLK_HZ). 0 = not set: refused below.
	parameter integer CLK_HZ = 0,
	// Ring size in 32-bit stereo samples. Must be a power of two.
	parameter RING_SAMPLES = 4096,         // 16 KB = ~85 ms at 48 kHz
	// Derived. Declared here rather than as a localparam in the body because
	// the port list is elaborated before the body.
	parameter ADDR_W = $clog2(RING_SAMPLES)
) (
	input         clk,
	input         reset,

	// MD+ command channel, straight off paprium_mdp_adapter
	input         active,
	input         track_start,
	input         stop_request,
	input   [7:0] fade_sectors,
	input   [7:0] volume,
	input         resume_request,
	input         osd_pause,

	// Ring buffer read side. rd_ptr is exported so the fetch side can compute
	// free space; fill_level is what the fetch side has written minus what we
	// have taken, in samples.
	output [ADDR_W-1:0] rd_ptr,
	input        [31:0] rd_data,
	input  [ADDR_W:0]   fill_level,
	output              sample_consumed,

	// Saturating count of sample ticks that found the ring empty while a track
	// was supposed to be playing. This is the number that sizes the buffer -
	// see docs/CDDA_DESIGN.md; APF's read latency is not documented anywhere.
	output reg   [15:0] underruns,

	output reg signed [15:0] audio_l,
	output reg signed [15:0] audio_r
);


	// ---- clock-derived counts (the clock-following change) ----
	localparam integer SAMPLE_CMP_I = CLK_HZ / 48000;                       // period SAMPLE_CMP + 1 clocks
	localparam integer MUTE_CLKS_I  = CLK_HZ / 20;                          // 50 ms
	localparam integer FADE_CLKS_I  = (CLK_HZ + 75 * 255 - 1) / (75 * 255); // per sector: 1 / (75 x 255) s, rounded up
	localparam [10:0] SAMPLE_CMP = SAMPLE_CMP_I[10:0];
	localparam [21:0] MUTE_CLKS  = MUTE_CLKS_I[21:0];
	localparam [19:0] FADE_CLKS  = FADE_CLKS_I[19:0];

	// synthesis translate_off
	initial begin
		if (CLK_HZ <= 0 || SAMPLE_CMP_I > 11'h7FF || MUTE_CLKS_I > 22'h3FFFFF || 255 * FADE_CLKS_I > 20'hFFFFF)
			$fatal(1, "paprium_cdda_play: CLK_HZ = %0d is unset or too large for the counters", CLK_HZ);
	end
	// synthesis translate_on

	// ---- pause state ----
	reg paused;
	always @(posedge clk) begin
		if (reset)
			paused <= 0;
		else if (track_start)
			paused <= 0;
		else if (stop_request && fade_sectors == 0)
			paused <= 1;
		else if (resume_request)
			paused <= 0;
	end

	// ---- track-start mute: ~50 ms at 53.7 MHz ----
	reg [21:0] mute_ctr;
	wire       muted = |mute_ctr;

	always @(posedge clk) begin
		if (reset)
			mute_ctr <= 0;
		else if (track_start)
			mute_ctr <= MUTE_CLKS;
		else if (mute_ctr > 0)
			mute_ctr <= mute_ctr - 1'd1;
	end

	// ---- fade engine ($13xx fades over fade_sectors sectors) ----
	reg  [7:0]  fade_vol;
	reg         fading;
	reg [19:0]  fade_timer;
	reg [19:0]  fade_step;

	always @(posedge clk) begin
		if (reset) begin
			fade_vol <= 8'hFF;
			fading   <= 0;
		end
		else if (track_start) begin
			fade_vol <= 8'hFF;
			fading   <= 0;
		end
		else if (stop_request) begin
			if (fade_sectors == 0) begin
				fade_vol <= 8'hFF;
				fading   <= 0;
			end
			else begin
				fading     <= 1;
				fade_step  <= {12'd0, fade_sectors} * FADE_CLKS;
				fade_timer <= 0;
			end
		end
		else if (fading) begin
			if (fade_timer >= fade_step) begin
				fade_timer <= 0;
				if (fade_vol == 0) fading   <= 0;
				else               fade_vol <= fade_vol - 1'd1;
			end
			else fade_timer <= fade_timer + 1'd1;
		end
	end

	// eff_volume = (game volume * fade) >> 8
	wire [15:0] vol_product = {8'd0, volume} * {8'd0, fade_vol};
	wire  [7:0] eff_volume  = vol_product[15:8];

	// ---- 48 kHz sample tick ----
	reg [10:0] sample_div;
	reg        sample_tick;

	always @(posedge clk) begin
		sample_tick <= 0;
		if (reset)
			sample_div <= 0;
		else if (sample_div >= SAMPLE_CMP) begin
			sample_div  <= 0;
			sample_tick <= 1;
		end
		else sample_div <= sample_div + 1'd1;
	end

	// ---- ring read pointer ----
	reg [ADDR_W-1:0] rd_addr;
	assign rd_ptr = rd_addr;

	wire ring_empty = (fill_level == 0);

	// A tick that should have produced audio but found the ring dry. Gated on
	// the same conditions as playback so ordinary silence (paused, muted,
	// faded out, no track) is not counted as an underrun.
	wire want_sample = active & ~paused & ~osd_pause & ~muted & (fade_vol > 0);

	assign sample_consumed = sample_tick & want_sample & ~ring_empty;

	// rd_data is the registered ring output for rd_addr, so it is valid the
	// cycle after the pointer moves. Scale and emit on the tick.
	wire signed [15:0] raw_l = $signed(rd_data[15:0]);
	wire signed [15:0] raw_r = $signed(rd_data[31:16]);

	wire signed [24:0] scaled_l = raw_l * $signed({1'b0, eff_volume});
	wire signed [24:0] scaled_r = raw_r * $signed({1'b0, eff_volume});

	always @(posedge clk) begin
		if (reset) begin
			audio_l   <= 0;
			audio_r   <= 0;
			rd_addr   <= 0;
			underruns <= 0;
		end
		else begin
			if (track_start) begin
				rd_addr <= 0;
				audio_l <= 0;
				audio_r <= 0;
			end
			else if (sample_tick) begin
				if (want_sample && !ring_empty) begin
					rd_addr <= rd_addr + 1'd1;
					audio_l <= scaled_l[23:8];
					audio_r <= scaled_r[23:8];
				end
				else begin
					// Hold silence rather than repeating the last sample: a
					// repeated sample under a starving stream buzzes.
					audio_l <= 0;
					audio_r <= 0;

					if (want_sample && ring_empty && !(&underruns))
						underruns <= underruns + 1'd1;
				end
			end
		end
	end

endmodule
