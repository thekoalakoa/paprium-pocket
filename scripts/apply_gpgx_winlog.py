"""Instrument GPGX's Paprium cart to log every read of the stream window.

    python scripts/apply_gpgx_winlog.py ../gpgx-build/core/cart_hw/paprium.h

Idempotent: refuses to apply twice. Adds a PAPRIUM_WINLOG build switch and,
when it is 1, appends one record per event to paprium_winlog.bin in the
current directory of the running frontend (RetroArch's working directory).

Why every read goes through ONE hook: bank 0 of the 68000 map carries a
read16 handler (paprium_r16), and vdp_dma_68k_ext takes the handler when
one is set (vdp_ctrl.c:3179). So CPU reads and 68k-bus VDP DMA reads of
0xC000-0xFFFF both land in paprium_r16's default branch. Page turns are
trapped at the top of the same function. Byte reads go via paprium_r8.

Record, 8 bytes, little-endian:
    u8   kind     0 = word read   1 = byte read   2 = page turn   3 = 0xDB cmd   4 = 0xDA cmd   5 = 0xAF cmd
    u8   pad
    u16  address  (kind 0/1: the 68000 address; kind 2: page size; kind 3: cmd arg low)
    u32  stamp    frame counter (high 16) | v_counter (low 16)

The question this exists to answer: are the elevator's window reads
TAPE-shaped (strictly sequential, one read per word, no re-reads, no holes)
or PAGE-shaped? A tape RTL is right by construction only for the first.
"""
import sys

MARK = "PAPRIUM_WINLOG"


def main():
    p = sys.argv[1]
    s = open(p, encoding='utf-8', errors='surrogateescape').read()
    if MARK in s:
        raise SystemExit("already applied")

    # 1. switch + writer, next to DEBUG_MODE
    old = "#define DEBUG_MODE 0"
    assert old in s
    s = s.replace(old, old + """

/* paprium-pocket: window read logger. See scripts/apply_gpgx_winlog.py. */
#define PAPRIUM_WINLOG 1
#if PAPRIUM_WINLOG
#include <stdio.h>
static FILE *winlog_fp = NULL;
static unsigned int winlog_frames = 0;
static void winlog(unsigned char kind, unsigned short address)
{
    unsigned char rec[8];
    unsigned int stamp;
    if (!winlog_fp) {
        winlog_fp = fopen("paprium_winlog.bin", "wb");
        if (!winlog_fp) return;
    }
    stamp = (winlog_frames << 16) | (v_counter & 0xFFFF);
    rec[0] = kind; rec[1] = 0;
    rec[2] = address & 0xFF; rec[3] = address >> 8;
    rec[4] = stamp & 0xFF; rec[5] = (stamp >> 8) & 0xFF;
    rec[6] = (stamp >> 16) & 0xFF; rec[7] = (stamp >> 24) & 0xFF;
    fwrite(rec, 1, 8, winlog_fp);
}
#endif""")

    # 2. page turn: right after decoder_ptr advances
    old = """		paprium_s.decoder_ptr += size;
		paprium_s.decoder_size -= size;
	}"""
    assert old in s
    s = s.replace(old, """		paprium_s.decoder_ptr += size;
		paprium_s.decoder_size -= size;
#if PAPRIUM_WINLOG
		winlog(2, (unsigned short) size);
#endif
	}""")

    # 3. word reads of the window: the default branch of paprium_r16
    old = """	default:
		data = *(uint16 *)(paprium_s.ram + address);
		break;
	}"""
    assert old in s
    s = s.replace(old, """	default:
		data = *(uint16 *)(paprium_s.ram + address);
#if PAPRIUM_WINLOG
		if (address >= 0xC000) winlog(0, (unsigned short) address);
#endif
		break;
	}""")

    # 4. byte reads of the window
    old = "	int data = paprium_s.ram[address^1];"
    assert s.count(old) == 1, s.count(old)
    s = s.replace(old, old + """
#if PAPRIUM_WINLOG
	if (address >= 0xC000) winlog(1, (unsigned short) address);
#endif""")

    # 5. the commands that move the pointer, as epoch markers. paprium_cmd(int
    #    data) takes the whole 16-bit word and derives cmd = data >> 8 on its
    #    first line; hook right after that. (An earlier draft fell back to the
    #    'case 0x1FEA:' label, which is in paprium_r16 - a READ of the command
    #    register - and would have marked epochs on the wrong event.)
    old = """static void paprium_cmd(int data)
{
	int cmd = data >> 8;"""
    assert old in s, "paprium_cmd head not in the expected shape"
    s = s.replace(old, old + """
#if PAPRIUM_WINLOG
	if (cmd == 0xDB) winlog(3, (unsigned short)(data & 0xFF));
	else if (cmd == 0xDA) winlog(4, (unsigned short)(data & 0xFF));
	else if (cmd == 0xAF) winlog(5, 0);
#endif""", 1)

    # 6. frame counter: paprium_audio(int cycles) is called from system.c once
    #    per frame's audio step. v_counter in the stamp orders reads within a
    #    frame; this orders frames.
    old = """void paprium_audio(int cycles)
{"""
    assert old in s, "paprium_audio not found"
    s = s.replace(old, old + """
#if PAPRIUM_WINLOG
	winlog_frames++;
#endif""", 1)

    open(p, 'w', encoding='utf-8', errors='surrogateescape').write(s)
    print("applied to", p)


if __name__ == '__main__':
    main()
