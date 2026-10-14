#!/usr/bin/env python3
"""
Signal Engine — Scoring Runner (Phase 3 Full Scoring Pipeline)
Calculates composite opportunity scores for all companies with intelligence data:
- Company Fit (0.20)
- Technology Gap (0.20)
- Pain Signal (0.20)
- Buying Signal (0.20)
- Contact Quality (0.10)
- Service Fit (0.10)
"""

import argparse
import fcntl
import json
import logging
import os
import sys

# Ensure project root is in sys.path when running scripts directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from intelligence.pain_detector import get_pain_detector
from scoring.opportunity_score import get_opportunity_scorer
from shared.mysql_client import get_mysql_client

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_scoring")


def run_scoring_pipeline(limit: int = 1000, score_all: bool = False):
    lock_file = "/tmp/nexidant_scoring.lock"
    try:
        lock_fd = open(lock_file, "w")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        logger.warning("Another instance of run_scoring.py is already running. Skipping execution.")
        return

    mysql_client = get_mysql_client()
    if not mysql_client.ping():
        logger.warning("Database unavailable. Exiting scoring run.")
        return

    scorer = get_opportunity_scorer()
    pain_detector = get_pain_detector()
    conn = mysql_client.get_connection()

    try:
        with conn.cursor() as cursor:
            # 1. Fetch companies
            if score_all or not limit or limit <= 0:
                cursor.execute(
                    """
                    SELECT id, domain, name, industry, employee_count_estimate, website_url, source, last_crawled_at
                    FROM companies
                    ORDER BY id DESC
                    """
                )
            else:
                cursor.execute(
                    """
                    SELECT c.id, c.domain, c.name, c.industry, c.employee_count_estimate, c.website_url, c.source, c.last_crawled_at
                    FROM companies c
                    WHERE (
                        c.last_crawled_at IS NOT NULL
                        OR c.website_url IS NULL
                        OR c.domain LIKE '%%.local'
                    )
                    AND NOT EXISTS (
                        SELECT 1 FROM scores s
                        WHERE s.company_id = c.id
                          AND s.computed_at >= COALESCE(c.last_crawled_at, c.created_at)
                          AND s.computed_at > DATE_SUB(NOW(), INTERVAL 7 DAY)
                    )
                    ORDER BY c.id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
            companies = cursor.fetchall()

        logger.info(
            f"Computing Phase 3 opportunity scores for {len(companies)} companies (limit={limit if not score_all else 'ALL'})..."
        )

        for comp in companies:
            comp_id = comp["id"]

            # Fast-track high priority leads without a website directly to 100.0 / Immediate
            is_no_website = (
                comp.get("website_url") is None
                or str(comp.get("domain", "")).endswith(".local")
            )
            if is_no_website:
                mysql_client.save_score(
                    company_id=comp_id,
                    company_fit=100.0,
                    technology_gap=100.0,
                    pain_signal=100.0,
                    buying_signal=100.0,
                    contact_quality=100.0,
                    service_fit=100.0,
                    opportunity_score=100.0,
                    priority_tier="immediate",
                    score_breakdown={
                        "reason": "established_business_missing_website",
                        "status": "highest_priority_no_website",
                        "opportunity_score": 100.0,
                        "priority_tier": "immediate",
                        "total_deal_range": [2500, 5000],
                    },
                )
                logger.info(
                    f"⚡ Fast-tracked No-Website Lead #{comp_id} ({comp.get('name') or comp.get('domain')}) -> Score: 100.0 (IMMEDIATE)"
                )
                continue

            with conn.cursor() as cursor:
                # Fetch latest tech fingerprint
                cursor.execute(
                    "SELECT * FROM technologies WHERE company_id = %s ORDER BY id DESC LIMIT 1",
                    (comp_id,),
                )
                tech = cursor.fetchone()

                # Fetch audit data
                cursor.execute(
                    "SELECT * FROM audits WHERE company_id = %s ORDER BY id DESC LIMIT 1",
                    (comp_id,),
                )
                audit = cursor.fetchone()

                # Fetch signals
                cursor.execute(
                    "SELECT * FROM signals WHERE company_id = %s", (comp_id,)
                )
                signals = cursor.fetchall()
                for s in signals:
                    if s.get("detail") and isinstance(s["detail"], str):
                        s["detail"] = json.loads(s["detail"])

                # Fetch opportunities
                cursor.execute(
                    "SELECT * FROM opportunities WHERE company_id = %s", (comp_id,)
                )
                opportunities = cursor.fetchall()

            # Parse tech evidence if present
            if tech and tech.get("evidence") and isinstance(tech["evidence"], str):
                tech["evidence"] = json.loads(tech["evidence"])

            # Detect pains for decoupled business severity scoring
            pains = pain_detector.detect_pains(
                tech_fingerprint=tech,
                audit_metrics=audit,
                signals=signals,
            )

            # Compute score
            breakdown = scorer.calculate_score(
                company_data=comp,
                tech_fingerprint=tech,
                audit_metrics=audit,
                signals=signals,
                pains=pains,
                opportunities=opportunities,
            )

            # Persist score
            mysql_client.save_score(
                company_id=comp_id,
                company_fit=breakdown["company_fit"],
                technology_gap=breakdown["technology_gap"],
                pain_signal=breakdown["pain_signal"],
                buying_signal=breakdown["buying_signal"],
                contact_quality=breakdown["contact_quality"],
                service_fit=breakdown["service_fit"],
                opportunity_score=breakdown["opportunity_score"],
                priority_tier=breakdown["priority_tier"],
                score_breakdown=breakdown,
            )

            logger.info(
                f"Scored {comp['domain']} -> Score: {breakdown['opportunity_score']} ({breakdown['priority_tier'].upper()}) "
                f"| Deal Range: ${breakdown['total_deal_range'][0]:,} - ${breakdown['total_deal_range'][1]:,}"
            )

        # Automatic Quality Gate: Prune low-fit companies (< 40 score) to keep database pristine
        pruned_count = mysql_client.prune_low_score_companies(min_score=40.0)
        if pruned_count > 0:
            logger.info(f"Quality Gate: Pruned {pruned_count} unqualified companies (Score < 40.0) from database.")

    finally:
        conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Signal Engine - Phase 3 Opportunity Scorer")
    parser.add_argument("--limit", type=int, default=1000, help="Maximum companies to score per batch (default: 1000)")
    parser.add_argument("--all", action="store_true", help="Score all companies without limit")
    args = parser.parse_args()

    run_scoring_pipeline(limit=args.limit, score_all=args.all)
