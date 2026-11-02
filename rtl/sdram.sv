//
// sdram.v
//
// sdram controller implementation
// Copyright (c) 2018 Sorgelig
// 
// This source file is free software: you can redistribute it and/or modify 
// it under the terms of the GNU General Public License as published 
// by the Free Software Foundation, either version 3 of the License, or 
// (at your option) any later version. 
// 
// This source file is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of 
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the 
// GNU General Public License for more details.
// 
// You should have received a copy of the GNU General Public License 
// along with this program.  If not, see <http://www.gnu.org/licenses/>. 
//
// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)

module sdram
// paprium: the controller's clock in Hz (this core runs it on clk_md, VCO/6). The refresh compares below come from
// it, so a PAL build (VCO/6 = 106,406,848 Hz) keeps the same refresh time. cartridge.sv passes core_top's value.
// 0.3.0 new core rule (scripts/clkcheck.py rule R4): the default is 0 = unset and every instance sets it; see
// clk_md_hz_check below
#(parameter integer CLK_MD_HZ = 0)
(

	// interface to the MT48LC16M16 chip
	inout  reg [15:0] SDRAM_DQ,   // 16 bit bidirectional data bus
	output reg [12:0] SDRAM_A,    // 13 bit multiplexed address bus
	output reg        SDRAM_DQML, // byte mask
	output reg        SDRAM_DQMH, // byte mask
	output reg  [1:0] SDRAM_BA,   // two banks
	output            SDRAM_nCS,  // a single chip select
	output reg        SDRAM_nWE,  // write enable
	output reg        SDRAM_nRAS, // row address select
	output reg        SDRAM_nCAS, // columns address select
	output            SDRAM_CLK,
	output            SDRAM_CKE,

	// cpu/chipset interface
	input             init,			// init signal after FPGA config to initialize RAM
	input             clk,			// sdram is accessed at up to 128MHz

	input      [24:1] addr0,
	input             wrl0,
	input             wrh0,
	input      [15:0] din0,
	output     [15:0] dout0,
	input             req0,
	output reg        ack0,
	
	input      [24:1] addr1,
	input             wrl1,
	input             wrh1,
	input      [15:0] din1,
	output     [15:0] dout1,
	input             req1,
	output reg        ack1,
	
	input      [24:1] addr2,
	input             wrl2,
	input             wrh2,
	input      [15:0] din2,
	output     [15:0] dout2,
	input             req2,
	output reg        ack2,

	// paprium: a VDP DMA read slot has opened (core_top's cart_dma, the VDP's l6 | l8, one clk register in
	// cartridge.sv); its port-1 read follows. 0 in the builds without Paprium
	input             hold1
);

assign SDRAM_nCS = 0;
assign SDRAM_CKE = 1;
assign {SDRAM_DQMH,SDRAM_DQML} = SDRAM_A[12:11];

localparam RASCAS_DELAY   = 3'd2; // tRCD=20ns -> 2 cycles@85MHz
localparam BURST_LENGTH   = 3'd0; // 0=1, 1=2, 2=4, 3=8, 7=full page
localparam ACCESS_TYPE    = 1'd0; // 0=sequential, 1=interleaved
localparam CAS_LATENCY    = 3'd2; // 2/3 allowed
localparam OP_MODE        = 2'd0; // only 0 (standard operation) allowed
localparam NO_WRITE_BURST = 1'd1; // 0=write burst enabled, 1=only single access write

localparam MODE = { 3'b000, NO_WRITE_BURST, OP_MODE, CAS_LATENCY, ACCESS_TYPE, BURST_LENGTH}; 

localparam STATE_IDLE  = 3'd0;             // state to check the requests
localparam STATE_START = STATE_IDLE+1'd1;  // state in which a new command is started
localparam STATE_CONT  = STATE_START+RASCAS_DELAY;
localparam STATE_READY = STATE_CONT+CAS_LATENCY+1'd1;
localparam STATE_LAST  = STATE_READY;      // last state in cycle

reg  [2:0] state;
reg [22:1] a;
reg [15:0] data;
reg        we;
reg  [1:0] ba = 0;
reg  [1:0] dqm;
reg        active = 0;
reg  [2:0] ram_req = 0;
wire [2:0] wr = {wrl2|wrh2,wrl1|wrh1,wrl0|wrh0};

// Anti-starvation for port 2 (the Paprium MCU). The arbiter below is strict
// fixed priority (refresh > port0 > port1 > port2), so under heavy port1
// (console / VDP stream-window) traffic the MCU on port2 can be starved for
// long stretches and fall behind on per-frame sprite/animation composition
// (issue #10: animations skip, worse with more enemies). Count how long port2
// has been waiting; once it exceeds STARVE2_LIMIT, let it win one arbitration
// round ahead of port0/port1. It only fires when port2 is genuinely starved,
// so non-Paprium cores (port2 = SVP) are unaffected in normal use. Reordering
// whole accesses is functionally safe: each access completes atomically and the
// per-port req/ack handshakes are independent - only timing/fairness changes.
// paprium: lowered from MisterPezz82's 24. Their own note says 24 "reduces (does
// not fully resolve)" the animation skipping, so the MCU is still starved at that
// value. Hardware here shows the elevator corrupting specifically WHEN A BACKGROUND
// ELEVATOR IS SCROLLING PAST - sustained tile streaming, exactly when port0/port1
// traffic peaks and port2 waits longest. 8 triples the MCU's worst-case service
// rate while still leaving the console 7 of every 8 rounds.
//
// The trade-off is real and needs watching: port0/port1 are the 68000 and VDP and
// have real-time deadlines, so cycles taken from them can create artefacts of their
// own. Test for NEW glitches elsewhere, not only whether the elevator improved.
// Restored to MisterPezz82's 24 after testing both directions on hardware.
//
// At 8 (3x more MCU bandwidth) the elevator glitched identically, and the build
// cost 1,145 ALMs and 0.87 ns for no benefit. At 96 (12x less) the elevator STILL
// glitched identically - but the game visibly slowed with dropped frames.
//
// That dissociation is the useful result. The knob demonstrably works: starve the
// MCU and frame pacing suffers, which is the animation skipping upstream logged as
// issue #10. But the elevator corruption is indifferent to MCU bandwidth in both
// directions, so starvation is NOT its cause - upstream's recorded root cause
// conflated two separate problems.
//
// 24 is kept because it is the value the animation-skipping fix was tuned to and
// neither direction improved on it.
localparam [7:0] STARVE2_LIMIT = 8'd24;
reg  [7:0] starve2 = 0;
wire       port2_pending = (ack2 != req2);
wire       boost2 = port2_pending && (starve2 >= STARVE2_LIMIT);

// paprium: refresh interval and the port-1 yield.
//
// The chip needs 8,192 auto refreshes every 64 ms, one per 7.8125 us at most. With no traffic a refresh is granted
// RFS_TOP + 2 ticks after the previous one (the compare tick, then the IDLE grant), so RFS_TOP = the 7.8125 us tick
// count - 2: 836 at NTSC (838 ticks = 7.804 us), 829 at PAL (831 ticks = 7.810 us). Upstream's 850 gave 852 ticks
// = 7.934 us, 1.6 % over. RFS_HALF arms the early refresh that rides on the next access (upstream's 425).
//
// The yield: the early refresh (RFS_HALF, carried in rfs from a grant) used to go first at IDLE even with a port-1
// read waiting. When a port-2 (MCU) access was in flight as a VDP DMA cart read arrived, the read then waited for
// the access AND a refresh and missed its 13-tick deadline: the VDP took the previous word again (4 pixels of a
// tile row repeated). Now only the top refresh (rfs_top, set at RFS_TOP) is mandatory; an early one waits while
// port 1 is pending and port 2 is not boosted, and port 0/1 grants keep it pending (rfs <= rfs2 | rfs) so it runs
// at the next free IDLE. Port 1's worst case is then 13 ticks (one access in flight plus its own), and no refresh
// interval exceeds RFS_TOP + 2 + one access in flight. Not covered: a boost2 grant ahead of a waiting port 1.
localparam integer RFS_IV    = CLK_MD_HZ / 128000;   // ticks in 7.8125 us (64 ms / 8,192), rounded down
localparam integer RFS_TOP_I = RFS_IV - 2;            // rfs_cnt is 10 bits: fine up to a 131 MHz clock
localparam   [9:0] RFS_TOP   = RFS_TOP_I[9:0];
localparam   [9:0] RFS_HALF  = RFS_TOP / 2;

// pocket: 0.3.0 new core - an unset (0) or out-of-range CLK_MD_HZ stops elaboration in every tool: the instance below
// names a module that does not exist. Unchecked, 0 would still build (RFS_TOP = 1022, about 9.5 us between refreshes at
// NTSC, over the chip's 7.8125 us), and so would a clock too fast for the 10-bit rfs_cnt
generate if (CLK_MD_HZ <= 0 || RFS_TOP_I < 2 || RFS_TOP_I > 1023) begin : clk_md_hz_check
	sdram_CLK_MD_HZ_is_unset_or_out_of_range clk_md_hz_bad();
end endgenerate

reg [15:0] dout;


assign dout0 = dout;
assign dout1 = dout;
assign dout2 = dout;


// paprium: the DMA hold (the new core's VDP DMA fix). A VDP DMA cart read is not waited for (no DTACK): the VDP's FIFO
// latch closes at a fixed tick of its strobe (CAS0, 16-20 ticks), and the full-system co-sim (2026-10-14) measured that
// a word whose cart_data changes 13 or 14 ticks after the strobe starts is lost - the VDP stores the previous word
// again, 4 pixels of a tile row - while one that changes by 10 is kept. Port 1 is granted on the second edge after the
// strobe starts and cart_data changes 9 ticks after it, so any access already running when the request arrives costs up
// to 6 ticks of that margin: the yield above stops a refresh chaining behind such an access, not the access itself.
// Measured on the WaterMelon logo: a port-2 MCU read (the SFX feeder) or a refresh granted 0-4 ticks before the strobe.
// The VDP announces every DMA slot: cart_dma (md_board's vdp_dma, the VDP's l6 | l8) rises 7 or 9 ticks before CAS0
// and falls with it. hold1 is cart_dma one register later (cartridge.sv), so hold_start's edge is 5 (or 7) ticks
// before the strobe and 7 (9) before port 1's grant edge. From that edge until port 1 is granted, or HOLD_MAX edges
// for a slot that reads work RAM and never requests port 1, nothing else is granted: no refresh (top or early), no
// port 0, no port 2 (boosted or not), and port 1 ignores boost2. An access granted on the edge before hold_start ends
// on the strobe's own edge, so the read is granted on time and cart_data changes 9 ticks into the strobe, every
// time. With cart_dma low (the 68000's reads, every non-Paprium build) the arbitration is the same as before, clock
// for clock. Costs: another port waits up to HOLD_MAX + 1 + 7 ticks per DMA slot (slots are >= 32 ticks apart), and a
// refresh due inside a hold waits for it (bench: longest interval 838-840 -> 855 ticks, only where the top refresh of
// an idle SDRAM meets a DMA slot; DMA traffic itself carries the early refresh every ~430-480 ticks)
localparam [3:0] HOLD_MAX = 4'd15;
reg        hold1_d = 1'b0;
reg        hold_on = 1'b0;
reg  [3:0] hold_n  = 4'd0;
wire       hold_start = hold1 & ~hold1_d;
wire       hold = hold_start | hold_on;

always @(posedge clk) begin
	hold1_d <= hold1;
	if (hold_start) begin
		hold_on <= 1'b1;
		hold_n  <= 4'd0;
	end
	else if (hold_on) begin
		hold_n <= hold_n + 1'd1;
		// released on the edge after port 1's grant (state START with ram_req[1]), or by the cap
		if ((state == STATE_START && ram_req[1]) || hold_n == HOLD_MAX) hold_on <= 1'b0;
	end
end

// access manager
always @(posedge clk) begin
	reg [9:0] rfs_cnt;
	reg rfs, rfs2, rfs_top;
	
	rfs_cnt <= rfs_cnt + 1'd1;
	if (rfs_cnt == RFS_TOP) begin
		rfs <= 1;
		rfs_top <= 1;   // paprium: the top refresh never yields
		rfs_cnt <= 0;
	end

	if (rfs_cnt == RFS_HALF) rfs2 <= 1;

	// Track how long port2 (MCU) has been waiting unserved.
	if (port2_pending) begin
		if (starve2 != 8'hff) starve2 <= starve2 + 1'd1;
	end else
		starve2 <= 0;

	if(state == STATE_IDLE && mode == MODE_NORMAL) begin
		if (rfs && !hold && (rfs_top || !(ack1 != req1 && !boost2))) begin   // paprium: an early refresh yields to a waiting port 1; nothing goes during a DMA hold
			rfs <= 0;
			rfs2 <= 0;
			rfs_top <= 0;
			rfs_cnt <= 0;
			we <= 0;
			dqm <= 2'b00;
			active <= 0;
			state <= STATE_START;
		end
		else if (ack0 != req0 && !boost2 && !hold) begin   // paprium: not during a DMA hold
			{ba,a} <= addr0;
			data <= din0;
			we <= wr[0];
			dqm <= wr[0] ? ~{wrh0,wrl0} : 2'b00;
			active <= 1;
			ram_req[0] <= 1;
			rfs <= rfs2 | rfs;   // paprium: a yielded refresh stays pending
			state <= STATE_START;
		end
		else if (ack1 != req1 && (!boost2 || hold)) begin   // paprium: a DMA read is not overtaken by a boosted port 2
			{ba,a} <= addr1;
			data <= din1;
			we <= wr[1];
			dqm <= wr[1] ? ~{wrh1,wrl1} : 2'b00;
			active <= 1;
			ram_req[1] <= 1;
			rfs <= rfs2 | rfs;   // paprium: a yielded refresh stays pending
			state <= STATE_START;
		end
		else if (ack2 != req2 && !hold) begin   // paprium: not during a DMA hold
			{ba,a} <= addr2;
			data <= din2;
			we <= wr[2];
			dqm <= wr[2] ? ~{wrh2,wrl2} : 2'b00;
			active <= 1;
			ram_req[2] <= 1;
			rfs <= rfs2;
			state <= STATE_START;
		end
	end

	if(state == STATE_READY && ram_req) begin
		dout <= SDRAM_DQ;
		active <= 0;
		ram_req <= 0;
		if (ram_req[0]) ack0 <= req0;
		else if (ram_req[1]) ack1 <= req1;
		else if (ram_req[2]) ack2 <= req2;
	end

	if(mode != MODE_NORMAL || state != STATE_IDLE || reset) begin
		state <= state + 1'd1;
		if(state == STATE_LAST) state <= STATE_IDLE;
	end
end


localparam MODE_NORMAL = 2'b00;
localparam MODE_RESET  = 2'b01;
localparam MODE_LDM    = 2'b10;
localparam MODE_PRE    = 2'b11;

// initialization 
reg [1:0] mode;
reg [4:0] reset=5'h1f;

initial reset=5'h1f;

always @(posedge clk) begin
	reg init_old=0;
	init_old <= init;

	if(init_old & ~init) reset <= 5'h1f;
	else if(state == STATE_LAST) begin
		if(reset != 0) begin
			reset <= reset - 5'd1;
			if(reset == 14)     mode <= MODE_PRE;
			else if(reset == 3) mode <= MODE_LDM;
			else                mode <= MODE_RESET;
		end
		else mode <= MODE_NORMAL;
	end
end

localparam CMD_NOP             = 3'b111;
localparam CMD_ACTIVE          = 3'b011;
localparam CMD_READ            = 3'b101;
localparam CMD_WRITE           = 3'b100;
localparam CMD_BURST_TERMINATE = 3'b110;
localparam CMD_PRECHARGE       = 3'b010;
localparam CMD_AUTO_REFRESH    = 3'b001;
localparam CMD_LOAD_MODE       = 3'b000;

// SDRAM state machines
always @(posedge clk) begin
	if(state == STATE_START) SDRAM_BA <= (mode == MODE_NORMAL) ? ba : 2'b00;

	SDRAM_DQ <= 'Z;
	casex({active,we,mode,state})
		{2'bXX, MODE_NORMAL, STATE_START}: {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= active ? CMD_ACTIVE : CMD_AUTO_REFRESH;
		{2'b11, MODE_NORMAL, STATE_CONT }: {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE, SDRAM_DQ} <= {CMD_WRITE, data};
		{2'b10, MODE_NORMAL, STATE_CONT }: {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_READ;

		// init
		{2'bXX,    MODE_LDM, STATE_START}: {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_LOAD_MODE;
		{2'bXX,    MODE_PRE, STATE_START}: {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_PRECHARGE;

		                          default: {SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE} <= CMD_NOP;
	endcase

	if(mode == MODE_NORMAL) begin
		casex(state)
			STATE_START: SDRAM_A <= a[13:1];
			STATE_CONT:  SDRAM_A <= {dqm, 2'b10, a[22:14]};
		endcase
	end
	else if(mode == MODE_LDM && state == STATE_START) SDRAM_A <= MODE;
	else if(mode == MODE_PRE && state == STATE_START) SDRAM_A <= 13'b0010000000000;
	else SDRAM_A <= 0;
end

altddio_out
#(
	.extend_oe_disable("OFF"),
	.intended_device_family("Cyclone V"),
	.invert_output("OFF"),
	.lpm_hint("UNUSED"),
	.lpm_type("altddio_out"),
	.oe_reg("UNREGISTERED"),
	.power_up_high("OFF"),
	.width(1)
)
sdramclk_ddr
(
	.datain_h(1'b0),
	.datain_l(1'b1),
	.outclock(clk),
	.dataout(SDRAM_CLK),
	.aclr(1'b0),
	.aset(1'b0),
	.oe(1'b1),
	.outclocken(1'b1),
	.sclr(1'b0),
	.sset(1'b0)
);

endmodule
