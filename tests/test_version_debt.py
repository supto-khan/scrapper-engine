"""
Unit tests for Version Debt and CDNJS release history calculations.
"""

from intelligence.technology.version_debt import VersionDebtCalculator, calculate_tech_debt


def test_jquery_legacy_version_debt():
    calc = VersionDebtCalculator(current_year=2026)
    debt = calc.calculate("jquery", "1.8.3")
    assert debt is not None
    assert debt.is_eol is True
    assert debt.major_versions_behind == 2
    assert debt.years_outdated >= 12
    assert debt.cve_risk_level == "critical"
    assert "officially End-of-Life" in debt.summary


def test_jquery_modern_version_debt():
    calc = VersionDebtCalculator(current_year=2026)
    debt = calc.calculate("jquery", "3.7.1")
    assert debt is not None
    assert debt.is_eol is False
    assert debt.major_versions_behind == 0
    assert debt.cve_risk_level == "low"


def test_angularjs_eol_detection():
    calc = VersionDebtCalculator(current_year=2026)
    debt = calc.calculate("angularjs", "1.5.8")
    assert debt is not None
    assert debt.is_eol is True
    assert debt.cve_risk_level == "critical"


def test_bootstrap_legacy_debt():
    calc = VersionDebtCalculator(current_year=2026)
    debt = calc.calculate("bootstrap", "3.3.7")
    assert debt is not None
    assert debt.is_eol is True
    assert debt.major_versions_behind == 2


def test_wordpress_version_debt():
    calc = VersionDebtCalculator(current_year=2026)
    debt = calc.calculate("wordpress", "5.4.1")
    assert debt is not None
    assert debt.is_eol is True
    assert debt.major_versions_behind == 1


def test_calculate_tech_debt_helper():
    debt_dict = calculate_tech_debt("jquery", "1.11.1")
    assert isinstance(debt_dict, dict)
    assert debt_dict["library_name"] == "jquery"
    assert debt_dict["detected_version"] == "1.11.1"
