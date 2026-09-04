"""Read paprium_winlog.bin (from apply_gpgx_winlog.py) and answer one question:

    are the game's reads of the stream window TAPE-shaped or PAGE-shaped?

    python scripts/analyze_winlog.py paprium_winlog.bin

A tape (the real cartridge, and the Pocket RTL) advances one word per read
and does not care which address was read. GPGX's page model copies 0x4000
(mode 2) or 0x800 (mode 7) bytes into the mirror on a read at exactly 0xC000
and lets the 68000 read anywhere inside it. The two agree only if, between
one re-point and the next, the 68000 reads strictly sequentially from the
start: address == previous + 2, every time, no re-reads, no holes, and no
turning the page early.

An EPOCH here is delimited by the events the firmware's epoch counter also
uses - the commands that move the pointer (0xDA, 0xDB, 0xAF) - and by page
turns. Per epoch this reports the count of reads and the count of each
deviation from a tape:

    rereads    address <= previous     (a tape would have moved on)
    holes      address >  previous + 2 (a tape would have delivered the
                                        skipped words to nobody)
    bytes      8-bit reads              (a tape advances a word per strobe;
                                        two byte reads of one word = +2)
    early      a page turned before 0x4000 (or 0x800) bytes were read from
               the previous one - GPGX skips to the next page boundary, a
               tape stays where it is

Record: u8 kind, u8 pad, u16 address, u32 stamp  (frame<<16 | v_counter).
"""
import struct
import sys
from collections import Counter

KIND = {0: 'word', 1: 'byte', 2: 'page', 3: 'DB', 4: 'DA', 5: 'AF', 6: 'dma', 7: 'dma+'}


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    d = open(sys.argv[1], 'rb').read()
    n = len(d) // 8
    if n == 0:
        raise SystemExit("empty log - the core never touched the window (or PAPRIUM_WINLOG was 0)")
    recs = [struct.unpack_from('<BBHI', d, i * 8) for i in range(n)]
    kinds = Counter(r[0] for r in recs)
    print("records : %d   %s" % (n, "  ".join("%s %d" % (KIND.get(k, k), c) for k, c in sorted(kinds.items()))))
    frames = recs[-1][3] >> 16
    print("frames  : %d   (%.1f s at 60 Hz)" % (frames, frames / 60.0))

    # walk epochs
    epochs = []
    cur = None

    def close(reason, early=False):
        # 'early' belongs to the epoch being CLOSED - the page that was turned
        # before it was finished - not to the epoch that starts afterwards.
        if cur is not None and cur['reads']:
            cur['end'] = reason
            cur['early'] = early
            epochs.append(dict(cur))

    prev = None
    page_size = None
    page_read = 0
    # 68k-bus VDP DMA records (apply_gpgx_dmalog.py): kind 6 carries the VDP
    # address register and the frame stamp, kind 7 the length (words), the
    # code register in the pad byte, and the 68000 source in the stamp.
    dmas = []
    pend = None
    for kind, pad, addr, stamp in recs:
        if kind == 6:
            pend = (stamp >> 16, stamp & 0xFFFF, addr)
        elif kind == 7 and pend is not None:
            dmas.append({'frame': pend[0], 'vc': pend[1], 'dest': pend[2],
                         'code': pad, 'len': addr, 'src': stamp})
            pend = None

    for kind, _, addr, stamp in recs:
        fr = stamp >> 16
        if kind in (6, 7):
            continue
        if kind in (3, 4, 5, 2):
            if kind == 2:
                # A page turn is "early" only against a page opened in THIS
                # re-point epoch and not yet read to its end. The first page
                # after a 0xDA/0xDB/0xAF is judged against nothing.
                early = page_size is not None and page_read < page_size
                close('page', early)
                cur = {'start': fr, 'reads': 0, 'rereads': 0, 'holes': 0, 'bytes': 0,
                       'first': None, 'last': None, 'page': addr, 'early': False}
                page_size = addr
                page_read = 0
            else:
                close(KIND[kind])
                cur = {'start': fr, 'reads': 0, 'rereads': 0, 'holes': 0, 'bytes': 0,
                       'first': None, 'last': None, 'page': None, 'early': False}
                page_size = None       # a re-point starts fresh
                page_read = 0
            prev = None
            continue
        if cur is None:
            cur = {'start': fr, 'reads': 0, 'rereads': 0, 'holes': 0, 'bytes': 0,
                   'first': None, 'last': None, 'page': None, 'early': False}
        cur['reads'] += 1
        if cur['first'] is None:
            cur['first'] = addr
        cur['last'] = addr
        if kind == 1:
            cur['bytes'] += 1
            step = 1
        else:
            step = 2
        if prev is not None:
            if addr <= prev:
                cur['rereads'] += 1
            elif addr > prev + 2:
                cur['holes'] += 1
        prev = addr
        page_read += step
    close('end')

    print()
    print("EPOCHS  (delimited by 0xDA / 0xDB / 0xAF and page turns)")
    print("   #   frame   first    last    reads  rereads  holes  bytes  early  ended-by")
    bad = 0
    for i, e in enumerate(epochs):
        flag = ""
        if e['rereads'] or e['holes'] or e['bytes'] or e['early']:
            bad += 1
            flag = "  <-- not tape-shaped"
        print("  %3d  %6d  0x%04X  0x%04X  %6d  %7d  %5d  %5d  %5s  %s%s"
              % (i, e['start'], e['first'], e['last'], e['reads'], e['rereads'],
                 e['holes'], e['bytes'], 'YES' if e['early'] else '-', e['end'], flag))

    tot_reads = sum(e['reads'] for e in epochs)
    tot_re = sum(e['rereads'] for e in epochs)
    tot_ho = sum(e['holes'] for e in epochs)
    tot_by = sum(e['bytes'] for e in epochs)
    tot_ea = sum(1 for e in epochs if e['early'])

    if dmas:
        tgt = {1: 'VRAM', 3: 'CRAM', 5: 'VSRAM'}
        win = [d for d in dmas if 0xC000 <= (d['src'] & 0xFFFF) <= 0xFFFF and (d['src'] >> 16) == 0]
        print()
        print("68K-BUS VDP DMA  (%d transfers, %d sourced from the stream window)" % (len(dmas), len(win)))
        print("   frame   vc   src       dest    target   words")
        for d in win[:60]:
            print("  %6d  %3d  0x%06X  0x%04X  %-6s  %5d"
                  % (d['frame'], d['vc'], d['src'], d['dest'], tgt.get(d['code'], '0x%X' % d['code']), d['len']))
        if len(win) > 60:
            print("  ... %d more" % (len(win) - 60))
        # Cross-reference: for every epoch that read PAST a drained page (the
        # over-read), was there a DMA whose source range covers those words?
        # A DMA that does -> the words were CONSUMED into VRAM at 'dest'.
        for i, e in enumerate(epochs):
            if e['rereads'] and e['page']:
                lo = 0xC000 + e['page']       # first over-read byte address
                hits = [d for d in win if d['frame'] in (e['start'], e['start'] + 1)
                        and (d['src'] & 0xFFFF) <= lo < (d['src'] & 0xFFFF) + d['len'] * 2]
                if hits:
                    print("  epoch %d over-read is INSIDE a DMA: dest 0x%04X %s, %d words from 0x%04X -> CONSUMED"
                          % (i, hits[0]['dest'], tgt.get(hits[0]['code'], '?'), hits[0]['len'], hits[0]['src'] & 0xFFFF))
                else:
                    print("  epoch %d over-read is covered by NO DMA in its frames -> not consumed by DMA" % i)

    print()
    print("VERDICT")
    print("  epochs %d   reads %d   rereads %d   holes %d   byte reads %d   early page turns %d"
          % (len(epochs), tot_reads, tot_re, tot_ho, tot_by, tot_ea))
    if bad == 0:
        print("  TAPE-SHAPED. Every epoch reads strictly sequentially from its start,")
        print("  one word per read, and no page is turned early. A tape that advances")
        print("  once per delivered word is correct BY CONSTRUCTION for this pattern;")
        print("  only a miscount on the Pocket can break it. The epoch counter's")
        print("  question stands unchanged.")
    else:
        print("  PAGE-SHAPED in %d of %d epochs. The game's read pattern is one GPGX's" % (bad, len(epochs)))
        print("  page model tolerates and a tape does not. The Pocket RTL and the")
        print("  reference emulator DIVERGE for this game on those epochs regardless")
        print("  of any miscount - a different finding from the double-advance story,")
        print("  and one no counter on the Pocket would ever show. Read the flagged")
        print("  rows: which kind of deviation, and whether it sits in the background")
        print("  payload (pointer below 0x9000 on the firmware side) or the sprite pad.")


if __name__ == '__main__':
    main()
