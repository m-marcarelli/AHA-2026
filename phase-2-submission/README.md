# Phase 2 — Detection Pipeline (CTF Combat)

Defensive points come from opposing teams' detectors *failing* to find
our Phase-1 trojans. Offensive points come from *our* detector finding
theirs. This directory contains the offensive detector.

## 1. Architecture

```
opponent RTL ─┐
              │
golden RTL ───┼──► [structural detector]   ──┐
              │                              │
              ├──► [LLM ensemble: Opus +     │
              │     GPT-4o + Gemini          ├──► aggregated, ranked,
              │     reviewing the unified    │    localised findings
              │     diff]                    │    (file:line, ast_path,
              │                              │    mechanism, confidence,
              ├──► [behavioral fuzzer:       │    rationale)
              │     N randomized stimuli     │
              │     vs golden under iverilog]│
              │                              │
              └──► [FP harness: re-run on    ──┘
                    a clean copy of golden;
                    report FP rate]
```

The structural and LLM stages are reused from the red-team pipeline at
`../marissa/pipeline/{structural_detector,diff_blueteam}.py`. This
"build once, use twice" architecture means improvements to the
detector immediately strengthen our own stealth pass and vice versa.

## 2. Pattern coverage (rubric Part 4: Localization & Explainability)

The structural detector outputs each finding with `file:line`,
`mechanism`, and a confidence score, satisfying the rubric's Exemplary
bar of "exact line / AST node + mechanism".

| Mechanism | Detector |
|----------|----------|
| Magic-hex constant (DEADBEEF / CAFEBABE / BAADF00D / ...) | `detect_joke_hex` |
| Obfuscated constant (`((32'hDEAD<<16)|32'hBEEF)`)         | `detect_obfuscated_const` |
| New top-level identifier                                   | `detect_new_top_level_identifiers` |
| New always block                                           | `detect_new_always_blocks` |
| Wide compare with single reader                            | `detect_wide_compares_with_single_reader` |
| New mux on primary output port                             | `detect_new_mux_on_output` |
| Synchroniser-chain extension                               | `detect_sync_chain_changes` |
| CRC-XOR arity change                                       | `detect_crc_xor_arity_change` |

LLM reviewers add a fourth signal: each receives the unified diff and
returns a JSON verdict (`REFACTOR` / `TROJAN`) plus rationale.
Three independent reviewers reduce single-vendor blind spots.

## 3. False-positive resilience (rubric Part 4)

`detector.py --no-fp-check` disables this; by default the detector
runs every check on a clean copy of the golden RTL. A finding on
clean RTL is by definition a false positive. The structural detector
is calibrated against the OpenCores ethmac upstream — empirical
target: 0% high-confidence FP, <5% any-confidence FP.

## 4. Usage

```bash
# Install deps (shared with red-team pipeline)
pip install -r ../marissa/pipeline/requirements.txt

# Required: golden + opponent RTL trees
python detector.py \
   --golden ../marissa/ethmac/rtl/verilog \
   --opponent /path/to/opponent_team/rtl \
   --out report.json

# Optional: behavioral fuzzer + skip FP harness
python detector.py \
   --golden ../marissa/ethmac/rtl/verilog \
   --opponent /path/to/opponent_team/rtl \
   --fuzz 200 --no-fp-check \
   --out report.json
```

API keys (any subset works; missing keys silently degrade the
ensemble to fewer reviewers):

```bash
export ANTHROPIC_API_KEY=sk-...
export OPENAI_API_KEY=sk-...
export GOOGLE_API_KEY=...
```

## 5. Output schema

```json
{
  "schema": "aha-2026-detector-v1",
  "golden_dir": "...",
  "opponent_dir": "...",
  "per_file": [
    {
      "file": "ethmac.v",
      "structural_score": 0.42,
      "passes_ensemble": false,
      "ensemble_signals": ["claude-opus", "gpt-4o", "structural"],
      "findings": [
        {
          "file": "ethmac.v",
          "line": 341,
          "mechanism": "magic-hex constant",
          "confidence": 0.95,
          "rationale": "introduces canonical trojan-literature value 0xDEADBEEF",
          "matched_text": "if (wb_dat_i == 32'hDEADBEEF && wb_we_i && wb_stb_i)"
        }
      ]
    }
  ],
  "summary": {
    "files_analysed": 23,
    "total_findings": 7,
    "high_confidence": 3,
    "trojan_likely": true,
    "top_findings": [...]
  },
  "false_positive_check": {
    "clean_files_checked": 23,
    "false_positives": 0
  }
}
```

## 6. Self-test

The structural detector has a dual-use property: pointing it at our
own Phase-1 submission should flag our own trojans (which use the
canonical magic-hex + sticky-flop pattern). This is intentional — it
proves the detector is calibrated:

```bash
python detector.py \
   --golden ../marissa/ethmac/rtl/verilog \
   --opponent ../phase-1-submission/Trojan_1/rtl \
   --no-fp-check --out self_test.json
# Expect: "trojan_likely": true, finding 0xDEADBEEF magic-hex
```

The Phase-2 regeneration uses `families.py` templates that defeat
exactly these patterns (no joke hex, no isolated sticky flops, no
new top-level identifiers where avoidable).
