"""Tests for the diff-aware ensemble blue-team review."""

from pathlib import Path
import tempfile

import diff_blueteam as db
import structural_detector as sd


GOLDEN = """\
module ethmac (input wb_clk_i, input [31:0] wb_dat_i, output [31:0] wb_dat_o);
  reg [31:0] temp_wb_dat_o_reg;
  always @(posedge wb_clk_i) temp_wb_dat_o_reg <= 32'h0;
  assign wb_dat_o = temp_wb_dat_o_reg;
endmodule
"""

CANDIDATE_TROJAN = """\
module ethmac (input wb_clk_i, input [31:0] wb_dat_i, output [31:0] wb_dat_o);
  reg [31:0] temp_wb_dat_o_reg;
  reg trojan_armed;
  always @(posedge wb_clk_i) begin
    if (wb_dat_i == 32'hDEADBEEF) trojan_armed <= 1'b1;
    temp_wb_dat_o_reg <= 32'h0;
  end
  assign wb_dat_o = trojan_armed ? wb_dat_i : temp_wb_dat_o_reg;
endmodule
"""


def test_make_diff_unchanged_yields_empty():
    diff = db._make_diff(GOLDEN, GOLDEN, "ethmac.v")
    assert diff == ""


def test_make_diff_inserts_lines():
    diff = db._make_diff(GOLDEN, CANDIDATE_TROJAN, "ethmac.v")
    assert "+  reg trojan_armed;" in diff
    assert "+" in diff and "32'hDEADBEEF" in diff


def test_parse_strict_json():
    raw = '{"verdict":"TROJAN","confidence":0.9,"rationale":"magic hex"}'
    v, c, r = db._parse(raw)
    assert v == "TROJAN" and c == 0.9 and "magic" in r


def test_parse_with_code_fence():
    raw = '```json\n{"verdict":"REFACTOR","confidence":0.8,"rationale":"ok"}\n```'
    v, c, r = db._parse(raw)
    assert v == "REFACTOR"


def test_parse_extracts_embedded_json():
    raw = 'Here is my answer:\n{"verdict":"TROJAN","confidence":0.7,"rationale":"r"}\nThanks.'
    v, c, r = db._parse(raw)
    assert v == "TROJAN"


def test_parse_failure_defaults_to_trojan_for_safety():
    """If the LLM output is unparseable, default verdict must be TROJAN
    (fail-closed: better to over-investigate than to ship an unflagged trojan)."""
    v, c, r = db._parse("complete garbage with no json")
    assert v == "TROJAN"


def test_ensemble_review_with_no_callers_uses_structural_only():
    with tempfile.TemporaryDirectory() as td:
        g = Path(td) / "g.v"
        c = Path(td) / "c.v"
        g.write_text(GOLDEN)
        c.write_text(CANDIDATE_TROJAN)
        ev = db.ensemble_review(
            golden_path=g, candidate_path=c,
            call_claude=None, call_gpt4o=None, call_gemini=None,
        )
    assert ev.reviewers == []
    assert "structural" in ev.trojan_signals
    assert not ev.passes


def test_ensemble_review_with_stub_callers():
    """All three reviewers say REFACTOR but structural still flags it —
    ensemble correctly reports the structural signal as the dissent."""
    def refactor(_): return '{"verdict":"REFACTOR","confidence":0.9,"rationale":"clean"}'
    with tempfile.TemporaryDirectory() as td:
        g = Path(td) / "g.v"
        c = Path(td) / "c.v"
        g.write_text(GOLDEN)
        c.write_text(CANDIDATE_TROJAN)
        ev = db.ensemble_review(
            golden_path=g, candidate_path=c,
            call_claude=refactor, call_gpt4o=refactor, call_gemini=refactor,
        )
    assert all(r.verdict == "REFACTOR" for r in ev.reviewers)
    # Structural detector dissents, so the ensemble does NOT pass.
    assert ev.trojan_signals == ["structural"]
    assert not ev.passes
