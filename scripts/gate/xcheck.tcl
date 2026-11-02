# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
# xcheck.tcl (the fit gate; the firmware's docs/STAGE1_PLAN.md sections 4.9 and 6): the crossing re-check of one
# database, read only.
#
#   cd <COPY of a fitted tree>/projects
#   quartus_sta -t <repo>/scripts/gate/xcheck.tcl <out.txt> [s1|026] [post_map]
#
# Writes, for gate.py:
#   - "collection <tag> : <n>" for every collection the SDC's exceptions use (profile s1 = the SDC of the new core,
#     the first step of the 0.3.0 work: the xfix crossings P2 / P2r / P0 / RM / SP / C2a / C2b, the new core's C2c / MV
#     / HOLD / VS, Scum!, the FX68K multicycle, the audio IIR multicycle, option D, the dot-clock h32_sync, and from the
#     synth step (test build 4a, the first 0.3.0 hardware test build of the sound cache) the first-boot bar's bar_sync /
#     bar_w_sync, (test build 5, the synth build) the hold picture's hold_vid_sync; profile 026 = 0.2.6's eleven xfix
#     collections), so a pattern that matches nothing is seen by the gate, not only as a critical warning in the STA
#     log;
#   - per corner the worst clk_sys <-> clk_md setup and hold paths, the worst hold of the design, the worst setup into
#     clk_sys and the number of failing hold paths (cap 500).
# post_map: run on a mapped (not fitted) database: create_timing_netlist -post_map. The slacks are then estimates; the
# collections are what the post-map run is for (they prove the new core's patterns match the netlist before any fit).
# Read only on the database: run it on a COPY (quartus_sta writes its own files into the project).
set out     [lindex $quartus(args) 0]
set profile s1
if {[llength $quartus(args)] > 1} { set profile [lindex $quartus(args) 1] }   ;# a string: expr would read 026 as octal
set postmap [expr {[llength $quartus(args)] > 2 && [lindex $quartus(args) 2] eq "post_map"}]
project_open megadrive_pocket -revision megadrive_pocket
if {$postmap} { create_timing_netlist -post_map } else { create_timing_netlist }
read_sdc
update_timing_netlist
set fh [open $out w]
puts $fh "xcheck profile $profile [expr {$postmap ? {post_map} : {fitted}}]"
set cs [get_clocks {ic|mp1|altera_pll_i|general[0].gpll~PLL_OUTPUT_COUNTER|divclk}]
set cm [get_clocks {ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk}]

# tag pattern kind profiles: kind reg = get_registers, keep = get_keepers, port = get_ports
set COLS {
  p2        {*|paprium_mcu_mem:mem_inst|mem_addr* *|paprium_mcu_mem:mem_inst|mem_din* *|paprium_mcu_mem:mem_inst|mem_wrl* *|paprium_mcu_mem:mem_inst|mem_wrh*} reg  {s1 026}
  p2r       {*|paprium_mcu_mem:mem_inst|mem_req*}                                     reg  {s1 026}
  p2r_dst   {*|cartridge:cartridge|sdram:sdram|ack2*}                                 reg  {s1}
  sdram     {*|cartridge:cartridge|sdram:sdram|*}                                     reg  {s1 026}
  p0        {*|cartridge:cartridge|cart_wr_addr* *|data_loader:*rom_data_loader|write_data* *|data_loader:cache_data_loader|*write_data_q*} reg {s1 026}
  rm        {*|cartridge:cartridge|rom_mask* *|cartridge:cartridge|rom_sz*}           reg  {s1 026}
  sp_ptr    {*|paprium_cart:paprium|stream_ptr*}                                      reg  {s1 026}
  sp_held   {*|cartridge:cartridge|stream_x*held*}                                    reg  {s1 026}
  sp_ph     {*|cartridge:cartridge|stream_x*ph*}                                      reg  {026}
  c1        {*|ramdp_io:ramdp_inst|cpu_we_st[0]* *|paprium_snoop:*|we_st[0]*}         reg  {026}
  c2a       {*|ramdp_io:ramdp_inst|ram_dp8:*|*portb_datain_reg* *|ramdp_io:ramdp_inst|ram_dp8:*|*PORT_B_DATA_IN* *|ramdp_io:ramdp_inst|ram_dp8:*|*portb_we_reg*} keep {s1 026}
  c2b       {*|paprium_snoop:*|q_a* *|paprium_snoop:*|q_d* *|paprium_snoop:*|q_b* *|paprium_snoop:*|stat_prg*} reg {s1 026}
  c2c       {*|paprium_regfile:regfile_inst|r_ea[*] *|paprium_regfile:regfile_inst|r_ec[*] *|paprium_regfile:regfile_inst|guard} reg {s1}
  mv        {*|cartridge:cartridge|paprium_mini_sync[0]*}                             reg  {s1}
  hold      {*|synch_3:paprium_hold_sync|stage_1[*]}                                  reg  {s1}
  vs        {*|paprium_vs_tap:*|synch_3:vs_sync|stage_1[*]}                           reg  {s1}
  scum_src  {*|cartridge:cartridge|rom_addr[*]}                                       reg  {s1}
  scum_dst  {*|cartridge:cartridge|paprium_scum:*|hit *|cartridge:cartridge|paprium_scum:*|data[*]} reg {s1}
  fx68k_ir  {*|fx68k:cpu|Ir[*]}                                                       reg  {s1}
  fx68k_uadr {*|fx68k:cpu|nanoAddr[*] *|fx68k:cpu|microAddr[*]}                       reg  {s1}
  audio_iir {*|audio_cond:*|iir_filter:*|iir_filter_tap:*|intreg[*] *|audio_cond:*|iir_filter:*|out_l[*] *|audio_cond:*|iir_filter:*|out_r[*] *|audio_cond:*|iir_filter:*|out_m[*] *|audio_cond:*|iir_filter:*|ch} reg {s1}
  audio_iir_any {*|audio_cond:*|iir_filter:*|*}                                      reg  {s1}
  od_vals   {*|paprium_xlink:*|d_word[*] *|paprium_xlink:*|d_busy[*] *|paprium_xlink:*|pend[*] *|paprium_xlink:*|od_hold[*] *|paprium_xlink:*|od_en} reg {s1}
  od_caps   {*|paprium_mcd_link:*}                                                    reg  {s1}
  vid_h32s  {*|synch_3:h32_sync|stage_1[*]}                                           reg  {s1}
  vid_bar   {*|synch_3:bar_sync|stage_1[*]}                                           reg  {s1}
  bar_w     {*|synch_3:bar_w_sync|stage_1[*]}                                         reg  {s1}
  vid_hold  {*|synch_3:hold_vid_sync|stage_1[*]}                                      reg  {s1}
  sdram_pins {dram_a[*] dram_ba[*] dram_dqm[*] dram_ras_n dram_cas_n dram_we_n dram_dq[*] dram_clk} port {s1}
}
foreach {tag pat kind profs} $COLS {
  if {[lsearch -exact $profs $profile] < 0} { continue }
  switch $kind {
    reg  { set c [get_registers -nowarn $pat] }
    keep { set c [get_keepers -nowarn $pat] }
    port { set c [get_ports -nowarn $pat] }
  }
  puts $fh "collection $tag : [get_collection_size $c]"
}
proc pth {fh cn lbl paths} {
  foreach_in_collection t $paths {
    puts $fh "$cn | $lbl | [format %.3f [get_path_info $t -slack]] | [get_node_info -name [get_path_info $t -from]] -> [get_node_info -name [get_path_info $t -to]]"
  }
}
foreach_in_collection oc [get_available_operating_conditions] {
  set_operating_conditions $oc
  update_timing_netlist
  set cn [get_operating_conditions_info $oc -display_name]
  pth $fh $cn "hold sys->md"     [get_timing_paths -hold  -npaths 12 -from_clock $cs -to_clock $cm]
  pth $fh $cn "setup sys->md"    [get_timing_paths -setup -npaths 12 -from_clock $cs -to_clock $cm]
  pth $fh $cn "hold md->sys"     [get_timing_paths -hold  -npaths 12 -from_clock $cm -to_clock $cs]
  pth $fh $cn "setup md->sys"    [get_timing_paths -setup -npaths 12 -from_clock $cm -to_clock $cs]
  pth $fh $cn "hold any"         [get_timing_paths -hold  -npaths 10]
  pth $fh $cn "setup to clk_sys" [get_timing_paths -setup -npaths 5 -to_clock $cs]
  set nh 0
  foreach_in_collection t [get_timing_paths -hold -npaths 500 -less_than_slack 0.0] { incr nh }
  puts $fh "$cn | counts | failing hold paths (cap 500): $nh"
}
close $fh
delete_timing_netlist
project_close
