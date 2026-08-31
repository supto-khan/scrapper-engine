"""
Upwork High-Intent Lead & Buying Signal Harvester.
Executes the Upwork spider to paginate through all pages for targeted Laravel, SaaS, and Modernization keywords.
Supports direct residential proxy routing and custom keywords.
"""

import argparse
import logging
import os
import sys

# Ensure signal-engine is on sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
from scraping.spiders.upwork_spider import UpworkSpider

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_upwork_spider")


def main():
    parser = argparse.ArgumentParser(description="Run Upwork High-Intent Job Spider with Pagination")
    parser.add_argument("--max-pages", type=int, default=30, help="Max search pages to paginate per keyword")
    parser.add_argument("--keywords", type=str, default="", help="Comma-separated custom keywords")
    parser.add_argument("--proxy", type=str, default="", help="Custom HTTP/SOCKS proxy URL (e.g. http://127.0.0.1:7890)")
    args = parser.parse_args()

    proxy_to_use = args.proxy or os.getenv("PROXY_URL", "")

    logger.info("=" * 60)
    logger.info("⚡ [Upwork Harvester] Starting Upwork Job & Buying Signal Crawl...")
    logger.info(f"Target Keywords ({len(UpworkSpider.SEARCH_KEYWORDS)} terms): {', '.join(UpworkSpider.SEARCH_KEYWORDS[:5])}...")
    logger.info(f"Max Pages per Keyword: {args.max_pages}")
    if proxy_to_use:
        logger.info(f"Proxy Routing: Enabled ({proxy_to_use.split('@')[-1]})")
    else:
        logger.info("Proxy Routing: Direct connection (Note: If Upwork hangs, enable VPN or set PROXY_URL in .env)")
    logger.info("=" * 60)

    settings = get_project_settings()
    settings.set("LOG_LEVEL", "INFO")
    settings.set("TWISTED_REACTOR", "twisted.internet.asyncioreactor.AsyncioSelectorReactor")

    if proxy_to_use:
        settings.set("HTTP_PROXY", proxy_to_use)
        settings.set("HTTPS_PROXY", proxy_to_use)

    process = CrawlerProcess(settings)
    process.crawl(UpworkSpider, max_pages=args.max_pages, keywords=args.keywords)
    process.start()

    logger.info("🎉 [Upwork Harvester] Finished Upwork crawl run.")


if __name__ == "__main__":
    main()
