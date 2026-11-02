// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 new core - the cart register file at $1FE0-$1FFF, seen from both sides. "Since the sprite-decoder
// step" below = since the cart FPGA's sprite decoder (paprium_hwdec) was added.
//
// The 68000 no longer sees RAMDP words at $1FE0-$1FFF. It sees these registers, and the MCU reaches them at
// region 0x0B (0x0B000000 + the register's offset from $1FE0). One clock domain (clk_sys); MCU writes take
// effect in the access's first bus cycle, in program order, with nothing posted, so the 68000 never sees a
// newer $1FEA than the $1FE6 the MCU wrote before it.
//
// MCU side (a 32-bit word at 0x0B000000 + 4k is {reg(+4k+2), reg(+4k)}, the RAMDP lane order):
//   +4 $1FE4, +6 $1FE6, +A $1FEA, +C $1FEC  stored, byte lanes honoured; a read returns the stored word
//                                           (+4 is the MCU's own word, never the 68000 view)
//   +8 $1FE8   act, not stored: bit 0 = 1 -> window on; value 0 -> window off and mini view
//   +E $1FEE   act, not stored: 0xAF5B -> window off and mini view
//   +12 $1FF2  act, not stored: 0, or bit 15 set -> stream invalid, guard cleared; other values no effect.
//              Since the sprite-decoder step: also passed to paprium_hwdec (0x8000 START, 0 / 0xC00x STOP)
//   +14 $1FF4, +16 $1FF6  sprite-decoder step: not stored, passed to paprium_hwdec (the load-list queue: entry high
//   half; clear
//              or push); MCU reads 0
//   +A         an MCU write also clears the busy guard; MCU writes raise no interrupt
//   every other offset: writes dropped, reads 0
//   Read data and ack are registered: two bus cycles, the ack in the second; the read data is 0 outside them.
// FPGAIO (the MCU's register block, fpgio.sv) slot 7 (STREAM_GO, 0x0100001C) is decoded here too, beside the stream
// engine: a write of N > 0 loads
//   remaining = N words, makes the stream valid and clears the guard; a write of 0 makes it invalid.
//   Since the sprite-decoder step: paprium_hwdec's GO (dec_go, dec_go_len) has the same effect at the end of a decoder
//   run; a slot-7 write wins a same-clock dec_go (they never meet: the firmware writes slot 7 only for FIFO B, DB06).
//
// 68000 side:
//   $1FE4 reads busy << 2 | the Console model bits 6, 8-10 (every other bit 0)
//   $1FE6, $1FEA, $1FEC read the stored words; every other register reads 0
//   writes land only in $1FEA and $1FEC, always the whole word (B Jam's choice: a byte write stores the byte, which the
//   68000 puts on both halves of the bus, in both halves, as RAMDP does); a 68000 write wins a same-clock MCU write;
//   any write to $1FEA raises post_b, to $1FEC post_a (one clock each)
//
// busy = guard | ~stream_valid
//   guard:        set by a 68000 write to $1FEA whose high byte is DA, DB or F2 (a set wins a same-clock clear);
//                 cleared by an MCU write to +A, a clearing +12 write, or a GO of N > 0 (slot 7 or the decoder's)
//   stream_valid: set by a GO of N > 0; cleared by a GO of 0, a clearing +12 write, the last word delivered,
//                 the window falling, and reset
//   remaining:    21 bits, one less per delivered word, saturating at 0; a GO wins a same-clock decrement
//
// The window ($C000-$FFFF) is served while window_en & ~mini_view. Both are 0 at every reset; mini_view stays
// 1 from the first window-off write until the next reset.
//
// Reset (power-on and every sys_reset): every stored register 0, window off, game view, stream invalid
// (busy 1), guard 0, remaining 0.

module paprium_regfile
(
	input              clk,             // clk_sys, the MCU clock
	input              reset,           // every reset (sys_reset | ~enable)
	input  McuBus      mcu,
	input  CpuBus      cpu,             // the 68000 bus as ramdp_io samples it on clk_sys
	input              cpu_we_ck,       // ramdp_io's filtered 68000 write strobe (one clock per write)
	input       [3:0]  model,           // the Console model bits {$1FE4 bit 10, 9, 8, 6}
	input              word_delivered,  // one clock per stream word delivered (the stream pointer's step)
	input              dec_go,          // sprite-decoder step: paprium_hwdec's GO, one clock
	input       [20:0] dec_go_len,      // ... its length in words

	output reg  [31:0] mcu_dati,        // region 0x0B read data (registered)
	output reg         mcu_ack,         // region 0x0B ack (registered)
	output reg  [15:0] cpu_dati,        // the 68000 view of the addressed register (registered)
	output reg         cpu_page,        // the 68000 address is in $1FE0-$1FFF (registered)
	output reg         stream_win,      // window_en & ~mini_view (registered): gates stream_cs
	output reg         window_en,
	output reg         mini_view,
	output             busy,
	output      [31:0] stream_status,   // {stream_valid, 10'd0, remaining}: the STREAM_GO read-back
	output             post_a,          // a 68000 write to $1FEC
	output             post_b,          // a 68000 write to $1FEA
	// sprite-decoder step: the MCU's stores to +12, +14, +16 (first bus clock) and their halfwords, for paprium_hwdec
	output             dec_f2,
	output             dec_f4,
	output             dec_f6,
	output      [15:0] dec_f2_v,
	output      [15:0] dec_f4_v,
	output      [15:0] dec_f6_v
);

	reg [15:0] r_e4;
	reg [15:0] r_e6;
	reg [15:0] r_ea;
	reg [15:0] r_ec;
	reg        guard;
	reg        stream_valid;
	reg [20:0] remaining;
	reg        go_hit_q;

	// power-up values (the configuration load) = the reset values
	initial begin
		r_e4         = 16'h0000;
		r_e6         = 16'h0000;
		r_ea         = 16'h0000;
		r_ec         = 16'h0000;
		guard        = 1'b0;
		stream_valid = 1'b0;
		remaining    = 21'd0;
		go_hit_q     = 1'b0;
		mcu_dati   = 32'h00000000;
		mcu_ack    = 1'b0;
		cpu_dati   = 16'h0000;
		cpu_page   = 1'b0;
		stream_win = 1'b0;
		window_en  = 1'b0;
		mini_view  = 1'b0;
	end

	// ---------------------------------------------------------------- MCU side
	wire       m_hit   = mcu.ce & mcu.map.regs;
	wire       m_first = m_hit & ~mcu_ack;                 // the access's first bus cycle
	wire [2:0] m_word  = mcu.addr[4:2];
	wire [3:0] m_we    = m_first ? mcu.we : 4'b0000;       // mcu.we already carries ce, we and the byte selects
	wire       m_lo    = m_we[0] | m_we[1];                // the word's low halfword (+4k)
	wire       m_hi    = m_we[2] | m_we[3];                // the word's high halfword (+4k+2)
	wire [15:0] m_vlo  = mcu.dato[15:0];
	wire [15:0] m_vhi  = mcu.dato[31:16];

	wire w_word1 = (m_word == 3'd1);                       // +4 $1FE4 (low), +6 $1FE6 (high)
	wire w_word2 = (m_word == 3'd2);                       // +8 $1FE8 (low), +A $1FEA (high)
	wire w_word3 = (m_word == 3'd3);                       // +C $1FEC (low), +E $1FEE (high)
	wire w_word4 = (m_word == 3'd4);                       // +10 $1FF0 (low, dropped), +12 $1FF2 (high)
	wire w_word5 = (m_word == 3'd5);                       // sprite-decoder step: +14 $1FF4 (low), +16 $1FF6 (high)

	wire mcu_wr_ea = w_word2 & m_hi;
	wire act_e8    = w_word2 & m_lo;
	wire act_ee    = w_word3 & m_hi;
	wire act_f2    = w_word4 & m_hi;

	wire f2_clear  = act_f2 & ((m_vhi == 16'h0000) | m_vhi[15]);
	wire wnd_on    = act_e8 & m_vlo[0];
	wire wnd_off   = (act_e8 & (m_vlo == 16'h0000)) | (act_ee & (m_vhi == 16'hAF5B));
	wire wnd_fall  = wnd_off & window_en;

	// sprite-decoder step: the decoder's registers, not stored here (paprium_hwdec)
	assign dec_f2   = act_f2;
	assign dec_f4   = w_word5 & m_lo;
	assign dec_f6   = w_word5 & m_hi;
	assign dec_f2_v = m_vhi;
	assign dec_f4_v = m_vlo;
	assign dec_f6_v = m_vhi;

	// STREAM_GO, FPGAIO slot 7 (addr[6:2] = 7). Edge-detected, so a write acts once whatever the slot's ack timing
	wire        go_hit  = mcu.ce & mcu.map.fpgio & (mcu.addr[6:2] == 5'd7) & (mcu.we != 4'b0000);
	wire        go_fw   = go_hit & ~go_hit_q;
	wire        go_wr   = go_fw | dec_go;                      // sprite-decoder step: or the decoder's GO (slot 7 wins one clock)
	wire [20:0] go_len  = mcu.dato[20:0];
	// sprite-decoder step: the decoder's GO also counts a word the window delivers on its own clock (that clock's
	// decrement is lost to the GO). word_delivered comes from clk_md, so it only selects, last, between values made of
	// registers
	wire        dec_nz  = (dec_go_len != 21'd0);
	wire        dec_gt1 = (dec_go_len > 21'd1);
	wire [20:0] dec_m1  = dec_go_len - 21'd1;
	wire [20:0] go_rem  = go_fw ? go_len : ((word_delivered & dec_nz) ? dec_m1 : dec_go_len);
	wire        go_val  = go_fw ? (go_len != 21'd0) : (word_delivered ? dec_gt1 : dec_nz);
	wire        go_load = go_fw ? (go_len != 21'd0) : (dec_go & dec_nz);

	// ---------------------------------------------------------------- 68000 side
	wire c_wr    = cpu_we_ck & (cpu.we_lo | cpu.we_hi);
	assign post_b = c_wr & (cpu.addr[12:1] == 12'hFF5);
	assign post_a = c_wr & (cpu.addr[12:1] == 12'hFF6);

	wire [7:0] c_hb  = cpu.dato[15:8];
	wire g_set   = post_b & ((c_hb == 8'hDA) | (c_hb == 8'hDB) | (c_hb == 8'hF2));
	wire g_clr   = mcu_wr_ea | f2_clear | go_load;

	// ---------------------------------------------------------------- busy, window, view
	assign busy          = guard | ~stream_valid;
	assign stream_status = {stream_valid, 10'd0, remaining};

	wire window_n = wnd_off ? 1'b0 : (wnd_on ? 1'b1 : window_en);
	wire mini_n   = mini_view | wnd_off;
	wire last_wd  = word_delivered & (remaining == 21'd1);

	always @(posedge clk) begin
		if (reset) begin
			r_e4         <= 16'h0000;
			r_e6         <= 16'h0000;
			r_ea         <= 16'h0000;
			r_ec         <= 16'h0000;
			guard        <= 1'b0;
			stream_valid <= 1'b0;
			remaining    <= 21'd0;
			go_hit_q     <= 1'b0;
			window_en    <= 1'b0;
			mini_view    <= 1'b0;
			stream_win   <= 1'b0;
			mcu_ack      <= 1'b0;
			mcu_dati     <= 32'h00000000;
		end
		else begin
			// stored registers: MCU lanes, then the 68000's whole word (a same-clock 68000 write wins)
			if (w_word1 & m_we[0]) r_e4[7:0]  <= mcu.dato[7:0];
			if (w_word1 & m_we[1]) r_e4[15:8] <= mcu.dato[15:8];
			if (w_word1 & m_we[2]) r_e6[7:0]  <= mcu.dato[23:16];
			if (w_word1 & m_we[3]) r_e6[15:8] <= mcu.dato[31:24];
			if (w_word2 & m_we[2]) r_ea[7:0]  <= mcu.dato[23:16];
			if (w_word2 & m_we[3]) r_ea[15:8] <= mcu.dato[31:24];
			if (w_word3 & m_we[0]) r_ec[7:0]  <= mcu.dato[7:0];
			if (w_word3 & m_we[1]) r_ec[15:8] <= mcu.dato[15:8];

			if (post_b) r_ea <= cpu.dato;   // new core (B Jam's choice for 68000 byte writes): the whole word, whichever byte strobe
			if (post_a) r_ec <= cpu.dato;

			// busy guard: a set wins a same-clock clear
			if (g_set)      guard <= 1'b1;
			else if (g_clr) guard <= 1'b0;

			// the stream: a GO wins a same-clock decrement
			go_hit_q <= go_hit;
			if (go_wr) begin
				remaining    <= go_rem;
				stream_valid <= go_val;
			end
			else begin
				if (word_delivered & (remaining != 21'd0)) remaining <= remaining - 21'd1;
				if (f2_clear | wnd_fall | last_wd)         stream_valid <= 1'b0;
			end

			// the window and the view
			window_en  <= window_n;
			mini_view  <= mini_n;
			stream_win <= window_n & ~mini_n;

			// MCU read: data registered in the first cycle, ack in the second. The data is 0 outside its own
			// access, so it can share one registered rv_di arm with FPGAIO (an OR of the two blocks)
			mcu_ack <= m_first;
			if (m_first) begin
				case (m_word)
					3'd1:    mcu_dati <= {r_e6, r_e4};
					3'd2:    mcu_dati <= {r_ea, 16'h0000};
					3'd3:    mcu_dati <= {16'h0000, r_ec};
					default: mcu_dati <= 32'h00000000;
				endcase
			end
			else mcu_dati <= 32'h00000000;
		end
	end

	// the 68000 view, registered on clk_sys like the RAMDP read it replaces (same latency into cart_data)
	always @(posedge clk) begin
		cpu_page <= (cpu.addr[12:5] == 8'hFF);
		case (cpu.addr[4:1])
			4'h2:    cpu_dati <= {5'b00000, model[3:1], 1'b0, model[0], 3'b000, busy, 2'b00};   // $1FE4
			4'h3:    cpu_dati <= r_e6;                                                              // $1FE6
			4'h5:    cpu_dati <= r_ea;                                                              // $1FEA
			4'h6:    cpu_dati <= r_ec;                                                              // $1FEC
			default: cpu_dati <= 16'h0000;
		endcase
	end

endmodule
