// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket (0.3.0 synth step): a virtual Grand Stick III on console port A, answering the game's own stick reader.
//
// The game finds the stick at boot ($B1DBC), reads it once a frame ($B22C2: the first read $B1FC0 with TH low sees
// D3:D2 = 01 and goes on in $B210C), reads its 6-bit switch byte once per power-on or reset ($B5A32), and takes its
// coin in $B5924. This block sees only what a real stick sees: the TH line and, during the write-back, the console-
// driven D0-D3. It never sees a read strobe. The phase is the number of TH edges since the frame start; a frame starts
// after TMO clocks with no TH edge (the six-button pad rule, pad_io's 1.512 ms). What the stick drives on D5..D0:
//   phase 0   TH low   ID           ID_REST, D1 = 1 with a pad in the EXT socket (D2 = 1, D3 = 0: a stick)
//   phase 1   TH high  ~{C,B,R,L,D,U}   the stick's buttons, record word bits 0-5
//   phase 2   TH low   ~{Mode,X,Y,Z,St,A}  bits 6-11
//   phase 3   TH high  the EXT pad's bits 0-5 (read only when the ID says a pad is there; else the game's dummy toggle)
//   phase 4   TH low   the EXT pad's bits 6-11
//   phase 5   TH high  status A: STA_REST, D3 = a coin waiting (record +$A bit 5)
//   phase 6   TH low   status B: STB_REST (record +$B, which nothing reads)
//   phase 7   TH high  the switches {ARCADE, INF. CREDITS, DEMO, TWO COINS, NO HIT FX, 3 PLAYERS} (1 = ON, DIP n = bit n-1)
//   phase 8+           all 1; the rise into phase 9 carries the coin ACK nibble (record +$E | $20, D0-D3 driven by the
//                      console), the rises into 11 and 13 the lamp nibbles (not used here)
// Not known until a capture of a real stick: the ID, status A and B at rest, the timeout and the ACK rule. They
// are parameters, so a capture changes numbers, not logic. ID $14 and status A $02 are the constants the GPGX model
// was checked with (in our coin study). The only game-visible effect of the timeout is when a read may start; the
// game's reads are a frame apart and their edges microseconds apart, so any value between those reads the same.
//
// The coin: a press of coin_btn adds one waiting coin (at most 7). Status A D3 is 1 while one waits. The ACK nibble's
// bit 2 takes one coin, but only when it changes 0 -> 1 from the previous frame's ACK nibble: the game holds +$E = 4
// in every read until its coin handler runs again, which is 1 frame in 4 in one of its loops, so taking a coin on
// every nibble with bit 2 would take coins the game never counted (3 coins at once -> 0 credits; the GPGX model's
// "artefact", found in our coin study). With the edge rule every coin gives one credit after the game's own first-coin
// gate. hold (the Pocket menu froze the 68000) stops the idle timer, so a freeze in the middle of a read cannot restart
// the phase (that would make a phantom coin, as our Grand Stick study found).
//
// Output: gdata_nx is the value the stick's data register takes at the next clock; paprium_pads loads it into its
// look-ahead port register e_q, so the console's read path stays pa_d / pa_o and one register through one LUT.
// pocket-end

module paprium_gs3 #(
	parameter [5:0]  ID_REST  = 6'h14,
	parameter [5:0]  STA_REST = 6'h02,
	parameter [5:0]  STB_REST = 6'h3F,
	parameter [16:0] TMO      = 17'd81200      // 1.512 ms at 53.693 MHz
)
(
	input         clk,          // clk_sys_53_69, the pads' clock
	input         reset,        // sys_reset
	input         hold,         // inmenu_sys_s: the Pocket menu has paused the 68000
	/* verilator lint_off UNUSEDSIGNAL */
	input   [6:0] pa_o,         // console port A: data out (TH = bit 6, the ACK nibble = bits 3-0)
	input   [6:0] pa_d,         // and direction (1 = input)
	/* verilator lint_on UNUSEDSIGNAL */
	input  [11:0] btn,          // the stick, active high, word order {Mode,X,Y,Z,St,A,C,B,R,L,D,U}
	input         pt_on,        // a pad in the EXT socket
	input  [11:0] pt_btn,       // its buttons, the same order
	input   [5:0] dip,          // the switches, DIP 1-6 = bits 0-5, 1 = ON
	input         coin_btn,     // the held level of the coin button
	output reg [5:0] gdata_nx   // what the stick drives on D5-D0 from the next clock
);

localparam [3:0] PRE = 4'd15;                  // TH high at the frame start (power-on, or TH an input)

wire       th_line = pa_d[6] | pa_o[6];        // an undriven TH reads high, as with the pull-up
/* verilator lint_off PROCASSINIT */
reg        th_r = 1'b1, th_p = 1'b1;
reg  [3:0] ph = PRE;
reg [16:0] idle = 17'd0;
reg  [2:0] pend = 3'd0;
reg        ackp = 1'b0, coin_q = 1'b0;
/* verilator lint_on PROCASSINIT */

wire edge_th = th_r ^ th_p;
// the phase as it stands this clock: a timed-out line is a frame start (TH low) or the pre-frame state (TH high)
wire [3:0] ph_cur = (idle == TMO) ? (th_p ? PRE : 4'd0) : ph;
wire rise    = th_r & ~th_p;
wire ack_nib = rise & (ph_cur == 4'd8) & ~|pa_d[3:0];   // the first write-back strobe, D0-D3 driven by the console
wire ack_bit = pa_o[2];
wire take    = ack_nib & ack_bit & ~ackp & (pend != 3'd0);
wire give    = coin_btn & ~coin_q & (pend != 3'd7);

always @(posedge clk) begin
	th_r   <= th_line;
	th_p   <= th_r;
	coin_q <= coin_btn;
	if (reset) begin
		ph   <= PRE;
		idle <= 17'd0;
		pend <= 3'd0;
		ackp <= 1'b0;
	end
	else begin
		if (edge_th) begin
			idle <= 17'd0;
			ph   <= (ph_cur == PRE) ? (th_r ? PRE : 4'd0) : ((ph_cur == 4'd14) ? 4'd14 : ph_cur + 4'd1);
		end
		else begin
			ph <= ph_cur;
			if (~hold & (idle != TMO)) idle <= idle + 17'd1;
		end
		if (ack_nib) ackp <= ack_bit;
		pend <= pend + {2'b00, give} - {2'b00, take};
	end
end

// chosen by the phase as it stands, so it settles 2-3 clocks after a TH edge (the game reads >= 12 68000 clocks,
// 84 clk_sys, after its TH write)
always @(*) begin
	case (ph_cur)
		4'd0:    gdata_nx = ID_REST | {4'b0000, pt_on, 1'b0};
		4'd1:    gdata_nx = ~btn[5:0];
		4'd2:    gdata_nx = ~btn[11:6];
		4'd3:    gdata_nx = pt_on ? ~pt_btn[5:0]  : 6'h3F;
		4'd4:    gdata_nx = pt_on ? ~pt_btn[11:6] : 6'h3F;
		4'd5:    gdata_nx = STA_REST | {2'b00, (pend != 3'd0), 3'b000};
		4'd6:    gdata_nx = STB_REST;
		4'd7:    gdata_nx = dip;
		default: gdata_nx = 6'h3F;
	endcase
end

endmodule
