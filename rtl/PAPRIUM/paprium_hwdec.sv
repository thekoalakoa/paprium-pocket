// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0, the sprite-decoder step (B Jam 2026-10-15 "preservation") - the cart FPGA's sprite decoder and its
// load-list queue. FPGAIO below = the MCU's register block in the FPGA (fpgio.sv).
//
// On the cart the chip never waits for this: AF's handler queues the frame's load list ($1FF6 = 1 clear, then per
// block $1FF4 = 0x200 | a[22:16], $1FF6 = a[15:0], last to first, then $1FF2 = 0x8000), composes, and replies; the
// cart FPGA decodes the blocks on its own, early, and the VBlank DMA reads them through the $C000 window. This
// module is that FPGA side, so the firmware's handlers, which do what the chip's do, reply at once and the game never
// waits.
//
// Register writes (from paprium_regfile, the chip's offsets; acted on one clock after the store's first bus clock,
// in program order):
//   +0x12 $1FF2  0x8000 = START; 0x0000 or bits 15:14 = 11 = STOP; anything else: no action here
//   +0x14 $1FF4  HI := the value (bits 6:0 = address bits 22:16; the 0x200 flag and the rest ignored)
//   +0x16 $1FF6  bit 0 = 1: CLEAR; bit 0 = 0: PUSH {HI[6:0], v[15:1], 0} (a 23-bit even byte address)
// The queue: 16 entries, a stack (the last push is served first, so a list pushed last to first is decoded first to
// last). A 17th push is dropped and sets OVF. Every chip push path clears first.
//   START, depth 0: nothing here (SPTR, the workspace and the stream are untouched; the register file still makes
//            the stream invalid, so busy reads 1). Every load-less AF / B1 and the DA07 prelude do this.
//   START, depth n: abort a run in progress; base := DEC_BASE (FPGAIO slot 17, bit 0 ignored); SPTR := base (the
//            window points at the first word to be decoded); the run takes entries q[n-1] .. q[0]; depth := 0.
//   CLEAR: depth := 0 and abort a run.  STOP: abort a run, the queue kept.  PUSH during a run: abort, then push.
//   Abort: no new request goes to the port (a staged one is dropped), an access already on the port finishes, the
//          buffered bytes are dropped, no GO; words already written stay. Flag ABORT.
// One entry: the byte at the entry's address (the high byte of ROM-image word a/2) must be 0x80, else the entry is
// skipped (BADTYPE). Then the chip's own 0x80 unpacker (0x0802FF78), t = the next byte, n = t & 0x3F:
//   t >> 6 = 0: n == 0 ends the entry, else n literal bytes;  1: n copies of the next byte;
//           2: n bytes copied byte by byte from d = the next byte back;  3: n zero bytes  (n = 0: operands only)
// Output: the bytes of one START are contiguous from base, across its entries: byte o lands at workspace byte
//   base + o (even = the high byte DQ[15:8] of SDRAM word 0x400000 + (base + o) / 2, odd = the low byte), exactly
//   where 0.2.6's ppm_unpack put them. Two bytes go as one write; a final odd byte goes alone (high lane only).
//   Copies read a 256-byte history of the START's output (ring[o & 0xFF]), not reset between entries. A copy with
//   d = 0 writes nothing for its n bytes (flag D0); a reference before base reads the ring's stale byte (flag PRE).
//   Neither is in the game's data.
// End of a run: the pending odd byte written, every write acknowledged, then GO: remaining := (o >> 1) - the words
//   the window delivered since START (saturating at 0), stream valid when that is not 0, guard cleared (the effect of
//   an FPGAIO slot-7 write, in paprium_regfile). Busy therefore falls when the whole START is decoded.
//
// SDRAM: ROM-image reads and workspace writes go through paprium_mcu_mem's port-2 arbiter (the MCU's flash and
// workspace port), one 16-bit access at a time, never through port 0 or 1: sdram.sv's DMA hold covers them exactly
// as it covers the MCU, so no VDP DMA cart read waits for this. The arbiter takes p2_* into its stage register when
// the stage is empty (p2_take), and returns each completion in order (p2_rd_done with p2_rdata, p2_wr_done).
//
// FPGAIO v1.2 slots 17-22 (board only; the chip has no such registers and no decoder interrupt, and needs none):
//   17 DEC_BASE   [20:0], bit 0 reads 0           the next START's base (workspace byte offset)       write: value
//   18 DEC_STAT   [4:0] depth, [9:5] entries left in the run, [10] RUN, [11] DONE (the last START finished),
//                 [16] OVF, [17] BADTYPE, [18] D0, [19] PRE, [20] LATE, [21] ABORT                 write 1: clear 16-21
//   19 DEC_WORDS  [20:0] words written (acknowledged) since the last START                          write: ignored
//   20 DEC_TIME   [31] valid, [23:0] clk_sys cycles from the last START to its GO (saturating)      write: ignored
//   21 DEC_MARGIN signed: the minimum since reset / the last write of (first window word delivered after a START)
//                 - (its GO), in clk_sys cycles; negative = the window was read before the run had finished
//                                                                                   write: back to 0x7FFFFFFF
//   22 DEC_LATECNT [15:0] window words delivered during a run at or beyond base + the words acknowledged (words
//                 read before they were written), saturating                                         write: clear
// TEST = 0 drops the monitors (19-22 read 0, LATE / MARGIN never set); the decoder is the same either way.
//
// Reset (every sys_reset): queue empty, idle, HI 0, DEC_BASE 0, flags and monitors cleared, MARGIN 0x7FFFFFFF.

module paprium_hwdec
#(parameter TEST = 1'b1)
(
	input             clk,             // clk_sys
	input             reset,           // every reset (sys_reset | ~enable)

	// paprium_regfile: the MCU's +0x12 / +0x14 / +0x16 stores (first bus clock) and their halfwords
	input             fr_f2,
	input             fr_f4,
	input             fr_f6,
	input      [15:0] fr_f2_v,
	input      [15:0] fr_f4_v,
	input      [15:0] fr_f6_v,

	// fpgio: FPGAIO slots 17-22
	input             fio_wr,          // a store to slot 17 + fio_wslot (first bus clock)
	input       [2:0] fio_wslot,
	input      [31:0] fio_wdata,
	input       [2:0] fio_rslot,       // slot - 17 of the access on the bus
	output reg [31:0] fio_rdata,       // combinational read data of slot 17 + fio_rslot

	// the stream (paprium_cart / paprium_regfile)
	input      [20:0] sptr,            // the live stream pointer
	input             word_delivered,  // one clock per window word delivered
	input             fw_sptr_wr,      // the firmware wrote FPGAIO slot 2 (SPTR)
	output reg        sptr_load,       // one clock: stream_ptr := sptr_val
	output reg [20:0] sptr_val,
	output            go,              // one clock: the run's GO, with go_len (into paprium_regfile)
	output     [20:0] go_len,

	// SDRAM port 2 through paprium_mcu_mem's arbiter
	output            p2_valid,
	output            p2_we,
	output      [1:0] p2_lanes,        // {wrh (DQ[15:8], the even byte), wrl}
	output     [24:1] p2_addr,
	output     [15:0] p2_wdata,
	input             p2_take,
	output            p2_flush,        // drop the staged access (an abort)
	input             p2_rd_done,
	input      [15:0] p2_rdata,
	input             p2_wr_done,
	input             p2_busy          // a decoder access is staged or on the port
);

	// ------------------------------------------------------------------------------------------------ states
	localparam [3:0] S_IDLE  = 4'd0,   // no run
	                 S_QRD   = 4'd1,   // the queue entry's address is on the queue RAM
	                 S_QLAT  = 4'd2,   // take the entry's address, start its reads
	                 S_TYPE  = 4'd3,   // the type byte
	                 S_TOK   = 4'd4,   // a code byte t
	                 S_PAR   = 4'd5,   // t's operand (the RLE byte or the copy distance)
	                 S_LIT   = 4'd6,   // n literal bytes
	                 S_FILL  = 4'd7,   // n copies of fillv (RLE, or 0 for a zero run)
	                 S_COPY  = 4'd8,   // n bytes from d back
	                 S_TAIL  = 4'd9,   // the pending odd byte, then every write acknowledged
	                 S_GO    = 4'd10,  // one clock: GO
	                 S_DRAIN = 4'd11;  // an abort: wait until no access of ours is staged or on the port

	reg  [3:0] st;
	wire       running  = (st != S_IDLE) & (st != S_DRAIN);       // a START taken and its GO not yet given
	wire       decoding = (st == S_TYPE) | (st == S_TOK) | (st == S_PAR) | (st == S_LIT) | (st == S_FILL) | (st == S_COPY);

	// ------------------------------------------------------------------------------------------------ register events
	reg        e_start, e_stop, e_clear, e_push, e_hi;
	reg [15:0] e_v;               // the $1FF6 value of a push
	reg  [6:0] e_hiv;             // the $1FF4 value's address bits
	always @(posedge clk) begin
		if (reset) begin
			e_start <= 1'b0; e_stop <= 1'b0; e_clear <= 1'b0; e_push <= 1'b0; e_hi <= 1'b0;
		end
		else begin
			e_start <= fr_f2 & (fr_f2_v == 16'h8000);
			e_stop  <= fr_f2 & ((fr_f2_v == 16'h0000) | (fr_f2_v[15:14] == 2'b11));
			e_clear <= fr_f6 & fr_f6_v[0];
			e_push  <= fr_f6 & ~fr_f6_v[0];
			e_hi    <= fr_f4;
		end
		e_v   <= fr_f6_v;
		e_hiv <= fr_f4_v[6:0];
	end

	// ------------------------------------------------------------------------------------------------ the queue
	(* ramstyle = "MLAB, no_rw_check" *) reg [21:0] qmem [0:15];   // the even byte address a[22:1]
	reg  [4:0] qn;                // depth 0..16
	reg  [6:0] qhi;               // the latched $1FF4 address bits
	wire [6:0] qhi_eff  = e_hi ? e_hiv : qhi;                      // a 32-bit store writes both halves at once
	wire       q_push   = e_push & ~qn[4];
	reg  [3:0] q_ra;              // the run's current entry
	reg [21:0] q_rd;
	always @(posedge clk) begin
		if (q_push) qmem[qn[3:0]] <= {qhi_eff, e_v[15:1]};
		q_rd <= qmem[q_ra];
	end

	// ------------------------------------------------------------------------------------------------ run state
	reg [20:1] dec_base;          // FPGAIO slot 17 (bit 0 reads 0)
	reg        start_pend;        // a START with entries, its run not begun yet (an abort is draining first)
	reg  [4:0] pend_n;            // its depth
	reg [20:0] base;              // the START's base (even)
	reg  [4:0] run_left;          // entries left in the run, the current one included
	reg [20:0] o;                 // bytes produced since START
	reg  [1:0] ty;                // the code's type (t >> 6)
	reg  [5:0] cnt;               // bytes left in the code
	reg  [7:0] fillv;             // the RLE byte (0 for a zero run)
	reg  [7:0] cdist;             // the copy distance
	reg  [7:0] last;              // the byte produced last (a copy with d = 1)
	reg        cp_ok;             // the history read for this copy is valid (the clock after its first)
	reg        tail_done;         // the odd byte of the run is in the write buffer

	// ------------------------------------------------------------------------------------------------ input: ROM words
	reg [21:0] rd_wa;             // the next ROM-image word to read
	(* ramstyle = "MLAB, no_rw_check" *) reg [15:0] fq [0:3];   // read words, in order (a LUT RAM: read without a clock)
	reg  [1:0] f_wp, f_rp;
	reg  [2:0] f_have;            // words in fq
	reg        f_lo;              // the head word's low (odd) byte is next
	reg  [1:0] rd_out;            // reads taken for this entry and not yet returned
	reg  [1:0] rd_drop;           // reads still to return that belong to an earlier entry (dropped)
	wire       in_valid = (f_have != 3'd0);
	wire [15:0] f_head  = fq[f_rp];
	wire [7:0] in_byte  = f_lo ? f_head[7:0] : f_head[15:8];

	// ------------------------------------------------------------------------------------------------ output: words
	reg [17:0] wb [0:3];          // {lanes {hi, lo}, data}: words waiting for the port, in order
	reg  [1:0] wb_wp, wb_rp;
	reg  [2:0] wb_n;
	reg [19:0] w_wa;              // the workspace word of the next write taken
	reg  [7:0] hb;                // the even byte of the word being assembled
	reg        hb_en;             // ... and whether it is written
	reg  [1:0] wr_out;            // writes taken and not yet acknowledged
	reg [20:0] acked;             // writes acknowledged since START (DEC_WORDS)

	wire       out_ok   = ~o[0] | (wb_n != 3'd4);                  // an odd byte completes a word: room needed

	// one output byte a clock at most
	reg        o_v;
	reg  [7:0] o_b;
	reg        o_en;
	reg  [7:0] hq;                // the history byte read for this clock
	wire       d1 = (cdist == 8'd1);
	always @* begin
		o_v  = 1'b0;
		o_b  = 8'h00;
		o_en = 1'b1;
		case (st)
			S_LIT:   begin o_v = in_valid & out_ok;      o_b = in_byte;          end
			S_FILL:  begin o_v = out_ok;                 o_b = fillv;            end
			S_COPY:  begin o_v = out_ok & (d1 | cp_ok);  o_b = d1 ? last : hq;   o_en = (cdist != 8'd0); end
			default: ;
		endcase
	end
	wire in_take = ((st == S_TYPE) | (st == S_TOK) | (st == S_PAR)) ? in_valid : (st == S_LIT) ? o_v : 1'b0;

	// the history: 256 bytes, written at o, read for the byte the NEXT clock produces (o + o_v - d). d = 1 reads the
	// byte being written this clock, so it comes from `last` instead; d >= 2 reads a byte written at least one edge
	// earlier, which the RAM returns. A copy's first clock reads with its new d and produces nothing (cp_ok).
	(* ramstyle = "M10K, no_rw_check" *) reg [7:0] ring [0:255];
	wire [7:0] h_ra = o[7:0] + {7'd0, o_v} - cdist;
	always @(posedge clk) begin
		if (o_v & o_en) ring[o[7:0]] <= o_b;
		hq <= ring[h_ra];
	end

	// ------------------------------------------------------------------------------------------------ the port
	wire       rd_ok    = decoding & (({1'b0, f_have} + {2'b00, rd_out}) < 4'd4);
	wire       rd_low   = (({1'b0, f_have} + {2'b00, rd_out}) < 4'd2);
	wire       wr_ok    = (wb_n != 3'd0) & (st != S_IDLE) & (st != S_DRAIN);
	wire       sel_rd   = rd_ok & (rd_low | ~wr_ok);               // a read first only when the input runs low
	wire       sel_wr   = wr_ok & ~sel_rd;
	wire [17:0] wb_head = wb[wb_rp];
	assign p2_valid = sel_rd | sel_wr;
	assign p2_we    = sel_wr;
	assign p2_lanes = sel_wr ? wb_head[17:16] : 2'b00;
	assign p2_addr  = sel_wr ? (24'h400000 + {4'd0, w_wa}) : {2'b00, rd_wa};
	assign p2_wdata = wb_head[15:0];
	assign p2_flush = (st == S_DRAIN);
	wire take_rd = p2_take & sel_rd;
	wire take_wr = p2_take & sel_wr;
	wire live    = running;                                        // completions count for this run
	wire ret_rd  = p2_rd_done;
	wire keep_rd = ret_rd & (rd_drop == 2'd0);

	// ------------------------------------------------------------------------------------------------ GO
	reg [20:0] delivered;         // window words delivered since START, up to the clock before this one
	wire [20:0] o_words  = {1'b0, o[20:1]};
	// The GO waits for a clock with no decoder store in flight: a store reaches paprium_regfile on its first bus clock
	// (fr_*) and this module one clock later (e_*), so a GO given on either clock would land before or with a later
	// START's stream invalidation, or race an abort. On the cart the firmware never writes these while a run ends.
	wire   quiet  = ~fr_f2 & ~fr_f6 & ~e_start & ~e_stop & ~e_clear & ~e_push;
	assign go     = (st == S_GO) & quiet;
	// The length leaves out a word the window delivers on the GO's own clock: paprium_regfile counts that one, with
	// word_delivered as the last select (it comes from clk_md: no arithmetic between it and a register here)
	assign go_len = (o_words > delivered) ? (o_words - delivered) : 21'd0;

	// ------------------------------------------------------------------------------------------------ flags / monitors
	reg        f_ovf, f_bad, f_d0, f_pre, f_late, f_abort, f_done;
	reg [23:0] t_cnt;             // cycles since START
	reg [23:0] t_time;            // DEC_TIME
	reg        t_valid;
	reg        m_arm, m_first_go, m_first_rd;
	reg [25:0] m_k;               // clocks since the first of the two events (GO, the first window word) after START
	reg [31:0] margin;
	reg [15:0] latecnt;
	wire [20:0] rel      = sptr - base;
	wire        late_now = TEST & word_delivered & (running | start_pend) & (rel >= {acked[19:0], 1'b0});
	wire        m_go_ev  = TEST & m_arm & go;
	wire        m_rd_ev  = TEST & m_arm & word_delivered;
	reg         m_take;
	reg  [31:0] m_val;
	reg         m_take_q;          // the sample, one clock later into the minimum (word_delivered is a clk_md input)
	reg  [31:0] m_val_q;
	always @* begin
		m_take = 1'b0;
		m_val  = 32'd0;
		if (m_go_ev & m_rd_ev & ~m_first_go & ~m_first_rd) begin m_take = 1'b1; m_val = 32'd0; end
		else if (m_go_ev & m_first_rd) begin m_take = 1'b1; m_val = -{6'd0, m_k}; end   // read first: negative
		else if (m_rd_ev & m_first_go) begin m_take = 1'b1; m_val = {6'd0, m_k}; end    // GO first: positive
	end

	// ------------------------------------------------------------------------------------------------ the sequencer
	wire ev_abort = running & (e_stop | e_clear | e_push | (e_start & (qn != 5'd0)));
	wire ev_any   = e_stop | e_clear | e_push | e_start;
	wire begin_ok = start_pend & ~ev_any & (st == S_IDLE);

	initial begin
		st = S_IDLE; qn = 5'd0; qhi = 7'd0; dec_base = 20'd0; start_pend = 1'b0;
		sptr_load = 1'b0; margin = 32'h7FFFFFFF; latecnt = 16'd0;
	end

	always @(posedge clk) begin
		if (reset) begin
			st <= S_IDLE;
			qn <= 5'd0;
			qhi <= 7'd0;
			dec_base <= 20'd0;
			start_pend <= 1'b0;
			sptr_load <= 1'b0;
			rd_out <= 2'd0; rd_drop <= 2'd0; wr_out <= 2'd0;
			f_have <= 3'd0; f_wp <= 2'd0; f_rp <= 2'd0; f_lo <= 1'b0;
			wb_n <= 3'd0; wb_wp <= 2'd0; wb_rp <= 2'd0;
			o <= 21'd0; acked <= 21'd0; delivered <= 21'd0; run_left <= 5'd0;
			f_ovf <= 1'b0; f_bad <= 1'b0; f_d0 <= 1'b0; f_pre <= 1'b0; f_late <= 1'b0; f_abort <= 1'b0; f_done <= 1'b0;
			t_cnt <= 24'd0; t_time <= 24'd0; t_valid <= 1'b0;
			m_k <= 26'd0; m_arm <= 1'b0; m_first_go <= 1'b0; m_first_rd <= 1'b0;
			margin <= 32'h7FFFFFFF; latecnt <= 16'd0; m_take_q <= 1'b0;
			cp_ok <= 1'b0; tail_done <= 1'b0;
		end
		else begin
			sptr_load <= 1'b0;
			cp_ok <= (st == S_COPY);

			// ---------------------------------------------------------------- the port's bookkeeping
			if (take_rd) rd_wa <= rd_wa + 22'd1;
			if (take_wr) begin
				wb_rp <= wb_rp + 2'd1;
				w_wa  <= w_wa + 20'd1;
			end
			rd_out <= rd_out + {1'b0, take_rd} - {1'b0, keep_rd};
			if (ret_rd & ~keep_rd) rd_drop <= rd_drop - 2'd1;
			wr_out <= wr_out + {1'b0, take_wr} - {1'b0, p2_wr_done};
			if (p2_wr_done & live) acked <= acked + 21'd1;
			if (keep_rd) fq[f_wp] <= p2_rdata;
			if (in_take) f_lo <= ~f_lo;
			f_wp   <= f_wp + {1'b0, keep_rd};
			f_rp   <= f_rp + {1'b0, in_take & f_lo};
			f_have <= f_have + {2'b00, keep_rd} - {2'b00, in_take & f_lo};

			// ---------------------------------------------------------------- output bytes -> words
			if (o_v) begin
				o    <= o + 21'd1;
				last <= o_b;
				if (~o[0]) begin
					hb    <= o_b;
					hb_en <= o_en;
				end
				else
					wb[wb_wp] <= {hb_en, o_en, hb, o_b};
			end
			wb_wp <= wb_wp + {1'b0, o_v & o[0]} + {1'b0, (st == S_TAIL) & ~tail_done & o[0] & (wb_n != 3'd4)};
			wb_n  <= wb_n + {2'b00, o_v & o[0]} + {2'b00, (st == S_TAIL) & ~tail_done & o[0] & (wb_n != 3'd4)}
			              - {2'b00, take_wr};
			// words of this START's stream: from the clock the window points at base (a word delivered on the clock the
			// pointer loads, or before, came from the stream before)
			if (sptr_load) delivered <= 21'd0;
			else if (word_delivered) delivered <= delivered + 21'd1;

			// ---------------------------------------------------------------- the decoder
			case (st)
				S_IDLE: if (begin_ok) begin
					start_pend <= 1'b0;
					run_left   <= pend_n;
					q_ra       <= pend_n[3:0] - 4'd1;   // pend_n = 16 -> entry 15
					st         <= S_QRD;
				end
				S_QRD: st <= S_QLAT;
				S_QLAT: begin
					rd_wa   <= q_rd;
					// the reads still out belong to the entry before: dropped as they return
					rd_drop <= rd_drop + rd_out - {1'b0, ret_rd};
					rd_out  <= 2'd0;
					f_have  <= 3'd0; f_wp <= 2'd0; f_rp <= 2'd0; f_lo <= 1'b0;
					st      <= S_TYPE;
				end
				S_TYPE: if (in_valid) begin
					if (in_byte == 8'h80) st <= S_TOK;
					else begin
						f_bad <= 1'b1;
						if (run_left > 5'd1) begin run_left <= run_left - 5'd1; q_ra <= q_ra - 4'd1; st <= S_QRD; end
						else begin run_left <= 5'd0; st <= S_TAIL; end
					end
				end
				S_TOK: if (in_valid) begin
					ty  <= in_byte[7:6];
					cnt <= in_byte[5:0];
					if (in_byte == 8'h00) begin                         // END: the next entry, or the run's tail
						if (run_left > 5'd1) begin run_left <= run_left - 5'd1; q_ra <= q_ra - 4'd1; st <= S_QRD; end
						else begin run_left <= 5'd0; st <= S_TAIL; end
					end
					else case (in_byte[7:6])
						2'd0: st <= S_LIT;
						2'd1, 2'd2: st <= S_PAR;
						default: begin fillv <= 8'h00; st <= (in_byte[5:0] == 6'd0) ? S_TOK : S_FILL; end
					endcase
				end
				S_PAR: if (in_valid) begin
					fillv <= in_byte;
					cdist <= in_byte;
					if (cnt == 6'd0) st <= S_TOK;                       // zero length: the operand only
					else if (ty == 2'd1) st <= S_FILL;
					else begin
						st <= S_COPY;
						if (in_byte == 8'h00) f_d0 <= 1'b1;
						if (o < {13'd0, in_byte}) f_pre <= 1'b1;
					end
				end
				S_LIT, S_FILL, S_COPY: if (o_v) begin
					cnt <= cnt - 6'd1;
					if (cnt == 6'd1) st <= S_TOK;
				end
				S_TAIL: begin
					if (~tail_done & o[0] & (wb_n != 3'd4)) begin
						wb[wb_wp] <= {hb_en, 1'b0, hb, 8'h00};
						tail_done <= 1'b1;
					end
					if ((tail_done | ~o[0]) & (wb_n == 3'd0) & (wr_out == 2'd0)) st <= S_GO;
				end
				S_GO: if (quiet) begin
					st      <= S_IDLE;
					f_done  <= 1'b1;
					t_time  <= t_cnt;
					t_valid <= 1'b1;
				end
				S_DRAIN: if (~p2_busy) begin
					// nothing of ours is staged or on the port: every count is 0 now
					rd_out <= 2'd0; rd_drop <= 2'd0; wr_out <= 2'd0;
					f_have <= 3'd0; f_wp <= 2'd0; f_rp <= 2'd0; f_lo <= 1'b0;
					st <= S_IDLE;
				end
				default: st <= S_IDLE;
			endcase

			// ---------------------------------------------------------------- register events (after the decoder:
			// an abort wins its clock)
			if (e_hi) qhi <= e_hiv;
			if (ev_abort) begin
				st <= S_DRAIN;
				f_abort <= 1'b1;
				wb_n <= 3'd0; wb_wp <= 2'd0; wb_rp <= 2'd0;
				m_arm <= 1'b0;
			end
			if (e_clear) begin
				qn <= 5'd0;
				if (start_pend) begin start_pend <= 1'b0; f_abort <= 1'b1; end
			end
			if (e_stop & start_pend) begin start_pend <= 1'b0; f_abort <= 1'b1; end
			if (e_push) begin
				if (start_pend) begin start_pend <= 1'b0; f_abort <= 1'b1; end
				if (qn[4]) f_ovf <= 1'b1;
				else qn <= qn + 5'd1;
			end
			if (e_start & (qn != 5'd0)) begin
				start_pend <= 1'b1;
				pend_n     <= qn;
				qn         <= 5'd0;
				base       <= {dec_base, 1'b0};
				sptr_load  <= 1'b1;
				sptr_val   <= {dec_base, 1'b0};
				o          <= 21'd0;
				acked      <= 21'd0;
				delivered  <= 21'd0;
				w_wa       <= dec_base;
				tail_done  <= 1'b0;
				f_done     <= 1'b0;
				t_cnt      <= 24'd0;
				t_valid    <= 1'b0;
				m_arm      <= TEST;
				m_k        <= 26'd0;
				m_first_go <= 1'b0;
				m_first_rd <= 1'b0;
			end

			// ---------------------------------------------------------------- monitors
			if (start_pend | running) begin
				if (t_cnt != 24'hFFFFFF) t_cnt <= t_cnt + 24'd1;
			end
			m_take_q <= 1'b0;
			if (m_arm & ~(e_start & (qn != 5'd0))) begin
				if ((m_first_go | m_first_rd) & (m_k != 26'h3FFFFFF)) m_k <= m_k + 26'd1;
				if (m_take) begin
					m_arm    <= 1'b0;
					m_take_q <= 1'b1;
					m_val_q  <= m_val;
				end
				else if (~m_first_go & ~m_first_rd) begin
					if (m_go_ev) begin m_first_go <= 1'b1; m_k <= 26'd1; end
					if (m_rd_ev) begin m_first_rd <= 1'b1; m_k <= 26'd1; end
				end
				if (fw_sptr_wr) m_arm <= 1'b0;
			end
			if (m_take_q & ($signed(m_val_q) < $signed(margin))) margin <= m_val_q;
			if (late_now) begin
				f_late <= 1'b1;
				if (latecnt != 16'hFFFF) latecnt <= latecnt + 16'd1;
			end

			// ---------------------------------------------------------------- FPGAIO writes
			if (fio_wr) begin
				case (fio_wslot)
					3'd0: dec_base <= fio_wdata[20:1];
					3'd1: begin
						if (fio_wdata[16]) f_ovf   <= 1'b0;
						if (fio_wdata[17]) f_bad   <= 1'b0;
						if (fio_wdata[18]) f_d0    <= 1'b0;
						if (fio_wdata[19]) f_pre   <= 1'b0;
						if (fio_wdata[20]) f_late  <= 1'b0;
						if (fio_wdata[21]) f_abort <= 1'b0;
					end
					3'd4: margin  <= 32'h7FFFFFFF;
					3'd5: latecnt <= 16'd0;
					default: ;
				endcase
			end
		end
	end

	// ------------------------------------------------------------------------------------------------ FPGAIO reads
	wire [31:0] stat = {10'd0, f_abort, f_late, f_pre, f_d0, f_bad, f_ovf, 4'd0, f_done, running,
	                    run_left, qn};
	always @* begin
		case (fio_rslot)
			3'd0:    fio_rdata = {11'd0, dec_base, 1'b0};
			3'd1:    fio_rdata = stat;
			3'd2:    fio_rdata = TEST ? {11'd0, acked} : 32'd0;
			3'd3:    fio_rdata = TEST ? {t_valid, 7'd0, t_time} : 32'd0;
			3'd4:    fio_rdata = TEST ? margin : 32'd0;
			3'd5:    fio_rdata = TEST ? {16'd0, latecnt} : 32'd0;
			default: fio_rdata = 32'hFFFF_FFFF;
		endcase
	end

endmodule
