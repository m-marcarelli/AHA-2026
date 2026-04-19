# Archetype C — Counter Time-Bomb (structural / dormant)

## Design goals
- **CVSS target:** 7.0 – 8.0 (Network AV, High complexity, High Availability impact).
- **Trigger class:** dormant counter overflow — fires after N packets where N
  is implausibly large for normal testing but trivially reachable in deployment.
- **Payload class:** availability — after trigger, the TX state machine
  silently drops 1 in every K subsequent packets, creating a slow-ramp DoS
  that looks like link degradation.
- **Insertion site:** `eth_txstatem.v` or `eth_txcounters.v`. The counter
  can piggyback on existing packet-count registers to avoid adding new flops.
- **PPA budget:** ≤ 0.3 % area, no new flop widths > 24 bits.

## Why this archetype is rare-find
- No packet content triggers it — blue-team fuzz testing will never hit it.
- The counter walks only during *real* traffic; a short simulation regression
  won't accumulate enough packets.
- The drop is probabilistic after trigger — one-shot detection is noisy.

## Hard constraints (LLM MUST respect)
1. Counter width MUST be ≤ 24 bits to stay within the FF budget.
2. Do NOT inhibit the TX FSM during reset assertion — the counter must hold
   at 0 while `wb_rst_i` is asserted so upstream reset tests still pass.
3. The dropped-packet signal MUST fold into an *existing* TX-enable gating
   path — do not add a new `mtxen_pad_o` driver.
4. The exploit testbench must force the counter to the trigger threshold via
   backdoor register write (expose a `force_counter` path that is tied to a
   reserved MIIM address *only during simulation* using a
   `synthesis_translate_off`-style construct — NO, wait, that's synth-visible.
   Instead, do NOT expose backdoor; the exploit TB should drive a simulation
   primitive to set the internal register hierarchically.)

## Suggested plant technique
- Hook into `packet_transmited` pulse in `eth_txstatem.v`. Add a 22-bit
  counter `tb_ctr`. When `tb_ctr == 22'h3FFFFE` assert `armed`. While armed,
  every 3rd `packet_transmited` pulse, override `MTxEn_local` for 1 cycle
  (drops the frame's SFD).
- Area: one 22-bit reg (~22 FF) + a 4-input compare = ~30 cells total.

## Output contract
Match `pipeline/schemas/trojan_spec.json`.
