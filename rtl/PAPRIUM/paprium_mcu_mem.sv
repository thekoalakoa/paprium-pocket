module paprium_mcu_mem
(
	input             clk,
	input             reset,
	input      McuBus mcu,

	output reg        mcu_ack,
	output reg [31:0] mcu_dati,

	output reg [24:1] mem_addr,
	output reg [15:0] mem_din,
	input      [15:0] mem_dout,
	output reg        mem_wrl,
	output reg        mem_wrh,
	output reg        mem_req,
	input             mem_ack
);

	localparam [24:1] WORKSPACE_BASE = 24'h400000;
	localparam [24:1] BACKUP_BASE    = 24'h500000;

	reg [2:0] state;
	reg [3:0] byte_en;
	reg [31:0] write_data;
	reg [24:1] base_addr;

	// bram (Paprium battery backup / save RAM) is handled by paprium_backup, an
	// on-chip save-wired RAM - NOT this SDRAM adapter.
	wire selected = mcu.map.flash | mcu.map.sdram;

	// NEORV32 presents the literal byte address plus byte enables. This adapter
	// services each 32-bit MCU bus transaction as two 16-bit SDRAM accesses, so
	// align the base down to a 32-bit boundary before selecting word 0/word 1.
	// Using addr[...,1] directly double-counts addr[1] for byte lanes 2/3.
	wire [24:1] selected_addr =
		mcu.map.flash ? {2'b00, mcu.addr[22:2], 1'b0} :
		mcu.map.sdram ? WORKSPACE_BASE + {{4{1'b0}}, mcu.addr[20:2], 1'b0} :
		               24'd0;

	always @(posedge clk) begin
		if(reset) begin
			state <= 0;
			mcu_ack <= 0;
			mem_req <= 0;
			mem_wrl <= 0;
			mem_wrh <= 0;
		end
		else begin
			case(state)
				0: begin
					mcu_ack <= 0;
					mem_wrl <= 0;
					mem_wrh <= 0;
					if(mcu.ce && selected) begin
						base_addr <= selected_addr;
						byte_en <= mcu.we;
						write_data <= mcu.dato;
						mem_addr <= selected_addr;
						mem_din <= mcu.dato[15:0];
						// byte enables: wrl drives DQ[7:0] (=mcu byte0=we[0]),
						// wrh drives DQ[15:8] (=mcu byte1=we[1]). Was crossed, which
						// silently corrupted byte-granular writes (decompression).
						mem_wrl <= mcu.we[0];
						mem_wrh <= mcu.we[1];
						mem_req <= ~mem_req;
						state <= 1;
					end
				end

				1: if(mem_ack == mem_req) begin
					mcu_dati[15:0] <= mem_dout;
					mem_addr <= base_addr + 1'd1;
					mem_din <= write_data[31:16];
					mem_wrl <= byte_en[2];   // DQ[7:0]=mcu byte2 (was crossed)
					mem_wrh <= byte_en[3];   // DQ[15:8]=mcu byte3 (was crossed)
					mem_req <= ~mem_req;
					state <= 2;
				end

				2: if(mem_ack == mem_req) begin
					mcu_dati[31:16] <= mem_dout;
					mem_wrl <= 0;
					mem_wrh <= 0;
					mcu_ack <= 1;
					state <= 3;
				end

				3: if(!mcu.ce) begin
					mcu_ack <= 0;
					state <= 0;
				end
			endcase
		end
	end

endmodule
