"""
Signal Engine — Resilient HTTP Client
Provides TLS fingerprint impersonation via `curl_cffi` when available,
with graceful fallback to standard `requests` and browser headers.
"""

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from curl_cffi import requests as _cffi_requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests as _cffi_requests  # type: ignore
    HAS_CURL_CFFI = False
    logger.info("curl_cffi is not installed. Using standard requests with browser headers as fallback.")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get(
    url: str,
    impersonate: str = "chrome124",
    timeout: int = 15,
    headers: Optional[dict[str, str]] = None,
    **kwargs: Any,
):
    """
    Perform a GET request. Uses curl_cffi with TLS impersonation if available,
    otherwise falls back to standard requests without breaking.
    """
    if HAS_CURL_CFFI:
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        return _cffi_requests.get(
            url, impersonate=impersonate, timeout=timeout, headers=merged_headers, **kwargs
        )

    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    return _cffi_requests.get(url, timeout=timeout, headers=merged_headers, **kwargs)


def post(
    url: str,
    impersonate: str = "chrome124",
    timeout: int = 15,
    headers: Optional[dict[str, str]] = None,
    **kwargs: Any,
):
    """
    Perform a POST request.
    """
    if HAS_CURL_CFFI:
        merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
        return _cffi_requests.post(
            url, impersonate=impersonate, timeout=timeout, headers=merged_headers, **kwargs
        )

    merged_headers = {**DEFAULT_HEADERS, **(headers or {})}
    return _cffi_requests.post(url, timeout=timeout, headers=merged_headers, **kwargs)
