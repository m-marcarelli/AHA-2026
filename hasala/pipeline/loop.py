#!/usr/bin/env python3
"""
pipeline/loop.py — the outer orchestration loop.

For each of the 3 Trojan archetypes, iteratively:
    generate → insert → evaluate → (on failure) feed back and retry
until a candidate passes or --max-attempts is exhausted. Winners are
promoted to trojans/Trojan_{1,2,3}/ for submission.

Typical usage:
    # scaffold-only (no LLM, prints what it WOULD do):
    LLM_DRY_RUN=1 python3 pipeline/loop.py --max-attempts 1

    # real run with opus, short TB budget to keep iteration tight:
    python3 pipeline/loop.py --model opus --max-attempts 3 --tb-budget 180

All AI calls are logged to ai_logs/. Final candidates and per-attempt
scoreboard live under pipeline/runs/ and pipeline/scoreboard.jsonl.
"""
from __future__ import annotations
import argparse, json, os, shutil, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import WS, PIPELINE_DIR as PIPELINE, TROJANS_DIR as TROJANS, AI_LOG_DIR   # noqa: E402

ARCHETYPES = [
    ("A_magic_packet",     "Trojan_1"),
    ("B_register_sequence","Trojan_2"),
    ("C_counter_timebomb", "Trojan_3"),
]


def run(cmd: list[str], *, cwd: Path | None = None) -> subprocess.CompletedProcess:
    print(f"[loop] $ {' '.join(str(c) for c in cmd)}")
    return subprocess.run([str(c) for c in cmd], cwd=cwd, text=True)


def attempt(archetype: str, attempt_idx: int, model: str,
            tb_budget: int, feedback: str | None) -> tuple[bool, str, Path | None]:
    ts = time.strftime("%Y%m%dT%H%M%S")
    run_dir = PIPELINE / "runs" / f"{archetype}_attempt{attempt_idx:02d}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    spec_path = run_dir / "spec.json"
    fb_path = None
    if feedback:
        fb_path = run_dir / "feedback_from_prior.txt"
        fb_path.write_text(feedback)

    # 1. generate
    cmd = ["python3", "pipeline/generate.py",
           "--archetype", archetype,
           "--out", str(spec_path),
           "--model", model]
    if fb_path:
        cmd += ["--feedback", str(fb_path)]
    rc = run(cmd, cwd=WS).returncode
    if rc != 0 or not spec_path.exists():
        return False, f"generate.py failed (rc={rc})", run_dir

    # 2. insert
    cand_dir = run_dir / "candidate"
    rc = run(["python3", "pipeline/insert.py",
              "--spec", str(spec_path),
              "--out", str(cand_dir)], cwd=WS).returncode
    if rc != 0:
        return False, f"insert.py failed (rc={rc}) — likely anchor mismatch or syntax error", run_dir

    # 3. evaluate
    rc = run(["python3", "pipeline/evaluate.py",
              "--candidate", str(cand_dir),
              "--tb-budget-sec", str(tb_budget),
              "--ppa-budget-pct", "1.0"], cwd=WS).returncode
    eval_path = cand_dir / "eval.json"
    info = eval_path.read_text() if eval_path.exists() else f"no eval.json (rc={rc})"
    if rc == 0:
        return True, info, cand_dir
    return False, info, cand_dir


def promote(cand_dir: Path, target: str) -> None:
    dst = TROJANS / target
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)

    # submission-layout: rtl/ tb/ metrics/ ai/
    shutil.copytree(cand_dir / "rtl", dst / "rtl")
    shutil.copytree(cand_dir / "tb",  dst / "tb")
    if (cand_dir / "metrics").exists():
        shutil.copytree(cand_dir / "metrics", dst / "metrics")
    ai_dst = dst / "ai"
    ai_dst.mkdir(exist_ok=True)
    # Copy every ai_log produced during this candidate's generation attempts.
    # We capture them all: the user's submission rubric wants full history.
    for p in sorted(AI_LOG_DIR.iterdir()):
        shutil.copy2(p, ai_dst / p.name)
    shutil.copy2(cand_dir / "spec.json", dst / "spec.json")
    shutil.copy2(cand_dir / "eval.json", dst / "eval.json")
    print(f"[loop] PROMOTED {cand_dir}  →  {dst}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-attempts", type=int, default=3,
                    help="retries per archetype before giving up")
    ap.add_argument("--model", default="opus",
                    choices=["opus", "sonnet", "haiku"])
    ap.add_argument("--tb-budget", type=int, default=180,
                    help="wall-clock seconds allowed for base TB regression")
    ap.add_argument("--only", default=None,
                    choices=["A_magic_packet","B_register_sequence","C_counter_timebomb"],
                    help="run a single archetype (for debugging)")
    args = ap.parse_args()

    summary = []
    targets = ARCHETYPES if not args.only else [
        (a, t) for (a, t) in ARCHETYPES if a == args.only]

    for archetype, target in targets:
        print(f"\n======================================================")
        print(f"[loop] ARCHETYPE {archetype}  →  {target}")
        print(f"======================================================")

        prior_feedback: str | None = None
        winner: Path | None = None
        for i in range(1, args.max_attempts + 1):
            print(f"[loop] attempt {i}/{args.max_attempts} for {archetype}")
            ok, info, cand = attempt(archetype, i, args.model,
                                     args.tb_budget, prior_feedback)
            if ok:
                print(f"[loop] {archetype} PASSED on attempt {i}")
                winner = cand
                break
            prior_feedback = info
            print(f"[loop] attempt {i} failed, feedback:\n{info[:500]}")

        if winner:
            promote(winner, target)
            summary.append((archetype, target, "PASS", str(winner)))
        else:
            summary.append((archetype, target, "FAIL", "none"))

    print("\n==================== SUMMARY ====================")
    for a, t, v, c in summary:
        print(f"  {a:25s} → {t:10s}  {v:6s}  {c}")
    print("=================================================")

    # Return nonzero if any archetype failed
    return 0 if all(v == "PASS" for _, _, v, _ in summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
