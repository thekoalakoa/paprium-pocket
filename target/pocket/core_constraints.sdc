#
# user core constraints
#
# put your clock groups in here as well as any net assignments
#
# Only the banner above survives from open-fpga/core-template/src/fpga/core/core_constraints.sdc, which
# is 14 lines and constrains nothing. The clock grouping below is local: agg23/openfpga-NES and
# agg23/openfpga-SNES each put every PLL output in its own asynchronous group, which is wrong for
# outputs that share a VCO.
#

# All six sys_pll outputs come off the same VCO and are phase-related, so they
# share one group, where SNES and NES split theirs. The raster output samples the
# general[1] domain from general[2] or general[4] directly, so those crossings have
# to stay timed
set_clock_groups -asynchronous \
 -group { bridge_spiclk } \
 -group { clk_74a } \
 -group { clk_74b } \
 -group { ic|mp1|altera_pll_i|general[0].gpll~PLL_OUTPUT_COUNTER|divclk \
          ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk \
          ic|mp1|altera_pll_i|general[2].gpll~PLL_OUTPUT_COUNTER|divclk \
          ic|mp1|altera_pll_i|general[3].gpll~PLL_OUTPUT_COUNTER|divclk \
          ic|mp1|altera_pll_i|general[4].gpll~PLL_OUTPUT_COUNTER|divclk \
          ic|mp1|altera_pll_i|general[5].gpll~PLL_OUTPUT_COUNTER|divclk } \
 -group { ic|audio_mixer|audio_pll|mf_audio_pll_inst|altera_pll_i|general[0].gpll~PLL_OUTPUT_COUNTER|divclk \
          ic|audio_mixer|audio_pll|mf_audio_pll_inst|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk }

# pocket: the H32/H40 dot clock mux is fabric, so STA propagates both clocks through
# it and analyzes every register in the video output domain under each. Only one is
# ever live, and a 6.71 MHz launch against a 5.37 MHz latch is a requirement no
# placement can meet, so cut that pair. Grouping is cumulative, so each dot clock
# stays timed against general[1], which is the crossing that carries real pixels
set_clock_groups -asynchronous \
 -group { ic|mp1|altera_pll_i|general[2].gpll~PLL_OUTPUT_COUNTER|divclk \
          ic|mp1|altera_pll_i|general[3].gpll~PLL_OUTPUT_COUNTER|divclk } \
 -group { ic|mp1|altera_pll_i|general[4].gpll~PLL_OUTPUT_COUNTER|divclk \
          ic|mp1|altera_pll_i|general[5].gpll~PLL_OUTPUT_COUNTER|divclk }

# Everything crossing general[1] into a dot clock is dot paced: video_cond updates
# rgb on its ce_pix, once per dot, and its sync and blanking flags change once per
# line at most. The dot is 16 general[1] cycles in H40 and 20 in H32, so charging
# the crossing a single cycle is far tighter than the value is actually held for.
# One latch cycle of relief is the whole stable window, which makes it the ceiling
# too, not room to spend: a path that really used a whole dot would capture the
# next one and shift the picture one pixel
set_multicycle_path -setup \
 -from {ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk} \
 -to   {ic|mp1|altera_pll_i|general[2].gpll~PLL_OUTPUT_COUNTER|divclk} 2
set_multicycle_path -hold \
 -from {ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk} \
 -to   {ic|mp1|altera_pll_i|general[2].gpll~PLL_OUTPUT_COUNTER|divclk} 1
set_multicycle_path -setup \
 -from {ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk} \
 -to   {ic|mp1|altera_pll_i|general[4].gpll~PLL_OUTPUT_COUNTER|divclk} 2
set_multicycle_path -hold \
 -from {ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk} \
 -to   {ic|mp1|altera_pll_i|general[4].gpll~PLL_OUTPUT_COUNTER|divclk} 1
# pocket-end

derive_clock_uncertainty

# pocket: FX68K micro/nanocode address. Ir, microAddr and nanoAddr load only on enT1
# (rtl/fx68k/fx68k.sv:270-272, 318-326). enT1 needs tState T4 and the same edge moves it
# to T1, so the next enT1 is at least 4 clocks later for ANY enPhi1/enPhi2 waveform, and
# 28 general[1] clocks with md_board's VCLK. The author's own constraint, fx68k.txt:57-73.
# Ir[n]~DUPLICATE copies are matched by these patterns: never add -no_duplicates.
set fx68k_ir   [get_registers -nowarn {*|fx68k:cpu|Ir[*]}]
set fx68k_uadr [get_registers -nowarn {*|fx68k:cpu|nanoAddr[*] *|fx68k:cpu|microAddr[*]}]
post_message "pocket: fx68k Ir [get_collection_size $fx68k_ir], uaddr [get_collection_size $fx68k_uadr]"
if {[get_collection_size $fx68k_ir] == 0 || [get_collection_size $fx68k_uadr] == 0} {
  post_message -type critical_warning "pocket: fx68k Ir->uaddr multicycle matched nothing"
}
set_multicycle_path -start -setup -from $fx68k_ir -to $fx68k_uadr 2
set_multicycle_path -start -hold  -from $fx68k_ir -to $fx68k_uadr 1
# pocket-end

# pocket: agg23 needs nothing here because its audio filters only ever run at
# audio_mclk, where a multiply has a whole sample period to land. audio_cond puts an
# iir_filter on clk_sys_53_69, where one cycle is not enough for a 16x40 multiply, a
# 37x24 multiply and the add that follows them.
#
# Nothing on those paths moves every cycle. Every register listed here is gated
# by the filter's ce, and so is every register that feeds it: intreg takes the
# other taps and inp, and out_l/out_r/out_m take y, which is inp and tap0.
# CEGen paces audio_cond's ce at 7.056 MHz off a 53.69 MHz clock, so captures
# are 7 cycles apart at the closest, and the filter in audio_filters.sv runs on
# a rate derived from the audio sample rate, which is slower still. Charging 2
# cycles is well inside both.
#
# inp and inp_m are deliberately not here. They latch the core's raw output,
# which does move every cycle, so their paths really are one cycle long.
set audio_iir_regs [get_registers { \
  *|iir_filter:*|iir_filter_tap:*|intreg[*] \
  *|iir_filter:*|out_l[*] \
  *|iir_filter:*|out_r[*] \
  *|iir_filter:*|out_m[*] \
  *|iir_filter:*|ch }]
set_multicycle_path -setup -to $audio_iir_regs 2
set_multicycle_path -hold  -to $audio_iir_regs 1
# pocket-end

# These APF/platform interfaces are protocol timed, source-synchronous to fixed
# board wiring, or handled inside the APF bridge, so they carry no external
# delays here. False-pathing them keeps the "fully constrained" check on the
# paths this core does constrain.
set_false_path -from [get_ports { \
  bridge_1wire bridge_spimiso bridge_spimosi bridge_spiss \
  port_tran_sck port_tran_sd port_tran_si \
}]

set_false_path -to [get_ports { \
  bridge_1wire bridge_spimiso bridge_spimosi \
  cram0_ce1_n cram0_clk \
  port_tran_sck port_tran_sck_dir port_tran_sd port_tran_sd_dir port_tran_so \
  scal_auddac scal_audlrck scal_audmclk scal_clk scal_de scal_hs scal_skip \
  scal_vid[*] scal_vs \
}]

# pocket: xram stage 1. The Pocket SRAM and cram0 are asynchronous parts the core does
# not clock (CRAM in async mode, CLK held low), so there is no external clock to write
# set_input_delay / set_output_delay against. Each pad crossing gets a delay BUDGET instead, and the
# controllers (PAPRIUM/paprium_xram.sv, paprium_cram.sv) spend whole clocks between launch and
# sample. The budgets are the xram facts probe's STA pad delays (worst of 4 corners, rounded up):
#   SRAM out 9.38 -> 10.0, in 4.51 -> 5.0; CRAM out 9.34 -> 10.0, in 4.78 -> 5.5; outputs never
#   earlier than 2.0 ns. With every pin register in its IOE (FAST_*_REGISTER in the qsf) they pass;
#   a register that falls out of its IOE fails them, which is the point. Only the Paprium variant
#   drives these pins; elsewhere they are constants and the collections time nothing.
set xram_sram_out [get_ports {sram_a[*] sram_dq[*] sram_oe_n sram_we_n sram_ub_n sram_lb_n}]
set_max_delay -to   $xram_sram_out 10.0
set_min_delay -to   $xram_sram_out 2.0
set_max_delay -from [get_ports {sram_dq[*]}] 5.0
set_min_delay -from [get_ports {sram_dq[*]}] 0.0

set xram_cram_out [get_ports {cram0_a[*] cram0_dq[*] cram0_adv_n cram0_cre cram0_ce0_n cram0_oe_n cram0_we_n cram0_ub_n cram0_lb_n}]
set_max_delay -to   $xram_cram_out 10.0
set_min_delay -to   $xram_cram_out 2.0
set_max_delay -from [get_ports {cram0_dq[*]}] 5.5
set_min_delay -from [get_ports {cram0_dq[*]}] 0.0
set_false_path -from [get_ports {cram0_wait}]
# pocket-end

# pocket: xram stage 2. The option-D values the MCU writes into paprium_xlink (clk_sys) reach
# paprium_mcd_link (clk_md) without a synchroniser of their own: mcd_link copies D_WORD / D_BUSY / PEND
# only on the clock its synchronised ARM toggle moves (>= 3 clk_md clocks after the MCU's ARM write,
# which follows the value writes) or, when that clock holds a $A12001 write, one clock later (buddy_s2
# finding 1: the ARM is latched until taken), and reads HOLD / the option-D enable as settings written long
# before a post. None of them changes near the edge that captures it, so the same-edge hold check
# between the two clocks is not a real path: two clk_md clocks of setup, hold edge one clock earlier.
set od_vals [get_registers {*|paprium_xlink:*|d_word[*] *|paprium_xlink:*|d_busy[*] *|paprium_xlink:*|pend[*] *|paprium_xlink:*|od_hold[*] *|paprium_xlink:*|od_en}]
set od_caps [get_registers {*|paprium_mcd_link:*}]
if {[get_collection_size $od_vals] == 0 || [get_collection_size $od_caps] == 0} {
  post_message -type critical_warning "pocket: xram stage-2 option-D multicycle matched nothing"
} else {
  set_multicycle_path -end -setup -from $od_vals -to $od_caps 2
  set_multicycle_path -end -hold  -from $od_vals -to $od_caps 2
}
# pocket-end

# pocket: xfix (2026-10-08) - clk_sys <-> clk_md crossings.
# Appended after the option-D block; goes with the SP-X RTL in cartridge.sv.
#
# general[0] = clk_sys_53_69 (VCO/12) and general[1] = clk_md_107_39 (VCO/6) come off one PLL with aligned
# edges, so STA times every crossing between them as synchronous: setup against the clk_md edge half way
# through a clk_sys period (9.312 ns), hold against the shared edge (0.000 ns). Each exception below removes
# only a check whose capture edge the RTL never uses for a value that changes on that edge, so the captured value
# and the edge it is captured on stay exactly what they are today. Setup stays timed everywhere except C2b, where
# the data is steady for >= 2 clk_sys before the capture. Every request / acknowledge toggle and every strobe
# sampler stays fully timed: the proofs depend on them.
set xf_md {ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk}
proc xf_col {tag col} {
  if {[get_collection_size $col] == 0} {
    post_message -type critical_warning "pocket: xfix $tag matched nothing"
  }
  return $col
}
set xf_sdram [xf_col sdram [get_registers {*|cartridge:cartridge|sdram:sdram|*}]]

# P2 - MCU port 2 address, write data, byte strobes. paprium_mcu_mem changes them only on the clk_sys edge that
# toggles mem_req (states 0 -> 1, 1 -> 2), or drops wrl/wrh after it has seen mem_ack == mem_req (states 2, 0).
# sdram takes addr2/din2/wrl2/wrh2 only on a clk_md edge where ack2 != req2. mem_req -> sdram stays timed, so on
# the shared edge sdram still sees req2 == ack2 and takes nothing; the first edge that can take them is the next
# clk_md edge, whose setup (9.312 ns) stays timed.
set xf_p2 [xf_col p2 [get_registers {*|paprium_mcu_mem:mem_inst|mem_addr* *|paprium_mcu_mem:mem_inst|mem_din* *|paprium_mcu_mem:mem_inst|mem_wrl* *|paprium_mcu_mem:mem_inst|mem_wrh*}]]
set_false_path -hold -from $xf_p2 -to $xf_sdram

# P2r - mem_req -> ack2 only. ack2 takes req2 only at the READY of a port-2 access, and req2 has not moved since
# that access was requested (mem_req toggles only after mem_ack == mem_req). mem_req -> every other sdram
# register (state, a, data, we, dqm, active, ram_req, rfs, starve2) stays timed.
set_false_path -hold -from [xf_col p2r_src [get_registers {*|paprium_mcu_mem:mem_inst|mem_req*}]] \
                     -to   [xf_col p2r_dst [get_registers {*|cartridge:cartridge|sdram:sdram|ack2*}]]

# P0 - ROM load, port 0. cart_wr_addr moves on the clk_sys edge that toggles rom_wr; the data_loader write_data
# one clk_sys earlier (cart_dl_wr is registered once more in cartridge.sv). Writes are >= 24 clk_sys apart
# (data_loader READ_WRITE_END = 23) and a port-0 write is done within 28 clk_md (14 clk_sys) even behind a
# refresh and a boosted port 2, so port 0 is idle in sdram whenever they move. rom_wr -> sdram stays timed.
set xf_p0 [xf_col p0 [get_registers {*|cartridge:cartridge|cart_wr_addr* *|data_loader:rom_data_loader|write_data*}]]
set_false_path -hold -from $xf_p0 -to $xf_sdram

# RM - rom_mask / rom_sz change only while a cartridge downloads (cartridge.sv 201-234). md_reset (ext_reset of
# md_board) is high from loading_s until reset_delay_count reaches 3, i.e. >= 2 full ram_clear_addr wraps
# (>= 610 us) after loading_s falls, while the loader drains in <= ~4 us, so md_board issues no cart cycle (the
# only clk_md use) anywhere near a change.
set xf_rm [xf_col rm [get_registers {*|cartridge:cartridge|rom_mask* *|cartridge:cartridge|rom_sz*}]]
set_false_path -from $xf_rm -to [get_clocks $xf_md]

# SP - stream pointer. ONLY with the SP-X RTL (cartridge.sv generate block stream_x); without it this path is a
# real race and must stay timed. On shared edges rom_addr and stream_x held take held, never the live
# stream_addr (stream_x shared_next is a clk_md function of ph -> ph_f, taken on the falling clk_md edge with
# 4.66 ns of setup and hold, which stays timed).
if {[get_collection_size [get_registers -nowarn {*|cartridge:cartridge|stream_x*held*}]] > 0} {
  set_false_path -hold -from [xf_col sp_src [get_registers {*|paprium_cart:paprium|stream_ptr*}]] \
                       -to   [get_registers {*|cartridge:cartridge|rom_addr* *|cartridge:cartridge|stream_x*held*}]
}

# C1 - NOT CHOSEN, left here for the record. First sample of the 68000 write strobe (ramdp_io cpu_we_st[0],
# paprium_snoop we_st[0]). The filter (== 3'b011) reads stage 0 unmasked only while the strobe is mid-assertion,
# so a late or metastable first sample is functionally safe: it moves the mailbox write, and mbx_irq, by one
# clk_sys (18.6 ns). That is exactly the kind of change in when the MCU sees the game that B Jam ruled out, so
# both checks stay timed and a seed that fails them (buddy s3: -0.320 setup) is rejected, not excepted.
# set_false_path -from [get_clocks $xf_md] \
#                -to [xf_col c1 [get_registers {*|ramdp_io:ramdp_inst|cpu_we_st[0]* *|paprium_snoop:*|we_st[0]*}]]

# C2a - ramdp_io port-B write data and write enable (68000 -> mailbox). Written only on the clk_sys edge after
# the filter has seen the strobe twice, when VD / LWR / UWR / VA have been steady for >= 2 clk_sys and stay so
# until the strobe ends (fx68k: dob loads at T3 of the bus-cycle micro-op, dataOe at S2, UDS/LDS after; md_board
# VD holds when nobody drives). On every other edge the registered write enable is 0. Hold only; setup timed.
# Port-B ADDRESS registers are left alone: 68000 mailbox reads use them on every edge.
# NOTE: the M10K register name patterns are UNVERIFIED (no STA run here); the guard reports an empty match.
set_false_path -hold -from [get_clocks $xf_md] \
               -to [xf_col c2a [get_keepers {*|ramdp_io:ramdp_inst|ram_dp8:*|*portb_datain_reg* *|ramdp_io:ramdp_inst|ram_dp8:*|*PORT_B_DATA_IN* *|ramdp_io:ramdp_inst|ram_dp8:*|*portb_we_reg*}]]

# C2b - paprium_snoop FIFO entries (address, data, byte lanes, PRG counter), taken on fire, the same filtered
# edge as C2a: one extra clk_sys of setup, hold kept at the shared edge.
set xf_c2b [xf_col c2b [get_registers {*|paprium_snoop:*|q_a* *|paprium_snoop:*|q_d* *|paprium_snoop:*|q_b* *|paprium_snoop:*|stat_prg*}]]
set_multicycle_path -end -setup -from [get_clocks $xf_md] -to $xf_c2b 2
set_multicycle_path -end -hold  -from [get_clocks $xf_md] -to $xf_c2b 1
# pocket-end
