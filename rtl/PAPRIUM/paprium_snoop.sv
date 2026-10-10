// pocket: paprium_snoop - passive capture of the 68000's writes into the Mega CD Word RAM window and
// the PRG-RAM table window, queued for paprium_xram (client 1). xram stage 2 (option D).
// Nothing here drives the 68000 bus or DTACK, and nothing reaches SDRAM.
//
//   Word RAM  $600000-$61FFFF  -> SRAM bytes 0x20000-0x3FFFF (direct window, no remap; main writes
//                                  $600000-$6110FF: objects, records, terrain, header)
//   PRG-RAM   $420000-$421FFF  -> SRAM bytes 0x10000-0x11FFF (holds the 976 table bytes at $5F4-$723,
//                                  $9C0-$BBF, $1C92-$1D31 of the sub program; rev-3 gate: bank 0 and
//                                  the sub held in reset)
//
// A 68000 word at A lands in SRAM word (base + A[16:1]) as it is: UDS -> UB# (DQ[15:8]), LDS -> LB#
// (DQ[7:0]), the "16-bit native" order of paprium_xram, so the RV reads it with `lh`.
//
// The 68000 bus signals come from md_board on clk_md_107_39; this runs on clk_sys_53_69 (same PLL,
// edges aligned, so the crossing is timed by STA exactly like ramdp_io's mailbox port). A write is
// taken when its strobe has been seen on two consecutive clocks after a clock without it - ramdp_io's
// cpu_we_st == 3'b011 rule, the one the mailbox has always used on hardware. LWR/UWR are the VDP's
// global write strobes (md_board cart_lwr = ~LWR, the same pin that writes work RAM), so $6xxxxx
// writes raise them like $A12xxx and $42xxxx do (static reading of md_board.v / ym7101.v).
// 68000 writes come >= ~28 clocks apart; an SRAM write takes wp + 3 = 7 clocks and an MCU access in
// flight <= ~14, so two entries never fill in practice; an overflow is counted, never silent.
//
// en_mirror / en_prg are quasi-static levels from paprium_mcd_link (synchronised in core_top).
//
// buddy_s2/sys (integration): main's terrain send cursor $FF9920 (a word in 68000 work RAM, which the brain
// reads at every call: the block main's NEXT send will overwrite) is tapped here too. md_board's cart_addr /
// cart_lwr / cart_uwr are the 68000's address and the VDP's global write strobes for EVERY write (md_board.v:
// cart_address = VA, cart_lwr = ~LWR, the same LWR that writes ram_68k), so a write to $FF9920 is seen exactly
// like a Word RAM write, and goes through the same two-clock filter and FIFO into SRAM word CURSOR_W
// (byte 0x12000, the brain's rvmap 'curt'). Gated by en_mirror (Mega CD Mode): with the option off, nothing.

module paprium_snoop #(
	parameter [16:0] MIRROR_BASE_W = 17'h10000,  // SRAM word address of $600000 (byte 0x20000)
	parameter [16:0] PRG_BASE_W    = 17'h08000,  // SRAM word address of $420000 (byte 0x10000)
	parameter [16:0] CURSOR_W      = 17'h09000   // buddy_s2/sys: SRAM word of main's cursor $FF9920 (byte 0x12000)
)(
	input  wire        clk,                       // clk_sys_53_69
	input  wire        reset,

	input  wire        en_mirror,
	input  wire        en_prg,

	input  wire [23:1] cart_addr,
	input  wire        cart_lwr,
	input  wire        cart_uwr,
	input  wire [15:0] cart_data_wr,

	output wire        sn_valid,
	output wire [16:0] sn_waddr,
	output wire [15:0] sn_data,
	output wire  [1:0] sn_be,                     // {UB, LB}
	input  wire        sn_take,

	output reg  [15:0] stat_prg,                  // words queued for the PRG window (all = xram's SNOOP)
	output reg  [15:0] stat_overflow
);

	wire in_mirror = en_mirror & (cart_addr[23:17] == 7'b0110000);       // $600000-$61FFFF
	wire in_prg    = en_prg    & (cart_addr[23:13] == 11'h210);          // $420000-$421FFF
	wire in_cur    = en_mirror & (cart_addr[23:1] == 23'h7FCC90);              // $FF9920 (buddy_s2/sys)
	wire act       = (in_mirror | in_prg | in_cur) & (cart_lwr | cart_uwr);

	reg  [2:0] we_st = 3'b000;
	always @(posedge clk) we_st <= {we_st[1:0], act};
	wire fire = (we_st == 3'b011);

	wire [16:0] waddr = in_mirror ? (MIRROR_BASE_W | {1'b0, cart_addr[16:1]})
	                  : in_cur    ? CURSOR_W
	                              : (PRG_BASE_W    | {5'b00000, cart_addr[12:1]});

	// two-entry FIFO
	reg  [16:0] q_a0, q_a1;
	reg  [15:0] q_d0, q_d1;
	reg   [1:0] q_b0, q_b1;
	reg         rp = 1'b0, wp = 1'b0;
	reg   [1:0] n  = 2'd0;

	assign sn_valid = (n != 2'd0);
	assign sn_waddr = rp ? q_a1 : q_a0;
	assign sn_data  = rp ? q_d1 : q_d0;
	assign sn_be    = rp ? q_b1 : q_b0;

	wire pop  = sn_take & (n != 2'd0);
	wire push = fire & ((n != 2'd2) | pop);          // a full FIFO that pops this clock still takes it

	always @(posedge clk) begin
		if (reset) begin
			rp <= 1'b0; wp <= 1'b0; n <= 2'd0;
			stat_prg      <= 16'd0;
			stat_overflow <= 16'd0;
		end
		else begin
			if (push) begin
				if (wp) begin q_a1 <= waddr; q_d1 <= cart_data_wr; q_b1 <= {cart_uwr, cart_lwr}; end
				else    begin q_a0 <= waddr; q_d0 <= cart_data_wr; q_b0 <= {cart_uwr, cart_lwr}; end
				wp <= ~wp;
				if (in_prg & ~in_mirror & ~in_cur & (stat_prg != 16'hFFFF)) stat_prg <= stat_prg + 1'd1;
			end
			if (fire & (n == 2'd2) & ~pop & (stat_overflow != 16'hFFFF)) stat_overflow <= stat_overflow + 1'd1;
			if (pop) rp <= ~rp;
			n <= n + {1'b0, push} - {1'b0, pop};
		end
	end

endmodule
