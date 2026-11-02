#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""Write the Quartus .hdl.mif init files of the Paprium MCU memories from the firmware's $readmemh images.

Stages 2, 3 and 4b of the 0.3.0 work change only the MCU firmware (0.3.0 was made in numbered stages: 1 = the new
firmware's own start-up, scheduler, dispatcher and board layer, 2 = the sprite engine, 3 = the unpackers, saves, zoom
and MegaWire, 4 = the sound bank cache, 5 = the music: our own song engine and synth). Their images reach a fitted bitstream without a refit:
this script rewrites the memories' init files in the fit's db/ folder, then `quartus_cdb --update_mif` and
`quartus_asm` rebuild the bitstream around the same placement.

usage: mkmif.py <img_dir> --db <projects/db> [--out <dir>] [--check]

  <img_dir>  mcu.txt, mcu_ext.txt and the WRAM images the fit's RTL reads ($readmemh format): wram_b0.txt ..
             wram_b3.txt (test build 4 on: four byte lanes) or wram_lo.txt / wram_hi.txt (before test build 4; a
             test build is a build B Jam tested on his own Pocket)
  --db       the fitted project's db folder. Each image is matched to its .hdl.mif there by the RAM's module (the
             file's signature line), its width and its depth, so the mapping follows the fit (instance hash,
             depth) rather than being written into this script.
  --out      write the regenerated files there, under the db's names, for copying into db/
  --check    compare each regenerated file byte for byte with the db's (the identity guard: on the images the
             fit was built from, every file must be IDENTICAL; run it once on every new fit before trusting the
             route)

Mapping (the db's .hdl.mif files that carry these memories):
  mcu_irom      the two arrays of rtl/PAPRIUM/mcu_core.sv: the 8192-deep one is rom0 (mcu.txt); the other is the
                extension (mcu_ext.txt): 14,336 deep from test build 5 (stage 5: the 88 KB IROM, EXT_KB = 56, built as 7
                slices of 2048 x 32: Quartus still writes ONE .hdl.mif for the inferred array, the depth tells it
                apart), 10,240 deep in 0.3.0 stage 1 and test builds 4a / 4b (EXT_KB = 40), 5,632 in 0.2.x
  paprium_wram  test build 4 on (four 12,288 x 8 lanes): ram0..ram3 = wram_b0.txt..wram_b3.txt (the declaration order of
                ram_b0..ram_b3 in rtl/PAPRIUM/memory.sv; check it with --check on the first test-build-4 database).
                Before test build 4 (two 24,576 x 8 arrays): ram0 = wram_lo.txt, ram1 = wram_hi.txt (the declaration order,
                measured on the 0.2.6 seed-5 fit; re-check it with --check whenever paprium_wram changes)
An image with fewer words than the memory is padded with zeros, as $readmemh leaves it; more words is an error.

The written format is Quartus' own (CRLF, signature header, UNS addresses descending, BIN data MSB first, tab
separated); --check against the 0.2.6 seed-5 db gave IDENTICAL on all four files.
"""
import argparse
import glob
import hashlib
import os
import re
import sys

IMAGES = {
    # image file: (module, width)
    "mcu.txt":     ("mcu_irom", 32),
    "mcu_ext.txt": ("mcu_irom", 32),
    "wram_lo.txt": ("paprium_wram", 8),
    "wram_hi.txt": ("paprium_wram", 8),
    "wram_b0.txt": ("paprium_wram", 8),   # test build 4 on: the four byte lanes
    "wram_b1.txt": ("paprium_wram", 8),
    "wram_b2.txt": ("paprium_wram", 8),
    "wram_b3.txt": ("paprium_wram", 8),
}


def readmemh(path, depth, width):
    txt = open(path, "r").read()
    txt = re.sub(r"/\*.*?\*/", " ", txt, flags=re.S)
    txt = re.sub(r"//[^\n]*", " ", txt)
    mem = [0] * depth
    a = n = 0
    for tok in txt.split():
        if tok.startswith("@"):
            a = int(tok[1:], 16)
            continue
        if re.search(r"[xXzZ]", tok):
            raise SystemExit(f"{path}: x/z token {tok!r} not handled")
        v = int(tok.replace("_", ""), 16)
        if v >> width:
            raise SystemExit(f"{path}: value {tok} wider than {width} bits")
        if a >= depth:
            raise SystemExit(f"{path}: address {a} beyond the memory's depth {depth}")
        mem[a] = v
        a += 1
        n += 1
    return mem, n


def mif_text(sig, width, depth, mem):
    # sig = the signature lines as the database has them (one per line, without "-- "): a parameterised instance
    # (test build 4's mcu_irom #(.EXT_KB(EXT_KB))) gets "mcu_irom(EXT_KB" and "40)"
    out = ["-- begin_signature"] + [f"-- {s}" for s in sig] + ["-- end_signature",
           f"WIDTH={width};", f"DEPTH={depth};", "", "ADDRESS_RADIX=UNS;", "DATA_RADIX=BIN;", "",
           "CONTENT BEGIN"]
    for a in range(depth - 1, -1, -1):
        out.append(f"\t{a} :\t{mem[a]:0{width}b};")
    out.append("END;")
    return ("\r\n".join(out) + "\r\n").encode("ascii")


def db_mifs(db):
    """{module: [(ram_index, name, width, depth, signature lines)]} for every .hdl.mif in db."""
    found = {}
    for path in sorted(glob.glob(os.path.join(db, "*.hdl.mif"))):
        name = os.path.basename(path)
        head = open(path, "rb").read(400).decode("ascii", "replace")
        sig = re.search(r"-- begin_signature\r?\n((?:-- [^\r\n]*\r?\n)+?)-- end_signature", head)
        wid = re.search(r"WIDTH=(\d+);", head)
        dep = re.search(r"DEPTH=(\d+);", head)
        idx = re.search(r"\.ram(\d+)_", name)
        if not (sig and wid and dep and idx):
            continue
        lines = [ln[3:] for ln in sig.group(1).replace("\r", "").split("\n") if ln]
        module = lines[0].split("(")[0]
        found.setdefault(module, []).append((int(idx.group(1)), name, int(wid.group(1)), int(dep.group(1)), lines))
    return found


def mapping(db):
    found = db_mifs(db)
    irom = found.get("mcu_irom", [])
    wram = found.get("paprium_wram", [])
    if len(irom) != 2:
        raise SystemExit(f"{db}: expected 2 mcu_irom mifs, found {len(irom)}")
    rom0 = [m for m in irom if m[3] == 8192]
    ext = [m for m in irom if m[3] != 8192]
    if len(rom0) != 1 or len(ext) != 1:
        raise SystemExit(f"{db}: cannot tell rom0 (8192 deep) from the extension: {irom}")
    wmap = {m[0]: m for m in wram}
    if sorted(wmap) == [0, 1, 2, 3]:      # test build 4 on: the four byte lanes
        return {"mcu.txt": rom0[0], "mcu_ext.txt": ext[0], "wram_b0.txt": wmap[0], "wram_b1.txt": wmap[1],
                "wram_b2.txt": wmap[2], "wram_b3.txt": wmap[3]}
    if sorted(wmap) != [0, 1]:
        raise SystemExit(f"{db}: expected paprium_wram ram0..ram3 (card 4) or ram0 and ram1, found {wram}")
    return {"mcu.txt": rom0[0], "mcu_ext.txt": ext[0], "wram_lo.txt": wmap[0], "wram_hi.txt": wmap[1]}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("img_dir")
    ap.add_argument("--db", required=True)
    ap.add_argument("--out")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if not a.out and not a.check:
        ap.error("nothing to do: give --out, --check or both")
    if a.out:
        os.makedirs(a.out, exist_ok=True)
    ok = True
    for src, (_, name, width, depth, sig) in mapping(a.db).items():
        module, w = IMAGES[src]
        if w != width or sig[0].split("(")[0] != module:
            raise SystemExit(f"{name}: width {width} / module {sig[0]}, {src} is {w} bits of {module}")
        mem, n = readmemh(os.path.join(a.img_dir, src), depth, width)
        data = mif_text(sig, width, depth, mem)
        line = f"{src:12s} words={n:6d} of {depth:6d} -> {name} md5={hashlib.md5(data).hexdigest()}"
        if a.out:
            open(os.path.join(a.out, name), "wb").write(data)
        if a.check:
            same = open(os.path.join(a.db, name), "rb").read() == data
            ok &= same
            line += "  IDENTICAL" if same else "  DIFFERENT"
        print(line)
    if a.check:
        print("ALL_IDENTICAL" if ok else "MISMATCH")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
