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


COMMON_MAIL_PROVIDERS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com",
    "icloud.com", "msn.com", "live.com", "comcast.net", "sbcglobal.net",
    "att.net", "verizon.net", "bellsouth.net", "cox.net", "charter.net",
    "zoho.com", "protonmail.com", "me.com", "mac.com", "ymail.com", "rocketmail.com",
    "earthlink.net", "roadrunner.com", "windstream.net", "frontier.com"
}

BLOCKED_LEAD_DOMAINS = {
    "example.com", "domain.com", "email.com", "yourcompany.com", "company.com",
    "sentry.io", "wix.com", "wixpress.com", "wordpress.org", "schema.org",
    "cloudflare.com", "github.com", "webcontainer-api.io",
    "realtor.com", "move.com", "cpadirectory.com", "yellowpages.com", "whitepages.com",
    "yelp.com", "angi.com", "angieslist.com", "thumbtack.com", "houzz.com",
    "homeadvisor.com", "bbb.org", "tripadvisor.com", "manta.com", "dnb.com",
    "zoominfo.com", "allbiz.com", "leadiq.com", "bumvar.com", "6bestrated.com",
    "citysquares.com", "breken.com", "facebook.com", "instagram.com", "linkedin.com",
    "twitter.com", "x.com", "youtube.com", "tiktok.com", "pinterest.com",
    "google.com", "bing.com", "duckduckgo.com", "qq.com", "163.com", "126.com", "sina.com",
    "angelone.in", "remax.com", "wxxi.org", "rs-event.sg", "digitalrealty.com",
}

BLOCKED_TLDS_AND_SUBSTRINGS = (
    ".local", ".localhost", ".internal", ".lan", ".corp", ".home", ".test", ".example", ".invalid",
    ".gov", ".mil", ".edu", ".ac.uk", ".gov.sg", ".edu.sg", ".org.sg", ".sg",
    ".fi", ".co.nz", ".com.hk", ".com.au", ".ru", ".cn", ".gov.", ".gob.",
    ".in", ".co.in", ".org.in", ".gov.in"
)

BLOCKED_PREFIXES = {
    "xxx", "test", "sample", "dummy", "exam", "noreply", "no-reply",
    "donotreply", "mailer-daemon", "postmaster", "root", "security",
    "abuse", "privacy", "terms", "admin", "webmaster"
}


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
    COMMON_MAIL_PROVIDERS = COMMON_MAIL_PROVIDERS
    BLOCKED_LEAD_DOMAINS = BLOCKED_LEAD_DOMAINS

    @classmethod
    def is_valid_lead_email(
        cls,
        email: str,
        company_name: str | None = None,
        company_domain: str | None = None,
        is_no_website: bool = False,
    ) -> tuple[bool, str]:
        """
        Guarantees lead email relevance, deliverability, and authenticity:
        - Blocks foreign government, municipal, academic, and disposable domains
        - Blocks synthetic .local and internal hostnames
        - Blocks platform/directory domains (realtor.com, cpadirectory.com, etc.)
        - For no-website leads: Verifies that custom business domains match the target business name
        """
        if not email or "@" not in email:
            return False, "missing_or_malformed"

        clean_email = email.lower().strip()
        if not cls.EMAIL_REGEX.match(clean_email):
            return False, "invalid_email_regex"

        parts = clean_email.split("@")
        if len(parts) != 2:
            return False, "invalid_format"

        prefix, domain = parts[0].strip(), parts[1].strip()

        if len(prefix) < 2 or prefix in BLOCKED_PREFIXES or prefix.startswith("helpdesk"):
            return False, f"blocked_prefix_{prefix}"

        if domain in BLOCKED_LEAD_DOMAINS:
            return False, f"blocked_domain_{domain}"

        if is_disposable_email(domain):
            return False, f"disposable_domain_{domain}"

        if any(domain.endswith(tld) or tld in domain for tld in BLOCKED_TLDS_AND_SUBSTRINGS):
            return False, f"blocked_tld_or_government_{domain}"

        # Common public providers (@gmail.com, @yahoo.com) are authentic personal/business inboxes
        if domain in COMMON_MAIL_PROVIDERS:
            return True, "valid_common_provider"

        is_no_web = is_no_website or (company_domain and company_domain.endswith(".local")) or (not company_domain)

        # If company has an official real website domain that matches email domain
        if company_domain and not company_domain.endswith(".local"):
            clean_comp_dom = company_domain.lower().replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0]
            if domain == clean_comp_dom:
                return True, "valid_company_domain"

        # For no-website leads with custom domains: strictly verify relevance to the business name
        if is_no_web and company_name:
            clean_company = re.sub(r"[^\w\s]", "", company_name.lower())
            stop_words = {
                "the", "and", "inc", "llc", "corp", "co", "ltd", "company", "group",
                "services", "specialists", "associates", "pc", "pa", "management",
                "auto", "care", "repair", "clinic", "center", "contractors", "law",
                "firm", "office", "dentistry", "plumbing", "roofing"
            }
            tokens = [t for t in clean_company.split() if len(t) >= 3 and t not in stop_words]

            domain_stem = domain.split(".")[0].lower()
            # If domain stem matches any company token or abbreviation (e.g. camlev for Campbell & Levine)
            has_match = (
                any(tok in domain_stem for tok in tokens)
                or any(domain_stem in tok for tok in tokens if len(domain_stem) >= 4)
                or any(tok.startswith(domain_stem[:3]) for tok in tokens if len(domain_stem) >= 3)
            )
            if not has_match and len(tokens) > 0:
                return False, f"custom_domain_mismatch_{domain_stem}_for_{clean_company}"

        return True, "valid_custom_domain"

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
