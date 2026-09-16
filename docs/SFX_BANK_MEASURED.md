# The cartridge's SFX bank, measured against the original samples

Written 2026-09-16 from the sample-bank matching run. The reference material is the
composer's original sound-effect and voice recordings, held privately by the project
and **not in this repository** (WaterMelon's copyright, like the ROM). What follows
is numbers and identifications derived from comparing those recordings with the
bytes in the ROM's SFX bank at `0x25ECA4` (extracted by `scripts/dump_sfx.py`);
no audio is reproduced here.

Three things it settles for this port, and one caveat:

1. **The SFX rate table's last entry is 4800 Hz, not 5333.** Measured entry by entry;
   the divisor table is `{1, 2, 4, 5, 8, 10}`. Six effects currently play 11 % fast.
2. **Both SFX sample formats are companded.** 4-bit entries are 15-level sign-magnitude
   codes around 8 (code 0 never occurs); 8-bit entries follow the same kind of law
   around 128. The linear decode this port inherited from mega-ppm (and that GPGX and
   `dump_sfx.py` share) compresses every effect's dynamics by about 3.3x.
3. **87 of the 127 entries are now identified by name** (see the table), including
   every by-ear identification in `SFX_CATALOGUE.md`.

**Caveat.** The originals prove what the ROM bytes *encode*. Whether the cartridge's
own player decodes them through the same companding law is a separate question that
one isolated hardware capture of a single effect will settle. Until then the decoder
change is a measured correction of the *data*, not yet a verified fidelity claim.

---

Adjudicator's synthesis, 2026-09-16. Inputs: two matchers (`sfxbank/`, `musicbank/`), two SFX-bank
verifiers (`verify_sfxbank/v2/` - complete, all 88 claimed pairs, fresh code, 87 CONFIRMED + 1
PLAUSIBLE; `verify_sfxbank2/` - forced to stop at 21 of 88 pairs, all 21 agreeing), and two
music-bank verifiers (`verify_musicbank/`, `verify_xcorr/`, both complete). Every number below is
from those directories; nothing was re-measured here except the decoder-law arithmetic in
`synthesis/build_identity.py` (normalisation of the published tables). The originals were read
in place by every workflow and no audio was written by this synthesis.

Machine-readable result: `match/identity.json` (127 entries; `verified` is true only where an
independent verifier reproduced the pair with its own code).

Conventions: "corr" is a normalised cross-correlation with the lag free; "null" is the best
correlation the same cart entry reaches against every OTHER original at the matched rate;
a "match" needed corr >= 0.60 and >= null + 0.15, or corr >= 0.45 and >= 4 x null. "Implied Hz"
is 44100 / (the resampling ratio that maximises the correlation, continuous sweep at 0.02 %
steps). "ROM Hz" is what `dump_sfx.py` / GPGX / mega-ppm read from the ROM's own type nibble.

## 1. Headline

- **87 of 127 cart SFX entries are verified copies of 83 composer originals** (56 4-bit, 31 8-bit);
  four originals appear twice (ATK KICK, PICKUP FOOD, ATK PUNCH, COMP TRANS), the second copy
  being a pitched variant in three of the four. One claimed pair (0x14 HIT1 FLESH) is downgraded
  to "related, not a copy". One further pair (0x11 HIT0 BAG) passes the criterion only with the
  companded decoder and only in one verifier's candidate scan: PLAUSIBLE, not verified.
- **The ROM's SFX rate table is measured, entry by entry, and one of its six rates is wrong as
  read:** divisor index 5 is 48000/10 = **4800 Hz**, not 48000/9 = 5333 Hz. Six entries
  (0x22, 0x2C, 0x2F, 0x48, 0x4C, 0x71) currently play 11.1 % fast (+1.8 semitones) in this port,
  in mega-ppm and in GPGX. The other four used classes are exact: 24000.0, 11999.8 +- 2.9,
  9600.1 +- 2.3, 6000.0 +- 0.6 Hz (class means over 77 unpitched verified pairs).
- **Both SFX banks are companded, not linear.** The 4-bit entries are 15-level offset-binary
  sign-magnitude codes centred on 8 (code 0 never occurs, 0 of 717,598 nibbles in 79 entries),
  high nibble first, plain PCM (not ADPCM/delta), with the magnitude growing ~x1.6 per code
  (22.7x = 27 dB from the smallest to the largest step). The 8-bit entries follow the same
  kind of law around 128 (mu-law-like, mu ~ 28-40; code 0 never occurs). The linear decode in
  `dump_sfx.py`, in mega-ppm's `sfx.c`, and in GPGX compresses the dynamics of every effect by
  about 3.3x. Decoding with the companded table raises the correlation against the originals
  in 55 of 56 4-bit pairs and 31 of 32 8-bit pairs (v2 verifier).
- **The music wave bank contains no composer original** (140 originals x 94 programs, two
  decimation hypotheses, continuous rate sweep 4-48 kHz, four independent runs). Its 8-bit
  programs are linear PCM (shown by the one cross-bank pair). Its type->rate mapping is only
  partly measured: rate(type 0)/rate(type 1) = 2.000 +- 0.004 under a same-pitch assumption;
  the absolute rate is unmeasured, and the one datum that bears on it (SFX 0x63 == program 0x5F
  at exactly 2:1) leans towards type 0 = 48000 Hz rather than the 24000 the emulators read.
- **Processing chain, measured:** each cart copy is a trimmed sub-range of the original (head =
  tail = 0 in all 87), decimated with **no anti-alias filter** (aliasing kept), same polarity in
  87/87, zero at code 8 / 128, no dither resolvable.

## 2. Identity table - verified pairs only (87)

Columns: matcher's corr and null; v2 verifier's corr / null (local-mean NCC, fresh code); the
partial verifier's corr / null where it completed; and the playback speed relative to the
original when the cart plays the entry at its measured class rate (1.000x unless the copy was
pitched when it was authored). Implied Hz is the matcher's continuous-sweep value; the v2
verifier agrees within 0.1 % on all 88 and within 0.02 % on 85.

| entry | bits | ROM Hz | original | ratio | implied Hz | corr | null | v2 corr / null | partial verifier corr / null | speed at ROM rate |
|---|---|---|---|---|---|---|---|---|---|---|
| 0x01 | 8 | 9600 | projecty_sfx0 016 ATK KICK | 2.75735 | 15993.6 | 0.904 | 0.445 | 0.904 / 0.444 | 0.904 / 0.444 | 0.600x |
| 0x02 | 8 | 12000 | projecty_sfx0 002 MENU CANCEL | 3.67500 | 12000.0 | 0.827 | 0.314 | 0.828 / 0.314 | 0.828 / 0.314 | 1.000x |
| 0x03 | 8 | 9600 | projecty_sfx0 004 PICKUP FOOD | 4.59375 | 9600.0 | 0.913 | 0.262 | 0.915 / 0.262 | 0.915 / 0.345 | 1.000x |
| 0x04 | 8 | 12000 | projecty_sfx0 005 PICKUP MISC | 3.67500 | 12000.0 | 0.885 | 0.229 | 0.890 / 0.229 | 0.887 / 0.247 | 1.000x |
| 0x05 | 8 | 12000 | projecty_sfx0 004 PICKUP FOOD | 3.67500 | 12000.0 | 0.852 | 0.241 | 0.854 / 0.242 | 0.854 / 0.312 | 1.000x |
| 0x07 | 8 | 9600 | projecty_sfx0 008 JUMP END | 4.59007 | 9607.7 | 0.908 | 0.618 | 0.908 / 0.674 | 0.908 / 0.687 | 1.000x |
| 0x08 | 8 | 12000 | projecty_sfx0 009 WEAPON FALL | 3.67500 | 12000.0 | 0.901 | 0.087 | 0.909 / 0.087 | 0.909 / 0.076 | 1.000x |
| 0x09 | 8 | 12000 | projecty_sfx0 010 ATK PILL | 3.67573 | 11997.6 | 0.855 | 0.199 | 0.860 / 0.202 | 0.860 / 0.205 | 1.000x |
| 0x0A | 8 | 12000 | projecty_sfx0 011 ATK KNIFE | 3.67427 | 12002.4 | 0.935 | 0.253 | 0.939 / 0.254 | 0.939 / 0.282 | 1.000x |
| 0x0B | 8 | 12000 | projecty_sfx0 012 ATK BAR | 3.67500 | 12000.0 | 0.913 | 0.596 | 0.915 / 0.596 | 0.915 / 0.601 | 1.000x |
| 0x0C | 8 | 12000 | projecty_sfx0 013 ATK WHIP | 3.67573 | 11997.6 | 0.932 | 0.458 | 0.932 / 0.465 | 0.931 / 0.459 | 1.000x |
| 0x0E | 8 | 12000 | projecty_sfx0 015 ATK PUNCH | 3.67427 | 12002.4 | 0.919 | 0.658 | 0.920 / 0.660 | 0.920 / 0.660 | 1.000x |
| 0x0F | 8 | 12000 | projecty_sfx0 016 ATK KICK | 3.67427 | 12002.4 | 0.927 | 0.461 | 0.927 / 0.462 | 0.927 / 0.462 | 1.000x |
| 0x10 | 8 | 12000 | projecty_sfx0 017 HIT0 FLESH | 3.67647 | 11995.2 | 0.623 | 0.472 | 0.630 / 0.475 | 0.630 / 0.475 | 1.000x |
| 0x12 | 8 | 12000 | projecty_sfx0 019 HIT0 METAL | 3.67647 | 11995.2 | 0.899 | 0.194 | 0.899 / 0.195 | 0.899 / 0.203 | 1.000x |
| 0x15 | 8 | 12000 | projecty_sfx0 022 HIT1 BAG | 3.67867 | 11988.0 | 0.833 | 0.394 | 0.833 / 0.531 | 0.834 / 0.540 | 1.000x |
| 0x16 | 8 | 9600 | projecty_sfx0 023 HIT1 METAL | 4.59467 | 9598.1 | 0.870 | 0.186 | 0.870 / 0.186 | 0.870 / 0.202 | 1.000x |
| 0x18 | 8 | 9600 | Y Voices rev1 SFX_DEATH_PLAYERM | 4.59375 | 9600.0 | 0.906 | 0.309 | 0.907 / 0.309 | 0.907 / 0.378 | 1.000x |
| 0x1A | 8 | 9600 | Y Voices rev1 SFX_DEATH_ENEM | 4.59375 | 9600.0 | 0.910 | 0.169 | 0.913 / 0.169 | 0.913 / 0.200 | 1.000x |
| 0x1C | 4 | 9600 | Y Voices rev1 SFX_DEATH_BOSSM | 4.59375 | 9600.0 | 0.917 | 0.126 | 0.917 / 0.118 | 0.917 / 0.116 | 1.000x |
| 0x1F | 4 | 12000 | projecty_sfx0 032 SPARK | 3.67500 | 12000.0 | 0.566 | 0.045 | 0.566 / 0.044 | 0.566 / 0.050 | 1.000x |
| 0x20 | 4 | 24000 | projecty_sfx0 033 SPARKLED | 1.83750 | 24000.0 | 0.825 | 0.093 | 0.825 / 0.084 | 0.818 / 0.100 | 1.000x |
| 0x22 | 4 | 5333 | projecty_sfx0 036 COMP TRANS | 9.18566 | 4801.0 | 0.977 | 0.379 | 0.977 / 0.377 | 0.977 / 0.377 | 1.000x |
| 0x23 | 4 | 12000 | projecty_sfx0 037 COMP ALARM0 | 3.67427 | 12002.4 | 0.888 | 0.128 | 0.910 / 0.149 | 0.904 / 0.146 | 1.000x |
| 0x24 | 4 | 6000 | projecty_sfx0 038 COMP ALARM1 | 7.35000 | 6000.0 | 0.892 | 0.198 | 0.935 / 0.198 | 0.935 / 0.198 | 1.000x |
| 0x27 | 4 | 12000 | projecty_sfx0 041 LASER 0 | 3.67500 | 12000.0 | 0.732 | 0.073 | 0.792 / 0.073 | 0.879 / 0.087 | 1.000x |
| 0x29 | 4 | 12000 | projecty_sfx0 043 BREAKGLASS | 3.67427 | 12002.4 | 0.454 | 0.086 | 0.476 / 0.098 | 0.476 / 0.107 | 1.000x |
| 0x2A | 4 | 6000 | projecty_sfx0 044 ELEVATOR START | 7.35000 | 6000.0 | 0.742 | 0.122 | 0.750 / 0.122 | 0.750 / 0.119 | 1.000x |
| 0x2B | 4 | 6000 | projecty_sfx0 046 ELEVATOR DING | 7.35000 | 6000.0 | 0.913 | 0.352 | 0.915 / 0.191 | 0.915 / 0.220 | 1.000x |
| 0x2C | 4 | 5333 | projecty_sfx0 047 ELEVATOR CHUNKLE 0 | 9.18750 | 4800.0 | 0.926 | 0.120 | 0.933 / 0.116 | 0.935 / 0.133 | 1.000x |
| 0x2D | 4 | 6000 | projecty_sfx0 048 ELEVATOR CHUNKLE 1 | 7.35000 | 6000.0 | 0.928 | 0.206 | 0.928 / 0.185 | 0.925 / 0.207 | 1.000x |
| 0x2E | 4 | 6000 | projecty_sfx0 049 TRAIN CHUNKLE 0 | 7.35000 | 6000.0 | 0.935 | 0.135 | 0.936 / 0.131 | 0.936 / 0.131 | 1.000x |
| 0x2F | 4 | 5333 | projecty_sfx0 050 TRAIN CHUNKLE 1 | 9.18750 | 4800.0 | 0.893 | 0.115 | 0.901 / 0.115 | 0.880 / 0.133 | 1.000x |
| 0x31 | 4 | 6000 | projecty_sfx0 052 FLYCAR CHUNKLE 0 | 7.35000 | 6000.0 | 0.608 | 0.087 | 0.608 / 0.083 | 0.715 / 0.106 | 1.000x |
| 0x32 | 4 | 6000 | projecty_sfx0 053 TROLEY CHUNKLE 0 | 7.35000 | 6000.0 | 0.839 | 0.052 | 0.902 / 0.051 | 0.902 / 0.053 | 1.000x |
| 0x33 | 4 | 6000 | Y Voices 008 MINDGAP | 7.35000 | 6000.0 | 0.832 | 0.196 | 0.833 / 0.182 | 0.833 / 0.226 | 1.000x |
| 0x34 | 4 | 6000 | Y Voices 009 STANDCLEAR | 7.35000 | 6000.0 | 0.824 | 0.128 | 0.898 / 0.128 | 0.898 / 0.132 | 1.000x |
| 0x35 | 4 | 6000 | Y Voices 010 APPROACHING | 7.35000 | 6000.0 | 0.786 | 0.229 | 0.918 / 0.229 | 0.918 / 0.222 | 1.000x |
| 0x36 | 4 | 6000 | Y Voices 011 WALK | 7.35000 | 6000.0 | 0.754 | 0.113 | 0.919 / 0.108 | 0.919 / 0.108 | 1.000x |
| 0x37 | 4 | 12000 | Y Voices 001 OUF | 3.67427 | 12002.4 | 0.928 | 0.302 | 0.928 / 0.300 | 0.928 / 0.304 | 1.000x |
| 0x38 | 4 | 6000 | Y Voices 002 HAHAKR b | 7.34853 | 6001.2 | 0.847 | 0.216 | 0.849 / 0.189 | 0.864 / 0.200 | 1.000x |
| 0x39 | 4 | 6000 | Y Voices 003 HAHACN b | 7.34853 | 6001.2 | 0.887 | 0.277 | 0.887 / 0.236 | 0.887 / 0.339 | 1.000x |
| 0x3A | 4 | 12000 | Y Voices 002 HAHAKR | 3.67573 | 11997.6 | 0.911 | 0.186 | 0.912 / 0.186 | 0.912 / 0.201 | 1.000x |
| 0x3B | 4 | 6000 | Y Voices 005 NONONO | 7.34853 | 6001.2 | 0.924 | 0.251 | 0.924 / 0.247 | 0.924 / 0.263 | 1.000x |
| 0x3C | 4 | 6000 | Y Voices 006 UDEAD | 7.35000 | 6000.0 | 0.925 | 0.195 | 0.931 / 0.172 | 0.931 / 0.173 | 1.000x |
| 0x3D | 4 | 9600 | Y Voices 007 IIIIIIII (citizens scream) | 4.59375 | 9600.0 | 0.924 | 0.068 | 0.925 / 0.068 | 0.925 / 0.078 | 1.000x |
| 0x3E | 4 | 6000 | Y Voices 012 00 | 7.35000 | 6000.0 | 0.750 | 0.170 | 0.800 / 0.140 | 0.800 / 0.166 | 1.000x |
| 0x3F | 4 | 6000 | Y Voices 013 01 | 7.35000 | 6000.0 | 0.865 | 0.186 | 0.902 / 0.154 | 0.873 / 0.175 | 1.000x |
| 0x40 | 4 | 6000 | Y Voices 014 02 | 7.35294 | 5997.6 | 0.731 | 0.178 | 0.731 / 0.148 | 0.732 / 0.214 | 1.000x |
| 0x41 | 4 | 6000 | Y Voices 015 03 | 7.35000 | 6000.0 | 0.759 | 0.255 | 0.895 / 0.255 | 0.895 / 0.276 | 1.000x |
| 0x42 | 4 | 6000 | Y Voices 016 04 | 7.35000 | 6000.0 | 0.857 | 0.280 | 0.901 / 0.280 | 0.901 / 0.307 | 1.000x |
| 0x43 | 4 | 6000 | Y Voices 017 05 | 7.35000 | 6000.0 | 0.790 | 0.196 | 0.903 / 0.128 | 0.903 / 0.128 | 1.000x |
| 0x44 | 4 | 6000 | Y Voices 018 06 | 7.35000 | 6000.0 | 0.539 | 0.187 | 0.874 / 0.187 | 0.874 / 0.198 | 1.000x |
| 0x45 | 4 | 6000 | Y Voices 019 07 | 7.35000 | 6000.0 | 0.705 | 0.140 | 0.898 / 0.133 | 0.898 / 0.133 | 1.000x |
| 0x46 | 4 | 6000 | Y Voices 020 08 | 7.35147 | 5998.8 | 0.733 | 0.225 | 0.733 / 0.223 | 0.734 / 0.226 | 1.000x |
| 0x47 | 4 | 6000 | Y Voices 021 09 | 7.35000 | 6000.0 | 0.745 | 0.145 | 0.788 / 0.145 | 0.788 / 0.146 | 1.000x |
| 0x48 | 4 | 5333 | projecty_sfx0 076 AMBIANT BARCHAT0 | 9.18750 | 4800.0 | 0.930 | 0.124 | 0.931 / 0.123 | 0.927 / 0.143 | 1.000x |
| 0x4A | 4 | 6000 | projecty_sfx0 081 SFX_AMBIANT_TV0 | 7.35000 | 6000.0 | 0.908 | 0.070 | 0.922 / 0.052 | 0.922 / 0.044 | 1.000x |
| 0x4B | 4 | 6000 | projecty_sfx0 080 AMBIANT WINDOUT0 | 7.35000 | 6000.0 | 0.937 | 0.086 | 0.943 / 0.065 | 0.943 / 0.070 | 1.000x |
| 0x4C | 4 | 5333 | projecty_sfx0 082 SFX_AMBIANT_AD0 | 9.18750 | 4800.0 | 0.543 | 0.062 | 0.653 / 0.042 | 0.836 / 0.044 | 1.000x |
| 0x4D | 4 | 9600 | projecty_sfx0 031 STEAM | 4.59467 | 9598.1 | 0.531 | 0.073 | 0.563 / 0.075 | 0.563 / 0.079 | 1.000x |
| 0x52 | 8 | 24000 | Y Voices 038 FRESH | 1.83750 | 24000.0 | 0.897 | 0.168 | 0.897 / 0.169 | 0.897 / 0.168 | 1.000x |
| 0x53 | 8 | 12000 | Y Voices 039 PRESENTEDBY | 3.67500 | 12000.0 | 0.746 | 0.202 | 0.751 / 0.202 | 0.751 / 0.202 | 1.000x |
| 0x55 | 4 | 12000 | Y Voices 041 HOHNO | 3.67500 | 12000.0 | 0.940 | 0.146 | 0.943 / 0.146 | 0.943 / 0.187 | 1.000x |
| 0x56 | 4 | 9600 | Y Voices 042 YES | 4.59467 | 9598.1 | 0.790 | 0.187 | 0.790 / 0.187 | 0.790 / 0.190 | 1.000x |
| 0x57 | 8 | 12000 | Y Voices 050 TUG_MOVE0 | 3.67353 | 12004.8 | 0.907 | 0.350 | 0.907 / 0.350 | 0.907 / 0.327 | 1.000x |
| 0x58 | 4 | 12000 | Y Voices 044 GO | 3.67500 | 12000.0 | 0.945 | 0.213 | 0.946 / 0.213 | 0.946 / 0.287 | 1.000x |
| 0x5A | 4 | 6000 | Y Voices 046 BIONAD | 7.35000 | 6000.0 | 0.864 | 0.089 | 0.919 / 0.079 | 0.919 / 0.082 | 1.000x |
| 0x5B | 4 | 9600 | Y Voices 048 SANOPHIXAD | 4.59375 | 9600.0 | 0.796 | 0.140 | 0.797 / 0.110 | 0.906 / 0.119 | 1.000x |
| 0x5C | 8 | 12000 | Y Voices 051 TUG_MOVE1 | 3.67500 | 12000.0 | 0.931 | 0.365 | 0.932 / 0.365 | 0.932 / 0.372 | 1.000x |
| 0x5D | 8 | 12000 | Y Voices 052 TUG_START | 3.67500 | 12000.0 | 0.907 | 0.264 | 0.911 / 0.265 | 0.911 / 0.264 | 1.000x |
| 0x5E | 8 | 12000 | Y Voices 053 DICE_MOVE0 | 3.67500 | 12000.0 | 0.915 | 0.309 | 0.916 / 0.309 | 0.915 / 0.310 | 1.000x |
| 0x5F | 8 | 12000 | Y Voices 054 DICE_MOVE1 | 3.67500 | 12000.0 | 0.930 | 0.352 | 0.930 / 0.352 | 0.930 / 0.406 | 1.000x |
| 0x60 | 8 | 9600 | Y Voices 055 DICE_START | 4.59467 | 9598.1 | 0.912 | 0.255 | 0.913 / 0.254 | 0.910 / 0.252 | 1.000x |
| 0x65 | 8 | 12000 | Y Voices 060 88_MOVE0 | 3.67427 | 12002.4 | 0.931 | 0.359 | 0.931 / 0.360 | 0.931 / 0.359 | 1.000x |
| 0x66 | 8 | 12000 | Y Voices 061 88_MOVE1 | 3.67500 | 12000.0 | 0.945 | 0.554 | 0.945 / 0.554 | 0.945 / 0.554 | 1.000x |
| 0x67 | 8 | 12000 | Y Voices 062 88_START | 3.67500 | 12000.0 | 0.897 | 0.231 | 0.897 / 0.231 | 0.880 / 0.228 | 1.000x |
| 0x6A | 4 | 12000 | Y Voices 066 MURDOCK_MOVE0 | 2.94660 | 14966.4 | 0.829 | 0.333 | 0.840 / 0.339 | 0.840 / 0.355 | 0.802x |
| 0x6B | 4 | 9600 | Y Voices 067 PANG_MOVE0 | 4.59375 | 9600.0 | 0.922 | 0.285 | 0.926 / 0.285 | 0.926 / 0.285 | 1.000x |
| 0x6C | 4 | 9600 | Y Voices 068 RONDO_MOVE0 | 4.59375 | 9600.0 | 0.901 | 0.256 | 0.902 / 0.257 | 0.902 / 0.264 | 1.000x |
| 0x6D | 4 | 9600 | Y Voices 069 RONDO_MOVE1 | 4.59375 | 9600.0 | 0.896 | 0.310 | 0.896 / 0.310 | 0.896 / 0.347 | 1.000x |
| 0x6E | 4 | 9600 | Y Voices 070 CHAVEZ_MOVE0 | 4.59283 | 9601.9 | 0.921 | 0.402 | 0.921 / 0.406 | 0.921 / 0.406 | 1.000x |
| 0x6F | 4 | 12000 | Y Voices 072 BISHOP_MOVE0 | 3.67500 | 12000.0 | 0.917 | 0.289 | 0.918 / 0.223 | 0.918 / 0.292 | 1.000x |
| 0x70 | 4 | 6000 | Y Voices 073 BISHOP_MOVE1 | 7.35000 | 6000.0 | 0.918 | 0.255 | 0.919 / 0.225 | 0.919 / 0.225 | 1.000x |
| 0x71 | 4 | 5333 | Y Voices 075 BISHOP_MOVE3 | 9.18750 | 4800.0 | 0.920 | 0.364 | 0.922 / 0.363 | 0.922 / 0.406 | 1.000x |
| 0x7B | 8 | 12000 | projecty_sfx0 015 ATK PUNCH | 3.89280 | 11328.6 | 0.927 | 0.668 | 0.927 / 0.668 | 0.927 / 0.668 | 1.059x |
| 0x7F | 4 | 9600 | projecty_sfx0 036 COMP TRANS | 4.00480 | 11011.8 | 0.862 | 0.316 | 0.862 / 0.316 | 0.868 / 0.320 | 0.872x |

Cross-checks against the by-ear identifications in `docs/SFX_CATALOGUE.md`: 0x4A "Punk-TV cue"
= SFX_AMBIANT_TV0 (0.922); 0x3D "crowd fleeing" = IIIIIIII (citizens scream) (0.925); 0x08
"something breaking" = WEAPON FALL (0.910); 0x1C "believed fat-enemy death" = SFX_DEATH_BOSSM,
i.e. the BOSS death (0.917) - consistent with the catalogue's finding that the game never
requests 0x1C for the big grunt, whose death is the ordinary SFX_DEATH_ENEM (0x1A) with the
rate-step flag; 0x4B "subway trains ambience" = AMBIANT WINDOUT0 (0.943).

### 2a. Downgraded (identity plausible, copy refuted)

| entry | bits | ROM Hz | original | ratio | implied Hz | corr | null | v2 corr / null | partial verifier corr / null | speed at ROM rate |
|---|---|---|---|---|---|---|---|---|---|---|
| 0x14 | 8 | 12000 | projecty_sfx0 021 HIT1 FLESH | 3.76835 | 11702.8 | 0.663 | 0.406 | 0.664 / 0.406 | 0.663 / 0.420 | 1.025x |

0x14 vs HIT1 FLESH: the numbers reproduce (0.664 at 11703 Hz, null 0.406-0.420) but it is the
only pair of 88 with inverted polarity (r = -0.664), the implied rate is 2.5 % off the named
12000 where the other 33 entries of that class land within 0.04 %, the peak is broad (0.63 at
+-2 %, a noise-burst signature), and the companded template LOWERS the correlation (0.625)
where the other 87 gain +0.01..+0.13. Related take, not a copy. It sits in the bank order
HIT1 FLESH/BAG/METAL = 0x14/0x15/0x16, which supports the identity.

### 2b. Cart entries without a verified original (39)

| entry | bits | ROM Hz | best candidate | corr | at Hz | null | status |
|---|---|---|---|---|---|---|---|
| 0x06 | 8 | 12000 | projecty_sfx0 077 AMBIANT KITCHEN0 | 0.216 | 8820.0 | - | UNMATCHED |
| 0x0D | 4 | 12000 | Y Voices 074 BISHOP_MOVE2 | 0.314 | 11025.0 | - | UNMATCHED |
| 0x11 | 8 | 12000 | projecty_sfx0 018 HIT0 BAG | 0.733 | 11997.6 | 0.422 | PLAUSIBLE-UNVERIFIED |
| 0x13 | 8 | 12000 | projecty_sfx0 020 HIT0 CONCERTE | 0.661 | 12135.9 | 0.567 | UNMATCHED |
| 0x17 | 8 | 12000 | projecty_sfx0 024 HIT1 CONCRETE | 0.583 | 11737.1 | 0.503 | UNMATCHED |
| 0x19 | 8 | 12000 | projecty_sfx0 045 ELEVATOR STOP | 0.607 | 6261.2 | 0.389 | PLAUSIBLE-UNVERIFIED |
| 0x1B | 8 | 12000 | Y Voices 006 UDEAD | 0.299 | 7350.0 | - | UNMATCHED |
| 0x1D | 4 | 12000 | Y Voices 029 X16 | 0.091 | 8000.0 | - | UNMATCHED |
| 0x1E | 4 | 12000 | Y Voices 006 UDEAD | 0.153 | 48000.0 | - | UNMATCHED |
| 0x21 | 4 | 12000 | Y Voices 041 HOHNO | 0.131 | 4363.636363636364 | - | UNMATCHED |
| 0x25 | 8 | 12000 | Y Voices 001 OUF | 0.238 | 24000.0 | - | UNMATCHED |
| 0x26 | 4 | 12000 | projecty_sfx0 040 EXPLODE 1 | 0.252 | 9600.0 | - | UNMATCHED |
| 0x28 | 4 | 6000 | Y Voices 077 NONE_MOVE0 | 0.204 | 48000.0 | - | UNMATCHED |
| 0x30 | 8 | 12000 | projecty_sfx0 017 HIT0 FLESH | 0.66 | 11016.2 | 0.463 | PLAUSIBLE-UNVERIFIED |
| 0x49 | 4 | 6000 | Y Voices 007 IIIIIIII (citizens scream) | 0.284 | 5512.5 | - | UNMATCHED |
| 0x4E | 4 | 12000 | Y Voices 071 MONALISA_MOVE0 | 0.161 | 9600.0 | - | UNMATCHED |
| 0x4F | 4 | 9600 | Y Voices 002 HAHAKR c | 0.17 | 9600.0 | - | UNMATCHED |
| 0x50 | 4 | 9600 | Y Voices 062 88_START | 0.115 | 12000.0 | - | UNMATCHED |
| 0x51 | 4 | 12000 | Y Voices 002 HAHAKR c | 0.133 | 8000.0 | - | UNMATCHED |
| 0x54 | 4 | 12000 | Y Voices 071 MONALISA_MOVE0 | 0.142 | 7350.0 | - | UNMATCHED |
| 0x59 | 4 | 24000 | Y Voices 059 ALEX_START | 0.504 | 14839.5 | 0.232 | UNMATCHED |
| 0x61 | 8 | 12000 | Y Voices 062 88_START | 0.659 | 13037.8 | 0.444 | PLAUSIBLE-UNVERIFIED |
| 0x62 | 8 | 12000 | Y Voices 054 DICE_MOVE1 | 0.486 | 7486.2 | 0.417 | UNMATCHED |
| 0x63 | 4 | 24000 | music program 0x5F (wave bank) | 0.913 | 12000.0 | 0.365 | CROSS-BANK-VERIFIED |
| 0x64 | 8 | 6000 | Y Voices 005 NONONO b | 0.375 | 5899.7 | 0.346 | UNMATCHED |
| 0x68 | 8 | 12000 | Y Voices 052 TUG_START | 0.518 | 5387.2 | 0.321 | UNMATCHED |
| 0x69 | 8 | 12000 | Y Voices 067 PANG_MOVE0 | 0.384 | 6300.0 | - | UNMATCHED |
| 0x72 | 4 | 12000 | Y Voices 077 NONE_MOVE0 | 0.115 | 12000.0 | - | UNMATCHED |
| 0x73 | 4 | 12000 | Y Voices 066 MURDOCK_MOVE0 | 0.145 | 22050.0 | - | UNMATCHED |
| 0x74 | 4 | 9600 | Y Voices 002 HAHAKR c | 0.252 | 8000.0 | - | UNMATCHED |
| 0x75 | 4 | 9600 | Y Voices 077 NONE_MOVE0 | 0.168 | 24000.0 | - | UNMATCHED |
| 0x76 | 4 | 9600 | Y Voices 002 HAHAKR c | 0.296 | 7350.0 | - | UNMATCHED |
| 0x77 | 4 | 12000 | Y Voices 055 DICE_START | 0.035 | 14700.0 | - | UNMATCHED |
| 0x78 | 8 | 12000 | projecty_sfx0 006 PICKUP EXTRA LIFE | 0.415 | 11959.3 | 0.344 | UNMATCHED |
| 0x79 | 4 | 6000 | Y Voices 074 BISHOP_MOVE2 | 0.436 | 23957.0 | 0.313 | UNMATCHED |
| 0x7A | 4 | 6000 | Y Voices 074 BISHOP_MOVE2 | 0.526 | 12091.9 | 0.447 | UNMATCHED |
| 0x7C | 8 | 12000 | Y Voices 074 BISHOP_MOVE2 | 0.533 | 14609.4 | 0.536 | UNMATCHED |
| 0x7D | 8 | 9600 | projecty_sfx0 048 ELEVATOR CHUNKLE 1 | 0.552 | 9654.1 | 0.526 | UNMATCHED |
| 0x7E | 4 | 9600 | projecty_sfx0 036 COMP TRANS | 0.506 | 15945.8 | 0.242 | UNMATCHED |

Notes on the four PLAUSIBLE-UNVERIFIED rows: each passes the match criterion in the v2
verifier's candidate scan with the companded (mu-law) template but not with the linear one,
and none was run by a second verifier. 0x11/HIT0 BAG is the strongest (0.733 vs 0.422 at
11997.6 Hz, in bank order 0x10..0x13 = HIT0 FLESH/BAG/METAL/CONCRETE; verify_xcorr's companded
decode gives 0.722 at 12000 with residual 0.69 - the same residual band as the accepted
noise-burst pairs 0x10/0x1F/0x29/0x4D, 0.78-0.89). The others need the implied rate off the
named class by 8-48 % (0x61 13038, 0x30 11016, 0x19 6261 Hz), which only 0x01/0x6A/0x7B/0x7F
among the verified pairs do, and those four lock exactly onto 0.600x / 0.802x / 1.059x / 0.872x
of a grid rate. Not claimed.

The 25 rows at the null floor (best 0.03-0.39, none above 1.3x its runner-up over 20 rates
in three independent scans) have no original among the originals. The one cross-bank identity: SFX
0x63 (4-bit, "24000") is wave-bank program 0x5F (8-bit) with every second sample kept,
sfx[k] = prog[2k+4], r 0.913 with the linear nibble decode and 0.955 with the companded one,
reproduced by both music-bank verifiers (nulls 0.27-0.56 depending on the length rule).

### 2c. Originals with no cart copy (56 of 140)

All the title/menu/announcer voices (ARCADEMODE, ORIMODE, ARENAMODE, OPTIONS, 64MEG, 96MEG, X16,
ONLYFOR0/1, TITLE, PRESSSTART, MWACTIVATED, GAMEOVER, YOUSCUM, CONGRATS, OK, PURAD, KINGFATAD,
ACHIEVEMENT), the Alex/Sheeva/Monalisa/NONE character voices (ALEX_MOVE0/1/2, ALEX_START,
SHEEVA_MOVE0/1, SHEVA_START, MONALISA_MOVE0, NONE_MOVE0), BISHOP_MOVE2/4, HAHAKR c, HAHACN,
FUCKU, NONONO b, HANDCLAP, SFX_DEATH_BOSSF, SFX_DEATH_ENEF; and the effects MENU SELECT, MENU
ERROR, PICKUP EXTRA LIFE, JUMP START, ATK TASER, HIT0 BAG (see 0x11), HIT0 CONCRETE, HIT1
CONCRETE, COMP CALL, COMP BLEEP, EXPLODE 0/1, CRUMBLE, ELEVATOR STOP (see 0x19), HOOVER
CHUNKLE 0, AMBIANT CHICHAT0/KITCHEN0/WALKWAY0, ELECTRIC ENGINE. Best failed candidates and
scores are listed per original in `sfxbank/RESULT.md` section C and `verify_sfxbank/v2/analyse1.txt`
(best 0.16-0.65 at the named rates; the 0.6+ ones are the HIT thumps against the wrong HIT
entry, and three spurious high-rate hits of short tonal templates). They are not in the music
wave bank either (section 4). Bank versus drop: 48 8-bit and 79 4-bit entries; the originals cover
31 of the 8-bit and 56 of the 4-bit.

Six of these 56 were flagged "PASS" by the v2 verifier's discrete 20-rate scan against the wave
bank (SHEEVA_MOVE0 vs 0x41 0.735, NONE_MOVE0 vs 0x48 0.705, CRUMBLE vs 0x00 0.750, ALEX_START vs
0x40 0.600, SFX_DEATH_ENEF vs 0x40 0.628). Adjudicated NOT matches: the null that scan used
(best OTHER program for the same original) is the wrong one for a 0.05-0.1 s tonal program;
the program-side nulls are 0x41 0.808, 0x48 0.801, 0x00 0.699, 0x40 0.618 (`musicbank/nulls_orig.txt`),
every flag is within 1.07x of them, and verify_musicbank's continuous sweep with residual
(real copies refine to residual 0.05-0.12; these stay at 0.6-0.9) found nothing for any of the 56.

## 3. The rate law, as measured

SFX bank (`type >> 4` = divisor index into a six-entry table; rate = 48000 / divisor):

| index | ROM reading (dump_sfx.py, GPGX, mega-ppm) | measured (continuous sweep vs the originals) | n verified, unpitched | spread | agreement with 48000/N |
|---|---|---|---|---|---|
| 0 | 48000 (/1) | untested - no entry in the 127 uses index 0 | 0 | - | - |
| 1 | 24000 (/2) | 24000.0 | 2 | 24000.0-24000.0 | N = 2 exactly |
| 2 | 12000 (/4) | 11999.8 | 31 | 11988.0-12004.8 | N = 4 exactly |
| 3 | 9600 (/5) | 9600.1 | 15 | 9598.1-9607.7 | N = 5 exactly |
| 4 | 6000 (/8) | 6000.0 | 29 | 5997.6-6001.2 | N = 8 exactly |
| 5 | 5333 (/9) | **4800.2** | 6 | 4800.0-4801.0 | **N = 10, not 9** |

So the divisor table is {1, 2, 4, 5, 8, 10}. The six index-5 entries correlate 0.54-0.98
against their originals at 4800 and 0.03-0.34 at 5333 (pass 1 of both the matcher and the v2
verifier found none of them at 5333); the partial verifier reproduced 0x22 at 4801.0 Hz
(0.977 vs null 0.377). The result does not depend on the decoder: the mu-law template gives the
same class means (11999.8 / 9599.5 / 6000.2 / 4800.2). The verified pairs whose implied rate
is NOT the class rate are exactly four, and each is a second copy of an original that also has
a 1.000x copy, at a ratio that locks to a simple factor of a grid rate: 0x01 ATK KICK 0.600x
at 9600 (0x0F is the 1.000x copy at 12000); 0x7B ATK PUNCH 1.059x = +1 semitone at 12000 (0x0E
unpitched); 0x6A MURDOCK_MOVE0 0.802x (5:4 down) at 12000; 0x7F COMP TRANS 0.872x at 9600
(0x22 is the 1.000x copy at 4800). These are authoring variants, not table errors.

The firmware's flag-0x0100 rate step (PORT_PLAN: index 3 -> 4, 9600 -> 6000 = 0.625x, verified
on hardware) is unchanged by this; what changes is the saturation case: a flagged index-4 entry
steps 6000 -> 4800 (0.800x), not 6000 -> 5333 (0.889x).

Music wave bank (`program_table`: nominal = 48000 / {1,2,4,5,8,9}[type + 1], i.e. types 0/1/2
-> 24000/12000/9600):

- rate(type 0) / rate(type 1) = **2.000 +- 0.004**, from one hit stored five times (0x4A, 0x4B
  type 1; 0x4C, 0x4D, 0x4E type 0): six cross-type pairs at sample-count ratios 1.9900-2.0036,
  best two 2.0000 and 1.9996, r 0.85-0.92, residual 0.38-0.53 (variants, not byte copies;
  within-type pairs 0.87-0.92). This is a RATE ratio only if the five takes were meant at one
  pitch; the bank itself stores one sound at 4:1 sample counts within one type for pitch
  (0x2A = 0x1F held 4x, byte-identical for 95 %; 0x29/0x20 rendered at 4:1, r 0.994), so the
  assumption is stated, not free. Both verifiers reproduced every number.
- Absolute rate: **unmeasured**. No original is in the bank, so no ratio to 44.1 kHz exists.
  The only lever is SFX 0x63 == program 0x5F at exactly 2:1 with both tables naming 24000:
  the SFX class is measured at 24000.0 against two originals (0x20, 0x52), so if the two copies
  were meant at one pitch, program 0x5F runs at 48000 and wave-bank type 0 = 48000, type 1 =
  24000 (index [type], not [type + 1]). If they were meant an octave apart, the 24000 reading
  stands. Nothing among the originals decides it; both music-bank verifiers note that the emulators'
  [type + 1] reading is the only support for 24000.
- Type 2 (0x5B, 0x5D, 0x5E, "9600"): no duplicate involves them; untested.

## 4. Codec

### 4-bit SFX entries (79 in the bank, 56 verified against originals)

Method (matcher, reproduced by v2 on its own alignments): for every verified pair, the aligned
original in units of its own RMS, pooled per cart code; the per-code conditional mean is the
least-squares optimal decoder. Two pools (matcher 37 entries / 338k samples; v2 56 entries /
478k samples), codes 1..15 in original-RMS units:

| code | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| matcher | -2.366 | -1.552 | -1.005 | -0.625 | -0.371 | -0.210 | -0.110 | -0.005 | +0.096 | +0.190 | +0.350 | +0.601 | +0.970 | +1.503 | +2.369 |
| v2 | -2.266 | -1.471 | -0.958 | -0.594 | -0.356 | -0.210 | -0.109 | -0.010 | +0.093 | +0.186 | +0.330 | +0.566 | +0.921 | +1.439 | +2.271 |

Code 0: 0 occurrences in 717,598 nibbles. Symmetric about code 8 (|neg| vs |pos| within 0.05 at
every magnitude). Magnitude m = 1..7 normalised to m = 7, averaged over both pools and both
signs: **0.044, 0.086, 0.152, 0.257, 0.416, 0.643, 1.000** (step ratios 1.95, 1.77, 1.70, 1.62,
1.55, 1.55). Candidate laws at the same points: mu-law mu=16 0.031 0.078 0.148 0.253 0.410
0.646 1; mu=8 0.046 0.109 0.196 0.314 0.475 0.697 1; exp 1.6^(m-7) 0.060 0.095 0.153 0.244
0.391 0.625 1. Decoder scores (mean NCC / mean residual in original-RMS units): linear as
extracted 0.860-0.898 / 0.43-0.48; mu-law 16-28 0.914-0.952 / 0.28-0.34; empirical table
0.914-0.951 / 0.28-0.34 (the two ranges are the two pools; the v2 pool keeps the weak pairs).
The ~x1.6/step exponential, mu-law 8-32 and the empirical table are within 0.003 of each
other; the "exactly 4.0 dB per step" of the music-bank matcher is over-stated (its lowest two
steps, 0.062/0.114 from the cross-bank pair, disagree with the original-referenced 0.044/0.086).

Alternatives refuted per entry (v2, 56 entries, each with its own rate re-sweep): low-nibble-
first wins 0/56 (median -0.28), two's-complement 0/56, sign-magnitude-linear 0/56, delta 0/56,
IMA ADPCM 0/56. On the cross-bank pair: corr(nibble, prog) +0.913 vs corr(nibble, diff(prog))
+0.35, cumsum -0.03, leaky integrators 0.30-0.59. **Plain PCM, one sample per nibble, high
nibble first, 15-level companded offset binary.** The LIVEN "Legacy 4-bit PCM" hypothesis
is consistent with 15 levels and companding but was not tested against that device.

### 8-bit SFX entries (48 in the bank, 31 verified)

Code 0 never occurs (0 of 191,887 samples); the last sample of every 8-bit entry is 128; zero
= code 128 (+0.008). Bin means over 16-code bins (matcher, 28 entries): -2.35 -1.59 -0.99
-0.61 -0.36 -0.21 -0.13 -0.064 | +0.077 +0.119 +0.223 +0.361 +0.605 +0.972 +1.538 +2.344;
code 255 = +2.86. Mu-law mu=40 scores 0.972 / 0.204 against linear 0.902 / 0.426 (mu 28-64 all
>= 0.970; the empirical 256-entry table, in `sfxbank/codec.json`, 0.971). At the bin centres
mu=28 fits the bin means to 0.033 rms, mu=40 to 0.069. Sub-claim "4-bit code = 8-bit code >> 4"
is REFUTED by v2: on the negative side 4-bit code k aligns with 8-bit bin k-1 (ratios 0.87-1.02
to bin k-1 vs 1.46-1.81 to bin k), and truncation would put 3 % of the 8-bit samples (codes
1-15) into nibble 0, which never occurs. Correct statement: the two banks share one magnitude
law (4-bit magnitude m <-> 8-bit magnitudes 16m..16m+15 on both sides); the 4-bit code is
8 +- m, the 8-bit code is 128 +- m.

### Music wave bank (94 programs, 8-bit)

Linear unsigned PCM. Evidence (verify_musicbank, verify_xcorr): decoding program 0x5F with the
SFX 8-bit companded table lowers its correlation with SFX 0x63 from 0.955 to 0.800 (residual
0.30 -> 0.60), and the wave bank uses code 0 (12,616 samples) which the companded SFX 8-bit
bank never emits. (The music-bank matcher's stated evidence - in-bank duplicates correlate
0.97-0.99 - is void: two copies in one code domain correlate whatever the codec.)

## 5. Processing chain (original -> cart copy)

| step | measured | numbers |
|---|---|---|
| trim | cart copy = sub-range of the original | head = tail = 0 in 87/87; start offset 0-0.08 s in most, 0.4-1.3 s for the long chunkles/lasers, 10.2 s for BARCHAT0; lengths 0.11-4.99 s |
| resample | integer-related decimation to the class rate, **no anti-alias filter** | raw-pick model beats the 0.9-Nyquist lowpass model by > 0.02 in 19/88 (0x44 "06" 0.874 vs 0.539, 0x36 WALK 0.919 vs 0.754, 0x35 APPROACHING 0.918 vs 0.786), loses by > 0.02 in 5, tie in 64; the in-bank pairs agree (0x5F -> 0x63 keeps every second sample at phase 2k+4; 0x2A is a 4x zero-order hold of 0x1F) |
| gain | one gain per entry, companded quantiser | linear-fit gains 60k-450k 16-bit units per original-RMS unit are the companding, not a level; after the companded decode the residual is 0.20 (8-bit) / 0.28-0.34 (4-bit) of the original's RMS |
| DC | none | zero code 8 / 128; the +-1000 "dc" of the linear fits is the companding asymmetry |
| polarity | preserved | +1 in 87/87 verified (the one inverted pair is the downgraded 0x14) |
| dither / noise shaping | not resolvable at 4 bits; 8-bit per-code table monotonic, adjacent codes 1-8 % apart | - |
| pitch variants | authored, not table | 0x01 0.600x, 0x6A 0.802x, 0x7B 1.059x, 0x7F 0.872x |

## 6. Consequences for the port

### SFX playback (mega-ppm firmware `repos/mega-ppm/mcu/sfx.c` + `rtl/PAPRIUM/audio_sfx.sv`)

1. **Rate index 5 is 4800 Hz, not 5333.** `aclk_bank` in `audio_sfx.sv` divides the 48 kHz tick
   by {1,2,4,5,8,9}; the comment "5333 -> 48000/9 = 5333.33 Hz, 0.006 % fast and inaudible" is
   about the wrong number - the entry class is 4800 and plays 11.1 % fast (+1.8 semitones).
   Fix: `div9` counts to 9 (0..9, `4'd9`) instead of 8 - same 4-bit register, no extra logic,
   no timing change. Affected entries: 0x22 COMP TRANS, 0x2C ELEVATOR CHUNKLE 0, 0x2F TRAIN
   CHUNKLE 1, 0x48 AMBIANT BARCHAT0, 0x4C SFX_AMBIANT_AD0, 0x71 BISHOP_MOVE3. Also the firmware's
   0x0100 saturation comment ("5 = 5333 Hz is the last rate") and `docs/PORT_PLAN.md` line 6325's
   table. Upstream mega-ppm (`fpga/audio_sfx.sv`, `dac_clocker ... .rate(5333)`) and GPGX carry the
   same error; this is the first place it is measured. Note GPGX's separate music-bank table
   `_rates[] = {2,4,5,8,9,10}` does contain a 10.
2. **The nibble/byte unpack in `sfx_player_update()` is the wrong decoder.** It does
   `(nibble * 65536) / 16 - 32768` and `(byte * 65536) / 256 - 32768` (linear). Measured, the
   codes are companded: replacing them with a 16-entry LUT (4-bit) and a 256-entry LUT or a
   mu-law formula (8-bit) is a firmware-only change (zero RTL, zero timing). A 4-bit LUT at
   the linear decode's peak (28672 at code 15, so peak level is unchanged and the shipped
   `vol * 96 / 128`, `/0x400` and echo-send 84/256 trims keep their meaning at peaks):
   `[-28672(unused), -28672, -18445, -11917, -7377, -4351, -2462, -1262, 0, 1262, 2462, 4351,
   7377, 11917, 18445, 28672]` (code 0 never occurs; clamp it to code 1). For 8-bit,
   `sign(c-128) * 28672 * ((41^(|c-128|/127) - 1) / 40)` (mu=40; mu=28 fits the bin means
   marginally better, 0.033 vs 0.069 rms, and both are inside the measured band).
   Audible consequence of the current decode: every effect's quiet parts (codes 7/9, 6/10) play
   3.2x (10 dB) too loud relative to its peaks - tails, room and breath are exaggerated,
   transients are flat. Which of the two decodes matches the CARTRIDGE's own DAC is not
   proven by the originals: the originals fix what the bytes ENCODE, and a cart that played them
   linearly would sound as the port does now. The isolated-evidence rule applies: confirm with
   one isolated hardware SFX capture (a companded-shaped effect such as 0x1C or 0x3D, level vs
   time against the original) before shipping the LUT as a fidelity claim. The identity work
   makes that capture cheap: the original is now known for 87 entries.
3. **No anti-alias filter** was used when the samples were made; the port should not add one on
   playback either (it does not - `sfx_chan` is a zero-order-hold FIFO paced at `srate`, which is
   what the 4x-hold program 0x2A in the music bank also implies for the cart's own player).
4. **Nothing else changes:** nibble order high-first (confirmed), the 0x0100 rate step
   (0.625x, 9600 -> 6000, unchanged), the by-ear catalogue rows (all confirmed, and 0x1C is the
   BOSS death, not a fat-grunt death), and the SFX FIFO/pacing path.

### Renderer wave-bank mapping (`scripts/wave_roots.py` / `render_wave.py`: `sr = 48000 // RATES[type + 1]`, RATES = {1,2,4,5,8,9})

- The RATIO type 0 : type 1 = 2 is now measured (conditional on the five-take family being one
  pitch); the renderer's 24000 : 12000 has that ratio.
- The ABSOLUTE rate stays an emulator reading. The one datum (SFX 0x63 == program 0x5F at 2:1,
  SFX class measured 24000) says type 0 = 48000 if the copies share a pitch, i.e. `RATES[type]`
  not `RATES[type + 1]`, which would make types 0/1/2 = 48000/24000/12000. For the renderer's
  pitch this is invisible: the wave pitch law is continuous 12-TET measured on hardware and
  the sample roots were fitted at the nominal rate, so a factor-2 rate error cancels in the
  transposition (the GPGX audit already notes this). It would show as BANDWIDTH (a 48000-rate
  program carries content to 24 kHz where the renderer band-limits at 12 kHz) and in the
  0xE0 "sample clock" reading still open in the synth state. Decidable from a hardware capture
  of a single program (0x5F or the 0x4A family) at a known note: spectrum above 12 kHz.
- The `{1,2,4,5,8,9}` list the renderer indexes into is the same list whose last entry the
  SFX measurement just corrected to 10; types 0-2 touch indices 1-3 only, so the correction does
  not reach the renderer, but the list as read is now known to be wrong in one place.
- Program bytes are linear (confirmed): `program_table`'s `- 128` decode is right; do not apply
  the SFX companding table to the wave bank (it lowers the cross-bank correlation 0.955 -> 0.800).

### What stays open

- Whether the cartridge's own player decodes the companded codes (point 2) - needs one isolated
  hardware SFX capture against its now-known original.
- The absolute wave-bank rate (48000 vs 24000 for type 0) - needs a program capture (bandwidth).
- Type 2 of the wave bank - no duplicate, no original, untested.
- SFX index 0 (48000) - no entry uses it.
- 0x11/HIT0 BAG and the three other PLAUSIBLE-UNVERIFIED rows - a second verifier run of the
  v2 candidate scan (`verify_sfxbank2/missed.py` is written, not run).
- The 39 cart entries and 56 originals without a partner: every scan reports them at the null
  floor; nothing among the originals identifies them.

## 7. Where the numbers live

The matching runs, their intermediate tables and the verifiers' re-runs are kept locally with
the originals; they are not in this repository because they sit beside game-derived audio.
Everything a reader needs to check a row is in the tables above: the entry, the named original,
the fitted ratio, the implied rate, the correlation and its null. `scripts/dump_sfx.py` extracts
the cart entries this was measured against.
