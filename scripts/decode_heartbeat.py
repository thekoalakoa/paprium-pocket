"""Read the crash-context heartbeat out of Paprium.sav (PPM_HEARTBEAT firmware).

    python scripts/decode_heartbeat.py "D:/Saves/genesis/common/Paprium/Paprium (ROM+Core+OST)/paprium/paprium.sav"

The firmware rewrites a 40-byte record at bram 0xF70 through every frame:
command entry/exit, per object, per walked sprite, per stream DMA, BGM unpack,
frame end. On a hang, exit the core from the Pocket menu; the OS dumps bram to
the .sav and this prints where the firmware stopped. The snapshot region is
16-bit byte-swapped in the file, like the ring.
"""
import struct, sys

HB = 0x910 + 1632
PHASES = {0: 'idle (last command returned)', 1: 'inside a command handler', 2: 'object render (list resolved)',
          3: 'stream DMA queued', 5: 'BGM module unpack', 6: 'frame end'}

def swapped(b):
    return bytes(b[i ^ 1] for i in range(len(b)))

def main():
    d = open(sys.argv[1], 'rb').read()
    if len(d) < 0x1000:
        raise SystemExit("expected a 4096-byte save, got %d" % len(d))
    r = swapped(d[0x900:0x1000])[HB - 0x900:HB - 0x900 + 40]
    if r[:4] != b'PHBT':
        raise SystemExit("no PHBT tag at 0x%X (found %r) - not a heartbeat build, or bram was not dumped" % (HB, r[:4]))
    frame, = struct.unpack('>I', r[4:8])
    cmd, phase, obj, spr = r[8], r[9], r[10], r[11]
    count, cursor, stage, dmac, dmar, satc = struct.unpack('>6H', r[12:24])
    sprinfo, bgm_addr, bgm_len, sp = struct.unpack('>4I', r[24:40])
    print("heartbeat   : frame %d (%.1f s at 60 Hz)" % (frame, frame / 60.0))
    print("last command: 0x%02X   phase: %d = %s" % (cmd, phase, PHASES.get(phase, '?')))
    print("object      : slot %d   sprite %d of count %d   spr_info offset 0x%06X" % (obj, spr, count, sprinfo))
    print("stream      : cursor tile %d   stage 0x%04X   dma_cmd_count %d   dma_remaining %d (%s)"
          % (cursor, stage, dmac, dmar, 'wrapped' if dmar > 0x8000 else 'ok'))
    print("sat_count   : %d" % satc)
    print("BGM         : last unpack at 0x%06X, %d bytes -> ends 0x%06X %s"
          % (bgm_addr, bgm_len, bgm_addr + bgm_len, '(OVER the block cache at 0x1F8000)' if bgm_addr + bgm_len > 0x1F8000 else ''))
    print("stack ptr   : 0x%08X %s" % (sp, '(below the 32 KB WRAM stack top 0x8003FFFC by %d bytes)' % (0x8003FFFC - sp) if 0x80000000 <= sp <= 0x8003FFFC else '(outside WRAM!)'))
    flags = []
    if count > 64: flags.append("count %d > 64: stream_tiles[64] overrun - stack smash" % count)
    if dmac > 120: flags.append("dma_cmd_count %d > 120: descriptor array (121) overrun" % dmac)
    if bgm_addr + bgm_len > 0x1F8000 and bgm_len: flags.append("BGM module overlaps the block cache")
    print("flags       : " + ('; '.join(flags) if flags else 'none'))

if __name__ == '__main__':
    main()
