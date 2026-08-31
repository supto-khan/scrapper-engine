import logging
import re
from typing import Any
import requests

logger = logging.getLogger(__name__)


class RdapContactFinder:
    """
    Zero-Cost Domain Registry (RDAP / WHOIS) Contact Harvester.
    Queries the official ICANN/RDAP protocol (https://rdap.org) to extract:
    - Domain Administrative Contact Email
    - Technical Contact Email
    - Registrant Name & Organization
    """

    EMAIL_REGEX = re.compile(
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", re.IGNORECASE
    )

    PRIVACY_KEYWORDS = {
        "privacy", "proxy", "whoisguard", "redacted", "withheld",
        "domainsbyproxy", "superprivacy", "contactprivacy", "identityprotect",
        "anonymouse", "cloudflareregistrar", "abuse@"
    }

    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SignalEngine-RDAP-Harvester/1.0",
            "Accept": "application/rdap+json, application/json",
        })

    def find_rdap_contacts(self, domain: str) -> list[dict[str, Any]]:
        clean_domain = domain.lower().replace("http://", "").replace("https://", "").strip().strip("/")
        contacts = []

        try:
            url = f"https://rdap.org/domain/{clean_domain}"
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                entities = data.get("entities", [])
                
                for entity in entities:
                    roles = entity.get("roles", [])
                    vcard = entity.get("vcardArray", [])
                    
                    name = None
                    email = None
                    
                    if len(vcard) > 1 and isinstance(vcard[1], list):
                        for field in vcard[1]:
                            if isinstance(field, list) and len(field) >= 4:
                                field_type = field[0]
                                field_val = field[3]
                                if field_type == "fn" and field_val:
                                    name = str(field_val).strip()
                                elif field_type == "email" and field_val:
                                    email = str(field_val).strip().lower()

                    # Filter out proxy / privacy emails
                    if email and not any(pk in email for pk in self.PRIVACY_KEYWORDS):
                        role_title = " / ".join(roles).title() if roles else "Domain Administrator"
                        name_str = name if name and not any(pk in name.lower() for pk in self.PRIVACY_KEYWORDS) else f"{clean_domain.split('.')[0].capitalize()} Admin"
                        parts = name_str.split()
                        first_name = parts[0]
                        last_name = parts[-1] if len(parts) > 1 else ""

                        contacts.append({
                            "full_name": name_str,
                            "first_name": first_name,
                            "last_name": last_name,
                            "title": role_title,
                            "role_category": "administrative",
                            "email": email,
                            "email_score": 80.0,
                            "verification_source": "rdap_registry",
                            "linkedin_url": None,
                            "source": "rdap_contact_finder",
                            "raw_contact_data": {
                                "domain": clean_domain,
                                "roles": roles,
                            },
                        })
                        logger.info(f"Discovered RDAP registry contact {email} ({name_str}) for {domain}")
        except Exception as e:
            logger.debug(f"RDAP lookup failed for {domain}: {e}")

        return contacts


def get_rdap_contact_finder() -> RdapContactFinder:
    return RdapContactFinder()
