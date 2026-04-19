# Archetype A — Magic Packet Activation

## Design goals
- **CVSS target:** 8.5 – 9.8 (Network AV, Low PR, High CIA impact)
- **Trigger class:** rarely activated — bit-level signature in received frame header.
- **Payload class:** privileged state change (disables RX address filter → promiscuous mode).
- **Insertion site (preferred):** `eth_rxaddrcheck.v` or the RX-side of `ethmac.v`.
- **PPA budget (per-Trojan):** ≤ 1 % area (+ 4 000 area units), ≤ 1 % cells (+ 400), no FF increase > ~40.
- **Testbench expectation:** must demonstrate:
  1. Normal RX packet path filters unicast traffic against the programmed MAC.
  2. A crafted packet with the trigger signature → MAC starts accepting all addresses.

## Why this archetype wins dynamic CTF points
The trigger is a 48- or 64-bit literal pattern embedded inside the destination
MAC / length bytes — zero extra storage, triggered by data already on the
Ethernet bus. Blue-team detectors that scan for suspicious constants may flag
it unless the constant is split across two always blocks in different files.
Keep the constant **split** across the two RX files so no single file
contains the whole signature.

## Hard constraints (LLM MUST respect)
1. Do NOT add new module ports on `ethmac`. The top-level interface must match
   the upstream exactly — any change invalidates the competition's synthesis
   script.
2. Do NOT modify `ethmac_defines.v` macros that affect the port list
   (e.g. `ETH_WISHBONE_B3`, `ETH_FIFO_XILINX`).
3. The inserted logic must be combinational or clocked by an **existing** clock
   domain (`wb_clk_i`, `mrx_clk_pad_i`, `mtx_clk_pad_i`). Do NOT create a new
   clock or reset.
4. The FULL upstream testbench `bench/verilog/tb_ethernet.v` MUST continue to
   report 0 failures. No normal-traffic regression allowed.
5. The trigger pattern MUST NOT appear in any legal Ethernet frame normally
   exercised by the test suite — i.e. avoid all-zero, all-one, or the
   canonical test MACs used in `tb_ethernet.v`.

## Suggested plant technique
- Add a 16-bit *linear feedback* comparator on the last two bytes of
  `MRxD_buf` stream. When two consecutive 32-bit windows match the constant
  pair, assert a latched `promisc_override` signal. OR it into the address
  accept signal.
- The comparator uses 2 × 32-bit registers → ~8 – 12 cells of area, well
  under budget.

## Output contract
The generator MUST return a JSON object matching the shared schema in
`pipeline/schemas/trojan_spec.json`. In particular, each `patch` entry must
include `{file, anchor_line_range:[start,end], replacement, explanation}`.
