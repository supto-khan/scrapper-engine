#!/usr/bin/env python3
"""
IMAP Reply Fetcher ($0 Setup)
Uses Python's standard library `imaplib` and `email` to poll mail.nexidant.com:993/SSL,
parse incoming replies, match them with opportunities/companies, and sync into outreach_messages.
Works out-of-the-box on every server without requiring compiled PHP extensions.
"""

import email
from email.header import decode_header
import imaplib
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Any
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from outreach.bounce.bounce_detector import get_bounce_detector
from outreach.replies.intent_classifier import get_intent_classifier
from shared.mysql_client import get_mysql_client
from shared.pipeline_monitor import get_pipeline_monitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


def clean_header_str(val: Any) -> str:
    if not val:
        return ""
    if not isinstance(val, (str, bytes)):
        return str(val)
    try:
        if isinstance(val, bytes):
            val = val.decode("utf-8", errors="ignore")
        decoded_parts = decode_header(val)
        out = []
        for part, enc in decoded_parts:
            if isinstance(part, bytes):
                out.append(part.decode(enc or "utf-8", errors="ignore"))
            else:
                out.append(str(part))
        return "".join(out).strip()
    except Exception:
        return str(val).strip()


def extract_body(msg: email.message.Message) -> str:
    body = ""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                cdispo = str(part.get("Content-Disposition"))
                if ctype == "text/plain" and "attachment" not in cdispo:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
                        break
                elif ctype == "text/html" and not body and "attachment" not in cdispo:
                    payload = part.get_payload(decode=True)
                    if payload:
                        body = payload.decode(part.get_content_charset() or "utf-8", errors="ignore")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body = payload.decode(msg.get_content_charset() or "utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"Error extracting email body: {e}")

    return body.strip()


def sync_imap_replies() -> int:
    host = os.getenv("IMAP_HOST", os.getenv("SMTP_HOST", "mail.nexidant.com"))
    port = int(os.getenv("IMAP_PORT", "993"))
    user = (os.getenv("IMAP_USERNAME") or os.getenv("SMTP_USER") or "info@nexidant.com").strip().strip("'\"")
    password = (os.getenv("IMAP_PASSWORD") or os.getenv("SMTP_PASSWORD") or "").strip().strip("'\"")

    logger.info(f"📥 Connecting to IMAP server ({host}:{port}/SSL) for {user}...")

    try:
        mail = imaplib.IMAP4_SSL(host, port)
        mail.login(user, password)
        mail.select("INBOX")
    except Exception as e:
        logger.error(f"❌ Failed to connect to IMAP server: {e}")
        return 0

    # Search for emails in the last 7 days
    date_since = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
    status, messages = mail.search(None, f'(SINCE "{date_since}")')

    if status != "OK" or not messages[0]:
        logger.info("✅ No new incoming messages found in the last 7 days.")
        try:
            mail.close()
            mail.logout()
        except Exception:
            pass
        return 0

    email_ids = messages[0].split()
    # Check latest 30 messages
    if len(email_ids) > 30:
        email_ids = email_ids[-30:]

    logger.info(f"✓ Checking {len(email_ids)} recent messages. Parsing replies...")

    mysql_client = get_mysql_client()
    synced_count = 0

    with mysql_client.get_connection() as conn:
        with conn.cursor() as cur:
            for e_id in email_ids:
                try:
                    # Fast header peek
                    res, msg_data = mail.fetch(e_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT MESSAGE-ID IN-REPLY-TO DATE)])")
                    if res != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                        continue

                    header_raw = msg_data[0][1]
                    header_msg = email.message_from_bytes(header_raw)

                    from_header = clean_header_str(header_msg.get("From"))
                    sender_email = email.utils.parseaddr(from_header)[1].lower()

                    # Skip messages from our own mailbox
                    if not sender_email or sender_email == user.lower():
                        continue

                    message_id = (header_msg.get("Message-ID") or "").strip("<>")
                    subject = clean_header_str(header_msg.get("Subject"))
                    in_reply_to = (header_msg.get("In-Reply-To") or "").strip("<>")

                    date_tuple = email.utils.parsedate_tz(header_msg.get("Date"))
                    if date_tuple:
                        sent_at = datetime.fromtimestamp(email.utils.mktime_tz(date_tuple)).strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        sent_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # Check duplicate
                    if message_id:
                        cur.execute("SELECT id FROM outreach_messages WHERE message_id = %s LIMIT 1", (message_id,))
                        if cur.fetchone():
                            continue
                    else:
                        cur.execute(
                            "SELECT id FROM outreach_messages WHERE sender_email = %s AND subject = %s AND sent_at = %s LIMIT 1",
                            (sender_email, subject, sent_at),
                        )
                        if cur.fetchone():
                            continue

                    # Fetch full body only for new incoming replies
                    b_res, b_data = mail.fetch(e_id, "(RFC822)")
                    body = ""
                    if b_res == "OK" and b_data and isinstance(b_data[0], tuple):
                        full_msg = email.message_from_bytes(b_data[0][1])
                        body = extract_body(full_msg)

                    # Match with contact/company
                    cur.execute("SELECT id, company_id FROM contacts WHERE email = %s LIMIT 1", (sender_email,))
                    contact_row = cur.fetchone()
                    contact_id = contact_row["id"] if contact_row else None
                    company_id = contact_row["company_id"] if contact_row else None

                    if not company_id:
                        domain = sender_email.split("@")[-1] if "@" in sender_email else ""
                        if domain:
                            cur.execute("SELECT id FROM companies WHERE domain LIKE %s LIMIT 1", (f"%{domain}%",))
                            comp_row = cur.fetchone()
                            if comp_row:
                                company_id = comp_row["id"]

                    matched_opportunity_id = None
                    if in_reply_to:
                        cur.execute(
                            "SELECT id, company_id, contact_id, opportunity_id FROM outreach_messages WHERE message_id = %s LIMIT 1",
                            (in_reply_to,),
                        )
                        orig = cur.fetchone()
                        if orig:
                            matched_opportunity_id = orig.get("opportunity_id")
                            if not company_id:
                                company_id = orig.get("company_id")
                            if not contact_id:
                                contact_id = orig.get("contact_id")

                    # Classify Reply Intent
                    intent_classifier = get_intent_classifier()
                    intent_result = intent_classifier.classify(subject=subject, body_text=body)
                    reply_intent = intent_result.get("intent", "unknown")
                    intent_conf = intent_result.get("confidence", 0.5)

                    # Insert into outreach_messages with intent
                    cur.execute(
                        """
                        INSERT INTO outreach_messages 
                        (company_id, contact_id, opportunity_id, sender_email, recipient_email, channel, direction, subject, body_text, status, reply_intent, intent_confidence, message_id, in_reply_to, sent_at, created_at)
                        VALUES (%s, %s, %s, %s, %s, 'email', 'inbound', %s, %s, 'delivered', %s, %s, %s, %s, %s, NOW())
                        """,
                        (company_id, contact_id, matched_opportunity_id, sender_email, user, subject, body, reply_intent, intent_conf, message_id, in_reply_to, sent_at),
                    )

                    # CRM Action based on intent
                    monitor = get_pipeline_monitor()
                    bounce_detector = get_bounce_detector()

                    if reply_intent == "positive_interest":
                        if company_id:
                            cur.execute(
                                "UPDATE opportunities SET status = 'in_discussion' WHERE company_id = %s AND status != 'converted'",
                                (company_id,),
                            )
                        # Instant Hot Lead Alert
                        monitor._send_alert(
                            title=f"🔥 HOT LEAD: Positive Reply from {sender_email}",
                            message=(
                                f"Company #{company_id or 'N/A'} replied with positive intent!\n"
                                f"Subject: {subject}\n"
                                f"Snippet: {intent_result.get('snippet', '')[:200]}\n"
                                f"Check CRM to follow up immediately."
                            ),
                            severity="critical",
                        )
                        logger.info(f"   🔥 HOT LEAD detected from {sender_email} ({reply_intent})")

                    elif reply_intent == "not_interested":
                        if company_id:
                            cur.execute(
                                "UPDATE opportunities SET status = 'closed_lost' WHERE company_id = %s AND status != 'converted'",
                                (company_id,),
                            )
                        # Auto-suppress to avoid future emails
                        bounce_detector._suppress_email(sender_email)
                        logger.info(f"   🛑 Unsubscribe / decline detected from {sender_email} — auto-suppressed")

                    elif reply_intent == "neutral_question":
                        if company_id:
                            cur.execute(
                                "UPDATE opportunities SET status = 'in_discussion' WHERE company_id = %s AND status != 'converted'",
                                (company_id,),
                            )
                        logger.info(f"   💬 Question/inquiry from {sender_email}")

                    else:
                        logger.info(f"   📨 Reply from {sender_email} (intent: {reply_intent})")

                    conn.commit()
                    synced_count += 1

                except Exception as ex:
                    logger.error(f"Error parsing message {e_id}: {ex}")

    try:
        mail.close()
        mail.logout()
    except Exception:
        pass

    logger.info(f"🎉 IMAP check complete. Synced {synced_count} new incoming messages.")
    return synced_count


if __name__ == "__main__":
    from typing import Any
    sync_imap_replies()
