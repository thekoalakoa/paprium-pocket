"""Extend the GPGX window logger with 68k-bus VDP DMA destinations.

    python scripts/apply_gpgx_dmalog.py ../gpgx-build/core/vdp_ctrl.c

Requires apply_gpgx_winlog.py to have been applied to paprium.h first (it
defines winlog()). Idempotent.

The window-read log says WHAT the 68000 read from the stream window and in
what order. It cannot say WHERE the VDP put it. This hook records, once per
68k-bus DMA transfer, the source address, the VDP address register, the
code register (target RAM and mode) and the length in words - which is the
"land/index" visibility the Pocket cannot afford at 98% ALM, for free.

It also settles the subway over-read: an 80-word read past a drained page
either belongs to a DMA whose length covered it (consumed) or to none.

Two 8-byte records per DMA, so the existing reader keeps working:
    kind 6   address = VDP address register (dest)   stamp = frame<<16 | v_counter
    kind 7   address = length in words               stamp = 68k source address (24 bit)
             pad     = code register & 0x0F  (0x01 VRAM write, 0x03 CRAM, 0x05 VSRAM)
"""
import sys

MARK = "PAPRIUM_DMALOG"


def main():
    p = sys.argv[1]
    s = open(p, encoding='utf-8', errors='surrogateescape').read()
    if MARK in s:
        raise SystemExit("already applied")

    old = """static void vdp_dma_68k_ext(unsigned int length)
{"""
    assert old in s
    s = s.replace(old, old + """
#ifdef PAPRIUM_WINLOG_EXTERN
  /* PAPRIUM_DMALOG: see scripts/apply_gpgx_dmalog.py */
  {
    extern void winlog_ext(unsigned char kind, unsigned char pad, unsigned short address, unsigned int stamp);
    uint32 src0 = (reg[23] << 17) | (dma_src << 1);
    winlog_ext(6, 0, addr, 0);
    winlog_ext(7, code & 0x0F, (unsigned short) length, src0);
  }
#endif""", 1)
    # vdp_ctrl.c is a different translation unit from paprium.h's static
    # winlog(); expose a thin extern in paprium.h that stamps the frame for
    # kind 6 and passes kind 7's source through untouched.
    open(p, 'w', encoding='utf-8', errors='surrogateescape').write(s)

    ph = p.replace('vdp_ctrl.c', 'cart_hw/paprium.h')
    h = open(ph, encoding='utf-8', errors='surrogateescape').read()
    assert "PAPRIUM_WINLOG" in h, "apply_gpgx_winlog.py first"
    if "winlog_ext" not in h:
        old = "static void winlog(unsigned char kind, unsigned short address)"
        assert old in h
        # insert the extern wrapper right after winlog()'s closing brace
        i = h.index(old)
        j = h.index("\n}\n", i) + 3
        h = h[:j] + """void winlog_ext(unsigned char kind, unsigned char pad, unsigned short address, unsigned int stamp)
{
    unsigned char rec[8];
    if (!winlog_fp) {
        winlog_fp = fopen("paprium_winlog.bin", "wb");
        if (!winlog_fp) return;
    }
    if (kind == 6) stamp = (winlog_frames << 16) | (v_counter & 0xFFFF);
    rec[0] = kind; rec[1] = pad;
    rec[2] = address & 0xFF; rec[3] = address >> 8;
    rec[4] = stamp & 0xFF; rec[5] = (stamp >> 8) & 0xFF;
    rec[6] = (stamp >> 16) & 0xFF; rec[7] = (stamp >> 24) & 0xFF;
    fwrite(rec, 1, 8, winlog_fp);
}
""" + h[j:]
        open(ph, 'w', encoding='utf-8', errors='surrogateescape').write(h)
    print("applied to", p, "and", ph, "- build vdp_ctrl.o with -DPAPRIUM_WINLOG_EXTERN")


if __name__ == '__main__':
    main()
