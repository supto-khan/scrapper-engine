import logging
import re
from typing import Any
import urllib.parse
from bs4 import BeautifulSoup
import scrapy
from scrapy.http import Response

from shared.mysql_client import get_mysql_client
from shared.redis_client import normalize_domain

logger = logging.getLogger(__name__)


class UpworkSpider(scrapy.Spider):
    """
    Upwork High-Intent Job & Buying Signal Spider.
    Paginates through every single search page for targeted Laravel, SaaS, and Modernization keywords.
    Extracts client budget, technical pain points, and company/domain leads.
    """

    name = "upwork"
    allowed_domains = ["upwork.com"]

    SEARCH_KEYWORDS = [
        "Laravel SaaS",
        "SaaS MVP Laravel",
        "Laravel modernization",
        "SaaS Laravel",
        "Laravel React",
        "Laravel Next.js",
        "Laravel API Integration",
        "Laravel performance optimization",
        "Laravel application issue",
        "Laravel existing application",
        "Laravel developer fix",
        "Laravel performance issue",
        "JavaScript issue",
    ]

    custom_settings = {
        "ROBOTSTXT_OBEY": False,
        "CONCURRENT_REQUESTS": 1,
        "DOWNLOAD_DELAY": 1.0,
        "RETRY_ENABLED": False,
        "DOWNLOAD_TIMEOUT": 10,
        "PLAYWRIGHT_DEFAULT_NAVIGATION_TIMEOUT": 8000,
        "DOWNLOAD_HANDLERS": {
            "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
            "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
        },
        "PLAYWRIGHT_LAUNCH_OPTIONS": {
            "headless": True,
            "args": [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-blink-features=AutomationControlled",
            ],
        },
        "PLAYWRIGHT_CONTEXTS": {
            "default": {
                "user_agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                "viewport": {"width": 1280, "height": 800},
                "locale": "en-US",
                "timezone_id": "America/New_York",
            }
        },
    }

    def __init__(self, max_pages: int = 50, keywords: str | None = None, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_pages = int(max_pages)
        if keywords:
            self.keywords = [k.strip() for k in keywords.split(",") if k.strip()]
        else:
            # Deduplicated list of exact user-requested search terms
            seen = set()
            self.keywords = []
            for k in self.SEARCH_KEYWORDS:
                if k.lower() not in seen:
                    seen.add(k.lower())
                    self.keywords.append(k)

        self.mysql_client = get_mysql_client()

    def start_requests(self):
        for keyword in self.keywords:
            encoded_query = urllib.parse.quote_plus(keyword)
            # Start on Page 1 for each keyword
            url = f"https://www.upwork.com/nx/search/jobs/?q={encoded_query}&sort=recency&page=1"
            yield scrapy.Request(
                url=url,
                callback=self.parse,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_goto_kwargs": {
                        "wait_until": "domcontentloaded",
                        "timeout": 8000,
                    },
                    "keyword": keyword,
                    "page_num": 1,
                    "encoded_query": encoded_query,
                },
                dont_filter=True,
            )

    async def parse(self, response: Response):
        page = response.meta.get("playwright_page")
        keyword = response.meta["keyword"]
        page_num = response.meta["page_num"]
        encoded_query = response.meta["encoded_query"]

        logger.info(f"🔎 [Upwork Spider] Parsing '{keyword}' — Page {page_num}...")

        # Wait for job tiles to render in Playwright DOM if page is active
        if page:
            try:
                await page.wait_for_selector("article[data-test='JobTile'], section.up-card-section", timeout=8000)
            except Exception:
                logger.debug(f"Timeout waiting for selector on page {page_num} for {keyword}")
            content = await page.content()
            await page.close()
        else:
            content = response.text

        soup = BeautifulSoup(content, "html.parser")
        job_cards = soup.find_all(lambda tag: tag.name in ["article", "section"] and (
            tag.get("data-test") == "JobTile" or "job-tile" in (tag.get("class") or [])
        ))

        if not job_cards:
            # Fallback selectors
            job_cards = soup.select("article, section.up-card-section, div[data-test='job-tile-list'] > section")

        found_on_page = 0
        for card in job_cards:
            title_tag = card.find(lambda t: t.name in ["h2", "h3", "a"] and ("job-title" in (t.get("class") or []) or t.get("data-test") == "UpLink"))
            title = title_tag.get_text(strip=True) if title_tag else ""
            if not title:
                continue

            link = ""
            if title_tag and title_tag.name == "a":
                link = title_tag.get("href", "")
            elif title_tag and title_tag.find("a"):
                link = title_tag.find("a").get("href", "")

            if link and link.startswith("/"):
                link = f"https://www.upwork.com{link}"

            desc_tag = card.find(lambda t: "job-description" in (t.get("class") or []) or t.get("data-test") == "JobDescription")
            description = desc_tag.get_text(strip=True) if desc_tag else card.get_text(separator=" ", strip=True)

            # Extract budget / spend tier
            budget_str = self._extract_budget(card.get_text(separator=" "))
            client_spend = self._extract_client_spend(card.get_text(separator=" "))

            # Extract client domain / company name if mentioned
            company_name, domain = self._extract_lead_identity(title, description)

            found_on_page += 1
            logger.info(f"   🎯 [Job] {title[:60]}... | Budget: {budget_str} | Spend: {client_spend}")

            if domain and company_name:
                self._save_upwork_lead(
                    company_name=company_name,
                    domain=domain,
                    job_title=title,
                    job_url=link or response.url,
                    description=description,
                    budget_str=budget_str,
                    client_spend=client_spend,
                    keyword=keyword,
                )

        logger.info(f"✓ [Upwork Spider] Found {found_on_page} jobs on '{keyword}' Page {page_num}.")

        # Pagination: Continue to Next Page if jobs were found and page_num < max_pages
        if found_on_page > 0 and page_num < self.max_pages:
            next_page_num = page_num + 1
            next_url = f"https://www.upwork.com/nx/search/jobs/?q={encoded_query}&sort=recency&page={next_page_num}"
            logger.info(f"➡️ [Upwork Spider] Paginating to Page {next_page_num} for '{keyword}'...")
            yield scrapy.Request(
                url=next_url,
                callback=self.parse,
                meta={
                    "playwright": True,
                    "playwright_include_page": True,
                    "playwright_page_goto_kwargs": {
                        "wait_until": "domcontentloaded",
                        "timeout": 8000,
                    },
                    "keyword": keyword,
                    "page_num": next_page_num,
                    "encoded_query": encoded_query,
                },
                dont_filter=True,
            )
        else:
            logger.info(f"🏁 [Upwork Spider] Reached last page for '{keyword}' at Page {page_num}.")

    def _extract_budget(self, text: str) -> str:
        # Fixed price matching
        m_fixed = re.search(r"\$[\d,]+(?:\s*-\s*\$[\d,]+)?", text)
        if m_fixed:
            return m_fixed.group(0)
        # Hourly rate matching
        m_hourly = re.search(r"\$[\d.]+\s*-\s*\$[\d.]+\s*/\s*hr", text, re.IGNORECASE)
        if m_hourly:
            return m_hourly.group(0)
        return "Budget: Open / Hourly"

    def _extract_client_spend(self, text: str) -> str:
        m_spend = re.search(r"(\$[\d,]+[kKmM]?\+?\s*spent)", text, re.IGNORECASE)
        if m_spend:
            return m_spend.group(1)
        return "$0 spent / New Client"

    def _extract_lead_identity(self, title: str, description: str) -> tuple[str | None, str | None]:
        """Extracts domain and company name from job brief text."""
        # Check for URLs in description
        urls = re.findall(r"https?://(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})", description)
        for u in urls:
            if not any(excl in u.lower() for excl in [
                "upwork.com", "github.com", "loom.com", "figma.com", "google.com",
                "docs.google.com", "drive.google.com", "trello.com", "notion.so"
            ]):
                norm = normalize_domain(u)
                comp_name = norm.split(".")[0].replace("-", " ").title()
                return comp_name, norm

        # Fallback: Detect company signatures in description (e.g. "We at Acme Retail...", "Our platform ShopHero...")
        m_comp = re.search(r"(?:at|our company|our platform|our website|we are)\s+([A-Z][A-Za-z0-9\s]{2,20})", description)
        if m_comp:
            name = m_comp.group(1).strip()
            slug = re.sub(r"[^a-z0-9]", "", name.lower())
            if 3 <= len(slug) <= 20:
                return name, f"{slug}.com"

        return None, None

    def _save_upwork_lead(
        self,
        company_name: str,
        domain: str,
        job_title: str,
        job_url: str,
        description: str,
        budget_str: str,
        client_spend: str,
        keyword: str,
    ) -> None:
        """Persists company and high-budget Upwork buying signal."""
        try:
            conn = self.mysql_client.get_connection()
            with conn.cursor() as cursor:
                # 1. Ensure company exists
                cursor.execute(
                    """
                    INSERT INTO companies (name, website_url, domain, source, industry, project_summary, employee_count_estimate)
                    VALUES (%s, %s, %s, 'upwork', 'Custom Web Applications & SaaS', %s, '10-50')
                    ON DUPLICATE KEY UPDATE 
                        project_summary = VALUES(project_summary),
                        updated_at = NOW()
                    """,
                    (company_name, f"https://{domain}", domain, f"Upwork Job: {job_title} ({budget_str})"),
                )
                cursor.execute("SELECT id FROM companies WHERE domain = %s", (domain,))
                row = cursor.fetchone()
                if row:
                    comp_id = row["id"]
                    # 2. Save buying & pain signal
                    self.mysql_client.save_signal(
                        company_id=comp_id,
                        signal_type="upwork_high_intent_job",
                        source_url=job_url,
                        confidence_score=90.0,
                        evidence_data={
                            "job_title": job_title,
                            "search_keyword": keyword,
                            "budget": budget_str,
                            "client_spend_history": client_spend,
                            "snippet": description[:300],
                            "intent_level": "immediate_budget_ready",
                        },
                    )
            conn.close()
        except Exception as e:
            logger.debug(f"Error saving Upwork lead {domain}: {e}")
