// ---------------------------------------------------------------------------
// Paprium MCU cart SFX PCM engine - full per-channel restoration.
//
// This is the original mega-ppm audio_sfx (8 channels, per-channel sample-rate
// select / pitch / pan / volume, serial mixer), adapted for the MiSTer port:
//   * the channel FIFOs are backed by a RIGHT-SIZED 256x16 dual-port RAM
//     (sfx_fifo_ram) instead of the port's general-purpose ram_dp16, which is
//     declared 65536x16 (=1 Mbit each). Eight of those for tiny 256-entry FIFOs
//     was up to 8 Mbit and is what overflowed the Cyclone V's block RAM - the
//     SFX logic itself is small. 8 x 4 Kbit = ~8 M10K, well inside budget.
//   * the rate clocks use this port's dac_clocker signature (audio_clock.sv):
//     rst tied low (free-running), dac_clk/phase left open, rate as 16-bit Hz.
// ---------------------------------------------------------------------------

module audio_sfx
(
	input  McuBus mcu,
	input  SndCk  snd,

	output [31:0]mcu_dati_sfx,
	output signed [15:0]snd_l,
	output signed [15:0]snd_r,

	// paprium: channel-7 state for the diagnostic logger. Channel 7 is where the
	// punk-TV cue lands (the game asks for it on mask 0x0080), and the mailbox
	// capture has already shown the REQUEST is correct - volume ramps to 0xC0 and
	// the pan sweeps - so the remaining question is what the channel does with it.
	output [10:0]dbg_ch7_vol,
	output       dbg_ch7_empty,
	output       dbg_ch7_wr
);

	SfxBank bank0;

	assign mcu_dati_sfx = bank0.sfx[mcu.addr[5:3]].status;

	//****************************** clocks
	wire [7:0]aclk;
	aclk_bank aclk_bank_inst
	(
		.mcu(mcu),
		.dac_next_sample(snd.next_sample),
		.aclk(aclk)
	);

	//****************************** sfx bank (8 channels)
	wire [7:0]chan_wr;

	sfx_bank sfx_bank0
	(
		.mcu(mcu),
		.aclk(aclk),
		.bank_idx(3'd0),
		.bank(bank0),
		.chan_wr(chan_wr)
	);

	// paprium: channel 7 taps. dbg_ch7_wr pulses on every PCM word the MCU pushes,
	// so a stalled count means the firmware stopped feeding the channel - which is
	// what a sound that starts and then dies looks like from here.
	assign dbg_ch7_vol   = bank0.sfx[7].vol;
	assign dbg_ch7_empty = bank0.sfx[7].status[0];
	assign dbg_ch7_wr    = chan_wr[7];

	//****************************** mixer
	mix_bank mix_bank0
	(
		.clk(mcu.clk),
		.bank(bank0),
		.next_sample(snd.next_sample),
		.snd_l(snd_l),
		.snd_r(snd_r)
	);

endmodule

//****************************************************************** audio clocks
// paprium: rewritten for area. Upstream gives each channel rate its own dac_clocker,
// and every one of those carries a 32-bit fractional divider (clk_dvp comparing a
// 32-bit accumulator against ck_base = 53,693,175) plus a 9-bit phase counter - about
// 65 ALUTs each, ~334 for the bank. On the Pocket that is unaffordable: the device
// fits at 99% ALM and this is Paprium's own logic, not the console's.
//
// Every rate the bank produces is a sub-multiple of the 48 kHz tick the engine already
// has, so they come free from counters that never exceed 9:
//
//   24000 = 48000/2   12000 = 48000/4   9600 = 48000/5   6000 = 48000/8
//   5333 -> 48000/9 = 5333.33 Hz, 0.006% fast and inaudible
//
// The divided rates are now phase-locked to the 48 kHz tick rather than free-running.
// For per-channel PCM pacing that is harmless, and deterministic rather than not.
module aclk_bank
(
	input  McuBus mcu,
	input  dac_next_sample,
	output [7:0]aclk
);

	assign aclk[0] = dac_next_sample;   // 48000
	assign aclk[6] = aclk[0];
	assign aclk[7] = aclk[0];

	reg [1:0] div2  = 0;   // /2  -> 24000
	reg [2:0] div4  = 0;   // /4  -> 12000
	reg [2:0] div5  = 0;   // /5  ->  9600
	reg [3:0] div8  = 0;   // /8  ->  6000
	reg [3:0] div9  = 0;   // /9  ->  5333.33

	always @(posedge mcu.clk) if(dac_next_sample) begin
		div2 <= (div2 == 2'd1) ? 2'd0 : div2 + 1'd1;
		div4 <= (div4 == 3'd3) ? 3'd0 : div4 + 1'd1;
		div5 <= (div5 == 3'd4) ? 3'd0 : div5 + 1'd1;
		div8 <= (div8 == 4'd7) ? 4'd0 : div8 + 1'd1;
		div9 <= (div9 == 4'd8) ? 4'd0 : div9 + 1'd1;
	end

	// One 48 kHz tick wide, exactly like dac_clocker's next_sample
	assign aclk[1] = dac_next_sample & (div2 == 2'd0);
	assign aclk[2] = dac_next_sample & (div4 == 3'd0);
	assign aclk[3] = dac_next_sample & (div5 == 3'd0);
	assign aclk[4] = dac_next_sample & (div8 == 4'd0);
	assign aclk[5] = dac_next_sample & (div9 == 4'd0);

endmodule
// paprium-end

//****************************************************************** sfx channels
module sfx_bank
(
	input  McuBus mcu,
	input  [7:0]aclk,
	input  [2:0]bank_idx,
	output SfxBank bank,
	output [7:0]chan_wr      // paprium: per-channel FIFO write pulses
);

	sfx_chan sfx_chan0(.mcu(mcu), .aclk(aclk), .chan_idx(6'd0 + {bank_idx,3'b000}), .sfx(bank.sfx[0]), .wr_pulse(chan_wr[0]));
	sfx_chan sfx_chan1(.mcu(mcu), .aclk(aclk), .chan_idx(6'd1 + {bank_idx,3'b000}), .sfx(bank.sfx[1]), .wr_pulse(chan_wr[1]));
	sfx_chan sfx_chan2(.mcu(mcu), .aclk(aclk), .chan_idx(6'd2 + {bank_idx,3'b000}), .sfx(bank.sfx[2]), .wr_pulse(chan_wr[2]));
	sfx_chan sfx_chan3(.mcu(mcu), .aclk(aclk), .chan_idx(6'd3 + {bank_idx,3'b000}), .sfx(bank.sfx[3]), .wr_pulse(chan_wr[3]));
	sfx_chan sfx_chan4(.mcu(mcu), .aclk(aclk), .chan_idx(6'd4 + {bank_idx,3'b000}), .sfx(bank.sfx[4]), .wr_pulse(chan_wr[4]));
	sfx_chan sfx_chan5(.mcu(mcu), .aclk(aclk), .chan_idx(6'd5 + {bank_idx,3'b000}), .sfx(bank.sfx[5]), .wr_pulse(chan_wr[5]));
	sfx_chan sfx_chan6(.mcu(mcu), .aclk(aclk), .chan_idx(6'd6 + {bank_idx,3'b000}), .sfx(bank.sfx[6]), .wr_pulse(chan_wr[6]));
	sfx_chan sfx_chan7(.mcu(mcu), .aclk(aclk), .chan_idx(6'd7 + {bank_idx,3'b000}), .sfx(bank.sfx[7]), .wr_pulse(chan_wr[7]));

endmodule


module sfx_chan
(
	input  McuBus mcu,
	input  [7:0]aclk,
	input  [5:0]chan_idx,
	output SfxOut sfx,
	output wr_pulse          // paprium: one per PCM word accepted, for the logger
);

	localparam FIFO_SIZE = 8;   // 256-entry FIFO

	assign sfx.status[0] = fifo_empty;
	assign sfx.status[1] = fifo_full;

	wire chan_ce  = mcu.ce & mcu.map.sfx & (mcu.addr[8:3] == chan_idx);

	wire type_we  = (mcu.addr[2] == 0) & chan_ce & mcu.we[1];
	wire pan_we   = (mcu.addr[2] == 0) & chan_ce & mcu.we[2];
	wire flags_we = (mcu.addr[2] == 0) & chan_ce & mcu.we[3];

	wire vol_we   = (mcu.addr[2] == 1) & chan_ce & (mcu.we[1:0] == 2'b11);
	wire pcm_we   = (mcu.addr[2] == 1) & chan_ce & (mcu.we[3:2] == 2'b11);

	wire [7:0]typev = mcu.dato[15:8];
	wire [7:0]pan   = mcu.dato[23:16];
	wire [7:0]flags = mcu.dato[31:24];
	wire [15:0]vol  = mcu.dato[15:0];

	//48000, 24000, 12000, 9600, 6000, 5333
	wire next_sample = aclk[srate];

	wire fifo_empty = addr_rd == addr_wr;
	wire fifo_full  = (addr_rd[FIFO_SIZE-1:0] == addr_wr[FIFO_SIZE-1:0]) & (addr_rd[FIFO_SIZE] != addr_wr[FIFO_SIZE]);

	reg [FIFO_SIZE:0]addr_rd;
	reg [FIFO_SIZE:0]addr_wr;

	reg pcm_we_st;
	reg [2:0]srate;
	reg [4:0]pitch;
	reg [4:0]pitch_ctr;

	always @(posedge mcu.clk) begin

		pcm_we_st <= pcm_we;

		if(type_we)
			srate <= typev[6:4];

		if(pan_we) begin
			sfx.pan[0] <= pan < 'h80 ? 'h80 : 'h100 - pan;  //L
			sfx.pan[1] <= pan > 'h80 ? 'h80 : pan;          //R
		end

		if(flags_we) begin
			pitch <= flags[7] ? 5'd31 : flags[5] ? 5'd1 : 5'd0;  //skip 1 of 2..32 cycles
			// paprium: 0x4000 echo and 0x0100 amplify, previously dropped
			sfx.echo <= flags[6];
			sfx.amp  <= flags[0];
		end

		if(vol_we)
			sfx.vol <= vol;

		if(!fifo_empty & next_sample & (pitch_ctr != 1)) begin
			addr_rd <= addr_rd + 1'd1;
			sfx.pcm <= mem_dato;
		end

		if(!fifo_full & ({pcm_we_st, pcm_we} == 2'b10))
			addr_wr <= addr_wr + 1'd1;

		if(next_sample)
			pitch_ctr <= pitch_ctr >= pitch ? 5'd0 : pitch_ctr + 1'd1;

	end

	assign wr_pulse = !fifo_full & ({pcm_we_st, pcm_we} == 2'b10);

	wire [15:0]mem_dato;

	sfx_fifo_ram pcm_buff
	(
		.clk_a(mcu.clk),
		.dati_a(mcu.dato[31:16]),
		.addr_a(addr_wr[FIFO_SIZE-1:0]),
		.we_a(pcm_we),

		.clk_b(mcu.clk),
		.addr_b(addr_rd[FIFO_SIZE-1:0]),
		.dato_b(mem_dato)
	);

endmodule

//****************************************************************** mixer
module mix_bank
(
	input clk,
	input SfxBank bank,
	input next_sample,

	output reg signed [15:0]snd_l,
	output reg signed [15:0]snd_r
);

	// paprium: the echo GPGX applies and this port used to drop. Per sample it
	// clears the current slot, lets echo-flagged voices accumulate into it,
	// advances the pointer and adds the slot it lands on to the output:
	//
	//     echo_l[ptr] = 0;  ... voices add (sample * 33)/100 ...
	//     ptr = (ptr+1) % (48000/6);   l += echo_l[ptr];
	//
	// One lap of an 8000-entry ring at 48 kHz is 166.7 ms, single tap, no
	// feedback - overwriting each slot rather than accumulating gives the clear
	// for free. 8000 x 32 = 256 Kbit, ~26 M10K against 62 free.
	localparam ECHO_LEN = 13'd8000;

	reg [12:0] eptr = 0;

	// Read and write live in their own always blocks with an unconditional read -
	// the only shape Quartus reliably maps to M10K here. An earlier version did
	// both inside a case statement and synthesis fell back to registers, which
	// blew past the device's register count entirely.
	reg [31:0] echo_ram[8192];
	reg [31:0] echo_rd;
	reg        echo_we;
	reg [31:0] echo_wdata;

	always @(posedge clk) if(echo_we) echo_ram[eptr] <= echo_wdata;
	always @(posedge clk) echo_rd <= echo_ram[eptr];

	reg signed [15:0]dry_l, dry_r;
	reg signed [15:0]send_l, send_r;

	// Saturate a mix accumulator to 16 bits
	function automatic signed [15:0] sat16(input signed [22:0] v);
		sat16 = (v < -23'sd32768) ? 16'sh8000
		      : (v >  23'sd32767) ? 16'sd32767
		      :                     v[15:0];
	endfunction

	reg mix_req;
	reg mix_next;
	reg mix_side;   //0:L,1:R
	reg [1:0] tail;  // paprium: echo read/write after both sides are mixed

	always @(posedge clk)
	if(next_sample) begin
		mix_req  <= 1;
		mix_next <= 1;
		mix_side <= 0;
		tail     <= 0;
		echo_we  <= 1'b0;
	end
	else if(mix_next) begin
		mix_next <= 0;
	end
	else if(mix_req & mix_ack) begin

		if(mix_side == 0) begin
			dry_l    <= mix_snd;
			send_l   <= sat16({{1{echo_acc[21]}}, echo_acc});
			mix_next <= 1;
			mix_side <= 1;
		end

		if(mix_side == 1) begin
			dry_r   <= mix_snd;
			send_r  <= sat16({{1{echo_acc[21]}}, echo_acc});
			mix_req <= 0;
			tail    <= 2'd1;
		end

	end
	else if(tail != 0) begin
		echo_we <= 1'b0;
		case(tail)
			// echo_rd already holds echo_ram[eptr] - the read runs every cycle
			2'd1: begin
				snd_l      <= sat16($signed(dry_l) + $signed(echo_rd[31:16]));
				snd_r      <= sat16($signed(dry_r) + $signed(echo_rd[15:0]));
				echo_we    <= 1'b1;
				echo_wdata <= {send_l, send_r};
				tail       <= 2'd2;
			end
			2'd2: begin
				eptr <= (eptr == ECHO_LEN - 1'd1) ? 13'd0 : eptr + 1'd1;
				tail <= 2'd0;
			end
			default: tail <= 2'd0;
		endcase
	end

	wire mix_ack;
	wire signed [15:0]mix_snd;
	wire signed [21:0]echo_acc;

	mix_mono mix_mono_inst
	(
		.clk(clk),
		.bank(bank),
		.mix_next(mix_next),
		.side(mix_side),
		.ack(mix_ack),
		.snd(mix_snd),
		.echo_acc(echo_acc)
	);

endmodule


module mix_mono
(
	input  clk,
	input  SfxBank bank,
	input  mix_next,
	input  side,

	output reg ack,
	output reg signed [15:0]snd,
	// paprium: this side's echo send, 33% of each echo-flagged voice
	output reg signed [21:0]echo_acc
);

	wire [3:0]chan_idx = state[5:2];

	// paprium: pan and vol are UNSIGNED in the struct, and reading them as signed
	// of the same width misreads their top value. pan runs 0..0x80, and 8'h80 as
	// signed is -128, so the fully-open side of every non-centred effect was
	// phase-INVERTED - audible as cancellation once summed to the Pocket's mono
	// speaker. Zero-extending by one bit before the signed multiply fixes both.
	wire signed [8:0] pan  = {1'b0, bank.sfx[chan_idx[2:0]].pan[side]};
	wire signed [11:0]vol  = {1'b0, bank.sfx[chan_idx[2:0]].vol};
	wire signed [15:0]pcm  = bank.sfx[chan_idx[2:0]].pcm;

	// paprium: GPGX gives each echo-flagged voice ONE side, alternating as voices
	// are allocated (`voice->echo = echo_pan++ & 1`). That counter lives in the
	// firmware and is not visible here, so the side is taken from the channel
	// index instead - deterministic, and it spreads echo across both sides the
	// same way. A deliberate deviation, and the only one in this feature.
	wire ch_echo = bank.sfx[chan_idx[2:0]].echo & (chan_idx[0] == side);
	wire ch_amp  = bank.sfx[chan_idx[2:0]].amp;

	// 33/100 as 84/256: 0.328 against 0.330, well inside the 4-bit source material
	wire signed [23:0]echo_send = ($signed(val) * 24'sd84) >>> 8;

	reg signed [15:0]val;
	reg signed [21:0]acc;
	reg [5:0]state;

	always @(posedge clk)
	if(mix_next) begin
		state    <= 0;
		acc      <= 0;
		ack      <= 0;
		echo_acc <= 0;
	end
	else if(!ack) begin

		state <= state + 1'd1;

		if(chan_idx < 8) begin
			case(state[1:0])
				0: val <= pcm;
				1: val <= $signed(val) * vol / 'h400;
				2: val <= $signed(val) * pan / 'h80;
				3: begin
					// paprium: amplify scales the RUNNING mix, not the voice -
					// GPGX does `l = (l * 125) / 100` on the accumulator inside
					// the voice loop. x1.25 is acc + acc/4.
					acc <= ch_amp ? ((acc + val) + ((acc + val) >>> 2))
					              :  (acc + val);
					if(ch_echo) echo_acc <= echo_acc + echo_send[21:0];
				end
			endcase
		end
		else begin

			if(acc < -32768)
				snd <= 16'sh8000;   // -32768 saturation floor (bit pattern; avoids 16'sd literal overflow)
			else if(acc > 32767)
				snd <= 16'sd32767;
			else
				snd <= acc[15:0];

			ack <= 1;

		end

	end

endmodule

//****************************************************************** sized FIFO RAM
// 256 x 16 simple dual-port (1 write port, 1 read port) = 4 Kbit -> 1 M10K.
// Right-sized for the per-channel SFX FIFO so 8 instances cost ~8 M10K instead
// of the 65536-deep ram_dp16's ~1 Mbit each.
module sfx_fifo_ram
(
	input  clk_a,
	input  [15:0]dati_a,
	input  [7:0]addr_a,
	input  we_a,

	input  clk_b,
	input  [7:0]addr_b,
	output reg [15:0]dato_b
);

	reg [15:0]ram[256];

	always @(posedge clk_a)
		if(we_a) ram[addr_a] <= dati_a;

	always @(posedge clk_b)
		dato_b <= ram[addr_b];

endmodule
