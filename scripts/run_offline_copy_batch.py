#!/usr/bin/env python3
"""
Nexidant Signal - Offline Asynchronous Copy Batch Generator
Pre-generates personalized Step 1 and Step 2 outreach copy using Qwen3.5-0.8B (or template fallback).
Stages messages in outreach_messages table so they are immediately ready for 10:00 AM dispatch.
"""

import logging
import os
import sys

# Add signal-engine directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
engine_dir = os.path.dirname(current_dir)
if engine_dir not in sys.path:
    sys.path.insert(0, engine_dir)

from outreach.personalization.copy_generator import get_copy_generator
from shared.mysql_client import get_mysql_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("offline_copy_batch")


def run_batch():
    logger.info("⚡ Starting Offline Asynchronous Copy Generation Batch...")
    client = get_mysql_client()
    copy_gen = get_copy_generator()

    with client.get_connection() as conn:
        with conn.cursor() as cursor:
            # Find qualified companies that have verified contacts but no queued or sent outreach
            query = """
                SELECT c.id as company_id, c.name, c.domain, c.industry,
                       ct.id as contact_id, ct.full_name, ct.first_name, ct.email, ct.title, ct.email_status,
                       s.priority_tier, s.opportunity_score,
                       t.cms, t.frontend_stack, t.ttfb_ms,
                       a.performance_score, a.lcp_ms
                FROM companies c
                JOIN contacts ct ON ct.company_id = c.id
                JOIN scores s ON s.company_id = c.id
                LEFT JOIN technologies t ON t.company_id = c.id
                LEFT JOIN audits a ON a.company_id = c.id
                WHERE ct.email_status IN ('valid', 'catch_all')
                  AND s.opportunity_score >= 40.0
                  AND s.priority_tier != 'ignore'
                  AND NOT EXISTS (
                      SELECT 1 FROM outreach_messages om 
                      WHERE (om.company_id = c.id OR om.recipient_email = ct.email) AND om.direction = 'outbound'
                  )
                ORDER BY (c.website_url IS NULL OR c.domain LIKE '%.local') DESC, s.opportunity_score DESC
                LIMIT 150
            """
            cursor.execute(query)
            candidates = cursor.fetchall()

            if not candidates:
                logger.info("✅ No un-staged verified leads found. All active leads already have outreach queued or sent.")
                return

            logger.info(f"📨 Found {len(candidates)} candidate contacts. Staging max 1 primary decision maker per company...")
            staged_count = 0
            staged_company_ids: set[int] = set()

            for row in candidates:
                company_id = row["company_id"]
                if company_id in staged_company_ids:
                    continue
                staged_company_ids.add(company_id)
                company_data = {
                    "id": row["company_id"],
                    "name": row["name"],
                    "domain": row["domain"],
                    "industry": row["industry"],
                }
                contact_data = {
                    "id": row["contact_id"],
                    "full_name": row["full_name"],
                    "first_name": row["first_name"],
                    "email": row["email"],
                    "title": row["title"],
                    "email_status": row["email_status"],
                }
                fe_val = row.get("frontend_stack")
                if isinstance(fe_val, str):
                    try:
                        import json
                        fe_val = json.loads(fe_val)
                    except Exception:
                        pass

                tech_fingerprint = {
                    "cms": row.get("cms"),
                    "frontend_stack": fe_val or [],
                    "ttfb_ms": row.get("ttfb_ms"),
                }
                audit_metrics = {
                    "performance_score": row.get("performance_score"),
                    "lcp_ms": row.get("lcp_ms"),
                }

                # Select segment
                segment = "laravel_modernization"
                if tech_fingerprint.get("frontend_stack"):
                    segment = "frontend_modernization"
                elif audit_metrics.get("lcp_ms") and audit_metrics["lcp_ms"] > 2500:
                    segment = "speed_optimization"

                # Generate Step 1 copy
                res = copy_gen.generate_message(
                    segment=segment,
                    company_data=company_data,
                    contact_data=contact_data,
                    tech_fingerprint=tech_fingerprint,
                    audit_metrics=audit_metrics,
                    step=1,
                )

                # Insert into outreach_messages with status 'queued'
                insert_sql = """
                    INSERT INTO outreach_messages 
                    (step, company_id, contact_id, recipient_email, channel, direction, segment, generator_type, subject, body_text, status, staged_at)
                    VALUES (1, %s, %s, %s, 'email', 'outbound', %s, %s, %s, %s, 'queued', NOW())
                """
                cursor.execute(
                    insert_sql,
                    (
                        company_data["id"],
                        contact_data["id"],
                        contact_data["email"],
                        segment,
                        res.get("generator_type", "template_engine"),
                        res["subject"],
                        res["body_text"],
                    ),
                )
                staged_count += 1
                logger.info(f"   ✓ Staged Step 1 email for {company_data['name']} ({contact_data['email']}) via {res.get('generator_type')}")

            conn.commit()
            logger.info(f"🎉 Successfully pre-generated and staged {staged_count} outreach messages.")


if __name__ == "__main__":
    run_batch()
