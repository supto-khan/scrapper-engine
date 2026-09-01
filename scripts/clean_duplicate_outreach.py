#!/usr/bin/env python3
"""
Nexidant Signal - Database Cleanup Utility for Outreach Messages
Removes duplicate queued messages and cleans up repeated staging records so
that no company or recipient email receives duplicate emails.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mysql_client import get_mysql_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("clean_duplicate_outreach")


def clean_duplicate_outreach_records():
    logger.info("🧹 Starting Duplicate Outreach Message Cleanup...")
    client = get_mysql_client()
    if not client.ping():
        logger.warning("Database unavailable. Cannot clean records.")
        return

    with client.get_connection() as conn:
        with conn.cursor() as cursor:
            # 1. Delete queued messages for companies that already received a delivered/sent message
            cleanup_sent_sql = """
                DELETE om_queued FROM outreach_messages om_queued
                JOIN (
                    SELECT DISTINCT company_id 
                    FROM outreach_messages 
                    WHERE direction = 'outbound' 
                      AND status IN ('sent', 'delivered', 'opened', 'clicked', 'replied')
                ) already_sent ON om_queued.company_id = already_sent.company_id
                WHERE om_queued.status = 'queued'
            """
            cursor.execute(cleanup_sent_sql)
            removed_already_sent = cursor.rowcount
            logger.info(f"   ✓ Removed {removed_already_sent} queued messages for companies that were already emailed.")

            # 2. Delete duplicate queued messages for the same company (keep lowest ID)
            cleanup_dup_company_sql = """
                DELETE om1 FROM outreach_messages om1
                INNER JOIN outreach_messages om2 
                WHERE om1.id > om2.id 
                  AND om1.company_id = om2.company_id 
                  AND om1.status = 'queued' 
                  AND om2.status = 'queued'
                  AND om1.direction = 'outbound'
                  AND om2.direction = 'outbound'
            """
            cursor.execute(cleanup_dup_company_sql)
            removed_dup_companies = cursor.rowcount
            logger.info(f"   ✓ Removed {removed_dup_companies} redundant duplicate queued messages for the same companies.")

            # 3. Delete duplicate queued messages for the same recipient email (keep lowest ID)
            cleanup_dup_email_sql = """
                DELETE om1 FROM outreach_messages om1
                INNER JOIN outreach_messages om2 
                WHERE om1.id > om2.id 
                  AND om1.recipient_email = om2.recipient_email 
                  AND om1.recipient_email IS NOT NULL 
                  AND om1.recipient_email != ''
                  AND om1.status = 'queued' 
                  AND om2.status = 'queued'
            """
            cursor.execute(cleanup_dup_email_sql)
            removed_dup_emails = cursor.rowcount
            logger.info(f"   ✓ Removed {removed_dup_emails} redundant queued messages for identical recipient emails.")

            # 4. Delete duplicate opportunities for the same company (keep lowest ID)
            cleanup_dup_opp_sql = """
                DELETE o1 FROM opportunities o1
                INNER JOIN opportunities o2 
                WHERE o1.id > o2.id 
                  AND o1.company_id = o2.company_id 
                  AND o1.type = o2.type
            """
            cursor.execute(cleanup_dup_opp_sql)
            removed_dup_opps = cursor.rowcount
            logger.info(f"   ✓ Removed {removed_dup_opps} redundant duplicate opportunity records.")

            # 5. Delete duplicate company records sharing identical names / local domains (keep lowest ID)
            cleanup_dup_companies_sql = """
                DELETE c1 FROM companies c1
                INNER JOIN companies c2 
                WHERE c1.id > c2.id 
                  AND (
                      (c1.domain LIKE '%.local' AND c2.domain LIKE '%.local' AND LOWER(TRIM(c1.name)) = LOWER(TRIM(c2.name)))
                      OR (LOWER(TRIM(c1.name)) = LOWER(TRIM(c2.name)) AND c1.source = 'google_maps' AND c2.source = 'google_maps')
                      OR (c1.domain LIKE '%.local' AND c2.domain NOT LIKE '%.local' AND LOWER(TRIM(c1.name)) = LOWER(TRIM(c2.name)))
                  )
            """
            cursor.execute(cleanup_dup_companies_sql)
            removed_dup_company_rows = cursor.rowcount
            logger.info(f"   ✓ Removed {removed_dup_company_rows} redundant duplicate company records (e.g. repeated local/map leads).")

            # 6. Delete all queued outreach messages with .local synthetic addresses
            cleanup_local_outreach_sql = """
                DELETE FROM outreach_messages 
                WHERE recipient_email LIKE '%.local' 
                   OR recipient_email LIKE '%@business.local'
                   OR company_id IN (SELECT id FROM companies WHERE domain LIKE '%.local')
            """
            cursor.execute(cleanup_local_outreach_sql)
            removed_local_outreach = cursor.rowcount
            logger.info(f"   ✓ Purged {removed_local_outreach} invalid .local outreach messages from the queue.")

            # 7. Delete synthetic .local contacts
            cleanup_local_contacts_sql = """
                DELETE FROM contacts 
                WHERE email LIKE '%.local' 
                   OR email LIKE '%@business.local'
            """
            cursor.execute(cleanup_local_contacts_sql)
            removed_local_contacts = cursor.rowcount
            logger.info(f"   ✓ Purged {removed_local_contacts} synthetic .local contact records.")

            conn.commit()
            total_cleaned = removed_already_sent + removed_dup_companies + removed_dup_emails + removed_dup_opps + removed_dup_company_rows + removed_local_outreach + removed_local_contacts
            logger.info(f"🎉 Cleanup completed! Total redundant records purged: {total_cleaned}")


if __name__ == "__main__":
    clean_duplicate_outreach_records()
