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
# Changes: Copyright (C) 2026 Marsupial Solutions LLC (GPL-3.0-or-later)
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

# pocket (0.3.0): the general[1] -> dot clock crossing. Every dot clock edge is also a
# general[1] edge (all off one VCO, phase 0), and cofi's 28 output registers (rgb, HS, VS,
# HBlank, VBlank) load on a general[1] edge once per dot. Where that load sits against the
# next dot edge is set by the boot: the VDP's dot phase is re-rolled at every VDP reset and
# the PLL counters are not, so the value can change ONE general[1] cycle before the dot edge
# that must take it. A whole dot of setup (the old -setup 2 / -hold 1) is therefore not
# real: it let routes run long and padded, and on some placements the same dot event
# reached two registers on different dot edges.
#
# The fix is in two parts. scanline_filler takes the 28 signals once, in 28 plain registers
# (preserve), so they are the only general[1] -> dot clock endpoints besides the h32_sync
# synchroniser below. And the window here is the same edge: setup is checked against the
# general[1] edge that launched the value. clk_vid is a fabric mux re-entering the global
# network, so it reaches its registers 1.5-4 ns after the general[1] edge (vidsta, seed 2);
# each of the 28 routes only has to be shorter than that lateness, and no hold padding is
# needed (the default hold becomes one general[1] cycle earlier). If the dot clock ever
# stops being late (a dedicated clock select, a PLL output used directly), this relationship
# no longer holds: delete these two lines and use the default single cycle instead.
#
# RULE: any future general[1] -> dot clock path (an OSD, a status overlay, anything) must be
# a synchronised crossing with its own false path, like h32_sync. Never logic straight off
# a clk_md signal into a clk_vid register: this window times only plain register-to-register
# routes, and a path with LUTs in it fails it or, worse, splits a dot event
set_multicycle_path -start -setup \
 -from {ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk} \
 -to   {ic|mp1|altera_pll_i|general[2].gpll~PLL_OUTPUT_COUNTER|divclk} 0
set_multicycle_path -start -setup \
 -from {ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk} \
 -to   {ic|mp1|altera_pll_i|general[4].gpll~PLL_OUTPUT_COUNTER|divclk} 0
# h32_sync is a real three-stage synchroniser of the VDP's RS1 latch, a mode bit that moves
# only on a register write, so its first stage is not a timed path
set vid_h32s [get_registers -nowarn {*|synch_3:h32_sync|stage_1[*]}]
if {[get_collection_size $vid_h32s] == 0} {
  post_message -type critical_warning "pocket: h32_sync stage_1 false path matched nothing"
} else {
  set_false_path -to $vid_h32s
}
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
# are 7 cycles apart at the closest. Charging 2 cycles is well inside that.
#
# pocket (0.3.0): scoped to audio_cond's filter. The pattern used to match every
# iir_filter, including the one in audio_filters.sv, which runs on audio_mclk
# (12.288 MHz, 81 ns a cycle): it needs no exception, and its ce is not the
# CEGen pace this argument rests on.
#
# inp and inp_m are deliberately not here. They latch the core's raw output,
# which does move every cycle, so their paths really are one cycle long.
set audio_iir_regs [get_registers -nowarn { \
  *|audio_cond:*|iir_filter:*|iir_filter_tap:*|intreg[*] \
  *|audio_cond:*|iir_filter:*|out_l[*] \
  *|audio_cond:*|iir_filter:*|out_r[*] \
  *|audio_cond:*|iir_filter:*|out_m[*] \
  *|audio_cond:*|iir_filter:*|ch }]
# pocket (0.3.0, from the new core's fit gate): in the Paprium build the whole filter is removed by synthesis (lpf_mode
# is hard-wired, so its output psg is unused: every register of audio_cond's iir_filter is "stuck at GND" or "lost
# fanout" in the map), and an empty collection then means nothing to except, not a broken pattern. Only when some
# audio_cond iir_filter register survives and the pattern still matches none of them is the guard a critical warning.
set audio_iir_any [get_registers -nowarn {*|audio_cond:*|iir_filter:*|*}]
if {[get_collection_size $audio_iir_regs] == 0 && [get_collection_size $audio_iir_any] == 0} {
  post_message "pocket: audio_cond IIR multicycle: the filter is removed by synthesis in this build, nothing to except"
} elseif {[get_collection_size $audio_iir_regs] == 0} {
  post_message -type critical_warning "pocket: audio_cond IIR multicycle matched nothing"
} else {
  set_multicycle_path -setup -to $audio_iir_regs 2
  set_multicycle_path -hold  -to $audio_iir_regs 1
}
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

# pocket: xram step 1 (the first step of our Pocket SRAM / CRAM work). The Pocket SRAM and cram0 are asynchronous parts
# the core does not clock (CRAM in async mode, CLK held low), so there is no external clock to write
# set_input_delay / set_output_delay against. Each pad crossing gets a delay BUDGET instead, and the
# controllers (PAPRIUM/paprium_xram.sv, paprium_cram.sv) spend whole clocks between launch and
# sample. The budgets are the STA pad delays of our xram probe build (worst of 4 corners, rounded up):
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

# pocket: xram step 2. The option-D values the MCU writes into paprium_xlink (clk_sys) reach
# paprium_mcd_link (clk_md) without a synchroniser of their own: mcd_link copies D_WORD / D_BUSY / PEND
# only on the clock its synchronised ARM toggle moves (>= 3 clk_md clocks after the MCU's ARM write,
# which follows the value writes) or, when that clock holds a $A12001 write, one clock later (a review
# finding of the second step of our 0.2.x CPU MATE work: the ARM is latched until taken), and reads HOLD / the
# option-D enable as settings written long before a post. None of them changes near the edge that captures it, so the
# same-edge hold check between the two clocks is not a real path: two clk_md clocks of setup, hold edge one clock
# earlier.
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
# Since the synth step's logic saving: in the Paprium build that write_data is the sound-cache slot's loader's ROM
# output register (cache_data_loader rom_region write_data_q, loaded only on ROM words, held between them, 24 clk_sys
# apart the same way); the other builds keep core_top's rom_data_loader (inside the rom_ld generate block). Each build
# matches one.
set xf_p0 [xf_col p0 [get_registers {*|cartridge:cartridge|cart_wr_addr* *|data_loader:*rom_data_loader|write_data* *|data_loader:cache_data_loader|*write_data_q*}]]
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

# C1 - not chosen, left here for the record. First sample of the 68000 write strobe (ramdp_io cpu_we_st[0],
# paprium_snoop we_st[0]). The filter (== 3'b011) reads stage 0 unmasked only while the strobe is mid-assertion,
# so a late or metastable first sample is functionally safe: it moves the mailbox write, and mbx_irq, by one
# clk_sys (18.6 ns). That is exactly the kind of change in when the MCU sees the game that B Jam ruled out, so
# both checks stay timed and a seed that fails them (one earlier fit: -0.320 setup) is rejected, not excepted.
# set_false_path -from [get_clocks $xf_md] \
#                -to [xf_col c1 [get_registers {*|ramdp_io:ramdp_inst|cpu_we_st[0]* *|paprium_snoop:*|we_st[0]*}]]

# C2a - ramdp_io port-B write data and write enable (68000 -> mailbox). Written only on the clk_sys edge after
# the filter has seen the strobe twice, when VD / LWR / UWR / VA have been steady for >= 2 clk_sys and stay so
# until the strobe ends (fx68k: dob loads at T3 of the bus-cycle micro-op, dataOe at S2, UDS/LDS after; md_board
# VD holds when nobody drives). On every other edge the registered write enable is 0. Hold only; setup timed.
# Port-B ADDRESS registers are left alone: 68000 mailbox reads use them on every edge.
# NOTE: the M10K register name patterns are not checked (no STA run here); the guard reports an empty match.
set_false_path -hold -from [get_clocks $xf_md] \
               -to [xf_col c2a [get_keepers {*|ramdp_io:ramdp_inst|ram_dp8:*|*portb_datain_reg* *|ramdp_io:ramdp_inst|ram_dp8:*|*PORT_B_DATA_IN* *|ramdp_io:ramdp_inst|ram_dp8:*|*portb_we_reg*}]]

# C2b - paprium_snoop FIFO entries (address, data, byte lanes, PRG counter), taken on fire, the same filtered
# edge as C2a: one extra clk_sys of setup, hold kept at the shared edge.
set xf_c2b [xf_col c2b [get_registers {*|paprium_snoop:*|q_a* *|paprium_snoop:*|q_d* *|paprium_snoop:*|q_b* *|paprium_snoop:*|stat_prg*}]]
set_multicycle_path -end -setup -from [get_clocks $xf_md] -to $xf_c2b 2
set_multicycle_path -end -hold  -from [get_clocks $xf_md] -to $xf_c2b 1
# pocket-end

# pocket: 0.3.0 new core - three more crossings, by the arguments above. Each collection goes through
# xf_col, so a pattern that matches nothing is a critical warning, never a silent no-op.
#
# C2c - the cart register file's flops that take the 68000's write data (paprium_regfile r_ea / r_ec, the stored
# $1FEA / $1FEC, and the busy guard, set from the post's high byte). Their 68000 term is enabled only by cpu_we_ck,
# ramdp_io's filtered strobe: the C2a edge, when VD / LWR / UWR / VA have been steady for >= 2 clk_sys and stay so
# until the strobe ends; on every other edge that term is 0. Hold only; setup stays timed. Their MCU writes are
# clk_sys and are not touched. The 68000 view (cpu_dati, cpu_page), which samples VA on every edge like the RAMDP
# port-B address, and the mailbox latch (0.2.6's paprium_cart mbx_irq, a timed path; fpgio CAUSE.B and STAMP_B since
# the new core) are not in the collection.
set_false_path -hold -from [get_clocks $xf_md]                -to [xf_col c2c [get_registers {*|paprium_regfile:regfile_inst|r_ea[*] *|paprium_regfile:regfile_inst|r_ec[*] *|paprium_regfile:regfile_inst|guard}]]

# MV - the 84 view switch, mini_view (paprium_regfile, clk_sys) into the first flop of its two-flop synchroniser in
# cartridge.sv (paprium_mini_sync[0], clk_md). It rises once per boot (the firmware's 84 handler's $1FEE or $1FE8 write)
# and falls only at reset; the FM XOR and the read launch use the second flop (paprium_mini_md), which stays
# timed. False path into the first flop only.
set_false_path -to [xf_col mv [get_registers {*|cartridge:cartridge|paprium_mini_sync[0]*}]]

# HOLD - the MCU's 68000 hold (fpgio ctrl[0] = CTRL.HOLD, clk_sys) into the first stage of its synch_3 in core_top
# (the new core's reset hold, the firmware's docs/MCU_INTERFACE.md 9: paprium_hold_sync, clk_md). It replaces 0.2.6's
# direct ctrl[0] -> md_board crossing, which seed 5 failed on hold. The hold changes once per boot (released ~2.8 s
# before the first post) and is set again by every reset; the release moves by up to one clk_md. The synchroniser's
# later stages and md_reset_effective stay timed. The instance name must match the new core's core_top edit: on a tree
# without that hold this collection is empty and xf_col reports it.
set_false_path -to [xf_col hold [get_registers {*|synch_3:paprium_hold_sync|stage_1[*]}]]

# Fafrium - the boot stub's GO (mcu_core fw_go_q, clk_sys) into the first stage of its synch_3 in core_top
# (fw_go_sync, clk_md). It rises once per power-on and never falls; the rise pulse is taken from the later stages,
# which stay timed. False path into the first stage only, as HOLD above.
set_false_path -to [xf_col fw_go [get_registers {*|synch_3:fw_go_sync|stage_1[*]}]]

# VS - the VS counter (MCU interface v1.1, FPGAIO slot 16): paprium_vs_tap's vs_tog (clk_md) into the first stage of its
# synch_3 on clk_sys. vs_tog is a level that flips once at the start of every VDP vertical sync (16.7 ms apart, NTSC)
# and holds for the whole frame, so the first stage may sample it on any edge: a late or early capture moves the
# count by one clk_sys, never adds or loses one (the new core's VS bench, random clock phase). The synchroniser's later
# stages and fpgio's counter stay timed. The instance names must match core_top / paprium_vs_tap.sv.
set_false_path -to [xf_col vs [get_registers {*|paprium_vs_tap:*|synch_3:vs_sync|stage_1[*]}]]
# pocket-end

# pocket: 0.3.0 synth step (test builds 4a / 4b, the 0.3.0 hardware test builds of the sound cache; MCU interface v1.3
# sections 3.9 / 21.2) - the first-boot bar's two synchronisers, by
# the dot-clock RULE above (a synchronised crossing with its own false path).
# BAR - XLINK BAR {EN, PX} (paprium_xlink, clk_sys = general[0]) into the first stage of bar_sync on the dot clock
# (general[2] / general[4]). The word is quasi-static: the firmware writes PX once per unpack chunk and EN at the
# start and the end of a first-boot unpack, so a first stage that catches a change on any edge only moves the bar
# by one dot clock, once. bar_sync's later stages and paprium_bar stay timed on the dot clock.
# BARW - paprium_bar's W (the dot clock) into the first stage of bar_w_sync on clk_sys, read back in XLINK BAR[26:16].
# W changes only at an H32 / H40 switch. The later stages stay timed on clk_sys.
# Only the Paprium variant drives the bar (XLINK lives there); elsewhere both synchronisers are constants and
# synthesis removes them, so the guard runs only where paprium_cart exists (as the Scum! block below does).
# pocket: synth step (test build 5, the 0.3.0 hardware test build of the synth; a project decision) - HOLDV: core_top's
# md_reset_effective (clk_md = general[1], the console held in reset) into the first stage of hold_vid_sync on the dot
# clock, where paprium_holdvid takes it to put black frames with the bar on the video outputs for the whole hold. The
# hold changes a few times a boot and stays for many frames; a first stage that catches a change on either edge only
# moves the handover by one dot clock, and the handover itself waits for a frame boundary (paprium_holdvid). Its later
# stages and paprium_holdvid stay timed on the dot clock. The Paprium variant only (core_top ties the input to 0
# elsewhere and synthesis removes it), so it sits in this block. The W read-back mux in front of bar_w_sync
# (paprium_holdvid's width while it drives the picture) is dot-clock logic into the BARW first stage, which stays a
# false path.
if {[get_collection_size [get_registers -nowarn {*|paprium_cart:paprium|*}]] > 0} {
  set_false_path -to [xf_col bar  [get_registers -nowarn {*|synch_3:bar_sync|stage_1[*]}]]
  set_false_path -to [xf_col barw [get_registers -nowarn {*|synch_3:bar_w_sync|stage_1[*]}]]
  set_false_path -to [xf_col holdv [get_registers -nowarn {*|synch_3:hold_vid_sync|stage_1[*]}]]
}
# pocket-end

# pocket (0.3.0): the Scum! lookup (PAPRIUM/paprium_scum.sv), the third inherited clk_md class on 0.2.6 seed 2
# (rom_addr -> scum data, -0.512 ns at slow 85C). cartridge.sv latches rom_addr on the clk_md edge that toggles rom_req,
# and no new read strobe can re-latch it before that read is served: a second toggle while rom_req != rom_ack would
# break the request handshake by itself. sdram.sv acks no sooner than 7 edges after the toggle (the IDLE grant, START ..
# READY), and cart_data takes scum hit / data only on the serve edge after the ack, so the lookup has at least 8 edges.
# hit and data are re-registered from rom_addr on every clock, so a value caught mid-change on an early edge is
# overwritten long before the serve. Two cycles of setup is therefore exact by protocol (the new core's Scum! bench: the
# serve never comes sooner than 8 edges after rom_addr moves). If the ROM read path is ever made to serve within 2
# clocks of the request, delete this block. Only rom_addr -> hit / data: every other input of the lookup stays timed.
set scum_src [get_registers -nowarn {*|cartridge:cartridge|rom_addr[*]}]
set scum_dst [get_registers -nowarn {*|cartridge:cartridge|paprium_scum:*|hit *|cartridge:cartridge|paprium_scum:*|data[*]}]
if {[get_collection_size $scum_dst] == 0} {
  if {[get_collection_size [get_registers -nowarn {*|paprium_cart:paprium|*}]] > 0} {
    post_message -type critical_warning "pocket: Scum! multicycle matched no hit / data register"
  }
} elseif {[get_collection_size $scum_src] == 0} {
  post_message -type critical_warning "pocket: Scum! multicycle matched no rom_addr register"
} else {
  set_multicycle_path -setup -from $scum_src -to $scum_dst 2
  set_multicycle_path -hold  -from $scum_src -to $scum_dst 1
}
# pocket-end

# pocket (0.3.0): SDRAM pad budgets, in the form of the xram step-1 block above. sdram.sv's address / DQM register
# (SDRAM_A, which also drives DQMH/DQML) has a synchronous clear and a synchronous load, which an I/O register cannot
# take, so on 0.2.x 10 address bits and both DQM pins stayed in the fabric (fit warning 176279) and reached the pins
# 2.5-4.6 ns after the packed ones, up to 0.58 ns after the SDRAM clock edge at slow 85C (seeds
# 1/2/3/5). The qsf now builds that register's clear and load in LUTs (ALLOW_SYNCH_CTRL_USAGE OFF on the sdram
# instance), so every pin register can pack. These budgets put the pads on the gate and fail when a register falls
# out of its IOE. Figures from report_datasheet on four 0.2.x placements (our STA review), worst of the four corners,
# relative to clk_74a as the datasheet gives them:
#   outputs, packed: clock-to-out <= 7.9 ns (unpacked 9.7-12.4); minimum >= 1.9 ns. dram_clk rises about 11.25 ns
#   after the launching edge at slow 85C (4.66 + its own 6.6), so 9.0 leaves the SDRAM >= 2.2 ns of setup;
#   dram_dq in (FAST_INPUT_REGISTER): setup at the pin <= 1.03 ns, hold at the pin <= 1.48 ns.
# These are pad budgets, not the SDRAM's own window: the part's tIS / tIH / tAC / tOH are not
# known here; a generated clock on dram_clk with set_output_delay / set_input_delay replaces this block once the
# datasheet is in hand. dram_cke is a constant and times nothing.
set sdram_out [get_ports {dram_a[*] dram_ba[*] dram_dqm[*] dram_ras_n dram_cas_n dram_we_n dram_dq[*] dram_clk}]
set_max_delay -to   $sdram_out 9.0
set_min_delay -to   $sdram_out 1.0
set_max_delay -from [get_ports {dram_dq[*]}] 2.0
set_min_delay -from [get_ports {dram_dq[*]}] -2.0
# pocket-end
