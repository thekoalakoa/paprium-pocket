// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: Scum! - the Pocket menu's cheat and arcade switches for Paprium (0.2.6, moved in 0.3.0).
//
// Every switch is a ROM-read substitution: while it is on, the 68000 reads a few
// replacement words in place of the game's own code, and the ROM file in SDRAM is
// never written. Off means the original bytes, so a switch can be flipped at any time;
// the arcade stage is read at boot, so it needs a reset.
//
//   en_health   players take no damage; their throws do no damage to enemies   (Little-Man)
//   en_pills    using a Blu pill (Down+A) no longer spends it         (Little-Man)
//   en_lives    dying no longer spends a life                         (Little-Man)
//   stage       the stage arcade mode starts on (krikzz); 0.3.0: only with Arcade Mode on
//
// 0.3.0 synth step (B Jam's decisions of 2026-10-19 / 2026-10-21): Arcade Mode is now a virtual Grand Stick III in port
// 1 (paprium_pads / paprium_gs3). The game reads the stick's switches and coin itself and runs its own arcade code on
// the unpatched ROM, so the arcade patch (adroxe's two nops at 0x0B5AB8 / 0x0B5ACC), the Multiplayer nop
// (0x0B5B1A), the pad hook (0x0B2392), the pad cave and its registers (0x0BF040-0x0BF0CB), the coin stub (0x0BF100)
// and the just-pressed latches are gone: 122 table words became 32. en_arcade, en_arc3p, en_tap, en_6btn, pad1 and
// pad2 are no longer read (the ports stay, so cartridge.sv and core_top's scum_sync are unchanged). With Arcade Mode
// off, hit and (where hit is 1) data are those of test build 4 (the 0.3.0 hardware test build of the MCU fast path) on
// every clock: none of the removed words could be served while Arcade Mode was off (checked on our Scum! bench).
//   en_arcade   test build 4: the hidden ARCADE PAPRIUM mode (adroxe), Select inserting a coin; synth step: not read
//   en_arc3p    test build 4: Arcade Mode Multiplayer (the stick's DIP bit 0 as a nop); synth step: not read
//   en_6btn     test build 4: only gated the hook's Mode injection; synth step: not read (the game reads X/Y/Z/Mode
//   itself)
//   en_tap      test build 4 and the synth step: not read
//
// xram step 2 (the second step of our Pocket SRAM / CRAM work): Mega CD Mode is no longer a Scum! switch. The CPU MATE
// partner is the cart MCU's (paprium_mcd_link, option D), so the 68000 buddy page and
// RAM (G_BUDDY, $16C000/$16FF00) and the pad hook in Mega CD Mode (G_HOOK) are gone:
// with Little-Man, Arcade, Stage and 6-Button off, the 68000 runs the unpatched ROM
//
// The approach and the pad hook are MisterPezz82's (Paprium MiSTer V.05/V.06); the
// arcade unlock and the Mode-button credit are adroxe's (Paprium-Arcade); the stage
// byte is krikzz's. The cheat sites were found on Genesis Plus GX with a 68000 write
// watch. Pezz's injection put X in bit 8 and Z in bit 10; the game's own 6-button read
// puts Z in bit 8 and X in bit 10 (SGDK's layout), so this follows the game.
//
// Timing: rom_addr is latched when an SDRAM read starts and holds for the whole
// access, so the table is looked up one clock later into registers and the result is
// ready long before the read returns. The cartridge applies it to every console read of
// the ROM, 68000 and VDP DMA alike, so a DMA copies a substituted word too. That is why
// nothing may sit in game data: 0.2.6 served the pad cave and its registers at
// 0x11C560-0x11C60B, inside the Hall of Fame name-entry bar's tiles, which then showed
// garbage. 0.3.0 serves the health cave in the zero padding the game never reads
// (0x0BF000; scripts/scum_table.py --check refuses any word in 0x11C560-0x11C75F; the synth
// step has no pad cave at all). The MCU's decompression stream never sees a substituted word.
//
// Flip guard (0.3.0): the switches the table uses are latched copies, taken only on a
// served read of the flip point 0x0B238C, the pad read's last instruction (before the
// hook, while there was one). No cave can be running there (the health cave is a leaf;
// the VBlank handlers are leaves), so a switch change can never split a patched
// instruction or pull a cave from under the 68000, not even when the Pocket menu froze
// the 68000 inside one and an interrupt is pending on resume. A change takes effect at
// the game's next pad read (every frame in play; twice in the boot routine before its
// arcade test, so a stage chosen before a reset still applies).
// pocket-end

module paprium_scum
(
	input             clk,
	/* verilator lint_off UNUSEDSIGNAL */
	input             reset,        // synth step: not read (it cleared the just-pressed latches)
	/* verilator lint_on UNUSEDSIGNAL */

	input      [24:1] rom_addr,     // word address of the SDRAM read in flight
	input             served,       // a 68000 ROM read is being latched into cart_data

	input             en_health,
	input             en_pills,
	input             en_lives,
	/* verilator lint_off UNUSEDSIGNAL */
	input             en_arcade,    // synth step: not read (the Grand Stick III, see above)
	input             en_arc3p,     // synth step: not read
	input             en_tap,       // 0.3.0: the EA 4-Way Play present; test build 4: not read (see above)
	input             en_6btn,      // synth step: not read
	/* verilator lint_on UNUSEDSIGNAL */
	input       [4:0] stage,        // 0 = off, 1-24 = stage 0x01-0x18, 25 = 0x1E

	/* verilator lint_off UNUSEDSIGNAL */
	input       [3:0] pad1,         // {MODE,X,Y,Z} held; synth step: not read (no pad hook)
	input       [3:0] pad2,
	/* verilator lint_on UNUSEDSIGNAL */

	output reg        hit,
	output reg [15:0] data
);

localparam [3:0] G_NONE = 4'd0, G_HEALTH = 4'd1, G_PILLS = 4'd2, G_LIVES = 4'd3,
                 G_STAGE = 4'd7,
                 G_FLIP = 4'd8;     // the flip point: never substituted

// the switches in use: taken from the inputs only on a served read of the flip point;
// all off at configuration (the game boots with no switch until its first pad read)
reg        q_health, q_pills, q_lives;
reg  [4:0] q_stage;
reg        flip_q;              // rom_addr is the flip point (registered lookup)
initial begin
	{q_health, q_pills, q_lives} = 3'b000;
	q_stage = 5'd0;
	flip_q  = 1'b0;
end

always @(posedge clk) begin
	if (served & flip_q) begin
		q_health <= en_health;
		q_pills  <= en_pills;
		q_lives  <= en_lives;
		q_stage  <= stage;
	end
end

wire [7:0] stage_byte = (q_stage == 5'd25) ? 8'h1E : {3'b000, q_stage};

always @(posedge clk) begin
	reg  [3:0] g;
	reg [15:0] w;

	g = G_NONE;
	w = 16'h0000;
	case (rom_addr)
		// @@scum-table-begin  (generated by scripts/scum_table.py --write; do not edit by hand)
		// players take no damage (jsr to the slot test); a player's throws do no damage to enemies (two nops)
		24'h017D62: begin g = G_HEALTH; w = 16'h4EB9; end   // 0x02FAC4
		24'h017D63: begin g = G_HEALTH; w = 16'h000B; end   // 0x02FAC6
		24'h017D64: begin g = G_HEALTH; w = 16'hF000; end   // 0x02FAC8
		24'h018745: begin g = G_HEALTH; w = 16'h4E71; end   // 0x030E8A
		24'h018746: begin g = G_HEALTH; w = 16'h4E71; end   // 0x030E8C
		24'h05F800: begin g = G_HEALTH; w = 16'h200A; end   // 0x0BF000
		24'h05F801: begin g = G_HEALTH; w = 16'h0280; end   // 0x0BF002
		24'h05F802: begin g = G_HEALTH; w = 16'h00FF; end   // 0x0BF004
		24'h05F803: begin g = G_HEALTH; w = 16'hFFFF; end   // 0x0BF006
		24'h05F804: begin g = G_HEALTH; w = 16'h0480; end   // 0x0BF008
		24'h05F805: begin g = G_HEALTH; w = 16'h00FF; end   // 0x0BF00A
		24'h05F806: begin g = G_HEALTH; w = 16'h8710; end   // 0x0BF00C
		24'h05F807: begin g = G_HEALTH; w = 16'h6516; end   // 0x0BF00E
		24'h05F808: begin g = G_HEALTH; w = 16'hE088; end   // 0x0BF010
		24'h05F809: begin g = G_HEALTH; w = 16'h5280; end   // 0x0BF012
		24'h05F80A: begin g = G_HEALTH; w = 16'h0C80; end   // 0x0BF014
		24'h05F80B: begin g = G_HEALTH; w = 16'h0000; end   // 0x0BF016
		24'h05F80C: begin g = G_HEALTH; w = 16'h00FF; end   // 0x0BF018
		24'h05F80D: begin g = G_HEALTH; w = 16'h620A; end   // 0x0BF01A
		24'h05F80E: begin g = G_HEALTH; w = 16'hB039; end   // 0x0BF01C
		24'h05F80F: begin g = G_HEALTH; w = 16'h00FF; end   // 0x0BF01E
		24'h05F810: begin g = G_HEALTH; w = 16'h9903; end   // 0x0BF020
		24'h05F811: begin g = G_HEALTH; w = 16'h6402; end   // 0x0BF022
		24'h05F812: begin g = G_HEALTH; w = 16'h7600; end   // 0x0BF024
		24'h05F813: begin g = G_HEALTH; w = 16'h302A; end   // 0x0BF026
		24'h05F814: begin g = G_HEALTH; w = 16'h0088; end   // 0x0BF028
		24'h05F815: begin g = G_HEALTH; w = 16'hB640; end   // 0x0BF02A
		24'h05F816: begin g = G_HEALTH; w = 16'h4E75; end   // 0x0BF02C
		// Blu pills are never spent: the decrement becomes nop
		24'h00D4FD: begin g = G_PILLS;  w = 16'h4E71; end   // 0x01A9FA
		24'h00D4FE: begin g = G_PILLS;  w = 16'h4E71; end   // 0x01A9FC
		// lives are never spent: the decrement becomes nop
		24'h015277: begin g = G_LIVES;  w = 16'h4E71; end   // 0x02A4EE
		// arcade start stage (krikzz): 0x0001 = Block 888
		24'h05850A: begin g = G_STAGE;  w = {8'h00, stage_byte}; end   // 0x0B0A14
		// the flip point (never substituted): new switches are taken on a served read here
		24'h0591C6: begin g = G_FLIP;   w = 16'h0000; end   // 0x0B238C
		// @@scum-table-end
		default: ;
	endcase

	hit <= ((g == G_HEALTH) & q_health) | ((g == G_PILLS) & q_pills) |
	       ((g == G_LIVES)  & q_lives)  |
	       ((g == G_STAGE) & (q_stage != 5'd0));
	data <= w;
	flip_q <= (g == G_FLIP);
end

endmodule
