# pocket: derived from agg23/openfpga-SNES generate.tcl, a bare project_open / execute_flow /
# project_close plus argv-driven selection of bitstream variants. The variant
# selection is kept, because this core ships four bitstreams (NTSC, PAL and their
# SVP twins) off one revision; the
# snapshot guard below, the STA report pass and the non-zero exit for CI are local.

package require ::quartus::project
package require ::quartus::flow

set base_dir [pwd]

# One revision builds every bitstream: a second revision would fork the ~35 tuned
# assignments in megadrive_pocket.qsf and they would drift apart. The svp variants
# trade the cartridge's save hardware for Virtua Racing's DSP, which does not fit
# next to the full core.
set variant [expr {$argc > 0 ? [lindex $argv 0] : "ntsc"}]

# Optional second argument: a fitter seed, for a seed sweep on a variant that is
# fitting at 98% and so lands differently run to run. Deliberately NOT an
# assignment in megadrive_pocket.qsf - three stray SEED lines were once committed
# there by a `git add -A` and would have silently steered every later build. The
# snapshot/restore below keeps the tracked qsf clean even though this writes an
# assignment into the open project. No argument means the qsf's own default.
set fit_seed [expr {$argc > 1 ? [lindex $argv 1] : ""}]
# paprium: the paprium variant is NTSC only - the MCU firmware's clock-derived timing
# is pinned to the 53.693 MHz NTSC master clock - and never SVP, since both the SVP and
# the Paprium MCU want SDRAM port 2
switch -- $variant {
    ntsc     { set pal_param '0; set svp_param '0; set paprium_param '0 ; set paprium_sfx_param '1 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    pal      { set pal_param '1; set svp_param '0; set paprium_param '0 ; set paprium_sfx_param '1 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    ntsc_svp { set pal_param '0; set svp_param '1; set paprium_param '0 ; set paprium_sfx_param '1 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    pal_svp  { set pal_param '1; set svp_param '1; set paprium_param '0 ; set paprium_sfx_param '1 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    paprium  { set pal_param '0; set svp_param '0; set paprium_param '1 ; set paprium_sfx_param '1 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    paprium_nosfx { set pal_param '0; set svp_param '0; set paprium_param '1; set paprium_sfx_param '0 ; set cdda_dbg_param '0 ; set cmdlog_param '0 }
    paprium_cddadbg { set pal_param '0; set svp_param '0; set paprium_param '1; set paprium_sfx_param '1; set cdda_dbg_param '1 ; set cmdlog_param '0 }
    paprium_cmdlog { set pal_param '0; set svp_param '0; set paprium_param '1; set paprium_sfx_param '1; set cdda_dbg_param '0 ; set cmdlog_param '1 }
    default { error "unknown variant \"$variant\", expected ntsc, pal, ntsc_svp, pal_svp, paprium, paprium_nosfx, paprium_cddadbg or paprium_cmdlog" }
}

# Quartus re-stamps QUARTUS_VERSION / LAST_QUARTUS_VERSION into these on open and
# close. The tracked copies stay at 21.1 so 21.1 and 25.1 build from one tree, so
# snapshot them here and restore them below.
set guarded_files {
    projects/megadrive_pocket.qpf
    projects/megadrive_pocket.qsf
}
set snap_dir build_output/.proj_snapshot
file mkdir $snap_dir
foreach f $guarded_files {
    if {[file exists $f]} {
        file copy -force $f [file join $snap_dir [file tail $f]]
    }
}

# -force lets project_open overwrite a revision database written by the other
# Quartus version; it lives under gitignored build output and is rebuilt anyway.
# The catch is required, not cosmetic: project_open stamps the guarded files
# immediately, so an aborted compile still needs the restore below to run.
set build_status [catch {
    project_open -force -revision megadrive_pocket projects/megadrive_pocket.qpf
    set_global_assignment -name NUM_PARALLEL_PROCESSORS ALL
    set_parameter -name PAL -entity core_top $pal_param
    set_parameter -name SVP -entity core_top $svp_param
    set_parameter -name PAPRIUM -entity core_top $paprium_param
    set_parameter -name PAPRIUM_SFX -entity core_top $paprium_sfx_param
    set_parameter -name PAPRIUM_CMD_LOG -entity core_top $cmdlog_param
    set_parameter -name PAPRIUM_CDDA_DBG -entity core_top $cdda_dbg_param

    # paprium: the shared qsf is tuned for Fmax - its own comment says the first fit
    # landed at 82% ALM "so there is room to spend on Fmax". The Paprium variants have
    # no such room: they fit at 99-100% and fail on LAB packing, not ALM count. Trade
    # it back here rather than in the qsf, so the ntsc/pal/svp bitstreams keep the
    # tuning that suits them.
    if {$paprium_param ne "'0"} {
        set_global_assignment -name OPTIMIZATION_MODE "AGGRESSIVE AREA"
        set_global_assignment -name OPTIMIZATION_TECHNIQUE AREA
        set_global_assignment -name QII_AUTO_PACKED_REGISTERS "MINIMIZE AREA WITH CHAINS"
        set_global_assignment -name PHYSICAL_SYNTHESIS_COMBO_LOGIC_FOR_AREA ON
        set_global_assignment -name ALM_REGISTER_PACKING_EFFORT HIGH
        set_global_assignment -name FITTER_EFFORT "STANDARD FIT"
        post_message "paprium: area-optimised fitter settings applied"
    }

    if {$fit_seed ne ""} {
        set_global_assignment -name SEED $fit_seed
        post_message "fitter seed $fit_seed (this run only - not written to the qsf)"
    }
    execute_flow -compile
    project_close

    # project_open changes cwd to the project directory; restore it
    cd $base_dir

    # Run custom STA report for detailed timing path analysis.
    # (sta_custom_report.tcl verifies its own report outputs.)
    file mkdir build_output/reports
    post_message "Running custom STA report..."
    if {[catch {qexec "quartus_sta -t scripts/sta_custom_report.tcl"} result]} {
        post_message -type warning "Custom STA report failed: $result"
    } else {
        post_message "Custom STA completed successfully."
    }
} build_error]

# The catch may have aborted with cwd still inside the project dir; reset it so
# the relative guarded/snapshot paths below resolve correctly.
cd $base_dir

# Restore the guarded files, on success and on failure alike. Must come after the
# STA report, which reopens the project and re-stamps the version metadata again.
foreach f $guarded_files {
    set snap [file join $snap_dir [file tail $f]]
    if {[file exists $snap]} {
        file copy -force $snap $f
    }
}

# Propagate a build/flow failure now that the files are restored, so quartus_sh
# -t exits non-zero for CI.
if {$build_status} {
    error $build_error
}
