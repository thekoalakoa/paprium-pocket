// pocket: 0.3.0, the sprite-decoder step - port 2 has two clients: the MCU (its flash and workspace views, as before)
// and paprium_hwdec, the cart FPGA's sprite decoder (ROM-image reads, workspace writes). One 16-bit access at a time,
// granted only while no access is on the port (mem_ack == mem_req), so mem_addr / mem_din / mem_wrl / mem_wrh / mem_req
// keep the SDC P2 / P2r
// premise: they move only on the clk_sys edge that toggles mem_req, or drop the strobes after the ack has been seen.
// The decoder's next access waits in a stage register (taken from paprium_hwdec when the stage is empty, never on the
// mem_ack path). When both wait, the decoder takes up to DEC_RUN accesses in a row and the MCU the next one, so the
// MCU waits for at most DEC_RUN decoder accesses before each of its halves; with one client waiting it gets every
// access. With the decoder idle the MCU's accesses run clock for clock as before (state 0 launches its first half on
// the clock it sees the request; half 1 launches on the clock half 0's ack is seen). Test build 4 (the 0.3.0 hardware
// test build of the MCU fast path): an access runs only the halves its byte lanes touch (one or two; see hi_too below).
// sdram.sv is unchanged: its DMA hold and boost2 apply to port 2 as a whole, so neither client can delay a VDP DMA cart
// read.
// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)
module paprium_mcu_mem
#(parameter [1:0] DEC_RUN = 2'd3)
(
	input             clk,
	input             reset,
	input             boot,      // Fafrium: the boot stub's view of the firmware file is open (power-on until fw_done)
	input      McuBus mcu,

	output reg        mcu_ack,
	output     [31:0] mcu_dati,

	output reg [24:1] mem_addr,
	output reg [15:0] mem_din,
	input      [15:0] mem_dout,
	// 0.3.0 new core, the reset-domain fixes (found in their review): power-up values. The reset no longer writes these
	// three (see the reset branch), so without an initial value they had none at all: X for ever in a 4-state simulator
	// (an Icarus bench with a port-2 model whose ack powers up 0 never gets its first access acknowledged), and only
	// Quartus's default power-up level in the fabric. 0 is what 0.2.6's reset gave them and what sdram.sv's ack2 (no
	// initial value) powers up to by default
	output reg        mem_wrl = 1'b0,
	output reg        mem_wrh = 1'b0,
	output reg        mem_req = 1'b0,
	input             mem_ack,

	// pocket: sprite-decoder step - the second client (paprium_hwdec)
	input             dec_valid,       // an access is offered (dec_* below)
	input             dec_we,
	input       [1:0] dec_lanes,       // {wrh, wrl} of a write
	input      [24:1] dec_addr,
	input      [15:0] dec_wdata,
	output            dec_take,        // the offered access goes into the stage this clock
	input             dec_flush,       // drop the staged access (and take none)
	output reg        dec_rd_done = 1'b0,   // one clock: a decoder read finished, dec_rdata holds its word
	output reg [15:0] dec_rdata,
	output reg        dec_wr_done = 1'b0,   // one clock: a decoder write finished
	output            dec_busy         // a decoder access is staged or on the port
);

	localparam [24:1] WORKSPACE_BASE = 24'h400000;
	localparam [24:1] BACKUP_BASE    = 24'h500000;

	reg [2:0] state;
	reg [3:0] byte_en;
	// pocket: test build 4 (the half-skip, on the sprite-decoder step's two-client port) - an MCU access runs only the
	// 16-bit halves its byte lanes touch. NEORV32 1.4.8.1 drives the byte enables by size for loads as for stores
	// (neorv32_cpu_bus byte_enable); mcu_core gives an instruction fetch all four (mcu.sel); no lane at all (never seen)
	// is taken as the whole word. A byte / halfword access takes one port-2 access instead of two (17.8 -> 11.0 cycles
	// with the IROM / WRAM tightly coupled, 15.1 without the half-skip; measured on our MCU bench for test build 4,
	// decoder idle). What the CPU reads is unchanged: it takes only its own lanes from the word (the other half of
	// mcu_dati keeps the previous access's data); what is written is unchanged: the skipped half was a port-2 read with
	// both byte strobes low. The arbiter is the sprite-decoder step's: a half-1-only access asks for the port from state 0
	// as a half 0 did (mcu_h1 with mcu_new), or waits in state 5; a half-0-only access ends in state 1 (no state-5 wait,
	// so the decoder can take the port at once). mem_addr / mem_din / mem_wrl / mem_wrh still move only on a launch, or
	// drop after done (P2 / P2r premise).
	reg        hi_too;                                          // half 1 runs after half 0
	wire [3:0] lanes  = (mcu.sel == 4'b0000) ? 4'b1111 : mcu.sel;
	wire       new_lo = lanes[1:0] != 2'b00;                    // the new access starts with half 0
	reg [31:0] write_data;
	reg [24:1] base_addr;
	// pocket: 0.3.0 new core (the firmware's docs/MCU_INTERFACE.md 3.5) - addr[23] = 1 in the flash region is the flash
	// byte view (0x0480_0000, the chip's 0x6C80_0000): byte A = ROM byte A. The choice is latched with the base address in
	// state 0 and each 16-bit half is byte-swapped as it is captured into mcu_dati (a registered capture, so no new
	// path into the CPU). Read only: a store through it runs as a read (mem_wrl / mem_wrh held at 0)
	reg        swap;
	wire       byte_view = mcu.map.flash & mcu.addr[23];
	wire [3:0] we_eff = byte_view ? 4'b0000 : mcu.we;
	// pocket: 0.3.0 new core, fit round 2 (its second round of fits and timing fixes) - the swap sits AFTER the capture
	// registers. mem_dout is sdram.sv's dout, which the new core's SDRAM I/O change put in the DQ pins' I/O registers, so
	// the clk_md -> clk_sys capture of the first sys edge after the ack is a route from the chip edge into the fabric
	// (9.312 ns), and the swap LUT in front of the capture added a level and a second route: -0.137 ns at slow 85C on fit
	// round 1, seed 1 (dout[2] -> mcu_dati[2]). The halves are now captured as they arrive (dati_raw, 0 levels), each with
	// the swap it was captured under (sw_lo / sw_hi), and mcu_dati applies
	// it: mcu_dati = what the swapped capture held, on every clock, exact by construction. The swap mux is now on
	// clk_sys -> clk_sys into the CPU (rv_di, ~11 ns of slack in fit round 1)
	reg [31:0] dati_raw;
	reg        sw_lo, sw_hi;
	assign mcu_dati = {sw_hi ? {dati_raw[23:16], dati_raw[31:24]} : dati_raw[31:16],
	                   sw_lo ? {dati_raw[7:0],   dati_raw[15:8]}  : dati_raw[15:0]};

	// bram (Paprium battery backup / save RAM) is handled by paprium_backup, an
	// on-chip save-wired RAM - NOT this SDRAM adapter.
	wire selected = mcu.map.flash | mcu.map.sdram;

	// NEORV32 presents the literal byte address plus byte enables. This adapter
	// services each 32-bit MCU bus transaction as two 16-bit SDRAM accesses, so
	// align the base down to a 32-bit boundary before selecting word 0/word 1.
	// Using addr[...,1] directly double-counts addr[1] for byte lanes 2/3.
	// Fafrium: the boot view 0x0380_0000-0x0387_FFFF = SDRAM bytes 0x0100_0000 + addr[18:0]: the firmware file (256 KB,
	// where the ROM loader put it from bridge 0x1100_0000), then the boot stub's scratch; only while boot = 1. With
	// boot = 0 every address maps as before
	wire fw_view = mcu.map.sdram & mcu.addr[23] & boot;
	wire [24:1] selected_addr =
		mcu.map.flash ? {2'b00, mcu.addr[22:2], 1'b0} :
		fw_view       ? {1'b1, 5'd0, mcu.addr[18:2], 1'b0} :
		mcu.map.sdram ? WORKSPACE_BASE + {{4{1'b0}}, mcu.addr[20:2], 1'b0} :
		               24'd0;

	// pocket: sprite-decoder step - the port. state is the MCU's transaction: 0 none, 1 half 0 on the port, 2 half 1 on
	// the port, 3 acknowledged (waiting for the request to drop), 4 half 0 waiting for the port, 5 half 1 waiting for the
	// port
	reg        inflight = 1'b0;    // an access is on the port: mem_req toggled and its ack not seen yet
	reg        own_dec = 1'b0;     // ... and it is the decoder's
	reg        own_we = 1'b0;      // ... a decoder write
	reg        stg_valid = 1'b0;   // the decoder's next access
	reg        stg_we;
	reg  [1:0] stg_lanes;
	reg [24:1] stg_addr;
	reg [15:0] stg_wdata;
	reg  [1:0] drun = 2'd0;        // decoder accesses granted since the MCU's last

	// Who goes next is chosen from registers (and the MCU's request), never from mem_ack: the ack only enables the
	// launch, so the clk_md -> clk_sys paths from ack2 stay an enable, as in the one-client adapter
	wire done      = inflight & (mem_ack == mem_req);              // the access on the port finished this clock
	wire port_free = ~inflight | done;
	wire mcu_new   = (state == 3'd0) & mcu.ce & selected;          // a new MCU transaction, seen this clock
	wire mcu_h0    = (mcu_new & new_lo) | (state == 3'd4);         // half 0 wants the port
	wire mcu_h1    = (mcu_new & ~new_lo) | ((state == 3'd1) & hi_too) | (state == 3'd5);   // half 1 (a3: only if touched)
	wire dec_want  = stg_valid & ~dec_flush;
	wire pick_mcu  = (mcu_h0 | mcu_h1) & (~dec_want | (drun == DEC_RUN));
	wire pick_dec  = dec_want & ~pick_mcu;
	wire launch    = port_free & (pick_mcu | pick_dec);
	wire g_mcu     = launch & pick_mcu;
	wire g_dec     = launch & pick_dec;
	wire [24:1] h0_addr = (state == 3'd0) ? selected_addr : base_addr;

	assign dec_take = ~stg_valid & dec_valid & ~dec_flush;
	assign dec_busy = stg_valid | (inflight & own_dec);

	always @(posedge clk) begin
		dec_rd_done <= 1'b0;
		dec_wr_done <= 1'b0;
		// a decoder access finishing (an access on the port always runs to its ack, in a reset too)
		if (done & own_dec) begin
			if (~own_we) dec_rdata <= mem_dout;
			dec_rd_done <= ~own_we & ~reset;
			dec_wr_done <= own_we & ~reset;
		end

		if(reset) begin
			state <= 0;
			mcu_ack <= 0;
			stg_valid <= 1'b0;
			drun <= 2'd0;
			if (done) inflight <= 1'b0;
			// 0.3.0 new core, the reset-domain fixes (a project decision; MCU_INTERFACE.md 8): the reset no longer touches the
			// port-2 request. sdram.sv's ack2 is reset only at init, so 0.2.6's mem_req <= 0 left req2 != ack2 after any reset
			// that found ack2 = 1, and the controller then ran one access nobody asked for. Holding mem_req, the write enables,
			// address and data lets an access the MCU had already requested finish as requested inside the reset
			// (it takes <= ~64 clk_sys; every reset here lasts >= 0.6 ms), so req2 == ack2 when the MCU starts and
			// nothing is launched by the reset itself. This is the SDC's P2/P2r premise (those registers move only
			// with a toggle, or after mem_ack == mem_req) holding through the reset too. MCU_INTERFACE 8's wording
			// "mem_req <= mem_ack" was benched and can still launch one stray read when an access completes on the
			// clock the reset starts (found in our reset simulations). Since the sprite-decoder step: inflight follows the
			// access to its ack, and nothing (a decoder access neither) launches before the port is free
		end
		else begin
			// the decoder's stage
			if (dec_take) begin
				stg_valid <= 1'b1;
				stg_we    <= dec_we;
				stg_lanes <= dec_lanes;
				stg_addr  <= dec_addr;
				stg_wdata <= dec_wdata;
			end
			else if (dec_flush | g_dec) stg_valid <= 1'b0;

			// the MCU's transaction
			case(state)
				0: begin
					mcu_ack <= 0;
					if(mcu_new) begin
						base_addr <= selected_addr;
						swap <= byte_view;
						byte_en <= we_eff;
						write_data <= mcu.dato;
						hi_too <= lanes[3:2] != 2'b00;
						if (new_lo) state <= g_mcu ? 3'd1 : 3'd4;
						else        state <= g_mcu ? 3'd2 : 3'd5;   // a3: only half 1
					end
				end
				1: if(done) begin
					dati_raw[15:0] <= mem_dout;
					sw_lo <= swap;
					if (hi_too) state <= pick_mcu ? 3'd2 : 3'd5;
					else begin                         // a3: only half 0, the access ends here
						mcu_ack <= 1;
						state <= 3;
					end
				end
				4: if(g_mcu) state <= 3'd1;
				5: if(g_mcu) state <= 3'd2;
				2: if(done) begin
					dati_raw[31:16] <= mem_dout;
					sw_hi <= swap;
					mcu_ack <= 1;
					state <= 3;
				end
				3: if(!mcu.ce) begin
					mcu_ack <= 0;
					state <= 0;
				end
				default: state <= 0;
			endcase

			// the port: launch the granted access (on the clock the last one's ack is seen, or later), or drop the
			// strobes after an ack when nothing follows
			if (launch) begin
				if (pick_mcu) begin
					if (mcu_h0) begin
						mem_addr <= h0_addr;
						mem_din  <= (state == 3'd0) ? mcu.dato[15:0] : write_data[15:0];
						// byte enables: wrl drives DQ[7:0] (=mcu byte0=we[0]),
						// wrh drives DQ[15:8] (=mcu byte1=we[1]). Was crossed, which
						// silently corrupted byte-granular writes (decompression).
						mem_wrl  <= (state == 3'd0) ? we_eff[0] : byte_en[0];
						mem_wrh  <= (state == 3'd0) ? we_eff[1] : byte_en[1];
					end
					else begin   // half 1: a3 can launch it straight from state 0 (base_addr not registered yet)
						mem_addr <= (state == 3'd0) ? {selected_addr[24:2], 1'b1} : base_addr + 1'd1;
						mem_din  <= (state == 3'd0) ? mcu.dato[31:16] : write_data[31:16];
						mem_wrl  <= (state == 3'd0) ? we_eff[2] : byte_en[2];   // DQ[7:0]=mcu byte2 (was crossed)
						mem_wrh  <= (state == 3'd0) ? we_eff[3] : byte_en[3];   // DQ[15:8]=mcu byte3 (was crossed)
					end
					drun <= 2'd0;
				end
				else begin
					mem_addr <= stg_addr;
					mem_din  <= stg_wdata;
					mem_wrl  <= stg_we & stg_lanes[0];
					mem_wrh  <= stg_we & stg_lanes[1];
					if (drun != DEC_RUN) drun <= drun + 2'd1;
				end
				mem_req  <= ~mem_req;
				inflight <= 1'b1;
				own_dec  <= pick_dec;
				own_we   <= pick_dec & stg_we;
			end
			else if (done) begin
				inflight <= 1'b0;
				mem_wrl  <= 0;
				mem_wrh  <= 0;
			end
		end
	end

endmodule
