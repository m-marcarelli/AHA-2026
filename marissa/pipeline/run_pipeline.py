#!/usr/bin/env python3
"""
AHA 2026 pipeline — CLI entry point.

Two modes:

  Full pipeline (end-to-end):
    python run_pipeline.py --target ethmac --num-trojans 3 --ideation parallel

  Individual stage:
    python run_pipeline.py stage <name> [--trojan trojan_N] [...]

Stages:
  ideate        Stage 0 — parallel multi-model trojan ideation
  generate      Stage 1+2 — AST analysis + RTL/TB generation
  simulate      Stage 3 — Icarus simulation + self-repair loop
  blueteam      Stage 4b — diff-aware ensemble blue-team review
  regression    Stage 3.5 — upstream ethmac functional regression gate
  equiv         Stage 5.5 — Yosys equivalence-under-disarm proof
  ppa           Stage 5 — Yosys + OpenSTA PPA + power
  cvss          Stage 4c — deterministic CVSS 3.1 scoring
  package       Repackage submission.zip

Each stage is independent: outputs of one stage are the inputs of the next,
and intermediate state lives on disk under output/<trojan>/.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

import orchestrator  # noqa: E402


# ---------------------------------------------------------------------------
# Stage dispatch
# ---------------------------------------------------------------------------
def _load_spec(trojan_id: str) -> dict:
    """Load the per-trojan spec from the saved ideation_selection.json,
    falling back to DEFAULT_TROJANS if no run has happened yet."""
    import json
    sel = orchestrator.LOG_DIR / "ideation_selection.json"
    if sel.exists():
        data = json.loads(sel.read_text())
        for spec in data.get("trojans", []):
            if spec.get("id") == trojan_id:
                return spec
    for spec in orchestrator.DEFAULT_TROJANS:
        if spec["id"] == trojan_id:
            return spec
    raise SystemExit(f"Unknown trojan id: {trojan_id}")


def stage_ideate(args: argparse.Namespace) -> int:
    rtl_ctx = (orchestrator.ETH_RTL / "ethmac.v").read_text() + "\n" + \
              (orchestrator.ETH_RTL / "eth_wishbone.v").read_text()
    result = orchestrator.run_ideation(rtl_ctx)
    print("ideation result:", "ok" if result else "fallback to defaults")
    return 0 if result else 1


def stage_generate(args: argparse.Namespace) -> int:
    spec = _load_spec(args.trojan)
    rtl, tb = orchestrator.generate_trojan(spec, prior_specs=[])
    out = orchestrator.OUTPUT_DIR / spec["id"]
    out.mkdir(exist_ok=True)
    (out / spec["target_file"]).write_text(orchestrator.clean_verilog(rtl))
    (out / f"tb_{spec['id']}.v").write_text(orchestrator.clean_verilog(tb, strip_timescale=False))
    print(f"generated: {out}")
    return 0 if rtl and tb else 1


def stage_simulate(args: argparse.Namespace) -> int:
    spec = _load_spec(args.trojan)
    out = orchestrator.OUTPUT_DIR / spec["id"]
    rtl_path = out / spec["target_file"]
    tb_path = out / f"tb_{spec['id']}.v"
    ok, sim_out = orchestrator.run_simulation(spec["id"], tb_path, rtl_path)
    print(sim_out[-2000:])
    print(f"simulate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 2


def stage_blueteam(args: argparse.Namespace) -> int:
    spec = _load_spec(args.trojan)
    out = orchestrator.OUTPUT_DIR / spec["id"]
    rtl = (out / spec["target_file"]).read_text()
    tb = (out / f"tb_{spec['id']}.v").read_text()
    new_rtl, new_tb = orchestrator.blue_team_review(spec, rtl, tb)
    (out / spec["target_file"]).write_text(orchestrator.clean_verilog(new_rtl))
    (out / f"tb_{spec['id']}.v").write_text(orchestrator.clean_verilog(new_tb, strip_timescale=False))
    return 0


def stage_regression(args: argparse.Namespace) -> int:
    from gates import run_upstream_regression
    spec = _load_spec(args.trojan)
    out = orchestrator.OUTPUT_DIR / spec["id"]
    ok, msg = run_upstream_regression(out / spec["target_file"])
    print(msg)
    return 0 if ok else 3


def stage_equiv(args: argparse.Namespace) -> int:
    from gates import yosys_equiv_check
    spec = _load_spec(args.trojan)
    out = orchestrator.OUTPUT_DIR / spec["id"]
    ok, msg = yosys_equiv_check(
        golden=orchestrator.ETH_RTL / spec["target_file"],
        modified=out / spec["target_file"],
        arm_signal_candidates=("trojan_armed", "wb_dat_pipe_valid", "csr_shadow"),
    )
    print(msg)
    return 0 if ok else 4


def stage_ppa(args: argparse.Namespace) -> int:
    spec = _load_spec(args.trojan)
    out = orchestrator.OUTPUT_DIR / spec["id"]
    res = orchestrator.run_ppa(spec["id"], out / spec["target_file"])
    print(res)
    return 0 if res.get("ppa_success") else 5


def stage_cvss(args: argparse.Namespace) -> int:
    import json
    from cvss_calc import score_from_vector
    spec = _load_spec(args.trojan)
    out = orchestrator.OUTPUT_DIR / spec["id"]
    rtl = (out / spec["target_file"]).read_text()
    cvss = orchestrator.calculate_cvss(spec, rtl)
    if cvss.get("vector") and cvss["vector"] != "parse_error":
        deterministic = score_from_vector(cvss["vector"])
        cvss["score"] = deterministic
        cvss["score_source"] = "deterministic-formula"
    (out / "cvss.json").write_text(json.dumps(cvss, indent=2))
    print(json.dumps(cvss, indent=2))
    return 0


def stage_package(args: argparse.Namespace) -> int:
    import json
    sel = orchestrator.LOG_DIR / "ideation_selection.json"
    trojans = orchestrator.DEFAULT_TROJANS
    if sel.exists():
        trojans = json.loads(sel.read_text()).get("trojans", trojans)
    orchestrator.package_submission(trojans)
    return 0


STAGES = {
    "ideate":     stage_ideate,
    "generate":   stage_generate,
    "simulate":   stage_simulate,
    "blueteam":   stage_blueteam,
    "regression": stage_regression,
    "equiv":      stage_equiv,
    "ppa":        stage_ppa,
    "cvss":       stage_cvss,
    "package":    stage_package,
}


# ---------------------------------------------------------------------------
# Argparse
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_pipeline.py",
        description="AHA 2026 hardware-trojan generation pipeline.",
    )
    p.add_argument("--target", default="ethmac", choices=("ethmac", "aes", "cv32e40p"),
                   help="DUT to attack (only ethmac currently has anchor templates)")
    p.add_argument("--num-trojans", type=int, default=3)
    p.add_argument("--ideation", choices=("parallel", "off"), default="parallel",
                   help="parallel = multi-model Stage 0; off = use DEFAULT_TROJANS")

    sub = p.add_subparsers(dest="cmd")
    stage = sub.add_parser("stage", help="Run a single pipeline stage")
    stage.add_argument("name", choices=list(STAGES.keys()))
    stage.add_argument("--trojan", default="trojan_1",
                       help="trojan id (trojan_1 | trojan_2 | trojan_3)")
    stage.add_argument("--max-repairs", type=int, default=3)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "stage":
        return STAGES[args.name](args)

    # Full pipeline path — defer to orchestrator.main()
    if args.target != "ethmac":
        sys.stderr.write(f"target={args.target} not yet supported by anchor templates\n")
        return 1
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.stderr.write("ERROR: ANTHROPIC_API_KEY not set.\n")
        return 1
    orchestrator.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
