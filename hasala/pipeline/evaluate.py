#!/usr/bin/env python3
"""
pipeline/evaluate.py — end-to-end fitness evaluation of a Trojan candidate.

Given a candidate directory produced by insert.py, run:

  Stage 1 — PPA synthesis (Yosys + OpenSTA) against the golden script.
            Parse area/cell counts; compute delta vs golden.
  Stage 2 — Golden functional TB regression (scripts/sim_base.sh) —
            disqualification gate. Caps at TB_BUDGET_SEC wall-clock.
  Stage 3 — Exploit testbench (iverilog the TB spec.exploit_tb contents
            + patched RTL). Check for `expected_trigger_marker` in stdout.

Outputs:
  - <candidate_dir>/eval.json  — summary
  - <candidate_dir>/metrics/   — PPA reports
  - appends one JSONL line to pipeline/scoreboard.jsonl

Exit codes:
  0 — PASS (base TB ok, PPA within budget, exploit fires)
  10 — FAIL: PPA synth failed
  11 — FAIL: PPA delta exceeds --ppa-budget-pct
  12 — FAIL: base TB regression hit a failure
  13 — FAIL: base TB timed out without reaching a pass gate
  14 — FAIL: exploit TB did not fire / compile
"""
from __future__ import annotations
import argparse, json, re, shutil, subprocess, sys, time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import WS, SCRIPTS_DIR as SCRIPTS, BENCH_DIR as BENCH, PIPELINE_DIR, ETH_SYNTH_DIR  # noqa: E402

# Prefer a top-level eth_synth/ (portable layout). Fall back to the legacy
# location under ethmac/eth_synth/ if that's what exists.
ETH_SYNTH_SRC = ETH_SYNTH_DIR if ETH_SYNTH_DIR.exists() else (WS / "ethmac" / "eth_synth")
SCOREBOARD = PIPELINE_DIR / "scoreboard.jsonl"


GOLDEN = {
    "area": 404314.0192,
    "total_cells": 39152,
    "flip_flops": 10546,
    "wns_slack_ns": 21.7855,
}


@dataclass
class EvalResult:
    candidate: str
    verdict: str
    # PPA
    area: float | None = None
    total_cells: int | None = None
    flip_flops: int | None = None
    area_pct: float | None = None
    cell_pct: float | None = None
    ff_delta: int | None = None
    wns_slack_ns: float | None = None
    # Base TB
    base_tb_pass: int | None = None
    base_tb_fail: int | None = None
    base_tb_seconds: float | None = None
    base_tb_verdict: str | None = None
    # Exploit
    exploit_triggered: bool | None = None
    # Notes
    note: str = ""


def _parse_area_report(path: Path) -> dict[str, Any]:
    txt = path.read_text()
    m_area = re.search(r"Chip area for module '\\ethmac':\s*([\d.]+)", txt)
    m_cells = re.search(r"Number of cells:\s+(\d+)", txt)
    area = float(m_area.group(1)) if m_area else None
    cells = int(m_cells.group(1)) if m_cells else None
    ff = 0
    for pat in (r"dfrtp_1\s+(\d+)", r"dfstp_2\s+(\d+)", r"dfxtp_1\s+(\d+)"):
        m = re.search(pat, txt)
        if m:
            ff += int(m.group(1))
    return {"area": area, "total_cells": cells, "flip_flops": ff}


def _parse_sta_report(path: Path) -> float | None:
    if not path.exists():
        return None
    txt = path.read_text()
    # Look for the core_clock slack line
    m = re.search(r"core_clock.*?\n.*?\n.*?\n.*?\n.*?\s([\-\d.]+)\s+\((MET|VIOLATED)\)", txt, re.DOTALL)
    if m:
        return float(m.group(1)) if m.group(2) == "MET" else -float(m.group(1))
    # Fallback — first slack number we see
    m = re.search(r"([\-\d.]+)\s+\(MET\)", txt)
    if m:
        return float(m.group(1))
    return None


def stage1_ppa(cand_dir: Path) -> tuple[int, dict[str, Any], str]:
    """Run Yosys + STA against the candidate RTL. Returns (exit_code, metrics, log_tail)."""
    synth = cand_dir / "eth_synth"
    if synth.exists():
        shutil.rmtree(synth)
    shutil.copytree(ETH_SYNTH_SRC, synth)
    # Rewrite the Yosys read_verilog line to point at the candidate rtl
    ys = synth / "synthesize_eth_sky130.ys"
    txt = ys.read_text()
    txt = txt.replace("../rtl/verilog/", str(cand_dir / "rtl/verilog/") + "/")
    ys.write_text(txt)

    t0 = time.time()
    proc = subprocess.run(
        ["bash", "./run_ppa.sh"],
        cwd=str(synth),
        capture_output=True, text=True,
        timeout=600,
    )
    dt = time.time() - t0

    log_tail = (proc.stdout[-2000:] + "\n" + proc.stderr[-2000:])
    metrics_dir = synth / "metrics"
    # Persist to candidate metrics/
    dest = cand_dir / "metrics"
    dest.mkdir(exist_ok=True)
    for name in ("area_report.txt", "sta_report.txt"):
        src = metrics_dir / name
        if src.exists():
            shutil.copy2(src, dest / name)

    if proc.returncode != 0 or not (metrics_dir / "area_report.txt").exists():
        return proc.returncode or 1, {"duration_s": dt, "error": "synth_failed"}, log_tail

    m = _parse_area_report(metrics_dir / "area_report.txt")
    m["wns_slack_ns"] = _parse_sta_report(metrics_dir / "sta_report.txt")
    m["duration_s"] = dt
    return 0, m, log_tail


def stage2_base_tb(cand_dir: Path, budget_sec: int) -> tuple[int, dict[str, Any], str]:
    run_dir = cand_dir / "base_tb_run"
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir()
    t0 = time.time()
    proc = subprocess.run(
        [str(SCRIPTS / "sim_base.sh"),
         str(cand_dir / "rtl/verilog"),
         str(run_dir),
         str(budget_sec)],
        capture_output=True, text=True,
        timeout=budget_sec + 60,
    )
    dt = time.time() - t0
    summary = proc.stdout[-3000:]
    log = run_dir / "log" / "eth_tb.log"
    succ = fail = 0
    if log.exists():
        succ = log.read_text().count("reported *SUCCESSFULL*")
        fail = log.read_text().count("reported *FAILED*")
    # Script exit codes: 0 pass, 1 fail, 2 timeout, 3 compile
    return proc.returncode, {
        "successes": succ,
        "failures": fail,
        "duration_s": dt,
        "exit_code": proc.returncode,
    }, summary


def stage3_exploit(cand_dir: Path) -> tuple[bool, str]:
    spec = json.loads((cand_dir / "spec.json").read_text())
    tb_meta = spec.get("exploit_tb", {})
    marker = tb_meta.get("expected_trigger_marker", "TROJAN_TRIGGERED")
    tb_name = tb_meta.get("filename", "exploit_tb.v")
    tb_path = cand_dir / "tb" / tb_name
    if not tb_path.exists():
        return False, f"exploit TB not found at {tb_path}"

    # Extract the top module name from the TB source
    src = tb_path.read_text()
    m = re.search(r"^\s*module\s+(\w+)", src, re.MULTILINE)
    top = m.group(1) if m else "exploit_tb"

    rtl_dir = cand_dir / "rtl/verilog"
    # Use every RTL file present (synth subset + extras); -s names the top.
    rtl_files = [str(p) for p in sorted(rtl_dir.glob("*.v"))]
    vvp = cand_dir / "exploit.vvp"
    compile_cmd = [
        "iverilog", "-g2005", "-s", top,
        "-I", str(rtl_dir), "-I", str(BENCH),
        "-o", str(vvp),
        str(tb_path),
        # bench models available for reuse if TB needs them
        str(BENCH / "eth_phy.v"),
        str(BENCH / "wb_bus_mon.v"),
        str(BENCH / "wb_master32.v"),
        str(BENCH / "wb_master_behavioral.v"),
        str(BENCH / "wb_slave_behavioral.v"),
    ] + rtl_files
    cproc = subprocess.run(compile_cmd, capture_output=True, text=True, timeout=180)
    if cproc.returncode != 0:
        return False, f"compile failed:\n{cproc.stderr[-1500:]}"

    rproc = subprocess.run(
        ["vvp", "-N", str(vvp)],
        capture_output=True, text=True, timeout=300,
    )
    stdout = rproc.stdout + "\n" + rproc.stderr
    (cand_dir / "exploit_stdout.log").write_text(stdout)
    triggered = marker in stdout
    return triggered, (f"marker={marker} triggered={triggered}\n\n" + stdout[-800:])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--tb-budget-sec", type=int, default=300,
                    help="wall-clock cap for the base TB regression (default 300s)")
    ap.add_argument("--ppa-budget-pct", type=float, default=1.0,
                    help="max allowable %% deviation in area or cells from golden")
    ap.add_argument("--skip-base-tb", action="store_true",
                    help="skip Stage 2 (for debugging plumbing only)")
    args = ap.parse_args()

    cand_dir = Path(args.candidate).resolve()
    if not cand_dir.exists():
        print(f"[evaluate] candidate dir not found: {cand_dir}")
        return 2
    result = EvalResult(candidate=str(cand_dir), verdict="PENDING")

    # ---------- Stage 1: PPA ----------
    rc, m1, tail1 = stage1_ppa(cand_dir)
    if rc != 0:
        result.verdict = "PPA_SYNTH_FAILED"
        result.note = tail1[-800:]
        _finalize(cand_dir, result)
        print(f"[evaluate] Stage 1 FAIL: {result.verdict}")
        return 10
    result.area = m1["area"]
    result.total_cells = m1["total_cells"]
    result.flip_flops = m1["flip_flops"]
    result.wns_slack_ns = m1.get("wns_slack_ns")
    result.area_pct = 100 * (m1["area"] - GOLDEN["area"]) / GOLDEN["area"]
    result.cell_pct = 100 * (m1["total_cells"] - GOLDEN["total_cells"]) / GOLDEN["total_cells"]
    result.ff_delta = m1["flip_flops"] - GOLDEN["flip_flops"]
    budget_ok = (abs(result.area_pct) <= args.ppa_budget_pct and
                 abs(result.cell_pct) <= args.ppa_budget_pct)
    print(f"[evaluate] Stage 1 PPA: area={result.area:.0f} "
          f"(Δ{result.area_pct:+.3f}%), cells={result.total_cells} "
          f"(Δ{result.cell_pct:+.3f}%), FF={result.flip_flops} "
          f"(Δ{result.ff_delta:+d}), slack={result.wns_slack_ns}")
    if not budget_ok:
        result.verdict = "PPA_OVER_BUDGET"
        result.note = f"budget pct = {args.ppa_budget_pct}"
        _finalize(cand_dir, result)
        return 11

    # ---------- Stage 2: base TB ----------
    if not args.skip_base_tb:
        rc2, m2, tail2 = stage2_base_tb(cand_dir, args.tb_budget_sec)
        result.base_tb_pass = m2["successes"]
        result.base_tb_fail = m2["failures"]
        result.base_tb_seconds = m2["duration_s"]
        if rc2 == 1:
            result.verdict = "BASE_TB_FAILED"
            result.base_tb_verdict = "FAIL"
            result.note = tail2[-800:]
            _finalize(cand_dir, result)
            return 12
        if rc2 == 3:
            result.verdict = "BASE_TB_COMPILE_FAILED"
            result.note = tail2[-800:]
            _finalize(cand_dir, result)
            return 12
        # rc2 == 0 → full pass; rc2 == 2 → timeout (acceptable if pass > threshold)
        if rc2 == 2 and m2["successes"] < 20:
            result.verdict = "BASE_TB_TIMEOUT_LOW_COUNT"
            result.base_tb_verdict = "TIMEOUT_LOW_COUNT"
            result.note = tail2[-800:]
            _finalize(cand_dir, result)
            return 13
        result.base_tb_verdict = "PASS" if rc2 == 0 else "TIMEOUT_OK"

    # ---------- Stage 3: exploit TB ----------
    triggered, info = stage3_exploit(cand_dir)
    result.exploit_triggered = triggered
    if not triggered:
        result.verdict = "EXPLOIT_NOT_TRIGGERED"
        result.note = info
        _finalize(cand_dir, result)
        return 14

    result.verdict = "PASS"
    _finalize(cand_dir, result)
    print(f"[evaluate] PASS — {cand_dir}")
    return 0


def _finalize(cand_dir: Path, result: EvalResult) -> None:
    (cand_dir / "eval.json").write_text(json.dumps(asdict(result), indent=2))
    with SCOREBOARD.open("a") as f:
        f.write(json.dumps(asdict(result)) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
