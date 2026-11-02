# The mailbox gate tables

Written by `tests/equiv/gatelock.py --table` from the cart chip's behaviour and checked against it on
every run (`tests/run_all.py`: `--check-table`). For each command index, on
mailbox B (`$1FEA`) and mailbox A (`$1FEC`), before C6 (after the app init) and after the game's own boot posts
and C6, every form the check posts and the cart chip's answer: `accepted`, `refused N` (2 default, 5 queue
full, 6 not ready, 7 bad arguments: `$1FE6` bit 9 for B, 10 for A, and the event N | r6 << 8) or `finish only`
(no request bit). The forms are posted one after another, so an answer can depend on the forms before it (a
second E7 while a send is pending, B6 without a session, 8C while a song is loading). Our firmware gives the same
answer, register words, events, register writes, cart RAM, zoom block and save in every row. A build that
runs the cart's MegaWire code is compared on the MegaWire rows too, each sampled after both sides' next
MegaWire task runs where the task has work waiting (the aligned sampling, tests/equiv/gatelock.py); on a
build without it those rows are marked `(megawire)`. Two named exceptions are listed in gatelock.py
(docs/ALLOWLIST.md, row B59, and the A858 page rule). Arguments read from the player's ROM (stream addresses,
C6's arguments) are not written here.

## Index 00

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 80xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | C0xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | 0042 | 0000 0000 0000 0000 | no request bit | finish only |
| before C6 | B | 4000 | 0000 0000 0000 0000 | no request bit | finish only |
| before C6 | A | 0080 | - | mailbox A index 00 | refused 2 |
| before C6 | A | C0FF | - | mailbox A index 00, high bits and low byte set | refused 2 |
| before C6 | A | 0000 | - | mailbox A without the request bit | finish only |
| after C6 | B | 80xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | C0xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | 0042 | 0000 0000 0000 0000 | no request bit | finish only |
| after C6 | B | 4000 | 0000 0000 0000 0000 | no request bit | finish only |
| after C6 | A | 0080 | - | mailbox A index 00 | refused 2 |
| after C6 | A | C0FF | - | mailbox A index 00, high bits and low byte set | refused 2 |
| after C6 | A | 0000 | - | mailbox A without the request bit | finish only |

## Index 01

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 8100 | 0000 0000 0000 0000 | 81 flags 00 | accepted |
| before C6 | B | C100 | 1234 0000 0000 0000 | 81 flags 00 with the argument flag | accepted |
| before C6 | B | 8102 | 0000 0000 0000 0000 | 81 flags 02 | accepted |
| before C6 | B | C102 | 1234 0000 0000 0000 | 81 flags 02 with the argument flag | accepted |
| before C6 | B | 8104 | 0000 0000 0000 0000 | 81 flags 04 | accepted |
| before C6 | B | C104 | 1234 0000 0000 0000 | 81 flags 04 with the argument flag | accepted |
| before C6 | B | 8108 | 0000 0000 0000 0000 | 81 flags 08 | accepted |
| before C6 | B | C108 | 1234 0000 0000 0000 | 81 flags 08 with the argument flag | accepted |
| before C6 | B | 810E | 0000 0000 0000 0000 | 81 flags 0E | accepted |
| before C6 | B | C10E | 1234 0000 0000 0000 | 81 flags 0E with the argument flag | accepted |
| before C6 | B | 810F | 0000 0000 0000 0000 | 81 flags 0F | accepted |
| before C6 | B | C10F | 1234 0000 0000 0000 | 81 flags 0F with the argument flag | accepted |
| before C6 | A | 0180 | - | mailbox A index 01 | accepted |
| before C6 | A | C1FF | - | mailbox A index 01, high bits and low byte set | accepted |
| before C6 | A | 0100 | - | mailbox A without the request bit | finish only |
| after C6 | B | 8100 | 0000 0000 0000 0000 | 81 flags 00 | accepted |
| after C6 | B | C100 | 1234 0000 0000 0000 | 81 flags 00 with the argument flag | accepted |
| after C6 | B | 8102 | 0000 0000 0000 0000 | 81 flags 02 | accepted |
| after C6 | B | C102 | 1234 0000 0000 0000 | 81 flags 02 with the argument flag | accepted |
| after C6 | B | 8104 | 0000 0000 0000 0000 | 81 flags 04 | accepted |
| after C6 | B | C104 | 1234 0000 0000 0000 | 81 flags 04 with the argument flag | accepted |
| after C6 | B | 8108 | 0000 0000 0000 0000 | 81 flags 08 | accepted |
| after C6 | B | C108 | 1234 0000 0000 0000 | 81 flags 08 with the argument flag | accepted |
| after C6 | B | 810E | 0000 0000 0000 0000 | 81 flags 0E | accepted |
| after C6 | B | C10E | 1234 0000 0000 0000 | 81 flags 0E with the argument flag | accepted |
| after C6 | B | 810F | 0000 0000 0000 0000 | 81 flags 0F | accepted |
| after C6 | B | C10F | 1234 0000 0000 0000 | 81 flags 0F with the argument flag | accepted |
| after C6 | A | 0180 | - | mailbox A index 01 | accepted |
| after C6 | A | C1FF | - | mailbox A index 01, high bits and low byte set | accepted |
| after C6 | A | 0100 | - | mailbox A without the request bit | finish only |

## Index 02

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 82xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| before C6 | B | C2xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| before C6 | A | 0280 | - | mailbox A index 02 | accepted |
| before C6 | A | C2FF | - | mailbox A index 02, high bits and low byte set | accepted |
| after C6 | B | 82xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | C2xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | A | 0280 | - | mailbox A index 02 | accepted |
| after C6 | A | C2FF | - | mailbox A index 02, high bits and low byte set | accepted |

## Index 03

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 8300 | 0000 0000 0000 0000 | 83 n = 0 (the stamp) | accepted |
| before C6 | B | 8310 | 0000 0000 0000 0000 | 83 n = 0 (the stamp) | accepted |
| before C6 | B | 83F0 | 0000 0000 0000 0000 | 83 n = 0 (the stamp) | accepted |
| before C6 | B | C300 | 0000 0000 0000 0000 | 83 n = 0 (the stamp) | accepted |
| before C6 | A | 0380 | - | mailbox A index 03 | accepted |
| before C6 | A | C3FF | - | mailbox A index 03, high bits and low byte set | accepted |
| after C6 | B | 8300 | 0000 0000 0000 0000 | 83 n = 0 (the stamp) | accepted |
| after C6 | B | 8310 | 0000 0000 0000 0000 | 83 n = 0 (the stamp) | accepted |
| after C6 | B | 83F0 | 0000 0000 0000 0000 | 83 n = 0 (the stamp) | accepted |
| after C6 | B | C300 | 0000 0000 0000 0000 | 83 n = 0 (the stamp) | accepted |
| after C6 | A | 0380 | - | mailbox A index 03 | accepted |
| after C6 | A | C3FF | - | mailbox A index 03, high bits and low byte set | accepted |

## Index 04

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | A | 0480 | - | mailbox A index 04 | accepted |
| before C6 | A | C4FF | - | mailbox A index 04, high bits and low byte set | accepted |
| before C6 | B | 8400 | 0000 0000 0000 0000 | 84 | accepted |
| before C6 | A | 0480 | - | mailbox A 84 | accepted |
| after C6 | A | 0480 | - | mailbox A index 04 | accepted |
| after C6 | A | C4FF | - | mailbox A index 04, high bits and low byte set | accepted |
| after C6 | B | 8400 | 0000 0000 0000 0000 | 84 | accepted |
| after C6 | A | 0480 | - | mailbox A 84 | accepted |

## Index 06

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 8600 | 0000 0000 0000 0000 | C6 without the argument flag | refused 7 |
| before C6 | A | 0680 | - | mailbox A index 06 | refused 7 |
| before C6 | A | C6FF | - | mailbox A index 06, high bits and low byte set | refused 7 |
| before C6 | B | C600 | from the ROM | C6 (the set-up) | accepted |
| after C6 | B | 8600 | 0000 0000 0000 0000 | C6 without the argument flag | refused 7 |
| after C6 | A | 0680 | - | mailbox A index 06 | refused 7 |
| after C6 | A | C6FF | - | mailbox A index 06, high bits and low byte set | refused 7 |
| after C6 | B | C600 | from the ROM | a second C6 | accepted |

## Index 07

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 87xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | C7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 0780 | - | mailbox A index 07 | refused 2 |
| before C6 | A | C7FF | - | mailbox A index 07, high bits and low byte set | refused 2 |
| after C6 | B | 87xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | C7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 0780 | - | mailbox A index 07 | refused 2 |
| after C6 | A | C7FF | - | mailbox A index 07, high bits and low byte set | refused 2 |

## Index 08

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 88xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | C8xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | 8800 | 0000 0000 0000 0000 | 88 00 | refused 6 |
| before C6 | B | 887F | 0000 0000 0000 0000 | 88 7F | refused 6 |
| before C6 | B | 8802 | 0000 0000 0000 0000 | 88 02 (the game's audio mode) | refused 6 |
| before C6 | A | 0880 | - | mailbox A index 08 | refused 6 |
| before C6 | A | C8FF | - | mailbox A index 08, high bits and low byte set | refused 6 |
| after C6 | B | 88xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | C8xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | 8800 | 0000 0000 0000 0000 | 88 00 | accepted |
| after C6 | B | 887F | 0000 0000 0000 0000 | 88 7F | accepted |
| after C6 | B | 8802 | 0000 0000 0000 0000 | 88 02 (the game's audio mode) | accepted |
| after C6 | A | 0880 | - | mailbox A index 08 | accepted |
| after C6 | A | C8FF | - | mailbox A index 08, high bits and low byte set | accepted |

## Index 09

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 89xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | C9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | 8900 | 0000 0000 0000 0000 | C9 00 without arguments | refused 6 |
| before C6 | B | C900 | 0040 0002 0000 0000 | C9 00 | refused 6 |
| before C6 | B | 897F | 0000 0000 0000 0000 | C9 7F without arguments | refused 6 |
| before C6 | B | C97F | 0040 0002 0000 0000 | C9 7F | refused 6 |
| before C6 | B | 8980 | 0000 0000 0000 0000 | C9 80 without arguments | refused 6 |
| before C6 | B | C980 | 0040 0002 0000 0000 | C9 80 | refused 6 |
| before C6 | B | 89FF | 0000 0000 0000 0000 | C9 FF without arguments | refused 6 |
| before C6 | B | C9FF | 0040 0002 0000 0000 | C9 FF | refused 6 |
| before C6 | A | 0980 | - | mailbox A index 09 | refused 6 |
| before C6 | A | C9FF | - | mailbox A index 09, high bits and low byte set | refused 6 |
| after C6 | B | 89xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | C9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | 8900 | 0000 0000 0000 0000 | C9 00 without arguments | accepted |
| after C6 | B | C900 | 0040 0002 0000 0000 | C9 00 | accepted |
| after C6 | B | 897F | 0000 0000 0000 0000 | C9 7F without arguments | accepted |
| after C6 | B | C97F | 0040 0002 0000 0000 | C9 7F | accepted |
| after C6 | B | 8980 | 0000 0000 0000 0000 | C9 80 without arguments | accepted |
| after C6 | B | C980 | 0040 0002 0000 0000 | C9 80 | accepted |
| after C6 | B | 89FF | 0000 0000 0000 0000 | C9 FF without arguments | accepted |
| after C6 | B | C9FF | 0040 0002 0000 0000 | C9 FF | accepted |
| after C6 | A | 0980 | - | mailbox A index 09 | accepted |
| after C6 | A | C9FF | - | mailbox A index 09, high bits and low byte set | accepted |

## Index 0A

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 8Axx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | CAxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | 8A00 | 0000 0000 0000 0000 | CA 00 without arguments | refused 6 |
| before C6 | B | CA00 | 00C0 0002 0000 0000 | CA 00 | refused 6 |
| before C6 | B | 8A7F | 0000 0000 0000 0000 | CA 7F without arguments | refused 6 |
| before C6 | B | CA7F | 00C0 0002 0000 0000 | CA 7F | refused 6 |
| before C6 | B | 8A80 | 0000 0000 0000 0000 | CA 80 without arguments | refused 6 |
| before C6 | B | CA80 | 00C0 0002 0000 0000 | CA 80 | refused 6 |
| before C6 | B | 8AFF | 0000 0000 0000 0000 | CA FF without arguments | refused 6 |
| before C6 | B | CAFF | 00C0 0002 0000 0000 | CA FF | refused 6 |
| before C6 | A | 0A80 | - | mailbox A index 0A | refused 6 |
| before C6 | A | CAFF | - | mailbox A index 0A, high bits and low byte set | refused 6 |
| after C6 | B | 8Axx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | CAxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | 8A00 | 0000 0000 0000 0000 | CA 00 without arguments | accepted |
| after C6 | B | CA00 | 00C0 0002 0000 0000 | CA 00 | accepted |
| after C6 | B | 8A7F | 0000 0000 0000 0000 | CA 7F without arguments | accepted |
| after C6 | B | CA7F | 00C0 0002 0000 0000 | CA 7F | accepted |
| after C6 | B | 8A80 | 0000 0000 0000 0000 | CA 80 without arguments | accepted |
| after C6 | B | CA80 | 00C0 0002 0000 0000 | CA 80 | accepted |
| after C6 | B | 8AFF | 0000 0000 0000 0000 | CA FF without arguments | accepted |
| after C6 | B | CAFF | 00C0 0002 0000 0000 | CA FF | accepted |
| after C6 | A | 0A80 | - | mailbox A index 0A | accepted |
| after C6 | A | CAFF | - | mailbox A index 0A, high bits and low byte set | accepted |

## Index 0B

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 8Bxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | CBxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 0B80 | - | mailbox A index 0B | refused 2 |
| before C6 | A | CBFF | - | mailbox A index 0B, high bits and low byte set | refused 2 |
| after C6 | B | 8Bxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | CBxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 0B80 | - | mailbox A index 0B | refused 2 |
| after C6 | A | CBFF | - | mailbox A index 0B, high bits and low byte set | refused 2 |

## Index 0C

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 8Cxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | CCxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | 8C00 | 0000 0000 0000 0000 | 8C 00 | refused 6 |
| before C6 | B | 8C80 | 0000 0000 0000 0000 | 8C 00 loop | refused 6 |
| before C6 | B | 8C01 | 0000 0000 0000 0000 | 8C 01 | refused 6 |
| before C6 | B | 8C81 | 0000 0000 0000 0000 | 8C 01 loop | refused 6 |
| before C6 | B | 8C08 | 0000 0000 0000 0000 | 8C 08 (a null slot) | refused 6 |
| before C6 | B | 8C88 | 0000 0000 0000 0000 | 8C 08 loop (a null slot) | refused 6 |
| before C6 | B | 8C09 | 0000 0000 0000 0000 | 8C 09 (a null slot) | refused 6 |
| before C6 | B | 8C89 | 0000 0000 0000 0000 | 8C 09 loop (a null slot) | refused 6 |
| before C6 | B | 8C3F | 0000 0000 0000 0000 | 8C 3F (a null slot) | refused 6 |
| before C6 | B | 8CBF | 0000 0000 0000 0000 | 8C 3F loop (a null slot) | refused 6 |
| before C6 | B | 8C40 | 0000 0000 0000 0000 | 8C 40 | refused 6 |
| before C6 | B | 8CC0 | 0000 0000 0000 0000 | 8C 40 loop | refused 6 |
| before C6 | A | 0C80 | - | mailbox A index 0C | refused 6 |
| before C6 | A | CCFF | - | mailbox A index 0C, high bits and low byte set | refused 6 |
| after C6 | B | 8Cxx | - | low byte 00 40 80 | refused 7 |
| after C6 | B | 8Cxx | - | low byte 01 02 05 07 3F 58 7F FF | accepted |
| after C6 | B | CCxx | - | low byte 00 40 80 | refused 7 |
| after C6 | B | CCxx | - | low byte 01 02 05 07 3F 58 7F FF | accepted |
| after C6 | B | 8C00 | 0000 0000 0000 0000 | 8C 00 | refused 7 |
| after C6 | B | 8C80 | 0000 0000 0000 0000 | 8C 00 loop | refused 7 |
| after C6 | B | 8C01 | 0000 0000 0000 0000 | 8C 01 | accepted |
| after C6 | B | 8C81 | 0000 0000 0000 0000 | 8C 01 loop | accepted |
| after C6 | B | 8C08 | 0000 0000 0000 0000 | 8C 08 (a null slot) | accepted |
| after C6 | B | 8C88 | 0000 0000 0000 0000 | 8C 08 loop (a null slot) | accepted |
| after C6 | B | 8C09 | 0000 0000 0000 0000 | 8C 09 (a null slot) | accepted |
| after C6 | B | 8C89 | 0000 0000 0000 0000 | 8C 09 loop (a null slot) | accepted |
| after C6 | B | 8C3F | 0000 0000 0000 0000 | 8C 3F (a null slot) | accepted |
| after C6 | B | 8CBF | 0000 0000 0000 0000 | 8C 3F loop (a null slot) | accepted |
| after C6 | B | 8C40 | 0000 0000 0000 0000 | 8C 40 | refused 7 |
| after C6 | B | 8CC0 | 0000 0000 0000 0000 | 8C 40 loop | refused 7 |
| after C6 | A | 0C80 | - | mailbox A index 0C | refused 7 |
| after C6 | A | CCFF | - | mailbox A index 0C, high bits and low byte set | refused 7 |

## Index 0D

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 8Dxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | CDxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | 8D00 | 0000 0000 0000 0000 | 8D 00 | refused 6 |
| before C6 | B | 8D01 | 0000 0000 0000 0000 | 8D 01 | refused 6 |
| before C6 | B | 8D20 | 0000 0000 0000 0000 | 8D 20 | refused 6 |
| before C6 | B | 8DFF | 0000 0000 0000 0000 | 8D FF | refused 6 |
| before C6 | A | 0D80 | - | mailbox A index 0D | refused 6 |
| before C6 | A | CDFF | - | mailbox A index 0D, high bits and low byte set | refused 6 |
| after C6 | B | 8Dxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | CDxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | 8D00 | 0000 0000 0000 0000 | 8D 00 | accepted |
| after C6 | B | 8D01 | 0000 0000 0000 0000 | 8D 01 | accepted |
| after C6 | B | 8D20 | 0000 0000 0000 0000 | 8D 20 | accepted |
| after C6 | B | 8DFF | 0000 0000 0000 0000 | 8D FF | accepted |
| after C6 | A | 0D80 | - | mailbox A index 0D | accepted |
| after C6 | A | CDFF | - | mailbox A index 0D, high bits and low byte set | accepted |

## Index 0E

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 8Exx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | CExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | 8E00 | 0000 0000 0000 0000 | 8E 00 | refused 6 |
| before C6 | B | 8E80 | 0000 0000 0000 0000 | 8E 00 loop | refused 6 |
| before C6 | B | 8E01 | 0000 0000 0000 0000 | 8E 01 | refused 6 |
| before C6 | B | 8E81 | 0000 0000 0000 0000 | 8E 01 loop | refused 6 |
| before C6 | B | 8E08 | 0000 0000 0000 0000 | 8E 08 | refused 6 |
| before C6 | B | 8E88 | 0000 0000 0000 0000 | 8E 08 loop | refused 6 |
| before C6 | B | 8E09 | 0000 0000 0000 0000 | 8E 09 | refused 6 |
| before C6 | B | 8E89 | 0000 0000 0000 0000 | 8E 09 loop | refused 6 |
| before C6 | B | 8E3F | 0000 0000 0000 0000 | 8E 3F | refused 6 |
| before C6 | B | 8EBF | 0000 0000 0000 0000 | 8E 3F loop | refused 6 |
| before C6 | B | 8E40 | 0000 0000 0000 0000 | 8E 40 | refused 6 |
| before C6 | B | 8EC0 | 0000 0000 0000 0000 | 8E 40 loop | refused 6 |
| before C6 | A | 0E80 | - | mailbox A index 0E | refused 6 |
| before C6 | A | CEFF | - | mailbox A index 0E, high bits and low byte set | refused 6 |
| after C6 | B | 8Exx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | CExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | 8E00 | 0000 0000 0000 0000 | 8E 00 | accepted |
| after C6 | B | 8E80 | 0000 0000 0000 0000 | 8E 00 loop | accepted |
| after C6 | B | 8E01 | 0000 0000 0000 0000 | 8E 01 | accepted |
| after C6 | B | 8E81 | 0000 0000 0000 0000 | 8E 01 loop | accepted |
| after C6 | B | 8E08 | 0000 0000 0000 0000 | 8E 08 | accepted |
| after C6 | B | 8E88 | 0000 0000 0000 0000 | 8E 08 loop | accepted |
| after C6 | B | 8E09 | 0000 0000 0000 0000 | 8E 09 | accepted |
| after C6 | B | 8E89 | 0000 0000 0000 0000 | 8E 09 loop | accepted |
| after C6 | B | 8E3F | 0000 0000 0000 0000 | 8E 3F | accepted |
| after C6 | B | 8EBF | 0000 0000 0000 0000 | 8E 3F loop | accepted |
| after C6 | B | 8E40 | 0000 0000 0000 0000 | 8E 40 | accepted |
| after C6 | B | 8EC0 | 0000 0000 0000 0000 | 8E 40 loop | accepted |
| after C6 | A | 0E80 | - | mailbox A index 0E | accepted |
| after C6 | A | CEFF | - | mailbox A index 0E, high bits and low byte set | accepted |

## Index 0F

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 8Fxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | CFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 0F80 | - | mailbox A index 0F | refused 2 |
| before C6 | A | CFFF | - | mailbox A index 0F, high bits and low byte set | refused 2 |
| after C6 | B | 8Fxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | CFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 0F80 | - | mailbox A index 0F | refused 2 |
| after C6 | A | CFFF | - | mailbox A index 0F, high bits and low byte set | refused 2 |

## Index 10

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 90xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | D0xx | - | low byte 00 | refused 7 |
| before C6 | B | D0xx | - | low byte 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | D000 | 0001 003C 0040 0000 | D0 00 voice 0001 | refused 7 |
| before C6 | B | 9000 | 0001 0000 0000 0000 | D0 00 without the argument flag | refused 7 |
| before C6 | B | D001 | 0000 003C 0040 0000 | D0 01 voice 0000 | refused 6 |
| before C6 | B | 9001 | 0000 0000 0000 0000 | D0 01 without the argument flag | refused 7 |
| before C6 | B | D001 | 0019 003C 0040 0000 | D0 01 voice 0019 | refused 6 |
| before C6 | B | 9001 | 0019 0000 0000 0000 | D0 01 without the argument flag | refused 7 |
| before C6 | B | D001 | 001A 003C 0040 0000 | D0 01 voice 001A | refused 7 |
| before C6 | B | 9001 | 001A 0000 0000 0000 | D0 01 without the argument flag | refused 7 |
| before C6 | B | D005 | 0019 003C 0040 0000 | D0 05 voice 0019 | refused 6 |
| before C6 | B | 9005 | 0019 0000 0000 0000 | D0 05 without the argument flag | refused 7 |
| before C6 | B | D005 | FFFF 003C 0040 0000 | D0 05 voice FFFF | refused 7 |
| before C6 | B | 9005 | FFFF 0000 0000 0000 | D0 05 without the argument flag | refused 7 |
| before C6 | A | 1080 | - | mailbox A index 10 | refused 7 |
| before C6 | A | D0FF | - | mailbox A index 10, high bits and low byte set | refused 7 |
| after C6 | B | 90xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | D0xx | - | low byte 00 | refused 7 |
| after C6 | B | D0xx | - | low byte 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | D000 | 0001 003C 0040 0000 | D0 00 voice 0001 | refused 7 |
| after C6 | B | 9000 | 0001 0000 0000 0000 | D0 00 without the argument flag | refused 7 |
| after C6 | B | D001 | 0000 003C 0040 0000 | D0 01 voice 0000 | accepted |
| after C6 | B | 9001 | 0000 0000 0000 0000 | D0 01 without the argument flag | refused 7 |
| after C6 | B | D001 | 0019 003C 0040 0000 | D0 01 voice 0019 | accepted |
| after C6 | B | 9001 | 0019 0000 0000 0000 | D0 01 without the argument flag | refused 7 |
| after C6 | B | D001 | 001A 003C 0040 0000 | D0 01 voice 001A | refused 7 |
| after C6 | B | 9001 | 001A 0000 0000 0000 | D0 01 without the argument flag | refused 7 |
| after C6 | B | D005 | 0019 003C 0040 0000 | D0 05 voice 0019 | accepted |
| after C6 | B | 9005 | 0019 0000 0000 0000 | D0 05 without the argument flag | refused 7 |
| after C6 | B | D005 | FFFF 003C 0040 0000 | D0 05 voice FFFF | refused 7 |
| after C6 | B | 9005 | FFFF 0000 0000 0000 | D0 05 without the argument flag | refused 7 |
| after C6 | A | 1080 | - | mailbox A index 10 | refused 7 |
| after C6 | A | D0FF | - | mailbox A index 10, high bits and low byte set | refused 7 |

## Index 11

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 91xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | D1xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | 9100 | 0000 0000 0000 0000 | D1 id 00 without arguments | refused 7 |
| before C6 | B | D100 | 0000 0080 0080 0000 | D1 id 00 level 0000 | refused 7 |
| before C6 | B | D100 | 0080 0080 0080 0000 | D1 id 00 level 0080 | refused 7 |
| before C6 | B | D100 | 0100 0080 0080 0000 | D1 id 00 level 0100 | refused 7 |
| before C6 | B | D100 | 01FF 0080 0080 0000 | D1 id 00 level 01FF | refused 7 |
| before C6 | B | 9101 | 0000 0000 0000 0000 | D1 id 01 without arguments | refused 7 |
| before C6 | B | D101 | 0000 0080 0080 0000 | D1 id 01 level 0000 | refused 7 |
| before C6 | B | D101 | 0080 0080 0080 0000 | D1 id 01 level 0080 | refused 7 |
| before C6 | B | D101 | 0100 0080 0080 0000 | D1 id 01 level 0100 | refused 7 |
| before C6 | B | D101 | 01FF 0080 0080 0000 | D1 id 01 level 01FF | refused 7 |
| before C6 | B | 9102 | 0000 0000 0000 0000 | D1 id 02 without arguments | refused 7 |
| before C6 | B | D102 | 0000 0080 0080 0000 | D1 id 02 level 0000 | refused 7 |
| before C6 | B | D102 | 0080 0080 0080 0000 | D1 id 02 level 0080 | refused 7 |
| before C6 | B | D102 | 0100 0080 0080 0000 | D1 id 02 level 0100 | refused 7 |
| before C6 | B | D102 | 01FF 0080 0080 0000 | D1 id 02 level 01FF | refused 7 |
| before C6 | B | 917F | 0000 0000 0000 0000 | D1 id 7F without arguments | refused 7 |
| before C6 | B | D17F | 0000 0080 0080 0000 | D1 id 7F level 0000 | refused 7 |
| before C6 | B | D17F | 0080 0080 0080 0000 | D1 id 7F level 0080 | refused 7 |
| before C6 | B | D17F | 0100 0080 0080 0000 | D1 id 7F level 0100 | refused 7 |
| before C6 | B | D17F | 01FF 0080 0080 0000 | D1 id 7F level 01FF | refused 7 |
| before C6 | B | 9180 | 0000 0000 0000 0000 | D1 id 80 without arguments | refused 7 |
| before C6 | B | D180 | 0000 0080 0080 0000 | D1 id 80 level 0000 | refused 7 |
| before C6 | B | D180 | 0080 0080 0080 0000 | D1 id 80 level 0080 | refused 7 |
| before C6 | B | D180 | 0100 0080 0080 0000 | D1 id 80 level 0100 | refused 7 |
| before C6 | B | D180 | 01FF 0080 0080 0000 | D1 id 80 level 01FF | refused 7 |
| before C6 | B | 9181 | 0000 0000 0000 0000 | D1 id 81 without arguments | refused 7 |
| before C6 | B | D181 | 0000 0080 0080 0000 | D1 id 81 level 0000 | refused 7 |
| before C6 | B | D181 | 0080 0080 0080 0000 | D1 id 81 level 0080 | refused 7 |
| before C6 | B | D181 | 0100 0080 0080 0000 | D1 id 81 level 0100 | refused 7 |
| before C6 | B | D181 | 01FF 0080 0080 0000 | D1 id 81 level 01FF | refused 7 |
| before C6 | B | 91FF | 0000 0000 0000 0000 | D1 id FF without arguments | refused 7 |
| before C6 | B | D1FF | 0000 0080 0080 0000 | D1 id FF level 0000 | refused 7 |
| before C6 | B | D1FF | 0080 0080 0080 0000 | D1 id FF level 0080 | refused 7 |
| before C6 | B | D1FF | 0100 0080 0080 0000 | D1 id FF level 0100 | refused 7 |
| before C6 | B | D1FF | 01FF 0080 0080 0000 | D1 id FF level 01FF | refused 7 |
| before C6 | A | 1180 | - | mailbox A index 11 | refused 7 |
| before C6 | A | D1FF | - | mailbox A index 11, high bits and low byte set | refused 7 |
| after C6 | B | 91xx | - | low byte 00 80 | refused 7 |
| after C6 | B | 91xx | - | low byte 01 02 05 07 3F 40 58 7F FF | accepted |
| after C6 | B | D1xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | 9100 | 0000 0000 0000 0000 | D1 id 00 without arguments | refused 7 |
| after C6 | B | D100 | 0000 0080 0080 0000 | D1 id 00 level 0000 | refused 7 |
| after C6 | B | D100 | 0080 0080 0080 0000 | D1 id 00 level 0080 | refused 7 |
| after C6 | B | D100 | 0100 0080 0080 0000 | D1 id 00 level 0100 | refused 7 |
| after C6 | B | D100 | 01FF 0080 0080 0000 | D1 id 00 level 01FF | refused 7 |
| after C6 | B | 9101 | 0000 0000 0000 0000 | D1 id 01 without arguments | accepted |
| after C6 | B | D101 | 0000 0080 0080 0000 | D1 id 01 level 0000 | refused 7 |
| after C6 | B | D101 | 0080 0080 0080 0000 | D1 id 01 level 0080 | accepted |
| after C6 | B | D101 | 0100 0080 0080 0000 | D1 id 01 level 0100 | refused 7 |
| after C6 | B | D101 | 01FF 0080 0080 0000 | D1 id 01 level 01FF | accepted |
| after C6 | B | 9102 | 0000 0000 0000 0000 | D1 id 02 without arguments | accepted |
| after C6 | B | D102 | 0000 0080 0080 0000 | D1 id 02 level 0000 | refused 7 |
| after C6 | B | D102 | 0080 0080 0080 0000 | D1 id 02 level 0080 | accepted |
| after C6 | B | D102 | 0100 0080 0080 0000 | D1 id 02 level 0100 | refused 7 |
| after C6 | B | D102 | 01FF 0080 0080 0000 | D1 id 02 level 01FF | accepted |
| after C6 | B | 917F | 0000 0000 0000 0000 | D1 id 7F without arguments | accepted |
| after C6 | B | D17F | 0000 0080 0080 0000 | D1 id 7F level 0000 | refused 7 |
| after C6 | B | D17F | 0080 0080 0080 0000 | D1 id 7F level 0080 | accepted |
| after C6 | B | D17F | 0100 0080 0080 0000 | D1 id 7F level 0100 | refused 7 |
| after C6 | B | D17F | 01FF 0080 0080 0000 | D1 id 7F level 01FF | accepted |
| after C6 | B | 9180 | 0000 0000 0000 0000 | D1 id 80 without arguments | refused 7 |
| after C6 | B | D180 | 0000 0080 0080 0000 | D1 id 80 level 0000 | refused 7 |
| after C6 | B | D180 | 0080 0080 0080 0000 | D1 id 80 level 0080 | refused 7 |
| after C6 | B | D180 | 0100 0080 0080 0000 | D1 id 80 level 0100 | refused 7 |
| after C6 | B | D180 | 01FF 0080 0080 0000 | D1 id 80 level 01FF | refused 7 |
| after C6 | B | 9181 | 0000 0000 0000 0000 | D1 id 81 without arguments | accepted |
| after C6 | B | D181 | 0000 0080 0080 0000 | D1 id 81 level 0000 | refused 7 |
| after C6 | B | D181 | 0080 0080 0080 0000 | D1 id 81 level 0080 | accepted |
| after C6 | B | D181 | 0100 0080 0080 0000 | D1 id 81 level 0100 | refused 7 |
| after C6 | B | D181 | 01FF 0080 0080 0000 | D1 id 81 level 01FF | accepted |
| after C6 | B | 91FF | 0000 0000 0000 0000 | D1 id FF without arguments | accepted |
| after C6 | B | D1FF | 0000 0080 0080 0000 | D1 id FF level 0000 | refused 7 |
| after C6 | B | D1FF | 0080 0080 0080 0000 | D1 id FF level 0080 | accepted |
| after C6 | B | D1FF | 0100 0080 0080 0000 | D1 id FF level 0100 | refused 7 |
| after C6 | B | D1FF | 01FF 0080 0080 0000 | D1 id FF level 01FF | accepted |
| after C6 | A | 1180 | - | mailbox A index 11 | refused 7 |
| after C6 | A | D1FF | - | mailbox A index 11, high bits and low byte set | refused 7 |

## Index 12

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 92xx | - | low byte 00 | refused 7 |
| before C6 | B | 92xx | - | low byte 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | D2xx | - | low byte 00 | refused 7 |
| before C6 | B | D2xx | - | low byte 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | 9200 | 0000 0000 0000 0000 | D2 00 | refused 7 |
| before C6 | B | 9201 | 0000 0000 0000 0000 | D2 01 | refused 6 |
| before C6 | B | 92FF | 0000 0000 0000 0000 | D2 FF | refused 6 |
| before C6 | A | 1280 | - | mailbox A index 12 | refused 7 |
| before C6 | A | D2FF | - | mailbox A index 12, high bits and low byte set | refused 7 |
| after C6 | B | 92xx | - | low byte 00 | refused 7 |
| after C6 | B | 92xx | - | low byte 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | D2xx | - | low byte 00 | refused 7 |
| after C6 | B | D2xx | - | low byte 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | 9200 | 0000 0000 0000 0000 | D2 00 | refused 7 |
| after C6 | B | 9201 | 0000 0000 0000 0000 | D2 01 | accepted |
| after C6 | B | 92FF | 0000 0000 0000 0000 | D2 FF | accepted |
| after C6 | A | 1280 | - | mailbox A index 12 | refused 7 |
| after C6 | A | D2FF | - | mailbox A index 12, high bits and low byte set | refused 7 |

## Index 13

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 93xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | D3xx | - | low byte 00 | refused 7 |
| before C6 | B | D3xx | - | low byte 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | D300 | 0080 0010 0000 0000 | D3 00 | refused 7 |
| before C6 | B | 9300 | 0000 0000 0000 0000 | D3 00 without arguments | refused 7 |
| before C6 | B | D301 | 0080 0010 0000 0000 | D3 01 | refused 6 |
| before C6 | B | 9301 | 0000 0000 0000 0000 | D3 01 without arguments | refused 7 |
| before C6 | B | D3FF | 0080 0010 0000 0000 | D3 FF | refused 6 |
| before C6 | B | 93FF | 0000 0000 0000 0000 | D3 FF without arguments | refused 7 |
| before C6 | A | 1380 | - | mailbox A index 13 | refused 7 |
| before C6 | A | D3FF | - | mailbox A index 13, high bits and low byte set | refused 7 |
| after C6 | B | 93xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | D3xx | - | low byte 00 | refused 7 |
| after C6 | B | D3xx | - | low byte 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | D300 | 0080 0010 0000 0000 | D3 00 | refused 7 |
| after C6 | B | 9300 | 0000 0000 0000 0000 | D3 00 without arguments | refused 7 |
| after C6 | B | D301 | 0080 0010 0000 0000 | D3 01 | accepted |
| after C6 | B | 9301 | 0000 0000 0000 0000 | D3 01 without arguments | refused 7 |
| after C6 | B | D3FF | 0080 0010 0000 0000 | D3 FF | accepted |
| after C6 | B | 93FF | 0000 0000 0000 0000 | D3 FF without arguments | refused 7 |
| after C6 | A | 1380 | - | mailbox A index 13 | refused 7 |
| after C6 | A | D3FF | - | mailbox A index 13, high bits and low byte set | refused 7 |

## Index 14

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | A | 9400 | - | mailbox A without the request bit | finish only |
| before C6 | B | 9494 | 0000 0000 0000 0000 | 94 on mailbox B (the frame tick path) | accepted |
| before C6 | B | D400 | 0001 0000 0000 0000 | D4 on mailbox B (the frame tick path) | accepted |
| before C6 | A | 9494 | - | 9494 (the frame tick) | accepted |
| before C6 | A | 1480 | - | mailbox A index 14 | accepted |
| after C6 | A | 9400 | - | mailbox A without the request bit | finish only |
| after C6 | B | 9494 | 0000 0000 0000 0000 | 94 on mailbox B (the frame tick path) | accepted |
| after C6 | B | D400 | 0001 0000 0000 0000 | D4 on mailbox B (the frame tick path) | accepted |
| after C6 | A | 9494 | - | 9494 (the frame tick) | accepted |
| after C6 | A | 1480 | - | mailbox A index 14 | accepted |

## Index 15

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 95xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | D5xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | 9500 | 0000 0000 0000 0000 | D5 00 without arguments | refused 6 |
| before C6 | B | D500 | 0040 0010 0000 0000 | D5 00 | refused 6 |
| before C6 | B | 9501 | 0000 0000 0000 0000 | D5 01 without arguments | refused 6 |
| before C6 | B | D501 | 0040 0010 0000 0000 | D5 01 | refused 6 |
| before C6 | B | 9502 | 0000 0000 0000 0000 | D5 02 without arguments | refused 6 |
| before C6 | B | D502 | 0040 0010 0000 0000 | D5 02 | refused 6 |
| before C6 | B | 9503 | 0000 0000 0000 0000 | D5 03 without arguments | refused 6 |
| before C6 | B | D503 | 0040 0010 0000 0000 | D5 03 | refused 6 |
| before C6 | B | 95FF | 0000 0000 0000 0000 | D5 FF without arguments | refused 6 |
| before C6 | B | D5FF | 0040 0010 0000 0000 | D5 FF | refused 6 |
| before C6 | A | 1580 | - | mailbox A index 15 | refused 6 |
| before C6 | A | D5FF | - | mailbox A index 15, high bits and low byte set | refused 6 |
| after C6 | B | 95xx | - | low byte 00 | accepted |
| after C6 | B | 95xx | - | low byte 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | D5xx | - | low byte 00 01 | accepted |
| after C6 | B | D5xx | - | low byte 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | 9500 | 0000 0000 0000 0000 | D5 00 without arguments | accepted |
| after C6 | B | D500 | 0040 0010 0000 0000 | D5 00 | accepted |
| after C6 | B | 9501 | 0000 0000 0000 0000 | D5 01 without arguments | refused 7 |
| after C6 | B | D501 | 0040 0010 0000 0000 | D5 01 | accepted |
| after C6 | B | 9502 | 0000 0000 0000 0000 | D5 02 without arguments | refused 7 |
| after C6 | B | D502 | 0040 0010 0000 0000 | D5 02 | refused 7 |
| after C6 | B | 9503 | 0000 0000 0000 0000 | D5 03 without arguments | refused 7 |
| after C6 | B | D503 | 0040 0010 0000 0000 | D5 03 | refused 7 |
| after C6 | B | 95FF | 0000 0000 0000 0000 | D5 FF without arguments | refused 7 |
| after C6 | B | D5FF | 0040 0010 0000 0000 | D5 FF | refused 7 |
| after C6 | A | 1580 | - | mailbox A index 15 | accepted |
| after C6 | A | D5FF | - | mailbox A index 15, high bits and low byte set | accepted |

## Index 16

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 96xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | D6xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | 9600 | 0000 0000 0000 0000 | D6 00 without arguments | refused 6 |
| before C6 | B | D600 | 0001 0000 0000 0000 | D6 00 | refused 6 |
| before C6 | B | 9601 | 0000 0000 0000 0000 | D6 01 without arguments | refused 6 |
| before C6 | B | D601 | 0001 0000 0000 0000 | D6 01 | refused 6 |
| before C6 | B | 9602 | 0000 0000 0000 0000 | D6 02 without arguments | refused 6 |
| before C6 | B | D602 | 0001 0000 0000 0000 | D6 02 | refused 6 |
| before C6 | B | 9603 | 0000 0000 0000 0000 | D6 03 without arguments | refused 6 |
| before C6 | B | D603 | 0001 0000 0000 0000 | D6 03 | refused 6 |
| before C6 | B | 9604 | 0000 0000 0000 0000 | D6 04 without arguments | refused 6 |
| before C6 | B | D604 | 0001 0000 0000 0000 | D6 04 | refused 6 |
| before C6 | B | 9605 | 0000 0000 0000 0000 | D6 05 without arguments | refused 6 |
| before C6 | B | D605 | 0001 0000 0000 0000 | D6 05 | refused 6 |
| before C6 | B | 9606 | 0000 0000 0000 0000 | D6 06 without arguments | refused 6 |
| before C6 | B | D606 | 0001 0000 0000 0000 | D6 06 | refused 6 |
| before C6 | B | 9607 | 0000 0000 0000 0000 | D6 07 without arguments | refused 6 |
| before C6 | B | D607 | 0001 0000 0000 0000 | D6 07 | refused 6 |
| before C6 | B | 9608 | 0000 0000 0000 0000 | D6 08 without arguments | refused 6 |
| before C6 | B | D608 | 0001 0000 0000 0000 | D6 08 | refused 6 |
| before C6 | B | 9609 | 0000 0000 0000 0000 | D6 09 without arguments | refused 6 |
| before C6 | B | D609 | 0001 0000 0000 0000 | D6 09 | refused 6 |
| before C6 | B | D605 | 0000 0001 0000 0000 | D6 05 voice 0000 | refused 6 |
| before C6 | B | D605 | 0019 0001 0000 0000 | D6 05 voice 0019 | refused 6 |
| before C6 | B | D605 | 001A 0001 0000 0000 | D6 05 voice 001A | refused 6 |
| before C6 | B | D605 | 0099 0001 0000 0000 | D6 05 voice 0099 | refused 6 |
| before C6 | B | D605 | 009A 0001 0000 0000 | D6 05 voice 009A | refused 6 |
| before C6 | B | D605 | 007F 0001 0000 0000 | D6 05 voice 007F | refused 6 |
| before C6 | A | 1680 | - | mailbox A index 16 | refused 6 |
| before C6 | A | D6FF | - | mailbox A index 16, high bits and low byte set | refused 6 |
| after C6 | B | 96xx | - | low byte 00 01 02 07 | accepted |
| after C6 | B | 96xx | - | low byte 05 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | D6xx | - | low byte 00 01 02 05 07 | accepted |
| after C6 | B | D6xx | - | low byte 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | 9600 | 0000 0000 0000 0000 | D6 00 without arguments | accepted |
| after C6 | B | D600 | 0001 0000 0000 0000 | D6 00 | accepted |
| after C6 | B | 9601 | 0000 0000 0000 0000 | D6 01 without arguments | accepted |
| after C6 | B | D601 | 0001 0000 0000 0000 | D6 01 | accepted |
| after C6 | B | 9602 | 0000 0000 0000 0000 | D6 02 without arguments | accepted |
| after C6 | B | D602 | 0001 0000 0000 0000 | D6 02 | accepted |
| after C6 | B | 9603 | 0000 0000 0000 0000 | D6 03 without arguments | accepted |
| after C6 | B | D603 | 0001 0000 0000 0000 | D6 03 | accepted |
| after C6 | B | 9604 | 0000 0000 0000 0000 | D6 04 without arguments | accepted |
| after C6 | B | D604 | 0001 0000 0000 0000 | D6 04 | accepted |
| after C6 | B | 9605 | 0000 0000 0000 0000 | D6 05 without arguments | refused 7 |
| after C6 | B | D605 | 0001 0000 0000 0000 | D6 05 | accepted |
| after C6 | B | 9606 | 0000 0000 0000 0000 | D6 06 without arguments | accepted |
| after C6 | B | D606 | 0001 0000 0000 0000 | D6 06 | accepted |
| after C6 | B | 9607 | 0000 0000 0000 0000 | D6 07 without arguments | accepted |
| after C6 | B | D607 | 0001 0000 0000 0000 | D6 07 | accepted |
| after C6 | B | 9608 | 0000 0000 0000 0000 | D6 08 without arguments | refused 7 |
| after C6 | B | D608 | 0001 0000 0000 0000 | D6 08 | refused 7 |
| after C6 | B | 9609 | 0000 0000 0000 0000 | D6 09 without arguments | refused 7 |
| after C6 | B | D609 | 0001 0000 0000 0000 | D6 09 | refused 7 |
| after C6 | B | D605 | 0000 0001 0000 0000 | D6 05 voice 0000 | accepted |
| after C6 | B | D605 | 0019 0001 0000 0000 | D6 05 voice 0019 | accepted |
| after C6 | B | D605 | 001A 0001 0000 0000 | D6 05 voice 001A | refused 7 |
| after C6 | B | D605 | 0099 0001 0000 0000 | D6 05 voice 0099 | accepted |
| after C6 | B | D605 | 009A 0001 0000 0000 | D6 05 voice 009A | refused 7 |
| after C6 | B | D605 | 007F 0001 0000 0000 | D6 05 voice 007F | refused 7 |
| after C6 | A | 1680 | - | mailbox A index 16 | accepted |
| after C6 | A | D6FF | - | mailbox A index 16, high bits and low byte set | accepted |

## Index 17

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 97xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | D7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 1780 | - | mailbox A index 17 | refused 2 |
| before C6 | A | D7FF | - | mailbox A index 17, high bits and low byte set | refused 2 |
| after C6 | B | 97xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | D7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 1780 | - | mailbox A index 17 | refused 2 |
| after C6 | A | D7FF | - | mailbox A index 17, high bits and low byte set | refused 2 |

## Index 18

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 98xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | D8xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 1880 | - | mailbox A index 18 | refused 2 |
| before C6 | A | D8FF | - | mailbox A index 18, high bits and low byte set | refused 2 |
| after C6 | B | 98xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | D8xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 1880 | - | mailbox A index 18 | refused 2 |
| after C6 | A | D8FF | - | mailbox A index 18, high bits and low byte set | refused 2 |

## Index 19

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 99xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | D9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 1980 | - | mailbox A index 19 | refused 2 |
| before C6 | A | D9FF | - | mailbox A index 19, high bits and low byte set | refused 2 |
| after C6 | B | 99xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | D9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 1980 | - | mailbox A index 19 | refused 2 |
| after C6 | A | D9FF | - | mailbox A index 19, high bits and low byte set | refused 2 |

## Index 1A

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 9Axx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | DAxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | 1A02 | 0000 0000 0000 0000 | no request bit | finish only |
| before C6 | B | DA00 | from the ROM | DA mode 0, a 0x80 stream | refused 7 |
| before C6 | B | DA00 | from the ROM | DA mode 0, a 0x81 stream | refused 7 |
| before C6 | B | DA00 | from the ROM | DA mode 0, a another type stream | refused 7 |
| before C6 | B | DA00 | 0100 0080 0000 0000 | DA mode 0, source 800000 | refused 7 |
| before C6 | B | DA00 | 0100 0080 0001 0000 | DA mode 0, source 800001 | refused 7 |
| before C6 | B | DA00 | 0100 0080 0002 0000 | DA mode 0, source 800002 | refused 7 |
| before C6 | B | DA00 | 0100 00FF FFFE 0000 | DA mode 0, source FFFFFE | refused 7 |
| before C6 | B | DA01 | from the ROM | DA mode 1, a 0x80 stream | refused 7 |
| before C6 | B | DA01 | from the ROM | DA mode 1, a 0x81 stream | refused 7 |
| before C6 | B | DA01 | from the ROM | DA mode 1, a another type stream | refused 7 |
| before C6 | B | DA01 | 0100 0080 0000 0000 | DA mode 1, source 800000 | refused 7 |
| before C6 | B | DA01 | 0100 0080 0001 0000 | DA mode 1, source 800001 | refused 7 |
| before C6 | B | DA01 | 0100 0080 0002 0000 | DA mode 1, source 800002 | refused 7 |
| before C6 | B | DA01 | 0100 00FF FFFE 0000 | DA mode 1, source FFFFFE | refused 7 |
| before C6 | B | DA02 | from the ROM | DA mode 2, a 0x80 stream | accepted |
| before C6 | B | DA02 | from the ROM | DA mode 2, a 0x81 stream | accepted |
| before C6 | B | DA02 | from the ROM | DA mode 2, a another type stream | refused 7 |
| before C6 | B | DA02 | 0100 0080 0000 0000 | DA mode 2, source 800000 | refused 7 |
| before C6 | B | DA02 | 0100 0080 0001 0000 | DA mode 2, source 800001 | refused 7 |
| before C6 | B | DA02 | 0100 0080 0002 0000 | DA mode 2, source 800002 | refused 7 |
| before C6 | B | DA02 | 0100 00FF FFFE 0000 | DA mode 2, source FFFFFE | refused 7 |
| before C6 | B | DA03 | from the ROM | DA mode 3, a 0x80 stream | refused 7 |
| before C6 | B | DA03 | from the ROM | DA mode 3, a 0x81 stream | refused 7 |
| before C6 | B | DA03 | from the ROM | DA mode 3, a another type stream | refused 7 |
| before C6 | B | DA03 | 0100 0080 0000 0000 | DA mode 3, source 800000 | refused 7 |
| before C6 | B | DA03 | 0100 0080 0001 0000 | DA mode 3, source 800001 | refused 7 |
| before C6 | B | DA03 | 0100 0080 0002 0000 | DA mode 3, source 800002 | refused 7 |
| before C6 | B | DA03 | 0100 00FF FFFE 0000 | DA mode 3, source FFFFFE | refused 7 |
| before C6 | B | DA05 | from the ROM | DA mode 5, a 0x80 stream | refused 7 |
| before C6 | B | DA05 | from the ROM | DA mode 5, a 0x81 stream | refused 7 |
| before C6 | B | DA05 | from the ROM | DA mode 5, a another type stream | refused 7 |
| before C6 | B | DA05 | 0100 0080 0000 0000 | DA mode 5, source 800000 | refused 7 |
| before C6 | B | DA05 | 0100 0080 0001 0000 | DA mode 5, source 800001 | refused 7 |
| before C6 | B | DA05 | 0100 0080 0002 0000 | DA mode 5, source 800002 | refused 7 |
| before C6 | B | DA05 | 0100 00FF FFFE 0000 | DA mode 5, source FFFFFE | refused 7 |
| before C6 | B | DA06 | from the ROM | DA mode 6, a 0x80 stream | accepted |
| before C6 | B | DA06 | from the ROM | DA mode 6, a 0x81 stream | refused 7 |
| before C6 | B | DA06 | from the ROM | DA mode 6, a another type stream | refused 7 |
| before C6 | B | DA06 | 0100 0080 0000 0000 | DA mode 6, source 800000 | refused 7 |
| before C6 | B | DA06 | 0100 0080 0001 0000 | DA mode 6, source 800001 | refused 7 |
| before C6 | B | DA06 | 0100 0080 0002 0000 | DA mode 6, source 800002 | refused 7 |
| before C6 | B | DA06 | 0100 00FF FFFE 0000 | DA mode 6, source FFFFFE | refused 7 |
| before C6 | B | DA07 | from the ROM | DA mode 7, a 0x80 stream | accepted |
| before C6 | B | DA07 | from the ROM | DA mode 7, a 0x81 stream | accepted |
| before C6 | B | DA07 | from the ROM | DA mode 7, a another type stream | refused 7 |
| before C6 | B | DA07 | 0100 0080 0000 0000 | DA mode 7, source 800000 | refused 7 |
| before C6 | B | DA07 | 0100 0080 0001 0000 | DA mode 7, source 800001 | refused 7 |
| before C6 | B | DA07 | 0100 0080 0002 0000 | DA mode 7, source 800002 | refused 7 |
| before C6 | B | DA07 | 0100 00FF FFFE 0000 | DA mode 7, source FFFFFE | refused 7 |
| before C6 | B | DA08 | from the ROM | DA mode 8, a 0x80 stream | refused 7 |
| before C6 | B | DA08 | from the ROM | DA mode 8, a 0x81 stream | refused 7 |
| before C6 | B | DA08 | from the ROM | DA mode 8, a another type stream | refused 7 |
| before C6 | B | DA08 | 0100 0080 0000 0000 | DA mode 8, source 800000 | refused 7 |
| before C6 | B | DA08 | 0100 0080 0001 0000 | DA mode 8, source 800001 | refused 7 |
| before C6 | B | DA08 | 0100 0080 0002 0000 | DA mode 8, source 800002 | refused 7 |
| before C6 | B | DA08 | 0100 00FF FFFE 0000 | DA mode 8, source FFFFFE | refused 7 |
| before C6 | B | DAFF | from the ROM | DA mode FF, a 0x80 stream | refused 7 |
| before C6 | B | DAFF | from the ROM | DA mode FF, a 0x81 stream | refused 7 |
| before C6 | B | DAFF | from the ROM | DA mode FF, a another type stream | refused 7 |
| before C6 | B | DAFF | 0100 0080 0000 0000 | DA mode FF, source 800000 | refused 7 |
| before C6 | B | DAFF | 0100 0080 0001 0000 | DA mode FF, source 800001 | refused 7 |
| before C6 | B | DAFF | 0100 0080 0002 0000 | DA mode FF, source 800002 | refused 7 |
| before C6 | B | DAFF | 0100 00FF FFFE 0000 | DA mode FF, source FFFFFE | refused 7 |
| before C6 | A | 1A80 | - | mailbox A index 1A | refused 7 |
| before C6 | A | DAFF | - | mailbox A index 1A, high bits and low byte set | refused 7 |
| before C6 | A | DA7F | - | mailbox A without the request bit | finish only |
| after C6 | B | 9Axx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | DAxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | 1A02 | 0000 0000 0000 0000 | no request bit | finish only |
| after C6 | B | DA00 | from the ROM | DA mode 0, a 0x80 stream | refused 7 |
| after C6 | B | DA00 | from the ROM | DA mode 0, a 0x81 stream | refused 7 |
| after C6 | B | DA00 | from the ROM | DA mode 0, a another type stream | refused 7 |
| after C6 | B | DA00 | 0100 0080 0000 0000 | DA mode 0, source 800000 | refused 7 |
| after C6 | B | DA00 | 0100 0080 0001 0000 | DA mode 0, source 800001 | refused 7 |
| after C6 | B | DA00 | 0100 0080 0002 0000 | DA mode 0, source 800002 | refused 7 |
| after C6 | B | DA00 | 0100 00FF FFFE 0000 | DA mode 0, source FFFFFE | refused 7 |
| after C6 | B | DA01 | from the ROM | DA mode 1, a 0x80 stream | refused 7 |
| after C6 | B | DA01 | from the ROM | DA mode 1, a 0x81 stream | refused 7 |
| after C6 | B | DA01 | from the ROM | DA mode 1, a another type stream | refused 7 |
| after C6 | B | DA01 | 0100 0080 0000 0000 | DA mode 1, source 800000 | refused 7 |
| after C6 | B | DA01 | 0100 0080 0001 0000 | DA mode 1, source 800001 | refused 7 |
| after C6 | B | DA01 | 0100 0080 0002 0000 | DA mode 1, source 800002 | refused 7 |
| after C6 | B | DA01 | 0100 00FF FFFE 0000 | DA mode 1, source FFFFFE | refused 7 |
| after C6 | B | DA02 | from the ROM | DA mode 2, a 0x80 stream | accepted |
| after C6 | B | DA02 | from the ROM | DA mode 2, a 0x81 stream | accepted |
| after C6 | B | DA02 | from the ROM | DA mode 2, a another type stream | refused 7 |
| after C6 | B | DA02 | 0100 0080 0000 0000 | DA mode 2, source 800000 | refused 7 |
| after C6 | B | DA02 | 0100 0080 0001 0000 | DA mode 2, source 800001 | refused 7 |
| after C6 | B | DA02 | 0100 0080 0002 0000 | DA mode 2, source 800002 | refused 7 |
| after C6 | B | DA02 | 0100 00FF FFFE 0000 | DA mode 2, source FFFFFE | refused 7 |
| after C6 | B | DA03 | from the ROM | DA mode 3, a 0x80 stream | refused 7 |
| after C6 | B | DA03 | from the ROM | DA mode 3, a 0x81 stream | refused 7 |
| after C6 | B | DA03 | from the ROM | DA mode 3, a another type stream | refused 7 |
| after C6 | B | DA03 | 0100 0080 0000 0000 | DA mode 3, source 800000 | refused 7 |
| after C6 | B | DA03 | 0100 0080 0001 0000 | DA mode 3, source 800001 | refused 7 |
| after C6 | B | DA03 | 0100 0080 0002 0000 | DA mode 3, source 800002 | refused 7 |
| after C6 | B | DA03 | 0100 00FF FFFE 0000 | DA mode 3, source FFFFFE | refused 7 |
| after C6 | B | DA05 | from the ROM | DA mode 5, a 0x80 stream | refused 7 |
| after C6 | B | DA05 | from the ROM | DA mode 5, a 0x81 stream | refused 7 |
| after C6 | B | DA05 | from the ROM | DA mode 5, a another type stream | refused 7 |
| after C6 | B | DA05 | 0100 0080 0000 0000 | DA mode 5, source 800000 | refused 7 |
| after C6 | B | DA05 | 0100 0080 0001 0000 | DA mode 5, source 800001 | refused 7 |
| after C6 | B | DA05 | 0100 0080 0002 0000 | DA mode 5, source 800002 | refused 7 |
| after C6 | B | DA05 | 0100 00FF FFFE 0000 | DA mode 5, source FFFFFE | refused 7 |
| after C6 | B | DA06 | from the ROM | DA mode 6, a 0x80 stream | accepted |
| after C6 | B | DA06 | from the ROM | DA mode 6, a 0x81 stream | refused 7 |
| after C6 | B | DA06 | from the ROM | DA mode 6, a another type stream | refused 7 |
| after C6 | B | DA06 | 0100 0080 0000 0000 | DA mode 6, source 800000 | refused 7 |
| after C6 | B | DA06 | 0100 0080 0001 0000 | DA mode 6, source 800001 | refused 7 |
| after C6 | B | DA06 | 0100 0080 0002 0000 | DA mode 6, source 800002 | refused 7 |
| after C6 | B | DA06 | 0100 00FF FFFE 0000 | DA mode 6, source FFFFFE | refused 7 |
| after C6 | B | DA07 | from the ROM | DA mode 7, a 0x80 stream | accepted |
| after C6 | B | DA07 | from the ROM | DA mode 7, a 0x81 stream | accepted |
| after C6 | B | DA07 | from the ROM | DA mode 7, a another type stream | refused 7 |
| after C6 | B | DA07 | 0100 0080 0000 0000 | DA mode 7, source 800000 | refused 7 |
| after C6 | B | DA07 | 0100 0080 0001 0000 | DA mode 7, source 800001 | refused 7 |
| after C6 | B | DA07 | 0100 0080 0002 0000 | DA mode 7, source 800002 | refused 7 |
| after C6 | B | DA07 | 0100 00FF FFFE 0000 | DA mode 7, source FFFFFE | refused 7 |
| after C6 | B | DA08 | from the ROM | DA mode 8, a 0x80 stream | refused 7 |
| after C6 | B | DA08 | from the ROM | DA mode 8, a 0x81 stream | refused 7 |
| after C6 | B | DA08 | from the ROM | DA mode 8, a another type stream | refused 7 |
| after C6 | B | DA08 | 0100 0080 0000 0000 | DA mode 8, source 800000 | refused 7 |
| after C6 | B | DA08 | 0100 0080 0001 0000 | DA mode 8, source 800001 | refused 7 |
| after C6 | B | DA08 | 0100 0080 0002 0000 | DA mode 8, source 800002 | refused 7 |
| after C6 | B | DA08 | 0100 00FF FFFE 0000 | DA mode 8, source FFFFFE | refused 7 |
| after C6 | B | DAFF | from the ROM | DA mode FF, a 0x80 stream | refused 7 |
| after C6 | B | DAFF | from the ROM | DA mode FF, a 0x81 stream | refused 7 |
| after C6 | B | DAFF | from the ROM | DA mode FF, a another type stream | refused 7 |
| after C6 | B | DAFF | 0100 0080 0000 0000 | DA mode FF, source 800000 | refused 7 |
| after C6 | B | DAFF | 0100 0080 0001 0000 | DA mode FF, source 800001 | refused 7 |
| after C6 | B | DAFF | 0100 0080 0002 0000 | DA mode FF, source 800002 | refused 7 |
| after C6 | B | DAFF | 0100 00FF FFFE 0000 | DA mode FF, source FFFFFE | refused 7 |
| after C6 | A | 1A80 | - | mailbox A index 1A | refused 7 |
| after C6 | A | DAFF | - | mailbox A index 1A, high bits and low byte set | refused 7 |
| after C6 | A | DA7F | - | mailbox A without the request bit | finish only |

## Index 1B

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 9Bxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | DBxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | DB00 | 0000 0000 0010 0000 | DB mode 0 (0000, 0000, 0010) | refused 7 |
| before C6 | B | DB00 | 1F00 0000 0100 0000 | DB mode 0 (1F00, 0000, 0100) | refused 7 |
| before C6 | B | DB00 | 1F00 0000 0102 0000 | DB mode 0 (1F00, 0000, 0102) | refused 7 |
| before C6 | B | DB00 | 0000 FF00 0100 0000 | DB mode 0 (0000, FF00, 0100) | refused 7 |
| before C6 | B | DB00 | 0000 FF00 0102 0000 | DB mode 0 (0000, FF00, 0102) | refused 7 |
| before C6 | B | DB00 | 0400 2000 00F0 0000 | DB mode 0 (0400, 2000, 00F0) | refused 7 |
| before C6 | B | DB00 | 0400 2000 00F2 0000 | DB mode 0 (0400, 2000, 00F2) | refused 7 |
| before C6 | B | DB00 | FFFE 0000 0002 0000 | DB mode 0 (FFFE, 0000, 0002) | refused 7 |
| before C6 | B | DB00 | 0000 FFFE 0002 0000 | DB mode 0 (0000, FFFE, 0002) | refused 7 |
| before C6 | B | DB02 | 0000 0000 0010 0000 | DB mode 2 (0000, 0000, 0010) | refused 7 |
| before C6 | B | DB02 | 1F00 0000 0100 0000 | DB mode 2 (1F00, 0000, 0100) | refused 7 |
| before C6 | B | DB02 | 1F00 0000 0102 0000 | DB mode 2 (1F00, 0000, 0102) | refused 7 |
| before C6 | B | DB02 | 0000 FF00 0100 0000 | DB mode 2 (0000, FF00, 0100) | refused 7 |
| before C6 | B | DB02 | 0000 FF00 0102 0000 | DB mode 2 (0000, FF00, 0102) | refused 7 |
| before C6 | B | DB02 | 0400 2000 00F0 0000 | DB mode 2 (0400, 2000, 00F0) | refused 7 |
| before C6 | B | DB02 | 0400 2000 00F2 0000 | DB mode 2 (0400, 2000, 00F2) | refused 7 |
| before C6 | B | DB02 | FFFE 0000 0002 0000 | DB mode 2 (FFFE, 0000, 0002) | refused 7 |
| before C6 | B | DB02 | 0000 FFFE 0002 0000 | DB mode 2 (0000, FFFE, 0002) | refused 7 |
| before C6 | B | DB03 | 0000 0000 0010 0000 | DB mode 3 (0000, 0000, 0010) | accepted |
| before C6 | B | DB03 | 1F00 0000 0100 0000 | DB mode 3 (1F00, 0000, 0100) | accepted |
| before C6 | B | DB03 | 1F00 0000 0102 0000 | DB mode 3 (1F00, 0000, 0102) | refused 7 |
| before C6 | B | DB03 | 0000 FF00 0100 0000 | DB mode 3 (0000, FF00, 0100) | accepted |
| before C6 | B | DB03 | 0000 FF00 0102 0000 | DB mode 3 (0000, FF00, 0102) | refused 7 |
| before C6 | B | DB03 | 0400 2000 00F0 0000 | DB mode 3 (0400, 2000, 00F0) | accepted |
| before C6 | B | DB03 | 0400 2000 00F2 0000 | DB mode 3 (0400, 2000, 00F2) | accepted |
| before C6 | B | DB03 | FFFE 0000 0002 0000 | DB mode 3 (FFFE, 0000, 0002) | refused 7 |
| before C6 | B | DB03 | 0000 FFFE 0002 0000 | DB mode 3 (0000, FFFE, 0002) | accepted |
| before C6 | B | DB06 | 0000 0000 0010 0000 | DB mode 6 (0000, 0000, 0010) | accepted |
| before C6 | B | DB06 | 0400 2000 00F0 0000 | DB mode 6 (0400, 2000, 00F0) | accepted |
| before C6 | B | DB06 | FFFE 0000 0002 0000 | DB mode 6 (FFFE, 0000, 0002) | accepted |
| before C6 | B | DB06 | 0000 FFFE 0002 0000 | DB mode 6 (0000, FFFE, 0002) | accepted |
| before C6 | B | DB07 | 0000 0000 0010 0000 | DB mode 7 (0000, 0000, 0010) | refused 7 |
| before C6 | B | DB07 | 1F00 0000 0100 0000 | DB mode 7 (1F00, 0000, 0100) | refused 7 |
| before C6 | B | DB07 | 1F00 0000 0102 0000 | DB mode 7 (1F00, 0000, 0102) | refused 7 |
| before C6 | B | DB07 | 0000 FF00 0100 0000 | DB mode 7 (0000, FF00, 0100) | refused 7 |
| before C6 | B | DB07 | 0000 FF00 0102 0000 | DB mode 7 (0000, FF00, 0102) | refused 7 |
| before C6 | B | DB07 | 0400 2000 00F0 0000 | DB mode 7 (0400, 2000, 00F0) | refused 7 |
| before C6 | B | DB07 | 0400 2000 00F2 0000 | DB mode 7 (0400, 2000, 00F2) | refused 7 |
| before C6 | B | DB07 | FFFE 0000 0002 0000 | DB mode 7 (FFFE, 0000, 0002) | refused 7 |
| before C6 | B | DB07 | 0000 FFFE 0002 0000 | DB mode 7 (0000, FFFE, 0002) | refused 7 |
| before C6 | A | 1B80 | - | mailbox A index 1B | refused 7 |
| before C6 | A | DBFF | - | mailbox A index 1B, high bits and low byte set | refused 7 |
| after C6 | B | 9Bxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | DBxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | DB00 | 0000 0000 0010 0000 | DB mode 0 (0000, 0000, 0010) | refused 7 |
| after C6 | B | DB00 | 1F00 0000 0100 0000 | DB mode 0 (1F00, 0000, 0100) | refused 7 |
| after C6 | B | DB00 | 1F00 0000 0102 0000 | DB mode 0 (1F00, 0000, 0102) | refused 7 |
| after C6 | B | DB00 | 0000 FF00 0100 0000 | DB mode 0 (0000, FF00, 0100) | refused 7 |
| after C6 | B | DB00 | 0000 FF00 0102 0000 | DB mode 0 (0000, FF00, 0102) | refused 7 |
| after C6 | B | DB00 | 0400 2000 00F0 0000 | DB mode 0 (0400, 2000, 00F0) | refused 7 |
| after C6 | B | DB00 | 0400 2000 00F2 0000 | DB mode 0 (0400, 2000, 00F2) | refused 7 |
| after C6 | B | DB00 | FFFE 0000 0002 0000 | DB mode 0 (FFFE, 0000, 0002) | refused 7 |
| after C6 | B | DB00 | 0000 FFFE 0002 0000 | DB mode 0 (0000, FFFE, 0002) | refused 7 |
| after C6 | B | DB02 | 0000 0000 0010 0000 | DB mode 2 (0000, 0000, 0010) | refused 7 |
| after C6 | B | DB02 | 1F00 0000 0100 0000 | DB mode 2 (1F00, 0000, 0100) | refused 7 |
| after C6 | B | DB02 | 1F00 0000 0102 0000 | DB mode 2 (1F00, 0000, 0102) | refused 7 |
| after C6 | B | DB02 | 0000 FF00 0100 0000 | DB mode 2 (0000, FF00, 0100) | refused 7 |
| after C6 | B | DB02 | 0000 FF00 0102 0000 | DB mode 2 (0000, FF00, 0102) | refused 7 |
| after C6 | B | DB02 | 0400 2000 00F0 0000 | DB mode 2 (0400, 2000, 00F0) | refused 7 |
| after C6 | B | DB02 | 0400 2000 00F2 0000 | DB mode 2 (0400, 2000, 00F2) | refused 7 |
| after C6 | B | DB02 | FFFE 0000 0002 0000 | DB mode 2 (FFFE, 0000, 0002) | refused 7 |
| after C6 | B | DB02 | 0000 FFFE 0002 0000 | DB mode 2 (0000, FFFE, 0002) | refused 7 |
| after C6 | B | DB03 | 0000 0000 0010 0000 | DB mode 3 (0000, 0000, 0010) | accepted |
| after C6 | B | DB03 | 1F00 0000 0100 0000 | DB mode 3 (1F00, 0000, 0100) | accepted |
| after C6 | B | DB03 | 1F00 0000 0102 0000 | DB mode 3 (1F00, 0000, 0102) | refused 7 |
| after C6 | B | DB03 | 0000 FF00 0100 0000 | DB mode 3 (0000, FF00, 0100) | accepted |
| after C6 | B | DB03 | 0000 FF00 0102 0000 | DB mode 3 (0000, FF00, 0102) | refused 7 |
| after C6 | B | DB03 | 0400 2000 00F0 0000 | DB mode 3 (0400, 2000, 00F0) | accepted |
| after C6 | B | DB03 | 0400 2000 00F2 0000 | DB mode 3 (0400, 2000, 00F2) | accepted |
| after C6 | B | DB03 | FFFE 0000 0002 0000 | DB mode 3 (FFFE, 0000, 0002) | refused 7 |
| after C6 | B | DB03 | 0000 FFFE 0002 0000 | DB mode 3 (0000, FFFE, 0002) | accepted |
| after C6 | B | DB06 | 0000 0000 0010 0000 | DB mode 6 (0000, 0000, 0010) | accepted |
| after C6 | B | DB06 | 0400 2000 00F0 0000 | DB mode 6 (0400, 2000, 00F0) | accepted |
| after C6 | B | DB06 | FFFE 0000 0002 0000 | DB mode 6 (FFFE, 0000, 0002) | accepted |
| after C6 | B | DB06 | 0000 FFFE 0002 0000 | DB mode 6 (0000, FFFE, 0002) | accepted |
| after C6 | B | DB07 | 0000 0000 0010 0000 | DB mode 7 (0000, 0000, 0010) | refused 7 |
| after C6 | B | DB07 | 1F00 0000 0100 0000 | DB mode 7 (1F00, 0000, 0100) | refused 7 |
| after C6 | B | DB07 | 1F00 0000 0102 0000 | DB mode 7 (1F00, 0000, 0102) | refused 7 |
| after C6 | B | DB07 | 0000 FF00 0100 0000 | DB mode 7 (0000, FF00, 0100) | refused 7 |
| after C6 | B | DB07 | 0000 FF00 0102 0000 | DB mode 7 (0000, FF00, 0102) | refused 7 |
| after C6 | B | DB07 | 0400 2000 00F0 0000 | DB mode 7 (0400, 2000, 00F0) | refused 7 |
| after C6 | B | DB07 | 0400 2000 00F2 0000 | DB mode 7 (0400, 2000, 00F2) | refused 7 |
| after C6 | B | DB07 | FFFE 0000 0002 0000 | DB mode 7 (FFFE, 0000, 0002) | refused 7 |
| after C6 | B | DB07 | 0000 FFFE 0002 0000 | DB mode 7 (0000, FFFE, 0002) | refused 7 |
| after C6 | A | 1B80 | - | mailbox A index 1B | refused 7 |
| after C6 | A | DBFF | - | mailbox A index 1B, high bits and low byte set | refused 7 |

## Index 1C

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 9Cxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | DCxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 1C80 | - | mailbox A index 1C | refused 2 |
| before C6 | A | DCFF | - | mailbox A index 1C, high bits and low byte set | refused 2 |
| after C6 | B | 9Cxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | DCxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 1C80 | - | mailbox A index 1C | refused 2 |
| after C6 | A | DCFF | - | mailbox A index 1C, high bits and low byte set | refused 2 |

## Index 1D

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 9Dxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | DDxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 1D80 | - | mailbox A index 1D | refused 2 |
| before C6 | A | DDFF | - | mailbox A index 1D, high bits and low byte set | refused 2 |
| after C6 | B | 9Dxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | DDxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 1D80 | - | mailbox A index 1D | refused 2 |
| after C6 | A | DDFF | - | mailbox A index 1D, high bits and low byte set | refused 2 |

## Index 1E

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 9Exx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | DExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 1E80 | - | mailbox A index 1E | refused 2 |
| before C6 | A | DEFF | - | mailbox A index 1E, high bits and low byte set | refused 2 |
| after C6 | B | 9Exx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | DExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 1E80 | - | mailbox A index 1E | refused 2 |
| after C6 | A | DEFF | - | mailbox A index 1E, high bits and low byte set | refused 2 |

## Index 1F

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | 9Fxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | DFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| before C6 | B | DF00 | 1C00 0000 0000 0000 | DF slot 0 | accepted |
| before C6 | B | DF01 | 1C00 0000 0000 0000 | DF slot 1 | accepted |
| before C6 | B | DF02 | 1C00 0000 0000 0000 | DF slot 2 | accepted |
| before C6 | B | DF03 | 1C00 0000 0000 0000 | DF slot 3 | accepted |
| before C6 | B | DF04 | 1C00 0000 0000 0000 | DF slot 4 | accepted |
| before C6 | B | DF05 | 1C00 0000 0000 0000 | DF slot 5 | accepted |
| before C6 | B | DF08 | 1C00 0000 0000 0000 | DF slot 8 | accepted |
| before C6 | B | DF09 | 1C00 0000 0000 0000 | DF slot 9 | accepted |
| before C6 | B | DF0A | 1C00 0000 0000 0000 | DF slot 10 | accepted |
| before C6 | B | DF7F | 1C00 0000 0000 0000 | DF slot 127 | accepted |
| before C6 | B | DFFF | 1C00 0000 0000 0000 | DF slot 255 | accepted |
| before C6 | B | DF01 | 1DFE 0000 0000 0000 | DF to 1DFE | accepted |
| before C6 | B | DF01 | 1DFF 0000 0000 0000 | DF to 1DFF | accepted |
| before C6 | B | DF01 | 1E00 0000 0000 0000 | DF to 1E00 | refused 7 |
| before C6 | B | DF01 | FFFF 0000 0000 0000 | DF to FFFF | refused 7 |
| before C6 | A | 1F80 | - | mailbox A index 1F | refused 7 |
| before C6 | A | DFFF | - | mailbox A index 1F, high bits and low byte set | refused 7 |
| after C6 | B | 9Fxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | DFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | DF00 | 1C00 0000 0000 0000 | DF slot 0 | accepted |
| after C6 | B | DF01 | 1C00 0000 0000 0000 | DF slot 1 | accepted |
| after C6 | B | DF02 | 1C00 0000 0000 0000 | DF slot 2 | accepted |
| after C6 | B | DF03 | 1C00 0000 0000 0000 | DF slot 3 | accepted |
| after C6 | B | DF04 | 1C00 0000 0000 0000 | DF slot 4 | accepted |
| after C6 | B | DF05 | 1C00 0000 0000 0000 | DF slot 5 | accepted |
| after C6 | B | DF08 | 1C00 0000 0000 0000 | DF slot 8 | accepted |
| after C6 | B | DF09 | 1C00 0000 0000 0000 | DF slot 9 | accepted |
| after C6 | B | DF0A | 1C00 0000 0000 0000 | DF slot 10 | accepted |
| after C6 | B | DF7F | 1C00 0000 0000 0000 | DF slot 127 | accepted |
| after C6 | B | DFFF | 1C00 0000 0000 0000 | DF slot 255 | accepted |
| after C6 | B | DF01 | 1DFE 0000 0000 0000 | DF to 1DFE | accepted |
| after C6 | B | DF01 | 1DFF 0000 0000 0000 | DF to 1DFF | accepted |
| after C6 | B | DF01 | 1E00 0000 0000 0000 | DF to 1E00 | refused 7 |
| after C6 | B | DF01 | FFFF 0000 0000 0000 | DF to FFFF | refused 7 |
| after C6 | A | 1F80 | - | mailbox A index 1F | refused 7 |
| after C6 | A | DFFF | - | mailbox A index 1F, high bits and low byte set | refused 7 |

## Index 20

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | A0xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | E0xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | E000 | BEEF 0200 0000 0000 | E0 slot 0 | accepted |
| before C6 | B | E001 | BEEF 0200 0000 0000 | E0 slot 1 | accepted |
| before C6 | B | E002 | BEEF 0200 0000 0000 | E0 slot 2 | accepted |
| before C6 | B | E003 | BEEF 0200 0000 0000 | E0 slot 3 | accepted |
| before C6 | B | E004 | BEEF 0200 0000 0000 | E0 slot 4 | accepted |
| before C6 | B | E005 | BEEF 0200 0000 0000 | E0 slot 5 | accepted |
| before C6 | B | E008 | BEEF 0200 0000 0000 | E0 slot 8 | accepted |
| before C6 | B | E009 | BEEF 0200 0000 0000 | E0 slot 9 | accepted |
| before C6 | B | E00A | BEEF 0200 0000 0000 | E0 slot 10 | accepted |
| before C6 | B | E07F | BEEF 0200 0000 0000 | E0 slot 127 | accepted |
| before C6 | B | E0FF | BEEF 0200 0000 0000 | E0 slot 255 | accepted |
| before C6 | B | E001 | BEEE 0200 0000 0000 | E0 key BEEE from 0200 | refused 7 |
| before C6 | B | E001 | BEEF 1DFF 0000 0000 | E0 key BEEF from 1DFF | accepted |
| before C6 | B | E001 | BEEF 1E00 0000 0000 | E0 key BEEF from 1E00 | refused 7 |
| before C6 | B | E001 | 0000 0200 0000 0000 | E0 key 0000 from 0200 | refused 7 |
| before C6 | B | E001 | EFBE 0200 0000 0000 | E0 key EFBE from 0200 | refused 7 |
| before C6 | A | 2080 | - | mailbox A index 20 | refused 7 |
| before C6 | A | E0FF | - | mailbox A index 20, high bits and low byte set | refused 7 |
| after C6 | B | A0xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | E0xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | E000 | BEEF 0200 0000 0000 | E0 slot 0 | accepted |
| after C6 | B | E001 | BEEF 0200 0000 0000 | E0 slot 1 | accepted |
| after C6 | B | E002 | BEEF 0200 0000 0000 | E0 slot 2 | accepted |
| after C6 | B | E003 | BEEF 0200 0000 0000 | E0 slot 3 | accepted |
| after C6 | B | E004 | BEEF 0200 0000 0000 | E0 slot 4 | accepted |
| after C6 | B | E005 | BEEF 0200 0000 0000 | E0 slot 5 | accepted |
| after C6 | B | E008 | BEEF 0200 0000 0000 | E0 slot 8 | accepted |
| after C6 | B | E009 | BEEF 0200 0000 0000 | E0 slot 9 | accepted |
| after C6 | B | E00A | BEEF 0200 0000 0000 | E0 slot 10 | accepted |
| after C6 | B | E07F | BEEF 0200 0000 0000 | E0 slot 127 | accepted |
| after C6 | B | E0FF | BEEF 0200 0000 0000 | E0 slot 255 | accepted |
| after C6 | B | E001 | BEEE 0200 0000 0000 | E0 key BEEE from 0200 | refused 7 |
| after C6 | B | E001 | BEEF 1DFF 0000 0000 | E0 key BEEF from 1DFF | accepted |
| after C6 | B | E001 | BEEF 1E00 0000 0000 | E0 key BEEF from 1E00 | refused 7 |
| after C6 | B | E001 | 0000 0200 0000 0000 | E0 key 0000 from 0200 | refused 7 |
| after C6 | B | E001 | EFBE 0200 0000 0000 | E0 key EFBE from 0200 | refused 7 |
| after C6 | A | 2080 | - | mailbox A index 20 | refused 7 |
| after C6 | A | E0FF | - | mailbox A index 20, high bits and low byte set | refused 7 |

## Index 21

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | A1xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | E1xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 2180 | - | mailbox A index 21 | refused 2 |
| before C6 | A | E1FF | - | mailbox A index 21, high bits and low byte set | refused 2 |
| after C6 | B | A1xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | E1xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 2180 | - | mailbox A index 21 | refused 2 |
| after C6 | A | E1FF | - | mailbox A index 21, high bits and low byte set | refused 2 |

## Index 22

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | A2xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | E2xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 2280 | - | mailbox A index 22 | refused 2 |
| before C6 | A | E2FF | - | mailbox A index 22, high bits and low byte set | refused 2 |
| after C6 | B | A2xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | E2xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 2280 | - | mailbox A index 22 | refused 2 |
| after C6 | A | E2FF | - | mailbox A index 22, high bits and low byte set | refused 2 |

## Index 23

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | A3xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | E3xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 2380 | - | mailbox A index 23 | refused 2 |
| before C6 | A | E3FF | - | mailbox A index 23, high bits and low byte set | refused 2 |
| after C6 | B | A3xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | E3xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 2380 | - | mailbox A index 23 | refused 2 |
| after C6 | A | E3FF | - | mailbox A index 23, high bits and low byte set | refused 2 |

## Index 24

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | A4xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | E4xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | A | 2480 | - | mailbox A index 24 | accepted |
| before C6 | A | E4FF | - | mailbox A index 24, high bits and low byte set | accepted |
| before C6 | B | A400 | 0000 0000 0000 0000 | MegaWire A400 | accepted |
| before C6 | B | A401 | 0000 0000 0000 0000 | MegaWire A401 | accepted |
| before C6 | B | E400 | 0000 0000 0000 0000 | MegaWire E400 | refused 7 |
| after C6 | B | A4xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | E4xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | A | 2480 | - | mailbox A index 24 | accepted |
| after C6 | A | E4FF | - | mailbox A index 24, high bits and low byte set | accepted |
| after C6 | B | A400 | 0000 0000 0000 0000 | MegaWire A400 | accepted |
| after C6 | B | A401 | 0000 0000 0000 0000 | MegaWire A401 | accepted |
| after C6 | B | E400 | 0000 0000 0000 0000 | MegaWire E400 | refused 7 |

## Index 25

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | A5xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | E5xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 2580 | - | mailbox A index 25 | refused 2 |
| before C6 | A | E5FF | - | mailbox A index 25, high bits and low byte set | refused 2 |
| after C6 | B | A5xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | E5xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 2580 | - | mailbox A index 25 | refused 2 |
| after C6 | A | E5FF | - | mailbox A index 25, high bits and low byte set | refused 2 |

## Index 26

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | A6xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | E6xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | A | 2680 | - | mailbox A index 26 | accepted |
| before C6 | A | E6FF | - | mailbox A index 26, high bits and low byte set | accepted |
| before C6 | B | A600 | 0000 0000 0000 0000 | MegaWire A600 | accepted |
| before C6 | B | E600 | 0000 0000 0000 0000 | MegaWire E600 | refused 7 |
| after C6 | B | A6xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | E6xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | A | 2680 | - | mailbox A index 26 | accepted |
| after C6 | A | E6FF | - | mailbox A index 26, high bits and low byte set | accepted |
| after C6 | B | A600 | 0000 0000 0000 0000 | MegaWire A600 | accepted |
| after C6 | B | E600 | 0000 0000 0000 0000 | MegaWire E600 | refused 7 |

## Index 27

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | A7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | E7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | E700 | 0000 0000 0000 0000 | E7 length 0000 | accepted |
| before C6 | B | E700 | 0000 00FB 0000 0000 | E7 length 00FB | accepted |
| before C6 | B | E700 | 0000 00FC 0000 0000 | E7 length 00FC | refused 7 |
| before C6 | B | E700 | 0000 FFFF 0000 0000 | E7 length FFFF | refused 7 |
| before C6 | A | 2780 | - | mailbox A index 27 | refused 7 |
| before C6 | A | E7FF | - | mailbox A index 27, high bits and low byte set | refused 7 |
| before C6 | B | E700 | 0000 0010 0000 0000 | E7 (a send) | accepted |
| before C6 | B | E700 | 0000 0010 0000 0000 | E7 again (send pending) | refused 6 |
| after C6 | B | A7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | E7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | E700 | 0000 0000 0000 0000 | E7 length 0000 | accepted |
| after C6 | B | E700 | 0000 00FB 0000 0000 | E7 length 00FB | accepted |
| after C6 | B | E700 | 0000 00FC 0000 0000 | E7 length 00FC | refused 7 |
| after C6 | B | E700 | 0000 FFFF 0000 0000 | E7 length FFFF | refused 7 |
| after C6 | A | 2780 | - | mailbox A index 27 | refused 7 |
| after C6 | A | E7FF | - | mailbox A index 27, high bits and low byte set | refused 7 |
| after C6 | B | E700 | 0000 0010 0000 0000 | E7 (a send) | accepted |
| after C6 | B | E700 | 0000 0010 0000 0000 | E7 again (send pending) | refused 6 |

## Index 28

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | A800 | 0000 0000 0000 0000 | MegaWire A800 | refused 7 |
| before C6 | B | E858 | 0000 0000 0000 0000 | MegaWire E858 | refused 7 |
| before C6 | A | 2880 | - | mailbox A A8 | refused 7 |
| after C6 | B | A800 | 0000 0000 0000 0000 | MegaWire A800 | refused 7 |
| after C6 | B | E858 | 0000 0000 0000 0000 | MegaWire E858 | refused 7 |
| after C6 | A | 2880 | - | mailbox A A8 | refused 7 |
| after C6 | B | A858 | 0000 0000 0000 0000 | A858 (the MegaWire screen) | accepted |

## Index 29

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | A9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | E9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | A | 2980 | - | mailbox A index 29 | accepted |
| before C6 | A | E9FF | - | mailbox A index 29, high bits and low byte set | accepted |
| before C6 | B | A900 | 0000 0000 0000 0000 | MegaWire A900 | accepted |
| before C6 | B | E900 | 0000 0000 0000 0000 | MegaWire E900 | refused 7 |
| before C6 | B | A900 | 0000 0000 0000 0000 | A9 after E7 | accepted |
| after C6 | B | A9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | E9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | A | 2980 | - | mailbox A index 29 | accepted |
| after C6 | A | E9FF | - | mailbox A index 29, high bits and low byte set | accepted |
| after C6 | B | A900 | 0000 0000 0000 0000 | MegaWire A900 | accepted |
| after C6 | B | E900 | 0000 0000 0000 0000 | MegaWire E900 | refused 7 |
| after C6 | B | A900 | 0000 0000 0000 0000 | A9 after E7 | accepted |

## Index 2A

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | AAxx | - | low byte 00 01 02 05 07 3F 40 7F 80 FF | refused 7 |
| before C6 | B | AAxx | - | low byte 58 | accepted |
| before C6 | B | EAxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | A | 2A80 | - | mailbox A index 2A | refused 7 |
| before C6 | A | EAFF | - | mailbox A index 2A, high bits and low byte set | refused 7 |
| before C6 | B | AA00 | 0000 0000 0000 0000 | MegaWire AA00 | refused 7 |
| before C6 | B | AA57 | 0000 0000 0000 0000 | MegaWire AA57 | refused 7 |
| before C6 | B | EA58 | 0000 0000 0000 0000 | MegaWire EA58 | refused 7 |
| after C6 | B | AAxx | - | low byte 00 01 02 05 07 3F 40 7F 80 FF | refused 7 |
| after C6 | B | AAxx | - | low byte 58 | accepted |
| after C6 | B | EAxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | A | 2A80 | - | mailbox A index 2A | refused 7 |
| after C6 | A | EAFF | - | mailbox A index 2A, high bits and low byte set | refused 7 |
| after C6 | B | AA00 | 0000 0000 0000 0000 | MegaWire AA00 | refused 7 |
| after C6 | B | AA57 | 0000 0000 0000 0000 | MegaWire AA57 | refused 7 |
| after C6 | B | EA58 | 0000 0000 0000 0000 | MegaWire EA58 | refused 7 |

## Index 2B

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | ABxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | EBxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 2B80 | - | mailbox A index 2B | refused 2 |
| before C6 | A | EBFF | - | mailbox A index 2B, high bits and low byte set | refused 2 |
| after C6 | B | ABxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | EBxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 2B80 | - | mailbox A index 2B | refused 2 |
| after C6 | A | EBFF | - | mailbox A index 2B, high bits and low byte set | refused 2 |

## Index 2C

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | ACxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | ECxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | EC00 | 0000 0028 0000 0000 | EC (0, 28) | refused 6 |
| before C6 | B | EC00 | 0000 0035 0000 0000 | EC (0, 35) | refused 6 |
| before C6 | B | EC00 | 0000 0081 0000 0000 | EC (0, 81) | refused 6 |
| before C6 | B | EC00 | 0001 0028 0000 0000 | EC (1, 28) | refused 6 |
| before C6 | B | EC00 | 0000 0000 0000 0000 | EC (0, 0) | refused 6 |
| before C6 | B | EC00 | 0000 FFFF 0000 0000 | EC (0, FFFF) | refused 6 |
| before C6 | B | EC00 | 0000 0028 0000 0000 | EC (0, 28) | refused 6 |
| before C6 | A | 2C80 | - | mailbox A index 2C | refused 6 |
| before C6 | A | ECFF | - | mailbox A index 2C, high bits and low byte set | refused 6 |
| after C6 | B | ACxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | ECxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | EC00 | 0000 0028 0000 0000 | EC (0, 28) | accepted |
| after C6 | B | EC00 | 0000 0035 0000 0000 | EC (0, 35) | accepted |
| after C6 | B | EC00 | 0000 0081 0000 0000 | EC (0, 81) | refused 7 |
| after C6 | B | EC00 | 0001 0028 0000 0000 | EC (1, 28) | refused 7 |
| after C6 | B | EC00 | 0000 0000 0000 0000 | EC (0, 0) | accepted |
| after C6 | B | EC00 | 0000 FFFF 0000 0000 | EC (0, FFFF) | refused 7 |
| after C6 | B | EC00 | 0000 0028 0000 0000 | EC (0, 28) | accepted |
| after C6 | A | 2C80 | - | mailbox A index 2C | refused 7 |
| after C6 | A | ECFF | - | mailbox A index 2C, high bits and low byte set | refused 7 |
| after C6 | B | EC00 | 0000 0080 0000 0000 | EC (0, 80): above card 5's cap (allow-list B48) | accepted |
| after C6 | B | EC00 | 0000 0028 0000 0000 | EC (0, 28) after it (allow-list B48) | accepted |

## Index 2D

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | ADxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | EDxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | AD00 | 0000 0000 0000 0000 | AD 00 | refused 6 |
| before C6 | B | AD3F | 0000 0000 0000 0000 | AD 3F | refused 6 |
| before C6 | B | AD40 | 0000 0000 0000 0000 | AD 40 | refused 6 |
| before C6 | B | ADFF | 0000 0000 0000 0000 | AD FF | refused 6 |
| before C6 | A | 2D80 | - | mailbox A index 2D | refused 6 |
| before C6 | A | EDFF | - | mailbox A index 2D, high bits and low byte set | refused 6 |
| after C6 | B | ADxx | - | low byte 00 01 02 05 07 3F | accepted |
| after C6 | B | ADxx | - | low byte 40 58 7F 80 FF | refused 7 |
| after C6 | B | EDxx | - | low byte 00 01 02 05 07 3F | accepted |
| after C6 | B | EDxx | - | low byte 40 58 7F 80 FF | refused 7 |
| after C6 | B | AD00 | 0000 0000 0000 0000 | AD 00 | accepted |
| after C6 | B | AD3F | 0000 0000 0000 0000 | AD 3F | accepted |
| after C6 | B | AD40 | 0000 0000 0000 0000 | AD 40 | refused 7 |
| after C6 | B | ADFF | 0000 0000 0000 0000 | AD FF | refused 7 |
| after C6 | A | 2D80 | - | mailbox A index 2D | accepted |
| after C6 | A | EDFF | - | mailbox A index 2D, high bits and low byte set | accepted |

## Index 2E

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | AExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | EExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | AE00 | 0000 0000 0000 0000 | AE00 | refused 6 |
| before C6 | A | 2E80 | - | mailbox A index 2E | refused 6 |
| before C6 | A | EEFF | - | mailbox A index 2E, high bits and low byte set | refused 6 |
| after C6 | B | AExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | EExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | AE00 | 0000 0000 0000 0000 | AE00 | accepted |
| after C6 | A | 2E80 | - | mailbox A index 2E | accepted |
| after C6 | A | EEFF | - | mailbox A index 2E, high bits and low byte set | accepted |

## Index 2F

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | AFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | EFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | AF00 | 0000 0000 0000 0000 | AF00 | refused 6 |
| before C6 | B | AF01 | 0000 0000 0000 0000 | AF01 | refused 6 |
| before C6 | A | 2F80 | - | mailbox A index 2F | refused 6 |
| before C6 | A | EFFF | - | mailbox A index 2F, high bits and low byte set | refused 6 |
| after C6 | B | AFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | EFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | AF00 | 0000 0000 0000 0000 | AF00 | accepted |
| after C6 | B | AF01 | 0000 0000 0000 0000 | AF01 | accepted |
| after C6 | A | 2F80 | - | mailbox A index 2F | accepted |
| after C6 | A | EFFF | - | mailbox A index 2F, high bits and low byte set | accepted |

## Index 30

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | B0xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | F0xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | B000 | 0000 0000 0000 0000 | B000 | refused 6 |
| before C6 | B | F000 | 0000 0000 0000 0000 | F000 | refused 6 |
| before C6 | A | 3080 | - | mailbox A index 30 | refused 6 |
| before C6 | A | F0FF | - | mailbox A index 30, high bits and low byte set | refused 6 |
| after C6 | B | B0xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | F0xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | B000 | 0000 0000 0000 0000 | B000 | accepted |
| after C6 | B | F000 | 0000 0000 0000 0000 | F000 | accepted |
| after C6 | A | 3080 | - | mailbox A index 30 | accepted |
| after C6 | A | F0FF | - | mailbox A index 30, high bits and low byte set | accepted |

## Index 31

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | B1xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | F1xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | B100 | 0000 0000 0000 0000 | B100 | refused 6 |
| before C6 | B | F100 | 0000 0000 0000 0000 | F100 | refused 6 |
| before C6 | A | 3180 | - | mailbox A index 31 | refused 6 |
| before C6 | A | F1FF | - | mailbox A index 31, high bits and low byte set | refused 6 |
| after C6 | B | B1xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | F1xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | B100 | 0000 0000 0000 0000 | B100 | accepted |
| after C6 | B | F100 | 0000 0000 0000 0000 | F100 | accepted |
| after C6 | A | 3180 | - | mailbox A index 31 | accepted |
| after C6 | A | F1FF | - | mailbox A index 31, high bits and low byte set | accepted |

## Index 32

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | B2xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | F2xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 6 |
| before C6 | B | F200 | 0000 0000 0000 0000 | F2 block 0 | refused 6 |
| before C6 | B | F200 | 0001 0000 0000 0000 | F2 block 1 | refused 6 |
| before C6 | B | F200 | 0002 0000 0000 0000 | F2 block 2 | refused 6 |
| before C6 | B | F200 | 3025 0000 0000 0000 | F2 block 12325 | refused 6 |
| before C6 | B | F200 | 3026 0000 0000 0000 | F2 block 12326 | refused 6 |
| before C6 | B | F200 | 3027 0000 0000 0000 | F2 block 12327 | refused 6 |
| before C6 | B | F200 | 7FFF 0000 0000 0000 | F2 block 32767 | refused 6 |
| before C6 | B | F200 | FFFF 0000 0000 0000 | F2 block 65535 | refused 6 |
| before C6 | A | 3280 | - | mailbox A index 32 | refused 6 |
| before C6 | A | F2FF | - | mailbox A index 32, high bits and low byte set | refused 6 |
| after C6 | B | B2xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | F2xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | F200 | 0000 0000 0000 0000 | F2 block 0 | accepted |
| after C6 | B | F200 | 0001 0000 0000 0000 | F2 block 1 | accepted |
| after C6 | B | F200 | 0002 0000 0000 0000 | F2 block 2 | accepted |
| after C6 | B | F200 | 3025 0000 0000 0000 | F2 block 12325 | accepted |
| after C6 | B | F200 | 3026 0000 0000 0000 | F2 block 12326 | accepted |
| after C6 | B | F200 | 3027 0000 0000 0000 | F2 block 12327 | accepted |
| after C6 | B | F200 | 7FFF 0000 0000 0000 | F2 block 32767 | accepted |
| after C6 | B | F200 | FFFF 0000 0000 0000 | F2 block 65535 | accepted |
| after C6 | A | 3280 | - | mailbox A index 32 | refused 7 |
| after C6 | A | F2FF | - | mailbox A index 32, high bits and low byte set | refused 7 |

## Index 33

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | B3xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | F3xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 3380 | - | mailbox A index 33 | refused 2 |
| before C6 | A | F3FF | - | mailbox A index 33, high bits and low byte set | refused 2 |
| after C6 | B | B3xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | F3xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 3380 | - | mailbox A index 33 | refused 2 |
| after C6 | A | F3FF | - | mailbox A index 33, high bits and low byte set | refused 2 |

## Index 34

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | B4xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | F4xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | F400 | from the ROM | F4 the game's first zoom picture | accepted |
| before C6 | B | F400 | from the ROM | F4 a source of another type | refused 7 |
| before C6 | B | F400 | 0080 0000 0000 0000 | F4 source 800000 | refused 7 |
| before C6 | B | F400 | 0080 0002 0000 0000 | F4 source 800002 | refused 7 |
| before C6 | A | 3480 | - | mailbox A index 34 | refused 7 |
| before C6 | A | F4FF | - | mailbox A index 34, high bits and low byte set | refused 7 |
| after C6 | B | B4xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | F4xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | F400 | from the ROM | F4 the game's first zoom picture | accepted |
| after C6 | B | F400 | from the ROM | F4 a source of another type | refused 7 |
| after C6 | B | F400 | 0080 0000 0000 0000 | F4 source 800000 | refused 7 |
| after C6 | B | F400 | 0080 0002 0000 0000 | F4 source 800002 | refused 7 |
| after C6 | A | 3480 | - | mailbox A index 34 | refused 7 |
| after C6 | A | F4FF | - | mailbox A index 34, high bits and low byte set | refused 7 |
| after C6 | B | F400 | from the ROM | F4 a 0x81 stream that is no zoom picture (allow-list B57) | accepted |
| after C6 | B | F400 | from the ROM | F4 a 0x80 stream that is no zoom picture (allow-list B57) | accepted |

## Index 35

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | B5xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | F5xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| before C6 | B | F500 | 0100 0100 0020 0020 | F5 (0100, 0100, 0020, 0020) | accepted |
| before C6 | B | F500 | 0000 0000 0000 0000 | F5 (0000, 0000, 0000, 0000) | accepted |
| before C6 | A | 3580 | - | mailbox A index 35 | refused 7 |
| before C6 | A | F5FF | - | mailbox A index 35, high bits and low byte set | refused 7 |
| after C6 | B | B5xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | F5xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | F500 | 0100 0100 0020 0020 | F5 (0100, 0100, 0020, 0020) | accepted |
| after C6 | B | F500 | 0000 0000 0000 0000 | F5 (0000, 0000, 0000, 0000) | accepted |
| after C6 | A | 3580 | - | mailbox A index 35 | refused 7 |
| after C6 | A | F5FF | - | mailbox A index 35, high bits and low byte set | refused 7 |

## Index 36

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | B6xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| before C6 | B | F6xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| before C6 | B | B600 | 0000 0000 0000 0000 | B6 | accepted |
| before C6 | B | F600 | 0000 0000 0000 0000 | B6 with the argument flag | refused 7 |
| before C6 | B | B600 | 0000 0000 0000 0000 | B6 again (no session) | accepted |
| before C6 | A | 3680 | - | mailbox A index 36 | accepted |
| before C6 | A | F6FF | - | mailbox A index 36, high bits and low byte set | accepted |
| after C6 | B | B6xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | accepted |
| after C6 | B | F6xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 7 |
| after C6 | B | B600 | 0000 0000 0000 0000 | B6 | accepted |
| after C6 | B | F600 | 0000 0000 0000 0000 | B6 with the argument flag | refused 7 |
| after C6 | B | B600 | 0000 0000 0000 0000 | B6 again (no session) | accepted |
| after C6 | A | 3680 | - | mailbox A index 36 | accepted |
| after C6 | A | F6FF | - | mailbox A index 36, high bits and low byte set | accepted |

## Index 37

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | B7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | F7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 3780 | - | mailbox A index 37 | refused 2 |
| before C6 | A | F7FF | - | mailbox A index 37, high bits and low byte set | refused 2 |
| after C6 | B | B7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | F7xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 3780 | - | mailbox A index 37 | refused 2 |
| after C6 | A | F7FF | - | mailbox A index 37, high bits and low byte set | refused 2 |

## Index 38

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | B8xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | F8xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 3880 | - | mailbox A index 38 | refused 2 |
| before C6 | A | F8FF | - | mailbox A index 38, high bits and low byte set | refused 2 |
| after C6 | B | B8xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | F8xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 3880 | - | mailbox A index 38 | refused 2 |
| after C6 | A | F8FF | - | mailbox A index 38, high bits and low byte set | refused 2 |

## Index 39

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | B9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | F9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 3980 | - | mailbox A index 39 | refused 2 |
| before C6 | A | F9FF | - | mailbox A index 39, high bits and low byte set | refused 2 |
| after C6 | B | B9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | F9xx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 3980 | - | mailbox A index 39 | refused 2 |
| after C6 | A | F9FF | - | mailbox A index 39, high bits and low byte set | refused 2 |

## Index 3A

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | BAxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | FAxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 3A80 | - | mailbox A index 3A | refused 2 |
| before C6 | A | FAFF | - | mailbox A index 3A, high bits and low byte set | refused 2 |
| after C6 | B | BAxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | FAxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 3A80 | - | mailbox A index 3A | refused 2 |
| after C6 | A | FAFF | - | mailbox A index 3A, high bits and low byte set | refused 2 |

## Index 3B

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | BBxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | FBxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 3B80 | - | mailbox A index 3B | refused 2 |
| before C6 | A | FBFF | - | mailbox A index 3B, high bits and low byte set | refused 2 |
| after C6 | B | BBxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | FBxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 3B80 | - | mailbox A index 3B | refused 2 |
| after C6 | A | FBFF | - | mailbox A index 3B, high bits and low byte set | refused 2 |

## Index 3C

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | BCxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | FCxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 3C80 | - | mailbox A index 3C | refused 2 |
| before C6 | A | FCFF | - | mailbox A index 3C, high bits and low byte set | refused 2 |
| after C6 | B | BCxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | FCxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 3C80 | - | mailbox A index 3C | refused 2 |
| after C6 | A | FCFF | - | mailbox A index 3C, high bits and low byte set | refused 2 |

## Index 3D

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | BDxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | FDxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 3D80 | - | mailbox A index 3D | refused 2 |
| before C6 | A | FDFF | - | mailbox A index 3D, high bits and low byte set | refused 2 |
| after C6 | B | BDxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | FDxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 3D80 | - | mailbox A index 3D | refused 2 |
| after C6 | A | FDFF | - | mailbox A index 3D, high bits and low byte set | refused 2 |

## Index 3E

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | BExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | FExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | A | 3E80 | - | mailbox A index 3E | refused 2 |
| before C6 | A | FEFF | - | mailbox A index 3E, high bits and low byte set | refused 2 |
| after C6 | B | BExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | FExx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | A | 3E80 | - | mailbox A index 3E | refused 2 |
| after C6 | A | FEFF | - | mailbox A index 3E, high bits and low byte set | refused 2 |

## Index 3F

| state | mailbox | word | arguments | form | the cart chip |
|---|---|---|---|---|---|
| before C6 | B | BFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | FFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| before C6 | B | 7FFF | 0000 0000 0000 0000 | no request bit | finish only |
| before C6 | A | 3F80 | - | mailbox A index 3F | refused 2 |
| before C6 | A | FFFF | - | mailbox A index 3F, high bits and low byte set | refused 2 |
| after C6 | B | BFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | FFxx | - | low byte 00 01 02 05 07 3F 40 58 7F 80 FF | refused 2 |
| after C6 | B | 7FFF | 0000 0000 0000 0000 | no request bit | finish only |
| after C6 | A | 3F80 | - | mailbox A index 3F | refused 2 |
| after C6 | A | FFFF | - | mailbox A index 3F, high bits and low byte set | refused 2 |
