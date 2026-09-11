# Animation analysis toolchain

Tools for reading Paprium's animation data and for testing a firmware animation
rule *without* a Quartus fit or a hardware session. They exist because the
dropped-weapon bug (0.2.4) took four refuted theories to solve, and every one of
them was killed by a measurement these scripts made.

They read two game-derived inputs, **neither of which is in this repository and
neither of which may be committed**:

```bash
export PAPRIUM_ROM=/path/to/Paprium.md
export PAPRIUM_ANIM_BLOB=/path/to/c010000_0001_00_0C0000_80.bin   # ROM 0x0C0000, decompressed
```

`paprium_data.py` resolves them and fails with instructions if they are unset.

## The tools

| script | what it does |
|---|---|
| `anim_data.py` | The animation table in the word order the cartridge MCU sees. `frames(w, obj, anim)` returns the frame words and the loop target; `loop_index()` says whether an animation loops or terminates. Run it directly to list an object's animations. |
| `sprite_blocks.py` | Per-frame graphics-block fingerprints. Matching these against winlog kind 15 tells you which animation was **really** drawn, whatever the object table claimed. |
| `winlog_objects.py` | Parses the winlog's per-object records into `(frame, slot, anim, nextAnim, reset, objID, +0x06, objAttr, framePtr, posX, posY)`. Reads older captures that carry only the first few fields. |
| `sim_anim_firmware.py` | Replays this firmware's `ppm_obj_render` against recorded captures. **This is the test that counts** — see below. |
| `render_object.py` | Renders an object's animations to PNG. Identifying an object by eye takes minutes; inferring one from its animation structure cost a day and was wrong three times. |

## Why the emulator cannot test an animation rule

Genesis Plus GX decides what to do at the end of an animation on the call that
**draws its last frame**. This firmware keeps the frame just drawn and decides on
the **next** call. A dropped weapon's queued follow-up is armed in the one-frame
gap between those two points, so the two implementations give *opposite* answers
on exactly the case that matters. An emulator "confirmation" would have been
meaningless in either direction.

`sim_anim_firmware.py` sidesteps that by replaying the firmware's own logic. The
game's whole side of the interface — `anim`, `nextAnim`, `reset` per object per
frame — is in the winlog, and the animation data is in the ROM, which is
everything `ppm_obj_render` reads:

```bash
python scripts/sim_anim_firmware.py ../vdp-capture/*.bin
```

It reports which objects chained and whether any chain escaped the character
walk-in, which is the regression to guard. 0.2.4 was settled this way: 5,558
object episodes, 11 of 11 weapon chains, 0 walk-in chains, stable for every
timing window from 0 to 4.

## The attract-mode demo is a test rig

Paprium's attract mode plays the game by itself — it fights, drops weapons and
walks characters in. Build the instrumented core, launch it, and leave it:

```bash
./scripts/gpgx_winlog_build.sh
# then RetroArch with -L gpgx-build/genesis_plus_gx_libretro.dll,
# working directory vdp-capture/ (the core writes paprium_winlog.bin there)
```

Each launch **overwrites** that file, so copy it aside first. It grows ~7 MB a
minute and weapon drops appeared around frame 47,000, so budget 20 minutes. Add a
`winlog_raw(26, ...)` at a decision point and the capture says directly which
objects your rule fired on — that is how the spawn-animation theory was refuted in
a single run, before it cost a fit.

The demo never picks a weapon back up, so anything needing player interaction
still needs a person at the controls.
