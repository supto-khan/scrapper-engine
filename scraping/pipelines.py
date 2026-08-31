import logging

from itemadapter import ItemAdapter
from scrapy.exceptions import DropItem

from intelligence.technology.tech_fingerprint import get_fingerprint_detector
from scraping.items import CompanyDiscoveryItem, CompanySiteCrawlItem
from shared.mysql_client import get_mysql_client
from shared.queue import RedisQueue
from shared.redis_client import get_redis_client, normalize_domain

logger = logging.getLogger(__name__)


class DomainNormalizationAndDedupPipeline:
    """
    Normalizes company domain, validates it, checks Redis deduplication filter,
    and drops already seen domains for discovery items.
    """

    def open_spider(self, spider):
        self.redis_client = get_redis_client()
        self.tier2_queue = RedisQueue("tier2_crawl", self.redis_client)

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        domain = adapter.get("domain") or adapter.get("website_url")
        if not domain:
            raise DropItem("Item missing domain or website_url")

        clean_domain = normalize_domain(domain)
        if not clean_domain or "." not in clean_domain:
            raise DropItem(f"Invalid domain format: {domain}")

        adapter["domain"] = clean_domain

        # Deduplication for discovery items
        if isinstance(item, CompanyDiscoveryItem):
            if self.redis_client.is_domain_seen(clean_domain):
                raise DropItem(f"Duplicate domain already seen: {clean_domain}")
            # Mark seen in Redis
            self.redis_client.mark_domain_seen(clean_domain)
            # Enqueue for tier-2 crawl if discovery spider
            self.tier2_queue.push(
                {
                    "domain": clean_domain,
                    "name": adapter.get("name"),
                    "source": adapter.get("source"),
                    "website_url": adapter.get("website_url")
                    or f"https://{clean_domain}",
                }
            )

        return item


class MySQLPersistencePipeline:
    """
    Persists discovered companies, tech fingerprints, and raw HTML snapshots into MySQL/MariaDB.
    """

    def open_spider(self, spider):
        self.mysql_client = get_mysql_client()
        self.detector = get_fingerprint_detector()

    def process_item(self, item, spider):
        adapter = ItemAdapter(item)
        domain = adapter.get("domain")

        try:
            if isinstance(item, CompanyDiscoveryItem):
                company_id = self.mysql_client.upsert_company(
                    domain=domain,
                    name=adapter.get("name") or domain,
                    source=adapter.get("source", "unknown"),
                    industry=adapter.get("industry"),
                    employee_count_estimate=adapter.get("employee_count_estimate"),
                    website_url=adapter.get("website_url"),
                )
                logger.info(f"Upserted company: {domain} (ID: {company_id})")

            elif isinstance(item, CompanySiteCrawlItem):
                company_record = self.mysql_client.get_company_by_domain(domain)
                if not company_record:
                    company_id = self.mysql_client.upsert_company(
                        domain=domain,
                        name=domain,
                        source="crawler",
                        website_url=adapter.get("source_url"),
                    )
                else:
                    company_id = company_record["id"]

                # 1. Save raw page snapshot
                self.mysql_client.save_raw_company_data(
                    company_id=company_id,
                    source_url=adapter.get("source_url"),
                    http_status=adapter.get("http_status"),
                    headers=adapter.get("headers"),
                    raw_html=adapter.get("raw_html"),
                )

                # 2. Extract technology fingerprint and persist
                raw_html = adapter.get("raw_html") or ""
                headers = adapter.get("headers") or {}
                ttfb_ms = adapter.get("ttfb_ms")

                fingerprint = self.detector.analyze(
                    url=adapter.get("source_url") or f"https://{domain}",
                    html_content=raw_html,
                    headers=headers,
                    ttfb_ms=ttfb_ms,
                )

                self.mysql_client.save_technology_fingerprint(
                    company_id=company_id,
                    cms=fingerprint["cms"],
                    frontend_stack=fingerprint["frontend_stack"],
                    backend_stack=fingerprint["backend_stack"],
                    https=fingerprint["https"],
                    hsts=fingerprint["hsts"],
                    ttfb_ms=fingerprint["ttfb_ms"],
                    evidence=fingerprint["evidence"],
                )
                logger.info(
                    f"Saved tech fingerprint for {domain}: CMS={fingerprint['cms']}, Frontend={fingerprint['frontend_stack']}"
                )

        except Exception as e:
            logger.error(
                f"Error persisting item for {domain} in MySQL: {e}", exc_info=True
            )

        return item
