import logging
import os
import re
import urllib.parse
from typing import Any
from bs4 import BeautifulSoup
from shared import http_client
from enrichment.email_validator import get_email_validator

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", re.IGNORECASE)

BLOCKED_EMAIL_DOMAINS = {
    "sentry.io", "wix.com", "wixpress.com", "example.com", "domain.com",
    "email.com", "yourcompany.com", "company.com", "wordpress.org",
    "schema.org", "cloudflare.com", "google.com", "github.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "yelp.com",
    "yellowpages.com", "manta.com", "bbb.org", "mapquest.com", "tripadvisor.com",
    "angi.com", "angieslist.com", "thumbtack.com", "houzz.com", "homeadvisor.com",
    "dnb.com", "zoominfo.com", "allbiz.com", "leadiq.com", "bumvar.com", "6bestrated.com",
    "bing.com", "yahoo.com", "duckduckgo.com", "cambridge.org", "webcontainer-api.io",
}

BLOCKED_EMAIL_PREFIXES = {
    "support", "privacy", "terms", "abuse", "noreply", "no-reply",
    "donotreply", "mailer-daemon", "postmaster", "root", "security", "slick-carousel",
}

DIRECTORY_DOMAINS = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "yelp.com",
    "yellowpages.com", "manta.com", "bbb.org", "mapquest.com", "linkedin.com",
    "tripadvisor.com", "angieslist.com", "angi.com", "thumbtack.com", "houzz.com",
    "homeadvisor.com", "dnb.com", "zoominfo.com", "google.com", "apple.com",
    "youtube.com", "tiktok.com", "pinterest.com", "nextdoor.com", "chamberofcommerce.com",
    "wikipedia.org", "indeed.com", "glassdoor.com", "ziprecruiter.com", "allbiz.com",
    "yahoo.com", "bing.com", "duckduckgo.com", "leadiq.com", "bumvar.com", "6bestrated.com",
    "schema.org", "citysquares.com", "breken.com", "contractorfinder.bradfordwhite.com",
    "cambridge.org", "dictionary.cambridge.org", "webcontainer-api.io",
}

IGNORED_FILE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".js", ".css", ".ico", ".woff", ".woff2"
}


class LocalBusinessEmailFinder:
    """
    High-accuracy Multi-Engine Web Search & Enrichment for Leads lacking direct contact emails or websites.
    
    Capabilities:
    1. Multi-Engine Search Dorking (Yahoo, Bing, DuckDuckGo)
    2. Official Business Website Resolution & Validation
    3. Direct Website Scraping (/contact, /about, homepage)
    4. DNS MX Server Verification for domain-level deliverability
    5. Direct Public Email Extraction from Social Profiles & Directories (e.g. Gmail / Outlook / Yahoo business inboxes)
    6. Apollo.io API Fallback
    """

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.apollo_api_key = os.getenv("APOLLO_API_KEY", "")
        self.validator = get_email_validator()

    def find_business_website_and_email(
        self, business_name: str, city: str, phone: str | None = None
    ) -> dict[str, Any]:
        """
        Main entrypoint: Discovers official website, domain, and verified email contacts.
        Returns: {
            "website_url": str | None,
            "domain": str | None,
            "contacts": list[dict[str, Any]]
        }
        """
        if not business_name:
            return {"website_url": None, "domain": None, "contacts": []}

        clean_name = re.sub(r"[^\w\s]", "", business_name).strip()
        seen_emails: set[str] = set()
        contacts: list[dict[str, Any]] = []

        # 1. Multi-Engine Search
        search_query = f"{clean_name} {city} email OR contact"
        raw_snippets, candidate_websites = self._execute_search_queries(search_query)

        # 2. Extract direct emails from search snippets / social directory snippets
        snippet_emails = self._extract_clean_emails_from_text(raw_snippets)
        for em in snippet_emails:
            if em not in seen_emails and self._is_valid_lead_email(em):
                seen_emails.add(em)
                contacts.append({
                    "email": em,
                    "first_name": "Owner / Manager",
                    "full_name": f"Management ({business_name})",
                    "title": "Business Owner / General Manager",
                    "source": "search_engine_discovery",
                    "email_status": "valid",
                })

        # 3. Discover Best Official Website
        best_website = self._select_best_website(candidate_websites, clean_name)
        discovered_domain = None

        if best_website:
            discovered_domain = best_website.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].lower()
            logger.info(f"🌐 Discovered official website for '{business_name}' ({city}): {best_website} (Domain: {discovered_domain})")

            # 4. Scrape discovered website for direct contact info
            site_emails = self._scrape_website_contacts(best_website)
            for em in site_emails:
                if em not in seen_emails and self._is_valid_lead_email(em):
                    seen_emails.add(em)
                    contacts.append({
                        "email": em,
                        "first_name": "Owner / Manager",
                        "full_name": f"Management ({business_name})",
                        "title": "Business Owner / General Manager",
                        "source": "website_contact_page",
                        "email_status": "valid",
                    })

            # 5. If no direct email on website, check DNS MX records for canonical deliverable inbox
            if not contacts and self.validator.has_mx_records(discovered_domain):
                for role_inbox in ["contact", "info", "office", "service"]:
                    candidate_em = f"{role_inbox}@{discovered_domain}"
                    val = self.validator.validate(candidate_em)
                    if val.get("status") in ["valid", "catch_all"]:
                        seen_emails.add(candidate_em)
                        contacts.append({
                            "email": candidate_em,
                            "first_name": "Owner / Manager",
                            "full_name": f"Management ({business_name})",
                            "title": "Executive & General Inquiries",
                            "source": "dns_mx_verified",
                            "email_status": "valid",
                        })
                        break

        # 6. Reverse Phone Lookup (if still no emails found and phone available)
        if not contacts and phone:
            phone_query = f"{phone} {clean_name} email"
            phone_snippets, _ = self._execute_search_queries(phone_query)
            phone_emails = self._extract_clean_emails_from_text(phone_snippets)
            for em in phone_emails:
                if em not in seen_emails and self._is_valid_lead_email(em):
                    seen_emails.add(em)
                    contacts.append({
                        "email": em,
                        "first_name": "Owner / Manager",
                        "full_name": f"Management ({business_name})",
                        "title": "Business Owner / General Manager",
                        "source": "reverse_phone_lookup",
                        "email_status": "valid",
                    })

        # 7. Apollo.io fallback
        if not contacts and self.apollo_api_key:
            apollo_contacts = self._search_apollo_by_name(business_name, city)
            for ac in apollo_contacts:
                if ac["email"] not in seen_emails:
                    seen_emails.add(ac["email"])
                    contacts.append(ac)

        logger.info(
            f"🔍 Search Discovery for '{business_name}' ({city}): Website={best_website} | Found {len(contacts)} email(s) -> {[c['email'] for c in contacts]}"
        )
        return {
            "website_url": best_website,
            "domain": discovered_domain,
            "contacts": contacts,
        }

    def find_business_email(self, business_name: str, city: str, phone: str | None = None) -> list[dict[str, Any]]:
        """Legacy helper for backward compatibility."""
        res = self.find_business_website_and_email(business_name, city, phone)
        return res.get("contacts", [])

    def _execute_search_queries(self, query: str) -> tuple[str, list[str]]:
        """Queries Yahoo and Bing to gather page text snippets and candidate website links."""
        encoded = urllib.parse.quote_plus(query)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        all_text_snippets: list[str] = []
        candidate_links: list[str] = []

        # Engine 1: Yahoo Search
        try:
            yahoo_url = f"https://search.yahoo.com/search?p={encoded}"
            r = http_client.get(yahoo_url, headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                all_text_snippets.append(soup.get_text(" "))

                for a in soup.select("h3.title a, .compText a, a[href]"):
                    href = a.get("href", "")
                    if "/RU=" in href:
                        try:
                            ru = href.split("/RU=")[1].split("/")[0]
                            href = urllib.parse.unquote(ru)
                        except Exception:
                            pass
                    if href.startswith("http"):
                        candidate_links.append(href)
        except Exception as e:
            logger.debug(f"Yahoo search notice: {e}")

        # Engine 2: Bing HTML Search
        try:
            bing_url = f"https://www.bing.com/search?q={encoded}&setlang=en"
            r = http_client.get(bing_url, headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                all_text_snippets.append(soup.get_text(" "))
                for a in soup.select(".b_algo h2 a, a[href]"):
                    href = a.get("href", "")
                    if href.startswith("http"):
                        candidate_links.append(href)
        except Exception as e:
            logger.debug(f"Bing search notice: {e}")

        return " ".join(all_text_snippets), candidate_links

    def _select_best_website(self, candidate_links: list[str], business_name: str) -> str | None:
        """
        Filters out aggregators/directories and validates that the candidate domain
        shares brand tokens with the business name to prevent false positives.
        """
        stopwords = {
            "inc", "llc", "corp", "corporation", "co", "the", "and", "service",
            "services", "company", "group", "solutions", "contractor", "contractors",
            "plumbing", "heating", "cooling", "electric", "electrical", "hvac", "roofing", "cleaning", "restoration"
        }
        normalized_name = (business_name or "").lower()
        raw_tokens = [t for t in re.findall(r"[a-z0-9]+", normalized_name) if len(t) >= 3]
        brand_tokens = [t for t in raw_tokens if t not in stopwords and len(t) >= 3]
        active_tokens = brand_tokens if brand_tokens else raw_tokens

        for link in candidate_links:
            try:
                parsed = urllib.parse.urlparse(link)
                netloc = parsed.netloc.lower().replace("www.", "")
                if not netloc or "." not in netloc:
                    continue

                # Exclude directories and search engines
                if any(netloc == d or netloc.endswith(f".{d}") for d in DIRECTORY_DOMAINS):
                    continue

                # Ensure relevance: at least one brand token must match domain stem
                domain_stem = netloc.split(".")[0]
                if active_tokens:
                    if any(tok in domain_stem for tok in active_tokens):
                        scheme = parsed.scheme if parsed.scheme in ["http", "https"] else "https"
                        return f"{scheme}://{netloc}"
                else:
                    scheme = parsed.scheme if parsed.scheme in ["http", "https"] else "https"
                    return f"{scheme}://{netloc}"
            except Exception:
                continue

        return None

    def _scrape_website_contacts(self, website_url: str) -> list[str]:
        """Scrapes contact pages and homepage for direct email addresses."""
        discovered: list[str] = []
        clean_url = website_url.rstrip("/")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }

        urls_to_try = [
            clean_url,
            f"{clean_url}/contact",
            f"{clean_url}/contact-us",
            f"{clean_url}/about",
            f"{clean_url}/about-us",
        ]

        for url in urls_to_try:
            try:
                r = http_client.get(url, headers=headers, timeout=6)
                if r.status_code == 200:
                    emails = self._extract_clean_emails_from_text(r.text)
                    discovered.extend(emails)
                    if len(discovered) >= 3:
                        break
            except Exception:
                continue

        return list(dict.fromkeys(discovered))

    def _extract_clean_emails_from_text(self, text: str) -> list[str]:
        """Extracts and sanitizes email addresses from raw HTML/text."""
        if not text:
            return []

        results: list[str] = []
        matches = EMAIL_REGEX.findall(text)
        for m in matches:
            clean = m.lower().strip(".,;:()<>[]'\"\\/")
            if self._is_valid_lead_email(clean):
                results.append(clean)

        return list(dict.fromkeys(results))

    def _is_valid_lead_email(self, email: str) -> bool:
        """Filters out system, privacy, and image/asset tokens."""
        if not email or "@" not in email:
            return False

        # Ignore images and asset extensions mistaken for emails
        if any(email.endswith(ext) for ext in IGNORED_FILE_EXTENSIONS):
            return False

        parts = email.split("@")
        if len(parts) != 2:
            return False

        prefix, domain = parts[0], parts[1]

        if prefix in BLOCKED_EMAIL_PREFIXES or len(prefix) < 2:
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


_local_finder_instance: LocalBusinessEmailFinder | None = None


def get_local_business_email_finder() -> LocalBusinessEmailFinder:
    global _local_finder_instance
    if _local_finder_instance is None:
        _local_finder_instance = LocalBusinessEmailFinder()
    return _local_finder_instance
