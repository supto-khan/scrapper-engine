#!/usr/bin/env python3
"""
Signal Engine — Intelligence Runner (Phase 2 Deep 360° Intelligence Suite)
Executes thorough multi-step technical and conversion diagnostics on discovered companies:
1. Deep 360° Multi-Page Audit (Homepage vs Subpages Latency, Assets, Mobile CRO, SEO, DNS Health)
2. Technology Fingerprinting (CMS, jQuery, Modern Frameworks)
3. Hiring Signals & Growth Signal Detection
4. Multi-Pillar Pain Point Detection (Speed + Mobile Friction + SEO/DNS Health)
5. Master Unified Opportunity Synthesis ($2,500 - $5,000 Turnkey Modernization)
"""

import argparse
import json
import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from intelligence.company_signals.company_signals import get_company_signal_detector
from intelligence.hiring_signals.hiring_detector import get_hiring_detector
from intelligence.opportunity_detector import get_opportunity_detector
from intelligence.pain_detector import get_pain_detector
from intelligence.retry.retry_queue import get_retry_queue
from intelligence.technology.tech_fingerprint import get_fingerprint_detector
from intelligence.website_audit.deep_auditor import get_deep_auditor
from intelligence.website_audit.screenshot_capture import get_screenshot_capture
from outreach.reports.pdf_report_generator import get_report_generator
from shared.mysql_client import get_mysql_client
from shared.pipeline_monitor import get_pipeline_monitor

# Inter-domain pacing delay (seconds) to avoid overwhelming target servers
INTER_AUDIT_DELAY = float(os.getenv("AUDIT_INTER_DOMAIN_DELAY_S", "2.0"))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_intelligence")


def run_intelligence_pipeline(limit: int = 50):
    mysql_client = get_mysql_client()
    if not mysql_client.ping():
        logger.warning("Database unavailable. Exiting intelligence run.")
        return

    monitor = get_pipeline_monitor()
    retry_queue = get_retry_queue()
    tech_detector = get_fingerprint_detector()
    hiring_detector = get_hiring_detector()
    company_detector = get_company_signal_detector()
    pain_detector = get_pain_detector()
    opp_detector = get_opportunity_detector()
    deep_auditor = get_deep_auditor()

    conn = mysql_client.get_connection()
    try:
      with monitor.track_stage("intelligence") as stage:
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
            companies_to_scan = list(cursor.fetchall())

        # Prepend due retries from the retry queue
        due_retries = retry_queue.pop_due_retries(max_items=10)
        retry_rows = []
        for retry_item in due_retries:
            retry_rows.append({
                "company_id": retry_item["company_id"],
                "domain": retry_item["domain"],
                "company_name": retry_item["domain"],
                "website_url": f"https://{retry_item['domain']}",
                "_retry_count": retry_item.get("retry_count", 0),
            })
        if retry_rows:
            logger.info(f"🔄 Prepending {len(retry_rows)} retry items to audit queue")
            companies_to_scan = retry_rows + companies_to_scan

        total = len(companies_to_scan)
        logger.info(
            f"🚀 Running Deep 360° Intelligence on {total} target companies "
            f"({len(retry_rows)} retries + {total - len(retry_rows)} new)..."
        )

        success_count = 0
        fail_count = 0

        for i, row in enumerate(companies_to_scan, 1):
            company_id = row["company_id"]
            domain = row["domain"]
            url = row.get("website_url") or f"https://{domain}"
            name = row.get("company_name") or domain
            retry_count = row.get("_retry_count", 0)

            logger.info(f"\n🔬 [{i}/{total}] Deep 360° Diagnostic: {name} ({domain}){'  [RETRY #' + str(retry_count) + ']' if retry_count else ''}...")

            try:
                # 1. Execute Deep 360° Multi-Page & DNS Audit
                deep_result = deep_auditor.audit_domain(domain=domain, website_url=url)
                speed = deep_result.get("speed_metrics", {})
                cro = deep_result.get("conversion_metrics", {})
                seo = deep_result.get("seo_metrics", {})
                dns_m = deep_result.get("dns_email_metrics", {})
                sec = deep_result.get("security_metrics", {})

                # 2. Tech Fingerprinting
                raw_html = ""
                # Use html collected during deep audit
                tech_result = tech_detector.analyze(
                    url=url,
                    html_content=raw_html,
                    headers={},
                    ttfb_ms=speed.get("homepage_ttfb_ms", 0),
                )
                has_https = sec.get("has_https", True)
                has_hsts = sec.get("has_hsts", False)

                tech_evidence = dict(tech_result.get("evidence", {}))
                tech_evidence["deep_360_audit"] = deep_result

                mysql_client.save_technology_fingerprint(
                    company_id=company_id,
                    cms=tech_result.get("cms"),
                    frontend_stack=tech_result.get("frontend_stack", []),
                    backend_stack=tech_result.get("backend_stack", []),
                    evidence=tech_evidence,
                    https=has_https,
                    hsts=has_hsts,
                )

                # 3. Hiring & Growth Signals
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

                # 4. Multi-Pillar Pain Detection
                audit_metrics = {
                    "ttfb_ms": speed.get("homepage_ttfb_ms", 0),
                    "total_duration_ms": speed.get("homepage_speed_ms", 0),
                }
                all_signals = hiring_signals + growth_signals
                detected_pains = pain_detector.detect_pains(
                    tech_fingerprint=tech_result,
                    audit_metrics=audit_metrics,
                    signals=all_signals,
                    deep_audit=deep_result,
                )

                # Record individual signals for database traceability
                for p in detected_pains:
                    mysql_client.save_signal(
                        company_id=company_id,
                        signal_type=p.get("type", "audit_pain_signal"),
                        source_url=url,
                        confidence_score=float(p.get("confidence", 0.90) * 100),
                        evidence_data=p,
                    )

                # 5. Synthesize Single Master Unified Opportunity
                detected_opps = opp_detector.detect_opportunities(
                    pains=detected_pains,
                    company_metadata=row,
                    deep_audit=deep_result,
                )

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

                # Clean bill of health check
                if not detected_pains:
                    mysql_client.save_signal(
                        company_id=company_id,
                        signal_type="clean_audit_verified",
                        source_url=url,
                        confidence_score=95.0,
                        evidence_data={
                            "status": "modern_clean_health",
                            "homepage_speed": speed.get("homepage_speed_s"),
                            "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        },
                    )

                logger.info(
                    f"   📊 Audit Summary for {domain}:\n"
                    f"      • Pages Audited: {deep_result.get('pages_audited_count')} (Homepage: {speed.get('homepage_speed_s')}s | Slowest Subpage: {speed.get('slowest_subpage_path')} at {speed.get('slowest_subpage_speed_s')}s)\n"
                    f"      • Mobile CRO: Missing tel: link: {cro.get('missing_mobile_tel_link')} | Max Form Fields: {cro.get('max_form_inputs')}\n"
                    f"      • Local SEO: Schema: {seo.get('has_local_business_schema')} | Broken Social Cards: {seo.get('broken_social_cards')}\n"
                    f"      • DNS Health: SPF: {dns_m.get('has_spf_record')} | DMARC: {dns_m.get('has_dmarc_record')} | Spam Risk: {dns_m.get('email_deliverability_risk')}\n"
                    f"      • SSL Cert: Valid: {sec.get('ssl_cert_valid')} | Days Remaining: {sec.get('ssl_cert_days_remaining', 'N/A')} | Expiring Soon: {sec.get('ssl_cert_expiring_soon')}\n"
                    f"      • Broken Links: {deep_result.get('link_health', {}).get('broken_links_count', 0)} dead pages found | Redirect Chains: {deep_result.get('link_health', {}).get('redirect_chain_detected', False)}\n"
                    f"      • Image Optimization: {deep_result.get('image_optimization', {}).get('total_images', 0)} images scanned | Non-WebP: {deep_result.get('image_optimization', {}).get('images_non_modern_format', 0)} | Missing Lazy: {deep_result.get('image_optimization', {}).get('images_missing_lazy_load', 0)} | Missing Alt: {deep_result.get('image_optimization', {}).get('images_missing_alt_text', 0)}\n"
                    f"      • Lighthouse: {'Performance=' + str(deep_result.get('lighthouse_metrics', {}).get('performance_score')) + '/100' if deep_result.get('lighthouse_metrics', {}).get('available') else 'Not available (no API key)'}\n"
                    f"      • Master Opportunity Generated: {len(detected_opps)} (Pains aggregated: {len(detected_pains)})"
                )

                # Capture live screenshot for PDF report embedding
                screenshot_path = None
                try:
                    screenshot_engine = get_screenshot_capture()
                    screenshot_path = screenshot_engine.capture_screenshot(url=url, domain=domain)
                except Exception as shot_err:
                    logger.debug(f"Screenshot capture skipped for {domain}: {shot_err}")

                # Generate branded PDF audit report
                try:
                    report_gen = get_report_generator()
                    company_name = name or domain
                    pdf_path = report_gen.generate_report(
                        domain=domain,
                        company_name=company_name,
                        deep_audit=deep_result,
                        pains=detected_pains,
                        screenshot_path=screenshot_path,
                    )
                    if pdf_path:
                        mysql_client.update_company_report_pdf(company_id=company_id, report_pdf_path=pdf_path)
                        logger.info(f"   📄 PDF Report saved & linked to DB: {pdf_path}")
                except Exception as pdf_err:
                    logger.warning(f"   ⚠️ PDF report generation failed for {domain}: {pdf_err}")

                success_count += 1

            except Exception as e:
                fail_count += 1
                logger.error(f"Error auditing {domain}: {e}", exc_info=True)

                # Push to retry queue instead of permanently losing this company
                retry_queue.push_retry(
                    company_id=company_id,
                    domain=domain,
                    error=str(e),
                    retry_count=retry_count,
                )

            # Inter-domain pacing delay to avoid overwhelming target servers
            if i < total:
                logger.debug(f"⏱ Pacing: waiting {INTER_AUDIT_DELAY}s before next domain audit...")
                time.sleep(INTER_AUDIT_DELAY)

        # Record stage metrics
        stage.record(
            items_processed=success_count,
            items_failed=fail_count,
            total_companies=total,
            retries_popped=len(retry_rows),
            retry_queue_pending=retry_queue.pending_count(),
            dead_letter_count=retry_queue.dead_letter_count(),
        )

        logger.info(
            f"\n🎉 Deep 360° Intelligence Pipeline Complete! "
            f"({success_count} succeeded, {fail_count} failed, "
            f"{retry_queue.pending_count()} pending retries)"
        )

    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Deep 360° Intelligence Analysis")
    parser.add_argument("--limit", type=int, default=10, help="Number of companies to deeply audit (default: 10)")
    args = parser.parse_args()

    run_intelligence_pipeline(limit=args.limit)
