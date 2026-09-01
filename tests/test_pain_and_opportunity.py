from intelligence.opportunity_detector import OpportunityDetector
from intelligence.pain_detector import PainDetector


def test_pain_and_opportunity_detection():
    pain_detector = PainDetector()
    opp_detector = OpportunityDetector()

    tech_fingerprint = {
        "cms": "WordPress 5.4.1",
        "frontend_stack": ["jQuery 1.11.2"],
        "backend_stack": ["PHP", "WordPress"],
        "https": False,
        "hsts": False,
        "ttfb_ms": 950,
        "evidence": {
            "wordpress": {"version": "5.4.1"},
            "jquery": {"version": "1.11.2"},
        },
    }

    audit_metrics = {
        "performance_score": 42,
        "lcp_ms": 3800,
        "ttfb_ms": 950,
    }

    signals = [
        {
            "type": "hiring_skill_match",
            "detail": {
                "matched_skills": [
                    {
                        "skill": "laravel",
                        "count": 2,
                        "sample": "Senior Laravel Developer",
                    }
                ]
            },
        }
    ]

    pains = pain_detector.detect_pains(tech_fingerprint, audit_metrics, signals)
    pain_types = [p["type"] for p in pains]

    assert "legacy_jquery" in pain_types
    assert "outdated_wordpress" in pain_types
    assert "insecure_transport_http" in pain_types
    assert "slow_website_speed" in pain_types
    assert "slow_backend_ttfb" in pain_types
    assert "hiring_capacity_bottleneck" in pain_types

    # Test master unified opportunity mapping
    opportunities = opp_detector.detect_opportunities(pains)
    opp_types = [o["type"] for o in opportunities]
    assert "turnkey_modernization_overhaul" in opp_types

    # Test single pain opportunity mapping
    wp_opp = opp_detector.detect_opportunities([{"type": "outdated_wordpress", "severity": "high", "evidence": {}}])
    assert wp_opp[0]["type"] == "cms_to_laravel_migration"
    assert wp_opp[0]["estimated_value_low"] == 20000
    assert wp_opp[0]["estimated_value_high"] == 60000
    assert "WordPress" in wp_opp[0]["recommended_service"]
