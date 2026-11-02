#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""run_all.py - build everything and run every skeleton check, in order; one PASS/FAIL line per step.

    python -I -B tests/run_all.py [--s1-replay] [--s1-rigs | --s1-rigs-only] [--scrub DIR]

Words used below. The stage-1 build (FW_S1, `tools/fwbuild.py s1`) is our new firmware's own start-up, scheduler and
board layer; the stage-5 images s5test / s5release (FW_S5) add our own song engine and synth; stages are the steps of
the 0.3.0 work (docs/ALLOWLIST.md lists them). A rig is a test program that replays recorded game sessions (captures)
into firmware builds, or into a build and our model of the cart's chip; a slice is a short replay this run passes or
fails on; a lockstep runs two sides event by event and compares them after every event. FZ1-FZ14, DEC and GO are the
fuzz rigs' named checks; L1 / L2 are the scheduler's levels (core/sched/sched.h); B34, B49 ... are allow-list rows
(docs/ALLOWLIST.md). Test builds 4, 4a, 4b, 5 and S3a / S3b are the firmware builds B Jam tested on his hardware.

Steps: check_tree (static guards; rule 5: the stage-1 source set reaches no 0.2.6 register and types no clock, checked
preprocessed as built) + its 7 planted stage-1 cases (5 mistakes, 2 controls) -> check_board (the board interface v1.2
== MCU interface v1.3's v1.2 lines; the page's v1.3 tables == its own Appendix A v1.3 lines) + its 17 negative
controls and the v1.3-header positive control
-> check_clock (test T23, docs/BOARD_IFACE.md section 6: the one build-time clock and its figures at both clocks) +
   its 5
   negative controls
-> fwbuild all (pocket legacy54k + pocket72k x test/release, host x test/release, stubs, s1 (the stage-1
host tests and RV32 checks); every Pocket build also runs the stack-bound and size-budget checks and fails when over)
-> check_images m1
(milestone 1: legacy54k == the shipped final 0.2.6 images) -> check_images layout pocket72k (milestone 2 invariants)
-> check_stack_su (fwstack's frames == GCC -fstack-usage) -> check_tools (the static checks fail when they must)
-> check_fwstack_exact (the stack check's address-taken rule and jump reading on a small program at three code bases)
-> the stage-1 image checks (check_images s1; fuzz_sched: crt0's interface checks, the scheduler under random
   interrupts with FZ5/FZ7/FZ8/FZ9/FZ11, and its 5 planted-bug negative controls; ~45 s)
-> check_fafrium (the Fafrium file, docs/FAFRIUM.md: the boot stub and tools/mkfafrium.py name the same format, the stub
   builds and fits its room, a file made from build/s1/pocket88k/s5release equals its images, 26 planted faults refused;
   the file in memory order is the images, and the leak guard on it finds nothing at all outside the allowed places,
   with 5 planted controls each caught at its place)
-> the stage-5 scheduler path (FW_S5: the ordered engine queue and the L1 / L2 split; tests/equiv/
   fuzz_sched_s5.py on the s5probe image under MCU interface v1.3's ARR / DONE / synth model: FZ5 / FZ7 / FZ8 / FZ9 /
   FZ11, then its 10 planted bugs each failing its check (two in their own scenarios: long brain calls, A + B pair
   storms), the urgent finish's positive control and the clean probe in both scenarios; ~1.5 min)
-> host_smoke (needs the audit harness, our test harness outside this tree: PAPRIUM_HARNESS_DIR or paths.local.json
   "harness_dir"; skipped otherwise)
-> leakguard (no chip / ROM / sub-CPU / brain values typed in as numbers, sources and built sections; allow-list =
   the two decided tables) + check_leakguard (its positive controls and the allow-list rule) (need paths.local.json
   "refs" and "brain_dir"; ~11 s)
-> the replay slice, decided on the rigs' exit codes (tests/equiv/slice.py; paths.local.json "equiv"; ~1 min): the host
   build == the final 0.2.6 reference digests (TEST, RELEASE), the pocket72k RV32 images == the host build, and three
   negative controls in which the rigs must exit 1
-> with --s1-replay: the stage-1 replay slice (tests/equiv/s1_slice.py; needs "equiv" ref_host test + release;
   ~2.5 min): the stage-1 host build (the dispatcher that works as the chip's + re-hosted 0.2.6 bodies) == the final
   0.2.6 host build post by post, TEST and RELEASE, and two planted differences that must fail. Opt-in because the
   default run is already close to 10 minutes (451-588 s, measured 2026-10-11); run it alone with
   python -I -B tests/equiv/s1_slice.py
-> with --s1-rigs (~4-5 min, so opt-in; --s1-rigs-only runs these steps alone, on the build already made):
   the stage-1 board mode (tests/equiv/s1_rv_slice.py: rvboard.py --mode s1, the RV32 TEST / RELEASE images on the
   stage-1 board model == the stage-1 host build post by post, solo frames 0-3,000, and 2 negative controls), the
   interrupt-race fuzz on the full images (tests/equiv/fuzz_s1.py: FZ1-FZ14, the GO check and DEC (the RTL
   decoder in the board model: no window word read before its block is decoded), TEST with the FZ10 watchdog scenario,
   RELEASE), FZ12 (the L1 budget), FZ13 (no job waits for a brain call), FZ14 (the call never masks the wheel) and DEC
   again over frames 0-3,000 (intro and play) on both images, its 11 planted-bug images and the slow-decoder control
   images each failing with its invariant, and the stage-1 battery-save checks of B Jam's question Q1 on RV32
   (fuzz_s1.py --q1); the TEST debug save's version 6 (2026-10-19): its CPU MATE late counter against the Mega CD stub
   model and its album recorder
   (tests/equiv/tdiag_s1.py, TEST, seeds 3, 5, 7 and 11, the whole run to the quit; its negative control test_bug_late
   and the fix's two planted faults, test_bug_disc and test_bug_tick, each caught by its own checks); the lost wake-up
   (2026-10-18) planted (tests/equiv/race_s1.py: the next DA02 at every boundary of R1's window and the control, TEST
   and RELEASE: the job runs at each; the images without the fix lose it: 2 negative controls), and the same on the
   stage-5 images (s5test / s5release on the v1.3 board, 2 more negative controls); the C6 hold
   (tests/equiv/c6count.py, allow-list row B34: the game's boot count byte = 94 on the TEST and RELEASE images at 8
   C600 phases; its 2 planted bugs must fail); the boot cache of test build 4b (tests/equiv/cache4b.py: the TEST and
   RELEASE images boot by boot on test build 4a's board model, MCU interface v1.3: the whole bank unpacked by the image
   = the chip's, the file kept / rejected / unpacked again, the warm, mid-unpack and mid-SFX-copy resets;
   its 13 planted bugs each caught by its own check; ~5 + ~25 min); since test build 5: the C6 hold on the stage-5
   images too (c6count on s5test / s5release, the 8 phases: C6's own set-up, the chip's audio init and the module
   pre-decode, inside the hold), and the boot cache on them (cache4b on s5test / s5release, test build 5's board model:
   the same cases plus the synth's output curve = the chip's, before CACHE, the version-10 record, crt0 refusing test
   build 4a's board; its 3 planted bugs) and the TEST debug save's version 10 (from test build S3a on: the lateness
   signs, the freeze telemetry and the CPU MATE counters only; tests/equiv/dbgsave10.py, ~2 min); stage 3 (test build
   S3a): the zoom against the cart chip's routines (tests/equiv/zoomlock.py: the s5release, s5test and stage-1 TEST
   images on random cases and the solo capture's F4 / F5 / B6 posts, then its 4 planted bugs; needs "harness_dir";
   ~6 min); with paths.local.json "equiv"."chip_runner" also the chip lockstep slice (tests/equiv/chiplock_slice.py,
   ~2 min; since the sprite-values update with the AF unit and the sprite values' four planted bugs, since test build 4
   seven (D23: the attribute word compared, ~9 min); the full corpora are run as tests/equiv/README.md says)
-> stage 3 (the MegaWire port, test build S3b), with paths.local.json "equiv"."chip_runner": tests/equiv/mw_oracle.py
   (the port == the cart's chip with no module, tick by tick and post by post, ~4,070 ticks; build/s1/host/mw_host),
   its three planted-bug harnesses (mw_host_bug1..3, each must differ) and the two plants of allow-list row B49's mask
   (--plan sweep --plant 1 / 2, each must differ); with --s1-rigs: tests/equiv/mwboot.py on the s5test and
   s5release images (the SRAM image check's 13 cases after the 68000's release, the lock, the port running from SRAM,
   the C6 count byte 94 with it at the 8 phases, MegaWire On = Off, $1B20 and the post gates == the chip's, the A858
   screen's hold and release at the chip's waits) and its 4 planted faults
-> with --scrub DIR: the scrub proof into DIR, a tool we keep private (it is not in this tree).
A step whose inputs are not configured prints SKIP. Exit status 1 if any step fails."""
import argparse, json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = [sys.executable, '-I', '-B']
ap = argparse.ArgumentParser()
ap.add_argument('--scrub', metavar='DIR', help='also run the scrub proof into DIR (outside the tree)')
ap.add_argument('--s1-replay', action='store_true', help='also run the stage-1 replay slice (tests/equiv/s1_slice.py)')
ap.add_argument('--s1-rigs', action='store_true', help='also run the stage-1 RV32 rigs of item W12 (board mode, fuzz, Q1)')
ap.add_argument('--s1-rigs-only', action='store_true', help='run only the stage-1 RV32 rigs (on the build already made)')
a = ap.parse_args()
loc = json.load(open(os.path.join(ROOT, 'paths.local.json'))) if os.path.exists(os.path.join(ROOT, 'paths.local.json')) else {}
harness = os.environ.get('PAPRIUM_HARNESS_DIR') or loc.get('harness_dir')
steps = [('tree guards', PY + [os.path.join(HERE, 'check_tree.py')]),
         ('card 5: the boot overlay\'s packed output curve == its generator, and its rebuild == the chip\'s curve formula '
          '(gen_c5_curve --check)', PY + [os.path.join(ROOT, 'board', 'pocket', 'boot', 'gen_c5_curve.py'), '--check']),
         ('check_tree rule 5 catches 5 planted stage-1 mistakes, passes 2 controls (negative controls)',
          PY + [os.path.join(HERE, 'check_tree.py'), '--selftest']),
         ('board header v1.3 == MCU interface v1.3 Appendix A (card 4a); the v1.3 tables == its Appendix A (check_board)',
          PY + [os.path.join(HERE, 'check_board.py')]),
         ('check_board catches 17 planted mistakes, passes a v1.3 header and fails it with a line dropped, passes the '
          'header as a v1.2 header (controls)',
          PY + [os.path.join(HERE, 'check_board.py'), '--selftest']),
         ('T23 one clock: figures and stage-1 images follow it at 53.693175 / 53.203424 MHz (check_clock --images)',
          PY + [os.path.join(HERE, 'check_clock.py'), '--images']),
         ('check_clock catches 5 planted mistakes (negative controls)', PY + [os.path.join(HERE, 'check_clock.py'), '--selftest']),
         ('build all (incl. stack bound + size budget per Pocket build)', PY + [os.path.join(ROOT, 'tools', 'fwbuild.py'), 'all']),
         ('milestone 1 (legacy54k == final 0.2.6)', PY + [os.path.join(HERE, 'check_images.py'), 'm1']),
         ('milestone 2 (pocket72k invariants)', PY + [os.path.join(HERE, 'check_images.py'), 'layout', '--layout', 'pocket72k']),
         ('stack frames == GCC -fstack-usage (pocket72k test)', PY + [os.path.join(HERE, 'check_stack_su.py')]),
         ('stack frames == GCC -fstack-usage (pocket72k release)', PY + [os.path.join(HERE, 'check_stack_su.py'), '--variant', 'release']),
         ('static checks fail when over (negative tests)', PY + [os.path.join(HERE, 'check_tools.py')]),
         ('stack check: only addresses the code builds count as taken, jumps read from the walk (a small program at the '
          'IROM, SRAM and WRAM-window bases: 3 real pointers caught, a start used as integers not, the objdump-note '
          'switch read from its table; check_fwstack_exact)', PY + [os.path.join(HERE, 'check_fwstack_exact.py')]),
         ('stage-1 images: fixed bytes kept, own crt0 and trap entry (check_images s1)', PY + [os.path.join(HERE, 'check_images.py'), 's1']),
         ('Fafrium: the stub and mkfafrium.py name the same format, the stub fits, a file of the s5release images = them '
          'byte for byte, 26 planted faults refused, the memory-order leak check (no hit outside the allowed places) with '
          'its 5 planted controls (check_fafrium)',
          PY + [os.path.join(HERE, 'check_fafrium.py')]),
         ('stage-1 crt0 interface checks on RV32: SYSINFO clock, USER_CODE (fuzz_sched --boot-checks)',
          PY + [os.path.join(HERE, 'equiv', 'fuzz_sched.py'), '--boot-checks']),
         ('stage-1 scheduler on RV32 with random interrupts: FZ5 FZ7 FZ8 FZ9 FZ11, 8 seeds (fuzz_sched)',
          PY + [os.path.join(HERE, 'equiv', 'fuzz_sched.py'), '--seeds', '8', '--cycles', '1500000']),
         ('fuzz_sched catches 5 planted scheduler bugs (negative controls)',
          PY + [os.path.join(HERE, 'equiv', 'fuzz_sched.py'), '--negative', '--seeds', '6', '--cycles', '1500000']),
         ('stage-5 scheduler path (F1: the ordered engine queue, the L1 / L2 split) on RV32 with random interrupts, MCU '
          'interface v1.3: FZ5 FZ7 FZ8 FZ9 FZ11, 8 seeds (fuzz_sched_s5)',
          PY + [os.path.join(HERE, 'equiv', 'fuzz_sched_s5.py'), '--seeds', '8', '--cycles', '1500000']),
         ('fuzz_sched_s5 catches 10 planted queue / scheduler bugs, the urgent positive control and the clean probe in all three '
          'scenarios pass (negative controls)',
          PY + [os.path.join(HERE, 'equiv', 'fuzz_sched_s5.py'), '--negative', '--seeds', '6', '--cycles', '1500000'])]
if harness:
    steps.append(('host smoke (audit harness driver)', PY + [os.path.join(HERE, 'host_smoke.py'), '--harness', harness]))
leak_refs = bool(loc.get('refs')) and bool(os.environ.get('PAPRIUM_BRAIN_DIR') or loc.get('brain_dir'))
if leak_refs:
    steps.append(('numeric leak guard: no chip/ROM/sub-CPU/brain values as numbers (sources + built sections, the '
                  'stage-5 pocket88k images included)',
                  PY + [os.path.join(ROOT, 'tools', 'leakguard.py')]))
    steps.append(('leak guard catches planted chip values; allow-list exact (positive controls)',
                  PY + [os.path.join(HERE, 'check_leakguard.py')]))
chip_runner = (loc.get('equiv') or {}).get('chip_runner')
EXE = '.exe' if os.name == 'nt' else ''
if chip_runner:
    mo = PY + [os.path.join(HERE, 'equiv', 'mw_oracle.py')]
    hb = os.path.join(ROOT, 'build', 's1', 'host')
    steps.append(('stage 3 (card S3b): the MegaWire port == the cart\'s chip with no module, tick by tick and post by '
                  'post (~4,070 ticks: the A4 posts, the attract-mode A9 + E7 and the 46 s give-up, an E7 inside state 3, '
                  'A6, the error packets, game packets of 1-251 bytes, a stale request tail and the MegaWire menu\'s 0x82 / '
                  '0x84 packets to their give-ups; the allow-list B49 / B50 / B51 '
                  'masks counted, B49 at the chip\'s own request length) (mw_oracle)', mo))
    for k, what in ((1, 'the give-up one tick early'), (2, 'E7\'s length bytes not swapped'),
                    (3, 'A9 leaves $1FE6 bit 4 set')):
        steps.append(('mw_oracle catches the planted MegaWire bug %d, %s (negative control)' % (k, what),
                      mo + ['--host', os.path.join(hb, 'mw_host_bug%d%s' % (k, EXE)), '--expect-fail']))
    for k, what in ((1, 'a chip byte just past the B49 request mask'), (2, 'our byte inside the B49 request mask')):
        steps.append(('mw_oracle sees %s (the mask\'s own negative control, the length sweep)' % what,
                      mo + ['--plan', 'sweep', '--plant', str(k), '--expect-fail']))
if loc.get('harness_dir') and os.path.isdir(loc.get('harness_dir')):
    ms = PY + [os.path.join(HERE, 'equiv', 'mw_screen.py'), '--host',
               os.path.join(ROOT, 'build', 's1', 'host', 'mw_host' + EXE)]
    steps.append(('stage 3 (card S3b): the A858 MegaWire screen == the cart\'s chip with no module (the $1FE4 stores and '
                  'the 68000 hold, the park word, the music stop, the state walk, the pages, the lines and the access '
                  'point after 3 s) (mw_screen)', ms))
    for k, what in ((1, 'page A one byte off'), (2, 'the 68000 released 10 ms late')):
        steps.append(('mw_screen catches %s (negative control)' % what, ms + ['--plant', str(k), '--expect-fail']))
steps.append(('stage 3 (card S3b): core/mw/mw_page_a.c is what tools/mkpagea.py builds',
              PY + [os.path.join(ROOT, 'tools', 'mkpagea.py'), '--check']))
if (loc.get('equiv') or {}).get('rom'):
    steps.append(('stage 3 (card S3b): page A of the A858 screen on a 68000 with a MODELLED VDP draws the cart screen\'s '
                  'layout (H40, the lines at rows 2-3 from column 4, the ROM font and palette, the black, the palette '
                  'line) (mw_pagea)', PY + [os.path.join(HERE, 'equiv', 'mw_pagea.py')]))
equiv = loc.get('equiv')
if equiv:
    sl = PY + [os.path.join(HERE, 'equiv', 'slice.py'), '--part']
    steps.append(('replay slice: host TEST/RELEASE == final 0.2.6 digests (solo frames 0-3,000)', sl + ['host']))
    steps.append(('replay slice: pocket72k RV32 images == host build (solo frames 0-3,000)', sl + ['rv32']))
    steps.append(('replay rigs exit 1 on a difference (3 negative controls)', sl + ['neg']))
    if a.s1_replay:
        steps.append(('stage-1 replay: s1 host TEST/RELEASE == final 0.2.6 host per post (solo frames 0-3,000), '
                      '2 planted differences caught (s1_slice)', PY + [os.path.join(HERE, 'equiv', 's1_slice.py')]))
rigs = []
if (a.s1_rigs or a.s1_rigs_only) and equiv:
    fz = PY + [os.path.join(HERE, 'equiv', 'fuzz_s1.py')]
    s1b = os.path.join(ROOT, 'build', 's1', 'pocket72k')
    rigs = [('stage-1 board mode: RV32 TEST / RELEASE == the stage-1 host per post (solo frames 0-3,000), 2 negative controls '
             '(s1_rv_slice)', PY + [os.path.join(HERE, 'equiv', 's1_rv_slice.py')]),
            ('stage-1 fuzz, TEST image: FZ1-FZ14 + the GO check + DEC, 4 seeds x frames 0-500, the FZ10 watchdog scenario (fuzz_s1)',
             fz + ['--build', os.path.join(s1b, 'test'), '--seeds', '4', '--wdog']),
            ('stage-1 fuzz, RELEASE image: 4 seeds x frames 0-500 (fuzz_s1)', fz + ['--build', os.path.join(s1b, 'release'), '--seeds', '4']),
            ('stage-1 L1 budget, the brain call below the game\'s work, the RTL decoder never read early, TEST image: 1 seed x frames 0-3,000, the intro and play sprite frames (fuzz_s1 FZ12, FZ13, FZ14, DEC)',
             fz + ['--build', os.path.join(s1b, 'test'), '--seeds', '1', '--frames', '3000']),
            ('stage-1 L1 budget, the brain call below the game\'s work, the RTL decoder never read early, RELEASE image: 1 seed x frames 0-3,000 (fuzz_s1 FZ12, FZ13, FZ14, DEC)',
             fz + ['--build', os.path.join(s1b, 'release'), '--seeds', '1', '--frames', '3000']),
            ('fuzz_s1 catches 11 planted bugs and a 40x slower decoder, each with its invariant (negative controls)',
             fz + ['--build', os.path.join(s1b, 'test'), '--negative', '--seeds', '3']),
            ('stage-1 Q1 on RV32: a 0.2.x 4 KB save loads unchanged, a fatal halt reaches the .sav, Soft Resets keep it, the SAT snapshot keeps the crowded frame (fuzz_s1 --q1)',
             fz + ['--build', os.path.join(s1b, 'test'), '--q1']),
            ('stage-1td on RV32, TEST image, seeds 3 / 5 / 7 / 11: the CPU MATE late count == the Mega CD stub model\'s '
             'own late ARMs, each counted once, the largest lateness == the largest readable == the true largest unless '
             'that answer was unreadable (after the replay and over the whole run to the quit), the 2026-10-19 fix\'s two races '
             'placed on purpose (section F), the short-path calls, the album\'s result word, CDDA counters, last play '
             'request and wait in the debug save and across a quit (tdiag_s1)',
             PY + [os.path.join(HERE, 'equiv', 'tdiag_s1.py'), '--build', os.path.join(s1b, 'test')]),
            ('tdiag_s1 negative control: the image without the LATE flag clear before each ARM (test_bug_late) counts '
             'more than the stub model\'s late ARMs',
             PY + [os.path.join(HERE, 'equiv', 'tdiag_s1.py'), '--build', os.path.join(s1b, 'test'), '--negative', 'late']),
            ('tdiag_s1 planted (the 2026-10-19 fix): a late ARM overtaken by the game\'s next post before its publish read not counted '
             '(test_bug_disc) falls short of the stub model\'s late ARMs (F1, else J2 / W1), every other check passing',
             PY + [os.path.join(HERE, 'equiv', 'tdiag_s1.py'), '--build', os.path.join(s1b, 'test'), '--negative', 'disc']),
            ('tdiag_s1 planted (the 2026-10-19 fix): late_max from a TICK read after a newer post (test_bug_tick) differs from the true '
             'largest lateness (F2, else J3 / W2), every other check passing',
             PY + [os.path.join(HERE, 'equiv', 'tdiag_s1.py'), '--build', os.path.join(s1b, 'test'), '--negative', 'tick'])]
    rc = PY + [os.path.join(HERE, 'equiv', 'race_s1.py')]
    rigs += [('stage-1 lost wake-up R1 (s1-t4c) planted on RV32, TEST image: the next DA02 at every boundary of the window '
              'and at the control: the job runs at each (race_s1)', rc + ['--build', os.path.join(s1b, 'test')]),
             ('stage-1 lost wake-up R1 planted on RV32, RELEASE image: the same (race_s1)', rc + ['--build', os.path.join(s1b, 'release')]),
             ('race_s1 negative control, TEST: the image without the fix (test_bug_r1) loses the planted job at both ends of '
              'the window', rc + ['--build', os.path.join(s1b, 'test'), '--negative']),
             ('race_s1 negative control, RELEASE (release_bug_r1)', rc + ['--build', os.path.join(s1b, 'release'), '--negative'])]
    s5b = os.path.join(ROOT, 'build', 's1', 'pocket88k')
    rigs += [('stage-5 lost wake-up R1 planted on RV32, s5test image (F1: the L2b engine items ahead of the L2c pass, the '
              'v1.3 board): the job runs at every boundary and the control (race_s1)', rc + ['--build', os.path.join(s5b, 's5test')]),
             ('stage-5 lost wake-up R1 planted on RV32, s5release image: the same (race_s1)', rc + ['--build', os.path.join(s5b, 's5release')]),
             ('race_s1 negative control, s5test (s5test_bug_r1) loses the planted job at both ends of the window',
              rc + ['--build', os.path.join(s5b, 's5test'), '--negative']),
             ('race_s1 negative control, s5release (s5release_bug_r1)', rc + ['--build', os.path.join(s5b, 's5release'), '--negative'])]
    c6 = PY + [os.path.join(HERE, 'equiv', 'c6count.py')]
    c6ph = []
    # 895350 (since 2026-10-18; was 895300): the game's first read
    # 72 MCLK after a VBlank start, inside it before its VS start.
    # The case check samples VSCNT once a loop pass (~42 model cycles), so a first read within one pass of a VBlank
    # start can go either way with the job's start alignment (c6count's own rule: "a boundary, not a test"): 895300's
    # 22 MCLK lies in that band (measured with a phase sweep: count 93 at first reads 2-12 MCLK past the edge on
    # the TEST image before the lost wake-up fix of 2026-10-18, 2-42 on the TEST image with that fix, 2 on both
    # RELEASE images; 94 at every
    # other phase of 82)
    for ph in ('capture', '1', '20000', '36850', '37000', '600000', '895350', '895450'):
        c6ph += ['--phase', ph]
    rigs += [("stage-1 C6 hold on RV32, TEST image: the game's boot count byte = 94 (the cart's) at the corpus's C600 phase and 7 "
              'more, first reads inside a VBlank before its VS start and on both sides of both edges (c6count, B34)', c6 + ['--build', os.path.join(s1b, 'test')] + c6ph),
             ('stage-1 C6 hold on RV32, RELEASE image: the same 8 phases (c6count)', c6 + ['--build', os.path.join(s1b, 'release')] + c6ph),
             ('c6count catches 2 planted bugs: no hold, no case check (negative controls)',
              c6 + ['--build', os.path.join(s1b, 'test'), '--negative']),
             ("stage-5 C6 hold on RV32, s5test image (test build 5): the boot count byte = 94 at the same 8 "
              'phases, C6\'s own set-up (the chip\'s audio init, the 52 modules pre-decoded) inside the hold (c6count)',
              c6 + ['--build', os.path.join(s5b, 's5test')] + c6ph),
             ('stage-5 C6 hold on RV32, s5release image: the same 8 phases (c6count)',
              c6 + ['--build', os.path.join(s5b, 's5release')] + c6ph)]
    c4 = PY + [os.path.join(HERE, 'equiv', 'cache4b.py'), '--build', os.path.join(s1b, 'test')]
    rigs += [('card 4b boot cache on RV32, TEST and RELEASE images, card-4a board model (MCU interface v1.3): a first boot '
              'unpacks the whole bank with the image\'s own code = the chip\'s bank (md5 6d994df5), the header last, the SFX '
              'bank copied, then CACHE as the last store (event order), the bar lit only for the unpack and off; the '
              'Quit\'s reboot and the MCU-only restart touch nothing; the file is kept; a corrupt bank / tail / directory, '
              'card 4a\'s pattern file, a short file, lost CRAM writes, a broken header, another stream\'s key and an image '
              'the CRAM kept with no file are unpacked again; a reset in the unpack starts it again; a reset in the SFX '
              'copy never boots warm over a half bank; a bad stream fails with no cache and the overlay then counts gone; '
              'the tables == their formulas; each boot\'s record in the debug save (version 8); crt0 refuses card 4\'s '
              'board and wrong FEATs (cache4b)', c4),
             ('cache4b catches 13 planted bugs, each in the check named for it (negative controls)', c4 + ['--negative'])]
    c45 = PY + [os.path.join(HERE, 'equiv', 'cache4b.py'), '--build', os.path.join(s5b, 's5test')]
    rigs += [('card 5 boot cache on RV32, s5test and s5release images, card-5 board model (FEAT CACHE, BAR, SYNTH, GS3, '
              'IROM 88): card 4b\'s cases on the stage-5 images (the bank = the chip\'s, the header, CACHE last, the SFX '
              'bank, the bar lit only for the unpack and dark through a rejected file\'s check) plus the synth\'s output '
              'curve in CRAM = the chip\'s (gen_chip_tables curve_full) on every boot that unpacks or keeps the file, its '
              'stores before CACHE, none on a warm boot; the debug record version 10; crt0 refuses card 4\'s and card '
              '4a\'s boards, a FEAT without SYNTH or CACHE and a 72 KB IROM (cache4b)', c45),
             ('cache4b catches card 5\'s 3 planted bugs (the curve one code off, the curve not written, crt0 taking card '
              '4a\'s FEAT bits), each in the check named for it (negative controls)', c45 + ['--negative']),
             ('card S3a TEST debug save version 10 on RV32, s5test image: only its blocks (the lateness signs, the '
              'freeze telemetry, the CPU MATE counters), the synth\'s TIMEOUTs from a planted DIAG count, the periodic '
              'writes and the heartbeat, PREV / PREV2 carried across a Soft Reset with the chain\'s worst and the '
              'lateness sign, a version-9 record named and not carried, the reader\'s lines (dbgsave10)',
              PY + [os.path.join(HERE, 'equiv', 'dbgsave10.py'), '--build', os.path.join(s5b, 's5test')])]
    if harness:
        zl = PY + [os.path.join(HERE, 'equiv', 'zoomlock.py')]
        rigs += [("stage 3 (card S3a) zoom on RV32, s5release image: the image's own zoom (core/zoom) == the cart chip's "
                  "routines in Unicorn (the audit harness) on 20,000 random cases and on the solo capture's F4 / F5 / B6 posts "
                  "through the chip's mailbox and job queue: the chip's block (stamps, F4 source, save) and RAMDP $0200-$09FF "
                  "byte for byte after every call / post, no access outside the image's memory (zoomlock)",
                  zl + ['--build', os.path.join(s5b, 's5release')]),
                 ('stage 3 zoom on RV32, s5test image: the same (zoomlock)', zl + ['--build', os.path.join(s5b, 's5test')]),
                 ('stage 3 zoom on RV32, the stage-1 TEST image: 5,000 random cases and the solo posts (zoomlock)',
                  zl + ['--build', os.path.join(s1b, 'test'), '--sweep', '5000']),
                 ("zoomlock catches 4 planted bugs (the nibble merge, the stamp walk, the copy-out's clear, a row read past the "
                  'F4 source), each image failing (negative controls)',
                  zl + ['--build', os.path.join(s5b, 's5release'), '--negative'])]
        cs = PY + [os.path.join(HERE, 'equiv', 'c6sprite.py')]
        rigs += [("stage 3 (card S3a) C6's sprite part on RV32, s5test image: after the solo capture's boot to the game's "
                  "C6 exit the anims-per-object table, the block directory and the anim container's 518,174 bytes == the "
                  "cart chip's after C6 (the audit harness), the boot count byte 94 (c6sprite)",
                  cs + ['--build', os.path.join(s5b, 's5test')]),
                 ('stage 3 C6 sprite part on RV32, s5release image: the same (c6sprite)',
                  cs + ['--build', os.path.join(s5b, 's5release')])]
        el = PY + [os.path.join(HERE, 'equiv', 'eeplock.py')]
        rigs += [("stage 3 (card S3a) saves on RV32, s5release image: the image's save jobs in the cart's format == the cart "
                  "chip's read / write jobs (0x0801A734 / 0x0801A86C) in Unicorn (the audit harness, its EEPROM model): the "
                  "validator cases (blank, one copy bad, both bad, sequence order and ties), a run of every id, 300 random "
                  "saves and jobs (the save, the cart RAM and the scratch byte for byte), the slot table read from the ROM, "
                  "the 0.2.x import against the chip's own records and the next boot; the note table's 12-byte tail read "
                  "from the ROM at the boot and note_freq at every pitch to its edge == the chip's (eeplock)",
                  el + ['--build', os.path.join(s5b, 's5release')]),
                 ('stage 3 saves on RV32, s5test image: the same, 100 random jobs (eeplock)',
                  el + ['--build', os.path.join(s5b, 's5test'), '--fuzz', '100']),
                 ('eeplock catches a planted bug (the write takes the newest valid copy), the image differing from the '
                  'chip (negative control)', el + ['--build', os.path.join(s5b, 's5release'), '--negative'])]
        lt = PY + [os.path.join(HERE, 'equiv', 'leveltab.py')]
        rigs += [('stage 3 the level table T built at power-on, s5release image: no table in the image, the image\'s '
                  'chip_level_init and its boot on the board model leave the formula\'s 1,024 bytes (the SHA-256 kept in '
                  'the test), the cart chip\'s own table after its C6 hashes the same (leveltab)',
                  lt + ['--build', os.path.join(s5b, 's5release')]),
                 ('stage 3 the level table T, s5test image: the same (leveltab)', lt + ['--build', os.path.join(s5b, 's5test')]),
                 ('leveltab catches a planted bug (the ceil rounded to nearest), the table\'s hash differing (negative '
                  'control)', lt + ['--build', os.path.join(s5b, 's5release'), '--negative'])]
        fl = PY + [os.path.join(HERE, 'equiv', 'f83lock.py')]
        rigs += [("stage 3 (card S3a) 83's frame-period check on RV32, s5release image: the image's disp_83_check == the cart "
                  "chip's 0x080209B4 in Unicorn (the audit harness) on 195 cases: every n 1-15, periods half a microsecond either "
                  "side of each window end, both targets and outside, 76 past the chip's 24-bit SysTick wrap (f83lock)",
                  fl + ['--build', os.path.join(s5b, 's5release')]),
                 ('stage 3 83 check on RV32, s5test image: the same (f83lock)', fl + ['--build', os.path.join(s5b, 's5test')]),
                 ('f83lock catches 2 planted bugs (the 24-bit wrap left out, window A one microsecond longer), each image '
                  'differing from the chip (negative controls)', fl + ['--build', os.path.join(s5b, 's5release'), '--negative'])]
        gl = PY + [os.path.join(HERE, 'equiv', 'gatelock.py')]
        gt = os.path.join(ROOT, 'docs', 'GATE_TABLES.md')
        rigs += [("stage 3 (card S3a) the mailbox gates on RV32, s5release image: every command index on both mailboxes x "
                  "the argument flag x the low bytes that choose a gate, every argument edge and the forms the game never "
                  "posts, before C6 and after it, == the cart chip (our model of it): register words, events, counters, "
                  "register writes, cart RAM, the zoom block, the save; the chip's answers == docs/GATE_TABLES.md (gatelock)",
                  gl + ['--build', os.path.join(s5b, 's5release'), '--check-table', gt]),
                 ('stage 3 mailbox gates on RV32, s5test image: the same (gatelock)',
                  gl + ['--build', os.path.join(s5b, 's5test'), '--check-table', gt]),
                 ("gatelock catches 2 planted gate bugs (DF's RAM bound one word longer, D608 taken), each image differing "
                  "from the chip at its planted form (negative controls)",
                  gl + ['--build', os.path.join(s5b, 's5release'), '--negative'])]
    mb = PY + [os.path.join(HERE, 'equiv', 'mwboot.py')]
    rigs += [('stage 3 (card S3b): the MegaWire SRAM image on RV32, s5test image, card-5 board model: the image check\'s '
              '13 cases in the thread after the 68000\'s release (valid; no file, bad magic, bad version, another build, '
              'three bad lengths, LOADED short, LOST, hot end wrong, cold part damaged, damaged), the lock, the port '
              'running from SRAM after C6\'s init, the game\'s count byte 94 with it at the 8 C600 phases, the option On = '
              'Off, and (with the chip runner) $1B20, the gates == the chip\'s and the A858 screen\'s hold and release at '
              'the chip\'s waits (mwboot)',
              mb + ['--build', os.path.join(s5b, 's5test'), '--opt-on'] + c6ph),
             ('stage 3: the same on the s5release image (mwboot)', mb + ['--build', os.path.join(s5b, 's5release'), '--opt-on'] + c6ph),
             ('mwboot catches 4 planted faults (the CRC compare forced to pass, the lock lost, the chip\'s $1B20 one byte '
              'off, the A858 screen\'s hold 10 ms late), each in its own check (negative controls)', mb + ['--build', os.path.join(s5b, 's5test'), '--negative'])]
    if loc.get('equiv', {}).get('chip_runner'):
        rigs.append(('chip lockstep (W13): the stage-1 host == the cart program per s1_scope.json and == final 0.2.6, solo '
                     '0-3,700 + the synthetic list, the AF unit and the tail, TEST 0-1,000, every Console word, 11 negative '
                     'controls (chiplock_slice)',
                     PY + [os.path.join(HERE, 'equiv', 'chiplock_slice.py')]))
if a.s1_rigs_only:
    steps = rigs
else:
    steps += rigs
if a.scrub:
    steps.append(('scrub: public copy builds byte-identical images, no leaks', PY + [os.path.join(ROOT, 'tools', 'scrub.py'), a.scrub]))
fails = 0
for name, cmd in steps:
    r = subprocess.run(cmd, capture_output=True, text=True)
    ok = r.returncode == 0
    fails += not ok
    print('%-4s %s' % ('PASS' if ok else 'FAIL', name))
    if not ok:
        print(r.stdout[-3000:], r.stderr[-3000:])
if not harness:
    print('SKIP host smoke (set PAPRIUM_HARNESS_DIR or paths.local.json "harness_dir")')
if not leak_refs:
    print('SKIP numeric leak guard (set paths.local.json "refs" and "brain_dir")')
if not equiv:
    print('SKIP replay slice (set paths.local.json "equiv": capture_solo, rom[, ref_host])')
print('ALL PASS' if not fails else '%d STEP(S) FAILED' % fails)
sys.exit(1 if fails else 0)
