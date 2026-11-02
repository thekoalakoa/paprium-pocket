// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (the synth's first version) - paprium_synth_pkg: the synth's MCU-interface layout (the
// firmware's docs/MCU_INTERFACE.md v1.3 section 3.10, frozen) shared by the interface block (paprium_synth_if, B1), its
// CRAM client mux (paprium_synth_cram, B10) and the mixer blocks that read and write the voice / SFX fields (B2-B9; the
// synth's blocks are listed in paprium_synth.sv's header).
//
// The state RAM (one M10K, 256 x 32, byte lanes) holds the 16 voice windows (11 words each) and the 8 SFX windows
// (8 words each) = 240 words, at fixed addresses with no adder:
//   voice v word w, w = 0..7   -> {1'b0, v[3:0], w[2:0]}     0x00-0x7F
//   voice v word w, w = 8..10  -> {2'b10, v[3:0], w[1:0]}    0x80-0xBF (w[1:0] = 0..2; 3 unused)
//   SFX   c word w, w = 0..7   -> {2'b11, c[2:0], w[2:0]}    0xC0-0xFF
// A window word holds the chip's fields at the window offsets of 3.10.3 / 3.10.4; reserved bits read 0 (masked on
// every write and on every MCU read). The getters below return the field zero-extended (fld_u) or sign-extended
// (fld_s); each consumer takes the extension the cart uses for that field there (we reverse engineered the STM32F4's
// commands as close as possible, with hardware verification): sign-extended for LAST_* and Y, both ways for
// ENV_LEVEL, zero-extended for every other field.

package paprium_synth_pkg;

	// ---- region 0x06 global registers: word index addr[11:2] ----
	localparam [9:0] RG_ID      = 10'h000;   // 0x000
	localparam [9:0] RG_CONFIG  = 10'h001;   // 0x004
	localparam [9:0] RG_FLAGS   = 10'h002;   // 0x008
	localparam [9:0] RG_WMASTER = 10'h003;   // 0x00C
	localparam [9:0] RG_WBOOST  = 10'h004;   // 0x010
	localparam [9:0] RG_SMASTER = 10'h005;   // 0x014
	localparam [9:0] RG_SMCFG   = 10'h006;   // 0x018
	localparam [9:0] RG_ECHOB   = 10'h007;   // 0x01C
	localparam [9:0] RG_ECHOS   = 10'h008;   // 0x020
	localparam [9:0] RG_ARM     = 10'h009;   // 0x024
	localparam [9:0] RG_SEQ     = 10'h00A;   // 0x028
	localparam [9:0] RG_DONE    = 10'h00B;   // 0x02C
	localparam [9:0] RG_STATUS  = 10'h00C;   // 0x030
	localparam [9:0] RG_PHASE   = 10'h00D;   // 0x034
	localparam [9:0] RG_YMFILT  = 10'h00E;   // 0x038
	localparam [9:0] RG_DTOUT   = 10'h00F;   // 0x03C
	localparam [9:0] RG_DIAG    = 10'h010;   // 0x040
	localparam [9:0] RG_TIMEOUT = 10'h011;   // 0x044
	localparam [9:0] RG_SEQLAT  = 10'h012;   // 0x048
	localparam [9:0] RG_SCHED   = 10'h013;   // 0x04C

	localparam [31:0] SYNTH_ID  = 32'h5335_0001;   // 'S' '5', map revision 1

	// FLAGS bits (3.10.1)
	localparam integer FL_SEQON   = 0;
	localparam integer FL_PLAYING = 1;
	localparam integer FL_SFXON   = 2;
	localparam integer FL_BGMECHO = 3;
	localparam integer FL_SFXECHO = 4;
	localparam integer FL_LEVELNZ = 5;

	// CONFIG.MODE
	localparam [1:0] MODE_NONE = 2'd0, MODE_DT = 2'd1, MODE_YM = 2'd2;

	// ---- voice window words (3.10.3) ----
	localparam [3:0] VW_POS     = 4'd0;    // +0x00 POS u32 (24.8)
	localparam [3:0] VW_LEN     = 4'd1;    // +0x04 LEN u32
	localparam [3:0] VW_LOOP    = 4'd2;    // +0x08 LOOP u32
	localparam [3:0] VW_BASE    = 4'd3;    // +0x0C BASE [21:0]             a CRAM byte offset, 0x100 + dir
	localparam [3:0] VW_STEP    = 4'd4;    // +0x10 STEP u16 | +0x12 DECLICK s16
	localparam [3:0] VW_GAIN    = 4'd5;    // +0x14 GAIN_L u16 | +0x16 GAIN_R u16
	localparam [3:0] VW_LAST    = 4'd6;    // +0x18 LAST_L s16 | +0x1A LAST_R s16
	localparam [3:0] VW_ENV     = 4'd7;    // +0x1C ENV_LEVEL s16 | +0x1E ENV_CNT u16
	localparam [3:0] VW_STATE   = 4'd8;    // +0x20 ENV_STATE u8 | +0x21 BB u8 | +0x22 MUTE u16
	localparam [3:0] VW_RATES1  = 4'd9;    // +0x24 AR | HOLD | DR | SL (u8)
	localparam [3:0] VW_RATES2  = 4'd10;   // +0x28 SUS | D2R | RR | COMPAND (u8)
	localparam [3:0] VW_N       = 4'd11;   // words 11-15 reserved

	// ---- SFX window words (3.10.4) ----
	localparam [3:0] SW_PTR     = 4'd0;    // +0x00 PTR [21:0] (an even CRAM byte offset)
	localparam [3:0] SW_BASE    = 4'd1;    // +0x04 BASE [21:0]
	localparam [3:0] SW_POS     = 4'd2;    // +0x08 POS u32
	localparam [3:0] SW_LEN     = 4'd3;    // +0x0C LEN u32
	localparam [3:0] SW_FMT     = 4'd4;    // +0x10 FORMAT u8 | +0x11 RATE u8 | +0x12 ID u16
	localparam [3:0] SW_GAIN    = 4'd5;    // +0x14 GAIN_L u16 | +0x16 GAIN_R u16
	localparam [3:0] SW_LOOP    = 4'd6;    // +0x18 LOOP u8 | +0x19 FILT u8 | +0x1A Y s16
	localparam [3:0] SW_DELAY   = 4'd7;    // +0x1C DELAY u16, [31:16] reserved
	localparam [3:0] SW_N       = 4'd8;    // words 8-15 reserved

	// state RAM address of voice v word w (w < VW_N) and SFX c word w (w < SW_N)
	function automatic [7:0] vaddr(input [3:0] v, input [3:0] w);
		vaddr = w[3] ? {2'b10, v, w[1:0]} : {1'b0, v, w[2:0]};
	endfunction
	function automatic [7:0] saddr(input [2:0] c, input [3:0] w);
		saddr = {2'b11, c, w[2:0]};
	endfunction

	// the stored bits of each window word (0 = reserved word)
	function automatic [31:0] vmask(input [3:0] w);
		case (w)
			VW_BASE:                 vmask = 32'h003F_FFFF;
			4'd11, 4'd12, 4'd13, 4'd14, 4'd15: vmask = 32'h0000_0000;
			default:                 vmask = 32'hFFFF_FFFF;
		endcase
	endfunction
	function automatic [31:0] smask(input [3:0] w);
		case (w)
			SW_PTR, SW_BASE:         smask = 32'h003F_FFFF;
			SW_DELAY:                smask = 32'h0000_FFFF;
			SW_POS, SW_LEN, SW_FMT, SW_GAIN, SW_LOOP: smask = 32'hFFFF_FFFF;
			default:                 smask = 32'h0000_0000;
		endcase
	endfunction
	// the mask of a state RAM word by its address (the inverse of vaddr / saddr)
	function automatic [31:0] amask(input [7:0] a);
		if (a[7:6] == 2'b11)     amask = smask({1'b0, a[2:0]});
		else if (a[7] == 1'b1)   amask = (a[1:0] == 2'b11) ? 32'd0 : vmask({2'b10, a[1:0]});
		else                     amask = vmask({1'b0, a[2:0]});
	endfunction

	// ---- field getters: a field of a window word, zero- or sign-extended ----
	function automatic [31:0] fld_u(input [31:0] word, input [4:0] lsb, input [5:0] bits);
		reg [31:0] m;
		begin
			m     = (bits >= 6'd32) ? 32'hFFFF_FFFF : ((32'd1 << bits) - 32'd1);
			fld_u = (word >> lsb) & m;
		end
	endfunction
	function automatic [31:0] fld_s(input [31:0] word, input [4:0] lsb, input [5:0] bits);
		reg [31:0] u;
		reg  [4:0] t;
		begin
			u = fld_u(word, lsb, bits);
			t = bits[4:0] - 5'd1;
			fld_s = (bits < 6'd32 && u[t]) ? (u | ~((32'd1 << bits) - 32'd1)) : u;
		end
	endfunction

	// named voice fields (word, lsb, bits); the extension the cart uses in the comment (u = zero-extended, s =
	// sign-extended)
	localparam [4:0] F_STEP_L = 5'd0,  F_DECLICK_L = 5'd16;              // VW_STEP: u / u
	localparam [4:0] F_GAINL_L = 5'd0, F_GAINR_L = 5'd16;               // VW_GAIN: u / u
	localparam [4:0] F_LASTL_L = 5'd0, F_LASTR_L = 5'd16;               // VW_LAST: s / s
	localparam [4:0] F_LEVEL_L = 5'd0, F_CNT_L = 5'd16;                 // VW_ENV: s and u / u
	localparam [4:0] F_STATE_L = 5'd0, F_BB_L = 5'd8, F_MUTE_L = 5'd16; // VW_STATE: u (u16 in the cart) / u / u
	localparam [4:0] F_AR_L = 5'd0, F_HOLD_L = 5'd8, F_DR_L = 5'd16, F_SL_L = 5'd24;   // VW_RATES1: u (u16 in the cart)
	localparam [4:0] F_SUS_L = 5'd0, F_D2R_L = 5'd8, F_RR_L = 5'd16, F_COMP_L = 5'd24; // VW_RATES2: u x3, u
	// named SFX fields
	localparam [4:0] F_FMT_L = 5'd0, F_RATE_L = 5'd8, F_ID_L = 5'd16;   // SW_FMT: u (u16 in the cart) x2 / u
	localparam [4:0] F_SLOOP_L = 5'd0, F_FILT_L = 5'd8, F_Y_L = 5'd16;  // SW_LOOP: u / u / s

	// ---- CRAM die-0 map (3.8): byte offsets inside the MCU window, as the synth addresses them ----
	localparam [21:0] CR_BANK      = 22'h000100;   // the sample bank (VOICE BASE is already a CRAM offset)
	localparam [21:0] CR_BGMRING   = 22'h152100;   // 256 blocks x 40 pairs {L, R} s16
	localparam [21:0] CR_SFXRING   = 22'h15C100;   // 256 blocks x 20 pairs
	localparam [21:0] CR_DACBUF_L  = 22'h170000;   // dac_buf_L, 1,920 x u16
	localparam [21:0] CR_DACBUF_R  = 22'h170F00;   // dac_buf_R, 1,920 x u16
	localparam [21:0] CR_CURVE_WIN = 22'h180000;   // the curve window
	localparam [21:0] CR_CURVE_CTR = 22'h198000;   // curve index 0
	localparam [21:0] CR_SFXBANK   = 22'h200000;   // the SFX bank, 68000 words as values (SFX PTR / BASE)

endpackage
