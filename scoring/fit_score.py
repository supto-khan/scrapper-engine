import logging
import re
from typing import Any

logger = logging.getLogger(__name__)


class CompanyFitScorer:
    """
    Computes company fit score (0 - 100) and produces explainable attribution.
    Strictly disqualifies dev agencies, software houses, IT consultancies,
    and any tech-supplier entity that is a competitor — not a buyer.

    Scoring axes:
    - Commercial Industry match (E-Commerce, Real Estate, Restaurant/Hospitality, Healthcare, Retail)
    - Team / employee count sweet spot (10 - 250 employees)
    - Verified source credibility
    """

    # ------------------------------------------------------------------ #
    # DISQUALIFICATION — these are SUPPLIERS / COMPETITORS, not buyers    #
    # Any single match in industry label, company name, or domain → 0.0  #
    # ------------------------------------------------------------------ #

    # Industry label keywords (checked against company.industry field)
    DISQUALIFIED_INDUSTRY_KEYWORDS: list[str] = [
        # Generic "agency" catch-all
        "agency",
        "agencies",
        # Software / Dev / Engineering
        "software development",
        "software house",
        "software company",
        "software consulting",
        "software solutions",
        "software services",
        "software studio",
        "software firm",
        "web development",
        "web design",
        "web agency",
        "web studio",
        "web solutions",
        "app development",
        "application development",
        "mobile development",
        "mobile app development",
        "mobile app agency",
        "custom development",
        "product development",
        "product studio",
        # IT / Consulting umbrella terms
        "it services",
        "it consulting",
        "it solutions",
        "it company",
        "it firm",
        "it agency",
        "information technology",
        "managed services",
        "msp",
        "system integrator",
        "systems integration",
        "technology consulting",
        "tech consulting",
        "technology company",
        "tech company",
        "technology services",
        "tech services",
        "technology solutions",
        "tech solutions",
        "technology firm",
        # Dev shops / studios
        "dev shop",
        "dev agency",
        "dev studio",
        "dev firm",
        "development studio",
        "development agency",
        "development company",
        "development firm",
        "development shop",
        # Digital / Creative agencies
        "digital agency",
        "digital studio",
        "digital transformation",
        "digital solutions",
        "digital services",
        "digital marketing agency",
        "digital marketing company",
        # Design agencies
        "ux agency",
        "ui agency",
        "ux/ui",
        "design agency",
        "design studio",
        "design company",
        "creative agency",
        "creative studio",
        # SaaS / Product companies (they build, not buy)
        "saas company",
        "saas provider",
        "saas platform",
        "saas startup",
        "software startup",
        "tech startup",
        "technology startup",
        # Offshore / outsourcing shops
        "outsourcing",
        "nearshore",
        "offshore development",
        "staff augmentation provider",
        "augmentation company",
        # DevOps / Cloud / Infra service companies
        "devops agency",
        "devops company",
        "cloud consulting",
        "cloud services company",
        "infrastructure services",
        # QA / Testing services
        "qa company",
        "testing company",
        "testing services",
        # Clutch / GoodFirms scraped legacy labels
        "software & web development",
        "software and web development",
        "web & software development",
    ]

    # Company NAME keywords — disqualify if name contains these
    # Only applied when no target industry label is present (avoids false positives
    # like "Retail Studios LLC" or "Healthcare Solutions Group")
    DISQUALIFIED_NAME_KEYWORDS: list[str] = [
        "infotech",
        "infosoft",
        "softtech",
        "softech",
        "techsolutions",
        "webdev",
        "devops",
        "coders",
        "codex",
        "devx",
        "appdev",
        "byte",
        "pixels",
        "pixelsoft",
        "codebase",
        "codehouse",
        "itworks",
        "techworks",
        "netsoft",
        "netsolutions",
        "outsource",
        "nearshore",
    ]

    # Domain-level signals — regex patterns that strongly indicate a dev agency domain
    DISQUALIFIED_DOMAIN_PATTERNS: list[str] = [
        r"(devs?|coder|codebase|codehouse|softdev|webdev|appdev)\.",
        r"\.(dev|code|tech|labs?|studio)$",
        r"^\w*(agency|agenc)(y|ies)?\.",
        r"^\w*(outsourc|offsh|nearsh)\w*\.",
    ]

    # ------------------------------------------------------------------ #
    # TARGET INDUSTRIES — commercial buyers we want to reach              #
    # ------------------------------------------------------------------ #

    TARGET_INDUSTRIES: list[str] = [
        "e-commerce",
        "ecommerce",
        "retail",
        "dtc",
        "direct to consumer",
        "real estate",
        "property management",
        "proptech",
        "real estate technology",
        "restaurant",
        "food delivery",
        "food & beverage",
        "hospitality",
        "catering",
        "hotel",
        "travel",
        "tourism",
        "health",
        "healthcare",
        "medtech",
        "fitness",
        "wellness",
        "logistics",
        "supply chain",
        "transportation",
        "automotive",
        "auto dealership",
        "financial services",
        "fintech",
        "insurance",
        "legal",
        "law firm",
        "education",
        "edtech",
        "commercial services",
        "construction",
        "manufacturing",
        "wholesale",
        "distribution",
        "media",
        "publishing",
        "sports",
        "entertainment",
    ]

    # ------------------------------------------------------------------ #
    # HELPERS                                                              #
    # ------------------------------------------------------------------ #

    def _is_disqualified(self, company_data: dict[str, Any]) -> tuple[bool, str]:
        """
        Returns (True, reason_string) if company is a dev agency / IT supplier.
        Uses 3 independent signal layers:
          1. Industry label keyword match  (broadest net)
          2. Company name keyword match    (name alone is suspicious)
          3. Domain regex pattern match    (structural domain signals)
        """
        industry = (company_data.get("industry") or "").lower().strip()
        name = (company_data.get("name") or "").lower().strip()
        domain = (company_data.get("domain") or "").lower().strip()

        # Layer 1: Industry label keyword match
        for kw in self.DISQUALIFIED_INDUSTRY_KEYWORDS:
            if kw in industry:
                return True, f"industry_keyword:{kw}"

        # Layer 2: Company name keyword match
        # Guard: skip if a confirmed target industry label is present — prevents
        # false positives like "Fitness Studios Group" or "Healthcare Solutions Ltd"
        is_confirmed_target = any(t in industry for t in self.TARGET_INDUSTRIES)
        if not is_confirmed_target:
            for kw in self.DISQUALIFIED_NAME_KEYWORDS:
                if re.search(rf"\b{re.escape(kw)}\b", name):
                    return True, f"name_keyword:{kw}"

        # Layer 3: Domain regex pattern match
        for pattern in self.DISQUALIFIED_DOMAIN_PATTERNS:
            if re.search(pattern, domain, re.IGNORECASE):
                return True, f"domain_pattern:{pattern}"

        return False, ""

    def _parse_employee_bounds(self, emp_str: str) -> tuple[int, int] | None:
        """Parses employee count strings into numeric bounds (min, max)."""
        if not emp_str:
            return None
        emp_clean = str(emp_str).lower().replace(",", "")

        range_match = re.search(r"(\d+)\s*(?:-|to)\s*(\d+)", emp_clean)
        if range_match:
            return int(range_match.group(1)), int(range_match.group(2))

        plus_match = re.search(r"(\d+)\s*\+", emp_clean)
        if plus_match:
            val = int(plus_match.group(1))
            return val, val * 2

        single_match = re.search(r"(\d+)", emp_clean)
        if single_match:
            val = int(single_match.group(1))
            return val, val

        return None

    # ------------------------------------------------------------------ #
    # SCORING                                                              #
    # ------------------------------------------------------------------ #

    def score_with_breakdown(self, company_data: dict[str, Any]) -> tuple[float, list[dict[str, Any]]]:
        # 0. Hard DISQUALIFY — dev agencies are competitors, not buyers
        disqualified, reason = self._is_disqualified(company_data)
        if disqualified:
            logger.debug(
                f"DISQUALIFIED [{reason}]: {company_data.get('name')} ({company_data.get('domain')})"
            )
            return 0.0, [{"reason": f"disqualified:{reason}", "points": -100.0}]

        score = 25.0  # Conservative baseline for newly discovered leads
        breakdown = [{"reason": "baseline_discovery", "points": 25.0}]

        # 1. Commercial Industry Fit (+35 max)
        industry = (company_data.get("industry") or "").lower()
        if any(target in industry for target in self.TARGET_INDUSTRIES):
            score += 35.0
            breakdown.append({"reason": f"target_industry_match:{industry}", "points": 35.0})
            logger.debug(f"Matched target industry '{industry}' → +35.0 pts")
        elif industry:
            score += 15.0
            breakdown.append({"reason": f"neutral_industry:{industry}", "points": 15.0})
            logger.debug(f"Matched neutral industry '{industry}' → +15.0 pts")

        # 2. Employee Size Sweet Spot (+30 max)
        emp_str = str(company_data.get("employee_count_estimate") or "")
        bounds = self._parse_employee_bounds(emp_str)

        if bounds:
            min_e, max_e = bounds
            if (min_e >= 10 and max_e <= 300) or (min_e <= 10 and max_e >= 20 and max_e <= 250):
                score += 30.0
                breakdown.append({"reason": f"employee_sweet_spot:{min_e}-{max_e}", "points": 30.0})
                logger.debug(f"Matched employee sweet spot {min_e}-{max_e} → +30.0 pts")
            elif max_e < 10:
                score += 15.0
                breakdown.append({"reason": f"startup_solo:{max_e}", "points": 15.0})
                logger.debug(f"Matched startup/solo size {max_e} → +15.0 pts")
            elif min_e >= 500:
                score += 10.0
                breakdown.append({"reason": f"large_enterprise:{min_e}", "points": 10.0})
                logger.debug(f"Matched enterprise size {min_e}+ → +10.0 pts")
            else:
                score += 20.0
                breakdown.append({"reason": f"general_size:{min_e}-{max_e}", "points": 20.0})
        elif "mid" in emp_str.lower():
            score += 25.0
            breakdown.append({"reason": "mid_size_estimate", "points": 25.0})

        # 3. Source Credibility (+10 max)
        source = (company_data.get("source") or "").lower()
        if source in ["clutch", "goodfirms", "designrush", "yelp", "google_maps", "gmaps"] or any(
            v in source for v in ["clutch", "goodfirms", "designrush", "yelp", "google_maps", "gmaps"]
        ):
            score += 10.0
            breakdown.append({"reason": f"verified_source:{source}", "points": 10.0})
            logger.debug(f"Matched verified source '{source}' → +10.0 pts")

        final_score = min(100.0, max(0.0, round(score, 2)))
        return final_score, breakdown

    def score(self, company_data: dict[str, Any]) -> float:
        score_val, _ = self.score_with_breakdown(company_data)
        return score_val


def get_fit_scorer() -> CompanyFitScorer:
    return CompanyFitScorer()
