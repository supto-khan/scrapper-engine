from datetime import datetime, timezone
import logging
from typing import Any

from scoring.buying_score import get_buying_scorer
from scoring.fit_score import get_fit_scorer
from scoring.pain_score import get_pain_and_tech_scorer

logger = logging.getLogger(__name__)


class OpportunityScorer:
    """
    Master Composite Opportunity Scorer implementing the exact spec formula:

    opportunity_score = (
        company_fit        * 0.20 +
        technology_gap      * 0.20 +
        pain_signal          * 0.20 +
        buying_signal         * 0.20 +
        contact_quality        * 0.10 +
        service_fit              * 0.10
    ) * staleness_factor

    Priority Classification:
    - 90–100: Immediate opportunity
    - 75–89: High priority
    - 60–74: Nurture
    - 40–59: Low priority
    - <40: Ignore
    """

    def __init__(self):
        self.fit_scorer = get_fit_scorer()
        self.pain_and_tech_scorer = get_pain_and_tech_scorer()
        self.buying_scorer = get_buying_scorer()

    def classify_priority(self, score: float, needs_recrawl: bool = False) -> str:
        if needs_recrawl and score >= 75.0:
            return "recrawl_review"
        if score >= 90.0:
            return "immediate"
        elif score >= 75.0:
            return "high"
        elif score >= 60.0:
            return "nurture"
        elif score >= 40.0:
            return "low"
        else:
            return "ignore"

    def compute_data_completeness(
        self,
        tech_fingerprint: dict[str, Any] | None = None,
        audit_metrics: dict[str, Any] | None = None,
        signals: list[dict[str, Any]] | None = None,
    ) -> float:
        """
        Differentiates 'genuinely clean, low-opportunity' from 'under-crawled/blocked'.
        Returns 0.0 - 1.0 completeness ratio.
        """
        completeness = 0.0
        if tech_fingerprint:
            completeness += 0.35
            if tech_fingerprint.get("evidence") or tech_fingerprint.get("frontend_stack"):
                completeness += 0.15
        if audit_metrics and (audit_metrics.get("ttfb_ms") or audit_metrics.get("performance_score")):
            completeness += 0.35
        if signals and len(signals) > 0:
            completeness += 0.15

        return min(1.0, round(completeness, 2))

    def compute_staleness_factor(self, last_crawled_at: Any | None = None) -> tuple[float, bool]:
        """
        Applies decay if lead has sat in pipeline without outreach for > 14 days.
        If > 30 days, flags for mandatory re-crawl.
        Returns: (staleness_factor, needs_recrawl)
        """
        if not last_crawled_at:
            return 1.0, False

        try:
            if isinstance(last_crawled_at, str):
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                    try:
                        crawled_dt = datetime.strptime(last_crawled_at.split(".")[0], fmt)
                        break
                    except ValueError:
                        continue
                else:
                    return 1.0, False
            elif isinstance(last_crawled_at, datetime):
                crawled_dt = last_crawled_at
            else:
                return 1.0, False

            # Ensure UTC comparison
            now = datetime.now()
            if crawled_dt.tzinfo:
                now = datetime.now(timezone.utc)

            age_days = (now - crawled_dt).days
            if age_days <= 14:
                return 1.0, False
            elif age_days <= 30:
                # Gradual decay: -2% per day past day 14 (floored at 0.70)
                decay = max(0.70, 1.0 - (age_days - 14) * 0.02)
                return round(decay, 2), False
            else:
                # Greater than 30 days stale: 0.70 cap and flag for recrawl
                return 0.70, True
        except Exception as e:
            logger.warning(f"Error computing staleness factor: {e}")
            return 1.0, False

    def compute_contact_quality(
        self, company_data: dict[str, Any], contacts: list[dict[str, Any]] | None = None
    ) -> float:
        """
        Phase 3 baseline contact quality (evaluates domain validity, website url presence).
        Expands in Phase 4 with verified decision makers.
        """
        score = 50.0
        if company_data.get("website_url"):
            score += 25.0
        if company_data.get("domain") and "." in company_data.get("domain", ""):
            score += 25.0
        if contacts:
            score = min(100.0, score + len(contacts) * 10.0)
        return min(100.0, score)

    def compute_service_fit(self, opportunities: list[dict[str, Any]]) -> float:
        """
        Evaluates alignment of detected opportunities with Nexidiant core revenue services.
        Awards both high-ticket turnkey projects (+25) and pilot-tier entry sprints (+15).
        """
        if not opportunities:
            return 20.0

        score = 40.0
        high_value_services = [
            "cms_to_laravel_migration",
            "frontend_modernization",
            "staff_augmentation",
            "new_website_creation",
        ]
        for opp in opportunities:
            opp_type = opp.get("type", "")
            if opp_type in high_value_services:
                score += 25.0
            else:
                score += 15.0

        return min(100.0, score)

    def calculate_score(
        self,
        company_data: dict[str, Any],
        tech_fingerprint: dict[str, Any] | None = None,
        audit_metrics: dict[str, Any] | None = None,
        signals: list[dict[str, Any]] | None = None,
        pains: list[dict[str, Any]] | None = None,
        opportunities: list[dict[str, Any]] | None = None,
        contacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """
        Computes composite opportunity score with:
        - Decoupled 6-dimensional metrics
        - Data completeness check (under-crawled vs low-opportunity)
        - Staleness time decay (>14 days stale)
        - Highest Priority Boost (Score 90-95 Immediate Tier) for businesses with no website
        """
        pains = pains or []
        signals = signals or []
        opportunities = opportunities or []

        # 1. Compute Individual Dimensions
        company_fit = self.fit_scorer.score(company_data)
        technology_gap = self.pain_and_tech_scorer.compute_technology_gap(
            tech_fingerprint, audit_metrics
        )
        pain_signal = self.pain_and_tech_scorer.compute_pain_signal(pains)
        buying_signal = self.buying_scorer.score(signals)
        contact_quality = self.compute_contact_quality(company_data, contacts)
        service_fit = self.compute_service_fit(opportunities)

        # 2. Data Completeness & Staleness
        data_completeness = self.compute_data_completeness(
            tech_fingerprint, audit_metrics, signals
        )
        last_crawled = company_data.get("last_crawled_at") or (tech_fingerprint or {}).get("scanned_at")
        staleness_factor, is_stale_recrawl = self.compute_staleness_factor(last_crawled)

        needs_recrawl = is_stale_recrawl or (data_completeness < 0.35 and company_fit >= 70.0)

        # Check if this is a high-priority "No Website" lead
        is_no_website = (
            company_data.get("is_high_priority_nowebsite")
            or company_data.get("has_website") is False
            or any(s.get("signal_type") == "missing_website" for s in signals)
            or any(o.get("type") == "new_website_creation" for o in opportunities)
        )

        # 3. Composite Weighted Formula with Staleness Decay
        raw_composite = (
            company_fit * 0.20
            + technology_gap * 0.20
            + pain_signal * 0.20
            + buying_signal * 0.20
            + contact_quality * 0.10
            + service_fit * 0.10
        )

        if is_no_website:
            # Direct Immediate Opportunity: commercial business with active phone/reviews but no web presence
            composite = 92.0
            priority_tier = "immediate"
        else:
            composite = round(min(100.0, max(0.0, raw_composite * staleness_factor)), 2)
            priority_tier = self.classify_priority(composite, needs_recrawl)

        # 4. Calculate Deal Value Range Sum
        deal_low_sum = sum(o.get("estimated_value_low", 0) for o in opportunities)
        deal_high_sum = sum(o.get("estimated_value_high", 0) for o in opportunities)
        if is_no_website and deal_high_sum == 0:
            deal_low_sum = 2500
            deal_high_sum = 5000

        breakdown = {
            "company_fit": company_fit,
            "technology_gap": technology_gap,
            "pain_signal": pain_signal,
            "buying_signal": buying_signal,
            "contact_quality": contact_quality,
            "service_fit": service_fit,
            "opportunity_score": composite,
            "raw_score_before_decay": round(raw_composite, 2),
            "staleness_factor": staleness_factor,
            "data_completeness": data_completeness,
            "needs_recrawl": needs_recrawl,
            "priority_tier": priority_tier,
            "total_deal_range": [deal_low_sum, deal_high_sum],
            "opportunities_count": len(opportunities),
        }

        return breakdown


def get_opportunity_scorer() -> OpportunityScorer:
    return OpportunityScorer()
