import json
import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class WebsiteContactScraper:
    """
    Direct Website Contact Scraper (Strategy 2 - 100% Free & Built-In Fallback).
    Extracts verified contact/inquiry emails directly from agency websites:
    - Homepage & footer
    - /contact, /contact-us, /get-in-touch
    - /about, /about-us
    - /team, /our-team
    - Schema.org / JSON-LD metadata
    - Cloudflare email protection de-obfuscation
    - Anti-spam obfuscated email formats (e.g. hello [at] domain.com)
    """

    TARGET_PATHS = [
        "",  # Homepage
        "/contact",
        "/contact-us",
        "/get-in-touch",
        "/about",
        "/about-us",
        "/team",
        "/our-team",
        "/privacy",
        "/privacy-policy",
        "/terms",
        "/terms-of-service",
        "/legal",
        "/impressum",
        "/.well-known/security.txt",
    ]

    IGNORED_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".css", ".js",
        ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".pdf", ".zip"
    }

    IGNORED_DOMAINS = {
        "sentry.io", "wix.com", "wixpress.com", "example.com", "domain.com",
        "email.com", "yourcompany.com", "company.com", "wordpress.org",
        "schema.org", "cloudflare.com", "google.com", "github.com"
    }

    EMAIL_REGEX = re.compile(
        r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", re.IGNORECASE
    )

    # Patterns for obfuscated emails like: name [at] domain [dot] com
    OBFUSCATED_EMAIL_REGEX = re.compile(
        r"([a-zA-Z0-9_.+-]+)\s*(?:\[at\]|\(at\)|\[@\]|@)\s*([a-zA-Z0-9-]+)\s*(?:\[dot\]|\(dot\)|\.)\s*([a-zA-Z0-9-.]+)",
        re.IGNORECASE
    )

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36 (SignalEngine/1.0)"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def resolve_canonical_domain(self, domain_or_url: str) -> str:
        """
        Unfurls redirect chains (e.g. go.designrush.com, click.clutch.co, or shortened URLs)
        to discover the actual target agency root domain.
        """
        if not domain_or_url:
            return ""

        clean = domain_or_url.strip().lower().replace("http://", "").replace("https://", "").strip("/")
        try:
            resp = self.session.get(f"https://{clean}", timeout=5, allow_redirects=True, stream=True)
            final_url = resp.url
            parsed = urlparse(final_url)
            final_netloc = parsed.netloc.lower().removeprefix("www.").strip("/")
            if final_netloc and final_netloc != clean and "." in final_netloc:
                logger.info(f"Unfurled redirect domain: {clean} -> {final_netloc}")
                return final_netloc
        except Exception:
            pass
        return clean

    def scrape_domain_contacts(self, domain: str, limit: int = 3) -> list[dict[str, Any]]:
        """
        Crawls domain contact pages and extracts emails.
        Returns a list of structured contact records.
        """
        if not domain:
            return []

        # Strategy 3: Unfurl canonical domain if redirect/directory subdomain
        canonical_domain = self.resolve_canonical_domain(domain)
        clean_domain = canonical_domain or domain.lower().replace("http://", "").replace("https://", "").strip().strip("/")
        base_url = f"https://{clean_domain}"
        found_emails: dict[str, dict[str, Any]] = {}

        logger.info(f"Direct Website Scraper: Scanning {clean_domain} for contact emails...")

        for path in self.TARGET_PATHS:
            if len(found_emails) >= limit:
                break

            target_url = urljoin(base_url, path)
            try:
                resp = self.session.get(target_url, timeout=self.timeout, allow_redirects=True)
                if resp.status_code != 200 or not resp.text:
                    continue

                extracted = self._extract_emails_from_html(resp.text, clean_domain)
                for email_info in extracted:
                    em = email_info["email"]
                    if em not in found_emails:
                        found_emails[em] = email_info

            except requests.exceptions.SSLError:
                # Try HTTP fallback if SSL fails
                if target_url.startswith("https://"):
                    try:
                        http_url = target_url.replace("https://", "http://", 1)
                        resp = self.session.get(http_url, timeout=self.timeout, allow_redirects=True)
                        if resp.status_code == 200 and resp.text:
                            extracted = self._extract_emails_from_html(resp.text, clean_domain)
                            for email_info in extracted:
                                em = email_info["email"]
                                if em not in found_emails:
                                    found_emails[em] = email_info
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Direct scraper could not reach {target_url}: {e}")
                continue

        contacts = list(found_emails.values())[:limit]
        if contacts:
            logger.info(
                f"Direct Website Scraper: Found {len(contacts)} contact(s) for {clean_domain}: "
                f"{[c['email'] for c in contacts]}"
            )
        else:
            logger.info(f"Direct Website Scraper: No public emails found on {clean_domain}")

        return contacts

    def _extract_emails_from_html(self, html_content: str, root_domain: str) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        soup = BeautifulSoup(html_content, "html.parser")

        # 1. Cloudflare De-obfuscation (<a data-cfemail="..."> or href="/cdn-cgi/l/email-protection#...")
        cf_tags = soup.find_all(attrs={"data-cfemail": True})
        for tag in cf_tags:
            hex_data = tag.get("data-cfemail")
            if hex_data:
                decoded = self._decode_cloudflare_email(hex_data)
                valid_em = self._clean_and_validate_candidate(decoded, root_domain)
                if valid_em:
                    results.append(self._format_contact(valid_em, root_domain, tag.get_text(strip=True)))

        cf_links = soup.find_all("a", href=re.compile(r"/cdn-cgi/l/email-protection#", re.IGNORECASE))
        for tag in cf_links:
            href = tag.get("href", "")
            if "#" in href:
                hex_data = href.split("#")[-1]
                decoded = self._decode_cloudflare_email(hex_data)
                valid_em = self._clean_and_validate_candidate(decoded, root_domain)
                if valid_em and not any(r["email"] == valid_em for r in results):
                    results.append(self._format_contact(valid_em, root_domain, tag.get_text(strip=True)))

        # 2. Look for mailto: links (highest confidence)
        mailto_links = soup.find_all("a", href=re.compile(r"^mailto:", re.IGNORECASE))
        for tag in mailto_links:
            href = tag.get("href", "")
            raw_email = href.split("?")[0].replace("mailto:", "").strip()
            valid_em = self._clean_and_validate_candidate(raw_email, root_domain)
            if valid_em and not any(r["email"] == valid_em for r in results):
                results.append(self._format_contact(valid_em, root_domain, tag.get_text(strip=True)))

        # 3. Schema.org / JSON-LD Structured Metadata
        json_ld_tags = soup.find_all("script", type="application/ld+json")
        for tag in json_ld_tags:
            try:
                if not tag.string:
                    continue
                data = json.loads(tag.string)
                self._extract_from_json_ld(data, root_domain, results)
            except Exception:
                pass

        # 4. Remove script and style elements before text regex scanning
        for script_or_style in soup(["script", "style", "noscript", "svg", "path"]):
            script_or_style.extract()

        clean_text = soup.get_text(separator=" ")

        # 5. Standard Text regex matching
        matches = self.EMAIL_REGEX.findall(clean_text)
        for candidate in matches:
            valid_em = self._clean_and_validate_candidate(candidate, root_domain)
            if valid_em and not any(r["email"] == valid_em for r in results):
                results.append(self._format_contact(valid_em, root_domain))

        # 6. Anti-Spam Obfuscated Email Parsing (e.g., hello [at] domain.com)
        obfuscated_matches = self.OBFUSCATED_EMAIL_REGEX.findall(clean_text)
        for user, dom, tld in obfuscated_matches:
            reconstructed = f"{user}@{dom}.{tld}".strip()
            valid_em = self._clean_and_validate_candidate(reconstructed, root_domain)
            if valid_em and not any(r["email"] == valid_em for r in results):
                results.append(self._format_contact(valid_em, root_domain))

        # Prioritize matching root_domain emails first, then priority prefixes (hello, contact, etc.)
        def sort_priority(item: dict[str, Any]) -> int:
            em = item["email"]
            score = 0
            if root_domain in em:
                score += 10
            for prefix in ["contact", "hello", "hi", "info", "team", "inquiries", "partnerships", "sales"]:
                if em.startswith(prefix + "@"):
                    score += 5
                    break
            return score

        results.sort(key=sort_priority, reverse=True)
        return results

    def _decode_cloudflare_email(self, hex_str: str) -> str:
        """Decodes Cloudflare's email protection XOR cipher."""
        try:
            r = int(hex_str[:2], 16)
            email = "".join(
                chr(int(hex_str[i:i + 2], 16) ^ r)
                for i in range(2, len(hex_str), 2)
            )
            return email
        except Exception:
            return ""

    def _extract_from_json_ld(self, data: Any, root_domain: str, results: list[dict[str, Any]]) -> None:
        """Recursively traverses JSON-LD payload looking for email fields."""
        if isinstance(data, dict):
            for k, v in data.items():
                if k.lower() == "email" and isinstance(v, str):
                    valid_em = self._clean_and_validate_candidate(v, root_domain)
                    if valid_em and not any(r["email"] == valid_em for r in results):
                        results.append(self._format_contact(valid_em, root_domain, "JSON-LD schema"))
                else:
                    self._extract_from_json_ld(v, root_domain, results)
        elif isinstance(data, list):
            for item in data:
                self._extract_from_json_ld(item, root_domain, results)

    def _clean_and_validate_candidate(self, email: str, root_domain: str) -> str | None:
        if not email or "@" not in email:
            return None

        email = email.lower().strip().strip(".,;:()<>[]'\"")

        # Filter out trailing extensions like .png, .jpg from image filenames
        if any(email.endswith(ext) for ext in self.IGNORED_EXTENSIONS):
            return None

        parts = email.split("@")
        if len(parts) != 2:
            return None

        user, domain = parts
        if not user or not domain or "." not in domain:
            return None

        # Filter out ignored domains
        if domain in self.IGNORED_DOMAINS or any(domain.endswith("." + d) for d in self.IGNORED_DOMAINS):
            return None

        # Filter common dummy / placeholder emails
        if user in ["username", "user", "name", "yourname", "email", "example"]:
            return None

        return email

    def _format_contact(self, email: str, root_domain: str, tag_text: str = "") -> dict[str, Any]:
        local_part = email.split("@")[0]
        title = "General Inquiries / Leadership"
        role_category = "general"

        if any(w in local_part for w in ["founder", "ceo", "director", "partner"]):
            title = "Leadership / Founder"
            role_category = "founder"
        elif any(w in local_part for w in ["tech", "dev", "engineering", "cto"]):
            title = "Technical Lead"
            role_category = "technical_executive"
        elif any(w in local_part for w in ["contact", "hello", "hi", "info", "inquiries", "office", "sales"]):
            title = "Contact / Inquiries"
            role_category = "general"

        full_name = f"{root_domain.capitalize()} {title}"

        return {
            "full_name": full_name,
            "first_name": root_domain.capitalize(),
            "last_name": title,
            "title": title,
            "role_category": role_category,
            "email": email,
            "email_score": 80.0,
            "verification_source": "website_crawler",
            "linkedin_url": None,
            "source": "website_crawler",
            "raw_contact_data": {
                "extracted_from": root_domain,
                "tag_text": tag_text,
            },
        }


def get_website_contact_scraper() -> WebsiteContactScraper:
    return WebsiteContactScraper()
