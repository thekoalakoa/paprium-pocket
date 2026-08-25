// ---------------------------------------------------------------------------
// Paprium MD+ adapter  (option A: RTL bridge + EverDrive-FIFO stub)
// ---------------------------------------------------------------------------
// Paprium's MCU drives BGM through TWO MCU-side regions (firmware unchanged):
//
//  1. mcu.map.mdp_ctrl  (0x7000000): the MD+ register block. The firmware's
//     `Mdp` struct {id[2], overlay, resp, cmd} sits at ADDR_MDP+0x3F7F6 and is
//     a 1:1 match for the core's md_plus.sv register map. We decode the MCU's
//     writes to the command port into the SAME mdp_* request signals md_plus.sv
//     produces (muxed by paprium_active in MegaDrive.sv), and answer the id /
//     overlay / result / command reads. We return the firmware-EXPECTED ids
//     (0x5241,0x5445) - md_plus.sv reports 0x4241,0x5445 for the 68k path.
//
//  2. mcu.map.mdp_fifo  (0x7800000): the EverDrive MCU FIFO. mdp_init() flushes
//     it then issues CMD_ROM_PATH(0x31) + CMD_CD_MOUNT(0x41), each followed by
//     CMD_STATUS2(0x40), expecting a status_key 0x5A and status 0. On MiSTer
//     there is no EverDrive; without a responder these poll-loops HANG the MCU
//     in init and the 68k is never released. This stub answers just enough:
//     a 1-char dummy ROM/CUE path and an OK status, so mdp_init() reaches
//     mdp_on=1. MiSTer's HPS owns real track discovery via the mdp_track_request
//     path, so the dummy path/mount is never actually used for streaming.
//
// EdFifo layout (32-bit ports): data @ +0, status @ +4, status bit7 = cpu_rxf
// (1 = fifo empty). ed_fifo_flush drains while !cpu_rxf; ed_fifo_rd waits while
// cpu_rxf then reads. ed_cmd_tx sends a 4-byte preamble 0x2B,0xD4,cmd,~cmd.
// ---------------------------------------------------------------------------

module paprium_mdp_adapter
(
	input             clk,
	input             reset,

	input      McuBus mcu,
	output reg [31:0] mcu_dati,        // data for mdp_ctrl | mdp_fifo reads

	// status feedback from the core's CDDA player
	input             mdp_playing,
	input       [7:0] mdp_current_track,

	// command outputs (mirror md_plus.sv; mux with it on paprium_active)
	output reg        mdp_track_request,
	output reg  [7:0] mdp_track_num,
	output reg        mdp_track_loop,
	output reg        mdp_stop_request,
	output reg  [7:0] mdp_fade_sectors,
	output reg        mdp_resume_request,
	output reg  [7:0] mdp_volume,
	output reg        mdp_volume_request,
	output reg        mdp_active
);
	// ---- MD+ register block word addresses (within mdp_ctrl) ----
	localparam [23:1] A_ID0 = 23'h1FBFB; // byte 0x3F7F6
	localparam [23:1] A_ID1 = 23'h1FBFC; // byte 0x3F7F8
	localparam [23:1] A_CTL = 23'h1FBFD; // byte 0x3F7FA  overlay
	localparam [23:1] A_RES = 23'h1FBFE; // byte 0x3F7FC  result
	localparam [23:1] A_CMD = 23'h1FBFF; // byte 0x3F7FE  command

	localparam [15:0] OVL_MAGIC = 16'hCD54;
	localparam [15:0] MDP_ID0   = 16'h5241; // firmware-expected ("RA")
	localparam [15:0] MDP_ID1   = 16'h5445; // ("TE")

	wire [23:1] waddr = mcu.addr[23:1];
	// 16-bit value lives in the high half for 2-mod-4 byte addresses (addr[1]=1).
	wire [15:0] wval  = mcu.addr[1] ? mcu.dato[31:16] : mcu.dato[15:0];

	reg        overlay_open;
	reg [15:0] last_cmd;

	// edge-detected MD+ control write
	wire ctl_wr = mcu.ce & (mcu.we != 0) & mcu.map.mdp_ctrl;
	reg  ctl_wr_d;

	// ===================== MD+ register bridge =====================
	always @(posedge clk) begin
		if (reset) begin
			overlay_open       <= 0;
			last_cmd           <= 0;
			ctl_wr_d           <= 0;
			mdp_track_request  <= 0;
			mdp_track_num      <= 0;
			mdp_track_loop     <= 0;
			mdp_stop_request   <= 0;
			mdp_fade_sectors   <= 0;
			mdp_resume_request <= 0;
			mdp_volume         <= 8'hFF;
			mdp_volume_request <= 0;
			mdp_active         <= 0;
		end
		else begin
			mdp_track_request  <= 0;
			mdp_stop_request   <= 0;
			mdp_resume_request <= 0;
			mdp_volume_request <= 0;

			ctl_wr_d <= ctl_wr;
			if (ctl_wr & ~ctl_wr_d) begin
				case (waddr)
					A_CTL: overlay_open <= (wval == OVL_MAGIC);
					A_CMD: if (overlay_open) begin
						last_cmd <= wval;
						case (wval[15:8])
							8'h11: begin mdp_track_num <= wval[7:0]; mdp_track_loop <= 0; mdp_track_request <= 1; end
							8'h12: begin mdp_track_num <= wval[7:0]; mdp_track_loop <= 1; mdp_track_request <= 1; end
							8'h13: begin mdp_fade_sectors <= wval[7:0]; mdp_stop_request <= 1; end
							8'h14: mdp_resume_request <= 1;
							8'h15: begin mdp_volume <= wval[7:0]; mdp_volume_request <= 1; end
							default: ;
						endcase
					end
					default: ;
				endcase
			end
			mdp_active <= overlay_open;
		end
	end

	// MD+ register reads (replicated into both 16-bit halves; NEORV32 takes its
	// half by address alignment).
	reg [15:0] mdp_rd16;
	always @(*) begin
		case (waddr)
			A_ID0: mdp_rd16 = MDP_ID0;
			A_ID1: mdp_rd16 = MDP_ID1;
			A_CTL: mdp_rd16 = overlay_open ? OVL_MAGIC : 16'h0000;
			A_RES: mdp_rd16 = {mdp_current_track, 7'b0, mdp_playing};
			A_CMD: mdp_rd16 = last_cmd;          // != 0xFFFF -> mdp_cmd() poll exits
			default: mdp_rd16 = 16'h0000;
		endcase
	end

	// ===================== EverDrive FIFO stub =====================
	localparam [7:0] CMD_ROM_PATH = 8'h31;
	localparam [7:0] CMD_CD_MOUNT = 8'h41;
	localparam [7:0] CMD_STATUS2  = 8'h40;

	reg  [7:0] rsp [0:7];
	reg  [3:0] rsp_len, rsp_pos;
	wire       fifo_empty = (rsp_pos >= rsp_len);

	// preamble parser (0x2B, 0xD4, cmd, ~cmd)
	reg  [1:0] pre_state;
	reg  [7:0] pre_cmd;

	wire fifo_data = mcu.map.mdp_fifo & ~mcu.addr[2];     // EDFIFO->data @ +0
	wire fifo_wr   = fifo_data & mcu.ce & (mcu.we != 0);
	wire fifo_rd   = fifo_data & mcu.ce & mcu.oe;
	reg  fifo_wr_d, fifo_rd_d;
	wire [7:0] wr_byte = mcu.dato[7:0];

	integer i;
	always @(posedge clk) begin
		if (reset) begin
			rsp_len <= 0; rsp_pos <= 0;
			pre_state <= 0; pre_cmd <= 0;
			fifo_wr_d <= 0; fifo_rd_d <= 0;
			for (i=0;i<8;i=i+1) rsp[i] <= 0;
		end
		else begin
			fifo_wr_d <= fifo_wr;
			fifo_rd_d <= fifo_rd;

			// write transaction (rising edge): feed the preamble parser
			if (fifo_wr & ~fifo_wr_d) begin
				case (pre_state)
					2'd0: if (wr_byte == 8'h2B) pre_state <= 2'd1;
					2'd1: pre_state <= (wr_byte == 8'hD4) ? 2'd2 : ((wr_byte == 8'h2B) ? 2'd1 : 2'd0);
					2'd2: begin pre_cmd <= wr_byte; pre_state <= 2'd3; end
					2'd3: begin
						pre_state <= 2'd0;             // 4th byte = ~cmd, act now
						rsp_pos   <= 0;
						case (pre_cmd)
							CMD_ROM_PATH: begin            // 1-char dummy path: len=1,"X"
								rsp[0] <= 8'h00; rsp[1] <= 8'h01; rsp[2] <= 8'h58;
								rsp_len <= 4'd3;
							end
							CMD_STATUS2: begin             // {key=5A, pid=05, did=00, status=00}
								rsp[0] <= 8'h5A; rsp[1] <= 8'h05; rsp[2] <= 8'h00; rsp[3] <= 8'h00;
								rsp_len <= 4'd4;
							end
							default: rsp_len <= 0;         // CD_MOUNT etc: nothing to return
						endcase
					end
				endcase
			end

			// read transaction (falling edge): pop one byte AFTER the MCU latched it
			if (fifo_rd_d & ~fifo_rd & ~fifo_empty)
				rsp_pos <= rsp_pos + 4'd1;
		end
	end

	// ===================== read data mux =====================
	// EDFIFO status: bit7 = cpu_rxf (1 = empty), bit6 = arm_rxf (don't care = 1).
	wire [7:0] fifo_status = {fifo_empty, 1'b1, 6'b0};

	always @(*) begin
		if (mcu.map.mdp_fifo)
			mcu_dati = mcu.addr[2] ? {24'd0, fifo_status}    // status @ +4
			                       : {24'd0, rsp[rsp_pos]};  // data   @ +0
		else
			mcu_dati = {mdp_rd16, mdp_rd16};                 // mdp_ctrl (both halves)
	end

endmodule
