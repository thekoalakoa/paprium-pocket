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
	output signed [15:0]snd_r
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
	sfx_bank sfx_bank0
	(
		.mcu(mcu),
		.aclk(aclk),
		.bank_idx(3'd0),
		.bank(bank0)
	);

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
module aclk_bank
(
	input  McuBus mcu,
	input  dac_next_sample,
	output [7:0]aclk
);

	assign aclk[0] = dac_next_sample;   // 48000
	assign aclk[6] = aclk[0];
	assign aclk[7] = aclk[0];

	// dac_clocker (audio_clock.sv): generates next_sample at `rate` Hz.
	dac_clocker aclk1(.clk(mcu.clk), .rst(1'b0), .rate(16'd24000), .ck_base(`CLK_FREQ), .dac_clk(), .next_sample(aclk[1]), .phase());
	dac_clocker aclk2(.clk(mcu.clk), .rst(1'b0), .rate(16'd12000), .ck_base(`CLK_FREQ), .dac_clk(), .next_sample(aclk[2]), .phase());
	dac_clocker aclk3(.clk(mcu.clk), .rst(1'b0), .rate(16'd9600),  .ck_base(`CLK_FREQ), .dac_clk(), .next_sample(aclk[3]), .phase());
	dac_clocker aclk4(.clk(mcu.clk), .rst(1'b0), .rate(16'd6000),  .ck_base(`CLK_FREQ), .dac_clk(), .next_sample(aclk[4]), .phase());
	dac_clocker aclk5(.clk(mcu.clk), .rst(1'b0), .rate(16'd5333),  .ck_base(`CLK_FREQ), .dac_clk(), .next_sample(aclk[5]), .phase());

endmodule

//****************************************************************** sfx channels
module sfx_bank
(
	input  McuBus mcu,
	input  [7:0]aclk,
	input  [2:0]bank_idx,
	output SfxBank bank
);

	sfx_chan sfx_chan0(.mcu(mcu), .aclk(aclk), .chan_idx(6'd0 + {bank_idx,3'b000}), .sfx(bank.sfx[0]));
	sfx_chan sfx_chan1(.mcu(mcu), .aclk(aclk), .chan_idx(6'd1 + {bank_idx,3'b000}), .sfx(bank.sfx[1]));
	sfx_chan sfx_chan2(.mcu(mcu), .aclk(aclk), .chan_idx(6'd2 + {bank_idx,3'b000}), .sfx(bank.sfx[2]));
	sfx_chan sfx_chan3(.mcu(mcu), .aclk(aclk), .chan_idx(6'd3 + {bank_idx,3'b000}), .sfx(bank.sfx[3]));
	sfx_chan sfx_chan4(.mcu(mcu), .aclk(aclk), .chan_idx(6'd4 + {bank_idx,3'b000}), .sfx(bank.sfx[4]));
	sfx_chan sfx_chan5(.mcu(mcu), .aclk(aclk), .chan_idx(6'd5 + {bank_idx,3'b000}), .sfx(bank.sfx[5]));
	sfx_chan sfx_chan6(.mcu(mcu), .aclk(aclk), .chan_idx(6'd6 + {bank_idx,3'b000}), .sfx(bank.sfx[6]));
	sfx_chan sfx_chan7(.mcu(mcu), .aclk(aclk), .chan_idx(6'd7 + {bank_idx,3'b000}), .sfx(bank.sfx[7]));

endmodule


module sfx_chan
(
	input  McuBus mcu,
	input  [7:0]aclk,
	input  [5:0]chan_idx,
	output SfxOut sfx
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

		if(flags_we)
			pitch <= flags[7] ? 5'd31 : flags[5] ? 5'd1 : 5'd0;  //skip 1 of 2..32 cycles

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

	reg mix_req;
	reg mix_next;
	reg mix_side;   //0:L,1:R

	always @(posedge clk)
	if(next_sample) begin
		mix_req  <= 1;
		mix_next <= 1;
		mix_side <= 0;
	end
	else if(mix_next) begin
		mix_next <= 0;
	end
	else if(mix_req & mix_ack) begin

		if(mix_side == 0) begin
			snd_l    <= mix_snd;
			mix_next <= 1;
			mix_side <= 1;
		end

		if(mix_side == 1) begin
			snd_r   <= mix_snd;
			mix_req <= 0;
		end

	end

	wire mix_ack;
	wire signed [15:0]mix_snd;

	mix_mono mix_mono_inst
	(
		.clk(clk),
		.bank(bank),
		.mix_next(mix_next),
		.side(mix_side),
		.ack(mix_ack),
		.snd(mix_snd)
	);

endmodule


module mix_mono
(
	input  clk,
	input  SfxBank bank,
	input  mix_next,
	input  side,

	output reg ack,
	output reg signed [15:0]snd
);

	wire [3:0]chan_idx = state[5:2];

	wire signed [7:0]pan  = bank.sfx[chan_idx[2:0]].pan[side];
	wire signed [10:0]vol = bank.sfx[chan_idx[2:0]].vol;
	wire signed [15:0]pcm = bank.sfx[chan_idx[2:0]].pcm;

	reg signed [15:0]val;
	reg signed [21:0]acc;
	reg [5:0]state;

	always @(posedge clk)
	if(mix_next) begin
		state <= 0;
		acc   <= 0;
		ack   <= 0;
	end
	else if(!ack) begin

		state <= state + 1'd1;

		if(chan_idx < 8) begin
			case(state[1:0])
				0: val <= pcm;
				1: val <= $signed(val) * vol / 'h400;
				2: val <= $signed(val) * pan / 'h80;
				3: acc <= acc + val;
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
