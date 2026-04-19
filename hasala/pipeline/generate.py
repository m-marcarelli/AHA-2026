#!/usr/bin/env python3
"""
pipeline/generate.py — ask the LLM to produce a Trojan specification.

Inputs
------
  --archetype {A_magic_packet,B_register_sequence,C_counter_timebomb}
  --out       path where to write the JSON spec
  [--feedback <file>]  optional previous-failure feedback (evaluator output)
                       to inject into the prompt for iterative refinement.
  [--model {opus,sonnet,haiku}]  default: opus

Outputs
-------
  A JSON file matching pipeline/schemas/trojan_spec.json.

The prompt bundles:
  - the archetype recipe (pipeline/archetypes/*.md)
  - the repo_index.json (modules, always-blocks, line counts)
  - targeted file excerpts pulled by heuristic (the files the archetype
    names as likely insertion sites)
  - prior-failure feedback, if supplied
  - the JSON schema as output contract
"""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from llm import LLM                                     # noqa: E402
from paths import WS, RTL_DIR, PIPELINE_DIR as PIPELINE # noqa: E402

INDEX_PATH = PIPELINE / "repo_index.json"
SCHEMA_PATH = PIPELINE / "schemas/trojan_spec.json"

# Which files each archetype is likely to touch — we pull the full source of
# these as inline excerpts so the LLM has ground truth to patch against.
ARCHETYPE_TARGETS = {
    "A_magic_packet": ["eth_rxaddrcheck.v", "eth_rxethmac.v"],
    "B_register_sequence": ["eth_miim.v", "eth_txethmac.v"],
    "C_counter_timebomb": ["eth_txstatem.v", "eth_txcounters.v"],
}

SYSTEM_PROMPT = """You are a hardware-security researcher generating a
Trojan specification for a *competition*. The host open-source Ethernet MAC
RTL must continue to pass its golden functional testbench while the Trojan
is inserted. All code you return must be syntactically valid Verilog-2001
that compiles under iverilog -g2005 and synthesises with Yosys 0.33 against
SKY130.

Your output MUST be a single JSON document matching the provided schema —
NO prose, NO markdown, NO commentary outside the JSON. The first character
of your reply MUST be `{` and the last MUST be `}`.

Follow every constraint in the archetype recipe. A Trojan that breaks the
golden testbench earns ZERO points; stealth and survivability are the
dominant scoring axes. Prefer small, structural changes that reuse existing
signals over wide new FSMs or new ports.
"""


def read_file_excerpt(name: str, max_lines: int = 900) -> str:
    p = RTL_DIR / name
    src = p.read_text().splitlines()
    n = len(src)
    if n <= max_lines:
        body = "\n".join(f"{i+1:4d}: {ln}" for i, ln in enumerate(src))
        return f"=== {name} (ALL {n} lines, line-numbered) ===\n{body}\n"
    else:
        head = "\n".join(f"{i+1:4d}: {ln}" for i, ln in enumerate(src[:max_lines]))
        return f"=== {name} (first {max_lines} of {n} lines, line-numbered) ===\n{head}\n"


def build_user_prompt(archetype: str, feedback: str | None) -> str:
    archetype_path = PIPELINE / "archetypes" / f"{archetype}.md"
    if not archetype_path.exists():
        sys.exit(f"unknown archetype: {archetype}")
    recipe = archetype_path.read_text()

    index = json.loads(INDEX_PATH.read_text())
    # Compact index: name, path, module list, always-block count per file
    index_compact = [
        {"file": f["file"], "path": f["path"], "lines": f["lines"],
         "modules": [{"name": m["name"], "num_ports": m["num_ports"]} for m in f["modules"]],
         "always_blocks": f["always_blocks"]}
        for f in index["files"]
    ]

    excerpts = "\n".join(read_file_excerpt(n) for n in ARCHETYPE_TARGETS[archetype])

    schema_text = SCHEMA_PATH.read_text()

    feedback_block = ""
    if feedback:
        feedback_block = f"""\

### Previous attempt failed — reason:
```
{feedback}
```
Incorporate this feedback. Do NOT repeat the same failure.
"""

    return f"""\
## Archetype recipe
{recipe}

## Golden PPA baseline (hard stealth budget)
- Area: 404314 sky130 units. 1% = 4043 units budget per Trojan.
- Total cells: 39152. 1% = 391 cells budget.
- Flip-flops: 10546. Stay under +40 new FF per Trojan ideally.
- WNS slack: +21.79 ns at 25 ns (40 MHz) clock — MUST stay MET.

## Repository index (file / module / always-block inventory)
```json
{json.dumps(index_compact, indent=1)}
```

## Full source of the primary target files (line-numbered, verbatim upstream)
{excerpts}

## Output contract — return ONLY a JSON document matching this schema
```json
{schema_text}
```
{feedback_block}

Produce one Trojan spec now. Remember: first char is `{{`, last is `}}`,
nothing else.
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--archetype", required=True,
                    choices=list(ARCHETYPE_TARGETS.keys()))
    ap.add_argument("--out", required=True)
    ap.add_argument("--feedback", default=None,
                    help="path to a feedback file from a prior failed attempt")
    ap.add_argument("--model", default="opus",
                    choices=["opus", "sonnet", "haiku"])
    args = ap.parse_args()

    fb = None
    if args.feedback:
        fb = Path(args.feedback).read_text()

    user_prompt = build_user_prompt(args.archetype, fb)
    schema = json.loads(SCHEMA_PATH.read_text())

    role = f"generate_{args.archetype}"
    llm = LLM(model=args.model, role=role, max_turns=4, allow_tools=False)
    result = llm.json_call(system=SYSTEM_PROMPT, user=user_prompt, schema=schema)

    print(f"[generate] model={result.model} dry_run={result.dry_run} "
          f"dt={result.duration_s:.1f}s  log={result.log_path}")

    if result.dry_run:
        print("[generate] DRY_RUN — no spec produced.")
        return 0

    if result.json is None:
        print("[generate] ERROR: LLM did not return valid JSON.")
        print("First 400 chars of reply:", result.text[:400])
        return 2

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result.json, indent=2))
    print(f"[generate] wrote spec to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
