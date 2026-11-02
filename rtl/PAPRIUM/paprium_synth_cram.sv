// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (block B10, in the synth's first version; the synth's blocks are listed in
// paprium_synth.sv's header) - paprium_synth_cram: the synth's CRAM clients on paprium_cram ports C and E (CRAM = the
// Pocket's cellular RAM; the firmware's docs/MCU_INTERFACE.md v1.3 section 3.8, the die-0 map).
//
// Port C (reads, 16-bit): NC clients, index 0 first (the synth's order: 0 wave samples, 1 SFX words, 2 the curve).
// Port E (reads and writes, one half or a pair): NE clients, index 0 first (0 the DT playback read, the only
// real-time one, then 1 echo-ring reads, 2 echo-ring writes, 3 dac_buf writes).
//
// A client raises q_req with its CRAM byte address (the die-0 byte offset of 3.8, < 0x400000) and holds it until q_gnt
// (one clock). A read then ends with q_done (one clock) and the data: port C gives the whole 16-bit word (c_data) and
// the addressed byte (c_byte = byte address bit 0 ? [15:8] : [7:0]); port E gives e_data ([15:0] for a single half,
// {second half, first half} for a pair). An E write needs no answer: at q_gnt it is the controller's.
//
// Order: each port runs ONE operation at a time, in grant order (an E write counts as done once the controller has
// started all its halves; anything granted after it is performed after it, the controller's own order). Across the
// ports: paprium_cram serves a pending E write before a pending C read, so this block never grants an E WRITE while a
// C read is outstanding (granted, its data not yet back); E reads are not held (port C never writes). In GRANT order:
//   * a C read sees every E write granted in an earlier clock or in the same clock as the read (the controller does
//     that write first) and never one granted in a later clock;
//   * an E read sees every E write granted before it and none granted after it.
// RAISE order is not grant order, on either port: a busy port, the fixed client ranks and the hold above can grant a
// request raised later before one raised earlier. Two cases: an E write and a C read of one word raised in the same
// clock while port E is busy (the DT playback, an echo read) -> the C read is granted first and returns the OLD word;
// while a C read of another word is out, an E write is held, and an E read of its word raised a clock later (client 1
// ranks above 2 / 3) is granted first and returns the OLD data. So a client that needs two accesses of one word in a
// given order raises the second only after the first's q_gnt, on one port or across the two:
//   * "read the old word, then write it" (the cart's wave over-read past the bank end lands in the BGM ring, which
//     the same block rewrites later; a ring block read and then rewritten, delay 255): raise the write after the
//     read's q_gnt;
//   * "write, then read the new word": raise the read after the write's q_gnt.
// Two requests raised in the same clock, or the second before the first's q_gnt, are unordered, with one exception
// that the fixed ranks give on port E (inferred, read from first_e below; the first version's own test streams rely on
// it, as do the directed tests of our CRAM bench): an echo-ring read (E client 1) and a ring or dac_buf write (E client
// 2 / 3) of one pair raised in the same clock are granted read first, whether port E is free or busy then (a write is
// never granted ahead of a lower client still requesting), so the read returns the OLD pair. No other same-clock pair
// is ordered.
// Waits: no bound is established for a C read or an E write (each depends on the other clients and ports). A lower
// client on a port waits for every higher one (index 0 first). An E write also waits while any C read is outstanding:
// under back-to-back C reads it can be granted only in the one clock between two of them, so at most one E write per
// C read (inferred, read from the code; no bench stream checks this bound). The DT playback read (E client 0, the
// first) is never held by port C: it waits only for the one E operation in flight, then its own controller time (each:
// its halves plus what the controller ranks above E: an A write, an aged B half), far inside its 1,119-clock sample.
//
// idle = nothing granted and not finished and no request: the synth's BUSY includes !idle, so the firmware's port-B
// reads of dac_buf after a block (the tick's $1880 copy) come after every write of that block (port B is served by the
// same controller, in order).
//
// Reset (sys_reset): no new grant on either port while reset is high; an operation already at the controller still
// finishes (a write lands; a read's data is dropped and its q_done swallowed: the clients are in reset), and the next
// grant on that port waits for it (the controller's registers reset only at power-on). Port A (the cache slot) and
// port B (the MCU) are not this block's: paprium_cram ranks A writes and aged B halves above C / E, and E above
// A reads (see paprium_cram's header).

module paprium_synth_cram #(
	parameter integer NC = 3,
	parameter integer NE = 4
)(
	input              clk,
	input              reset,

	// ---- port C clients ----
	input     [NC-1:0] cq_req,
	input  [NC*22-1:0] cq_addr,                    // client i at [22i +: 22], a CRAM byte address
	output reg [NC-1:0] cq_gnt,
	output reg [NC-1:0] cq_done,
	output      [15:0] c_data,
	output reg   [7:0] c_byte,

	// ---- port E clients ----
	input     [NE-1:0] eq_req,
	input     [NE-1:0] eq_we,
	input     [NE-1:0] eq_pair,
	input  [NE*22-1:0] eq_addr,                    // a CRAM byte address (a pair: 4-byte aligned)
	input  [NE*32-1:0] eq_wdata,
	output reg [NE-1:0] eq_gnt,
	output reg [NE-1:0] eq_done,
	output      [31:0] e_data,

	output             idle,

	// ---- paprium_cram ports C and E ----
	output reg         c_rd,
	output reg  [20:0] c_raddr,
	input              c_rd_done,
	input       [15:0] c_rdata,
	output reg         e_wr,
	output      [21:0] e_waddr,
	output             e_wpair,
	output reg  [31:0] e_wdata,
	output reg         e_rd,
	output      [21:0] e_raddr,
	output             e_rpair,
	input              e_rd_done,
	input       [31:0] e_rdata,
	input              e_wbusy
);

	localparam integer CW = (NC > 1) ? $clog2(NC) : 1;
	localparam integer EW = (NE > 1) ? $clog2(NE) : 1;

	// the first requester, lowest index, as a one-hot vector, and the chosen client's fields: selected with loops over
	// constant indexes (no index arithmetic: a variable part-select at 22 x i made the mapper use DSP blocks)
	function automatic [NC-1:0] first_c(input [NC-1:0] r);
		integer i;
		reg     f;
		begin
			first_c = {NC{1'b0}};
			f = 1'b0;
			for (i = 0; i < NC; i = i + 1) if (r[i] && !f) begin first_c[i] = 1'b1; f = 1'b1; end
		end
	endfunction
	function automatic [NE-1:0] first_e(input [NE-1:0] r);
		integer i;
		reg     f;
		begin
			first_e = {NE{1'b0}};
			f = 1'b0;
			for (i = 0; i < NE; i = i + 1) if (r[i] && !f) begin first_e[i] = 1'b1; f = 1'b1; end
		end
	endfunction

	reg        c_out = 1'b0;                        // a C read at the controller (not reset by sys_reset: it drains)
	wire [NC-1:0] c_pick = first_c(cq_req & ~cq_gnt);   // a client granted last clock has not dropped its request yet
	// the cross-port order: an E write is not granted while a C read is outstanding (the controller would do it first)
	wire [NE-1:0] e_pick = first_e(eq_req & ~eq_gnt & ~(eq_we & {NE{c_out}}));
	reg  [21:0]   c_paddr;
	reg  [CW-1:0] c_pidx;
	reg  [21:0]   e_paddr;
	reg  [31:0]   e_pwdata;
	reg           e_pwe, e_ppair;
	reg  [EW-1:0] e_pidx;
	integer k;
	always @(*) begin
		c_paddr = 22'd0; c_pidx = {CW{1'b0}};
		for (k = 0; k < NC; k = k + 1) if (c_pick[k]) begin c_paddr = cq_addr[22 * k +: 22]; c_pidx = k[CW-1:0]; end
		e_paddr = 22'd0; e_pwdata = 32'd0; e_pwe = 1'b0; e_ppair = 1'b0; e_pidx = {EW{1'b0}};
		for (k = 0; k < NE; k = k + 1) if (e_pick[k]) begin
			e_paddr = eq_addr[22 * k +: 22]; e_pwdata = eq_wdata[32 * k +: 32]; e_pwe = eq_we[k]; e_ppair = eq_pair[k];
			e_pidx = k[EW-1:0];
		end
	end

	// ---- port C ----
	reg        c_own_ok = 1'b0;                     // its done goes to a client (cleared by reset: swallowed)
	reg  [CW-1:0] c_own = {CW{1'b0}};
	reg        c_lsb = 1'b0;
	// Trimmed to save logic: c_data is paprium_cram's own c_rdata register: it is written only when a port-C read
	// completes (with c_rd_done) and holds until the next one, which this block cannot start before the clock after
	// cq_done; every client takes c_data only in its cq_done clock, where both are the read's word
	assign c_data = c_rdata;

	always @(posedge clk) begin
		c_rd    <= 1'b0;
		cq_gnt  <= {NC{1'b0}};
		cq_done <= {NC{1'b0}};
		if (c_out) begin
			if (c_rd_done) begin
				c_out  <= 1'b0;
				c_byte <= c_lsb ? c_rdata[15:8] : c_rdata[7:0];
				if (c_own_ok & ~reset) cq_done[c_own] <= 1'b1;
			end
		end
		else if (!reset && c_pick != {NC{1'b0}}) begin
			c_out    <= 1'b1;
			c_own_ok <= 1'b1;
			c_own    <= c_pidx;
			c_lsb    <= c_paddr[0];
			c_rd     <= 1'b1;
			c_raddr  <= c_paddr[21:1];
			cq_gnt   <= c_pick;
		end
		if (reset) c_own_ok <= 1'b0;
	end

	// ---- port E ----
	localparam [1:0] E_FREE = 2'd0, E_RD = 2'd1, E_WR1 = 2'd2, E_WR2 = 2'd3;
	reg  [1:0] e_st = E_FREE;                       // not reset by sys_reset (drains, as port C)
	reg        e_own_ok = 1'b0;
	reg  [EW-1:0] e_own = {EW{1'b0}};
	// Trimmed to save logic: e_data is paprium_cram's own e_rdata register: written only by port-E read halves (the last
	// with e_rd_done) and held until the next E read, which this block cannot start before the clock after eq_done; every
	// client takes e_data only in its eq_done clock, where both are the read's data
	assign e_data = e_rdata;
	// Trimmed to save logic: one address / pair register for both E operations. paprium_cram takes e_waddr / e_wpair only
	// in a clock with e_wr and e_raddr / e_rpair only in a clock with e_rd (its port latches), and this block raises at
	// most one of the two in a clock, so both outputs carry the granted operation's address in the clock that matters
	reg  [20:0] e_addr;
	reg         e_pp;
	assign e_waddr = {1'b0, e_addr};
	assign e_raddr = {1'b0, e_addr};
	assign e_wpair = e_pp;
	assign e_rpair = e_pp;

	always @(posedge clk) begin
		e_wr    <= 1'b0;
		e_rd    <= 1'b0;
		eq_gnt  <= {NE{1'b0}};
		eq_done <= {NE{1'b0}};
		case (e_st)
			E_RD: if (e_rd_done) begin
				e_st   <= E_FREE;
				if (e_own_ok & ~reset) eq_done[e_own] <= 1'b1;
			end
			E_WR1: e_st <= E_WR2;                    // the controller took the write at the last edge: e_wbusy is 1 now
			E_WR2: if (!e_wbusy) e_st <= E_FREE;     // all its halves started: anything later goes after it
			default: if (!reset && e_pick != {NE{1'b0}}) begin
				e_own_ok <= 1'b1;
				e_own    <= e_pidx;
				eq_gnt   <= e_pick;
				e_addr   <= e_paddr[21:1];
				e_pp     <= e_ppair;
				if (e_pwe) begin
					e_st    <= E_WR1;
					e_wr    <= 1'b1;
					e_wdata <= e_pwdata;
				end
				else begin
					e_st    <= E_RD;
					e_rd    <= 1'b1;
				end
			end
		endcase
		if (reset) e_own_ok <= 1'b0;
	end

	assign idle = ~c_out & (e_st == E_FREE) & (cq_req == {NC{1'b0}}) & (eq_req == {NE{1'b0}});

endmodule
