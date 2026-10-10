// pocket: paprium_xram - the Pocket's asynchronous SRAM as the cart MCU's external RAM window
// (MCU 0x08000000-0x0803FFFF, aliased above). xram stage 1.
//
// Part (Analogue developer docs, "External Hardware", and the AS6C2016 datasheet Rev 1.1):
// AS6C2016-55BIN, 128K x 16 = 256 KB, 55 ns, 3.3 V. The board ties its chip enable active, so
// only OE#/WE#/UB#/LB# are ours. Datasheet minimums used here: tAA/tBA 55, tOE 30, tOH 10,
// tOHZ 20 (max), tWP 45, tAW 50, tDW 25, tDH/tAS/tWR 0, tBW 50.
//
// Clients, fixed priority (one 16-bit operation at a time):
//   0  APF loader  data_loader output (bridge 0x4xxxxxxx). A 1-clock pulse, >= 24 clocks apart,
//                  no back-pressure: held in a 1-entry register and served first. A pulse that
//                  finds the register still full is counted in stat_loader_lost.
//   1  snoop       stage 2 (68000 Word RAM mirror). Tied off in stage 1.
//   2  MCU writes  POSTED: a 32-bit store is acked as soon as the 1-entry buffer takes it, and
//                  written in the background (one or two 16-bit operations).
//   3  MCU reads   the NEORV32 Wishbone window, always the whole 32-bit word (two 16-bit reads).
//                  Level request, ack held until the request drops (paprium_mcu_mem's pattern). A
//                  read waits behind the posted buffer, so a load sees the MCU's own earlier stores.
//                  Request drop (buddy_s2, review finding 3): if the request drops while its read is
//                  still in the engine (NEORV32 1.4.8.1 does this only after its 127-cycle bus
//                  timeout, then up to 31 more clocks in the gateway's CANCELED state), that read
//                  finishes WITHOUT an ack (`mc_drop`). Before, it acked whatever request was up by
//                  then, so a new read issued 1..rd+8 clocks after the drop got the old word.
//
// Byte order, "16-bit native" (the same as RAMDP and the rv_port map): RV byte X lives in SRAM
// word X>>1, the even byte on DQ[7:0] (LB#), the odd byte on DQ[15:8] (UB#). APF's loader word
// is {file byte 2k+1, file byte 2k} (bridge_endian_little = 0), so file byte n = RV byte n.
//
// Pin structure (from the xram facts probe, which packed every pin register into its IOE): the
// FSM writes fabric registers (*_f); each pin register copies its fabric register on EVERY clock
// with no enable and no reset, so address, controls, DQ out and the 16 DQ output enables can all
// sit in the IOE (FAST_*_REGISTER in the qsf; with a clock enable Quartus leaves the OE registers
// in the fabric). DQ is captured every clock by the IOE input register (dq_in).
//
// Cycle plan at clk_sys 53.69 MHz (T = 18.624 ns). F = FSM edge, pins follow one edge later.
//   read : F0 address + OE#=UB#=LB#=0 -> pins F1 -> dq_in samples at F(1+rd) -> stored at F(2+rd).
//          A second half's address goes to the fabric at the first half's sample edge F(1+rd),
//          so its pins change one clock after that sample (no reliance on tOH); it is stored at
//          F(3+2rd). OE# rises after the last half.
//          rd = 5 by default (93.1 ns; the datasheet + STA budget of the facts work needs 4).
//   write: F0 address, DQ, UB#/LB# -> F1 WE#=0 -> F(1+wp) WE#=1 -> F(2+wp) DQ released, UB#/LB#=1
//          wp = 4 by default (74.5 ns low; tWP 45 needs 3). wp + 3 clocks per 16-bit write.
//   turnaround: DQ is driven no sooner than 2 clocks after OE# rose at the pins (tOHZ 20 ns).
// Both counts are run-time settable through XCFG (0 = default) so a smoke test can measure the
// real margin on the card.
//
// Reset is power-on only (PLL lock), never sys_reset: sys_reset is held through the APF load,
// which is exactly when the loader writes.
//
// Power-up: the pin registers have no initial value (an initial value could keep them out of
// the IOE), so the strobes read 0 until the first clk_sys edge. With CE# tied low that is a
// write of floating DQ into word 0 before anything is loaded; harmless.

module paprium_xram #(
	parameter [3:0]  RD_DEF   = 4'd5,
	parameter [3:0]  WP_DEF   = 4'd4,
	parameter [16:0] LOCK_TOP = 17'h08000         // word address: the image area, bytes 0x00000-0x0FFFF
)(
	input  wire        clk,                        // clk_sys_53_69
	input  wire        reset,                      // power-on only

	input  wire  [3:0] cfg_rd,                     // 0 = RD_DEF
	input  wire  [3:0] cfg_wp,                     // 0 = WP_DEF
	input  wire        cfg_lock,                   // 1 = MCU writes into the image area are dropped (acked)

	// client 0: APF loader
	input  wire        ld_wr,
	input  wire [17:0] ld_addr,                    // byte address
	input  wire [15:0] ld_data,

	// client 1: snoop FIFO head (stage 2; tie sn_valid low)
	input  wire        sn_valid,
	input  wire [16:0] sn_waddr,
	input  wire [15:0] sn_data,
	input  wire  [1:0] sn_be,                      // {UB, LB}, active high
	output reg         sn_take,

	// clients 2/3: MCU
	input  wire        mc_req,
	input  wire [17:0] mc_addr,                    // byte address, bits 1:0 ignored (word access)
	input  wire  [3:0] mc_sel,                     // byte lanes of a store. Loads always read the whole
	                                               // word: NEORV32 1.4.8.1 does not drive wb_sel_o on an
	                                               // instruction fetch (it carries the data port's last
	                                               // byte enables) and no bus signal tells a fetch apart
	                                               // (wb_tag_o[2] is 0 for most fetches), so a load cannot
	                                               // trust the lanes. Found in the NEORV32 RTL sim.
	input  wire        mc_wr,
	input  wire [31:0] mc_wdata,
	output reg  [31:0] mc_rdata,
	output reg         mc_ack,

	// pins
	output reg  [16:0] sram_a,
	inout  wire [15:0] sram_dq,
	output reg         sram_oe_n,
	output reg         sram_we_n,
	output reg         sram_ub_n,
	output reg         sram_lb_n,

	// diagnostics
	output reg  [31:0] stat_loader_writes,
	output reg  [15:0] stat_loader_lost,
	output reg  [31:0] stat_snoop_writes
);

	wire [3:0] rd = (cfg_rd != 4'd0) ? cfg_rd : RD_DEF;
	wire [3:0] wp = (cfg_wp != 4'd0) ? cfg_wp : WP_DEF;

	// ---- pin layer ----------------------------------------------------------------------------
	reg  [16:0] a_f    = 17'd0;
	reg  [15:0] dq_f   = 16'd0;
	reg         dqoe_f = 1'b0;
	reg         oe_f   = 1'b1;
	reg         we_f   = 1'b1;
	reg         ub_f   = 1'b1;
	reg         lb_f   = 1'b1;

	reg  [15:0] dq_o;
	(* preserve *) reg [15:0] dq_oe;              // one per pin, so each packs into its own IOE
	reg  [15:0] dq_in;

	genvar gi;
	generate for (gi = 0; gi < 16; gi = gi + 1) begin : g_dq
		assign sram_dq[gi] = dq_oe[gi] ? dq_o[gi] : 1'bz;
	end endgenerate

	always @(posedge clk) begin
		sram_a    <= a_f;
		dq_o      <= dq_f;
		dq_oe     <= {16{dqoe_f}};
		sram_oe_n <= oe_f;
		sram_we_n <= we_f;
		sram_ub_n <= ub_f;
		sram_lb_n <= lb_f;
		dq_in     <= sram_dq;
	end

	// ---- client state -------------------------------------------------------------------------
	reg         ld_pend = 1'b0;
	reg  [16:0] ld_waddr;
	reg  [15:0] ld_wdata;

	reg         pw_valid = 1'b0;                   // posted MCU write
	reg  [16:0] pw_waddr;                          // word address of half 0 (bit 0 = 0)
	reg  [31:0] pw_data;
	reg   [3:0] pw_sel;                            // halves still to write are those with lanes set

	reg         mc_done = 1'b0;                    // acked, waiting for the request to drop
	reg         mc_drop = 1'b0;                    // the read in the engine lost its request (finding 3)

	wire        mc_lockhit = cfg_lock & ({mc_addr[17:2], 1'b0} < LOCK_TOP);

	// ---- operation engine ---------------------------------------------------------------------
	localparam [2:0] S_IDLE = 3'd0, S_RD = 3'd1, S_CAP = 3'd2, S_WA = 3'd3, S_WP = 3'd4, S_WH = 3'd5;
	reg   [2:0] st = S_IDLE;
	reg   [3:0] cnt;
	reg         turn = 1'b0;                       // OE# rose one clock ago: no DQ drive yet
	reg         oe_low = 1'b0;                     // OE# low (fabric)
	reg         rd_half;                           // half being read
	reg         rd_more;                           // read half 1 after half 0
	reg   [1:0] wr_owner;                          // 0 loader, 1 snoop, 2 MCU posted
	reg         wr_half;                           // posted write: which half

	always @(posedge clk) begin
		sn_take <= 1'b0;

		// the loader never waits for the engine; a pulse that finds the register full is lost
		if (ld_wr) begin
			if (ld_pend & ~(st == S_IDLE & ~turn & ~oe_low)) stat_loader_lost <= stat_loader_lost + 1'd1;
			ld_pend  <= 1'b1;
			ld_waddr <= ld_addr[17:1];
			ld_wdata <= ld_data;
		end

		if (!mc_req) begin
			mc_done <= 1'b0;
			mc_ack  <= 1'b0;
			if (st == S_RD || st == S_CAP) mc_drop <= 1'b1;   // only MCU reads use S_RD / S_CAP
		end

		// posted write: taken whenever the buffer is free, whatever the engine is doing
		if (mc_req & mc_wr & ~mc_done & ~mc_ack & ~pw_valid & ~reset) begin
			mc_ack  <= 1'b1;
			mc_done <= 1'b1;
			if (~mc_lockhit & (mc_sel != 4'b0000)) begin
				pw_valid <= 1'b1;
				pw_waddr <= {mc_addr[17:2], 1'b0};
				pw_data  <= mc_wdata;
				pw_sel   <= mc_sel;
			end
		end

		if (turn) turn <= 1'b0;

		if (reset) begin
			st       <= S_IDLE;
			a_f      <= 17'd0;
			dqoe_f   <= 1'b0;
			oe_f     <= 1'b1;
			we_f     <= 1'b1;
			ub_f     <= 1'b1;
			lb_f     <= 1'b1;
			turn     <= 1'b0;
			oe_low   <= 1'b0;
			pw_valid <= 1'b0;
			mc_done  <= 1'b0;
			mc_ack   <= 1'b0;
			mc_drop  <= 1'b0;
			ld_pend  <= ld_wr;                       // a loader word is never dropped, even in reset
			stat_loader_writes <= 32'd0;
			stat_loader_lost   <= 16'd0;
			stat_snoop_writes  <= 32'd0;
		end
		else case (st)

			S_IDLE: begin
				// writes: OE# must have been high at the pins for 2 clocks (tOHZ 20 ns)
				if ((ld_pend | sn_valid | pw_valid) & oe_low) begin
					oe_f   <= 1'b1;
					oe_low <= 1'b0;
					turn   <= 1'b1;
				end
				else if ((ld_pend | sn_valid | pw_valid) & ~turn) begin
					dqoe_f <= 1'b1;
					st     <= S_WA;
					if (ld_pend) begin
						wr_owner <= 2'd0;
						ld_pend  <= ld_wr;                // a pulse in this very clock stays pending
						stat_loader_writes <= stat_loader_writes + 1'd1;
						a_f  <= ld_waddr;
						dq_f <= ld_wdata;
						ub_f <= 1'b0;
						lb_f <= 1'b0;
					end
					else if (sn_valid) begin
						wr_owner <= 2'd1;
						sn_take  <= 1'b1;
						stat_snoop_writes <= stat_snoop_writes + 1'd1;
						a_f  <= sn_waddr;
						dq_f <= sn_data;
						ub_f <= ~sn_be[1];
						lb_f <= ~sn_be[0];
					end
					else begin
						wr_owner <= 2'd2;
						if (pw_sel[1:0] != 2'b00) begin
							wr_half <= 1'b0;
							a_f  <= pw_waddr;
							dq_f <= pw_data[15:0];
							ub_f <= ~pw_sel[1];
							lb_f <= ~pw_sel[0];
						end
						else begin
							wr_half <= 1'b1;
							a_f  <= {pw_waddr[16:1], 1'b1};
							dq_f <= pw_data[31:16];
							ub_f <= ~pw_sel[3];
							lb_f <= ~pw_sel[2];
						end
					end
				end
				else if (~(ld_pend | sn_valid | pw_valid) & mc_req & ~mc_wr & ~mc_done & ~mc_ack) begin
					// MCU read: launch the first needed half; OE# and both byte lanes low
					oe_f    <= 1'b0;
					oe_low  <= 1'b1;
					ub_f    <= 1'b0;
					lb_f    <= 1'b0;
					rd_half <= 1'b0;                    // both halves, always (see mc_sel)
					rd_more <= 1'b1;
					a_f     <= {mc_addr[17:2], 1'b0};
					cnt     <= rd;
					st      <= S_RD;
				end
				else if (oe_low) begin
					// nothing to do after a read: OE# and the lanes go back high
					oe_f   <= 1'b1;
					ub_f   <= 1'b1;
					lb_f   <= 1'b1;
					oe_low <= 1'b0;
					turn   <= 1'b1;
				end
			end

			S_RD: begin
				if (cnt != 4'd0) cnt <= cnt - 1'd1;
				else begin
					// dq_in is sampling the pins at this edge; the next half may launch now
					if (rd_more) a_f <= {a_f[16:1], 1'b1};
					st <= S_CAP;
				end
			end

			S_CAP: begin
				if (rd_half) mc_rdata[31:16] <= dq_in;
				else         mc_rdata[15:0]  <= dq_in;
				if (rd_more) begin
					rd_more <= 1'b0;
					rd_half <= 1'b1;
					cnt     <= rd - 1'd1;               // its pins changed one clock ago
					st      <= S_RD;
				end
				else begin
					// finding 3: a read whose request dropped on the way (or drops now) ends unanswered
					if (!mc_drop && mc_req) begin
						mc_ack  <= 1'b1;
						mc_done <= 1'b1;
					end
					mc_drop <= 1'b0;
					st      <= S_IDLE;                  // OE# stays low; IDLE raises it if nothing follows
				end
			end

			S_WA: begin
				we_f <= 1'b0;
				cnt  <= wp - 1'd1;
				st   <= S_WP;
			end

			S_WP: begin
				if (cnt != 4'd0) cnt <= cnt - 1'd1;
				else begin
					we_f <= 1'b1;
					st   <= S_WH;
				end
			end

			// WE# is rising at the pins; address, data and lanes are held one more clock (tWR/tDH 0)
			S_WH: begin
				dqoe_f <= 1'b0;
				ub_f   <= 1'b1;
				lb_f   <= 1'b1;
				st     <= S_IDLE;
				if (wr_owner == 2'd2) begin
					if (wr_half == 1'b0 && pw_sel[3:2] != 2'b00) pw_sel[1:0] <= 2'b00;  // half 1 next
					else pw_valid <= 1'b0;
				end
			end

			default: st <= S_IDLE;
		endcase
	end

endmodule
