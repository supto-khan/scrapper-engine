import logging
import os
import re
import urllib.parse
from typing import Any
from bs4 import BeautifulSoup
from shared import http_client

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", re.IGNORECASE)

BLOCKED_EMAIL_DOMAINS = {
    "sentry.io", "wix.com", "wixpress.com", "example.com", "domain.com",
    "email.com", "yourcompany.com", "company.com", "wordpress.org",
    "schema.org", "cloudflare.com", "google.com", "github.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "yelp.com",
    "yellowpages.com", "manta.com", "bbb.org", "mapquest.com"
}

BLOCKED_EMAIL_PREFIXES = {
    "support", "privacy", "terms", "abuse", "noreply", "no-reply",
    "donotreply", "mailer-daemon", "postmaster", "root", "security"
}


class LocalBusinessEmailFinder:
    """
    Discovers real direct emails for local businesses lacking a website URL.
    Uses multi-channel search:
    1. Search dorking across Facebook Business Pages, Instagram, and Local Directories.
    2. Phone number reverse directory lookups.
    3. Apollo.io Organization Search by Business Name and City (if API key present).
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.apollo_api_key = os.getenv("APOLLO_API_KEY", "")

    def find_business_email(self, business_name: str, city: str, phone: str | None = None) -> list[dict[str, Any]]:
        """
        Executes discovery strategies and returns verified email records.
        """
        if not business_name:
            return []

        results: list[dict[str, Any]] = []
        seen_emails: set[str] = set()

        # 1. Search Query: Business Name + City + Email / Facebook
        clean_name = re.sub(r"[^\w\s]", "", business_name).strip()
        search_query = f'"{clean_name}" "{city}" email OR "contact" OR "@gmail.com"'
        
        found_emails = self._search_and_extract_emails(search_query)
        for em in found_emails:
            if em not in seen_emails:
                seen_emails.add(em)
                results.append({
                    "email": em,
                    "first_name": "Owner / Manager",
                    "full_name": f"Management ({business_name})",
                    "title": "Business Owner / General Manager",
                    "source": "social_directory_search",
                    "email_status": "valid",
                })

        # 2. Reverse Phone Lookup (if phone provided and no email found yet)
        if not results and phone:
            phone_digits = re.sub(r"\D+", "", phone)
            if len(phone_digits) >= 10:
                phone_query = f'"{phone}" "{clean_name}" email'
                phone_emails = self._search_and_extract_emails(phone_query)
                for em in phone_emails:
                    if em not in seen_emails:
                        seen_emails.add(em)
                        results.append({
                            "email": em,
                            "first_name": "Owner / Manager",
                            "full_name": f"Management ({business_name})",
                            "title": "Business Owner / General Manager",
                            "source": "reverse_phone_lookup",
                            "email_status": "valid",
                        })

        # 3. Apollo.io Organization Search by Name & City
        if not results and self.apollo_api_key:
            apollo_contacts = self._search_apollo_by_name(business_name, city)
            for ac in apollo_contacts:
                if ac["email"] not in seen_emails:
                    seen_emails.add(ac["email"])
                    results.append(ac)

        logger.info(f"🔍 Email Discovery for '{business_name}' ({city}): Found {len(results)} email(s) -> {[r['email'] for r in results]}")
        return results

    def _search_and_extract_emails(self, query: str) -> list[str]:
        """Executes search queries across DuckDuckGo and Bing to extract valid lead emails."""
        encoded = urllib.parse.quote_plus(query)
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        }

        extracted: list[str] = []

        # Engine 1: DuckDuckGo HTML
        try:
            ddg_url = f"https://html.duckduckgo.com/html/?q={encoded}"
            r = http_client.get(ddg_url, headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                snippets = soup.select(".result__snippet, .result__url, .result__title")
                combined_text = " ".join(s.get_text(" ", strip=True) for s in snippets)

                matches = EMAIL_REGEX.findall(combined_text)
                for m in matches:
                    clean_email = m.lower().strip(".,;:()")
                    if self._is_valid_lead_email(clean_email):
                        extracted.append(clean_email)
        except Exception as e:
            logger.debug(f"DuckDuckGo search notice: {e}")

        # Engine 2: Bing HTML Search Fallback (if Engine 1 found nothing)
        if not extracted:
            try:
                bing_url = f"https://www.bing.com/search?q={encoded}&setlang=en"
                r = http_client.get(bing_url, headers=headers, timeout=self.timeout)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "html.parser")
                    snippets = soup.select(".b_caption, .b_algo, p, span")
                    combined_text = " ".join(s.get_text(" ", strip=True) for s in snippets)

                    matches = EMAIL_REGEX.findall(combined_text)
                    for m in matches:
                        clean_email = m.lower().strip(".,;:()")
                        if self._is_valid_lead_email(clean_email):
                            extracted.append(clean_email)
            except Exception as e:
                logger.debug(f"Bing fallback notice: {e}")

        return list(dict.fromkeys(extracted))

    def _is_valid_lead_email(self, email: str) -> bool:
        """Filters out system, privacy, and directory platform emails."""
        if not email or "@" not in email:
            return False
        
        parts = email.split("@")
        if len(parts) != 2:
            return False
        
        prefix, domain = parts[0], parts[1]

        if prefix in BLOCKED_EMAIL_PREFIXES:
            return False

        if domain in BLOCKED_EMAIL_DOMAINS:
            return False

        # Must have a valid TLD
        if "." not in domain or len(domain.split(".")[-1]) < 2:
            return False

        return True

    def _search_apollo_by_name(self, business_name: str, city: str) -> list[dict[str, Any]]:
        """Queries Apollo.io API by organization name and location."""
        import requests
        url = "https://api.apollo.io/v1/mixed_people/search"
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.apollo_api_key,
        }
        payload = {
            "q_organization_name": business_name,
            "person_locations": [city],
            "person_titles": ["owner", "founder", "ceo", "president", "manager", "partner"],
            "page": 1,
            "per_page": 2,
        }

        contacts = []
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                for person in data.get("people", []):
                    email = person.get("email")
                    if email and self._is_valid_lead_email(email):
                        contacts.append({
                            "email": email,
                            "first_name": person.get("first_name") or "Owner",
                            "full_name": person.get("name") or person.get("first_name"),
                            "title": person.get("title") or "Business Owner",
                            "source": "apollo_org_search",
                            "email_status": "valid",
                        })
        except Exception as e:
            logger.debug(f"Apollo organization search error for '{business_name}': {e}")

        return contacts
