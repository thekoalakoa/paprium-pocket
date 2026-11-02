/* Copyright (C) 2026 Marsupial Solutions LLC
   SPDX-License-Identifier: GPL-3.0-or-later */
/* tests/stub_tests.c - host unit tests of the board-layer parts that need no hardware (built by fwbuild.py stubs).
 * Since test build 4b (2026-10-22, a firmware build B Jam tested on his hardware): the boot-cache stub's pure parts
 * (board/pocket/boot/boot_cache.c): the bitwise CRC-32, the overlay header check and the state choice from XLINK CACHE
 * (the board-dependent boot_cache_boot is RV32-only, proven by tests/equiv/cache4b.py). Stages are the steps of the
 * 0.3.0 work (README.md, "Terms"). */
#include <stdio.h>
#include <string.h>
#include "pocket_map.h"
#include "boot_cache.h"

static int fails;
#define CHECK(c, ...) do { if (c) printf("PASS "); else { printf("FAIL "); fails++; } printf(__VA_ARGS__); printf("\n"); } while (0)

int main(void)
{
    /* the standard CRC-32 check value */
    CHECK(boot_crc32("123456789", 9) == 0xCBF43926u, "boot_crc32(\"123456789\") == 0xCBF43926");
    /* stage 3: the SRAM image's word CRC == the bytewise CRC on the same bytes (65 lengths, 0-256 B, varied data) */
    {
        static uint32_t wd[64];
        uint32_t s = 0x12345678u, bad = 0u;
        for (unsigned n = 0; n <= 64; n++) {
            for (unsigned i = 0; i < 64; i++) {
                s = s * 1664525u + 1013904223u;
                wd[i] = s ^ (i * 0x01010101u);
            }
            if (boot_crc32_words(wd, 4u * n) != boot_crc32(wd, 4u * n))
                bad++;
        }
        CHECK(bad == 0u, "boot_crc32_words == boot_crc32 on 65 lengths (0-256 B)");
    }
    static uint32_t ov[64];
    boot_overlay_hdr *h = (boot_overlay_hdr *) ov;
    for (unsigned i = 4; i < 64; i++) ov[i] = i * 2654435761u;
    h->magic = BOOT_OVERLAY_MAGIC; h->length = 60 * 4; h->entry = sizeof *h;
    h->crc32 = boot_crc32(h + 1, h->length);
    CHECK(boot_overlay_ok(h, sizeof ov), "intact overlay accepted");
    CHECK(boot_cache_check(0u, h, sizeof ov) == BOOT_CACHE_FIRST_BOOT, "cache invalid + overlay -> FIRST_BOOT");
    CHECK(boot_cache_check(POCKET_CACHE_VALID | 0x152100u, h, sizeof ov) == BOOT_CACHE_VALID,
          "CACHE.VALID -> VALID (a warm boot: the overlay is not looked at)");
    ov[20] ^= 1;
    CHECK(!boot_overlay_ok(h, sizeof ov), "one flipped bit rejected");
    CHECK(boot_cache_check(0u, h, sizeof ov) == BOOT_CACHE_SILENT, "cache invalid + a changed overlay -> SILENT");
    ov[20] ^= 1; h->length = sizeof ov;
    CHECK(!boot_overlay_ok(h, sizeof ov), "length past the room rejected");
    h->length = 60 * 4; h->entry = 0;
    CHECK(!boot_overlay_ok(h, sizeof ov), "an entry inside the header rejected");
    h->entry = sizeof *h + h->length;
    CHECK(!boot_overlay_ok(h, sizeof ov), "an entry past the bytes rejected");
    h->entry = sizeof *h; h->magic = 0;
    CHECK(boot_cache_check(0u, h, sizeof ov) == BOOT_CACHE_SILENT, "no magic (overwritten by .bss) -> SILENT");
    return fails != 0;
}
