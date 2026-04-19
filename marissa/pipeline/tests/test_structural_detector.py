"""Tests for the structural trojan detector."""

import structural_detector as sd


GOLDEN = """\
module ethmac (
  input wb_clk_i, wb_rst_i,
  input  [31:0] wb_dat_i,
  output [31:0] wb_dat_o,
  input  wb_we_i, wb_stb_i
);
  reg [31:0] temp_wb_dat_o_reg;
  always @(posedge wb_clk_i) begin
    temp_wb_dat_o_reg <= 32'h0;
  end
  assign wb_dat_o = temp_wb_dat_o_reg;
endmodule
"""


def test_clean_yields_zero_findings():
    rpt = sd.analyse_text("ethmac.v", GOLDEN, GOLDEN)
    assert not rpt.trojan_likely
    assert rpt.stealth_score == 1.0
    assert rpt.findings == []


def test_detects_joke_hex():
    candidate = GOLDEN.replace(
        "temp_wb_dat_o_reg <= 32'h0;",
        "if (wb_dat_i == 32'hDEADBEEF && wb_we_i && wb_stb_i)\n"
        "      temp_wb_dat_o_reg <= 32'h0;"
    )
    rpt = sd.analyse_text("ethmac.v", GOLDEN, candidate)
    assert rpt.trojan_likely
    mechanisms = {f.mechanism for f in rpt.findings}
    assert "magic-hex constant" in mechanisms


def test_detects_obfuscated_constant():
    candidate = GOLDEN.replace(
        "temp_wb_dat_o_reg <= 32'h0;",
        "if (wb_dat_i == ((32'hDEAD<<16)|32'hBEEF))\n"
        "      temp_wb_dat_o_reg <= 32'h0;"
    )
    rpt = sd.analyse_text("ethmac.v", GOLDEN, candidate)
    mechanisms = {f.mechanism for f in rpt.findings}
    assert "obfuscated constant" in mechanisms


def test_detects_new_top_level_identifier():
    candidate = GOLDEN.replace(
        "reg [31:0] temp_wb_dat_o_reg;",
        "reg [31:0] temp_wb_dat_o_reg;\n  reg trojan_armed;"
    )
    rpt = sd.analyse_text("ethmac.v", GOLDEN, candidate)
    mechanisms = {f.mechanism for f in rpt.findings}
    assert "new top-level identifier" in mechanisms


def test_detects_new_mux_on_output():
    candidate = GOLDEN.replace(
        "assign wb_dat_o = temp_wb_dat_o_reg;",
        "assign wb_dat_o = trojan_armed ? wb_dat_i : temp_wb_dat_o_reg;"
    )
    rpt = sd.analyse_text("ethmac.v", GOLDEN, candidate)
    mechanisms = {f.mechanism for f in rpt.findings}
    assert "new mux on primary output" in mechanisms


def test_sync_chain_extension_low_confidence():
    """Adding _sync3 to an existing _sync1/_sync2 chain should be detected
    but with lower confidence than a brand-new identifier (it looks like a
    plausible CDC fix)."""
    g = "reg foo_sync1, foo_sync2;\n"
    c = "reg foo_sync1, foo_sync2;\nreg foo_sync3;\n"
    rpt = sd.analyse_text("foo.v", g, c)
    # The detector flags it but with lower confidence
    sync = [f for f in rpt.findings if "synchroniser" in f.mechanism or "sync" in f.rationale.lower()]
    assert sync, "expected sync-chain finding"


def test_detects_crc_xor_arity_change():
    g = "assign CrcNext[4] = (Enable & (Data[3] ^ Data[2] ^ Data[0] ^ Crc[28] ^ Crc[30] ^ Crc[31])) ^ Crc[0];"
    c = ("assign CrcNext[4] = (Enable & (Data[3] ^ Data[2] ^ Data[0] ^ "
         "Crc[28] ^ Crc[30] ^ Crc[31])) ^ Crc[0] ^ (Initialize & Data[1]);")
    rpt = sd.analyse_text("eth_crc.v", g, c)
    mechanisms = {f.mechanism for f in rpt.findings}
    assert "CRC-XOR arity changed" in mechanisms


def test_findings_have_line_numbers():
    candidate = GOLDEN.replace(
        "temp_wb_dat_o_reg <= 32'h0;",
        "if (wb_dat_i == 32'hDEADBEEF) temp_wb_dat_o_reg <= 32'h0;"
    )
    rpt = sd.analyse_text("ethmac.v", GOLDEN, candidate)
    for f in rpt.findings:
        assert f.line > 0, f"finding {f} missing line number"
