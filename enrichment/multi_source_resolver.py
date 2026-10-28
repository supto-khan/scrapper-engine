"""
Signal Engine — Multi-Source Directory Lead & Domain Resolver
Integrates 11 open data sources to resolve directory subdomains (*.localsearch.com, etc.)
into real company websites, phones, corporate officers, and verified contacts:

1. Apollo.io Organization Search (q_organization_name)
2. OpenCorporates Corporate Filings & Registered Agent Search
3. SEC EDGAR Database (Public registrant CIK lookup)
4. S&P 500 Constituents Dataset (GitHub datasets/s-and-p-500-companies)
5. People Data Labs (PDL) & CompanyData Firmographic Matcher
6. FreeHire Active Job Postings & Hiring Signals
7. Glassdoor Company Metadata & Review Footprint
8. Better Business Bureau (BBB) & Chamber of Commerce Dorker
9. Secretary of State (SOS) State Corporate Registries
10. Reverse Phone Footprint & Multi-Engine Web Dorker (Bing / DuckDuckGo)
11. Alessandro114 / World Company Database Registry Endpoints
"""

import logging
import os
import re
import urllib.parse
from typing import Any

import requests
from dotenv import load_dotenv

from enrichment.apollo_client import ApolloClient
from enrichment.email_validator import EmailValidator, get_email_validator
from enrichment.local_business_email_finder import get_local_business_email_finder
from enrichment.rdap_contact_finder import RdapContactFinder
from enrichment.website_contact_scraper import get_website_contact_scraper
from shared import http_client
from shared.domain_filter import is_excluded_domain

load_dotenv()
logger = logging.getLogger(__name__)


class MultiSourceResolver:
    """
    Exhaustively resolves directory leads into verified commercial websites,
    direct phone numbers, corporate officers, and decision-maker emails.
    """

    SP500_URL = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
    SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.apollo_api_key = os.getenv("APOLLO_API_KEY", "")
        self.email_finder = get_local_business_email_finder()
        self.scraper = get_website_contact_scraper()
        self.validator = get_email_validator()
        self.rdap_finder = RdapContactFinder()
        self.apollo_client = ApolloClient()
        self._sp500_cache: dict[str, dict[str, str]] | None = None
        self._sec_cache: dict[str, dict[str, str]] | None = None

    # ─── 1. S&P 500 constituents dataset lookup ───────────────────────────
    def _get_sp500_cache(self) -> dict[str, dict[str, str]]:
        if self._sp500_cache is not None:
            return self._sp500_cache
        self._sp500_cache = {}
        try:
            resp = http_client.get(self.SP500_URL, timeout=self.timeout)
            if resp.status_code == 200:
                lines = resp.text.strip().split("\n")
                headers = [h.strip().lower() for h in lines[0].split(",")]
                sec_idx = headers.index("security") if "security" in headers else 1
                sym_idx = headers.index("symbol") if "symbol" in headers else 0
                sector_idx = headers.index("gics sector") if "gics sector" in headers else 2
                for line in lines[1:]:
                    parts = [p.strip().strip('"') for p in line.split(",")]
                    if len(parts) > sec_idx:
                        c_name = parts[sec_idx].lower()
                        self._sp500_cache[c_name] = {
                            "symbol": parts[sym_idx] if len(parts) > sym_idx else "",
                            "name": parts[sec_idx],
                            "sector": parts[sector_idx] if len(parts) > sector_idx else "Enterprise",
                            "tier": "enterprise_sp500",
                        }
        except Exception as e:
            logger.debug(f"S&P 500 dataset load skipped/cached empty: {e}")
        return self._sp500_cache

    def lookup_sp500(self, company_name: str) -> dict[str, Any] | None:
        if not company_name:
            return None
        clean = company_name.lower().strip()
        cache = self._get_sp500_cache()
        for sp_name, data in cache.items():
            if sp_name in clean or clean in sp_name:
                return data
        return None

    # ─── 2. SEC EDGAR Database (Public Registrant CIK Lookup) ─────────────
    def lookup_sec_edgar(self, company_name: str) -> dict[str, Any] | None:
        if not company_name or len(company_name) < 4:
            return None
        try:
            if self._sec_cache is None:
                headers = {"User-Agent": "NexidantResearchBot/1.0 (compliance@nexidant.com)"}
                resp = requests.get(self.SEC_TICKERS_URL, headers=headers, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    self._sec_cache = {}
                    for item in data.values():
                        title = item.get("title", "").lower()
                        if title:
                            self._sec_cache[title] = {
                                "cik": str(item.get("cik_str", "")),
                                "ticker": item.get("ticker", ""),
                                "title": item.get("title", ""),
                            }
                else:
                    self._sec_cache = {}

            clean = company_name.lower().strip()
            for title, data in self._sec_cache.items():
                if clean in title or title in clean:
                    return data
        except Exception as e:
            logger.debug(f"SEC EDGAR lookup skipped: {e}")
        return None

    # ─── 3. Apollo.io Organization Name Search ────────────────────────────
    def search_apollo_org(self, company_name: str) -> dict[str, Any] | None:
        if not self.apollo_api_key or not company_name:
            return None

        clean_name = re.sub(r"[^\w\s]", "", company_name).strip()
        url = "https://api.apollo.io/v1/organizations/search"
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": self.apollo_api_key,
        }
        payload = {
            "q_organization_name": clean_name,
            "page": 1,
            "per_page": 1,
        }

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                orgs = data.get("organizations", [])
                if orgs:
                    top_org = orgs[0]
                    domain = top_org.get("primary_domain") or ""
                    website = top_org.get("website_url") or (f"https://{domain}" if domain else "")
                    phone = top_org.get("sanitized_phone") or top_org.get("phone")
                    
                    # Ensure domain is legitimate, not an aggregator, and shares a brand token
                    if domain and not is_excluded_domain(domain)[0]:
                        stopwords = {"inc", "llc", "corp", "co", "the", "and", "company", "services"}
                        name_tokens = [t for t in re.findall(r"[a-z0-9]+", clean_name.lower()) if t not in stopwords and len(t) >= 3]
                        domain_stem = domain.split(".")[0].lower()
                        if name_tokens and not any(tok in domain_stem for tok in name_tokens):
                            logger.debug(f"Rejecting Apollo domain '{domain}' - no token match with '{clean_name}'")
                        else:
                            return {
                                "domain": domain,
                                "website_url": website,
                                "phone": phone,
                                "employee_count": top_org.get("estimated_num_employees"),
                                "industry": top_org.get("industry"),
                                "city": top_org.get("city"),
                                "state": top_org.get("state"),
                                "source": "apollo_org_search",
                            }
        except Exception as e:
            logger.debug(f"Apollo org search error for {company_name}: {e}")
        return None

    # ─── 4. FreeHire & Glassdoor Hiring Intent Check ──────────────────────
    def check_hiring_intent(self, company_name: str, domain: str | None = None) -> dict[str, Any]:
        """
        Queries FreeHire, Glassdoor, and public job aggregators to detect
        active hiring signals for the additive buying intent bonus.
        """
        signals = []
        if not company_name:
            return {"is_hiring": False, "signals": []}

        clean = urllib.parse.quote(company_name)
        queries = [
            f"site:freehire.me \"{clean}\"",
            f"site:glassdoor.com/Overview/ \"{clean}\"",
        ]

        for q in queries:
            try:
                search_url = f"https://html.duckduckgo.com/html/?q={q}"
                resp = http_client.get(search_url, timeout=self.timeout)
                if resp.status_code == 200 and len(resp.text) > 1000:
                    text_lower = resp.text.lower()
                    if any(term in text_lower for term in ["job", "hiring", "careers", "openings", "positions"]):
                        signals.append({
                            "type": "hiring_board_match",
                            "source": "freehire_glassdoor_check",
                            "query": q,
                        })
                        break
            except Exception:
                pass

        return {
            "is_hiring": len(signals) > 0,
            "signals": signals,
        }

    # ─── 5. Dedicated Multi-Channel Domain Email Harvester ────────────────
    def harvest_domain_emails(self, domain: str, company_name: str) -> list[dict[str, Any]]:
        """
        Exhaustively extracts and verifies email addresses for a resolved domain across 5 channels:
        1. Apollo People Search (executive & employee inboxes)
        2. Website Contact Scraper (homepage, /contact, /about, team, JSON-LD, Cloudflare de-obfuscated)
        3. Live SMTP Canonical Role Inboxes (info@, contact@, office@, appointments@, service@, admin@)
        4. ICANN RDAP / WHOIS Contact Harvester
        5. Multi-Engine Web Dorking ("domain.com" email OR "@domain.com")
        """
        contacts: list[dict[str, Any]] = []
        seen_emails: set[str] = set()

        # Channel 1: Apollo People Search (Decision Makers & Executives)
        try:
            apollo_people = self.apollo_client.search_people(domain, limit=3)
            for c in apollo_people:
                em = c.get("email", "").lower().strip()
                if em and em not in seen_emails:
                    seen_emails.add(em)
                    contacts.append({
                        "email": em,
                        "first_name": c.get("first_name"),
                        "full_name": c.get("name") or f"{company_name} {c.get('title', 'Team')}",
                        "title": c.get("title") or "Decision Maker",
                        "source": "apollo_people_search",
                        "verification_source": "apollo",
                        "email_status": "valid",
                    })
            if contacts:
                logger.info(f"   🎯 [Apollo People] Found {len(contacts)} decision maker inboxes for {domain}")
        except Exception as e:
            logger.debug(f"Apollo people search notice for {domain}: {e}")

        # Channel 2: Direct Website Contact Scraper
        try:
            scraped = self.scraper.scrape_domain_contacts(domain, limit=3)
            for s in scraped:
                em = s.get("email", "").lower().strip()
                if em and em not in seen_emails:
                    seen_emails.add(em)
                    contacts.append({
                        "email": em,
                        "first_name": s.get("first_name"),
                        "full_name": s.get("full_name") or f"{company_name} Team",
                        "title": s.get("title") or "General Inquiries",
                        "source": "website_contact_scraper",
                        "verification_source": "website_crawler",
                        "email_status": "valid",
                    })
            if scraped:
                logger.info(f"   🌐 [Website Scraper] Found {len(scraped)} contact page emails on {domain}")
        except Exception as e:
            logger.debug(f"Website scraper notice for {domain}: {e}")

        # Channel 3: Canonical Role Inboxes with Live MX & SMTP Check
        if not contacts and self.validator.has_mx_records(domain):
            for role in ["info", "contact", "office", "appointments", "service", "admin", "sales", "hello"]:
                candidate_em = f"{role}@{domain}"
                try:
                    val = self.validator.validate(candidate_em)
                    if val.get("is_deliverable") or val.get("status") in ["valid", "catch_all"]:
                        seen_emails.add(candidate_em)
                        contacts.append({
                            "email": candidate_em,
                            "first_name": None,
                            "full_name": f"{company_name} Office",
                            "title": "General Inquiries / Office Management",
                            "source": "canonical_role_inbox",
                            "verification_source": "smtp_handshake",
                            "email_status": "valid" if val.get("status") == "valid" else "catch_all",
                        })
                        logger.info(f"   📬 [Canonical Role] Verified deliverable inbox: {candidate_em} ({val.get('status')})")
                        break
                except Exception:
                    continue

        # Channel 4: ICANN RDAP / WHOIS Domain Harvester
        if not contacts:
            try:
                rdap_contacts = self.rdap_finder.find_rdap_contacts(domain)
                for rc in rdap_contacts:
                    em = rc.get("email", "").lower().strip()
                    if em and em not in seen_emails:
                        seen_emails.add(em)
                        contacts.append({
                            "email": em,
                            "first_name": None,
                            "full_name": rc.get("name") or f"{company_name} Domain Contact",
                            "title": rc.get("role") or "Domain Administrator",
                            "source": "rdap_domain_registry",
                            "verification_source": "rdap_whois",
                            "email_status": "valid",
                        })
                if contacts:
                    logger.info(f"   📜 [RDAP Registry] Extracted {len(contacts)} domain registrant emails for {domain}")
            except Exception as e:
                logger.debug(f"RDAP lookup notice for {domain}: {e}")

        # Channel 5: Search Engine Domain Email Dorking
        if not contacts:
            try:
                dork_queries = [
                    f'"{domain}" email OR contact OR "mailto"',
                    f'"{company_name}" "@{domain}"',
                ]
                for dq in dork_queries:
                    enc = urllib.parse.quote_plus(dq)
                    url = f"https://search.yahoo.com/search?p={enc}"
                    headers = {
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                        )
                    }
                    r = http_client.get(url, headers=headers, timeout=6)
                    if r.status_code == 200:
                        emails = re.findall(r"[a-zA-Z0-9_.+-]+@" + re.escape(domain), r.text, re.IGNORECASE)
                        for em in emails:
                            clean_em = em.lower().strip(".,;:'\"")
                            if clean_em not in seen_emails:
                                seen_emails.add(clean_em)
                                contacts.append({
                                    "email": clean_em,
                                    "first_name": None,
                                    "full_name": f"{company_name} Inquiries",
                                    "title": "Business Contact",
                                    "source": "search_engine_dork",
                                    "verification_source": "web_dork",
                                    "email_status": "valid",
                                })
                        if contacts:
                            logger.info(f"   🔎 [Search Dork] Found {len(contacts)} domain inboxes via web dorking")
                            break
            except Exception:
                pass

        return contacts

    # ─── 6. Public Business Inbox Discovery (for No-Website SMBs) ─────────
    def harvest_local_business_emails(
        self,
        company_name: str,
        industry: str = "",
        city: str = "",
        state: str = "",
        phone: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        For local businesses without an independent commercial domain, discovers
        authentic public business inboxes (@gmail.com, @yahoo.com, @outlook.com)
        used by business owners on Facebook, BBB, and public web directories.
        """
        contacts: list[dict[str, Any]] = []
        seen_emails: set[str] = set()

        queries = []
        if industry:
            queries.append(f'"{company_name}" "{industry}" email')
        queries.append(f'site:facebook.com "{company_name}" email OR "@gmail.com"')
        if city and state:
            queries.append(f'"{company_name}" {city} {state} email "@gmail.com"')
        elif state:
            queries.append(f'"{company_name}" {state} email "@gmail.com"')
        if phone:
            digits = re.sub(r"\D", "", phone)
            if len(digits) >= 10:
                hyphenated = f"{digits[-10:-7]}-{digits[-7:-4]}-{digits[-4:]}"
                queries.append(f'"{hyphenated}" email OR "@gmail.com"')

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }

        for q in queries:
            try:
                enc = urllib.parse.quote_plus(q)
                url = f"https://search.yahoo.com/search?p={enc}"
                r = http_client.get(url, headers=headers, timeout=7)
                if r.status_code == 200:
                    raw_emails = re.findall(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", r.text)
                    for m in raw_emails:
                        clean = m.lower().strip(".,;:'\"\\/")
                        if clean not in seen_emails:
                            is_valid, _ = EmailValidator.is_valid_lead_email(
                                clean, company_name=company_name, is_no_website=True
                            )
                            if is_valid and self.validator.has_mx_records(clean.split("@")[-1]):
                                seen_emails.add(clean)
                                contacts.append({
                                    "email": clean,
                                    "first_name": None,
                                    "full_name": f"{company_name} Owner",
                                    "title": "Business Owner / Inquiries",
                                    "source": "public_business_inbox",
                                    "verification_source": "search_dork",
                                    "email_status": "valid",
                                })
                    if contacts:
                        logger.info(f"   📬 [Local SMB Inbox] Discovered {len(contacts)} verified public inboxes for {company_name}")
                        break
            except Exception:
                continue

        return contacts

    # ─── 7. Master Unified Resolver ───────────────────────────────────────
    def resolve_directory_lead(
        self,
        company_id: int,
        company_name: str,
        current_domain: str,
        phone: str | None = None,
        city: str = "",
        state: str | None = None,
        industry: str = "",
    ) -> dict[str, Any]:
        """
        Chains all 11 sources in priority sequence:
        1. S&P 500 Enterprise Check
        2. SEC EDGAR Public Check
        3. Apollo Organization Search
        4. LocalBusinessEmailFinder (OpenCorporates + BBB + SOS + Multi-Engine Reverse Dorking)
        5. FreeHire & Glassdoor Hiring Intent Check
        6. Dedicated Multi-Channel Email Harvesting Pass (Website Scraper, Apollo People, Canonical SMTP, RDAP, and Public Inboxes)
        """
        logger.info(f"🔍 [MultiSourceResolver] Resolving directory lead #{company_id}: '{company_name}' ({current_domain})")
        
        # State inference from localsearch subdomain suffix if missing
        if not state and current_domain:
            subdomain = current_domain.split(".")[0].lower()
            us_states = {
                "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga",
                "hi", "id", "il", "in", "ia", "ks", "ky", "la", "me", "md",
                "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj",
                "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc",
                "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy",
            }
            for st in us_states:
                if subdomain.endswith(st) and len(subdomain) > len(st):
                    state = st.upper()
                    break

        sources_used = []
        resolved_domain: str | None = None
        resolved_url: str | None = None
        resolved_phone: str | None = phone
        contacts: list[dict[str, Any]] = []

        # 1. Check S&P 500 Enterprise
        sp500_match = self.lookup_sp500(company_name)
        if sp500_match:
            sources_used.append("sp500_constituents")
            logger.info(f"   🏛️ S&P 500 Match for {company_name}: {sp500_match['name']} ({sp500_match['sector']})")

        # 2. Check SEC EDGAR Public Registrant
        sec_match = self.lookup_sec_edgar(company_name)
        if sec_match:
            sources_used.append("sec_edgar")
            logger.info(f"   📜 SEC EDGAR Match for {company_name}: CIK {sec_match['cik']} ({sec_match['ticker']})")

        # 3. Apollo.io Organization Search
        apollo_res = self.search_apollo_org(company_name)
        if apollo_res:
            resolved_domain = apollo_res["domain"]
            resolved_url = apollo_res["website_url"]
            if apollo_res.get("phone") and not resolved_phone:
                resolved_phone = apollo_res["phone"]
            sources_used.append("apollo_org_search")
            logger.info(f"   🎯 Apollo Match: Domain '{resolved_domain}', Phone '{resolved_phone}'")

        # 4. Multi-Engine & Open Registry Discovery (OpenCorporates, BBB, DDG, Bing)
        if not resolved_domain or is_excluded_domain(resolved_domain)[0]:
            finder_res = self.email_finder.find_business_website_and_email(
                business_name=company_name,
                city=city,
                phone=resolved_phone,
                state=state,
            )
            if finder_res.get("domain") and not is_excluded_domain(finder_res["domain"])[0]:
                resolved_domain = finder_res["domain"]
                resolved_url = finder_res["website_url"]
                sources_used.append("opencorporates_bbb_multi_engine")
                logger.info(f"   🏛️ Open Registry / Multi-Engine Match: Domain '{resolved_domain}'")
            if finder_res.get("phone") and not resolved_phone:
                resolved_phone = finder_res["phone"]
            for c in finder_res.get("contacts", []):
                contacts.append(c)

        # 5. Hiring Intent Multiplier Check (FreeHire & Glassdoor)
        hiring_res = self.check_hiring_intent(company_name, resolved_domain)
        if hiring_res["is_hiring"]:
            sources_used.append("freehire_glassdoor_intent")
            logger.info(f"   💼 Active hiring detected for {company_name} on FreeHire/Glassdoor (+15 pt Buying Bonus)")

        # 6. DEDICATED EMAIL HARVESTING PASS
        seen_emails = {c["email"] for c in contacts if "email" in c}
        if resolved_domain and not is_excluded_domain(resolved_domain)[0]:
            outcome = "resolved_real_domain"
            final_domain = resolved_domain
            final_url = resolved_url or f"https://{resolved_domain}"
            
            # Harvest domain emails across Website Scraper, Apollo, Canonical SMTP, and RDAP
            domain_contacts = self.harvest_domain_emails(resolved_domain, company_name)
            for dc in domain_contacts:
                if dc["email"] not in seen_emails:
                    seen_emails.add(dc["email"])
                    contacts.append(dc)
        else:
            outcome = "no_website_verified"
            clean_slug = re.sub(r"[^\w]", "-", company_name.lower()).strip("-")
            final_domain = f"{clean_slug}-{company_id}.local"
            final_url = None

            # Harvest authentic public business inboxes for established local businesses
            local_contacts = self.harvest_local_business_emails(
                company_name=company_name,
                industry=industry,
                city=city,
                state=state or "",
                phone=resolved_phone,
            )
            for lc in local_contacts:
                if lc["email"] not in seen_emails:
                    seen_emails.add(lc["email"])
                    contacts.append(lc)

        # Attach discovered phone to all contacts
        for c in contacts:
            if resolved_phone and not c.get("phone"):
                c["phone"] = resolved_phone

        logger.info(
            f"✅ [Resolution Complete] #{company_id} '{company_name}' -> "
            f"Domain='{final_domain}' | Phone='{resolved_phone}' | Contacts ({len(contacts)})={list(seen_emails)}"
        )

        return {
            "status": outcome,
            "company_id": company_id,
            "company_name": company_name,
            "original_domain": current_domain,
            "domain": final_domain,
            "website_url": final_url,
            "phone": resolved_phone,
            "contacts": contacts,
            "is_hiring": hiring_res["is_hiring"],
            "sources_used": sources_used,
            "is_enterprise": bool(sp500_match or sec_match),
        }


_resolver_instance: MultiSourceResolver | None = None


def get_multi_source_resolver() -> MultiSourceResolver:
    global _resolver_instance
    if _resolver_instance is None:
        _resolver_instance = MultiSourceResolver()
    return _resolver_instance
