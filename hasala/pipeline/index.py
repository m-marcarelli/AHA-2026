#!/usr/bin/env python3
"""
pipeline/index.py — Build a JSON index of the ethmac RTL for RAG + insertion.

For each of the 22 Verilog source files used by the competition's synthesis
script, we extract:

  - module name(s)
  - ports (name, direction, width)
  - top-level always blocks (with line span + clock/reset sensitivity)
  - localparams / `define uses
  - raw file size + sha256 (to detect upstream drift)

Output: repo_index.json in the pipeline/ folder. This file is small enough
to feed as context to an LLM call and gives the generator precise coordinates
for AST-level insertion.

No LLM calls here — this is pure static analysis.
"""
from __future__ import annotations
import hashlib, json, re, sys
from pathlib import Path

try:
    from pyverilog.vparser.parser import parse
    from pyverilog.vparser.ast import (
        ModuleDef, Ioport, Input, Output, Inout, Reg, Wire, Always,
        SensList, Sens, Identifier, Decl
    )
except ImportError as e:
    sys.exit(f"pyverilog import failed: {e}. pip install pyverilog")

# Path-resolve via pipeline/paths.py so we work regardless of install location.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import WS, RTL_DIR, PIPELINE_DIR   # noqa: E402

OUT_PATH = PIPELINE_DIR / "repo_index.json"

# The 22 files that feed Yosys synthesis. Keeping this list explicit (not
# glob) so the indexer matches the synthesis flow exactly.
RTL_FILES = [
    "ethmac.v", "ethmac_defines.v", "eth_miim.v",
    "eth_clockgen.v", "eth_shiftreg.v", "eth_outputcontrol.v",
    "eth_registers.v", "eth_register.v", "eth_maccontrol.v",
    "eth_receivecontrol.v", "eth_transmitcontrol.v", "eth_txethmac.v",
    "eth_txcounters.v", "eth_txstatem.v", "eth_rxethmac.v",
    "eth_rxcounters.v", "eth_rxstatem.v", "eth_rxaddrcheck.v",
    "eth_crc.v", "eth_wishbone.v", "eth_spram_256x32.v",
    "eth_fifo.v", "eth_macstatus.v", "eth_random.v",
]


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _width(node) -> str:
    """Return a "[hi:lo]" string for a port width, or '' for 1-bit."""
    w = getattr(node, "width", None)
    if w is None:
        return ""
    try:
        return f"[{w.msb.value}:{w.lsb.value}]"
    except Exception:
        return "[?]"


def _direction(node) -> str:
    if isinstance(node, Input):  return "input"
    if isinstance(node, Output): return "output"
    if isinstance(node, Inout):  return "inout"
    return "unknown"


def _extract_always_blocks(src_lines: list[str]) -> list[dict]:
    """Regex-based always-block span extractor.
    Pyverilog *can* give us Always AST nodes but the line numbers it emits are
    unreliable against the original file once preprocessor `include is used.
    Regex gives us honest source-line spans which is what we need for patching.
    """
    results = []
    in_block = False
    start_line = 0
    sens = ""
    brace_depth = 0  # counts begin..end (net)
    for i, line in enumerate(src_lines, start=1):
        stripped = line.strip()
        # detect start
        if not in_block and re.match(r"^\s*always\b", line):
            start_line = i
            m = re.search(r"@\s*\(([^)]*)\)", line)
            sens = m.group(1).strip() if m else "<no sensitivity>"
            in_block = True
            brace_depth = 0
            # single-line always like "always @* y = x;" — close immediately
            if ";" in line and "begin" not in line:
                results.append({
                    "start_line": start_line, "end_line": i,
                    "sensitivity": sens, "form": "single-statement"
                })
                in_block = False
                continue
        if in_block:
            # count begin/end balance
            for tok in re.findall(r"\bbegin\b|\bend\b", stripped):
                brace_depth += 1 if tok == "begin" else -1
            # An always-block ends when we close the outermost begin/end
            if brace_depth == 0 and ("end" in stripped or ";" in stripped) and i != start_line:
                # but only if we actually entered a begin
                if re.search(r"\bend\b", stripped):
                    results.append({
                        "start_line": start_line, "end_line": i,
                        "sensitivity": sens, "form": "begin-end"
                    })
                    in_block = False
    return results


def index_file(path: Path) -> dict:
    src = path.read_text()
    src_lines = src.splitlines()
    entry = {
        "file": path.name,
        "path": str(path.relative_to(WS)),
        "sha256_16": _sha256(path),
        "lines": len(src_lines),
        "modules": [],
        "always_blocks": _extract_always_blocks(src_lines),
        "defines": sorted(set(re.findall(r"`define\s+(\w+)", src))),
        "backtick_uses": sorted(set(re.findall(r"`(\w+)", src))),
    }
    # Pyverilog parse for port list per module
    try:
        ast, _ = parse([str(path)], preprocess_include=[str(RTL_DIR)])
        for desc in ast.description.definitions:
            if not isinstance(desc, ModuleDef):
                continue
            ports = []
            # ANSI-style ports on module header
            if desc.portlist and desc.portlist.ports:
                for p in desc.portlist.ports:
                    inner = p.first if isinstance(p, Ioport) else p
                    ports.append({
                        "name": getattr(inner, "name", str(inner)),
                        "direction": _direction(inner) if hasattr(inner, "name") else "portref",
                        "width": _width(inner),
                    })
            # Non-ANSI port declarations in module body
            for item in (desc.items or []):
                if isinstance(item, Decl):
                    for d in item.list:
                        if isinstance(d, (Input, Output, Inout)):
                            nm = d.name
                            if not any(x["name"] == nm for x in ports):
                                ports.append({
                                    "name": nm,
                                    "direction": _direction(d),
                                    "width": _width(d),
                                })
            entry["modules"].append({
                "name": desc.name,
                "ports": ports,
                "num_ports": len(ports),
            })
    except Exception as e:
        entry["parse_error"] = f"{type(e).__name__}: {e}"
    return entry


def main() -> int:
    out = {
        "workspace": str(WS),
        "rtl_dir": str(RTL_DIR),
        "files": [],
        "golden_ppa": {
            "area": 404314.0192,
            "total_cells": 39152,
            "flip_flops": 10546,
            "wns_slack_ns": 21.7855,
            "clock_period_ns": 25.0,
        },
        "golden_tb": {
            "simulator": "iverilog 12.0",
            "verified_pass_count": 50,
            "verified_fail_count": 0,
            "note": "Full regression is ~25 min; use scripts/sim_base.sh as gate.",
        },
    }
    for name in RTL_FILES:
        p = RTL_DIR / name
        if not p.exists():
            sys.exit(f"missing RTL file: {p}")
        entry = index_file(p)
        out["files"].append(entry)
        print(f"[index] {name:30s} modules={len(entry['modules']):>2} "
              f"always={len(entry['always_blocks']):>3} lines={entry['lines']}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, indent=2))
    print(f"[index] wrote {OUT_PATH} "
          f"({OUT_PATH.stat().st_size/1024:.1f} KB, "
          f"{sum(len(f['modules']) for f in out['files'])} modules, "
          f"{sum(len(f['always_blocks']) for f in out['files'])} always-blocks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
