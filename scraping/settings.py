import os

from dotenv import load_dotenv

load_dotenv()

BOT_NAME = "signal-engine"

SPIDER_MODULES = ["scraping.spiders"]
NEWSPIDER_MODULE = "scraping.spiders"

# Directory discovery requires standard browser headers
ROBOTSTXT_OBEY = False

# Concurrency & polite delays
CONCURRENT_REQUESTS = int(os.getenv("CONCURRENT_REQUESTS", 8))
CONCURRENT_REQUESTS_PER_DOMAIN = 2
DOWNLOAD_DELAY = float(os.getenv("DOWNLOAD_DELAY", 1.0))
RANDOMIZE_DOWNLOAD_DELAY = True

# AutoThrottle
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 1.0
AUTOTHROTTLE_MAX_DELAY = 10.0
AUTOTHROTTLE_TARGET_CONCURRENCY = 2.0
AUTOTHROTTLE_DEBUG = False

# Default Request Headers (mimics desktop Chrome 126 on macOS)
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
}

# Download Handlers: Standard robust HTTP/HTTPS handlers
DOWNLOAD_HANDLERS = {
    "http": "scrapy.core.downloader.handlers.http.HTTPDownloadHandler",
    "https": "scrapy.core.downloader.handlers.http.HTTPDownloadHandler",
}

# Twisted Reactor
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"

# Downloader Middlewares
DOWNLOADER_MIDDLEWARES = {
    "scraping.middlewares.proxy_middleware.ProxyMiddleware": 410,
    "scraping.middlewares.playwright_middleware.PlaywrightFallbackMiddleware": 580,
}

# Item Pipelines
ITEM_PIPELINES = {
    "scraping.pipelines.DomainNormalizationAndDedupPipeline": 300,
    "scraping.pipelines.MySQLPersistencePipeline": 400,
}

# Retry settings
RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, 429]

# Logging
LOG_LEVEL = "INFO"

# Feed Export encoding
FEED_EXPORT_ENCODING = "utf-8"
