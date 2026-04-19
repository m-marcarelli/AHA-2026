#!/usr/bin/env bash
# AHA 2026 pipeline — host setup helper.
# Installs Python deps and prints exact instructions for the EDA toolchain
# (Icarus Verilog, Yosys, OpenSTA, sv2v) which usually need package-manager
# or build-from-source steps that vary by platform.

set -euo pipefail

cd "$(dirname "$0")"

echo "== Installing Python dependencies =="
pip install -r requirements.txt

echo
echo "== EDA toolchain (verify each is on PATH) =="
need_iverilog=0; need_yosys=0; need_opensta=0; need_sv2v=0
command -v iverilog >/dev/null 2>&1 || need_iverilog=1
command -v yosys    >/dev/null 2>&1 || need_yosys=1
command -v sta      >/dev/null 2>&1 || need_opensta=1
command -v sv2v     >/dev/null 2>&1 || need_sv2v=1

if [ $need_iverilog -eq 0 ]; then echo "  iverilog: $(iverilog -V 2>&1 | head -1)"; else echo "  iverilog: MISSING"; fi
if [ $need_yosys    -eq 0 ]; then echo "  yosys:    $(yosys -V 2>&1 | head -1)";    else echo "  yosys:    MISSING"; fi
if [ $need_opensta  -eq 0 ]; then echo "  OpenSTA:  $(sta -version 2>&1 | head -1)"; else echo "  OpenSTA:  MISSING"; fi
if [ $need_sv2v     -eq 0 ]; then echo "  sv2v:     $(sv2v --version 2>&1 | head -1)"; else echo "  sv2v:     (only required for cv32e40p target)"; fi

if [ $need_iverilog -eq 1 ] || [ $need_yosys -eq 1 ] || [ $need_opensta -eq 1 ]; then
  echo
  echo "== Install hints =="
  echo "Debian/Ubuntu:"
  echo "  sudo apt install -y iverilog yosys"
  echo "  # OpenSTA: build from https://github.com/The-OpenROAD-Project/OpenSTA"
  echo "macOS (Homebrew):"
  echo "  brew install icarus-verilog yosys opensta"
  echo "Windows:"
  echo "  Recommend WSL2 + Ubuntu, or use the provided Dockerfile:"
  echo "    docker build -t aha-pipeline ."
  echo "    docker run --rm -it -e ANTHROPIC_API_KEY -e OPENAI_API_KEY -e GOOGLE_API_KEY aha-pipeline"
  exit 1
fi

echo
echo "== API keys =="
for k in ANTHROPIC_API_KEY OPENAI_API_KEY GOOGLE_API_KEY; do
  if [ -z "${!k:-}" ]; then echo "  $k: NOT SET (pipeline degrades gracefully)"; else echo "  $k: set"; fi
done

echo
echo "Setup OK. Run with: python run_pipeline.py --target ethmac --num-trojans 3"
