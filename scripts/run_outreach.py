#!/usr/bin/env python3
"""
Signal Engine — Sales Outreach Automation Runner (Phase 5)
1. Fetches prioritized leads (score >= min_score) with enriched decision makers
2. Segments leads into targeted campaign buckets (Laravel, Frontend, Speed, Hiring)
3. Generates hyper-personalized, CAN-SPAM compliant cold outreach copy
4. Stages messages into the database queue for human review and cold email export
"""

import json
import logging
import os
import sys

# Ensure project root is in sys.path when running scripts directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from outreach.queue.queue_manager import get_queue_manager
from shared.mysql_client import get_mysql_client
from shared.pipeline_monitor import get_pipeline_monitor

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("run_outreach")


def run_outreach_pipeline(min_score: float = 60.0, limit: int = 50):
    mysql_client = get_mysql_client()
    if not mysql_client.ping():
        logger.warning("Database unavailable. Exiting outreach run.")
        return

    monitor = get_pipeline_monitor()
    queue_manager = get_queue_manager()
    conn = mysql_client.get_connection()

    try:
      with monitor.track_stage("outreach") as stage:
        with conn.cursor() as cursor:
            # Query prioritized leads that have enriched contacts and NO existing outbound outreach
            sql = """
            SELECT DISTINCT c.id, c.domain, c.name, s.opportunity_score, s.priority_tier
            FROM companies c
            JOIN scores s ON s.company_id = c.id
            JOIN contacts ct ON ct.company_id = c.id
            WHERE s.opportunity_score >= %s
              AND c.domain NOT LIKE '%.local'
              AND ct.email NOT LIKE '%.local'
              AND NOT EXISTS (
                  SELECT 1 FROM outreach_messages om
                  WHERE om.company_id = c.id AND om.direction = 'outbound'
              )
            ORDER BY s.opportunity_score DESC
            LIMIT %s
            """
            cursor.execute(sql, (min_score, limit))
            companies = cursor.fetchall()

        logger.info(
            f"Running Phase 5 Outreach staging for {len(companies)} prioritized leads..."
        )

        total_staged = 0
        fail_count = 0
        for comp in companies:
            comp_id = comp["id"]
            try:
                contacts = mysql_client.get_company_contacts(comp_id)

                with conn.cursor() as cursor:
                    # Fetch tech fingerprint
                    cursor.execute(
                        "SELECT * FROM technologies WHERE company_id = %s ORDER BY id DESC LIMIT 1",
                        (comp_id,),
                    )
                    tech = cursor.fetchone()
                    if tech and tech.get("evidence") and isinstance(tech["evidence"], str):
                        tech["evidence"] = json.loads(tech["evidence"])

                    # Fetch audit
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

                msg_ids = queue_manager.stage_outreach_for_company(
                    company_data=comp,
                    contacts=contacts,
                    tech_fingerprint=tech,
                    audit_metrics=audit,
                    signals=signals,
                    opportunities=opportunities,
                )
                total_staged += len(msg_ids)
            except Exception as e:
                fail_count += 1
                logger.error(f"Error staging outreach for company #{comp_id}: {e}", exc_info=True)

        stage.record(
            items_processed=total_staged,
            items_failed=fail_count,
            companies_processed=len(companies),
        )

        logger.info(
            f"Phase 5 Outreach run complete: Staged {total_staged} personalized messages."
        )

    finally:
        conn.close()


if __name__ == "__main__":
    run_outreach_pipeline()
