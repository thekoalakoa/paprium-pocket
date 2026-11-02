// pocket: 0.3.0 new core - FPGAIO v1.0 (FPGAIO = the MCU's register block in the FPGA; the firmware's
// docs/MCU_INTERFACE.md v1.0 section 4); v1.1 adds slot 16, the VS counter (for the firmware's freeze telemetry,
// B Jam 2026-10-13); v1.2 adds slots 17-22, the cart FPGA decoder's base and monitors (the sprite-decoder step,
// B Jam 2026-10-15). Every v1.0 / v1.1 slot keeps its address and meaning.
// v1.3 (the synth step, MCU_INTERFACE.md v1.3 sections 4, 4.1, 4.2, 4.6, 4.10; from test build 4a on, the first
// 0.3.0 hardware test build of the sound cache): slot 14 STAMP_A, slot 23 FEAT, CAUSE bit 4 BLK (the synth's BUSY
// fell; set only with FEAT.SYNTH) with its MEI enable CTRL bit 6 BLKIE. Every v1.2 slot, bit and reset value keeps
// its meaning.
// Since test build S3c (a hardware test build of the MegaWire step): CAUSE.V is set on the Pocket too, by core_top's
// Console Reset (a 68000-only
// console Reset; its one-clock pulse comes in as post_v), and its level goes back out as cause_v: core_top keeps the
// 68000 in reset while it is pending, so the board's warm vector page is in RAMDP before the 68000's first fetch.
// Every other slot, bit and reset value keeps its meaning.
//
// Region 0x01 of the cart MCU, slot = addr[6:2] (32 slots; 0.2.6 decoded addr[5:2]). Every slot has registered
// read data and a registered ack held until the request drops (the pattern of XLINK, the MCU's register block for the
// Pocket's own memories and the CPU MATE link): an access takes two bus clocks,
// one more than 0.2.6's constant ack. A write takes effect once, in the access's first bus clock. The read data is
// 0 outside an FPGAIO access, so it can share one registered rv_di arm with the cart register file (region 0x0B).
//
//   slot  addr        name       read                                    write
//    0    0x01000000  CTRL       {16'0, CAUSE.B, LSTAT[6:0], ctrl[7:0]}  lane 0 -> ctrl[7:0]
//    1    0x01000004  (TIME_MS)  0xFFFFFFFF (retired: TIMER replaces)    ignored
//    2    0x01000008  SPTR       {11'0, live stream pointer}             sptr_wr out (the stream engine loads it)
//    3    0x0100000C  VOL_SFX    0xFFFFFFFF                              paprium_cart (sfx_volume, interim)
//    4    0x01000010  VOL_BGM    0xFFFFFFFF                              ignored (no RTL consumer)
//    5    0x01000014  DIAG       0xFFFFFFFF                              ignored
//    6    0x01000018  IRQCLR     0xFFFFFFFF                              lane 0 bit 0 = 1: clear CAUSE.B (legacy)
//    7    0x0100001C  STREAM_GO  stream_status in (the register file)    decoded by the register file
//    8    0x01000020  CAUSE      {27'0, BLK, V, S, A, B} (v1.3: BLK)     lane 0: write 1 to clear bits 4:0
//    9    0x01000024  MSIP       {31'0, MSIP}                            lane 0: MSIP := bit 0
//   10    0x01000028  TIMER      cycle count at the MCU clock            ignored
//   11    0x0100002C  TCMP       compare                                 per byte lane
//   12    0x01000030  TCTRL      {31'0, TEN}                             lane 0: TEN := bit 0
//   13    0x01000034  STAMP_B    TIMER when CAUSE.B was last set         ignored
//   14    0x01000038  STAMP_A    TIMER when CAUSE.A was last set         ignored                    (v1.3)
//   15    0x0100003C  WLOCK      {11'0, mask}                            bits 20:0, write 1 to set (lanes 0-2)
//   16    0x01000040  VSCNT      {16'0, VDP vertical syncs since reset}  ignored                    (v1.1)
//   17    0x01000044  DEC_BASE   {11'0, base[20:1], 0}                   the next START's base      (v1.2)
//   18    0x01000048  DEC_STAT   the decoder's state and flags           1 clears flag bits 16-21   (v1.2)
//   19    0x0100004C  DEC_WORDS  words written since the last START      ignored                    (v1.2)
//   20    0x01000050  DEC_TIME   {valid, 7'0, START -> GO cycles}        ignored                    (v1.2)
//   21    0x01000054  DEC_MARGIN signed min (first window read - GO)     any: 0x7FFFFFFF            (v1.2)
//   22    0x01000058  DEC_LATECNT {16'0, window words read too early}    any: clear                 (v1.2)
//   23    0x0100005C  FEAT       the FEAT parameter: what this bitstream carries (never 0xFFFFFFFF)  ignored  (v1.3)
//  24-31  0x01000060+ reserved   0xFFFFFFFF                              ignored
// Slots 17-22 live in paprium_hwdec (its header has the bits); here they are only decoded: a store's first bus clock
// goes out as dec_wr with the slot, and a read takes dec_rdata (paprium_hwdec's read mux for dec_rslot).
//
// CTRL: bit 0 HOLD (the 68000 held), 1 exit (not connected), 2 sdram_en (0.2.6's window; the new core moves the
// window to $1FE8), 3 RSTSEEN, 4 MENU_MUTE_EN (the Pocket-menu music mute), 5 OPT_AT_RESET_EN (the "options apply
// at reset" latch, dormant), 6 BLKIE (v1.3), 7 a plain bit.
// CAUSE (MEI sources, level latches): B = a 68000 write to $1FEA, A = a 68000 write to $1FEC (both through
// ramdp_io's filtered write pulse), S = a change of XLINK's posts_s[0] (one event per buddy post), V = a console reset
// (since test build S3c: core_top's Console Reset; MiSTer's board its own), BLK (v1.3) = post_blk, the synth's
// STATUS.BUSY 1 -> 0 edge, taken only when FEAT bit 2 (SYNTH) is set (test build 4a: no synth, post_blk tied 0, so
// BLK never sets). A set and a clear of the same bit in one clock: the set wins.
// irq_ext = B | A | S | V | (BLK & CTRL.BLKIE).
// STAMP_A (v1.3) = TIMER at the clock CAUSE.A was last set, exactly as STAMP_B for CAUSE.B (the same set pulse).
// Timer: TIMER +1 every clock, wrapping; irq_tmr = TEN & ~(TIMER - TCMP)[31], registered (a level while TIMER has
// reached or passed TCMP, within half the wrap; a compare written in the past fires at once; it falls within two
// clocks of a TCMP or TCTRL write).
// VSCNT (v1.1): a 16-bit count of the VDP's vertical syncs, for the TEST freeze telemetry (a VS count that stops tells
// a dead VDP from a dead 68000, which stops only the frame post). vs_tog comes from core_top's paprium_vs_tap, already
// synchronised into this clock: it changes once at the start of every VS pulse (a level, so no event is lost to the
// crossing), and every change counts one. The count wraps at 65,536 frames (18.2 min NTSC); the firmware extends it.
//
// Every reset (md_srst, registered once as 0.2.6's md_srst_st): CTRL = 0x09 (HOLD, RSTSEEN), CAUSE, MSIP, TIMER,
// TCMP, TEN, STAMP_B, STAMP_A, WLOCK and VSCNT = 0. At configuration CTRL = 0x01 and the rest 0. FEAT is a constant.
// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)

module fpgio #(
	parameter [31:0] FEAT = 32'd0   // v1.3 slot 23 (MCU_INTERFACE.md 4.10): core_top's PAPRIUM_FEAT through cartridge / paprium_cart
)(

	input  McuBus mcu,
	input  md_srst,
	input  [6:0]link_status,//pocket: xram step 2 - XLINK LSTAT[6:0], read back in ctrl[14:8] (0 without it)

	// CAUSE sources (mcu.clk)
	input  post_b,           // a 68000 write to $1FEA: ramdp_io's filtered write pulse, cpu.addr[12:1] == 0xFF5
	input  post_a,           // a 68000 write to $1FEC: the same pulse, cpu.addr[12:1] == 0xFF6
	input  post_s,           // XLINK posts_s[0]: every change is one buddy post
	input  post_v,           // console reset (EXTI 13): since test build S3c, core_top's Console Reset (a one-clock pulse)
	input  post_blk,         // v1.3 CAUSE.BLK: the synth's STATUS.BUSY fell (a one-clock pulse); 0 without the synth
	input  vs_tog,           // v1.1 VSCNT: changes once per VDP vertical sync (core_top paprium_vs_tap, synchronised)

	// read-backs of state that lives beside the stream engine
	input  [20:0]sptr,       // slot 2: the live stream pointer
	input  [31:0]stream_status,// slot 7: {valid, 10'0, remaining[20:0]} from the register file (0 without it)
	input  [31:0]dec_rdata,  // v1.2 slots 17-22: paprium_hwdec's read data for dec_rslot

	output reg [31:0]mcu_dati,
	output reg mcu_ack,
	output sptr_wr,          // slot 2 written (first bus clock only): the stream engine loads mcu.dato[20:0]
	output dec_wr,           // v1.2: slot 17-22 written (first bus clock only), slot 17 + dec_wslot, data mcu.dato
	output [2:0]dec_wslot,
	output [2:0]dec_rslot,   // v1.2: slot - 17 of the access on the bus (paprium_hwdec's read mux)

	output md_rst,
	output exit,
	output sdram_en,
	output menu_mute_en,
	output opt_at_reset_en,

	output irq_ext,          // -> mext_irq_i
	output cause_v,          // CAUSE.V pending (this clock): core_top holds the 68000 in reset meanwhile
	output reg irq_tmr,      // -> mtime_irq_i
	output irq_sw,           // -> msw_irq_i
	output [20:0]wlock,      // -> mcu_core (test build 4, the MCU fast path: mcu_tcm_wram): bit k locks WRAM KB 27 + k

	output       debug_ctrl_write,
	output [7:0]debug_ctrl_value
);

//************************************************************************************* bus

	wire [4:0]slot		= mcu.addr[6:2];
	wire hit				= mcu.ce & mcu.map.fpgio;
	wire first			= hit & ~mcu_ack;                // the access's first bus clock
	wire [3:0]we		= first ? mcu.we : 4'b0000;       // mcu.we carries ce, the store and the byte selects

	wire w_ctrl			= (slot == 5'd0)  & we[0];
	wire w_irqclr		= (slot == 5'd6)  & we[0];
	wire w_cause		= (slot == 5'd8)  & we[0];
	wire w_msip			= (slot == 5'd9)  & we[0];
	wire w_tcmp			= (slot == 5'd11);
	wire w_tctrl		= (slot == 5'd12) & we[0];
	wire w_wlock		= (slot == 5'd15);

	assign sptr_wr				= (slot == 5'd2) & (we != 4'b0000);
	wire [4:0]dslot			= slot - 5'd17;
	assign dec_wr				= (slot >= 5'd17) & (slot <= 5'd22) & (we != 4'b0000);
	assign dec_wslot			= dslot[2:0];
	assign dec_rslot			= dslot[2:0];
	assign debug_ctrl_write	= w_ctrl;
	assign debug_ctrl_value	= mcu.dato[7:0];

//************************************************************************************* registers

	reg [7:0]ctrl;
	reg md_srst_st;
	reg [4:0]cause;     // {BLK, V, S, A, B} (v1.3: BLK)
	reg s_q;
	reg msip;
	reg [31:0]timer;
	reg [31:0]tcmp;
	reg ten;
	reg [31:0]stamp_b;
	reg [31:0]stamp_a;  // v1.3
	reg [20:0]wl;
	reg vs_q;
	reg [15:0]vscnt;

	initial begin       // the configuration values
		ctrl			= 8'h01;
		md_srst_st	= 1'b0;
		cause			= 5'd0;
		s_q			= 1'b0;
		msip			= 1'b0;
		timer			= 32'd0;
		tcmp			= 32'd0;
		ten			= 1'b0;
		stamp_b		= 32'd0;
		stamp_a		= 32'd0;
		wl				= 21'd0;
		vs_q			= 1'b0;
		vscnt			= 16'd0;
		irq_tmr		= 1'b0;
		mcu_ack		= 1'b0;
		mcu_dati		= 32'd0;
	end

	assign md_rst				= ctrl[0];
	assign exit					= ctrl[1];
	assign sdram_en			= ctrl[2];
	assign menu_mute_en		= ctrl[4];
	assign opt_at_reset_en	= ctrl[5];
	assign irq_ext				= (|cause[3:0]) | (cause[4] & ctrl[6]);   // v1.3: BLK only with CTRL.BLKIE
	assign irq_sw				= msip;
	assign cause_v				= cause[3];   // since test build S3c
	assign wlock				= wl;

	wire [4:0]c_set	= {post_blk & FEAT[2], post_v, post_s ^ s_q, post_a, post_b};   // v1.3: BLK needs FEAT.SYNTH
	wire [4:0]c_clr	= (w_cause ? mcu.dato[4:0] : 5'd0) | {4'd0, w_irqclr & mcu.dato[0]};
	wire signed [31:0]tdiff	= timer - tcmp;          // >= 0: TIMER has reached or passed TCMP (within half the wrap)

	always @(posedge mcu.clk)
	begin

		md_srst_st		<= md_srst;
		s_q				<= post_s;                     // follows through a reset: no event leaks out of one
		vs_q				<= vs_tog;                     // the same: a VS during the reset is not counted after it

		if(md_srst_st)
		begin
			ctrl			<= 8'h09;
			cause			<= 5'd0;
			msip			<= 1'b0;
			timer			<= 32'd0;
			tcmp			<= 32'd0;
			ten			<= 1'b0;
			stamp_b		<= 32'd0;
			stamp_a		<= 32'd0;   // v1.3
			wl				<= 21'd0;
			vscnt			<= 16'd0;
			irq_tmr		<= 1'b0;
		end
			else
		begin
			if(w_ctrl) ctrl <= mcu.dato[7:0];

			cause			<= (cause & ~c_clr) | c_set;    // the set wins
			if(post_b) stamp_b <= timer;
			if(post_a) stamp_a <= timer;                // v1.3: the same pulse that sets CAUSE.A

			if(w_msip) msip <= mcu.dato[0];

			timer			<= timer + 32'd1;
			if(w_tcmp & we[0]) tcmp[7:0]   <= mcu.dato[7:0];
			if(w_tcmp & we[1]) tcmp[15:8]  <= mcu.dato[15:8];
			if(w_tcmp & we[2]) tcmp[23:16] <= mcu.dato[23:16];
			if(w_tcmp & we[3]) tcmp[31:24] <= mcu.dato[31:24];
			if(w_tctrl) ten <= mcu.dato[0];
			irq_tmr		<= ten & (tdiff >= 32'sd0);

			if(w_wlock) wl <= wl | (mcu.dato[20:0] & {{5{we[2]}}, {8{we[1]}}, {8{we[0]}}});

			if(vs_tog ^ vs_q) vscnt <= vscnt + 16'd1;   // v1.1: one per VDP vertical sync, wrapping
		end

	end

//************************************************************************************* read data and ack

	always @(posedge mcu.clk)
	begin

		if(!hit)
		begin
			mcu_ack		<= 1'b0;
			mcu_dati		<= 32'd0;
		end
			else
		if(!mcu_ack)
		begin
			mcu_ack		<= 1'b1;
			case(slot)
				5'd0:		mcu_dati <= {16'd0, cause[0], link_status, ctrl};
				5'd2:		mcu_dati <= {11'd0, sptr};
				5'd7:		mcu_dati <= stream_status;
				5'd8:		mcu_dati <= {27'd0, cause};   // v1.3: bit 4 BLK
				5'd9:		mcu_dati <= {31'd0, msip};
				5'd10:	mcu_dati <= timer;
				5'd11:	mcu_dati <= tcmp;
				5'd12:	mcu_dati <= {31'd0, ten};
				5'd13:	mcu_dati <= stamp_b;
				5'd14:	mcu_dati <= stamp_a;         // v1.3
				5'd15:	mcu_dati <= {11'd0, wl};
				5'd16:	mcu_dati <= {16'd0, vscnt};  // v1.1
				5'd17, 5'd18, 5'd19, 5'd20, 5'd21, 5'd22:
						mcu_dati <= dec_rdata;       // v1.2: paprium_hwdec
				5'd23:	mcu_dati <= FEAT;            // v1.3
				default:	mcu_dati <= 32'hFFFF_FFFF;   // 1 (retired), 3, 4, 5, 6, 24-31 (reserved)
			endcase
		end

	end
//*************************************************************************************
endmodule
