#!/usr/bin/env python3
"""
Signal Engine — Directory Lead & Real Domain Resolver Runner
Converts placeholder directory leads (*.localsearch.com, etc.) into high-value opportunities:
- Discovers real company domains & phones via Apollo, OpenCorporates, BBB, SEC EDGAR, and open datasets.
- Discovered domains are updated in MySQL to undergo 360° Tech Audits.
- Companies with no website are converted to .local and fast-tracked to 100.0 (IMMEDIATE) for turnkey website creation.
"""

import argparse
import concurrent.futures
import fcntl
import logging
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from enrichment.multi_source_resolver import get_multi_source_resolver
from shared.mysql_client import get_mysql_client

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("resolve_directory_leads")


def process_single_lead(comp: dict, resolver, mysql_client) -> str:
    company_id = comp["id"]
    name = comp.get("name") or comp.get("domain", "")
    current_domain = comp.get("domain", "")
    phone = comp.get("phone")

    try:
        res = resolver.resolve_directory_lead(
            company_id=company_id,
            company_name=name,
            current_domain=current_domain,
            phone=phone,
            industry=comp.get("industry") or "",
        )

        status = res["status"]
        final_domain = res["domain"]
        final_url = res["website_url"]
        final_phone = res["phone"]
        contacts = res.get("contacts", [])

        # Update phone if found and missing in DB
        if final_phone and final_phone != phone:
            mysql_client.update_company_phone(company_id=company_id, phone=final_phone)

        # Save any newly discovered contacts
        for c in contacts:
            try:
                mysql_client.save_contact(
                    company_id=company_id,
                    email=c["email"],
                    first_name=c.get("first_name"),
                    full_name=c.get("full_name") or f"{name} Team",
                    title=c.get("title") or "Decision Maker",
                    source=c.get("source") or "directory_resolver",
                    email_status=c.get("email_status") or "valid",
                    verification_source=c.get("verification_source") or "multi_source_resolver",
                )
            except Exception:
                pass

        if status == "resolved_real_domain":
            # Update domain and reset last_crawled_at so 360° Tech Auditor processes it
            mysql_client.update_company_domain(
                company_id=company_id,
                new_domain=final_domain,
                website_url=final_url,
            )
            # Tag company source
            conn = mysql_client.get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE companies SET source = 'directory_resolved', last_crawled_at = NULL WHERE id = %s",
                        (company_id,),
                    )
                    conn.commit()
            finally:
                conn.close()

            logger.info(f"✅ [#100 Real Site] Upgraded #{company_id} ({name}) -> {final_domain} ({final_url})")
            return "real_domain_found"

        else:
            # Verified no independent website -> Fast-track to 100.0 IMMEDIATE Tier
            mysql_client.update_company_domain(
                company_id=company_id,
                new_domain=final_domain,
                website_url=None,
            )
            mysql_client.save_score(
                company_id=company_id,
                company_fit=100.0,
                technology_gap=100.0,
                pain_signal=100.0,
                buying_signal=100.0 if res.get("is_hiring") else 85.0,
                contact_quality=90.0 if contacts else 60.0,
                service_fit=100.0,
                opportunity_score=100.0,
                priority_tier="immediate",
                score_breakdown={
                    "reason": "established_business_missing_website",
                    "status": "highest_priority_no_website",
                    "opportunity_score": 100.0,
                    "priority_tier": "immediate",
                    "recommended_service": "Turnkey Website Design & Development",
                    "total_deal_range": [2500, 5000],
                    "sources_checked": res.get("sources_used", []),
                },
            )
            logger.info(f"⚡ [#100 No Website] Fast-tracked #{company_id} ({name}) -> {final_domain} (100.0 IMMEDIATE)")
            return "no_website_fast_tracked"

    except Exception as e:
        logger.error(f"Error resolving lead #{company_id} ({name}): {e}", exc_info=True)
        return "error"


def run_resolver(limit: int = 50, workers: int = 3):
    lock_file = "/tmp/nexidant_directory_resolver.lock"
    try:
        lock_fd = open(lock_file, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        logger.warning("Another instance of resolve_directory_leads.py is already running. Skipping execution.")
        return

    mysql_client = get_mysql_client()
    if not mysql_client.ping():
        logger.warning("Database unavailable. Exiting resolver run.")
        return

    resolver = get_multi_source_resolver()
    conn = mysql_client.get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, name, domain, phone, industry
                FROM companies
                WHERE (domain LIKE '%%.localsearch.com' OR domain LIKE '%%.localsearch.com.au')
                  AND (last_crawled_at IS NULL OR source = 'local_business_directory')
                ORDER BY id DESC
                LIMIT %s
                """,
                (limit,),
            )
            leads = cur.fetchall()
    finally:
        conn.close()

    if not leads:
        logger.info("No pending directory leads found to resolve.")
        return

    total = len(leads)
    logger.info(f"🚀 Starting multi-source resolution for {total} directory leads (workers: {workers})...")

    real_domains_count = 0
    no_web_count = 0
    error_count = 0

    if workers <= 1:
        for comp in leads:
            res = process_single_lead(comp, resolver, mysql_client)
            if res == "real_domain_found":
                real_domains_count += 1
            elif res == "no_website_fast_tracked":
                no_web_count += 1
            else:
                error_count += 1
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_comp = {executor.submit(process_single_lead, comp, resolver, mysql_client): comp for comp in leads}
            for f in concurrent.futures.as_completed(future_to_comp):
                res = f.result()
                if res == "real_domain_found":
                    real_domains_count += 1
                elif res == "no_website_fast_tracked":
                    no_web_count += 1
                else:
                    error_count += 1

    logger.info(
        f"\n🎯 Directory Lead Resolution Complete!\n"
        f"   • Real Websites Discovered & Upgraded: {real_domains_count}\n"
        f"   • Confirmed No-Website Leads (Fast-Tracked to 100.0): {no_web_count}\n"
        f"   • Errors: {error_count}\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Resolve Directory Leads into Real Domains and Immediate Opportunities")
    parser.add_argument("--limit", type=int, default=50, help="Number of directory leads to resolve per batch (default: 50)")
    parser.add_argument("--workers", type=int, default=3, help="Concurrent worker threads (default: 3)")
    parser.add_argument("--continuous", action="store_true", help="Run continuously in a loop with rest intervals")
    parser.add_argument("--interval", type=int, default=30, help="Rest seconds between batches in continuous mode (default: 30)")
    args = parser.parse_args()

    if args.continuous:
        logger.info(f"🔄 Starting continuous directory lead resolution loop (batch={args.limit}, interval={args.interval}s)...")
        while True:
            try:
                run_resolver(limit=args.limit, workers=args.workers)
            except Exception as e:
                logger.error(f"Error in continuous resolver loop: {e}", exc_info=True)
            time.sleep(args.interval)
    else:
        run_resolver(limit=args.limit, workers=args.workers)
