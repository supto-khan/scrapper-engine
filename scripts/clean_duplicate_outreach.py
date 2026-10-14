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
            # Optimized grouped query to avoid full-table quadratic O(N^2) Cartesian self-join
            cleanup_dup_companies_sql = """
                DELETE c FROM companies c
                INNER JOIN (
                    SELECT LOWER(TRIM(name)) as norm_name, MIN(id) as min_id
                    FROM companies
                    WHERE (domain LIKE '%.local' OR source = 'google_maps')
                      AND name IS NOT NULL AND TRIM(name) != ''
                    GROUP BY LOWER(TRIM(name))
                    HAVING COUNT(*) > 1
                ) dups ON LOWER(TRIM(c.name)) = dups.norm_name AND c.id > dups.min_id
                WHERE (c.domain LIKE '%.local' OR c.source = 'google_maps')
            """
            cursor.execute(cleanup_dup_companies_sql)
            removed_dup_company_rows = cursor.rowcount
            logger.info(f"   ✓ Removed {removed_dup_company_rows} redundant duplicate company records (e.g. repeated local/map leads).")

            # 6. Delete all queued outreach messages with invalid, synthetic, or foreign-government recipient addresses
            cleanup_local_outreach_sql = """
                DELETE FROM outreach_messages 
                WHERE recipient_email LIKE '%.local' 
                   OR recipient_email LIKE '%@business.local'
                   OR recipient_email LIKE '%@%.local'
                   OR recipient_email LIKE '%.gov%'
                   OR recipient_email LIKE '%.mil%'
                   OR recipient_email LIKE '%.edu%'
                   OR recipient_email LIKE '%.sg'
                   OR recipient_email LIKE '%.fi'
                   OR recipient_email LIKE '%.co.nz'
                   OR recipient_email LIKE '%.com.hk'
                   OR recipient_email LIKE '%.com.au'
                   OR recipient_email LIKE '%@qq.com'
                   OR recipient_email LIKE '%@163.com'
                   OR recipient_email LIKE '%@126.com'
                   OR recipient_email LIKE '%@realtor.com'
                   OR recipient_email LIKE '%@cpadirectory.com'
                   OR recipient_email LIKE '%@yellowpages.com'
                   OR recipient_email LIKE '%@yelp.com'
                   OR recipient_email LIKE '%@angi.com'
                   OR recipient_email LIKE '%@thumbtack.com'
                   OR recipient_email LIKE '%@angelone.in'
                   OR recipient_email LIKE '%@remax.com'
                   OR recipient_email LIKE '%@wxxi.org'
                   OR recipient_email LIKE '%@digitalrealty.com'
            """
            cursor.execute(cleanup_local_outreach_sql)
            removed_local_outreach = cursor.rowcount
            logger.info(f"   ✓ Purged {removed_local_outreach} invalid/junk outreach messages from the queue.")

            # 7. Delete synthetic .local contacts and mark junk addresses as invalid
            cleanup_local_contacts_sql = """
                DELETE FROM contacts 
                WHERE email LIKE '%.local' 
                   OR email LIKE '%@business.local'
                   OR email LIKE '%@%.local'
            """
            cursor.execute(cleanup_local_contacts_sql)
            removed_local_contacts = cursor.rowcount
            logger.info(f"   ✓ Purged {removed_local_contacts} synthetic .local contact records.")

            invalidate_junk_contacts_sql = """
                UPDATE contacts SET email_status = 'invalid'
                WHERE email_status != 'invalid'
                  AND (
                      email LIKE '%.gov%'
                      OR email LIKE '%.mil%'
                      OR email LIKE '%.edu%'
                      OR email LIKE '%.sg'
                      OR email LIKE '%.fi'
                      OR email LIKE '%.co.nz'
                      OR email LIKE '%.com.hk'
                      OR email LIKE '%.com.au'
                      OR email LIKE '%@qq.com'
                      OR email LIKE '%@163.com'
                      OR email LIKE '%@126.com'
                      OR email LIKE '%@realtor.com'
                      OR email LIKE '%@cpadirectory.com'
                      OR email LIKE '%@yellowpages.com'
                      OR email LIKE '%@yelp.com'
                      OR email LIKE '%@angi.com'
                      OR email LIKE '%@thumbtack.com'
                      OR email LIKE '%@angelone.in'
                      OR email LIKE '%@remax.com'
                      OR email LIKE '%@wxxi.org'
                      OR email LIKE '%@digitalrealty.com'
                  )
            """
            cursor.execute(invalidate_junk_contacts_sql)
            invalidated_contacts = cursor.rowcount
            if invalidated_contacts > 0:
                logger.info(f"   ✓ Flagged {invalidated_contacts} junk/foreign contacts as invalid.")

            conn.commit()
            total_cleaned = removed_already_sent + removed_dup_companies + removed_dup_emails + removed_dup_opps + removed_dup_company_rows + removed_local_outreach + removed_local_contacts
            logger.info(f"🎉 Cleanup completed! Total redundant records purged: {total_cleaned}")


if __name__ == "__main__":
    clean_duplicate_outreach_records()
