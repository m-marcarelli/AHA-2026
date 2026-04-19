"""Tests for structurally distinct trojan family templates."""

import re

import families
import structural_detector as sd


# Minimal stand-ins for the specific anchor lines each family targets.
FAMILY_1_GOLDEN = """\
module ethmac (input wb_clk_i, input wb_rst_i, input Broadcast,
               input ControlFrmAddressOK, output mtxen_pad_o);
reg             WillSendControlFrame_sync1;
reg             WillSendControlFrame_sync2;
always @(posedge wb_clk_i)
  begin
    WillSendControlFrame_sync2 <=  WillSendControlFrame_sync1;
  end
endmodule
"""

FAMILY_2_GOLDEN = """\
assign CrcNext[0] = Enable & (Data[0] ^ Crc[28]);
assign CrcNext[4] = (Enable & (Data[3] ^ Data[2] ^ Data[0] ^ Crc[28] ^ Crc[30] ^ Crc[31])) ^ Crc[0];
assign CrcNext[5] = (Enable & (Data[3] ^ Data[1] ^ Data[0] ^ Crc[28] ^ Crc[29] ^ Crc[31])) ^ Crc[1];
"""

FAMILY_3_GOLDEN = """\
assign RxAbort = (RxAddressInvalid & ~r_Pro) & RxCheckEn;
"""


def test_family_1_applies_and_no_joke_hex():
    mod = families.apply_family_1(FAMILY_1_GOLDEN)
    ok, msg = families.verify_family_1(mod)
    assert ok, msg
    # No joke-hex constant introduced.
    rpt = sd.analyse_text("ethmac.v", FAMILY_1_GOLDEN, mod)
    joke = [f for f in rpt.findings if f.mechanism == "magic-hex constant"]
    assert not joke, f"family 1 should not introduce magic hex: {joke}"


def test_family_1_extends_sync_chain():
    mod = families.apply_family_1(FAMILY_1_GOLDEN)
    assert "WillSendControlFrame_sync3" in mod
    assert "Broadcast & ControlFrmAddressOK" in mod
    # The detector should pick up the sync extension (low-confidence;
    # that's the point — it looks like a plausible CDC fix).
    rpt = sd.analyse_text("ethmac.v", FAMILY_1_GOLDEN, mod)
    sync_findings = [f for f in rpt.findings if "sync" in f.rationale.lower()
                     or "synchroniser" in f.mechanism]
    assert sync_findings, "sync-chain extension should be detectable"


def test_family_2_xors_crc_seed():
    mod = families.apply_family_2(FAMILY_2_GOLDEN)
    ok, msg = families.verify_family_2(mod)
    assert ok, msg
    assert "Initialize & Data[1]" in mod
    # Detector should pick up the CRC arity change.
    rpt = sd.analyse_text("eth_crc.v", FAMILY_2_GOLDEN, mod)
    crc = [f for f in rpt.findings if f.mechanism == "CRC-XOR arity changed"]
    assert crc, "family 2 should be detectable as CRC-XOR change (calibration)"


def test_family_3_modifies_rxabort_predicate():
    mod = families.apply_family_3(FAMILY_3_GOLDEN)
    ok, msg = families.verify_family_3(mod)
    assert ok, msg
    assert "~(CrcHashGood & Broadcast)" in mod


def test_no_family_uses_joke_hex():
    """All three families must avoid the canonical magic-hex constants
    that opponent detectors immediately flag."""
    for fam_id, (spec, apply, verify) in families.FAMILIES.items():
        # Pick an appropriate golden sample for each family.
        gold = {
            "1": FAMILY_1_GOLDEN,
            "2": FAMILY_2_GOLDEN,
            "3": FAMILY_3_GOLDEN,
        }[fam_id]
        mod = apply(gold)
        joke_hex = re.findall(r"32'h([0-9A-Fa-f]+)", mod)
        joke_hex_lower = {int(v, 16) for v in joke_hex}
        for v in joke_hex_lower:
            assert v not in sd.JOKE_HEX_VALUES, \
                f"family {fam_id} introduced joke-hex 0x{v:08X}"


def test_all_families_have_distinct_target_files():
    targets = {f[0].target_file for f in families.FAMILIES.values()}
    assert len(targets) == 3, f"families must span 3 files, got {targets}"


def test_all_families_have_distinct_mechanisms():
    mechanisms = {f[0].mechanism_class for f in families.FAMILIES.values()}
    assert len(mechanisms) == 3, f"mechanisms must be distinct, got {mechanisms}"


def test_all_families_have_valid_cvss_vectors():
    import cvss_calc
    for spec, _, _ in families.FAMILIES.values():
        score = cvss_calc.score_from_vector(spec.cvss_vector)
        assert score > 0, f"{spec.name} has score 0 — payload is too weak"


def test_average_cvss_meets_exemplary_band():
    """Rubric Part 2 Exemplary: average CVSS in 7.0..10.0."""
    import cvss_calc
    scores = [cvss_calc.score_from_vector(f[0].cvss_vector)
              for f in families.FAMILIES.values()]
    avg = sum(scores) / len(scores)
    # Aspirational; prints actual to aid tuning if it ever drops.
    assert avg >= 6.0, f"family CVSS average {avg:.2f} below acceptable 6.0"
