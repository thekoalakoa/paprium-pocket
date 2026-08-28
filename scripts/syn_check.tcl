# paprium: analysis + synthesis only, for fast feedback on RTL errors.
# generate.tcl runs the whole flow, which is an hour per variant on this device;
# most iterations only need to know whether the tree elaborates and what it
# synthesises to. Usage:
#
#   quartus_sh -t scripts/syn_check.tcl <variant>
#
# Variant names match generate.tcl. Leaves the project files stamped the way
# generate.tcl's guard does, so run that for anything shipped.

package require ::quartus::project
package require ::quartus::flow

set base_dir [pwd]
set variant [expr {$argc > 0 ? [lindex $argv 0] : "paprium"}]

switch -- $variant {
    ntsc     { set pal_param '0; set svp_param '0; set paprium_param '0 ; set paprium_sfx_param '1 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    pal      { set pal_param '1; set svp_param '0; set paprium_param '0 ; set paprium_sfx_param '1 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    ntsc_svp { set pal_param '0; set svp_param '1; set paprium_param '0 ; set paprium_sfx_param '1 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    pal_svp  { set pal_param '1; set svp_param '1; set paprium_param '0 ; set paprium_sfx_param '1 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    paprium  { set pal_param '0; set svp_param '0; set paprium_param '1 ; set paprium_sfx_param '1 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    paprium_nosfx { set pal_param '0; set svp_param '0; set paprium_param '1; set paprium_sfx_param '0 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    paprium_cddadbg { set pal_param '0; set svp_param '0; set paprium_param '1; set paprium_sfx_param '1; set cdda_dbg_param '1 ; set cmdlog_param '0 }
    paprium_cmdlog { set pal_param '0; set svp_param '0; set paprium_param '1; set paprium_sfx_param '1; set cdda_dbg_param '0 ; set cmdlog_param '1 }
    default { error "unknown variant \"$variant\"" }
}

set snap_dir build_output/.proj_snapshot
file mkdir $snap_dir
foreach f {projects/megadrive_pocket.qpf projects/megadrive_pocket.qsf} {
    if {[file exists $f]} {
        file copy -force $f [file join $snap_dir [file tail $f]]
    }
}

set status [catch {
    project_open -force -revision megadrive_pocket projects/megadrive_pocket.qpf
    set_global_assignment -name NUM_PARALLEL_PROCESSORS ALL
    set_parameter -name PAL -entity core_top $pal_param
    set_parameter -name SVP -entity core_top $svp_param
    set_parameter -name PAPRIUM -entity core_top $paprium_param
    set_parameter -name PAPRIUM_SFX -entity core_top $paprium_sfx_param
    set_parameter -name PAPRIUM_CDDA_DBG -entity core_top $cdda_dbg_param
    set_parameter -name PAPRIUM_CMD_LOG -entity core_top $cmdlog_param
    execute_module -tool map
    project_close
    cd $base_dir
} result]

foreach f {megadrive_pocket.qpf megadrive_pocket.qsf} {
    set snap [file join $snap_dir $f]
    if {[file exists $snap]} {
        file copy -force $snap [file join projects $f]
    }
}

if {$status} {
    post_message -type error "analysis+synthesis failed for variant $variant: $result"
    exit 1
}
post_message "analysis+synthesis OK for variant $variant"
exit 0
