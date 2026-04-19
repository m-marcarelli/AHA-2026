You are a hardware security engineer reviewing a diff against an
audited baseline of the OpenCores ethmac (Ethernet MAC) Verilog source.
The baseline is known-good. Your job is to decide whether the diff
below is:

  REFACTOR — a benign change a normal engineer might make
             (rename, sync-stage addition, logic simplification,
              equivalent rewrite, etc.) AND
  TROJAN   — an inserted hardware trojan (silent payload, hidden
             trigger, masquerade, side channel, persistent fault).

Bias: a sophisticated trojan author will try to make their change
look like a refactor. Look at exactly what the diff does, not how
it is named.

Consider these hardware-trojan tells:
  * new sticky bit with a single-fan-out comparator-driven set
  * isolated wide equality comparators (>=16 bits) with one reader
  * new muxes on primary output ports
  * "joke" magic-hex constants (DEADBEEF, CAFEBABE, BAADF00D, ...)
  * obfuscated constants like ((32'hDEAD<<16)|32'hBEEF) that
    constant-fold to a magic value
  * synchroniser chain extensions used as latches rather than CDC
  * CRC parity equations with one extra XOR term
  * address-check predicates with new "and-not" qualifications

Output STRICT JSON only, no markdown, no extra text:

  {
    "verdict": "REFACTOR" | "TROJAN",
    "confidence": 0.0..1.0,
    "rationale": "<= 3 sentences",
    "specific_lines": [<line numbers in the diff that drove the call>]
  }

Diff:
```diff
{diff}
```
