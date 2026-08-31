#!/usr/bin/env python3
"""
Signal Engine — Lead Exporter (Phase 4 Full Pipeline Export)
Exports discovered companies, technologies, opportunity scores, priority tiers,
and primary enriched decision makers with verified emails.
"""

import csv
import logging
import os
import sys

# Ensure project root is in sys.path when running scripts directly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared.mysql_client import get_mysql_client

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("export_leads")


def export_leads(output_csv: str = "leads_export.csv", min_score: float = 0.0):
    mysql_client = get_mysql_client()
    if not mysql_client.ping():
        logger.error("Cannot connect to MySQL database.")
        sys.exit(1)

    conn = mysql_client.get_connection()
    try:
        with conn.cursor() as cursor:
            sql = """
            SELECT
                c.id,
                c.domain,
                c.name,
                c.source,
                c.industry,
                c.employee_count_estimate,
                c.website_url,
                t.cms,
                t.frontend_stack,
                t.backend_stack,
                t.https,
                t.hsts,
                t.ttfb_ms,
                s.opportunity_score,
                s.priority_tier,
                s.company_fit,
                s.technology_gap,
                s.pain_signal,
                s.buying_signal,
                ct.full_name as contact_name,
                ct.title as contact_title,
                ct.email as contact_email,
                ct.email_status as contact_email_status,
                c.created_at
            FROM companies c
            LEFT JOIN (
                SELECT * FROM technologies t1
                WHERE t1.id = (
                    SELECT MAX(t2.id) FROM technologies t2 WHERE t2.company_id = t1.company_id
                )
            ) t ON c.id = t.company_id
            LEFT JOIN (
                SELECT * FROM scores s1
                WHERE s1.id = (
                    SELECT MAX(s2.id) FROM scores s2 WHERE s2.company_id = s1.company_id
                )
            ) s ON c.id = s.company_id
            LEFT JOIN (
                SELECT * FROM contacts ct1
                WHERE ct1.id = (
                    SELECT MIN(ct2.id) FROM contacts ct2
                    WHERE ct2.company_id = ct1.company_id
                      AND ct2.email_status IN ('valid', 'catch_all', 'unverified')
                )
            ) ct ON c.id = ct.company_id
            WHERE COALESCE(s.opportunity_score, 0) >= %s
            ORDER BY COALESCE(s.opportunity_score, 0) DESC, c.id DESC
            """
            cursor.execute(sql, (min_score,))
            rows = cursor.fetchall()

        with open(output_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "Company ID",
                    "Domain",
                    "Name",
                    "Priority Tier",
                    "Opportunity Score",
                    "Decision Maker Name",
                    "Decision Maker Title",
                    "Verified Email",
                    "Email Status",
                    "Company Fit",
                    "Tech Gap",
                    "Pain Signal",
                    "Buying Signal",
                    "Source",
                    "Industry",
                    "Employees",
                    "CMS",
                    "Frontend Stack",
                    "Backend Stack",
                    "HTTPS",
                    "HSTS",
                    "TTFB (ms)",
                    "Discovered At",
                ]
            )
            for r in rows:
                writer.writerow(
                    [
                        r["id"],
                        r["domain"],
                        r["name"],
                        (r["priority_tier"] or "Unscored").upper(),
                        f"{r['opportunity_score']:.1f}"
                        if r["opportunity_score"] is not None
                        else "N/A",
                        r["contact_name"] or "",
                        r["contact_title"] or "",
                        r["contact_email"] or "",
                        (r["contact_email_status"] or "").upper(),
                        f"{r['company_fit']:.1f}"
                        if r["company_fit"] is not None
                        else "N/A",
                        f"{r['technology_gap']:.1f}"
                        if r["technology_gap"] is not None
                        else "N/A",
                        f"{r['pain_signal']:.1f}"
                        if r["pain_signal"] is not None
                        else "N/A",
                        f"{r['buying_signal']:.1f}"
                        if r["buying_signal"] is not None
                        else "N/A",
                        r["source"],
                        r["industry"] or "",
                        r["employee_count_estimate"] or "",
                        r["cms"] or "",
                        r["frontend_stack"] or "[]",
                        r["backend_stack"] or "[]",
                        "Yes" if r["https"] else "No",
                        "Yes" if r["hsts"] else "No",
                        r["ttfb_ms"] or "",
                        r["created_at"],
                    ]
                )
        logger.info(
            f"Successfully exported {len(rows)} leads with enrichment to {output_csv}"
        )
    finally:
        conn.close()


if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "leads_export.csv"
    export_leads(out_file)
