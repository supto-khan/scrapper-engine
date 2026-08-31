#!/usr/bin/env python3
"""
Signal Engine — Intelligence Runner (Phase 2 Full Intelligence Suite)
Executes multi-step intelligence analysis on discovered companies:
1. Technology Fingerprinting (CMS, jQuery, Frontend/Backend stack)
2. TTFB & Server Response Measurement (12.0s timeout to capture slow sites)
3. Hiring Signals & ATS Embed Detection
4. Pain Point Detection (Confidence & Severity Weighted)
5. Opportunity Detection & Deal Value Estimation (Version-Stamped from YAML)
6. Clean Bill of Health Logging (Storing positive/negative audit states)
"""

import json
import logging
import os
import sys
import time
import requests

# Ensure project root is in sys.path when running scripts directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from intelligence.company_signals.company_signals import get_company_signal_detector
from intelligence.hiring_signals.hiring_detector import get_hiring_detector
from intelligence.opportunity_detector import get_opportunity_detector
from intelligence.pain_detector import get_pain_detector
from intelligence.technology.tech_fingerprint import get_fingerprint_detector
from shared.mysql_client import get_mysql_client

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_intelligence")

DIAGNOSTIC_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def run_intelligence_pipeline(limit: int = 50):
    mysql_client = get_mysql_client()
    if not mysql_client.ping():
        logger.warning("Database unavailable. Exiting intelligence run.")
        return

    tech_detector = get_fingerprint_detector()
    hiring_detector = get_hiring_detector()
    company_detector = get_company_signal_detector()
    pain_detector = get_pain_detector()
    opp_detector = get_opportunity_detector()

    conn = mysql_client.get_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    c.id as company_id,
                    c.domain,
                    c.name as company_name,
                    c.website_url,
                    c.industry,
                    c.employee_count_estimate
                FROM companies c
                LEFT JOIN technologies t ON t.company_id = c.id
                WHERE t.id IS NULL OR t.scanned_at < DATE_SUB(NOW(), INTERVAL 7 DAY)
                ORDER BY c.id DESC
                LIMIT %s
                """,
                (limit,),
            )
            companies_to_scan = cursor.fetchall()

        logger.info(
            f"Running Phase 2 Intelligence on {len(companies_to_scan)} target companies..."
        )

        session = requests.Session()
        session.headers.update({
            "User-Agent": DIAGNOSTIC_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

        for row in companies_to_scan:
            company_id = row["company_id"]
            domain = row["domain"]
            url = row.get("website_url") or f"https://{domain}"

            logger.info(f"\n🔍 Diagnostic Scan: {row.get('company_name')} ({domain})...")

            try:
                raw_html = ""
                headers_dict = {}
                ttfb_ms = 0
                total_duration_ms = 0

                # Diagnostic crawl with 12.0s timeout to capture slow/reachable sites
                start_time = time.time()
                try:
                    r = session.get(url, timeout=12.0, allow_redirects=True)
                    total_duration_ms = int((time.time() - start_time) * 1000)
                    ttfb_ms = int(r.elapsed.total_seconds() * 1000)
                    raw_html = r.text
                    headers_dict = dict(r.headers)
                except requests.exceptions.Timeout:
                    logger.warning(f"⏰ High latency timeout (>12s) on {url} (Severe Server Bottleneck)")
                    total_duration_ms = 12000
                    ttfb_ms = 12000
                except Exception as ex:
                    logger.warning(f"Could not reach {url}: {ex}")

                # 1. Tech Fingerprinting
                tech_result = tech_detector.analyze(
                    url=url,
                    html_content=raw_html,
                    headers=headers_dict,
                    ttfb_ms=ttfb_ms,
                )
                has_https = url.startswith("https://")
                has_hsts = "strict-transport-security" in [k.lower() for k in headers_dict.keys()]

                # Include TTFB in tech evidence
                tech_evidence = dict(tech_result.get("evidence", {}))
                tech_evidence["performance"] = {
                    "ttfb_ms": ttfb_ms,
                    "total_duration_ms": total_duration_ms,
                    "slow_site_detected": ttfb_ms > 1500,
                }

                mysql_client.save_technology_fingerprint(
                    company_id=company_id,
                    cms=tech_result.get("cms"),
                    frontend_stack=tech_result.get("frontend_stack", []),
                    backend_stack=tech_result.get("backend_stack", []),
                    evidence=tech_evidence,
                    https=has_https,
                    hsts=has_hsts,
                )

                # 2. Hiring & Growth Signals
                hiring_signals = hiring_detector.analyze(url, raw_html)
                for sig in hiring_signals:
                    mysql_client.save_signal(
                        company_id=company_id,
                        signal_type=sig.get("type", "hiring_signal"),
                        source_url=url,
                        confidence_score=float(sig.get("confidence", 85.0)),
                        evidence_data=sig.get("detail", {}),
                    )

                growth_signals = company_detector.analyze(url, raw_html)
                for sig in growth_signals:
                    mysql_client.save_signal(
                        company_id=company_id,
                        signal_type=sig.get("type", "company_signal"),
                        source_url=url,
                        confidence_score=float(sig.get("confidence", 80.0)),
                        evidence_data=sig.get("detail", {}),
                    )

                # 3. Pain & Opportunity Detection
                audit_metrics = {
                    "ttfb_ms": ttfb_ms,
                    "total_duration_ms": total_duration_ms,
                }
                all_signals = hiring_signals + growth_signals
                detected_pains = pain_detector.detect_pains(
                    tech_fingerprint=tech_result,
                    audit_metrics=audit_metrics,
                    signals=all_signals,
                )
                detected_opps = opp_detector.detect_opportunities(
                    detected_pains,
                    company_metadata=row,
                )

                # 4. Save Opportunities & Deal Estimates
                for opp in detected_opps:
                    mysql_client.save_opportunity(
                        company_id=company_id,
                        type=opp["type"],
                        recommended_service=opp["recommended_service"],
                        estimated_value_low=opp["estimated_value_low"],
                        estimated_value_high=opp["estimated_value_high"],
                        confidence=opp["confidence"],
                        evidence=opp["evidence"],
                    )

                # 5. Clean Bill of Health Logging (Negative Result Persistence)
                if not detected_pains and raw_html:
                    mysql_client.save_signal(
                        company_id=company_id,
                        signal_type="clean_audit_verified",
                        source_url=url,
                        confidence_score=95.0,
                        evidence_data={
                            "status": "modern_stack_clean_health",
                            "ttfb_ms": ttfb_ms,
                            "cms": tech_result.get("cms") or "Modern Custom Framework",
                            "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                    )

                logger.info(
                    f"   ✓ TTFB: {ttfb_ms}ms | CMS: {tech_result.get('cms') or 'Custom'} | "
                    f"Frontend: {tech_result.get('frontend_stack')} | "
                    f"Opportunities: {len(detected_opps)}"
                )
            except Exception as e:
                logger.error(f"Error processing {domain}: {e}")

        logger.info("\n🎉 Phase 2 Intelligence Pipeline Complete!")

    finally:
        conn.close()


if __name__ == "__main__":
    run_intelligence_pipeline()
