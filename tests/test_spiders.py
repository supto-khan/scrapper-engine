from scrapy.http import HtmlResponse, Request

from scraping.items import CompanyDiscoveryItem
from scraping.spiders.clutch_spider import ClutchSpider
from scraping.spiders.goodfirms_spider import GoodFirmsSpider


def test_clutch_spider_parsing():
    spider = ClutchSpider()
    html = """
    <html>
        <body>
            <li class="provider">
                <h3 class="company_info"><a href="/profile/alpha-dev">Alpha Dev Labs</a></h3>
                <a class="website-link__item" href="https://alphadevlabs.com">Visit Website</a>
                <span class="employees">50 - 249</span>
            </li>
        </body>
    </html>
    """
    request = Request(url="https://clutch.co/web-developers")
    response = HtmlResponse(
        url="https://clutch.co/web-developers",
        request=request,
        body=html,
        encoding="utf-8",
    )

    results = list(spider.parse(response))
    assert len(results) == 1
    item = results[0]
    assert isinstance(item, CompanyDiscoveryItem)
    assert item["name"] == "Alpha Dev Labs"
    assert item["website_url"] == "https://alphadevlabs.com"
    assert item["source"] == "clutch"
    assert item["employee_count_estimate"] == "50 - 249"


def test_goodfirms_spider_parsing():
    spider = GoodFirmsSpider()
    html = """
    <html>
        <body>
            <div class="firm-wrapper">
                <h3 class="firm-name"><a href="#">Beta Solutions</a></h3>
                <a class="visit-website" href="https://betasolutions.io">Visit Website</a>
                <span class="firm-employees">10 - 49</span>
            </div>
        </body>
    </html>
    """
    request = Request(url="https://www.goodfirms.co/web-development-services")
    response = HtmlResponse(
        url="https://www.goodfirms.co/web-development-services",
        request=request,
        body=html,
        encoding="utf-8",
    )

    results = list(spider.parse(response))
    assert len(results) == 1
    item = results[0]
    assert isinstance(item, CompanyDiscoveryItem)
    assert item["name"] == "Beta Solutions"
    assert item["website_url"] == "https://betasolutions.io"
    assert item["source"] == "goodfirms"


def test_yelp_spider_parsing():
    from scraping.spiders.yelp_spider import YelpSpider
    spider = YelpSpider()
    html = """
    <html>
        <body>
            <div data-testid="serp-ia-card">
                <h3><a href="/biz/empire-state-realty-new-york">Empire State Realty</a></h3>
                <a href="/biz_redir?url=https%3A%2F%2Fempirestaterealty.com&src_bizid=123">Visit Website</a>
                <span class="category-str-list">Real Estate Services</span>
            </div>
        </body>
    </html>
    """
    request = Request(url="https://www.yelp.com/search?find_desc=Real+Estate&find_loc=New+York%2C+NY")
    response = HtmlResponse(
        url="https://www.yelp.com/search?find_desc=Real+Estate&find_loc=New+York%2C+NY",
        request=request,
        body=html,
        encoding="utf-8",
    )

    results = list(spider.parse(response))
    assert len(results) == 1
    item = results[0]
    assert isinstance(item, CompanyDiscoveryItem)
    assert item["name"] == "Empire State Realty"
    assert item["website_url"] == "https://empirestaterealty.com"
    assert item["source"] == "yelp"
    assert item["industry"] == "Real Estate Services"


def test_yelp_discovery_feed():
    from discovery.directories.yelp_discovery import YelpDiscoveryFeed
    feed = YelpDiscoveryFeed()
    entry = feed.parse_entry({
        "name": "Manhattan Fine Dining",
        "website_url": "https://www.manhattanfinedining.com/menu",
        "industry": "Food & Hospitality",
        "employee_count_estimate": "25-50",
    })
    assert entry["name"] == "Manhattan Fine Dining"
    assert entry["domain"] == "manhattanfinedining.com"
    assert entry["source"] == "yelp"
    assert entry["industry"] == "Food & Hospitality"

