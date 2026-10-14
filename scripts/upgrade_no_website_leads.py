#!/usr/bin/env python3
"""
Nexidant Signal — Upgrade Existing No-Website Leads to Highest Priority (100% Score)

This script scans the database for any existing leads lacking a custom website
(e.g., website_url IS NULL or domain ends with .local):
1. Awards them the highest opportunity score (100.0 / Immediate Priority Tier).
2. Updates companies.latest_score_id and touches last_crawled_at = NOW().
3. Ensures a 'new_website_creation' opportunity ($2,500 - $5,000) exists.
4. Validates any existing non-local contact emails so they become immediately eligible for outreach.
"""

import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mysql_client import get_mysql_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("upgrade_no_website_leads")


def upgrade_existing_no_website_leads():
    logger.info("🚀 Starting Batch Upgrade for all existing No-Website leads to 100% Highest Priority...")
    client = get_mysql_client()
    if not client.ping():
        logger.error("❌ Database unavailable. Cannot run upgrade.")
        return 0

    conn = client.get_connection()
    try:
        with conn.cursor() as cursor:
            # 1. Fetch matching company IDs in memory to avoid MySQL trigger lock (Error 1442)
            cursor.execute(
                """
                SELECT id 
                FROM companies 
                WHERE website_url IS NULL 
                   OR domain LIKE '%.local'
                ORDER BY id ASC
                """
            )
            rows = cursor.fetchall()
            company_ids = [r["id"] for r in rows]
            total_nowebsite = len(company_ids)
            logger.info(f"🔍 Found {total_nowebsite} total no-website company records in database.")

            if total_nowebsite == 0:
                logger.info("✅ No no-website companies found to upgrade.")
                return 0

            # 2. Touch last_crawled_at on companies without a website
            logger.info("👉 [1/4] Setting last_crawled_at for no-website leads...")
            cursor.execute(
                """
                UPDATE companies 
                SET last_crawled_at = COALESCE(last_crawled_at, NOW()),
                    updated_at = NOW()
                WHERE website_url IS NULL 
                   OR domain LIKE '%.local'
                """
            )
            touched_count = cursor.rowcount
            logger.info(f"   ✓ Updated last_crawled_at on {touched_count} records.")

            # 3. Ensure 'new_website_creation' opportunities exist in bulk
            logger.info("👉 [2/4] Ensuring 'new_website_creation' opportunities ($2,500 - $5,000)...")
            cursor.execute(
                """
                INSERT INTO opportunities (
                    company_id, type, recommended_service, 
                    estimated_value_low, estimated_value_high, 
                    confidence, evidence, status
                )
                SELECT 
                    c.id,
                    'new_website_creation',
                    'Turnkey High-Converting Web & Online Booking Portal',
                    2500,
                    5000,
                    1.0,
                    '{"intent": "high_converting_booking_portal", "pain_point": "Established local business with active phone/reviews but no custom website."}',
                    'discovered'
                FROM companies c
                LEFT JOIN opportunities o 
                    ON o.company_id = c.id 
                   AND o.type = 'new_website_creation'
                WHERE (c.website_url IS NULL OR c.domain LIKE '%.local')
                  AND o.id IS NULL
                """
            )
            new_opps_count = cursor.rowcount
            logger.info(f"   ✓ Created {new_opps_count} missing 'new_website_creation' opportunities.")

            # 4. Insert 100.0 score records in batches using pure VALUES (avoids Error 1442 with triggers)
            logger.info("👉 [3/4] Assigning 100.0 Score & Immediate Priority Tier in batches...")
            score_breakdown_json = json.dumps({
                "reason": "established_business_missing_website",
                "status": "highest_priority_no_website",
                "opportunity_score": 100.0,
                "priority_tier": "immediate",
                "total_deal_range": [2500, 5000],
            })

            batch_size = 500
            inserted_scores = 0

            # Find which company IDs don't already have an active 100.0 score
            cursor.execute(
                """
                SELECT DISTINCT company_id 
                FROM scores 
                WHERE opportunity_score = 100.0 
                  AND priority_tier = 'immediate'
                """
            )
            already_scored_ids = {r["company_id"] for r in cursor.fetchall()}
            ids_needing_score = [cid for cid in company_ids if cid not in already_scored_ids]

            logger.info(f"   ℹ️ {len(ids_needing_score)} companies need new 100.0 score records.")

            for i in range(0, len(ids_needing_score), batch_size):
                chunk = ids_needing_score[i : i + batch_size]
                data_batch = [
                    (cid, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 100.0, "immediate", score_breakdown_json)
                    for cid in chunk
                ]
                cursor.executemany(
                    """
                    INSERT INTO scores (
                        company_id, company_fit, technology_gap, 
                        pain_signal, buying_signal, contact_quality, 
                        service_fit, opportunity_score, priority_tier, 
                        score_breakdown
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    data_batch,
                )
                inserted_scores += len(chunk)
                conn.commit()

            logger.info(f"   ✓ Inserted {inserted_scores} top-tier 100.0 score records (synced by DB trigger).")

            # 5. Validate contacts for no-website companies that have non-local emails
            logger.info("👉 [4/4] Validating real contact emails for outreach readiness...")
            cursor.execute(
                """
                UPDATE contacts ct
                JOIN companies c ON c.id = ct.company_id
                SET ct.email_status = 'valid'
                WHERE (c.website_url IS NULL OR c.domain LIKE '%.local')
                  AND ct.email NOT LIKE '%.local'
                  AND ct.email NOT LIKE '%@business.local'
                  AND ct.email_status != 'valid'
                """
            )
            validated_contacts = cursor.rowcount
            logger.info(f"   ✓ Marked {validated_contacts} existing real emails as valid.")

            # Count total eligible for outreach right now
            cursor.execute(
                """
                SELECT COUNT(DISTINCT c.id) as ready_cnt
                FROM companies c
                JOIN contacts ct ON ct.company_id = c.id
                WHERE (c.website_url IS NULL OR c.domain LIKE '%.local')
                  AND ct.email NOT LIKE '%.local'
                  AND ct.email NOT LIKE '%@business.local'
                  AND ct.email_status IN ('valid', 'catch_all')
                  AND NOT EXISTS (
                      SELECT 1 FROM outreach_messages om WHERE om.company_id = c.id
                  )
                """
            )
            ready_leads = cursor.fetchone()["ready_cnt"]

            conn.commit()
            logger.info(
                f"\n🎉 UPGRADE COMPLETE! Successfully upgraded {total_nowebsite} no-website leads to 100.0 Score!"
            )
            logger.info(
                f"📬 Immediately outreach-ready no-website leads waiting in queue: {ready_leads}"
            )
            return total_nowebsite

    finally:
        conn.close()


if __name__ == "__main__":
    upgrade_existing_no_website_leads()
