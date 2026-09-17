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
import concurrent.futures
import json
import logging
import os
import sys
import threading
import time
from typing import Any

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
from shared.domain_filter import is_excluded_domain, is_retryable_failure
from shared.mysql_client import get_mysql_client
from shared.pipeline_monitor import get_pipeline_monitor

# Inter-domain pacing delay (seconds) to avoid overwhelming target servers
INTER_AUDIT_DELAY = float(os.getenv("AUDIT_INTER_DOMAIN_DELAY_S", "2.0"))

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_intelligence")


def audit_single_company(
    row: dict[str, Any],
    company_idx: int,
    total: int,
    mysql_client,
    retry_queue,
    deep_auditor,
    tech_detector,
    hiring_detector,
    company_detector,
    pain_detector,
    opp_detector,
    enable_screenshots: bool = False,
    enable_pdf_reports: bool = True,
) -> bool:
    """
    Audits a single company through the complete Deep 360° suite:
    1. Fast aggregator/directory domain exclusion
    2. Deep multi-page & DNS audit
    3. Safety gate check & disqualification (with non-retryable error classification)
    4. HTML snapshot persistence
    5. Audit record persistence
    6. Tech fingerprinting
    7. Hiring & growth signal detection
    8. Multi-pillar pain detection
    9. Master unified opportunity synthesis
    10. Screenshot & PDF report generation

    Returns True if audit succeeded, False if disqualified, failed, or errored.
    """
    company_id = row["company_id"]
    domain = row["domain"]
    url = row.get("website_url") or f"https://{domain}"
    name = row.get("company_name") or domain
    retry_count = row.get("_retry_count", 0)

    # Fast check: Filter out aggregator / directory / social domains immediately
    is_excluded, reason = is_excluded_domain(domain)
    if is_excluded:
        logger.info(
            f"\n⏭️ [{company_idx}/{total}] Skipping directory/aggregator domain: {name} ({domain}) "
            f"[{reason}] — marking disqualified"
        )
        try:
            mysql_client.save_audit_result(
                company_id=company_id,
                url=url,
                performance_score=0,
                accessibility_score=0,
                seo_score=0,
                raw_audit_data={
                    "status": "disqualified",
                    "error": reason,
                    "domain": domain,
                    "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            mysql_client.save_score(
                company_id=company_id,
                company_fit=0.0,
                technology_gap=0.0,
                pain_signal=0.0,
                buying_signal=0.0,
                contact_quality=0.0,
                service_fit=0.0,
                opportunity_score=0.0,
                priority_tier="disqualified",
                score_breakdown={
                    "disqualified": True,
                    "reason": reason,
                },
            )
        except Exception as db_err:
            logger.warning(f"Error saving disqualified status for {domain}: {db_err}")
        return False

    logger.info(
        f"\n🔬 [{company_idx}/{total}] Deep 360° Diagnostic: {name} ({domain})"
        f"{'  [RETRY #' + str(retry_count) + ']' if retry_count else ''}..."
    )

    try:
        # 1. Execute Deep 360° Multi-Page & DNS Audit
        deep_result = deep_auditor.audit_domain(domain=domain, website_url=url)
        raw_html = deep_result.get("raw_html", "")
        headers = deep_result.get("headers", {})
        status_code = deep_result.get("status_code")
        is_reachable = deep_result.get("reachable", False)

        speed = deep_result.get("speed_metrics", {})
        cro = deep_result.get("conversion_metrics", {})
        seo = deep_result.get("seo_metrics", {})
        dns_m = deep_result.get("dns_email_metrics", {})
        sec = deep_result.get("security_metrics", {})
        lh = deep_result.get("lighthouse_metrics", {})

        # 🛑 RED FLAG SAFETY GATE: If domain is unreachable or crawl failed
        if not is_reachable or not raw_html:
            logger.warning(
                f"🚨 [RED FLAG: AUDIT FAILED] Domain '{domain}' is unreachable (HTTP {status_code}). "
                f"Flagging red & strictly disqualifying lead from outreach queue."
            )
            # 1. Save Signal
            mysql_client.save_signal(
                company_id=company_id,
                signal_type="crawl_audit_failed",
                source_url=url,
                confidence_score=100.0,
                evidence_data={
                    "status_code": status_code,
                    "reason": "unreachable_or_connection_error",
                    "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            # 2. Save Audit Record (Failed status & updates last_crawled_at)
            mysql_client.save_audit_result(
                company_id=company_id,
                url=url,
                performance_score=0,
                accessibility_score=0,
                seo_score=0,
                raw_audit_data={
                    "status": "failed",
                    "error": "crawl_audit_failed",
                    "status_code": status_code,
                    "reachable": False,
                    "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
            # 3. Save Technology Fingerprint (Marks failed crawl so query won't loop)
            mysql_client.save_technology_fingerprint(
                company_id=company_id,
                cms=None,
                frontend_stack=[],
                backend_stack=[],
                evidence={
                    "crawl_failed": True,
                    "status_code": status_code,
                    "reachable": False,
                    "scanned_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                },
                https=False,
                hsts=False,
            )
            # 4. Save Disqualified Score
            mysql_client.save_score(
                company_id=company_id,
                company_fit=0.0,
                technology_gap=0.0,
                pain_signal=0.0,
                buying_signal=0.0,
                contact_quality=0.0,
                service_fit=0.0,
                opportunity_score=0.0,
                priority_tier="disqualified",
                score_breakdown={
                    "disqualified": True,
                    "red_flag": True,
                    "reason": "site_unreachable_or_failed_audit",
                    "status_code": status_code,
                },
            )
            audit_error = deep_result.get("error", "")
            if is_retryable_failure(status_code, audit_error):
                retry_queue.push_retry(
                    company_id=company_id,
                    domain=domain,
                    error=f"HTTP {status_code} - unreachable {audit_error}".strip(),
                    retry_count=retry_count,
                )
            else:
                logger.info(
                    f"🛑 Skipping retry for {domain} — permanent non-retryable error "
                    f"(HTTP {status_code}{f', {audit_error}' if audit_error else ''})"
                )
            return False

        # 2. Persist Raw Crawled HTML Snapshot (Provenance metadata only, avoid raw HTML blob bloat)
        mysql_client.save_raw_company_data(
            company_id=company_id,
            source_url=url,
            http_status=status_code,
            headers=headers,
            raw_html=None,
        )

        # 3. Persist Full Performance Audit Record into audits table
        mysql_client.save_audit_result(
            company_id=company_id,
            url=url,
            performance_score=lh.get("performance_score"),
            accessibility_score=lh.get("accessibility_score"),
            seo_score=lh.get("seo_score"),
            lcp_ms=lh.get("lcp_ms") or speed.get("homepage_speed_ms"),
            cls=lh.get("cls"),
            inp_ms=lh.get("inp_ms"),
            ttfb_ms=speed.get("homepage_ttfb_ms"),
            raw_audit_data={"status": "completed"},
        )

        # 4. Tech Fingerprinting on Real Scraped HTML
        tech_result = tech_detector.analyze(
            url=url,
            html_content=raw_html,
            headers=headers,
            ttfb_ms=speed.get("homepage_ttfb_ms", 0),
        )
        has_https = sec.get("has_https", True)
        has_hsts = sec.get("has_hsts", False)

        tech_evidence = dict(tech_result.get("evidence", {}))

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

        lh = deep_result.get("lighthouse_metrics", {})
        if lh.get("available"):
            lh_str = f"Performance={lh.get('performance_score')}/100"
        elif not os.getenv("PAGESPEED_API_KEY"):
            lh_str = "Not configured (no PAGESPEED_API_KEY in .env)"
        else:
            lh_str = "Unavailable (Google API timeout or rate-limited)"

        logger.info(
            f"   📊 Audit Summary for {domain}:\n"
            f"      • Pages Audited: {deep_result.get('pages_audited_count')} (Homepage: {speed.get('homepage_speed_s')}s | Slowest Subpage: {speed.get('slowest_subpage_path')} at {speed.get('slowest_subpage_speed_s')}s)\n"
            f"      • Mobile CRO: Missing tel: link: {cro.get('missing_mobile_tel_link')} | Max Form Fields: {cro.get('max_form_inputs')}\n"
            f"      • Local SEO: Schema: {seo.get('has_local_business_schema')} | Broken Social Cards: {seo.get('broken_social_cards')}\n"
            f"      • DNS Health: SPF: {dns_m.get('has_spf_record')} | DMARC: {dns_m.get('has_dmarc_record')} | Spam Risk: {dns_m.get('email_deliverability_risk')}\n"
            f"      • SSL Cert: Valid: {sec.get('ssl_cert_valid')} | Days Remaining: {sec.get('ssl_cert_days_remaining', 'N/A')} | Expiring Soon: {sec.get('ssl_cert_expiring_soon')}\n"
            f"      • Broken Links: {deep_result.get('link_health', {}).get('broken_links_count', 0)} dead pages found | Redirect Chains: {deep_result.get('link_health', {}).get('redirect_chain_detected', False)}\n"
            f"      • Image Optimization: {deep_result.get('image_optimization', {}).get('total_images', 0)} images scanned | Non-WebP: {deep_result.get('image_optimization', {}).get('images_non_modern_format', 0)} | Missing Lazy: {deep_result.get('image_optimization', {}).get('images_missing_lazy_load', 0)} | Missing Alt: {deep_result.get('image_optimization', {}).get('images_missing_alt_text', 0)}\n"
            f"      • Lighthouse: {lh_str}\n"
            f"      • Master Opportunity Generated: {len(detected_opps)} (Pains aggregated: {len(detected_pains)})"
        )

        # Capture live screenshot for PDF report embedding (if explicitly enabled)
        screenshot_path = None
        if enable_screenshots:
            try:
                screenshot_engine = get_screenshot_capture()
                screenshot_path = screenshot_engine.capture_screenshot(url=url, domain=domain)
            except Exception as shot_err:
                logger.debug(f"Screenshot capture skipped for {domain}: {shot_err}")

        # Generate branded PDF audit report (if enabled)
        if enable_pdf_reports:
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

        return True

    except Exception as e:
        logger.error(f"Error auditing {domain}: {e}", exc_info=True)
        # Push to retry queue if temporary
        retry_queue.push_retry(
            company_id=company_id,
            domain=domain,
            error=str(e),
            retry_count=retry_count,
        )
        return False


def run_intelligence_pipeline(
    limit: int = 50,
    workers: int = 10,
    enable_screenshots: bool = False,
    enable_pdf_reports: bool = True,
):
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
        with conn.cursor() as cursor:
            query = """
                SELECT
                    c.id as company_id,
                    c.domain,
                    c.name as company_name,
                    c.website_url,
                    c.industry,
                    c.employee_count_estimate
                FROM companies c
                LEFT JOIN technologies t ON t.company_id = c.id
                LEFT JOIN audits a ON a.company_id = c.id
                WHERE c.domain NOT LIKE '%%.local'
                  AND (
                      c.last_crawled_at IS NULL
                      OR t.id IS NULL
                      OR a.id IS NULL
                      OR c.last_crawled_at < DATE_SUB(NOW(), INTERVAL 7 DAY)
                  )
                GROUP BY c.id, c.domain, c.name, c.website_url, c.industry, c.employee_count_estimate
                ORDER BY c.id DESC
            """
            if limit and limit > 0:
                query += " LIMIT %s"
                cursor.execute(query, (int(limit),))
            else:
                cursor.execute(query.replace("%%", "%"))
            companies_to_scan = list(cursor.fetchall())
    finally:
        conn.close()

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
    effective_workers = max(1, workers)
    logger.info(
        f"🚀 Running Deep 360° Intelligence on {total} target companies "
        f"with {effective_workers} concurrent worker{'s' if effective_workers > 1 else ''} "
        f"({len(retry_rows)} retries + {total - len(retry_rows)} new)..."
    )

    success_count = 0
    fail_count = 0

    with monitor.track_stage("intelligence") as stage:
        def worker_task(item: tuple[int, dict[str, Any]]) -> bool:
            idx, row = item
            return audit_single_company(
                row=row,
                company_idx=idx,
                total=total,
                mysql_client=mysql_client,
                retry_queue=retry_queue,
                deep_auditor=deep_auditor,
                tech_detector=tech_detector,
                hiring_detector=hiring_detector,
                company_detector=company_detector,
                pain_detector=pain_detector,
                opp_detector=opp_detector,
                enable_screenshots=enable_screenshots,
                enable_pdf_reports=enable_pdf_reports,
            )

        if effective_workers <= 1:
            # Sequential mode
            for i, row in enumerate(companies_to_scan, 1):
                ok = worker_task((i, row))
                if ok:
                    success_count += 1
                else:
                    fail_count += 1
                if i < total and INTER_AUDIT_DELAY > 0:
                    time.sleep(INTER_AUDIT_DELAY)
        else:
            # Concurrent worker pool with bounded sliding window
            with concurrent.futures.ThreadPoolExecutor(max_workers=effective_workers) as executor:
                items_iter = iter(enumerate(companies_to_scan, 1))
                pending_futures: set[concurrent.futures.Future] = set()

                max_active = max(effective_workers * 2, 4)
                for item in items_iter:
                    pending_futures.add(executor.submit(worker_task, item))
                    if len(pending_futures) >= max_active:
                        break

                while pending_futures:
                    done, pending_futures = concurrent.futures.wait(
                        pending_futures, return_when=concurrent.futures.FIRST_COMPLETED
                    )
                    for f in done:
                        try:
                            ok = f.result()
                            if ok:
                                success_count += 1
                            else:
                                fail_count += 1
                        except Exception as exc:
                            fail_count += 1
                            logger.error(f"Worker task uncaught exception: {exc}", exc_info=True)

                        try:
                            next_item = next(items_iter)
                            pending_futures.add(executor.submit(worker_task, next_item))
                        except StopIteration:
                            pass

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Deep 360° Intelligence Analysis")
    default_limit = int(os.getenv("INTELLIGENCE_AUDIT_LIMIT", "1"))
    default_workers = int(os.getenv("INTELLIGENCE_WORKERS", "10"))
    parser.add_argument(
        "--limit",
        type=int,
        default=default_limit,
        help=f"Number of companies to deeply audit (default: {default_limit}, use 0 or --all for unlimited)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Audit all pending uncrawled companies without limit",
    )
    parser.add_argument(
        "--workers",
        "-w",
        type=int,
        default=default_workers,
        help=f"Number of concurrent worker threads (default: {default_workers}, set 1 for sequential)",
    )
    parser.add_argument(
        "--screenshots",
        action="store_true",
        default=os.getenv("ENABLE_AUDIT_SCREENSHOTS", "0").lower() in ("1", "true", "yes"),
        help="Capture live browser screenshots via Playwright (default: False to avoid OOM crashes during bulk scans)",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Skip PDF report generation during intelligence scan",
    )
    args = parser.parse_args()

    effective_limit = 0 if args.all else args.limit
    effective_workers = max(1, args.workers)
    run_intelligence_pipeline(
        limit=effective_limit,
        workers=effective_workers,
        enable_screenshots=args.screenshots,
        enable_pdf_reports=not args.no_pdf,
    )
