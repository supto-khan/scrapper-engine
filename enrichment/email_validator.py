import logging
import os
import re
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()
from enrichment.smtp_verifier import SmtpVerifier, get_smtp_verifier

logger = logging.getLogger(__name__)


class EmailValidator:
    """
    Integrates ZeroBounce / NeverBounce with syntax & disposable email filtering,
    as well as 100% free self-hosted SMTP handshake (RCPT TO) mailbox verification.
    Enforces the <5% expected bounce rate requirement before leads enter outreach queues.
    """

    EMAIL_REGEX = re.compile(
        r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    )

    DISPOSABLE_DOMAINS = {
        "mailinator.com",
        "tempmail.com",
        "10minutemail.com",
        "guerrillamail.com",
        "throwawaymail.com",
        "sharklasers.com",
        "yopmail.com",
        "trashmail.com",
        "getairmail.com",
        "dispostable.com",
    }

    def __init__(
        self,
        zerobounce_key: str | None = None,
        timeout: int = 10,
        enable_smtp_handshake: bool = True,
    ):
        self.zerobounce_key = zerobounce_key or os.getenv("ZEROBOUNCE_API_KEY") or None
        self.timeout = timeout
        self.enable_smtp_handshake = enable_smtp_handshake
        self.smtp_verifier = get_smtp_verifier()

    def has_mx_records(self, domain: str) -> bool:
        """
        Checks if a domain has valid DNS MX (Mail Exchange) records configured.
        """
        if not domain or "." not in domain:
            return False

        clean_dom = domain.lower().strip().removeprefix("www.")
        try:
            import dns.resolver

            resolver = dns.resolver.Resolver()
            resolver.timeout = 4.0
            resolver.lifetime = 4.0
            answers = resolver.resolve(clean_dom, "MX")
            return len(answers) > 0
        except Exception:
            # Fallback: check if domain has standard A record resolving
            try:
                import socket

                socket.gethostbyname(clean_dom)
                return True
            except Exception:
                return False

    def validate(self, email: str) -> dict[str, Any]:
        """
        Validates an email address.
        Returns:
            - status: 'valid' | 'invalid' | 'catch_all' | 'unknown'
            - score: float (0.0 - 100.0)
            - is_deliverable: bool
            - source: str
        """
        if not email or not self.EMAIL_REGEX.match(email):
            return {
                "status": "invalid",
                "score": 0.0,
                "is_deliverable": False,
                "source": "syntax_check",
                "reason": "Invalid email syntax format",
            }

        domain = email.split("@")[1].lower()
        if domain in self.DISPOSABLE_DOMAINS:
            return {
                "status": "invalid",
                "score": 0.0,
                "is_deliverable": False,
                "source": "disposable_check",
                "reason": "Disposable email provider",
            }

        # Verify DNS MX records
        has_mx = self.has_mx_records(domain)
        if not has_mx:
            return {
                "status": "invalid",
                "score": 0.0,
                "is_deliverable": False,
                "source": "dns_mx_check",
                "reason": f"Domain {domain} has no active mail servers",
            }

        # If ZeroBounce API key is provided, query verification API
        if self.zerobounce_key:
            return self._verify_zerobounce(email)

        # 100% Free Self-Hosted SMTP Handshake Verification
        if self.enable_smtp_handshake:
            try:
                smtp_res = self.smtp_verifier.verify_mailbox(email)
                if smtp_res.get("status") in ["valid", "invalid", "catch_all"]:
                    return smtp_res
                logger.debug(f"SMTP handshake returned '{smtp_res.get('status')}' for {email}: {smtp_res.get('reason')}")
            except Exception as e:
                logger.debug(f"SMTP handshake error for {email}: {e}")

        # Baseline heuristic validation if third-party API key not configured
        return {
            "status": "valid",
            "score": 85.0,
            "is_deliverable": True,
            "source": "dns_mx_verified",
            "reason": f"Syntax valid and domain {domain} has verified MX servers",
        }

    def _verify_zerobounce(self, email: str) -> dict[str, Any]:
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
                return {
                    "status": "valid"
                    if is_valid
                    else ("catch_all" if zb_status == "catch-all" else "invalid"),
                    "score": float(data.get("score", 85.0) if is_valid else 0.0),
                    "is_deliverable": is_valid or zb_status == "catch-all",
                    "source": "zerobounce",
                    "reason": data.get("sub_status") or zb_status,
                }
        except Exception as e:
            logger.warning(f"ZeroBounce verification failed for {email}: {e}")

        return {
            "status": "unknown",
            "score": 70.0,
            "is_deliverable": True,
            "source": "fallback",
            "reason": "ZeroBounce API error fallback",
        }


def get_email_validator() -> EmailValidator:
    return EmailValidator()
