"""Tests for fragile helper functions in orchestrator.py."""

import os
# Avoid importing orchestrator side-effects (it instantiates anthropic.Anthropic
# at module load). Stub the env var; the client still creates but won't be used.
os.environ.setdefault("ANTHROPIC_API_KEY", "stub-for-import")

import orchestrator as orch


def test_check_rtl_budget_clean_passes():
    rtl = ("reg foo;\nwire bar;\n"
           "always @(posedge clk) foo <= 1'b1;\n"
           "assign bar = foo;\n")
    ok, why = orch.check_rtl_budget(rtl, rtl)
    assert ok, why


def test_check_rtl_budget_rejects_extra_regs():
    g = "reg a;\n"
    c = "reg a;\nreg b;\nreg c;\nreg d;\n"  # +3 regs
    ok, _ = orch.check_rtl_budget(g, c)
    assert not ok


def test_check_rtl_budget_rejects_wide_compare():
    g = "assign x = y;\n"
    c = "assign x = y;\nassign z = a[256:0] == 1'b0;\n"
    ok, why = orch.check_rtl_budget(g, c)
    assert not ok and "comparator" in why


def test_check_rtl_budget_rejects_new_always_block():
    g = "always @(posedge clk) x <= 0;\n"
    c = "always @(posedge clk) x <= 0;\nalways @(posedge clk) y <= 1;\n"
    ok, why = orch.check_rtl_budget(g, c)
    assert not ok


def test_check_rtl_budget_rejects_removing_critical_logic():
    """Removing temp_wb_dat_o_reg <= ... should be caught."""
    g = "temp_wb_dat_o_reg <= temp_wb_dat_o;\n"
    c = "// removed\n"
    ok, why = orch.check_rtl_budget(g, c)
    assert not ok


def test_extract_json_simple():
    obj = orch._extract_json('text {"a":1,"b":2} more text', required_keys=("a",))
    assert obj == {"a": 1, "b": 2}


def test_extract_json_handles_braces_in_strings():
    obj = orch._extract_json('{"text":"this has } a brace","ok":true}',
                             required_keys=("text",))
    assert obj["text"] == "this has } a brace"


def test_extract_json_returns_none_when_keys_missing():
    obj = orch._extract_json('{"a":1}', required_keys=("b",))
    assert obj is None


def test_extract_json_returns_none_for_empty():
    assert orch._extract_json("", required_keys=("a",)) is None
    assert orch._extract_json("nothing here", required_keys=("a",)) is None


def test_extract_patch_json_requires_three_fields():
    valid = '{"reset_line":"a","trigger_line":"b","assign_line":"c"}'
    assert orch._extract_patch_json(valid) is not None
    invalid = '{"reset_line":"a","trigger_line":"b"}'
    assert orch._extract_patch_json(invalid) is None


def test_clean_verilog_strips_default_nettype():
    src = "`default_nettype none\nmodule foo;\nendmodule\n"
    out = orch.clean_verilog(src)
    assert "default_nettype" not in out


def test_clean_verilog_preserves_module_body():
    src = "module foo;\n  reg x;\nendmodule\n"
    out = orch.clean_verilog(src)
    assert "module foo" in out and "reg x" in out


def test_extract_block_finds_tagged():
    text = "blah\n```verilog\nmodule x; endmodule\n```\nblah"
    assert "module x" in orch.extract_block(text, "verilog")


def test_extract_block_falls_back_to_first_unmatched():
    text = "intro\n```python\ncode\n```\nbye"
    out = orch.extract_block(text, "verilog")
    assert out == "code"
