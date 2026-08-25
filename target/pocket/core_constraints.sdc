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
  cram0_dq[*] \
  port_tran_sck port_tran_sd port_tran_si \
}]

set_false_path -to [get_ports { \
  bridge_1wire bridge_spimiso bridge_spimosi \
  cram0_a[*] cram0_adv_n cram0_ce0_n cram0_ce1_n cram0_clk cram0_cre \
  cram0_dq[*] cram0_lb_n cram0_oe_n cram0_ub_n cram0_we_n \
  port_tran_sck port_tran_sck_dir port_tran_sd port_tran_sd_dir port_tran_so \
  scal_auddac scal_audlrck scal_audmclk scal_clk scal_de scal_hs scal_skip \
  scal_vid[*] scal_vs \
}]
