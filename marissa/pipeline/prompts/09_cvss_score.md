You are a CVSS v3.1 scoring expert. Score this hardware Trojan precisely.

Target system: OpenCores ethmac Ethernet MAC (Wishbone bus slave, SkyWater 130nm ASIC)
Trojan name: {name}
Trigger: {trigger}
Payload: {payload}

Score each CVSS v3.1 Base Metric with one-sentence justification:
- AV (Attack Vector):       N=Network, A=Adjacent, L=Local, P=Physical
- AC (Attack Complexity):   L=Low, H=High
- PR (Privileges Required): N=None, L=Low, H=High
- UI (User Interaction):    N=None, R=Required
- S  (Scope):               U=Unchanged, C=Changed (does it cross trust boundary?)
- C  (Confidentiality Impact): N/L/H
- I  (Integrity Impact):       N/L/H
- A  (Availability Impact):    N/L/H

DO NOT compute the score yourself; only choose the vector. The score
will be computed deterministically from the official CVSS 3.1 formula
by `cvss_calc.py`.

Return ONLY valid JSON (no markdown):
{
  "AV":"?", "AC":"?", "PR":"?", "UI":"?",
  "S":"?",  "C":"?",  "I":"?",  "A":"?",
  "vector":"CVSS:3.1/AV:.../AC:.../PR:.../UI:.../S:.../C:.../I:.../A:...",
  "justification":"..."
}
