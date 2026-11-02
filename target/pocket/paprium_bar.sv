// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (test builds 4a and 4b, the 0.3.0 hardware test builds of the sound cache; the firmware's
// docs/MCU_INTERFACE.md v1.3 sections 3.9 and 21.2) - the first-boot bar.
//
// While XLINK BAR.EN = 1 (XLINK = the MCU's register block for the Pocket's own memories and the CPU MATE link,
// paprium_xlink.sv) the core's video output is lit white (RGB 0xFFFFFF) on the last 4 active lines of every
// frame, from the first active pixel for BAR.PX pixels (PX >= W lights the whole line). The firmware lights it only
// during a first-boot unpack, while the 68000 is held, and writes EN = 0 before it releases the 68000; EN = 0 leaves
// every pixel as the core made it.
//
// On the dot clock (clk_vid), from the video output's own DE and VS (core_top's scanline_filler outputs):
//   hcnt        active pixels already passed in this line (the index of this clock's pixel while de = 1)
//   line        active lines already completed in this frame (the index of the current line while de = 1)
//   lines_prev  active lines in the last complete frame (taken at the VS rise); 0 until one frame has been seen, and
//               then nothing is lit, so the first frame after power-on can never light the whole picture
//   w           active pixels in the last complete active line (XLINK BAR read-back W; 0 before the first line)
// lit = en & de & (hcnt < px) & (lines_prev >= 4) & (line >= lines_prev - 4) & (line < lines_prev).
// The frame's line count follows the previous frame (scanline_filler pads every frame to its snap point, 224 or 240).
// Across a height switch one frame is off: after 240 -> 224 it lights nothing (lines 236-239 do not exist), after
// 224 -> 240 it lights lines 220-223 (16 lines up); the next frame is right again.
// en and px come from clk_sys through core_top's synchroniser (bar_sync), w goes back through bar_w_sync: both are
// quasi-static (the firmware writes PX once per unpack chunk; W changes only at an H32 / H40 switch).

module paprium_bar (
    input  wire        clk,                     // clk_vid (the dot clock)
    input  wire        en,                      // BAR.EN, synchronised to clk
    input  wire [10:0] px,                      // BAR.PX, synchronised to clk
    input  wire        de,                      // this clock's pixel is active (scanline_filler de)
    input  wire        vs,                      // the output VS (active high); a frame starts at its rise
    output wire        lit,                     // light this clock's pixel
    output reg  [10:0] w = 11'd0                // active pixels in the last complete active line
);

  reg  [10:0] hcnt       = 11'd0;
  reg   [9:0] line       = 10'd0;
  reg   [9:0] lines_prev = 10'd0;
  reg         de_q       = 1'b0;
  reg         vs_q       = 1'b0;

  always @(posedge clk) begin
    de_q <= de;
    vs_q <= vs;
    if (de) begin
      if (hcnt != 11'h7FF) hcnt <= hcnt + 11'd1;
    end
    else if (de_q) begin                        // the line's last active pixel was the clock before
      w    <= hcnt;
      hcnt <= 11'd0;
      if (line != 10'h3FF) line <= line + 10'd1;
    end
    if (vs & ~vs_q) begin                       // a new frame
      lines_prev <= line;
      line       <= 10'd0;
    end
  end

  wire [9:0] first = lines_prev - 10'd4;
  assign lit = en & de & (hcnt < px) & (lines_prev >= 10'd4) & (line >= first) & (line < lines_prev);

endmodule
