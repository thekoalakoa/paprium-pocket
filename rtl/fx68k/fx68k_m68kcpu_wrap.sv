// fx68k-soak: pin-compatible wrapper around ijor/FX68K for paprium-pocket Nuked md_board.
// Measurement / soak branch only - NOT a shipping CPU swap.
// 2026-09-06 DATA_FC_AUDIT addr-data-fix soak (from addr-fix BC6E8519 blank):
// - KEEP: ADDRESS=eab[23:1]; ADDRESS_z=~addrOe (CART_ADDR_AUDIT — Nuked-true)
// - FIX:  DATA_o=oEdb, iEdb(DATA_i) — Nuked pin is TRUE (DATA_o=~data_io cancels
//         internal ~load; cart_data/VD true; FX68K oEdb/iEdb true). Prior data-noinv
//         499F99E6 kept ADDRESS=~eab — not a clean combo with addr-fix.
// - FIX:  FC={FC2,FC1,FC0} (drop invert) — ym6045 fc00..fc11 decode true FC bits;
//         Nuked FC=~w32x with inverted-sense regs → pin true; FX68K rFC true.
// - KEEP: *n pass-through; BG=BGn; RW_z=eRWn&ASn; strobe_z=ASn; FC_z=ASn; DATA_z=ASn|eRWn
// - KEEP: HALTn=1'b1; HALT_pull=~oHALTEDn; cold pwrUp; combo enPhi lead-1; MCLK/14 CLEAN
`timescale 1ns / 1ns

module fx68k_m68kcpu_wrap (
	input MCLK,
	input CLK,
	input VPA,
	input BR,
	input BGACK,
	input DTACK,
	input [2:0] IPL,
	input BERR,
	input RESET_i,
	output RESET_pull,
	input HALT_i,
	output HALT_pull,
	input [15:0] DATA_i,
	output [15:0] DATA_o,
	output DATA_z,
	output E_CLK,
	output BG,
	output [2:0] FC,
	output FC_z,
	output RW,
	output RW_z,
	output [22:0] ADDRESS,
	output ADDRESS_z,
	output AS,
	output LDS,
	output UDS,
	output strobe_z
);

	localparam [15:0] COLD_PWRUP_CYCLES = 16'd4095;
	reg pwrUp = 1'b1;
	reg [15:0] coldCnt = 16'd0;
	always @(posedge MCLK) begin
		if (pwrUp) begin
			if (coldCnt == COLD_PWRUP_CYCLES)
				pwrUp <= 1'b0;
			else
				coldCnt <= coldCnt + 16'd1;
		end
	end

	wire fx_reset = ~RESET_i | pwrUp;
	wire fx_haltn = 1'b1;

	reg [3:0] phiCnt;
	always @(posedge MCLK) begin
		if (fx_reset)
			phiCnt <= 4'd0;
		else if (phiCnt == 4'd13)
			phiCnt <= 4'd0;
		else
			phiCnt <= phiCnt + 4'd1;
	end
	wire enPhi1 = ~fx_reset & (phiCnt == 4'd13);
	wire enPhi2 = ~fx_reset & (phiCnt == 4'd6);

	wire ASn, LDSn, UDSn, eRWn, VMAn;
	wire BGn, oRESETn, oHALTEDn;
	wire FC0, FC1, FC2;
	wire [23:1] eab;
	wire [15:0] oEdb;
	wire addrOe;

	fx68k cpu (
		.clk(MCLK),
		.HALTn(fx_haltn),
		.extReset(fx_reset),
		.pwrUp(pwrUp),
		.enPhi1(enPhi1),
		.enPhi2(enPhi2),
		.eRWn(eRWn),
		.ASn(ASn),
		.LDSn(LDSn),
		.UDSn(UDSn),
		.E(E_CLK),
		.VMAn(VMAn),
		.FC0(FC0),
		.FC1(FC1),
		.FC2(FC2),
		.BGn(BGn),
		.oRESETn(oRESETn),
		.oHALTEDn(oHALTEDn),
		.DTACKn(DTACK),
		.VPAn(VPA),
		.BERRn(BERR),
		.BRn(BR),
		.BGACKn(BGACK),
		.IPL0n(IPL[0]),
		.IPL1n(IPL[1]),
		.IPL2n(IPL[2]),
		.iEdb(DATA_i),
		.oEdb(oEdb),
		.eab(eab),
		.addrOe(addrOe)
	);

	assign AS = ASn;
	assign LDS = LDSn;
	assign UDS = UDSn;
	assign RW = eRWn;
	assign ADDRESS = eab[23:1];
	assign DATA_o = oEdb;
	assign DATA_z = ASn | eRWn;
	assign ADDRESS_z = ~addrOe;
	assign RW_z = eRWn & ASn;
	assign strobe_z = ASn;
	assign FC = {FC2, FC1, FC0};
	assign FC_z = ASn;
	assign BG = BGn;
	assign RESET_pull = ~oRESETn;
	assign HALT_pull = ~oHALTEDn;

endmodule