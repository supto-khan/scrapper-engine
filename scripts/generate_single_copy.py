#!/usr/bin/env python3
"""
Nexidant Signal - Single Company Copy Generator CLI
Generates personalized outreach copy on demand for a single company/contact using Qwen3.5-0.8B (or template fallback).
Outputs JSON to stdout for easy consumption by Laravel / PHP.
"""

import json
import os
import sys

# Add signal-engine directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
engine_dir = os.path.dirname(current_dir)
if engine_dir not in sys.path:
    sys.path.insert(0, engine_dir)

from outreach.personalization.copy_generator import get_copy_generator
from shared.mysql_client import get_mysql_client


def generate_copy_for_company(company_id: int, contact_id: int | None = None, segment: str = "laravel_modernization"):
    client = get_mysql_client()
    copy_gen = get_copy_generator()

    with client.get_connection() as conn:
        with conn.cursor() as cursor:
            # Fetch company data
            cursor.execute("SELECT id, name, domain, industry FROM companies WHERE id = %s", (company_id,))
            company_row = cursor.fetchone()
            if not company_row:
                print(json.dumps({"error": f"Company #{company_id} not found"}))
                return

            # Fetch contact data
            if contact_id:
                cursor.execute(
                    "SELECT id, full_name, first_name, email, title, email_status FROM contacts WHERE id = %s",
                    (contact_id,),
                )
            else:
                cursor.execute(
                    "SELECT id, full_name, first_name, email, title, email_status FROM contacts WHERE company_id = %s LIMIT 1",
                    (company_id,),
                )
            contact_row = cursor.fetchone() or {
                "id": None,
                "full_name": "Decision Maker",
                "first_name": "there",
                "email": f"contact@{company_row['domain']}",
                "title": "Executive",
                "email_status": "unverified",
            }

            # Fetch tech and audit data
            cursor.execute("SELECT cms, frontend_stack, ttfb_ms, evidence FROM technologies WHERE company_id = %s ORDER BY id DESC LIMIT 1", (company_id,))
            tech_row = cursor.fetchone() or {}

            cursor.execute("SELECT performance_score, lcp_ms FROM audits WHERE company_id = %s ORDER BY id DESC LIMIT 1", (company_id,))
            audit_row = cursor.fetchone() or {}

            res = copy_gen.generate_message(
                segment=segment,
                company_data=company_row,
                contact_data=contact_row,
                tech_fingerprint=tech_row,
                audit_metrics=audit_row,
                step=1,
            )

            print(json.dumps(res))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Usage: generate_single_copy.py <company_id> [contact_id] [segment]"}))
        sys.exit(1)

    c_id = int(sys.argv[1])
    ct_id = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != "null" else None
    seg = sys.argv[3] if len(sys.argv) > 3 else "laravel_modernization"

    generate_copy_for_company(c_id, ct_id, seg)
