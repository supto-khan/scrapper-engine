import logging
from typing import Any

from intelligence.website_audit.pagespeed_client import PageSpeedClient

logger = logging.getLogger(__name__)


class WebsitePerformanceAuditor:
    """
    Website Performance Auditor integrating Core Web Vitals and PageSpeed metrics.
    """

    def __init__(self, client: PageSpeedClient | None = None):
        self.client = client or PageSpeedClient()

    def audit(self, url: str) -> dict[str, Any] | None:
        """
        Runs performance audit on a target URL and parses key metrics:
        - Performance, Accessibility, SEO Scores (0-100)
        - Core Web Vitals: LCP (ms), CLS, INP (ms), FCP (ms), TTFB (ms)
        """
        raw_data = self.client.run_pagespeed(url, strategy="mobile")
        if not raw_data:
            return None

        try:
            lighthouse = raw_data.get("lighthouseResult", {})
            categories = lighthouse.get("categories", {})
            audits = lighthouse.get("audits", {})

            # Scores (0-100)
            perf_score = (
                int(categories.get("performance", {}).get("score", 0) * 100)
                if categories.get("performance")
                else None
            )
            a11y_score = (
                int(categories.get("accessibility", {}).get("score", 0) * 100)
                if categories.get("accessibility")
                else None
            )
            seo_score = (
                int(categories.get("seo", {}).get("score", 0) * 100)
                if categories.get("seo")
                else None
            )

            # Core Web Vitals
            lcp_ms = (
                int(audits.get("largest-contentful-paint", {}).get("numericValue", 0))
                if audits.get("largest-contentful-paint")
                else None
            )
            fcp_ms = (
                int(audits.get("first-contentful-paint", {}).get("numericValue", 0))
                if audits.get("first-contentful-paint")
                else None
            )
            cls_val = (
                float(
                    audits.get("cumulative-layout-shift", {}).get("numericValue", 0.0)
                )
                if audits.get("cumulative-layout-shift")
                else None
            )
            inp_ms = (
                int(audits.get("interaction-to-next-paint", {}).get("numericValue", 0))
                if audits.get("interaction-to-next-paint")
                else None
            )
            ttfb_ms = (
                int(audits.get("server-response-time", {}).get("numericValue", 0))
                if audits.get("server-response-time")
                else None
            )

            evidence = {
                "source": "google_pagespeed_insights",
                "strategy": "mobile",
                "metrics": {
                    "performance_score": perf_score,
                    "accessibility_score": a11y_score,
                    "seo_score": seo_score,
                    "lcp_ms": lcp_ms,
                    "fcp_ms": fcp_ms,
                    "cls": cls_val,
                    "inp_ms": inp_ms,
                    "ttfb_ms": ttfb_ms,
                },
            }

            return {
                "url": url,
                "performance_score": perf_score,
                "accessibility_score": a11y_score,
                "seo_score": seo_score,
                "lcp_ms": lcp_ms,
                "cls": cls_val,
                "inp_ms": inp_ms,
                "ttfb_ms": ttfb_ms,
                "evidence": evidence,
                "raw_data": raw_data,
            }
        except Exception as e:
            logger.error(f"Error parsing audit metrics for {url}: {e}")
            return None


def get_performance_auditor() -> WebsitePerformanceAuditor:
    return WebsitePerformanceAuditor()
