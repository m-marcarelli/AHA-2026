# Step 02 — Clone FreeCores Ethmac

**Date:** 2026-04-18
**Goal:** Obtain a pristine copy of the upstream FreeCores Ethmac repository
that our AI pipeline will operate on.

## Commands executed

```bash
cd /home/hasala/competition/ethmac_workspace
rmdir ethmac                      # remove the empty placeholder dir
git clone --depth 1 https://github.com/freecores/ethmac.git ethmac
cd ethmac
git log -1 --format="%H%n%an%n%ad%n%s"
```

## Clone metadata (pin for reproducibility)

| Field         | Value                                       |
| ------------- | ------------------------------------------- |
| Repo URL      | https://github.com/freecores/ethmac         |
| Commit SHA    | `dd26899086edf3b797d2775ef9502d204a9a8149`  |
| Commit author | Peter Gustavsson                            |
| Commit date   | Mon Sep 30 10:27:40 2019 +0200              |
| Commit msg    | Added core description file                 |
| Clone depth   | 1 (shallow — we do not need upstream history) |
| Clone size    | ~12,320 lines of Verilog across 30 files    |

## Top-level contents

```
ethmac/
├── README.txt
├── bench/verilog/          ← 14 testbench / behavioral-model files
├── doc/
├── ethmac.core
├── rtl/verilog/            ← 30 RTL files (22 used by the competition synth)
├── scripts/
└── sim/rtl_sim/            ← ModelSim / NCSim simulation harness
```

## RTL files that feed the competition's Yosys synthesis

These 22 files are taken verbatim from `eth_synth/synthesize_eth_sky130.ys`
(top module is `ethmac`):

```
ethmac.v                 ethmac_defines.v        eth_miim.v
eth_clockgen.v           eth_shiftreg.v          eth_outputcontrol.v
eth_registers.v          eth_register.v          eth_maccontrol.v
eth_receivecontrol.v     eth_transmitcontrol.v   eth_txethmac.v
eth_txcounters.v         eth_txstatem.v          eth_rxethmac.v
eth_rxcounters.v         eth_rxstatem.v          eth_rxaddrcheck.v
eth_crc.v                eth_wishbone.v          eth_spram_256x32.v
eth_fifo.v               eth_macstatus.v         eth_random.v
```

Files present in the repo but NOT used by synthesis (safe to ignore but note
they exist in sim): `eth_cop.v`, `eth_top.v`, `timescale.v`,
`xilinx_dist_ram_16x32.v`.

## Functional testbench

The upstream functional test harness lives in `bench/verilog/tb_ethernet.v`
(~24,730 lines) and is driven by `sim/rtl_sim/bin/run_sim`. This is the
golden functional TB — **every Trojan variant must pass it**, otherwise the
Trojan is disqualified per SCORING.md Part 3.

Note: the upstream `sim_file_list.lst` references proprietary Artisan BIST
libraries that are NOT in the repo. We will set up iverilog-based smoke
simulation against only the open-source bench files — documented separately
in a later step.

## Next step

See `03_golden_ppa_baseline.md`.
