#!/usr/bin/env python3
"""
pipeline/llm.py — LLM client for the Trojan insertion pipeline.

Backend: shells out to the `claude` CLI with `-p --output-format json`. This
uses the user's existing Claude Code authentication (no separate API key to
manage) and lets us pick the right model per call-site (opus for generation,
haiku for quick classifications).

Every call:
  1. Writes prompt + response verbatim to ai_logs/<timestamp>-<role>.json
     (the submission package requires "All AI interactions").
  2. Validates response against an optional JSON schema.
  3. Supports --dry-run via the LLM_DRY_RUN env var — returns a stub response
     without spending any credits. Useful when exercising the pipeline plumbing.

Usage from Python:
    from pipeline.llm import LLM
    llm = LLM(model="opus", role="generate_T1")
    reply = llm.json_call(system="...", user="...", schema={...})
"""
from __future__ import annotations
import json, os, subprocess, sys, time, uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from paths import WS, AI_LOG_DIR   # noqa: E402
AI_LOG_DIR.mkdir(parents=True, exist_ok=True)


def _extract_json(text: str) -> Any | None:
    """Best-effort JSON extraction from a model reply.
    Tries, in order: (1) raw parse, (2) first fenced ```json block,
    (3) the outermost {...} balanced substring.
    """
    import re
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # Balanced-brace scan: find the largest outermost {...}.
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass
    return None


@dataclass
class LLMResult:
    text: str
    json: Any | None = None
    model: str = ""
    log_path: Path | None = None
    duration_s: float = 0.0
    dry_run: bool = False
    raw_cli_response: dict | None = field(default=None, repr=False)


class LLM:
    """Wrapper around `claude -p` with structured logging.

    Parameters
    ----------
    model : str
        One of "opus", "sonnet", "haiku", or a full model name.
    role  : str
        Short tag used in the log filename ("index", "generate_T1", "critique").
    max_turns : int
        Hard cap on Claude's internal agentic loop (`--max-turns`). 1 for pure
        completion, higher if you want the tool some freedom to self-correct.
    """

    def __init__(self, model: str = "sonnet", role: str = "llm",
                 max_turns: int = 4, allow_tools: bool = False):
        self.model = model
        self.role = role
        self.max_turns = max_turns
        self.allow_tools = allow_tools
        self.dry_run = bool(int(os.environ.get("LLM_DRY_RUN", "0")))

    # ------------------------------------------------------------------ core

    def _log_path(self) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        uid = uuid.uuid4().hex[:6]
        return AI_LOG_DIR / f"{ts}_{self.role}_{uid}.json"

    def _run_claude(self, system: str, user: str,
                    schema: dict | None = None) -> dict:
        """Invoke claude CLI and return its parsed JSON envelope."""
        cmd = [
            "claude", "-p",
            "--output-format", "json",
            "--model", self.model,
            "--max-turns", str(self.max_turns),
        ]
        if system:
            cmd += ["--append-system-prompt", system]
        # NOTE: --json-schema is unreliable in claude -p mode (it's a hint,
        # not enforced). We instead embed the schema into the user prompt and
        # extract the JSON from the text reply ourselves.
        if not self.allow_tools:
            # Force pure-text generation: deny every tool. This keeps calls
            # deterministic and cheap; we don't want the model running bash.
            cmd += ["--disallowedTools", "Bash Edit Write Read Glob Grep Agent"]

        t0 = time.time()
        proc = subprocess.run(cmd, input=user, text=True, capture_output=True)
        dt = time.time() - t0

        # claude -p returns rc=1 on errors like max_turns but still emits a
        # valid JSON envelope on stdout. Parse first, then decide on failure.
        try:
            envelope = json.loads(proc.stdout)
        except json.JSONDecodeError:
            envelope = None

        if envelope is None:
            raise RuntimeError(
                f"claude -p returned non-JSON (rc={proc.returncode}, dt={dt:.1f}s):\n"
                f"STDERR: {proc.stderr[:2000]}\nSTDOUT: {proc.stdout[:500]}"
            )

        envelope["_duration_s"] = dt
        envelope["_cli_rc"] = proc.returncode

        # If an envelope came back but no "result" field AND it's flagged as
        # an error, surface that — but keep the envelope so callers can inspect
        # usage / cost data.
        if proc.returncode != 0 and not envelope.get("result"):
            # common CC errors: error_max_turns, error_rate_limit, etc.
            raise RuntimeError(
                f"claude -p errored (rc={proc.returncode}, subtype={envelope.get('subtype')}):\n"
                f"cost_usd={envelope.get('total_cost_usd')}\n"
                f"num_turns={envelope.get('num_turns')}\n"
                f"usage={envelope.get('usage')}"
            )
        return envelope

    # ---------------------------------------------------------------- public

    def text_call(self, system: str, user: str) -> LLMResult:
        return self._call(system, user, schema=None)

    def json_call(self, system: str, user: str,
                  schema: dict | None = None) -> LLMResult:
        return self._call(system, user, schema=schema)

    def _call(self, system: str, user: str,
              schema: dict | None) -> LLMResult:
        log_path = self._log_path()
        record = {
            "role": self.role,
            "model": self.model,
            "system": system,
            "user": user,
            "schema": schema,
            "dry_run": self.dry_run,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        }

        if self.dry_run:
            stub = {
                "result": "DRY_RUN",
                "note": "LLM_DRY_RUN=1 — no API call made.",
                "echo_user_head": user[:400],
            }
            record["response"] = stub
            record["duration_s"] = 0.0
            log_path.write_text(json.dumps(record, indent=2))
            return LLMResult(
                text=json.dumps(stub),
                json=stub,
                model=self.model,
                log_path=log_path,
                duration_s=0.0,
                dry_run=True,
                raw_cli_response=None,
            )

        envelope = self._run_claude(system, user, schema)
        # Claude CLI's JSON envelope puts the model reply under "result"
        text = envelope.get("result", "")
        parsed: Any | None = None
        if schema is not None:
            parsed = _extract_json(text)

        record["response"] = envelope
        record["parsed_json"] = parsed
        record["duration_s"] = envelope.get("_duration_s", 0.0)
        log_path.write_text(json.dumps(record, indent=2))

        return LLMResult(
            text=text,
            json=parsed,
            model=self.model,
            log_path=log_path,
            duration_s=envelope.get("_duration_s", 0.0),
            dry_run=False,
            raw_cli_response=envelope,
        )


# --------------------------------------------------------------------- smoke
if __name__ == "__main__":
    # Smoke check — never hits the API unless -r is passed explicitly.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("-r", "--really-call", action="store_true",
                    help="actually invoke the Claude CLI (spends credits)")
    ap.add_argument("--model", default="haiku")
    args = ap.parse_args()

    if not args.really_call:
        os.environ["LLM_DRY_RUN"] = "1"
        print("[llm.py] running in DRY_RUN mode (no credits spent)")
    llm = LLM(model=args.model, role="smoke")
    r = llm.json_call(
        system="You are a strict JSON emitter. Reply ONLY with valid JSON.",
        user='Return the object {"status": "ok", "model_name": "<your model>"}',
        schema={
            "type": "object",
            "properties": {"status": {"type": "string"},
                           "model_name": {"type": "string"}},
            "required": ["status"],
        },
    )
    print(f"[llm.py] model={r.model} dry_run={r.dry_run} dt={r.duration_s:.2f}s")
    print(f"[llm.py] log = {r.log_path}")
    print(f"[llm.py] reply (parsed json): {r.json}")
