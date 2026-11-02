# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
# vidsta.tcl (the fit gate; the firmware's docs/STAGE1_PLAN.md section 6, test T24): the clk_md -> dot clock crossing
# of one database, read only.
#
#   cd <COPY of a fitted tree>/projects
#   quartus_sta -t <repo>/scripts/gate/vidsta.tcl <out.tsv> [post_map]
#
# Adapted from the vidsta.tcl of our earlier video timing audit (the audit that found the 0.2.6 multicycle defect).
# The new core takes the 28 cofi
# signals once in scanline_filler's 28 plain registers, and the SDC times them in a same-edge window (-start -setup 0
# from general[1] to general[2] / general[4]) with a false path into h32_sync's first stage. This writes, per corner,
# for setup and hold, one row per unique (from, to) pair of every clock into each dot clock (general[2] H40,
# general[4] H32), with its slack, data delay, clock skew, launch / latch, logic levels and clock relationship, under
# the project's own SDC. vidsta_gate.py judges it: exactly 28 reg->reg pairs from clk_md per dot clock, into the 28
# filler registers, 0 logic levels, the same-edge relationship, setup and hold >= 0 in all four corners.
# post_map: create_timing_netlist -post_map (pairs and levels only; slacks are estimates).
set out [lindex $quartus(args) 0]
set postmap [expr {[llength $quartus(args)] > 1 && [lindex $quartus(args) 1] eq "post_map"}]
set CLK(md)  {ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk}
set CLK(h40) {ic|mp1|altera_pll_i|general[2].gpll~PLL_OUTPUT_COUNTER|divclk}
set CLK(h32) {ic|mp1|altera_pll_i|general[4].gpll~PLL_OUTPUT_COUNTER|divclk}
proc pi {p key} { if {[catch {set v [get_path_info $p $key]} e]} { return "NA" }; return $v }
proc nname {id} { if {[catch {set v [get_node_info -name $id]} e]} { return "NA" }; return $v }
proc cname {id} { if {[catch {set v [get_clock_info -name $id]} e]} { return "NA" }; return $v }
project_open megadrive_pocket -revision megadrive_pocket
if {$postmap} { create_timing_netlist -post_map } else { create_timing_netlist }
read_sdc
update_timing_netlist
set fh [open $out w]
puts $fh [join {corner kind dot from_clock to_clock from to slack data_delay clock_skew launch latch levels relationship} "\t"]
set allclk [get_clocks *]
foreach_in_collection oc [get_available_operating_conditions] {
  set_operating_conditions $oc
  update_timing_netlist
  set cn [get_operating_conditions_info $oc -display_name]
  foreach dot {h40 h32} {
    foreach kind {setup hold} {
      foreach_in_collection fc $allclk {
        set fname [cname $fc]
        if {$fname eq $CLK($dot)} { continue }
        if {[catch {set paths [get_timing_paths -$kind -npaths 200000 -pairs_only -from_clock $fc -to_clock [get_clocks $CLK($dot)]]} e]} {
          puts $fh [join [list $cn $kind $dot $fname $CLK($dot) ERROR $e NA NA NA NA NA NA NA] "\t"]
          continue
        }
        foreach_in_collection p $paths {
          puts $fh [join [list $cn $kind $dot [cname [get_path_info $p -from_clock]] [cname [get_path_info $p -to_clock]] \
            [nname [get_path_info $p -from]] [nname [get_path_info $p -to]] [pi $p -slack] [pi $p -data_delay] \
            [pi $p -clock_skew] [pi $p -launch_time] [pi $p -latch_time] [pi $p -num_logic_levels] \
            [pi $p -clock_relationship]] "\t"]
        }
      }
    }
  }
  flush $fh
}
close $fh
delete_timing_netlist
project_close
