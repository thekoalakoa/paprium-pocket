// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (test build 5, the 0.3.0 hardware test build of the synth; a project decision, confirmed by
// B Jam 2026-10-23) - the picture during a cart hold.
//
// While the console is held in reset (core_top's md_reset_effective: the Pocket's load, the shell reset and the cart
// MCU's hold of the 68000, ~20 s on a first start while the MCU unpacks the sound bank) md_board's VDP is held too and
// makes no sync, so the Dock / a TV saw no signal and kept its last picture (test build 4b, the first-boot unpack
// build, on hardware on 2026-10-23: 17.5 s of a frozen screen). This block keeps a valid picture on the APF video
// outputs for the whole hold: black frames at the VDP's own line and frame rate, 224 active lines, with the
// first-boot bar (XLINK BAR) drawn on them as paprium_bar draws it on the core's picture.
//
// It sits AFTER the core's own video path and changes nothing in it: md_board, the VDP, video_cond, scanline_filler,
// paprium_bar and core_top's slot-word / DE / RGB registers see exactly the signals they saw before, on every clock, so
// the game's boot after the release is the same clock for clock and so is the core's picture. The VDP stays held in
// reset with the 68000 and starts from reset at the release, as it always did. This block only chooses, on the dot
// clock, which of two complete pictures reaches the four APF video outputs (all four on the one select, gen):
//   gen = 0: video_hs / video_vs = scanline_filler's, video_de / video_rgb = core_top's registers (the core's picture)
//   gen = 1: this block's black frames (its syncs and its registered DE / RGB)
// The handover, both ways at a frame boundary:
//   into a hold: gen rises at the end of one of this block's own frames (the clock before its VS) while hold = 1, so
//     its first VS starts a whole frame (the core's frame then running is cut short: the VDP has stopped anyway);
//   out of a hold: gen falls ON the clock of scanline_filler's first VS after hold fell (gen is combinational there),
//     so that VS and everything after it are the core's own picture, exactly as without this block (this block's frame
//     then running is cut short by it: one short frame a boot, as the H32 -> H40 switch every boot makes).
// All four outputs switch on the same clock. Each picture's DE / RGB registers already run one clock behind its own syncs
// (core_top's video_de_reg / video_rgb_reg behind the filler's, de_q / rgb_q here behind hs / vs), so each clock's four
// outputs are one picture's own sample: on the takeover clock this block's VS with its DE / RGB at 0 (the last dot of
// its last line), and from the handover clock on core_top's own four outputs, as without this block. (A select one clock
// late for DE / RGB would put the core's VS beside this block's last DE / RGB on the handover clock: VS and DE on one dot.)
//
// The frames (the VDP's rates on this dot clock; clk_vid follows H32 / H40 as core_top selects it):
//   a line is 342 dots in H32 (MCLK / 10) and 427 / 428 alternately in H40 (3,420 MCLK = 427.5 dots of MCLK / 8);
//   a frame is 262 lines (NTSC) or 313 (PAL): 59.92 / 49.70 Hz as the VDP's;
//   VS on dot 0 of line 0 and HS on dot 7 of every line (one-clock pulses, scanline_filler's HSYNC_DELAY 7 apart);
//   DE on lines 16-239 (224) from dot 40, for 256 dots (H32) or 320 (H40); RGB 0 (black) but the bar; the scaler slot
//   word on the first blanked pixel after each active line, as core_top makes it, with v30 = 0 (224 lines), H32 and
//   the aspect bit as latched at this block's VS.
// The bar (en / px = core_top's bar_sync output; paprium_bar's rule on these frames): the last 4 active lines (220-223)
// are white from the first active pixel for px pixels (px >= the width lights the whole line). w = this block's active
// width (256 / 320) while gen = 1, so XLINK BAR's W read-back tells the firmware the width it draws on.
module paprium_holdvid #(
    parameter bit PAL = 1'b0
) (
    input  wire        clk,         // clk_vid (the dot clock)
    input  wire        hold,        // md_reset_effective, synchronised to clk (core_top's hold_vid_sync)
    input  wire        h32,         // H32 (synchronised: core_top's h32_s)
    input  wire        arcorr,      // the aspect-correction setting (synchronised: core_top's cfg_arcorr_s)
    input  wire        bar_en,      // XLINK BAR EN / PX, synchronised (core_top's bar_sync)
    input  wire [10:0] bar_px,
    input  wire        f_vs,        // scanline_filler's VS (one-clock pulse): the handover point out of a hold
    output wire        gen,         // this clock's video_hs / video_vs / video_de / video_rgb come from this block
    output wire        hs,
    output wire        vs,
    output reg         de_q,
    output reg  [23:0] rgb_q,
    output wire [10:0] w
);

  localparam [8:0] VT = PAL ? 9'd313 : 9'd262;   // lines a frame
  localparam [8:0] V0 = 9'd16;                    // first active line
  localparam [8:0] VN = 9'd224;                   // active lines
  localparam [8:0] H0 = 9'd40;                    // first active dot
  localparam [8:0] HS_AT = 9'd7;                  // HS dot (scanline_filler's HSYNC_DELAY after VS)

  // power-up values: every register starts at 0 (Quartus' power-up, the initial block for simulation)
  reg  [8:0] hc;                                  // dot in the line
  reg  [8:0] vc;                                  // line in the frame
  reg        odd;                                 // H40: this line is 428 dots, else 427
  reg        on;                                  // this block holds the picture (until the handover clock)
  reg        act_d;                               // last clock was an active dot
  reg        s_h32, s_arc;                        // latched at this block's VS for the slot word
  initial begin
    hc = 9'd0; vc = 9'd0; odd = 1'b0; on = 1'b0; act_d = 1'b0; s_h32 = 1'b0; s_arc = 1'b0;
    de_q = 1'b0; rgb_q = 24'd0;
  end

  wire [8:0] ht    = h32 ? 9'd342 : (odd ? 9'd428 : 9'd427);
  wire       hlast = (hc >= ht - 9'd1);           // >= : a mid-line H32 / H40 switch ends the line at once
  wire       vlast = (vc >= VT - 9'd1);
  wire [8:0] wd    = h32 ? 9'd256 : 9'd320;
  wire [8:0] gx    = hc - H0;                     // active dot index (valid while act)
  wire [8:0] gl    = vc - V0;                     // active line index (valid while act)
  wire       act   = (vc >= V0) && (vc < V0 + VN) && (hc >= H0) && (hc < H0 + wd);
  wire       lit   = bar_en & act & ({2'b00, gx} < bar_px) & (gl >= VN - 9'd4);
  // Fafrium: the refusal screen. While the boot stub refuses a firmware file it keeps BAR at EN | PX 2047 (the
  // firmware's own bar never reaches 2047: its PX is at most the active width), and every active dot is plain red
  // (255, 0, 0), steady, with no text; the 68000 stays held, so this block holds the picture
  wire       red   = bar_en & (&bar_px);

  assign vs  = (vc == 9'd0) && (hc == 9'd0);
  assign hs  = (hc == HS_AT);
  assign gen = on & ~(~hold & f_vs);              // the handover clock out of a hold is already the core's
  assign w   = {2'b00, wd};

  always @(posedge clk) begin
    if (hlast) begin
      hc  <= 9'd0;
      odd <= ~odd;
      vc  <= vlast ? 9'd0 : vc + 9'd1;
    end else begin
      hc  <= hc + 9'd1;
    end

    if (!on) begin
      if (hold && hlast && vlast) on <= 1'b1;   // into a hold: from this block's next VS
    end else if (!hold && f_vs) begin
      on <= 1'b0;                               // out of a hold: from the core's first VS
    end

    // the registered DE / RGB, as core_top's video_de_reg / video_rgb_reg are made from the filler's
    act_d <= act;
    de_q  <= act;
    if (vs) begin
      s_h32 <= h32;
      s_arc <= arcorr;
    end
    if (~act && act_d)
      rgb_q <= {8'b0, s_arc & ~s_h32, s_h32, 1'b0, 13'b0};   // the scaler slot word: {arcorr, h32, v30 = 0}
    else if (act)
      rgb_q <= red ? 24'hFF0000 : {24{lit}};                  // black, or the bar's white; red: a refused file
    else
      rgb_q <= 24'd0;
  end

endmodule
