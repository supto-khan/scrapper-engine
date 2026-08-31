import logging
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class HunterClient:
    """
    Hunter.io API client for Domain Search and Email Finder.
    Conforms to Rule 9: Timeout, retry with backoff, and rate-limit handling.
    """

    BASE_URL = "https://api.hunter.io/v2"

    # Technical decision maker titles to prioritize
    TARGET_TITLES = [
        "cto",
        "chief technology officer",
        "vp of engineering",
        "vice president of engineering",
        "head of engineering",
        "director of engineering",
        "lead developer",
        "founder",
        "co-founder",
        "chief executive officer",
        "ceo",
        "head of product",
    ]

    def __init__(
        self, api_key: str | None = None, timeout: int = 15, max_retries: int = 3
    ):
        self.api_key = api_key or os.getenv("HUNTER_API_KEY") or None
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_call_time = 0.0
        self._min_interval = 0.5  # 2 requests/sec rate limit

    def _rate_limit_wait(self):
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    def search_domain(self, domain: str, limit: int = 10) -> list[dict[str, Any]]:
        """
        Searches Hunter.io for email addresses and decision makers at a specific domain.
        Returns normalized list of decision-maker contacts.
        """
        if not self.api_key:
            logger.warning("HUNTER_API_KEY not configured. Skipping live Hunter query.")
            return []

        url = f"{self.BASE_URL}/domain-search"
        params = {
            "domain": domain,
            "api_key": self.api_key,
            "limit": limit,
        }

        for attempt in range(1, self.max_retries + 1):
            self._rate_limit_wait()
            try:
                response = requests.get(url, params=params, timeout=self.timeout)
                if response.status_code == 200:
                    data = response.json().get("data", {})
                    emails = data.get("emails", [])
                    return self._parse_contacts(emails, domain)
                elif response.status_code == 429:
                    wait_time = 2**attempt * 2
                    logger.warning(
                        f"Hunter.io 429 rate limit. Backing off for {wait_time}s..."
                    )
                    time.sleep(wait_time)
                elif response.status_code >= 500:
                    wait_time = 2**attempt
                    logger.warning(
                        f"Hunter.io server error {response.status_code}. Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.warning(
                        f"Hunter.io returned {response.status_code} for {domain}: {response.text[:200]}"
                    )
                    return []
            except requests.exceptions.Timeout:
                logger.warning(
                    f"Hunter.io timeout on {domain} (attempt {attempt}/{self.max_retries})"
                )
                time.sleep(2**attempt)
            except Exception as e:
                logger.warning(f"Hunter.io exception for {domain}: {e}")
                time.sleep(1)

        return []

    def _parse_contacts(
        self, raw_emails: list[dict[str, Any]], domain: str
    ) -> list[dict[str, Any]]:
        contacts = []
        for item in raw_emails:
            value = item.get("value")
            if not value or "@" not in value:
                continue

            first_name = item.get("first_name")
            last_name = item.get("last_name")
            full_name = (
                f"{first_name or ''} {last_name or ''}".strip() or value.split("@")[0]
            )
            position = item.get("position") or "Unknown"
            score = item.get("confidence")

            # Determine role category
            pos_lower = position.lower()
            role_category = "general"
            if any(
                t in pos_lower
                for t in [
                    "cto",
                    "technology",
                    "engineering",
                    "technical",
                    "developer",
                    "architect",
                    "software",
                ]
            ):
                role_category = "technical_executive"
            elif any(t in pos_lower for t in ["founder", "ceo", "president", "owner"]):
                role_category = "founder"
            elif any(t in pos_lower for t in ["product", "design"]):
                role_category = "product_lead"

            contacts.append(
                {
                    "full_name": full_name,
                    "first_name": first_name,
                    "last_name": last_name,
                    "title": position,
                    "role_category": role_category,
                    "email": value,
                    "email_score": float(score) if score is not None else 80.0,
                    "verification_source": "hunter",
                    "linkedin_url": item.get("linkedin"),
                    "source": "hunter",
                    "raw_contact_data": item,
                }
            )
        return contacts


def get_hunter_client() -> HunterClient:
    return HunterClient()
