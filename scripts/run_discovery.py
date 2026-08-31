#!/usr/bin/env python3
"""
Signal Engine — End-Client Business Discovery Runner
Discovers real buyer businesses (E-Commerce, Real Estate, Food/Hospitality, Healthcare)
needing custom applications, software fixes, and digital modernization.

Features:
1. Multi-Page Pagination (Crawl depth 1 to N pages).
2. End-Client Target Industry Feeds (E-Commerce, Real Estate, Food & Hospitality).
3. Reviewer & Client Case-Study Extraction (Ingesting end-clients who hired developers).
4. Strict Agency / Competitor Exclusion (Filters out software agencies & dev shops).
"""

import logging
import os
import re
import sys
import urllib.parse
from bs4 import BeautifulSoup

# Ensure project root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from shared import http_client
from discovery.company_discovery import CompanyDiscoveryOrchestrator

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("run_discovery")

# End-Client Target Feeds (Expanded across High-Value Commercial Sectors)
DISCOVERY_FEEDS = [
    # -------------------------------------------------------------------------
    # 1. Clutch Feeds (E-Commerce, Healthcare, Real Estate, FinTech, Mobile, Logistics)
    # -------------------------------------------------------------------------
    {"source": "clutch", "url": "https://clutch.co/developers/ecommerce", "industry": "E-Commerce & Online Stores", "max_pages": 15},
    {"source": "clutch", "url": "https://clutch.co/developers/shopify", "industry": "E-Commerce & Online Stores", "max_pages": 15},
    {"source": "clutch", "url": "https://clutch.co/developers/magento", "industry": "E-Commerce & Online Stores", "max_pages": 10},
    {"source": "clutch", "url": "https://clutch.co/real-estate", "industry": "Real Estate & PropTech", "max_pages": 15},
    {"source": "clutch", "url": "https://clutch.co/developers/healthcare", "industry": "Healthcare & Life Sciences", "max_pages": 15},
    {"source": "clutch", "url": "https://clutch.co/developers/financial-services", "industry": "FinTech & Financial Services", "max_pages": 15},
    {"source": "clutch", "url": "https://clutch.co/app-developers", "industry": "Commercial Business Applications", "max_pages": 20},
    {"source": "clutch", "url": "https://clutch.co/developers/supply-chain-logistics", "industry": "Logistics & Supply Chain", "max_pages": 10},
    # -------------------------------------------------------------------------
    # 2. DesignRush Feeds (Multi-Category End-Clients & Case Studies)
    # -------------------------------------------------------------------------
    {"source": "designrush", "url": "https://www.designrush.com/agency/ecommerce", "industry": "E-Commerce & Online Stores", "max_pages": 15},
    {"source": "designrush", "url": "https://www.designrush.com/agency/shopify-web-design-companies", "industry": "E-Commerce & Online Stores", "max_pages": 10},
    {"source": "designrush", "url": "https://www.designrush.com/agency/real-estate-web-design-companies", "industry": "Real Estate & PropTech", "max_pages": 15},
    {"source": "designrush", "url": "https://www.designrush.com/agency/healthcare-web-design-agencies", "industry": "Healthcare & Life Sciences", "max_pages": 10},
    {"source": "designrush", "url": "https://www.designrush.com/agency/b2b-web-design-companies", "industry": "B2B SaaS & Tech Services", "max_pages": 15},
    # -------------------------------------------------------------------------
    # 3. GoodFirms Feeds
    # -------------------------------------------------------------------------
    {"source": "goodfirms", "url": "https://www.goodfirms.co/ecommerce-development-companies", "industry": "E-Commerce & Online Stores", "max_pages": 15},
    {"source": "goodfirms", "url": "https://www.goodfirms.co/real-estate-companies", "industry": "Real Estate & PropTech", "max_pages": 15},
    {"source": "goodfirms", "url": "https://www.goodfirms.co/healthcare-software-development-companies", "industry": "Healthcare & Life Sciences", "max_pages": 10},
    {"source": "goodfirms", "url": "https://www.goodfirms.co/fintech-software-development-companies", "industry": "FinTech & Financial Services", "max_pages": 10},
    # -------------------------------------------------------------------------
    # 4. Yelp Feeds (Multi-Metro Commercial Buyers: NYC, LA, Chicago, Miami, Austin, Dallas)
    # -------------------------------------------------------------------------
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Real+Estate&find_loc=New+York%2C+NY", "industry": "Real Estate & PropTech", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Real+Estate&find_loc=Los+Angeles%2C+CA", "industry": "Real Estate & PropTech", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Property+Management&find_loc=Austin%2C+TX", "industry": "Real Estate & PropTech", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Restaurants&find_loc=New+York%2C+NY", "industry": "Food & Hospitality", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Restaurants&find_loc=Chicago%2C+IL", "industry": "Food & Hospitality", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Restaurants&find_loc=Miami%2C+FL", "industry": "Food & Hospitality", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Shopping&find_loc=New+York%2C+NY", "industry": "E-Commerce & Online Stores", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Boutique+Clothing&find_loc=Los+Angeles%2C+CA", "industry": "E-Commerce & Online Stores", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Medical+Clinics&find_loc=New+York%2C+NY", "industry": "Healthcare & Life Sciences", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Healthcare+Services&find_loc=Dallas%2C+TX", "industry": "Healthcare & Life Sciences", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Logistics&find_loc=Houston%2C+TX", "industry": "Logistics & Supply Chain", "max_pages": 10},
    {"source": "yelp", "url": "https://www.yelp.com/search?find_desc=Commercial+Services&find_loc=Atlanta%2C+GA", "industry": "Commercial Business & Services", "max_pages": 10},
]


def extract_client_mentions_from_text(text: str, default_industry: str) -> list[dict[str, str]]:
    """
    Tier-2 Discovery: Extracts reviewer/client companies mentioned in case studies & reviews.
    Examples: 'As Director of Operations at Sands Investment Group, I partnered with...'
              'Client: Acme Shoes hired them to build a Shopify store...'
    """
    client_leads = []
    if not text:
        return client_leads

    # Pattern 1: 'at [Company Name], I partnered / hired / worked'
    match_at = re.findall(
        r"(?:at|for|from)\s+([A-Z][A-Za-z0-9\s&,.-]{2,30}?)(?:,\s*(?:I|we|our)|,\s*a\s+|,\s*the\s+|\s+(?:hired|partnered|contracted|engaged))",
        text
    )
    for name in match_at:
        clean_name = name.strip(" ,.-")
        if (
            len(clean_name) > 3
            and not any(w in clean_name.lower() for w in ["clutch", "goodfirms", "designrush", "team", "agency", "company", "director", "manager", "ceo"])
        ):
            guess_domain = clean_name.lower().replace("&", "and")
            guess_domain = re.sub(r"[^a-z0-9]", "", guess_domain) + ".com"
            client_leads.append({
                "name": clean_name,
                "domain": guess_domain,
                "industry": default_industry,
                "project_summary": text[:200],
            })

    return client_leads


def crawl_clutch_feed(orchestrator: CompanyDiscoveryOrchestrator, feed: dict, target_remaining: int) -> int:
    base_url = feed["url"]
    industry = feed["industry"]
    max_pages = feed.get("max_pages", 10)
    total_ingested = 0

    for page in range(1, max_pages + 1):
        if total_ingested >= target_remaining:
            break

        target_url = f"{base_url}?page={page - 1}" if page > 1 else base_url
        logger.info(f"\n🔍 [Clutch.co] Crawling Page {page}/{max_pages}: {industry} ({target_url})...")

        try:
            r = http_client.get(target_url, impersonate="chrome124", timeout=15)
            if r.status_code != 200:
                logger.warning(f"Clutch fetch failed on page {page}: HTTP {r.status_code}")
                break

            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select("li.provider, div.provider-row, div.provider-card, .directory-list .provider-info")
            if not cards:
                cards = soup.select("h3")

            page_count = 0
            for card in cards:
                if total_ingested >= target_remaining:
                    break

                h3 = card.select_one("h3") if hasattr(card, "select_one") else card
                name = h3.get_text(strip=True) if h3 else None
                if not name or len(name) < 2:
                    continue

                container = (
                    card
                    if hasattr(card, "select")
                    else (
                        h3.find_parent("div", class_=lambda c: c and "provider-info" in c.lower())
                        or h3.find_parent("li")
                        or h3.find_parent("div")
                    )
                )

                website_url = None
                employees = None

                if container:
                    # 1. Look for direct client review / testimonial quotes
                    review_text = container.get_text(separator=" ")
                    client_mentions = extract_client_mentions_from_text(review_text, industry)
                    for client_lead in client_mentions:
                        if total_ingested >= target_remaining:
                            break
                        accepted = orchestrator.ingest_candidate({
                            "name": client_lead["name"],
                            "website_url": f"https://{client_lead['domain']}",
                            "domain": client_lead["domain"],
                            "source": "clutch_review_client",
                            "industry": industry,
                            "project_summary": client_lead["project_summary"],
                            "employee_count_estimate": "10-50",
                        })
                        if accepted:
                            page_count += 1
                            total_ingested += 1

                    for a in container.select('a[href*="r.clutch.co/redirect"]'):
                        href = a.get("href")
                        parsed = urllib.parse.urlparse(href)
                        params = urllib.parse.parse_qs(parsed.query)
                        if "u" in params:
                            website_url = params["u"][0]
                            break

                    emp_el = container.select_one("span.employees, span[data-employees]")
                    if emp_el:
                        employees = emp_el.get_text(strip=True)

                if name and website_url and total_ingested < target_remaining:
                    accepted = orchestrator.ingest_candidate({
                        "name": name,
                        "website_url": website_url,
                        "domain": website_url,
                        "source": "clutch",
                        "industry": industry,
                        "employee_count_estimate": employees or "10-49",
                    })
                    if accepted:
                        page_count += 1
                        total_ingested += 1

            if page_count == 0 and page > 2:
                break

        except Exception as e:
            logger.error(f"Error crawling Clutch page {page}: {e}")
            break

    return total_ingested


def crawl_goodfirms_feed(orchestrator: CompanyDiscoveryOrchestrator, feed: dict, target_remaining: int) -> int:
    base_url = feed["url"]
    industry = feed["industry"]
    max_pages = feed.get("max_pages", 10)
    total_ingested = 0

    for page in range(1, max_pages + 1):
        if total_ingested >= target_remaining:
            break

        target_url = f"{base_url}?page={page}" if page > 1 else base_url
        logger.info(f"\n🔍 [GoodFirms.co] Crawling Page {page}/{max_pages}: {industry} ({target_url})...")

        try:
            r = http_client.get(target_url, impersonate="chrome124", timeout=15)
            if r.status_code != 200:
                logger.warning(f"GoodFirms fetch failed on page {page}: HTTP {r.status_code}")
                break

            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select(".firm-wrapper, .service-provider, .entity-card, .firm-item, [data-firm-id]")
            page_count = 0

            for card in cards:
                if total_ingested >= target_remaining:
                    break

                name_el = card.select_one("h3, .firm-name, a.firm-title")
                name = name_el.get_text(strip=True) if name_el else None

                # Extract Reviewer / Client mentions
                review_text = card.get_text(separator=" ")
                client_mentions = extract_client_mentions_from_text(review_text, industry)
                for client_lead in client_mentions:
                    if total_ingested >= target_remaining:
                        break
                    accepted = orchestrator.ingest_candidate({
                        "name": client_lead["name"],
                        "website_url": f"https://{client_lead['domain']}",
                        "domain": client_lead["domain"],
                        "source": "goodfirms_review_client",
                        "industry": industry,
                        "project_summary": client_lead["project_summary"],
                        "employee_count_estimate": "10-50",
                    })
                    if accepted:
                        page_count += 1
                        total_ingested += 1

                link_el = card.select_one("a.visit-website, a[data-website], a[href*='visit-website'], a.site-url, a[href^='http']:not([href*='goodfirms.co'])")
                website_url = link_el.get("href") if link_el else None

                emp_el = card.select_one(".firm-employees, span.employees")
                employees = emp_el.get_text(strip=True) if emp_el else None

                if name and website_url and total_ingested < target_remaining:
                    accepted = orchestrator.ingest_candidate({
                        "name": name,
                        "website_url": website_url,
                        "domain": website_url,
                        "source": "goodfirms",
                        "industry": industry,
                        "employee_count_estimate": employees or "10-49",
                    })
                    if accepted:
                        page_count += 1
                        total_ingested += 1

            if page_count == 0 and page > 2:
                break

        except Exception as e:
            logger.error(f"Error crawling GoodFirms page {page}: {e}")
            break

    return total_ingested


def crawl_designrush_feed(orchestrator: CompanyDiscoveryOrchestrator, feed: dict, target_remaining: int) -> int:
    base_url = feed["url"]
    industry = feed["industry"]
    max_pages = feed.get("max_pages", 10)
    total_ingested = 0

    for page in range(1, max_pages + 1):
        if total_ingested >= target_remaining:
            break

        target_url = f"{base_url}?page={page}" if page > 1 else base_url
        logger.info(f"\n🔍 [DesignRush] Crawling Page {page}/{max_pages}: {industry} ({target_url})...")

        try:
            r = http_client.get(target_url, impersonate="chrome124", timeout=15)
            if r.status_code != 200:
                logger.warning(f"DesignRush fetch failed on page {page}: HTTP {r.status_code}")
                break

            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select(".agency-card, .directory-card, [data-agency-id], .card")
            page_count = 0

            for card in cards:
                if total_ingested >= target_remaining:
                    break

                name_el = card.select_one("h3, .agency-name, a.title, .company-name")
                name = name_el.get_text(strip=True) if name_el else None

                # Extract Reviewer / Client case studies from card summary
                review_text = card.get_text(separator=" ")
                client_mentions = extract_client_mentions_from_text(review_text, industry)
                for client_lead in client_mentions:
                    if total_ingested >= target_remaining:
                        break
                    accepted = orchestrator.ingest_candidate({
                        "name": client_lead["name"],
                        "website_url": f"https://{client_lead['domain']}",
                        "domain": client_lead["domain"],
                        "source": "designrush_client",
                        "industry": industry,
                        "project_summary": client_lead["project_summary"],
                        "employee_count_estimate": "10-50",
                    })
                    if accepted:
                        page_count += 1
                        total_ingested += 1

                link_el = card.select_one("a[href*='visit'], a[data-url], a.website-link, a[href^='http']:not([href*='designrush.com'])")
                website_url = link_el.get("href") if link_el else None

                if name and website_url and total_ingested < target_remaining:
                    accepted = orchestrator.ingest_candidate({
                        "name": name,
                        "website_url": website_url,
                        "domain": website_url,
                        "source": "designrush",
                        "industry": industry,
                        "employee_count_estimate": "10-50",
                    })
                    if accepted:
                        page_count += 1
                        total_ingested += 1

            if page_count == 0 and page > 2:
                break

        except Exception as e:
            logger.error(f"Error crawling DesignRush page {page}: {e}")
            break

    return total_ingested


def crawl_yelp_feed(orchestrator: CompanyDiscoveryOrchestrator, feed: dict, target_remaining: int) -> int:
    base_url = feed["url"]
    industry = feed["industry"]
    max_pages = feed.get("max_pages", 10)
    total_ingested = 0

    for page in range(1, max_pages + 1):
        if total_ingested >= target_remaining:
            break

        # Yelp pagination uses &start=0, &start=10, &start=20...
        page_offset = (page - 1) * 10
        if page > 1:
            sep = "&" if "?" in base_url else "?"
            target_url = f"{base_url}{sep}start={page_offset}"
        else:
            target_url = base_url

        logger.info(f"\n🔍 [Yelp.com] Crawling Page {page}/{max_pages}: {industry} ({target_url})...")

        try:
            r = http_client.get(target_url, impersonate="chrome124", timeout=15)
            if r.status_code != 200:
                logger.warning(f"Yelp fetch failed on page {page}: HTTP {r.status_code}")
                break

            soup = BeautifulSoup(r.text, "html.parser")
            cards = soup.select(
                "[data-testid='serp-ia-card'], div[class*='businessCard'], div[class*='container__'], .business-card, .search-result"
            )
            if not cards:
                cards = soup.select("li, div[class*='resultCard']")

            page_count = 0
            for card in cards:
                if total_ingested >= target_remaining:
                    break

                biz_link = card.select_one("a[href*='/biz/']")
                name = biz_link.get_text(strip=True) if biz_link else None
                if not name or len(name) < 2 or "yelp" in name.lower():
                    continue

                # Extract Reviewer / Client mentions from review snippet
                review_text = card.get_text(separator=" ")
                client_mentions = extract_client_mentions_from_text(review_text, industry)
                for client_lead in client_mentions:
                    if total_ingested >= target_remaining:
                        break
                    accepted = orchestrator.ingest_candidate({
                        "name": client_lead["name"],
                        "website_url": f"https://{client_lead['domain']}",
                        "domain": client_lead["domain"],
                        "source": "yelp_review_client",
                        "industry": industry,
                        "project_summary": client_lead["project_summary"],
                        "employee_count_estimate": "10-50",
                    })
                    if accepted:
                        page_count += 1
                        total_ingested += 1

                # Look for external website redirect or direct URL
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
                else:
                    clean_name_slug = re.sub(r"[^a-zA-Z0-9]", "", name).lower()
                    if clean_name_slug and len(clean_name_slug) >= 3:
                        website_url = f"https://www.{clean_name_slug}.com"

                if name and website_url and total_ingested < target_remaining:
                    accepted = orchestrator.ingest_candidate({
                        "name": name,
                        "website_url": website_url,
                        "domain": website_url,
                        "source": "yelp",
                        "industry": industry,
                        "employee_count_estimate": "10-49",
                    })
                    if accepted:
                        page_count += 1
                        total_ingested += 1

            if page_count == 0 and page > 2:
                break

        except Exception as e:
            logger.error(f"Error crawling Yelp page {page}: {e}")
            break

    return total_ingested


from discovery.hiring.job_feed_discovery import get_job_board_discovery


def run_discovery(target_leads: int = 200):
    logger.info(f"🚀 Starting Multi-Source End-Client Discovery (Daily Target Goal: {target_leads} leads)...")
    orchestrator = CompanyDiscoveryOrchestrator()
    total_discovered = 0

    # 1. First Pass: Public Job Intent & Hiring Feeds (High active buyer intent)
    try:
        job_discovery = get_job_board_discovery()
        hiring_leads = job_discovery.discover_hiring_leads()
        total_discovered += hiring_leads
        logger.info(f"📊 Progress after Job Intent discovery: {total_discovered}/{target_leads} leads.")
    except Exception as e:
        logger.error(f"Error during job intent discovery: {e}", exc_info=True)

    # 2. Second Pass: Dynamic Directory Pagination until Daily Goal is Achieved
    if total_discovered < target_leads:
        logger.info(f"🔄 Continuing directory deep-crawling to reach remaining {target_leads - total_discovered} leads...")
        for feed in DISCOVERY_FEEDS:
            if total_discovered >= target_leads:
                logger.info(f"🎯 Target goal of {target_leads} leads reached! Halting further discovery.")
                break

            source = feed["source"]
            needed = target_leads - total_discovered
            try:
                if source == "clutch":
                    total_discovered += crawl_clutch_feed(orchestrator, feed, target_remaining=needed)
                elif source == "goodfirms":
                    total_discovered += crawl_goodfirms_feed(orchestrator, feed, target_remaining=needed)
                elif source == "designrush":
                    total_discovered += crawl_designrush_feed(orchestrator, feed, target_remaining=needed)
                elif source == "yelp":
                    total_discovered += crawl_yelp_feed(orchestrator, feed, target_remaining=needed)
            except Exception as e:
                logger.error(f"Error crawling {feed['url']}: {e}", exc_info=True)

    logger.info(f"\n🎉 Multi-Source Discovery Finished! Total new end-client leads ingested: {total_discovered}")
    logger.info("👉 Ready for Intelligence scanning & Scoring on the Dashboard!")
    return total_discovered


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Lead Discovery")
    parser.add_argument("--target", type=int, default=200, help="Target number of new leads to discover (default: 200)")
    args = parser.parse_args()

    run_discovery(target_leads=args.target)
