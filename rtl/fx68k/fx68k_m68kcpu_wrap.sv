// Pin-compatible wrapper around ijor/FX68K for paprium-pocket's Nuked md_board.
// SHIPPING CPU from 0.2.2, selected by USE_FX68K (see projects/megadrive_pocket.qsf).
// FX68K (c) 2018, 2021 Jorge Cwik, GPLv3-or-later. Wrapper GPLv3-or-later.
// NOTE: the 0.2.2 bitstream was fit from this file at md5 a748606093f7a18ad641d300a7824ef0,
// which differs from the current file only in this header comment.
// flicker A/B VCLK-enPhi on 0.2.1 (isolation: Nuked clean).
// ONE VARIABLE vs lead-1 free-run A4DEABF0: enPhi from VCLK edge-detect (CLK=VCLK);
// LOCKED pads 0298/AA50 unchanged. Prior VCLK 3D7CED75 was on 0.2.0 pre-animation-fix.
// - KEEP: ADDRESS=eab[23:1]; ADDRESS_z=~addrOe
// - KEEP: DATA_o=oEdb, iEdb(DATA_i); DATA_z=ASn|eRWn
// - KEEP: FC={FC2,FC1,FC0}; FC_z=ASn
// ALT1+VPA: BR/BGACK/VPA flopped on enPhi2 (vs ALT1 E98AAB3E)
// Spec-GO 1-tick DTACK: MCLK-flop DTACK -> FX DTACKn (ONE VARIABLE vs ALT1+VPA)
// - KEEP: *n pass-through except BRn/BGACKn=br_d/bgack_d, VPAn=vpa_d; BG=BGn; RW_z=eRWn&ASn; strobe_z=ASn
// - KEEP: HALTn=1'b1; HALT_pull=~oHALTEDn; cold pwrUp; fx_reset
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

	// VCLK-synced enPhi (CLK port = VCLK from md_board); mutually exclusive one-hots
	reg clk_r;
	always @(posedge MCLK) clk_r <= CLK;
	wire rise = CLK & ~clk_r;
	wire mid  = ~CLK & clk_r;
	wire enPhi1 = ~fx_reset & rise;
	wire enPhi2 = ~fx_reset & mid;


	// ALT1+VPA: BR/BGACK/VPA enPhi2-register (stable at next enPhi1); ONE VARIABLE vs ALT1
	reg br_d, bgack_d, vpa_d;
	always @(posedge MCLK) begin
		if (fx_reset) begin
			br_d <= 1'b1;
			bgack_d <= 1'b1;
			vpa_d <= 1'b1;
		end else if (enPhi2) begin
			br_d <= BR;
			bgack_d <= BGACK;
			vpa_d <= VPA;
		end
	end

	// Spec-GO 1-tick DTACK wrap: sample DTACK every MCLK; feed FX from flop
	reg dtack_d;
	always @(posedge MCLK) begin
		if (fx_reset) dtack_d <= 1'b1;
		else dtack_d <= DTACK;
	end
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
		.DTACKn(dtack_d),
		.VPAn(vpa_d),
		.BERRn(BERR),
		.BRn(br_d),
		.BGACKn(bgack_d),
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
	// FC HOLD: the real m68kcpu ties the FC tri-state to the same enable as AS/UDS/LDS
	// (68k.v:2045/2235, :5683/5698/5713), so FC never floats while AS is asserted. FC_z = ASn
	// floated it at every cycle end; md_board.v:837-838 ORs that into FC0/FC1 combinationally
	// while md_board.v:784-786 still holds AS low for one MCLK2, ym6045.v:632-633/820 reads
	// FC1&FC0 as an interrupt acknowledge with no AS term, and ym7101.v:2395/2582 clears the
	// pending HINT/VINT. asn_d covers the boards AS-register lag so FC can only float once
	// the boards AS has actually gone high; the BG/BGACK terms reproduce the netlists own
	// tri-state states. Sim: 71 lost IRQs/frame -> 0; on a DMA frame 53 lost -> 0.
	reg asn_d = 1'b1;
	always @(posedge MCLK) asn_d <= ASn;
	assign FC_z = ASn & asn_d & (~BGn | ~bgack_d | fx_reset);
	assign BG = BGn;
	assign RESET_pull = ~oRESETn;
	assign HALT_pull = ~oHALTEDn;

endmodule
