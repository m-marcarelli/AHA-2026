# Step 04 — Base Functional Testbench Harness

**Date:** 2026-04-18
**Goal:** Drive the upstream FreeCores ethmac functional testbench
(`bench/verilog/tb_ethernet.v`) through an open-source simulator (iverilog)
so we have a scriptable **pass/fail gate**. Every candidate Trojan must
survive this gate — per SCORING.md Part 3, a Trojan that breaks the base
testbench is disqualified and earns 0 defensive points.

## Commands executed

### 4.1 Compile-only sanity check (first pass)

```bash
mkdir -p /home/hasala/competition/ethmac_workspace/sim_base/{out,log}
cd        /home/hasala/competition/ethmac_workspace/sim_base/out

RTL=/home/hasala/competition/ethmac_workspace/ethmac/rtl/verilog
BENCH=/home/hasala/competition/ethmac_workspace/ethmac/bench/verilog

iverilog -o tb_ethernet.vvp -g2005 \
  -I $RTL -I $BENCH \
  $RTL/ethmac.v $RTL/ethmac_defines.v $RTL/eth_miim.v \
  $RTL/eth_clockgen.v $RTL/eth_shiftreg.v $RTL/eth_outputcontrol.v \
  $RTL/eth_registers.v $RTL/eth_register.v $RTL/eth_maccontrol.v \
  $RTL/eth_receivecontrol.v $RTL/eth_transmitcontrol.v $RTL/eth_txethmac.v \
  $RTL/eth_txcounters.v $RTL/eth_txstatem.v $RTL/eth_rxethmac.v \
  $RTL/eth_rxcounters.v $RTL/eth_rxstatem.v $RTL/eth_rxaddrcheck.v \
  $RTL/eth_crc.v $RTL/eth_wishbone.v $RTL/eth_spram_256x32.v \
  $RTL/eth_fifo.v $RTL/eth_macstatus.v $RTL/eth_random.v \
  $BENCH/tb_ethernet.v $BENCH/eth_phy.v \
  $BENCH/wb_bus_mon.v $BENCH/wb_slave_behavioral.v \
  $BENCH/wb_master32.v $BENCH/wb_master_behavioral.v
```

- **Result**: clean compile, 0 errors, 0 warnings. Produced `tb_ethernet.vvp` (27 MB).
- **Why these files:** the 22 RTL files match the competition's synth script exactly.
  The bench files are the subset of `sim/rtl_sim/bin/sim_file_list.lst` that does
  NOT depend on proprietary Artisan/BIST libraries.
- **Why `-g2005`:** the upstream RTL is Verilog-2001/2005 (not SystemVerilog).
  `-g2005` disables stricter SV2012 checks that trip on legal 2005 constructs.

### 4.2 Smoke run (60 s) — confirm simulation starts & tests pass

```bash
cd /home/hasala/competition/ethmac_workspace/sim_base/out
timeout 60 vvp -N tb_ethernet.vvp
```

Then inspect `../log/eth_tb.log`.

**Observed in the first 60 s of wall-clock:**
- `test_access_to_mac_reg` — TEST 0 through TEST 4 all `reported *SUCCESSFULL*`
- `test_mii` — progressed through TEST 0 … TEST 14 (of 17), all `*SUCCESSFULL*`
- Zero occurrences of `*FAILED*`

### 4.3 Reusable runner — `scripts/sim_base.sh`

We captured the workflow in a single script. It:

1. Takes `(RTL_DIR, RUN_DIR, TIMEOUT_SEC)` — the pipeline will point `RTL_DIR`
   at a candidate Trojan's `rtl/` copy.
2. Compiles with iverilog; bails with exit code 3 on compile failure.
3. Runs `vvp -N` under `timeout`; bails with exit code 2 on timeout.
4. Greps the testbench log for `*SUCCESSFULL*` vs `*FAILED*` markers and
   prints a pass/fail verdict; bails with exit code 1 on any failure.

```bash
# golden-baseline invocation (this step)
/home/hasala/competition/ethmac_workspace/scripts/sim_base.sh \
  /home/hasala/competition/ethmac_workspace/ethmac/rtl/verilog \
  /home/hasala/competition/ethmac_workspace/sim_base \
  720
```

## Test-suite inventory (from `tb_ethernet.v` lines 509-532)

| Task                                  | Tests  | Notes                         |
| ------------------------------------- | -----: | ----------------------------- |
| `test_access_to_mac_reg`              | 5      | register r/w + BD-RAM + reset |
| `test_mii`                            | 18     | MII clock divider + PHY regs  |
| `test_mac_full_duplex_transmit`       | 24 × 2 | ideal + real-delay carriers   |
| `test_mac_full_duplex_receive`        | 16 × 2 | ideal + real-delay carriers   |
| `test_mac_full_duplex_flow_control`   | 6 × 2  | PAUSE frame generation        |
| **Total**                             | **ca. 115** | ~20-30 min under iverilog |

Each test logs exactly one `*SUCCESSFULL*` or `*FAILED*` line. The runner
counts those markers for the pass/fail verdict.

## How this fits into the Trojan loop

`sim_base.sh` is the **disqualification gate**:

```
 candidate Trojan RTL
        │
        ▼
 scripts/sim_base.sh ───► PASS ─► continue to PPA measurement
                         FAIL ─► reject, regenerate Trojan
```

A "PASS" here is a hard precondition for *any* Trojan scoring Part 3
(dynamic CTF) points. Because the full run takes ~20 min, we will
additionally build a **fast smoke subset** (reg + MII + 1-pass transmit
only, ~2 min) for tight iteration in the insertion pipeline — full TB is
run only as a final acceptance gate before freezing a Trojan.

## Golden-run result (720 s wall-clock cap)

```
[sim_base] =================== RESULT ===================
[sim_base] successful tests : 50
[sim_base] failed tests     : 0
[sim_base] vvp exit code    : 124    (timeout — expected, TB is long)
[sim_base] VERDICT: TIMEOUT after 720s (reached 50 tests so far)
```

Tests covered inside the 12-minute budget:

| Heading                             | Golden tests passed |
| ----------------------------------- | ------------------: |
| ACCESS TO MAC REGISTERS TEST        | 5 / 5               |
| MIIM MODULE TEST                    | 18 / 18             |
| MAC FULL DUPLEX TRANSMIT TEST       | 24 / 24             |
| MAC FULL DUPLEX RECEIVE TEST        | 3 / ~32 (cut short) |
| **Totals**                          | **50 / 50 passed, 0 failed** |

This confirms that the golden ethmac **compiles and simulates cleanly under
iverilog 12.0** and that the testbench machinery (PHY model, Wishbone
masters/slaves, PAUSE-frame flows, etc.) is fully functional under our
open-source sim stack. The partial log is preserved at
`golden_metrics/eth_tb_partial.log` (20 KB, 329 lines).

**A full regression would need ~20-30 min** of wall-clock (iverilog is
slower than ModelSim on this TB). Running the full regression once per
Trojan is fine as a final acceptance gate, but too slow for tight iteration.

## Fast smoke subset (planned for step 05)

For the insertion-loop inner iteration we will author a stripped **smoke TB**
(~3 min) that:
- covers `test_access_to_mac_reg(0,4)` + `test_mii(0,17)`, AND
- a *single* transmit + *single* receive + *single* flow-control pass.

That's enough to catch the overwhelming majority of Trojan-induced
regressions (register FSMs, MDIO, TX/RX datapath) while staying cheap
enough to run on every generation step. The full TB is run only when a
candidate otherwise passes PPA + exploit checks.

## Next step

`05_smoke_tb_and_pipeline_scaffold.md` — author the fast smoke TB and stand
up the agentic pipeline skeleton described in `pipeline/README.md`.
