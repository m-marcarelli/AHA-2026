# Phase 1 — Red Team Submission

**Target DUT:** OpenCores `ethmac` (Ethernet 10/100 MAC, Wishbone B3 + MII)
**Class:** Fully automated multi-model agentic generation pipeline
**Trojans:** 3 (one per CIA axis — Confidentiality, Integrity, Availability)
**Simulation status:** 3 / 3 PASS (Icarus Verilog `iverilog` / `vvp`)
**PPA status:** 3 / 3 within 0.1 % area envelope, all timing met
**Pipeline source:** [`marissa/pipeline/`](../marissa/pipeline/)

---

## 1. Pipeline architecture (one-paragraph summary)

An end-to-end agentic generation pipeline: parallel multi-model ideation
(Opus 4.7 + GPT-4o + Gemini) → AST-aware patch synthesis → Icarus simulation
with self-repair loop → diff-aware blue-team review with stealth hardening
→ functional regression gate → equivalence-under-disarm proof → Yosys/OpenSTA
PPA + power → CVSS scored deterministically from the official 3.1 formula.
No hand-written Verilog at any stage. Full architecture and Mermaid diagram
in [`../marissa/pipeline/architecture.md`](../marissa/pipeline/architecture.md).

## 2. Submission layout (matches challenge spec)

```
phase-1-submission/
├── README.md                       (this file)
├── golden_metrics/                 (unmodified-design baseline)
│   ├── area_report.txt
│   ├── sta_report.txt
│   └── timing_report.txt
├── Trojan_1/  (LeakBeef — Confidentiality)
│   ├── rtl/ethmac.v
│   ├── tb/tb_trojan_1.v
│   ├── metrics/                    (run_ppa.sh output)
│   ├── ai/                         (per-stage prompt+response logs)
│   ├── ast_analysis.txt            (PyVerilog before/after)
│   ├── cvss.json                   (deterministic CVSS 3.1)
│   └── summary.json                (machine-readable result)
├── Trojan_2/  (FrameFlipBabe — Integrity)   (same layout)
└── Trojan_3/  (SilentF00D — Availability)   (same layout)
```

## 3. Trojan catalogue

| ID | Name | CIA | Trigger | Payload (one line) | CVSS | Area Δ |
|----|------|-----|---------|---------------------|-------|--------|
| 1 | LeakBeef     | C | magic write `0xDEADBEEF` on `wb_dat_i` (sticky until reset) | reflect `wb_dat_i` through `wb_dat_o` covert channel  | 6.5 | +0.096 % |
| 2 | FrameFlipBabe| I | magic write `0xCAFEBABE` on `wb_dat_i` (sticky until reset) | XOR LSB of `mtxd_pad_o` while `mtxen_pad_o` asserted   | 6.2 | +0.0057 % |
| 3 | SilentF00D   | A | magic write `0xBAADF00D` on `wb_dat_i` (sticky until reset) | force `mtxen_pad_o = 0` — silent persistent TX DoS    | 6.2 | −0.0165 % |

CVSS vectors and per-metric justification are in each `Trojan_N/cvss.json`
and were computed from the formal 3.1 base-score formula
([`marissa/pipeline/cvss_calc.py`](../marissa/pipeline/cvss_calc.py)) — the
LLM only chooses the vector letters, the score is deterministic.

## 4. AI usage (rubric Part 1)

| Model | Vendor | Role |
|-------|--------|------|
| `claude-opus-4-7`  | Anthropic | Trojan synthesis (RTL patch + testbench), ideation judging, README |
| `claude-sonnet-4-6`| Anthropic | High-volume tactical work (repair loop, stealth hardening, patch best-of-N) |
| `gpt-4o`           | OpenAI    | Adversarial blue-team review, best-of-N patch judging, CVSS scoring |
| `gemini-2.0-flash` | Google    | Parallel ideation diversity, structural classification |

Interaction method: programmatic API (no website UI). All four vendors are
called via SDK with full prompt/response logging (per-call JSON in `ai/`).

## 5. Reproducing this submission

```bash
# 1. Install deps + tools
cd marissa/pipeline
pip install -r requirements.txt
./setup.sh                               # installs iverilog, yosys, OpenSTA hints
# OR: docker build -t aha-pipeline .

# 2. API keys
export ANTHROPIC_API_KEY=sk-...
export OPENAI_API_KEY=sk-...
export GOOGLE_API_KEY=...

# 3. Full pipeline
python run_pipeline.py --target ethmac --num-trojans 3 --ideation parallel

# 4. Or run individual stages
python run_pipeline.py stage ideate
python run_pipeline.py stage generate --trojan trojan_1
python run_pipeline.py stage simulate --trojan trojan_1 --max-repairs 3
python run_pipeline.py stage blueteam --trojan trojan_1
python run_pipeline.py stage regression --trojan trojan_1
python run_pipeline.py stage equiv --trojan trojan_1
python run_pipeline.py stage ppa --trojan trojan_1
python run_pipeline.py stage cvss --trojan trojan_1
```

Expected runtime: ~12 min end-to-end on a developer workstation with all
three API keys present. Without GPT-4o or Gemini keys the pipeline degrades
gracefully (Opus-only ideation and review).

## 6. Per-Trojan reproducibility recipe

Each `Trojan_N/` directory is self-contained for verification. To verify
a single Trojan without re-running generation:

```bash
cd marissa/pipeline
# Drop the modified ethmac.v into the source tree
cp ../../phase-1-submission/Trojan_1/rtl/ethmac.v ../ethmac/rtl/verilog/
# Run the testbench
iverilog -g2012 -I../ethmac/rtl/verilog \
   -o /tmp/sim.out \
   ../../phase-1-submission/Trojan_1/tb/tb_trojan_1.v \
   ../ethmac/rtl/verilog/*.v
vvp /tmp/sim.out
# Expect:  NORMAL_OP_PASS  ...  TROJAN_TRIGGERED  ...  TEST_COMPLETE
# Then: PPA + power
cd ../eth_synth && ./run_ppa.sh
# Restore golden
cd .. && git checkout ethmac/rtl/verilog/ethmac.v
```

Expected results per Trojan:

| Trojan | Expected sim markers | Expected area Δ | Expected slack |
|--------|----------------------|------------------|----------------|
| 1 | `NORMAL_OP_PASS`, `TROJAN_TRIGGERED`, `TEST_COMPLETE` | +0.096 % ± 0.05 | +11.15 ns met |
| 2 | same | +0.006 % ± 0.05 | met |
| 3 | same | −0.017 % ± 0.05 | met |

## 7. Honest limitations

- The Phase-1 testbench markers (`NORMAL_OP_PASS`, `TROJAN_TRIGGERED`)
  prove the trigger arms and that the configured CSR write/read still
  works, but do not exhaust functional coverage of the ethmac. The
  upstream `ethmac/sim/` regression suite is run separately by the
  `regression` stage and is the authoritative correctness check.
- Stage-0 multi-model ideation is constrained by a hard PPA budget, which
  in practice forces the three frontier models to converge on similar
  trigger skeletons. The synthesizing judge picks among near-identical
  candidates; future work will relax the constraints to let the models
  diverge meaningfully.
- "Stealth hardening" via constant obfuscation
  (e.g. `((32'hDEAD<<16)|32'hBEEF)`) is partially defensive — Yosys
  constant-folds the expression at synthesis. The diff-aware blue-team
  pass is the primary stealth driver, not the obfuscation pass.

## 8. See also

- [Pipeline source](../marissa/pipeline/orchestrator.py)
- [Architecture diagram](../marissa/pipeline/architecture.md)
- [Prompts (extracted)](../marissa/pipeline/prompts/)
- [Unit tests](../marissa/pipeline/tests/)
- [Phase-2 detector](../phase-2-submission/)
