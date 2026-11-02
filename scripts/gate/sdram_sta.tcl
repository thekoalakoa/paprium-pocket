# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
# sdram_sta.tcl (the fit gate; the new core's SDRAM I/O change, the firmware's docs/STAGE1_PLAN.md section 6): the
# SDRAM pins of one fitted database, read only.
#
#   cd <COPY of a fitted tree>/projects
#   quartus_sta -t <repo>/scripts/gate/sdram_sta.tcl <out.txt> [<core sdc without the pad-budget block>]
#
# Part 1 (the project's own SDC, i.e. the SDRAM pad budgets: set_max_delay 9.0 / set_min_delay 1.0 to every dram_*
# output,
#   2.0 / -2.0 from dram_dq): per corner, the worst setup and hold path to every dram_* output and from every dram_dq
#   input ("pad <dir> <setup|hold> <port>"), and, as Part 1 of our earlier bootpaths.tcl (from our comparison of the
#   0.2.6 byte-fix builds, md5 24cbc81e), the longest and shortest register -> pad delay of every dram_* output
#   ("sdpin" lines, the B1 metric of that comparison).
# Part 2 (only when the second argument is given): the session-only SDRAM output constraint of bootpaths.tcl Part 2 (a
#   generated clock on dram_clk, the inverted clk_md through the altddio_out; tIS 1.5 / tIH 0.8 ns) on the project's
#   constraints with the pad-budget block left out (the given file: core_constraints.sdc minus that block; with the
#   block in, its max / min delays would override the generated-clock relationship): "P2 setup|hold <port>" lines.
# Nothing is written to any SDC. sdram_gate.py judges the output.
set out [lindex $quartus(args) 0]
set nov5 ""
if {[llength $quartus(args)] > 1} { set nov5 [lindex $quartus(args) 1] }
project_open megadrive_pocket -revision megadrive_pocket
create_timing_netlist
read_sdc
update_timing_netlist
set fh [open $out w]
proc nm {id} { if {[catch {set v [get_node_info -name $id]}]} { return NA }; return $v }
proc pinfo {t} {
  set s [format %.3f [get_path_info $t -slack]]
  set x ""
  catch { set x " (arr [format %.3f [get_path_info $t -arrival_time]], req [format %.3f [get_path_info $t -required_time]], dd [format %.3f [get_path_info $t -data_delay]])" }
  return "$s | [nm [get_path_info $t -from]] -> [nm [get_path_info $t -to]]$x"
}
set outs {}
foreach p [list dram_ba[0] dram_ba[1] dram_ras_n dram_cas_n dram_we_n dram_clk dram_dqm[0] dram_dqm[1]] { lappend outs $p }
for {set i 0} {$i < 13} {incr i} { lappend outs "dram_a\[$i\]" }
for {set i 0} {$i < 16} {incr i} { lappend outs "dram_dq\[$i\]" }
set ins {}
for {set i 0} {$i < 16} {incr i} { lappend ins "dram_dq\[$i\]" }
puts $fh "ports out [llength $outs] in [llength $ins]"
foreach_in_collection oc [get_available_operating_conditions] {
  set_operating_conditions $oc
  update_timing_netlist
  set cn [get_operating_conditions_info $oc -display_name]
  foreach p $outs {
    set port [get_ports -nowarn $p]
    if {[get_collection_size $port] == 0} { puts $fh "$cn | pad out setup $p | NOPORT"; continue }
    foreach kind {setup hold} {
      set k 0
      if {![catch {set ps [get_timing_paths -$kind -npaths 1 -to $port]} e]} {
        foreach_in_collection t $ps { puts $fh "$cn | pad out $kind $p | [pinfo $t]"; incr k }
      }
      if {$k == 0} { puts $fh "$cn | pad out $kind $p | NONE" }
    }
    # bootpaths Part 1: register -> pad delay, no clock latency
    set mx NA; set mn NA; set src NA
    if {![catch {set r [report_path -to $port -npaths 1]} e]} { set mx [lindex $r 1] }
    if {![catch {set r [report_path -min_path -to $port -npaths 1]} e]} { set mn [lindex $r 1] }
    catch { foreach_in_collection q [get_path -to $port -npaths 1] { set src [nm [get_path_info $q -from]] } }
    puts $fh "$cn | sdpin $p | max $mx | min $mn | from $src"
  }
  foreach p $ins {
    set port [get_ports -nowarn $p]
    foreach kind {setup hold} {
      set k 0
      if {![catch {set ps [get_timing_paths -$kind -npaths 1 -from $port]} e]} {
        foreach_in_collection t $ps { puts $fh "$cn | pad in $kind $p | [pinfo $t]"; incr k }
      }
      if {$k == 0} { puts $fh "$cn | pad in $kind $p | NONE" }
    }
  }
  flush $fh
}
if {$nov5 ne ""} {
  reset_design
  if {[catch {read_sdc -hdl} e]} { puts $fh "P2 read_sdc -hdl: $e" }
  read_sdc ../platform/pocket/apf_constraints.sdc
  read_sdc $nov5
  set ok 1
  if {[catch {
    create_generated_clock -name sdclk_pin -source [get_pins -compatibility_mode {*mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk}] -invert [get_ports dram_clk]
  } e]} { puts $fh "P2 create_generated_clock failed: $e"; set ok 0 }
  if {$ok} {
    set pouts [get_ports {dram_a[*] dram_ba[*] dram_ras_n dram_cas_n dram_we_n dram_dqm[*] dram_dq[*]}]
    set_output_delay -clock sdclk_pin -max 1.5 $pouts
    set_output_delay -clock sdclk_pin -min -0.8 $pouts
    update_timing_netlist
    puts $fh "P2 sdclk_pin clocks: [get_collection_size [get_clocks sdclk_pin]]"
    foreach_in_collection oc [get_available_operating_conditions] {
      set_operating_conditions $oc
      update_timing_netlist
      set cn [get_operating_conditions_info $oc -display_name]
      foreach p $outs {
        if {$p eq "dram_clk"} continue
        set port [get_ports -nowarn $p]
        foreach kind {setup hold} {
          if {[catch {set ps [get_timing_paths -$kind -npaths 1 -to $port]} e]} { puts $fh "$cn | P2 $kind $p | ERROR $e"; continue }
          set k 0
          foreach_in_collection t $ps { puts $fh "$cn | P2 $kind $p | [pinfo $t]"; incr k }
          if {$k == 0} { puts $fh "$cn | P2 $kind $p | NONE" }
        }
      }
      flush $fh
    }
  }
}
close $fh
delete_timing_netlist
project_close
