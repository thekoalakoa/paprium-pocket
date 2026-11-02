# core/tables: the cart chip's constant tables, generated

Written 2026-10-10. `chip_tables.c` / `chip_tables.h` are **generated** by `gen_chip_tables.py`; do not edit them.
No value here comes from the cart program's bytes. The tables were worked out from our own study of how the cart
behaves and checked on hardware. The cart chip is the STM32 microcontroller on the real cartridge.

```
python -I -B core/tables/gen_chip_tables.py                  # rewrite chip_tables.c / chip_tables.h
python -I -B core/tables/gen_chip_tables.py --mif DIR        # + chip_out_curve_knee.mif (11-bit words) for the RTL
python -I -B core/tables/gen_chip_tables.py --bin-dir DIR    # + raw images of the tables (for checks)
```

Python 3 standard library only. The arithmetic is done at 60 digits (Python's `decimal` module), so the output does
not depend on the host's math library.

## What is here

| array | what | entries | bytes |
|---|---|---|---|
| `chip_pan_A` | a pan table | 256 x u8 | 256 |
| `chip_pan_B` | a pan table | 256 x u8 | 256 |
| `chip_level_T` | the level table | 512 x u16 | 1,024 |
| `chip_wave_expand` | the sample expansion (companding) table of the wave voices | 256 x s16 | 512 |
| `chip_sfx8_expand` | the sample expansion table of the 8-bit sound effects | 256 x s16 | 512 |
| `chip_sfx4_expand` | the sample expansion table of the 4-bit sound effects | 16 x s16 | 32 |
| `chip_out_curve_knee` | the stored part of the output soft-clip curve (16,384 entries in all) | 2,464 x u16 (11-bit values) | 4,928 |

Total: 2,592 bytes for the six start-up tables, 7,520 bytes with the curve (measured, the rv32 object's `.rodata`).
Some entries look odd; they are the cart chip's own values, kept as they are.

The level table T is not in the image (2026-10-30): `chip_tables.c` holds `chip_level_init`, which the boot runs at
every MCU start before any post can arrive (interim/s1/bodies_s1.c `s1_interim_boot`), and the 1,024-byte array in
working RAM (wram_upper). The loop uses integers only. `gen_chip_tables.py` runs the same loop and stops unless it gives
the exact table; `tests/equiv/leveltab.py` checks a built image's RAM (the init alone, and after the board model's
boot).

`chip_out_curve(idx)` gives any entry of the full output curve.
