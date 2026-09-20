import argparse
import itertools
import json
import logging
import os
import random
import re
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

# 80 High-Value Local Service Verticals (High Budget for Custom Websites, Booking, & SEO)
TARGET_NICHES = [
    # Dental & Oral Care
    "Dental Clinic", "Cosmetic Dentistry", "Pediatric Dentist", "Orthodontist",
    "Periodontist", "Endodontist", "Oral Surgeon", "Emergency Dentist",
    # Medical, Aesthetic & Wellness
    "Medical Spa & Aesthetics", "Plastic Surgery Center", "Dermatology Clinic",
    "Chiropractor", "Physical Therapy Clinic", "Optometrist & Eyecare", "Podiatrist Clinic",
    "Urgent Care Clinic", "Mental Health & Therapy", "Acupuncture & Holistic Wellness",
    "Weight Loss Clinic", "Audiologist & Hearing Care", "Vein Clinic",
    # Legal Services
    "Personal Injury Lawyer", "Commercial Law Firm", "Criminal Defense Attorney",
    "Family & Divorce Lawyer", "Estate Planning Attorney", "Immigration Lawyer",
    "Bankruptcy Attorney", "Real Estate Attorney", "Employment Lawyer", "Tax Attorney",
    # Construction, Remodeling & Trades
    "Roofing Contractor", "Plumbing & HVAC", "Commercial Electrician", "General Contractor",
    "Custom Home Builder", "Kitchen & Bath Remodeling", "Foundation Repair & Waterproofing",
    "Solar Installation", "Landscaping & Hardscaping", "Tree Service & Removal",
    "Pool Builder & Service", "Painting Contractor", "Flooring Contractor",
    "Paving & Concrete Contractor", "Fencing Contractor", "Garage Door Repair",
    "Water Damage Restoration", "Mold Remediation", "Window & Door Replacement",
    "HVAC Repair & Service", "Commercial Plumbing", "Siding Contractor",
    "Cabinet Maker & Custom Woodworking", "Insulation Contractor", "Masonry Contractor",
    # Automotive
    "Auto Repair & Body Shop", "Collision Repair Center", "Auto Detailing & Ceramic Coating",
    "Transmission Repair", "Tire Shop & Wheel Alignment", "Towing & Roadside Service",
    "Windshield & Auto Glass Repair", "Custom Auto Shop",
    # Professional & B2B Services
    "Accounting & CPA", "Bookkeeping & Payroll", "Wealth Management Advisor",
    "Insurance Agency", "Real Estate Brokerage", "Commercial Real Estate",
    "Property Management", "Mortgage Broker", "IT Services & MSP",
    "Architecture Firm", "Civil Engineering Firm", "Commercial Cleaning", "Janitorial Services",
    # Hospitality, Events & Specialty
    "Catering & Event Venue", "Wedding Planner", "Photography Studio",
    "Veterinary Hospital", "Emergency Animal Hospital", "Dog Training & Boarding",
    "Pet Grooming Salon", "Moving & Storage Company", "Commercial Locksmith",
    "Security System Installation", "Martial Arts Academy"
]

# Top 260 US Cities and High-Growth Metro Markets across all 50 states
US_METROS = [
    # Top 20 Metros
    "New York, NY", "Los Angeles, CA", "Chicago, IL", "Houston, TX", "Phoenix, AZ",
    "Philadelphia, PA", "San Antonio, TX", "San Diego, CA", "Dallas, TX", "Austin, TX",
    "San Jose, CA", "Fort Worth, TX", "Jacksonville, FL", "Columbus, OH", "Charlotte, NC",
    "Indianapolis, IN", "San Francisco, CA", "Seattle, WA", "Denver, CO", "Oklahoma City, OK",
    # Tier 1 Metros & Capital Hubs
    "Nashville, TN", "El Paso, TX", "Washington, DC", "Boston, MA", "Las Vegas, NV",
    "Portland, OR", "Detroit, MI", "Louisville, KY", "Memphis, TN", "Baltimore, MD",
    "Milwaukee, WI", "Albuquerque, NM", "Fresno, CA", "Tucson, AZ", "Sacramento, CA",
    "Mesa, AZ", "Kansas City, MO", "Atlanta, GA", "Omaha, NE", "Colorado Springs, CO",
    "Raleigh, NC", "Virginia Beach, VA", "Miami, FL", "Oakland, CA", "Minneapolis, MN",
    "Tulsa, OK", "Bakersfield, CA", "Wichita, KS", "Arlington, TX", "Aurora, CO",
    "Tampa, FL", "New Orleans, LA", "Cleveland, OH", "Honolulu, HI", "Anaheim, CA",
    "Henderson, NV", "Stockton, CA", "Lexington, KY", "Corpus Christi, TX", "Irvine, CA",
    "Riverside, CA", "Newark, NJ", "Saint Paul, MN", "Santa Ana, CA", "Cincinnati, OH",
    "Greensboro, NC", "Pittsburgh, PA", "St. Louis, MO", "Lincoln, NE", "Orlando, FL",
    "Durham, NC", "Plano, TX", "Anchorage, AK", "Chula Vista, CA", "Fort Wayne, IN",
    "Chandler, AZ", "Toledo, OH", "Scottsdale, AZ", "Reno, NV", "Madison, WI",
    "Gilbert, AZ", "Buffalo, NY", "Glendale, AZ", "North Las Vegas, NV", "Winston-Salem, NC",
    "Chesapeake, VA", "Norfolk, VA", "Fremont, CA", "Garland, TX", "Irving, TX",
    "Hialeah, FL", "Richmond, VA", "Boise, ID", "Spokane, WA", "Baton Rouge, LA",
    "Des Moines, IA", "Tacoma, WA", "San Bernardino, CA", "Modesto, CA", "Fontana, CA",
    "Santa Clarita, CA", "Birmingham, AL", "Oxnard, CA", "Fayetteville, NC", "Rochester, NY",
    "Moreno Valley, CA", "Amarillo, TX", "Huntington Beach, CA", "Grand Rapids, MI", "Salt Lake City, UT",
    "Tallahassee, FL", "Huntsville, AL", "Peoria, AZ", "Knoxville, TN", "Worcester, MA",
    "Newport News, VA", "Brownsville, TX", "Overland Park, KS", "Santa Rosa, CA", "Garden Grove, CA",
    "Chattanooga, TN", "Providence, RI", "Fort Lauderdale, FL", "Cary, NC", "Port St. Lucie, CA",
    "Cape Coral, FL", "Sioux Falls, SD", "Springfield, MO", "Tempe, AZ", "Eugene, OR",
    "Salem, OR", "Rockford, IL", "McKinney, TX", "Frisco, TX", "Pasadena, CA",
    "Alexandria, VA", "Sunnyvale, CA", "Lakewood, CO", "Lancaster, CA", "Bellevue, WA",
    "Concord, CA", "Clarksville, TN", "Hollywood, FL", "Paterson, NJ", "Bridgeport, CT",
    "Torrance, CA", "Naperville, IL", "Savannah, GA", "Olathe, KS", "Gainesville, FL",
    "Fullerton, CA", "Killeen, TX", "Syracuse, NY", "Waco, TX", "Roseville, CA",
    "Denton, TX", "Surprise, AZ", "Roseville, CA", "Thornton, CO", "Pasadena, TX",
    "Charleston, SC", "Joliet, IL", "McAllen, TX", "Midland, TX", "Sterling Heights, MI",
    # Affluent Suburbs & Booming Metros
    "Coral Gables, FL", "Boca Raton, FL", "Delray Beach, FL", "West Palm Beach, FL", "Sarasota, FL",
    "Naples, FL", "Clearwater, FL", "Saint Petersburg, FL", "The Woodlands, TX", "Sugar Land, TX",
    "Round Rock, TX", "New Braunfels, TX", "Pearland, TX", "Frisco, TX", "Prosper, TX",
    "Southlake, TX", "Grapevine, TX", "Alpharetta, GA", "Marietta, GA", "Roswell, GA",
    "Sandy Springs, GA", "Johns Creek, GA", "Duluth, GA", "Franklin, TN", "Brentwood, TN",
    "Murfreesboro, TN", "Hendersonville, TN", "Mount Juliet, TN", "Greenville, SC", "Columbia, SC",
    "Mount Pleasant, SC", "Rock Hill, SC", "Hilton Head, SC", "Wilmington, NC", "Asheville, NC",
    "Apex, NC", "Holly Springs, NC", "Huntersville, NC", "Mooresville, NC", "Concord, NC",
    "Bellevue, WA", "Kirkland, WA", "Redmond, WA", "Renton, WA", "Bellingham, WA",
    "Beaverton, OR", "Bend, OR", "Hillsboro, OR", "Lake Oswego, OR", "Tigard, OR",
    "Boulder, CO", "Fort Collins, CO", "Longmont, CO", "Castle Rock, CO", "Centennial, CO",
    "Parker, CO", "Broomfield, CO", "Loveland, CO", "Greeley, CO", "Grand Junction, CO",
    "Carmel, IN", "Fishers, IN", "Noblesville, IN", "Greenwood, IN", "Bloomington, IN",
    "Ann Arbor, MI", "Troy, MI", "Novi, MI", "Rochester Hills, MI", "Royal Oak, MI",
    "Naperville, IL", "Schaumburg, IL", "Evanston, IL", "Arlington Heights, IL", "Oak Park, IL",
    "Overland Park, KS", "Leawood, KS", "Olathe, KS", "Lenexa, KS", "Shawnee, KS",
    "Scottsdale, AZ", "Paradise Valley, AZ", "Chandler, AZ", "Gilbert, AZ", "Queen Creek, AZ",
    "Newport Beach, CA", "Beverly Hills, CA", "Santa Monica, CA", "Pasadena, CA", "Laguna Beach, CA",
    "Carlsbad, CA", "Encinitas, CA", "San Clemente, CA", "Temecula, CA", "Palm Springs, CA"
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
            try:
                entry = feed.parse_entry(raw)
            except Exception as e:
                logger.debug(f"Error parsing raw lead entry: {e}")
                continue

            clean_domain = entry["domain"]
            name = entry["name"]
            has_website = entry["has_website"]

            # Redis & MySQL Deduplication (Domain & Company Name)
            if orchestrator.redis_client.is_domain_seen(clean_domain):
                logger.debug(f"Skipping duplicate domain (seen in Redis): {clean_domain}")
                continue

            if name and orchestrator.redis_client.is_name_seen(name, city=city):
                logger.debug(f"Skipping duplicate company name (seen in Redis): {name}")
                continue

            existing_db = orchestrator.mysql_client.get_company_by_domain(clean_domain)
            if existing_db:
                orchestrator.redis_client.mark_domain_seen(clean_domain)
                if name:
                    orchestrator.redis_client.mark_name_seen(name, city=city)
                logger.debug(f"Skipping duplicate company #{existing_db['id']}: {name}")
                continue

            if name:
                slug_city = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")
                existing_name_db = orchestrator.mysql_client.get_company_by_name(name, city_slug=slug_city)
                if existing_name_db:
                    orchestrator.redis_client.mark_domain_seen(clean_domain)
                    orchestrator.redis_client.mark_name_seen(name, city=city)
                    logger.debug(f"Skipping duplicate company #{existing_name_db['id']} by name match: {name}")
                    continue

            orchestrator.redis_client.mark_domain_seen(clean_domain)
            if name:
                orchestrator.redis_client.mark_name_seen(name, city=city)

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
                    type="new_website_creation",
                    recommended_service="Turnkey High-Converting Web & Online Booking Portal",
                    estimated_value_low=2500,
                    estimated_value_high=5000,
                    confidence=1.0,
                    evidence={
                        "phone": entry.get("phone"),
                        "rating": entry.get("rating"),
                        "review_count": entry.get("review_count"),
                        "intent": "high_converting_booking_portal",
                        "pain_point": "Established local business with active local traction, but no website to capture mobile search traffic.",
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

                # 4. Multi-Engine Web Search Discovery: Discovers Official Website & Verified Inboxes
                search_discovery = local_email_finder.find_business_website_and_email(
                    business_name=name,
                    city=city,
                    phone=entry.get("phone")
                )

                if search_discovery.get("domain"):
                    new_dom = search_discovery["domain"]
                    new_url = search_discovery.get("website_url")
                    mysql_client.update_company_domain(company_id, new_dom, new_url)
                    logger.info(f"🌐 Discovered Official Website for '{name}': {new_url} (Domain: {new_dom})")

                discovered_emails = search_discovery.get("contacts", [])
                if discovered_emails:
                    for ct in discovered_emails:
                        mysql_client.save_contact(
                            company_id=company_id,
                            full_name=ct.get("full_name") or f"Management ({name})",
                            first_name=ct.get("first_name") or None,
                            email=ct["email"],
                            title=ct.get("title") or "Business Owner / General Manager",
                            email_status=ct.get("email_status", "valid"),
                            source=ct.get("source", "search_engine_discovery"),
                        )
                    logger.info(f"📧 Found Direct Email for '{name}': {[c['email'] for c in discovered_emails]}")
                elif entry.get("phone"):
                    logger.info(f"📞 Recorded Phone-Only Lead: {name} ({city}) | Phone: {entry.get('phone')}")

                logger.info(f"🔥 High Priority Lead: {name} ({city}) | Phone: {entry.get('phone')} | Score: 92 (IMMEDIATE)")
            else:
                # 1. Unaudited lead: marked as pending_audit (CANNOT be sent outreach until crawled & audited)
                mysql_client.save_score(
                    company_id=company_id,
                    company_fit=0.0,
                    technology_gap=0.0,
                    pain_signal=0.0,
                    buying_signal=0.0,
                    contact_quality=0.0,
                    service_fit=0.0,
                    opportunity_score=0.0,
                    priority_tier="pending_audit",
                    score_breakdown={
                        "status": "pending_crawl_and_audit",
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
                                first_name=sc.get("first_name") or None,
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
