# Usage: quartus_sta -t scripts/sta_custom_report.tcl
#
# Writes setup/hold path reports and the clock Fmax summary to
# build_output/reports/ for CI to collect.
#
# pocket: no upstream counterpart, writes the setup/hold path reports and the clock Fmax
# summary that CI collects.

# Save working directory BEFORE project_open changes it
set base_dir [pwd]
set project_path "$base_dir/projects/megadrive_pocket"
set report_dir   "$base_dir/build_output/reports"

file mkdir $report_dir

post_message "Base directory : $base_dir"
post_message "Project        : $project_path"
post_message "Report output  : $report_dir"

# Open project and set up timing analysis
project_open $project_path
create_timing_netlist
read_sdc
update_timing_netlist

# Generate detailed reports
set out_setup "$report_dir/megadrive_pocket.sta.paths_setup.rpt"
set out_setup_0c "$report_dir/megadrive_pocket.sta.paths_setup_current_0c.rpt"
set out_hold  "$report_dir/megadrive_pocket.sta.paths_hold.rpt"
set out_sum   "$report_dir/megadrive_pocket.sta.clock_summary.rpt"

post_message "Generating setup timing paths report..."
report_timing -setup -npaths 80 -detail full_path -file $out_setup

post_message "Generating hold timing paths report..."
report_timing -hold  -npaths 40 -detail full_path -file $out_hold

set sdram_reports [list]

# sdram_clk only exists once the core drives the SDRAM pins and the create_generated_clock
# in core_constraints.sdc is enabled. Asking for these reports before that fails the
# report_timing command outright, so skip them until the clock is there.
if {[get_collection_size [get_clocks -nowarn sdram_clk]] > 0} {
    set out_sdram_wr "$report_dir/megadrive_pocket.sta.sdram_write.rpt"
    set out_sdram_rd "$report_dir/megadrive_pocket.sta.sdram_read.rpt"
    set sdram_reports [list $out_sdram_wr $out_sdram_rd]

    post_message "Generating SDRAM write path report (sys_pll -> sdram_clk)..."
    report_timing -setup -npaths 10 -detail full_path \
      -to_clock sdram_clk \
      -file $out_sdram_wr

    post_message "Generating SDRAM read path report (sdram_clk -> sys_pll)..."
    report_timing -setup -npaths 10 -detail full_path \
      -from_clock sdram_clk \
      -file $out_sdram_rd
} else {
    post_message "No sdram_clk defined, skipping the SDRAM path reports"
}

post_message "Generating clock Fmax summary..."
report_clock_fmax_summary -file $out_sum

# 0C corner last: each set_operating_conditions invalidates the timing
# netlist, so visiting the corner once (with no switch-back) saves a full
# timing update pass.
post_message "Generating 0C setup timing paths report..."
set_operating_conditions 8_slow_1100mv_0c
report_timing -setup -npaths 120 -detail full_path -file $out_setup_0c

foreach f [concat [list $out_setup $out_setup_0c $out_hold $out_sum] $sdram_reports] {
    if {[file exists $f]} {
        post_message "  OK: $f ([file size $f] bytes)"
    } else {
        post_message -type warning "  MISSING: $f"
    }
}

delete_timing_netlist
project_close

post_message "Custom STA reports complete."
