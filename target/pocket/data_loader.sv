// Vendored from agg23/openfpga-NES target/pocket/data_loader.sv

// MIT License

// Copyright (c) 2022 Adam Gastineau

// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:

// The above copyright notice and this permission notice shall be included in all
// copies or substantial portions of the Software.

// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
// SOFTWARE.
//
////////////////////////////////////////////////////////////////////////////////

// A data loader for consuming APF bridge writes and directing them to some storage medium
//
// This takes the 32 bit words from APF, and splits it into four / OUTPUT_WORD_SIZE words (4 separate bytes, or 2 16-bit words).
// You can configure the cycle delay by setting WRITE_MEM_CLOCK_DELAY
// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)
module data_loader #(
    // Upper 4 bits of address
    parameter ADDRESS_MASK_UPPER_4 = 0,
    parameter ADDRESS_SIZE = 28,

    // Number of clk_memory cycles to delay each write output
    // Min 4. Component will assert this value is within the valid range
    // Be aware that APF sends data every ~75 74MHz cycles, so you cannot send data slower than this
    parameter WRITE_MEM_CLOCK_DELAY = 4,

    // Number of clk_memory cycles to hold the write_en signal high
    // Min 1. Component will assert this value is within the valid range
    parameter WRITE_MEM_EN_CYCLE_LENGTH = 1,

    // Word size in number of bytes. Can either be 1 (output 8 bits), or 2 (output 16 bits)
    // Component will assert this value is within the valid range
    parameter OUTPUT_WORD_SIZE = 1,

    // pocket: a second bridge region on the same loader (default 0: the stock loader, bit for bit). With 1, writes to
    // ADDRESS_MASK_UPPER_4_B are taken too and write_b tells them apart (one more FIFO bit); the two regions' words
    // go through the one FIFO in arrival order, so a region's writes come out as its own loader's would whenever the
    // other region is not loading in the same ~1 us (the APF loads one data slot at a time)
    parameter SECOND_REGION = 0,
    parameter ADDRESS_MASK_UPPER_4_B = 0,

    // pocket: a third bridge region with its OWN output registers write_en_r / write_addr_r / write_data_r (default
    // 0: none, the loader bit for bit as before). Its words go through the same FIFO with one more bit and load only
    // the _r registers, which hold between its words as that region's own stock loader's write_* would; the other
    // regions' write_* never move on its words (core_top's ROM region 0x1 served by the sound-cache slot's loader)
    parameter ROM_REGION = 0,
    parameter ADDRESS_MASK_UPPER_4_R = 0,
    parameter ADDRESS_SIZE_R = 28
) (
    input wire clk_74a,
    input wire clk_memory,

    input wire bridge_wr,
    input wire bridge_endian_little,
    input wire [31:0] bridge_addr,
    input wire [31:0] bridge_wr_data,

    // These outputs are synced to the memory clock
    output reg write_en = 0,
    output reg [ADDRESS_SIZE-1:0] write_addr = 0,
    output reg [8 * OUTPUT_WORD_SIZE - 1:0] write_data = 0,
    output reg write_b = 0,                  // pocket: this write is region B's (SECOND_REGION only, else 0)

    // pocket: the ROM_REGION's writes (synced to the memory clock like write_*; constant 0 without ROM_REGION)
    output wire write_en_r,
    output wire [ADDRESS_SIZE_R-1:0] write_addr_r,
    output wire [8 * OUTPUT_WORD_SIZE - 1:0] write_data_r
);

  `define MAX(x, y) ((x > y) ? x : y)

  localparam WORD_SIZE = 8 * OUTPUT_WORD_SIZE;

  // Only use the lower 28 bits of the address (pocket: plus the region bit with SECOND_REGION, and the ROM_REGION
  // bit on top with ROM_REGION)
  localparam FIFO_SIZE = WORD_SIZE + 28 + ((SECOND_REGION != 0) ? 1 : 0) + ((ROM_REGION != 0) ? 1 : 0);

  wire mem_empty;

  wire [FIFO_SIZE - 1:0] fifo_out;

  reg read_req = 0;
  reg write_req = 0;
  reg [31:0] shift_data;
  reg [27:0] buff_bridge_addr;
  reg buff_b = 0;

  wire hit_a = (bridge_addr[31:28] == ADDRESS_MASK_UPPER_4);
  wire hit_b = (SECOND_REGION != 0) && (bridge_addr[31:28] == ADDRESS_MASK_UPPER_4_B);
  wire hit_r = (ROM_REGION != 0) && (bridge_addr[31:28] == ADDRESS_MASK_UPPER_4_R);   // pocket
  wire buff_r;                               // pocket: the ROM_REGION bit of the word being written (rom_region)
  wire word_r;                               // pocket: the word read from the FIFO is the ROM_REGION's (rom_region)
  localparam B_BIT = FIFO_SIZE - 1 - ((ROM_REGION != 0) ? 1 : 0);   // pocket: region B's FIFO bit (SECOND_REGION)

  wire [FIFO_SIZE - 1:0] fifo_in;
  generate
    if (ROM_REGION != 0 && SECOND_REGION != 0) begin : three_regions   // pocket
      assign fifo_in = {buff_r, buff_b, shift_data[WORD_SIZE-1:0], buff_bridge_addr[27:0]};
    end
    else if (ROM_REGION != 0) begin : rom_and_a                        // pocket
      assign fifo_in = {buff_r, shift_data[WORD_SIZE-1:0], buff_bridge_addr[27:0]};
    end
    else if (SECOND_REGION != 0) begin : two_regions
      assign fifo_in = {buff_b, shift_data[WORD_SIZE-1:0], buff_bridge_addr[27:0]};
    end
    else begin : one_region
      assign fifo_in = {shift_data[WORD_SIZE-1:0], buff_bridge_addr[27:0]};
    end
  endgenerate

  dcfifo dcfifo_component (
      .data(fifo_in),
      .rdclk(clk_memory),
      .rdreq(read_req),
      .wrclk(clk_74a),
      .wrreq(write_req),
      .q(fifo_out),
      .rdempty(mem_empty)
      // .wrempty(),
      // .aclr(),
      // .eccstatus(),
      // .rdfull(),
      // .rdusedw(),
      // .wrfull(),
      // .wrusedw()
  );
  defparam dcfifo_component.clocks_are_synchronized = "FALSE",
      dcfifo_component.intended_device_family = "Cyclone V", dcfifo_component.lpm_numwords = 4,
      dcfifo_component.lpm_showahead = "OFF", dcfifo_component.lpm_type = "dcfifo",
      dcfifo_component.lpm_width = FIFO_SIZE, dcfifo_component.lpm_widthu = 2,
      dcfifo_component.overflow_checking = "OFF", dcfifo_component.rdsync_delaypipe = 5,
      dcfifo_component.underflow_checking = "OFF", dcfifo_component.use_eab = "OFF",
      dcfifo_component.wrsync_delaypipe = 5;

  /// APF to Mem clock

  localparam WRITE_NONE = 0;
  localparam WRITE_START = 1;
  localparam WRITE_REQ_SHIFT = 2;

  reg prev_bridge_wr = 0;
  reg [2:0] write_count = 0;
  reg [2:0] write_state = WRITE_NONE;

  // Receive APF writes and buffer them into the memory clock domain
  always @(posedge clk_74a) begin
    prev_bridge_wr <= bridge_wr;

    if (~prev_bridge_wr && bridge_wr && (hit_a || hit_b || hit_r)) begin
      // Beginning APF write to core
      write_state <= WRITE_REQ_SHIFT;
      write_req <= 1;
      write_count <= 0;

      shift_data <= bridge_endian_little ? bridge_wr_data : {
        bridge_wr_data[7:0], bridge_wr_data[15:8], bridge_wr_data[23:16], bridge_wr_data[31:24]
      };

      buff_bridge_addr <= bridge_addr[27:0];
      buff_b <= hit_b;
    end

    case (write_state)
      WRITE_START: begin
        write_req   <= 1;

        write_state <= WRITE_REQ_SHIFT;
      end
      WRITE_REQ_SHIFT: begin
        write_req <= 0;

        // We will be writing again in the next cycle
        shift_data <= {8'h0, shift_data[31:WORD_SIZE]};
        buff_bridge_addr <= buff_bridge_addr + OUTPUT_WORD_SIZE;

        write_count <= write_count + 1;

        if (write_count == (4 / OUTPUT_WORD_SIZE) - 1) begin
          // Finished write
          write_state <= WRITE_NONE;
        end else begin
          write_state <= WRITE_START;
        end
      end
    endcase
  end

  /// Mem clock to core

  reg [5:0] read_state = 0;

  localparam READ_DELAY = 1;
  localparam READ_WRITE = 2;
  localparam READ_WRITE_EN_CYCLE_OFF = READ_WRITE + WRITE_MEM_EN_CYCLE_LENGTH;
  localparam READ_WRITE_END_DEFAULT = WRITE_MEM_CLOCK_DELAY - 1;
  // Must use max to prevent READ_WRITE_END from being the same as READ_WRITE_EN_CYCLE_OFF
  localparam READ_WRITE_END =
  `MAX(READ_WRITE_END_DEFAULT, READ_WRITE_EN_CYCLE_OFF + 1);
  localparam HAS_DELAY = READ_WRITE_END_DEFAULT > READ_WRITE_EN_CYCLE_OFF;

  always @(posedge clk_memory) begin
    if (read_state != 0) begin
      read_state <= read_state + 1;
    end else if (~mem_empty) begin
      // Start read
      read_state <= READ_DELAY;
      read_req   <= 1;
    end

    case (read_state)
      READ_DELAY: begin
        read_req <= 0;
        write_en <= 0;
      end
      READ_WRITE: begin
        //  Read data is available
        if (!word_r) begin                   // pocket: a ROM_REGION word loads write_*_r instead (rom_region)
        write_en   <= 1;

        // Lowest 28 bits are the address
        write_addr <= fifo_out[27:0];

        write_data <= fifo_out[WORD_SIZE+27:28];

        if (SECOND_REGION != 0) write_b <= fifo_out[B_BIT];
        end

        read_req   <= 0;
      end
      READ_WRITE_EN_CYCLE_OFF: begin
        write_en <= 0;

        if (!HAS_DELAY) begin
          // No extra delay, immediately go back to start
          read_state <= 0;
        end
      end
      READ_WRITE_END: begin
        read_state <= 0;
      end
    endcase
  end

  // pocket: the ROM_REGION. Its bit is taken with buff_b's own strobe and kept for both halves; its output registers
  // step exactly as write_* do above (on in READ_WRITE, off in READ_DELAY and READ_WRITE_EN_CYCLE_OFF) but only on its
  // words, so between its words they hold, as that region's own loader's would
  generate
    if (ROM_REGION != 0) begin : rom_region
      reg buff_r_q = 0;
      reg write_en_q = 0;
      reg [ADDRESS_SIZE_R-1:0] write_addr_q = 0;
      reg [WORD_SIZE-1:0] write_data_q = 0;

      always @(posedge clk_74a) begin
        if (~prev_bridge_wr && bridge_wr && (hit_a || hit_b || hit_r)) buff_r_q <= hit_r;
      end

      always @(posedge clk_memory) begin
        if (read_state == READ_DELAY || read_state == READ_WRITE_EN_CYCLE_OFF) write_en_q <= 0;
        if (read_state == READ_WRITE && word_r) begin
          write_en_q   <= 1;
          write_addr_q <= fifo_out[ADDRESS_SIZE_R-1:0];
          write_data_q <= fifo_out[WORD_SIZE+27:28];
        end
      end

      assign buff_r       = buff_r_q;
      assign word_r       = fifo_out[FIFO_SIZE-1];
      assign write_en_r   = write_en_q;
      assign write_addr_r = write_addr_q;
      assign write_data_r = write_data_q;
    end
    else begin : no_rom_region
      assign buff_r       = 1'b0;
      assign word_r       = 1'b0;
      assign write_en_r   = 1'b0;
      assign write_addr_r = {ADDRESS_SIZE_R{1'b0}};
      assign write_data_r = {WORD_SIZE{1'b0}};
    end
  endgenerate

  initial begin
    // Verify parameters
    if (WRITE_MEM_CLOCK_DELAY < 4) begin
      $error("WRITE_MEM_CLOCK_DELAY has a minimum value of 4. Received %d", WRITE_MEM_CLOCK_DELAY);
    end

    if (WRITE_MEM_EN_CYCLE_LENGTH < 1 || WRITE_MEM_EN_CYCLE_LENGTH >= WRITE_MEM_CLOCK_DELAY - 2) begin
      $error(
          "WRITE_MEM_EN_CYCLE_LENGTH must be between 1 and %d (inclusive, based off of WRITE_MEM_CLOCK_DELAY). Received %d",
          WRITE_MEM_CLOCK_DELAY - 2 - 1, WRITE_MEM_EN_CYCLE_LENGTH);
    end

    if (OUTPUT_WORD_SIZE < 1 || OUTPUT_WORD_SIZE > 2) begin
      $error("OUTPUT_WORD_SIZE must be 1 or 2. Received %d", OUTPUT_WORD_SIZE);
    end
  end

endmodule
