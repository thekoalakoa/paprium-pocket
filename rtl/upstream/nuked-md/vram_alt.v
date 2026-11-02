// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// vram_alt: "Design B", a drop-in replacement for Nuked-MD's vram.v (same ports, one clock, registered outputs like
// vram.v). md_board.v instantiates it as vram1 unless VRAM_ORIG is defined, which puts vram.v back. Written for this
// core; it is covered by the core's licence (see README).
//
// Idea: no 2,048-bit row register, no 2,048-bit serial snapshot, no 256:1 byte muxes.
//   MM  : the 64 KB as ONE true-dual-port block RAM, 8,192 words x 64 bits (64 M10K).
//         word address = {row, col[7:3]}, byte lane = col[2:0]  (a word = an 8-byte "chunk" of a row).
//         port A = the random port: the write, or (every other edge) a one-edge-early read of the next column for RD_o.
//         port B = the serial snapshot copy, chunk by chunk (and, with G1 = 1, the write on a cas-edge write so that
//                  port A can still read: the only case where the random port needs two accesses on one edge).
//   SB  : the serial snapshot as a SEPARATE block RAM (2 M10K): written 64 bits at a time, read one byte at a time,
//         refilled by a background copy after every read transfer. A write into a chunk of the snapshot row that has
//         not been copied yet is "snooped": port B reads that chunk on the very write edge (mixed-port OLD_DATA), so
//         the copy always holds the row as it was one edge before the transfer, exactly like vram.v's 'ser <= mem_o'.
//   need: 32 flags "chunk not yet copied for the current snapshot" (instead of a 256-bit captured vector).
//
// The edge rules of vram.v, with k = this rising edge:
//   RD_o(k)  = Q(k)[col(k)], Q(k) = memory after edge k-1 at row(k-1)   -> port A reads {row, col_next} at k-1
//   write(k) = M[row(k)][col(k)] <= RD_i                                 -> port A (or port B) writes at k
//   T(k)     : snapshot = Q(k) = memory after edge k-1 at row(k-1) = row_d, aser <= col(k)
//   S(k)&~T  : SD_o <= snapshot[aser], aser++
//
// STRICT = 1 adds what only matters for timing the VDP never produces: serial bypasses (a serial clock 1-2 edges
// after a chunk is fetched) and, with G1 = 1, the port-B write on a cas-edge write. STRICT = 0 is a minimal variant
// whose VDP-timing assumptions are not proven; do not use it.
// G1 = 0 (the default, and what md_board.v uses): no port-B write. A write on a cas edge into another chunk followed
// by a read on the next edge then reads the written chunk's old byte; the VDP never makes that write (Nuked's ym7101
// puts WE0's fall at least one dot clock after CAS1's), and it never appeared in any recorded VDP traffic.
//
// Timing hardening (exact restructures; every output equals the unhardened file's for every input):
//   F1: nbyte takes its lane from the registered aser (was the next-state aser).
//   F2: the snapshot buffer is read at the registered aser (was the next-state aser, which is now gone).
//   F3: the register-only part of the snoop condition is one kept node with the late pin term ANDed last, and the
//       copy bookkeeping (port-B address, need, p) selects on T and snoop at the last mux level.
// F1 and F2 take the VDP's mode-latch / SC decode off every vram path except the enables of aser and vram_ser (the
// same enables vram.v has); F3 shortens the T / snoop chains into the port-B address and the need flags.
//   F4 (0.3.0 new core, SHADOW = 1): "shadow pins". RAS / CAS / WE / OE are 1-2 LUT functions of VDP latch
//       registers, so ym7101 also gives their values after the next edge (RAS_nx .. OE_nx, the same equations on the
//       latches' D inputs). Registered here, they equal the pins on every edge for any input (no reset touches those
//       latches; power-up values below), and every rule above reads the registers instead of the pins: the VDP decode
//       (latch -> pin, ~2-3 ns) then ends at these four registers instead of at 64 M10K port-B address registers.
//       In the new core's first round of fits: T -> port-B address (class C) below 0 in 2 of 4 seeds, 39 endpoints on
//       seed 3 (dl573 -> OE -> T -> b_addr, -0.339 ns at slow 85C). SHADOW = 0 reads the pins (trace-driven benches).
//   F5 (0.3.0 new core, the third round of fits): the snoop condition's register part (F3's sn_pre) is a register,
//       sn_pre_q, loaded
//       on every edge with the value sn_pre will have after that edge, computed from the D inputs of its own sources
//       (need, col, row, R). It equals sn_pre on every edge for any input (power-up: need = 0, so both are 0; no reset
//       touches vram_alt). F3's busy term is dropped from it: need[c] = 1 implies |need = 1, so busy & need[c] = need[c].
//       The copy flags (need[], their OR and the 32:1 need[col] mux) then end at sn_pre_q instead of at 64 M10K port-B
//       address registers. In the second round: need[20] -> busy (4 LUTs) -> sn_pre -> snoop -> b_addr below 0 on seeds
//       5 and 6 (188 endpoints on seed 6, -0.437 ns at slow 85C); need[col] -> sn_pre the worst vram1 path on seeds 1
//       and 2.
module vram_alt #(parameter STRICT = 1, parameter G1 = 0, parameter SHADOW = 0)
	(
	input MCLK,
	input RAS,
	input CAS,
	input WE,
	input OE,
	// verilator lint_off UNUSEDSIGNAL
	input RAS_nx,                       // F4: the pins' values after the next edge (used with SHADOW = 1)
	input CAS_nx,
	input WE_nx,
	input OE_nx,
	// verilator lint_on UNUSEDSIGNAL
	input SC,
	input SE,
	input [7:0] AD,
	input [7:0] RD_i,
	output reg [7:0] RD_o,
	output RD_d,
	output [7:0] SD_o,
	output SD_d
	);

	// Every register starts at 0, as the FPGA powers up (the equivalence runs start vram.v from 0 too).
	// verilator lint_off PROCASSINIT

	// ------------------------------------------------------------------ F4: the pins as registers
	// ym7101's VRAM pin latches power up 0, which gives RAS1 = 0, CAS1 = 0, WE0 = 1, OE1 = 1; WE and OE are kept
	// inverted so all four registers power up 0 too (a power-up-1 register would get inverters around it)
	reg  ras_q = 1'b0, cas_q = 1'b0, nwe_q = 1'b0, noe_q = 1'b0;
	always @(posedge MCLK)
	begin
		ras_q <= RAS_nx;
		cas_q <= CAS_nx;
		nwe_q <= ~WE_nx;
		noe_q <= ~OE_nx;
	end
	wire pRAS = (SHADOW != 0) ? ras_q  : RAS;
	wire pCAS = (SHADOW != 0) ? cas_q  : CAS;
	wire pWE  = (SHADOW != 0) ? ~nwe_q : WE;
	wire pOE  = (SHADOW != 0) ? ~noe_q : OE;

	// ------------------------------------------------------------------ random-port state (as vram.v)
	reg  [7:0] row   = 8'd0;     // vram.v addr[15:8]
	reg  [7:0] col   = 8'd0;     // vram.v addr[7:0]
	reg  [7:0] row_d = 8'd0;     // row before the previous edge = the row vram.v's mem_o shows
	reg        dt    = 1'b0;
	reg        o_OE  = 1'b0, o_RAS = 1'b0, o_cas = 1'b0, o_SC = 1'b0, o_valid = 1'b0;
	initial RD_o = 8'd0;

	wire cas = ~pRAS & ~pCAS;
	wire wr  = cas & ~pWE;
	wire rd  = cas & ~pOE & ~dt;
	wire F   = o_RAS & ~pRAS;           // RAS fall: row, dt load
	wire C   = ~o_cas & cas;            // cas edge: column load
	wire T   = dt & ~o_OE & pOE;        // read transfer
	wire S   = ~o_SC & SC;              // serial clock rise

	wire [4:0] chunk_nx = C ? AD[7:3] : col[7:3];   // the column register's chunk after this edge

	// ------------------------------------------------------------------ serial snapshot copy state
	reg  [7:0]  R    = 8'd0;            // snapshot row
	reg  [31:0] need = 32'd0;           // 1 = chunk not yet fetched for the current snapshot (power-on: none)
	reg  [4:0]  p    = 5'd0;            // background copy pointer
	reg  [7:0]  aser = 8'd0;            // vram.v addr_ser
	reg  [7:0]  vram_ser = 8'd0;

	wire busy  = |need;
	// F3: register-only part of the snoop condition (= busy & (row == R) & need[col[7:3]]), ANDed with the late pin term
	// (wr) last; F5: held in a look-ahead register (loaded below)
	reg  sn_pre_q = 1'b0;
	wire snoop = sn_pre_q & wr;     // write into a not-yet-copied chunk of the snapshot row
	wire seq   = busy & need[p];
	// a write on a cas edge whose next column lies in another chunk: port A must write AND read the next column
	wire g1req = (G1 != 0) & (STRICT != 0) & wr & C & (AD[7:3] != col[7:3]);   // G1 = 0: none (VDP-unreachable case dropped)

	// port B request, priority: transfer > snoop > background copy > the cas-edge write (then port A reads)
	// F3: same priority (transfer > snoop > copy > G1), written so T and snoop are the last mux selects
	wire [12:0] b_low  = (~seq & g1req) ? {row, col[7:3]} : {R, p};
	wire [12:0] b_addr = T ? {row_d, col[7:3]} : (snoop ? {row, col[7:3]} : b_low);
	wire  [4:0] b_x    = (T | snoop) ? col[7:3] : p;
	wire        b_copy = T | snoop | seq;
	wire        b_g1   = ~T & ~snoop & ~seq & g1req;
	// F3: next-state terms from registers only
	wire [31:0] need_t = ~(32'd1 << col[7:3]);
	wire [31:0] need_s = need & ~(32'd1 << col[7:3]);
	wire [31:0] need_q = need & ~(32'd1 << p);      // = 'clear p if seq': ~seq means need[p] = 0 or need = 0
	wire  [4:0] p_t    = col[7:3] + 5'd1;
	wire  [4:0] p_q    = busy ? p + 5'd1 : p;
	// F5: sn_pre after this edge = need'[cn] & (row' == R'), from the next states the always block below gives:
	//   chunk cn = col'[7:3] = C ? AD[7:3] : col[7:3]      row' = F ? AD : row      R' = T ? row_d : R
	//   need'[c] = (c != b_x) & (T | need[c])   (T: need_t, every chunk but col[7:3]; snoop: need_s, need less chunk
	//              col[7:3]; else need_q, need less chunk p; b_x is col[7:3] on T or snoop and p otherwise)
	// (busy' & need'[cn] = need'[cn]: a set flag makes busy). AD is the late input (the VDP's bus), so it enters as few
	// LUT levels as possible: its own 32:1 need mux and compares, the cas-edge and RAS-fall selects last.
	wire  [7:0] R_nx      = T ? row_d : R;
	wire        nc_ad     = (AD[7:3]  != b_x) & (T | need[AD[7:3]]);
	wire        nc_col    = (col[7:3] != b_x) & (T | need[col[7:3]]);
	wire        sn_pre_nx = (C ? nc_ad : nc_col) & (F ? (AD == R_nx) : (row == R_nx));

	// ------------------------------------------------------------------ memories
	wire [63:0] qA, qB;
	wire  [7:0] sbq;
	wire        a_wr   = wr & ~b_g1;
	wire [12:0] a_addr = {row, (a_wr ? col[7:3] : chunk_nx)};
	wire  [7:0] a_be   = 8'd1 << col[2:0];

	reg         rb_copy = 1'b0;         // port B fetched a snapshot chunk at the previous edge ...
	reg   [4:0] rb_x    = 5'd0;         // ... this one

	vram_alt_mm mm
		(
		.clock(MCLK),
		.address_a(a_addr), .byteena_a(a_be), .data_a({8{RD_i}}), .wren_a(a_wr), .q_a(qA),
		.address_b(b_addr), .byteena_b(a_be), .data_b({8{RD_i}}), .wren_b(b_g1), .q_b(qB)
		);

	vram_alt_sb sb
		(
		.clock(MCLK),
		.wraddress(rb_x), .data(qB), .wren(rb_copy),
		.rdaddress(aser), .q(sbq)   // F2
		);

	// ------------------------------------------------------------------ serial output
	// A serial byte for an S at edge k comes from
	//   hit1: the chunk port B read at k-1 (on qB now),
	//   hit2: the chunk port B read at k-2, written into SB at k-1 (SB cannot return it yet): the byte the serial
	//         port will want was latched from qB at k-1 (nbyte, lane aser[2:0] of k-1, which is aser[2:0] now
	//         whenever hit2 is used),
	//   else: SB, read at k-1 at byte aser of k-1, which is aser now whenever SB is used.
	reg   [7:0] nbyte = 8'd0;
	reg   [4:0] wx    = 5'd0;
	reg         wv    = 1'b0;

	wire hit1 = rb_copy & (rb_x == aser[7:3]);
	wire hit2 = wv & (wx == aser[7:3]);
	wire  [7:0] b_qB  = qB[8*aser[2:0] +: 8];
	wire  [7:0] sbyte = (STRICT != 0) ? (hit1 ? b_qB : (hit2 ? nbyte : sbq)) : sbq;

	assign SD_o = vram_ser;
	assign SD_d = SE;

	// ------------------------------------------------------------------ random read output
	wire  [7:0] rbyte = qA[8*col[2:0] +: 8];
	assign RD_d = ~o_valid;

	always @(posedge MCLK)
	begin
		// serial port
		if (T)
			aser <= col;
		else if (S)
		begin
			aser <= aser + 8'h1;
			vram_ser <= sbyte;
		end

		// snapshot copy bookkeeping
		// F3: late inputs (T, snoop) at the last mux level
		if (T)
			R <= row_d;
		need <= T ? need_t : (snoop ? need_s : need_q);
		p    <= T ? p_t    : (snoop ? p      : p_q);
		sn_pre_q <= sn_pre_nx;   // F5
		rb_copy <= b_copy;
		rb_x    <= b_x;
		nbyte   <= qB[8*aser[2:0] +: 8];      // F1
		wx      <= rb_x;
		wv      <= rb_copy & ~T;

		// random port (vram.v)
		if (F)
		begin
			dt <= ~pOE;
			row <= AD;
		end
		if (C)
			col <= AD;
		row_d <= row;

		if (rd)
		begin
			RD_o <= rbyte;
			o_valid <= 1'h1;
		end
		else if (pCAS | pOE)
		begin
			o_valid <= 1'h0;
		end

		o_OE  <= pOE;
		o_RAS <= pRAS;
		o_cas <= cas;
		o_SC  <= SC;
	end

`ifdef VRAM_ALT_SHADOW_CHECK
	// simulation only (the F4 proof): the F4 registers against the pins on every edge
	integer n_shadow_err = 0, n_shadow_clk = 0;
	always @(negedge MCLK) begin
		n_shadow_clk = n_shadow_clk + 1;
		if ({ras_q, cas_q, ~nwe_q, ~noe_q} !== {RAS, CAS, WE, OE}) begin
			n_shadow_err = n_shadow_err + 1;
			if (n_shadow_err <= 5) $display("VRAM_ALT_SHADOW_CHECK pin_q %b != pins %b (t=%0t)", {ras_q, cas_q, ~nwe_q, ~noe_q}, {RAS, CAS, WE, OE}, $time);
		end
	end
`endif
`ifdef VRAM_ALT_SNLA_CHECK
	// simulation only (F5 proof): sn_pre_q against F3's combinational snoop condition on every edge, plus coverage:
	// edges with sn_pre = 1, snoops, and sn_pre = 1 right after a cas edge (AD arm), a RAS fall (AD row) or a transfer
	integer n_snla_err = 0, n_snla_clk = 0, n_snla_one = 0, n_snla_snoop = 0, n_snla_c = 0, n_snla_f = 0, n_snla_t = 0;
	reg snla_c = 1'b0, snla_f = 1'b0, snla_t = 1'b0;
	wire snla_ref = busy & (row == R) & need[col[7:3]];
	always @(posedge MCLK) begin snla_c <= C; snla_f <= F; snla_t <= T; end
	always @(negedge MCLK) begin
		n_snla_clk = n_snla_clk + 1;
		if (sn_pre_q !== snla_ref) begin
			n_snla_err = n_snla_err + 1;
			if (n_snla_err <= 5) $display("VRAM_ALT_CHECK SNLA sn_pre_q %b != sn_pre %b (t=%0t)", sn_pre_q, snla_ref, $time);
		end
		if (snla_ref) begin
			n_snla_one = n_snla_one + 1;
			if (snla_c) n_snla_c = n_snla_c + 1;
			if (snla_f) n_snla_f = n_snla_f + 1;
			if (snla_t) n_snla_t = n_snla_t + 1;
			if (wr) n_snla_snoop = n_snla_snoop + 1;
		end
	end
`endif
`ifdef VRAM_ALT_CHECKS
	// simulation-only self checks: the serial byte must come from a chunk fetched for the current snapshot, and
	// (STRICT=0) from SB itself; a cas-edge write followed by a read must have had its port-B write.
	integer n_ahead = 0, n_min = 0, n_g1 = 0;
	reg g1_lost = 1'b0;
	// rd_taint: RD_o holds a byte read right after a cas-edge write into another 32-byte block whose port-B write
	// could not be granted (the only case where the random port alone cannot give vram.v's byte). A classifying
	// harness may read it to skip (and count) the RD_o compare while it is set.
	reg rd_taint = 1'b0;
	wire g1need = wr & C & (AD[7:5] != col[7:5]);
	always @(posedge MCLK) begin
		g1_lost <= g1need & ~b_g1;
		if (rd) rd_taint <= g1_lost;
		if (S & ~T & need[aser[7:3]]) begin
			n_ahead = n_ahead + 1;
			if (n_ahead <= 5) $display("VRAM_ALT_CHECK serial byte %02x needed before its chunk was fetched (t=%0t)", aser, $time);
		end
		if ((STRICT == 0) & S & ~T & (hit1 | hit2)) begin
			n_min = n_min + 1;
			if (n_min <= 5) $display("VRAM_ALT_CHECK STRICT=0 would need a serial bypass (aser %02x, t=%0t)", aser, $time);
		end
		if (rd & g1_lost) begin
			n_g1 = n_g1 + 1;
			if (n_g1 <= 5) $display("VRAM_ALT_CHECK read after a cas-edge write without its port-B write (t=%0t)", $time);
		end
	end
`endif
	// verilator lint_on PROCASSINIT
endmodule
