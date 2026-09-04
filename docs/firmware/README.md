# Firmware source for the Pocket port

`repos/mega-ppm` is krikzz's `mega-ppm` at upstream commit `84be6bd`
(https://github.com/krikzz/mega-ppm) with this port's changes applied as an
UNCOMMITTED working-tree diff - that repo has no git identity configured
here and nothing from this port has ever been committed to it. This patch
is the versioned copy of that diff. Regenerate it with:

    git -C repos/mega-ppm diff > docs/firmware/mega-ppm-port.patch

Firmware states the diagnostic cards were built from, by `rtl/PAPRIUM/mcu.txt`
md5 (the file Quartus bakes into the bitstream):

| mcu.txt    | switches                                   | bitstreams            |
|------------|--------------------------------------------|-----------------------|
| `357663aa` | onset ring 1, epoch 0, pad 0               | `dec2f09f` (ring)     |
| `14844a95` | onset ring 1, epoch 0, pad 0, stub staged  | control `80e68bc9`, cut-2 sweep, epoch sweep, fcut |
| `5235f357` | onset ring 0, epoch 1                      | `53076197` (hangs)    |
| `8111bd8a` | onset ring 1, epoch 0, **PPM_DA_PAD 1**    | not fitted            |

The switches live in `mcu/mame.h`. A firmware-only change is a ROM-only
change to the bitstream: fitted on the same RTL at the same seed it lands on
the same placement (the control proved this against the epoch build).

## Fitting the padding fix, when the go comes

The working RTL is the functional-cut RTL. A padding fit must use the RING
RTL to inherit `dec2f09f`'s placement (seed 5, setup -2.549, boots):

    git checkout a22aea4 -- rtl/PAPRIUM/paprium_cart.sv rtl/PAPRIUM/fpgio.sv rtl/PAPRIUM/mcu_core.sv rtl/PAPRIUM/structs.sv
    sed -i 's/^#define PPM_DA_PAD              0/#define PPM_DA_PAD              1/' ../repos/mega-ppm/mcu/mame.h
    ./scripts/build_mcu.sh          # expect mcu.txt 8111bd8a
    quartus_sh -t generate.tcl paprium 5
