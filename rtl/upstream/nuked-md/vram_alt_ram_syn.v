// Copyright (C) 2026 Marsupial Solutions LLC
// SPDX-License-Identifier: GPL-3.0-or-later
// The two block RAMs of vram_alt as Intel altsyncram instances, for the Quartus build and for our Icarus benches (with
// altera_mf.v). Our Verilator benches use behavioural twins of them, proven equal to these in a lockstep bench (the
// twins and the bench are not in this repository).

// 8192 x 64 true dual port, single clock, unregistered outputs, contents 0 at power-up.
// Port A: read/write with 8 byte enables, same-port read-during-write NEW_DATA_NO_NBE_READ (= vram.v's vram_ip).
// Port B: the same, 8 byte enables. Mixed-port read-during-write OLD_DATA (a read of the word the other port writes
// on the same edge sees the old word).
module vram_alt_mm
	(
	input         clock,
	input  [12:0] address_a,
	input   [7:0] byteena_a,
	input  [63:0] data_a,
	input         wren_a,
	output [63:0] q_a,
	input  [12:0] address_b,
	input   [7:0] byteena_b,
	input  [63:0] data_b,
	input         wren_b,
	output [63:0] q_b
	);
	altsyncram #(
		.intended_device_family("Cyclone V"),
		.lpm_type("altsyncram"),
		.operation_mode("BIDIR_DUAL_PORT"),
		.ram_block_type("M10K"),
		.width_a(64), .widthad_a(13), .numwords_a(8192),
		.width_b(64), .widthad_b(13), .numwords_b(8192),
		.width_byteena_a(8), .width_byteena_b(8), .byte_size(8),
		.outdata_reg_a("UNREGISTERED"), .outdata_reg_b("UNREGISTERED"),
		.outdata_aclr_a("NONE"), .outdata_aclr_b("NONE"),
		.address_reg_b("CLOCK0"), .indata_reg_b("CLOCK0"), .wrcontrol_wraddress_reg_b("CLOCK0"), .byteena_reg_b("CLOCK0"),
		.clock_enable_input_a("BYPASS"), .clock_enable_output_a("BYPASS"),
		.clock_enable_input_b("BYPASS"), .clock_enable_output_b("BYPASS"),
		.read_during_write_mode_port_a("NEW_DATA_NO_NBE_READ"),
		.read_during_write_mode_port_b("NEW_DATA_NO_NBE_READ"),
		.read_during_write_mode_mixed_ports("OLD_DATA"),
		.power_up_uninitialized("FALSE"),
		.init_file("UNUSED")
	) ram (
		.clock0(clock),
		.address_a(address_a), .byteena_a(byteena_a), .data_a(data_a), .wren_a(wren_a), .q_a(q_a),
		.address_b(address_b), .byteena_b(byteena_b), .data_b(data_b), .wren_b(wren_b), .q_b(q_b),
		.aclr0(1'b0), .aclr1(1'b0), .addressstall_a(1'b0), .addressstall_b(1'b0),
		.clock1(1'b1), .clocken0(1'b1), .clocken1(1'b1), .clocken2(1'b1), .clocken3(1'b1),
		.rden_a(1'b1), .rden_b(1'b1), .eccstatus()
	);
endmodule

// simple dual port, write port A 32 x 64, read port B 256 x 8 (byte j = bits 8*(j%8)+7..8*(j%8) of word j/8),
// single clock, unregistered output, contents 0 at power-up,
// mixed-port read-during-write DONT_CARE (vram_alt never uses a word on the edge it is written).
module vram_alt_sb
	(
	input         clock,
	input   [4:0] wraddress,
	input  [63:0] data,
	input         wren,
	input   [7:0] rdaddress,
	output  [7:0] q
	);
	altsyncram #(
		.intended_device_family("Cyclone V"),
		.lpm_type("altsyncram"),
		.operation_mode("DUAL_PORT"),
		.ram_block_type("M10K"),
		.width_a(64), .widthad_a(5), .numwords_a(32),
		.width_b(8), .widthad_b(8), .numwords_b(256),
		.width_byteena_a(1),
		.outdata_reg_b("UNREGISTERED"), .outdata_aclr_b("NONE"),
		.address_reg_b("CLOCK0"), .rdcontrol_reg_b("CLOCK0"),
		.clock_enable_input_a("BYPASS"), .clock_enable_input_b("BYPASS"), .clock_enable_output_b("BYPASS"),
		.read_during_write_mode_mixed_ports("DONT_CARE"),
		.power_up_uninitialized("FALSE"),
		.init_file("UNUSED")
	) ram (
		.clock0(clock),
		.address_a(wraddress), .data_a(data), .wren_a(wren),
		.address_b(rdaddress), .q_b(q),
		.aclr0(1'b0), .aclr1(1'b0), .addressstall_a(1'b0), .addressstall_b(1'b0), .byteena_a(1'b1), .byteena_b(1'b1),
		.clock1(1'b1), .clocken0(1'b1), .clocken1(1'b1), .clocken2(1'b1), .clocken3(1'b1),
		.data_b({8{1'b1}}), .rden_a(1'b1), .rden_b(1'b1), .wren_b(1'b0), .q_a(), .eccstatus()
	);
endmodule
