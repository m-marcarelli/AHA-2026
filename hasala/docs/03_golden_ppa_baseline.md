# Step 03 — Golden PPA Baseline

**Date:** 2026-04-18
**Goal:** Per the competition README, place `eth_synth/` at the top level of
the cloned ethmac repo and run `run_ppa.sh`. The resulting numbers are the
**golden baseline** every Trojan is compared against for the "PPA Overhead"
stealth score (SCORING.md Part 2 — need < 1% deviation to earn "4 - Exemplary").

## Commands executed

```bash
# Copy the canonical PPA scripts into the ethmac tree (README requirement)
cp -r /home/hasala/competition/HOST_AHA_Challenge_2026/eth_synth \
      /home/hasala/competition/ethmac_workspace/ethmac/eth_synth

# Run the synthesis + STA pipeline
cd /home/hasala/competition/ethmac_workspace/ethmac/eth_synth
bash ./run_ppa.sh 2>&1 | tee ../../docs/03_golden_ppa_run.log

# Preserve a canonical copy of the metrics outside the repo tree
GM=/home/hasala/competition/ethmac_workspace/golden_metrics
cp metrics/area_report.txt                     $GM/area_report.txt
cp metrics/sta_report.txt                      $GM/sta_report.txt
cp synth_outputs/eth_synth_sky130.v            $GM/eth_synth_sky130.v
head -50 metrics/timing_report.txt             > $GM/timing_report_head.txt
tail -30 metrics/timing_report.txt             > $GM/timing_report_tail.txt
wc -l    metrics/timing_report.txt             > $GM/timing_report_fullsize.txt
```

## Baseline PPA numbers (golden)

| Metric                       | Value                                |
| ---------------------------- | ------------------------------------ |
| Chip area (sky130 units)     | **404 314.0192**                     |
| Total cells                  | **39 152**                           |
| Total wires (bits)           | 59 853 (88 969 bits)                 |
| Flip-flops (`dfrtp + dfstp + dfxtp`) | 1 140 + 101 + 9 305 = **10 546** |
| Inverters (`clkinv_1`)       | 1 353                                |
| Worst-negative slack — core_clock | **+21.7855 ns (MET)**           |
| Critical-path endpoint       | `_92452_/D (sky130_fd_sc_hd__dfrtp_1)` |
| Yosys runtime                | ~18 s user + 2 s system              |
| Synthesized netlist          | 312 283 lines, 6.9 MB                |

Clock period defined in `grade_timing.sta`: 25 ns (40 MHz).

### Raw STA report
```
max_delay/setup group core_clock
                                      Required    Actual
Endpoint                                 Delay     Delay     Slack
------------------------------------------------------------------
_92452_/D (sky130_fd_sc_hd__dfrtp_1)   99.9298   78.1444   21.7855 (MET)
```

## Stealth budget (from baseline + SCORING.md)

For a **4 - Exemplary** PPA score (< 1% deviation averaged across the three
Trojans), each Trojan should ideally stay within these soft per-Trojan envelopes:

| Metric        | Golden            | 1 % envelope (+/-)     |
| ------------- | ----------------- | ---------------------- |
| Area          | 404 314           | ± **4 043**            |
| Total cells   | 39 152            | ± **391**              |
| Flip-flops    | 10 546            | ± **105**              |
| WNS slack     | 21.79 ns (MET)    | must remain MET; avoid pushing below ~21.5 ns |

These are **targets**, not hard limits; the averaging rule in the rubric means
one Trojan can be slightly hotter if the other two are quieter.

## Warning observed during synthesis (non-fatal)

Yosys' LTP pass emits a few thousand `Detected loop at $abc$…MuxGate…` warnings.
These are expected: they come from transparent-latch inference in `eth_fifo.v`
and a couple of other ethmac sources where data loops through a mux to itself.
Synthesis still completes and STA still reports MET. The bulk of
`timing_report.txt` (49 MB) is these warnings — we keep only head/tail in
`golden_metrics/` for submission sanity.

## Files now preserved under `golden_metrics/`

```
golden_metrics/
├── area_report.txt             (3.4 KB — cell/area histogram)
├── sta_report.txt              (604 B  — worst-path report)
├── eth_synth_sky130.v          (6.9 MB — synthesized netlist)
├── timing_report_head.txt      (first 50 lines of Yosys LTP)
├── timing_report_tail.txt      (final summary of Yosys LTP)
└── timing_report_fullsize.txt  (size proof: full file was 51.4 MB)
```

## Next step

See `04_base_testbench.md` — we need to prove that the pristine ethmac passes
its own functional TB with iverilog. That sim harness becomes the
disqualification gate for every candidate Trojan.
