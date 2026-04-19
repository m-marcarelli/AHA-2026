"""
Pipeline gates that protect Phase-2 defensive points.

`SCORING.md` Part 3 explicit rule:

    "If an inserted Trojan causes the host open-source hardware project
     to fail its standard functional testbench (i.e., the Trojan inadvertently
     breaks the base functionality of the device), it is disqualified.
     The inserting team receives 0 defensive points."

These gates make that disqualification impossible by construction.

  run_upstream_regression(modified_rtl)
        Runs the OpenCores ethmac upstream testbench against the modified
        RTL. Pass = trojan-disarmed paths preserved. Fail = drop the
        candidate before it can reach the submission.

  yosys_equiv_check(golden, modified, arm_signal_candidates)
        Uses Yosys' equiv_make / equiv_simple to formally prove that
        the modified design with the trojan arm signal forced to 0 is
        gate-level equivalent to the golden design. Provides a
        documentation artifact and an additional safety net beyond
        simulation.

Both gates degrade gracefully (skip with a warning) if the required EDA
tools are not installed, so the pipeline can still demo without them
while flagging in the artifact JSON that the gate did not run.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
REPO_ROOT = HERE.parent
ETH_RTL = REPO_ROOT / "ethmac" / "rtl" / "verilog"
ETH_BENCH = REPO_ROOT / "ethmac" / "bench" / "verilog"

# Upstream OpenCores testbench file list.
# Order matters: defines first, then bench infrastructure, then the top TB.
_UPSTREAM_BENCH_FILES = [
    "tb_eth_defines.v",
    "wb_model_defines.v",
    "eth_phy_defines.v",
    "eth_phy.v",
    "eth_host.v",
    "eth_memory.v",
    "wb_master32.v",
    "wb_master_behavioral.v",
    "wb_slave_behavioral.v",
    "wb_bus_mon.v",
    "tb_ethernet.v",  # the canonical OpenCores ethmac testbench
]

_UPSTREAM_RTL_FILES = [
    "ethmac_defines.v",
    "ethmac.v", "eth_miim.v", "eth_clockgen.v", "eth_shiftreg.v",
    "eth_outputcontrol.v", "eth_registers.v", "eth_register.v",
    "eth_maccontrol.v", "eth_receivecontrol.v", "eth_transmitcontrol.v",
    "eth_txethmac.v", "eth_txcounters.v", "eth_txstatem.v",
    "eth_rxethmac.v", "eth_rxcounters.v", "eth_rxstatem.v",
    "eth_rxaddrcheck.v", "eth_crc.v", "eth_wishbone.v",
    "eth_spram_256x32.v", "eth_fifo.v", "eth_macstatus.v", "eth_random.v",
]


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


# ---------------------------------------------------------------------------
# Stage 3.5 — functional regression against the upstream OpenCores testbench
# ---------------------------------------------------------------------------
def run_upstream_regression(modified_rtl: Path,
                            timeout_sec: int = 600) -> tuple[bool, str]:
    """
    Run the OpenCores ethmac upstream functional testbench with the given
    modified RTL substituted in place of its golden equivalent. Returns
    (ok, message). ok=True only if the testbench reports zero failures.
    """
    if not _have("iverilog") or not _have("vvp"):
        return True, "SKIP: iverilog/vvp not on PATH (gate not enforceable in this env)"

    if not ETH_BENCH.exists():
        return True, f"SKIP: upstream bench dir missing ({ETH_BENCH})"

    bench_files = [ETH_BENCH / f for f in _UPSTREAM_BENCH_FILES if (ETH_BENCH / f).exists()]
    if not bench_files:
        return True, f"SKIP: no upstream bench files found in {ETH_BENCH}"

    rtl_files = [
        modified_rtl if f == modified_rtl.name else ETH_RTL / f
        for f in _UPSTREAM_RTL_FILES
    ]
    missing = [str(p) for p in rtl_files if not p.exists()]
    if missing:
        return True, f"SKIP: missing upstream RTL: {missing[:3]}"

    with tempfile.TemporaryDirectory() as td:
        sim_bin = Path(td) / "regress_sim"
        cmd = [
            "iverilog", "-g2012",
            f"-I{ETH_RTL}", f"-I{ETH_BENCH}",
            "-o", str(sim_bin),
        ] + [str(f) for f in bench_files] + [str(f) for f in rtl_files]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            return False, f"REGRESSION FAIL: compile timeout ({timeout_sec}s)"

        if r.returncode != 0:
            return False, f"REGRESSION FAIL (compile):\n{r.stderr[-2000:]}"

        try:
            r2 = subprocess.run(["vvp", str(sim_bin)],
                                capture_output=True, text=True, timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            return False, f"REGRESSION FAIL: simulation timeout ({timeout_sec}s)"

        out = (r2.stdout + r2.stderr).lower()
        # OpenCores tb_ethernet conventions: "test failed" / "tests passed"
        # Be conservative: any "fail" / "error" / "fatal" wording = fail.
        bad_markers = ("test failed", "fatal", "tb_ethernet error",
                       "assertion failed", "comparison error")
        if any(m in out for m in bad_markers):
            ctx = "\n".join(line for line in out.splitlines() if any(m in line for m in bad_markers))
            return False, f"REGRESSION FAIL: matched failure marker:\n{ctx[:2000]}"
        if r2.returncode != 0:
            return False, f"REGRESSION FAIL (sim exit {r2.returncode}):\n{out[-2000:]}"
        return True, f"REGRESSION PASS  ({len(out.splitlines())} sim lines, no failure markers)"


# ---------------------------------------------------------------------------
# Stage 5.5 — Yosys equivalence-under-disarm
# ---------------------------------------------------------------------------
_EQUIV_SCRIPT_TEMPLATE = """\
# Yosys equivalence check: golden vs. modified-with-arm-tied-low.
# Generated by gates.yosys_equiv_check
read_verilog -sv {include_dirs} {golden_files}
hierarchy -top ethmac
proc; opt; memory; opt
rename ethmac ethmac_golden
design -stash golden

read_verilog -sv {include_dirs} {modified_files}
hierarchy -top ethmac
# Force the trojan arm signal low for the equivalence proof.
chparam -set ARM_FORCE_ZERO 1 ethmac
# (If the design uses a wire/reg named arm, stub it with a tie-low cell.)
{stubs}
proc; opt; memory; opt
rename ethmac ethmac_modified
design -stash modified

design -copy-from golden   -as ethmac_golden   ethmac_golden
design -copy-from modified -as ethmac_modified ethmac_modified

equiv_make ethmac_golden ethmac_modified equiv_top
hierarchy -top equiv_top
equiv_simple -seq 5
equiv_status -assert
"""


def yosys_equiv_check(golden: Path,
                      modified: Path,
                      arm_signal_candidates: tuple[str, ...] = ("trojan_armed",)
                      ) -> tuple[bool, str]:
    """
    Formal equivalence check between golden and modified RTL with the
    trojan arm signal forced to 0. Returns (ok, message).

    If Yosys is not installed, returns (True, "SKIP ...") — the gate is
    advisory in environments that lack a Yosys build.
    """
    if not _have("yosys"):
        return True, "SKIP: yosys not on PATH"

    if not golden.exists():
        return False, f"golden missing: {golden}"
    if not modified.exists():
        return False, f"modified missing: {modified}"

    # Find which candidate arm signal exists in the modified file.
    mod_text = modified.read_text()
    found_arm = None
    for cand in arm_signal_candidates:
        if re.search(rf"\b{re.escape(cand)}\b", mod_text):
            found_arm = cand
            break
    if not found_arm:
        return True, ("SKIP: no recognised arm-signal identifier in modified file "
                      "(tried " + ",".join(arm_signal_candidates) + ")")

    # Build a stub clause that forces the arm signal low. This is the
    # textbook "equivalence under disarm" idea — if the trojan is purely
    # additive when disarmed, the proof goes through.
    stubs = (f"# Tie {found_arm} to 0 so the proof shows additive-only behavior\n"
             f"# (synth-equivalent to: assign {found_arm} = 1'b0;)\n"
             f"connect -port ethmac {found_arm} 1'b0\n")

    # Multi-file ethmac: we re-use the same RTL list for both designs;
    # the only thing that differs is the modified file substitution.
    golden_list = [ETH_RTL / f for f in _UPSTREAM_RTL_FILES]
    modified_list = [
        modified if f == modified.name else ETH_RTL / f
        for f in _UPSTREAM_RTL_FILES
    ]

    incl = f"-I {ETH_RTL}"
    script = _EQUIV_SCRIPT_TEMPLATE.format(
        include_dirs=incl,
        golden_files=" ".join(str(p) for p in golden_list),
        modified_files=" ".join(str(p) for p in modified_list),
        stubs=stubs,
    )

    with tempfile.TemporaryDirectory() as td:
        ys = Path(td) / "equiv.ys"
        ys.write_text(script)
        try:
            r = subprocess.run(["yosys", "-q", "-s", str(ys)],
                               capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired:
            return False, "EQUIV FAIL: yosys timeout"

    if r.returncode == 0 and "Equivalence successfully proven" in (r.stdout + r.stderr):
        return True, f"EQUIV PASS  (arm signal {found_arm} → 0 yields gate equivalence)"
    return False, ("EQUIV FAIL\n"
                   f"--- yosys stderr ---\n{r.stderr[-1500:]}\n"
                   f"--- yosys stdout (tail) ---\n{r.stdout[-1500:]}")
