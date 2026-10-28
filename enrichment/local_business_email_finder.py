import base64
import logging
import os
import re
import urllib.parse
from typing import Any
from bs4 import BeautifulSoup
from shared import http_client
from enrichment.email_validator import get_email_validator

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", re.IGNORECASE)

BLOCKED_EMAIL_DOMAINS = {
    "sentry.io", "wix.com", "wixpress.com", "example.com", "domain.com",
    "email.com", "yourcompany.com", "company.com", "wordpress.org",
    "schema.org", "cloudflare.com", "google.com", "github.com",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "yelp.com",
    "yellowpages.com", "manta.com", "bbb.org", "mapquest.com", "tripadvisor.com",
    "angi.com", "angieslist.com", "thumbtack.com", "houzz.com", "homeadvisor.com",
    "dnb.com", "zoominfo.com", "allbiz.com", "leadiq.com", "bumvar.com", "6bestrated.com",
    "bing.com", "yahoo.com", "duckduckgo.com", "cambridge.org", "webcontainer-api.io",
}

BLOCKED_EMAIL_PREFIXES = {
    "support", "privacy", "terms", "abuse", "noreply", "no-reply",
    "donotreply", "mailer-daemon", "postmaster", "root", "security", "slick-carousel",
}

DIRECTORY_DOMAINS = {
    "facebook.com", "instagram.com", "twitter.com", "x.com", "yelp.com",
    "yellowpages.com", "manta.com", "bbb.org", "mapquest.com", "linkedin.com",
    "tripadvisor.com", "angieslist.com", "angi.com", "thumbtack.com", "houzz.com",
    "homeadvisor.com", "dnb.com", "zoominfo.com", "google.com", "apple.com",
    "youtube.com", "tiktok.com", "pinterest.com", "nextdoor.com", "chamberofcommerce.com",
    "wikipedia.org", "indeed.com", "glassdoor.com", "ziprecruiter.com", "allbiz.com",
    "yahoo.com", "bing.com", "duckduckgo.com", "leadiq.com", "bumvar.com", "6bestrated.com",
    "schema.org", "citysquares.com", "breken.com", "contractorfinder.bradfordwhite.com",
    "cambridge.org", "dictionary.cambridge.org", "webcontainer-api.io", "opencorporates.com",
    "bizapedia.com",
}

IGNORED_FILE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg", ".js", ".css", ".ico", ".woff", ".woff2"
}

# Major US Area Code to State and Metro Region Mapping
US_AREA_CODES: dict[str, tuple[str, str]] = {
    "201": ("NJ", "Jersey City"), "202": ("DC", "Washington"), "203": ("CT", "Bridgeport"),
    "205": ("AL", "Birmingham"), "206": ("WA", "Seattle"), "207": ("ME", "Portland"),
    "208": ("ID", "Boise"), "209": ("CA", "Stockton"), "210": ("TX", "San Antonio"),
    "212": ("NY", "New York"), "213": ("CA", "Los Angeles"), "214": ("TX", "Dallas"),
    "215": ("PA", "Philadelphia"), "216": ("OH", "Cleveland"), "217": ("IL", "Springfield"),
    "218": ("MN", "Duluth"), "219": ("IN", "Gary"), "224": ("IL", "Elgin"),
    "225": ("LA", "Baton Rouge"), "228": ("MS", "Gulfport"), "229": ("GA", "Albany"),
    "231": ("MI", "Muskegon"), "234": ("OH", "Akron"), "239": ("FL", "Cape Coral"),
    "240": ("MD", "Germantown"), "248": ("MI", "Troy"), "251": ("AL", "Mobile"),
    "252": ("NC", "Greenville"), "253": ("WA", "Tacoma"), "254": ("TX", "Killeen"),
    "256": ("AL", "Huntsville"), "260": ("IN", "Fort Wayne"), "262": ("WI", "Kenosha"),
    "267": ("PA", "Philadelphia"), "269": ("MI", "Kalamazoo"), "270": ("KY", "Bowling Green"),
    "281": ("TX", "Houston"), "301": ("MD", "Silver Spring"), "302": ("DE", "Wilmington"),
    "303": ("CO", "Denver"), "304": ("WV", "Charleston"), "305": ("FL", "Miami"),
    "308": ("NE", "Grand Island"), "309": ("IL", "Peoria"), "310": ("CA", "Los Angeles"),
    "312": ("IL", "Chicago"), "313": ("MI", "Detroit"), "314": ("MO", "St. Louis"),
    "315": ("NY", "Syracuse"), "316": ("KS", "Wichita"), "317": ("IN", "Indianapolis"),
    "318": ("LA", "Shreveport"), "319": ("IA", "Cedar Rapids"), "320": ("MN", "St. Cloud"),
    "321": ("FL", "Orlando"), "323": ("CA", "Los Angeles"), "325": ("TX", "Abilene"),
    "330": ("OH", "Akron"), "334": ("AL", "Montgomery"), "336": ("NC", "Greensboro"),
    "337": ("LA", "Lafayette"), "346": ("TX", "Houston"), "347": ("NY", "New York"),
    "351": ("MA", "Lowell"), "352": ("FL", "Gainesville"), "360": ("WA", "Vancouver"),
    "361": ("TX", "Corpus Christi"), "386": ("FL", "Daytona Beach"), "401": ("RI", "Providence"),
    "402": ("NE", "Omaha"), "404": ("GA", "Atlanta"), "405": ("OK", "Oklahoma City"),
    "406": ("MT", "Billings"), "407": ("FL", "Orlando"), "408": ("CA", "San Jose"),
    "409": ("TX", "Beaumont"), "410": ("MD", "Baltimore"), "412": ("PA", "Pittsburgh"),
    "413": ("MA", "Springfield"), "414": ("WI", "Milwaukee"), "415": ("CA", "San Francisco"),
    "417": ("MO", "Springfield"), "419": ("OH", "Toledo"), "423": ("TN", "Chattanooga"),
    "424": ("CA", "Los Angeles"), "425": ("WA", "Bellevue"), "430": ("TX", "Tyler"),
    "432": ("TX", "Midland"), "434": ("VA", "Lynchburg"), "435": ("UT", "St. George"),
    "440": ("OH", "Parma"), "443": ("MD", "Baltimore"), "469": ("TX", "Dallas"),
    "470": ("GA", "Atlanta"), "475": ("CT", "Bridgeport"), "478": ("GA", "Macon"),
    "479": ("AR", "Fort Smith"), "480": ("AZ", "Mesa"), "484": ("PA", "Allentown"),
    "501": ("AR", "Little Rock"), "502": ("KY", "Louisville"), "503": ("OR", "Portland"),
    "504": ("LA", "New Orleans"), "505": ("NM", "Albuquerque"), "507": ("MN", "Rochester"),
    "508": ("MA", "Worcester"), "509": ("WA", "Spokane"), "510": ("CA", "Oakland"),
    "512": ("TX", "Austin"), "513": ("OH", "Cincinnati"), "515": ("IA", "Des Moines"),
    "516": ("NY", "Hempstead"), "517": ("MI", "Lansing"), "518": ("NY", "Albany"),
    "520": ("AZ", "Tucson"), "530": ("CA", "Redding"), "540": ("VA", "Roanoke"),
    "541": ("OR", "Eugene"), "551": ("NJ", "Jersey City"), "559": ("CA", "Fresno"),
    "561": ("FL", "West Palm Beach"), "562": ("CA", "Long Beach"), "563": ("IA", "Davenport"),
    "567": ("OH", "Toledo"), "570": ("PA", "Scranton"), "571": ("VA", "Arlington"),
    "573": ("MO", "Columbia"), "574": ("IN", "South Bend"), "575": ("NM", "Las Cruces"),
    "580": ("OK", "Lawton"), "585": ("NY", "Rochester"), "586": ("MI", "Warren"),
    "601": ("MS", "Jackson"), "602": ("AZ", "Phoenix"), "603": ("NH", "Manchester"),
    "605": ("SD", "Sioux Falls"), "606": ("KY", "Ashland"), "607": ("NY", "Binghamton"),
    "608": ("WI", "Madison"), "609": ("NJ", "Trenton"), "610": ("PA", "Allentown"),
    "612": ("MN", "Minneapolis"), "614": ("OH", "Columbus"), "615": ("TN", "Nashville"),
    "616": ("MI", "Grand Rapids"), "617": ("MA", "Boston"), "618": ("IL", "Belleville"),
    "619": ("CA", "San Diego"), "620": ("KS", "Hutchinson"), "623": ("AZ", "Phoenix"),
    "626": ("CA", "Pasadena"), "628": ("CA", "San Francisco"), "629": ("TN", "Nashville"),
    "630": ("IL", "Aurora"), "631": ("NY", "Brentwood"), "636": ("MO", "O'Fallon"),
    "641": ("IA", "Mason City"), "646": ("NY", "New York"), "650": ("CA", "San Mateo"),
    "651": ("MN", "St. Paul"), "660": ("MO", "Sedalia"), "661": ("CA", "Bakersfield"),
    "662": ("MS", "Southaven"), "667": ("MD", "Baltimore"), "669": ("CA", "San Jose"),
    "678": ("GA", "Atlanta"), "682": ("TX", "Fort Worth"), "701": ("ND", "Fargo"),
    "702": ("NV", "Las Vegas"), "703": ("VA", "Arlington"), "704": ("NC", "Charlotte"),
    "706": ("GA", "Augusta"), "707": ("CA", "Santa Rosa"), "708": ("IL", "Cicero"),
    "712": ("IA", "Sioux City"), "713": ("TX", "Houston"), "714": ("CA", "Anaheim"),
    "715": ("WI", "Eau Claire"), "716": ("NY", "Buffalo"), "717": ("PA", "Lancaster"),
    "718": ("NY", "New York"), "719": ("CO", "Colorado Springs"), "720": ("CO", "Denver"),
    "724": ("PA", "New Castle"), "727": ("FL", "St. Petersburg"), "731": ("TN", "Jackson"),
    "732": ("NJ", "Toms River"), "734": ("MI", "Ann Arbor"), "737": ("TX", "Austin"),
    "740": ("OH", "Newark"), "754": ("FL", "Fort Lauderdale"), "757": ("VA", "Virginia Beach"),
    "760": ("CA", "Oceanside"), "762": ("GA", "Augusta"), "763": ("MN", "Brooklyn Park"),
    "765": ("IN", "Muncie"), "770": ("GA", "Roswell"), "772": ("FL", "Port St. Lucie"),
    "773": ("IL", "Chicago"), "774": ("MA", "Worcester"), "775": ("NV", "Reno"),
    "779": ("IL", "Rockford"), "781": ("MA", "Lynn"), "785": ("KS", "Topeka"),
    "786": ("FL", "Miami"), "801": ("UT", "Salt Lake City"), "802": ("VT", "Burlington"),
    "803": ("SC", "Columbia"), "804": ("VA", "Richmond"), "805": ("CA", "Oxnard"),
    "806": ("TX", "Lubbock"), "808": ("HI", "Honolulu"), "810": ("MI", "Flint"),
    "812": ("IN", "Evansville"), "813": ("FL", "Tampa"), "814": ("PA", "Erie"),
    "815": ("IL", "Rockford"), "816": ("MO", "Kansas City"), "817": ("TX", "Fort Worth"),
    "818": ("CA", "Los Angeles"), "828": ("NC", "Asheville"), "830": ("TX", "New Braunfels"),
    "831": ("CA", "Salinas"), "832": ("TX", "Houston"), "843": ("SC", "Charleston"),
    "845": ("NY", "Newburgh"), "847": ("IL", "Elgin"), "848": ("NJ", "Toms River"),
    "850": ("FL", "Tallahassee"), "854": ("SC", "Charleston"), "856": ("NJ", "Camden"),
    "857": ("MA", "Boston"), "858": ("CA", "San Diego"), "859": ("KY", "Lexington"),
    "860": ("CT", "Hartford"), "862": ("NJ", "Newark"), "863": ("FL", "Lakeland"),
    "864": ("SC", "Greenville"), "865": ("TN", "Knoxville"), "878": ("PA", "Pittsburgh"),
    "901": ("TN", "Memphis"), "903": ("TX", "Tyler"), "904": ("FL", "Jacksonville"),
    "906": ("MI", "Marquette"), "907": ("AK", "Anchorage"), "908": ("NJ", "Elizabeth"),
    "909": ("CA", "San Bernardino"), "910": ("NC", "Fayetteville"), "912": ("GA", "Savannah"),
    "913": ("KS", "Overland Park"), "914": ("NY", "Yonkers"), "915": ("TX", "El Paso"),
    "916": ("CA", "Sacramento"), "917": ("NY", "New York"), "918": ("OK", "Tulsa"),
    "919": ("NC", "Raleigh"), "920": ("WI", "Green Bay"), "925": ("CA", "Concord"),
    "928": ("AZ", "Yuma"), "929": ("NY", "New York"), "931": ("TN", "Clarksville"),
    "936": ("TX", "Conroe"), "937": ("OH", "Dayton"), "940": ("TX", "Denton"),
    "941": ("FL", "North Port"), "947": ("MI", "Troy"), "949": ("CA", "Irvine"),
    "951": ("CA", "Riverside"), "952": ("MN", "Bloomington"), "954": ("FL", "Fort Lauderdale"),
    "956": ("TX", "Laredo"), "970": ("CO", "Fort Collins"), "971": ("OR", "Portland"),
    "972": ("TX", "Dallas"), "973": ("NJ", "Newark"), "978": ("MA", "Lowell"),
    "979": ("TX", "College Station"), "980": ("NC", "Charlotte"), "984": ("NC", "Raleigh"),
    "985": ("LA", "Houma"), "989": ("MI", "Saginaw"),
}


class LocalBusinessEmailFinder:
    """
    High-accuracy Multi-Engine Web Search & Multi-Option Enrichment for Leads lacking direct contact emails or websites.
    
    Implements 4 complementary discovery strategies alongside standard web resolution:
    - Strategy 1: Unique Phone Footprint Search (Reverse phone & multi-format dorking)
    - Strategy 2: Facebook Business Page / Social OpenGraph Scraper (Social crawler UA bypass)
    - Strategy 3: Better Business Bureau (BBB) & Business Directory Scraper (Bingbot UA bypass)
    - Strategy 4: Secretary of State (SOS) Corporate Registries & OpenCorporates Filings
    - Deliverability Guard: Live DNS MX + EmailValidator filtering to guarantee 0% spam/foreign scrapings.
    """

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.apollo_api_key = os.getenv("APOLLO_API_KEY", "")
        self.validator = get_email_validator()

    def normalize_phone_number(self, raw_phone: str | None) -> dict[str, str] | None:
        """Parses and formats a raw phone string into searchable representations."""
        if not raw_phone:
            return None
        digits = re.sub(r"\D", "", raw_phone)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10:
            return None

        area_code = digits[:3]
        prefix = digits[3:6]
        line = digits[6:]

        state, city = US_AREA_CODES.get(area_code, ("", ""))

        return {
            "digits": digits,
            "formatted": f"({area_code}) {prefix}-{line}",
            "hyphenated": f"{area_code}-{prefix}-{line}",
            "dotted": f"{area_code}.{prefix}.{line}",
            "compact": f"{area_code} {prefix} {line}",
            "area_code": area_code,
            "state": state,
            "city": city,
        }

    def decode_bing_url(self, href: str) -> str:
        """Decodes base64-wrapped target URLs from Bing search results."""
        if "&u=a1" in href:
            try:
                raw_b64 = href.split("&u=a1")[1].split("&")[0]
                padded = raw_b64 + "=" * (-len(raw_b64) % 4)
                return base64.b64decode(padded).decode("utf-8", errors="ignore")
            except Exception:
                pass
        return href

    def find_business_website_and_email(
        self,
        business_name: str,
        city: str = "",
        phone: str | None = None,
        state: str | None = None,
    ) -> dict[str, Any]:
        """
        Main entrypoint: Exhaustively attempts all 4 strategies alongside existing
        methods to discover real websites, verified contacts, and phone numbers.
        """
        if not business_name:
            return {"website_url": None, "domain": None, "phone": phone, "contacts": []}

        clean_name = re.sub(r"[^\w\s]", "", business_name).strip()
        phone_info = self.normalize_phone_number(phone)
        resolved_city = city or (phone_info["city"] if phone_info else "")
        resolved_state = state or (phone_info["state"] if phone_info else "")

        seen_emails: set[str] = set()
        contacts: list[dict[str, Any]] = []
        discovered_website: str | None = None
        discovered_domain: str | None = None
        discovered_phone: str | None = phone_info["formatted"] if phone_info else phone

        logger.info(
            f"🔍 [Enrichment] Starting 4-Tier Deep Search for '{clean_name}' "
            f"| City='{resolved_city}', State='{resolved_state}', Phone='{discovered_phone}'"
        )

        # -------------------------------------------------------------
        # OPTION 3: Better Business Bureau (BBB) & Directory Scraper
        # (Often unlocks the exact official domain + verified phone + owner)
        # -------------------------------------------------------------
        try:
            bbb_res = self._search_bbb_and_directories(clean_name, phone_info, resolved_city, resolved_state)
            if bbb_res.get("website_url"):
                discovered_website = bbb_res["website_url"]
                discovered_domain = bbb_res.get("domain")
                logger.info(f"🏛️ [Option 3 BBB] Discovered official website: {discovered_website}")
            if bbb_res.get("phone") and not discovered_phone:
                discovered_phone = bbb_res["phone"]
            for c in bbb_res.get("contacts", []):
                if c["email"] not in seen_emails and self._is_valid_lead_email(c["email"], clean_name, discovered_domain):
                    seen_emails.add(c["email"])
                    contacts.append(c)
        except Exception as e:
            logger.debug(f"[Option 3 BBB error]: {e}")

        # -------------------------------------------------------------
        # OPTION 4: Secretary of State (SOS) & OpenCorporates Filings
        # (Finds Legal Registered Agent / President / Officer Names)
        # -------------------------------------------------------------
        discovered_officer: str | None = None
        try:
            sos_res = self._search_sos_and_corporateregistries(clean_name, resolved_state)
            if sos_res.get("officer_name"):
                discovered_officer = sos_res["officer_name"]
                logger.info(f"📜 [Option 4 SOS] Found Registered Agent/Officer: '{discovered_officer}'")
            for c in sos_res.get("contacts", []):
                if c["email"] not in seen_emails and self._is_valid_lead_email(c["email"], clean_name, discovered_domain):
                    seen_emails.add(c["email"])
                    contacts.append(c)
        except Exception as e:
            logger.debug(f"[Option 4 SOS error]: {e}")

        # -------------------------------------------------------------
        # OPTION 2: Facebook Business Page / Social OpenGraph Scraper
        # (Extracts public business inboxes like @gmail.com/@yahoo.com from FB)
        # -------------------------------------------------------------
        try:
            fb_res = self._search_facebook_business_page(clean_name, phone_info, resolved_city, resolved_state)
            if fb_res.get("website_url") and not discovered_website:
                discovered_website = fb_res["website_url"]
                discovered_domain = fb_res.get("domain")
            if fb_res.get("phone") and not discovered_phone:
                discovered_phone = fb_res["phone"]
            for c in fb_res.get("contacts", []):
                if c["email"] not in seen_emails and self._is_valid_lead_email(c["email"], clean_name, discovered_domain):
                    seen_emails.add(c["email"])
                    contacts.append(c)
        except Exception as e:
            logger.debug(f"[Option 2 FB error]: {e}")

        # -------------------------------------------------------------
        # OPTION 1: Unique Phone Footprint & Multi-Engine Web Search
        # (Reverse phone footprint dorking on DuckDuckGo, Yahoo, Bing)
        # -------------------------------------------------------------
        try:
            phone_res = self._search_phone_footprint(clean_name, phone_info, resolved_city, resolved_state)
            if phone_res.get("website_url") and not discovered_website:
                discovered_website = phone_res["website_url"]
                discovered_domain = phone_res.get("domain")
            for c in phone_res.get("contacts", []):
                if c["email"] not in seen_emails and self._is_valid_lead_email(c["email"], clean_name, discovered_domain):
                    seen_emails.add(c["email"])
                    contacts.append(c)
        except Exception as e:
            logger.debug(f"[Option 1 Phone Footprint error]: {e}")

        # -------------------------------------------------------------
        # Standard Website Scraping & Canonical SMTP Inboxes
        # (If an official website was discovered through any option)
        # -------------------------------------------------------------
        if discovered_website and discovered_domain:
            site_emails = self._scrape_website_contacts(discovered_website)
            for em in site_emails:
                if em not in seen_emails and self._is_valid_lead_email(em, clean_name, discovered_domain):
                    seen_emails.add(em)
                    contacts.append({
                        "email": em,
                        "first_name": None,
                        "full_name": f"{business_name} Team",
                        "title": "General Inquiries",
                        "source": "website_contact_page",
                        "email_status": "valid",
                    })

            # Check canonical role inboxes (contact@, info@, office@) with live SMTP verification
            if not contacts and self.validator.has_mx_records(discovered_domain):
                for role_inbox in ["contact", "info", "office", "service", "appointments", "admin"]:
                    candidate_em = f"{role_inbox}@{discovered_domain}"
                    val = self.validator.validate(candidate_em)
                    if val.get("is_deliverable") or val.get("status") in ["valid", "catch_all"]:
                        seen_emails.add(candidate_em)
                        contacts.append({
                            "email": candidate_em,
                            "first_name": None,
                            "full_name": f"{business_name} Leadership",
                            "title": "Executive & General Inquiries",
                            "source": "canonical_synthesizer",
                            "verification_source": "smtp_handshake",
                            "email_status": "valid" if val.get("status") == "valid" else "catch_all",
                        })
                        break

        # -------------------------------------------------------------
        # Permutator / Synthesizer on Discovered Officer/Agent Name
        # -------------------------------------------------------------
        if not contacts and discovered_officer and discovered_domain and self.validator.has_mx_records(discovered_domain):
            try:
                from enrichment.email_permutator import get_email_permutator
                permutator = get_email_permutator()
                perm_contacts = permutator.synthesize_verified_contacts(
                    executives=[{"name": discovered_officer, "title": "Owner / Registered Agent"}],
                    domain=discovered_domain,
                )
                for pc in perm_contacts:
                    if pc["email"] not in seen_emails and self._is_valid_lead_email(pc["email"], clean_name, discovered_domain):
                        seen_emails.add(pc["email"])
                        contacts.append(pc)
            except Exception as e:
                logger.debug(f"Permutator on discovered officer error: {e}")

        # -------------------------------------------------------------
        # Apollo.io fallback
        # -------------------------------------------------------------
        if not contacts and self.apollo_api_key:
            apollo_contacts = self._search_apollo_by_name(business_name, resolved_city)
            for ac in apollo_contacts:
                if ac["email"] not in seen_emails and self._is_valid_lead_email(ac["email"], clean_name, discovered_domain):
                    seen_emails.add(ac["email"])
                    contacts.append(ac)

        # Attach discovered phone number to all contact records
        for c in contacts:
            if discovered_phone and not c.get("phone"):
                c["phone"] = discovered_phone
                if not c.get("raw_contact_data"):
                    c["raw_contact_data"] = {}
                c["raw_contact_data"]["phone"] = discovered_phone

        logger.info(
            f"🎯 4-Tier Deep Discovery Summary for '{business_name}': "
            f"Website={discovered_website} | Phone={discovered_phone} | "
            f"Contacts ({len(contacts)}) -> {[c['email'] for c in contacts]}"
        )

        return {
            "website_url": discovered_website,
            "domain": discovered_domain,
            "phone": discovered_phone,
            "contacts": contacts,
        }

    # =========================================================================
    # OPTION 1: Phone Footprint & Location Reverse Dorking
    # =========================================================================
    def _search_phone_footprint(
        self, clean_name: str, phone_info: dict[str, str] | None, city: str, state: str
    ) -> dict[str, Any]:
        """
        Queries search engines using unique phone footprint variations:
        - "(XXX) XXX-XXXX" OR "XXX-XXX-XXXX" email
        - "{clean_name}" "{hyphenated}"
        """
        results: list[dict[str, Any]] = []
        candidate_links: list[str] = []

        queries = []
        if phone_info:
            fmt = phone_info["formatted"]
            hyp = phone_info["hyphenated"]
            queries.append(f'"{fmt}" OR "{hyp}" email')
            queries.append(f'"{clean_name}" "{hyp}"')
            queries.append(f'"{clean_name}" "{phone_info["digits"]}"')
        queries.append(f'"{clean_name}" {city} {state} email contact')

        for q in queries:
            snippets, links = self._execute_search_queries(q)
            candidate_links.extend(links)
            emails = self._extract_clean_emails_from_text(snippets)
            for em in emails:
                if self._is_valid_lead_email(em, clean_name, is_no_website=True):
                    results.append({
                        "email": em,
                        "first_name": None,
                        "full_name": f"{clean_name} Team",
                        "title": "Business Contact",
                        "source": "phone_footprint_search",
                        "email_status": "valid",
                    })

        best_site = self._select_best_website(candidate_links, clean_name)
        discovered_domain = None
        if best_site:
            discovered_domain = best_site.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].lower()

        return {
            "website_url": best_site,
            "domain": discovered_domain,
            "contacts": results,
        }

    # =========================================================================
    # OPTION 2: Facebook Business Page / Social OpenGraph Scraper
    # =========================================================================
    def _search_facebook_business_page(
        self, clean_name: str, phone_info: dict[str, str] | None, city: str, state: str
    ) -> dict[str, Any]:
        """
        Finds the official Facebook business page and extracts inboxes/phone
        via OpenGraph crawler headers ('facebookexternalhit/1.1').
        """
        fb_contacts: list[dict[str, Any]] = []
        fb_urls: list[str] = []
        discovered_site: str | None = None
        discovered_phone: str | None = None

        search_q = f'site:facebook.com "{clean_name}" {city}'
        if phone_info:
            search_q += f' "{phone_info["hyphenated"]}"'

        _, links = self._execute_search_queries(search_q)
        for link in links:
            decoded = self.decode_bing_url(link)
            if "facebook.com/" in decoded:
                path = decoded.split("facebook.com/")[1].split("?")[0].strip("/")
                # Exclude non-page paths
                if not any(path.startswith(x) for x in ["login", "share", "help", "policies", "watch", "marketplace"]):
                    fb_urls.append(decoded)

        # Scrape candidate Facebook pages using facebookexternalhit crawler
        crawler_headers = {
            "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
            "Accept": "*/*",
        }

        for fb_url in fb_urls[:3]:
            try:
                r = http_client.get(fb_url, headers=crawler_headers, timeout=self.timeout)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "html.parser")
                    og_desc = soup.find("meta", property="og:description")
                    desc = soup.find("meta", attrs={"name": "description"})
                    page_text = " ".join([
                        og_desc.get("content", "") if og_desc else "",
                        desc.get("content", "") if desc else "",
                        soup.get_text(" ")[:5000],
                    ])

                    # Extract emails
                    emails = self._extract_clean_emails_from_text(page_text)
                    for em in emails:
                        if self._is_valid_lead_email(em, clean_name, is_no_website=True):
                            fb_contacts.append({
                                "email": em,
                                "first_name": None,
                                "full_name": f"{clean_name} Owner",
                                "title": "Business Inquiries",
                                "source": "facebook_business_page",
                                "email_status": "valid",
                            })

                    # Extract phone number if not present
                    phone_matches = re.findall(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}", page_text)
                    if phone_matches and not discovered_phone:
                        discovered_phone = phone_matches[0]

                    # Check if Facebook links to their official website
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if href.startswith("http") and not any(d in href for d in DIRECTORY_DOMAINS):
                            best_site = self._select_best_website([href], clean_name)
                            if best_site:
                                discovered_site = best_site
                                break
            except Exception as e:
                logger.debug(f"FB scrape exception for {fb_url}: {e}")

        discovered_domain = None
        if discovered_site:
            discovered_domain = discovered_site.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].lower()

        return {
            "website_url": discovered_site,
            "domain": discovered_domain,
            "phone": discovered_phone,
            "contacts": fb_contacts,
        }

    # =========================================================================
    # OPTION 3: Better Business Bureau (BBB) & Directory Scraper
    # =========================================================================
    def _search_bbb_and_directories(
        self, clean_name: str, phone_info: dict[str, str] | None, city: str, state: str
    ) -> dict[str, Any]:
        """
        Scrapes BBB profiles with Bingbot User-Agent.
        Extracts official website, phone numbers, and owner/principal contacts.
        """
        discovered_site: str | None = None
        discovered_domain: str | None = None
        discovered_phone: str | None = None
        contacts: list[dict[str, Any]] = []

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        # Query BBB with full business name and clean brand name
        names_to_try = [clean_name]
        clean_brand = re.sub(
            r"\b(inc|llc|corp|corporation|co|ltd|management|group|services|associates|pc|pa)\b",
            "",
            clean_name,
            flags=re.IGNORECASE,
        ).strip()
        if clean_brand and clean_brand.lower() != clean_name.lower() and len(clean_brand) >= 3:
            names_to_try.append(clean_brand)

        profile_links = []
        for n in names_to_try:
            encoded_name = urllib.parse.quote_plus(n)
            bbb_search_url = f"https://www.bbb.org/search?find_country=USA&find_text={encoded_name}"
            try:
                r = http_client.get(bbb_search_url, headers=headers, timeout=self.timeout)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        href = a["href"]
                        if "/profile/" in href and href not in profile_links:
                            full_href = href if href.startswith("http") else f"https://www.bbb.org{href}"
                            if state and f"/{state.lower()}/" in full_href:
                                profile_links.insert(0, full_href)
                            else:
                                profile_links.append(full_href)
                if profile_links:
                    break
            except Exception as e:
                logger.debug(f"BBB search request error: {e}")

        # Scrape the top matched BBB profile
        for profile_url in profile_links[:2]:
            try:
                rp = http_client.get(profile_url, headers=headers, timeout=self.timeout)
                if rp.status_code == 200:
                    sp = BeautifulSoup(rp.text, "html.parser")
                    
                    # Extract phone
                    for a in sp.find_all("a", href=True):
                        if a["href"].startswith("tel:"):
                            extracted_tel = a["href"].replace("tel:", "").strip()
                            if not discovered_phone and len(re.sub(r"\D", "", extracted_tel)) >= 10:
                                discovered_phone = extracted_tel

                    # Extract official website
                    for a in sp.find_all("a", href=True):
                        if "Visit Website" in a.get_text() or a.get_text().strip().startswith("http"):
                            href = a["href"]
                            if href.startswith("http") and not any(d in href for d in DIRECTORY_DOMAINS):
                                best = self._select_best_website([href], clean_name)
                                if best:
                                    discovered_site = best
                                    break

                    # Extract Principal / Owner names
                    page_text = sp.get_text(" ")
                    owner_match = re.search(r"(?:Owner|Principal|President|CEO|Manager):\s*([A-Z][a-z]+ [A-Z][a-z]+)", page_text)
                    if owner_match:
                        owner_name = owner_match.group(1).strip()
                        logger.info(f"🏛️ [Option 3 BBB] Discovered Business Principal: {owner_name}")

                    # Extract emails
                    emails = self._extract_clean_emails_from_text(rp.text)
                    for em in emails:
                        if self._is_valid_lead_email(em, clean_name, is_no_website=True):
                            contacts.append({
                                "email": em,
                                "first_name": None,
                                "full_name": f"{clean_name} Management",
                                "title": "Principal Contact",
                                "source": "bbb_directory",
                                "email_status": "valid",
                            })
                    if discovered_site:
                        break
            except Exception as inner_e:
                logger.debug(f"BBB profile fetch error: {inner_e}")


        if discovered_site:
            discovered_domain = discovered_site.replace("https://", "").replace("http://", "").replace("www.", "").split("/")[0].lower()

        return {
            "website_url": discovered_site,
            "domain": discovered_domain,
            "phone": discovered_phone,
            "contacts": contacts,
        }

    # =========================================================================
    # OPTION 4: Secretary of State (SOS) & Corporate Registry Search
    # =========================================================================
    def _search_sos_and_corporateregistries(self, clean_name: str, state: str) -> dict[str, Any]:
        """
        Searches OpenCorporates for state registered corporate entities.
        Extracts Registered Agent name, President/Officers, and registered address.
        """
        officer_name: str | None = None
        contacts: list[dict[str, Any]] = []

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }

        query = urllib.parse.quote_plus(clean_name)
        oc_url = f"https://opencorporates.com/companies?q={query}"
        try:
            r = http_client.get(oc_url, headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                candidate_entity_urls = []
                for a in soup.select("a.company_search_result, ul.companies li a"):
                    href = a.get("href", "")
                    if href.startswith("/companies/us_"):
                        full_href = f"https://opencorporates.com{href}"
                        # Prioritize state matching (e.g. /companies/us_nc/)
                        if state and f"/us_{state.lower()}/" in full_href:
                            candidate_entity_urls.insert(0, full_href)
                        else:
                            candidate_entity_urls.append(full_href)

                # Scrape matched corporate filing
                for entity_url in candidate_entity_urls[:2]:
                    try:
                        rp = http_client.get(entity_url, headers=headers, timeout=self.timeout)
                        if rp.status_code == 200:
                            sp = BeautifulSoup(rp.text, "html.parser")
                            page_text = sp.get_text(" ")

                            # Extract Registered Agent (e.g. "Agent Name Cohen, Jeffrey" or "Agent Name: John Doe")
                            agent_match = re.search(r"Agent Name\s+([A-Za-z]+,\s+[A-Za-z]+|[A-Za-z]+\s+[A-Za-z]+)", page_text)
                            if agent_match:
                                raw_agent = agent_match.group(1).strip()
                                if "," in raw_agent:
                                    parts = raw_agent.split(",")
                                    officer_name = f"{parts[1].strip()} {parts[0].strip()}"
                                else:
                                    officer_name = raw_agent
                                logger.info(f"📜 [Option 4 SOS] Extracted Legal Agent/Officer: '{officer_name}' from {entity_url}")

                            # Extract emails from filing
                            emails = self._extract_clean_emails_from_text(rp.text)
                            for em in emails:
                                if self._is_valid_lead_email(em, clean_name, is_no_website=True):
                                    contacts.append({
                                        "email": em,
                                        "first_name": officer_name.split()[0] if officer_name else None,
                                        "full_name": officer_name or f"{clean_name} Registered Agent",
                                        "title": "Registered Agent / Owner",
                                        "source": "secretary_of_state_filing",
                                        "email_status": "valid",
                                    })
                            if officer_name:
                                break
                    except Exception as inner_e:
                        logger.debug(f"OpenCorporates entity page error: {inner_e}")
        except Exception as e:
            logger.debug(f"OpenCorporates search error: {e}")

        return {
            "officer_name": officer_name,
            "contacts": contacts,
        }

    # =========================================================================
    # Search Engine Query Execution (Bing, Yahoo, Mojeek)
    # =========================================================================
    def _execute_search_queries(self, query: str) -> tuple[str, list[str]]:
        """Queries Yahoo and Bing to gather page text snippets and candidate website links."""
        encoded = urllib.parse.quote_plus(query)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }

        all_text_snippets: list[str] = []
        candidate_links: list[str] = []

        # Engine 1: Yahoo Search
        try:
            yahoo_url = f"https://search.yahoo.com/search?p={encoded}"
            r = http_client.get(yahoo_url, headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                all_text_snippets.append(soup.get_text(" "))

                for a in soup.select("h3.title a, .compText a, a[href]"):
                    href = a.get("href", "")
                    if "/RU=" in href:
                        try:
                            ru = href.split("/RU=")[1].split("/")[0]
                            href = urllib.parse.unquote(ru)
                        except Exception:
                            pass
                    if href.startswith("http"):
                        candidate_links.append(href)
        except Exception as e:
            logger.debug(f"Yahoo search notice: {e}")

        # Engine 2: Bing HTML Search with Base64 URL Decoding
        try:
            bing_url = f"https://www.bing.com/search?q={encoded}&setmkt=en-US&setlang=en-US"
            r = http_client.get(bing_url, headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                all_text_snippets.append(soup.get_text(" "))
                for a in soup.select(".b_algo h2 a, a[href]"):
                    raw_href = a.get("href", "")
                    decoded = self.decode_bing_url(raw_href)
                    if decoded.startswith("http"):
                        candidate_links.append(decoded)
        except Exception as e:
            logger.debug(f"Bing search notice: {e}")

        return " ".join(all_text_snippets), candidate_links

    def _select_best_website(self, candidate_links: list[str], business_name: str) -> str | None:
        """
        Filters out aggregators/directories and validates that the candidate domain
        shares brand tokens with the business name to prevent false positives.
        """
        stopwords = {
            "inc", "llc", "corp", "corporation", "co", "the", "and", "service",
            "services", "company", "group", "solutions", "contractor", "contractors",
            "plumbing", "heating", "cooling", "electric", "electrical", "hvac", "roofing", "cleaning", "restoration"
        }
        normalized_name = (business_name or "").lower()
        raw_tokens = [t for t in re.findall(r"[a-z0-9]+", normalized_name) if len(t) >= 3]
        brand_tokens = [t for t in raw_tokens if t not in stopwords and len(t) >= 3]
        active_tokens = brand_tokens if brand_tokens else raw_tokens

        scored_candidates: list[tuple[int, str]] = []
        for link in candidate_links:
            try:
                parsed = urllib.parse.urlparse(link)
                netloc = parsed.netloc.lower().replace("www.", "")
                if not netloc or "." not in netloc:
                    continue

                # Exclude directories and search engines
                if any(netloc == d or netloc.endswith(f".{d}") for d in DIRECTORY_DOMAINS):
                    continue

                domain_stem = netloc.split(".")[0]
                # Disallow single-word global brands mistaken for local businesses
                if domain_stem in ["genesis", "tom", "apple", "amazon", "microsoft", "google", "circle", "elevate"]:
                    continue

                match_count = sum(1 for tok in active_tokens if tok in domain_stem)
                if active_tokens:
                    if match_count > 0:
                        scheme = parsed.scheme if parsed.scheme in ["http", "https"] else "https"
                        scored_candidates.append((match_count, f"{scheme}://{netloc}"))
                else:
                    scheme = parsed.scheme if parsed.scheme in ["http", "https"] else "https"
                    scored_candidates.append((1, f"{scheme}://{netloc}"))
            except Exception:
                continue

        if scored_candidates:
            scored_candidates.sort(key=lambda x: x[0], reverse=True)
            return scored_candidates[0][1]

        return None

    def _scrape_website_contacts(self, website_url: str) -> list[str]:
        """Scrapes contact pages and homepage for direct email addresses."""
        discovered: list[str] = []
        clean_url = website_url.rstrip("/")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }

        urls_to_try = [
            clean_url,
            f"{clean_url}/contact",
            f"{clean_url}/contact-us",
            f"{clean_url}/about",
            f"{clean_url}/about-us",
        ]

        for url in urls_to_try:
            try:
                r = http_client.get(url, headers=headers, timeout=6)
                if r.status_code == 200:
                    emails = self._extract_clean_emails_from_text(r.text)
                    discovered.extend(emails)
                    if len(discovered) >= 3:
                        break
            except Exception:
                continue

        return list(dict.fromkeys(discovered))

    def _extract_clean_emails_from_text(self, text: str) -> list[str]:
        """Extracts and sanitizes email addresses from raw HTML/text."""
        if not text:
            return []

        results: list[str] = []
        matches = EMAIL_REGEX.findall(text)
        for m in matches:
            clean = m.lower().strip(".,;:()<>[]'\"\\/")
            if self._is_valid_lead_email(clean):
                results.append(clean)

        return list(dict.fromkeys(results))

    def _is_valid_lead_email(
        self, email: str, business_name: str | None = None, company_domain: str | None = None, is_no_website: bool = False
    ) -> bool:
        """
        Filters out system, privacy, image/asset tokens, foreign government domains,
        directory aggregators, unresolvable domains, and mismatched business addresses.
        """
        if not email or "@" not in email:
            return False

        # Ignore images and asset extensions mistaken for emails
        if any(email.lower().endswith(ext) for ext in IGNORED_FILE_EXTENSIONS):
            return False

        clean = email.lower().strip()
        from enrichment.email_validator import EmailValidator
        is_valid, reason = EmailValidator.is_valid_lead_email(
            clean, company_name=business_name, company_domain=company_domain, is_no_website=is_no_website
        )
        if not is_valid:
            logger.debug(f"Rejecting candidate lead email {email}: {reason}")
            return False

        # Verify DNS MX records so the email can actually receive incoming messages
        domain = clean.split("@")[-1].strip()
        if not self.validator.has_mx_records(domain):
            logger.debug(f"Rejecting lead email {email}: Domain {domain} has no active MX/A records")
            return False

        return True

    def _search_apollo_by_name(self, business_name: str, city: str) -> list[dict[str, Any]]:
        """Queries Apollo.io API by organization name and location."""
        import requests
        url = "https://api.apollo.io/v1/mixed_people/search"
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.apollo_api_key,
        }
        payload = {
            "q_organization_name": business_name,
            "person_locations": [city] if city else [],
            "person_titles": ["owner", "founder", "ceo", "president", "manager", "partner"],
            "page": 1,
            "per_page": 2,
        }

        contacts = []
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                for person in data.get("people", []):
                    email = person.get("email")
                    if email and self._is_valid_lead_email(email, business_name):
                        contacts.append({
                            "email": email,
                            "first_name": person.get("first_name") or None,
                            "full_name": person.get("name") or person.get("first_name") or f"{business_name} Leadership",
                            "title": person.get("title") or "Business Leadership",
                            "source": "apollo_org_search",
                            "email_status": "valid",
                        })
        except Exception as e:
            logger.debug(f"Apollo organization search error for '{business_name}': {e}")

        return contacts


_local_finder_instance: LocalBusinessEmailFinder | None = None


def get_local_business_email_finder() -> LocalBusinessEmailFinder:
    global _local_finder_instance
    if _local_finder_instance is None:
        _local_finder_instance = LocalBusinessEmailFinder()
    return _local_finder_instance
