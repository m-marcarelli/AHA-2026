#!/usr/bin/env python3
"""
pipeline/insert.py — apply a Trojan spec to a fresh copy of the RTL.

Steps
-----
1. Copy the pristine `ethmac/rtl/verilog/` tree into `<out_dir>/rtl/verilog/`.
2. For each patch entry in the spec:
      - Open <file>.
      - Verify the anchor text on anchor_line_range[0] and [1] matches the
        pristine file (defence against LLM line-number drift).
      - Apply `replace_range` or `insert_after`.
3. Also write the exploit testbench under `<out_dir>/tb/<exploit_tb.filename>`.
4. Write the parsed spec back under `<out_dir>/spec.json`.
5. Run a syntax smoke — iverilog -tnull across the patched RTL. If it fails,
   insert.py exits non-zero.

Usage:
  python3 insert.py --spec spec.json --out <candidate_dir>
"""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import WS, RTL_DIR   # noqa: E402

RTL_FILES = [
    "ethmac.v", "ethmac_defines.v", "eth_miim.v",
    "eth_clockgen.v", "eth_shiftreg.v", "eth_outputcontrol.v",
    "eth_registers.v", "eth_register.v", "eth_maccontrol.v",
    "eth_receivecontrol.v", "eth_transmitcontrol.v", "eth_txethmac.v",
    "eth_txcounters.v", "eth_txstatem.v", "eth_rxethmac.v",
    "eth_rxcounters.v", "eth_rxstatem.v", "eth_rxaddrcheck.v",
    "eth_crc.v", "eth_wishbone.v", "eth_spram_256x32.v",
    "eth_fifo.v", "eth_macstatus.v", "eth_random.v",
    # Non-synth files also needed for iverilog smoke:
    "timescale.v", "eth_top.v", "xilinx_dist_ram_16x32.v",
]


def apply_patch(file_path: Path, patch: dict) -> None:
    orig_lines = file_path.read_text().splitlines(keepends=True)
    n = len(orig_lines)
    start = int(patch["anchor_line_range"][0])
    end   = int(patch["anchor_line_range"][1])
    if not (1 <= start <= n and 1 <= end <= n and start <= end):
        raise ValueError(
            f"patch anchor out of range for {file_path.name}: "
            f"[{start},{end}] but file has {n} lines"
        )

    def strip_nl(s: str) -> str:
        return s.rstrip("\r\n")

    want_start = patch.get("anchor_start_text")
    want_end   = patch.get("anchor_end_text")
    got_start  = strip_nl(orig_lines[start - 1])
    got_end    = strip_nl(orig_lines[end - 1])
    if want_start and want_start.strip() and want_start.strip() not in got_start:
        raise ValueError(
            f"anchor_start_text mismatch in {file_path.name}:{start}\n"
            f"  expected: {want_start!r}\n"
            f"  got     : {got_start!r}"
        )
    if want_end and want_end.strip() and want_end.strip() not in got_end:
        raise ValueError(
            f"anchor_end_text mismatch in {file_path.name}:{end}\n"
            f"  expected: {want_end!r}\n"
            f"  got     : {got_end!r}"
        )

    replacement = patch["replacement"]
    if not replacement.endswith("\n"):
        replacement += "\n"

    if patch["mode"] == "replace_range":
        new_lines = orig_lines[: start - 1] + [replacement] + orig_lines[end:]
    elif patch["mode"] == "insert_after":
        new_lines = orig_lines[: end] + [replacement] + orig_lines[end:]
    else:
        raise ValueError(f"unknown patch mode: {patch['mode']}")

    file_path.write_text("".join(new_lines))


def iverilog_syntax_check(rtl_dir: Path) -> tuple[bool, str]:
    """Compile-only pass with `iverilog -tnull` to catch syntax regressions
    before we hand the tree off to the simulator. Top module = ethmac."""
    cmd = ["iverilog", "-tnull", "-g2005", "-I", str(rtl_dir), "-s", "ethmac"]
    for name in RTL_FILES:
        p = rtl_dir / name
        if p.exists():
            cmd.append(str(p))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    ok = (proc.returncode == 0)
    log = proc.stderr or proc.stdout
    return ok, log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--out", required=True,
                    help="destination candidate directory (created fresh)")
    args = ap.parse_args()

    spec = json.loads(Path(args.spec).read_text())
    out_dir = Path(args.out)
    rtl_out = out_dir / "rtl" / "verilog"
    tb_out  = out_dir / "tb"

    # 1. fresh copy of pristine RTL
    if out_dir.exists():
        shutil.rmtree(out_dir)
    rtl_out.mkdir(parents=True, exist_ok=True)
    tb_out.mkdir(parents=True, exist_ok=True)
    for name in RTL_FILES:
        src = RTL_DIR / name
        if src.exists():
            shutil.copy2(src, rtl_out / name)

    # 2. apply patches
    modified_files = []
    for patch in spec["patches"]:
        fp = rtl_out / patch["file"]
        if not fp.exists():
            print(f"[insert] ERROR: patch targets non-existent file {patch['file']}")
            return 3
        try:
            apply_patch(fp, patch)
        except Exception as e:
            print(f"[insert] FAIL: {e}")
            return 4
        modified_files.append(patch["file"])
        print(f"[insert] patched {patch['file']} "
              f"({patch['mode']} {patch['anchor_line_range']})")

    # 3. exploit testbench
    tb = spec.get("exploit_tb", {})
    tb_name = tb.get("filename", "exploit_tb.v")
    (tb_out / tb_name).write_text(tb.get("contents", ""))

    # 4. persist spec for later consumption
    (out_dir / "spec.json").write_text(json.dumps(spec, indent=2))
    (out_dir / "modified_files.json").write_text(
        json.dumps(sorted(set(modified_files)), indent=2))

    # 5. syntax smoke
    ok, log = iverilog_syntax_check(rtl_out)
    (out_dir / "iverilog_syntax.log").write_text(log)
    if not ok:
        print(f"[insert] SYNTAX FAIL. See {out_dir}/iverilog_syntax.log")
        print(log[-1500:])
        return 5

    print(f"[insert] OK — candidate written to {out_dir} "
          f"(patched files: {', '.join(sorted(set(modified_files)))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
