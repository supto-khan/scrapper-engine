import logging
from typing import Any

from outreach.personalization.copy_generator import get_copy_generator
from outreach.segmentation.segment_rules import get_lead_segmenter
from shared.mysql_client import get_mysql_client

logger = logging.getLogger(__name__)


class OutreachQueueManager:
    """
    Manages staging and queuing of personalized outreach emails.
    Enforces CAN-SPAM compliance, deduplication, and suppression list checks.
    """

    def __init__(self):
        self.mysql = get_mysql_client()
        self.segmenter = get_lead_segmenter()
        self.copy_gen = get_copy_generator()
        self.suppression_list: set[str] = set()

    def add_to_suppression(self, email: str):
        """Adds an email or domain to the suppression list."""
        self.suppression_list.add(email.lower().strip())

    def stage_outreach_for_company(
        self,
        company_data: dict[str, Any],
        contacts: list[dict[str, Any]],
        tech_fingerprint: dict[str, Any] | None = None,
        audit_metrics: dict[str, Any] | None = None,
        signals: list[dict[str, Any]] | None = None,
        opportunities: list[dict[str, Any]] | None = None,
        campaign_id: int | None = None,
    ) -> list[int]:
        """
        Generates and stages personalized outreach messages for valid decision-maker contacts.
        Returns list of created message IDs.
        """
        company_id = company_data["id"]
        created_message_ids = []

        if not contacts:
            return []

        # 1. Determine Lead Segment
        segment = self.segmenter.segment_lead(
            company_data=company_data,
            tech_fingerprint=tech_fingerprint,
            opportunities=opportunities,
            signals=signals,
        )

        for contact in contacts:
            email = contact.get("email", "").lower().strip()
            # Only stage deliverable contacts (valid or catch_all)
            if contact.get("email_status") not in ["valid", "catch_all", "unverified"]:
                logger.info(
                    f"Skipping undeliverable contact {email} (status: {contact.get('email_status')})"
                )
                continue

            # Check suppression
            if email in self.suppression_list:
                logger.info(f"Skipping suppressed email {email}")
                continue

            # Check database for existing outreach to avoid sending duplicate emails
            if self.mysql.has_existing_outreach(
                company_id=company_id, contact_id=contact.get("id"), email=email
            ):
                logger.info(
                    f"Skipping contact {email} at company #{company_id} — outreach already exists or was sent."
                )
                continue

            # 2. Generate personalized copy
            msg_data = self.copy_gen.generate_message(
                segment=segment,
                company_data=company_data,
                contact_data=contact,
                tech_fingerprint=tech_fingerprint,
                audit_metrics=audit_metrics,
                signals=signals,
                opportunities=opportunities,
            )

            # 3. Save to database outreach queue (staged for review/export)
            evidence_snapshot = {
                "segment": segment,
                "tech_cms": (tech_fingerprint or {}).get("cms"),
                "frontend_stack": (tech_fingerprint or {}).get("frontend_stack"),
                "opportunities_count": len(opportunities or []),
            }

            msg_id = self.mysql.save_outreach_message(
                company_id=company_id,
                contact_id=contact["id"],
                subject=msg_data["subject"],
                body_text=msg_data["body_text"],
                campaign_id=campaign_id,
                status="queued",
                evidence_snapshot=evidence_snapshot,
            )
            created_message_ids.append(msg_id)
            logger.info(
                f"Staged outreach message #{msg_id} for {contact['full_name']} ({email}) at {company_data.get('domain')}"
            )

        return created_message_ids


def get_queue_manager() -> OutreachQueueManager:
    return OutreachQueueManager()
