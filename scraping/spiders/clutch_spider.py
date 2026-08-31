import scrapy
from bs4 import BeautifulSoup

from scraping.items import CompanyDiscoveryItem


class ClutchSpider(scrapy.Spider):
    """
    Spider to discover US commercial companies (real estate, e-commerce, retail, hospitality)
    listed on Clutch.co — NOT dev agencies or software houses.
    Yields CompanyDiscoveryItem (Tier-1 discovery).
    """

    name = "clutch_spider"
    allowed_domains = ["clutch.co"]

    # Target commercial industry buyers — NOT dev shops or software houses
    start_urls = [
        "https://clutch.co/real-estate",
        "https://clutch.co/retail",
        "https://clutch.co/e-commerce",
        "https://clutch.co/logistics-supply-chain",
        "https://clutch.co/healthcare",
        "https://clutch.co/hospitality",
    ]

    custom_settings = {
        "DOWNLOAD_DELAY": 2.0,
    }

    def start_requests(self):
        for url in self.start_urls:
            # Clutch may have Cloudflare protection; flag playwright if needed or use HTTP/2 standard
            yield scrapy.Request(
                url,
                headers={"Referer": "https://www.google.com/"},
                callback=self.parse,
            )

    def parse(self, response):
        """Parse directory listing page for providers."""
        # Check if page is blocked or standard HTML
        soup = BeautifulSoup(response.text, "html.parser")
        provider_cards = soup.select("li.provider, div.provider-row, div.provider-card")

        if not provider_cards:
            # Fallback selectors
            provider_cards = soup.select(
                ".directory-list .provider-info, .provider-detail"
            )

        for card in provider_cards:
            name_el = card.select_one(
                "h3.company_info, a.company_title, .provider-target, h3"
            )
            name = name_el.get_text(strip=True) if name_el else None

            # Look for external website visit button
            site_link = card.select_one(
                "a.website-link__item, a[data-link_track*='website'], a.directory_profile"
            )
            website_url = None
            if site_link and site_link.get("href"):
                website_url = site_link["href"]

            # Look for employee count estimate
            employees_el = card.select_one("span.employees, span[data-employees]")
            employees = employees_el.get_text(strip=True) if employees_el else None

            if name and website_url:
                # Derive industry label from the current URL path
                path_industry = response.url.split("clutch.co/")[-1].split("?")[0].replace("-", " ").title()
                yield CompanyDiscoveryItem(
                    name=name,
                    website_url=website_url,
                    domain=website_url,
                    source="clutch",
                    industry=path_industry or "Commercial Services",
                    employee_count_estimate=employees,
                )

        # Pagination
        next_page = soup.select_one(
            "li.page-item.next a, a.page-link[rel='next'], a[data-page='next']"
        )
        if next_page and next_page.get("href"):
            next_url = response.urljoin(next_page["href"])
            yield scrapy.Request(
                next_url,
                callback=self.parse,
            )
