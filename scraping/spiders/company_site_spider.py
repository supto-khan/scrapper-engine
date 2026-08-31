import time

import scrapy

from scraping.items import CompanySiteCrawlItem
from scoring.fit_score import get_fit_scorer
from shared.queue import RedisQueue
from shared.redis_client import get_redis_client, normalize_domain


class CompanySiteSpider(scrapy.Spider):
    """
    Tier-2 Spider: Crawls actual company websites discovered in Tier-1.
    Extracts raw HTML, headers, response metrics, and yields CompanySiteCrawlItem.
    """

    name = "company_site_spider"

    custom_settings = {
        "DOWNLOAD_DELAY": 1.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
        "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
    }

    def __init__(self, target_domain: str | None = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.target_domain = target_domain
        self.redis_client = get_redis_client()
        self.tier2_queue = RedisQueue("tier2_crawl", self.redis_client)
        self._fit_scorer = get_fit_scorer()

    def start_requests(self):
        # 1. If explicit target_domain passed as CLI argument
        if self.target_domain:
            clean = normalize_domain(self.target_domain)
            if clean:
                for scheme in ["https://", "http://"]:
                    url = f"{scheme}{clean}"
                    yield scrapy.Request(
                        url,
                        meta={"target_domain": clean, "start_time": time.time()},
                        callback=self.parse,
                        errback=self.handle_error,
                        dont_filter=True,
                    )
            return

        # 2. Otherwise drain pending items from the Redis tier2 queue
        count = 0
        skipped = 0
        while True:
            item = self.tier2_queue.pop()
            if not item:
                break

            domain = item.get("domain")
            website_url = item.get("website_url") or f"https://{domain}"

            # Guard: disqualify any dev agency / software house that slipped
            # into the queue before the new scoring filters were applied.
            disqualified, reason = self._fit_scorer._is_disqualified({
                "name": item.get("name") or domain,
                "domain": domain,
                "industry": item.get("industry") or "",
            })
            if disqualified:
                self.logger.info(
                    f"[Tier-2 Guard] Skipping dev-agency domain '{domain}' ({reason})"
                )
                skipped += 1
                continue

            yield scrapy.Request(
                website_url,
                meta={"target_domain": domain, "start_time": time.time()},
                callback=self.parse,
                errback=self.handle_error,
                dont_filter=True,
            )
            count += 1
            if count >= 100:  # batch limit per spider run
                break

        if skipped:
            self.logger.info(f"[Tier-2 Guard] Skipped {skipped} disqualified agency domain(s).")

        if count == 0:
            self.logger.info("No pending domains found in Redis tier2 queue.")

    def parse(self, response):
        domain = response.meta.get("target_domain") or normalize_domain(response.url)
        start_time = response.meta.get("start_time")
        ttfb_ms = None
        if start_time:
            ttfb_ms = int((time.time() - start_time) * 1000)

        # Convert headers to normal string dict
        headers_dict = {}
        for k, v in response.headers.items():
            k_str = k.decode("utf-8", errors="ignore")
            v_str = b", ".join(v).decode("utf-8", errors="ignore")
            headers_dict[k_str] = v_str

        yield CompanySiteCrawlItem(
            domain=domain,
            source_url=response.url,
            http_status=response.status,
            headers=headers_dict,
            raw_html=response.text,
            ttfb_ms=ttfb_ms,
        )

    def handle_error(self, failure):
        request = failure.request
        domain = request.meta.get("target_domain")
        self.logger.warning(
            f"Crawl failed for domain {domain} at {request.url}: {failure.value}. "
            "Continuing batch per Failure Policy."
        )
