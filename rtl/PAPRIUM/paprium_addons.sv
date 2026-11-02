// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 32X Mode and the Mega CD list (0.2.6) - detection stubs, no add-on hardware.
//
// Paprium checks for a 32X and a Mega CD at boot. A 32X turns some throwables into
// 32X boxes; a Mega CD unlocks the CPU MATE option, whose partner is driven by a pad
// word the game reads from the Mega CD's sub-CPU ($A12024). Neither add-on is emulated
// here: these registers only answer the boot probes. Since xram step 2 (option D, the CPU MATE link of
// paprium_mcd_link and paprium_xlink): the
// partner's word is the cart MCU's, released by paprium_mcd_link at the modelled original's
// time into $A12024 (COMSTAT2), with the sub's honest busy bit in $A12020 bit 7. Both are
// flops loaded ahead of the read, so no read changes its bus timing; with option D off
// (xlink LCTRL[0] = 0) both read 0, as before. No 68000 code, no ROM patch.
//
//   32X      word reads at $A130EC/$A130EE return "MARS" ($4D41/$5253)
//   Mega CD  BIOS-ID bytes at $400120-$40014F, a gate-array stub at $A12000-$A1203F
//            (handshake latches and echoes, $A12022 = 'W' = sub-CPU alive), a PRG-RAM
//            probe word at $420000 and the "MB" marker at $420290. Word RAM is not
//            modelled. No DTACK, no SDRAM traffic of its own.
//
// Ported from the FAKEADDONS stub of the MiSTer Paprium test builds (MegaDrive.sv,
// fk_ block), which passed on hardware there: 32X boxes appear and CPU MATE unlocks.
// Both off gives en = 0, so the cartridge's own data reaches the console unchanged.
// Both are read at boot, so a change needs a reset.
//
// 0.2.6 options: the Mega CD is now a unit list. cd_unit
// picks which ID bytes the stub returns, and only the bytes the game's own check ($BC944,
// $BCA6A-$BCB6A) compares are returned; every compared word is driven for every unit, so
// nothing falls through to the cartridge ROM behind $400000 (an 8 MB ROM reads there).
// No Sega BIOS byte is copied: these are the ID letters and model digits the game tests.
//
// B Jam's menu (2026-10-09): one entry per unit; a unit sold in both regions takes the region
// from the Console list (paprium_opts below), so the stub's ID bytes do not depend on region.
//
//   cd_unit  OSD entry                  $400120 124  126  128  12C  14A  14C  14E   game sees
//    0       None                        (nothing driven)                            no CD
//    1       Aiwa CSD-GM1  (today's)     0000 424F 0000 0000 0000 0032 0031 3143   code 9
//    2       Mega-CD / Sega CD           0000 0000 0000 424F 0000 0031 0000 0000   flag 0x10
//    3       Mega-CD 2 / Sega CD 2       0000 0000 0000 424F 0000 0032 0030 3000   flag 0x20
//    4       Wondermega                  574F 0000 0000 0000 424F 0031 0000 0000   code 7
//    5       Wondermega M2 / X'Eye       574F 0000 0000 0000 424F 0032 0000 0000   code 6
//    6       LaserActive                 0000 004C 4400 424F 0000 0000 0000 0000   code 8
//    7       CDX                         0000 424F 0000 0000 0000 0032 0032 3100   code A
//    8       Unknown CD                  0000 424F 0000 0000 0000 0033 0000 0000   flag 0xF0
// The gate-array, PRG-RAM and "MB" part of the stub answers for every unit (cd_unit != 0).
//
// TMSS presence, lite (tmss_on = a console whose version nibble is 1). The game's $BC676 (run
// from RAM) reads byte $000120, clears $A14101 bit 0, reads $000120 again and sets the bit
// back: a different byte that is not 00/FF = a TMSS ROM was mapped. The cart's boot code
// also writes 'SEGA' to $A14000 when the version nibble is not 0. Here: DTACK for any access
// to $A14000-$A14003 and the $A14100/1 word (the arbiter gives none there, so without it the
// 68000 would wait for ever), a latch of $A14101 bit 0 (reset = 1, cart mapped, since there
// is no BIOS to run first), and while the latch is 0 a read of $000120 returns TMSS_BYTE
// instead of the cart. Nothing else is remapped, no Sega code or wording. The DTACK is a
// flop on the bus strobes, released with them, as cartridge.sv's dtack_ext is.
// pocket-end

module paprium_addons
(
	input             clk,          // clk_md_107_39, md_board's MCLK2
	input             reset,
	input             tmss_reset,   // 0.2.6: md_board's system reset (ext_reset), clears the TMSS latch

	input             en_32x,
	input       [3:0] cd_unit,      // 0.2.6: effective Mega CD unit (0 = none), see the table above
	input             tmss_on,      // 0.2.6: TMSS console (version nibble 1)

	input      [23:1] cart_addr,
	input             cart_oe,
	input             cart_lwr,
	input             cart_uwr,
	input      [15:0] cart_data_wr,

	// pocket: xram step 2 - option D (paprium_mcd_link, same clock)
	input             busy,         // COMSTAT0 bit 15: the sub is running a command
	input      [15:0] comstat2,     // $A12024: the partner's pad word
	output      [7:0] g3_q,         // $A12003 as written (bank bits [7:6] gate the PRG snoop)

	output            data_en,
	output reg [15:0] data_out,
	output reg        dtack         // 0.2.6: TMSS registers only
);

// 0.2.6: a byte a cart never has at $000120 is unknowable, so this is simply one that is not
// 00, not FF and not the byte Paprium's own header has there. Read with UDS (even address).
localparam [15:0] TMSS_BYTE = 16'h0101;

wire [23:0] a     = {cart_addr, 1'b0};
wire        en_cd = (cd_unit != 4'd0);
wire        gate  = (a[23:6] == 18'h28480);                 // $A12000-$A1203F
wire  [4:0] w     = a[5:1];

reg         en = 1'b0;
reg   [7:0] g1 = 8'h00, g2 = 8'h00, g3 = 8'h00;              // $A12001 / $A12002 / $A12003
reg   [7:0] c0 = 8'h00, c1 = 8'h00, c2 = 8'h00, c3 = 8'h00;  // $A12010-$A12013 comm bytes
reg  [15:0] prg = 16'h0000;                                  // $420000 probe word
wire  [7:0] g3r = {g3[7:3], 1'b0, g3[1], 1'b1};              // RET=1, MODE=0: (A12003 & 5) == 1
assign      g3_q = g3;

// 0.2.6: the BIOS-ID words. hdr = one of the eight compared words ($400120-$40014F)
wire        hdr  = (a[23:6] == 18'h10004) &                  // $400100-$40013F
                   ((a[5:1] == 5'h10) | (a[5:1] == 5'h12) | (a[5:1] == 5'h13) |
                    (a[5:1] == 5'h14) | (a[5:1] == 5'h16))
                 | (a[23:4] == 20'h40014) & (a[3:1] >= 3'd5); // $40014A/C/E
reg  [15:0] hdr_q;
always @(*) begin
	hdr_q = 16'h0000;
	case (a[7:1])
		7'h10: case (cd_unit)                                // $400120: 'W','O'
			4'd4, 4'd5: hdr_q = 16'h574F;
			default: ;
		endcase
		7'h12: case (cd_unit)                                // $400124: 'B','O' / -,'L'
			4'd1, 4'd7, 4'd8: hdr_q = 16'h424F;
			4'd6:             hdr_q = 16'h004C;
			default: ;
		endcase
		7'h13: case (cd_unit)                                // $400126: 'D'
			4'd6: hdr_q = 16'h4400;
			default: ;
		endcase
		7'h14: case (cd_unit)                                // $400128: 'B','O'
			4'd2, 4'd3, 4'd6: hdr_q = 16'h424F;
			default: ;
		endcase
		7'h16: case (cd_unit)                                // $40012C: 'B','O'
			4'd4, 4'd5: hdr_q = 16'h424F;
			default: ;
		endcase
		7'h25: case (cd_unit)                                // $40014A: -, model digit at $40014B
			4'd2, 4'd4:             hdr_q = 16'h0031;
			4'd1, 4'd3, 4'd5, 4'd7: hdr_q = 16'h0032;
			4'd8:                   hdr_q = 16'h0033;
			default: ;
		endcase
		7'h26: case (cd_unit)                                // $40014C: -, $40014D
			4'd1: hdr_q = 16'h0031;
			4'd3: hdr_q = 16'h0030;
			4'd7: hdr_q = 16'h0032;
			default: ;
		endcase
		7'h27: case (cd_unit)                                // $40014E: $40014E, $40014F
			4'd1: hdr_q = 16'h3143;
			4'd3: hdr_q = 16'h3000;
			4'd7: hdr_q = 16'h3100;
			default: ;
		endcase
		default: ;
	endcase
end

// 0.2.6: TMSS-lite
wire        tm_reg  = (a[23:2] == 22'h285000);               // $A14000-$A14003
wire        tm_bank = (a[23:1] == 23'h50A080);               // $A14100/$A14101
reg         cart_mapped = 1'b1;                              // $A14101 bit 0

always @(posedge clk) begin
	if (tmss_reset | ~tmss_on) cart_mapped <= 1'b1;
	else if (tm_bank & cart_lwr) cart_mapped <= cart_data_wr[0];

	dtack <= tmss_on & (tm_reg | tm_bank) & (cart_oe | cart_lwr | cart_uwr);
end

always @(posedge clk) begin
	if (reset) begin
		{g1, g2, g3} <= 24'd0;
		{c0, c1, c2, c3} <= 32'd0;
		prg <= 16'd0;
	end
	else if (en_cd) begin
		if (gate) case (w)
			5'd0: if (cart_lwr) g1 <= cart_data_wr[7:0];
			5'd1: begin if (cart_uwr) g2 <= cart_data_wr[15:8]; if (cart_lwr) g3 <= cart_data_wr[7:0]; end
			5'd8: begin if (cart_uwr) c0 <= cart_data_wr[15:8]; if (cart_lwr) c1 <= cart_data_wr[7:0]; end
			5'd9: begin if (cart_uwr) c2 <= cart_data_wr[15:8]; if (cart_lwr) c3 <= cart_data_wr[7:0]; end
			default: ;
		endcase
		if (a == 24'h420000) begin
			if (cart_uwr) prg[15:8] <= cart_data_wr[15:8];
			if (cart_lwr) prg[7:0]  <= cart_data_wr[7:0];
		end
	end
end

always @(posedge clk) begin
	en       <= 1'b0;
	data_out <= 16'h0000;
	if (cart_oe) begin
		if (en_32x) case (a)
			24'hA130EC: begin en <= 1'b1; data_out <= 16'h4D41; end   // "MA"
			24'hA130EE: begin en <= 1'b1; data_out <= 16'h5253; end   // "RS"
			default: ;
		endcase
		if (en_cd) begin
			if (hdr) begin en <= 1'b1; data_out <= hdr_q; end
			case (a)
				24'h420290: begin en <= 1'b1; data_out <= 16'h4D42; end   // "MB"
				24'h420000: begin en <= 1'b1; data_out <= prg;      end
				default: ;
			endcase
			if (gate) begin
				en <= 1'b1;
				case (w)
					5'd0:    data_out <= {8'h00, g1};
					5'd1:    data_out <= {g2, g3r};
					5'd8:    data_out <= {c0, c1};
					5'd9:    data_out <= {c2, c3};
					5'd16:   data_out <= {busy, 7'd0, c1}; // $A12020/21: busy, and the sub-CPU echoes $A12011
					5'd17:   data_out <= {8'h57, 8'h00}; // $A12022 = 'W', sub-CPU alive
					5'd18:   data_out <= comstat2;      // $A12024: COMSTAT2, the buddy word (option D)
					default: data_out <= 16'h0000;
				endcase
			end
		end
		// 0.2.6: TMSS ROM "mapped" (latch 0): $000120 is not the cart's byte
		if (tmss_on & ~cart_mapped & (a == 24'h000120)) begin en <= 1'b1; data_out <= TMSS_BYTE; end
	end
end

assign data_en = en;

endmodule


// 0.2.6: the console / Mega CD / MegaWire OSD options, decoded once on the APF
// side (clk_74a) into the few bits the console, the stub and the cart MCU need. Every output is a
// flop on static inputs; core_top carries them over with synch_3, like the other settings.
//
// B Jam's menu (2026-10-09): the OSD names carry no region tag; the console name implies it.
//
//   console (OSD value)       region  version  $1FE4 bits (fw)  expansion port   game code
//    0 Mega Drive              JP      0        -                yes              1   (today)
//    1 Genesis                 USA     0        -                yes              1
//    2 Mega Drive 2            JP      1+TMSS   0x700            yes              2
//    3 Genesis Model 2         USA     1+TMSS   0x700            yes              2
//    4 Genesis 3               USA     1+TMSS   0x000            no               3
//    5 Nomad                   USA     1+TMSS   0x400            no               4
//    6 Mega Jet                JP      1+TMSS   0x600            no               5
//    7 Unknown                 JP      0        bit 6            yes              F
//    8 TeraDrive (0.3.0)       JP      0        -                yes (see below)  B
//
//   megacd (OSD value)        region
//    0 None                    console's
//    1 Aiwa CSD-GM1            JP (fixed)       = the old "Mega CD Mode" on, so a persisted check
//                                                 keeps today's stub
//    2 Mega-CD / Sega CD       console's        separate unit
//    3 Mega-CD 2 / Sega CD 2   console's        separate unit
//    4 Wondermega              JP (fixed)
//    5 Wondermega M2 / X'Eye   console's        one picture (code 6) for both units
//    6 LaserActive             console's        code 8 in both regions
//    7 CDX                     USA (fixed)
//    8 Unknown CD              console's        separate unit
//    9-15                      = None
//
// Hardware rules: a combined unit (1, 4-7) is the console: its version nibble and TMSS come from the
// unit (table below) and the $1FE4 model bits are 0 (the game skips the console tests for codes 6-A
// anyway); its region is its own (Aiwa, Wondermega JP; CDX USA) or, for a unit sold in both regions
// (Wondermega M2 / X'Eye, LaserActive), the Console list's region. A console with no expansion port
// (Genesis 3, Nomad, Mega Jet) cannot take a separate Mega CD (2, 3, 8), which is then off. 32X is
// left alone. cd_real (= the buddy's Mega CD Mode) is any unit the game recognises; None and Unknown
// CD give 0. disk_n is the version register's DISK bit (0 = unit on).
//
// 0.3.0: TeraDrive (Console 8), B Jam's menu entry. The game tells a TeraDrive by its 128 KB of VRAM ($BC81C,
// only reached with version 0 and no combined unit) and then by 8 KB of Z80 RAM (code B, which this core has). td_en
// switches md_board's vram_td_stub on, the only part that answers that test; everything else is a Japanese Model 1
// (version 0, no $1FE4 model bits). A separate Mega CD unit is allowed with it (whether a real TeraDrive takes one is
// not known); a combined unit is the console, so it turns the stub off.
//
// 0.3.0: TMSS per combined unit. 0.2.6 gave every combined unit version 0 (no TMSS). B Jam
// (2026-10-11): every all-in-one unit shows the TMSS licence screen, the CDX included, and the CDX
// is set exactly like the others. So every combined unit reports version 1 and the core answers
// the TMSS check itself with the stand-in (tmss_on in paprium_addons), as on a Mega Drive 2: no
// licence screen, no BIOS file, the game boots straight in.
//   unit                    version / TMSS   source
//    1 Aiwa CSD-GM1          1                B Jam, 2026-10-11 (every all-in-one unit)
//    4 Wondermega            1                B Jam, 2026-10-11
//    5 Wondermega M2 / X'Eye 1                B Jam, 2026-10-11
//    6 LaserActive           1                B Jam, 2026-10-11
//    7 CDX                   1                B Jam's CDX, 2026-10-11
// The game reads it at boot ($BC944: version nibble 1 -> the TMSS probe $BC6BC sees the stand-in,
// then the unit's own code), so a change needs a reset like every other option here.
module paprium_opts
(
	input            clk,
	input      [3:0] console,         // 0.3.0: 4 bits, 8 = TeraDrive
	input      [3:0] megacd,
	output reg       jap     = 1'b1,  // version register bit 7 = ~jap
	output reg       ver1    = 1'b0,  // version nibble 1, and TMSS-lite on
	output reg [3:0] model   = 4'd0,  // {$1FE4 bit 10, 9, 8, 6} for the cart MCU
	output reg [3:0] cd_unit = 4'd0,  // effective unit for paprium_addons
	output reg       disk_n  = 1'b1,
	output reg       cd_real = 1'b0,
	output reg       td_en   = 1'b0   // 0.3.0: the TeraDrive stub (Console 8, no combined unit)
);

reg       c_jap, c_ver1, c_noexp;
reg [3:0] c_model;
always @(*) begin
	{c_jap, c_ver1, c_model, c_noexp} = {1'b1, 1'b0, 4'b0000, 1'b0};
	case (console)
		4'd1: {c_jap, c_ver1, c_model, c_noexp} = {1'b0, 1'b0, 4'b0000, 1'b0};
		4'd2: {c_jap, c_ver1, c_model, c_noexp} = {1'b1, 1'b1, 4'b1110, 1'b0};
		4'd3: {c_jap, c_ver1, c_model, c_noexp} = {1'b0, 1'b1, 4'b1110, 1'b0};
		4'd4: {c_jap, c_ver1, c_model, c_noexp} = {1'b0, 1'b1, 4'b0000, 1'b1};
		4'd5: {c_jap, c_ver1, c_model, c_noexp} = {1'b0, 1'b1, 4'b1000, 1'b1};
		4'd6: {c_jap, c_ver1, c_model, c_noexp} = {1'b1, 1'b1, 4'b1100, 1'b1};
		4'd7: {c_jap, c_ver1, c_model, c_noexp} = {1'b1, 1'b0, 4'b0001, 1'b0};
		4'd8: {c_jap, c_ver1, c_model, c_noexp} = {1'b1, 1'b0, 4'b0000, 1'b0};   // 0.3.0: TeraDrive
		default: ;
	endcase
end

wire [3:0] u        = (megacd > 4'd8) ? 4'd0 : megacd;
wire       separate = (u == 4'd2) | (u == 4'd3) | (u == 4'd8);
wire [3:0] unit     = (separate & c_noexp) ? 4'd0 : u;
wire       combined = (unit == 4'd1) | ((unit >= 4'd4) & (unit <= 4'd7));
wire       u_tmss   = combined;             // 0.3.0: every combined unit reports TMSS; see above

always @(posedge clk) begin
	// region: Aiwa and Wondermega are Japanese only, CDX is American only; every other unit
	// (Wondermega M2 / X'Eye, LaserActive, a separate unit, none) follows the Console list
	jap     <= (unit == 4'd7) ? 1'b0 : ((unit == 4'd1) | (unit == 4'd4)) ? 1'b1 : c_jap;
	ver1    <= combined ? u_tmss : c_ver1;
	model   <= combined ? 4'd0 : c_model;
	cd_unit <= unit;
	disk_n  <= (unit == 4'd0);
	cd_real <= (unit != 4'd0) & (unit != 4'd8);
	td_en   <= (console == 4'd8) & ~combined;
end

endmodule
