import logging
from datetime import datetime, timezone
from typing import Any

from enrichment.email_validator import get_email_validator
from outreach.personalization.copy_generator import get_copy_generator
from outreach.segmentation.segment_rules import get_lead_segmenter
from shared.mysql_client import get_mysql_client
from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Warm-up schedule: days since first send → max emails allowed per day
WARMUP_SCHEDULE = [
    (3, 5),      # Day 1-3:  max 5/day
    (7, 15),     # Day 4-7:  max 15/day
    (14, 30),    # Day 8-14: max 30/day
    (999999, 50),  # Day 15+: max 50/day
]


class OutreachQueueManager:
    """
    Manages staging and queuing of personalized outreach emails.
    Enforces CAN-SPAM compliance, deduplication, suppression list checks,
    daily warm-up rate limiting, and pre-send email verification.
    """

    def __init__(self):
        self.mysql = get_mysql_client()
        self.segmenter = get_lead_segmenter()
        self.copy_gen = get_copy_generator()
        self.email_validator = get_email_validator()
        self.redis = get_redis_client()
        self.suppression_list: set[str] = set()

    def add_to_suppression(self, email: str):
        """Adds an email or domain to the suppression list."""
        self.suppression_list.add(email.lower().strip())

    def _get_daily_send_count(self) -> int:
        """Returns the number of outreach messages staged today."""
        today_key = f"outreach:daily_sent:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        try:
            count = self.redis.client.get(today_key)
            return int(count) if count else 0
        except Exception:
            return 0

    def _increment_daily_send_count(self):
        """Increments today's staged outreach count in Redis with 48h TTL."""
        today_key = f"outreach:daily_sent:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
        try:
            pipe = self.redis.client.pipeline()
            pipe.incr(today_key)
            pipe.expire(today_key, 172800)  # 48h TTL
            pipe.execute()
        except Exception as e:
            logger.warning(f"Failed to increment daily send count: {e}")

    def _get_daily_limit(self) -> int:
        """
        Calculates today's send limit based on warm-up schedule.
        Uses Redis key 'outreach:warmup_start_date' to track when warm-up began.
        """
        try:
            start_date_str = self.redis.client.get("outreach:warmup_start_date")
            if not start_date_str:
                # First time — set warm-up start date
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                self.redis.client.set("outreach:warmup_start_date", today)
                start_date_str = today

            if isinstance(start_date_str, bytes):
                start_date_str = start_date_str.decode("utf-8")

            start_date = datetime.strptime(start_date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            days_active = (datetime.now(timezone.utc) - start_date).days + 1

            for max_days, limit in WARMUP_SCHEDULE:
                if days_active <= max_days:
                    return limit

            return WARMUP_SCHEDULE[-1][1]

        except Exception as e:
            logger.warning(f"Warm-up schedule lookup failed, using conservative limit: {e}")
            return 5  # Conservative fallback

    def _is_daily_limit_reached(self) -> bool:
        """Check if we've hit today's warm-up send limit."""
        current = self._get_daily_send_count()
        limit = self._get_daily_limit()
        if current >= limit:
            logger.warning(
                f"🛑 Daily warm-up limit reached: {current}/{limit} emails staged today. "
                f"Pausing outreach to protect sender reputation."
            )
            return True
        return False

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

        # Check warm-up daily limit BEFORE processing any contacts
        if self._is_daily_limit_reached():
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

            # Re-check limit before each contact (in case we hit it mid-loop)
            if self._is_daily_limit_reached():
                break

            # Only stage deliverable contacts (valid or catch_all)
            if contact.get("email_status") not in ["valid", "catch_all", "unverified"]:
                logger.info(
                    f"Skipping undeliverable contact {email} (status: {contact.get('email_status')})"
                )
                continue

            # Check in-memory suppression
            if email in self.suppression_list:
                logger.info(f"Skipping suppressed email {email}")
                continue

            # Check Redis-backed bounce suppression set
            if email and self.redis and self.redis.client and self.redis.client.sismember("outreach:suppressed_emails", email):
                logger.info(f"⛔ Skipping bounce-suppressed email {email}")
                continue

            # Pre-send email verification gate
            if email:
                validation = self.email_validator.validate(email)
                if not validation.get("is_deliverable", True):
                    logger.info(
                        f"⛔ Skipping unverified email {email} — "
                        f"reason: {validation.get('reason', 'unknown')} "
                        f"(source: {validation.get('source', 'unknown')})"
                    )
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
                subject_variant=msg_data.get("subject_variant", "A"),
            )
            created_message_ids.append(msg_id)
            self._increment_daily_send_count()
            logger.info(
                f"Staged outreach message #{msg_id} for {contact['full_name']} ({email}) at {company_data.get('domain')}"
            )

        return created_message_ids


def get_queue_manager() -> OutreachQueueManager:
    return OutreachQueueManager()
