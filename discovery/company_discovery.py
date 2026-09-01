import logging
import re
from typing import Any

from shared.mysql_client import get_mysql_client
from shared.queue import RedisQueue
from shared.redis_client import get_redis_client, normalize_domain

logger = logging.getLogger(__name__)

# Keywords indicating an agency / software vendor (to exclude)
AGENCY_EXCLUSION_KEYWORDS = [
    "agency", "agencies", "software company", "software development",
    "web development", "web design company", "dev shop", "dev studio",
    "digital agency", "creative agency", "it services", "it solutions",
    "staff augmentation", "software consultancy", "app developers",
    "software house", "tech studio", "custom software agency"
]

# Industry Matching Keywords (Tier 1 & Tier 2)
INDUSTRY_KEYWORDS = {
    "E-Commerce & Online Stores": [
        "e-commerce", "ecommerce", "online store", "shopify", "woocommerce",
        "marketplace", "d2c", "retail", "fashion", "apparel", "products", "cart"
    ],
    "Real Estate & PropTech": [
        "real estate", "property management", "realtor", "mls", "idx",
        "listing platform", "proptech", "brokerage", "apartments", "leasing"
    ],
    "Food & Hospitality": [
        "restaurant", "food delivery", "menu", "pos", "food ordering",
        "catering", "hospitality", "dining", "bar", "cafe"
    ],
    "Healthcare & Life Sciences": [
        "healthcare", "medical", "clinic", "dental", "doctor", "health",
        "patient", "biotech", "pharma", "therapy", "wellness", "hospital"
    ],
    "FinTech & Financial Services": [
        "fintech", "finance", "banking", "lending", "credit", "investment",
        "wealth", "insurance", "payments", "accounting", "tax"
    ],
    "Logistics & Supply Chain": [
        "logistics", "freight", "transport", "warehouse", "shipping", "supply chain",
        "fleet", "trucking", "delivery"
    ],
    "B2B SaaS & Tech Services": [
        "saas", "software platform", "b2b platform", "cloud platform", "crm", "erp"
    ]
}


class CompanyDiscoveryOrchestrator:
    """
    Orchestrates discovery across all active directory feeds:
    - Filters out software agencies / dev shops (competitors).
    - Prioritizes end-client businesses needing custom software (E-Commerce, Real Estate, Food/Hospitality).
    - Normalizes records, performs Redis deduplication, upserts to MySQL, and enqueues for analysis.
    """

    def __init__(self):
        self.redis_client = get_redis_client()
        self.mysql_client = get_mysql_client()
        self.tier2_queue = RedisQueue("tier2_crawl", self.redis_client)
        self._warmup_seen_domains()

    def _warmup_seen_domains(self) -> None:
        """Pre-seeds Redis seen_domains and seen_names sets from MySQL companies table to prevent duplicate crawls across server restarts."""
        try:
            conn = self.mysql_client.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT domain, name FROM companies")
                rows = cursor.fetchall()
                for row in rows:
                    dom = row.get("domain")
                    if dom:
                        self.redis_client.mark_domain_seen(dom)
                    c_name = row.get("name")
                    if c_name:
                        self.redis_client.mark_name_seen(c_name)
            conn.close()
            logger.info(f"💾 Pre-warmed Redis domain & name deduplication cache with {len(rows)} existing companies from MySQL.")
        except Exception as e:
            logger.debug(f"Redis cache pre-warm skipped or MySQL offline: {e}")

    def is_agency_or_competitor(self, name: str, domain: str, industry: str = "") -> bool:
        """
        Detects if a company is a software agency/developer rather than an end-client business.
        """
        combined = f"{name} {domain} {industry}".lower()
        return any(kw in combined for kw in AGENCY_EXCLUSION_KEYWORDS)

    def classify_target_industry(self, text: str, default_industry: str = "Custom Business Application") -> str:
        """
        Classifies an end-client business into target industry verticals.
        """
        if not text:
            return default_industry

        clean_text = text.lower()
        for ind_label, keywords in INDUSTRY_KEYWORDS.items():
            if any(kw in clean_text for kw in keywords):
                return ind_label

        return default_industry

    def ingest_candidate(self, candidate: dict[str, Any], allow_agency: bool = False) -> bool:
        """
        Ingests a single discovered company candidate.
        Returns True if newly accepted, False if duplicate, invalid, or excluded agency.
        """
        name = (candidate.get("name") or "").strip()
        raw_domain = candidate.get("domain") or candidate.get("website_url") or ""
        clean_domain = normalize_domain(raw_domain)
        industry = candidate.get("industry") or ""

        if not clean_domain or "." not in clean_domain:
            logger.warning(f"Skipping invalid candidate domain: {raw_domain}")
            return False

        # 1. Agency / Competitor Exclusion Filter
        if not allow_agency and self.is_agency_or_competitor(name, clean_domain, industry):
            logger.info(f"🚫 [Exclusion Filter] Skipped software agency/competitor: {name} ({clean_domain})")
            return False

        # 2. Redis & MySQL Deduplication (Domain & Business Name Defense)
        if self.redis_client.is_domain_seen(clean_domain):
            logger.info(f"Duplicate domain skipped (seen in Redis): {clean_domain}")
            return False

        if name and self.redis_client.is_name_seen(name):
            logger.info(f"Duplicate company name skipped (seen in Redis): {name}")
            return False

        existing_in_db = self.mysql_client.get_company_by_domain(clean_domain)
        if existing_in_db:
            self.redis_client.mark_domain_seen(clean_domain)
            if name:
                self.redis_client.mark_name_seen(name)
            logger.info(f"Duplicate domain skipped (already exists in MySQL #{existing_in_db['id']}): {clean_domain}")
            return False

        if name:
            existing_name_db = self.mysql_client.get_company_by_name(name)
            if existing_name_db:
                self.redis_client.mark_name_seen(name)
                logger.info(f"Duplicate company name skipped (already exists in MySQL #{existing_name_db['id']}): {name}")
                return False

        self.redis_client.mark_domain_seen(clean_domain)
        if name:
            self.redis_client.mark_name_seen(name)

        # 3. Target Industry Classification
        final_industry = self.classify_target_industry(
            f"{name} {industry} {candidate.get('project_summary', '')}",
            default_industry=industry or "Commercial Business & Services"
        )

        # 4. Persist to MySQL
        try:
            company_id = self.mysql_client.upsert_company(
                domain=clean_domain,
                name=name or clean_domain,
                source=candidate.get("source", "discovery"),
                industry=final_industry,
                employee_count_estimate=candidate.get("employee_count_estimate"),
                website_url=candidate.get("website_url"),
            )
            # If source is a verified directory review / client testimonial, record high-confidence past spend signal
            source_str = candidate.get("source", "")
            if company_id and ("client" in source_str or "review" in source_str):
                self.mysql_client.save_signal(
                    company_id=company_id,
                    signal_type="directory_client_review",
                    source_url=candidate.get("website_url", f"https://{clean_domain}"),
                    confidence_score=90.0,
                    evidence_data={
                        "project_summary": candidate.get("project_summary", "Verified client review case study"),
                        "intent_type": "confirmed_past_agency_spend",
                        "confidence_weight": 90.0,
                    },
                )
        except Exception as e:
            logger.error(f"Failed to upsert company {clean_domain} to MySQL: {e}")
            company_id = 0

        # 5. Enqueue for Tier-2 crawl
        self.tier2_queue.push(
            {
                "company_id": company_id,
                "domain": clean_domain,
                "name": name,
                "source": candidate.get("source"),
                "industry": final_industry,
                "website_url": candidate.get("website_url") or f"https://{clean_domain}",
            }
        )

        logger.info(f"✅ Accepted & queued end-client business: {name} ({clean_domain}) [{final_industry}]")
        return True
