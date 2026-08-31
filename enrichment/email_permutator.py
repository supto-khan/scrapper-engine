import logging
import re
from typing import Any

from enrichment.email_validator import EmailValidator, get_email_validator

logger = logging.getLogger(__name__)


class EmailPermutator:
    """
    Synthesizes standard corporate email permutations for discovered executives:
    - first@domain
    - first.last@domain
    - f.last@domain
    - flast@domain
    - last@domain
    Validates candidates via MX syntax & SMTP deliverability checks.
    """

    def __init__(self, validator: EmailValidator | None = None):
        self.validator = validator or get_email_validator()

    def generate_permutations(self, first_name: str, last_name: str, domain: str) -> list[str]:
        clean_domain = domain.lower().replace("http://", "").replace("https://", "").strip().strip("/")
        fn = re.sub(r"[^a-zA-Z]", "", first_name).lower()
        ln = re.sub(r"[^a-zA-Z]", "", last_name).lower() if last_name else ""

        if not fn:
            return []

        candidates = []
        if fn and ln:
            candidates.extend([
                f"{fn}.{ln}@{clean_domain}",
                f"{fn}@{clean_domain}",
                f"{fn[0]}{ln}@{clean_domain}",
                f"{fn[0]}.{ln}@{clean_domain}",
                f"{ln}.{fn}@{clean_domain}",
            ])
        else:
            candidates.append(f"{fn}@{clean_domain}")

        return candidates

    def synthesize_verified_contacts(
        self,
        executives: list[dict[str, Any]],
        domain: str,
    ) -> list[dict[str, Any]]:
        clean_domain = domain.lower().replace("http://", "").replace("https://", "").strip().strip("/")
        verified_contacts = []

        for exec_info in executives:
            fn = exec_info.get("first_name", "")
            ln = exec_info.get("last_name", "")
            full_name = exec_info.get("full_name") or f"{fn} {ln}".strip()
            title = exec_info.get("title", "Executive / Founder")

            candidates = self.generate_permutations(fn, ln, clean_domain)
            for email in candidates:
                # Validate syntax and MX
                val = self.validator.validate(email)
                if val.get("status") in ["valid", "catch_all"]:
                    verified_contacts.append({
                        "full_name": full_name,
                        "first_name": fn,
                        "last_name": ln,
                        "title": title,
                        "role_category": "executive",
                        "email": email,
                        "email_score": val.get("score", 75.0),
                        "verification_source": f"permutator_{val.get('source', 'mx')}",
                        "linkedin_url": exec_info.get("linkedin_url"),
                        "source": "email_permutator",
                        "raw_contact_data": {
                            "domain": clean_domain,
                            "original_title": title,
                        },
                    })
                    logger.info(f"Synthesized MX-verified executive email {email} for {full_name} ({domain})")
                    break  # Found best candidate for this executive

        return verified_contacts


def get_email_permutator() -> EmailPermutator:
    return EmailPermutator()
