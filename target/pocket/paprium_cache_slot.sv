// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// pocket: 0.3.0 synth step (test builds 4a / 4b, the 0.3.0 hardware test builds of the sound cache; the firmware's
// docs/MCU_INTERFACE.md v1.3 section 21.1) - the sound-cache data slot's board side.
//
// data.json slot id 20 "Sound cache" (index 2, bridge 0x60000000, nonvolatile, size_maximum 0x400000) is backed by
// CRAM die 0 bytes 0x000000-0x3FFFFF (CRAM = the Pocket's cellular RAM), the MCU's window 0x09000000-0x093FFFFF
// (MCU_INTERFACE.md 3.8). Three paths:
//
//   load   (setup, sys_reset held, the MCU not running): APF bridge writes to 0x6000_0000 + i go through the stock
//          data_loader (big-endian bridge words byte-reversed, two 16-bit halves, low half first, >= 24 clk_sys apart)
//          into CRAM port A-write as die word i / 2, so CRAM word 2k = {file byte 4k+1, file byte 4k} and the MCU sees
//          file byte i at 0x0900_0000 + i (MCU_INTERFACE finding 17). Only 0x6000_0000-0x603F_FFFF lands; `loaded`
//          counts the bytes that did (XLINK CACHE_LOADED: 2 per 16-bit half, i.e. 4 per bridge word, saturating at
//          0x7FFFFF, power-on reset only). A write the CRAM had to drop is counted by paprium_cram (XLINK LOST[31:16]).
//          The same loader also serves the SRAM image region 0x4xxxxxxx (SHARE = 1; it was core_top's own
//          xram_data_loader with the same word size and delay): its writes leave on xld_* for paprium_xram, never on
//          CRAM port A or in `loaded`. data.json has no slot at 0x4, so on this package the loader only ever sees
//          cache words; with both regions, each region's writes come out as its own loader's whenever the other is
//          not loading in the same ~1 us (the APF loads one data slot at a time).
//          With ROM_SHARE = 1 the same loader also serves the cartridge ROM region 0x1xxxxxxx (it was core_top's own
//          rom_data_loader: word size 2, delay 24, 25 address bits, clk_sys): its words go through the one FIFO with a
//          ROM bit and load only the loader's own ROM output registers (rom_wr / rom_addr / rom_data, for the
//          cartridge's download port), which hold between ROM words as the stock loader's did; ld_* and everything
//          below never move on a ROM word, and the flush side keys on BRIDGE_UPPER_4 only, as before.
//   flush  (Quit, power-off, sleep: Reset Enter first, then APF reads the nonvolatile slots, while the MCU reboots and
//          may already be busy on CRAM port B): APF bridge reads of 0x6xxx_xxxx are served from CRAM port A-read, whose
//          latency varies (it waits behind A-write, E and an aged MCU half), so the stock data_unloader's fixed delay
//          cannot be used. Instead clk_sys streams read-ahead words into a 4-entry ring from a start address clk_74a
//          gives it: a sequential flush is answered in the clock after each strobe, and the stream's rate (two CRAM
//          reads a word, one MCU half between them at worst) stays above the APF's word rate even with the MCU
//          reading or writing CRAM back to back. A read that is not the stream's next word (the first, or a jump)
//          restarts the stream at that word (a new epoch: words of an older epoch are dropped, a fetch in progress is
//          abandoned at its next half) and is answered when the word arrives; APF allows the data "up until the next
//          read strobe" (bus-communication). The stream reads ahead only when the read that restarted it was the word
//          after the read before it (sequential); after a jump it brings that one word and stops, so a run of jumps
//          never finds a useless read-ahead in the way of its word. A load write stops the stream and holds a restart for QUIET clk_74a, so
//          nothing read before the write lands is served after it (the APF never mixes the two; this keeps the rule
//          exact). Both halves of this path reset at power-on only, so a sys_reset in the middle of a flush changes
//          nothing.
//   size   the datatable word of slot index 2 (word 5): XLINK CACHE.VALID ? CACHE.SIZE : 0, in clk_74a. VALID and SIZE
//          are written once per power-on (one-shot, XLINK); SIZE is sampled here every clk_74a and used only when the
//          synchronised VALID has been 1 for a clock, by which time SIZE has been steady for >= 3 clk_74a. The
//          datatable has one core-side write port, so this module drives it: word 3 (the save's size, save_dt from
//          core_top) and word 5 alternate every clk_74a, each rewritten every other clock (wren is core_top's).
//
// clk_74a and clk_sys are asynchronous clock groups (core_constraints.sdc), so no crossing here is timed. Each crossing
// is a three-flop synchroniser of a level or of a Gray count that moves at most one step between two samples of the
// other clock, and every multi-bit value that goes with a count is held steady from before the count moves until the
// other side is done with it:
//   - the restart {epoch (2-bit Gray), start word, run, ahead}: clk_74a changes it at most every 4 clk_74a; clk_sys takes it
//     only after the synchronised epoch has held two clocks and re-checks the epoch after each CRAM half, dropping the
//     word if it moved (so a start word caught mid-change is never answered);
//   - the ring: clk_sys writes entry wcnt % 4 {word, its address, its epoch} in the clock it steps wcnt (3-bit Gray,
//     at most once per ~18 clk_sys); clk_74a reads the entry only after seeing the step, and steps rcnt (3-bit Gray) at
//     most every other clk_74a (one step per clk_sys sample); clk_sys rewrites an entry only after rcnt passed it.

module paprium_cache_slot #(
    parameter [3:0] BRIDGE_UPPER_4 = 4'h6,      // the slot's bridge region, 0x6xxx_xxxx (data.json "address")
    parameter [7:0] QUIET          = 8'd128,    // clk_74a after a load write before a restart (> the loader's ~1 us)
    parameter       SHARE          = 0,         // 1 = the loader also serves the SRAM image region (xld_*);
                                                // 0 (default) = the one-region slot, as before this logic saving
                                                // (core_top passes 1)
    parameter [3:0] SHARE_UPPER_4  = 4'h4,      // ... at 0x4xxx_xxxx (core_top's former xram_data_loader)
    parameter       ROM_SHARE      = 0,         // 1 = the loader also serves the cartridge ROM region (rom_*);
                                                // 0 (default) = as before (core_top passes 1)
    parameter [3:0] ROM_UPPER_4    = 4'h1       // ... at 0x1xxx_xxxx (core_top's former rom_data_loader)
) (
    input  wire        clk_74a,
    input  wire        reset_74a,               // power-on only (~pll_ever_locked)
    input  wire        clk_sys,                 // clk_sys_53_69
    input  wire        reset_sys,               // power-on only (xmem_reset), like paprium_cram

    // APF bridge, clk_74a
    input  wire        bridge_wr,
    input  wire        bridge_rd,
    input  wire        bridge_endian_little,
    input  wire [31:0] bridge_addr,
    input  wire [31:0] bridge_wr_data,
    output reg  [31:0] bridge_rd_data,          // core_top's read mux serves it for 32'h6xxxxxxx

    // XLINK CACHE (clk_sys) and the datatable words (clk_74a): 3 = save_dt, 5 = VALID ? SIZE : 0, alternating
    input  wire        cache_valid,
    input  wire [22:0] cache_size,
    input  wire [31:0] save_dt,
    output wire  [9:0] dt_addr,
    output wire [31:0] dt_data,

    // XLINK CACHE_LOADED (clk_sys)
    output reg  [22:0] loaded,

    // the SRAM image loader's writes (clk_sys, paprium_xram ld_*: byte address, 16-bit halves); 0 with SHARE = 0
    output wire        xld_wr,
    output wire [17:0] xld_addr,
    output wire [15:0] xld_data,

    // the ROM loader's writes (clk_sys, the cartridge's cart_dl_wr / addr / data: byte address, 16-bit halves,
    // registers held between writes); 0 with ROM_SHARE = 0
    output wire        rom_wr,
    output wire [24:0] rom_addr,
    output wire [15:0] rom_data,

    // paprium_cram port A (clk_sys)
    output wire        cr_wr,
    output wire [21:0] cr_waddr,
    output wire [15:0] cr_wdata,
    output reg         cr_rd,
    output reg  [21:0] cr_raddr,
    input  wire        cr_rd_done,
    input  wire [15:0] cr_rdata
);

  // ---- load: the stock loader, byte addresses, 16-bit halves (and the SRAM image region with SHARE) --------------
  wire        ld_en;
  wire [27:0] ld_addr;
  wire [15:0] ld_data;
  wire        ld_b;                             // the write is the SRAM image region's (SHARE only)

  data_loader #(
      .ADDRESS_MASK_UPPER_4 (BRIDGE_UPPER_4),
      .ADDRESS_SIZE         (28),               // all of bridge_addr[27:0]: a write past 4 MB is dropped, not aliased
      .OUTPUT_WORD_SIZE     (2),
      .WRITE_MEM_CLOCK_DELAY(24),               // as test build 4's CDDA / SRAM loaders: one CRAM write (<= 11 clocks) each
      .SECOND_REGION        (SHARE),
      .ADDRESS_MASK_UPPER_4_B(SHARE_UPPER_4),
      .ROM_REGION           (ROM_SHARE),
      .ADDRESS_MASK_UPPER_4_R(ROM_UPPER_4),
      .ADDRESS_SIZE_R       (25)                // the stock rom_data_loader's 25 bits (the cartridge SDRAM)
  ) cache_data_loader (
      .clk_74a   (clk_74a),
      .clk_memory(clk_sys),

      .bridge_wr           (bridge_wr),
      .bridge_endian_little(bridge_endian_little),
      .bridge_addr         (bridge_addr),
      .bridge_wr_data      (bridge_wr_data),

      .write_en  (ld_en),
      .write_addr(ld_addr),
      .write_data(ld_data),
      .write_b   (ld_b),

      .write_en_r  (rom_wr),
      .write_addr_r(rom_addr),
      .write_data_r(rom_data)
  );

  wire ld_in = ld_en & ~ld_b & (ld_addr[27:22] == 6'd0);   // bridge 0x6000_0000-0x603F_FFFF: the cache window
  assign xld_wr   = ld_en & ld_b;                   // bridge 0x4xxx_xxxx: as the 18-bit SRAM loader (it aliased too)
  assign xld_addr = (SHARE != 0) ? ld_addr[17:0] : 18'd0;
  assign xld_data = (SHARE != 0) ? ld_data : 16'd0;
  assign cr_wr    = ld_in;
  assign cr_waddr = {1'b0, ld_addr[21:1]};          // die word = byte / 2, inside the MCU window (die words < 0x200000)
  assign cr_wdata = ld_data;

  always @(posedge clk_sys) begin
    if (reset_sys) loaded <= 23'd0;
    else if (ld_in) loaded <= (loaded >= 23'h7FFFFE) ? 23'h7FFFFF : loaded + 23'd2;
  end

  // ---- size word for the datatable --------------------------------------------------------------------------
  wire        valid_s;
  reg         valid_q  = 1'b0;
  reg  [22:0] size_q   = 23'd0;
  reg         dt_phase = 1'b0;
  synch_3 cache_valid_sync (.i(cache_valid), .o(valid_s), .clk(clk_74a));
  always @(posedge clk_74a) begin
    valid_q  <= valid_s;
    size_q   <= cache_size;                         // quasi-static: written once, while VALID rises with it
    dt_phase <= ~dt_phase;
  end
  wire [31:0] dt_size = valid_q ? {9'd0, size_q} : 32'd0;
  assign dt_addr = dt_phase ? 10'd5 : 10'd3;        // data slot index 2's size word / index 1's (the save)
  assign dt_data = dt_phase ? dt_size : save_dt;

  // ---- flush: Gray helpers -------------------------------------------------------------------------------------
  function [1:0] g2next(input [1:0] g);             // 2-bit Gray 00 -> 01 -> 11 -> 10 -> 00
    g2next = {g[0], ~g[1]};
  endfunction
  function [2:0] b2g(input [2:0] b);  b2g = b ^ (b >> 1);                         endfunction
  function [2:0] g2b(input [2:0] g);  g2b = {g[2], g[2] ^ g[1], g[2] ^ g[1] ^ g[0]}; endfunction

  // ---- flush: the shared state ------------------------------------------------------------------------------
  // clk_74a -> clk_sys: the restart
  reg   [1:0] st_g    = 2'd0;                       // the epoch, one Gray step per restart
  reg  [19:0] st_addr = 20'd0;                      // its start word (32-bit word index in the 4 MB window)
  reg         st_run  = 1'b0;                       // 1 = stream from st_addr, 0 = stop
  reg         st_ahead = 1'b0;                      // 1 = read ahead (a sequential read asked); 0 = that one word only
  reg   [2:0] rcnt_g  = 3'd0;                       // entries consumed (Gray)
  // clk_sys -> clk_74a: the ring
  reg  [31:0] e_d  [0:3];                           // the word, {byte 4k+3, 4k+2, 4k+1, 4k}
  reg  [19:0] e_a  [0:3];                           // its address k
  reg   [1:0] e_ep [0:3];                           // its epoch
  reg   [2:0] wcnt_g  = 3'd0;                       // entries written (Gray)
  integer ii;
  initial for (ii = 0; ii < 4; ii = ii + 1) begin e_d[ii] = 32'd0; e_a[ii] = 20'd0; e_ep[ii] = 2'd0; end

  // ---- flush: clk_74a side ----------------------------------------------------------------------------------
  reg         prev_rd = 1'b0, prev_wr = 1'b0;
  wire        in_region = (bridge_addr[31:28] == BRIDGE_UPPER_4);
  wire        rd_strobe = bridge_rd & ~prev_rd & in_region;
  wire        wr_strobe = bridge_wr & ~prev_wr & in_region;
  wire [19:0] rq        = bridge_addr[21:2];          // the 32-bit word asked for

  wire  [2:0] wcnt_s;                                 // wcnt_g, synchronised
  reg   [2:0] rcnt   = 3'd0;                          // entries consumed (binary)
  reg         rhold  = 1'b0;                          // rcnt stepped last clock: no step this clock
  reg  [19:0] exp_a  = 20'd0;                         // the word the stream brings next (this epoch)
  reg         pend   = 1'b0;                          // a read strobe still waiting for its word
  reg  [19:0] pend_a = 20'd0;
  reg         pend_q = 1'b0;                          // ... and it was the word after the read before it (sequential)
  reg         last_v = 1'b0;                          // the previous read strobe's word, for "sequential"
  reg  [19:0] last_a = 20'd0;
  reg         defer  = 1'b0;                          // a restart owed (at pend_a)
  reg         stop   = 1'b0;                          // a stop owed (a load write came)
  reg   [7:0] quiet  = 8'd0;                          // clocks left before a restart after a load write
  reg   [1:0] space  = 2'd0;                          // clocks before another restart / stop may be sent

  synch_3 #(.WIDTH(3)) cache_wcnt_sync (.i(wcnt_g), .o(wcnt_s), .clk(clk_74a));

  wire  [2:0] avail  = g2b(wcnt_s) - rcnt;            // entries written and not yet consumed (0..4)
  wire  [1:0] hd     = rcnt[1:0];
  wire        head   = (avail != 3'd0);
  // the head belongs to the running stream (and no load write came since it was asked for)
  wire        h_cur  = head & (e_ep[hd] == st_g) & st_run & ~stop & (quiet == 8'd0);
  wire        h_old  = head & ~h_cur;                 // a word of an older epoch, a stopped stream or a load: drop it
  wire        can_r  = ~rhold;
  // this clock hands a waiting read its word (the ring chain below): no restart is sent in the same clock
  wire        r_give = ~rd_strobe & ~(can_r & h_old) & can_r & h_cur & pend & (e_a[hd] == pend_a);

  function [31:0] to_bridge(input [31:0] w, input little);   // {byte 3, 2, 1, 0} -> the bridge word
    to_bridge = little ? w : {w[7:0], w[15:8], w[23:16], w[31:24]};
  endfunction

  initial bridge_rd_data = 32'd0;

  always @(posedge clk_74a) begin
    prev_rd <= bridge_rd;
    prev_wr <= bridge_wr;
    rhold   <= 1'b0;
    if (reset_74a) begin
      st_g   <= 2'd0;
      st_run <= 1'b0;
      st_ahead <= 1'b0;
      last_v <= 1'b0;
      rcnt   <= 3'd0;
      rcnt_g <= 3'd0;
      pend   <= 1'b0;
      defer  <= 1'b0;
      stop   <= 1'b0;
      quiet  <= 8'd0;
      space  <= 2'd0;
      bridge_rd_data <= 32'd0;
    end
    else begin
      if (quiet != 8'd0) quiet <= quiet - 8'd1;
      if (space != 2'd0) space <= space - 2'd1;

      // the ring: a read strobe first, else drop an old head, else hand a waiting read its word. A stream asked for
      // by a read that was not sequential (st_ahead = 0) brings that one word only and then stops on both sides, so
      // a run of jumps never leaves a useless read-ahead in the way of the next jump's word
      if (rd_strobe) begin
        last_v <= 1'b1;
        last_a <= rq;
        if (can_r & h_cur & (e_a[hd] == rq)) begin  // the stream's next word is here: answer now
          bridge_rd_data <= to_bridge(e_d[hd], bridge_endian_little);
          pend  <= 1'b0;
          defer <= 1'b0;                            // (a restart owed for an earlier read is moot now)
          exp_a <= rq + 20'd1;
          if (~st_ahead) st_run <= 1'b0;            // a one-word stream is done
          rcnt  <= rcnt + 3'd1; rcnt_g <= b2g(rcnt + 3'd1); rhold <= 1'b1;
        end
        else begin
          pend   <= 1'b1;
          pend_a <= rq;
          pend_q <= last_v & (rq == last_a + 20'd1);
          // the running stream holds rq or fetches it next (the APF's next word, or the one after a read that was
          // late; for a one-word stream only its word): wait for it, which never costs more than one word; else (a
          // jump back or ahead, a stopped stream, a load write since) restart the stream there
          if (!(st_run & ~stop & (quiet == 8'd0) &
                ((rq == exp_a) | (st_ahead & ((rq - exp_a) <= {17'd0, avail} + 20'd1))))) defer <= 1'b1;
        end
      end
      else if (can_r & h_old) begin
        rcnt  <= rcnt + 3'd1; rcnt_g <= b2g(rcnt + 3'd1); rhold <= 1'b1;
      end
      else if (can_r & h_cur & pend) begin
        if (e_a[hd] == pend_a) begin                // the waiting read's word (r_give)
          bridge_rd_data <= to_bridge(e_d[hd], bridge_endian_little);
          pend  <= 1'b0;
          defer <= 1'b0;                            // the old stream brought it after all: no restart
          exp_a <= pend_a + 20'd1;
          if (~st_ahead) st_run <= 1'b0;            // a one-word stream is done
          rcnt  <= rcnt + 3'd1; rcnt_g <= b2g(rcnt + 3'd1); rhold <= 1'b1;
        end
        else if ((pend_a - e_a[hd]) < 20'd8) begin  // a word before it the APF went past (a read that was late)
          exp_a <= e_a[hd] + 20'd1;
          if (~st_ahead) begin st_run <= 1'b0; defer <= 1'b1; end   // a one-word stream will not bring it
          rcnt  <= rcnt + 3'd1; rcnt_g <= b2g(rcnt + 3'd1); rhold <= 1'b1;
        end
        else defer <= 1'b1;                         // the stream is past it: restart there
      end

      // the restart / stop channel (one change per four clocks; clk_sys takes a change once it has held)
      if (wr_strobe) begin                          // a load write: stop the stream, hold restarts for QUIET
        pend   <= 1'b0;
        defer  <= 1'b0;
        quiet  <= QUIET;
        stop   <= st_run | stop;
        last_v <= 1'b0;
      end
      else if (stop & (space == 2'd0)) begin
        st_g   <= g2next(st_g);
        st_run <= 1'b0;
        stop   <= 1'b0;
        space  <= 2'd3;
      end
      else if (defer & ~rd_strobe & ~r_give & (quiet == 8'd0) & (space == 2'd0)) begin
        st_g     <= g2next(st_g);                   // a restart at the waiting read's word
        st_addr  <= pend_a;
        st_run   <= 1'b1;
        st_ahead <= pend_q;                         // read ahead only for a sequential read
        exp_a    <= pend_a;
        defer   <= 1'b0;
        space   <= 2'd3;
      end
    end
  end

  // ---- flush: clk_sys side ----------------------------------------------------------------------------------
  wire  [1:0] st_s;
  wire  [2:0] rcnt_s;
  reg   [1:0] st_q   = 2'd0;                          // st_s a clock ago (a restart is taken once it has held)
  reg   [1:0] cur_ep = 2'd0;                          // the epoch being streamed
  reg         run    = 1'b0;
  reg         ahead  = 1'b0;                          // read ahead (else stop after the start word)
  reg  [19:0] cur_a  = 20'd0;                         // the next word to read
  reg   [2:0] wcnt   = 3'd0;                          // entries written (binary)
  reg  [15:0] d_lo   = 16'd0;
  reg   [1:0] fst    = 2'd0;

  synch_3 #(.WIDTH(2)) cache_st_sync   (.i(st_g),   .o(st_s),   .clk(clk_sys));
  synch_3 #(.WIDTH(3)) cache_rcnt_sync (.i(rcnt_g), .o(rcnt_s), .clk(clk_sys));

  wire  [2:0] used   = wcnt - g2b(rcnt_s);            // entries the ring holds (as far as clk_sys knows: 0..4)
  wire        room   = (used < 3'd4);
  wire        moved  = (st_s != cur_ep);              // a restart (or a stop) is waiting

  initial begin
    cr_rd    = 1'b0;
    cr_raddr = 22'd0;
  end

  always @(posedge clk_sys) begin
    cr_rd <= 1'b0;
    st_q  <= st_s;
    if (reset_sys) begin
      fst    <= 2'd0;
      cur_ep <= 2'd0;
      run    <= 1'b0;
      wcnt   <= 3'd0;
      wcnt_g <= 3'd0;
    end
    else case (fst)
      2'd0: begin
        if (moved) begin
          if (st_s == st_q) begin                   // held for two clocks: {start word, run, ahead} are steady
            cur_ep <= st_s;
            cur_a  <= st_addr;
            run    <= st_run;
            ahead  <= st_ahead;
          end
        end
        else if (run & room) begin
          cr_rd    <= 1'b1;
          cr_raddr <= {1'b0, cur_a, 1'b0};          // die word 2k: bytes 4k (low), 4k+1
          fst      <= 2'd1;
        end
      end
      2'd1: if (cr_rd_done) begin
        d_lo <= cr_rdata;
        if (moved) fst <= 2'd0;                     // a restart came: drop this word
        else begin
          cr_rd    <= 1'b1;
          cr_raddr <= {1'b0, cur_a, 1'b1};          // die word 2k+1: bytes 4k+2 (low), 4k+3
          fst      <= 2'd2;
        end
      end
      2'd2: if (cr_rd_done) begin
        if (!moved) begin
          e_d[wcnt[1:0]]  <= {cr_rdata, d_lo};
          e_a[wcnt[1:0]]  <= cur_a;
          e_ep[wcnt[1:0]] <= cur_ep;
          wcnt   <= wcnt + 3'd1;
          wcnt_g <= b2g(wcnt + 3'd1);                // with the entry: clk_74a reads it only after this step
          cur_a  <= cur_a + 20'd1;
          if (!ahead) run <= 1'b0;                  // a one-word stream (a jump's): done
        end
        fst <= 2'd0;
      end
      default: fst <= 2'd0;
    endcase
  end

endmodule
