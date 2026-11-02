// Pads every frame out to the nearest snap point with black lines, so the height
// announced to the scaler always matches the height emitted. From agg23's
// openfpga-SNES, rtl/mister_top/scanline_filler.sv
// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)
module scanline_filler #(
    parameter int SNAP_COUNT = 1,
    parameter int SNAP_POINTS[SNAP_COUNT] = '{240},
    parameter int HSYNC_DELAY = 6,
    // pocket (0.3.0, from the new core's fit gate): 1 = hsync_in / vsync_in are active low (the VDP's own polarity).
    // They are then captured as they arrive and inverted AFTER the capture registers, so the clk_md -> dot clock
    // crossing stays a plain register-to-register route with no logic (vidsta: 0 levels on all 28 pairs). An inverter
    // in front of the capture, as core_top had it, kept one LUT on the hsync_r / vsync_r pairs: the 0.2.6 fit and the
    // new core's synthesis both show it. The capture registers still power up at 0 (a power-up-1 register is built with
    // inverters around it, which puts the LUT back), and sync_started masks them for the first clock instead, so the
    // filler sees the syncs inactive at power-up exactly as before: exact by construction.
    parameter bit SYNC_N = 1'b0
) (
    input wire clk,

    input wire hsync_in,
    input wire vsync_in,

    input wire vblank_in,
    input wire hblank_in,

    input wire [23:0] rgb_in,

    output reg  hsync,
    output wire vsync,

    output reg de,
    output reg [23:0] rgb,
    output reg [7:0] snap_index,
    output reg [8:0] snap_point
);
  // pocket: the five inputs come from video_cond's cofi registers on clk_md_107_39, and clk
  // is a dot clock off the same VCO. They are taken ONCE, here, by these 28 registers, and
  // nothing below (nor the core's slot latch, which reads vsync) looks at an input directly.
  // Before this every consumer read the clk_md values through its own LUT path, so the same
  // dot event could reach two registers on different dot edges (a lost VS or DE fall for a
  // whole boot, depending on the boot's dot phase). One dot of latency, on sync, DE and
  // pixels alike. They must meet the same-edge window in core_constraints.sdc: placed next to cofi, no logic in
  // between. Power-up 0, as the registers below.
  //
  // pocket (0.3.0 new core, fit round 2 of its fits and timing fixes): how the 28 are built. As plain `q <= in` flops
  // they had 0 logic levels after synthesis but 10-13 of them got one after fitting, in every seed of fit round 1: a
  // ~feeder LUT (a one-input route-through) between the cofi register and the D input. A Cyclone V half-ALM has one
  // LUT, two flops and ONE direct (asdata) input; the area-first packing (Auto Packed Registers = Minimize Area with
  // Chains, ALM register packing effort high) puts two LUT-less flops in a half, so one of the two takes asdata and the
  // other is fed through the LUT (measured: seed 1 LABs X52/X53 Y20-Y24, feeder-fed = "clk d", direct = "clk asdata").
  // Seed 2 also had a router duplicate of vblank_r (a 29th pair). So each capture flop is now a dffeas whose
  // synchronous load (cap_ld, 1 on every clock: a kept register that powers up 1 and loads 1) takes the clk_md value
  // through asdata, and whose d input is its own inverse through a kept LUT (*_nq). That LUT is the flop's own, so its
  // half-ALM has no LUT and no direct input left for a second flop: the cofi value can only reach it through asdata, 0
  // levels by construction. Everything below reads the flop through that LUT (~*_nq), so the flop has one fanout and
  // nothing for the router to duplicate. With cap_ld = 1 the flop loads asdata on every clock: q <= in, as before,
  // exact by construction (the d input is never selected). Checked on our filler bench: the new file against the old
  // one on every clock from power-up.
  /* verilator lint_off PROCASSINIT */
  (* preserve *) reg cap_ld = 1'b1;
  /* verilator lint_on PROCASSINIT */
  always @(posedge clk) cap_ld <= 1'b1;

  wire        hsync_q, vsync_q, vblank_q, hblank_q;
  wire [23:0] rgb_q;
  wire        hsync_nq  /* synthesis keep */;
  wire        vsync_nq  /* synthesis keep */;
  wire        vblank_nq /* synthesis keep */;
  wire        hblank_nq /* synthesis keep */;
  wire [23:0] rgb_nq    /* synthesis keep */;
  assign hsync_nq  = ~hsync_q;
  assign vsync_nq  = ~vsync_q;
  assign vblank_nq = ~vblank_q;
  assign hblank_nq = ~hblank_q;
  assign rgb_nq    = ~rgb_q;

  // the node names stay hsync_r, vsync_r, vblank_r, hblank_r; the 24 pixel bits are rgb_r[n].ff (Quartus cannot
  // array a primitive, so a generate loop; the fit gate's vidsta, scripts/gate, takes both names)
  dffeas #(.power_up("low")) hsync_r  (.d(hsync_nq),  .clk(clk), .ena(1'b1), .clrn(1'b1), .prn(1'b1), .aload(1'b0),
                                       .asdata(hsync_in),  .sclr(1'b0), .sload(cap_ld), .q(hsync_q));
  dffeas #(.power_up("low")) vsync_r  (.d(vsync_nq),  .clk(clk), .ena(1'b1), .clrn(1'b1), .prn(1'b1), .aload(1'b0),
                                       .asdata(vsync_in),  .sclr(1'b0), .sload(cap_ld), .q(vsync_q));
  dffeas #(.power_up("low")) vblank_r (.d(vblank_nq), .clk(clk), .ena(1'b1), .clrn(1'b1), .prn(1'b1), .aload(1'b0),
                                       .asdata(vblank_in), .sclr(1'b0), .sload(cap_ld), .q(vblank_q));
  dffeas #(.power_up("low")) hblank_r (.d(hblank_nq), .clk(clk), .ena(1'b1), .clrn(1'b1), .prn(1'b1), .aload(1'b0),
                                       .asdata(hblank_in), .sclr(1'b0), .sload(cap_ld), .q(hblank_q));
  genvar gi;
  generate
    for (gi = 0; gi < 24; gi = gi + 1) begin : rgb_r
      dffeas #(.power_up("low")) ff (.d(rgb_nq[gi]), .clk(clk), .ena(1'b1), .clrn(1'b1), .prn(1'b1), .aload(1'b0),
                                     .asdata(rgb_in[gi]), .sclr(1'b0), .sload(cap_ld), .q(rgb_q[gi]));
    end
  endgenerate

  // the captured values as the logic below reads them (through the flop's own kept LUT)
  wire        hsync_c  = ~hsync_nq;
  wire        vsync_c  = ~vsync_nq;
  wire        vblank_c = ~vblank_nq;
  wire        hblank_c = ~hblank_nq;
  wire [23:0] rgb_c    = ~rgb_nq;
  // the syncs active high, from here on (the fit-gate fix: the inversion sits after the capture, in the dot clock
  // domain); with SYNC_N the power-up 0 of a capture register would read as an active sync, so the first clock is
  // masked
  /* verilator lint_off PROCASSINIT */
  reg sync_started = 0;
  /* verilator lint_on PROCASSINIT */
  always @(posedge clk) sync_started <= 1'b1;
  wire hsync_a = SYNC_N ? (sync_started & ~hsync_c) : hsync_c;
  wire vsync_a = SYNC_N ? (sync_started & ~vsync_c) : vsync_c;
  // pocket-end

  reg prev_de = 0;
  reg prev_hsync = 0;
  reg prev_vsync = 0;
  reg [2:0] hs_delay = 0;

  reg [8:0] output_line_count = 0;
  reg [8:0] visible_line_count = 0;
  // reg [9:0] clks_since_hsync_count = 0;
  // reg [8:0] black_pixel_count = 0;

  reg drawing_line = 0  /* synthesis noprune */;
  reg drawing_black = 0  /* synthesis noprune */;

  wire extended_vblank = vblank_c && ~(output_line_count < snap_point && output_line_count > 0)  /* synthesis keep */;
  wire de_blanks = ~(hblank_c || extended_vblank);

  always @(posedge clk) begin
    prev_hsync <= hsync_a;
    prev_vsync <= vsync_a;
    prev_de <= de_blanks;

    hsync <= 0;
    de <= 0;
    rgb <= 0;
    // clks_since_hsync_count <= clks_since_hsync_count + 1;

    if (vsync_a && ~prev_vsync) begin
      // Reset line count on start of vsync
      output_line_count  <= 0;
      visible_line_count <= 0;
    end

    if (de_blanks && ~prev_de) begin
      // We're drawing on this line
      drawing_line  <= 1;
      drawing_black <= 0;
    end
    // else if (output_line_count < snap_point && ~drawing_line &&
    //              clks_since_hsync_count > CLKS_UNTIL_BLANK_LINE[9:0] &&
    //              black_pixel_count < horizontal_width) begin
    //   // No data to render for this line, but we haven't met the snap point, so fill black
    //   de <= 1;
    //   rgb <= 0;
    //   black_pixel_count <= black_pixel_count + 1;
    //   drawing_black <= 1;
    // end

    if (de_blanks) begin
      de <= 1;
      if (vblank_c) begin
        // Extended blanking
        rgb <= 0;
        drawing_black <= 1;
      end else begin
        // Normal pixels
        rgb <= rgb_c;
      end
    end else if (~de_blanks && prev_de) begin
      // Falling edge of drawing
      output_line_count <= output_line_count + 1;
      if (~drawing_black) begin
        // If we drew black this line, it's not visible
        visible_line_count <= visible_line_count + 1;
      end
    end

    // Move hsync to not collide with vsync
    // ------------
    if (hs_delay > 0) begin
      hs_delay <= hs_delay - 1;
    end

    if (hs_delay == 1) begin
      hsync <= 1;
      // clks_since_hsync_count <= 0;
      // black_pixel_count <= 0;
      // drawing_black <= 0;
      drawing_line <= 0;
    end

    if (hsync_a && ~prev_hsync) begin
      if (HSYNC_DELAY <= 1) begin
        hsync <= 1;
        // clks_since_hsync_count <= 0;
        // black_pixel_count <= 0;
        // drawing_black <= 0;
        drawing_line <= 0;
      end else begin
        hs_delay <= HSYNC_DELAY[2:0];
      end
    end
  end

  always @(posedge clk) begin
    for (int i = 0; i < SNAP_COUNT; i = i + 1) begin
      if (visible_line_count <= SNAP_POINTS[i][8:0]) begin
        snap_index <= i[7:0];
        snap_point <= SNAP_POINTS[i][8:0];
      end
    end

  end

  assign vsync = vsync_a && ~prev_vsync;

endmodule
