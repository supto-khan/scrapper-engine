import logging
import os
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)


class PageSpeedClient:
    """
    Google PageSpeed Insights API client.
    Conforms to Rule 9: Timeout, retry with backoff, and rate-limit handling.
    """

    API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

    def __init__(
        self, api_key: str | None = None, timeout: int = 25, max_retries: int = 3
    ):
        self.api_key = api_key or os.getenv("PAGESPEED_API_KEY") or None
        self.timeout = timeout
        self.max_retries = max_retries
        self._last_call_time = 0.0
        self._min_interval = 1.0  # rate limit: 1 request/sec default

    def _rate_limit_wait(self):
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_call_time = time.time()

    def run_pagespeed(
        self, url: str, strategy: str = "mobile"
    ) -> dict[str, Any] | None:
        """
        Runs PageSpeed Insights for a URL with retries and backoff.
        strategy: 'mobile' or 'desktop'
        """
        params: dict[str, Any] = {
            "url": url,
            "strategy": strategy,
            "category": ["performance", "accessibility", "seo"],
        }
        if self.api_key:
            params["key"] = self.api_key

        headers = {
            "Accept": "application/json",
            "User-Agent": "NexidantSignalEngine/1.0",
        }

        for attempt in range(1, self.max_retries + 1):
            self._rate_limit_wait()
            try:
                response = requests.get(
                    self.API_URL,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )

                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    wait_time = 2**attempt * 2
                    logger.warning(
                        f"PageSpeed API rate limit (429) for {url}. Waiting {wait_time}s (attempt {attempt}/{self.max_retries})"
                    )
                    time.sleep(wait_time)
                elif response.status_code >= 500:
                    wait_time = 2**attempt
                    logger.warning(
                        f"PageSpeed API server error ({response.status_code}) for {url}. Retrying in {wait_time}s..."
                    )
                    time.sleep(wait_time)
                else:
                    logger.warning(
                        f"PageSpeed API returned status {response.status_code} for {url}: {response.text[:200]}"
                    )
                    return None

            except requests.exceptions.Timeout:
                logger.warning(
                    f"PageSpeed API timeout for {url} (attempt {attempt}/{self.max_retries})"
                )
                time.sleep(2**attempt)
            except Exception as e:
                logger.warning(f"PageSpeed API exception for {url}: {e}")
                time.sleep(1)

        logger.error(
            f"Failed to fetch PageSpeed data for {url} after {self.max_retries} attempts."
        )
        return None
