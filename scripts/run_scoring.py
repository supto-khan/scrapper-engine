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


def run_scoring_pipeline():
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
            cursor.execute(
                """
                SELECT id, domain, name, industry, employee_count_estimate, website_url, source
                FROM companies
                ORDER BY id DESC
                """
            )
            companies = cursor.fetchall()

        logger.info(
            f"Computing Phase 3 opportunity scores for {len(companies)} companies..."
        )

        for comp in companies:
            comp_id = comp["id"]

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
    run_scoring_pipeline()
