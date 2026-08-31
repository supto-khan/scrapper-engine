import logging
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class ApolloClient:
    """
    Apollo.io API client for Organization People Search and Decision-Maker Discovery.
    Conforms to Rule 9: Timeout, retry with backoff, and rate-limit handling.
    """

    BASE_URL = "https://api.apollo.io/v1"

    TARGET_TITLES = [
        "Chief Technology Officer",
        "CTO",
        "VP of Engineering",
        "Vice President of Engineering",
        "Head of Engineering",
        "Director of Engineering",
        "Founder",
        "Co-Founder",
        "Chief Executive Officer",
        "CEO",
        "Head of Product",
    ]

    def __init__(
        self, api_key: str | None = None, timeout: int = 15, max_retries: int = 3
    ):
        self.api_key = api_key or os.getenv("APOLLO_API_KEY") or None
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_call_time = 0.0
        self._min_interval = 3.0  # Smooth pacing to avoid Apollo free tier per-minute bursts
        self._quota_exhausted = False

    def _rate_limit_wait(self):
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    def search_people(self, domain: str, limit: int = 5) -> list[dict[str, Any]]:
        """
        Searches Apollo.io for contacts at a specific company domain.
        Hierarchy:
        1. First tries prioritized executive & technical decision-maker titles.
        2. If 0 contacts found, automatically falls back to searching ANY available contact/employee at the domain.
        """
        if not self.api_key or self._quota_exhausted:
            return []

        url = f"{self.BASE_URL}/mixed_people/api_search"
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.api_key,
        }

        # Pass 1: Try specific prioritized decision maker titles
        payload_targeted = {
            "q_organization_domains": domain,
            "person_titles": self.TARGET_TITLES,
            "page": 1,
            "per_page": limit,
        }

        contacts = self._execute_search(url, headers, payload_targeted, domain)
        if contacts or self._quota_exhausted:
            return contacts

        # Pass 2: Fallback — search for ANY employee / contact at the domain
        logger.info(f"No specific executive titles found for {domain}. Running broad contact search...")
        payload_broad = {
            "q_organization_domains": domain,
            "page": 1,
            "per_page": limit,
        }
        return self._execute_search(url, headers, payload_broad, domain)

    def _execute_search(self, url: str, headers: dict[str, str], payload: dict[str, Any], domain: str) -> list[dict[str, Any]]:
        if self._quota_exhausted:
            return []

        for attempt in range(1, self.max_retries + 1):
            self._rate_limit_wait()
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                self._last_call_time = time.time()
                if response.status_code == 200:
                    people = response.json().get("people", [])
                    return self._parse_people(people, headers)
                elif response.status_code == 429:
                    retry_after_hdr = response.headers.get("Retry-After")
                    try:
                        raw_wait = int(retry_after_hdr) if retry_after_hdr else 2**attempt * 3
                    except ValueError:
                        raw_wait = 2**attempt * 3

                    # If Apollo asks to wait more than 15 seconds, daily/hourly quota is exhausted
                    if raw_wait > 15:
                        self._quota_exhausted = True
                        logger.warning(
                            f"Apollo.io daily quota reached (Retry-After: {raw_wait}s). "
                            f"Skipping Apollo for session and switching directly to Website Scraper fallback."
                        )
                        return []

                    wait_time = min(raw_wait, 15)
                    logger.warning(
                        f"Apollo.io 429 burst rate limit on {domain}. Backing off for {wait_time}s (attempt {attempt}/{self.max_retries})..."
                    )
                    time.sleep(wait_time)
                    self._last_call_time = time.time()
                elif response.status_code >= 500:
                    wait_time = 2**attempt
                    logger.warning(
                        f"Apollo.io server error {response.status_code}. Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                    self._last_call_time = time.time()
                else:
                    logger.warning(
                        f"Apollo.io returned {response.status_code} for {domain}: {response.text[:200]}"
                    )
                    return []
            except requests.exceptions.Timeout:
                logger.warning(
                    f"Apollo.io timeout on {domain} (attempt {attempt}/{self.max_retries})"
                )
                time.sleep(2**attempt)
                self._last_call_time = time.time()
            except Exception as e:
                logger.warning(f"Apollo.io exception for {domain}: {e}")
                time.sleep(1)
                self._last_call_time = time.time()

        return []

    def _parse_people(self, raw_people: list[dict[str, Any]], headers: dict[str, str]) -> list[dict[str, Any]]:
        contacts = []
        for p in raw_people:
            email = p.get("email")
            pid = p.get("id")

            # If email is not in search result, try matching person by ID
            if (not email or "@" not in email) and pid:
                try:
                    match_url = f"{self.BASE_URL}/people/match"
                    match_res = requests.post(match_url, headers=headers, json={"id": pid}, timeout=self.timeout)
                    if match_res.status_code == 200:
                        matched_person = match_res.json().get("person", {})
                        email = matched_person.get("email") or email
                        p.update(matched_person)
                except Exception as e:
                    logger.debug(f"Could not match email for person {pid}: {e}")

            first_name = p.get("first_name")
            last_name = p.get("last_name")
            full_name = p.get("name") or f"{first_name or ''} {last_name or ''}".strip()
            title = p.get("title") or "Technical Decision Maker"

            pos_lower = title.lower()
            role_category = "general"
            if any(
                t in pos_lower for t in ["cto", "engineering", "technical", "developer"]
            ):
                role_category = "technical_executive"
            elif any(t in pos_lower for t in ["founder", "ceo", "president"]):
                role_category = "founder"
            elif any(t in pos_lower for t in ["product", "design"]):
                role_category = "product_lead"

            contacts.append(
                {
                    "full_name": full_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "title": title,
                    "role_category": role_category,
                    "email": email,
                    "email_score": 85.0,
                    "verification_source": "apollo",
                    "linkedin_url": p.get("linkedin_url"),
                    "source": "apollo",
                    "raw_contact_data": p,
                }
            )
        return contacts


def get_apollo_client() -> ApolloClient:
    return ApolloClient()
