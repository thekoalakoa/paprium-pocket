# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
# queries.tcl (the fit gate; the firmware's docs/STAGE1_PLAN.md section 6 and docs/MCU_INTERFACE.md sections 9, 12 I8
# and 20): the new core's STA query list of one database, read only. The new core = the first step of the 0.3.0 work.
#
#   cd <COPY of a fitted tree>/projects
#   quartus_sta -t <repo>/scripts/gate/queries.tcl <out.txt> [post_map]
#
# One line per query, operating condition and kind:  <corner> | <query> | <kind> | <slack> | <from> -> <to>
# (NONE when the query has no path; ERROR when Quartus refused it), plus "collection <tag> : <n>" and one
# "design <wishbone|card4>" line. queries_gate.py judges them (thresholds there); the 0.2.6 seed 2 reference for
# sdram_cart_data is scripts/gate/ref.
#
# The MCU rows follow the design in the netlist (card4 = test build 4, the MCU fast path: the IROM / WRAM tightly
# coupled to the NEORV32, found by its mcu_tcm_wram instance; otherwise the Wishbone design of 0.2.x and of the new
# core before the fast path):
#   Wishbone (before the fast path):
#   wram_write       setup into the MCU work RAM's write side (paprium_wram port A: the seed-6 path)     >= +0.5
#   wram_read        setup out of paprium_wram (the half-cycle read into the CPU)                       >= 0
#   rv_di_irom       setup from the IROM into the NEORV32                                              >= 0
#   test build 4 (MCU_INTERFACE.md 20: both WRAM half-cycle paths are gone, every MCU memory path is a full clk_sys
#   cycle):
#   tcm_wram_in      setup into mcu_tcm_wram (processor-bus address / data / byte enables, the lock map -> the M10K
#                    write enables, the read flag and ack)                                            >= 0
#   tcm_wram_out     setup out of mcu_tcm_wram (the gated read data into the CPU, the ack)            >= 0
#   tcm_irom_in      setup into mcu_tcm_irom (the processor-bus address into the IROM M10K)           >= 0
#   tcm_irom_out     setup out of mcu_tcm_irom into the NEORV32 (fetch and load data, the ack)        >= 0
#   ramdp_ack        setup from ramdp_io's registered ack (test build 4) into the NEORV32            >= 0
#   Both designs:
#   rv_di_regs       setup from the registered FPGAIO / register-file read data into the NEORV32       >= 0
#   rv_di_ramdp      setup from RAMDP (halfword and byte views) into the NEORV32                       >= 0
#   rv_di_mem        setup from paprium_mcu_mem's read data into the NEORV32                           >= 0
#                    (0.2.x: the mcu_dati registers; the new core from fit round 2: dati_raw + sw_lo / sw_hi, the swap
#                    after)
#   sdram_cart_data  setup from the SDRAM read data to the 68000's cart_data (the FM XOR)     vs 0.2.6 seed 2
#   hold_in          any timed path into paprium_hold_sync stage_1 (the false path must cut it)         none
#   hold_out         setup / hold out of paprium_hold_sync (its later stages, md_reset_effective)     >= 0 / > 0
#   vs_in            any timed path into the VS synchroniser's stage_1 (v1.1)                          none
#   vs_out           setup / hold out of the VS synchroniser                                          >= 0 / > 0
#   vscnt            setup into fpgio's VS counter                                                    >= 0
#   the synth (test build 5 on, the synth build: the synth in region 0x06, found by a paprium_synth instance; a
#   "stage5 synth" line; B4-B9 below are the synth's blocks, listed in paprium_synth.sv's header):
#   syn_cram_rd      setup from paprium_cram's port-C read data / done (the synth's stream reads: wave and SFX
#                    samples) into the synth                                                          >= 0
#   syn_dsp          setup through the synth's DSP blocks (the gain chain B4, the wave voices B5, the SFX channels B6,
#                    the echo B7, the DT playback B9: their result pins)                              >= 0
#   syn_dsp_in       setup through the same DSP blocks' data inputs (their ax / ay / az / bx / by / bz pins): every path
#                    INTO a synth DSP, also one that ends in a register the Fitter packed into the block and so never
#                    reaches a result pin (B6's f_rate -> mp, packed into its DSP's output register, as our trim fits
#                    showed; a project decision)                                                      >= 0
#   syn_dacbuf_w     setup from the synth's CRAM port-E side (paprium_synth_cram e_*: dac_buf and the echo rings'
#                    writes, the E read requests) into paprium_cram                                   >= 0
#   syn_dacbuf_r     setup from paprium_cram's port-E read data / done (the DT playback's dac_buf reads, the echo
#                    rings) into the synth                                                            >= 0
#   irom_x           setup from the IROM extension's block RAM (mcu_irom rom_x: the 88 KB IROM's 7 slices and their
#                    output mux) into the NEORV32                                                     >= 0
# post_map: create_timing_netlist -post_map (collections only; slacks are estimates).
set out [lindex $quartus(args) 0]
set postmap [expr {[llength $quartus(args)] > 1 && [lindex $quartus(args) 1] eq "post_map"}]
project_open megadrive_pocket -revision megadrive_pocket
if {$postmap} { create_timing_netlist -post_map } else { create_timing_netlist }
read_sdc
update_timing_netlist
set fh [open $out w]
proc nm {id} { if {[catch {set v [get_node_info -name $id]}]} { return NA }; return $v }
set card4 [expr {[get_collection_size [get_keepers -nowarn {*|mcu_core:mcu_inst|mcu_tcm_wram:*}]] > 0}]
puts $fh "design [expr {$card4 ? {card4} : {wishbone}}]"
set s5 [expr {[get_collection_size [get_keepers -nowarn {*|paprium_synth:*}]] > 0}]
if {$s5} { puts $fh "stage5 synth" }
set C [dict create]
set CL {
  neo        {*|mcu_core:mcu_inst|*:neorv32_inst|*}                           keep
  regs_dati  {*|fpgio:fpgio_inst|mcu_dati[*] *|paprium_regfile:regfile_inst|mcu_dati[*]}    reg
  ramdp      {*|ramdp_io:ramdp_inst|*}                                                      keep
  mem_dati   {*|paprium_mcu_mem:mem_inst|mcu_dati[*] *|paprium_mcu_mem:mem_inst|dati_raw[*] *|paprium_mcu_mem:mem_inst|sw_lo *|paprium_mcu_mem:mem_inst|sw_hi} reg
  sdram_dout {*|cartridge:cartridge|sdram:sdram|dout*}                                      reg
  cart_data  {*|cartridge:cartridge|cart_data[*]}                                           reg
  hold_s1    {*|synch_3:paprium_hold_sync|stage_1[*]}                                       reg
  hold_all   {*|synch_3:paprium_hold_sync|*}                                                reg
  vs_s1      {*|paprium_vs_tap:*|synch_3:vs_sync|stage_1[*]}                                reg
  vs_all     {*|paprium_vs_tap:*|synch_3:vs_sync|*}                                         reg
  vscnt      {*|fpgio:fpgio_inst|vscnt[*]}                                                  reg
}
if {$card4} {
  lappend CL tcm_wram {*|mcu_core:mcu_inst|mcu_tcm_wram:wram_tcm_inst|*} keep \
             tcm_irom {*|mcu_core:mcu_inst|mcu_tcm_irom:irom_tcm_inst|*} keep \
             ramdp_ack {*|ramdp_io:ramdp_inst|mcu_ack} reg
} else {
  lappend CL wram {*|paprium_wram:wram_inst|*} keep \
             wram_wr {*|paprium_wram:wram_inst|*porta*} keep \
             irom {*|mcu_irom:mcu_irom_inst|*} keep
}
if {$s5} {
  lappend CL syn_all   {*|paprium_synth:*} keep \
             cram_c_rd {*|paprium_cram:*|c_rdata[*] *|paprium_cram:*|c_rd_done} reg \
             cram_e_rd {*|paprium_cram:*|e_rdata[*] *|paprium_cram:*|e_rd_done} reg \
             cram_all  {*|paprium_cram:*} reg \
             syn_e     {*|paprium_synth_cram:*|e_*} keep \
             syn_dsp_p {*synth_on.synth_inst|*|Mult*|resulta[*]} pin \
             syn_dsp_in_p {*synth_on.synth_inst|*|Mult*|ax[*] *synth_on.synth_inst|*|Mult*|ay[*] *synth_on.synth_inst|*|Mult*|az[*] *synth_on.synth_inst|*|Mult*|bx[*] *synth_on.synth_inst|*|Mult*|by[*] *synth_on.synth_inst|*|Mult*|bz[*]} pin \
             irom_x    {*|mcu_irom:mcu_irom_inst|altsyncram:rom_x_rtl_0|*} keep
}
foreach {tag pat kind} $CL {
  if {$kind eq "reg"} { set c [get_registers -nowarn $pat] } elseif {$kind eq "pin"} { set c [get_pins -compatibility_mode -nowarn $pat] } else { set c [get_keepers -nowarn $pat] }
  dict set C $tag $c
  puts $fh "collection $tag : [get_collection_size $c]"
}
proc q {fh cn name kind n args} {
  if {[catch {set ps [get_timing_paths -$kind -npaths $n {*}$args]} e]} { puts $fh "$cn | $name | $kind | ERROR | $e"; return }
  set k 0
  foreach_in_collection t $ps {
    puts $fh "$cn | $name | $kind | [format %.3f [get_path_info $t -slack]] | [nm [get_path_info $t -from]] -> [nm [get_path_info $t -to]]"
    incr k
  }
  if {$k == 0} { puts $fh "$cn | $name | $kind | NONE | no path" }
}
# one query: name kind npaths, then {from-tag or -} {to-tag or -}, or {through-tag prefixed with @} -; an empty
# collection prints EMPTY (never an unrestricted query: Quartus would read an empty -from / -to / -through as "any")
if {$card4} {
  set QL {
    tcm_wram_in     setup 3 -          tcm_wram
    tcm_wram_out    setup 3 tcm_wram   -
    tcm_irom_in     setup 3 -          tcm_irom
    tcm_irom_out    setup 3 tcm_irom   neo
    ramdp_ack       setup 3 ramdp_ack  neo
  }
} else {
  set QL {
    wram_write      setup 3 -          wram_wr
    wram_read       setup 3 wram       -
    rv_di_irom      setup 3 irom       neo
  }
}
append QL {
  rv_di_regs      setup 3 regs_dati  neo
  rv_di_ramdp     setup 3 ramdp      neo
  rv_di_mem       setup 3 mem_dati   neo
  sdram_cart_data setup 3 sdram_dout cart_data
  hold_in         setup 1 -          hold_s1
  hold_in         hold  1 -          hold_s1
  hold_out        setup 3 hold_all   -
  hold_out        hold  3 hold_all   -
  vs_in           setup 1 -          vs_s1
  vs_in           hold  1 -          vs_s1
  vs_out          setup 3 vs_all     -
  vs_out          hold  3 vs_all     -
  vscnt           setup 3 -          vscnt
  vscnt           hold  3 -          vscnt
}
if {$s5} {
  append QL {
    syn_cram_rd     setup 3 cram_c_rd  syn_all
    syn_dsp         setup 3 @syn_dsp_p -
    syn_dsp_in      setup 3 @syn_dsp_in_p -
    syn_dacbuf_w    setup 3 syn_e      cram_all
    syn_dacbuf_r    setup 3 cram_e_rd  syn_all
    irom_x          setup 3 irom_x     neo
  }
}
foreach_in_collection oc [get_available_operating_conditions] {
  set_operating_conditions $oc
  update_timing_netlist
  set cn [get_operating_conditions_info $oc -display_name]
  foreach {name kind n ft tt} $QL {
    set args {}
    set empty 0
    if {[string index $ft 0] eq "@"} { set c [dict get $C [string range $ft 1 end]]; if {[get_collection_size $c] == 0} { set empty 1 }; lappend args -through $c } \
    elseif {$ft ne "-"} { set c [dict get $C $ft]; if {[get_collection_size $c] == 0} { set empty 1 }; lappend args -from $c }
    if {$tt ne "-"} { set c [dict get $C $tt]; if {[get_collection_size $c] == 0} { set empty 1 }; lappend args -to $c }
    if {$empty} { puts $fh "$cn | $name | $kind | EMPTY | a collection matched nothing"; continue }
    q $fh $cn $name $kind $n {*}$args
  }
  flush $fh
}
close $fh
delete_timing_netlist
project_close
