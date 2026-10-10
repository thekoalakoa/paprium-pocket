// pocket: paprium_cram - one die of the Pocket's cellular PSRAM (cram0, CE0#) in asynchronous
// mode, for the CDDA ring (port A), the SFX echo line (port E), a spare stream-read port
// (port C, reserved, tied off) and the MCU window 0x09000000-0x093FFFFF (port B). xram
// stage 1 + echo line.
//
// Part (Analogue developer docs and the AS1C8M16PL datasheet Rev 1.0): AS1C8M16PL-70BIN, 16 MB =
// two 4M x 16 dies wired in parallel except CE0#/CE1#, 1.8 V, address/data multiplexed (A[21:16]
// on pins, A[15:0] on A/DQ, latched by ADV# rising), 70 ns. Analogue's two warnings are design
// rules here: CE1# is a constant 1 (die 1 is never selected, so both CEs can never be low), and
// die word 3FFFFFh is never accessed (its access sequence reaches the configuration registers):
// the engine replaces that one address with 3FFFFEh, and no port can generate it anyway.
//
// Die-0 word map:
//   0x000000-0x1FFFFF  port B window (MCU) and port C (reserved)
//   0x200000-0x201FFF  CDDA ring, 16 KB (paprium_cdda_buf_cram RING_BASE_W)
//   0x210000-0x213E7F  SFX echo line, 8,000 slots x 32 bit (port E, E_BASE_W): slot s is the
//                      word pair E_BASE_W + 2s (bits 15:0) and E_BASE_W + 2s + 1 (bits 31:16)
//   0x3FFFFF           never accessed
//
// Initialisation (every power-on reset; the CRAM keeps power across core loads and a previous
// core may have left it in deep power-down, partial-array refresh or burst mode):
//   wait N_PU clocks with CE# high (>= tPU 150 us), CE0# low N_CEL clocks (>= 10 us: leaves deep
//   power-down), CE# high N_PU clocks (>= 150 us re-initialisation), CRE write RCR = 0010h (full
//   array refresh, DPD off), CRE write BCR = 9D1Fh (the power-up default: asynchronous mode),
//   one array read ("reading the memory array is highly recommended" after a register access).
//   ~0.63 ms at 53.69 MHz. Requests that arrive meanwhile wait (A writes in the 1-entry register).
//
// Ports, fixed priority A-write > E-write > E-read > A-read > C-read > B:
//   A-write  ring landing writes (data_loader: a pulse, >= 24 clocks apart, no back-pressure),
//            held in one register; worst wait one operation (<= 11 clocks). A pulse that finds the
//            register full is counted in stat_aw_lost.
//   E        the SFX echo line (audio_sfx mix_bank): per 48 kHz sample one 32-bit slot write
//            (posted, one register, two halves) and one 32-bit slot read (pulse in, one done pulse
//            out with all 32 bits), so 4 operations per ~1,119 clocks. The read is asked for a
//            whole sample period (~1,040 clocks) before its data is used. A pulse that finds its
//            register still busy is counted in stat_e_lost. E ages too: once E has been pending
//            E_AGE clocks it goes ahead of an aged B half, so an oversubscribed bus (XCFG maximum,
//            B back to back) delays the NEORV32 rather than starving the echo; at the default
//            timing E is done long before E_AGE and the order above is all there is.
//   A-read   ring prefetch reads (pulse in, one outstanding, done pulse out).
//   C-read   reserved, same interface as A-read (tied off).
//   B        MCU window (level request, ack held until the request drops). The two halves of a
//            32-bit access are NOT atomic, so a ring write never waits behind a whole B access.
//            Request drop (buddy_s2, review finding 3): a request that drops while its operation is
//            in the engine, or between its two halves, is abandoned (`b_drop`): the operation ends
//            without an ack and its pending second half is never done. Before, a new request that
//            came up before the engine was idle again got the dropped one's ack, or its second half
//            on top of the dropped one's first (got {new hi, old lo}). NEORV32 1.4.8.1 drops a
//            request only after its 127-cycle bus timeout (+ <= 31 clocks in the gateway's CANCELED
//            state); B's own bound is ~2 x (B_AGE + 3 operations), so this is a guard, not a fix of a
//            path seen in the defaults.
//            A B half that has waited B_AGE clocks goes ahead of E, A-read and C (whose buffers
//            absorb one operation), so the NEORV32's 127-clock bus timeout cannot be reached however
//            busy the streams are: a 32-bit B access is bounded at ~2 x (B_AGE + 3 operations).
//
// Op timing (the facts probe's cycle plan, STA + datasheet-model checked). F = FSM edge, the
// pins follow one edge later (E0 = F1):
//   read : E0 CE#=0 ADV#=0 A[21:16] + A/DQ = address, UB#=LB#=0; E1 ADV#=1; E2 A/DQ released;
//          E3 OE#=0; the IOE samples at E(rd); E(rd+1) CE#/OE#/UB#/LB# high.
//          rd = 6 by default (111.7 ns: tAADV 70 and the OE# path both close; 5 leaves 0.7 ns
//          on the OE# path). rd + 3 clocks per 16-bit read.
//   write: E0 CE#=0 ADV#=0 address; E1 ADV#=1 WE#=0; E2 A/DQ = data; E(we) WE#=CE#=1;
//          E(we+1) A/DQ released, UB#/LB# high. we = 5 by default (tCW 93 >= 70, tWP 74.5 >= 45,
//          tDW 55.9 >= 20). we + 2 clocks per 16-bit write.
//   CE# is high for >= 2 clocks between operations (refresh opportunity: > 15 ns) and low for at
//   most ~200 ns per operation (tCEM 4 us), except the deliberate 19 us DPD exit at init.
// Both counts can be changed at run time through XCFG (0 = default; clamped to the structural
// minimums rd >= 4, we >= 3).
//
// Pin structure as in paprium_xram: fabric registers, IOE pin registers copied every clock with
// no enable and no reset, DQ captured every clock by the IOE input register. CLK is held low
// (asynchronous mode), WAIT is ignored.

module paprium_cram #(
	parameter [3:0]  RD_DEF = 4'd6,
	parameter [3:0]  WE_DEF = 4'd5,
	parameter        N_PU   = 16384,               // clocks, >= 150 us (8,054)
	parameter        N_CEL  = 1024,                // clocks, >= 10 us (537)
	parameter        B_AGE  = 16,                  // clocks a B half may wait behind E / A-read / C
	parameter [21:0] E_BASE_W = 22'h210000,        // port E slot 0 (bits 13:0 must be 0)
	parameter [7:0]  E_AGE  = 8'd255               // clocks E may wait before it goes ahead of aged B
)(
	input  wire        clk,                        // clk_sys_53_69
	input  wire        reset,                      // power-on only, not sys_reset

	input  wire  [3:0] cfg_rd,                     // 0 = RD_DEF
	input  wire  [3:0] cfg_we,                     // 0 = WE_DEF

	// port A: ring
	input  wire        a_wr,                       // pulse
	input  wire [21:0] a_waddr,                    // die word address
	input  wire [15:0] a_wdata,
	input  wire        a_rd,                       // pulse, only when no A read is outstanding
	input  wire [21:0] a_raddr,
	output reg         a_rd_done,                  // pulse, a_rdata valid
	output reg  [15:0] a_rdata,

	// port C: reserved stream reads (tie c_rd low)
	input  wire        c_rd,
	input  wire [20:0] c_raddr,                    // die word address in 0x000000-0x1FFFFF
	output reg         c_rd_done,
	output reg  [15:0] c_rdata,

	// port E: SFX echo line, 32-bit slots
	input  wire        e_wr,                       // pulse
	input  wire [12:0] e_wslot,
	input  wire [31:0] e_wdata,
	input  wire        e_rd,                       // pulse, only when no E read is outstanding
	input  wire [12:0] e_rslot,
	output reg         e_rd_done,                  // pulse, e_rdata valid
	output reg  [31:0] e_rdata,

	// port B: MCU window (byte address inside the 4 MB window)
	input  wire        b_req,
	input  wire [21:0] b_addr,
	input  wire  [3:0] b_sel,                      // store lanes (loads read the whole word)
	input  wire        b_wr,
	input  wire [31:0] b_wdata,
	output reg  [31:0] b_rdata,
	output reg         b_ack,

	// pins (cram0)
	output reg   [5:0] cram_a,                     // A[21:16]
	inout  wire [15:0] cram_dq,
	output wire        cram_clk,
	output reg         cram_adv_n,
	output reg         cram_cre,
	output reg         cram_ce0_n,
	output wire        cram_ce1_n,
	output reg         cram_oe_n,
	output reg         cram_we_n,
	output reg         cram_ub_n,
	output reg         cram_lb_n,

	output reg         ready,                      // init done
	output reg  [31:0] stat_ops,
	output reg  [15:0] stat_aw_lost,
	output reg  [15:0] stat_e_lost
);

	assign cram_clk   = 1'b0;
	assign cram_ce1_n = 1'b1;

	wire [3:0] rd = (cfg_rd == 4'd0) ? RD_DEF : (cfg_rd < 4'd4) ? 4'd4 : cfg_rd;
	wire [3:0] we = (cfg_we == 4'd0) ? WE_DEF : (cfg_we < 4'd3) ? 4'd3 : cfg_we;

	// ---- pin layer ----------------------------------------------------------------------------
	reg   [5:0] a_f    = 6'd0;
	reg  [15:0] dq_f   = 16'd0;
	reg         dqoe_f = 1'b0;
	reg         adv_f  = 1'b1;
	reg         cre_f  = 1'b0;
	reg         ce_f   = 1'b1;
	reg         oe_f   = 1'b1;
	reg         we_f   = 1'b1;
	reg         ub_f   = 1'b1;
	reg         lb_f   = 1'b1;

	reg  [15:0] dq_o;
	(* preserve *) reg [15:0] dq_oe;
	reg  [15:0] dq_in;

	genvar gi;
	generate for (gi = 0; gi < 16; gi = gi + 1) begin : g_dq
		assign cram_dq[gi] = dq_oe[gi] ? dq_o[gi] : 1'bz;
	end endgenerate

	always @(posedge clk) begin
		cram_a     <= a_f;
		dq_o       <= dq_f;
		dq_oe      <= {16{dqoe_f}};
		cram_adv_n <= adv_f;
		cram_cre   <= cre_f;
		cram_ce0_n <= ce_f;
		cram_oe_n  <= oe_f;
		cram_we_n  <= we_f;
		cram_ub_n  <= ub_f;
		cram_lb_n  <= lb_f;
		dq_in      <= cram_dq;
	end

	// ---- port holding registers ---------------------------------------------------------------
	reg         aw_pend = 1'b0, ar_pend = 1'b0, cr_pend = 1'b0;
	reg  [21:0] aw_addr, ar_addr;
	reg  [20:0] cr_addr;
	reg  [15:0] aw_data;

	// port E: one slot write and one slot read in flight, two halves each (bit 0 = even word)
	reg   [1:0] ew_pend = 2'b00, er_pend = 2'b00;
	reg  [12:0] ew_slot, er_slot;
	reg  [31:0] ew_data;
	wire        e_pend  = (ew_pend != 2'b00) | (er_pend != 2'b00);
	reg   [7:0] e_wait  = 8'd0;                    // clocks E has been pending
	wire        e_old   = e_wait >= E_AGE;

	reg         b_done = 1'b0;                     // acked, waiting for the request to drop
	reg         b_act  = 1'b0;                     // first half done, second pending
	reg         b_drop = 1'b0;                     // finding 3: the B access in flight lost its request
	// B reads always do both halves (NEORV32 1.4.8.1 leaves wb_sel_o stale on loads it cannot tell
	// from fetches, see paprium_xram); B writes do the halves whose lanes are set
	wire        b_h0   = ~b_wr | (b_sel[1:0] != 2'b00);
	wire        b_h1   = ~b_wr | (b_sel[3:2] != 2'b00);
	wire [21:0] b_w0   = {1'b0, b_addr[21:2], 1'b0};
	wire [21:0] b_w1   = {1'b0, b_addr[21:2], 1'b1};
	reg   [5:0] b_wait = 6'd0;                     // clocks the pending B half has waited
	wire        b_pend = b_req & ~b_done & ~b_ack;
	wire        b_old  = b_wait >= B_AGE[5:0];
	wire        b_live = b_act & ~b_drop;          // a second half that still belongs to the request

	// ---- engine -------------------------------------------------------------------------------
	localparam [3:0] S_INIT = 4'd0, S_IDLE = 4'd1, S_R1 = 4'd2, S_R2 = 4'd3, S_RW = 4'd4, S_RC = 4'd5,
	                 S_W1 = 4'd6, S_WW = 4'd7, S_WE = 4'd8;
	localparam [2:0] O_AW = 3'd0, O_AR = 3'd1, O_C = 3'd2, O_B = 3'd3, O_E = 3'd4;

	reg   [3:0] st = S_INIT;
	reg   [3:0] cnt;
	reg   [2:0] owner;
	reg         op_init;                           // an init operation (no client to answer)
	reg  [15:0] wbuf;
	reg         op_bhalf, op_blast;

	// init sequencer
	localparam [2:0] I_PU = 3'd0, I_CEL = 3'd1, I_PU2 = 3'd2, I_RCR = 3'd3, I_BCR = 3'd4, I_RD = 3'd5,
	                 I_DONE = 3'd6;
	reg   [2:0] ist = I_PU;
	reg  [14:0] icnt = 15'd0;

	task automatic launch(input [2:0] who, input wr, input cre, input [21:0] wa, input [15:0] wd,
	                      input [1:0] be, input bhalf, input blast);
		begin
			owner    <= who;
			op_bhalf <= bhalf;
			op_blast <= blast;
			wbuf     <= wd;
			ce_f     <= 1'b0;
			adv_f    <= 1'b0;
			cre_f    <= cre;
			a_f      <= (wa == 22'h3FFFFF) ? 6'h3F       : wa[21:16];
			dq_f     <= (wa == 22'h3FFFFF) ? 16'hFFFE    : wa[15:0];   // never word 3FFFFFh
			dqoe_f   <= 1'b1;
			oe_f     <= 1'b1;
			we_f     <= 1'b1;
			ub_f     <= wr ? ~be[1] : 1'b0;
			lb_f     <= wr ? ~be[0] : 1'b0;
			stat_ops <= stat_ops + 1'd1;
			st       <= wr ? S_W1 : S_R1;
		end
	endtask

	always @(posedge clk) begin
		a_rd_done <= 1'b0;
		c_rd_done <= 1'b0;
		e_rd_done <= 1'b0;

		if (a_wr) begin
			if (aw_pend & ~(st == S_IDLE)) stat_aw_lost <= stat_aw_lost + 1'd1;
			aw_pend <= 1'b1; aw_addr <= a_waddr; aw_data <= a_wdata;
		end
		if (a_rd) begin ar_pend <= 1'b1; ar_addr <= a_raddr; end
		if (c_rd) begin cr_pend <= 1'b1; cr_addr <= c_raddr; end
		if (e_wr) begin
			if (ew_pend != 2'b00) stat_e_lost <= stat_e_lost + 1'd1;
			ew_pend <= 2'b11; ew_slot <= e_wslot; ew_data <= e_wdata;
		end
		if (e_rd) begin
			if (er_pend != 2'b00) stat_e_lost <= stat_e_lost + 1'd1;
			er_pend <= 2'b11; er_slot <= e_rslot;
		end

		if (!b_req) begin
			b_done <= 1'b0;
			b_ack  <= 1'b0;
			if (st == S_IDLE) b_act <= 1'b0;         // an MCU reset between two halves: never do the second
			else if (b_act || (owner == O_B && !op_init && st != S_INIT)) b_drop <= 1'b1;   // finding 3
		end

		// B ageing: counts while a B half waits; cleared when a B operation starts
		if (!b_pend || (st == S_IDLE && !aw_pend && !(e_pend & (~b_old | e_old)) && (b_old || !(ar_pend | cr_pend)))) b_wait <= 6'd0;
		else if (!b_old) b_wait <= b_wait + 1'd1;

		// E ageing: counts while any E half is pending
		if (!e_pend) e_wait <= 8'd0;
		else if (!e_old) e_wait <= e_wait + 1'd1;

		if (reset) begin
			st       <= S_INIT;
			ist      <= I_PU;
			icnt     <= 15'd0;
			ready    <= 1'b0;
			op_init  <= 1'b0;
			a_f      <= 6'd0;
			dqoe_f   <= 1'b0;
			adv_f    <= 1'b1;
			cre_f    <= 1'b0;
			ce_f     <= 1'b1;
			oe_f     <= 1'b1;
			we_f     <= 1'b1;
			ub_f     <= 1'b1;
			lb_f     <= 1'b1;
			ar_pend  <= 1'b0;
			cr_pend  <= 1'b0;
			ew_pend  <= 2'b00;
			er_pend  <= 2'b00;
			aw_pend  <= a_wr;
			b_act    <= 1'b0;
			b_drop   <= 1'b0;
			b_done   <= 1'b0;
			b_ack    <= 1'b0;
			stat_ops <= 32'd0;
			stat_aw_lost <= 16'd0;
			stat_e_lost  <= 16'd0;
		end
		else case (st)

			S_INIT: begin
				icnt <= icnt + 1'd1;
				case (ist)
					I_PU, I_PU2: if (icnt == N_PU[14:0] - 1'd1) begin icnt <= 15'd0; ist <= ist + 1'd1; end
					I_CEL: begin
						ce_f <= 1'b0;                     // CE0# low, nothing else: leaves deep power-down
						if (icnt == N_CEL[14:0] - 1'd1) begin ce_f <= 1'b1; icnt <= 15'd0; ist <= I_PU2; end
					end
					// CRE writes: the register value is the address bus value (A[19:18] selects)
					I_RCR: begin op_init <= 1'b1; ist <= I_BCR;  launch(O_AW, 1'b1, 1'b1, 22'h000010, 16'h0010, 2'b11, 1'b0, 1'b0); end
					I_BCR: begin op_init <= 1'b1; ist <= I_RD;   launch(O_AW, 1'b1, 1'b1, 22'h089D1F, 16'h9D1F, 2'b11, 1'b0, 1'b0); end
					I_RD:  begin op_init <= 1'b1; ist <= I_DONE; launch(O_AR, 1'b0, 1'b0, 22'h000000, 16'h0000, 2'b11, 1'b0, 1'b0); end
					default: begin op_init <= 1'b0; ready <= 1'b1; st <= S_IDLE; end
				endcase
			end

			S_IDLE: begin
				op_init <= 1'b0;
				if (b_drop) begin b_drop <= 1'b0; b_act <= 1'b0; end   // finding 3: forget the dropped access
				if (aw_pend) begin
					aw_pend <= a_wr;                      // a pulse in this very clock stays pending
					launch(O_AW, 1'b1, 1'b0, aw_addr, aw_data, 2'b11, 1'b0, 1'b0);
				end
				else if ((ew_pend != 2'b00) & (~(b_pend & b_old) | e_old)) begin
					if (ew_pend[0]) begin
						ew_pend <= e_wr ? 2'b11 : {ew_pend[1], 1'b0};
						launch(O_E, 1'b1, 1'b0, {E_BASE_W[21:14], ew_slot, 1'b0}, ew_data[15:0],  2'b11, 1'b0, 1'b0);
					end
					else begin
						ew_pend <= e_wr ? 2'b11 : 2'b00;
						launch(O_E, 1'b1, 1'b0, {E_BASE_W[21:14], ew_slot, 1'b1}, ew_data[31:16], 2'b11, 1'b1, 1'b1);
					end
				end
				else if ((er_pend != 2'b00) & (~(b_pend & b_old) | e_old)) begin
					if (er_pend[0]) begin
						er_pend <= e_rd ? 2'b11 : {er_pend[1], 1'b0};
						launch(O_E, 1'b0, 1'b0, {E_BASE_W[21:14], er_slot, 1'b0}, 16'h0000, 2'b11, 1'b0, 1'b0);
					end
					else begin
						er_pend <= e_rd ? 2'b11 : 2'b00;
						launch(O_E, 1'b0, 1'b0, {E_BASE_W[21:14], er_slot, 1'b1}, 16'h0000, 2'b11, 1'b1, 1'b1);
					end
				end
				else if (ar_pend & ~(b_pend & b_old)) begin
					ar_pend <= a_rd;
					launch(O_AR, 1'b0, 1'b0, ar_addr, 16'h0000, 2'b11, 1'b0, 1'b0);
				end
				else if (cr_pend & ~(b_pend & b_old)) begin
					cr_pend <= c_rd;
					launch(O_C, 1'b0, 1'b0, {1'b0, cr_addr}, 16'h0000, 2'b11, 1'b0, 1'b0);
				end
				else if (b_pend) begin
					if (b_live)
						launch(O_B, b_wr, 1'b0, b_w1, b_wdata[31:16], b_sel[3:2], 1'b1, 1'b1);
					else if (b_h0)
						launch(O_B, b_wr, 1'b0, b_w0, b_wdata[15:0],  b_sel[1:0], 1'b0, ~b_h1);
					else
						launch(O_B, b_wr, 1'b0, b_w1, b_wdata[31:16], b_sel[3:2], 1'b1, 1'b1);
				end
			end

			// ---- read
			S_R1: begin adv_f <= 1'b1; st <= S_R2; end                 // pins E1: address latched
			S_R2: begin dqoe_f <= 1'b0; cnt <= rd - 4'd2; st <= S_RW; end   // pins E2: A/DQ released
			S_RW: begin                                                 // pins E3..: OE# low
				oe_f <= 1'b0;
				if (cnt != 4'd0) cnt <= cnt - 1'd1;
				else begin                                              // the IOE samples at this edge
					ce_f <= 1'b1; oe_f <= 1'b1; ub_f <= 1'b1; lb_f <= 1'b1;
					st   <= S_RC;
				end
			end
			S_RC: begin                                                 // CE# high (>= 2 clocks to the next op)
				st <= op_init ? S_INIT : S_IDLE;
				if (!op_init) case (owner)
					O_AR: begin a_rdata <= dq_in; a_rd_done <= 1'b1; end
					O_C:  begin c_rdata <= dq_in; c_rd_done <= 1'b1; end
					O_E:  begin
						if (op_bhalf) e_rdata[31:16] <= dq_in;
						else          e_rdata[15:0]  <= dq_in;
						if (op_blast) e_rd_done <= 1'b1;
					end
					O_B:  begin
						if (op_bhalf) b_rdata[31:16] <= dq_in;
						else          b_rdata[15:0]  <= dq_in;
						if (b_drop || !b_req) begin b_act <= 1'b0; b_drop <= 1'b0; end   // finding 3
						else if (op_blast) begin b_act <= 1'b0; b_ack <= 1'b1; b_done <= 1'b1; end
						else            b_act <= 1'b1;
					end
					default: ;
				endcase
			end

			// ---- write (CRE writes use the same cycle)
			S_W1: begin adv_f <= 1'b1; we_f <= 1'b0; cnt <= we - 4'd3; st <= S_WW; end  // pins E1
			S_WW: begin                                                 // pins E2..: data on A/DQ
				dq_f <= wbuf;
				if (cnt != 4'd0) cnt <= cnt - 1'd1;
				else st <= S_WE;
			end
			S_WE: begin
				if (!we_f) begin                                        // pins E(we): WE#, CE# high
					we_f <= 1'b1; ce_f <= 1'b1;
				end
				else begin                                              // pins E(we+1): release
					dqoe_f <= 1'b0; ub_f <= 1'b1; lb_f <= 1'b1; cre_f <= 1'b0;
					st <= op_init ? S_INIT : S_IDLE;
					if (!op_init && owner == O_B) begin
						if (b_drop || !b_req) begin b_act <= 1'b0; b_drop <= 1'b0; end   // finding 3
						else if (op_blast) begin b_act <= 1'b0; b_ack <= 1'b1; b_done <= 1'b1; end
						else            b_act <= 1'b1;
					end
				end
			end

			default: st <= S_IDLE;
		endcase
	end

endmodule
