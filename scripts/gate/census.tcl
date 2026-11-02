# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
# census.tcl (the fit gate; the firmware's docs/STAGE1_PLAN.md sections 4.9 and 6): the vram1 census and the clk_md
# class census of one database, read only.
#
#   cd <COPY of a fitted tree>/projects
#   quartus_sta -t <repo>/scripts/gate/census.tcl <out.txt> [<limit_ns> [post_map]]
#
# Adapted from the v1census.tcl of our earlier VRAM timing trial (md5 570c07d5; the shipped 0.2.6 seed 2 reference
# base_census.txt was made with it). Sections A-E are that script's, unchanged; K is new. Per operating condition:
#  A) every vram1 endpoint (register or M10K port register) with setup slack < limit, worst path per endpoint, with the
#     chain of combinational cells (so the VDP pin it rides on is visible); census_gate.py sorts them into the trial's
#     classes A-D (the trigger for vram_alt.v's shadow pins, its F4: class C or D below 0);
#  B) every endpoint outside vram1 reached FROM vram1 with setup slack < limit;
#  C) for each vram1 endpoint < limit, every distinct startpoint < limit (up to 40 per endpoint);
#  D) a census of ALL negative clk_md (general[1]) setup endpoints, grouped by destination and source block;
#  E) worst hold to / from vram1;
#  K) the freeze-capable classes of STAGE1_PLAN.md section 6 and the Z80 enable class: per class the sizes of its from /
#  to
#     collections, its worst setup path into clk_md (even when positive) and its number of negative endpoints.
#     census_gate.py compares K with the same lines of the shipped 0.2.6 seed 2 (scripts/gate/ref).
# post_map: create_timing_netlist -post_map (collections and structure only; slacks are estimates).
set out [lindex $quartus(args) 0]
set lim [expr {[llength $quartus(args)] > 1 ? [lindex $quartus(args) 1] : 0.3}]
set postmap [expr {[llength $quartus(args)] > 2 && [lindex $quartus(args) 2] eq "post_map"}]
project_open megadrive_pocket -revision megadrive_pocket
if {$postmap} { create_timing_netlist -post_map } else { create_timing_netlist }
read_sdc
update_timing_netlist
set fh [open $out w]
set cm [get_clocks {ic|mp1|altera_pll_i|general[1].gpll~PLL_OUTPUT_COUNTER|divclk}]
set V {*|md_board:md_board|vram*:vram1}
set v1all [get_keepers -nowarn [list "$V|*"]]
set v1regs [get_registers -nowarn [list "$V|*"]]
puts $fh "vram1 keepers [get_collection_size $v1all] registers [get_collection_size $v1regs]"
proc nm {n} {
  set s [get_node_info -name $n]
  regsub -all {core_top:ic\|md_board:md_board\|} $s {} s
  regsub -all {fc1004:ym\|ym7101:vdp\|} $s {vdp|} s
  regsub -all {altsyncram:ram\|altsyncram_[a-z0-9]+:auto_generated\|} $s {} s
  regsub -all {z80cpu:z80\|} $s {z80|} s
  return $s
}
proc chain {t} {
  set r {}
  foreach_in_collection p [get_path_info $t -arrival_points] {
    set n [get_point_info $p -node]
    if {$n eq ""} { continue }
    set s [nm $n]
    if {[string match "*clock*" [get_point_info $p -type]]} { continue }
    lappend r $s
  }
  set o {}
  set last ""
  foreach s $r {
    regsub {\|(combout|q|dataa|datab|datac|datad|datae|dataf|d|clk|portbaddr|portaaddr|i|o)\[?[0-9]*\]?$} $s {} b
    if {$b ne $last} { lappend o $b; set last $b }
  }
  return [join $o " > "]
}
proc strip {e} { regsub {^[^:]*:} $e {} e; regsub {\[.*$} $e {} e; regsub {~.*$} $e {} e; return $e }
proc grp2 {s} {
  set p [split $s "|"]
  set b [strip [lindex $p 0]]
  if {[llength $p] > 1} { return "$b|[strip [lindex $p 1]]" }
  return $b
}
proc grp1 {s} { return [strip [lindex [split $s "|"] 0]] }
proc pinfo {t} {
  return "[format %+.3f [get_path_info $t -slack]] | [nm [get_path_info $t -from]] -> [nm [get_path_info $t -to]] | lv [get_path_info $t -num_logic_levels] | dd [format %.3f [get_path_info $t -data_delay]] | skew [format %+.3f [get_path_info $t -clock_skew]]"
}

# K: class = name, from patterns ({} = any), to patterns ({} = any), kind (freeze = the envelope, enable = must be >= 0)
# z80_enable's sources: zclk_q (the Z80 latch enable's look-ahead register) and, since the third fit round, the terms of
# its next value that the Z80's instruction- register look-ahead reads (prescaler dff11 / dff16 / dff17, the test
# register sl_test1).
set CLASSES {
  fx68k_ccr      {}                                                                   {*|fx68k:cpu|excUnit:excUnit|fx68kAlu:alu|pswCcr*} freeze
  vd_bus         {}                                                                   {*|md_board:md_board|VD[*]}                        freeze
  va_ras_vd      {*|md_board:md_board|VA[*] *|fx68k:cpu|busControl:busControl|rAS*}  {*|md_board:md_board|VD[*]}                        freeze
  vdp_io_data    {}                                                                   {*|ym7101:vdp|io_data[*]}                          freeze
  vdp_io_address {*|ym7101:vdp|io_address[*]}                                         {}                                                 freeze
  z80_internal   {*|z80cpu:z80|*}                                                     {*|z80cpu:z80|*}                                   freeze
  z80_enable     {*|ym7101:vdp|zclk_q* *|ym7101:vdp|ym7101_dff:prescaler_dff11|* *|ym7101:vdp|ym7101_dff:prescaler_dff16|* *|ym7101:vdp|ym7101_dff:prescaler_dff17|* *|ym7101:vdp|ym_slatch_r:sl_test1|*} {*|z80cpu:z80|*} enable
}
set KC [dict create]
foreach {name fp tp kind} $CLASSES {
  set args [list -to_clock $cm]
  set fs -1
  set ts -1
  if {$fp ne {}} { set f [get_registers -nowarn $fp]; set fs [get_collection_size $f]; lappend args -from $f }
  if {$tp ne {}} { set t [get_registers -nowarn $tp]; set ts [get_collection_size $t]; lappend args -to $t }
  dict set KC $name [list $args $fs $ts $kind]
  puts $fh "K | class $name | kind $kind | from [expr {$fs < 0 ? {any} : $fs}] | to [expr {$ts < 0 ? {any} : $ts}]"
}

foreach_in_collection oc [get_available_operating_conditions] {
  set_operating_conditions $oc
  update_timing_netlist
  set cn [get_operating_conditions_info $oc -display_name]
  puts $fh "==== $cn"
  # A
  set n 0
  foreach_in_collection t [get_timing_paths -setup -to $v1all -npaths 20000 -nworst 1 -less_than_slack $lim] {
    incr n
    puts $fh "A | $cn | [pinfo $t]"
    puts $fh "    chain: [chain $t]"
  }
  puts $fh "A | $cn | endpoints in vram1 with setup slack < $lim : $n"
  # B
  set n 0
  foreach_in_collection t [get_timing_paths -setup -from $v1all -npaths 20000 -nworst 1 -less_than_slack $lim] {
    set d [nm [get_path_info $t -to]]
    if {[string match "*vram*:vram1|*" $d]} { continue }
    incr n
    puts $fh "B | $cn | [pinfo $t]"
    puts $fh "    chain: [chain $t]"
  }
  puts $fh "B | $cn | endpoints outside vram1 fed from vram1 with setup slack < $lim : $n"
  # C
  set pairs [dict create]
  foreach_in_collection t [get_timing_paths -setup -to $v1all -npaths 50000 -nworst 40 -less_than_slack $lim] {
    set f [nm [get_path_info $t -from]]
    set d [nm [get_path_info $t -to]]
    set s [get_path_info $t -slack]
    set k "$f -> $d"
    if {![dict exists $pairs $k] || [dict get $pairs $k] > $s} { dict set pairs $k $s }
  }
  set lst {}
  dict for {k s} $pairs { lappend lst [list $s $k] }
  foreach e [lsort -real -index 0 $lst] { puts $fh "C | $cn | [format %+.3f [lindex $e 0]] | [lindex $e 1]" }
  puts $fh "C | $cn | distinct start->end pairs into vram1 < $lim : [llength $lst]"
  # D
  set grp [dict create]
  set n 0
  foreach_in_collection t [get_timing_paths -setup -to_clock $cm -npaths 50000 -nworst 1 -less_than_slack 0] {
    incr n
    set f [nm [get_path_info $t -from]]
    set d [nm [get_path_info $t -to]]
    set s [get_path_info $t -slack]
    set fb [grp2 $f]
    set db [grp1 $d]
    set k "$fb => $db"
    if {[dict exists $grp $k]} {
      set v [dict get $grp $k]
      dict set grp $k [list [expr {[lindex $v 0] + 1}] [expr {min([lindex $v 1], $s)}] [expr {[lindex $v 2] + $s}] [lindex $v 3]]
    } else {
      dict set grp $k [list 1 $s $s "$f -> $d"]
    }
  }
  set lst {}
  dict for {k v} $grp { lappend lst [list [lindex $v 1] $k [lindex $v 0] [lindex $v 2] [lindex $v 3]] }
  foreach e [lsort -real -index 0 $lst] {
    puts $fh "D | $cn | worst [format %+.3f [lindex $e 0]] | endpoints [lindex $e 2] | tns [format %.3f [lindex $e 3]] | [lindex $e 1] | e.g. [lindex $e 4]"
  }
  puts $fh "D | $cn | negative clk_md setup endpoints: $n"
  # E
  foreach_in_collection t [get_timing_paths -hold -to $v1all -npaths 3 -nworst 1] { puts $fh "E | $cn | hold to vram1 | [pinfo $t]" }
  foreach_in_collection t [get_timing_paths -hold -from $v1all -npaths 3 -nworst 1] { puts $fh "E | $cn | hold from vram1 | [pinfo $t]" }
  # K
  dict for {name v} $KC {
    lassign $v args fs ts kind
    if {$fs == 0 || $ts == 0} { puts $fh "K | $cn | $name | EMPTY"; continue }
    set w ""
    foreach_in_collection t [get_timing_paths -setup -npaths 1 {*}$args] { set w [pinfo $t] }
    set nn 0
    foreach_in_collection t [get_timing_paths -setup -npaths 5000 -nworst 1 -less_than_slack 0 {*}$args] { incr nn }
    if {$w eq ""} { puts $fh "K | $cn | $name | NOPATH" } else { puts $fh "K | $cn | $name | $w | negative endpoints $nn" }
  }
  flush $fh
}
close $fh
delete_timing_netlist
project_close
