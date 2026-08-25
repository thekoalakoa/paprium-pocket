//============================================================================
//  Megadrive/Master Cartridge implementation
//  Copyright (c) 2023 Alexey Melnikov
//
//  This program is free software; you can redistribute it and/or modify it
//  under the terms of the GNU General Public License as published by the Free
//  Software Foundation; either version 2 of the License, or (at your option)
//  any later version.
//
//  This program is distributed in the hope that it will be useful, but WITHOUT
//  ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
//  FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
//  more details.
//
//  You should have received a copy of the GNU General Public License along
//  with this program; if not, write to the Free Software Foundation, Inc.,
//  51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
//============================================================================

// Adapted from rtl/upstream/cartridge.sv. Everything that does not fit, or
// that has no consumer on the Pocket, is gone: Pier Solar, the Sega Channel,
// the Master System cart path with its boot ROM and OPLL, the J-Cart
// and the lightgun. The SVP does not fit either, but Virtua Racing needs it, so it
// is behind the SVP parameter and ships as its own bitstream that trades the save
// hardware for the DSP. Every difference sits inside a marker pair below.
module cartridge
// pocket: the device cannot hold the SVP next to the full core, so the SVP build
// is a separate bitstream the Chip32 loader picks for Virtua Racing only. Virtua
// Racing has no battery RAM, so that build gives up the save RAM and the EEPROM
// to pay for the DSP
// paprium: PAPRIUM is a third bitstream variant on the same footing as SVP. It swaps
// the general mapper/protection hardware for the Paprium cartridge subsystem: SSF2
// banking is suppressed, SDRAM port 2 moves from the SVP to the Paprium MCU, and the
// save RAM becomes the MCU-managed 4 KB backup RAM. SVP and PAPRIUM are mutually
// exclusive - both want port 2
#(parameter SVP = 1'b0, parameter PAPRIUM = 1'b0)
// pocket-end
(
	input             clk,
	input             clk_ram,
	input             reset,
	input             reset_sdram,

	output            SDRAM_CLK,
	output            SDRAM_CKE,
	output     [12:0] SDRAM_A,
	output      [1:0] SDRAM_BA,
	inout      [15:0] SDRAM_DQ,
	output            SDRAM_DQML,
	output            SDRAM_DQMH,
	output            SDRAM_nCS,
	output            SDRAM_nCAS,
	output            SDRAM_nRAS,
	output            SDRAM_nWE,

	input             cart_dl,
	input      [24:0] cart_dl_addr,
	input      [15:0] cart_dl_data,
	input             cart_dl_wr,
	output reg        cart_dl_wait,

// pocket: APF reads the save size out of the data table before it will write a
// save file back, so the core has to say whether the cart has battery RAM at all.
// An EEPROM cart carries no battery-RAM marker in its header, hence two flags
	output reg        sram_present,
	output            eeprom_present,
// pocket-end

	input             cart_ms,
	input      [23:1] cart_addr,
	output reg [15:0] cart_data,
	input      [15:0] cart_data_wr,
	input             cart_cs,
	input             cart_oe,
	input             cart_lwr,
	input             cart_uwr,
	input             cart_time,
	output            cart_data_en,
	output            cart_dtack,
	input             cart_dma,

// pocket: the APF save slot is a byte-addressed 64 KB file served by
// data_loader/data_unloader, and a word-wide port on the save RAM would drag in
// read-during-write bypass logic. The fill window needs a flag of its own because
// cart_dl stays high until every data slot is in, the save file included, so
// filling on cart_dl would erase the file it had just loaded
	input      [15:0] save_addr,
	input       [7:0] save_di,
	output      [7:0] save_do,
	input             save_wr,
	input             save_clear,
	output            save_change,
// pocket-end

// paprium: the Paprium subsystem's connections to the top level. paprium_active
// selects the Paprium audio mix and the 48 kHz CDDA rate there; paprium_md_reset
// lets the MCU hold the 68000 in reset while it boots the cartridge. The mdp_*
// group is the MCU's MD+ background-music command channel: on MiSTer it drives the
// core's MD+ engine, which this build does not compile, so it is exported for the
// APF CDDA streamer to consume instead
	output            paprium_active,
	output            paprium_md_reset,
	output signed [15:0] paprium_sfx_l,
	output signed [15:0] paprium_sfx_r,

	output            mdp_track_request,
	output      [7:0] mdp_track_num,
	output            mdp_track_loop,
	output            mdp_stop_request,
	output      [7:0] mdp_fade_sectors,
	output            mdp_resume_request,
	output      [7:0] mdp_volume,
	output            mdp_volume_request,
	output            mdp_active,
	input             mdp_playing,
	input       [7:0] mdp_current_track,
// paprium-end

	output            ym2612_quirk,

	output     [23:0] md_addr
);

sdram sdram
(
	.*,
	.init(reset_sdram),
	.clk(clk_ram),

	.addr0(cart_wr_addr),
	.din0({cart_dl_data[7:0], cart_wr_addr0 ? cart_dl_data[7:0] : cart_dl_data[15:8]}),
	.dout0(),
	.wrl0(1),
	.wrh0(1),
	.req0(rom_wr),
	.ack0(rom_wrack),

	.addr1(rom_addr),
	.dout1(rom_data),
// pocket: port 1 never writes. Upstream drives these for the Sega Channel, whose
// rom_we is 0 here, so req1 can never fire with rom_rd low and the strobes are never
// sampled asserted. Leaving them connected only feeds 16 bits of data and two
// strobes into the arbiter on the clk_ram clock that nothing ever uses
	.din1(0),
	.wrl1(0),
	.wrh1(0),
// pocket-end
	.req1(rom_req),
	.ack1(rom_ack),

// paprium: port 2 is the SVP ROM port in the base build and the Paprium MCU flash /
// workspace port here. PAPRIUM and SVP are mutually exclusive so one mux serves both;
// it constant-folds away in the builds where paprium_active is tied low. rom2_a is
// [20:1], the SVP 2 MB window, and addr2 is [24:1], hence the zero extension
	.addr2(paprium_active ? paprium_mem_addr : {4'd0, rom2_a}),
	.din2(paprium_active ? paprium_mem_din : 16'd0),
	.dout2(rom2_data),
	.wrl2(paprium_active & paprium_mem_wrl),
	.wrh2(paprium_active & paprium_mem_wrh),
	.req2(paprium_active ? paprium_mem_req : rom2_req),
	.ack2(rom2_ack)
// paprium-end
);

reg        cart_wr_addr0;
reg        rom_wr = 0;
wire       rom_wrack;
reg [24:1] rom_mask;
reg [25:1] rom_sz;
reg [26:0] cart_wr_addr;

always @(posedge clk) begin
	reg old_dl, old_reset;

	old_reset <= reset;
	if(~old_reset && reset) cart_dl_wait <= 0;
	
	old_dl <= cart_dl;
	if(~old_dl & cart_dl) begin
		rom_mask <= 0;
		cart_wr_addr <= 0;
		rom_sz <= 0;
	end

	if (cart_dl & cart_dl_wr) begin
		cart_dl_wait <= 1;
		cart_wr_addr0 <= cart_ms;
		rom_wr <= ~rom_wr;
		cart_wr_addr <= rom_sz;
		rom_mask <= rom_mask | rom_sz[24:1];
		rom_sz <= rom_sz + 1'd1;
	end
	else if(rom_wr == rom_wrack) begin
		if(cart_wr_addr0) begin
			cart_wr_addr0 <= 0;
			rom_wr <= ~rom_wr;
			cart_wr_addr <= rom_sz;
			rom_mask <= rom_mask | rom_sz[24:1];
			rom_sz <= rom_sz + 1'd1;
		end
		else begin
			cart_dl_wait <= 0;
		end
	end
end


//--------------------- all carts --------------------------------------

assign cart_dtack   = svp_cs | dtack_ext;
assign cart_data_en = cart_oe & (cart_cs | svp_cs | data_en);

reg data_en;
always @(posedge clk_ram) data_en <= ms_rom_cs | ms_ram_cs | fm_det_cs | pier_eeprom_cs | cart_cs_ext | sf_cs | chk_cs;

// paprium: a mailbox access is answered from the Paprium cart RAM, not SDRAM. Without
// this the same cycle would also launch a ROM fetch whose late data would overwrite
// the mailbox value in cart_data
wire rom_data_req = (cart_cs & ~paprium_mailbox_cs) | ms_rom_cs | cart_cs_ext;
// paprium-end
wire sdram_rd     = cart_oe;

reg  [24:1] rom_addr;
reg         rom_req;
wire        rom_ack;
wire [15:0] rom_data;
reg         rom_rd;
reg         dtack_ext;

always @(posedge clk_ram) begin
	reg rd_old, we_old;
	
	if(~sdram_rd) dtack_ext <= 0;

	if(rom_req == rom_ack) begin
		if(rom_rd) begin
			cart_data <= rom_data;
			if(cart_cs_ext) dtack_ext <= 1;
		end
		rom_rd <= 0;
	end

	we_old <= rom_we;
	rd_old <= sdram_rd & rom_data_req;
	if((~rd_old & sdram_rd & rom_data_req) || (~we_old & rom_we)) begin
		// paprium: the decompression stream window supplies its own address from the MCU
		// pointer instead of the decoded cart address
		rom_addr <= paprium_stream_cs ? paprium_stream_addr :
		            (cart_ms ? ms_cart_addr : md_cart_addr) & rom_mask[24:1];
		// paprium-end
		rom_req <= ~rom_req;
		rom_rd <= sdram_rd;
		paprium_stream_pending <= paprium_stream_cs & sdram_rd;  // paprium
	end

// pocket: three deletions in one region. The reads whose source is gone: Master
// System boot ROM and work RAM, the FM detect register, Pier Solar's protection and
// SPI EEPROM, and the J-Cart pad. Port A is 64 KB, the size of the APF save
// slot, not upstream's 128 KB. And nothing shares the port any more, so the mux
// starts at the EEPROM branch
	if(md_sram_cs)     cart_data <= {sram_q,sram_q};
	if(md_eeprom_cs)   cart_data <= md_eeprom_data;
	if(svp_cs)         cart_data <= svp_data;
	if(sf_cs)          cart_data <= sf_data;
	if(chk_cs)         cart_data <= chk_data;
	// paprium: the mailbox wins the mux - it is the cart RAM the 68000 boots out of
	if(paprium_mailbox_cs) cart_data <= paprium_cart_data;
end

wire [15:0] sram_addr;
wire  [7:0] sram_di;
wire  [7:0] sram_q;
wire        sram_wren;

always_comb begin
	if(eeprom_quirk) begin
// pocket-end
		sram_addr = eeprom_ram_a;
		sram_di   = eeprom_ram_d;
		sram_wren = eeprom_ram_we;
	end
	else if(sf_quirk) begin
		sram_addr = cart_addr[15:1];
		sram_di   = cart_data_wr[7:0];
		sram_wren = sf_sram_wr;
	end
	else begin
		sram_addr = cart_addr[16:1];
		sram_di   = cart_data_wr[7:0];
		sram_wren = md_sram_cs & cart_lwr;
	end
end

reg [16:1] ram_rst_a;
always @(posedge clk) ram_rst_a <= ram_rst_a + 1'd1;

// pocket: upstream shares one 128 KB mixed-width RAM between the save SRAM and the
// SVP DRAM; that shape needs more block RAM than this device has left, plus the
// bypass logic a mixed width brings, so each bitstream keeps only its half. The
// base build's save RAM is byte wide and 64 KB, the APF save slot, and fills off
// save_clear rather than cart_dl. The SVP build swaps it for the DSP's 128 KB DRAM:
// Virtua Racing has no battery RAM, so nothing reads sram_q there and the only
// second client of the DRAM is the download fill, which never overlaps the DSP.
// The fill is a flat FFFF: upstream's sram00_quirk zero-fill arm serves save-RAM
// games, which never route to this build
wire  [7:0] sram2_q;
wire [15:0] svp_dram_q;

generate
if(SVP) begin
	spram #(16,16) svp_dram
	(
		.clock(clk),
		.address(cart_dl ? ram_rst_a : svp_dram_a),
		.data(cart_dl ? 16'hFFFF : svp_dram_do),
		.wren(cart_dl | svp_dram_we),
		.q(svp_dram_q)
	);

	assign sram_q  = 0;
	assign sram2_q = 0;
end
// paprium: the Paprium save is paprium_backup's 4 KB array inside paprium_cart, and
// save_do / save_change are muxed to it, so this 64 KB cart SRAM is pure dead weight
// in the Paprium build. At 512 Kbit it is more block RAM than the entire Paprium
// subsystem costs (MCU work RAM 256 Kbit + firmware ROM 128 Kbit + backup 32 Kbit),
// which makes dropping it the single largest memory saving available to this bitstream
else if(PAPRIUM) begin
	assign sram_q     = 0;
	assign sram2_q    = 0;
	assign svp_dram_q = 0;
end
// paprium-end
else begin
	wire [15:0] sram2_addr;
	wire  [7:0] sram2_di;
	wire        sram2_wren;

	always_comb begin
		if(save_clear) begin
			sram2_addr = ram_rst_a;
			sram2_di   = sram00_quirk ? 8'h00 : 8'hFF;
			sram2_wren = 1;
		end
		else begin
			sram2_addr = save_addr;
			sram2_di   = save_di;
			sram2_wren = save_wr;
		end
	end

	dpram #(16,8) ram
	(
		.clock(clk),
		.address_a(sram_addr),
		.data_a(sram_di),
		.wren_a(sram_wren),
		.q_a(sram_q),

		.address_b(sram2_addr),
		.data_b(sram2_di),
		.wren_b(sram2_wren),
		.q_b(sram2_q)
	);

	assign svp_dram_q = 0;
end
endgenerate
// pocket-end

// paprium: the Paprium save is the MCU-managed 4 KB backup RAM inside paprium_cart,
// not this build's cart SRAM
assign save_do     = paprium_active ? paprium_save_do     : sram2_q;
assign save_change = paprium_active ? paprium_save_change : sram_wren;
// paprium-end

//---------------------- MD cart ---------------------------------------

assign    md_addr = {cart_addr,1'b0};

reg [5:0] md_bank[8] = '{0,1,2,3,4,5,6,7};
reg       md_bank_sram = 0;
reg       md_bank_use = 0;

always @(posedge clk) begin
	if(reset) begin
		md_bank <= '{0,1,2,3,4,5,6,7};
		md_bank_sram <= 0;
		md_bank_use <= 0;
	end
// pocket: the SSF2 banks key off the ROM size, not a quirk, so unlike the mappers below
// they do not fall out of the SVP build on their own. Gating the write leaves the three
// bank registers at reset and folds the banked arm of md_cart_addr away
	// paprium: Paprium does NOT use SSF2 banking - the real mega-ppm cart FPGA has no
	// bank logic, it only flags the A130xx TIME region. Its anti-emulation routine RUNS
	// in slot 1 and writes A130F3=0; stock SSF2 banking would remap the slot the code is
	// executing in, giving a garbage fetch and an illegal-instruction crash at 0x081192
	// hidden under the legal screen. Suppressing it keeps the reads identity-mapped
	else if (!SVP && !PAPRIUM && cart_lwr && cart_time) begin
// pocket-end
		if(rom_mask[24:22]) begin
			if(cart_addr[3:1]) begin
				md_bank_use <= 1;
				if(~pier_quirk) md_bank[cart_addr[3:1]] <= cart_data_wr[5:0]; //SSF2 banks
				else if(cart_addr[3:1] == 4) {ep_cs, ep_hold , ep_sck, ep_si} <= cart_data_wr[3:0]; // Pier EEPROM
				else if(~cart_addr[3]) md_bank[{1'b1,cart_addr[2:1]}] <= cart_data_wr[3:0]; // Pier Banks
			end
			else if(~pier_quirk) md_bank_sram <= cart_data_wr[0];
		end
		else if(~schan_quirk) md_bank_sram <= cart_data_wr[0];
	end
end

// paprium: no mapper is live in the Paprium build. The real cart FPGA has no bank
// logic, SSF2 banking is suppressed above, and Realtec / SF-00x / the SVP DMA offset
// belong to other cartridges. Folding this to a pass-through drops the bank registers,
// both mapper address paths and their quirk comparators
wire [24:1] md_cart_addr = PAPRIUM ? cart_addr :
                           realtec_quirk ? realtec_addr       :
                           sf_quirk      ? sf_rom_addr        :
                           md_bank_use   ? {md_bank[cart_addr[21:19]], cart_addr[18:1]} :
                                           cart_addr - svp_dma;


// SVP
// pocket: upstream defines svp_dma and svp_cs inline; the declarations split off
// here so the generate branches below can drive them per build
wire        svp_dma;
wire        svp_cs;
// pocket-end

wire [20:1] rom2_a;
wire [15:0] rom2_data;
wire        rom2_req;
wire        rom2_ack;

wire [15:0] svp_data;
wire        svp_dtack_n;

wire [15:0] svp_dram_a;
wire [15:0] svp_dram_do;
wire        svp_dram_we;

// pocket: the DSP only exists in the SVP bitstream; the base branch drives constants
// so the reads and the address arithmetic above stay verbatim and fold away, and
// DRAM_DI is svp_dram_q rather than upstream's sram2_q because the shared save RAM
// this device cannot afford is what made them one signal. Upstream qualifies all three
// with svp_quirk, which the loader has already decided by serial, so it is 1 here; reset
// covers the download, so the DSP still starts no earlier
generate
if(SVP) begin
	assign svp_dma = cart_dma;
	assign svp_cs  = ~svp_dtack_n;

	reg svp_ce;
	always @(posedge clk) svp_ce <= ~reset & ~svp_ce;

	SVP svp
	(
		.CLK(clk),
		.CE(svp_ce),
		.RST_N(~reset),
		.ENABLE(1),

		.BUS_A(cart_addr[23:1]),
		.BUS_DO(svp_data),
		.BUS_DI(cart_data_wr),
		.BUS_SEL(cart_oe | cart_lwr),
		.BUS_RNW(~cart_lwr),
		.BUS_DTACK_N(svp_dtack_n),
		.DMA_ACTIVE(cart_dma),

		.ROM_A(rom2_a),
		.ROM_DI(rom2_data),
		.ROM_REQ(rom2_req),
		.ROM_ACK(rom2_ack),

		.DRAM_A(svp_dram_a),
		.DRAM_DI(svp_dram_q),
		.DRAM_DO(svp_dram_do),
		.DRAM_WE(svp_dram_we)
	);
end
else begin
	assign svp_dma = 0;
	assign svp_cs = 0;
	assign svp_data = 0;
	assign svp_dtack_n = 1;
	assign rom2_a = 0;
	assign rom2_req = 0;
	assign svp_dram_a = 0;
	assign svp_dram_do = 0;
	assign svp_dram_we = 0;
end
endgenerate
// pocket-end

// paprium: the Paprium cartridge subsystem. Ported from MisterPezz82's MiSTer fork;
// the differences from it are the PAPRIUM generate guard (that core always compiles
// the subsystem in and gates it at run time on the serial - this device cannot afford
// to carry it in the other bitstreams), the byte-wide save port, and the MD+ commands
// leaving the module instead of driving an on-chip MD+ engine
wire [15:0] paprium_cart_data;
wire        paprium_mailbox_cs;
wire        paprium_stream_cs;
wire [24:1] paprium_stream_addr;
wire [24:1] paprium_mem_addr;
wire [15:0] paprium_mem_din;
wire        paprium_mem_wrl;
wire        paprium_mem_wrh;
wire        paprium_mem_req;
wire  [7:0] paprium_save_do;
wire        paprium_save_change;
reg         paprium_stream_pending = 0;
reg         paprium_stream_ack_toggle = 0;

// The Paprium build is Paprium-only. Like the SVP bitstream, the loader has already
// decided by serial which core to launch, so re-detecting the header here would only add
// a way to fail on a differently-headered dump. Hard-wiring it also drops the whole quirk
// table, cart_id and crc from this build. To go back to serial detection, restore the
// 'GM T-574120' compare in the quirk table and drive this from it
wire paprium_quirk = PAPRIUM;

assign paprium_active = PAPRIUM & paprium_quirk;

// One toggle per COMPLETED stream word. The stream pointer must advance per word
// actually delivered, not per raw bus strobe: the cycle-accurate VDP glitches
// cart_cs/cart_oe within a single DMA word, and keying off the combinational
// stream_cs falling edge double-counted those glitches and desynced the stream
// (per-pixel tile noise on backgrounds while resident font/UI stayed clean)
wire paprium_stream_read_ack = paprium_stream_pending & rom_rd & (rom_req == rom_ack);

always @(posedge clk_ram) begin
	if(reset) paprium_stream_ack_toggle <= 0;
	else if(paprium_stream_read_ack) paprium_stream_ack_toggle <= ~paprium_stream_ack_toggle;
end

generate
if(PAPRIUM) begin
	paprium_cart paprium
	(
		.clk(clk),
		.reset(reset),
		.enable(paprium_quirk),

		.cart_addr(cart_addr),
		.cart_data_wr(cart_data_wr),
		.cart_cs(cart_cs),
		.cart_oe(cart_oe),
		.cart_lwr(cart_lwr),
		.cart_uwr(cart_uwr),
		.cart_time(cart_time),
		.stream_read_ack_toggle(paprium_stream_ack_toggle),

		.cart_data(paprium_cart_data),
		.mailbox_cs(paprium_mailbox_cs),
		.stream_cs(paprium_stream_cs),
		.stream_addr(paprium_stream_addr),
		.md_reset(paprium_md_reset),

		.mdp_track_request(mdp_track_request),
		.mdp_track_num(mdp_track_num),
		.mdp_track_loop(mdp_track_loop),
		.mdp_stop_request(mdp_stop_request),
		.mdp_fade_sectors(mdp_fade_sectors),
		.mdp_resume_request(mdp_resume_request),
		.mdp_volume(mdp_volume),
		.mdp_volume_request(mdp_volume_request),
		.mdp_active(mdp_active),
		.mdp_playing(mdp_playing),
		.mdp_current_track(mdp_current_track),

		.sfx_l(paprium_sfx_l),
		.sfx_r(paprium_sfx_r),

		.dbg_ramdp_write(),
		.dbg_ramdp_addr(),
		.dbg_ramdp_data(),

		.save_addr(save_addr),
		.save_di(save_di),
		.save_do(paprium_save_do),
		.save_wr(save_wr),
		.save_change(paprium_save_change),

		.mem_addr(paprium_mem_addr),
		.mem_din(paprium_mem_din),
		.mem_dout(rom2_data),
		.mem_wrl(paprium_mem_wrl),
		.mem_wrh(paprium_mem_wrh),
		.mem_req(paprium_mem_req),
		.mem_ack(rom2_ack)
	);
end
else begin
	assign paprium_cart_data   = 0;
	assign paprium_mailbox_cs  = 0;
	assign paprium_stream_cs   = 0;
	assign paprium_stream_addr = 0;
	assign paprium_mem_addr    = 0;
	assign paprium_mem_din     = 0;
	assign paprium_mem_wrl     = 0;
	assign paprium_mem_wrh     = 0;
	assign paprium_mem_req     = 0;
	assign paprium_save_do     = 0;
	assign paprium_save_change = 0;
	assign paprium_md_reset    = 0;
	assign paprium_sfx_l       = 0;
	assign paprium_sfx_r       = 0;

	assign mdp_track_request  = 0;
	assign mdp_track_num      = 0;
	assign mdp_track_loop     = 0;
	assign mdp_stop_request   = 0;
	assign mdp_fade_sectors   = 0;
	assign mdp_resume_request = 0;
	assign mdp_volume         = 0;
	assign mdp_volume_request = 0;
	assign mdp_active         = 0;
end
endgenerate
// paprium-end

// SRAM
// pocket: svp_quirk already sets noram_quirk, so this select is dead in the SVP build at
// run time but not statically. Saying so drops the address compares, and with the sram
// mux constant, save_change with them
wire md_sram_cs = !SVP && ~cart_ms && (cart_addr[23:21] == 1) && (md_bank_sram || (cart_addr >= rom_sz && ~&cart_addr[20:19])) && ~noram_quirk;
// pocket-end

// EEPROM
wire        md_eeprom_cs   = (eeprom_quirk[3:2] == 2'b01) ? (cart_addr[23:19] == 5'b00111) : (eeprom_quirk[2:0] && ((eeprom_bank & ~cart_addr[20]) || !eeprom_quirk[3]) && cart_addr[23:21] == 3'b001);
wire [15:0] md_eeprom_data;

always_comb begin
	md_eeprom_data = 0;
	casex(eeprom_quirk)
		4'b0001: md_eeprom_data[7] = eeprom_sda;
		4'b0010: md_eeprom_data[0] = eeprom_sda;
		4'b0011: md_eeprom_data[1] = eeprom_sda;
		4'b01xx: md_eeprom_data[7] = eeprom_sda;
		4'b1xxx: md_eeprom_data[0] = eeprom_sda;
		default:;
	endcase
end

reg         eeprom_sdai;
wire        eeprom_sdao;
reg         eeprom_scl;
wire [14:0] eeprom_ram_a;
wire  [7:0] eeprom_ram_d;
wire        eeprom_ram_we;
wire  [7:0] eeprom_ram_q;
reg         eeprom_bank;
always @(posedge clk) begin
	if(reset || !eeprom_quirk) begin
		eeprom_bank <= 0;
		eeprom_sdai <= 1;
		eeprom_scl  <= 1;
	end
	else if(cart_addr[23:21] == 3'b001 && cart_cs && (cart_lwr | cart_uwr)) begin
		casex (eeprom_quirk)
			4'b0001: if(cart_lwr) {eeprom_sdai,eeprom_scl} <= cart_data_wr[7:6];
			4'b0010: if(cart_lwr) {eeprom_scl,eeprom_sdai} <= cart_data_wr[1:0];
			4'b0011: if(cart_lwr) {eeprom_scl,eeprom_sdai} <= cart_data_wr[1:0];
			4'b01xx: if(cart_addr[20:19] == 2'b10) {eeprom_scl,eeprom_sdai} <= cart_data_wr[1:0];
			4'b1xxx:      if (~cart_addr[20] &  cart_lwr & ~cart_uwr) eeprom_sdai <= cart_data_wr[0];
						else if (~cart_addr[20] & ~cart_lwr &  cart_uwr) eeprom_scl  <= cart_data_wr[8];
						else if (~cart_addr[20] &  cart_lwr &  cart_uwr) eeprom_bank <= ~cart_data_wr[0];
		endcase
	end
end

wire eeprom_sda = {eeprom_sdao & eeprom_sdai};

//                                        C01     C01     C02     C16      C65       C08      C04
wire [12:0] eeprom_mask[8] = '{13'h00, 13'h7f, 13'h7f, 13'hff, 13'h7ff, 13'h1fff, 13'h3ff, 13'h1ff};

// pocket: the EEPROM engine is part of what the SVP bitstream sells to afford the
// DSP; Virtua Racing has none, and the loader only routes Virtua Racing to that
// build. sda_o high is the bus idle level, so a mis-routed EEPROM game sees a
// device that never answers
// paprium: Paprium has no serial EEPROM either, and the Paprium build detects no
// quirks at all, so the 24CXX engine can never be selected. Same tie-off as the SVP
// bitstream uses
generate
if(SVP || PAPRIUM) begin
	assign eeprom_sdao = 1;
	// The sram mux still reads these when eeprom_quirk hits; tie them off so
	// save_change stays driven instead of floating with the 24CXX gone
	assign eeprom_ram_a  = 0;
	assign eeprom_ram_d  = 0;
	assign eeprom_ram_we = 0;
end
else begin
	EPPROM_24CXX e24cxx
	(
		.clk(clk),
		.rst(reset),
		.en(1),

		.mode((eeprom_quirk[2:0] <= 3'b010) ? 2'd0 : (eeprom_quirk[2:0] == 3'b101) ? 2'd2 : 2'd1),
		.mask(eeprom_mask[eeprom_quirk[2:0]]),

		.sda_i(eeprom_sdai),
		.sda_o(eeprom_sdao),
		.scl(eeprom_scl),

		.ram_addr(eeprom_ram_a),
		.ram_d(eeprom_ram_d),
		.ram_wr(eeprom_ram_we),
		.ram_q(sram_q)
	);
end
endgenerate
// pocket-end


// pocket: Pier Solar's SPI EEPROM and its protection reads are not built here.
// ep_si/ep_sck/ep_hold/ep_cs keep their names so the SSF2 bank block
// above needs no edit; pier_quirk is 0, so the branch that writes them is dead
reg         ep_si, ep_sck, ep_hold, ep_cs;
wire        pier_quirk = 0;
wire        pier_eeprom_cs = 0;

// The Sega Channel is 4 MB of writable ROM in SDRAM for one Japanese download
// service, and the J-Cart is a second controller port the Pocket does not have.
// rom_we staying 0 is what keeps the sdram port 1 write strobes from ever being
// sampled asserted, so do not revive it without giving them a gate of their own
wire        rom_we = 0;
wire        schan_quirk = 0;
// pocket-end

// MK3U Trilogy 10MB version (13MB isn't compatible with real HW!)
// pocket: Virtua Racing is 2 MB, so cart_addr[23:22] and cart_addr < rom_sz cannot both hold
// in the SVP build; the fitter cannot see that, and the compares feed the dtack_ext path
wire cart_cs_ext = !SVP && ~cart_ms && (cart_addr[23:22] && cart_addr[23:20]<'hA) && (cart_addr < rom_sz);
// pocket-end

// Realtec
reg [21:17] realtec_bank;
reg   [4:0] realtec_mask;
reg         realtec_boot;
always @(posedge clk) begin
	if (reset | ~realtec_quirk) begin
		realtec_bank <= 0;
		realtec_mask <= 0;
		realtec_boot <= 1;
	end
	else begin
		if (cart_addr[23:16] == 8'h40 && !cart_addr[11:1] && cart_uwr) begin
			case(cart_addr[15:12])
				4'h0: begin realtec_bank[21:20] <= cart_data_wr[2:1]; realtec_boot <= ~cart_data_wr[0]; end
				4'h2: begin 
					case (cart_data_wr[5:0])
						6'd0,6'd1:                                      realtec_mask <= 5'b00000;
						6'd2:                                           realtec_mask <= 5'b00001;
						6'd3,6'd4:                                      realtec_mask <= 5'b00011;
						6'd5,6'd6,6'd7,6'd8:                            realtec_mask <= 5'b00111;
						6'd9,6'd10,6'd11,6'd12,6'd13,6'd14,6'd15,6'd16: realtec_mask <= 5'b01111;
						default:                                        realtec_mask <= 5'b11111;
					endcase
				end
				4'h4: begin realtec_bank[19:17] <= cart_data_wr[2:0]; end
			endcase
		end
	end
end

wire [23:1] realtec_addr = realtec_boot ? {11'b00000111111,cart_addr[12:1]} : {2'b00,(cart_addr[21:17] & realtec_mask) + realtec_bank,cart_addr[16:1]};

//SF-001,SF-002,SF-004 mappers
wire        sf_cs     = sf_quirk && (sf_sram_en | cart_time);
wire [15:0] sf_data   = cart_time ? (sf_quirk[1:0] == 2'd3 ? sf004_do : 16'h0000) : {8'hff,sram_q};

reg   [7:0] sf001_bank_reg;
reg   [7:0] sf002_bank_reg;
reg         sf004_sram_reg;
reg   [7:0] sf004_bank_reg;
reg   [2:0] sf004_first_page;

always @(posedge clk) begin
	if(reset || !sf_quirk) begin
		sf001_bank_reg <= 8'h00;
		sf002_bank_reg <= 8'h00;
		sf004_sram_reg <= 0;
		sf004_bank_reg <= 8'h80;
		sf004_first_page <= '0;
	end
	else if(cart_lwr && !cart_addr[23:16]) begin
		
		case(sf_quirk[1:0])

			//sf-001 new rev
			1: if(sf_quirk[2] && !sf001_bank_reg[5] && cart_addr[11:8] == 4'he) sf001_bank_reg <= cart_data_wr[7:0];

			//sf-002
			2: sf002_bank_reg <= cart_data_wr[7:0];

			//sf-004
			3: if (sf004_bank_reg[7]) begin
					case (cart_addr[11:8])
						4'hd: sf004_sram_reg <= cart_data_wr[7];
						4'he: sf004_bank_reg <= cart_data_wr[7:0];
						4'hf: sf004_first_page <= cart_data_wr[6:4];
					endcase
				end
		endcase
	end
end

wire [23:1] sf001_rom_a   = (sf001_bank_reg[7] && !cart_addr[21:18]) ? {6'b001110,cart_addr[17:1]} : {2'b00,cart_addr[21:1]};
wire        sf001_sram_en = (cart_addr[23:20] == 4 && !sf_quirk[2]) || (cart_addr[23:18] == 6'b001111 && sf001_bank_reg[7]);

wire [23:1] sf002_rom_a   = {2'b00,cart_addr[21] & ~sf002_bank_reg[7],cart_addr[20:1]};
wire        sf002_sram_en = (cart_addr[23:18] == 6'b001111);
						
wire [23:1] sf004_rom_a   = (cart_addr[23:16] < 8'h14 && sf004_bank_reg[6]) ? {3'b000,sf004_first_page + cart_addr[20:18],cart_addr[17:1]} : {3'b000,sf004_first_page,cart_addr[17:1]};
wire        sf004_sram_en = (cart_addr[23:20] == 2 && sf004_sram_reg);
wire [15:0] sf004_do      = {8'hff,1'b0,sf004_first_page,4'b0000};

wire        sf_sram_en    = sf_quirk[1:0] == 1 ? sf001_sram_en :
                            sf_quirk[1:0] == 2 ? sf002_sram_en : 
                                                 sf004_sram_en;

wire [23:1] sf_rom_addr   = sf_quirk[1:0] == 1 ? sf001_rom_a : 
                            sf_quirk[1:0] == 2 ? sf002_rom_a : 
                                                 sf004_rom_a;

wire        sf_sram_wr    = sf_sram_en & cart_lwr;

//Simple check
reg         chk_cs;
reg  [15:0] chk_data;

always @(posedge clk) begin
	chk_cs <= 0;
	case(chk_quirk)
		1: if(md_addr == 'h400000) begin
				chk_data <= 'h9000;
				chk_cs <= 1;
			end
			else if(md_addr == 'h401000) begin
				chk_data <= 'hd300;
				chk_cs <= 1;
			end

		2: if(md_addr == 'hA13000) begin
				chk_data <= 'h0a;
				chk_cs <= 1;
			end

		3: if(md_addr == 'hA13000) begin
				chk_data <= 'h1c;
				chk_cs <= 1;
			end
	endcase
end

// pocket: a Master System cart needs a 16 KB boot ROM, the Z80 bus decode and four
// more mappers, and its FM needs the OPLL. The Pocket has its own Master System
// core, and cart_ms is tied low here
wire [21:0] ms_cart_addr = 0;
wire        ms_rom_cs = 0;
wire        ms_ram_cs = 0;
wire        fm_det_cs = 0;
// pocket-end

//---------------------- Cart detect ---------------------------------------

// pocket: pier_quirk and schan_quirk are constants at their deletion sites above, so they
// are gone from here. Only the base build writes svp_quirk, where it feeds noram_quirk
reg       sram00_quirk, fmbusy_quirk, noram_quirk, svp_quirk;
// pocket-end
reg [3:0] eeprom_quirk;
reg       realtec_quirk;
reg [2:0] sf_quirk;
reg [3:0] chk_quirk;

always @(posedge clk) begin
	reg [87:0] cart_id;
	reg [15:0] crc = 0;
	reg [15:0] crc_real = 0;
	reg [31:0] realtec_id = 0;
	reg [31:0] sp = 0;
	reg old_dl;
	old_dl <= cart_dl;

	if(~old_dl && cart_dl) begin
// pocket: the quirks whose logic is gone are constants now, there is no lightgun to
// pick a type or a sensor delay for, and the battery-RAM flag clears with the rest
		{sram00_quirk,fmbusy_quirk,noram_quirk,svp_quirk,eeprom_quirk,realtec_quirk,sf_quirk,chk_quirk} <= '0;
		sram_present <= 0;
// pocket-end
		crc_real <= 0;
		crc <= 0;
	end

	if(cart_dl_wr & cart_dl & ~cart_ms) begin
		if(cart_dl_addr == 'h000) sp[31:16] <= {cart_dl_data[7:0],cart_dl_data[15:8]};
		if(cart_dl_addr == 'h002) sp[15:00] <= {cart_dl_data[7:0],cart_dl_data[15:8]};
		if(cart_dl_addr == 'h180) cart_id[87:72] <= {cart_dl_data[7:0],cart_dl_data[15:8]};
		if(cart_dl_addr == 'h182) cart_id[71:56] <= {cart_dl_data[7:0],cart_dl_data[15:8]};
		if(cart_dl_addr == 'h184) cart_id[55:40] <= {cart_dl_data[7:0],cart_dl_data[15:8]};
		if(cart_dl_addr == 'h186) cart_id[39:24] <= {cart_dl_data[7:0],cart_dl_data[15:8]};
		if(cart_dl_addr == 'h188) cart_id[23:08] <= {cart_dl_data[7:0],cart_dl_data[15:8]};
		if(cart_dl_addr == 'h18A) cart_id[07:00] <= cart_dl_data[7:0];
		if(cart_dl_addr == 'h18E) crc <= {cart_dl_data[7:0],cart_dl_data[15:8]};
// pocket: the loader only ever sends Virtua Racing here, so this build detects nothing.
// paprium: and the Paprium build only ever gets Paprium, so it detects nothing either -
// see the paprium_quirk note above the subsystem
// Gating the table drops it, cart_id, sp and crc
		if(!SVP && !PAPRIUM && cart_dl_addr == 'h190) begin
// pocket-end
			     if(cart_id[63:0] == "T-50446 ") eeprom_quirk <= 4'b0001;  // X24C01 John Madden Football 93
			else if(cart_id[63:0] == "T-50516 ") eeprom_quirk <= 4'b0001;  // X24C01 John Madden Football 93 Championship Edition
			else if(cart_id[63:0] == "T-50396 ") eeprom_quirk <= 4'b0001;  // X24C01 NHLPA Hockey 93
			else if(cart_id[63:0] == "T-50176 ") eeprom_quirk <= 4'b0001;  // X24C01 Rings of Power
			else if(cart_id[63:0] == "T-50606 ") eeprom_quirk <= 4'b0001;  // X24C01 Bill Walsh College Football
			else if(cart_id[63:0] == "MK-1215 ") eeprom_quirk <= 4'b0010;  // X24C01 Evander Real Deal Holyfield's Boxing
			else if(cart_id[63:0] == "G-4060  ") eeprom_quirk <= 4'b0010;  // X24C01 Wonder Boy
			else if(cart_id[63:0] == "00001211") eeprom_quirk <= 4'b0010;  // X24C01 Sports Talk Baseball
			else if(cart_id[63:0] == "MK-1228 ") eeprom_quirk <= 4'b0010;  // X24C01 Greatest Heavyweights
			else if(cart_id[63:0] == "G-5538  ") eeprom_quirk <= 4'b0010;  // X24C01 Greatest Heavyweights JP
			else if(cart_id[63:0] == "PR-1993 ") eeprom_quirk <= 4'b0010;  // X24C01 Greatest Heavyweights (prototype)
			else if(cart_id[63:0] == "00004076") eeprom_quirk <= 4'b0010;  // X24C01 Honoo no Toukyuuji Dodge Danpei
			else if(cart_id[63:0] == "T-12046 ") eeprom_quirk <= 4'b0010;  // X24C01 Mega Man - The Wily Wars 
			else if(cart_id[63:0] == "T-12053 ") eeprom_quirk <= 4'b0010;  // X24C01 Rockman Mega World 
			else if(cart_id[63:0] == "G-4524  ") eeprom_quirk <= 4'b0010;  // X24C01 Ninja Burai Densetsu
			else if(cart_id[63:0] == "00054503") eeprom_quirk <= 4'b0010;  // X24C01 Game Toshokan
			else if(cart_id[63:0] == "T-81033 ") eeprom_quirk <= 4'b0011;  // 24C02 NBA Jam (J)
			else if(cart_id[63:0] == "T-081326") eeprom_quirk <= 4'b0011;  // 24C02 NBA Jam (U)(E)
			else if(cart_id[63:0] == "T-081276") eeprom_quirk <= 4'b1011;  // 24C02 NFL Quarterback Club
			else if(cart_id[63:0] == "T-81406 ") eeprom_quirk <= 4'b1111;  // 24C04 NBA Jam TE
			else if(cart_id[63:0] == "T-081586") eeprom_quirk <= 4'b1100;  // 24C16 NFL Quarterback Club '96
			else if(cart_id[63:0] == "T-81576 ") eeprom_quirk <= 4'b1101;  // 24C65 College Slam
			else if(cart_id[63:0] == "T-81476 ") eeprom_quirk <= 4'b1101;  // 24C65 Frank Thomas Big Hurt Baseball
			else if(cart_id[63:0] == "T-120106") eeprom_quirk <= 4'b0110;  // 24C08 Brian Lara Cricket
			else if(sp=="DNLD" && crc == 'h168B) eeprom_quirk <= 4'b0110;  // 24C08 JCART Micro Machines Military
			else if(sp=="DNLD" && crc == 'h165E) eeprom_quirk <= 4'b0100;  // 24C16 JCART Micro Machines Turbo Tournament 96
			else if(cart_id[63:0] == "T-120096") eeprom_quirk <= 4'b0100;  // 24C16 JCART Micro Machines 2 - Turbo Tournament
			else if(cart_id[63:0] == "T-120146") eeprom_quirk <= 4'b0101;  // 24C65 Brian Lara Cricket 96 / Shane Warne Cricket

// pocket: pier_quirk and schan_quirk are tied off at their deletion sites above
// and the lightgun ports are gone, so the rows that set them (Pier Solar, Game no
// Kanzume Otokuyou) and the sensor-delay block that closed the upstream chain are
// dropped
			else if(cart_id[63:0] == "T-113016") noram_quirk  <= 1;        // Puggsy fake ram check
			else if(cart_id[63:0] == "MK-1229 ") svp_quirk    <= 1;        // Virtua Racing EU/US
			else if(cart_id[63:0] == "G-7001  ") svp_quirk    <= 1;        // Virtua Racing JP
			else if(cart_id[63:0] == "T-35036 ") fmbusy_quirk <= 1;        // Hellfire US
			else if(cart_id[63:0] == "T-25073 ") fmbusy_quirk <= 1;        // Hellfire JP
			else if(cart_id[63:0] == "MK-1137-") fmbusy_quirk <= 1;        // Hellfire EU
			else if(cart_id[63:0] == "G-4034  ") fmbusy_quirk <= 1;        // DAISENPU/TWIN HAWK JP/EU
			else if(cart_id[63:0] == "T-44016 ") fmbusy_quirk <= 1;        // Tecmo World Cup
			else if(cart_id[63:0] == "T-44023 ") fmbusy_quirk <= 1;        // Tecmo World Cup JP
			else if(cart_id[63:0] == " GM 0000") sram00_quirk <= 1;        // Sonic 1 Remastered
			else if(cart_id[87:40] == "SF-001")  sf_quirk     <= {crc == 16'h3E08,2'b01}; // Beggar Prince (Unl), Beggar Prince rev 1 (Unl)
			else if(cart_id[87:40] == "SF-002")  sf_quirk     <= {1'b1,2'b10}; // Legend of Wukong (Unl)
			else if(cart_id[87:40] == "SF-004")  sf_quirk     <= {1'b1,2'b11}; // Star Odyssey (Unl)
// pocket-end
		end

// pocket: "RA" at $1B0 is the header's battery-RAM marker, and APF wants the save
// size in the data table before it will write a save file back. The SVP build has
// no save RAM behind the flag, and announcing one would let APF overwrite a real
// save file with zeroes if a battery game is ever run there by hand
// paprium: the Paprium header carries NO "RA" battery-RAM marker at 0x1B0 (verified
// against the GM MK-12056-00 dump), so header detection would leave sram_present low,
// APF would never allocate a save slot, and the MCU's backup RAM would never persist.
// The Paprium build announces the save unconditionally - it is a Paprium-only bitstream
		if(cart_dl_addr == 'h1B0 && (PAPRIUM || ({cart_dl_data[7:0],cart_dl_data[15:8]} == "RA" && !SVP))) sram_present <= 1;
// pocket-end

		if(cart_dl_addr == 'h7E100) realtec_id[31:16] <= {cart_dl_data[7:0],cart_dl_data[15:8]};
		if(cart_dl_addr == 'h7E102) realtec_id[15: 0] <= {cart_dl_data[7:0],cart_dl_data[15:8]};
// pocket: realtec_quirk is set from the ROM body, not the header, so the chain above does
// not cover it. Stuck at 0 it takes the Realtec bank registers, realtec_addr and realtec_id
		if(!SVP && cart_dl_addr == 'h7E104 && realtec_id == "SEGA") realtec_quirk <= 1; // Earth Defend, Funny World & Balloon Boy, Whac-a-Critter
// pocket-end
		
		if(cart_dl_addr[24:9]) crc_real <= crc_real + {cart_dl_data[7:0],cart_dl_data[15:8]};
		
		if(sf_quirk || svp_quirk || eeprom_quirk || pier_quirk) noram_quirk <= 1;
	end
	
// pocket: the checksum quirks key off crc_real, so gating here drops that whole-ROM adder too
	if(~cart_dl && !SVP) begin
// pocket-end
		if(crc == 'h0000 && crc_real == 'h7037) chk_quirk <= 1; // Ma Jiang Qing Ren - Ji Ma Jiang Zhi
		if(crc == 'h0000 && crc_real == 'h3b95) chk_quirk <= 1; // Super Majon Club
		if(crc == 'hffff && crc_real == 'h0474) chk_quirk <= 2; // Super Mario 2 1998
		if(crc == 'h2020 && crc_real == 'hb4eb) chk_quirk <= 3; // Super Mario World
	end
end

assign ym2612_quirk = fmbusy_quirk;

// pocket: an EEPROM cart carries no battery-RAM marker in its header, so APF's save
// size has to come from the quirk instead. Never in the SVP build, whose EEPROM
// engine is gone: the flag would let APF overwrite a real save file with garbage
assign eeprom_present = !SVP && |eeprom_quirk;
// pocket-end

endmodule
