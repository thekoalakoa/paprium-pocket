// pocket: paprium_xlink - the MCU's register block at 0x0A000000 for the external memories and the
// hook-free CPU MATE link (xram stages 1 and 2). In core_top on clk_sys_53_69, next to the
// two memory controllers. Stage 1 = timing configuration + diagnostics; stage 2 = the option-D
// registers of paprium_mcd_link (clk_md_107_39), reached through toggles and quasi-static values.
//
//   off  name        access  bits
//   00   XCFG        rw      [3:0] SRAM read wait  [7:4] SRAM WE# low  [11:8] CRAM read wait
//                            [15:12] CRAM write length  [16] SRAM image lock (MCU writes below
//                            SRAM byte 0x10000 are dropped). 0 in a field = the RTL default
//   04   ID          r       0x58524D31 'XRM1' (stage 1) / 0x58524D32 'XRM2' (stage 2 RTL present)
//   08   SNOOP       r       SRAM writes taken from the snoop since power-up (stage 2)
//   0C   LOADED      r       SRAM words written by the APF loader since power-up
//   10   CRAM_OPS    r       CRAM 16-bit operations since power-up
//   14   UNDERRUN    r       [15:0] CDDA underruns (paprium_cdda_play)  [31:16] snoop overflows (stage 2)
//   18   LOST        r       [15:0] SRAM loader words lost  [31:16] CRAM ring writes lost
//   1C   STATUS      r       [0] CRAM initialised  [31:16] PRG-window words snooped (stage 2)
//   --- stage 2 (option D), read 0 / ignored with STAGE2 = 0 ---
//   20   LSTAT       r       [3:0] flags {late, AI off, restart, send pending} (sticky, see LCLR)
//                            [4] BUSY as the 68000 sees it  [5] armed  [6] SRES (1 = sub running)
//                            [7] SBRQ (1 = sub halted)  [15:8] late count  [31:16] post count
//   24   LCLR        w       [3:0] write 1 to clear the matching flag
//   28   D_WORD      rw      [23:0] sub cycles after the post at which COMSTAT2 takes PEND
//   2C   D_BUSY      rw      [23:0] sub cycles after the post at which BUSY clears
//   30   PEND        rw      [15:0] the word for COMSTAT2 ($A12024)
//   34   ARM         w       any write arms the release with D_WORD / D_BUSY / PEND
//   38   TICK        r       [23:0] sub-cycle ticks since the last post (frozen at the busy release)
//   3C   LCTRL       rw      [0] option D on: honest BUSY + COMSTAT2 (0 = today's stub answers: BUSY 0,
//                            COMSTAT2 0)  [15:8] HOLD: clk_md clocks from the post's filtered strobe to
//                            the timer origin (reset value HOLD_DEF; see paprium_mcd_link). Written 0 =
//                            HOLD_DEF (buddy_s2, review finding 5: a plain `LCTRL = 1` used to set HOLD 0,
//                            moving the timer origin 14 clk_md clocks, ~1.6 sub ticks, early against
//                            (A)); the read returns the HOLD in use. HOLD 0 itself is no longer
//                            selectable (1..255 are).
//   LSTAT[7:0] is also the high byte of the FPGAIO ctrl read (fpgio.sv), so the main loop's existing
//   ctrl read sees a post, a restart or an AI-off at no extra cost.
//
// Wishbone side: one-clock ack, held until the request drops, like the memory controllers.
// Resets: `reset` (power-on) for the stage-1 part; `od_reset` (the cartridge reset, sys_reset) for
// the option-D controls, so a Pocket reset never leaves option D on for a firmware that just restarted.

module paprium_xlink #(
	parameter       STAGE2   = 1'b0,
	parameter [7:0] HOLD_DEF = 8'd14
)(
	input  wire        clk,                        // clk_sys_53_69
	input  wire        reset,                      // power-on only, like the controllers
	input  wire        od_reset,                   // cartridge reset (sys_reset)

	input  wire        req,
	input  wire  [5:0] addr,                       // byte offset in the block
	input  wire        wr,
	input  wire [31:0] wdata,
	output reg  [31:0] rdata,
	output reg         ack,

	output reg  [31:0] xcfg,

	input  wire [31:0] st_snoop,
	input  wire [31:0] st_loaded,
	input  wire [31:0] st_cram_ops,
	input  wire [15:0] st_underruns,
	input  wire [15:0] st_snoop_ovf,
	input  wire [15:0] st_snoop_prg,
	input  wire [15:0] st_loader_lost,
	input  wire [15:0] st_cram_lost,
	input  wire        st_cram_ready,

	// stage 2: to paprium_mcd_link (clk_md side, which samples the values on arm_toggle)
	output reg  [23:0] d_word,
	output reg  [23:0] d_busy,
	output reg  [15:0] pend,
	output reg         arm_toggle,
	output reg   [3:0] clr_toggle,
	output reg         od_en,
	output reg   [7:0] od_hold,
	// stage 2: from paprium_mcd_link (clk_md_107_39, same PLL; registered here, timed by STA)
	input  wire  [7:0] stub_lstat,                 // {sbrq, sres, armed, busy, flags[3:0]}
	input  wire  [7:0] stub_late_count,
	input  wire [15:0] stub_post_count,
	input  wire [23:0] stub_tick,

	output wire  [6:0] link_status                 // stage 2: {sbrq, sres, busy, flags} into fpgio ctrl[14:8]
);

	reg  [7:0] lstat_s1 = 8'd0, lstat_s = 8'd0;
	reg  [7:0] late_s;
	reg [15:0] posts_s;
	reg [23:0] tick_s;
	always @(posedge clk) begin
		lstat_s1 <= stub_lstat;
		lstat_s  <= lstat_s1;
		late_s   <= stub_late_count;
		posts_s  <= stub_post_count;
		tick_s   <= stub_tick;
	end

	assign link_status = STAGE2 ? {lstat_s[7:6], lstat_s[4:0]} : 7'd0;

	always @(posedge clk) begin
		if (!req) ack <= 1'b0;
		if (reset) begin
			xcfg       <= 32'd0;
			ack        <= 1'b0;
		end
		if (reset | od_reset) begin
			d_word     <= 24'd0;
			d_busy     <= 24'd0;
			pend       <= 16'd0;
			arm_toggle <= 1'b0;
			clr_toggle <= 4'd0;
			od_en      <= 1'b0;
			od_hold    <= HOLD_DEF;
		end
		else if (req & ~ack) begin
			ack <= 1'b1;
			if (wr) case (addr[5:2])
				4'h0: xcfg <= wdata;
				4'h9: if (STAGE2) clr_toggle <= clr_toggle ^ wdata[3:0];
				4'hA: if (STAGE2) d_word <= wdata[23:0];
				4'hB: if (STAGE2) d_busy <= wdata[23:0];
				4'hC: if (STAGE2) pend   <= wdata[15:0];
				4'hD: if (STAGE2) arm_toggle <= ~arm_toggle;
				4'hF: if (STAGE2) begin od_en <= wdata[0]; od_hold <= (wdata[15:8] == 8'd0) ? HOLD_DEF : wdata[15:8]; end
				default: ;
			endcase
			case (addr[5:2])
				4'h0: rdata <= xcfg;
				4'h1: rdata <= STAGE2 ? 32'h58524D32 : 32'h58524D31;
				4'h2: rdata <= st_snoop;
				4'h3: rdata <= st_loaded;
				4'h4: rdata <= st_cram_ops;
				4'h5: rdata <= {st_snoop_ovf, st_underruns};
				4'h6: rdata <= {st_cram_lost, st_loader_lost};
				4'h7: rdata <= {(STAGE2 ? st_snoop_prg : 16'd0), 15'd0, st_cram_ready};
				4'h8: rdata <= STAGE2 ? {posts_s, late_s, lstat_s} : 32'd0;
				4'hA: rdata <= STAGE2 ? {8'd0, d_word} : 32'd0;
				4'hB: rdata <= STAGE2 ? {8'd0, d_busy} : 32'd0;
				4'hC: rdata <= STAGE2 ? {16'd0, pend} : 32'd0;
				4'hE: rdata <= STAGE2 ? {8'd0, tick_s} : 32'd0;
				4'hF: rdata <= STAGE2 ? {16'd0, od_hold, 7'd0, od_en} : 32'd0;
				default: rdata <= 32'd0;
			endcase
		end
	end

endmodule
