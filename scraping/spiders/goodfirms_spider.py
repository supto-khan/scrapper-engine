import scrapy
from bs4 import BeautifulSoup

from scraping.items import CompanyDiscoveryItem


class GoodFirmsSpider(scrapy.Spider):
    """
    Spider to discover US commercial companies (real estate, retail, e-commerce, hospitality)
    listed on GoodFirms.co — NOT software development agencies.
    Yields CompanyDiscoveryItem (Tier-1 discovery).
    """

    name = "goodfirms_spider"
    allowed_domains = ["goodfirms.co"]

    # Target commercial industry buyers — NOT dev shops
    start_urls = [
        "https://www.goodfirms.co/directory/real-estate",
        "https://www.goodfirms.co/directory/retail",
        "https://www.goodfirms.co/directory/e-commerce",
        "https://www.goodfirms.co/directory/healthcare",
        "https://www.goodfirms.co/directory/logistics",
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
        firm_cards = soup.select(".firm-wrapper, .service-provider, .entity-card")

        if not firm_cards:
            firm_cards = soup.select(".firm-item, .directory-card")

        for card in firm_cards:
            name_el = card.select_one("h3.firm-name, a.firm-title, .firm-name a, h3 a")
            name = name_el.get_text(strip=True) if name_el else None

            # Look for external website visit button
            site_link = card.select_one(
                "a.visit-website, a[data-website], a[href*='visit-website'], a.site-url"
            )
            website_url = None
            if site_link and site_link.get("href"):
                website_url = site_link["href"]

            employees_el = card.select_one(".firm-employees, span.employees")
            employees = employees_el.get_text(strip=True) if employees_el else None

            if name and website_url:
                path_industry = response.url.split("/directory/")[-1].split("?")[0].replace("-", " ").title()
                yield CompanyDiscoveryItem(
                    name=name,
                    website_url=website_url,
                    domain=website_url,
                    source="goodfirms",
                    industry=path_industry or "Commercial Services",
                    employee_count_estimate=employees,
                )

        # Pagination
        next_page = soup.select_one("a[rel='next'], .pagination .next a, a.next-page")
        if next_page and next_page.get("href"):
            next_url = response.urljoin(next_page["href"])
            yield scrapy.Request(
                next_url,
                callback=self.parse,
            )
