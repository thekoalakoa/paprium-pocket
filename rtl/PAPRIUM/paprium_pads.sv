// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: the controller ports for Paprium (0.3.0 new core): three Pocket controllers and an emulated EA 4-Way Play.
//
// fourway = 0 is 0.2.6 exactly: pad 1 on port A, pad 2 on port B, each a pad_io on its own port (with mode6 = the
// 0.2.6 MODE, which core_top gives it then).
//
// fourway = 1 (B Jam's revised decision of 2026-10-11 on the EA 4-Way Play: when the Pocket menu's 3-Player Mode = On
// or Arcade Mode = Multiplayer, taken at boot in core_top, as if the adapter were plugged in before power-on): an EA
// 4-Way Play on ports A and B, as upstream's fourway.sv and Genesis Plus GX model it. The console writes the pad
// number on port B (bits 6-4, latched when bits 1-0 read 0, pins the console does not drive reading 1); port A then
// carries that pad, and only that pad sees the console's TH. Number 4-7 answers the adapter's id ($7C: bits 1-0 low).
// The game detects it at boot ($B1E3C), then reads pads A, B and C every frame ($B1EB4) and never pad D. Pad A =
// Pocket controller 1, B = 2, C = 3; pad C counts only when controller 3 is a docked pad (type 2 or 3 in bits 31-28,
// so a docked keyboard, which also reports as controller 3, is not a pad); an empty slot (pad C without a docked pad,
// pad D always) reads as nothing plugged in: the lines pulled high, as a real adapter with nothing in that socket.
// Port B reads back what the console drives. The select latch powers up on pad A and is cleared by the console reset,
// as Genesis Plus GX's latch is (the game rewrites it before any read after a reset anyway).
//
// The game itself supports the adapter: with it, Arena takes three players, and Arcade takes three with the map code
// or the Grand Stick III DIP bit (Arcade Mode Multiplayer). Players 1 and 2 play as before (Genesis Plus GX, same
// inputs with and without the adapter). Its pad read through the adapter is a six-button read, and on this core it
// works (an RTL bench of the game's own code: X/Y/Z/Mode reach all three records), where the 0.2.6 direct-port read
// never saw a six-button pad. With the adapter, mode6 (pad_io's MODE) is the 6-Button switch (0.3.0): on =
// six-button pads, off = three-button pads.
//
// 0.3.0 test build 4 (the 0.3.0 hardware test build of the MCU fast path) (B Jam 2026-10-16, the controller fixes): (1)
// mode6 is the 6-Button switch on the direct ports too, and pad_io now counts the first TH rise of a read that starts
// with TH low, so the game's own direct-port read ($B1FC0) finds a real six-button pad (type 2: X/Y/Z/Mode by its read,
// B + forward no longer does the Z action), as with the adapter; (2) a pad answers only when its Pocket controller is
// there, on the direct ports and in the adapter's sockets alike (pad C as before): an empty port or socket reads as
// nothing plugged in (no phantom player 2 on a handheld Pocket), so the Boom Box shows a badge only for the pads that
// are there, each of the 6-Button type.
//
// 0.3.0 synth step (B Jam's decisions 6a-6c of 2026-10-19 / 2026-10-21): gs3_on = a Grand Stick III in port 1
// (paprium_gs3): port A answers the game's own stick reader instead of pad 1, so the game runs its own arcade code
// on the unpatched ROM. Pocket controller 1 is the stick (the same button map as pad 1; Select is the stick's Mode
// button, or the coin while Arcade is on: gs3_coin), Dock controller 3 is the pad in the stick's EXT socket when
// gs3_pt (Multiplayer or 3-Player Mode), port B stays pad 2. core_top never sets fourway with gs3_on (no EA 4-Way
// Play with the stick on). gs3_on = 0 is test build 4 exactly, on every clock (checked on our pads bench).
// pocket-end

module paprium_pads
(
	input        clk,         // clk_sys_53_69, as the pads always ran
	input        reset,       // sys_reset
	input        mode6,       // pad_io MODE (core_top: 6-Button with the adapter, 0.2.6's cfg_6btn without)
	input        fourway,     // 1 = EA 4-Way Play on ports A/B; 0 = 0.2.6's two ports (static while the game runs)
	input        fourway_nx,  // the value fourway takes at the next clock (its synch_3's nxt), for the look-ahead below
	input  [3:0] key3_type_nx, // the value key3[31:28] takes at the next clock (cont3_sync's nxt), ditto
	// synth step: the Grand Stick III, all taken at boot in core_top and static while the game runs
	input        gs3_on,      // the stick in port 1 (Arcade Mode On, Multiplayer or Stick Only)
	input        gs3_on_nx,   // the value gs3_on takes at the next clock (its synch_3's nxt), for e_q below
	input        gs3_pt,      // the EXT socket holds Dock controller 3 (Multiplayer, or 3-Player Mode)
	input  [5:0] gs3_dip,     // the switch byte, DIP 1-6 = bits 0-5
	input        gs3_coin,    // Select is the coin (Arcade Mode On or Multiplayer)
	input        hold,        // the Pocket menu has paused the 68000 (inmenu_sys_s)

	/* verilator lint_off UNUSEDSIGNAL */
	input [31:0] key1,        // Pocket cont1-3 keys, already in this clock domain (buttons [15:0],
	input [31:0] key2,        // type [31:28]: test build 4 reads it for controllers 1 and 2 too; the rest is unused)
	input [31:0] key3,
	/* verilator lint_on UNUSEDSIGNAL */

	input  [6:0] pa_o,        // console port A: data out, direction (1 = input)
	input  [6:0] pa_d,
	input  [6:0] pb_o,
	input  [6:0] pb_d,
	output [6:0] pa_i,        // what the console reads on port A / B
	output [6:0] pb_i
);

// pocket: 0.3.0 new core, fit round 2 (its second round of fits and timing fixes) - the port reads are built from
// look-ahead registers. Before, the console's read of port A went n -> pad number decode -> dir -> pad_io's port_out ->
// the 5-way pad mux -> the I/O chip's read mux -> md_board's VD: up to four LUTs of this clk_sys logic in front of the
// clk_md data bus (sys -> md setup -0.122 ns at slow 85C on round-1 seed 2, n[0] -> VD[1]; the VA -> VD class shares
// the read mux). Every select and the selected pad's data are now registers that hold exactly what the old decode gave
// on the same clock: each is loaded from the NEXT value of its inputs (n's own D input; fourway_nx and key3_type_nx
// from their synchronisers' second stage; pad_io's pdata_nx). So a read is pa_d / pa_o (the console's own pins) and
// four registers through one LUT, the same value on every clock as before (our pads bench: old against new from
// power-up, every clock). The pads' TH logic (dir1-3, in2) sees the same values as before too.

// the adapter's select latch (as before, written as its D input)
wire [6:0] pb_rd = pb_d | pb_o;              // port B as the adapter sees it: undriven pins pulled high
reg  [2:0] n;
initial n = 3'd0;
wire [2:0] n_nx = reset ? 3'd0 : (fourway & ~|pb_rd[1:0]) ? pb_rd[6:4] : n;
always @(posedge clk) n <= n_nx;

wire [5:0] pd2;                              // pad 2's data register (port B without the adapter)
wire [5:0] pd1_nx, pd2_nx, pd3_nx;           // the values pad_io's data registers take at the next clock
wire [5:0] g_nx;                             // synth step: ditto for the Grand Stick III (paprium_gs3, below)

// the look-ahead registers, power-up = the decode of the power-up state (n = 0, fourway = 0: pad 1 on port A)
//   s7c = fourway & n[2]          the adapter's id answer
//   u1  = ~(~fourway | n == 0)    pad 1 not selected (stored inverted, so it powers up 0)
//   s2  = fourway & n == 1,  s3 = fourway & n == 2
//   e   = the selected pad's data bits 5-0: pad 1 / pad 2 / pad 3 when it is a docked pad / none (all 1);
//         synth step: the Grand Stick III in pad 1's place while it is on
/* verilator lint_off PROCASSINIT */
reg       s7c_q = 1'b0, u1_q = 1'b0, s2_q = 1'b0, s3_q = 1'b0;
reg [5:0] e_q   = 6'd0;
/* verilator lint_on PROCASSINIT */
wire      sel1_nx = ~fourway_nx | (n_nx == 3'd0);
wire      sel2_nx = fourway_nx & (n_nx == 3'd1);
wire      sel3_nx = fourway_nx & (n_nx == 3'd2);
wire      p3_on_nx = (key3_type_nx == 4'd2) | (key3_type_nx == 4'd3);   // a docked pad on controller 3
// test build 4: controllers 1 and 2 are there when their type is 1 (the Pocket's own controls), 2 or 3 (a docked pad);
// 0 is none, 4 / 5 a docked keyboard / mouse (APF controller types). Registered from the synchronised key words: a
// plug-in is asynchronous to the game anyway, so the clock of delay changes nothing it can see
/* verilator lint_off PROCASSINIT */
reg       p1_on_q = 1'b0, p2_on_q = 1'b0;
/* verilator lint_on PROCASSINIT */
always @(posedge clk) begin
	p1_on_q <= (key1[31:28] == 4'd1) | (key1[31:28] == 4'd2) | (key1[31:28] == 4'd3);
	p2_on_q <= (key2[31:28] == 4'd1) | (key2[31:28] == 4'd2) | (key2[31:28] == 4'd3);
end
always @(posedge clk) begin
	s7c_q <= fourway_nx & n_nx[2];
	u1_q  <= ~sel1_nx;
	s2_q  <= sel2_nx;
	s3_q  <= sel3_nx;
	// test build 4: a selected pad whose controller is not there answers nothing (all 1), like an unselected socket.
	// synth step: with the stick on, port A is the stick's data register (its next value, as pad 1's)
	e_q   <= (sel1_nx & gs3_on_nx) ? g_nx :
	         (sel1_nx & p1_on_q) ? pd1_nx : (sel2_nx & p2_on_q) ? pd2_nx : (sel3_nx & p3_on_nx) ? pd3_nx : 6'h3F;
end

// synth step: the Grand Stick III. Its buttons are controller 1's in the stick's word order
// {Mode,X,Y,Z,St,A,C,B,R,L,D,U}, with pad 1's map (MD A-B-C on Y-B-A; Mode = Select, X = L, Y = X, Z = R); Select is
// the coin instead of Mode while gs3_coin. The EXT pad is controller 3 when it is a docked pad, three-button with
// 6-Button off (as pad_io's MODE). A controller that is not there presses nothing. While the stick is off it is held
// in reset, so a boot with the stick on starts it in the pre-frame state with no coin waiting
wire        p3_on_g  = (key3[31:28] == 4'd2) | (key3[31:28] == 4'd3);
wire [11:0] gs3_stk  = {key1[14] & ~gs3_coin, key1[8], key1[6], key1[9], key1[15], key1[7],
                        key1[4], key1[5], key1[3], key1[2], key1[1], key1[0]} & {12{p1_on_q}};
wire [11:0] gs3_ext  = {key3[14], key3[8], key3[6], key3[9], key3[15], key3[7],
                        key3[4], key3[5], key3[3], key3[2], key3[1], key3[0]} & {{4{mode6}}, 8'hFF};
paprium_gs3 gs3 (
	.clk(clk), .reset(reset | ~gs3_on), .hold(hold), .pa_o(pa_o), .pa_d(pa_d),
	.btn(gs3_stk), .pt_on(gs3_pt & p3_on_g), .pt_btn(gs3_ext), .dip(gs3_dip),
	.coin_btn(key1[14] & gs3_coin & p1_on_q), .gdata_nx(g_nx)
);

wire [6:0] dir1  = u1_q ? 7'h7F : pa_d;      // an unselected pad sees no TH
wire [6:0] dir2  = ~fourway ? pb_d : s2_q ? pa_d : 7'h7F;
wire [6:0] in2   = fourway ? pa_o : pb_o;
wire [6:0] dir3  = s3_q ? pa_d : 7'h7F;

// a pin the console drives reads back its own level; an input pin reads the selected pad (or 1 when no pad answers;
// test build 4: also when pad 2's controller is not there, on port B without the adapter)
assign pa_i = s7c_q ? 7'h7C : ((~pa_d & pa_o) | (pa_d & {1'b1, e_q}));
assign pb_i = fourway ? pb_rd : ((~pb_d & pb_o) | (pb_d & {1'b1, pd2 | {6{~p2_on_q}}}));

// MD A-B-C lands on Y-B-A, as on the fpgagen Genesis core (0.2.6's mapping, unchanged). port_out is no longer read
// (the reads above use the data registers); pads 1 and 3 give only their next data value
/* verilator lint_off PINCONNECTEMPTY */
pad_io pad1 (
	.clk(clk), .reset(reset), .MODE(mode6), .SMS(1'b0),
	.P_UP(key1[0]), .P_DOWN(key1[1]), .P_LEFT(key1[2]), .P_RIGHT(key1[3]),
	.P_C(key1[4]), .P_B(key1[5]), .P_A(key1[7]), .P_Y(key1[6]), .P_X(key1[8]), .P_Z(key1[9]),
	.P_MODE(key1[14]), .P_START(key1[15]),
	.GUN_EN(1'b0), .GUN_TYPE(1'b0), .GUN_SENSOR(1'b0), .GUN_A(1'b0), .GUN_B(1'b0), .GUN_C(1'b0), .GUN_START(1'b0),
	.MOUSE_EN(1'b0), .MOUSE_FLIPY(1'b0), .MOUSE(25'd0),
	.port_out(), .port_in(pa_o), .port_dir(dir1), .pdata_q(), .pdata_nx(pd1_nx)
);

pad_io pad2 (
	.clk(clk), .reset(reset), .MODE(mode6), .SMS(1'b0),
	.P_UP(key2[0]), .P_DOWN(key2[1]), .P_LEFT(key2[2]), .P_RIGHT(key2[3]),
	.P_C(key2[4]), .P_B(key2[5]), .P_A(key2[7]), .P_Y(key2[6]), .P_X(key2[8]), .P_Z(key2[9]),
	.P_MODE(key2[14]), .P_START(key2[15]),
	.GUN_EN(1'b0), .GUN_TYPE(1'b0), .GUN_SENSOR(1'b0), .GUN_A(1'b0), .GUN_B(1'b0), .GUN_C(1'b0), .GUN_START(1'b0),
	.MOUSE_EN(1'b0), .MOUSE_FLIPY(1'b0), .MOUSE(25'd0),
	.port_out(), .port_in(in2), .port_dir(dir2), .pdata_q(pd2), .pdata_nx(pd2_nx)
);

pad_io pad3 (
	.clk(clk), .reset(reset), .MODE(mode6), .SMS(1'b0),
	.P_UP(key3[0]), .P_DOWN(key3[1]), .P_LEFT(key3[2]), .P_RIGHT(key3[3]),
	.P_C(key3[4]), .P_B(key3[5]), .P_A(key3[7]), .P_Y(key3[6]), .P_X(key3[8]), .P_Z(key3[9]),
	.P_MODE(key3[14]), .P_START(key3[15]),
	.GUN_EN(1'b0), .GUN_TYPE(1'b0), .GUN_SENSOR(1'b0), .GUN_A(1'b0), .GUN_B(1'b0), .GUN_C(1'b0), .GUN_START(1'b0),
	.MOUSE_EN(1'b0), .MOUSE_FLIPY(1'b0), .MOUSE(25'd0),
	.port_out(), .port_in(pa_o), .port_dir(dir3), .pdata_q(), .pdata_nx(pd3_nx)
);
/* verilator lint_on PINCONNECTEMPTY */

endmodule
