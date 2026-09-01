import hashlib
import logging
import re
from typing import Any

from shared.redis_client import normalize_domain

logger = logging.getLogger(__name__)


class GoogleMapsDiscoveryFeed:
    """
    Feed reader & normalizer for Google Maps local business data.
    Supports both businesses WITH a website and businesses WITHOUT a website.
    """

    def parse_entry(self, raw_entry: dict[str, Any]) -> dict[str, Any]:
        raw_url = raw_entry.get("website_url") or raw_entry.get("website") or raw_entry.get("domain") or ""
        name = (raw_entry.get("name") or "").strip()
        city = (raw_entry.get("city") or "").strip()
        phone = (raw_entry.get("phone") or raw_entry.get("formatted_phone_number") or "").strip()
        category = raw_entry.get("category") or raw_entry.get("types") or raw_entry.get("industry") or "Local Business & Services"
        
        if isinstance(category, list):
            category = category[0] if category else "Local Business & Services"
            category = category.replace("_", " ").title()

        has_website = bool(raw_url and raw_url.strip() and raw_url.strip() != "None")
        
        if has_website:
            clean = normalize_domain(raw_url)
            website_url = raw_url if raw_url.startswith("http") else f"https://{raw_url}"
        else:
            # Deterministic canonical synthetic domain for zero-website local business deduplication
            slug_name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "business"
            slug_city = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-") or "us"
            clean = f"{slug_name}-{slug_city}.local"
            website_url = None

        return {
            "name": name or clean,
            "domain": clean,
            "website_url": website_url,
            "has_website": has_website,
            "source": "google_maps",
            "industry": category,
            "phone": phone,
            "address": raw_entry.get("address") or raw_entry.get("formatted_address"),
            "rating": raw_entry.get("rating"),
            "review_count": raw_entry.get("review_count") or raw_entry.get("user_ratings_total"),
            "employee_count_estimate": raw_entry.get("employee_count_estimate", "10-50"),
            "is_high_priority_nowebsite": not has_website,
        }
