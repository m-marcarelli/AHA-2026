# Waveform Inspection Guide

Each Trojan testbench dumps a VCD when run. The matching `.gtkw` save
file restores a curated signal layout — clocks, reset, the trigger
surface (Wishbone), trojan internal state, and the MII TX side that
each payload affects.

## Generate the VCD

```bash
cd marissa/pipeline
iverilog -g2012 -I ../ethmac/rtl/verilog \
  -o /tmp/sim.out \
  ../../phase-1-submission/Trojan_1/tb/tb_trojan_1.v \
  ../ethmac/rtl/verilog/*.v
vvp /tmp/sim.out                # produces tb_trojan_1.vcd in the cwd
```

## View the waveform

```bash
gtkwave tb_trojan_1.vcd ../../phase-1-submission/Trojan_1/tb/tb_trojan_1.gtkw
```

## What to look for

| Trojan | Pre-trigger waveform | Post-trigger waveform |
|--------|----------------------|------------------------|
| 1 — LeakBeef     | `wb_dat_o` returns the configured CSR value on read | After the magic write, `dut.trojan_armed` goes high; subsequent `wb_dat_o` reads return manipulated data |
| 2 — FrameFlipBabe| `mtxd_pad_o` toggles cleanly while `mtxen_pad_o` is high | After arm, the LSB of `mtxd_pad_o` is XORed during every `mtxen_pad_o`-asserted nibble |
| 3 — SilentF00D   | `mtxen_pad_o` rises during frame TX | After arm, `mtxen_pad_o` stays low forever; `int_o` and CSRs continue to report nominal (the silent DoS) |

## Marker strings

`vvp` stdout emits three markers used by the regression gate:

  * `NORMAL_OP_PASS`     — the configured CSR write/read survived
  * `TROJAN_TRIGGERED`   — the magic write fired the arm latch
  * `TEST_COMPLETE`      — testbench reached `$finish`

A passing run emits all three in order. The full functional regression
of the OpenCores upstream `tb_ethernet.v` is run separately by the
`regression` gate and is the authoritative correctness check.
