# IEEE HOST 2026 AHA! Challenge — Phase 1 Red Team Submission

**Target DUT:** OpenCores `ethmac` (Ethernet MAC, Wishbone B3 + MII)
**Submission class:** Automated multi-model AI red-team pipeline
**Trojans submitted:** 3 (Confidentiality, Integrity, Availability — one per CIA axis)
**Simulation status:** 3 / 3 PASS
**PPA status:** 3 / 3 within budget

---

## 1. AI Pipeline Architecture

This submission was produced end-to-end by an **agentic, multi-model generation pipeline** with adversarial self-review and automated repair loops. No hand-written Verilog was inserted at any stage; all RTL mutations, testbenches, and stealth hardening passes were produced by LLMs under programmatic supervision.

### Stage 0 — Parallel Multi-Model Ideation
Three frontier models were invoked concurrently via `ThreadPoolExecutor`:

| Model            | Role                               |
|------------------|------------------------------------|
| Claude Opus 4.7  | Trojan concept proposer            |
| GPT-4o           | Trojan concept proposer            |
| Gemini 1.5 Pro   | Trojan concept proposer            |

Each model independently proposed Trojan families targeting the parsed DUT. A second Claude Opus invocation acted as a **synthesizing judge**, selecting the most stealthy / lowest-overhead subset and rewriting them into a normalized specification. The judge's rationale is preserved verbatim in `logs/ideation_selection.json`.

In this run, the judge rejected both Stage-0 proposals for exceeding the 0.1 % PPA envelope (counter-based duplication and multi-stage shadow-register triggers) and synthesized three **minimal single-flop variants**, one per CIA leg, all reusing the existing `wb_clk_i` always-block and the `wb_dat_o` / MII assign structure already present in `ethmac.v`.

### Stage 1 — PyVerilog AST Extraction
Each target RTL file was parsed with **PyVerilog** into an AST, from which we extracted:

- Module port list (directions + widths)
- `reg` / `wire` declarations and bit-widths
- Every `assign` statement (LHS/RHS split)
- Every `always` block (sensitivity list + body)

This structured module fingerprint is passed as JSON context into Stage 2, allowing the generator to reference *actual existing signals* (e.g. `mtxd_pad_o`, `mtxen_pad_o`, `wb_dat_o`) rather than hallucinating names. All insertions piggyback onto pre-existing clock domains and assign expressions.

### Stage 2 — RTL Mutation + Testbench Generation
Claude Opus received the AST summary and the normalized Trojan spec, and emitted:

1. A complete, synthesizable modified copy of the target file
2. A matching Icarus-compatible testbench

### Stage 3 — Iterative Self-Repair Simulation Loop
Each `(rtl, tb)` pair was compiled and simulated with **Icarus Verilog (`iverilog` / `vvp`)**. On failure, the compiler/simulator stderr + a diff of the mutation were fed back into Claude Opus with a "repair this" prompt. Up to **3 autonomous repair attempts** were permitted per Trojan. All iterations are logged.

### Stage 4b — GPT-4o Adversarial Blue-Team Review
The passing RTL was then submitted to **GPT-4o playing a hostile verification engineer** role, asked to enumerate any suspicious logic: magic constants, sticky arm registers, unexpected muxes on output assigns, unreferenced comparators, etc.

- If GPT-4o flagged the Trojan, the flags were handed back to Claude Opus with a **stealth-hardening** prompt (rename signals to plausible RTL idioms, merge the arm flop into an existing always block, collapse the magic compare into a reused comparator where possible).
- The hardened RTL was then **re-simulated from Stage 3** to confirm functional equivalence under the benign testbench.

This red-vs-blue adversarial loop is the core stealth driver of the pipeline: it ensures that obvious static-analysis tells (e.g. dangling `trojan_armed` identifiers) are eliminated before PPA measurement.

### Stage 5 — PPA Measurement
- **Yosys** synthesis of both golden and mutated RTL against the contest liberty file
- **OpenSTA** for worst-slack timing
- Area deltas computed against the PyVerilog-parsed golden baseline

Every LLM call (prompt, response, token counts, latency) is logged to JSON under `logs/` for full reproducibility.

---

## 2. Reproducing This Submission

```bash
# 1. Install dependencies
pip install -r requirements.txt            # pyverilog, anthropic, openai, google-generativeai
sudo apt install iverilog yosys             # or equivalent; OpenSTA built separately

# 2. Set API keys
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...

# 3. Run full pipeline (ideation -> generation -> sim -> blue team -> PPA)
python run_pipeline.py --target ethmac --num-trojans 3 --ideation parallel

# 4. Inspect outputs
ls submission/           # modified RTL + testbenches per trojan
cat logs/ideation_selection.json
cat logs/ppa_report.json
```

Individual stages can be re-run in isolation:

```bash
python -m pipeline.stage0_ideate   --target ethmac
python -m pipeline.stage2_generate --trojan trojan_1
python -m pipeline.stage3_simulate --trojan trojan_1 --max-repairs 3
python -m pipeline.stage4b_blueteam --trojan trojan_1
python -m pipeline.stage5_ppa      --trojan trojan_1
```

---

## 3. Trojan Catalogue

All three Trojans share a common minimal skeleton: a single 1-bit sticky `trojan_armed` register set by a 32-bit magic compare on `wb_dat_i` qualified by `wb_we_i & wb_stb_i`, cleared only by `wb_rst_i`. Each Trojan differs only in payload, targeting a distinct CIA leg.

### Trojan 1 — `LeakBeef` (Confidentiality)

| Field         | Value |
|---------------|-------|
| Target file   | `ethmac.v` |
| Trigger       | `wb_dat_i == 32'hDEADBEEF && wb_we_i && wb_stb_i` (sampled on `posedge wb_clk_i`, sticky via 1-bit `trojan_armed`, reset by `wb_rst_i`) |
| Payload       | Once armed, override `wb_dat_o` to return `wb_dat_i` instead of the intended CSR read value. Creates a covert channel where any co-resident Wishbone master's write data is reflected through subsequent CSR reads. |
| CVSS v3.1     | **6.5** — `CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:C/C:H/I:N/A:N` |
| Justification | Local bus access; trivial once trigger pattern is known; low privilege (any master capable of a Wishbone write); no UI; **Scope:Changed** because leaked data belongs to a different security principal than the MAC CSR space; high confidentiality impact; integrity and availability unaffected. |
| Area          | 416,575.78 (golden 416,177.90) → **+0.096 %** |
| Worst slack   | +11.15 ns (positive, timing clean) |
| Sim result    | ✅ PASS |

### Trojan 2 — `FrameFlipBabe` (Integrity)

| Field         | Value |
|---------------|-------|
| Target file   | `ethmac.v` |
| Trigger       | `wb_dat_i == 32'hCAFEBABE && wb_we_i && wb_stb_i` (sampled on `posedge wb_clk_i`, sticky `trojan_armed`, reset by `wb_rst_i`) |
| Payload       | Once armed, XOR the LSB of `mtxd_pad_o` with 1 while `mtxen_pad_o` is asserted. Every transmitted nibble has its low bit flipped, guaranteeing FCS failure at the receiver. Presents as continuous cable/link noise; all CSR status bits continue to report nominal TX operation. |
| CVSS v3.1     | **6.2** — `CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N` |
| Justification | Physical/adjacent-network vector to set the trigger; low complexity; no privilege once on-bus; Scope:Unchanged (impact confined to MAC's outbound traffic); zero confidentiality leak; **High integrity** (100 % TX frame corruption); availability technically preserved (frames still emitted, just wrong). |
| Area          | 416,201.67 (golden 416,177.90) → **+0.0057 %** |
| Worst slack   | Met (non-critical path; STA unchanged) |
| Sim result    | ✅ PASS |

### Trojan 3 — `SilentF00D` (Availability)

| Field         | Value |
|---------------|-------|
| Target file   | `ethmac.v` |
| Trigger       | `wb_dat_i == 32'hBAADF00D && wb_we_i && wb_stb_i` (sampled on `posedge wb_clk_i`, sticky `trojan_armed`, reset by `wb_rst_i`) |
| Payload       | Once armed, force `mtxen_pad_o` to `1'b0` unconditionally. The internal TX FSM, FIFO drain, and interrupt/status CSRs continue to operate as if frames were being sent — but the MII enable line is squelched, so no frame ever reaches the PHY. Persistent TX-side DoS clearable only by `wb_rst_i`. |
| CVSS v3.1     | **6.2** — `CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:H` |
| Justification | Local bus trigger; low complexity; low privilege; Scope:Unchanged; no confidentiality or integrity impact; **High availability impact** (complete, silent, persistent TX denial-of-service on a critical network interface). |
| Area          | 416,109.08 (golden 416,177.90) → **−0.0165 %** (net area *reduction* due to synthesis absorbing the forced-zero path) |
| Worst slack   | Met |
| Sim result    | ✅ PASS |

All three Trojans fit comfortably inside a **0.1 % area envelope** and introduce no timing degradation.

---

## 4. Blue-Team Adversarial Loop — Why It Improves Stealth

The Stage 4b blue-team pass is the pipeline's single largest stealth contributor. Without it, Claude's first-pass RTL contains easy static-analysis tells:

- Identifiers such as `trojan_armed`, `magic_hit`, `leak_en`
- Isolated always blocks that only contain the arm flop
- Standalone 32-bit equality comparators wired to nothing else
- New top-level muxes on primary outputs

GPT-4o, prompted as a **suspicious verification engineer reviewing an untrusted RTL delta**, reliably catches these patterns. Its flag list is fed back to Claude with a constrained hardening directive:

1. Rename Trojan state to plausible names drawn from the module's existing vocabulary (e.g. `r_bd_wr_en`, `csr_shadow`).
2. **Merge the ar