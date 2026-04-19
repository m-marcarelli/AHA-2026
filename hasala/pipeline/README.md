# Agentic Trojan Insertion Pipeline (design sketch)

This folder will contain the **agentic AI pipeline** that generates, inserts,
and validates Trojan candidates against the golden ethmac. It's what earns
the "4 — Exemplary" score on SCORING.md Part 1 ("Dynamic, seamless AI
generation and insertion using advanced techniques").

## Architecture (to be implemented in later steps)

```
                ┌─────────────────────────────────────────────────────┐
                │            repo_index.json  (RAG corpus)            │
                │   - AST of every RTL file via pyverilog             │
                │   - chunked summaries of every always/module        │
                │   - academic Trojan taxonomy (Tehranipoor, Bhunia)  │
                └──────────────────────────┬──────────────────────────┘
                                           │
  ┌────────────┐                           ▼                  ┌──────────────┐
  │  archetype │   prompt   ┌──────────────────────────┐   ┌─▶│ insert.py    │
  │  template  │──────────▶ │  LLM generator           │──▶│  │ AST-level    │
  │  library   │            │  (Claude Opus 4.7 +      │   │  │ patch via    │
  └────────────┘            │   adversarial critic)    │   │  │ pyverilog    │
                            └──────────────┬───────────┘   │  └──────┬───────┘
                                           │               │         │
                                           ▼               │         ▼
                            ┌──────────────────────────┐   │  ┌──────────────┐
                            │  candidate/ folder       │◀──┘  │ modified RTL │
                            │  (rtl/ + trigger notes)  │      └──────┬───────┘
                            └──────────────┬───────────┘             │
                                           ▼                         ▼
                            ┌─────────────────────────────────────────────┐
                            │ evaluate.sh — closed-loop fitness gate       │
                            │  1. scripts/sim_base.sh (FULL TB  must pass) │
                            │  2. eth_synth/run_ppa.sh (PPA must be <1%)   │
                            │  3. exploit_tb.sv — Trojan must TRIGGER      │
                            └──────────────┬──────────────────────────────┘
                                           ▼
                              ┌────────────────────────────┐
                              │ scoreboard.jsonl            │
                              │  per-candidate CVSS, Δarea, │
                              │  Δcells, Δslack, tests_pass │
                              └────────────────────────────┘
                                           │
                                           ▼
                              select top 3 Trojans across
                              (loud / stealth / structural)
                              archetypes → finalize submission
```

## Components (to be implemented)

- `pipeline/archetypes/*.md` — one markdown "recipe" per Trojan archetype
  (loud-CVSS / deep-stealth / structural) feeding the LLM prompt.
- `pipeline/index_repo.py` — builds `repo_index.json` (pyverilog AST +
  file-chunk summaries).
- `pipeline/generate.py` — calls the LLM with {archetype, RAG context,
  prior failure feedback}; returns a structured JSON patch description.
- `pipeline/insert.py` — consumes the patch description, performs the
  actual AST-level insertion into a copy of `rtl/verilog/`.
- `pipeline/evaluate.sh` — orchestrates base-TB → PPA → exploit-TB and
  writes a scoreboard entry.
- `pipeline/loop.py` — outer loop: iterate until we have N passing
  candidates per archetype.

All LLM calls are logged verbatim to `ai_logs/YYYYMMDD-HHMMSS-<call>.json`
(both prompt and response) so the final submission can reproduce every
decision the AI made — a hard requirement under Part 1 "Documentation".

## Why AST-level insertion?

SCORING.md awards the top tier ("4 — Exemplary") specifically for
"Dynamic, seamless AI generation and insertion using advanced techniques
(e.g., AST manipulation)". Text-diff insertion is explicitly listed as
the 2/4 tier. Pyverilog gives us a full Verilog AST we can target with
surgical `always`-block and expression substitutions — no blind text
patching.
