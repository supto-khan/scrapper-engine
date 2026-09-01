import logging
from typing import Any

from enrichment.apollo_client import ApolloClient, get_apollo_client
from enrichment.email_permutator import EmailPermutator, get_email_permutator
from enrichment.email_validator import EmailValidator, get_email_validator
from enrichment.hunter_client import HunterClient, get_hunter_client
from enrichment.local_business_email_finder import (
    LocalBusinessEmailFinder,
    get_local_business_email_finder,
)
from enrichment.rdap_contact_finder import RdapContactFinder, get_rdap_contact_finder
from enrichment.search_executive_finder import SearchExecutiveFinder, get_search_executive_finder
from enrichment.website_contact_scraper import WebsiteContactScraper, get_website_contact_scraper
from shared.mysql_client import get_mysql_client

logger = logging.getLogger(__name__)


class EnrichmentWorker:
    """
    Decoupled Multi-Layer Enrichment Worker for achieving 100% Decision Maker Coverage:
    - Tier 1: Apollo.io People API (if daily quota available)
    - Tier 2: Hunter.io API (if configured)
    - Tier 3: Direct Website Contact Scraper (/contact, /about, /team, security.txt, obfuscated mailto)
    - Tier 4: Search Engine Executive Discovery + Email Permutator (Finds real CEO/Founders)
    - Tier 5: ICANN RDAP / WHOIS Registry Contact Harvester (Admin & Tech contacts)
    - Tier 6: Multi-Engine Search Discovery & Official Website Resolution (Yahoo, Bing, Google)
    """

    def __init__(
        self,
        hunter_client: HunterClient | None = None,
        apollo_client: ApolloClient | None = None,
        email_validator: EmailValidator | None = None,
        website_scraper: WebsiteContactScraper | None = None,
        search_finder: SearchExecutiveFinder | None = None,
        rdap_finder: RdapContactFinder | None = None,
        permutator: EmailPermutator | None = None,
        local_finder: LocalBusinessEmailFinder | None = None,
    ):
        self.apollo = apollo_client or get_apollo_client()
        self.validator = email_validator or get_email_validator()
        self.website_scraper = website_scraper or get_website_contact_scraper()
        self.search_finder = search_finder or get_search_executive_finder()
        self.rdap_finder = rdap_finder or get_rdap_contact_finder()
        self.permutator = permutator or get_email_permutator()
        self.local_finder = local_finder or get_local_business_email_finder()
        self.mysql = get_mysql_client()

    def enrich_company(
        self, company_id: int, domain: str, company_name: str | None = None
    ) -> list[dict[str, Any]]:
        """
        Enriches a single company through 6 redundant fallback tiers.
        """
        clean_dom = domain.lower().replace("http://", "").replace("https://", "").strip().strip("/")
        canonical_dom = self.website_scraper.resolve_canonical_domain(clean_dom) or clean_dom
        logger.info(f"Enriching company {canonical_dom} (ID: {company_id})...")
        discovered_contacts: list[dict[str, Any]] = []

        # Tier 1: Apollo.io Search
        apollo_contacts = self.apollo.search_people(canonical_dom, limit=5)
        if apollo_contacts:
            discovered_contacts.extend(apollo_contacts)
            logger.info(f"[Tier 1] Found {len(apollo_contacts)} contacts via Apollo for {canonical_dom}")

        # Tier 2: Direct Website Scraping (/contact, /about, /team, security.txt, humans.txt)
        if not discovered_contacts:
            scraped_contacts = self.website_scraper.scrape_domain_contacts(canonical_dom, limit=3)
            if scraped_contacts:
                discovered_contacts.extend(scraped_contacts)
                logger.info(f"[Tier 2] Found {len(scraped_contacts)} contacts via Direct Website Scraping for {canonical_dom}")

        # Tier 3: Search Engine Executive Discovery + Email Permutator
        if not discovered_contacts:
            executives = self.search_finder.find_executives(canonical_dom, company_name)
            if executives:
                perm_contacts = self.permutator.synthesize_verified_contacts(executives, canonical_dom)
                if perm_contacts:
                    discovered_contacts.extend(perm_contacts)
                    logger.info(f"[Tier 3] Synthesized {len(perm_contacts)} executive emails via Search + Permutator for {canonical_dom}")

        # Tier 4: ICANN RDAP / WHOIS Registry Contacts
        if not discovered_contacts:
            rdap_contacts = self.rdap_finder.find_rdap_contacts(canonical_dom)
            if rdap_contacts:
                discovered_contacts.extend(rdap_contacts)
                logger.info(f"[Tier 4] Found {len(rdap_contacts)} RDAP registry contacts for {canonical_dom}")

        # Tier 5: Multi-Role Canonical Inboxes (hello@, contact@, info@, sales@) with MX Verification
        if not discovered_contacts and not canonical_dom.endswith(".local"):
            if self.validator.has_mx_records(canonical_dom):
                dom_label = canonical_dom.split(".")[0].capitalize()
                for role_prefix in ["hello", "contact", "info", "sales"]:
                    synth_email = f"{role_prefix}@{canonical_dom}"
                    val = self.validator.validate(synth_email)
                    if val.get("status") in ["valid", "catch_all"]:
                        synth_contact = {
                            "full_name": f"{dom_label} Leadership",
                            "first_name": dom_label,
                            "last_name": "Leadership",
                            "title": f"Executive & {role_prefix.capitalize()} Inquiries",
                            "role_category": "general",
                            "email": synth_email,
                            "email_score": 75.0,
                            "verification_source": "dns_mx_verified",
                            "linkedin_url": None,
                            "source": "canonical_synthesizer",
                            "raw_contact_data": {
                                "type": "canonical_mx_fallback",
                                "domain": canonical_dom,
                                "inbox": role_prefix,
                            },
                        }
                        discovered_contacts.append(synth_contact)
                        logger.info(f"[Tier 5] Generated MX-verified canonical contact {synth_email} for {canonical_dom}")
                        break

        # Tier 6: Multi-Engine Web Search Discovery (Google, Yahoo, Bing) for Missing Websites / Direct Inboxes
        if not discovered_contacts or canonical_dom.endswith(".local"):
            search_name = company_name or clean_dom.split(".")[0].replace("-", " ").title()
            logger.info(f"[Tier 6] Running Multi-Engine Search Discovery for '{search_name}'...")
            search_res = self.local_finder.find_business_website_and_email(
                business_name=search_name,
                city="",
            )
            if search_res.get("domain") and canonical_dom.endswith(".local"):
                new_dom = search_res["domain"]
                new_url = search_res.get("website_url")
                self.mysql.update_company_domain(company_id, new_dom, new_url)
                logger.info(f"[Tier 6] Upgraded company {company_id} domain from {canonical_dom} -> {new_dom} ({new_url})")

            for sc in search_res.get("contacts", []):
                discovered_contacts.append(sc)
                logger.info(f"[Tier 6] Discovered search verified contact {sc['email']} for '{search_name}'")

        # Deduplicate contacts by email
        unique_contacts = {}
        for c in discovered_contacts:
            em = c.get("email")
            if not em or not isinstance(em, str) or "@" not in em:
                continue
            em = em.lower().strip()
            if em not in unique_contacts:
                unique_contacts[em] = c

        saved_contacts = []
        for em, contact in unique_contacts.items():
            # Validate email
            val_result = self.validator.validate(em)
            email_status = val_result["status"]
            email_score = val_result["score"]
            v_source = val_result["source"]

            # Save contact record to MySQL
            contact_id = self.mysql.save_contact(
                company_id=company_id,
                full_name=contact["full_name"],
                email=em,
                first_name=contact.get("first_name"),
                last_name=contact.get("last_name"),
                title=contact.get("title"),
                role_category=contact.get("role_category"),
                email_status=email_status,
                email_score=email_score,
                verification_source=v_source,
                linkedin_url=contact.get("linkedin_url"),
                source=contact.get("source", "hunter"),
                raw_contact_data=contact.get("raw_contact_data"),
            )

            contact["id"] = contact_id
            contact["email_status"] = email_status
            contact["email_score"] = email_score
            saved_contacts.append(contact)

        logger.info(
            f"Enrichment completed for {canonical_dom}: Saved {len(saved_contacts)} contacts."
        )
        return saved_contacts


def get_enrichment_worker() -> EnrichmentWorker:
    return EnrichmentWorker()
