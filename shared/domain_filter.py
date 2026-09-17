"""
Signal Engine — Domain Filtering & Aggregator Detection
Identifies directory, aggregator, social, and non-target domains to prevent wasted audit cycles.
"""

from typing import Tuple

DIRECTORY_AGGREGATOR_DOMAINS = {
    # Directory & Local Search platforms
    "localsearch.com",
    "localsearch.com.au",
    "yellowpages.com",
    "yellowpages.com.au",
    "whitepages.com",
    "whitepages.com.au",
    "yelp.com",
    "yelp.com.au",
    "truelocal.com.au",
    "hotfrog.com.au",
    "hotfrog.com",
    "womo.com.au",
    "dnb.com",
    "zoominfo.com",
    "bloomberg.com",
    "crunchbase.com",
    "bbb.org",
    "tripadvisor.com",
    "tripadvisor.com.au",
    "clutch.co",
    "bark.com",
    "checkatrade.com",
    "angi.com",
    "thumbtack.com",

    # Social Media & Content Platforms
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "twitter.com",
    "x.com",
    "youtube.com",
    "tiktok.com",
    "pinterest.com",
    "reddit.com",

    # Freelance & Jobs
    "upwork.com",
    "fiverr.com",
    "freelancer.com",
    "indeed.com",
    "seek.com.au",

    # Search Engines & Wikis
    "google.com",
    "google.com.au",
    "bing.com",
    "yahoo.com",
    "wikipedia.org",
}

NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 405, 410, 451}

PERMANENT_DNS_ERROR_KEYWORDS = [
    "nodename nor servname",
    "name or service not known",
    "nxdomain",
    "could not resolve host",
    "dns_probe_finished_nxdomain",
    "err_name_not_resolved",
]


def is_excluded_domain(domain: str) -> Tuple[bool, str]:
    """
    Checks if a domain should be excluded from intelligence audits.
    Returns (is_excluded, reason).
    """
    if not domain:
        return True, "empty_domain"

    clean_d = domain.lower().strip()
    # Strip port if any
    clean_d = clean_d.split(":")[0].strip("/")

    # Exclude internal / test domains
    if clean_d.endswith(".local") or clean_d.endswith(".internal") or clean_d.endswith(".localhost"):
        return True, "internal_test_domain"

    # Exclude directory / aggregator domains and their subdomains
    for root in DIRECTORY_AGGREGATOR_DOMAINS:
        if clean_d == root or clean_d.endswith("." + root):
            return True, f"directory_aggregator_{root}"

    return False, ""


def is_retryable_failure(status_code: int | None, error_message: str = "") -> bool:
    """
    Determines if a crawl failure is temporary (retryable) or permanent (not retryable).
    - 403 Forbidden, 404 Not Found, 410 Gone: Permanent (do not retry)
    - Permanent DNS failure (NXDOMAIN / Name not resolved): Permanent (do not retry)
    - 5xx Server Error, connection timeout, network reset: Retryable
    """
    if status_code in NON_RETRYABLE_STATUS_CODES:
        return False

    err_str = str(error_message).lower()
    for kw in PERMANENT_DNS_ERROR_KEYWORDS:
        if kw in err_str:
            return False

    return True
