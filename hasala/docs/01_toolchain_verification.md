# Step 01 — Toolchain Verification

**Date:** 2026-04-18
**Goal:** Confirm every tool required by `eth_synth/run_ppa.sh` (and our
downstream simulation / insertion pipeline) is installed and callable.

## Commands executed

```bash
# Which binaries exist?
which yosys sta sv2v git iverilog verilator gtkwave python3

# Full version banners
yosys -V
echo "exit" | sta          # OpenSTA prints banner then exits
iverilog -V
git --version
python3 --version
python3 -c "import pyverilog, sys; print('pyverilog', pyverilog.__version__)"
```

## Observed versions

| Tool       | Binary path         | Version                               | Required for                           |
| ---------- | ------------------- | ------------------------------------- | -------------------------------------- |
| Yosys      | `/usr/bin/yosys`    | `0.33 (git sha1 2584903a060)`         | RTL → gate-level synthesis (SKY130)    |
| OpenSTA    | `/usr/local/bin/sta`| `3.1.0 e629909aaf`                    | Static timing analysis of the netlist  |
| Icarus     | `/usr/bin/iverilog` | `12.0 (stable)`                       | Functional simulation of ethmac + TBs  |
| GTKWave    | `/usr/bin/gtkwave`  | present                               | Waveform inspection for Trojan proof   |
| Git        | `/usr/bin/git`      | `2.43.0`                              | Cloning the FreeCores/ethmac repo      |
| Python     | `/usr/bin/python3`  | `3.12.3`                              | Pipeline scripting                     |
| Pyverilog  | pip site-packages   | `1.3.0`                               | AST-level RTL parsing / insertion      |
| sv2v       | —                   | NOT INSTALLED                         | Only needed for cv32e40p — N/A here    |
| Verilator  | —                   | NOT INSTALLED                         | Optional; iverilog is sufficient       |

## Decision

All mandatory tools for the **Ethmac** target are installed. We do NOT need
`sv2v` because Ethmac is pure Verilog-2001. `verilator` is skipped for now —
iverilog is fast enough for the small ethmac TBs and matches what FreeCores
originally used.

## Reference — the three stages of `eth_synth/run_ppa.sh`

1. `yosys -s ./synthesize_eth_sky130.ys`
   Reads all 22 ethmac RTL files, elaborates `ethmac` as top, techmaps against
   `sky130_fd_sc_hd__tt_025C_1v80.lib`, emits synthesized netlist and reports.
2. `sta ./grade_timing.sta`
   Creates a 25 ns (40 MHz) clock, runs `report_checks -path_delay max` to
   produce the worst-case timing path report.
3. Outputs land in `./metrics/{timing_report.txt, area_report.txt, sta_report.txt}`.

This is the exact pipeline judges will run against each Trojan variant.

## Next step

See `02_clone_ethmac.md`.
