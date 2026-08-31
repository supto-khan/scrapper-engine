#!/usr/bin/env python3
"""
Signal Engine — Decoupled Enrichment Runner (Phase 4)
Runs asynchronous batch enrichment on high-priority scored leads:
1. Discovers decision makers (Hunter.io / Apollo.io)
2. Validates emails (<5% bounce target via ZeroBounce/NeverBounce)
3. Updates contacts in database & recalculates lead contact scores
"""

import logging
import os
import sys

# Ensure project root is in sys.path when running scripts directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from enrichment.enrichment_worker import get_enrichment_worker
from shared.mysql_client import get_mysql_client

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_enrichment")


def run_enrichment_pipeline(min_score: float = 40.0, limit: int = 500):
    mysql_client = get_mysql_client()
    if not mysql_client.ping():
        logger.warning("Database unavailable. Exiting enrichment run.")
        return

    worker = get_enrichment_worker()
    conn = mysql_client.get_connection()

    try:
        with conn.cursor() as cursor:
            # Select scored leads that haven't had contacts enriched yet
            sql = """
            SELECT c.id, c.domain, c.name, s.opportunity_score, s.priority_tier
            FROM companies c
            JOIN scores s ON s.company_id = c.id
            LEFT JOIN contacts ct ON ct.company_id = c.id
            WHERE s.opportunity_score >= %s
              AND ct.id IS NULL
            GROUP BY c.id, c.domain, c.name, s.opportunity_score, s.priority_tier
            ORDER BY s.opportunity_score DESC
            LIMIT %s
            """
            cursor.execute(sql, (min_score, limit))
            leads = cursor.fetchall()

        logger.info(
            f"Starting batch enrichment on {len(leads)} prioritized leads (score >= {min_score})..."
        )

        for lead in leads:
            company_id = lead["id"]
            domain = lead["domain"]
            contacts = worker.enrich_company(company_id=company_id, domain=domain)
            logger.info(
                f"Enriched {domain} (Score: {lead['opportunity_score']}) with {len(contacts)} contacts."
            )

    finally:
        conn.close()


if __name__ == "__main__":
    run_enrichment_pipeline()
