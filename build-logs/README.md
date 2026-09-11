# Build logs

Quartus console output from every fit of the Paprium core since the 0.1.0 release,
one file per run. Each is the full `quartus_sh -t generate.tcl paprium <seed>` transcript:
analysis, fitter, assembler and the timing report. They are kept so a placement or a
slack figure quoted in [docs/PORT_PLAN.md](../docs/PORT_PLAN.md) can be checked against
the run that produced it.

How a log is produced (from the repo root, Git Bash):

```bash
PATH=/c/intelFPGA_lite/21.1/quartus/bin64:$PATH nohup quartus_sh -t generate.tcl paprium 5 > build-logs/build-<name>.log 2>&1
```

Reading one: the gate is the **first** "Worst-case setup slack" / "Worst-case hold slack"
pair in the file (slow 1100 mV 85 °C corner). The later pairs are the other corners. ALM
usage is not in the log; it is in `projects/output_files/megadrive_pocket.fit.summary`
after the run, and in the PORT_PLAN entry for each card.

The table below is extracted from the files themselves. Runs whose RTL is unchanged from
the 0.1.0 ring (firmware-only changes, seed 5) all land on the same placement and read
-2.549 / +0.264; that is the placement the 0.2.0 bitstream shipped on (`build-scratch5.log`).
Runs with different figures carried RTL changes that were later reverted or parked.

| Log | Started | Seed | Fitter | Setup slack | Hold slack |
|---|---|---|---|---|---|
| `build.log` | Fri Sep  4 09:45:40 2026 | 5 | ok | -2.404 | 0.260 |
| `build-seed6.log` | Fri Sep  4 10:37:58 2026 | 6 | no fitter result | - | - |
| `build-control.log` | Fri Sep  4 10:44:03 2026 | 5 | ok | -2.404 | 0.260 |
| `build-cut2.log` | Fri Sep  4 11:20:01 2026 | 5 | ok | -3.343 | 0.167 |
| `build-cut2-seed6.log` | Fri Sep  4 11:45:59 2026 | 6 | ok | -2.989 | 0.271 |
| `build-cut2-seed7.log` | Fri Sep  4 12:10:35 2026 | 7 | ok | -2.812 | 0.253 |
| `build-cut2-seed8.log` | Fri Sep  4 12:34:56 2026 | 8 | ok | -4.609 | 0.266 |
| `build-cut2-seed9.log` | Fri Sep  4 12:59:22 2026 | 9 | ok | -3.241 | 0.295 |
| `build-epoch-seed6.log` | Fri Sep  4 13:24:47 2026 | 6 | ok | -2.835 | 0.274 |
| `build-epoch-seed7.log` | Fri Sep  4 13:49:50 2026 | 7 | ok | -3.057 | 0.286 |
| `build-epoch-seed8.log` | Fri Sep  4 14:19:10 2026 | 8 | ok | -2.835 | 0.295 |
| `build-epoch-seed9.log` | Fri Sep  4 14:48:43 2026 | 9 | ok | -3.235 | 0.298 |
| `build-fcut.log` | Fri Sep  4 15:13:29 2026 | 5 | ok | -2.839 | 0.278 |
| `build-pad.log` | Fri Sep  4 16:19:38 2026 | 5 | ok | -2.549 | 0.264 |
| `build-busyrest.log` | Fri Sep  4 17:39:01 2026 | 5 | ok | -2.549 | 0.264 |
| `build-pulse2.log` | Fri Sep  4 18:59:42 2026 | 5 | ok | -2.549 | 0.264 |
| `build-listorder.log` | Fri Sep  4 19:24:50 2026 | 5 | ok | -2.549 | 0.264 |
| `build-stream.log` | Fri Sep  4 20:15:18 2026 | 5 | ok | -2.549 | 0.264 |
| `build-stream2.log` | Fri Sep  4 20:53:53 2026 | 5 | ok | -2.549 | 0.264 |
| `build-stream3.log` | Fri Sep  4 22:01:36 2026 | 5 | ok | -2.549 | 0.264 |
| `build-heartbeat.log` | Sat Sep  5 09:53:57 2026 | 5 | ok | -2.549 | 0.264 |
| `build-heartbeat2.log` | Sat Sep  5 10:50:58 2026 | 5 | ok | -2.549 | 0.264 |
| `build-heartbeat3.log` | Sat Sep  5 12:03:57 2026 | 5 | ok | -2.549 | 0.264 |
| `build-sfxquiet.log` | Sat Sep  5 13:00:00 2026 | 5 | ok | -2.549 | 0.264 |
| `build-port2load.log` | Sat Sep  5 14:17:42 2026 | 5 | ok | -2.549 | 0.264 |
| `build-scratch1.log` | Sat Sep  5 16:18:26 2026 | 5 | ok | -2.549 | 0.264 |
| `build-scratch2.log` | Sat Sep  5 17:14:06 2026 | 5 | ok | -2.549 | 0.264 |
| `build-scratch3.log` | Sat Sep  5 19:13:53 2026 | 5 | ok | -2.549 | 0.264 |
| `build-scratch4.log` | Sat Sep  5 20:05:41 2026 | 5 | ok | -2.549 | 0.264 |
| `build-scratch5.log` | Sat Sep  5 20:51:57 2026 | 5 | ok | -2.549 | 0.264 |
| `build-stickyswitch.log` | Sun Sep  6 09:28:22 2026 | 5 | ok | -2.549 | 0.264 |
| `build-dmafloor.log` | Sun Sep  6 10:25:29 2026 | 5 | killed at 10:29 (floor at 0xAE, superseded) | - | - |
| `build-dmafloor2.log` | Sun Sep  6 10:30:06 2026 | 5 | ok | -2.549 | 0.264 |
| `build-chainend.log` | Sun Sep  6 11:36:02 2026 | 5 | ok | -2.549 | 0.264 |
| `build-atload.log` | Fri Sep 11 07:25:45 2026 | 5 | ok | -1.469 | 0.052 |
| `build-propgate.log` | Fri Sep 11 08:24:22 2026 | 5 | ok | -1.469 | 0.052 |
