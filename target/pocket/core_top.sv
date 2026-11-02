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
// Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)
// pocket: words used in the pocket comments of this file. "New core" = the first step of the 0.3.0 work, which built
// the new cart register file and MCU interface v1.0 (the firmware's docs/STAGE1_PLAN.md); "synth step" = the 0.3.0
// step that moved the cart chip's audio work into logic (paprium_synth); "MegaWire step" = the 0.3.0 step that
// added the MegaWire code to the firmware; "release fit" = the fit made for the 0.3.0 release. "Test build N" = a
// 0.3.0 hardware test build that B Jam ran on the Pocket: 4 = the MCU fast path, 4a = the first sound-cache build,
// 4b = the first-boot unpack build, 5 = the synth build, S3c = a test build of the MegaWire step. "Fit round 1 / 2" =
// the new core's first and second rounds of fits and timing fixes. "xram step 1 / 2" = the two steps of our Pocket
// SRAM / CRAM work (paprium_xlink.sv). FPGAIO = the MCU's register block in the FPGA (fpgio.sv); XLINK = the MCU's
// register block for the Pocket's own memories and the CPU MATE link (paprium_xlink.sv); CRAM = the Pocket's cellular
// RAM; RAMDP = the cart RAM that both the 68000 and the MCU see; MCU interface vN / MCU_INTERFACE = the firmware's
// docs/MCU_INTERFACE.md.

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

  // pocket: cram0 is driven by the xram block (xmem) in the Paprium build, tied off there otherwise

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

  // pocket: the SRAM is driven by the xram block (xmem) in the Paprium build, tied off there otherwise

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
// Paprium cartridge subsystem, and is NTSC-only (generate.tcl): the RTL's clock figures
// follow CLK_HZ below, but the MCU firmware is built for one clock (its build-time
// clk_hz), so a PAL Paprium bitstream also needs a PAL firmware build
  parameter PAPRIUM = 1'b0;
  // Diagnostic switch: drop the cartridge PCM engine to buy ~700 ALMs. Shipping is 1
  parameter PAPRIUM_SFX = 1'b1;
  // Diagnostic build: report openfile's outcome as playback duration. Shipping is 0.
  // pocket: synth step (test build 4a on) - the album path is gone, so nothing reads this any more; it stays declared
  // because generate.tcl / syn_check.tcl / the qsf still set it on every variant
  parameter PAPRIUM_CDDA_DBG = 1'b0;

  // paprium: log the 68k's mailbox commands to their own APF data slot. Diagnostic
  // builds only; shipping is 0 and the whole block folds away.
  parameter PAPRIUM_CMD_LOG = 1'b0;

  // pocket: 0.3.0 new core (the clock-following change) - the one clock value. clk_sys_53_69 is VCO/12
  // and clk_md_107_39 VCO/6 in both regions (the wire names carry the NTSC figures). Every
  // clock-derived count in the RTL is computed from these two and passed down as a
  // parameter; scripts/clkcheck.py refuses a clock literal anywhere else
  localparam integer CLK_HZ    = PAL ? 53_203_424 : 53_693_175;
  localparam integer CLK_MD_HZ = 2 * CLK_HZ;

  // pocket: synth step (MCU interface v1.3 section 4.10) - FPGAIO FEAT (slot 23), what this bitstream carries, a
  // constant the firmware's crt0 checks. Test builds 4a / 4b: [0] CACHE (the sound-cache slot, XLINK CACHE /
  // CACHE_LOADED) = 1, [1] BAR (the first-boot bar, XLINK BAR) = 1, [2] SYNTH = 0, [3] SFXFIFO = PAPRIUM_SFX (region
  // 0x06 is audio_sfx's FIFOs, FPGAIO VOL_SFX live), [4] MDP = 1 (region 0x07, the MD+ block, kept with its album gone:
  // mdp_playing reads 0), [5] ALBUM = 0 (removed: it shared CRAM port A with the cache slot), [6] GS3 = 0, [23:16] IROM
  // = 72 (KB).
  // NTSC: 0x0048_001B. SYNTH and SFXFIFO are never both 1
  // pocket: synth step (the synth's first version) - PAPRIUM_SYNTH = 1: region 0x06 is the synth (paprium_synth,
  // MCU_INTERFACE v1.3 3.10) instead of audio_sfx, FEAT [2] SYNTH = 1 and [3] SFXFIFO = 0, and paprium_cram ports C / E
  // are the synth's. Hand-set like the other FEAT inputs: 0 until the synth integration (test build 5) turns it on
  // pocket: synth step (test build 5, the integration; MCU interface v1.3 sections 3.1, 4.10, 21.5) - test build 5 is
  // the synth fit:
  // PAPRIUM_SYNTH = 1 (the synth on region 0x06; audio_sfx's FIFOs are not built), [4] MDP = 0 (the MD+ block is out of
  // paprium_cart: region 0x07 is unassigned), [6] GS3 = 1 (the virtual Grand Stick III in paprium_pads), [23:16] IROM
  // = 88 KB (mcu_core: rom0 32 KB + a 56 KB extension in 7 slices, from FEAT itself through paprium_cart). NTSC:
  // 0x0058_0047 = CACHE | BAR | SYNTH | GS3, IROM 88: what test build 5's firmware crt0 asks for (CACHE | BAR | SYNTH,
  // IROM >= 88)
  localparam        PAPRIUM_SYNTH   = 1'b1;
  localparam [7:0]  PAPRIUM_IROM_KB = 8'd88;
  localparam [31:0] PAPRIUM_FEAT    = {8'd0, PAPRIUM_IROM_KB, 9'd0, 1'b1, 1'b0, 1'b0,
                                       ((PAPRIUM_SFX && !PAPRIUM_SYNTH) ? 1'b1 : 1'b0), (PAPRIUM_SYNTH ? 1'b1 : 1'b0),
                                       1'b1, 1'b1};
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
  // pocket: synth step (test build 4a on) - the album's fetcher is gone, so no variant issues a target command (tied 0
  // below)
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

  // paprium: the Paprium save is the MCU-managed backup RAM, not a 64 KB cart SRAM.
  // APF sizes the .sav file from this, and paprium_backup only decodes 13 address bits,
  // so a 64 KB slot would wrap 8 times over the array and corrupt the save on load.
  // New core (B Jam's decision of 2026-10-11 on the save size): 8 KB like the cart's EEPROM (0.2.x: 4 KB, 32'h1000); a
  // 0.2.x 4 KB .sav loads into the low half, at the same addresses as before
  localparam [31:0] SAVE_SIZE = PAPRIUM ? 32'h2000 : 32'h10000;
  // pocket: synth step (MCU interface v1.3 section 21.1, test builds 4a / 4b) - the Paprium build also writes the
  // sound-cache slot's size (data slot index 2, datatable word 5) all the time: XLINK CACHE.VALID ? CACHE.SIZE : 0. The
  // words come from paprium_cache_slot (xmem block), which alternates word 3 (save_dt) and word 5 on clk_74a, each
  // rewritten every other clock, so the Pocket writes the cache file back at a shutdown only once the firmware has set
  // CACHE, with exactly SIZE bytes; a session that ends before that writes no file. Other variants keep word 3 alone
  // (xmem_tie)
  wire [31:0] save_dt = (sram_present_74a | eeprom_present_74a) ? SAVE_SIZE : 32'd0;
  wire [ 9:0] datatable_addr;
  wire        datatable_wren = pll_core_locked_s;
  wire [31:0] datatable_data;
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
  wire [31:0] cache_rd_data;   // pocket: synth step - the sound-cache slot's flush reads (paprium_cache_slot; 0 elsewhere)

  always @(*) begin
    casex (bridge_addr)
      32'h2xxxxxxx: begin
        bridge_rd_data <= save_rd_data;
      end
      // paprium: command log, diagnostic builds only
      32'h3xxxxxxx: begin
        bridge_rd_data <= cmdlog_rd_data;
      end
      // pocket: synth step (MCU interface v1.3 section 21.1) - the sound-cache slot (data.json id 20, 0x60000000)
      32'h6xxxxxxx: begin
        bridge_rd_data <= cache_rd_data;
      end
      32'hF8xxxxxx: begin
        bridge_rd_data <= cmd_bridge_rd_data;
      end
      default: begin
        bridge_rd_data <= 0;
      end
    endcase
  end

  // pocket: one register per interact.json option this core exposes, plus the download
  // flag, with the CDC below carrying only what the console actually needs on its own
  // clocks. rom_download has to end before the save slot lands, because the cartridge
  // clears its save SRAM over that window.
  // paprium: most options are gone - the ones that remain are Region, 6 Button Pad and
  // Aspect Ratio. Everything else is a localparam so the fitter can drop its logic.
  reg rom_download = 0;

  // paprium: Auto is gone from the menu. This core ships no loader (core.json lists a
  // single bitstream), so nothing ever wrote detected_jap and Auto was silently Export
  // anyway.
  // 0.2.6: the Region register ($0C, no menu entry since 0.1.0) is gone too.
  // The region now comes from the Console list, or from a combined Mega CD unit
  // (paprium_opts below); the default (Mega Drive, Mega CD None) is Japan, as before.
  wire cfg_jap;

  // paprium: the audio filter menu is gone and the mode is hard-wired to 3 (No Filter).
  // Measured on hardware: any other mode stops the punk-TV cue being audible. It is
  // also the cheapest arm by a wide margin - every other mode routes the PSG through
  // psg_iir (146 ALMs), while mode 3 takes psg_amp, a single adder. Hard-wiring it
  // drops psg_iir, genesis_lpf (bypassed at mode 3) and genesis_fm_lpf (mode 1 only).
  // Cost: less authentic than a real Mega Drive's low-pass. Deliberate, for one game.
  localparam [1:0] CFG_LPF = 2'd3;
  // paprium: YM2612 only - the YM3438 option is gone
  localparam       CFG_FM  = 1'b0;

  // Defaults to 6-button because that is what this core has always presented, and
  // the Pocket has the face buttons for it. A handful of games misread the pad
  // paprium: TIED OFF. Paprium's own pad read is a 3-button read that bails after
  // one TH toggle, so X/Y/Z/Mode never worked and the menu option did nothing.
  // Upstream's fix is a ROM-read substitution injecting X/Y/Z into the game's pad
  // struct, which bypasses this protocol entirely - so tying MODE low does not
  // foreclose it. With MODE constant, pad_io's JCNT state machine, the ~1.5 ms
  // JTMR counter (11600*7) and the extra protocol frames all fold away, on both
  // ports. See docs/PORT_PLAN.md.
  // paprium: RESTORED as a register. Tying this off was measured to COST 1,151
  // ALMs rather than save them (16,900 -> 18,051), which is the opposite of the
  // intent; mcu.txt was eliminated as a cause by a later build that changed the
  // firmware and left the ALM count identical. The menu entry stays removed - the
  // option never did anything, because Paprium's pad read is a 3-button read - so
  // this simply sits at its default and costs nothing user-visible.
  // 0.3.0: no longer used. With the EA 4-Way Play (paprium_pads) the game's own six-button read works on
  // this core (measured on an RTL bench of the game's own pad code: X/Y/Z/Mode land in all three players'
  // records; the 0.2.6 direct-port read loses pad_io's first TH rise and sees three-button pads). So the pads' six-button mode now
  // follows the 6-Button switch (Scum! 0x44): on = six-button pads for players 1-3, which gives player 3 its
  // X/Y/Z/Mode; off = three-button pads, which is what the game saw in 0.2.6
  // 0.3.0 (B Jam's revised decision of 2026-10-11 on the EA 4-Way Play): that holds only while the EA 4-Way Play is
  // present. Without it the ports are 0.2.6's, and so is their MODE: this register again (pads section below)
  // 0.3.0 test build 4 (B Jam 2026-10-16): no longer read. pad_io now counts the first TH rise of the direct-port read,
  // so the 6-Button switch gives real six-button pads on the direct ports too, and it is the pads' MODE everywhere
  reg cfg_6btn = 1;

  // paprium: CRAM Dots and Composite Blend menus removed and both tied off. The dot is
  // a Mega Drive artefact the VDP produces when CRAM is written mid-line; cofi is a
  // composite-style horizontal blur. Neither is wanted for this core, and tying them
  // off lets the fitter drop cofi and the VDP's dot path entirely.
  localparam CFG_CRAMDOT = 1'b0;
  localparam CFG_BLEND   = 1'b0;

  // MiSTer's h40corr. video_cond takes it as an input, but there it only picks a row of
  // the arx/ary table, and the Pocket reads its aspect out of video.json instead. So the
  // bit picks a scaler slot here and video_cond's own port stays tied off
  reg cfg_arcorr = 0;

  // pocket: Scum! (0.2.6), four entries at the bottom of the core's menu. Little-Man (the cheats) is one
  // list whose value is the {lives,pills,health} mask. The stages need two lists, since
  // a list holds 16 choices: page 1 writes 0 or 1-15, page 2 writes 0 or 16-25 (25 is
  // Arena, stage 0x1E). The Pocket replays saved settings in a fixed order at boot, so
  // "last one changed" cannot be known here: page 2 wins whenever it holds a stage.
  // 0.3.0: Arcade Mode is its own list ($5C: 0 Off, 1 On, 2 Multiplayer); the stage lists only
  // pick the stage, and only while Arcade Mode is on (0.2.6: any stage switched Arcade Mode on).
  // Multiplayer adds the Grand Stick III DIP bit (Scum! G_ARC3P): three players in Arcade
  reg [2:0] scum_cheats  = 0;
  reg [4:0] scum_stage_a = 0;
  reg [4:0] scum_stage_b = 0;
  reg       scum_6btn    = 0;
  // 32X Mode: the add-on detection stub (PAPRIUM/paprium_addons.sv), read at boot. The
  // Mega CD list below replaced the Mega CD Mode check
  reg       scum_32x     = 0;
  reg [4:0] scum_stage   = 0;
  reg       scum_arcade  = 0;
  // 0.3.0: Arcade Mode. Synth step (B Jam's decision 6b of 2026-10-21): 0 Off, 1 On, 2 Multiplayer, 3 Stick Only
  reg [1:0] scum_arcmode = 0;
  reg       scum_arc3p   = 0;
  // 0.3.0 (B Jam's revised decision of 2026-10-11 on the EA 4-Way Play): "3-Player Mode" ($60, check, default Off). The
  // EA 4-Way Play is present when 3-Player Mode = On or Arcade Mode = Multiplayer (which needs it); the pads section
  // takes it at boot. Synth step (B Jam's decision 6a): never with the Grand Stick III on; then the stick's EXT socket
  // is Dock controller 3
  reg       scum_3p      = 0;
  reg       scum_tap     = 0;
  // 0.3.0 synth step (B Jam's decisions 6a-6c of 2026-10-19 / 2026-10-21): the Grand Stick III. Arcade Mode On,
  // Multiplayer and Stick Only put a virtual Grand Stick III in port 1 (paprium_pads / paprium_gs3), and the game runs
  // its own arcade code from the stick's switches on the unpatched ROM (the Scum! Arcade patch, the pad hook and the
  // coin stub are gone). The switch byte (DIP 1-6 = bits 0-5): Arcade Mode On or Multiplayer = ARCADE (bit 5);
  // Multiplayer = 3 PLAYERS (bit 0); "Arcade Coins" ($64): 1 Coin 1 Credit = no bit, 2 Coins 1 Credit = TWO COINS
  // (bit 2), "Inf. Credits (0012)" = INF. CREDITS (bit 4), which the game answers with its red 0012 stop, by design,
  // as on B Jam's stick; "Attract Only" ($68, check) = DEMO (bit 3); NO HIT FX (bit 1) is left out (nothing to see on
  // a Pocket). Stick Only = a stick with every switch off (B Jam's own stick), so Coins and Attract Only apply only
  // with Arcade on. Select is the coin only while Arcade is on; with Stick Only it is the stick's Mode button. The
  // EXT socket holds Dock controller 3 with Multiplayer or 3-Player Mode (no EA 4-Way Play with the stick on). All
  // taken at boot with the adapter (below), as the game reads the stick's switches once per power-on or reset
  reg [1:0] scum_coins   = 0;     // synth step: Arcade Coins, 0 1C1C, 1 2C1C, 2 Inf. Credits (0012)
  reg       scum_attract = 0;     // synth step: Attract Only
  reg       gs3_on_74    = 0;
  reg       gs3_pt_74    = 0;
  reg       gs3_coin_74  = 0;
  reg [5:0] gs3_dip_74   = 0;

  always @(posedge clk_74a) begin
    scum_arcade <= (scum_arcmode == 2'd1) | (scum_arcmode == 2'd2);
    scum_arc3p  <= (scum_arcmode == 2'd2);
    scum_tap    <= scum_3p & (scum_arcmode == 2'd0);                 // synth step: no 4-Way Play with the stick on
    scum_stage  <= ((scum_arcmode == 2'd1) | (scum_arcmode == 2'd2)) ?
                   ((scum_stage_b != 5'd0) ? scum_stage_b : scum_stage_a) : 5'd0;
    gs3_on_74   <= (scum_arcmode != 2'd0);
    gs3_pt_74   <= (scum_arcmode != 2'd0) & ((scum_arcmode == 2'd2) | scum_3p);
    gs3_coin_74 <= (scum_arcmode == 2'd1) | (scum_arcmode == 2'd2);
    gs3_dip_74  <= ((scum_arcmode == 2'd1) | (scum_arcmode == 2'd2)) ?
                   {1'b1, (scum_coins == 2'd2), scum_attract, (scum_coins == 2'd1), 1'b0, (scum_arcmode == 2'd2)} : 6'd0;
  end

  // pocket: 0.2.6 options: Console (list, $54), Mega CD (list, $50,
  // replaces the Mega CD Mode check; its value 1 is Aiwa CSD-GM1 = the old stub, so a persisted
  // "on" keeps today's behaviour) and MegaWire (check, $58, default off). paprium_opts decodes them
  // on this clock and applies the hardware rules; synch_3 carries the results:
  //   clk_md  : cfg_jap (md_settings_sync), version nibble + DISK (md_board), the stub's unit
  //             select and TMSS-lite enable (opt_md_sync), cd_real = the buddy's Mega CD Mode
  //             (scum_sync bit 19, where the check used to go)
  //   clk_sys : the cart MCU's GPIO input, {MegaWire, $1FE4 model bits} (opt_mcu_sync); the
  //             firmware copies them into $1FE4/$1FE6 at its reset (ppm_reset)
  // All are read by the game at boot ($BC944), so a change needs a reset, as 32X Mode does.
  reg [3:0] opt_console = 4'd0;    // 0.3.0: 4 bits, 8 = TeraDrive
  reg [3:0] opt_megacd  = 4'd0;
  reg       opt_mwire   = 1'b0;

  // New core (MCU_INTERFACE 4.1 CTRL bit 5): the "options apply at reset" latch, built
  // DORMANT. OPT_AT_RESET_EN = 0 (configuration, every reset, and until firmware writes it) selects the live
  // option registers below, exactly as 0.2.6; the copies follow them every clk_74a. With 1, every option
  // consumer (paprium_opts, so the version nibble, TMSS-lite, DISK, JAP, the CD stub, cd_real, and the MCU's
  // GPIO copy) holds the values from the clock before it went to 1, and a change the APF makes waits for the
  // next reset, which clears bit 5 (as a fix our 0.2.6 hardware study proposed: one consistent machine per boot). For
  // diagnosis only; if it is never switched on, the 0.3.0 release fit removes it (B Jam 2026-10-11)
  wire                          opt_at_reset_en;       // fpgio ctrl[5], clk_sys_53_69
  wire                          opt_at_reset_en_74a;
  synch_3 opt_at_reset_sync (.i(opt_at_reset_en), .o(opt_at_reset_en_74a), .clk(clk_74a));
  reg  [$bits(opt_console)-1:0] opt_console_q = '0;
  reg  [$bits(opt_megacd)-1:0]  opt_megacd_q  = '0;
  reg                           opt_mwire_q   = 1'b0;
  always @(posedge clk_74a) begin
    if (!opt_at_reset_en_74a) begin
      opt_console_q <= opt_console;
      opt_megacd_q  <= opt_megacd;
      opt_mwire_q   <= opt_mwire;
    end
  end
  wire [$bits(opt_console)-1:0] opt_console_e = opt_at_reset_en_74a ? opt_console_q : opt_console;
  wire [$bits(opt_megacd)-1:0]  opt_megacd_e  = opt_at_reset_en_74a ? opt_megacd_q  : opt_megacd;
  wire                          opt_mwire_e   = opt_at_reset_en_74a ? opt_mwire_q   : opt_mwire;

  wire       opt_jap, opt_ver1, opt_disk_n, opt_cd_real;
  wire       opt_td_en;           // 0.3.0: the TeraDrive stub (md_board's vram_td_stub)
  wire [3:0] opt_model, opt_cd_unit;

  paprium_opts opts (
      .clk    (clk_74a),
      .console(opt_console_e),   // new core: through the dormant latch
      .megacd (opt_megacd_e),
      .jap    (opt_jap),
      .ver1   (opt_ver1),
      .model  (opt_model),
      .cd_unit(opt_cd_unit),
      .disk_n (opt_disk_n),
      .cd_real(opt_cd_real),
      .td_en  (opt_td_en)
  );
  assign cfg_jap = opt_jap;

  wire       opt_ver1_s, opt_disk_n_s, opt_td_en_s;
  wire [3:0] opt_cd_unit_s;
  wire [5:0] mcu_opts_s;          // {Japan, MegaWire, $1FE4 bit 10, 9, 8, 6}, clk_sys_53_69 (new core: + Japan)

  synch_3 #(
      .WIDTH(7)
  ) opt_md_sync (
      .i({opt_td_en, opt_ver1, opt_disk_n, opt_cd_unit}),
      .o({opt_td_en_s, opt_ver1_s, opt_disk_n_s, opt_cd_unit_s}),
      .clk(clk_md_107_39)
  );

  synch_3 #(
      .WIDTH(6)
  ) opt_mcu_sync (
      // pocket: new core - adds opt_jap (option word bit 25) and takes MegaWire through the dormant latch.
      // opt_jap and opt_model come from paprium_opts, which already sees the latched Console / Mega CD
      .i({opt_jap, opt_mwire_e, opt_model}),
      .o(mcu_opts_s),
      .clk(clk_sys_53_69)
  );
  // pocket-end


  localparam [13:0] RESET_PULSE = 14'd8000;  // ~108 us at 74.25 MHz

  reg  [13:0] reset_counter = 0;
  wire        core_reset = (reset_counter != 0);
  reg         cr_req_74a = 1'b0;   // pocket: test build S3c - the Console Reset action: one change per press

  always @(posedge clk_74a) begin
    if (reset_counter != 0) begin
      reset_counter <= reset_counter - 1'd1;
    end

    if (bridge_wr) begin
      casex (bridge_addr)
        32'h00000000: begin
          rom_download <= bridge_wr_data[0];
        end
        32'h0000001C: begin
          cfg_6btn <= bridge_wr_data[0];
        end
        32'h00000028: begin
          cfg_arcorr <= bridge_wr_data[0];
        end
        32'h00000030: scum_cheats  <= bridge_wr_data[2:0];
        32'h00000040: scum_stage_a <= bridge_wr_data[4:0];
        32'h00000044: scum_6btn    <= bridge_wr_data[0];
        32'h00000048: scum_stage_b <= bridge_wr_data[4:0];
        32'h0000004C: scum_32x     <= bridge_wr_data[0];
        32'h00000050: opt_megacd   <= bridge_wr_data[3:0];   // 0.2.6
        32'h00000054: opt_console  <= bridge_wr_data[3:0];   // 0.3.0: + TeraDrive (8)
        32'h00000058: opt_mwire    <= bridge_wr_data[0];
        32'h0000005C: scum_arcmode <= bridge_wr_data[1:0];   // 0.3.0: Arcade Mode
        32'h00000060: scum_3p      <= bridge_wr_data[0];     // 0.3.0: 3-Player Mode
        32'h00000064: scum_coins   <= bridge_wr_data[1:0];   // synth step: Arcade Coins (Grand Stick III switches)
        32'h00000068: scum_attract <= bridge_wr_data[0];     // synth step: Attract Only
        32'hF0000000: begin
          reset_counter <= RESET_PULSE;
        end
        32'hF0000004: cr_req_74a <= ~cr_req_74a;   // pocket: test build S3c - Console Reset (interact.json "Console Reset")
      endcase
    end
  end

  wire       reset_n_s;
  wire       core_reset_s;
  wire       dataslot_allcomplete_s;
  wire       scum_6btn_s;
  wire       cfg_6btn_s;
  wire       inmenu_sys_s;

  synch_3 #(
      .WIDTH(6)
  ) settings_sync (
      // 0.3.0: 6-Button; and (B Jam's revised decision on the EA 4-Way Play) 0.2.6's cfg_6btn again, the pads' MODE
      // without the EA 4-Way Play
      .i({reset_n, core_reset, dataslot_allcomplete, scum_6btn, cfg_6btn, osnotify_inmenu}),
      .o({
        reset_n_s,
        core_reset_s,
        dataslot_allcomplete_s,
        scum_6btn_s,
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
  wire inmenu_md_s;

  synch_3 #(
      .WIDTH(5)
  ) md_settings_sync (
      .i({loading_74a, reset_req_74a, cfg_jap, rom_download, osnotify_inmenu}),
      .o({
        loading_s,
        md_reset_req_s,
        cfg_jap_s,
        rom_download_s,
        inmenu_md_s
      }),
      .clk(clk_md_107_39)
  );

  // Fafrium: the boot stub's GO (cartridge -> paprium_cart -> mcu_core, clk_sys, a power-on flag) restarts the reset
  // envelope below once, as the end of an APF load does (reset_delay_count to 0: shell_reset -> sys_reset for 2-3
  // ram_clear_addr steps), so the firmware starts from the same reset as one built into the bitstream did
  wire       fw_go;
  wire       fw_go_md;
  // Fafrium: fw_len_bad is 1 unless the Fafrium slot's last load was exactly 256 KB (cartridge.sv's length mark,
  // which covers files up to 32 MB).
  // It goes to XLINK FAFRIUM, where only the boot stub reads it. It reads 0 once fw_done is set.
  wire       fw_len_bad;
  synch_3 fw_go_sync (.i(fw_go), .o(), .rise(fw_go_md), .clk(clk_md_107_39));

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
    if (loading_s | (~prev_md_reset_req & md_reset_req_s) | fw_go_md) begin   // Fafrium: + fw_go_md
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

  // pocket: synth step (a logic saving) - in the Paprium build the ROM region is served by the sound-cache slot's
  // loader (paprium_cache_slot ROM_SHARE = 1, xmem block: the same stock data_loader, word size 2, delay 24, 25 address
  // bits, with its own ROM output registers), so this loader is the other builds' only
  generate
    if (!PAPRIUM) begin : rom_ld
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
    end
  endgenerate

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

  // Fafrium: while the boot stub runs (from the first sys_reset release after a complete load until GO), paprium_cart's
  // reset ignores sys_reset, so a Soft Reset or the Quit's Reset Enter cannot stop the copy half way (a new load,
  // cart_dl, still resets it; the Quit's read-back raises cart_dl). From the clock after GO the cart is held in reset
  // until the envelope's own sys_reset is up (fw_done, a power-on flag: from then the boot view is closed), so the MCU
  // runs nothing between GO and the restart. Outside the stub phase and that gap pap_reset is a register equal to
  // sys_reset on every clock (the same next-state function), so the cart's release is sys_reset's own clock
  reg         fw_stub   = 1'b0;
  reg         fw_done   = 1'b0;
  reg         pap_reset = 1'b0;
  wire        sys_reset_nx = (&shell_reset_sync) ? 1'b1 : (shell_reset_sync == 2'b00) ? 1'b0 : sys_reset;
  wire        fw_stub_nx   = ~fw_go & ~cart_dl & (fw_stub | ~sys_reset);
  always @(posedge clk_sys_53_69) begin
    fw_stub   <= fw_stub_nx;
    if (fw_go & sys_reset) fw_done <= 1'b1;
    pap_reset <= (sys_reset_nx & ~fw_stub_nx) | (fw_go & ~fw_done);
  end


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

  // paprium: command-log read-back on its own bridge region (0x3xxxxxxx) and its
  // own data slot, so a diagnostic capture can never touch the 8 KB save.
  wire [13:0] cmdlog_read_addr;
  wire  [7:0] cmdlog_read_data;
  wire [31:0] cmdlog_rd_data;

  generate
    if (PAPRIUM_CMD_LOG) begin : cmdlog_unload
      data_unloader #(
          .ADDRESS_MASK_UPPER_4(4'h3),
          .ADDRESS_SIZE        (14),
          .INPUT_WORD_SIZE     (1),
          .READ_MEM_CLOCK_DELAY(4)
      ) cmdlog_data_unloader (
          .clk_74a   (clk_74a),
          .clk_memory(clk_sys_53_69),

          .bridge_rd           (bridge_rd),
          .bridge_endian_little(bridge_endian_little),
          .bridge_addr         (bridge_addr),
          .bridge_rd_data      (cmdlog_rd_data),

          .read_en  (),
          .read_addr(cmdlog_read_addr),
          .read_data(cmdlog_read_data)
      );
    end
    else begin : cmdlog_unload_off
      assign cmdlog_rd_data   = 32'd0;
      assign cmdlog_read_addr = 14'd0;
    end
  endgenerate
  // paprium-end

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

  // pocket: 32X Mode / Mega CD Mode answer their boot probes ahead of the cartridge,
  // as the MiSTer test builds do; both off leaves the cartridge's own data untouched
  wire [15:0] cart_data_cart;
  wire        cart_data_en_cart;
  wire [15:0] addon_data;
  wire        addon_data_en;

  // pocket-end

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

  // pocket: 0.3.0 new core - Pocket-menu music mute (MCU_INTERFACE 4.1, CTRL bit 4). While
  // the Pocket menu is open and the firmware has set MENU_MUTE_EN, the album pauses in place
  // (cdda_play stops taking samples and outputs 0, then carries on from the same ring
  // address) and the cart SFX pair is forced to 0. FM/PSG keep 0.2.6's audio_cond mute on
  // inmenu_sys_s alone. Both terms are on clk_sys (settings_sync, fpgio): no new crossing.
  // MENU_MUTE_EN is 0 until the firmware writes it, so 0.2.6's firmware keeps 0.2.6's sound
  wire        paprium_menu_mute_en;
  wire        menu_mute = inmenu_sys_s & paprium_menu_mute_en;
  // pocket-end

  wire        mdp_track_request;
  wire  [7:0] mdp_track_num;
  wire        mdp_track_loop;
  wire        mdp_stop_request;
  wire  [7:0] mdp_fade_sectors;
  wire        mdp_resume_request;
  wire  [7:0] mdp_volume;
  wire        mdp_volume_request;
  wire        mdp_active;

  // New core: the 68000 is held from the first clk_md of every reset. shell_reset (clk_md, high from the
  // clock after the reset request until the MCU leaves reset) covers the window before the MCU's HOLD bit
  // (fpgio ctrl[0], reset to 1 by every sys_reset) has crossed; HOLD keeps it held after shell_reset falls,
  // until the firmware releases it. HOLD comes from clk_sys through a synch_3 (core_constraints.sdc: false path into
  // its first stage, *|synch_3:paprium_hold_sync|stage_1*), so the 68000 release moves ~3 clk_md (~28 ns) once a boot
  //
  // Fit round 2: md_reset_effective is a register (md_reset_eff_q) that holds, on every clk_md, exactly the value
  // of the old expression md_reset | (paprium_active & (paprium_md_reset_s | shell_reset)): it loads the same function
  // of its inputs' NEXT values - md_reset's and shell_reset's own D inputs (the always block above), the HOLD
  // synchroniser's stage_2 (nxt = what o takes next), paprium_active a build constant. Fit round 1 had the OR as a LUT
  // in front of the arbiter's reset gate (fc1004 SRES -> ym6045 w76 -> INTAK -> the VDP decode -> VD): the md_reset ->
  // VD[5] path set the vd_bus class at -0.821 ns (slow 85C, seed 1) and HOLD's o -> VD[5] failed the fit gate's
  // hold_out query (-0.668). Now the reset gate sees one register. The HOLD synchroniser itself is unchanged (stage_1
  // keeps its false path; stage_1 -> stage_2 is still a plain flop hop); the release still moves ~3 clk_md once a boot,
  // exactly as before. Exact by construction; checked on our reset bench: the register against the old expression on
  // every clock
  wire        paprium_md_reset_nx;   // the synchroniser's o after this clock (o itself has no other reader now)
  synch_3 paprium_hold_sync (.i(paprium_md_reset), .o(), .clk(clk_md_107_39), .nxt(paprium_md_reset_nx));
  wire        md_reset_nx    = loading_s ? 1'b1 : (reset_delay_count == 3) ? 1'b0 : md_reset;
  wire        shell_reset_nx = (reset_delay_count < 3);
  reg         md_reset_eff_q = 1'b0;   // power-up: md_reset, shell_reset and the synchroniser all 0
  always @(posedge clk_md_107_39)
    md_reset_eff_q <= md_reset_nx | (paprium_active & (paprium_md_reset_nx | shell_reset_nx));
  wire        md_reset_effective = md_reset_eff_q;
  wire        addon_dtack;        // 0.2.6: TMSS-lite registers ($A14000-3, $A14101)

  // pocket: test build S3c (the MegaWire step; B Jam's decision of 2026-10-18 to add a cart-exact Console Reset) - the
  // console's own Reset button, 68000-only, as a Pocket menu action. A real console's Reset resets the 68000 and (through
  // the bus arbiter's one-shot, which clears $A11200) holds the Z80 until the game releases it; the VDP, work RAM, Z80 RAM
  // and the cart keep running, and the cart chip only acknowledges its EXTI13 line. So this presses md_board's
  // reset_button alone - never ext_reset (SRES), md_reset (the RAM clears), shell_reset or sys_reset (the MCU) - and
  // raises FPGAIO CAUSE.V (= the chip's EXTI13). What the 68000 then fetches is the board's warm vector page, the one
  // variant that reproduces every Reset captured on the cart: PC $00010100 and the boot page's own
  // exception vectors in RAMDP $0000-$00FF, the rest of RAMDP and work RAM as the game left them. The firmware's board
  // layer writes that page on CAUSE.V and only then acknowledges it, so ext_vres (the 68000's RESET + HALT, nothing
  // else) holds the 68000 from the press until the acknowledgement AND the end of the button pulse: no 68000 cycle can
  // fetch a vector before the page is in. Nothing here is a timer or a list of lock screens: whether the game locks
  // ($80B78's guard before its first entry; F5 stamps in $0200-$09FF during a zoom) follows from that state alone.
  // The button pulse is 31 wraps of ram_clear_addr (~9.2-9.5 ms), Soft Reset's btn_reset length. A press while the
  // 68000 is held anyway (power-on, a load, Soft Reset, the MCU's boot hold), or during a Console Reset still being
  // served, is dropped. The Pocket menu's pause (pause_req) is left as it is: a press from the open menu resets the
  // 68000 at once and it starts again once the menu closes. Non-Paprium variants: every output 0 (no menu entry there).
  wire        cr_btn;               // -> md_board reset_button, with btn_reset
  wire        cr_hold;              // -> md_board ext_vres
  wire        cr_post_sys;          // clk_sys: one pulse per accepted press -> cartridge (FPGAIO CAUSE.V)
  wire        cr_cause_v;           // clk_sys: CAUSE.V pending (from the cartridge)
  generate
    if (PAPRIUM) begin : console_reset
      wire       req_md;
      synch_3 req_sync (.i(cr_req_74a), .o(req_md), .clk(clk_md_107_39));
      wire       v_md;
      synch_3 v_sync (.i(cr_cause_v), .o(v_md), .clk(clk_md_107_39));
      reg        req_q = 1'b0;
      reg        btn_q = 1'b0;
      reg        hold_q = 1'b0;
      reg        seen_q = 1'b0;     // CAUSE.V seen pending since the press
      reg        acc_q = 1'b0;      // one change per accepted press (to clk_sys)
      reg  [4:0] cnt_q = 5'd0;
      always @(posedge clk_md_107_39) begin
        req_q <= req_md;
        if (md_reset_effective | btn_reset | loading_s) begin      // another reset owns the console
          btn_q  <= 1'b0;
          hold_q <= 1'b0;
          seen_q <= 1'b0;
        end else if ((req_md ^ req_q) & ~hold_q) begin             // a press: accepted
          btn_q  <= 1'b1;
          hold_q <= 1'b1;
          seen_q <= 1'b0;
          cnt_q  <= 5'd0;
          acc_q  <= ~acc_q;
        end else begin
          if (btn_q & (&ram_clear_addr)) cnt_q <= cnt_q + 1'd1;
          if (&cnt_q) btn_q <= 1'b0;
          if (v_md) seen_q <= 1'b1;
          if (~btn_q & seen_q & ~v_md) hold_q <= 1'b0;             // page written and acknowledged, button up
        end
      end
      assign cr_btn  = btn_q;
      assign cr_hold = hold_q;
      wire       acc_sys, acc_rise, acc_fall;
      synch_3 acc_sync (.i(acc_q), .o(acc_sys), .clk(clk_sys_53_69), .rise(acc_rise), .fall(acc_fall));
      assign cr_post_sys = acc_rise | acc_fall;
    end else begin : no_console_reset
      assign cr_btn = 1'b0;
      assign cr_hold = 1'b0;
      assign cr_post_sys = 1'b0;
    end
  endgenerate
  // pocket-end

  // Paprium reads the real cartridge OE; everything else keeps the early DMA strobe
  assign      cart_oe = paprium_active ? cart_oe_raw : cart_oe_early;

  // pocket: xram step 2 - option D: the stub's busy bit and COMSTAT2 come from
  // paprium_mcd_link (xmem block below); tied to 0 in the other variants
  wire        od_busy;
  wire [15:0] od_comstat2;
  wire  [7:0] od_g3;
  wire  [6:0] od_link_status;
  wire        od_post_bit;   // pocket: new core - XLINK posts_s[0], clk_sys: FPGAIO CAUSE.S (one event a post)
  wire        paprium_vs_tog_s;   // pocket: new core (MCU interface v1.1) - paprium_vs_tap below, clk_sys: FPGAIO VSCNT

  // pocket: the 32X / Mega CD boot-probe stubs (declared with the cart wires above)
  paprium_addons addons (
      .clk         (clk_md_107_39),
      .reset       (md_reset),
      .tmss_reset  (md_reset_effective),   // 0.2.6: md_board's ext_reset (SRES)
      .en_32x      (scum_s[18]),
      .cd_unit     (opt_cd_unit_s),        // 0.2.6: was en_cd = Mega CD Mode
      .tmss_on     (opt_ver1_s),
      .cart_addr   (cart_addr),
      .cart_oe     (cart_oe & paprium_active),
      .cart_lwr    (cart_lwr),
      .cart_uwr    (cart_uwr),
      .cart_data_wr(cart_data_wr),
      .busy        (od_busy),
      .comstat2    (od_comstat2),
      .g3_q        (od_g3),
      .data_en     (addon_data_en),
      .data_out    (addon_data),
      .dtack       (addon_dtack)
  );

  assign cart_data    = addon_data_en ? addon_data : cart_data_cart;
  assign cart_data_en = addon_data_en | cart_data_en_cart;

  // pocket: xram step 1 - the Paprium MCU's external-memory bus and the CDDA ring's
  // CRAM port. Declared here because the CDDA block, the xram block and the cartridge all use them.
  wire        xb_req;
  wire  [1:0] xb_region;
  wire [23:0] xb_addr;
  wire  [3:0] xb_sel;
  wire        xb_wr;
  wire [31:0] xb_wdata;
  wire [31:0] xb_rdata;
  wire        xb_ack;

  wire        cr_wr, cr_rd, cr_rd_done;
  wire [21:0] cr_waddr, cr_raddr;
  wire [15:0] cr_wdata, cr_rdata;

  // pocket: synth step (MCU interface v1.3 sections 3.9 / 21.2) - the first-boot bar: XLINK BAR (clk_sys, xmem block)
  // to paprium_bar on the dot clock (video section) through bar_sync, and its W read-back through bar_w_sync
  wire        xl_bar_en;
  wire [10:0] xl_bar_px;
  wire [10:0] bar_w_sys;

  // the SFX echo line (audio_sfx mix_bank) on paprium_cram port E instead of 32 M10K
  wire        echo_ready, echo_wr, echo_rd, echo_rd_done;
  wire [12:0] echo_wslot, echo_rslot;
  wire [31:0] echo_wdata, echo_rdata;
  // pocket: synth step (PAPRIUM_SYNTH) - the synth's CRAM clients (paprium_synth_cram) on paprium_cram ports C and E
  wire        syn_c_rd, syn_c_rd_done, syn_e_wr, syn_e_wpair, syn_e_rd, syn_e_rpair, syn_e_rd_done, syn_e_wbusy;
  wire [20:0] syn_c_raddr;
  wire [15:0] syn_c_rdata;
  wire [21:0] syn_e_waddr, syn_e_raddr;
  wire [31:0] syn_e_wdata, syn_e_rdata;
  // pocket-end

  // ==========================================================================
  // paprium: CDDA background music - REMOVED in the 0.3.0 synth step (test build 4a on; MCU interface v1.3 section
  // 21.5). The album path (paprium_cdda_fetch, the bridge 0x3 / 0x5 landing loaders, paprium_cdda_buf_cram's ring in
  // CRAM and paprium_cdda_play) shared CRAM port A with the sound-cache slot, which takes the port now (xmem block
  // below; data.json slot id 300 is gone, id 20 takes its place). Its outputs are constants: no music, no target
  // dataslot command, the MD+ block's status reads "not playing" (FEAT.MDP stays 1: region 0x07 answers as on test
  // build 4, the firmware sees every track as finished, as before the streamer existed). The CDDA source files stay in
  // the tree, unreachable (paprium.qip), until the synth integration deletes them with the rest of the interim
  // audio. The cdda mix terms below fold away.
  // ==========================================================================
  wire signed [15:0] cdda_l            = 16'sd0;
  wire signed [15:0] cdda_r            = 16'sd0;
  wire        [15:0] cdda_underruns    = 16'd0;   // XLINK UNDERRUN[15:0] reads 0
  wire               mdp_playing       = 1'b0;
  wire        [7:0]  mdp_current_track = 8'd0;

  assign target_dataslot_read       = 1'b0;
  assign target_dataslot_id         = 16'd0;
  assign target_dataslot_slotoffset = 32'd0;
  assign target_dataslot_bridgeaddr = 32'd0;
  assign target_dataslot_length     = 32'd0;
  // paprium-end

  // ==========================================================================
  // pocket: xram step 1. The Pocket's spare memories, which the
  // other variants still tie off:
  //   SRAM  AS6C2016-55BIN, 128K x 16 = 256 KB: the MCU's window 0x08000000, loaded by an APF
  //         data slot at bridge 0x4xxxxxxx (0.2.6 defines no such slot; the snoop's Word RAM
  //         mirror lives here)
  //   CRAM  cram0 die 0 (AS1C8M16PL-70BIN, async mode): the CDDA ring (moved out of 16 M10K),
  //         the MCU's window 0x09000000 and a reserved stream port (unused); cram1 stays
  //         tied off
  //   LINK  the register block 0x0A000000 (wait states, counters)
  // Everything runs on clk_sys_53_69, the MCU's own clock, so there is no new clock crossing.
  // The controllers reset on power-on (PLL lock, latched) only: sys_reset is held through the
  // APF load, which is when the SRAM loader writes.
  // ==========================================================================
  generate
  if (PAPRIUM) begin : xmem

    wire xmem_lock_s;
    synch_3 xmem_lock_sync (.i(pll_core_locked), .o(xmem_lock_s), .clk(clk_sys_53_69));
    reg  xmem_ever = 0;
    always @(posedge clk_sys_53_69) if (xmem_lock_s) xmem_ever <= 1;
    wire xmem_reset = ~xmem_ever;

    wire [31:0] xcfg;

    // ---- APF loader for the SRAM (bridge 0x4xxxxxxx, byte addresses, 16-bit words) ----
    // pocket: synth step (a logic saving) - served by the sound-cache slot's loader (paprium_cache_slot SHARE = 1: the
    // same stock data_loader, word size 2, delay 24, with a region bit), no longer a data_loader of its own here
    wire        xld_wr;
    wire [17:0] xld_addr;
    wire [15:0] xld_data;

    // ---- pocket: synth step (MCU interface v1.3 section 21.1, test builds 4a / 4b) - the sound-cache slot ----
    // data.json id 20 at bridge 0x6xxxxxxx: the load writes CRAM die 0 through port A-write (file byte i = MCU byte
    // 0x0900_0000 + i), the flush reads it back through port A-read, CACHE_LOADED counts what landed, and the datatable
    // word 5 = XLINK CACHE.VALID ? CACHE.SIZE : 0. Everything here resets at power-on only (the flush runs while
    // sys_reset reboots the MCU). Port A was the album ring's (gone on test build 4a). It also drives the datatable's
    // core-side write port (words 3 and 5, alternating)
    wire        xl_cache_valid;
    wire [22:0] xl_cache_size;
    wire [22:0] cache_loaded;

    paprium_cache_slot #(.BRIDGE_UPPER_4(4'h6), .SHARE(1), .SHARE_UPPER_4(4'h4), .ROM_SHARE(1), .ROM_UPPER_4(4'h1)) cache_slot (
        .clk_74a   (clk_74a),
        .reset_74a (~pll_ever_locked),
        .clk_sys   (clk_sys_53_69),
        .reset_sys (xmem_reset),

        .bridge_wr           (bridge_wr),
        .bridge_rd           (bridge_rd),
        .bridge_endian_little(bridge_endian_little),
        .bridge_addr         (bridge_addr),
        .bridge_wr_data      (bridge_wr_data),
        .bridge_rd_data      (cache_rd_data),

        .cache_valid(xl_cache_valid),
        .cache_size (xl_cache_size),
        .save_dt    (save_dt),
        .dt_addr    (datatable_addr),
        .dt_data    (datatable_data),
        .loaded     (cache_loaded),

        .xld_wr  (xld_wr),
        .xld_addr(xld_addr),
        .xld_data(xld_data),

        .rom_wr  (ioctl_wr),             // pocket: synth step (a logic saving) - the ROM download (was core_top's rom_data_loader)
        .rom_addr(ioctl_addr),
        .rom_data(ioctl_data),

        .cr_wr     (cr_wr),
        .cr_waddr  (cr_waddr),
        .cr_wdata  (cr_wdata),
        .cr_rd     (cr_rd),
        .cr_raddr  (cr_raddr),
        .cr_rd_done(cr_rd_done),
        .cr_rdata  (cr_rdata)
    );

    // ---- xbus demux: one request, three slaves, ack and data back by region ----
    wire        xs_ack, xc_ack, xl_ack;
    wire [31:0] xs_rdata, xc_rdata, xl_rdata;
    assign xb_ack   = (xb_region == 2'd0) ? xs_ack   : (xb_region == 2'd1) ? xc_ack   : xl_ack;
    assign xb_rdata = (xb_region == 2'd0) ? xs_rdata : (xb_region == 2'd1) ? xc_rdata : xl_rdata;

    wire [31:0] xs_ld_words, xs_sn_words;
    wire [15:0] xs_ld_lost;

    // ---- xram step 2: option D (paprium_mcd_link, clk_md) and the snoop (clk_sys) ----
    wire [23:0] xl_d_word, xl_d_busy;
    wire [15:0] xl_pend;
    wire        xl_arm_tg, xl_od_en;
    wire  [3:0] xl_clr_tg;
    wire  [7:0] xl_hold;
    wire  [3:0] od_flags;
    wire        od_armed, od_sres, od_sbrq;
    wire  [7:0] od_late;
    wire [15:0] od_posts;
    wire [23:0] od_tick;
    wire        od_en_mirror, od_en_prg;

    // the option-D state resets with the cartridge (shell_reset, the clk_md source of sys_reset,
    // which resets the MCU), not with md_reset
    paprium_mcd_link #(.CLK_MD_HZ(CLK_MD_HZ)) mcd_link (
        .clk         (clk_md_107_39),
        .reset       (shell_reset),
        .en_cd       (scum_s[19]),
        .cart_addr   (cart_addr),
        .cart_lwr    (cart_lwr),
        .cart_data_wr(cart_data_wr),
        .g3_q        (od_g3),
        .d_word      (xl_d_word),
        .d_busy      (xl_d_busy),
        .pend        (xl_pend),
        .arm_tg      (xl_arm_tg),
        .clr_tg      (xl_clr_tg),
        .od_en       (xl_od_en),
        .hold        (xl_hold),
        .busy        (od_busy),
        .comstat2    (od_comstat2),
        .flags       (od_flags),
        .armed       (od_armed),
        .sres_run    (od_sres),
        .sbrq        (od_sbrq),
        .late_count  (od_late),
        .post_count  (od_posts),
        .tick        (od_tick),
        .en_mirror   (od_en_mirror),
        .en_prg      (od_en_prg)
    );

    wire  [1:0] sn_en_s;
    synch_3 #(.WIDTH(2)) sn_en_sync (.i({od_en_prg, od_en_mirror}), .o(sn_en_s), .clk(clk_sys_53_69));

    wire        sn_valid, sn_take;
    wire [16:0] sn_waddr;
    wire [15:0] sn_data;
    wire  [1:0] sn_be;
    wire [15:0] sn_ovf, sn_prg;

    paprium_snoop snoop (
        .clk         (clk_sys_53_69),
        .reset       (xmem_reset),
        .en_mirror   (sn_en_s[0]),
        .en_prg      (sn_en_s[1]),
        .cart_addr   (cart_addr),
        .cart_lwr    (cart_lwr),
        .cart_uwr    (cart_uwr),
        .cart_data_wr(cart_data_wr),
        .sn_valid    (sn_valid),
        .sn_waddr    (sn_waddr),
        .sn_data     (sn_data),
        .sn_be       (sn_be),
        .sn_take     (sn_take),
        .stat_prg    (sn_prg),
        .stat_overflow(sn_ovf)
    );

    paprium_xram xram (
        .clk  (clk_sys_53_69),
        .reset(xmem_reset),

        .cfg_rd  (xcfg[3:0]),
        .cfg_wp  (xcfg[7:4]),
        .cfg_lock(xcfg[16]),

        .ld_wr  (xld_wr),
        .ld_addr(xld_addr),
        .ld_data(xld_data),

        .sn_valid(sn_valid),            // xram step 2: the 68000 Word RAM / PRG snoop
        .sn_waddr(sn_waddr),
        .sn_data (sn_data),
        .sn_be   (sn_be),
        .sn_take (sn_take),

        .mc_req  (xb_req & (xb_region == 2'd0)),
        .mc_addr (xb_addr[17:0]),
        .mc_sel  (xb_sel),
        .mc_wr   (xb_wr),
        .mc_wdata(xb_wdata),
        .mc_rdata(xs_rdata),
        .mc_ack  (xs_ack),

        .sram_a   (sram_a),
        .sram_dq  (sram_dq),
        .sram_oe_n(sram_oe_n),
        .sram_we_n(sram_we_n),
        .sram_ub_n(sram_ub_n),
        .sram_lb_n(sram_lb_n),

        .stat_loader_writes(xs_ld_words),
        .stat_loader_lost  (xs_ld_lost),
        .stat_snoop_writes (xs_sn_words)
    );

    wire [31:0] xc_ops;
    wire [15:0] xc_lost;
    wire        xc_ready;

    paprium_cram cram (
        .clk  (clk_sys_53_69),
        .reset(xmem_reset),

        .cfg_rd(xcfg[11:8]),
        .cfg_we(xcfg[15:12]),

        .a_wr     (cr_wr),              // synth step: the sound-cache slot's load / flush (was the CDDA ring)
        .a_waddr  (cr_waddr),
        .a_wdata  (cr_wdata),
        .a_rd     (cr_rd),
        .a_raddr  (cr_raddr),
        .a_rd_done(cr_rd_done),
        .a_rdata  (cr_rdata),

        // synth step: port C = the synth's stream reads (PAPRIUM_SYNTH), else unused; port E = the synth's rings and
        // dac_buf (PAPRIUM_SYNTH), else test build 4 / 4a's SFX echo line, slot s = the pair {8'h84, s, 1'b0} (die word
        // 0x210000 + 2s, as the controller's old E_BASE_W)
        .c_rd     (PAPRIUM_SYNTH ? syn_c_rd : 1'b0),
        .c_raddr  (PAPRIUM_SYNTH ? syn_c_raddr : 21'd0),
        .c_rd_done(syn_c_rd_done),
        .c_rdata  (syn_c_rdata),

        .e_wr     (PAPRIUM_SYNTH ? syn_e_wr    : echo_wr),
        .e_waddr  (PAPRIUM_SYNTH ? syn_e_waddr : {8'h84, echo_wslot, 1'b0}),
        .e_wpair  (PAPRIUM_SYNTH ? syn_e_wpair : 1'b1),
        .e_wdata  (PAPRIUM_SYNTH ? syn_e_wdata : echo_wdata),
        .e_rd     (PAPRIUM_SYNTH ? syn_e_rd    : echo_rd),
        .e_raddr  (PAPRIUM_SYNTH ? syn_e_raddr : {8'h84, echo_rslot, 1'b0}),
        .e_rpair  (PAPRIUM_SYNTH ? syn_e_rpair : 1'b1),
        .e_rd_done(echo_rd_done),
        .e_rdata  (echo_rdata),
        .e_wbusy  (syn_e_wbusy),
        .e_rbusy  (),

        .b_req  (xb_req & (xb_region == 2'd1)),
        .b_addr (xb_addr[21:0]),
        .b_sel  (xb_sel),
        .b_wr   (xb_wr),
        .b_wdata(xb_wdata),
        .b_rdata(xc_rdata),
        .b_ack  (xc_ack),

        .cram_a    (cram0_a),
        .cram_dq   (cram0_dq),
        .cram_clk  (cram0_clk),
        .cram_adv_n(cram0_adv_n),
        .cram_cre  (cram0_cre),
        .cram_ce0_n(cram0_ce0_n),
        .cram_ce1_n(cram0_ce1_n),
        .cram_oe_n (cram0_oe_n),
        .cram_we_n (cram0_we_n),
        .cram_ub_n (cram0_ub_n),
        .cram_lb_n (cram0_lb_n),

        .ready       (xc_ready),
        .stat_ops    (xc_ops),
        .stat_aw_lost(xc_lost),
        .stat_e_lost ()
    );

    assign echo_ready = xc_ready;
    assign syn_e_rd_done = echo_rd_done;   // synth step: port E answers its one client
    assign syn_e_rdata   = echo_rdata;

    paprium_xlink #(.STAGE2(1'b1)) xlink (
        .clk  (clk_sys_53_69),
        .reset(xmem_reset),
        .od_reset(sys_reset),

        .req  (xb_req & (xb_region == 2'd2)),
        .addr (xb_addr[6:0]),           // synth step (v1.3): addr[6:2], 32 word slots (was addr[5:0])
        .wr   (xb_wr),
        .wdata(xb_wdata),
        .rdata(xl_rdata),
        .ack  (xl_ack),

        .xcfg(xcfg),

        .st_snoop      (xs_sn_words),
        .st_loaded     (xs_ld_words),
        .st_cram_ops   (xc_ops),
        .st_underruns  (cdda_underruns),
        .st_snoop_ovf  (sn_ovf),
        .st_snoop_prg  (sn_prg),
        .st_loader_lost(xs_ld_lost),
        .st_cram_lost  (xc_lost),
        .st_cram_ready (xc_ready),

        .d_word(xl_d_word), .d_busy(xl_d_busy), .pend(xl_pend), .arm_toggle(xl_arm_tg),
        .clr_toggle(xl_clr_tg), .od_en(xl_od_en), .od_hold(xl_hold),
        .stub_lstat({od_sbrq, od_sres, od_armed, od_busy, od_flags}),
        .stub_late_count(od_late), .stub_post_count(od_posts), .stub_tick(od_tick),
        .link_status(od_link_status),
        .post_bit(od_post_bit),      // pocket: new core

        // pocket: synth step (MCU interface v1.3 section 3.9) - CACHE, CACHE_LOADED, BAR
        .cache_valid    (xl_cache_valid),
        .cache_size     (xl_cache_size),
        .st_cache_loaded(cache_loaded),
        .bar_en         (xl_bar_en),
        .bar_px         (xl_bar_px),
        .bar_w          (bar_w_sys),
        .st_fw_len_bad  (fw_len_bad)       // Fafrium: XLINK FAFRIUM bit 0 (from cartridge.sv, on clk_sys)
    );

  end
  else begin : xmem_tie
    assign echo_ready   = 0;    // pocket: no CRAM controller, no echo line
    assign echo_rd_done = 0;
    assign echo_rdata   = 0;
    assign syn_c_rd_done = 0;   // pocket: synth step - nor the synth's ports
    assign syn_c_rdata   = 0;
    assign syn_e_rd_done = 0;
    assign syn_e_rdata   = 0;
    assign syn_e_wbusy   = 0;

    // tie off PSRAM, unused (ROM lives in SDRAM)
    assign cram0_a     = 'h0;
    assign cram0_dq    = {16{1'bZ}};
    assign cram0_clk   = 0;
    assign cram0_adv_n = 1;
    assign cram0_cre   = 0;
    assign cram0_ce0_n = 1;
    assign cram0_ce1_n = 1;
    assign cram0_oe_n  = 1;
    assign cram0_we_n  = 1;
    assign cram0_ub_n  = 1;
    assign cram0_lb_n  = 1;

    // tie off SRAM, unused
    assign sram_a      = 'h0;
    assign sram_dq     = {16{1'bZ}};
    assign sram_oe_n   = 1;
    assign sram_we_n   = 1;
    assign sram_ub_n   = 1;
    assign sram_lb_n   = 1;

    assign xb_ack      = 1'b1;
    assign xb_rdata    = 32'hffffffff;
    assign od_busy        = 1'b0;   // pocket: xram step 2
    assign od_comstat2    = 16'd0;
    assign od_link_status = 7'd0;
    assign od_post_bit    = 1'b0;   // pocket: new core
    assign cr_rd_done  = 1'b0;
    assign cr_rdata    = 16'd0;
    assign cr_wr       = 1'b0;      // pocket: synth step - no cache slot without the Paprium memories
    assign cr_waddr    = 22'd0;
    assign cr_wdata    = 16'd0;
    assign cr_rd       = 1'b0;
    assign cr_raddr    = 22'd0;
    assign cache_rd_data  = 32'd0;
    assign datatable_addr = 10'd3;      // the save's size word alone, as before the synth step
    assign datatable_data = save_dt;
    assign xl_bar_en   = 1'b0;
    assign xl_bar_px   = 11'd0;
  end
  endgenerate
  // pocket-end

  // pocket: Scum! switches and the pads' X/Y/Z/Mode, straight from the APF side into
  // the cartridge's clk_ram domain. {MODE,X,Y,Z} = Select, L, X, R, the buttons
  // input.json already labels Mode, X, Y and Z
  wire [21:0] scum_s;

  synch_3 #(
      .WIDTH(22)
  ) scum_sync (
      .i({scum_tap,                   // 0.3.0: bit 21 = the EA 4-Way Play asked for (taken at boot below)
          scum_arc3p,                 // 0.3.0: bit 20 = Arcade Mode Multiplayer
          opt_cd_real, scum_32x,      // 0.2.6: bit 19 = a recognised Mega CD unit (was Mega CD Mode)
          cont2_key[14], cont2_key[8], cont2_key[6], cont2_key[9],
          cont1_key[14], cont1_key[8], cont1_key[6], cont1_key[9],
          scum_stage, scum_6btn, scum_arcade, scum_cheats}),
      .o(scum_s),
      .clk(clk_md_107_39)
  );

  // 0.3.0 (B Jam's revised decision of 2026-10-11 on the EA 4-Way Play): the game looks for the EA 4-Way Play once, at
  // boot ($B1E3C), so the adapter is taken only while the 68000 is held in reset (md_reset_effective: power-on and
  // loading, every core reset and Soft Reset, the MCU's HOLD) and held while the game runs; a menu change waits for the
  // next Soft Reset. Off (the default) gives the ports exactly as 0.2.6. tap_md feeds the Scum! pad hook (cartridge,
  // this clock) and, through tap_sync, the pads (clk_sys); it changes only while the 68000 is held, so the crossing is
  // quiet
  reg         tap_md = 1'b0;
  always @(posedge clk_md_107_39) if (md_reset_effective) tap_md <= scum_s[21];
  wire        tap_sys;
  wire        tap_sys_nx;   // fit round 2: the value tap_sys takes at the next clk_sys (paprium_pads' look-ahead)
  synch_3 tap_sync (.i(tap_md), .o(tap_sys), .clk(clk_sys_53_69), .nxt(tap_sys_nx));

  // 0.3.0 synth step: the Grand Stick III's settings, taken at boot exactly as the adapter is ({on, EXT socket,
  // Select = coin, switch byte}): the game detects the stick at boot ($B1DBC) and reads its switches once per power-on
  // or reset ($B5A32), so a menu change waits for the next Soft Reset, and the crossing into clk_sys is quiet (they
  // change only while the 68000 is held)
  wire  [8:0] gs3_s;
  synch_3 #(.WIDTH(9)) gs3_md_sync (.i({gs3_on_74, gs3_pt_74, gs3_coin_74, gs3_dip_74}), .o(gs3_s), .clk(clk_md_107_39));
  reg   [8:0] gs3_md = 9'd0;
  always @(posedge clk_md_107_39) if (md_reset_effective) gs3_md <= gs3_s;
  wire  [8:0] gs3_sys;
  wire  [8:0] gs3_sys_nx;   // the value gs3_sys takes at the next clk_sys (paprium_pads' look-ahead uses bit 8)
  synch_3 #(.WIDTH(9)) gs3_sys_sync (.i(gs3_md), .o(gs3_sys), .clk(clk_sys_53_69), .nxt(gs3_sys_nx));
  // pocket-end

  cartridge #(
      .SVP(SVP),
      .PAPRIUM(PAPRIUM),
      .PAPRIUM_SFX(PAPRIUM_SFX),
      .PAPRIUM_CMDLOG(PAPRIUM_CMD_LOG),
      .CLK_HZ(CLK_HZ),
      .CLK_MD_HZ(CLK_MD_HZ),  // pocket: new core - clk_md, on to sdram's refresh compares
      .PAPRIUM_FEAT(PAPRIUM_FEAT),  // pocket: synth step - FPGAIO FEAT (MCU interface v1.3 section 4.10)
      .PAPRIUM_SYNTH(PAPRIUM_SYNTH) // pocket: synth step - region 0x06 = the synth
  ) cartridge (
      .clk        (clk_sys_53_69),
      .clk_ram    (clk_md_107_39),
      .reset      (sys_reset),
      .reset_sdram(~pll_core_locked),
      .pap_reset  (pap_reset),   // Fafrium
      .fw_done    (fw_done),     // Fafrium
      .fw_go      (fw_go),       // Fafrium
      .fw_len_bad (fw_len_bad),  // Fafrium

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
      .cart_data   (cart_data_cart),
      .cart_data_wr(cart_data_wr),
      .cart_cs     (cart_cs),
      .cart_oe     (cart_oe),
      .cart_lwr    (cart_lwr),
      .cart_uwr    (cart_uwr),
      .cart_time   (cart_time),
      .cart_data_en(cart_data_en_cart),
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
      .paprium_cd_none (opt_cd_unit_s == 4'd0),   // new core: Mega CD None, clk_md
      .paprium_opt_at_reset_en(opt_at_reset_en),   // new core: CTRL bit 5
      .paprium_console_reset(cr_post_sys),        // pocket: test build S3c - Console Reset -> FPGAIO CAUSE.V
      .paprium_cause_v(cr_cause_v),               // pocket: test build S3c - CAUSE.V pending: the 68000 stays held
      .cmdlog_read_addr(cmdlog_read_addr),
      .cmdlog_read_data(cmdlog_read_data),

      .paprium_sfx_l   (paprium_sfx_l),
      .paprium_sfx_r   (paprium_sfx_r),
      .paprium_menu_mute_en(paprium_menu_mute_en),   // pocket: 0.3.0 new core, the Pocket-menu music mute

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

      .scum_health(scum_s[0]),
      .scum_pills (scum_s[1]),
      .scum_lives (scum_s[2]),
      .scum_arcade(scum_s[3]),
      .scum_arc3p (scum_s[20]),      // 0.3.0: Arcade Mode Multiplayer
      .scum_tap   (tap_md),          // 0.3.0: the EA 4-Way Play present (taken at boot)
      .scum_6btn  (scum_s[4]),
      .scum_stage (scum_s[9:5]),
      .scum_pad1  (scum_s[13:10]),
      .scum_pad2  (scum_s[17:14]),

      // pocket: xram step 1
      .xb_req   (xb_req),
      .xb_region(xb_region),
      .xb_addr  (xb_addr),
      .xb_sel   (xb_sel),
      .xb_wr    (xb_wr),
      .xb_wdata (xb_wdata),
      .xb_rdata (xb_rdata),
      .xb_ack   (xb_ack),

      // pocket: xram step 2
      .link_status(od_link_status),
      .link_post  (od_post_bit),    // pocket: new core
      .vs_tog     (paprium_vs_tog_s),   // pocket: new core (MCU interface v1.1) - FPGAIO VSCNT
      // 0.2.6: the cart MCU's GPIO input. New core (MCU_INTERFACE v1.0 section 5): {PAL build, Console region
      // is Japan, Pocket menu open, MegaWire, model bits}; the top three become option word bits 26, 25, 24
      .mcu_opts   ({PAL ? 1'b1 : 1'b0, mcu_opts_s[5], inmenu_sys_s, mcu_opts_s[4:0]}),

      .echo_ready  (echo_ready),
      .echo_wr     (echo_wr),
      .echo_wslot  (echo_wslot),
      .echo_wdata  (echo_wdata),
      .echo_rd     (echo_rd),
      .echo_rslot  (echo_rslot),
      .echo_rd_done(echo_rd_done),
      .echo_rdata  (echo_rdata),

      // pocket: synth step - the synth's CRAM clients (unused while PAPRIUM_SYNTH = 0)
      .syn_c_rd     (syn_c_rd),
      .syn_c_raddr  (syn_c_raddr),
      .syn_c_rd_done(syn_c_rd_done),
      .syn_c_rdata  (syn_c_rdata),
      .syn_e_wr     (syn_e_wr),
      .syn_e_waddr  (syn_e_waddr),
      .syn_e_wpair  (syn_e_wpair),
      .syn_e_wdata  (syn_e_wdata),
      .syn_e_rd     (syn_e_rd),
      .syn_e_raddr  (syn_e_raddr),
      .syn_e_rpair  (syn_e_rpair),
      .syn_e_rd_done(syn_e_rd_done),
      .syn_e_rdata  (syn_e_rdata),
      .syn_e_wbusy  (syn_e_wbusy),

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

  // pocket: the controller ports, no md_io.sv, because nothing on the Pocket needs its keyboard, lightgun or
  // J-Cart muxing. 0.3.0 (paprium_pads.sv): Pocket controllers 1-3 behind an emulated EA 4-Way Play on ports
  // A and B; the game finds it at boot and reads pads A-C through it, so its own three-player modes work with three
  // Dock controllers. Controller 3 counts only as a docked pad (type 2 or 3). 0.3.0 (B Jam's revised decision of
  // 2026-10-11 on the EA 4-Way Play):
  // the adapter is present only when 3-Player Mode = On or Arcade Mode = Multiplayer (tap_sys, taken at boot,
  // above), and its pads are six-button pads with 6-Button on. Otherwise fourway = 0: 0.2.6's wiring (pad 1 on
  // port A, pad 2 on port B). Test build 4 (B Jam 2026-10-16): MODE = the 6-Button switch on the direct ports too (real
  // six-button pads: pad_io counts the first TH rise; the Scum! hook injects nothing), and a pad whose Pocket
  // controller is not there reads as an empty port or socket. MD A-B-C lands on Y-B-A as on the fpgagen Genesis core, and the EXT
  // port reads back whatever the console drives, since there is nothing plugged into it. Synth step: with Arcade
  // Mode On, Multiplayer or Stick Only, port A is a virtual Grand Stick III on controller 1 (its EXT socket = Dock
  // controller 3, port B = pad 2, no EA 4-Way Play); Arcade Mode Off is test build 4's wiring on every clock

  wire [31:0] cont1_key_s;
  wire [31:0] cont2_key_s;
  wire [31:0] cont3_key_s;

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

  // controller 3: the buttons and the type field only
  wire [19:0] cont3_key_nx;   // fit round 2: the next value of {type, buttons} (paprium_pads' look-ahead uses the type)
  synch_3 #(
      .WIDTH(20)
  ) cont3_sync (
      .i  ({cont3_key[31:28], cont3_key[15:0]}),
      .o  ({cont3_key_s[31:28], cont3_key_s[15:0]}),
      .clk(clk_sys_53_69),
      .nxt(cont3_key_nx)
  );
  assign cont3_key_s[27:16] = 12'd0;

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
  paprium_pads pads (
      .clk    (clk_sys_53_69),
      .reset  (sys_reset),
      .mode6  (scum_6btn_s),                          // test build 4: the 6-Button switch, adapter or not (it was
                                                      // 0.2.6's cfg_6btn without the adapter)
      .fourway(tap_sys),                              // 0.3.0: the EA 4-Way Play, taken at boot
      .fourway_nx(tap_sys_nx),                        // fit round 2: their next values, for the look-ahead registers
      .key3_type_nx(cont3_key_nx[19:16]),
      .gs3_on   (gs3_sys[8]),                         // synth step: the Grand Stick III in port 1, taken at boot
      .gs3_on_nx(gs3_sys_nx[8]),
      .gs3_pt   (gs3_sys[7]),                         // its EXT socket = Dock controller 3
      .gs3_coin (gs3_sys[6]),                         // Select is the coin
      .gs3_dip  (gs3_sys[5:0]),                       // its switch byte
      .hold     (inmenu_sys_s),                       // the Pocket menu froze the 68000: the stick's timer waits
      .key1   (cont1_key_s),
      .key2   (cont2_key_s),
      .key3   (cont3_key_s),
      .pa_o   (PA_o),
      .pa_d   (PA_d),
      .pb_o   (PB_o),
      .pb_d   (PB_d),
      .pa_i   (PA_i),
      .pb_i   (PB_i)
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

  // pocket: synth step, the FM-chip trims T1-T6 (measurement only) - the Paprium build ties off FM-chip (ym3438)
  // features the cart's Z80 driver never uses. YM_TRIM bits: 0 T1 LFO (reg 22), 2 T3 ch3 mode / CSM / A8-AE, 3 T4
  // timers A / B, 4 T5 test registers 21 / 2C and the debug read. Bit 1 (T2 SSG-EG, needs well-formed packets) and bit
  // 5 (T6 AM, data-dependent) act only where two separate patches of ours add their code (not in this repository).
  // Every other
  // variant builds the full chip (YM_TRIM = 0, the die-derived RTL unchanged).
  localparam [5:0] YM_TRIM = PAPRIUM ? 6'h1D : 6'h00;

  md_board #(.YM_TRIM(YM_TRIM)) md_board (
      .MCLK2(clk_md_107_39),

      .ext_reset   (md_reset_effective),  // paprium: the MCU holds the 68000 while it boots
      .reset_button(btn_reset | cr_btn),   // pocket: test build S3c - + the Console Reset's button press
      // md_board.v reads these, MiSTer leaves them dangling
      .ext_vres    (cr_hold),             // pocket: test build S3c - the 68000 held until the warm page is in (Console Reset)
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
      .ext_dtack       (cart_dtack | addon_dtack),   // 0.2.6: + TMSS-lite
      .pal             (PAL),
      .jap             (cfg_jap_s),
      .disk_n          (opt_disk_n_s),               // 0.2.6: version register bit 5
      .version         ({3'b000, opt_ver1_s}),       // 0.2.6: version nibble
      .td_en           (opt_td_en_s),                // 0.3.0: TeraDrive stub (128 KB VRAM test)

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
      .vdp_cramdot_dis(~CFG_CRAMDOT),   // paprium: menu removed, tied off
      .vdp_hsync2     (),

      .ym2612_status_enable(ym2612_quirk),
      .dma_68k_req         (dma_68k_req),
      .dma_z80_req         (dma_z80_req),
      .dma_z80_ack         (dma_z80_ack),
      .res_z80             (res_z80)
  );
  // pocket-end

  // pocket: 0.3.0 new core (MCU interface v1.1) - the VS counter for the TEST freeze telemetry (the firmware's freeze
  // counters, B Jam 2026-10-13): every start of the VDP's vertical sync flips one bit on clk_md, which crosses into
  // clk_sys through a synch_3 (SDC block VS: false path into its first stage only) and is counted by fpgio into FPGAIO
  // slot 16. A frozen count beside a live MCU heartbeat says the VDP stopped; a live count with no 9494 posts says the
  // 68000 did
  paprium_vs_tap paprium_vs_tap (
      .clk_md  (clk_md_107_39),
      .vs_n    (vdp_vs),
      .clk_sys (clk_sys_53_69),
      .vs_tog_s(paprium_vs_tog_s)
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
      .blender  (CFG_BLEND),  // paprium: menu removed, tied off

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

  // pocket: synth step (test build 5, a project decision) - video_de / video_rgb / video_hs / video_vs are chosen
  // below, after the core's own picture, by paprium_holdvid (black frames with the first-boot bar while the console is
  // held)
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

  // The VDP syncs come out active low and the filler's edge detects want active high. pocket (0.3.0, from the new
  // core's fit gate): the filler takes them active low (SYNC_N) and inverts them after its capture registers, so the
  // clk_md -> dot clock crossing has no logic in it (an inverter here was one LUT level on two of the 28 pairs, which
  // the same-edge window forbids)

  wire [23:0] filler_rgb;
  wire        filler_de;
  wire [ 7:0] snap_index;
  wire        filler_hs;   // pocket: synth step (test build 5) - the filler's syncs; paprium_holdvid picks video_hs / video_vs
  wire        filler_vs;
  // pocket: synth step (test build 5, a project decision) - paprium_holdvid's outputs (below the bar block): gen = it
  // drives all four video outputs on this clock (its DE / RGB are registered one clock behind its syncs, as
  // video_de_reg / video_rgb_reg are behind the filler's), w = its active width
  wire        hv_gen, hv_hs, hv_vs, hv_de;
  wire [23:0] hv_rgb;
  wire [10:0] hv_w;

  // A 224 to 240 change moves video_cond's blanking window in the same frame the
  // scaler is told the new height, so that frame comes out short. The filler pads
  // every frame back up to its snap point with black lines.
  // HSYNC_DELAY: 7 dot clocks, the VS to HS separation the VDP syncs had before
  scanline_filler #(
      .SNAP_COUNT (2),
      .SNAP_POINTS('{240, 224}),
      .HSYNC_DELAY(7),
      .SYNC_N     (1'b1)
  ) scanline_filler (
      .clk(clk_vid),

      .hsync_in(core_hs),   // active low (SYNC_N)
      .vsync_in(core_vs),

      .vblank_in(core_vblank),
      .hblank_in(core_hblank),
      .rgb_in   (core_rgb),

      .hsync(filler_hs),
      .vsync(filler_vs),

      .de (filler_de),
      .rgb(filler_rgb),

      .snap_index(snap_index)
  );

  // pocket: synth step (MCU interface v1.3 sections 3.9 / 21.2, test builds 4a / 4b) - the first-boot bar. XLINK BAR
  // (clk_sys) crosses into the dot clock through bar_sync, a three-flop synchroniser whose first stage is a false path
  // (core_constraints.sdc, the dot-clock RULE: no timed pair into clk_vid from another clock); paprium_bar lights the
  // last 4 active lines for PX pixels from the first active pixel while EN = 1, and measures W, which goes back to
  // XLINK through bar_w_sync (first stage false path too). Both values are quasi-static (a PX write per unpack chunk;
  // W changes only at an H32 / H40 switch), so a word caught mid-change is right again one clock later. EN = 0 (every
  // reset, and the firmware clears it before it releases the 68000) leaves the picture as the core makes it
  wire [11:0] bar_vid;   // {EN, PX} on clk_vid
  wire        bar_lit;
  wire [10:0] bar_w_vid;
  synch_3 #(.WIDTH(12)) bar_sync (.i({xl_bar_en, xl_bar_px}), .o(bar_vid), .clk(clk_vid));
  paprium_bar paprium_bar (
      .clk(clk_vid),
      .en (bar_vid[11]),
      .px (bar_vid[10:0]),
      .de (filler_de),
      .vs (filler_vs),
      .lit(bar_lit),
      .w  (bar_w_vid)
  );
  synch_3 #(.WIDTH(11)) bar_w_sync (.i(hv_gen ? hv_w : bar_w_vid), .o(bar_w_sys), .clk(clk_sys_53_69));

  reg prev_de = 0;
  reg prev_vs = 0;
  reg slot_h32 = 0;
  reg slot_arcorr = 0;
  reg [7:0] latched_snap_index = 0;

  always @(posedge clk_vid) begin
    prev_de <= filler_de;
    prev_vs <= filler_vs;

    video_de_reg <= 0;

    if (filler_vs && ~prev_vs) begin
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
      video_rgb_reg <= filler_rgb | {24{bar_lit}};   // pocket: synth step - the first-boot bar is white (0xFFFFFF)
    end else begin
      // pocket (0.3.0): the APF wants rgb at 0 while DE is low, apart from the slot word on
      // the first blanked pixel. It used to stay on the bus until the next line's DE
      video_rgb_reg <= 24'd0;
    end
  end

  // pocket: synth step (test build 5; a project decision, confirmed by B Jam 2026-10-23) - a valid picture for the
  // whole cart hold. While md_reset_effective holds the console (the first start's ~20 s unpack among others) the VDP
  // makes no sync and the Dock kept a stale frame (test build 4b). paprium_holdvid then puts black frames at the VDP's
  // own rates on the four APF video outputs, with the first-boot bar on them, and hands back to the core's picture on
  // the filler's first VS after the release. It only selects between two complete pictures after everything above:
  // md_board, the filler, paprium_bar and the slot-word registers are untouched, so the picture outside a hold and the
  // game's boot are as before. The hold crosses from clk_md through hold_vid_sync, whose first stage is a false path
  // (core_constraints.sdc HOLDV, the dot-clock RULE); the Paprium variant only (elsewhere the input is 0 and synthesis
  // removes the block)
  wire hold_vid;
  synch_3 hold_vid_sync (.i(PAPRIUM ? md_reset_effective : 1'b0), .o(hold_vid), .clk(clk_vid));
  paprium_holdvid #(.PAL(PAL)) paprium_holdvid (
      .clk   (clk_vid),
      .hold  (hold_vid),
      .h32   (h32_s),
      .arcorr(cfg_arcorr_s),
      .bar_en(bar_vid[11]),
      .bar_px(bar_vid[10:0]),
      .f_vs  (filler_vs),
      .gen   (hv_gen),
      .hs    (hv_hs),
      .vs    (hv_vs),
      .de_q  (hv_de),
      .rgb_q (hv_rgb),
      .w     (hv_w)
  );
  // One select for all four: each clock's outputs are one picture's own sample, so the handover clock and every clock
  // after it are video_de_reg / video_rgb_reg / the filler's syncs exactly, and VS never meets the other picture's DE
  assign video_hs  = hv_gen ? hv_hs  : filler_hs;
  assign video_vs  = hv_gen ? hv_vs  : filler_vs;
  assign video_de  = hv_gen ? hv_de  : video_de_reg;
  assign video_rgb = hv_gen ? hv_rgb : video_rgb_reg;
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

      .lpf_mode(CFG_LPF),   // paprium: hard-wired to No Filter
      .fm_mode (CFG_FM),    // paprium: YM2612 only

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
  // MisterPezz82 set the Paprium gain by A/B recording against real hardware: Paprium
  // mixes its music against its own loud cart SFX and needs ~+10 dB (294/256) where
  // ordinary MD+ content takes 93/256. Carried over rather than rediscovered, and
  // confirmed on hardware here - with the game's own audio options set correctly the
  // cart effects are loud and clear at 294, so the boost is right and the mix is not
  // the limiting factor. An earlier reading of "SFX inaudible under music" led to a
  // plan to drop this to 93; hardware refuted it before the build shipped.
  //
  // The non-Paprium arm was previously 294 as well, which is wrong for plain MD+ CDDA
  // by about 10 dB - MiSTer selects on paprium_active and only Paprium gets the boost.
  // PAPRIUM is a localparam, so the unused arm folds away.
  //
  // The adjustable menu that measured the masking has served its purpose and is gone;
  // the gain is a constant again, so the multiplier folds back to shift-adds. The mix
  // below still hard-clips (294 plus full-scale FM plus full-scale cart SFX overflows a
  // 16-bit output about threefold) - that is inherited from MiSTer and left alone.
  localparam signed [9:0] CDDA_MULT_DEFAULT = PAPRIUM ? 10'sd294 : 10'sd93;

  wire signed [9:0] cdda_mult = CDDA_MULT_DEFAULT;

  wire signed [25:0] cdda_scaled_l = $signed(cdda_l) * cdda_mult;
  wire signed [25:0] cdda_scaled_r = $signed(cdda_r) * cdda_mult;
  wire signed [17:0] cdda_att_l    = cdda_scaled_l >>> 8;
  wire signed [17:0] cdda_att_r    = cdda_scaled_r >>> 8;

  // pocket: 0.3.0 new core, the Pocket-menu music mute - the cart SFX pair is 0 while menu_mute holds (see its
  // declaration)
  wire signed [15:0] sfx_mix_l = menu_mute ? 16'sd0 : paprium_sfx_l;
  wire signed [15:0] sfx_mix_r = menu_mute ? 16'sd0 : paprium_sfx_r;

  wire signed [18:0] mix_l = $signed(base_audio_l) + $signed(sfx_mix_l) + $signed(cdda_att_l);
  wire signed [18:0] mix_r = $signed(base_audio_r) + $signed(sfx_mix_r) + $signed(cdda_att_r);

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
