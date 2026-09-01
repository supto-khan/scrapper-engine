import logging
import os
from typing import Any
import yaml

logger = logging.getLogger(__name__)


class OpportunityDetector:
    """
    Translates detected business pain points into specific Nexidiant agency service offerings,
    synthesizing multiple issues into a unified high-ticket Master Modernization Opportunity ($2,500 - $5,000).
    """

    DEFAULT_CATALOG = {
        "turnkey_modernization_overhaul": {
            "service": "Turnkey Web Modernization, Mobile Conversion & Performance Overhaul",
            "billing_model": "fixed_project",
            "deal_low": 25000,
            "deal_high": 50000,
            "offshore_new_vendor_quote_low": 2500,
            "offshore_new_vendor_quote_high": 5000,
            "pilot_sprint_quote_low": 900,
            "pilot_sprint_quote_high": 1800,
            "opp_type": "turnkey_modernization_overhaul",
            "confidence_default": 0.95,
            "quote_positioning": "master_audit_solution",
        },
        "subpage_speed_discrepancy": {
            "service": "Multi-Page Speed & Asset Optimization",
            "billing_model": "fixed_project",
            "deal_low": 8000,
            "deal_high": 20000,
            "offshore_new_vendor_quote_low": 1500,
            "offshore_new_vendor_quote_high": 3500,
            "pilot_sprint_quote_low": 800,
            "pilot_sprint_quote_high": 1500,
            "opp_type": "performance_optimization",
            "confidence_default": 0.90,
            "quote_positioning": "pilot_sprint_intro",
        },
        "missing_mobile_tel_link": {
            "service": "Mobile CRO & 1-Tap Booking Integration",
            "billing_model": "fixed_project",
            "deal_low": 5000,
            "deal_high": 15000,
            "offshore_new_vendor_quote_low": 1000,
            "offshore_new_vendor_quote_high": 2500,
            "pilot_sprint_quote_low": 500,
            "pilot_sprint_quote_high": 1000,
            "opp_type": "conversion_rate_optimization",
            "confidence_default": 0.95,
            "quote_positioning": "pilot_sprint_intro",
        },
        "dns_email_deliverability_risk": {
            "service": "DNS & Email Deliverability Authentication (SPF / DMARC)",
            "billing_model": "fixed_project",
            "deal_low": 3000,
            "deal_high": 8000,
            "offshore_new_vendor_quote_low": 500,
            "offshore_new_vendor_quote_high": 1200,
            "pilot_sprint_quote_low": 350,
            "pilot_sprint_quote_high": 600,
            "opp_type": "infrastructure_security",
            "confidence_default": 0.95,
            "quote_positioning": "pilot_sprint_intro",
        },
        "legacy_jquery": {
            "service": "Frontend Modernization (React / Next.js / TypeScript)",
            "billing_model": "fixed_project",
            "deal_low": 15000,
            "deal_high": 40000,
            "offshore_new_vendor_quote_low": 3500,
            "offshore_new_vendor_quote_high": 10000,
            "pilot_sprint_quote_low": 1200,
            "pilot_sprint_quote_high": 2500,
            "opp_type": "frontend_modernization",
            "confidence_default": 0.85,
            "quote_positioning": "new_vendor_anchor_low",
        },
        "legacy_angularjs_eol": {
            "service": "Legacy AngularJS to React / Next.js Migration",
            "billing_model": "fixed_project",
            "deal_low": 20000,
            "deal_high": 45000,
            "offshore_new_vendor_quote_low": 4500,
            "offshore_new_vendor_quote_high": 12000,
            "pilot_sprint_quote_low": 1500,
            "pilot_sprint_quote_high": 3000,
            "opp_type": "frontend_modernization",
            "confidence_default": 0.95,
            "quote_positioning": "new_vendor_anchor_low",
        },
        "outdated_wordpress": {
            "service": "WordPress to Custom Next.js / Modern Stack Migration",
            "billing_model": "fixed_project",
            "deal_low": 20000,
            "deal_high": 60000,
            "offshore_new_vendor_quote_low": 5000,
            "offshore_new_vendor_quote_high": 15000,
            "pilot_sprint_quote_low": 1500,
            "pilot_sprint_quote_high": 3000,
            "opp_type": "cms_to_laravel_migration",
            "confidence_default": 0.90,
            "quote_positioning": "new_vendor_anchor_low",
        },
        "hiring_capacity_bottleneck": {
            "service": "Dedicated Full-Stack Engineering Team Augmentation",
            "billing_model": "monthly_recurring",
            "typical_duration_months": 6,
            "deal_low": 30000,
            "deal_high": 80000,
            "offshore_new_vendor_quote_low": 3500,
            "offshore_new_vendor_quote_high": 8000,
            "pilot_sprint_quote_low": 1500,
            "pilot_sprint_quote_high": 3500,
            "opp_type": "staff_augmentation",
            "confidence_default": 0.85,
            "quote_positioning": "new_vendor_anchor_low",
        },
    }

    def __init__(self, config_path: str | None = None):
        self.pricing_version = "1.4.0"
        self.currency = "USD"
        self.active_positioning = "new_vendor_anchor_low"
        self.positioning_profiles = {}
        self.service_catalog = dict(self.DEFAULT_CATALOG)
        self._load_config(config_path)

    def _load_config(self, config_path: str | None = None) -> None:
        if not config_path:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            config_path = os.path.join(base_dir, "config", "opportunity_pricing.yaml")

        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f)
                    if cfg:
                        self.pricing_version = cfg.get("version", "1.4.0")
                        self.currency = cfg.get("currency", "USD")
                        self.active_positioning = cfg.get("active_positioning", "new_vendor_anchor_low")
                        self.positioning_profiles = cfg.get("positioning_profiles", {})
            except Exception as e:
                logger.warning(f"Could not load opportunity_pricing.yaml, using defaults: {e}")

    def detect_opportunities(
        self,
        pains: list[dict[str, Any]],
        company_metadata: dict[str, Any] | None = None,
        deep_audit: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Synthesizes detected pains into high-value opportunities.
        When multiple technical and conversion pains exist, combines them into a
        SINGLE unified Master Opportunity ($2,500 - $5,000) with 3-pillar evidence.
        """
        if not pains:
            return []

        opportunities = []

        # If 2 or more pains exist, generate Master Unified Opportunity
        if len(pains) >= 2 or deep_audit:
            speed_pains = [p for p in pains if "speed" in p["type"] or "ttfb" in p["type"] or "performance" in p["type"]]
            cro_pains = [p for p in pains if "tel" in p["type"] or "form" in p["type"] or "booking" in p["type"]]
            seo_dns_pains = [p for p in pains if "schema" in p["type"] or "dns" in p["type"] or "social" in p["type"] or "security" in p["type"] or "http" in p["type"]]
            tech_pains = [p for p in pains if "jquery" in p["type"] or "wordpress" in p["type"] or "angular" in p["type"] or "hiring" in p["type"]]

            master_opp = {
                "type": "turnkey_modernization_overhaul",
                "recommended_service": "Turnkey Web Modernization, Mobile Conversion & Performance Overhaul",
                "billing_model": "fixed_project",
                "estimated_value_low": 25000,
                "estimated_value_high": 50000,
                "offshore_quote_range": [2500, 5000],
                "pilot_sprint_range": [900, 1800],
                "pricing_version": self.pricing_version,
                "currency": self.currency,
                "confidence": 0.95,
                "quote_positioning": "master_audit_solution",
                "positioning_metadata": {
                    "active_positioning": "master_audit_solution",
                    "recommended_cta": "Complimentary 360° architecture audit + modernization sprint",
                },
                "evidence": {
                    "total_pains_detected": len(pains),
                    "all_pain_titles": [p.get("title") for p in pains],
                    "speed_pillar": speed_pains,
                    "conversion_pillar": cro_pains,
                    "seo_dns_pillar": seo_dns_pains,
                    "tech_stack_pillar": tech_pains,
                    "deep_audit_summary": deep_audit or {},
                },
                "status": "detected",
            }
            opportunities.append(master_opp)
            return opportunities

        # Single pain fallback
        pain = pains[0]
        pain_type = pain.get("type")
        catalog_item = self.service_catalog.get(pain_type, self.DEFAULT_CATALOG.get("turnkey_modernization_overhaul"))

        opp_record = {
            "type": catalog_item["opp_type"],
            "recommended_service": catalog_item["service"],
            "billing_model": catalog_item.get("billing_model", "fixed_project"),
            "estimated_value_low": catalog_item["deal_low"],
            "estimated_value_high": catalog_item["deal_high"],
            "offshore_quote_range": [
                catalog_item.get("offshore_new_vendor_quote_low", 2500),
                catalog_item.get("offshore_new_vendor_quote_high", 5000),
            ],
            "pilot_sprint_range": [
                catalog_item.get("pilot_sprint_quote_low", 900),
                catalog_item.get("pilot_sprint_quote_high", 1800),
            ],
            "pricing_version": self.pricing_version,
            "currency": self.currency,
            "confidence": pain.get("confidence", 0.90),
            "quote_positioning": catalog_item.get("quote_positioning", "pilot_sprint_intro"),
            "evidence": {
                "pain_title": pain.get("title"),
                "pain_description": pain.get("description"),
                "pain_severity": pain.get("severity"),
                "raw_evidence": pain.get("evidence"),
            },
            "status": "detected",
        }
        opportunities.append(opp_record)
        return opportunities


def get_opportunity_detector() -> OpportunityDetector:
    return OpportunityDetector()
