//
// Pocket integration shell around md_board.v: PLL, reset, ROM download, pads,
// video, audio.
//
// The module port list below is open-fpga/core-template src/fpga/core/core_top.v
// verbatim: apf_top.v fixes it and it cannot change. The body follows the layout of
// agg23/openfpga-NES target/pocket/core_top.v, with its save_state_controller,
// pll_reconfig and nes_top replaced by this core. Everything outside a marked region
// comes from one of those two, the port list and unused-peripheral tie-offs included.
//
// Savestates are left out (framework.sleep_supported = false). Adding them starts
// in the core, not here: MegaDrive_MiSTer ships no savestate engine, so one has to
// be written first (README, "Not included").
//

`default_nettype none

module core_top (

    //
    // physical connections
    //

    ///////////////////////////////////////////////////
    // clock inputs 74.25mhz. not phase aligned, so treat these domains as asynchronous

    input wire clk_74a,  // mainclk1
    input wire clk_74b,  // mainclk1

    ///////////////////////////////////////////////////
    // cartridge interface
    // switches between 3.3v and 5v mechanically
    // output enable for multibit translators controlled by pic32

    // GBA AD[15:8]
    inout  wire [7:0] cart_tran_bank2,
    output wire       cart_tran_bank2_dir,

    // GBA AD[7:0]
    inout  wire [7:0] cart_tran_bank3,
    output wire       cart_tran_bank3_dir,

    // GBA A[23:16]
    inout  wire [7:0] cart_tran_bank1,
    output wire       cart_tran_bank1_dir,

    // GBA [7] PHI#
    // GBA [6] WR#
    // GBA [5] RD#
    // GBA [4] CS1#/CS#
    //     [3:0] unwired
    inout  wire [7:4] cart_tran_bank0,
    output wire       cart_tran_bank0_dir,

    // GBA CS2#/RES#
    inout  wire cart_tran_pin30,
    output wire cart_tran_pin30_dir,
    output wire cart_pin30_pwroff_reset,

    // GBA IRQ/DRQ
    inout  wire cart_tran_pin31,
    output wire cart_tran_pin31_dir,

    // infrared
    input  wire port_ir_rx,
    output wire port_ir_tx,
    output wire port_ir_rx_disable,

    // GBA link port
    inout  wire port_tran_si,
    output wire port_tran_si_dir,
    inout  wire port_tran_so,
    output wire port_tran_so_dir,
    inout  wire port_tran_sck,
    output wire port_tran_sck_dir,
    inout  wire port_tran_sd,
    output wire port_tran_sd_dir,

    ///////////////////////////////////////////////////
    // cellular psram 0 and 1, two chips (64mbit x2 dual die per chip)

    output wire [21:16] cram0_a,
    inout  wire [ 15:0] cram0_dq,
    input  wire         cram0_wait,
    output wire         cram0_clk,
    output wire         cram0_adv_n,
    output wire         cram0_cre,
    output wire         cram0_ce0_n,
    output wire         cram0_ce1_n,
    output wire         cram0_oe_n,
    output wire         cram0_we_n,
    output wire         cram0_ub_n,
    output wire         cram0_lb_n,

    output wire [21:16] cram1_a,
    inout  wire [ 15:0] cram1_dq,
    input  wire         cram1_wait,
    output wire         cram1_clk,
    output wire         cram1_adv_n,
    output wire         cram1_cre,
    output wire         cram1_ce0_n,
    output wire         cram1_ce1_n,
    output wire         cram1_oe_n,
    output wire         cram1_we_n,
    output wire         cram1_ub_n,
    output wire         cram1_lb_n,

    ///////////////////////////////////////////////////
    // sdram, 512mbit 16bit

    output wire [12:0] dram_a,
    output wire [ 1:0] dram_ba,
    inout  wire [15:0] dram_dq,
    output wire [ 1:0] dram_dqm,
    output wire        dram_clk,
    output wire        dram_cke,
    output wire        dram_ras_n,
    output wire        dram_cas_n,
    output wire        dram_we_n,

    ///////////////////////////////////////////////////
    // sram, 1mbit 16bit

    output wire [16:0] sram_a,
    inout  wire [15:0] sram_dq,
    output wire        sram_oe_n,
    output wire        sram_we_n,
    output wire        sram_ub_n,
    output wire        sram_lb_n,

    ///////////////////////////////////////////////////
    // vblank driven by dock for sync in a certain mode

    input wire vblank,

    ///////////////////////////////////////////////////
    // i/o to 6515D breakout usb uart

    output wire dbg_tx,
    input  wire dbg_rx,

    ///////////////////////////////////////////////////
    // i/o pads near jtag connector user can solder to

    output wire user1,
    input  wire user2,

    ///////////////////////////////////////////////////
    // RFU internal i2c bus

    inout  wire aux_sda,
    output wire aux_scl,

    ///////////////////////////////////////////////////
    // RFU, do not use
    output wire vpll_feed,


    //
    // logical connections
    //

    ///////////////////////////////////////////////////
    // video, audio output to scaler
    output wire [23:0] video_rgb,
    output wire        video_rgb_clock,
    output wire        video_rgb_clock_90,
    output wire        video_de,
    output wire        video_skip,
    output wire        video_vs,
    output wire        video_hs,

    output wire audio_mclk,
    input  wire audio_adc,
    output wire audio_dac,
    output wire audio_lrck,

    ///////////////////////////////////////////////////
    // bridge bus connection
    // synchronous to clk_74a
    output wire        bridge_endian_little,
    input  wire [31:0] bridge_addr,
    input  wire        bridge_rd,
    output reg  [31:0] bridge_rd_data,
    input  wire        bridge_wr,
    input  wire [31:0] bridge_wr_data,

    ///////////////////////////////////////////////////
    // controller data
    //
    // key bitmap:
    //   [0]    dpad_up
    //   [1]    dpad_down
    //   [2]    dpad_left
    //   [3]    dpad_right
    //   [4]    face_a
    //   [5]    face_b
    //   [6]    face_x
    //   [7]    face_y
    //   [8]    trig_l1
    //   [9]    trig_r1
    //   [10]   trig_l2
    //   [11]   trig_r2
    //   [12]   trig_l3
    //   [13]   trig_r3
    //   [14]   face_select
    //   [15]   face_start
    //   [31:28] type
    // joy values - unsigned
    //   [ 7: 0] lstick_x
    //   [15: 8] lstick_y
    //   [23:16] rstick_x
    //   [31:24] rstick_y
    // trigger values - unsigned
    //   [ 7: 0] ltrig
    //   [15: 8] rtrig
    //
    input wire [31:0] cont1_key,
    input wire [31:0] cont2_key,
    input wire [31:0] cont3_key,
    input wire [31:0] cont4_key,
    input wire [31:0] cont1_joy,
    input wire [31:0] cont2_joy,
    input wire [31:0] cont3_joy,
    input wire [31:0] cont4_joy,
    input wire [15:0] cont1_trig,
    input wire [15:0] cont2_trig,
    input wire [15:0] cont3_trig,
    input wire [15:0] cont4_trig

);

  // not using the IR port, so turn off both the LED, and
  // disable the receive circuit to save power
  assign port_ir_tx              = 0;
  assign port_ir_rx_disable      = 1;

  assign bridge_endian_little    = 0;

  // cart is unused, so set all level translators accordingly
  // directions are 0:IN, 1:OUT
  assign cart_tran_bank3         = 8'hzz;
  assign cart_tran_bank3_dir     = 1'b0;
  assign cart_tran_bank2         = 8'hzz;
  assign cart_tran_bank2_dir     = 1'b0;
  assign cart_tran_bank1         = 8'hzz;
  assign cart_tran_bank1_dir     = 1'b0;
  assign cart_tran_bank0         = 4'hf;
  assign cart_tran_bank0_dir     = 1'b1;
  assign cart_tran_pin30         = 1'b0;
  assign cart_tran_pin30_dir     = 1'bz;
  assign cart_pin30_pwroff_reset = 1'b0;
  assign cart_tran_pin31         = 1'bz;
  assign cart_tran_pin31_dir     = 1'b0;

  // link port unused, tristate everything
  assign port_tran_so            = 1'bz;
  assign port_tran_so_dir        = 1'b0;
  assign port_tran_si            = 1'bz;
  assign port_tran_si_dir        = 1'b0;
  assign port_tran_sck           = 1'bz;
  assign port_tran_sck_dir       = 1'b0;
  assign port_tran_sd            = 1'bz;
  assign port_tran_sd_dir        = 1'b0;

  // tie off PSRAM, unused (ROM lives in SDRAM)
  assign cram0_a                 = 'h0;
  assign cram0_dq                = {16{1'bZ}};
  assign cram0_clk               = 0;
  assign cram0_adv_n             = 1;
  assign cram0_cre               = 0;
  assign cram0_ce0_n             = 1;
  assign cram0_ce1_n             = 1;
  assign cram0_oe_n              = 1;
  assign cram0_we_n              = 1;
  assign cram0_ub_n              = 1;
  assign cram0_lb_n              = 1;

  assign cram1_a                 = 'h0;
  assign cram1_dq                = {16{1'bZ}};
  assign cram1_clk               = 0;
  assign cram1_adv_n             = 1;
  assign cram1_cre               = 0;
  assign cram1_ce0_n             = 1;
  assign cram1_ce1_n             = 1;
  assign cram1_oe_n              = 1;
  assign cram1_we_n              = 1;
  assign cram1_ub_n              = 1;
  assign cram1_lb_n              = 1;

  // tie off SRAM, unused
  assign sram_a                  = 'h0;
  assign sram_dq                 = {16{1'bZ}};
  assign sram_oe_n               = 1;
  assign sram_we_n               = 1;
  assign sram_ub_n               = 1;
  assign sram_lb_n               = 1;

  assign dbg_tx                  = 1'bZ;
  assign user1                   = 1'bZ;
  assign aux_scl                 = 1'bZ;
  assign vpll_feed               = 1'bZ;


  // pocket: four bitstreams, not one. The MD master clock is baked into the PLL, so PAL
  // is a hand-edited twin of the generated mf_pllbase and generate.tcl picks between
  // them with this parameter; it is not runtime settable. SVP swaps the cartridge's
  // save hardware for Virtua Racing's DSP, which the device cannot fit next to the
  // full core, and the Chip32 loader picks that build by cartridge serial. The wire
  // names carry the NTSC figures in both regions. dram_clk is not driven here either,
  // rtl/upstream/sdram.sv drives it off its own altddio_out
  parameter PAL = 1'b0;
  parameter SVP = 1'b0;
// paprium: a third variant. It swaps the general mapper and save hardware for the
// Paprium cartridge subsystem, and is NTSC-only: the MCU's CLOCK_FREQUENCY generic and
// CLK_FREQ are 53.693 MHz, so building it PAL would put every clock-derived figure in
// the firmware out by 0.9%
  parameter PAPRIUM = 1'b0;
  // Diagnostic switch: drop the cartridge PCM engine to buy ~700 ALMs. Shipping is 1
  parameter PAPRIUM_SFX = 1'b1;
  // Diagnostic build: report openfile's outcome as playback duration. Shipping is 0.
  parameter PAPRIUM_CDDA_DBG = 1'b0;
// paprium-end


  //
  // clocks
  //

  // VCO = 644.3181 MHz NTSC, 638.441088 MHz PAL, every MD clock is an integer
  // divide of it. The wire names carry the NTSC figures in both. Both dot rates get
  // their own counter pair, VCO/96 for H40 and VCO/120 for H32, so the scaler is fed
  // one PLL edge per real dot in either mode; the video section muxes them
  wire clk_sys_53_69;
  wire clk_md_107_39;
  wire clk_vid_6_71;
  wire clk_vid_6_71_90deg;
  wire clk_vid_5_37;
  wire clk_vid_5_37_90deg;
  wire pll_core_locked;
  wire pll_core_locked_s;

  synch_3 pll_lock_sync (
      .i  (pll_core_locked),
      .o  (pll_core_locked_s),
      .clk(clk_74a)
  );

  // Latched, so a later lock dip does not re-reset the core
  reg pll_ever_locked = 0;
  always @(posedge clk_74a) begin
    if (pll_core_locked_s) begin
      pll_ever_locked <= 1;
    end
  end

  generate
    if (PAL) begin
      mf_pllbase_pal mp1 (
          .refclk(clk_74a),
          .rst   (0),

          .outclk_0(clk_sys_53_69),       // VCO/12, MD master clock
          .outclk_1(clk_md_107_39),       // VCO/6, md_board MCLK2 and SDRAM
          .outclk_2(clk_vid_6_71),        // VCO/96, H40 dot clock
          .outclk_3(clk_vid_6_71_90deg),  // video DDR
          .outclk_4(clk_vid_5_37),        // VCO/120, H32 dot clock
          .outclk_5(clk_vid_5_37_90deg),

          .locked(pll_core_locked)
      );
    end else begin
      mf_pllbase mp1 (
          .refclk(clk_74a),
          .rst   (0),

          .outclk_0(clk_sys_53_69),
          .outclk_1(clk_md_107_39),
          .outclk_2(clk_vid_6_71),
          .outclk_3(clk_vid_6_71_90deg),
          .outclk_4(clk_vid_5_37),
          .outclk_5(clk_vid_5_37_90deg),

          .locked(pll_core_locked)
      );
    end
  endgenerate

  // dram_clk comes out of sdram.sv on clk_md_107_39 (datain_h=0/datain_l=1, inverted)
  // pocket-end


  //
  // host/target command handler
  //

  wire        reset_n;
  wire [31:0] cmd_bridge_rd_data;

  wire        status_boot_done = pll_core_locked_s;
  wire        status_setup_done = pll_core_locked_s;
  wire        status_running = reset_n;

  wire        dataslot_requestread;
  wire [15:0] dataslot_requestread_id;
  wire        dataslot_requestread_ack = 1;
  wire        dataslot_requestread_ok = 1;

  wire        dataslot_requestwrite;
  wire [15:0] dataslot_requestwrite_id;
  wire [31:0] dataslot_requestwrite_size;
  wire        dataslot_requestwrite_ack = 1;
  wire        dataslot_requestwrite_ok = 1;

  wire        dataslot_update;
  wire [15:0] dataslot_update_id;
  wire [31:0] dataslot_update_size;

  wire        dataslot_allcomplete;

  wire [31:0] rtc_epoch_seconds;
  wire [31:0] rtc_date_bcd;
  wire [31:0] rtc_time_bcd;
  wire        rtc_valid;

  // No savestates, so tie the handshake off and keep framework.sleep_supported
  // false in core.json, or the OS will try to sleep this core
  wire        savestate_supported = 0;
  wire [31:0] savestate_addr = 0;
  wire [31:0] savestate_size = 0;
  wire [31:0] savestate_maxloadsize = 0;

  wire        savestate_start;
  wire        savestate_start_ack = 0;
  wire        savestate_start_busy = 0;
  wire        savestate_start_ok = 0;
  wire        savestate_start_err = 0;

  wire        savestate_load;
  wire        savestate_load_ack = 0;
  wire        savestate_load_busy = 0;
  wire        savestate_load_ok = 0;
  wire        savestate_load_err = 0;

  wire        osnotify_inmenu;

  // No saves and nothing else to write back, so no target dataslot commands
  // paprium: driven by paprium_cdda_fetch in the Paprium builds, 0 elsewhere
  wire        target_dataslot_read;
  wire        target_dataslot_write = 0;
  wire        target_dataslot_getfile = 0;
  wire        target_dataslot_openfile = 0;   // paprium: openfile is not used

  wire        target_dataslot_ack;
  wire        target_dataslot_done;
  wire [ 2:0] target_dataslot_err;

  wire [15:0] target_dataslot_id;
  wire [31:0] target_dataslot_slotoffset;
  wire [31:0] target_dataslot_bridgeaddr;
  wire [31:0] target_dataslot_length;

  wire [31:0] target_buffer_param_struct = 0;
  wire [31:0] target_buffer_resp_struct = 0;

  // pocket: APF creates a .sav for every game unless the slot size reads back 0, so
  // datatable[3] follows the cartridge's own SRAM/EEPROM detect instead of a constant.
  // 64 KB is the whole cartridge SRAM window
  wire        sram_present_74a;
  wire        eeprom_present_74a;

  // paprium: the Paprium save is the MCU-managed 4 KB backup RAM, not a 64 KB cart SRAM.
  // APF sizes the .sav file from this, and paprium_backup only decodes 12 address bits,
  // so a 64 KB slot would wrap 16 times over the array and corrupt the save on load
  localparam [31:0] SAVE_SIZE = PAPRIUM ? 32'h1000 : 32'h10000;
  wire [ 9:0] datatable_addr = 10'd3;
  wire        datatable_wren = pll_core_locked_s;
  wire [31:0] datatable_data = (sram_present_74a | eeprom_present_74a) ? SAVE_SIZE : 32'd0;
  // pocket-end
  wire [31:0] datatable_q;

  core_bridge_cmd icb (

      .clk    (clk_74a),
      .reset_n(reset_n),

      .bridge_endian_little(bridge_endian_little),
      .bridge_addr         (bridge_addr),
      .bridge_rd           (bridge_rd),
      .bridge_rd_data      (cmd_bridge_rd_data),
      .bridge_wr           (bridge_wr),
      .bridge_wr_data      (bridge_wr_data),

      .status_boot_done (status_boot_done),
      .status_setup_done(status_setup_done),
      .status_running   (status_running),

      .dataslot_requestread    (dataslot_requestread),
      .dataslot_requestread_id (dataslot_requestread_id),
      .dataslot_requestread_ack(dataslot_requestread_ack),
      .dataslot_requestread_ok (dataslot_requestread_ok),

      .dataslot_requestwrite     (dataslot_requestwrite),
      .dataslot_requestwrite_id  (dataslot_requestwrite_id),
      .dataslot_requestwrite_size(dataslot_requestwrite_size),
      .dataslot_requestwrite_ack (dataslot_requestwrite_ack),
      .dataslot_requestwrite_ok  (dataslot_requestwrite_ok),

      .dataslot_update     (dataslot_update),
      .dataslot_update_id  (dataslot_update_id),
      .dataslot_update_size(dataslot_update_size),

      .dataslot_allcomplete(dataslot_allcomplete),

      .rtc_epoch_seconds(rtc_epoch_seconds),
      .rtc_date_bcd     (rtc_date_bcd),
      .rtc_time_bcd     (rtc_time_bcd),
      .rtc_valid        (rtc_valid),

      .savestate_supported  (savestate_supported),
      .savestate_addr       (savestate_addr),
      .savestate_size       (savestate_size),
      .savestate_maxloadsize(savestate_maxloadsize),

      .savestate_start     (savestate_start),
      .savestate_start_ack (savestate_start_ack),
      .savestate_start_busy(savestate_start_busy),
      .savestate_start_ok  (savestate_start_ok),
      .savestate_start_err (savestate_start_err),

      .savestate_load     (savestate_load),
      .savestate_load_ack (savestate_load_ack),
      .savestate_load_busy(savestate_load_busy),
      .savestate_load_ok  (savestate_load_ok),
      .savestate_load_err (savestate_load_err),

      .osnotify_inmenu(osnotify_inmenu),

      .target_dataslot_read    (target_dataslot_read),
      .target_dataslot_write   (target_dataslot_write),
      .target_dataslot_getfile (target_dataslot_getfile),
      .target_dataslot_openfile(target_dataslot_openfile),

      .target_dataslot_ack (target_dataslot_ack),
      .target_dataslot_done(target_dataslot_done),
      .target_dataslot_err (target_dataslot_err),

      .target_dataslot_id        (target_dataslot_id),
      .target_dataslot_slotoffset(target_dataslot_slotoffset),
      .target_dataslot_bridgeaddr(target_dataslot_bridgeaddr),
      .target_dataslot_length    (target_dataslot_length),

      .target_buffer_param_struct(target_buffer_param_struct),
      .target_buffer_resp_struct (target_buffer_resp_struct),

      .datatable_addr(datatable_addr),
      .datatable_wren(datatable_wren),
      .datatable_data(datatable_data),
      .datatable_q   (datatable_q)

  );


  //
  // settings
  //

  wire [31:0] save_rd_data;

  always @(*) begin
    casex (bridge_addr)
      32'h2xxxxxxx: begin
        bridge_rd_data <= save_rd_data;
      end
      32'hF8xxxxxx: begin
        bridge_rd_data <= cmd_bridge_rd_data;
      end
      default: begin
        bridge_rd_data <= 0;
      end
    endcase
  end

  // pocket: one register per interact.json option this core exposes, plus the loader's
  // download flag and the region byte it reads out of the cart header. detected_jap
  // keeps a register of its own so a loader write and a menu write cannot race, and the
  // CDC below carries only what the console actually needs on its own clocks.
  // rom_download is held by the loader around the cartridge loadf and has to end before
  // the save slot lands, because the cartridge clears its save SRAM over that window
  reg rom_download = 0;

  // 0 auto, 1 Japan, 2 export
  reg [1:0] cfg_region = 0;
  // Region the loader read out of the header, only consulted in auto. It lives in
  // its own register rather than sharing cfg_region's, so the loader write and the
  // menu write cannot race
  reg detected_jap = 0;

  wire cfg_jap = (cfg_region == 2'd0) ? detected_jap : (cfg_region == 2'd1);

  // 0 Model 1, 1 Model 2, 2 minimal, 3 none
  reg [1:0] cfg_lpf = 0;
  // 0 YM2612 ladder DAC, 1 YM3438
  reg cfg_fm = 0;

  // Defaults to 6-button because that is what this core has always presented, and
  // the Pocket has the face buttons for it. A handful of games misread the pad
  reg cfg_6btn = 1;

  // The dot the VDP puts in the left column when CRAM is written mid-line
  reg cfg_cramdot = 0;

  // Composite-style horizontal blend (cofi), the MiSTer Composite Blend option
  reg cfg_blend = 0;

  // MiSTer's h40corr. video_cond takes it as an input, but there it only picks a row of
  // the arx/ary table, and the Pocket reads its aspect out of video.json instead. So the
  // bit picks a scaler slot here and video_cond's own port stays tied off
  reg cfg_arcorr = 0;

  localparam [13:0] RESET_PULSE = 14'd8000;  // ~108 us at 74.25 MHz

  reg  [13:0] reset_counter = 0;
  wire        core_reset = (reset_counter != 0);

  always @(posedge clk_74a) begin
    if (reset_counter != 0) begin
      reset_counter <= reset_counter - 1'd1;
    end

    if (bridge_wr) begin
      casex (bridge_addr)
        32'h00000000: begin
          rom_download <= bridge_wr_data[0];
        end
        32'h0000000C: begin
          cfg_region <= bridge_wr_data[1:0];
        end
        32'h00000018: begin
          detected_jap <= bridge_wr_data[0];
        end
        32'h00000010: begin
          cfg_lpf <= bridge_wr_data[1:0];
        end
        32'h00000014: begin
          cfg_fm <= bridge_wr_data[0];
        end
        32'h0000001C: begin
          cfg_6btn <= bridge_wr_data[0];
        end
        32'h00000020: begin
          cfg_cramdot <= bridge_wr_data[0];
        end
        32'h00000024: begin
          cfg_blend <= bridge_wr_data[0];
        end
        32'h00000028: begin
          cfg_arcorr <= bridge_wr_data[0];
        end
        32'hF0000000: begin
          reset_counter <= RESET_PULSE;
        end
      endcase
    end
  end

  wire       reset_n_s;
  wire       core_reset_s;
  wire       dataslot_allcomplete_s;
  wire [1:0] cfg_lpf_s;
  wire       cfg_fm_s;
  wire       cfg_6btn_s;
  wire       inmenu_sys_s;

  synch_3 #(
      .WIDTH(8)
  ) settings_sync (
      .i({reset_n, core_reset, dataslot_allcomplete, cfg_lpf, cfg_fm, cfg_6btn, osnotify_inmenu}),
      .o({
        reset_n_s,
        core_reset_s,
        dataslot_allcomplete_s,
        cfg_lpf_s,
        cfg_fm_s,
        cfg_6btn_s,
        inmenu_sys_s
      }),
      .clk(clk_sys_53_69)
  );
  // pocket-end


  //
  // reset
  //

  // pocket: md_board wants ext_reset held for the whole load and released 3 steps after
  // the last event, and reset_button held long enough for the console's own reset
  // detector to see it, so one core_hold wire is not enough. dataslot_allcomplete reads
  // 0 out of reset and rises once every slot is in, which is what keeps the console
  // down until the first cartridge has landed in SDRAM; under Chip32 the loader owns
  // the sequencing, so the envelope covers its flag too. ram_clear_addr does double
  // duty as the work RAM clear address, and sys_reset is the clk_sys_53_69 view of the
  // same envelope
  wire loading_74a = ~dataslot_allcomplete | rom_download;
  wire reset_req_74a = ~reset_n | core_reset | ~pll_ever_locked;

  wire loading_s;
  wire md_reset_req_s;
  wire cfg_jap_s;
  wire rom_download_s;
  wire cfg_cramdot_s;
  wire cfg_blend_s;
  wire inmenu_md_s;

  synch_3 #(
      .WIDTH(7)
  ) md_settings_sync (
      .i({
        loading_74a, reset_req_74a, cfg_jap, rom_download, cfg_cramdot, cfg_blend, osnotify_inmenu
      }),
      .o({
        loading_s,
        md_reset_req_s,
        cfg_jap_s,
        rom_download_s,
        cfg_cramdot_s,
        cfg_blend_s,
        inmenu_md_s
      }),
      .clk(clk_md_107_39)
  );

  reg        btn_reset = 0;
  reg        md_reset = 0;
  reg        shell_reset = 0;
  reg [15:1] ram_clear_addr = 0;
  reg [ 4:0] reset_delay_count = 0;
  reg        prev_md_reset_req = 0;

  always @(posedge clk_md_107_39) begin
    ram_clear_addr <= ram_clear_addr + 1'd1;
    if (&ram_clear_addr & ~&reset_delay_count) begin
      reset_delay_count <= reset_delay_count + 1'd1;
    end

    prev_md_reset_req <= md_reset_req_s;
    if (loading_s | (~prev_md_reset_req & md_reset_req_s)) begin
      reset_delay_count <= 0;
    end

    shell_reset <= (reset_delay_count < 3);

    if (loading_s) begin
      md_reset <= 1;
    end else if (reset_delay_count == 3) begin
      md_reset <= 0;
    end

    if (~prev_md_reset_req & md_reset_req_s) begin
      btn_reset <= 1;
    end else if (&reset_delay_count) begin
      btn_reset <= 0;
    end
  end

  reg       sys_reset = 0;
  reg [1:0] shell_reset_sync = 0;

  always @(posedge clk_sys_53_69) begin
    shell_reset_sync <= {shell_reset_sync[0], shell_reset};
    if (!shell_reset_sync) begin
      sys_reset <= 0;
    end
    if (&shell_reset_sync) begin
      sys_reset <= 1;
    end
  end
  // pocket-end


  //
  // ROM download
  //

  // pocket: the ROM lands in the cartridge's own SDRAM, so the address is 25 bits and
  // there is no back-pressure to honour: APF delivers one word per ~54 clk_sys_53_69
  // and a port 0 write takes ~4. dataslot_allcomplete can still rise while the last
  // words drain out of the loader, so cart_dl is held past the final write
  wire        ioctl_wr;
  wire [24:0] ioctl_addr;
  wire [15:0] ioctl_data;

  data_loader #(
      .ADDRESS_MASK_UPPER_4 (4'h1),
      .ADDRESS_SIZE         (25),
      .OUTPUT_WORD_SIZE     (2),
      .WRITE_MEM_CLOCK_DELAY(24)
  ) rom_data_loader (
      .clk_74a   (clk_74a),
      .clk_memory(clk_sys_53_69),

      .bridge_wr           (bridge_wr),
      .bridge_endian_little(bridge_endian_little),
      .bridge_addr         (bridge_addr),
      .bridge_wr_data      (bridge_wr_data),

      .write_en  (ioctl_wr),
      .write_addr(ioctl_addr),
      .write_data(ioctl_data)
  );

  reg [11:0] cart_dl_hold = 0;

  always @(posedge clk_sys_53_69) begin
    if (ioctl_wr) begin
      cart_dl_hold <= 12'hFFF;
    end else if (cart_dl_hold) begin
      cart_dl_hold <= cart_dl_hold - 1'd1;
    end
  end

  wire        cart_dl = ~dataslot_allcomplete_s | (cart_dl_hold != 0);
  // pocket-end


  //
  // saves
  //

  // pocket: the save RAM lives inside cartridge.sv, so this is its port and not a RAM
  // here: 16 address bits for the 64 KB cartridge SRAM window, one bus muxed between
  // load and unload, and the present flags synced back to clk_74a for the datatable
  wire [15:0] save_write_addr;
  wire [15:0] save_read_addr;
  wire [ 7:0] save_di;
  wire [ 7:0] save_do;
  wire        save_wr;

  wire [15:0] save_addr = save_wr ? save_write_addr : save_read_addr;

  // Both delays: the block RAM answers in 1 clk_sys_53_69, 4 for margin
  data_loader #(
      .ADDRESS_MASK_UPPER_4 (4'h2),
      .ADDRESS_SIZE         (16),
      .OUTPUT_WORD_SIZE     (1),
      .WRITE_MEM_CLOCK_DELAY(4)
  ) save_data_loader (
      .clk_74a   (clk_74a),
      .clk_memory(clk_sys_53_69),

      .bridge_wr           (bridge_wr),
      .bridge_endian_little(bridge_endian_little),
      .bridge_addr         (bridge_addr),
      .bridge_wr_data      (bridge_wr_data),

      .write_en  (save_wr),
      .write_addr(save_write_addr),
      .write_data(save_di)
  );

  data_unloader #(
      .ADDRESS_MASK_UPPER_4(4'h2),
      .ADDRESS_SIZE        (16),
      .INPUT_WORD_SIZE     (1),
      .READ_MEM_CLOCK_DELAY(4)
  ) save_data_unloader (
      .clk_74a   (clk_74a),
      .clk_memory(clk_sys_53_69),

      .bridge_rd           (bridge_rd),
      .bridge_endian_little(bridge_endian_little),
      .bridge_addr         (bridge_addr),
      .bridge_rd_data      (save_rd_data),

      .read_en  (),
      .read_addr(save_read_addr),
      .read_data(save_do)
  );

  wire        sram_present;
  wire        eeprom_present;
  wire        ym2612_quirk;

  synch_3 sram_present_sync (
      .i  (sram_present),
      .o  (sram_present_74a),
      .clk(clk_74a)
  );

  synch_3 eeprom_present_sync (
      .i  (eeprom_present),
      .o  (eeprom_present_74a),
      .clk(clk_74a)
  );
  // pocket-end


  //
  // cartridge
  //

  // pocket: cartridge.sv owns the SDRAM controller, so the dram_* pins leave the shell
  // here instead of being tied off with the rest. Holding both buses is the closest
  // this core gets to a pause: the 68k request waits for the Z80 to be off the bus and
  // for any VDP DMA to retire, so a transfer in flight is never cut short
  wire [23:1] cart_addr;
  wire [15:0] cart_data;
  wire [15:0] cart_data_wr;
  wire        cart_cs;
// paprium: two strobes now, muxed below. The stock core uses the VDP early DMA OE to
// hide SDRAM latency on ordinary ROM reads. Paprium's 0xC000-0xFFFF window is not an
// ordinary read: every accepted one advances the cart FPGA private stream pointer, so a
// speculative early phase that never delivers a word still consumes one and desyncs the
// stream. Paprium takes the real cartridge OE (CAS0) instead
  wire        cart_oe_raw;
  wire        cart_oe_early;
  wire        cart_oe;
// paprium-end
  wire        cart_lwr;
  wire        cart_uwr;
  wire        cart_time;
  wire        cart_dma;
  wire        cart_data_en;
  wire        cart_dtack;

  reg         pause_req = 0;
  reg         dma_68k_req = 0;
  reg         dma_z80_req = 0;

  wire        dma_z80_ack;
  wire        res_z80;

  always @(posedge clk_md_107_39) begin
    pause_req <= inmenu_md_s;

    if (pause_req & ~md_reset & ~btn_reset & ~loading_s) begin
      dma_z80_req <= 1;
      if ((dma_z80_ack | res_z80) & ~cart_dma) begin
        dma_68k_req <= 1;
      end
    end else begin
      dma_68k_req <= 0;
      dma_z80_req <= 0;
    end
  end

  // paprium: the signals crossing between the Paprium cartridge subsystem and this
  // level. The mdp_* group is the MCU's MD+ background-music command channel; on
  // MiSTer it drives the core's on-chip MD+ engine, which this build does not
  // compile. Nothing consumes it yet - the APF CDDA streamer that will answer it is
  // still to be written - so mdp_playing reads back 0 and the firmware sees every
  // track as already finished. Sound effects work regardless; they are the cart's own
  // PCM engine, not CDDA
  wire        paprium_active;
  wire        paprium_md_reset;
  wire signed [15:0] paprium_sfx_l;
  wire signed [15:0] paprium_sfx_r;

  wire        mdp_track_request;
  wire  [7:0] mdp_track_num;
  wire        mdp_track_loop;
  wire        mdp_stop_request;
  wire  [7:0] mdp_fade_sectors;
  wire        mdp_resume_request;
  wire  [7:0] mdp_volume;
  wire        mdp_volume_request;
  wire        mdp_active;

  wire        md_reset_effective = md_reset | (paprium_active & paprium_md_reset);

  // Paprium reads the real cartridge OE; everything else keeps the early DMA strobe
  assign      cart_oe = paprium_active ? cart_oe_raw : cart_oe_early;

  // ==========================================================================
  // paprium: CDDA background music. Replaces MiSTer's HPS-fed DDR3 ring with an
  // APF data slot the core drives itself - see docs/CDDA_DESIGN.md.
  //
  //   fetch (clk_74a)  openfile + chunked reads -> BRIDGE 0x3xxxxxxx
  //   data_loader      catches those writes, crosses to clk_sys
  //   buf              ring, 16-bit in / 32-bit out, chunk flow control
  //   play (clk_sys)   48 kHz consume, fade, volume, pause
  // ==========================================================================
  wire signed [15:0] cdda_l;
  wire signed [15:0] cdda_r;
  wire        [15:0] cdda_underruns;
  wire               mdp_playing;
  wire        [7:0]  mdp_current_track;

  generate
  if(PAPRIUM) begin : cdda

    localparam CDDA_CHUNK  = 4096;
    localparam CDDA_CHUNKS = 4;      // 16 KB, ~85 ms at 48 kHz
    // PAPRIUM_CDDA_DBG reports openfile's error code as playback duration - see the
    // parameter comment in paprium_cdda_fetch.sv. Shipping is 0.
    localparam CDDA_DIAG   = PAPRIUM_CDDA_DBG;

    // The 8-byte header entry lands in its own tiny bridge region so it cannot be
    // confused with audio arriving in the ring.
    wire        cdda_hdr_wr_en;
    wire  [2:0] cdda_hdr_wr_addr;
    wire [15:0] cdda_hdr_wr_data;

    data_loader #(
        .ADDRESS_MASK_UPPER_4 (4'h5),
        .ADDRESS_SIZE         (3),      // one 8-byte entry
        .OUTPUT_WORD_SIZE     (2),
        .WRITE_MEM_CLOCK_DELAY(24)
    ) cdda_hdr_loader (
        .clk_74a   (clk_74a),
        .clk_memory(clk_74a),           // the fetch sequencer lives in this domain

        .bridge_wr           (bridge_wr),
        .bridge_endian_little(bridge_endian_little),
        .bridge_addr         (bridge_addr),
        .bridge_wr_data      (bridge_wr_data),

        .write_en  (cdda_hdr_wr_en),
        .write_addr(cdda_hdr_wr_addr),
        .write_data(cdda_hdr_wr_data)
    );

    // ---- command channel across to the bridge domain -------------------
    // mdp_track_request and mdp_stop_request are single clk_sys pulses. A
    // toggle survives the crossing where a pulse would not; synch_3 hands back
    // both edges, so either one is a request.
    reg  trk_toggle = 0, stop_toggle = 0;
    always @(posedge clk_sys_53_69) begin
      if(mdp_track_request) trk_toggle  <= ~trk_toggle;
      if(mdp_stop_request)  stop_toggle <= ~stop_toggle;
    end

    wire trk_rise, trk_fall, stop_rise, stop_fall;
    synch_3 trk_synch (.i(trk_toggle),  .o(), .clk(clk_74a), .rise(trk_rise),  .fall(trk_fall));
    synch_3 stop_synch(.i(stop_toggle), .o(), .clk(clk_74a), .rise(stop_rise), .fall(stop_fall));

    // track_num and track_loop are written alongside the request and held until
    // the next one, so they are stable long before the toggle lands.
    wire [7:0] trk_num_s;
    wire       trk_loop_s;
    synch_3 #(.WIDTH(8)) trk_num_synch (.i(mdp_track_num), .o(trk_num_s), .clk(clk_74a));
    synch_3            trk_loop_synch(.i(mdp_track_loop), .o(trk_loop_s), .clk(clk_74a));

    wire [15:0] wr_chunk_gray, rd_chunk_gray;
    wire        fetch_playing;
    wire  [7:0] fetch_track;

    paprium_cdda_fetch #(
        .CHUNK_BYTES(CDDA_CHUNK),
        .NUM_CHUNKS (CDDA_CHUNKS),
        .DIAG_MODE  (CDDA_DIAG)
    ) cdda_fetch (
        .clk_74a(clk_74a),
        .reset  (~pll_core_locked_s),

        .track_request(trk_rise | trk_fall),
        .track_num    (trk_num_s),
        .track_loop   (trk_loop_s),
        .stop_request (stop_rise | stop_fall),


        .target_dataslot_read      (target_dataslot_read),
        .target_dataslot_ack       (target_dataslot_ack),
        .target_dataslot_done      (target_dataslot_done),
        .target_dataslot_err       (target_dataslot_err),
        .target_dataslot_id        (target_dataslot_id),
        .target_dataslot_slotoffset(target_dataslot_slotoffset),
        .target_dataslot_bridgeaddr(target_dataslot_bridgeaddr),
        .target_dataslot_length    (target_dataslot_length),

        .hdr_wr_en  (cdda_hdr_wr_en),
        .hdr_wr_addr(cdda_hdr_wr_addr),
        .hdr_wr_data(cdda_hdr_wr_data),

        .rd_chunk_gray(rd_chunk_gray[2:0]),
        .wr_chunk_gray(wr_chunk_gray[2:0]),

        .playing      (fetch_playing),
        .current_track(fetch_track)
    );

    // ---- landing buffer ------------------------------------------------
    wire        cdda_wr_en;
    wire [13:0] cdda_wr_addr;
    wire [15:0] cdda_wr_data;

    data_loader #(
        .ADDRESS_MASK_UPPER_4 (4'h3),
        .ADDRESS_SIZE         (14),     // 16 KB ring
        .OUTPUT_WORD_SIZE     (2),
        .WRITE_MEM_CLOCK_DELAY(24)
    ) cdda_data_loader (
        .clk_74a   (clk_74a),
        .clk_memory(clk_sys_53_69),

        .bridge_wr           (bridge_wr),
        .bridge_addr         (bridge_addr),
        .bridge_wr_data      (bridge_wr_data),

        .write_en  (cdda_wr_en),
        .write_addr(cdda_wr_addr),
        .write_data(cdda_wr_data)
    );

    wire [12:0] ring_rd_ptr;
    wire [31:0] ring_rd_data;
    wire [12:0] ring_fill;
    wire        ring_consumed;

    paprium_cdda_buf #(
        .CHUNK_BYTES(CDDA_CHUNK),
        .NUM_CHUNKS (CDDA_CHUNKS)
    ) cdda_buf (
        .clk  (clk_sys_53_69),
        .reset(sys_reset),

        .wr_en  (cdda_wr_en),
        .wr_addr(cdda_wr_addr[13:1]),   // data_loader gives a byte address
        .wr_data(cdda_wr_data),

        .wr_chunk_gray(wr_chunk_gray[2:0]),
        .rd_chunk_gray(rd_chunk_gray[2:0]),

        .rd_ptr         (ring_rd_ptr),
        .rd_data        (ring_rd_data),
        .sample_consumed(ring_consumed),
        .fill_level     (ring_fill),

        .flush(mdp_track_request)
    );

    paprium_cdda_play #(
        .RING_SAMPLES(CDDA_CHUNK * CDDA_CHUNKS / 4)
    ) cdda_play (
        .clk  (clk_sys_53_69),
        .reset(sys_reset),

        .active        (mdp_active),
        .track_start   (mdp_track_request),
        .stop_request  (mdp_stop_request),
        .fade_sectors  (mdp_fade_sectors),
        .volume        (mdp_volume),
        .resume_request(mdp_resume_request),
        .osd_pause     (1'b0),

        .rd_ptr         (ring_rd_ptr),
        .rd_data        (ring_rd_data),
        .fill_level     (ring_fill),
        .sample_consumed(ring_consumed),

        .underruns(cdda_underruns),
        .audio_l  (cdda_l),
        .audio_r  (cdda_r)
    );

    // ---- status back to the MCU ----------------------------------------
    synch_3            playing_synch(.i(fetch_playing), .o(mdp_playing), .clk(clk_sys_53_69));
    synch_3 #(.WIDTH(8)) track_synch(.i(fetch_track), .o(mdp_current_track), .clk(clk_sys_53_69));

  end
  else begin : no_cdda
    assign target_dataslot_read       = 0;
    assign target_dataslot_id         = 0;
    assign target_dataslot_slotoffset = 0;
    assign target_dataslot_bridgeaddr = 0;
    assign target_dataslot_length     = 0;
    assign cdda_l                     = 0;
    assign cdda_r                     = 0;
    assign cdda_underruns             = 0;
    assign mdp_playing                = 0;
    assign mdp_current_track          = 0;
  end
  endgenerate
  // paprium-end
  // paprium-end

  cartridge #(
      .SVP(SVP),
      .PAPRIUM(PAPRIUM),
      .PAPRIUM_SFX(PAPRIUM_SFX)
  ) cartridge (
      .clk        (clk_sys_53_69),
      .clk_ram    (clk_md_107_39),
      .reset      (sys_reset),
      .reset_sdram(~pll_core_locked),

      .SDRAM_CLK (dram_clk),
      .SDRAM_CKE (dram_cke),
      .SDRAM_A   (dram_a),
      .SDRAM_BA  (dram_ba),
      .SDRAM_DQ  (dram_dq),
      .SDRAM_DQML(dram_dqm[0]),
      .SDRAM_DQMH(dram_dqm[1]),
      .SDRAM_nCS (),             // Pocket SDRAM has no CS pin (always selected)
      .SDRAM_nCAS(dram_cas_n),
      .SDRAM_nRAS(dram_ras_n),
      .SDRAM_nWE (dram_we_n),

      .cart_dl       (cart_dl),
      .cart_dl_addr  (ioctl_addr),
      .cart_dl_data  (ioctl_data),
      .cart_dl_wr    (ioctl_wr),
      .cart_dl_wait  (),
      .sram_present  (sram_present),
      .eeprom_present(eeprom_present),
      .ym2612_quirk  (ym2612_quirk),

      .cart_ms     (1'b0),          // MD mode only, same reason md_board.M3 is tied high
      .cart_addr   (cart_addr),
      .cart_data   (cart_data),
      .cart_data_wr(cart_data_wr),
      .cart_cs     (cart_cs),
      .cart_oe     (cart_oe),
      .cart_lwr    (cart_lwr),
      .cart_uwr    (cart_uwr),
      .cart_time   (cart_time),
      .cart_data_en(cart_data_en),
      .cart_dtack  (cart_dtack),
      .cart_dma    (cart_dma),

      .save_clear (rom_download_s),
      .save_addr  (save_addr),
      .save_di    (save_di),
      .save_do    (save_do),
      .save_wr    (save_wr),
      .save_change(),               // MiSTer uses it to schedule a save writeback, APF does not

      // paprium: mdp_playing and mdp_current_track are the CDDA engine's status back to
      // the MCU. Tied off until the streamer exists, which makes the firmware treat every
      // requested track as finished immediately
      .paprium_active  (paprium_active),
      .paprium_md_reset(paprium_md_reset),
      .paprium_sfx_l   (paprium_sfx_l),
      .paprium_sfx_r   (paprium_sfx_r),

      .mdp_track_request (mdp_track_request),
      .mdp_track_num     (mdp_track_num),
      .mdp_track_loop    (mdp_track_loop),
      .mdp_stop_request  (mdp_stop_request),
      .mdp_fade_sectors  (mdp_fade_sectors),
      .mdp_resume_request(mdp_resume_request),
      .mdp_volume        (mdp_volume),
      .mdp_volume_request(mdp_volume_request),
      .mdp_active        (mdp_active),
      .mdp_playing       (mdp_playing),
      .mdp_current_track (mdp_current_track),
      // paprium-end

      .md_addr()                    // MiSTer's cheat engine watches the bus, this port has none
  );
  // pocket-end


  //
  // work RAM
  //

  // pocket: md_board expects the 68000 and Z80 RAM outside itself and clears neither,
  // so both are cleared here through port B while md_reset is asserted. The Z80 side
  // clears to RET, which is what the Titan 2 bug needs to read
  wire [14:0] ram_68k_address;
  wire [ 1:0] ram_68k_byteena;
  wire [15:0] ram_68k_data;
  wire        ram_68k_wren;
  wire [15:0] ram_68k_o;

  wire [12:0] ram_z80_address;
  wire [ 7:0] ram_z80_data;
  wire        ram_z80_wren;
  wire [ 7:0] ram_z80_o;

  dpram #(
      .addr_width(15),
      .data_width(16)
  ) ram_68k (
      .clock(clk_md_107_39),

      .address_a(ram_68k_address),
      .data_a   (ram_68k_data),
      .wren_a   (ram_68k_wren),
      .byteena_a(ram_68k_byteena),
      .q_a      (ram_68k_o),

      .address_b(ram_clear_addr),
      .wren_b   (md_reset)
  );

  dpram #(
      .addr_width(13),
      .data_width(8)
  ) ram_z80 (
      .clock(clk_md_107_39),

      .address_a(ram_z80_address),
      .data_a   (ram_z80_data),
      .wren_a   (ram_z80_wren),
      .q_a      (ram_z80_o),

      .address_b(ram_clear_addr),
      .wren_b   (md_reset),
      .data_b   (8'hC7)            // RET, works around the Titan 2 bug
  );
  // pocket-end


  //
  // pads
  //

  // pocket: two pads straight onto the MD controller ports, no md_io.sv, because
  // nothing on the Pocket needs its multitap, keyboard, lightgun or J-Cart muxing. MD
  // A-B-C lands on Y-B-A as on the fpgagen Genesis core, and the EXT port reads back
  // whatever the console drives, since there is nothing plugged into it
  wire [31:0] cont1_key_s;
  wire [31:0] cont2_key_s;

  synch_3 #(
      .WIDTH(32)
  ) cont1_sync (
      .i  (cont1_key),
      .o  (cont1_key_s),
      .clk(clk_sys_53_69)
  );

  synch_3 #(
      .WIDTH(32)
  ) cont2_sync (
      .i  (cont2_key),
      .o  (cont2_key_s),
      .clk(clk_sys_53_69)
  );

  wire [6:0] PA_i;
  wire [6:0] PA_o;
  wire [6:0] PA_d;
  wire [6:0] PB_i;
  wire [6:0] PB_o;
  wire [6:0] PB_d;
  wire [6:0] PC_i;
  wire [6:0] PC_o;
  wire [6:0] PC_d;

  // port_out drives the console's port input, so pad to MD
  pad_io pad1 (
      .clk  (clk_sys_53_69),
      .reset(sys_reset),

      .MODE(cfg_6btn_s),
      .SMS (1'b0),

      .P_UP   (cont1_key_s[0]),
      .P_DOWN (cont1_key_s[1]),
      .P_LEFT (cont1_key_s[2]),
      .P_RIGHT(cont1_key_s[3]),
      // MD A-B-C lands on Y-B-A, as on the fpgagen Genesis core
      .P_C    (cont1_key_s[4]),
      .P_B    (cont1_key_s[5]),
      .P_A    (cont1_key_s[7]),
      .P_Y    (cont1_key_s[6]),
      .P_X    (cont1_key_s[8]),
      .P_Z    (cont1_key_s[9]),
      .P_MODE (cont1_key_s[14]),
      .P_START(cont1_key_s[15]),

      .GUN_EN    (1'b0),
      .GUN_TYPE  (1'b0),
      .GUN_SENSOR(1'b0),
      .GUN_A     (1'b0),
      .GUN_B     (1'b0),
      .GUN_C     (1'b0),
      .GUN_START (1'b0),

      .MOUSE_EN   (1'b0),
      .MOUSE_FLIPY(1'b0),
      .MOUSE      (25'd0),

      .port_out(PA_i),
      .port_in (PA_o),
      .port_dir(PA_d)
  );

  pad_io pad2 (
      .clk  (clk_sys_53_69),
      .reset(sys_reset),

      .MODE(cfg_6btn_s),
      .SMS (1'b0),

      .P_UP   (cont2_key_s[0]),
      .P_DOWN (cont2_key_s[1]),
      .P_LEFT (cont2_key_s[2]),
      .P_RIGHT(cont2_key_s[3]),
      .P_C    (cont2_key_s[4]),
      .P_B    (cont2_key_s[5]),
      .P_A    (cont2_key_s[7]),
      .P_Y    (cont2_key_s[6]),
      .P_X    (cont2_key_s[8]),
      .P_Z    (cont2_key_s[9]),
      .P_MODE (cont2_key_s[14]),
      .P_START(cont2_key_s[15]),

      .GUN_EN    (1'b0),
      .GUN_TYPE  (1'b0),
      .GUN_SENSOR(1'b0),
      .GUN_A     (1'b0),
      .GUN_B     (1'b0),
      .GUN_C     (1'b0),
      .GUN_START (1'b0),

      .MOUSE_EN   (1'b0),
      .MOUSE_FLIPY(1'b0),
      .MOUSE      (25'd0),

      .port_out(PB_i),
      .port_in (PB_o),
      .port_dir(PB_d)
  );

  assign PC_i = PC_d | PC_o;
  // pocket-end

  //
  // console
  //

  // pocket: the shell instantiates md_board.v rather than a MiSTer top, so the work
  // RAM, cartridge and pad wiring above is the shell's job instead of the core's.
  // cart_oe is muxed between the real CAS0 and vdp_dma_oe_early - see the paprium note
  // above the declarations. TMSS
  // stays bypassed because no TMSS ROM is ever loaded
  wire [23:0] core_rgb;
  wire        core_hs;
  wire        core_vs;
  wire        core_hblank;
  wire        core_vblank;
  wire [ 8:0] md_mol;
  wire [ 8:0] md_mor;
  wire [ 9:0] md_mol_2612;
  wire [ 9:0] md_mor_2612;
  wire [15:0] md_psg;
  wire        md_fm_clk1;
  wire        md_fm_sel23;

  wire [ 7:0] vdp_r;
  wire [ 7:0] vdp_g;
  wire [ 7:0] vdp_b;
  wire        vdp_hs;
  wire        vdp_vs;
  wire        vdp_hclk1;
  wire        vdp_intfield;
  wire        vdp_de_h;
  wire        vdp_de_v;
  wire        vdp_m2;
  wire        vdp_m5;
  wire        vdp_rs1;

  md_board md_board (
      .MCLK2(clk_md_107_39),

      .ext_reset   (md_reset_effective),  // paprium: the MCU holds the 68000 while it boots
      .reset_button(btn_reset),
      // md_board.v reads these, MiSTer leaves them dangling
      .ext_vres    (1'b0),
      .ext_zres    (1'b0),

      .ram_68k_address(ram_68k_address),
      .ram_68k_byteena(ram_68k_byteena),
      .ram_68k_data   (ram_68k_data),
      .ram_68k_wren   (ram_68k_wren),
      .ram_68k_o      (ram_68k_o),
      .ram_z80_address(ram_z80_address),
      .ram_z80_data   (ram_z80_data),
      .ram_z80_wren   (ram_z80_wren),
      .ram_z80_o      (ram_z80_o),

      // TMSS ROM is not loaded, so the block stays bypassed
      .tmss_enable (1'b0),
      .tmss_data   (16'd0),
      .tmss_address(),

      // paprium: both OE strobes are taken now and muxed at the declaration, so
      // neither is dangling. cart_dma gates the menu
      // pause and, in the svp builds, the cartridge's DSP DMA path
      .M3              (1'b1),          // MD mode, no Master System
      .cart_address    (cart_addr),
      .cart_data       (cart_data),
      .cart_data_en    (cart_data_en),
      .cart_data_wr    (cart_data_wr),
      .cart_cs         (cart_cs),
      .cart_oe         (cart_oe_raw),    // paprium: no longer dangling
      .vdp_dma_oe_early(cart_oe_early),
      .cart_lwr        (cart_lwr),
      .cart_uwr        (cart_uwr),
      .cart_time       (cart_time),
      .cart_cas2       (),
      .cart_dma        (),
      .vdp_dma         (cart_dma),
      .cart_m3_pause   (1'b0),
      .ext_dtack       (cart_dtack),
      .pal             (PAL),
      .jap             (cfg_jap_s),

      .V_R       (vdp_r),
      .V_G       (vdp_g),
      .V_B       (vdp_b),
      .V_HS      (vdp_hs),
      .V_VS      (),
      .V_CS      (),
      .vdp_vsync2(vdp_vs),

      .A_L         (),
      .A_R         (),
      .A_L_2612    (),
      .A_R_2612    (),
      .MOL         (md_mol),
      .MOR         (md_mor),
      .MOL_2612    (md_mol_2612),
      .MOR_2612    (md_mor_2612),
      .PSG         (md_psg),
      .DAC_ch_index(),
      .fm_sel23    (md_fm_sel23),
      .fm_clk1     (md_fm_clk1),

      .PA_i(PA_i),
      .PA_o(PA_o),
      .PA_d(PA_d),  // 1 = input, 0 = output
      .PB_i(PB_i),
      .PB_o(PB_o),
      .PB_d(PB_d),
      .PC_i(PC_i),
      .PC_o(PC_o),
      .PC_d(PC_d),

      .vdp_hclk1      (vdp_hclk1),
      .vdp_intfield   (vdp_intfield),
      .vdp_de_h       (vdp_de_h),
      .vdp_de_v       (vdp_de_v),
      .vdp_m5         (vdp_m5),
      .vdp_rs1        (vdp_rs1),
      .vdp_m2         (vdp_m2),
      .vdp_lcb        (),
      .vdp_psg_clk1   (),
      .vdp_cramdot_dis(~cfg_cramdot_s),
      .vdp_hsync2     (),

      .ym2612_status_enable(ym2612_quirk),
      .dma_68k_req         (dma_68k_req),
      .dma_z80_req         (dma_z80_req),
      .dma_z80_ack         (dma_z80_ack),
      .res_z80             (res_z80)
  );
  // pocket-end


  //
  // video
  //

  // pocket: this APF video path has no upstream counterpart. The scaler wants one
  // sample per clk_vid edge and a height that cannot change mid-frame, and the VDP
  // gives neither. video_cond turns its raw sync and DE strobes into blanking windows.
  // H32 holds a dot for 10 MCLK against H40's 8, so the two modes take separate dot
  // clocks off the same VCO and clk_vid picks between them, which leaves video_skip
  // with nothing to drop. scanline_filler pads every frame up to its snap point so a
  // 224 to 240 change cannot emit a short frame. The scaler slot word rides the first
  // blanked pixel, because that is the only sample the scaler ignores
  //
  // The select is a clk_md_107_39 signal, so the switch can emit a runt pulse. It only
  // disturbs the frame it lands in, and the filler re-locks at the next vsync
  wire h32 = ~vdp_rs1;

  reg  clk_vid;
  reg  clk_vid_90deg;

  always @(*) begin
    clk_vid       = h32 ? clk_vid_5_37 : clk_vid_6_71;
    clk_vid_90deg = h32 ? clk_vid_5_37_90deg : clk_vid_6_71_90deg;
  end

  assign video_rgb_clock    = clk_vid;
  assign video_rgb_clock_90 = clk_vid_90deg;

  video_cond video_cond (
      .clk(clk_md_107_39),

      .vdp_hclk1   (vdp_hclk1),
      .vdp_de_h    (vdp_de_h),
      .vdp_de_v    (vdp_de_v),
      .vdp_intfield(vdp_intfield),
      .vdp_m2      (vdp_m2),
      .vdp_m5      (vdp_m5),
      .vdp_rs1     (vdp_rs1),

      .r_in (vdp_r),
      .g_in (vdp_g),
      .b_in (vdp_b),
      .hs_in(vdp_hs),
      .vs_in(vdp_vs),

      .pal      (PAL),
      .border_en(1'b0),
      .h40corr  (1'b0),
      .blender  (cfg_blend_s),

      .arx(),  // MiSTer aspect ratio hints, unused on Pocket
      .ary(),

      .ce_pix   (),
      .interlace(),
      .f1       (),

      .r_out  (core_rgb[23:16]),
      .g_out  (core_rgb[15:8]),
      .b_out  (core_rgb[7:0]),
      .hs_out (core_hs),
      .vs_out (core_vs),
      .hbl_out(core_hblank),
      .vbl_out(core_vblank)
  );

  // The VDP DAC is already RGB888. It runs on clk_md_107_39, and clk_vid is that clock
  // over 16 in H40 and over 20 in H32, so one clk_vid edge samples one held pixel

  reg video_de_reg;
  reg [23:0] video_rgb_reg;

  assign video_de   = video_de_reg;
  assign video_rgb  = video_rgb_reg;
  assign video_skip = 0;

  wire h32_s;

  synch_3 h32_sync (
      .i  (h32),
      .o  (h32_s),
      .clk(clk_vid)
  );

  wire cfg_arcorr_s;

  synch_3 arcorr_sync (
      .i  (cfg_arcorr),
      .o  (cfg_arcorr_s),
      .clk(clk_vid)
  );

  // The VDP syncs come out active low, the filler's edge detects want active high
  wire        vid_hs = ~core_hs;
  wire        vid_vs = ~core_vs;

  wire [23:0] filler_rgb;
  wire        filler_de;
  wire [ 7:0] snap_index;

  // A 224 to 240 change moves video_cond's blanking window in the same frame the
  // scaler is told the new height, so that frame comes out short. The filler pads
  // every frame back up to its snap point with black lines.
  // HSYNC_DELAY: 7 dot clocks, the VS to HS separation the VDP syncs had before
  scanline_filler #(
      .SNAP_COUNT (2),
      .SNAP_POINTS('{240, 224}),
      .HSYNC_DELAY(7)
  ) scanline_filler (
      .clk(clk_vid),

      .hsync_in(vid_hs),
      .vsync_in(vid_vs),

      .vblank_in(core_vblank),
      .hblank_in(core_hblank),
      .rgb_in   (core_rgb),

      .hsync(video_hs),
      .vsync(video_vs),

      .de (filler_de),
      .rgb(filler_rgb),

      .snap_index(snap_index)
  );

  reg prev_de = 0;
  reg prev_vs = 0;
  reg slot_h32 = 0;
  reg slot_arcorr = 0;
  reg [7:0] latched_snap_index = 0;

  always @(posedge clk_vid) begin
    prev_de <= filler_de;
    prev_vs <= video_vs;

    video_de_reg <= 0;

    if (video_vs && ~prev_vs) begin
      latched_snap_index <= snap_index;
      slot_h32           <= h32_s;
      slot_arcorr        <= cfg_arcorr_s;
    end

    if (~filler_de && prev_de) begin
      // scaler_modes: {arcorr, h32, v30}, so 0 = 320x224, 1 = 320x240, 2 = 256x224,
      // 3 = 256x240, 4 = 320x224 corrected, 5 = 320x240 corrected. SNAP_POINTS puts
      // 240 at index 0, so v30 is ~snap_index[0]. Upstream's h40corr only moves the
      // H40 row of the aspect table, so ~slot_h32 keeps H32 out of the corrected pair
      video_rgb_reg <= {8'b0, slot_arcorr & ~slot_h32, slot_h32, ~latched_snap_index[0], 13'b0};
    end else if (filler_de) begin
      video_de_reg  <= 1;
      video_rgb_reg <= filler_rgb;
    end
  end
  // pocket-end


  //
  // audio
  //

  // pocket: agg23 hands its core's stereo pair straight to audio_mixer, but md_board
  // has no summed output. MOL/MOR carry one FM channel slot at a time, so a
  // sample only exists once audio_cond has summed the slots; sending md_board's own
  // A_L/A_R mix to the 48 kHz output instead folds the slot rate into the audio band
  // paprium: audio_cond now feeds the mix below rather than the output buffer directly
  wire signed [15:0] base_audio_l;
  wire signed [15:0] base_audio_r;
  // paprium-end
  wire [15:0] audio_l;
  wire [15:0] audio_r;

  audio_cond audio_cond (
      .clk  (clk_sys_53_69),
      .reset(sys_reset),
      .mute (inmenu_sys_s),

      .lpf_mode(cfg_lpf_s),
      .fm_mode (cfg_fm_s),

      .fm_clk1 (md_fm_clk1),
      .fm_sel23(md_fm_sel23),
      .MOL     (md_mol),
      .MOR     (md_mor),
      .MOL_2612(md_mol_2612),
      .MOR_2612(md_mor_2612),
      .PSG     (md_psg),

      .sms_fm_audio(14'd0),  // MD mode only, no Master System FM

      .AUDIO_L(base_audio_l),
      .AUDIO_R(base_audio_r)
  );
  // pocket-end

  // paprium: the cartridge's own PCM sound-effect engine is a second stereo pair that
  // has to be summed with FM/PSG. Both are full-scale 16-bit, so the sum needs headroom
  // and a hard clip - without one, loud effects over loud music wrap and click. Three
  // guard bits cover FM/PSG plus cart SFX plus the boosted CDDA term.
  // In the other builds paprium_sfx_* is a constant 0 and this folds to a pass-through
  // CDDA gain. MisterPezz82 set this by A/B recording against real hardware: Paprium
  // mixes its music against its own loud cart SFX and needs ~+10 dB (294/256) where
  // ordinary MD+ content takes 93/256. Carried over rather than rediscovered.
  wire signed  [9:0] cdda_mult     = 10'sd294;
  wire signed [25:0] cdda_scaled_l = $signed(cdda_l) * cdda_mult;
  wire signed [25:0] cdda_scaled_r = $signed(cdda_r) * cdda_mult;
  wire signed [17:0] cdda_att_l    = cdda_scaled_l >>> 8;
  wire signed [17:0] cdda_att_r    = cdda_scaled_r >>> 8;

  wire signed [18:0] mix_l = $signed(base_audio_l) + $signed(paprium_sfx_l) + $signed(cdda_att_l);
  wire signed [18:0] mix_r = $signed(base_audio_r) + $signed(paprium_sfx_r) + $signed(cdda_att_r);

  wire mix_l_ov = (mix_l[18:15] != 4'b0000) && (mix_l[18:15] != 4'b1111);
  wire mix_r_ov = (mix_r[18:15] != 4'b0000) && (mix_r[18:15] != 4'b1111);

  assign audio_l = mix_l_ov ? (mix_l[18] ? 16'h8000 : 16'h7fff) : mix_l[15:0];
  assign audio_r = mix_r_ov ? (mix_r[18] ? 16'h8000 : 16'h7fff) : mix_r[15:0];
  // paprium-end

  reg [15:0] audio_buffer_l = 0;
  reg [15:0] audio_buffer_r = 0;

  // Buffer audio to have better fitting on audio route
  always @(posedge clk_sys_53_69) begin
    audio_buffer_l <= audio_l;
    audio_buffer_r <= audio_r;
  end

  audio_mixer #(
      .DW    (16),
      .STEREO(1)
  ) audio_mixer (
      .clk_74b   (clk_74b),
      .clk_audio (clk_sys_53_69),
      .reset     (sys_reset),
      .vol_att   (4'd0),
      .mix       (2'd0),            // 0 = none, 1 = 25%, 2 = 50% L/R crossfeed
      .is_signed (1'b1),
      .core_l    (audio_buffer_l),
      .core_r    (audio_buffer_r),
      .audio_mclk(audio_mclk),
      .audio_lrck(audio_lrck),
      .audio_dac (audio_dac)
  );

endmodule
