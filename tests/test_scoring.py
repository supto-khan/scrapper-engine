from scoring.buying_score import BuyingSignalScorer
from scoring.fit_score import CompanyFitScorer
from scoring.opportunity_score import OpportunityScorer
from scoring.pain_score import PainAndTechGapScorer


def test_fit_scorer():
    fit_scorer = CompanyFitScorer()
    company = {
        "name": "Acme Retail Co",
        "industry": "E-Commerce & DTC Retail",
        "employee_count_estimate": "50 - 249",
        "source": "clutch",
    }
    score = fit_scorer.score(company)
    assert score >= 90.0  # Perfect fit for commercial end-client targeting


def test_pain_and_tech_gap_scorer():
    scorer = PainAndTechGapScorer()
    tech = {
        "cms": "WordPress 5.2",
        "frontend_stack": ["jQuery 1.12.4"],
        "https": False,
        "hsts": False,
        "ttfb_ms": 1200,
        "evidence": {
            "wordpress": {"version": "5.2"},
            "jquery": {"version": "1.12.4"},
        },
    }
    gap_score = scorer.compute_technology_gap(tech)
    assert gap_score >= 80.0  # Heavy legacy debt

    pains = [
        {"type": "outdated_wordpress", "severity": "high"},
        {"type": "legacy_jquery", "severity": "high"},
        {"type": "insecure_transport_http", "severity": "critical"},
    ]
    pain_score = scorer.compute_pain_signal(pains)
    assert pain_score >= 85.0


def test_buying_signal_scorer():
    buying_scorer = BuyingSignalScorer()
    signals = [
        {
            "type": "hiring_skill_match",
            "detail": {"matched_skills": [{"skill": "laravel"}]},
        },
        {"type": "hiring_ats_detected", "detail": {"ats": "greenhouse"}},
    ]
    score = buying_scorer.score(signals)
    assert score >= 55.0


def test_composite_opportunity_scorer():
    scorer = OpportunityScorer()
    company = {
        "domain": "target-retail.com",
        "website_url": "https://target-retail.com",
        "industry": "E-Commerce & Consumer Retail",
        "employee_count_estimate": "50 - 249",
        "source": "clutch",
    }
    tech = {
        "cms": "WordPress 5.0",
        "frontend_stack": ["jQuery 1.11.0"],
        "https": True,
        "hsts": False,
        "evidence": {"wordpress": {"version": "5.0"}, "jquery": {"version": "1.11.0"}},
    }
    signals = [
        {
            "type": "hiring_skill_match",
            "detail": {"matched_skills": [{"skill": "laravel"}]},
        },
        {"type": "career_page_detected"},
    ]
    pains = [
        {"type": "outdated_wordpress", "severity": "high"},
        {"type": "legacy_jquery", "severity": "high"},
    ]
    opportunities = [
        {
            "type": "cms_to_laravel_migration",
            "recommended_service": "WordPress to Custom Laravel Migration",
            "estimated_value_low": 20000,
            "estimated_value_high": 60000,
        }
    ]

    breakdown = scorer.calculate_score(
        company_data=company,
        tech_fingerprint=tech,
        audit_metrics=None,
        signals=signals,
        pains=pains,
        opportunities=opportunities,
    )

    assert breakdown["opportunity_score"] >= 75.0
    assert breakdown["priority_tier"] in ["immediate", "high"]
    assert breakdown["total_deal_range"] == [20000, 60000]
    assert breakdown["data_completeness"] >= 0.50
    assert breakdown["staleness_factor"] == 1.0


def test_staleness_decay_and_recrawl_flag():
    scorer = OpportunityScorer()
    from datetime import datetime, timedelta
    
    # 20 days old -> -12% decay (factor = 0.88)
    twenty_days_ago = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S")
    factor, needs_recrawl = scorer.compute_staleness_factor(twenty_days_ago)
    assert factor < 1.0
    assert factor == 0.88
    assert needs_recrawl is False

    # 35 days old -> 0.70 factor, needs_recrawl = True
    thirty_five_days_ago = (datetime.now() - timedelta(days=35)).strftime("%Y-%m-%d %H:%M:%S")
    factor_old, needs_recrawl_old = scorer.compute_staleness_factor(thirty_five_days_ago)
    assert factor_old == 0.70
    assert needs_recrawl_old is True


def test_data_completeness_flagging():
    scorer = OpportunityScorer()
    # Empty tech / no audit -> low completeness
    completeness = scorer.compute_data_completeness(None, None, [])
    assert completeness == 0.0

    # Partial tech
    completeness_partial = scorer.compute_data_completeness(
        tech_fingerprint={"evidence": {"wordpress": {"version": "5.0"}}},
        audit_metrics={"ttfb_ms": 900},
        signals=[],
    )
    assert completeness_partial >= 0.80


def test_buying_scorer_detail_none_fallback_and_cap():
    scorer = BuyingSignalScorer()
    
    # 1. Test detail: None crash bug fix
    signals_none = [
        {"type": "hiring_skill_match", "detail": None, "confidence": 1.0},
        {"type": "client_industry_tag", "detail": None, "confidence": 1.0},  # Should NOT trigger past spend
    ]
    score, breakdown = scorer.score_with_breakdown(signals_none)
    assert score == 25.0  # Base score, client_industry_tag ignored
    assert len(breakdown) == 1

    # 2. Test 4+ matching skills cap at 40.0
    signals_heavy_skills = [
        {
            "type": "hiring_skill_match",
            "detail": {
                "matched_skills": [
                    {"skill": "laravel"},     # +30
                    {"skill": "next.js"},     # +30
                    {"skill": "react"},       # +25
                    {"skill": "shopify"},     # +25
                ]
            },
            "confidence": 1.0,
        }
    ]
    score_cap, breakdown_cap = scorer.score_with_breakdown(signals_heavy_skills)
    assert score_cap == 65.0  # 25 base + 40 max cap (uncapped would have been 25 + 110 = 135)


def test_fit_scorer_numeric_bounds_edge_cases():
    scorer = CompanyFitScorer()
    
    # 500-999 must NOT trigger the "50" sweet spot
    company_enterprise = {
        "industry": "Retail & E-Commerce",
        "employee_count_estimate": "500 - 999",
    }
    score, breakdown = scorer.score_with_breakdown(company_enterprise)
    # 25 (base) + 35 (industry) + 10 (enterprise) = 70.0
    assert score == 70.0
    assert any("large_enterprise" in b["reason"] for b in breakdown)

    # 10 - 49 sweet spot
    company_sweet = {
        "industry": "Real Estate & PropTech",
        "employee_count_estimate": "10 - 49",
    }
    score_sweet, breakdown_sweet = scorer.score_with_breakdown(company_sweet)
    # 25 (base) + 35 (industry) + 30 (sweet spot) = 90.0
    assert score_sweet == 90.0
    assert any("employee_sweet_spot" in b["reason"] for b in breakdown_sweet)
