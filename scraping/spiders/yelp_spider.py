import urllib.parse
import scrapy
from bs4 import BeautifulSoup

from scraping.items import CompanyDiscoveryItem


class YelpSpider(scrapy.Spider):
    """
    Spider to discover commercial buyer businesses (real estate, restaurants, retail, healthcare)
    listed on Yelp — NOT dev agencies or software houses.
    Yields CompanyDiscoveryItem (Tier-1 discovery).
    """

    name = "yelp_spider"
    allowed_domains = ["yelp.com"]

    # Target commercial industry buyers across major US metropolitan markets
    start_urls = [
        "https://www.yelp.com/search?find_desc=Real+Estate&find_loc=New+York%2C+NY",
        "https://www.yelp.com/search?find_desc=Restaurants&find_loc=New+York%2C+NY",
        "https://www.yelp.com/search?find_desc=Shopping&find_loc=New+York%2C+NY",
        "https://www.yelp.com/search?find_desc=Healthcare&find_loc=New+York%2C+NY",
        "https://www.yelp.com/search?find_desc=Professional+Services&find_loc=New+York%2C+NY",
    ]

    custom_settings = {
        "DOWNLOAD_DELAY": 2.0,
    }

    def start_requests(self):
        for url in self.start_urls:
            yield scrapy.Request(
                url,
                headers={"Referer": "https://www.google.com/"},
                callback=self.parse,
            )

    def parse(self, response):
        soup = BeautifulSoup(response.text, "html.parser")
        cards = soup.select(
            "[data-testid='serp-ia-card'], div[class*='businessCard'], div[class*='container__'], .business-card, .search-result"
        )
        if not cards:
            cards = soup.select("li, div[class*='resultCard']")

        for card in cards:
            biz_link = card.select_one("a[href*='/biz/']")
            name = biz_link.get_text(strip=True) if biz_link else None

            # Look for external website redirect (/biz_redir?url=...) or direct link
            site_link = card.select_one(
                "a[href*='/biz_redir'], a[href*='biz_redir?url='], a.visit-website, a[href^='http']:not([href*='yelp.com'])"
            )
            website_url = None
            if site_link and site_link.get("href"):
                raw_href = site_link["href"]
                if "biz_redir" in raw_href:
                    parsed = urllib.parse.urlparse(raw_href)
                    params = urllib.parse.parse_qs(parsed.query)
                    if "url" in params:
                        website_url = params["url"][0]
                    else:
                        website_url = raw_href
                else:
                    website_url = raw_href

            # Category / Industry label
            cat_el = card.select_one("span[class*='css-'], p[class*='css-'], .category-str-list, .price-category")
            cat_text = cat_el.get_text(strip=True) if cat_el else "Commercial Services"

            if name and website_url:
                yield CompanyDiscoveryItem(
                    name=name,
                    website_url=website_url,
                    domain=website_url,
                    source="yelp",
                    industry=cat_text or "Commercial Services",
                    employee_count_estimate="10-49",
                )

        # Pagination
        next_page = soup.select_one("a[aria-label='Next'], a.next-link, a[class*='next-link'], a.pagination-link-next")
        if next_page and next_page.get("href"):
            next_url = response.urljoin(next_page["href"])
            yield scrapy.Request(
                next_url,
                callback=self.parse,
            )
