// pocket: paprium_mcd_link - the hook-free CPU MATE's Mega CD side (xram stage 2, option D).
// Sits beside paprium_addons on clk_md_107_39, the 68000's own clock (md_board MCLK2),
// so every release instant is exact to one 9.3 ns clock. It never drives DTACK and changes no bus
// timing: the stub's read mux shows `busy` in $A12020 bit 7 and `comstat2` at $A12024, both plain
// flops loaded ahead of the read (gate_report item 2).
//
//  strobe    a write is taken when its strobe is seen on two consecutive clocks after a clock
//            without it (ramdp_io's cpu_we_st == 3'b011 rule), so a one-clock glitch on LWR is never
//            an event. The event clock is F = the third clock of the strobe.
//  post      the game's command-2 send (main $9C686): a low-byte write to $A12011 whose low 7 bits are
//            2 and whose bit 7 differs from the bit 7 of the previous $A12011 low-byte write (R6).
//            `last7` is this module's own copy, so a glitch that rewrote the stub's c1 cannot hide a
//            post. The 512 $55AA/$AA55 tests and the $80 handshake have other low bits: never posts.
//            A post is taken only while the sub runs (SRES = 1), as the real sub could not see it.
//  timer     sub cycles since the post: the 12.5 MHz sub clock with W = 0, made exactly from this
//            clock: +250,000 per clock, one tick per 2,147,727 (107.386 MHz x 250,000 / 2,147,727 =
//            12.5 MHz exactly; gate_nb 3.1). Its origin is T0 = F - 1 + HOLD clocks, phase 0 there.
//            tick >= D is first true at edge T0 + ceil(D x 8.5909); the release flop changes one
//            clock later. HOLD (LCTRL[15:8], xlink) moves the origin so that the release lands on
//            (A)'s instant: (A) counts from the end of the post's write bus cycle and samples at the
//            end of the read bus cycle (gate_nb section 2). The default and its derivation are in
//            the xram stage-2 README; it is NOT measured.
//  busy      set at the post (only with option D on); cleared at tick D_BUSY (if armed). RET stays
//            the stub's constant 1.
//  comstat2  takes PEND at tick D_WORD (if armed, option D on). Armed late (the tick already past
//            D_WORD): released at once and counted (flag + late_count).
//  restart   $A12001 bit 0 written 1 -> 0 (main $09CA2A, every boot and soft reset): flag (powers up
//            1, the MCU clears it), busy/arm/timer cleared, comstat2 := 0 (the original sub's init
//            clears COMSTAT2 at sub $3A8, before main can read it again).
//  AI off    $A12001 bit 1 (SBRQ) written 0 -> 1 (main $09C9C2 `|= 3`; also the boot's first write of
//            3): flag, busy cleared, disarmed, comstat2 held.
//  snoop     en_mirror = Mega CD Mode; en_prg = Mega CD Mode & bank ($A12003[7:6]) == 0 & sub held in
//            reset (the rev-3 gate). Quasi-static levels for paprium_snoop on clk_sys.
//
// arm       (buddy_s2, review finding 1) an ARM toggle is latched in `arm_p` until the release logic takes it.
//            Before, `arm_ev` was a one-clock pulse read only in the branch that runs when the clock holds no
//            post and no $A12001 write, so an ARM landing on such a clock was lost and BUSY stayed set until
//            the MCU armed again. Now: a $A12001 write clock only delays it by one clock (restart / AI off
//            have stopped the timer by then, so it is ignored exactly as an ARM one clock later would be).
//            A post clock DROPS it: the MCU cannot have seen a post in the clock it lands, so that ARM was
//            computed for an earlier post, and dropping it is what an ARM one clock earlier would have
//            met (armed, then cleared by the post). Keeping it would arm the new post with the old
//            post's D_WORD / D_BUSY / PEND.
//
// Reset (R1): the cartridge reset (core_top shell_reset, the clk_md source of sys_reset that resets
// the MCU), NOT md_reset. The stub's own registers keep md_reset.

module paprium_mcd_link
(
	input  wire        clk,                       // clk_md_107_39
	input  wire        reset,                     // shell_reset (cartridge reset)
	input  wire        en_cd,                     // Mega CD Mode

	input  wire [23:1] cart_addr,
	input  wire        cart_lwr,
	input  wire [15:0] cart_data_wr,
	input  wire  [7:0] g3_q,                      // the stub's $A12003 (bank bits [7:6])

	// from paprium_xlink (clk_sys): values are stable long before their toggle moves
	input  wire [23:0] d_word,
	input  wire [23:0] d_busy,
	input  wire [15:0] pend,
	input  wire        arm_tg,                    // toggles once per ARM write
	input  wire  [3:0] clr_tg,                    // toggle per flag: write-1-to-clear
	input  wire        od_en,                     // option D on (LCTRL[0])
	input  wire  [7:0] hold,                      // LCTRL[15:8]

	output reg         busy,
	output reg  [15:0] comstat2,

	output reg   [3:0] flags,                     // {late, AI off, restart, send pending}
	output reg         armed,
	output reg         sres_run,                  // live SRES (1 = sub running), powers up 1
	output reg         sbrq,                      // live SBRQ (1 = sub bus requested / halted)
	output reg   [7:0] late_count,
	output reg  [15:0] post_count,
	output reg  [23:0] tick,

	output wire        en_mirror,
	output wire        en_prg
);

	localparam [21:0] INC = 22'd250000;
	localparam [21:0] DIV = 22'd2147727;
	localparam [21:0] DMI = DIV - INC;           // acc + INC >= DIV  <=>  acc >= DMI

	wire [23:0] a      = {cart_addr, 1'b0};
	wire        gate   = (a[23:6] == 18'h28480);  // $A12000-$A1203F
	wire        act011 = en_cd & gate & (a[5:1] == 5'd8) & cart_lwr;   // $A12011 (low byte of $A12010)
	wire        act001 = en_cd & gate & (a[5:1] == 5'd0) & cart_lwr;   // $A12001

	reg   [2:0] st011 = 3'b000, st001 = 3'b000;
	always @(posedge clk) begin
		st011 <= {st011[1:0], act011};
		st001 <= {st001[1:0], act001};
	end
	wire        f011 = (st011 == 3'b011);
	wire        f001 = (st001 == 3'b011);
	wire  [7:0] dat  = cart_data_wr[7:0];

	// MCU-side toggles and level, two flops each (clk_sys -> clk_md; same PLL, but no reliance on it)
	reg   [2:0] arm_s = 3'b000;
	reg   [2:0] clr_s0 = 3'b000, clr_s1 = 3'b000, clr_s2 = 3'b000, clr_s3 = 3'b000;
	reg   [1:0] en_s  = 2'b00;
	always @(posedge clk) begin
		arm_s  <= {arm_s[1:0],  arm_tg};
		clr_s0 <= {clr_s0[1:0], clr_tg[0]};
		clr_s1 <= {clr_s1[1:0], clr_tg[1]};
		clr_s2 <= {clr_s2[1:0], clr_tg[2]};
		clr_s3 <= {clr_s3[1:0], clr_tg[3]};
		en_s   <= {en_s[0], od_en};
	end
	wire        arm_ev = arm_s[2] ^ arm_s[1];
	reg         arm_p;                            // an ARM not yet taken (finding 1)
	wire        arm_go = arm_ev | arm_p;
	wire  [3:0] clr_ev = {clr_s3[2] ^ clr_s3[1], clr_s2[2] ^ clr_s2[1], clr_s1[2] ^ clr_s1[1], clr_s0[2] ^ clr_s0[1]};
	wire        on     = en_s[1];

	reg  [21:0] acc;
	reg   [7:0] pre;                              // hold-off clocks left before the timer starts
	reg         running;                          // the timer counts
	reg         word_done;
	reg         last7;
	reg  [23:0] dw_l, db_l;
	reg  [15:0] pd_l;

	assign en_mirror = en_cd;
	assign en_prg    = en_cd & (g3_q[7:6] == 2'b00) & ~sres_run;

	wire        post    = f011 & (dat[6:0] == 7'd2) & (dat[7] != last7) & sres_run;
	wire        rst_edg = f001 &  sres_run & ~dat[0];            // SRES 1 -> 0
	wire        aio_edg = f001 & ~sbrq     &  dat[1];            // SBRQ 0 -> 1
	wire        wrap    = (acc >= DMI);
	wire        w_due   = (tick >= dw_l);
	wire        b_due   = (tick >= db_l);

	always @(posedge clk) begin
		if (reset) begin
			busy       <= 1'b0;
			comstat2   <= 16'd0;
			flags      <= 4'b0010;                // restart flag powers up 1
			armed      <= 1'b0;
			sres_run   <= 1'b1;
			sbrq       <= 1'b0;
			late_count <= 8'd0;
			post_count <= 16'd0;
			tick       <= 24'd0;
			acc        <= 22'd0;
			pre        <= 8'd0;
			running    <= 1'b0;
			word_done  <= 1'b0;
			last7      <= 1'b0;
			arm_p      <= 1'b0;
		end
		else begin
			// finding 1: hold an ARM through a $A12001 write clock (taken in the final branch below);
			// the post branch clears it
			if (arm_ev) arm_p <= 1'b1;

			// write-1-to-clear from the MCU first, so an event in the same clock wins
			if (clr_ev[0]) flags[0] <= 1'b0;
			if (clr_ev[1]) flags[1] <= 1'b0;
			if (clr_ev[2]) flags[2] <= 1'b0;
			if (clr_ev[3]) flags[3] <= 1'b0;

			// the sub-cycle clock: hold-off, then exact 12.5 MHz ticks
			if (pre != 8'd0) begin
				pre <= pre - 1'd1;
				if (pre == 8'd1) begin running <= 1'b1; acc <= INC; end
			end
			else if (running) begin
				acc <= wrap ? (acc - DMI) : (acc + INC);
				if (wrap && tick != 24'hFFFFFF) tick <= tick + 1'd1;
			end

			if (f011) last7 <= dat[7];

			if (post) begin
				busy       <= on;
				armed      <= 1'b0;
				arm_p      <= 1'b0;               // an ARM in this clock was for an earlier post (finding 1)
				word_done  <= 1'b0;
				tick       <= 24'd0;
				flags[0]   <= 1'b1;
				post_count <= post_count + 1'd1;
				if (hold == 8'd0) begin running <= 1'b1; acc <= INC; pre <= 8'd0; end
				else              begin running <= 1'b0; acc <= 22'd0; pre <= hold; end
			end
			else if (f001) begin
				sbrq <= dat[1];
				if (dat[0]) sres_run <= 1'b1;
				if (rst_edg) begin
					flags[1] <= 1'b1;
					sres_run <= 1'b0;
					busy <= 1'b0; armed <= 1'b0; running <= 1'b0; pre <= 8'd0; comstat2 <= 16'd0;
				end
				if (aio_edg) begin
					flags[2] <= 1'b1;
					busy <= 1'b0; armed <= 1'b0; running <= 1'b0; pre <= 8'd0;
				end
			end
			else begin
				// the MCU arms the release
				arm_p <= 1'b0;                    // taken (or ignored when no timer runs), as arm_ev was
				if (arm_go & (running | (pre != 8'd0))) begin
					armed <= 1'b1;
					dw_l  <= d_word;
					db_l  <= d_busy;
					pd_l  <= pend;
					if (running & (tick >= d_word)) begin
						flags[3] <= 1'b1;
						if (late_count != 8'hFF) late_count <= late_count + 1'd1;
					end
				end
				// releases: never before (A)'s instant, at once when armed late
				if (armed & running) begin
					if (!word_done && w_due) begin
						if (on) comstat2 <= pd_l;
						word_done <= 1'b1;
					end
					if (b_due) begin
						busy <= 1'b0; running <= 1'b0; armed <= 1'b0;
					end
				end
				if (~on) busy <= 1'b0;
			end
		end
	end

endmodule
