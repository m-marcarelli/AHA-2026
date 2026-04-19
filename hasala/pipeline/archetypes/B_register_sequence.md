# Archetype B — Register-Sequence Unlock (stealth / side-channel)

## Design goals
- **CVSS target:** 7.0 – 8.2 (Local PR, Low AV complexity, High Integrity impact).
- **Trigger class:** sequence of MIIM register writes to reserved PHY
  addresses — looks like legitimate debug traffic, no suspicious constants.
- **Payload class:** integrity compromise — inverts one bit in the TX FCS
  (CRC) output whenever the MAC transmits with a specific source MAC byte set,
  causing selective packet corruption that the victim can't diagnose.
- **Insertion site:** `eth_miim.v` (unlock FSM) + `eth_txethmac.v` (FCS
  corruption). Splitting across two files is deliberate — static detectors
  that audit one file at a time won't see the linkage.
- **PPA budget:** ≤ 0.5 % area total, ≤ 0.3 % cells.

## Why this archetype is hard to detect
- No magic constants — the trigger is a *sequence* of values in a temporal
  order. Static analysis won't catch it; only dynamic replay of the right
  write ordering exposes it.
- Payload is a single-bit XOR, statistically indistinguishable from a
  transmit channel error at low rates.
- The unlock FSM dies silently on wrong-order writes — no persistent state
  footprint.

## Hard constraints (LLM MUST respect)
1. The unlock FSM MUST be a 2-bit state register (4 states max). No more.
2. Do NOT alter `eth_miim`'s external interface. The MDIO protocol must still
   look correct on the wire during regression.
3. When the payload is NOT armed, the TX FCS output MUST equal the golden
   FCS. Any always-armed XOR disqualifies the design.
4. Use only existing clock domains (`wb_clk`, `mtx_clk_pad_i`).
5. Document the unlock sequence exactly in the generated `README.md` so the
   exploit testbench can reproduce it bit-for-bit.

## Suggested plant technique
- Unlock FSM: watches MIIM writes to PHY address `5'h1E` (reserved). On a
  write sequence `DEAD → BEEF → CAFE` in three consecutive transactions,
  assert `armed` latch.
- Payload: in `eth_txethmac`, XOR bit[0] of the outgoing FCS with `armed`
  AND ( `MAC_src_byte[3] == 8'hA5` ).

## Output contract
Match `pipeline/schemas/trojan_spec.json`.
