/* da_twin - the GPGX half of the 0xDA payload comparison.
 *
 * The mega-ppm firmware records, for every 0xDA unpack it performs on hardware,
 * the source ROM address, the expanded length, and a CRC32 of the expanded
 * bytes (see docs/CRC_SNAPSHOT.md). This program produces the same three
 * numbers for the same source addresses using the reference decompressors
 * lifted verbatim from Genesis Plus GX's cart_hw/paprium.h.
 *
 * The point of doing it this way rather than instrumenting a live GPGX run:
 * the unpack is a pure function of the compressed bytes at src. It does not
 * depend on scene, frame, or anything else about the run. So the comparison
 * needs no gameplay reproduction at all - feed it the source addresses the
 * hardware recorded and the outputs must agree byte for byte.
 *
 * Both implementations apply the same ^1 endian swizzle to source AND
 * destination. GPGX swizzles relative to decoder_ram + offset while the
 * firmware swizzles the absolute SDRAM address, so the two agree only while
 * the destination is even - every destination we have ever recorded (0x0000
 * and 0x9000) is. If that ever stops being true the comparison is invalid and
 * this note is why.
 *
 * Build:  gcc -O2 -o da_twin da_twin.c
 * Usage:  da_twin <rom.bin> [--swap] < srclist.txt
 *         srclist is one hex source address per line; prints "src len crc".
 *
 * The ROM is not in this repository and must not be added to it.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

typedef uint8_t  uint8;
typedef uint32_t uint;

static uint8 *rom;
static long   rom_len;
static uint8  dst_buf[0x20000];

/* Bounds-checked ROM fetch. A wrong endian convention or a bad source address
 * sends the decoders off the end of the image; without this they read garbage
 * and produce a plausible-looking wrong answer instead of an error. */
static int rom_oob = 0;
static inline uint8 romb(uint a) {
    if (a >= (uint) rom_len) { rom_oob = 1; return 0; }
    return rom[a];
}
static int dst_oob = 0;
static inline void put(int i, uint8 v) {
    if (i < 0 || i >= (int) sizeof dst_buf) { dst_oob = 1; return; }
    dst_buf[i] = v;
}
static inline uint8 get(int i) {
    if (i < 0 || i >= (int) sizeof dst_buf) { dst_oob = 1; return 0; }
    return dst_buf[i];
}

/* --- verbatim from GPGX cart_hw/paprium.h, returning the produced size --- */

static int decoder_lz_rle(uint src)
{
    int size = 0;
    int len, lz = 0, rle = 0, code;
    while (1) {
        int type = romb((src++) ^ 1);
        code = type >> 6;
        len  = type & 0x3F;
        if ((code == 0) && (len == 0)) break;
        else if (code == 1) rle = romb((src++) ^ 1);
        else if (code == 2) lz  = size - romb((src++) ^ 1);
        while (len-- > 0) {
            switch (code) {
            case 0: put((size++) ^ 1, romb((src++) ^ 1)); break;
            case 1: put((size++) ^ 1, rle); break;
            case 2: put((size++) ^ 1, get((lz++) ^ 1)); break;
            case 3: put((size++) ^ 1, 0); break;
            }
        }
        if (rom_oob || dst_oob) return -1;
    }
    return size;
}

static int decoder_lzo(uint src)
{
    int size = 0;
    int len, lz = 0, raw;   /* GPGX leaves lz uninitialised on the state==0 path;
                             * it is computed and then never read there (len==0),
                             * so zeroing it is observationally identical and not UB. */
    int state = 0;
    while (1) {
        int code = romb((src++) ^ 1);
        if (code & 0x80) goto code_80;
        if (code & 0x40) goto code_40;
        if (code & 0x20) goto code_20;
        if (code & 0x10) goto code_10;

        if (state == 0) {
            raw = code & 0x0F;
            if (raw == 0) {
                int extra = 0;
                while (1) { raw = romb((src++) ^ 1); if (raw) break; extra += 255;
                            if (rom_oob) return -1; }
                raw += extra; raw += 15;
            }
            raw += 3;
            len = 0; state = 4;
            goto copy_loop;
        } else if (state < 4) {
            raw = code & 0x03;
            lz  = (code >> 2) & 0x03;
            lz += romb((src++) ^ 1) << 2;
            lz += 1;
            len = 2;
            goto copy_loop;
        } else {
            raw = code & 0x03;
            lz  = (code >> 2) & 0x03;
            lz += romb((src++) ^ 1) << 2;
            lz += 2049;
            len = 3;
            goto copy_loop;
        }

code_10:
        len = code & 0x07;
        if (len == 0) {
            int extra = 0;
            while (1) { len = romb((src++) ^ 1); if (len) break; extra += 255;
                        if (rom_oob) return -1; }
            len += extra; len += 7;
        }
        len += 2;
        lz = ((code >> 3) & 1) << 14;
        code = romb((src++) ^ 1);
        raw = code & 0x03;
        lz += code >> 2;
        lz += romb((src++) ^ 1) << 6;
        lz += 16384;
        if (lz == 16384) break;
        goto copy_loop;

code_20:
        len = code & 0x1F;
        if (len == 0) {
            int extra = 0;
            while (1) { len = romb((src++) ^ 1); if (len) break; extra += 255;
                        if (rom_oob) return -1; }
            len += extra; len += 31;
        }
        len += 2;
        code = romb((src++) ^ 1);
        raw = code & 0x03;
        lz  = code >> 2;
        lz += romb((src++) ^ 1) << 6;
        lz += 1;
        goto copy_loop;

code_40:
        raw = code & 0x03;
        len = ((code >> 5) & 1) + 3;
        lz  = (code >> 2) & 0x07;
        lz += romb((src++) ^ 1) << 3;
        lz += 1;
        goto copy_loop;

code_80:
        raw = code & 0x03;
        len = ((code >> 5) & 0x03) + 5;
        lz  = (code >> 2) & 0x07;
        lz += romb((src++) ^ 1) << 3;
        lz += 1;

copy_loop:
        if (len > 0) state = raw; else state = 4;
        lz = size - lz;
        while (1) {
            if (len > 0)      { put((size++) ^ 1, get((lz++) ^ 1)); len--; }
            else if (raw > 0) { put((size++) ^ 1, romb((src++) ^ 1)); raw--; }
            else break;
        }
        if (rom_oob || dst_oob) return -1;
    }
    return size;
}

static int decoder_type(uint src)
{
    int type = romb((src++) ^ 1);
    if (type == 0x80) return decoder_lz_rle(src);
    if (type == 0x81) return decoder_lzo(src);
    fprintf(stderr, "  unknown decoder type 0x%02X at 0x%X\n", type, src - 1);
    return -1;
}

/* Same polynomial, init and final xor as snap_crc32() in mcu/mame.c. */
static uint crc32_of(const uint8 *p, int n)
{
    static uint tab[256];
    static int  ready = 0;
    if (!ready) {
        for (uint i = 0; i < 256; i++) {
            uint c = i;
            for (int k = 0; k < 8; k++) c = (c & 1) ? (0xEDB88320u ^ (c >> 1)) : (c >> 1);
            tab[i] = c;
        }
        ready = 1;
    }
    uint c = 0xFFFFFFFFu;
    for (int i = 0; i < n; i++) c = tab[(c ^ p[i]) & 0xFF] ^ (c >> 8);
    return c ^ 0xFFFFFFFFu;
}

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "usage: da_twin <rom.bin> [--swap] < srclist\n"); return 2; }
    int swap = (argc > 2 && !strcmp(argv[2], "--swap"));

    FILE *f = fopen(argv[1], "rb");
    if (!f) { perror(argv[1]); return 2; }
    fseek(f, 0, SEEK_END); rom_len = ftell(f); fseek(f, 0, SEEK_SET);
    rom = malloc(rom_len);
    if (fread(rom, 1, rom_len, f) != (size_t) rom_len) { fprintf(stderr, "short read\n"); return 2; }
    fclose(f);
    if (swap) for (long i = 0; i + 1 < rom_len; i += 2) {
        uint8 t = rom[i]; rom[i] = rom[i + 1]; rom[i + 1] = t;
    }
    fprintf(stderr, "rom %s: %ld bytes%s\n", argv[1], rom_len, swap ? " (byteswapped)" : "");

    char line[64];
    while (fgets(line, sizeof line, stdin)) {
        if (line[0] == '\n' || line[0] == '#') continue;
        uint src = (uint) strtoul(line, NULL, 16);
        memset(dst_buf, 0, sizeof dst_buf);
        rom_oob = dst_oob = 0;
        int n = decoder_type(src);
        if (n < 0) { printf("%08X FAIL %s\n", src, rom_oob ? "rom-oob" : "dst-oob"); continue; }
        printf("%08X %d %08X\n", src, n, crc32_of(dst_buf, n));
    }
    return 0;
}
