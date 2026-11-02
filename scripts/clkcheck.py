#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""clkcheck: the RTL has one clock value, and no clock-derived number is written as a literal.

Written in 0.3.0's stage 1, the first stage of the new firmware and its RTL (the firmware tree's docs/MCU_INTERFACE.md
v1.0, section 7). core_top defines the clock once:
    localparam integer CLK_HZ    = PAL ? 53_203_424 : 53_693_175;   // clk_sys
    localparam integer CLK_MD_HZ = 2 * CLK_HZ;                      // clk_md
and passes it down as parameters. Every count that depends on the clock (dividers, timeouts, generics) is an
expression of CLK_HZ or CLK_MD_HZ, so a PAL build (or another clock) changes one line. This lint keeps it so.

Rules (scope and allow-list in scripts/clkcheck.json):
  R1  the retired `CLK_FREQ macro appears nowhere.
  R2  no integer literal, in any base, lies within 0.5 % of a clock value (CLK_HZ or CLK_MD_HZ, NTSC or PAL),
      except on core_top's own CLK_HZ definition line.
  R3  every decimal literal >= 1000 either sits on a line that names CLK_HZ or CLK_MD_HZ (a rate or ratio the
      clock is divided by), or is on the allow-list for its file with its exact count and the reason it does not
      follow the clock (a sample rate, a size, a console-clock or APF-clock count, ...).
  R4  every module that declares a CLK_HZ / CLK_MD_HZ parameter gives it the default 0 (unset), and every
      instance of it in scope sets it by name.
  Pending entries (clock-derived literals below the R3 threshold that another item owns) print a warning
  while they are still there. The last one, the SDRAM refresh compare, is done (see "done" in the json).

usage: clkcheck.py [--root DIR] [--selftest]
  exit 0 = clean, 1 = a rule failed. --selftest plants literals in an in-memory copy of the tree (nothing is
  written) and checks that each plant is caught and that the clean tree passes.
"""
import argparse
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

NUM = re.compile(r"(?<![\w'$`.])(?:(\d[\d_]*)\s*)?'[sS]?([dDhHbBoO])\s*([0-9a-fA-FxXzZ_?]+)"
                 r"|(?<![\w'$`.])(\d[\d_]*)(?![\w.'])")
CLK_NAME = re.compile(r"\bCLK_(?:MD_)?HZ\b")


def strip_comments(s):
    """Blank out comments and string literals, keeping line numbers."""
    out = []
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if s.startswith("//", i):
            j = s.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i)); i = j
        elif s.startswith("/*", i):
            j = s.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(re.sub(r"[^\n]", " ", s[i:j])); i = j
        elif c == '"':
            j = i + 1
            while j < n and s[j] != '"' and s[j] != "\n":
                j += 2 if s[j] == "\\" else 1
            j = min(j + 1, n)
            out.append('"' + " " * (j - i - 2) + '"' if j - i >= 2 else s[i:j]); i = j
        else:
            out.append(c); i += 1
    return "".join(out)


def literals(line):
    """(value, base, text) for every integer literal on a comment-free line."""
    for m in NUM.finditer(line):
        if m.group(4) is not None:
            yield int(m.group(4).replace("_", "")), "d", m.group(0)
        else:
            b = m.group(2).lower()
            d = m.group(3).replace("_", "")
            if re.search(r"[xXzZ?]", d):
                continue
            try:
                v = int(d, {"d": 10, "h": 16, "b": 2, "o": 8}[b])
            except ValueError:
                continue
            yield v, b, m.group(0)


def load_tree(root, cfg):
    files = {}
    for pat in cfg["scope"]:
        for p in sorted(glob.glob(os.path.join(root, pat), recursive=True)):
            rel = os.path.relpath(p, root).replace("\\", "/")
            files[rel] = open(p, encoding="utf-8", errors="replace").read()
    return files


def check(files, cfg, quiet=False):
    errors, warns = [], []
    clocks = [v for vs in cfg["clocks"].values() for v in vs]
    src = cfg["source"]
    allow, whole = {}, {}
    for e in cfg["allow"]:
        if e["value"] == "*":
            whole[e["file"]] = e                      # a data table: R3 skips the file, R2 still applies
        else:
            allow[(e["file"], e["value"])] = e
    seen = {}
    clean = {f: strip_comments(t) for f, t in files.items()}

    for f, text in clean.items():
        for ln, line in enumerate(text.split("\n"), 1):
            # R1
            if re.search(r"`CLK_FREQ\b|`define\s+CLK_FREQ\b", line):
                errors.append(f"R1 {f}:{ln}: `CLK_FREQ is retired; use the CLK_HZ parameter")
            is_source = f == src["file"] and re.search(r"\blocalparam\b.*\bCLK_HZ\s*=", line)
            names_clock = bool(CLK_NAME.search(line))
            for v, b, txt in literals(line):
                # R2
                if not is_source and any(abs(v - c) <= c * 0.005 for c in clocks)                         and not allow.get((f, v), {}).get("clock_value"):
                    errors.append(f"R2 {f}:{ln}: '{txt}' = {v} is a clock value; derive it from CLK_HZ / CLK_MD_HZ")
                    continue
                # R3
                if b == "d" and v >= 1000 and not is_source and not names_clock and f not in whole:
                    seen[(f, v)] = seen.get((f, v), []) + [ln]

    for (f, v), lines in sorted(seen.items()):
        e = allow.get((f, v))
        where = f"{f}:{','.join(map(str, lines))}"
        if e is None:
            errors.append(f"R3 {where}: literal {v} is not derived from CLK_HZ / CLK_MD_HZ and not on the allow-list")
        elif e.get("count", len(lines)) != len(lines):
            errors.append(f"R3 {where}: literal {v} appears {len(lines)} times, the allow-list says {e['count']} "
                          f"({e['kind']}: {e['why']})")
    for (f, v), e in sorted(allow.items()):
        if (f, v) not in seen and not e.get("clock_value"):
            warns.append(f"stale allow-list entry: {f} {v} ({e['kind']}) is no longer there")
    for f, e in sorted(whole.items()):
        if f not in files:
            warns.append(f"stale allow-list entry: {f} (whole file, {e['kind']}) is not in scope")

    # R4
    pmods = {}
    for f, text in clean.items():
        for m in re.finditer(r"\bmodule\s+(\w+)\s*(#\s*\((.*?)\)\s*)?\(", text, re.S):
            params = m.group(3) or ""
            for pm in re.finditer(r"\bparameter\b[^;,)]*?\b(CLK_(?:MD_)?HZ)\s*=\s*([^,)\n]+)", params):
                pmods.setdefault(m.group(1), []).append(pm.group(1))
                if pm.group(2).strip() != "0":
                    errors.append(f"R4 {f}: module {m.group(1)} parameter {pm.group(1)} defaults to "
                                  f"'{pm.group(2).strip()}'; the default must be 0 (unset)")
    for f, text in clean.items():
        for mod, names in pmods.items():
            for m in re.finditer(r"(?<![\w.$])" + mod + r"\b\s*(#\s*\((?:[^()]|\([^()]*\))*\))?\s*(\w+)\s*\(", text):
                if m.group(2) in ("if", "for", "begin"):
                    continue
                if re.search(r"\bmodule\s+$", text[max(0, m.start() - 40):m.start()]):
                    continue                                    # the declaration, not an instance
                hdr = m.group(1) or ""
                ln = text.count("\n", 0, m.start()) + 1
                for nm in names:
                    if not re.search(r"\." + nm + r"\s*\(", hdr):
                        errors.append(f"R4 {f}:{ln}: instance {m.group(2)} of {mod} does not set {nm}")

    for p in cfg.get("pending", []):
        t = files.get(p["file"], "")
        if re.search(p["pattern"], strip_comments(t)):
            warns.append(f"pending ({p['owner']}): {p['file']}: '{p['pattern']}' - {p['why']}")

    if not quiet:
        for w in warns:
            print("WARN", w)
        for e in errors:
            print("FAIL", e)
        print(f"clkcheck: {len(files)} files, {len(errors)} errors, {len(warns)} warnings")
    return errors


PLANTS = [
    ("NEORV32 generic as a literal", "rtl/PAPRIUM/mcu_core.sv",
     r"\.CLOCK_FREQUENCY\(CLK_HZ\)", ".CLOCK_FREQUENCY(53693175)"),
    ("album compare back to 11'd1118", "rtl/PAPRIUM/paprium_cdda_play.sv",
     r"sample_div >= SAMPLE_CMP", "sample_div >= 11'd1118"),
    ("album mute back to 22'd2685000", "rtl/PAPRIUM/paprium_cdda_play.sv",
     r"mute_ctr <= MUTE_CLKS", "mute_ctr <= 22'd2685000"),
    ("mcd_link divisor as a literal", "rtl/PAPRIUM/paprium_mcd_link.sv",
     r"DIV = DIV_I\[21:0\];", "DIV = 22'd2147727;"),
    ("ms counter on a hex clock literal", "rtl/PAPRIUM/fpgio.sv",     # a stage-1 change retired the ms counter itself
     r"\Z", "\nmodule planted_hex(input clk, output reg t); reg [31:0] c; always @(posedge clk) "
            "if (c == 32'h3334AF7 / 1000 - 1) t <= 1; endmodule\n"),
    ("`CLK_FREQ reintroduced", "rtl/PAPRIUM/paprium_cart.sv",
     r"\.ck_base\(CLK_HZ\)", ".ck_base(`CLK_FREQ)"),
    ("mcd_link instance without CLK_MD_HZ", "target/pocket/core_top.sv",
     r"paprium_mcd_link #\(\.CLK_MD_HZ\(CLK_MD_HZ\)\) mcd_link", "paprium_mcd_link mcd_link"),
    ("cartridge instance without CLK_HZ", "target/pocket/core_top.sv",
     r",\r?\n      \.CLK_HZ\(CLK_HZ\)", ""),
    ("a second 48000 in paprium_cart", "rtl/PAPRIUM/paprium_cart.sv",
     r"\.rate\(16'd48000\),", ".rate(16'd48000), .rate2(16'd48000),"),
    ("a module default set to the clock", "rtl/PAPRIUM/paprium_cdda_play.sv",
     r"parameter integer CLK_HZ = 0,", "parameter integer CLK_HZ = 53_693_175,"),
    ("a new unlisted 1 ms count", "rtl/PAPRIUM/audio_sfx.sv",
     r"\Z", "\nmodule planted_ms(input clk, output reg t); reg [15:0] c; always @(posedge clk) "
            "if (c == 16'd53693) t <= 1; endmodule\n"),
    # stage 1's merge: the clk_md seam core_top -> cartridge -> sdram (the SDRAM refresh compare)
    ("cartridge instance without CLK_MD_HZ", "target/pocket/core_top.sv",
     r",\r?\n      \.CLK_MD_HZ\(CLK_MD_HZ\)", ""),
    ("sdram instance without CLK_MD_HZ", "rtl/cartridge.sv",
     r"sdram #\(\.CLK_MD_HZ\(CLK_MD_HZ\)\) sdram", "sdram sdram"),
    ("sdram default back to the NTSC clock", "rtl/sdram.sv",
     r"parameter integer CLK_MD_HZ = 0\)", "parameter CLK_MD_HZ = 107_386_350)"),
]


def selftest(files, cfg):
    ok = True
    base = check(files, cfg, quiet=True)
    print(f"clean tree: {len(base)} errors" + ("" if not base else " (selftest needs a clean tree)"))
    ok &= not base
    for name, f, pat, rep in PLANTS:
        if f not in files or not re.search(pat, files[f]):
            print(f"  plant '{name}': anchor not found in {f} - SKIPPED (counts as a failure)")
            ok = False
            continue
        t = dict(files)
        t[f] = re.sub(pat, lambda _m: rep, files[f], count=1)
        errs = check(t, cfg, quiet=True)
        caught = len(errs) > 0
        ok &= caught
        print(f"  plant '{name}' ({f}): {'caught' if caught else 'MISSED'}"
              + (f" - {errs[0]}" if caught else ""))
    print("clkcheck selftest", "PASS" if ok else "FAIL")
    return ok


def main():
    ap = argparse.ArgumentParser(description="one clock value, no clock literals")
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--config", default=os.path.join(HERE, "clkcheck.json"))
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    cfg = json.load(open(a.config, encoding="utf-8"))
    files = load_tree(a.root, cfg)
    if a.selftest:
        return 0 if selftest(files, cfg) else 1
    return 1 if check(files, cfg) else 0


if __name__ == "__main__":
    sys.exit(main())
