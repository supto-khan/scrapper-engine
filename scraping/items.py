import scrapy


class CompanyDiscoveryItem(scrapy.Item):
    """
    Tier-1 Discovery item yielded by Clutch & GoodFirms spiders.
    """

    name = scrapy.Field()
    domain = scrapy.Field()
    website_url = scrapy.Field()
    source = scrapy.Field()
    industry = scrapy.Field()
    employee_count_estimate = scrapy.Field()


class CompanySiteCrawlItem(scrapy.Item):
    """
    Tier-2 Crawl item yielded by company_site_spider.
    """

    domain = scrapy.Field()
    source_url = scrapy.Field()
    http_status = scrapy.Field()
    headers = scrapy.Field()
    raw_html = scrapy.Field()
    ttfb_ms = scrapy.Field()
