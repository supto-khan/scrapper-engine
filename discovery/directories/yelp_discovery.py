import logging
from typing import Any

from shared.redis_client import normalize_domain

logger = logging.getLogger(__name__)


class YelpDiscoveryFeed:
    """
    Feed reader / helper for Yelp directory data.
    """

    def parse_entry(self, raw_entry: dict[str, Any]) -> dict[str, Any]:
        raw_url = raw_entry.get("website_url") or raw_entry.get("domain") or ""
        clean = normalize_domain(raw_url)
        return {
            "name": raw_entry.get("name") or clean,
            "domain": clean,
            "website_url": raw_url,
            "source": "yelp",
            "industry": raw_entry.get("industry", "Commercial Business & Services"),
            "employee_count_estimate": raw_entry.get("employee_count_estimate"),
        }
