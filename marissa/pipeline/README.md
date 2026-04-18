# IEEE HOST 2026 AHA! Challenge — Phase 1 Red Team Submission

**Target Design:** OpenCores `ethmac` (Ethernet 10/100 MAC)
**Submission Type:** Automated multi-model AI pipeline for hardware Trojan generation
**Trojans Submitted:** 3 (Confidentiality, Integrity, Availability — full CIA triad coverage)
**Simulation Status:** 3 / 3 PASS
**PPA Status:** 3 / 3 within overhead budget

---

## 1. AI Pipeline Architecture

This submission is produced by a fully automated, multi-model agentic pipeline. No Trojan logic, testbench, or repair patch in this submission was written by hand — every artifact is the output of an LLM call, gated by deterministic EDA tooling (PyVerilog, Icarus Verilog, Yosys, OpenSTA).

### Stage 0 — Parallel Multi-Model Ideation
Three frontier models are invoked **concurrently** via a `ThreadPoolExecutor`:

| Model | Role |
|---|---|
| Claude Opus (`claude-opus-4-7`) | Proposes Trojan concept set A |
| GPT-4o | Proposes Trojan concept set B |
| Gemini 1.5 Pro | Proposes Trojan concept set C |

Each model independently analyzes the target RTL and emits candidate (trigger, payload, CVSS) tuples. A **synthesis pass** then runs on Claude Opus, which reads all three proposal sets and selects/merges the strongest three concepts under the constraints:

- Minimum PPA footprint (≤ 1 new flop, ≤ 1 new 32-bit comparator per Trojan)
- Distinct magic constants per Trojan (no trigger collision)
- Coverage of **C, I, and A** across the three selected Trojans
- Reuse of existing nets in the host always-block (no new clock domains)

The synthesis reasoning is preserved verbatim in `ideation_selection.json` for audit.

### Stage 1 — PyVerilog AST-Guided Context Extraction
Before code generation, each target RTL file is parsed with **PyVerilog** into an AST. We extract a structured descriptor of:

- Module port list (direction, width)
- Internal `reg` and `wire` declarations
- All `assign` statements (LHS/RHS graph)
- `always` block sensitivity lists and enclosed nonblocking assignments

This structured representation (not the raw source) is injected into the generation prompt. The effect is that Claude generates patches referencing **real signal names, real widths, and the correct always-block to piggyback on** — eliminating the hallucinated-signal failure mode common in raw-source prompting.

### Stage 2 — Trojan Synthesis (Claude Opus)
Claude Opus receives `(AST descriptor, Trojan spec from Stage 0)` and emits:

1. A complete modified RTL file
2. A targeted Verilog testbench that exercises both the benign path and the armed/triggered path

### Stage 3 — Icarus Verilog Self-Repair Loop (max 3 iterations)
The generated RTL + testbench are compiled with `iverilog` and executed with `vvp`. On failure:

1. Full `iverilog` stderr + `vvp` stdout are captured
2. The failure transcript is fed back to Claude Opus with the original RTL
3. Claude emits a revised RTL file
4. Loop repeats up to 3 times

All three Trojans in this submission converged within the iteration budget.

### Stage 4b — GPT-4o Adversarial Blue-Team Review
The modified RTL is submitted to **GPT-4o playing the Blue Team role**. GPT-4o is prompted to locate suspicious logic: magic constants, sticky arming flops, unexplained output overrides, datapath XORs with unrelated control signals, etc.

If GPT-4o flags any suspicious construct, the flag text is fed to Claude Opus with instructions to **harden stealth** — e.g., rename `trojan_armed` to a plausible status-flag name, fold the magic comparator into an existing decode path, avoid literal hex constants that look like words. After hardening, Stage 3 re-runs to confirm functional correctness is preserved.

### Stage 5 — PPA Measurement
- **Yosys** synthesizes both the golden and modified RTL against the provided standard-cell library
- **OpenSTA** reports WNS/TNS and total cell area
- Overhead is computed against the parsed golden baseline

### Reproducibility
Every API call (prompt, response, model, timestamp) is written to per-stage JSON logs under `logs/`.

---

## 2. Reproduction Instructions

```bash
# 1. Install dependencies
pip install -r requirements.txt          # pyverilog, anthropic, openai, google-generativeai
# Ensure iverilog, yosys, and sta are on PATH

# 2. Configure API keys
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...
export GOOGLE_API_KEY=...

# 3. Run the full pipeline
python run_pipeline.py --target ethmac --num-trojans 3 --ideation on

# 4. Inspect outputs
ls submission/trojan_{1,2,3}/      # modified RTL + testbench
cat logs/stage0_ideation.json      # parallel proposals + synthesis
cat logs/stage4b_blueteam.json     # GPT-4o review transcripts
cat submission/ppa_report.json     # Yosys + OpenSTA results
```

To re-run only a single stage (e.g., re-harden stealth after a blue-team flag):

```bash
python run_pipeline.py --resume-from stage4b --trojan trojan_2
```

---

## 3. Trojan Catalog

All three Trojans target `ethmac.v` and piggyback on the existing `posedge wb_clk_i` always block. Each adds exactly **one 1-bit sticky flop** (`trojan_armed`) and **one 32-bit equality comparator** against a distinct magic constant written over the Wishbone data bus.

---

### Trojan 1 — `CovertEcho-Leak` (Confidentiality)

| Field | Value |
|---|---|
| **Target file** | `ethmac.v` |
| **Trigger** | `wb_dat_i == 32'hDEADBEEF && wb_we_i && wb_stb_i` on `posedge wb_clk_i` — latches `trojan_armed` sticky until hard reset |
| **Payload** | Overrides Wishbone read data: `assign wb_dat_o = trojan_armed ? ({r_MAC_ADDR1[15:0], r_MAC_ADDR0[31:16]} ^ temp_wb_dat_o_reg) : temp_wb_dat_o_reg;` — every subsequent CSR read XOR-leaks the on-chip MAC address onto the host bus |
| **CVSS 3.1 vector** | `AV:L/AC:L/PR:L/UI:N/S:C/C:H/I:N/A:N` — **Score 7.2** |
| **CVSS justification** | Local Wishbone access required (AV:L); trigger is a single bus write (AC:L); driver-level privilege (PR:L); no user interaction (UI:N); scope changes because on-chip identity state crosses the NIC→host trust boundary (S:C); high confidentiality impact, no integrity/availability effect |
| **Sim** | PASS |
| **Area overhead** | 416 323 µm² vs. golden 416 178 µm² → **+0.035 %** |
| **Timing** | No WNS violation |

---

### Trojan 2 — `FrameFlip` (Integrity)

| Field | Value |
|---|---|
| **Target file** | `ethmac.v` |
| **Trigger** | `wb_dat_i == 32'hCAFEBABE && wb_we_i && wb_stb_i` on `posedge wb_clk_i` — latches `trojan_armed` sticky |
| **Payload** | `assign mtxd_pad_o[0] = trojan_armed ? (mtxd_int[0] ^ mtxen_int) : mtxd_int[0];` — flips the LSB of every transmitted MII nibble while TX_EN is asserted, invalidating the FCS of every outbound frame. Observationally indistinguishable from a marginal-cable integrity fault. |
| **CVSS 3.1 vector** | `AV:L/AC:L/PR:L/UI:N/S:C/C:N/I:H/A:L` — **Score 7.6** |
| **CVSS justification** | Local bus trigger (AV:L, AC:L, PR:L); scope-changed (S:C) because corruption propagates to every downstream network peer beyond the MAC's security authority; integrity high (I:H) as all egress frames are silently corrupted; partial availability loss (A:L) since frames are droppable but link stays up |
| **Sim** | PASS |
| **Area overhead** | 416 323 µm² vs. golden 416 178 µm² → **+0.035 %** |
| **Timing** | No WNS violation |

---

### Trojan 3 — `SilentMute` (Availability)

| Field | Value |
|---|---|
| **Target file** | `ethmac.v` |
| **Trigger** | `wb_dat_i == 32'hBAADF00D && wb_we_i && wb_stb_i` on `posedge wb_clk_i` — latches `trojan_armed` sticky until hard reset |
| **Payload** | `assign mtxen_pad_o = trojan_armed ? 1'b0 : mtxen_int;` — MAC permanently de-asserts TX_EN; the PHY emits nothing while host-visible CSRs, TX FIFO pointers, and TX-done interrupts continue to look healthy. Descriptors appear to complete successfully. |
| **CVSS 3.1 vector** | `AV:L/AC:H/PR:L/UI:N/S:U/C:N/I:N/A:H` — **Score 6.5** |
| **CVSS justification** | Local Wishbone write needed (AV:L); specific 32-bit magic value (AC:H); driver-level privilege (PR:L); no user interaction; scope unchanged at the formal CVSS boundary (S:U); availability high (A:H) — persistent, hard-to-diagnose one-way link death requiring power-on reset to clear |
| **Sim** | PASS |
| **Area overhead** | 416 323 µm² vs. golden 416 178 µm² → **+0.035 %** |
| **Timing** | No WNS violation |

---

### Aggregate PPA

| Metric | Golden | Modified (per Trojan) | Overhead |
|---|---|---|---|
| Cell area (µm²) | 416 177.90 | 416 323.04 | +145.14 µm² (+0.035 %) |
| WNS | 0.00 ns | 0.00 ns | 0 |

The overhead corresponds to exactly one DFF + one 32-bit equality comparator, as specified by the ideation constraint. No pipeline stages, no new clock domains, no new reset nets.

---

## 4. Blue-Team Feedback Loop — Why It Improves Stealth

The Stage 4b adversarial review is a **generative-vs-discriminative loop between two different model families** (Claude Opus as generator, GPT-4o as discriminator). This matters for stealth for three reasons:

1. **Cross-family detection bias.** Claude and GPT-4o were trained by different organizations with different RTL corpora and different code-review priors. A construct that Claude considers stealthy may be obvious to GPT-4o, and vice-versa. Using a foreign discriminator is strictly stronger than self-critique.

2. **Forces removal of LLM "tells."** Generator LLMs leave characteristic fingerprints — signal names like `trojan_armed`,