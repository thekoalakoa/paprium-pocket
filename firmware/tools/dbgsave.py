#!/usr/bin/env python3
# Copyright (C) 2026 Marsupial Solutions LLC
# SPDX-License-Identifier: GPL-3.0-or-later
"""dbgsave.py - decode the TEST debug save of the new firmware (board/pocket/dbgsave.h) from a Paprium .sav.

    python -I -B tools/dbgsave.py Paprium.sav [--json OUT] [--logs]

The TEST image copies its counters, boot milestones, freeze telemetry and two logs into save bytes 0x1000-0x1FFF (the
upper half of the 8 KB save; the lower half is the game's, in 0.2.x's layout until the firmware kept the saves in the
cart's own format). It does so once every period of TIM7 (the cart chip's 102 ms timer), once at the boot and at a
fatal halt (then again every ~0.66 s while the halt runs). The .sav holds the save RAM with the two bytes of every
16-bit half swapped (the MCU's byte i is the file's byte i ^ 1, as tools for 0.2.6's snapshot found), so the words are
read back swapped. (The MCU is the cart's NEORV32 soft CPU in the core; the VDP is the Mega Drive's video chip.)
Format: blocks, each a header word (id << 16 | words) and its words; the end block is 0xFFFF << 16. Version 2 adds the
'prev' block: what the boot found in the region before clearing it (the previous session's record, so a Soft Reset after
a freeze or a halt keeps it; the latest fatal halt is carried forward until a newer one replaces it). Version 3 adds the
'vs' block (MCU interface v1.1's VS counter: the VDP's vertical syncs since the boot, the time the count last moved) and
its two words in 'prev'; the freeze line then says which of the 68000 and the VDP were still running at the record's
last write (the MCU was: it wrote the record). Version 4 adds the 'dec' block (MCU interface v1.2, 2026-10-15: the
values of the RTL sprite decoder's slots 18-22 in FPGAIO, the core's register block for the MCU, at the write:
DEC_STAT, DEC_WORDS, DEC_TIME, DEC_MARGIN, DEC_LATECNT); a LATECNT above 0 (a window word served before its block was
decoded) or a flag is reported. Version 5 adds the 'prev2' block. The Pocket's quit restarts the MCU about 0.3 s before
the .sav is read (in two saves from a hardware test on 2026-10-17 the record was a 316.704 ms boot both times), and a
reset clears the decoder's registers and every counter, so 'prev' (a summary) was all that reached the .sav of the
session played. 'prev2' carries the previous session's decoder, CPU MATE, SFX feeder, exception, dispatcher and stack
counters, and their worst over every session chained since (a quit and quick relaunches keep the worst one); a record
before version 5 gets a note that it has none. Versions 1-4 are read too.
Version 6 (2026-10-19): (1) the CPU MATE counter. Version 5's 'late' (glue late_seen) counted every publish while the
stub's sticky LATE flag was up, so it read ~100 % (31,629 of 36,904 calls in a long hardware play test) while the real
rate in the simulations of the core with the firmware was 3-60 %; it is printed with that label and a note, and is no
lateness sign. Version 6 counts each answer armed after the original's instant (expected since the change of
2026-10-15 that runs the brain call in the thread; harmful only if the game reads $A12024 first), the most sub cycles
one came after it, and the short-path calls (D_WORD under 1,000 sub cycles: no CPU MATE partner active); 'the longest
call' is wall time, the game's own work that preempted the call included. (2) The album: the audio block carries the MD+
result word (MD+ is the CD audio adapter the album plays through; the word holds the CDDA fetch's track and whether it
plays), the command word the adapter last took, XLINK's CDDA underruns and ring writes lost (XLINK is the core's
register block for its external memories), the last album call and play request and how long a requested track has
waited with playing 0; 'prev2' carries them across the quit and the longest wait over the chain ('music: track 11
requested 3.2 s before this write, playing = no').
Version 7 (test build 4a, 2026-10-21): the 'cache' block, the TEST image's sound-cache probe
(board/pocket/s1_cache4a.h): each boot's entry (this one's and the previous seven, carried across the Quit's own reboot,
which finds CACHE.VALID set and touches nothing): what the boot found (no file / the file loaded whole and every word
right / a file of another size / CRAM writes lost in the load / words wrong / a warm boot), the words that differed and
the first one, the check and fill times, whether CACHE read back set, the bar's width W (0 = no video while the 68000
was held) and the VDP's vertical syncs during the probe; the audio-call log keeps 128 calls. (CRAM is the Pocket's
cellular RAM chip.)
Version 8 (test build 4b, 2026-10-22): the 'cache' block is the boot cache's record (board/pocket/boot/c4b.h
c4b_rec_t; board/pocket/s1_cache4b.h): this boot's and the previous four, carried across the Quit's reboot: what the
boot found (a warm boot / no file / the file loaded and checked / the file's header, ROM key or bank wrong / a file of
another size / CRAM writes lost / the overlay gone / the ROM not as expected) and did (unpacked, the header written,
CACHE set, the SFX bank copied), the bank's CRC-32 (and whether it is the chip's bank's: CHIP_BANK_CRC), the loaded
header's, the first wrong block, the samples decoded, the decoder's WavPack CRC errors, the ROM key, the check / unpack /
check-after / SFX copy times, the bar's widest W and the VDP's vertical syncs while the 68000 was held.
Version 9 (test build 5, 2026-10-23, the s5 images: the new firmware with the song engine, built with FW_S5;
board/pocket/dbgsave.h): no interim audio (no 'audio' or 'aulog' block; 'interim', the 0.2.6 sprite bodies' counters,
stays). The 'synth' block holds the synth's DIAG totals (DT halves incomplete, instants serviced on the 5 ms TIMEOUT,
MCU writes while a block ran, DT playback reads not served. DIAG, TIMEOUT, CONFIG and DONE are synth registers, and
WBUSY and UNDERRUN are fields of DIAG (docs/MCU_INTERFACE.md section 3.10.1); DT is the Datenmeister mode (CONFIG MODE
1), the music mode with the cart's own DAC), the counts behind its TEST assertions and which of them failed:
  A1: no write but DONE while a block runs, except the stores of the module starts + C6 items (the items with no
      arrival: the 8C's module start, C6's song_c6_init / song_c6_ready). As a count: WBUSY <= the WBUSY the DONE
      stores with no hold-off added (DIAG read around each) + those items' own (a diagnostic, printed apart, never a
      failure);
  A2: UNDERRUN <= the DT starts;
  A3: no TIMEOUT.
It also holds the module starts + C6 items and those a block started during, the queue's deepest, C6's hold record,
the first CONFIG write's time, the synth's registers and the main-loop pass counts. 'prev2' carries, in version 8's
audio words, the previous session's synth TIMEOUTs, failed assertions, WBUSY, the free DONE stores' WBUSY, UNDERRUN,
DT starts and the module starts' + C6 items' WBUSY (and the worst TIMEOUTs and failed assertions over the chain); the
boot cache's entry also says whether the synth's output curve was written (C4B_F_CURVE).
Version 10 (test build S3a, 2026-10-29, the s5 TEST images; board/pocket/dbgsave.h): the record cut to what has caught
problems on hardware, carried across the Quit's reboot as before: the lateness signs (the sprite decoder's late
words and flags, the synth's TIMEOUTs, refusals and failed jobs, exceptions, the stack floor), the freeze telemetry
(the MCU heartbeat, the frame ticks, the last post, the VS count: which side stopped; a fatal halt's record) and the
CPU MATE counters (discarded, aborted, the answers armed late, the longest call); 'prev' and 'prev2' come from a
version-10 record only (another version is named, nothing carried); no milestones, level counters, synth
assertions, boot cache history or logs any more.
After the record (and with no record too) it prints the TEST SAT snapshot (SAT = the sprite attribute table) in save
bytes 0x900-0xFFF (legacy/026/mame.c ppm_snapshot_sat). Layout 2 (from 2026-10-17) holds the session's most crowded
frame with its true count, the latest frame of 20 or more, the session's most and its frame ends over 80, and marks a
torn copy. Layout 1 (0.2.6 TEST and the s1 images before 2026-10-17) holds the last busy frame, its count capped at 80.
Each table is printed with the lines the console would show over 320 px and over 20 sprites (an estimate: the H40
rules, H40 being the 320-pixel mode, applied to the stored table; --json adds it as 'snapshot'). From 2026-10-17 the
AF close is the chip's: a frame of more than 80 entries posted AF02 is stored as the chip's multiplex (entries 14-79
link to k - 13: the console's slots 14-79 hold entries 28-93, its slots 0-13 entries 0-13 above line 48 and 14-27
below); the reader names it and gives no line totals for it (entries 80-93 are not in the save). Exit status:
0 = a record decoded; 1 = no record (a 0.2.x 4 KB save, a RELEASE image, or the size probe turned it off); 2 = a record
of another version or a broken block chain. Stage numbers are the steps of the 0.3.0 work (README.md, "Terms")."""
import argparse, json, struct, sys

OFF, SIZE, MAGIC = 0x1000, 0x1000, 0x42443153
VERSIONS = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10)
STALE_S = 0.15                      # a counter that has not moved for longer than this at a write (a write every
                                    # 0.102 s, a frame every 0.0167 s) has stopped
LEVELS = ['L1 (posts)', 'L2a (wheel)', 'L2b (tick, decoder) + the brain call (thread, stage 1i)', 'decoder + board work', 'jobs (L2c since stage 1i)']
MS = {0x01: 'crt0 done (MCU up)', 0x02: 'interrupts on', 0x03: 'boot page', 0x04: 'interim modules', 0x05: 'app init',
      0x06: '68000 released', 0x07: '68000 released (slow read-back)', 0x08: 'card 4a cache probe done (v7) / card 4b boot cache record (v8, v9)',
      0x10: 'first post', 0x11: 'C6 posted',
      0x12: 'C6 done', 0x13: 'first 9494', 0x14: 'fatal halt'}
NAMES = {
    1: ('head', ['magic', 'version', 'writes', 'now', 'mcycle', 'clk_hz', 'words', 'oracle_built']),
    2: ('boot', ['magic', 'code', 'time', 'value']),
    3: ('stats', None),
    4: ('sched', ['l1', 'l1_empty', 'l2a', 'l2b', 'l3_loops', 'posts_b', 'posts_a', 'sends', 'held', 'held_overflow',
                  'replayed', 'ticks', 'ticks_urgent', 'slices', 'brain_calls', 'wheel_runs', 'exc', 'exc_first_cause',
                  'exc_first_epc', 'exc_first_tval', 'l2b_active']),
    5: ('wdog', ['ticks', 'gated', 'merged', 'arm_max']),
    6: ('fatal', ['code', 'a', 'b', 'time', 'polls']),
    7: ('glue', ['inits', 'events', 'sends', 'deferred', 'calls', 'published', 'discarded', 'aborted', 'abort_landings',
                 'ignored_halted', 'ignored_notready', 'restarts', 'aioffs', 'releases', 'restores_done', 'rearms',
                 'dbusy_fixed', 'late_seen', 'arm_lost', 'exc_brain', 'cycles_last', 'cycles_max',
                 'late', 'late_max', 'short_calls']),                   # (the last three: version 6, TEST)
    8: ('audio', ['ticks', 'catchups', 'pushes', 'first_batches', 'vu_rows',
                  'alb_res', 'alb_xl14', 'alb_xl18', 'alb_calls', 'alb_play_f', 'alb_play_und', 'alb_wait',
                  'alb_wait_max']),                                     # (alb_*: version 6, TEST)
    9: ('disp', None),
    10: ('stack', ['high_water_bytes', 'floor_intact']),
    11: ('interim', ['da_direct', 'go_words_last', 'dec_flushes', 'dec_entries', 'dec_list_max']),
    12: ('aulog', None),
    13: ('oracle', None),
    14: ('prev', ['state', 'writes', 'now', 'mcycle', 'boot_code', 'boot_time', 'heartbeat', 'gated', 'n9494',
                  't_last_9494', 't_last_post', 'last_word', 'exc', 'exc_first_cause', 'exc_first_epc', 'fatal_age',
                  'fatal_code', 'fatal_a', 'fatal_b', 'fatal_time', 'fatal_polls', 'vs_count', 't_last_vs']),
    15: ('vs', ['count', 'raw', 't_last']),
    16: ('dec', ['stat', 'words', 'time', 'margin', 'latecnt']),
    17: ('prev2', ['state', 'dec_stat', 'dec_margin', 'dec_latecnt', 'late', 'discarded', 'aborted', 'abort_landings',
                   'cycles_max', 'catchups', 'exc', 'refusals', 'jobs_failed', 'stack_hw', 'floor_ok', 'dec_words',
                   'dec_time', 'calls', 'exc_first_cause', 'exc_first_epc', 'exc_first_tval', 'boots', 'dirty_age',
                   'w_dec_flags', 'w_dec_margin_x', 'w_dec_latecnt', 'w_late', 'w_discarded', 'w_aborted',
                   'w_abort_landings', 'w_cycles_max', 'w_catchups', 'w_exc', 'w_refusals', 'w_jobs_failed', 'w_stack_hw',
                   'w_floor_overwritten']),
    18: ('cache', None),                                               # version 7: test build 4a's sound-cache probe
                                                                       # (cache_block); version 8: test build 4b's boot
                                                                       # cache (cache_block8)
    19: ('synth', ['incomplete', 'timeouts', 'wbusy', 'underrun', 'done_free', 'done_wbusy', 'dt_starts', 'jobs', 'overlaps',
                   'job_wbusy', 'fails',
                   'diag_defer', 'diag_forced', 'q_max', 'c6_hold', 't_config', 'config', 'status', 'flags', 'seq',
                   'dtout', 'sched', 'pass_blk', 'pass_item', 'pass_bracket', 'pass_tail', 'pass_skip_job',
                   'pass_skip_same', 'pass_post', 'pass_retry']),       # version 9 (test build 5's s5 images,
                                                                        # dbgsave.h DBG_SY_*)
}
# version 7: the 'cache' block (board/pocket/s1_cache4a.h s1_c4a_block_t): the probe boots counted, then 8 entries of 10
# words (this boot's first)
C4A_ENTRY = ['kind', 'cache_in', 'loaded', 'lost', 'bad', 'first_bad', 'first_val', 't_check', 't_fill', 'vs']
C4A_KINDS = {0: 'none', 1: 'WARM', 2: 'FIRST', 3: 'PASS', 4: 'BAD', 5: 'SIZE', 6: 'LOST'}
C4A_BYTES, C4A_WORDS = 0x152100, 0x152100 // 4
C4A_F_CACHE_SET, C4A_F_HDR_OK, C4A_F_BAR_SEEN, C4A_F_BAR_OFF, C4A_F_WROTE = (1 << b for b in range(8, 13))
# version 8: the 'cache' block (board/pocket/s1_cache4b.h s1_c4b_block_t): the boots counted, then 5 entries of 16 words
# (board/pocket/boot/c4b.h c4b_rec_t, this boot's first)
C4B_ENTRY = ['kind', 'cache_in', 'loaded', 'lost', 'bank_crc', 'hdr_crc', 'bad', 'samples', 'crc_errs', 'key', 't_check',
             't_unpack', 't_verify', 't_sfx', 'vs', 'stream']
C4B_KINDS = {0: 'none', 1: 'WARM', 2: 'FIRST', 3: 'PASS', 4: 'HDR', 5: 'KEY', 6: 'BANK', 7: 'SIZE', 8: 'LOST', 9: 'GONE',
             10: 'NOROM'}
C4B_F = dict(CACHE_SET=1 << 8, UNPACKED=1 << 9, HDR_WRITTEN=1 << 10, FAIL=1 << 11, SFX=1 << 12, BAR_OFF=1 << 13,
             BAR_SEEN=1 << 14, CRCERR=1 << 15, CURVE=1 << 27)    # (CURVE: version 9, test build 5's s5 images)
C4B_WHY = {0: '', 1: 'the game\'s pointer table or the stream\'s address not as expected', 2: 'the WavPack stream\'s blocks '
           'not as expected', 3: 'the unpack stopped or its count / CRCs were wrong', 4: 'the check after the unpack failed',
           5: 'the header did not read back', 6: 'CACHE did not read back'}
C4B_HDR_WORDS = {0: 'the magic', 2: 'the format', 3: 'the sizes', 11: 'the ROM key', 63: 'its CRC-32'}
C4B_BYTES = 0x152100
CHIP_BANK_CRC = 0x97CD71B8          # CRC-32 of the sound bank as the cart-engine runner (our test harness that runs
                                    # the cart program) leaves it after C6 (1,384,448 B, measured
                                    # 2026-10-22): a check value, not game data
# version 6: DBG_B_PREV2 in its own layout (board/pocket/dbgsave.h): the largest lateness and the longest wait folded
# after the stack floor, the short-path calls and the album state at the last write after the first exception
PREV2_V6 = ['state', 'dec_stat', 'dec_margin', 'dec_latecnt', 'late', 'discarded', 'aborted', 'abort_landings',
            'cycles_max', 'catchups', 'exc', 'refusals', 'jobs_failed', 'stack_hw', 'floor_ok', 'late_max', 'alb_wait_max',
            'dec_words', 'dec_time', 'calls', 'exc_first_cause', 'exc_first_epc', 'exc_first_tval', 'short_calls',
            'alb_res', 'alb_under', 'alb_lost', 'alb_calls', 'alb_wait', 'boots', 'dirty_age',
            'w_dec_flags', 'w_dec_margin_x', 'w_dec_latecnt', 'w_late', 'w_discarded', 'w_aborted', 'w_abort_landings',
            'w_cycles_max', 'w_catchups', 'w_exc', 'w_refusals', 'w_jobs_failed', 'w_stack_hw', 'w_floor_overwritten',
            'w_late_max', 'w_alb_wait_max']
# version 9 (test build 5's s5 images): the same layout, version 8's audio words carrying the synth's (dbgsave.h
# DBG_P2_SY_*)
PREV2_V9 = [{'catchups': 'sy_timeouts', 'alb_wait_max': 'sy_fails', 'alb_res': 'sy_wbusy', 'alb_under': 'sy_done_wbusy',
             'alb_lost': 'sy_underrun', 'alb_calls': 'sy_dt_starts', 'alb_wait': 'sy_job_wbusy',
             'w_catchups': 'w_sy_timeouts', 'w_alb_wait_max': 'w_sy_fails'}.get(n, n) for n in PREV2_V6]
SY_FAILS = ((1, 'A1 (a write other than a DONE store with no hold-off or a store of a module start or a C6 item met a '
                'running block: WBUSY > what those DONE stores added + the module starts\' + C6 items\' own)'),
            (2, 'A2 (DT playback reads missed beyond one a DT start: UNDERRUN > the DT starts)'),
            (4, 'A3 (an instant serviced on the 5 ms TIMEOUT)'))
# version 10 (the s5 TEST images from test build S3a on, 2026-10-29): fixed blocks (board/pocket/dbgsave.h DBG_PV_* /
# DBG_Q_* / DBG_GL_*)
PREV_V10 = ['state', 'writes', 'now', 'heartbeat', 'n9494', 't_last_9494', 't_last_post', 'last_word', 'exc',
            'exc_first_cause', 'exc_first_epc', 'fatal_age', 'fatal_code', 'fatal_a', 'fatal_b', 'fatal_time', 'vs_count',
            't_last_vs']
Q_FOLD_V10 = ['dec_stat', 'dec_margin', 'dec_latecnt', 'timeouts', 'exc', 'floor_ok', 'stack_hw', 'refusals', 'jobs_failed',
              'discarded', 'aborted', 'late', 'cycles_max']
PREV2_V10 = (['state'] + Q_FOLD_V10 + ['dec_words', 'dec_time', 'exc_first_cause', 'exc_first_epc', 'exc_first_tval',
                                       'boots', 'dirty_age'] +
             ['w_' + {'dec_stat': 'dec_flags', 'dec_margin': 'dec_margin_x', 'floor_ok': 'floor_overwritten'}.get(n, n)
              for n in Q_FOLD_V10])
NAMES_V10 = {
    1: NAMES[1],
    3: ('stats', ['n9494', 't_last_9494', 't_last_post', 'last_word']),
    4: ('sched', ['exc', 'exc_first_cause', 'exc_first_epc', 'exc_first_tval']),
    5: ('wdog', ['ticks']),
    6: NAMES[6],
    7: ('glue', ['discarded', 'aborted', 'late', 'cycles_max']),
    9: ('disp', ['refusals', 'jobs_failed']),
    10: NAMES[10],
    14: ('prev', PREV_V10),
    15: NAMES[15],
    16: NAMES[16],
    17: ('prev2', PREV2_V10),
    19: ('synth', ['timeouts']),
}
SUB_HZ = 12500000                   # the Mega CD sub clock the CPU MATE deadlines count (80 ns a sub cycle)
FRAME_HZ = {53693175: 59.922743, 53203424: 49.701459}   # the VDP's frame rate by the build clock (NTSC / PAL)
ALB_OFF, ALB_WAITING = 0x8000, 0x80000000
MARGIN_X = 0x7FFFFFFF                # prev2's chain keeps DEC_MARGIN ^ MARGIN_X (larger = worse, 0 = none; dbgsave.h)
DEC_FLAGS = ((16, 'OVF'), (17, 'BADTYPE'), (18, 'D0'), (19, 'PRE'), (20, 'LATE'), (21, 'ABORT'))
AU_KIND = {1: 'sfx_play', 2: 'sfx_loop', 3: 'sfx_stop', 10: 'mdp_init', 11: 'mdp_play', 12: 'mdp_play_once',
           13: 'mdp_stop', 14: 'mdp_set_vol'}


def words_of(raw):
    b = bytearray(raw)
    b[0::2], b[1::2] = raw[1::2], raw[0::2]            # undo the .sav's swap of each 16-bit half
    return list(struct.unpack('<%dI' % (len(b) // 4), bytes(b)))


def decode(raw):
    if len(raw) < OFF + SIZE:
        return None, ('the .sav is %d bytes: no debug region (a 0.2.x 4 KB save, or one written before the 8 KB save '
                      'RAM; the stage-1 TEST image needs the 8 KB one)' % len(raw))
    w = words_of(raw[OFF:OFF + SIZE])
    if w[0] >> 16 != 1 or w[1] != MAGIC:
        return None, 'no debug record at 0x1000 (a RELEASE image, the size probe, or never written)'
    out, i = {}, 0
    names = NAMES_V10 if w[2] == 10 else NAMES
    while i < len(w):
        bid, n = w[i] >> 16, w[i] & 0xFFFF
        if bid == 0xFFFF:
            break
        if bid not in names or i + 1 + n > len(w):
            raise ValueError('broken block chain at word %d (id %#x, %d words)' % (i, bid, n))
        name, fields = names[bid]
        if w[2] == 10:
            pass
        elif bid == 17 and w[2] >= 9:
            fields = PREV2_V9
        elif bid == 17 and w[2] >= 6:
            fields = PREV2_V6
        data = w[i + 1:i + 1 + n]
        if fields:
            d = dict(zip(fields, data))
            if len(data) > len(fields):
                d['extra'] = data[len(fields):]
        else:
            d = data
        out[name] = d
        i += 1 + n
    if out['head']['version'] not in VERSIONS:
        raise ValueError('record version %d (this tool reads %s)' % (out['head']['version'], VERSIONS))
    if out['head']['version'] == 10:
        return out, None
    out['stats'] = stats(out['stats'])
    out['disp'] = disp(out['disp'])
    for k in ('aulog', 'oracle'):
        if k in out:
            n, ring = out[k][0], out[k][1:]
            last = [ring[(n - j - 1) % len(ring)] for j in range(min(n, len(ring)))][::-1]
            out[k] = dict(n=n, last=last)
    if 'cache' in out:
        out['cache'] = cache_block(out['cache']) if out['head']['version'] == 7 else cache_block8(out['cache'])
    return out, None


def cache_block(v):
    """the version-7 'cache' block: {'boots', 'entries': [this boot's, the previous ones newest first]} (entries of kind 0
    left out); each entry its words plus kind / flags / w decoded"""
    if len(v) != 1 + 8 * len(C4A_ENTRY):
        raise ValueError('cache block of %d words (want %d)' % (len(v), 1 + 8 * len(C4A_ENTRY)))
    ents = []
    for i in range(8):
        e = dict(zip(C4A_ENTRY, v[1 + i * len(C4A_ENTRY):1 + (i + 1) * len(C4A_ENTRY)]))
        k = e['kind']
        e.update(kind_name=C4A_KINDS.get(k & 0xFF, '?%d' % (k & 0xFF)), flags=k & 0xFF00, w=(k >> 16) & 0x7FF)
        if k & 0xFF:
            ents.append(e)
    return dict(boots=v[0], entries=ents)


def cache_block8(v):
    """the version-8 'cache' block: {'boots', 'v8': True, 'entries': [this boot's, the previous ones newest first]}
    (entries of kind 0 left out); each entry its words plus kind / flags / w / bad parts decoded"""
    if len(v) != 1 + 5 * len(C4B_ENTRY):
        raise ValueError('cache block of %d words (want %d)' % (len(v), 1 + 5 * len(C4B_ENTRY)))
    ents = []
    for i in range(5):
        e = dict(zip(C4B_ENTRY, v[1 + i * len(C4B_ENTRY):1 + (i + 1) * len(C4B_ENTRY)]))
        k = e['kind']
        e.update(kind_name=C4B_KINDS.get(k & 0xFF, '?%d' % (k & 0xFF)), flags=k & 0x0800FF00, w=(k >> 16) & 0x7FF,
                 first_bad=e['bad'] & 0xFF, n_bad=(e['bad'] >> 8) & 0xFF, hdr_word=(e['bad'] >> 16) & 0xFF,
                 why=e['bad'] >> 24, blocks=e['vs'] >> 16, vsyncs=e['vs'] & 0xFFFF)
        if k & 0xFF:
            ents.append(e)
    return dict(boots=v[0], v8=True, entries=ents)


def cache_entry_text8(e, ms):
    """one boot of the boot cache in plain words"""
    k, f = e['kind_name'], e['flags']
    F = lambda n: bool(f & C4B_F[n])
    found = {'WARM': 'CACHE.VALID was set at the start (a reset inside the session, or the Quit\'s own reboot while the '
                     'Pocket reads the file back): nothing touched',
             'FIRST': 'no file loaded (CACHE_LOADED 0)',
             'PASS': 'the file loaded whole (%d B) and checked: header, ROM key, every block\'s CRC, the tail and the '
                     'bank CRC-32: KEPT' % e['loaded'],
             'HDR': 'the file loaded whole but its header is wrong (%s; a card-4a pattern file reads so)' %
                    C4B_HDR_WORDS.get(e['hdr_word'], 'word %d' % e['hdr_word']),
             'KEY': 'the file\'s header is right but it was made from another WavPack stream (the ROM key)',
             'BANK': 'the file\'s header is right but its bank is wrong (%d wrong, the first %s)' % (
                 e['n_bad'], 'the tail' if e['first_bad'] == 0xFE else 'block %d' % e['first_bad']),
             'SIZE': 'a file of %d B loaded, not the image\'s %d B' % (e['loaded'], C4B_BYTES),
             'LOST': 'CRAM writes lost while the file loaded (XLINK LOST %d)' % (e['lost'] >> 16),
             'GONE': 'CACHE.VALID was 0 but the boot overlay is overwritten (a reset after an unpack that failed in this '
                     'power-on): nothing done, the wave bank as it is',
             'NOROM': 'the ROM is not as expected (%s): nothing unpacked, no cache' % C4B_WHY.get(e['why'], '?')}
    s = '%s: %s' % (k, found.get(k, 'kind %#x' % (e['kind'] & 0xFF)))
    if k in ('WARM', 'GONE'):
        return s + ' (CACHE %#010x)' % e['cache_in']
    if k == 'NOROM':
        return s + '; the stream the table names at ROM %#x' % e['stream']
    if F('UNPACKED'):
        s += '; the bank unpacked from ROM %#x (%d WavPack blocks): %d samples in %s, the decoder\'s block CRC errors %d' % (
            e['stream'], e['blocks'], e['samples'], ms(e['t_unpack']), e['crc_errs'] & 0xFFFF)
        if F('FAIL'):
            s += '; FAILED: %s%s: no header, no CACHE (no file at the Quit; the next power-on unpacks again)' % (
                C4B_WHY.get(e['why'], '?'), '' if not e['crc_errs'] >> 16 else ' (unpack stop code %d)' % (e['crc_errs'] >> 16))
        else:
            s += '; checked and the header written in %s' % ms(e['t_verify'])
    s += '; the bank CRC-32 %#010x (%s)' % (e['bank_crc'], 'the chip\'s bank' if e['bank_crc'] == CHIP_BANK_CRC else
                                             'NOT the chip\'s bank %#010x' % CHIP_BANK_CRC)
    if e['loaded'] and k != 'PASS':
        s += ', the file\'s header said %#010x' % e['hdr_crc']
    s += '; ROM key %#010x; check %s' % (e['key'], ms(e['t_check']))
    s += '; CACHE set to the image size: %s' % ('yes (read back)' if F('CACHE_SET') else 'NO')
    s += '; SFX bank copied: %s%s' % ('yes, %s' % ms(e['t_sfx']) if F('SFX') else 'NO', '')
    if F('CURVE'):
        s += '; the synth\'s output curve written'
    s += '; the bar: W %d (%s), %s; VDP vertical syncs while held %d' % (
        e['w'], 'the video ran during the hold' if F('BAR_SEEN') else 'no video line seen during the hold',
        'off at the release' if F('BAR_OFF') else 'STILL ON at the release', e['vsyncs'])
    return s


def cache_entry_text(e, ms):
    """one probe boot in plain words"""
    k, f = e['kind_name'], e['flags']
    found = {'WARM': 'CACHE.VALID was set at the start (a reset inside the session, or the Quit\'s own reboot while the '
                     'Pocket reads the file back): nothing touched',
             'FIRST': 'no file loaded (CACHE_LOADED 0): the pattern written',
             'PASS': 'the file loaded whole (CACHE_LOADED %d B, the image size) and every word right: KEPT' % e['loaded'],
             'BAD': 'the file loaded whole (%d B) but %d words wrong: the pattern written again' % (e['loaded'], e['bad']),
             'SIZE': 'a file of %d B loaded, not the image\'s %d B: the pattern written again' % (e['loaded'], C4A_BYTES),
             'LOST': 'CRAM writes lost while the file loaded (XLINK LOST %d): the pattern written again' % (e['lost'] >> 16)}
    s = '%s: %s' % (k, found.get(k, 'kind %#x' % (e['kind'] & 0xFF)))
    if k == 'WARM':
        return s + ' (CACHE %#010x)' % e['cache_in']
    if e['bad']:
        s += '; the check found %d of %d words wrong, the first at word %d (byte %#x): %#010x%s' % (
            e['bad'], C4A_WORDS, e['first_bad'], 4 * e['first_bad'], e['first_val'],
            '' if f & C4A_F_HDR_OK else ', the header wrong too')
        if k == 'FIRST' and e['bad'] < C4A_WORDS:
            s += ' (the CRAM still held part of an image)'
    else:
        s += '; the check found every word right' + (' (the CRAM kept the image with no file loaded: MCU_INTERFACE '
                                                     'finding 16)' if k == 'FIRST' else '')
    s += '; check %s%s' % (ms(e['t_check']), (', fill %s' % ms(e['t_fill'])) if f & C4A_F_WROTE else '')
    s += '; CACHE set to the image size: %s' % ('yes (read back)' if f & C4A_F_CACHE_SET else 'NO (read back wrong)')
    s += '; the bar: W %d (%s), %s; VDP vertical syncs during the probe %d' % (
        e['w'], 'the video ran during the hold' if f & C4A_F_BAR_SEEN else 'no video line seen during the hold',
        'off at the release' if f & C4A_F_BAR_OFF else 'STILL ON at the release', e['vs'])
    return s


def cache_lines(o, ms):
    """test build 4a's sound-cache probe (version 7) or test build 4b's boot cache (version 8): this boot and the
    carried ones"""
    c = o.get('cache')
    if c is None:
        return []
    if c.get('v8'):
        L = ['boot cache (card 4b; %d boots counted by the chain of records):' % c['boots']]
        for i, e in enumerate(c['entries']):
            L.append('  %s %s' % ('this boot:' if i == 0 else 'boot -%d:' % i, cache_entry_text8(e, ms)))
        return L
    L = ['sound-cache probe (card 4a; %d probe boots counted by the chain of records):' % c['boots']]
    for i, e in enumerate(c['entries']):
        L.append('  %s %s' % ('this boot:' if i == 0 else 'boot -%d:' % i, cache_entry_text(e, ms)))
    return L


def stats(v):
    lv = []
    for k in range(5):
        e, lo, hi, mx = v[4 * k:4 * k + 4]
        lv.append(dict(level=LEVELS[k], entries=e, cycles=lo | (hi << 32), max_incl=mx))
    p = 20
    ms = v[p:p + 0x18]
    p += 0x18
    names = ['lat_n', 'lat_sum', 'lat_max', 'n84', 't84_last', 't84_max', 'n9494', 't_last_9494', 't_last_post',
             'last_word', 'depth_max']
    d = dict(zip(names, v[p:p + len(names)]))
    d['levels'] = lv
    d['milestones'] = {MS.get(c, 'code %#x' % c): t for c, t in enumerate(ms) if t}
    return d


def disp(v):
    return dict(refusals=v[0], last_trace=v[1], jobs_run=v[2], jobs_failed=v[3], q_wr=v[4] & 0xFF, q_rd=(v[4] >> 8) & 0xFF,
                app_ready=(v[4] >> 16) & 0xFF, mixer=v[4] >> 24, wd_arm=v[5] & 0xFFFF, wd_count=v[5] >> 16,
                heartbeat_count=v[6] & 0xFFFF, f81=[(v[6] >> s) & 0xF for s in (16, 20, 24, 28)],
                fe4_shadow=v[7] & 0xFFFF, fe6_shadow=v[7] >> 16,
                trace=[(v[8 + i // 2] >> (16 * (i & 1))) & 0xFFFF for i in range(16)])


def flags_of(stat):
    return ' '.join(n for b_, n in DEC_FLAGS if (stat >> b_) & 1) or 'none'


def margin_text(m, ms):
    """DEC_MARGIN (signed 32; 0x7FFFFFFF = no START since the reset)"""
    mg = m - (1 << 32) if m & 0x80000000 else m
    return '-' if mg == 0x7FFFFFFF else ms(mg) if mg >= 0 else '-' + ms(-mg)


V5_LATE = ('v5 counter: every publish while the stub\'s sticky LATE flag was up, NOT a count of late answers (stage 1td: '
           'the co-sims\' real rate 3-60 %, stale reads 0)')
V6_LATE = 'expected since stage 1i; harmful only if the game reads first'
WALL = 'wall time, the game\'s own work that preempted the call included'


def fps(o):
    return FRAME_HZ.get(o['head']['clk_hz'], FRAME_HZ[53693175])


def secs(frames, o):
    return '%.2f s' % (frames / fps(o))


def cmd_text(c):
    """an album command word as the debug save keeps it (16 bits; bit 15 = not written: the album was off)"""
    off = ' - NOT WRITTEN (the album was off: mdp_on 0)' if c & ALB_OFF else ''
    c &= 0x7FFF
    hb, lo = c >> 8, c & 0xFF
    if c == 0:
        return 'the album init' + (' - it FAILED, the album is off (mdp_on 0: no play / stop is written)' if off else ' (on)')
    t = ('play track %d, looped' % lo if hb == 0x12 else 'play track %d once' % lo if hb == 0x11 else
         'stop' if hb == 0x13 else 'volume %d' % lo if hb == 0x15 else 'command')
    return '%s (%#06x)%s' % (t, c, off)


def wait_text(w, o):
    """the alb_wait word: frames since the last play request while playing stayed 0 (bit 31 still waiting, bit 30 a stop
    ended it before the track played)"""
    f = w & 0x3FFFFFFF
    if w & ALB_WAITING:
        return 'playing still 0, %s after the request' % secs(f, o)
    if w & 0x40000000:
        return 'stopped after %s without playing' % secs(f, o)
    return 'it played within %s of the request (the first write that saw playing)' % secs(f, o)


def underrun_text(x14):
    u = x14 & 0xFFFF
    return 'CDDA underruns %d%s%s' % (u, ' (saturated)' if u == 0xFFFF else '',
                                     ', snoop overflows %d' % (x14 >> 16) if x14 >> 16 else '')


def lost_text(x18):
    return 'CRAM ring writes lost %d, SRAM loader words lost %d' % (x18 >> 16, x18 & 0xFFFF)


def res_text(res):
    return 'the adapter holds track %d, playing = %s; the command it last took %#06x' % (
        (res >> 8) & 0xFF, 'yes' if res & 1 else 'no', res >> 16)


def music_lines(o):
    """the album's state at this write (version 6), in plain words"""
    a, v = o['audio'], o['head']['version']
    if 'alb_res' not in a:
        return ['music (the album, MD+ path): not in this record (version %d; version 6 records the MD+ result word, '
                'XLINK\'s CDDA counters and the last play request)' % v]
    c, now = a['alb_calls'], o['vs']['count']
    L = ['music (the album, MD+ path) at this write: %s; %s; %s' % (res_text(a['alb_res']), underrun_text(a['alb_xl14']),
                                                                   lost_text(a['alb_xl18']))]
    if c & 0xFFFF:
        d = (now - a['alb_play_f']) & 0xFFFFFFFF
        L.append('  the last play request: %s, %s before this write (frame %d): %s; CDDA underruns at the first write '
                 'after it %d (%+d since)' % (cmd_text(c & 0xFFFF), secs(d, o), a['alb_play_f'],
                                              wait_text(a['alb_wait'], o), a['alb_play_und'],
                                              (a['alb_xl14'] & 0xFFFF) - a['alb_play_und']))
    else:
        L.append('  no play request since the boot')
    L.append('  the last album call: %s; the longest wait this session for a requested track to play %s' % (
        cmd_text(c >> 16), secs(a['alb_wait_max'], o)))
    if (a['alb_wait'] & ALB_WAITING) and not (c & ALB_OFF):
        L.append('  music: track %d requested %s before this write, playing = no' % (
            c & 0xFF, secs(a['alb_wait'] & 0x3FFFFFFF, o)))
    return L


def fails_text(f):
    return 'none' if not f else '; '.join(t for b_, t in SY_FAILS if f & b_) or '%#x' % f


def synth_lines(o, ms):
    """version 9 (test build 5's s5 images): the synth and its TEST assertions at this write, in plain words"""
    y = o.get('synth')
    if y is None:
        return []
    cfg = y['config']
    mode = {0: 'none yet', 1: 'DT', 2: 'YM-DAC', 3: 'none'}[cfg & 3]
    L = ['synth (card 5) at this write: CONFIG %s%s (SEQ %d), STATUS %#010x (blocks mixed %d mod 4,096), FLAGS %#04x, '
         'DTOUT %#010x (gain %d/256, invert %d, DC blocker %d); the first CONFIG write of this boot %s' % (
             mode, ' PAL' if cfg & 4 else '', cfg >> 16, y['status'], (y['status'] >> 16) & 0xFFF, y['flags'],
             y['dtout'], y['dtout'] & 0xFFFF, (y['dtout'] >> 16) & 1, (y['dtout'] >> 17) & 0xF,
             ms(y['t_config'] & ~1) if y['t_config'] else 'not yet'),
         '  DIAG totals since the boot: DT halves incomplete %d, instants serviced on the TIMEOUT %d (must be 0), MCU '
         'writes while a block ran %d (DONE stores with no hold-off %d, %d of them while a block ran), DT playback reads '
         'not served %d (DT starts %d); DIAG clears put off %d, forced %d' % (
             y['incomplete'], y['timeouts'], y['wbusy'], y['done_free'], y['done_wbusy'], y['underrun'], y['dt_starts'],
             y['diag_defer'], y['diag_forced']),
         '  TEST assertions (the synth checks A1, A2, A3): %s' % ('A1 A2 A3 all hold' if not y['fails'] else
                                                          'FAILED ' + fails_text(y['fails'])),
         '  module starts + C6 items (the items with no arrival: the 8C\'s module starts and C6\'s two engine items a '
         'boot) %d, a block started during their stores in %d, their writes that met '
         'a running block %d (the chip\'s preemptible engine items, done as the chip does them; a '
         'diagnostic, not a failure); the engine '
         'queue\'s deepest %d; C6\'s hold record %#010x' % (y['jobs'], y['overlaps'], y['job_wbusy'], y['q_max'],
                                                            y['c6_hold']),
         '  main-loop passes: in items %d, after blocks %d, after posts with no item %d, at job tails %d; skipped (a job '
         'queued) %d, (no block since) %d; CAUSE.BLK %d; re-reads (a block ran during the reads) %d' % (
             y['pass_item'], y['pass_bracket'], y['pass_post'], y['pass_tail'], y['pass_skip_job'], y['pass_skip_same'],
             y['pass_blk'], y['pass_retry'])]
    return L


def prev2_lines(o, ms):
    """the carried block (version 5 / 6), or the note that the record has none"""
    v, q = o['head']['version'], o.get('prev2')
    if q is None:
        return ['previous session\'s lateness counters (decoder late words, CPU MATE, SFX feeder): not in this record '
                '(a version-%d record keeps only the summary above; version 5 carries them in \'prev2\', so a quit no '
                'longer loses them)' % v]
    st = q['state']
    if st == 0:
        return ['previous session\'s lateness counters (prev2): none (no previous record at this boot)']
    if st == 0xFFFFFFFF:
        return ['previous session\'s lateness counters (prev2): none (a record of a version this image could not read)']
    if st < 4:
        return ['previous session\'s lateness counters (prev2): not carried (its record is version %d, before the '
                'decoder block)' % st]
    exc = (' (first: cause %#x at pc %#x, tval %#x)' % (q['exc_first_cause'], q['exc_first_epc'], q['exc_first_tval'])
           if q['exc'] else '')
    if v < 6:                               # a version-5 image: its 'late' is the sticky-flag count
        cm = ('  its CPU MATE: calls %d, answers published late %d (%s), discarded %d (must be 0), aborted %d (must be 0; '
              'landed %d), the longest call %s (%s)' % (q['calls'], q['late'], V5_LATE, q['discarded'], q['aborted'],
                                                         q['abort_landings'], ms(q['cycles_max']), WALL))
    elif st < 6:                            # carried by a version-6 image from an older record: no true count there
        cm = ('  its CPU MATE: calls %d, answers armed late: not counted by its v%d image (its counter counted publishes '
              'while the stub\'s sticky flag was up; not carried), discarded %d (must be 0), aborted %d (must be 0; '
              'landed %d), the longest call %s (%s)' % (q['calls'], st, q['discarded'], q['aborted'],
                                                         q['abort_landings'], ms(q['cycles_max']), WALL))
    else:
        cm = ('  its CPU MATE: calls %d, answers armed after the original\'s instant %d (%s), the latest by up to %.1f us, '
              'short-path calls (no partner active) %d; discarded %d (must be 0), aborted %d (must be 0; landed %d); the '
              'longest call %s (%s)' % (q['calls'], q['late'], V6_LATE, q['late_max'] * 1e6 / SUB_HZ, q['short_calls'],
                                         q['discarded'], q['aborted'], q['abort_landings'], ms(q['cycles_max']), WALL))
    L = ['previous session (carried from its v%d record at this boot): sprite decoder late words %d (must be 0); '
         'decoder flags %s; the smallest GO -> first window read %s; its last START %d words, START -> GO %s' % (
             st, q['dec_latecnt'], flags_of(q['dec_stat']), margin_text(q['dec_margin'], ms), q['dec_words'],
             ms(q['dec_time'] & 0xFFFFFF) if q['dec_time'] >> 31 else '-'),
         cm,
         ('  its synth: instants serviced on the TIMEOUT %d (must be 0); failed TEST assertions: %s; writes while a '
          'block ran %d (DONE stores with no hold-off %d of them, the module starts\' + C6 items\' own %d: B2); DT '
          'reads not served %d '
          '(DT starts %d)' % (q['sy_timeouts'], fails_text(q['sy_fails']), q['sy_wbusy'], q['sy_done_wbusy'],
                          q['sy_job_wbusy'], q['sy_underrun'], q['sy_dt_starts']) if v >= 9 else
          '  its SFX feeder catch-ups %d' % q['catchups']) +
         '; exceptions %d (must be 0)%s; dispatcher refusals %d, failed jobs %d; stack high-water %d B, floor word %s' % (
             q['exc'], exc, q['refusals'], q['jobs_failed'], q['stack_hw'], 'intact' if q['floor_ok'] else 'OVERWRITTEN')]
    if 6 <= v < 9:
        if st < 6:
            L.append('  its music: not in its v%d record' % st)
        else:
            c = q['alb_calls']
            L.append('  its music at its last write: %s; the last play request: %s%s; the last album call: %s; %s; %s; '
                     'its longest wait for a requested track to play %s' % (
                         res_text(q['alb_res']), cmd_text(c & 0xFFFF) if c & 0xFFFF else 'none',
                         (' - ' + wait_text(q['alb_wait'], o)) if c & 0xFFFF else '', cmd_text(c >> 16),
                         underrun_text(q['alb_under']), lost_text(q['alb_lost']), secs(q['alb_wait_max'], o)))
            if (q['alb_wait'] & ALB_WAITING) and not (c & ALB_OFF):
                L.append('  music (previous session): track %d requested %s before its last write, playing = no' % (
                    c & 0xFF, secs(q['alb_wait'] & 0x3FFFFFFF, o)))
    if q['boots']:
        mx = q['w_dec_margin_x']
        da = q['dirty_age']
        if v < 6:
            cw = 'CPU MATE late %d (%s)' % (q['w_late'], V5_LATE)
        else:
            cw = ('CPU MATE answers armed late %d (the most in one session; %s), the latest by up to %.1f us' % (
                q['w_late'], V6_LATE, q['w_late_max'] * 1e6 / SUB_HZ))
        L.append('worst over the %d chained session%s (each boot folds the one before it: counts and times the largest, '
                 'the margin the smallest, the flags ORed): sprite decoder late words %d (must be 0); decoder flags %s; '
                 'the smallest GO -> first window read %s; %s, discarded %d (must be 0), aborted %d (must be 0; landed %d), '
                 'the longest call %s (%s); %s; exceptions %d (must be 0); refusals %d, failed jobs '
                 '%d; stack high-water %d B, floor word %s%s' % (
                     q['boots'], '' if q['boots'] == 1 else 's', q['w_dec_latecnt'], flags_of(q['w_dec_flags']),
                     margin_text(mx ^ MARGIN_X, ms) if mx else '-', cw, q['w_discarded'], q['w_aborted'],
                     q['w_abort_landings'], ms(q['w_cycles_max']), WALL,
                     ('the synth\'s instants on the TIMEOUT %d, failed TEST assertions %s' % (
                         q['w_sy_timeouts'], fails_text(q['w_sy_fails']))) if v >= 9 else
                     'SFX feeder catch-ups %d' % q['w_catchups'], q['w_exc'], q['w_refusals'],
                     q['w_jobs_failed'], q['w_stack_hw'], 'OVERWRITTEN in one' if q['w_floor_overwritten'] else 'intact',
                     ('; the longest wait for a requested track to play %s' % secs(q['w_alb_wait_max'], o)) if 6 <= v < 9
                     else ''))
        sign = ('late words, an OVF / BADTYPE / D0 / PRE / LATE flag, an exception, the stack floor, the synth\'s TIMEOUTs '
                'or a failed TEST assertion (version 9); a late CPU MATE answer is no sign' if v >= 9 else
                'late words, an OVF / BADTYPE / D0 / PRE / LATE flag, an exception, the stack floor; from version 6 a late '
                'CPU MATE answer is no sign' if v >= 6 else
                'late words, an OVF / BADTYPE / D0 / PRE / LATE flag, a late CPU MATE answer, an exception, the stack floor')
        L.append('  the newest session with a lateness sign (%s): %s' % (
            sign, 'none in the chain' if not da else 'the previous session' if da == 1 else '%d sessions back' % da))
        if v < 6 and da and q['w_late']:
            clean = (not q['w_dec_latecnt'] and not (q['w_dec_flags'] & 0x001F0000) and not q['w_exc'] and
                     not q['w_floor_overwritten'])
            L.append('  note (stage 1td): a version-5 image counts its CPU MATE counter in this sign, and that counter is '
                     'the sticky-flag artefact; %s' % (
                         'without it the chain has no lateness sign (decoder late words, decoder flags, exceptions and '
                         'the stack floor are all clean in its worst)' if clean else
                         'the chain also has another sign (see its worst above)'))
    if v < 6:
        L.append('note (stage 1td): in a version-5 record the CPU MATE \'late\' counts every publish that found the stub\'s '
                 'sticky LATE flag up from any earlier late ARM (cleared only at the boot and in rare housekeeping), so it '
                 'reads close to the calls; the co-sims\' real late rate was 3-60 %%, with no stale read. A late ARM (the '
                 'answer armed after the original\'s instant) is expected since stage 1i, when the brain call began to '
                 'wait for the game\'s own work, and is harmful only if the game reads $A12024 before it. The brain runs '
                 'whenever the game posts it (a Mega CD unit selected and the Options CPU MATE row on), partner or not, '
                 'as on the cart. Version 6 counts each late answer. \'The longest call\' is %s.' % WALL)
    return L


def freeze_view(hz, now, n9494, t9494, vs_count, t_vs):
    """which of the 68000 and the VDP were still running at a write (the MCU was: it wrote the record).
    vs_count None = no VS counter in the record (version 1 or 2). Returns (text, verdict)"""
    age = lambda t: ((now - t) & 0xFFFFFFFF) / float(hz)
    alive68 = bool(n9494) and age(t9494) <= STALE_S
    m68 = 'running' if alive68 else ('no 9494 for %.3f s' % age(t9494) if n9494 else 'no 9494 yet')
    if vs_count is None:
        return '68000 %s; VDP unknown (no VS counter: a record before version 3)' % m68, None
    alivevdp = bool(vs_count) and age(t_vs) <= STALE_S
    vdp = 'running' if alivevdp else ('no vertical sync for %.3f s' % age(t_vs) if vs_count else 'no vertical sync since the boot')
    if not n9494 and not vs_count and now / float(hz) <= 1.0:
        verdict = 'starting (a write from the boot: no frame yet)'
    elif alive68 and alivevdp:
        verdict = 'running'
    elif alivevdp:
        verdict = '68000 STOPPED, VDP alive (a dead or paused 68000)'
    elif alive68:
        verdict = 'VDP STOPPED, 68000 still posting'
    else:
        verdict = 'VDP STOPPED and no 9494 (a dead VDP or its clock)'
    return '68000 %s; VDP %s -> %s' % (m68, vdp, verdict), verdict


def report10(o):
    """version 10 (the s5 TEST images from test build S3a on, 2026-10-29): the lateness signs, the freeze telemetry, the
    CPU MATE counters, PREV / PREV2"""
    h = o['head']
    hz = h['clk_hz'] or 53693175
    ms = lambda c: '%.3f ms' % (1000.0 * c / hz)
    s, v, dc, sc, g = o['stats'], o['vs'], o['dec'], o['sched'], o['glue']
    L = ['debug save v10 (the lateness signs, the freeze telemetry, the CPU MATE counters), write %d, board time %s, '
         'clock %d Hz' % (h['writes'], ms(h['now']), hz)]
    L.append('freeze telemetry: MCU heartbeat (TIM7 ticks) %d; 9494s %d, the last at %s (%s before this write); '
             'last post %#06x at %s' % (o['wdog']['ticks'], s['n9494'], ms(s['t_last_9494']),
                                        ms((h['now'] - s['t_last_9494']) & 0xFFFFFFFF), s['last_word'], ms(s['t_last_post'])))
    L.append('  VDP vertical syncs %d (VSCNT %#06x), the count last moved at %s (%s before this write)' % (
        v['count'], v['raw'], ms(v['t_last']), ms((h['now'] - v['t_last']) & 0xFFFFFFFF)))
    L.append('  at this write: ' + freeze_view(hz, h['now'], s['n9494'], s['t_last_9494'], v['count'], v['t_last'])[0])
    f = o['fatal']
    if f['code']:
        L.append('FATAL HALT: event %#x (%#x, %#x) at %s' % (f['code'], f['a'], f['b'], ms(f['time'])))
    L.append('lateness signs: sprite decoder late words (LATECNT) %d (must be 0), flags %s, the smallest GO -> first '
             'window read %s, last START %d words, START -> GO %s; the synth\'s instants serviced on the TIMEOUT %d (must '
             'be 0); exceptions %d (must be 0)%s; refusals %d, failed jobs %d; stack high-water %d B, floor word %s' % (
                 dc['latecnt'], flags_of(dc['stat']), margin_text(dc['margin'], ms), dc['words'],
                 ms(dc['time'] & 0xFFFFFF) if dc['time'] >> 31 else '-', o['synth']['timeouts'], sc['exc'],
                 (' (first: cause %#x at pc %#x, tval %#x)' % (sc['exc_first_cause'], sc['exc_first_epc'],
                                                              sc['exc_first_tval'])) if sc['exc'] else '',
                 o['disp']['refusals'], o['disp']['jobs_failed'], o['stack']['high_water_bytes'],
                 'intact' if o['stack']['floor_intact'] else 'OVERWRITTEN'))
    L.append('CPU MATE: discarded %d (must be 0), aborted %d (must be 0), answers armed after the original\'s instant %d '
             '(%s), the longest call %s (%s)' % (g['discarded'], g['aborted'], g['late'], V6_LATE, ms(g['cycles_max']),
                                                 WALL))
    p = o['prev']
    if p['state'] == 0:
        L.append('previous session: none in the save RAM at this boot (a blank save, a 0.2.x import, a RELEASE session)')
    elif p['state'] != 10:
        L.append('previous session: a version-%d record at this boot (another layout: not carried; the chain starts '
                 'again)' % p['state'] if p['state'] < 0x10000 else
                 'previous session: a record of an unknown version (%#x): not carried' % p['state'])
    else:
        L.append('previous session (v10 record, as this boot found it): last write %d at %s; heartbeat %d; 9494s %d, the '
                 'last at %s (%s before its last write); last post %#06x at %s; exceptions %d%s; its VDP vertical syncs '
                 '%d, the count last moved at %s' % (
                     p['writes'], ms(p['now']), p['heartbeat'], p['n9494'], ms(p['t_last_9494']),
                     ms((p['now'] - p['t_last_9494']) & 0xFFFFFFFF), p['last_word'], ms(p['t_last_post']), p['exc'],
                     ' (first: cause %#x at pc %#x)' % (p['exc_first_cause'], p['exc_first_epc']) if p['exc'] else '',
                     p['vs_count'], ms(p['t_last_vs'])))
        L.append('  at its last write: ' + freeze_view(hz, p['now'], p['n9494'], p['t_last_9494'], p['vs_count'],
                                                        p['t_last_vs'])[0])
    if p['fatal_age']:
        L.append('EARLIER FATAL HALT (%s): event %#x (%#x, %#x) at %s' % (
            'the previous session' if p['fatal_age'] == 1 else '%d sessions back' % p['fatal_age'],
            p['fatal_code'], p['fatal_a'], p['fatal_b'], ms(p['fatal_time'])))
    q = o['prev2']
    if q['state'] == 10:
        L.append('previous session\'s lateness signs (carried from its v10 record): sprite decoder late words %d (must be '
                 '0), flags %s, the smallest GO -> first window read %s; TIMEOUTs %d (must be 0); exceptions %d (must be '
                 '0)%s; refusals %d, failed jobs %d; stack high-water %d B, floor word %s; its CPU MATE: discarded %d, '
                 'aborted %d, armed late %d, the longest call %s' % (
                     q['dec_latecnt'], flags_of(q['dec_stat']), margin_text(q['dec_margin'], ms), q['timeouts'], q['exc'],
                     (' (first: cause %#x at pc %#x, tval %#x)' % (q['exc_first_cause'], q['exc_first_epc'],
                                                                  q['exc_first_tval'])) if q['exc'] else '',
                     q['refusals'], q['jobs_failed'], q['stack_hw'], 'intact' if q['floor_ok'] else 'OVERWRITTEN',
                     q['discarded'], q['aborted'], q['late'], ms(q['cycles_max'])))
    if q['boots']:
        mx = q['w_dec_margin_x']
        L.append('worst over the %d chained session%s: sprite decoder late words %d (must be 0), flags %s, the smallest GO '
                 '-> first window read %s; TIMEOUTs %d; exceptions %d; refusals %d, failed jobs %d; stack high-water %d B, '
                 'floor word %s; CPU MATE discarded %d, aborted %d, armed late %d (the most in one session), the longest '
                 'call %s' % (
                     q['boots'], '' if q['boots'] == 1 else 's', q['w_dec_latecnt'], flags_of(q['w_dec_flags']),
                     margin_text(mx ^ MARGIN_X, ms) if mx else '-', q['w_timeouts'], q['w_exc'], q['w_refusals'],
                     q['w_jobs_failed'], q['w_stack_hw'], 'OVERWRITTEN in one' if q['w_floor_overwritten'] else 'intact',
                     q['w_discarded'], q['w_aborted'], q['w_late'], ms(q['w_cycles_max'])))
        da = q['dirty_age']
        L.append('  the newest session with a lateness sign (late words, an OVF / BADTYPE / D0 / PRE / LATE flag, a '
                 'TIMEOUT, an exception, the stack floor; refusals, failed jobs and late CPU MATE answers are no sign): %s' % (
                     'none in the chain' if not da else 'the previous session' if da == 1 else '%d sessions back' % da))
    return '\n'.join(L)


def report(o, logs):
    if o['head']['version'] == 10:
        return report10(o)
    h = o['head']
    hz = h['clk_hz'] or 53693175
    ms = lambda c: '%.3f ms' % (1000.0 * c / hz)
    L = ['debug save v%d, write %d, board time %s, clock %d Hz' % (h['version'], h['writes'], ms(h['now']), hz)]
    s = o['stats']
    L.append('boot milestones:')
    for k, t in sorted(s['milestones'].items(), key=lambda kv: kv[1]):
        L.append('  %-34s %s' % (k, ms(t)))
    b = o['boot']
    L.append('boot record: code %#x at %s' % (b['code'], ms(b['time'])))
    L.append('freeze telemetry: MCU heartbeat (TIM7 ticks) %d; 9494s %d, the last at %s (%s before this write); '
             'last post %#06x at %s' % (o['wdog']['ticks'], s['n9494'], ms(s['t_last_9494']),
                                        ms((h['now'] - s['t_last_9494']) & 0xFFFFFFFF), s['last_word'], ms(s['t_last_post'])))
    v = o.get('vs')
    if v is not None:
        L.append('  VDP vertical syncs %d (VSCNT %#06x), the count last moved at %s (%s before this write)' % (
            v['count'], v['raw'], ms(v['t_last']), ms((h['now'] - v['t_last']) & 0xFFFFFFFF)))
    L.append('  at this write: ' + freeze_view(hz, h['now'], s['n9494'], s['t_last_9494'], v['count'] if v else None,
                                               v['t_last'] if v else 0)[0])
    tot = h['mcycle']
    L.append('levels (exclusive cycles; idle is the rest of %d):' % tot)
    used = 0
    for lv in s['levels']:
        used += lv['cycles']
        L.append('  %-20s %9d runs  %12d cycles (%5.1f %%)  longest %s' % (
            lv['level'], lv['entries'], lv['cycles'], 100.0 * lv['cycles'] / tot if tot else 0, ms(lv['max_incl'])))
    L.append('  %-20s %12s %12d cycles' % ('idle (rest)', '', max(tot - used, 0)))
    L.append('L1 latency (STAMP_B to the read): %d posts, mean %s, max %s' % (
        s['lat_n'], ms(s['lat_sum'] / s['lat_n']) if s['lat_n'] else '-', ms(s['lat_max'])))
    L.append('84 window off after its post: %d times, last %s, max %s (R9: 0.1-0.5 ms)' % (
        s['n84'], ms(s['t84_last']), ms(s['t84_max'])))
    sc = o['sched']
    L.append('scheduler: L1 %d (%d empty), L2a %d, L2b %d, posts B %d / A %d, sends %d, brain calls %d, exceptions %d' % (
        sc['l1'], sc['l1_empty'], sc['l2a'], sc['l2b'], sc['posts_b'], sc['posts_a'], sc['sends'], sc['brain_calls'],
        sc['exc']) + (' (first: cause %#x at pc %#x, tval %#x)' % (sc['exc_first_cause'], sc['exc_first_epc'],
                                                                     sc['exc_first_tval']) if sc['exc'] else ''))
    dc = o.get('dec')
    if dc is not None:
        mg = dc['margin'] - (1 << 32) if dc['margin'] & 0x80000000 else dc['margin']
        fl = [n for b_, n in DEC_FLAGS if (dc['stat'] >> b_) & 1]
        L.append('RTL sprite decoder (MCU interface v1.2): queue %d, %s; last START %d words written, START -> GO %s; '
                 'window words served ahead of the decode (LATECNT, must be 0) %d; the smallest GO -> first window read %s; '
                 'flags %s' % (dc['stat'] & 0x1F, 'running' if (dc['stat'] >> 10) & 1 else 'idle', dc['words'],
                               ms(dc['time'] & 0xFFFFFF) if dc['time'] >> 31 else '-', dc['latecnt'],
                               '-' if mg == 0x7FFFFFFF else ms(mg) if mg >= 0 else '-' + ms(-mg), ' '.join(fl) or 'none'))
    f = o['fatal']
    if f['code']:
        L.append('FATAL HALT: event %#x (%#x, %#x) at %s, %d polls' % (f['code'], f['a'], f['b'], ms(f['time']), f['polls']))
    L.extend(cache_lines(o, ms))
    p = o.get('prev')
    if p is not None:
        if p['state'] == 0:
            L.append('previous session: none in the save RAM at this boot (a blank save, a 0.2.x import, a RELEASE session)')
        elif p['state'] in VERSIONS:
            L.append('previous session (v%d record, as this boot found it): last write %d at %s; heartbeat %d (%d gated); '
                     '9494s %d, the last at %s (%s before its last write); last post %#06x at %s; exceptions %d%s' % (
                         p['state'], p['writes'], ms(p['now']), p['heartbeat'], p['gated'], p['n9494'], ms(p['t_last_9494']),
                         ms((p['now'] - p['t_last_9494']) & 0xFFFFFFFF), p['last_word'], ms(p['t_last_post']), p['exc'],
                         ' (first: cause %#x at pc %#x)' % (p['exc_first_cause'], p['exc_first_epc']) if p['exc'] else ''))
            if p['state'] >= 3:
                L.append('  its VDP vertical syncs %d, the count last moved at %s' % (p.get('vs_count', 0),
                                                                                      ms(p.get('t_last_vs', 0))))
            L.append('  at its last write: ' + freeze_view(hz, p['now'], p['n9494'], p['t_last_9494'],
                                                            p.get('vs_count') if p['state'] >= 3 else None,
                                                            p.get('t_last_vs', 0))[0])
        else:
            L.append('previous session: a record of a version this image could not read (%#x)' % p['state'])
        if p['fatal_age']:
            L.append('EARLIER FATAL HALT (%s): event %#x (%#x, %#x) at %s, %d polls' % (
                'the previous session' if p['fatal_age'] == 1 else '%d sessions back' % p['fatal_age'],
                p['fatal_code'], p['fatal_a'], p['fatal_b'], ms(p['fatal_time']), p['fatal_polls']))
    L.extend(prev2_lines(o, ms))
    g = o['glue']
    if 'late' in g:                         # version 6
        L.append('CPU MATE: calls %d, published %d, discarded %d (must be 0), aborted %d (must be 0; landed %d), '
                 'exceptions in the brain %d (must be 0), restarts %d; answers armed after the original\'s instant %d '
                 '(%s), the latest by up to %.1f us; short-path calls (D_WORD under 1,000 sub cycles: no partner '
                 'active) %d; the longest call %s (%s)' % (
                     g['calls'], g['published'], g['discarded'], g['aborted'], g['abort_landings'], g['exc_brain'],
                     g['restarts'], g['late'], V6_LATE, g['late_max'] * 1e6 / SUB_HZ, g['short_calls'],
                     ms(g['cycles_max']), WALL))
    else:
        L.append('CPU MATE: calls %d, published %d, discarded %d (must be 0), aborted %d (must be 0; landed %d), late %d '
                 '(%s), restarts %d' % (g['calls'], g['published'], g['discarded'], g['aborted'], g['abort_landings'],
                                        g['late_seen'], V5_LATE, g['restarts']))
    if 'audio' in o:                        # the s1 images (version 9 has none: the interim audio is gone)
        L.extend(music_lines(o))
        a = o['audio']
        L.append('audio: feeder ticks %d, pushes %d, VU rows %d' % (a['ticks'], a['pushes'], a['vu_rows']))
    L.extend(synth_lines(o, ms))
    d = o['disp']
    L.append('dispatcher: refusals %d, jobs %d (%d failed), watchdog count %d, $1FE4 %#06x $1FE6 %#06x' % (
        d['refusals'], d['jobs_run'], d['jobs_failed'], d['wd_arm'], d['fe4_shadow'], d['fe6_shadow']))
    L.append('stack: high-water %d B, floor word %s' % (o['stack']['high_water_bytes'],
                                                       'intact' if o['stack']['floor_intact'] else 'OVERWRITTEN'))
    if logs:
        au = o.get('aulog')
        if au:
            L.append('audio calls (last %d of %d):' % (len(au['last']), au['n']))
            for e in au['last']:
                L.append('  post %5d  %-13s %#04x' % (e & 0xFFFF, AU_KIND.get(e >> 24, '?%d' % (e >> 24)), (e >> 16) & 0xFF))
        orc = o.get('oracle')
        if orc:
            L.append('register writes (last %d of %d): %s' % (len(orc['last']), orc['n'],
                                                              ' '.join('%02X:%04X' % (e >> 24, e & 0xFFFFFF) for e in orc['last'][-64:])))
    return '\n'.join(L)


# ---- 0.2.6's TEST SAT snapshot in save bytes 0x900-0xFFF (legacy/026/mame.c ppm_snapshot_sat; TEST images only)
SNAP_BOOT, SNAP_BASE, SNAP_L2, SNAP_LATEST = 0x900, 0x910, 0x906, 0x910 + 8 + 640 + 64 * 6
SNAP_DISP, SNAP_T = 0x910 + 8 + 640 + 1024, 0x910 + 8 + 640 + 1024 + 80
H40_ENTRIES, LINE_SPR, LINE_CELLS, LINES = 80, 20, 40, 224


def sat_entries(m, at):
    """the 80 entries at MCU byte `at`: (y, size << 8 | link, attr, x) words as the cart RAM holds them"""
    return [struct.unpack_from('<4H', m, at + 8 * i) for i in range(H40_ENTRIES)]


def mux02(sat):
    """the stored table is the chip's AF02 multiplex (in the s1 images from 2026-10-17 the frame end is the chip's:
    legacy/026/mame.c chip_af_over80, which does what the cart chip's routine at $08019334-$0801936C does): a frame of
    more than 80 entries posted AF02 has entries 14..top-2 relinked to k - 13 (top = the count, at most 94: the console's
    slots 14-79 hold entries 28-93), so every stored entry 14-79 links to k - 13; a table as composed links entry k to
    k + 1, and the chip's AF00 / AF01 closes keep the links"""
    return all(sat[k][1] & 0xFF == k - 13 for k in range(14, H40_ENTRIES))


def vdp_lines(sat):
    """what the console's sprite layer does with the stored table (an estimate from the documented H40 rules): the
    link walk from entry 0 (at most 80 entries; it ends at link 0 or at a link of 80
    or more, past the console's table), then per line 0-223 the sprites of the walk that cover it: more than 20 = the
    line is over 20 sprites (the later ones are not drawn); the first 20's widths over 40 cells = the line is over 320 px
    (the cells past 320 are not drawn). Returns (walk length, its last link, lines over 320 px, lines over 20 sprites)"""
    order, k = [], 0
    while k < H40_ENTRIES and k not in order:
        order.append(k)
        if sat[k][1] & 0x7F == 0:
            break
        k = sat[k][1] & 0x7F
    over320 = over20 = 0
    for line in range(LINES):
        on = []
        for e in order:
            y, sl = sat[e][0] & 0x3FF, sat[e][1]
            if 0 <= line + 128 - y < 8 * ((sl >> 8) & 3) + 8:
                on.append(((sl >> 10) & 3) + 1)
        over20 += len(on) > LINE_SPR
        over320 += sum(on[:LINE_SPR]) > LINE_CELLS
    return len(order), sat[order[-1]][1] & 0x7F, over320, over20


def snapshot(raw):
    """the SAT snapshot of a .sav (a 0.2.x 4 KB save or the s1 images' 8 KB one), or None when the save has none.
    Layout 1 (0.2.6 TEST, and the s1 images before 2026-10-17): the last frame with 20 or more entries, its count capped
    at 80.
    Layout 2 (from 2026-10-17; tag 'S2' at 0x906 and 2 in the last byte): the session's most crowded frame (the latest of
    equals) with its true count, the latest frame of 20 or more with its true count, the most entries any frame end
    closed this session and how many closed more than 80. Bit 15 of a layout-2 true count = a torn copy (a frame start
    came after the thread took the request, before or while it copied: the next frame's table may be mixed in)"""
    if len(raw) < 0x1000:
        return None
    m = bytes(raw[i ^ 1] for i in range(0x1000))       # MCU bytes (the .sav swaps each 16-bit half)
    if m[SNAP_BASE:SNAP_BASE + 4] != b'PSAT':
        return None
    be16 = lambda a: (m[a] << 8) | m[a + 1]
    be32 = lambda a: struct.unpack('>I', m[a:a + 4])[0]
    l2 = m[SNAP_L2:SNAP_L2 + 2] == b'S2' and m[SNAP_T + 23] == 2
    s = dict(layout=2 if l2 else 1, boots=be16(SNAP_BOOT + 4) if m[SNAP_BOOT:SNAP_BOOT + 4] == b'PBOT' else None,
             frames=be32(SNAP_T + 13), ae=be32(SNAP_DISP), af=be32(SNAP_DISP + 4), ad=be32(SNAP_DISP + 8))
    slots = [('crowded' if l2 else 'last', SNAP_BASE + 8, be16(SNAP_BASE + 4), be16(SNAP_BASE + 6) if l2 else None,
              be32(SNAP_DISP + 12) if l2 else s['af'])]
    if l2:
        n = be16(SNAP_L2 + 2)
        slots.append(('latest', SNAP_LATEST, min(n & 0x7FFF, H40_ENTRIES), n, s['af']))
        s.update(most=be16(SNAP_L2 + 4), over80=be32(SNAP_L2 + 6))
    for name, at, capped, true, af in slots:
        sat = sat_entries(m, at)
        mux = mux02(sat)                                # the chip's AF02 multiplex: no line totals (see mux02)
        walk, last, o320, o20 = (None,) * 4 if mux else vdp_lines(sat)
        s[name] = dict(capped=capped, true=None if true is None else true & 0x7FFF, torn=bool(true is not None and
                       true & 0x8000), af=af, walk=walk, last_link=last, lines_over_320px=o320,
                       lines_over_20_sprites=o20, link79=sat[79][1] & 0xFF, mux02=mux, sat=[list(e) for e in sat])
    return s


MUX02_WORDS = ('the chip\'s AF02 multiplex: entries 0-13 at the top of the screen and 14-27 below line 48 share the '
               'console\'s first 14 slots, entries 28-93 fill the other 66')


def pieces(f):
    """a frame's entry count in plain words"""
    if f['true'] is not None:
        n = f['true']
        if n > H40_ENTRIES and f.get('mux02'):
            return '%d sprite pieces (over the console\'s 80: %s%s)' % (
                n, MUX02_WORDS, '; the %d past 94 take turns, frame by frame' % (n - 94) if n > 94 else '')
        return '%d sprite piece%s%s' % (n, '' if n == 1 else 's', ' (over the console\'s 80: %d not in its table that '
                                         'frame)' % (n - H40_ENTRIES) if n > H40_ENTRIES else '')
    if f['capped'] >= H40_ENTRIES and f['link79'] == H40_ENTRIES:
        return ('more than 80 sprite pieces (over the console\'s 80; the count was stored capped at 80, and entry 79 '
                'links on to entry 80)')
    if f['capped'] >= H40_ENTRIES and f.get('mux02'):
        return ('more than 80 sprite pieces (over the console\'s 80; the count was stored capped at 80, and the table is '
                '%s)' % MUX02_WORDS)
    return '%d sprite pieces' % f['capped']            # (at 80: the close cleared entry 79's link, so exactly 80)


def snapshot_lines(s):
    """the snapshot in plain words"""
    if s is None:
        return ['sprite snapshot (save 0x900-0xFFF): none (a RELEASE session, or no frame of 20 or more sprite pieces)']
    vdp = lambda f: ('lines over 320 px / over 20 sprites not modelled for the chip\'s multiplexed table (entries 80-93, '
                     'the console\'s slots 66-79, are not in the save)' if f.get('mux02') else
                     'the console would show %d line%s over 320 px and %d over 20 sprites (MODELLED: its H40 rules on '
                     'the stored table)' % (f['lines_over_320px'], '' if f['lines_over_320px'] == 1 else 's',
                                            f['lines_over_20_sprites']))
    torn = lambda f: (' (TORN COPY: the next frame started before or while it was copied, so its table may hold some '
                      'of the next frame\'s pieces)' if f['torn'] else '')
    L = ['sprite snapshot (TEST, save 0x900-0xFFF, layout %d, boot %s):' % (s['layout'], s['boots'])]
    if s['layout'] == 1:
        f = s['last']
        L.append('  last busy frame (the last frame end with 20 or more pieces, number %d): %s; %s' % (
            f['af'], pieces(f), vdp(f)))
        return L
    c, t = s['crowded'], s['latest']
    L.append('  this session: the most sprite pieces in one frame %d; frames over the console\'s 80: %d' % (
        s['most'], s['over80']))
    L.append('  crowded frame (frame end %d): %s; %s%s' % (c['af'], pieces(c), vdp(c), torn(c)))
    if s['most'] > c['true']:
        L.append('    (the most this session, %d, is more than the kept frame\'s: that frame\'s copy was dropped, the '
                 'next frame started before the snapshot was taken)' % s['most'])
    L.append('  latest busy frame (frame end %d%s): %s; %s%s' % (
        t['af'], ', the same frame' if t['af'] == c['af'] else '', pieces(t), vdp(t), torn(t)))
    return L


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('sav')
    ap.add_argument('--json')
    ap.add_argument('--logs', action='store_true')
    a = ap.parse_args()
    raw = open(a.sav, 'rb').read()
    snap = snapshot(raw)
    try:
        o, why = decode(raw)
    except ValueError as e:
        print('BROKEN: %s' % e)
        print('\n'.join(snapshot_lines(snap)))
        sys.exit(2)
    if o is None:
        print('NO RECORD: %s' % why)
        print('\n'.join(snapshot_lines(snap)))
        sys.exit(1)
    print(report(o, a.logs))
    if o['head']['version'] >= 10:          # from version 10 (test build S3a on): 0x900-0xFFF holds the cart's save
                                            # copies (id 3's second, the
        print('save 0x900-0xFFF: the cart\'s save copies from card S3a on (no sprite snapshot)')   # MegaWire record)
    else:
        print('\n'.join(snapshot_lines(snap)))
    if a.json:
        o['snapshot'] = snap
        json.dump(o, open(a.json, 'w'), indent=1)
    sys.exit(0)


if __name__ == '__main__':
    main()
