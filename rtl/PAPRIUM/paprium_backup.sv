// ---------------------------------------------------------------------------
// Paprium battery-backup (SRAM save) RAM.
//
// Paprium's save is the MCU-managed backup RAM (4 KB). On real hardware the
// EverDrive/ASIC persists it; here we back it with an on-chip true-dual-port
// RAM whose second port is the MiSTer cartridge save interface, so the HPS
// load/save (.sav) path persists it like any normal Mega Drive SRAM.
//
//   Port A : MCU (mcu.map.bram), 32-bit, serviced as two 16-bit accesses with
//            read-modify-write so byte-granular MCU writes are preserved.
//   Port B : HPS save interface (save_addr/save_di/save_do/save_wr), 16-bit.
//
// The RAM uses FULL-word writes on both ports in a single process so Quartus
// infers it into M10K block RAM (byte-enabled partial writes do not infer and
// blow up into thousands of registers - hence the read-modify-write here).
//
// 4 KB = 2048 x 16. The MCU 32-bit word index is mcu.addr[11:2]; the save side
// uses save_addr[10:0]. bram_change pulses on an MCU write to drive autosave.
// ---------------------------------------------------------------------------

module paprium_backup
(
	input         clk,
	input         reset,

	input  McuBus mcu,
	output reg [31:0] mcu_dati,
	output reg        mcu_ack,
	output reg        bram_change,

	// HPS cartridge save interface (16-bit)
	input      [14:0] save_addr,
	input      [15:0] save_di,
	output     [15:0] save_do,
	input             save_wr
);

	localparam AW = 11;   // 2048 x 16 = 4 KB

	// ---- True dual-port RAM via the core's proven dpram_dif (infers M10K) ----
	// Port A = MCU (16-bit), Port B = HPS save (16-bit). Full-word writes; byte
	// granularity is handled by the read-modify-write FSM below.
	reg  [AW-1:0] a_addr;   // combinational (driven below)
	reg  [15:0]   a_din;    // combinational
	reg           a_we;     // combinational
	wire [15:0]   a_q;
	wire [15:0]   b_q;

	dpram_dif #(AW,16,AW,16) ram
	(
		.clock(clk),
		.address_a(a_addr),
		.data_a(a_din),
		.wren_a(a_we),
		.q_a(a_q),

		.address_b(save_addr[AW-1:0]),
		.data_b(save_di),
		.wren_b(save_wr),
		.q_b(b_q)
	);
	assign save_do = b_q;

	// ---- MCU 32-bit access FSM (read-modify-write per 16-bit half) ----
	wire [AW-1:0] a0 = {mcu.addr[11:2], 1'b0};
	wire [AW-1:0] a1 = {mcu.addr[11:2], 1'b1};

	localparam IDLE=0, RD0=1, WR0=2, RD1=3, WR1=4, ACK=5, DONE=6;

	reg [2:0]  state;
	reg [31:0] wdata;
	reg [3:0]  wen;

	// Combinational port-A control (1-cycle RAM read latency).
	always @(*) begin
		a_addr = a0;
		a_din  = 16'd0;
		a_we   = 1'b0;
		case(state)
			RD0: begin a_addr = a0; end
			WR0: begin a_addr = a0;
			           a_din  = {wen[1] ? wdata[15:8]  : a_q[15:8], wen[0] ? wdata[7:0]   : a_q[7:0]};
			           a_we   = |wen[1:0]; end
			RD1: begin a_addr = a1; end
			WR1: begin a_addr = a1;
			           a_din  = {wen[3] ? wdata[31:24] : a_q[15:8], wen[2] ? wdata[23:16] : a_q[7:0]};
			           a_we   = |wen[3:2]; end
			default: ;
		endcase
	end

	always @(posedge clk) begin
		bram_change <= 0;

		if(reset) begin
			state   <= IDLE;
			mcu_ack <= 0;
		end
		else case(state)
			IDLE: begin
				mcu_ack <= 0;
				if(mcu.ce && mcu.map.bram) begin
					wdata <= mcu.dato;
					wen   <= mcu.we;
					state <= RD0;
				end
			end
			RD0: state <= WR0;                          // a_q <- mem[a0]
			WR0: begin
				mcu_dati[15:0] <= a_q;                  // read result (pre-write)
				if(|wen[1:0]) bram_change <= 1;
				state <= RD1;
			end
			RD1: state <= WR1;                          // a_q <- mem[a1]
			WR1: begin
				mcu_dati[31:16] <= a_q;
				if(|wen[3:2]) bram_change <= 1;
				state <= ACK;
			end
			ACK: begin
				mcu_ack <= 1;
				state   <= DONE;
			end
			DONE: if(!mcu.ce) begin
				mcu_ack <= 0;
				state   <= IDLE;
			end
		endcase
	end

endmodule
