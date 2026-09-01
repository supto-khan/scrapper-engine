"""
Nexidant Signal Engine — Bounce Detection & Auto-Suppression

Scans IMAP inbox for Delivery Status Notifications (DSN) and
auto-suppress hard-bounced emails to protect sender reputation.

Hard bounce codes (5.x.x / 550+):
  → mailbox doesn't exist, domain dead, permanently undeliverable
  → Auto-suppresses immediately

Soft bounce codes (4.x.x / 4xx):
  → mailbox full, temporarily unavailable, greylisting
  → After 3 soft bounces on the same email → promoted to hard bounce

Spam complaints:
  → Treated as hard bounce → immediate suppression
"""

import email
import email.utils
import imaplib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from typing import Any

from dotenv import load_dotenv

from shared.mysql_client import get_mysql_client
from shared.redis_client import get_redis_client

load_dotenv()
logger = logging.getLogger(__name__)

# Redis set key for permanently suppressed emails
SUPPRESSED_SET_KEY = "outreach:suppressed_emails"

# DSN status code patterns
HARD_BOUNCE_CODES = re.compile(r"5\.\d+\.\d+")
SOFT_BOUNCE_CODES = re.compile(r"4\.\d+\.\d+")

# Common SMTP response codes indicating hard bounces
HARD_SMTP_PATTERNS = [
    "550",
    "551",
    "552",
    "553",
    "554",
    "user unknown",
    "mailbox not found",
    "does not exist",
    "no such user",
    "address rejected",
    "invalid recipient",
    "recipient rejected",
    "unknown user",
    "undeliverable",
    "account disabled",
    "account has been disabled",
    "mailbox unavailable",
]

# Patterns indicating spam complaints
COMPLAINT_PATTERNS = [
    "abuse",
    "spam complaint",
    "feedback report",
    "complaint",
    "marked as spam",
    "junk mail",
]

# Max soft bounces before promoting to hard bounce
MAX_SOFT_BOUNCES = 3


def _clean_header(val: Any) -> str:
    """Decode an email header value to a clean string."""
    if not val:
        return ""
    try:
        if isinstance(val, bytes):
            val = val.decode("utf-8", errors="ignore")
        decoded = decode_header(str(val))
        parts = []
        for part, enc in decoded:
            if isinstance(part, bytes):
                parts.append(part.decode(enc or "utf-8", errors="ignore"))
            else:
                parts.append(str(part))
        return "".join(parts).strip()
    except Exception:
        return str(val).strip()


class BounceDetector:
    """
    Scans IMAP inbox for bounce notifications and auto-suppresses
    hard-bounced emails from future outreach.
    """

    def __init__(self):
        self.mysql = get_mysql_client()
        self.redis = get_redis_client()

        self.imap_host = os.getenv("IMAP_HOST", os.getenv("SMTP_HOST", "mail.nexidant.com"))
        self.imap_port = int(os.getenv("IMAP_PORT", "993"))
        self.imap_user = (
            os.getenv("IMAP_USERNAME") or os.getenv("SMTP_USER") or "info@nexidant.com"
        ).strip().strip("'\"")
        self.imap_password = (
            os.getenv("IMAP_PASSWORD") or os.getenv("SMTP_PASSWORD") or ""
        ).strip().strip("'\"")

    def scan_and_suppress(self, days_back: int = 7) -> dict[str, int]:
        """
        Main entry point: scan IMAP for bounces and suppress hard bounces.
        Returns summary counts.
        """
        stats = {
            "messages_scanned": 0,
            "hard_bounces": 0,
            "soft_bounces": 0,
            "complaints": 0,
            "emails_suppressed": 0,
            "promotions": 0,  # soft → hard after MAX_SOFT_BOUNCES
        }

        try:
            mail = imaplib.IMAP4_SSL(self.imap_host, self.imap_port)
            mail.login(self.imap_user, self.imap_password)
            mail.select("INBOX")
        except Exception as e:
            logger.error(f"❌ Bounce detector: IMAP connection failed: {e}")
            return stats

        try:
            date_since = (datetime.now() - timedelta(days=days_back)).strftime("%d-%b-%Y")
            status, messages = mail.search(None, f'(SINCE "{date_since}")')

            if status != "OK" or not messages[0]:
                logger.info("✅ Bounce detector: No messages to scan.")
                return stats

            email_ids = messages[0].split()
            if len(email_ids) > 100:
                email_ids = email_ids[-100:]

            logger.info(f"🔍 Bounce detector: Scanning {len(email_ids)} messages for bounces...")

            for e_id in email_ids:
                stats["messages_scanned"] += 1
                try:
                    bounce_info = self._check_message_for_bounce(mail, e_id)
                    if not bounce_info:
                        continue

                    bounce_type = bounce_info["bounce_type"]
                    bounced_email = bounce_info["email"]

                    if bounce_type == "hard_bounce":
                        stats["hard_bounces"] += 1
                    elif bounce_type == "soft_bounce":
                        stats["soft_bounces"] += 1
                    elif bounce_type == "complaint":
                        stats["complaints"] += 1

                    # Record bounce event
                    self._record_bounce_event(bounce_info)

                    # Auto-suppress hard bounces and complaints
                    if bounce_type in ("hard_bounce", "complaint"):
                        suppressed = self._suppress_email(bounced_email)
                        if suppressed:
                            stats["emails_suppressed"] += 1

                    # Check soft bounce promotion threshold
                    elif bounce_type == "soft_bounce":
                        soft_count = self._get_soft_bounce_count(bounced_email)
                        if soft_count >= MAX_SOFT_BOUNCES:
                            logger.warning(
                                f"🔄 Promoting {bounced_email} to hard bounce "
                                f"({soft_count} soft bounces reached threshold)"
                            )
                            suppressed = self._suppress_email(bounced_email)
                            if suppressed:
                                stats["emails_suppressed"] += 1
                                stats["promotions"] += 1

                except Exception as ex:
                    logger.warning(f"Error processing message {e_id}: {ex}")

        finally:
            try:
                mail.close()
                mail.logout()
            except Exception:
                pass

        logger.info(
            f"🎯 Bounce scan complete: "
            f"{stats['hard_bounces']} hard, {stats['soft_bounces']} soft, "
            f"{stats['complaints']} complaints | "
            f"{stats['emails_suppressed']} emails suppressed"
        )
        return stats

    def _check_message_for_bounce(self, mail, e_id) -> dict[str, Any] | None:
        """
        Fetches an email and checks if it's a bounce/DSN notification.
        Returns bounce info dict or None if not a bounce.
        """
        res, msg_data = mail.fetch(e_id, "(RFC822)")
        if res != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
            return None

        msg = email.message_from_bytes(msg_data[0][1])
        from_addr = _clean_header(msg.get("From", "")).lower()
        subject = _clean_header(msg.get("Subject", "")).lower()
        content_type = msg.get_content_type() or ""

        # Check if this is a DSN message
        is_dsn = (
            "delivery" in subject
            or "undeliverable" in subject
            or "returned" in subject
            or "failure" in subject
            or "bounce" in subject
            or "mailer-daemon" in from_addr
            or "postmaster" in from_addr
            or content_type == "multipart/report"
        )

        if not is_dsn:
            # Check for complaint patterns
            is_complaint = any(p in subject or p in from_addr for p in COMPLAINT_PATTERNS)
            if not is_complaint:
                return None

        # Extract the original recipient email from the bounce message
        bounced_email = self._extract_bounced_email(msg)
        if not bounced_email:
            return None

        # Skip if it's our own outbox address
        if bounced_email == self.imap_user.lower():
            return None

        # Determine bounce type
        body = self._get_message_body(msg)
        dsn_code = self._extract_dsn_code(msg, body)
        bounce_type = self._classify_bounce(dsn_code, body, subject, from_addr)

        # Match to our outreach message
        in_reply_to = (msg.get("In-Reply-To") or "").strip("<>")
        original_message_id = self._match_outreach_message(bounced_email, in_reply_to)

        return {
            "email": bounced_email,
            "bounce_type": bounce_type,
            "dsn_code": dsn_code,
            "raw_reason": body[:500] if body else subject,
            "original_message_id": original_message_id,
        }

    def _extract_bounced_email(self, msg: email.message.Message) -> str | None:
        """Extract the original recipient email from a bounce notification."""
        # 1. Check DSN report parts
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "message/delivery-status":
                    dsn_text = str(part.get_payload())
                    # Look for "Final-Recipient:" or "Original-Recipient:"
                    match = re.search(
                        r"(?:Final-Recipient|Original-Recipient):\s*(?:rfc822;?)?\s*(\S+@\S+)",
                        dsn_text,
                        re.IGNORECASE,
                    )
                    if match:
                        return match.group(1).lower().strip("<>")

        # 2. Check common bounce message patterns in body
        body = self._get_message_body(msg)
        if body:
            # Pattern: "Delivery to the following recipient failed:" or "... <email@domain>"
            patterns = [
                r"(?:delivery to|message to|sent to|recipient)[:\s]*<?(\S+@\S+\.\w+)>?",
                r"<(\S+@\S+\.\w+)>",
                r"(\S+@\S+\.\w+)\s+(?:failed|rejected|undeliverable)",
            ]
            for pattern in patterns:
                match = re.search(pattern, body, re.IGNORECASE)
                if match:
                    addr = match.group(1).lower().strip("<>.,;")
                    # Skip our own address
                    if addr != self.imap_user.lower():
                        return addr

        # 3. Fallback: check To header (for auto-replies that went to our sent address)
        to_header = _clean_header(msg.get("To", ""))
        addr = email.utils.parseaddr(to_header)[1].lower()
        if addr and addr != self.imap_user.lower() and "@" in addr:
            return addr

        return None

    def _extract_dsn_code(self, msg: email.message.Message, body: str) -> str | None:
        """Extract DSN status code (e.g. 5.1.1) from the bounce message."""
        # Check DSN parts
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "message/delivery-status":
                    dsn_text = str(part.get_payload())
                    match = re.search(r"Status:\s*(\d\.\d+\.\d+)", dsn_text, re.IGNORECASE)
                    if match:
                        return match.group(1)

        # Check body
        if body:
            match = re.search(r"(\d\.\d+\.\d+)", body)
            if match:
                return match.group(1)

        return None

    def _classify_bounce(
        self, dsn_code: str | None, body: str, subject: str, from_addr: str
    ) -> str:
        """Classify bounce as hard_bounce, soft_bounce, or complaint."""
        combined = f"{body} {subject} {from_addr}".lower()

        # Check for complaints first
        if any(p in combined for p in COMPLAINT_PATTERNS):
            return "complaint"

        # DSN code classification
        if dsn_code:
            if HARD_BOUNCE_CODES.match(dsn_code):
                return "hard_bounce"
            if SOFT_BOUNCE_CODES.match(dsn_code):
                return "soft_bounce"

        # SMTP pattern matching
        if any(p in combined for p in HARD_SMTP_PATTERNS):
            return "hard_bounce"

        # Soft bounce indicators
        soft_patterns = ["mailbox full", "quota", "temporarily", "try again", "greylisted"]
        if any(p in combined for p in soft_patterns):
            return "soft_bounce"

        # Default to unknown → treat as soft
        return "soft_bounce"

    def _get_message_body(self, msg: email.message.Message) -> str:
        """Extract plain text body from an email message."""
        body = ""
        try:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            charset = part.get_content_charset() or "utf-8"
                            body = payload.decode(charset, errors="ignore")
                            break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    charset = msg.get_content_charset() or "utf-8"
                    body = payload.decode(charset, errors="ignore")
        except Exception:
            pass
        return body.strip()

    # ─── Database Operations ──────────────────────────────────────────────

    def _record_bounce_event(self, bounce_info: dict[str, Any]):
        """Insert a bounce event into the bounce_events table."""
        conn = self.mysql.get_connection()
        try:
            bounced_email = bounce_info["email"]

            # Resolve contact & company
            contact_id = None
            company_id = None
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, company_id FROM contacts WHERE email = %s LIMIT 1",
                    (bounced_email,),
                )
                row = cur.fetchone()
                if row:
                    contact_id = row["id"]
                    company_id = row["company_id"]

                # Check for duplicate bounce event
                cur.execute(
                    """
                    SELECT id FROM bounce_events
                    WHERE email = %s AND bounce_type = %s AND detected_at > DATE_SUB(NOW(), INTERVAL 1 DAY)
                    LIMIT 1
                    """,
                    (bounced_email, bounce_info["bounce_type"]),
                )
                if cur.fetchone():
                    return  # Already recorded recently

                cur.execute(
                    """
                    INSERT INTO bounce_events
                    (contact_id, company_id, email, bounce_type, dsn_code, raw_reason, original_message_id, suppressed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        contact_id,
                        company_id,
                        bounced_email,
                        bounce_info["bounce_type"],
                        bounce_info.get("dsn_code"),
                        bounce_info.get("raw_reason", "")[:2000],
                        bounce_info.get("original_message_id"),
                        1 if bounce_info["bounce_type"] in ("hard_bounce", "complaint") else 0,
                    ),
                )
        finally:
            conn.close()

    def _suppress_email(self, email_addr: str) -> bool:
        """
        Suppress an email: add to Redis set, update contacts table,
        and update any queued outreach messages.
        Returns True if newly suppressed.
        """
        email_addr = email_addr.lower().strip()

        # Add to Redis suppression set
        newly_added = self.redis.client.sadd(SUPPRESSED_SET_KEY, email_addr)

        if newly_added:
            logger.info(f"🛑 Suppressed bounced email: {email_addr}")

            conn = self.mysql.get_connection()
            try:
                with conn.cursor() as cur:
                    # Update contact status
                    cur.execute(
                        "UPDATE contacts SET email_status = 'bounced' WHERE email = %s",
                        (email_addr,),
                    )

                    # Cancel any queued outreach to this email
                    cur.execute(
                        """
                        UPDATE outreach_messages
                        SET status = 'cancelled', error_message = 'Email hard-bounced — auto-suppressed'
                        WHERE recipient_email = %s AND status = 'queued'
                        """,
                        (email_addr,),
                    )
            finally:
                conn.close()

        return bool(newly_added)

    def _get_soft_bounce_count(self, email_addr: str) -> int:
        """Get total soft bounce count for an email."""
        conn = self.mysql.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) as cnt FROM bounce_events WHERE email = %s AND bounce_type = 'soft_bounce'",
                    (email_addr,),
                )
                row = cur.fetchone()
                return int(row["cnt"]) if row else 0
        finally:
            conn.close()

    def _match_outreach_message(self, email_addr: str, in_reply_to: str) -> int | None:
        """Try to match bounce to an original outreach message ID."""
        conn = self.mysql.get_connection()
        try:
            with conn.cursor() as cur:
                if in_reply_to:
                    cur.execute(
                        "SELECT id FROM outreach_messages WHERE message_id = %s LIMIT 1",
                        (in_reply_to,),
                    )
                    row = cur.fetchone()
                    if row:
                        return row["id"]

                # Fallback: find the most recent outbound message to this email
                cur.execute(
                    """
                    SELECT id FROM outreach_messages
                    WHERE recipient_email = %s AND direction = 'outbound'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (email_addr,),
                )
                row = cur.fetchone()
                return row["id"] if row else None
        finally:
            conn.close()

    def is_suppressed(self, email_addr: str) -> bool:
        """Check if an email is in the suppression set."""
        return bool(self.redis.client.sismember(SUPPRESSED_SET_KEY, email_addr.lower().strip()))


# ─── Module Accessor ──────────────────────────────────────────────────────

_bounce_detector: BounceDetector | None = None


def get_bounce_detector() -> BounceDetector:
    global _bounce_detector
    if _bounce_detector is None:
        _bounce_detector = BounceDetector()
    return _bounce_detector
