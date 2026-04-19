# Step 00 — Workspace Setup

**Date:** 2026-04-18
**Host OS:** Ubuntu 24.04.4 LTS (WSL2, kernel 6.6.87.2-microsoft-standard-WSL2)
**Shell:** bash

## Purpose
Create a self-contained workspace for the HOST AHA! 2026 Phase 1 red-team entry
against the FreeCores Ethernet MAC. All generation, synthesis, simulation, and
PPA measurement happens inside this folder so that the final submission zip can
be produced directly from it.

## Directory Layout

```
/home/hasala/competition/
├── HOST_AHA_Challenge_2026/     # upstream competition repo (read-only reference)
└── ethmac_workspace/            # our working tree
    ├── ethmac/                  # cloned FreeCores/ethmac repository
    ├── golden_metrics/          # PPA metrics of the UNMODIFIED design
    ├── trojans/                 # one subfolder per submitted Trojan
    │   ├── Trojan_1/{rtl,tb,metrics,ai}
    │   ├── Trojan_2/{rtl,tb,metrics,ai}
    │   └── Trojan_3/{rtl,tb,metrics,ai}
    ├── pipeline/                # agentic AI insertion / evaluation pipeline
    ├── scripts/                 # helper shell/python scripts
    ├── ai_logs/                 # raw chat transcripts and JSONL logs
    └── docs/                    # numbered step-by-step setup / run logs
```

## Commands executed

```bash
mkdir -p /home/hasala/competition/ethmac_workspace
cd /home/hasala/competition/ethmac_workspace
mkdir -p ethmac golden_metrics scripts ai_logs pipeline docs trojans
ls -la
```

## Output

```
drwxr-xr-x ai_logs
drwxr-xr-x docs
drwxr-xr-x ethmac
drwxr-xr-x golden_metrics
drwxr-xr-x pipeline
drwxr-xr-x scripts
drwxr-xr-x trojans
```

## Notes
- The upstream competition repo is left untouched under `HOST_AHA_Challenge_2026/`
  so that we always have a clean reference for the canonical `eth_synth/` scripts
  and SCORING.md.
- Every shell command we run from this point forward is captured in numbered
  documents under `docs/` (this file is `00_workspace_setup.md`). These documents
  are part of the submission package.
