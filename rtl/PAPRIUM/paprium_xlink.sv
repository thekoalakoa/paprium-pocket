// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: paprium_xlink - the MCU's register block at 0x0A000000 for the external memories and the
// hook-free CPU MATE link (xram steps 1 and 2, the two steps of our Pocket SRAM / CRAM work). In core_top on
// clk_sys_53_69, next to the two memory controllers. Step 1 = timing configuration + diagnostics; step 2 = the option-D
// registers of paprium_mcd_link (clk_md_107_39), reached through toggles and quasi-static values.
//
//   off  name        access  bits
//   00   XCFG        rw      [3:0] SRAM read wait  [7:4] SRAM WE# low  [11:8] CRAM read wait
//                            [15:12] CRAM write length  [16] SRAM image lock (MCU writes below
//                            SRAM byte 0x10000 are dropped). 0 in a field = the RTL default
//   04   ID          r       0x58524D31 'XRM1' (step 1) / 0x58524D32 'XRM2' (step 2 RTL present)
//   08   SNOOP       r       SRAM writes taken from the snoop since power-up (step 2)
//   0C   LOADED      r       SRAM words written by the APF loader since power-up
//   10   CRAM_OPS    r       CRAM 16-bit operations since power-up
//   14   UNDERRUN    r       [15:0] CDDA underruns (paprium_cdda_play)  [31:16] snoop overflows (step 2)
//   18   LOST        r       [15:0] SRAM loader words lost  [31:16] CRAM ring writes lost
//   1C   STATUS      r       [0] CRAM initialised  [31:16] PRG-window words snooped (step 2)
//   --- step 2 (option D), read 0 / ignored with STAGE2 = 0 ---
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
//                            HOLD_DEF (found in the review of the second step of our 0.2.x CPU MATE work: a
//                            plain `LCTRL = 1` used to set HOLD 0, moving the timer origin 14 clk_md clocks, ~1.6 sub
//                            ticks, early against (A)); the read returns the HOLD in use. HOLD 0 itself is no longer
//                            selectable (1..255 are).
//   LSTAT[7:0] is also the high byte of the FPGAIO ctrl read (fpgio.sv), so the main loop's existing
//   ctrl read sees a post, a restart or an AI-off at no extra cost.
//   --- MCU interface v1.3 (the 0.3.0 synth step, test builds 4a / 4b; the firmware's docs/MCU_INTERFACE.md 3.9, 21.1,
//   21.2) ---
//   40   CACHE       rw      [31] VALID  [22:0] SIZE: the sound-cache slot. Power-on reset only (kept across every
//                            sys_reset: the Pocket reads the slot back while the MCU reboots). A write while VALID = 0
//                            takes SIZE := [22:0] and VALID := [31]; while VALID = 1 writes are ignored (one-shot until
//                            the next power-on). Read {VALID, 8'0, SIZE}. Drives the datatable word: VALID ? SIZE : 0
//   44   CACHE_LOADED r      [22:0] bytes the Pocket loaded into the cache window (bridge 0x6000_0000-0x603F_FFFF) at
//                            this power-on, 4 a bridge word, saturating at 0x7FFFFF (core_top's paprium_cache_slot)
//   48   BAR         rw      [31] EN  [10:0] PX; read-only [26:16] W (active pixels in the last complete active line).
//                            Reset on every reset (od_reset). EN = 1: the last 4 active lines lit white for PX pixels
//   --- Fafrium (0.3.0): read by the boot stub, not by the firmware ---
//   4C   FAFRIUM     r       [0] LENBAD: 1 unless the Fafrium data slot's last load ended exactly at byte 256 KB of
//                            the slot (cartridge.sv fw_len_bad: the slot's first word clears its length mark, the
//                            window's last word sets it, any word at or past 256 KB clears it; this covers files
//                            up to 32 MB, see cartridge.sv). 1 at power-on; no reset changes it. It reads 0 once
//                            fw_done is set, so only the stub sees it. The stub refuses the file when it is 1.
//   50-7C reserved            read 0, writes ignored
//   v1.3 decodes addr[6:2] (32 word slots); 0x00-0x3C keep their meaning (0.2.6-v1.2 decoded addr[5:2], so
//   0x40-0x7C aliased 0x00-0x3C there). The 0x18 LOST word's high half counts every CRAM port-A write lost
//   (from test build 4a: the cache load's; the CDDA ring is gone).
//
// Wishbone side: one-clock ack, held until the request drops, like the memory controllers.
// Resets: `reset` (power-on) for the step-1 part and CACHE; `od_reset` (the cartridge reset, sys_reset) for
// the option-D controls and BAR, so a Pocket reset never leaves option D on for a firmware that just restarted.

module paprium_xlink #(
	parameter       STAGE2   = 1'b0,
	parameter [7:0] HOLD_DEF = 8'd14
)(
	input  wire        clk,                        // clk_sys_53_69
	input  wire        reset,                      // power-on only, like the controllers
	input  wire        od_reset,                   // cartridge reset (sys_reset)

	input  wire        req,
	input  wire  [6:0] addr,                       // byte offset in the block (v1.3: 7 bits, 32 word slots)
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

	// step 2: to paprium_mcd_link (clk_md side, which samples the values on arm_toggle)
	output reg  [23:0] d_word,
	output reg  [23:0] d_busy,
	output reg  [15:0] pend,
	output reg         arm_toggle,
	output reg   [3:0] clr_toggle,
	output reg         od_en,
	output reg   [7:0] od_hold,
	// step 2: from paprium_mcd_link (clk_md_107_39, same PLL; registered here, timed by STA)
	input  wire  [7:0] stub_lstat,                 // {sbrq, sres, armed, busy, flags[3:0]}
	input  wire  [7:0] stub_late_count,
	input  wire [15:0] stub_post_count,
	input  wire [23:0] stub_tick,

	output wire  [6:0] link_status,                // step 2: {sbrq, sres, busy, flags} into fpgio ctrl[14:8]
	output wire        post_bit,                   // 0.3.0 new core: posts_s[0]; every change is one post
	                                               // (FPGAIO CAUSE.S, MCU_INTERFACE.md v1.0 section 4.2)

	// v1.3 (synth step, test builds 4a / 4b): the sound-cache slot and the first-boot bar
	output reg         cache_valid,                // CACHE.VALID (power-on reset only)
	output reg  [22:0] cache_size,                 // CACHE.SIZE
	input  wire [22:0] st_cache_loaded,            // CACHE_LOADED (paprium_cache_slot, power-on reset only)
	output reg         bar_en,                     // BAR.EN
	output reg  [10:0] bar_px,                     // BAR.PX
	input  wire [10:0] bar_w,                      // BAR.W (paprium_bar, synchronised into this clock)
	input  wire        st_fw_len_bad               // Fafrium: FAFRIUM bit 0 (cartridge.sv fw_len_bad, already on this clock)
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
	assign post_bit    = STAGE2 ? posts_s[0] : 1'b0;

	always @(posedge clk) begin
		if (!req) ack <= 1'b0;
		if (reset) begin
			xcfg       <= 32'd0;
			ack        <= 1'b0;
			cache_valid <= 1'b0;                     // v1.3: power-on only
			cache_size  <= 23'd0;
		end
		if (reset | od_reset) begin
			d_word     <= 24'd0;
			d_busy     <= 24'd0;
			pend       <= 16'd0;
			arm_toggle <= 1'b0;
			clr_toggle <= 4'd0;
			od_en      <= 1'b0;
			od_hold    <= HOLD_DEF;
			bar_en     <= 1'b0;                      // v1.3: every reset
			bar_px     <= 11'd0;
		end
		else if (req & ~ack) begin
			ack <= 1'b1;
			if (wr) case (addr[6:2])
				5'h00: xcfg <= wdata;
				5'h09: if (STAGE2) clr_toggle <= clr_toggle ^ wdata[3:0];
				5'h0A: if (STAGE2) d_word <= wdata[23:0];
				5'h0B: if (STAGE2) d_busy <= wdata[23:0];
				5'h0C: if (STAGE2) pend   <= wdata[15:0];
				5'h0D: if (STAGE2) arm_toggle <= ~arm_toggle;
				5'h0F: if (STAGE2) begin od_en <= wdata[0]; od_hold <= (wdata[15:8] == 8'd0) ? HOLD_DEF : wdata[15:8]; end
				5'h10: if (!cache_valid) begin cache_size <= wdata[22:0]; cache_valid <= wdata[31]; end   // v1.3 CACHE
				5'h12: begin bar_en <= wdata[31]; bar_px <= wdata[10:0]; end                             // v1.3 BAR
				default: ;
			endcase
			case (addr[6:2])
				5'h00: rdata <= xcfg;
				5'h01: rdata <= STAGE2 ? 32'h58524D32 : 32'h58524D31;
				5'h02: rdata <= st_snoop;
				5'h03: rdata <= st_loaded;
				5'h04: rdata <= st_cram_ops;
				5'h05: rdata <= {st_snoop_ovf, st_underruns};
				5'h06: rdata <= {st_cram_lost, st_loader_lost};
				5'h07: rdata <= {(STAGE2 ? st_snoop_prg : 16'd0), 15'd0, st_cram_ready};
				5'h08: rdata <= STAGE2 ? {posts_s, late_s, lstat_s} : 32'd0;
				5'h0A: rdata <= STAGE2 ? {8'd0, d_word} : 32'd0;
				5'h0B: rdata <= STAGE2 ? {8'd0, d_busy} : 32'd0;
				5'h0C: rdata <= STAGE2 ? {16'd0, pend} : 32'd0;
				5'h0E: rdata <= STAGE2 ? {8'd0, tick_s} : 32'd0;
				5'h0F: rdata <= STAGE2 ? {16'd0, od_hold, 7'd0, od_en} : 32'd0;
				5'h10: rdata <= {cache_valid, 8'd0, cache_size};                   // v1.3 CACHE
				5'h11: rdata <= {9'd0, st_cache_loaded};                          // v1.3 CACHE_LOADED
				5'h12: rdata <= {bar_en, 4'd0, bar_w, 5'd0, bar_px};              // v1.3 BAR
				5'h13: rdata <= {31'd0, st_fw_len_bad};                            // Fafrium: FAFRIUM, for the boot stub
				default: rdata <= 32'd0;                                           // incl. 0x50-0x7C reserved
			endcase
		end
	end

endmodule
