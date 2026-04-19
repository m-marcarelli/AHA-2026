"""Central path resolution for the Trojan-insertion pipeline.

Resolution order:
  1. $ETHMAC_WS environment variable (explicit override).
  2. Auto-detect: walk up from this file until we find a directory that
     contains both `pipeline/` and `ethmac/rtl/verilog/`.

This lets the whole workspace move without code edits.
"""
from __future__ import annotations
import os
from pathlib import Path


def _autodetect_ws() -> Path:
    p = Path(__file__).resolve()
    for parent in [p.parent] + list(p.parents):
        if (parent / "ethmac" / "rtl" / "verilog").is_dir() and (parent / "pipeline").is_dir():
            return parent
    # Fallback: parent of pipeline/
    return Path(__file__).resolve().parent.parent


_env_ws = os.environ.get("ETHMAC_WS", "").strip()
WS: Path = (Path(_env_ws) if _env_ws else _autodetect_ws()).resolve()

# Canonical subpaths
RTL_DIR       = WS / "ethmac" / "rtl" / "verilog"
BENCH_DIR     = WS / "ethmac" / "bench" / "verilog"
ETH_SYNTH_DIR = WS / "eth_synth"
SCRIPTS_DIR   = WS / "scripts"
PIPELINE_DIR  = WS / "pipeline"
AI_LOG_DIR    = WS / "ai_logs"
TROJANS_DIR   = WS / "trojans"
GOLDEN_DIR    = WS / "golden_metrics"

__all__ = [
    "WS", "RTL_DIR", "BENCH_DIR", "ETH_SYNTH_DIR", "SCRIPTS_DIR",
    "PIPELINE_DIR", "AI_LOG_DIR", "TROJANS_DIR", "GOLDEN_DIR",
]


if __name__ == "__main__":
    # Quick sanity print.
    import sys
    print(f"[paths] WS            = {WS}")
    for name in __all__[1:]:
        p = globals()[name]
        exists = "OK " if p.exists() else "MISS"
        print(f"[paths] {name:13s} = {p}  [{exists}]")
    sys.exit(0 if WS.exists() else 1)
