import logging
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()
from enrichment.decision_engine import DecisionEngine
from enrichment.disposable_checker import DISPOSABLE_DOMAINS, is_disposable_email
from enrichment.role_checker import is_role_account
from enrichment.smtp_verifier import SmtpVerifier, get_smtp_verifier
from enrichment.syntax_checker import validate_email_syntax

logger = logging.getLogger(__name__)


class EmailValidator:
    """
    Multi-Tier Email Verification Pipeline.
    Coordinates RFC syntax validation, disposable domain filtering, role-based account detection,
    DNS MX resolution, and self-hosted SMTP handshake verification via DecisionEngine.
    """

    EMAIL_REGEX = re.compile(
        r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    )
    DISPOSABLE_DOMAINS = DISPOSABLE_DOMAINS

    def __init__(
        self,
        zerobounce_key: str | None = None,
        timeout: int = 10,
        enable_smtp_handshake: bool = True,
        smtp_verifier: SmtpVerifier | None = None,
    ):
        self.zerobounce_key = zerobounce_key or os.getenv("ZEROBOUNCE_API_KEY") or None
        self.timeout = timeout
        self.enable_smtp_handshake = enable_smtp_handshake
        self.smtp_verifier = smtp_verifier or get_smtp_verifier()

    def has_mx_records(self, domain: str) -> bool:
        """
        Checks if a domain has valid DNS MX (Mail Exchange) records configured.
        Falls back to RFC 5321 A-record resolution if no explicit MX records exist.
        """
        if not domain or "." not in domain:
            return False

        clean_dom = domain.lower().strip().removeprefix("www.")
        try:
            records = self.smtp_verifier.get_mx_records(clean_dom)
            if records:
                return True
        except Exception:
            pass

        # Fallback: RFC 5321 implicit MX (check if domain has standard A record resolving)
        try:
            import socket

            socket.gethostbyname(clean_dom)
            return True
        except Exception:
            return False

    def validate(self, email: str) -> dict[str, Any]:
        """
        Executes the staged email verification pipeline:
        1. RFC 5321/5322 Syntax Intelligence
        2. Disposable / Burner Domain Detection
        3. Role-based Account Detection (admin@, support@, etc.)
        4. DNS MX Mail Exchanger Verification
        5. Commercial API / Self-Hosted SMTP Handshake Verification
        6. DecisionEngine Synthesis (status, sub_status, confidence score)
        """
        # 1. Syntax Intelligence
        syntax_valid, syntax_err = validate_email_syntax(email)
        if not syntax_valid:
            return DecisionEngine.evaluate(
                email=email,
                syntax_valid=False,
                syntax_error=syntax_err,
            )

        domain = email.split("@")[-1].lower().strip()

        # 2. Disposable Email Filter
        if is_disposable_email(domain):
            return DecisionEngine.evaluate(
                email=email,
                syntax_valid=True,
                is_disposable=True,
            )

        # 3. Role Account Detection
        is_role, role_prefix = is_role_account(email)

        # 4. Verify DNS MX records
        has_mx = self.has_mx_records(domain)
        if not has_mx:
            return DecisionEngine.evaluate(
                email=email,
                syntax_valid=True,
                is_disposable=False,
                is_role=is_role,
                role_prefix=role_prefix,
                has_mx=False,
                mx_error=f"Domain {domain} has no active mail servers",
            )

        # 5. Third-Party Commercial Verification API (if configured)
        if self.zerobounce_key:
            return self._verify_zerobounce(email, is_role=is_role, role_prefix=role_prefix)

        # 6. Self-Hosted Free SMTP Handshake Verification
        if self.enable_smtp_handshake:
            try:
                smtp_res = self.smtp_verifier.verify_mailbox(email)
                return DecisionEngine.evaluate(
                    email=email,
                    syntax_valid=True,
                    is_disposable=False,
                    is_role=is_role,
                    role_prefix=role_prefix,
                    has_mx=True,
                    smtp_result=smtp_res,
                )
            except Exception as e:
                logger.debug(f"SMTP handshake error for {email}: {e}")

        # 7. Baseline DNS MX Verified fallback
        return DecisionEngine.evaluate(
            email=email,
            syntax_valid=True,
            is_disposable=False,
            is_role=is_role,
            role_prefix=role_prefix,
            has_mx=True,
        )

    def _verify_zerobounce(
        self,
        email: str,
        is_role: bool = False,
        role_prefix: str | None = None,
    ) -> dict[str, Any]:
        url = "https://api.zerobounce.net/v2/validate"
        params = {
            "api_key": self.zerobounce_key,
            "email": email,
        }
        try:
            response = requests.get(url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                data = response.json()
                zb_status = (data.get("status") or "").lower()
                is_valid = zb_status == "valid"
                status = "valid" if is_valid else ("catch_all" if zb_status == "catch-all" else "invalid")
                sub_status = "role_account" if (is_valid and is_role) else (data.get("sub_status") or zb_status)
                return {
                    "email": email,
                    "status": status,
                    "sub_status": sub_status,
                    "score": float(data.get("score", 85.0) if is_valid else 0.0),
                    "confidence": float(data.get("score", 85.0) if is_valid else 0.0),
                    "is_deliverable": is_valid or zb_status == "catch-all",
                    "is_role_account": is_role,
                    "is_disposable": False,
                    "source": "zerobounce",
                    "reason": data.get("sub_status") or zb_status,
                    "smtp_code": None,
                }
        except Exception as e:
            logger.warning(f"ZeroBounce verification failed for {email}: {e}")

        return {
            "email": email,
            "status": "unknown",
            "sub_status": "fallback",
            "score": 70.0,
            "confidence": 70.0,
            "is_deliverable": True,
            "is_role_account": is_role,
            "is_disposable": False,
            "source": "fallback",
            "reason": "ZeroBounce API error fallback",
            "smtp_code": None,
        }


def get_email_validator() -> EmailValidator:
    return EmailValidator()
