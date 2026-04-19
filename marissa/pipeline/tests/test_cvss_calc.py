"""Validate the deterministic CVSS calculator against NVD-published values."""

import pytest
import cvss_calc


# Reference vectors with NVD-verified base scores.
NVD_REFERENCES = [
    # (vector, expected_score)
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H", 9.8),  # Heartbleed-class
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H", 10.0),
    ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:C/C:H/I:N/A:N", 6.5),
    ("CVSS:3.1/AV:L/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:H", 5.5),
    ("CVSS:3.1/AV:P/AC:L/PR:N/UI:N/S:U/C:N/I:H/A:N", 4.6),
    ("CVSS:3.1/AV:N/AC:H/PR:N/UI:R/S:U/C:L/I:L/A:N", 4.2),
    ("CVSS:3.1/AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H", 8.8),
    ("CVSS:3.1/AV:N/AC:L/PR:N/UI:R/S:C/C:L/I:L/A:N", 6.1),
    ("CVSS:3.1/AV:A/AC:L/PR:L/UI:N/S:U/C:N/I:N/A:N", 0.0),
]


@pytest.mark.parametrize("vector,expected", NVD_REFERENCES)
def test_score_matches_nvd(vector, expected):
    got = cvss_calc.score_from_vector(vector)
    assert abs(got - expected) < 0.05, f"{vector}: got {got}, expected {expected}"


def test_severity_bands():
    assert cvss_calc.severity(0.0) == "None"
    assert cvss_calc.severity(3.9) == "Low"
    assert cvss_calc.severity(4.0) == "Medium"
    assert cvss_calc.severity(6.9) == "Medium"
    assert cvss_calc.severity(7.0) == "High"
    assert cvss_calc.severity(8.9) == "High"
    assert cvss_calc.severity(9.0) == "Critical"
    assert cvss_calc.severity(10.0) == "Critical"


def test_invalid_vector_raises():
    with pytest.raises(ValueError):
        cvss_calc.score_from_vector("CVSS:3.1/AV:Z/AC:L/PR:N/UI:N/S:U/C:N/I:N/A:N")
    with pytest.raises(ValueError):
        cvss_calc.score_from_vector("not a vector")


def test_score_from_metrics_pr_table_changes_with_scope():
    # PR:L weights differently when S=C vs S=U.
    s_u = cvss_calc.score_from_metrics(
        AV="N", AC="L", PR="L", UI="N", S="U", C="H", I="N", A="N")
    s_c = cvss_calc.score_from_metrics(
        AV="N", AC="L", PR="L", UI="N", S="C", C="H", I="N", A="N")
    assert s_c > s_u, "Scope:Changed must score higher than Unchanged"


def test_zero_impact_yields_zero():
    s = cvss_calc.score_from_metrics(
        AV="N", AC="L", PR="N", UI="N", S="U", C="N", I="N", A="N")
    assert s == 0.0
