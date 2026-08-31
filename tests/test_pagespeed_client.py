from unittest.mock import MagicMock, patch

from intelligence.website_audit.pagespeed_client import PageSpeedClient
from intelligence.website_audit.performance_audit import WebsitePerformanceAuditor


def test_pagespeed_client_mock_success():
    client = PageSpeedClient(api_key="test_key")
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "lighthouseResult": {
            "categories": {
                "performance": {"score": 0.45},
                "accessibility": {"score": 0.88},
                "seo": {"score": 0.90},
            },
            "audits": {
                "largest-contentful-paint": {"numericValue": 3400},
                "cumulative-layout-shift": {"numericValue": 0.15},
                "server-response-time": {"numericValue": 650},
            },
        }
    }

    with patch("requests.get", return_value=mock_response):
        auditor = WebsitePerformanceAuditor(client)
        result = auditor.audit("https://slow-agency.com")

        assert result is not None
        assert result["performance_score"] == 45
        assert result["accessibility_score"] == 88
        assert result["lcp_ms"] == 3400
        assert result["cls"] == 0.15
        assert result["ttfb_ms"] == 650
        assert result["evidence"]["metrics"]["performance_score"] == 45


def test_pagespeed_client_handles_error():
    client = PageSpeedClient(api_key="test_key", max_retries=1)
    mock_response = MagicMock()
    mock_response.status_code = 500

    with patch("requests.get", return_value=mock_response):
        auditor = WebsitePerformanceAuditor(client)
        result = auditor.audit("https://error-site.com")
        assert result is None
