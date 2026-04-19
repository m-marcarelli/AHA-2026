#!/usr/bin/env bash
# sim_base.sh — compile + run the upstream FreeCores ethmac testbench
# against a given RTL source directory (defaults to golden rtl/verilog).
#
# Usage:
#   sim_base.sh [RTL_DIR] [RUN_DIR] [TIMEOUT_SEC]
#
# Produces a pass/fail summary on stdout and detailed logs in RUN_DIR/log/.
# Exit code: 0 = all reported tests SUCCESSFUL and no FAILED markers,
#            1 = at least one FAILED marker detected,
#            2 = simulation timed out before reaching test_summary,
#            3 = compilation failure.

set -u

# Resolve workspace root: $ETHMAC_WS wins, else auto-detect as parent of
# the directory containing this script.
if [ -n "${ETHMAC_WS:-}" ]; then
  WS="$ETHMAC_WS"
else
  WS="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

RTL_DIR="${1:-$WS/ethmac/rtl/verilog}"
RUN_DIR="${2:-$WS/sim_base}"
TIMEOUT_SEC="${3:-900}"   # 15 min default; full regression needs ~20-30 min

BENCH="$WS/ethmac/bench/verilog"
OUT="$RUN_DIR/out"
LOG="$RUN_DIR/log"

mkdir -p "$OUT" "$LOG"

VVP="$OUT/tb_ethernet.vvp"

echo "[sim_base] RTL_DIR = $RTL_DIR"
echo "[sim_base] RUN_DIR = $RUN_DIR"
echo "[sim_base] TIMEOUT = ${TIMEOUT_SEC}s"

echo "[sim_base] compiling with iverilog..."
iverilog -o "$VVP" -g2005 \
  -I "$RTL_DIR" -I "$BENCH" \
  "$RTL_DIR"/ethmac.v            "$RTL_DIR"/ethmac_defines.v   "$RTL_DIR"/eth_miim.v \
  "$RTL_DIR"/eth_clockgen.v      "$RTL_DIR"/eth_shiftreg.v     "$RTL_DIR"/eth_outputcontrol.v \
  "$RTL_DIR"/eth_registers.v     "$RTL_DIR"/eth_register.v     "$RTL_DIR"/eth_maccontrol.v \
  "$RTL_DIR"/eth_receivecontrol.v "$RTL_DIR"/eth_transmitcontrol.v "$RTL_DIR"/eth_txethmac.v \
  "$RTL_DIR"/eth_txcounters.v    "$RTL_DIR"/eth_txstatem.v     "$RTL_DIR"/eth_rxethmac.v \
  "$RTL_DIR"/eth_rxcounters.v    "$RTL_DIR"/eth_rxstatem.v     "$RTL_DIR"/eth_rxaddrcheck.v \
  "$RTL_DIR"/eth_crc.v           "$RTL_DIR"/eth_wishbone.v     "$RTL_DIR"/eth_spram_256x32.v \
  "$RTL_DIR"/eth_fifo.v          "$RTL_DIR"/eth_macstatus.v    "$RTL_DIR"/eth_random.v \
  "$BENCH"/tb_ethernet.v         "$BENCH"/eth_phy.v \
  "$BENCH"/wb_bus_mon.v          "$BENCH"/wb_slave_behavioral.v \
  "$BENCH"/wb_master32.v         "$BENCH"/wb_master_behavioral.v \
  2> "$OUT/iverilog.stderr"
RC=$?
if [ $RC -ne 0 ]; then
  echo "[sim_base] COMPILE FAILED (rc=$RC). stderr:"
  cat "$OUT/iverilog.stderr"
  exit 3
fi

echo "[sim_base] running vvp with ${TIMEOUT_SEC}s wall-clock cap..."
cd "$OUT"
timeout "$TIMEOUT_SEC" vvp -N "$VVP" > "$OUT/vvp.stdout" 2> "$OUT/vvp.stderr"
SIM_RC=$?

LOGFILE="$LOG/eth_tb.log"
if [ ! -f "$LOGFILE" ]; then
  echo "[sim_base] ERROR: testbench log not created at $LOGFILE"
  exit 3
fi

SUCC=$(grep -c "reported \*SUCCESSFULL\*" "$LOGFILE" || true)
FAIL=$(grep -c "reported \*FAILED\*"       "$LOGFILE" || true)
SUMMARY=$(grep -c "End of SIMULATION\|End of simulation\|FINAL SUMMARY" "$LOGFILE" || true)

echo "[sim_base] =================== RESULT ==================="
echo "[sim_base] successful tests : $SUCC"
echo "[sim_base] failed tests     : $FAIL"
echo "[sim_base] vvp exit code    : $SIM_RC"
echo "[sim_base] log file         : $LOGFILE"
echo "[sim_base] =============================================="

if [ "$FAIL" -gt 0 ]; then
  echo "[sim_base] VERDICT: FAIL ($FAIL test(s) reported FAILED)"
  grep -B1 -A3 "reported \*FAILED\*" "$LOGFILE" | head -40
  exit 1
fi

if [ "$SIM_RC" -eq 124 ]; then
  echo "[sim_base] VERDICT: TIMEOUT after ${TIMEOUT_SEC}s (reached $SUCC tests so far)"
  exit 2
fi

echo "[sim_base] VERDICT: PASS"
exit 0
