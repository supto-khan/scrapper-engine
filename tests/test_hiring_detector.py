from intelligence.company_signals.company_signals import CompanySignalDetector
from intelligence.hiring_signals.hiring_detector import HiringSignalDetector


def test_hiring_detector_finds_laravel_and_ats():
    detector = HiringSignalDetector()
    html = """
    <html>
        <body>
            <a href="/careers">Careers & Jobs</a>
            <div class="job-item">
                <h3>Senior Laravel Developer</h3>
                <p>We are hiring an experienced PHP engineer to modernize our backend systems.</p>
            </div>
            <script src="https://boards.greenhouse.io/embed/job_board.js"></script>
        </body>
    </html>
    """
    signals = detector.analyze("https://growing-shop.com", html)
    sig_types = [s["type"] for s in signals]

    assert "career_page_detected" in sig_types
    assert "hiring_ats_detected" in sig_types
    assert "hiring_skill_match" in sig_types

    skill_signal = next(s for s in signals if s["type"] == "hiring_skill_match")
    matched = [m["skill"] for m in skill_signal["detail"]["matched_skills"]]
    assert "laravel" in matched


def test_company_signals_detects_scale():
    detector = CompanySignalDetector()
    html = """
    <div>
        <p>Founded in 2018, we have delivered 500+ projects for 200 clients worldwide.</p>
        <p>Recognized as an Inc 5000 fastest growing company.</p>
    </div>
    """
    signals = detector.analyze("https://fast-growing-corp.com", html)
    sig_subtypes = [s["detail"]["subtype"] for s in signals]

    assert "company_age" in sig_subtypes
    assert "client_scale" in sig_subtypes
    assert "industry_award" in sig_subtypes


def test_agency_exclusion_filter():
    from discovery.company_discovery import CompanyDiscoveryOrchestrator

    orchestrator = CompanyDiscoveryOrchestrator()

    # Should detect agencies/competitors
    assert orchestrator.is_agency_or_competitor("PixelCraft Software Agency", "pixelcraft.com", "Web Development") is True
    assert orchestrator.is_agency_or_competitor("SuperDev Studio", "superdev.io", "IT Services") is True

    # Should allow real commercial businesses (clients)
    assert orchestrator.is_agency_or_competitor("Sands Investment Group", "sandsinvestment.com", "Real Estate") is False
    assert orchestrator.is_agency_or_competitor("Luxe Apparel Boutique", "luxeapparel.com", "E-Commerce & Retail") is False


def test_job_board_intent_discovery():
    from discovery.hiring.job_feed_discovery import JobBoardIntentDiscovery
    from unittest.mock import MagicMock, patch

    mock_orch = MagicMock()
    mock_orch.is_agency_or_competitor.return_value = False
    mock_orch.classify_target_industry.return_value = "E-Commerce & Online Stores"
    mock_orch.ingest_candidate.return_value = True

    discovery = JobBoardIntentDiscovery(orchestrator=mock_orch)

    mock_jobs = [
        {
            "company_name": "Nordic Apparel Co",
            "domain": "nordicapparel.com",
            "website_url": "https://nordicapparel.com",
            "job_title": "Shopify Frontend Developer",
            "summary": "Looking for a developer to rebuild our custom Shopify checkout and React store",
            "job_url": "https://remotive.com/job/123",
            "source": "remotive_api",
        }
    ]

    with patch.object(discovery.api_collector, "fetch_all", return_value=mock_jobs), \
         patch.object(discovery.rss_collector, "fetch_all", return_value=[]), \
         patch.object(discovery, "_save_hiring_signal"):
        ingested = discovery.discover_hiring_leads()
        assert ingested == 1
        mock_orch.ingest_candidate.assert_called_once()


