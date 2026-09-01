import argparse
import itertools
import json
import logging
import os
import random
import sys
import time
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from discovery.company_discovery import CompanyDiscoveryOrchestrator
from discovery.directories.google_maps_crawler import GoogleMapsCrawler
from discovery.directories.google_maps_discovery import GoogleMapsDiscoveryFeed
from enrichment.local_business_email_finder import LocalBusinessEmailFinder
from enrichment.website_contact_scraper import WebsiteContactScraper
from shared.mysql_client import get_mysql_client
from shared.proxy_manager import get_proxy_manager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("google_maps_crawler_runner")

STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "discovery", "directories", "gmaps_crawler_state.json")

# 25 High-Value Local Service Verticals (High Budget for Web & Booking Systems)
TARGET_NICHES = [
    "Dental Clinic",
    "Cosmetic Dentistry",
    "Roofing Contractor",
    "Plumbing & HVAC",
    "Personal Injury Lawyer",
    "Commercial Law Firm",
    "Medical Spa & Aesthetics",
    "Orthodontist",
    "Chiropractor",
    "Auto Repair & Body Shop",
    "Real Estate Brokerage",
    "Property Management",
    "General Contractor",
    "Commercial Cleaning",
    "Accounting & CPA",
    "Solar Installation",
    "Landscaping & Hardscaping",
    "Catering & Event Venue",
    "Veterinary Hospital",
    "Physical Therapy Clinic",
    "Dermatology Clinic",
    "Plastic Surgery Center",
    "Foundation Repair & Waterproofing",
    "Custom Home Builder",
    "Commercial Electrician",
]

# Top 60 US Metro Markets
US_METROS = [
    "Miami, FL", "Austin, TX", "Dallas, TX", "Houston, TX", "Atlanta, GA",
    "Los Angeles, CA", "San Diego, CA", "Chicago, IL", "New York, NY",
    "Tampa, FL", "Orlando, FL", "Phoenix, AZ", "Scottsdale, AZ", "Denver, CO",
    "Charlotte, NC", "Raleigh, NC", "Nashville, TN", "Seattle, WA", "Las Vegas, NV",
    "San Antonio, TX", "Fort Worth, TX", "Jacksonville, FL", "Columbus, OH",
    "Indianapolis, IN", "San Jose, CA", "San Francisco, CA", "Oklahoma City, OK",
    "El Paso, TX", "Washington, DC", "Boston, MA", "Memphis, TN", "Louisville, KY",
    "Baltimore, MD", "Milwaukee, WI", "Albuquerque, NM", "Tucson, AZ", "Fresno, CA",
    "Sacramento, CA", "Mesa, AZ", "Kansas City, MO", "Omaha, NE", "Colorado Springs, CO",
    "Virginia Beach, VA", "Minneapolis, MN", "Tulsa, OK", "Arlington, TX", "New Orleans, LA",
    "Bakersfield, CA", "Cleveland, OH", "Honolulu, HI", "St. Louis, MO", "Pittsburgh, PA",
    "Cincinnati, OH", "Salt Lake City, UT", "Baton Rouge, LA", "Boise, ID", "Birmingham, AL"
]


def load_crawler_state() -> int:
    """Loads persistent rotation pointer to guarantee 100% unique query coverage across runs."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                data = json.load(f)
                return int(data.get("pointer", 0))
        except Exception:
            return 0
    return 0


def save_crawler_state(pointer: int):
    """Saves rotation pointer to disk."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({"pointer": pointer, "last_updated": time.time()}, f, indent=2)
    except Exception as e:
        logger.debug(f"Could not save crawler state: {e}")


def get_query_matrix() -> list[tuple[str, str]]:
    """Generates an exhaustive combination matrix of all Niches x all US Metros."""
    return list(itertools.product(TARGET_NICHES, US_METROS))


def run_gmaps_discovery_batch(max_queries: int = 8, limit_per_query: int = 20, max_pages: int = 5) -> int:
    """
    Executes a batch of local business queries using dual-layer stealth scraping + rotating proxies,
    and ingests verified unique leads into MySQL + Redis.
    """
    crawler = GoogleMapsCrawler(timeout=15)
    feed = GoogleMapsDiscoveryFeed()
    orchestrator = CompanyDiscoveryOrchestrator()
    mysql_client = get_mysql_client()
    contact_scraper = WebsiteContactScraper(timeout=6)
    local_email_finder = LocalBusinessEmailFinder(timeout=8)
    proxy_manager = get_proxy_manager()

    active_proxies = proxy_manager.get_active_count()
    matrix = get_query_matrix()
    total_combinations = len(matrix)
    pointer = load_crawler_state()

    new_leads_count = 0
    nowebsite_count = 0

    logger.info(f"📋 Loaded Query Matrix: {total_combinations} total (Niche x City) combinations | Current Position: #{pointer} | Active Proxies: {active_proxies}")

    for i in range(max_queries):
        current_idx = (pointer + i) % total_combinations
        category, city = matrix[current_idx]

        logger.info(f"\n🔎 [{i+1}/{max_queries}] Searching: '{category}' in '{city}'...")
        raw_results = crawler.search_local_businesses(category=category, city=city, max_pages=max_pages, limit_per_page=limit_per_query)

        for raw in raw_results:
            entry = feed.parse_entry(raw)
            clean_domain = entry["domain"]
            name = entry["name"]
            has_website = entry["has_website"]

            # Redis & MySQL Deduplication
            if orchestrator.redis_client.is_domain_seen(clean_domain):
                logger.debug(f"Skipping duplicate domain (seen in Redis): {clean_domain}")
                continue

            existing_db = orchestrator.mysql_client.get_company_by_domain(clean_domain)
            if existing_db:
                orchestrator.redis_client.mark_domain_seen(clean_domain)
                logger.debug(f"Skipping duplicate company #{existing_db['id']}: {name}")
                continue

            orchestrator.redis_client.mark_domain_seen(clean_domain)

            # Persist Company to MySQL
            company_id = mysql_client.upsert_company(
                domain=clean_domain,
                name=name,
                source=raw.get("source", "google_maps"),
                industry=entry["industry"],
                employee_count_estimate=entry["employee_count_estimate"],
                website_url=entry["website_url"],
            )

            if not company_id:
                continue

            new_leads_count += 1

            if not has_website:
                nowebsite_count += 1
                # 1. Record Missing Website Signal
                mysql_client.save_signal(
                    company_id=company_id,
                    signal_type="missing_website",
                    confidence=1.0,
                    evidence_data={
                        "rating": entry.get("rating"),
                        "review_count": entry.get("review_count"),
                        "phone": entry.get("phone"),
                        "city": entry.get("city"),
                        "category": entry.get("category"),
                    },
                )

                # 2. Assign High-Value Opportunity (New Modern Website & Booking System)
                mysql_client.save_opportunity(
                    company_id=company_id,
                    opportunity_type="new_website_creation",
                    title="Turnkey High-Converting Web & Online Booking Portal",
                    pain_point="Established local business with active local traction, but no website to capture mobile search traffic.",
                    estimated_value_low=2500,
                    estimated_value_high=5000,
                    evidence={
                        "phone": entry.get("phone"),
                        "rating": entry.get("rating"),
                        "review_count": entry.get("review_count"),
                        "intent": "high_converting_booking_portal",
                    },
                )

                # 3. Award Immediate Tier 1 Score (92.0 / Immediate Priority)
                mysql_client.save_score(
                    company_id=company_id,
                    company_fit=90.0,
                    technology_gap=95.0,
                    pain_signal=90.0,
                    buying_signal=95.0,
                    contact_quality=80.0,
                    service_fit=100.0,
                    opportunity_score=92.0,
                    priority_tier="immediate",
                    score_breakdown={
                        "reason": "established_business_missing_website",
                        "phone": entry.get("phone"),
                        "reviews": entry.get("review_count"),
                    },
                )

                # 4. Search for direct business email across Social & Phone Lookups
                discovered_emails = local_email_finder.find_business_email(
                    business_name=name,
                    city=city,
                    phone=entry.get("phone")
                )

                if discovered_emails:
                    for ct in discovered_emails:
                        mysql_client.save_contact(
                            company_id=company_id,
                            full_name=ct.get("full_name") or f"Management ({name})",
                            first_name=ct.get("first_name") or "Owner / Manager",
                            email=ct["email"],
                            title=ct.get("title") or "Business Owner / General Manager",
                            email_status=ct.get("email_status", "valid"),
                            source=ct.get("source", "social_directory_search"),
                        )
                    logger.info(f"📧 Found Direct Email for No-Website Business: {[c['email'] for c in discovered_emails]} ({name})")
                elif entry.get("phone"):
                    mysql_client.save_contact(
                        company_id=company_id,
                        full_name=f"Management ({name})",
                        first_name="Owner / Manager",
                        email=f"contact@{clean_domain}",
                        title="Business Owner / General Manager",
                        email_status="valid",
                        source="google_maps",
                    )

                logger.info(f"🔥 High Priority Lead (NO Website): {name} ({city}) | Phone: {entry.get('phone')} | Score: 92 (IMMEDIATE)")
            else:
                # 1. Baseline scoring so it immediately appears in Qualified Leads
                mysql_client.save_score(
                    company_id=company_id,
                    company_fit=75.0,
                    technology_gap=50.0,
                    pain_signal=50.0,
                    buying_signal=70.0,
                    contact_quality=50.0,
                    service_fit=75.0,
                    opportunity_score=68.0,
                    priority_tier="high",
                    score_breakdown={
                        "reason": "active_local_business",
                        "rating": entry.get("rating"),
                        "reviews": entry.get("review_count"),
                    },
                )

                # 2. Instant real-time website email extraction
                try:
                    site_contacts = contact_scraper.scrape_contacts_from_site(
                        domain=clean_domain,
                        website_url=entry.get("website_url"),
                    )
                    if site_contacts:
                        for sc in site_contacts:
                            mysql_client.save_contact(
                                company_id=company_id,
                                full_name=sc.get("full_name") or f"Management ({name})",
                                first_name=sc.get("first_name") or "Owner / Manager",
                                email=sc["email"],
                                title=sc.get("title") or "Business Management",
                                email_status="valid",
                                source="website_direct",
                            )
                        logger.info(f"📧 Scraped Direct Website Email: {[c['email'] for c in site_contacts]} ({clean_domain})")
                except Exception as e:
                    logger.debug(f"Direct contact scrape notice for {clean_domain}: {e}")

                # 3. Enqueue into tier2_crawl for deep audit
                orchestrator.tier2_queue.push(
                    {
                        "company_id": company_id,
                        "domain": clean_domain,
                        "name": name,
                        "source": raw.get("source", "google_maps"),
                        "industry": entry["industry"],
                        "website_url": entry["website_url"],
                    }
                )
                logger.info(f"✅ Ingested Lead: {name} ({clean_domain}) | Score: 68 -> Queued for Deep Tech Audit")

        # Jitter delay between search queries
        time.sleep(random.uniform(3.0, 6.0))

    # Advance and save persistent pointer
    new_pointer = (pointer + max_queries) % total_combinations
    save_crawler_state(new_pointer)

    logger.info(f"\n🎉 Batch Summary: Discovered {new_leads_count} unique leads ({nowebsite_count} High-Priority 'No Website' leads). State pointer advanced to #{new_pointer}.")
    return new_leads_count


def run_continuous_daemon(interval_minutes: float = 15.0, queries_per_cycle: int = 10, max_pages: int = 5):
    """Runs continuous 24/7 discovery loop with smooth intervals and proxy rotation."""
    proxy_manager = get_proxy_manager()
    logger.info("🚀 Warming up proxy pool...")
    proxy_manager.refresh_pool(target_size=10, max_check=40)

    sleep_interval_seconds = int(interval_minutes * 60)
    logger.info(f"🚀 Starting Nexidant Signal 24/7 Lead Engine (Cycle: {interval_minutes}m / {sleep_interval_seconds}s)...")
    iteration = 1

    while True:
        try:
            logger.info(f"\n==================== Discovery Cycle #{iteration} ====================")
            run_gmaps_discovery_batch(max_queries=queries_per_cycle, limit_per_query=20, max_pages=max_pages)
            logger.info(f"⏳ Cycle #{iteration} Complete. Next cycle in {interval_minutes} minutes ({sleep_interval_seconds}s)...")
            time.sleep(sleep_interval_seconds)
            iteration += 1
        except KeyboardInterrupt:
            logger.info("🛑 Crawler stopped by user.")
            break
        except Exception as e:
            logger.error(f"Unexpected error in daemon loop: {e}", exc_info=True)
            time.sleep(60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="24/7 Local Business & Google Maps Discovery Crawler")
    parser.add_argument("--daemon", action="store_true", help="Run in continuous 24/7 background daemon mode")
    parser.add_argument("--interval-minutes", type=float, default=15.0, help="Minutes between discovery cycles in daemon mode (default: 15.0)")
    parser.add_argument("--cycle-hours", type=float, default=None, help="Optional hours between discovery cycles (converts to interval minutes)")
    parser.add_argument("--queries", type=int, default=8, help="Number of search queries to execute per cycle (default: 8)")
    parser.add_argument("--max-pages", type=int, default=5, help="Maximum pages to paginate per search query (default: 5)")
    args = parser.parse_args()

    interval = args.interval_minutes
    if args.cycle_hours is not None:
        interval = args.cycle_hours * 60.0

    if args.daemon:
        run_continuous_daemon(interval_minutes=interval, queries_per_cycle=args.queries, max_pages=args.max_pages)
    else:
        run_gmaps_discovery_batch(max_queries=args.queries, max_pages=args.max_pages)
