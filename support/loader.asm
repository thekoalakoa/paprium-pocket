// pocket: Chip32 loader for the Mega Drive core. agg23's loader picks one bitstream
// and runs it, but this core ships four because the master clock is baked into the
// PLL and the SVP does not fit next to the save hardware, so the loader has to read
// the cartridge header's region field (0x1F0..0x1F2) and serial (0x183..0x18A) and
// choose before loading:
//   US, or anything unrecognised -> core 0 (NTSC, 53.693175 MHz)
//   EU and not US                -> core 1 (PAL, 53.203424 MHz)
//   Virtua Racing's serial       -> core 2 or 3, region as above plus the SVP
// Same region rule as MiSTer's Genesis.sv, same serials as cartridge.sv's svp_quirk.
//
// Derived from agg23/openfpga-SNES support/loader.asm: the slot numbering, the bitstream select and
// the error path are its, the SNES cartridge work (SMC header detection, ROM size
// calculation, check_header.asm) is dropped. util.asm is that repo's verbatim.

architecture chip32.vm
output "loader.bin", create

constant DEBUG = 0

// scratch area in the last 1K of the 8K chip32 memory
constant rambuf = 0x1b00

constant cart_dataslot = 1
constant save_dataslot = 10

// core_top.sv bridge registers
constant download_addr = 0x0    // downloading flag (reset envelope)
constant region_addr = 0x18     // header region, consulted when the menu is on auto

// Host init command
constant host_init = 0x4002

constant region_offset = 0x1F0
constant region_length = 3

// The header's "GM MK-1229 -00" style serial without the "GM " prefix, the same
// 8 bytes cartridge.sv compares as cart_id[63:0]
constant serial_offset = 0x183
constant serial_length = 8

// One read spans serial through region (0x183..0x1F2): util.asm's seek()/read()
// skip labels are constants, so the macros cannot expand a second time. The
// serial lands at rambuf, the region field at regionbuf inside the same window
constant header_length = region_offset + region_length - serial_offset
constant regionbuf = rambuf + region_offset - serial_offset

// Error vector (0x0)
jp error_handler

// Init vector (0x2)
jp start

include "util.asm"
align(2)

start:
// ld sets the zero flag, so the error message is staged before the open
ld r14,#rom_err_msg
ld r1,#cart_dataslot
open r1,r2
jp nz,print_error_and_exit

ld r1,#serial_offset
seek()
ld r1,#header_length
ld r2,#rambuf
read()
close

// r3 = JP seen, r4 = US seen, r5 = EU seen
ld r3,#0
ld r4,#0
ld r5,#0

// Character form, any of the three bytes, so "JUE" and "UE " both resolve
ld r6,#regionbuf
ld r7,#region_length

char_loop:
ld.b r1,(r6)
cmp r1,#0x4A                // "J"
jp nz,char_not_jp
ld r3,#1
char_not_jp:
cmp r1,#0x55                // "U"
jp nz,char_not_us
ld r4,#1
char_not_us:
cmp r1,#0x45                // "E"
jp nz,char_not_eu
ld r5,#1
char_not_eu:
add r6,#1
sub r7,#1
jp nz,char_loop

// Hex nibble form, first byte only, and only where that byte is not already a
// region character: "E" is 0x45, which also falls inside the "A".."F" range
ld.b r1,(regionbuf)
cmp r1,#0x4A                // "J"
jp z,decide
cmp r1,#0x55
jp z,decide
cmp r1,#0x45
jp z,decide

cmp r1,#0x30                // "0"
jp c,decide
cmp r1,#0x3A
jp c,nibble_digit
cmp r1,#0x41                // "A"
jp c,decide
cmp r1,#0x47
jp nc,decide
sub r1,#0x37
jp nibble_flags

nibble_digit:
sub r1,#0x30

nibble_flags:
ld r2,r1
and r2,#1                   // bit 0 = JP
jp z,nibble_us
ld r3,#1
nibble_us:
ld r2,r1
and r2,#4                   // bit 2 = US
jp z,nibble_eu
ld r4,#1
nibble_eu:
ld r2,r1
and r2,#8                   // bit 3 = EU
jp z,decide
ld r5,#1

// US wins over EU, and an unstamped or junk field falls through to NTSC
decide:
ld r0,#0
cmp r4,#0
jp nz,set_core
cmp r5,#0
jp z,set_core
ld r0,#1

// Virtua Racing needs the SVP, and its bitstreams sit at core id +2
set_core:
ld r8,#svp_serial_us
call serial_cmp
jp z,svp_core
ld r8,#svp_serial_jp
call serial_cmp
jp nz,run_core
svp_core:
add r0,#2
run_core:
core r0

// Japan only when the header says so and neither export region does, which is
// MiSTer's default US > EU > JP priority. An unstamped field resolves to US, so
// this has to test hdr_j and not just the absence of the other two. After the
// core switch, since that reconfigures the FPGA and clears the register
ld r2,#0
cmp r4,#0
jp nz,write_region
cmp r5,#0
jp nz,write_region
cmp r3,#0
jp z,write_region
ld r2,#1

write_region:
ld r1,#region_addr
pmpw r1,r2

ld r1,#download_addr
ld r2,#1
pmpw r1,r2                  // downloading = 1, core held in reset

ld r3,#cart_dataslot
ld r14,#rom_err_msg
loadf r3
jp nz,print_error_and_exit

ld r1,#download_addr
ld r2,#0
pmpw r1,r2                  // downloading = 0, ends the save clear window

// A missing save is not an error
ld r3,#save_dataslot
loadf r3

ld r0,#host_init
host r0,r0

exit 0

// Serial compare, r8 = expected string; z set only on a full 8-byte match. Uses
// r8..r12 because r3..r5 still hold the region flags for write_region
serial_cmp:
ld r9,#rambuf
ld r10,#serial_length
serial_cmp_loop:
ld.b r11,(r8)
ld.b r12,(r9)
cmp r11,r12
ret nz
add r8,#1
add r9,#1
sub r10,#1
jp nz,serial_cmp_loop
ret

error_handler:
ld r14,#generic_err_msg

print_error_and_exit:
printf r14
exit 1

svp_serial_us:
db "MK-1229 "                // Virtua Racing EU/US
svp_serial_jp:
db "G-7001  "                // Virtua Racing JP

rom_err_msg:
db "Could not load ROM",0

generic_err_msg:
db "Error",0
align(2)
