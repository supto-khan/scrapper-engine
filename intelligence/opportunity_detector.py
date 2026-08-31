import logging
import os
from typing import Any
import yaml

logger = logging.getLogger(__name__)


class OpportunityDetector:
    """
    Translates detected business pain points into specific Nexidiant agency service offerings,
    calculates estimated deal values based on versioned opportunity_pricing.yaml,
    assigns opportunity confidence, and decouples internal US TAM sizing from offshore quoting posture.
    """

    DEFAULT_CATALOG = {
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
        "legacy_bootstrap_debt": {
            "service": "Frontend UI & Component Modernization (Tailwind CSS / React)",
            "billing_model": "fixed_project",
            "deal_low": 10000,
            "deal_high": 25000,
            "offshore_new_vendor_quote_low": 2500,
            "offshore_new_vendor_quote_high": 7500,
            "pilot_sprint_quote_low": 1000,
            "pilot_sprint_quote_high": 2000,
            "opp_type": "frontend_modernization",
            "confidence_default": 0.85,
            "quote_positioning": "pilot_sprint_intro",
        },
        "outdated_wordpress": {
            "service": "WordPress to Custom Laravel / Next.js Migration",
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
        "wordpress_maintenance_debt": {
            "service": "WordPress Performance & Headless Architecture Rebuild",
            "billing_model": "fixed_project",
            "deal_low": 10000,
            "deal_high": 25000,
            "offshore_new_vendor_quote_low": 2500,
            "offshore_new_vendor_quote_high": 7500,
            "pilot_sprint_quote_low": 1000,
            "pilot_sprint_quote_high": 2000,
            "opp_type": "wordpress_rebuild",
            "confidence_default": 0.80,
            "quote_positioning": "pilot_sprint_intro",
        },
        "insecure_transport_http": {
            "service": "Security & SSL Infrastructure Modernization",
            "billing_model": "fixed_project",
            "deal_low": 3000,
            "deal_high": 8000,
            "offshore_new_vendor_quote_low": 800,
            "offshore_new_vendor_quote_high": 2000,
            "pilot_sprint_quote_low": 500,
            "pilot_sprint_quote_high": 1000,
            "opp_type": "infrastructure_security",
            "confidence_default": 0.95,
            "quote_positioning": "pilot_sprint_intro",
        },
        "poor_mobile_performance": {
            "service": "Core Web Vitals & Frontend Speed Optimization",
            "billing_model": "fixed_project",
            "deal_low": 5000,
            "deal_high": 15000,
            "offshore_new_vendor_quote_low": 1200,
            "offshore_new_vendor_quote_high": 3500,
            "pilot_sprint_quote_low": 800,
            "pilot_sprint_quote_high": 1800,
            "opp_type": "performance_optimization",
            "confidence_default": 0.90,
            "quote_positioning": "pilot_sprint_intro",
        },
        "slow_backend_ttfb": {
            "service": "Backend Response Optimization & Caching",
            "billing_model": "fixed_project",
            "deal_low": 8000,
            "deal_high": 20000,
            "offshore_new_vendor_quote_low": 2000,
            "offshore_new_vendor_quote_high": 5000,
            "pilot_sprint_quote_low": 1000,
            "pilot_sprint_quote_high": 2200,
            "opp_type": "backend_optimization",
            "confidence_default": 0.85,
            "quote_positioning": "pilot_sprint_intro",
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
        self.pricing_version = "1.3.0"
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
                        self.pricing_version = cfg.get("version", "1.3.0")
                        self.currency = cfg.get("currency", "USD")
                        self.active_positioning = cfg.get("active_positioning", "new_vendor_anchor_low")
                        self.positioning_profiles = cfg.get("positioning_profiles", {})
                        services = cfg.get("services", {})
                        # Override catalog values
                        for key, data in services.items():
                            for pain_k, cat_item in self.service_catalog.items():
                                if cat_item["opp_type"] == key:
                                    cat_item["deal_low"] = data.get("estimated_value_low", cat_item["deal_low"])
                                    cat_item["deal_high"] = data.get("estimated_value_high", cat_item["deal_high"])
                                    cat_item["billing_model"] = data.get("billing_model", cat_item.get("billing_model", "fixed_project"))
                                    cat_item["typical_duration_months"] = data.get("typical_duration_months", cat_item.get("typical_duration_months", 1))
                                    cat_item["offshore_new_vendor_quote_low"] = data.get("offshore_new_vendor_quote_low", cat_item.get("offshore_new_vendor_quote_low"))
                                    cat_item["offshore_new_vendor_quote_high"] = data.get("offshore_new_vendor_quote_high", cat_item.get("offshore_new_vendor_quote_high"))
                                    cat_item["pilot_sprint_quote_low"] = data.get("pilot_sprint_quote_low", cat_item.get("pilot_sprint_quote_low"))
                                    cat_item["pilot_sprint_quote_high"] = data.get("pilot_sprint_quote_high", cat_item.get("pilot_sprint_quote_high"))
                                    cat_item["service"] = data.get("title", cat_item["service"])
                                    cat_item["quote_positioning"] = data.get("quote_positioning", cat_item.get("quote_positioning"))
                        logger.info(f"Loaded pricing matrix v{self.pricing_version} ({self.active_positioning}) from {config_path}")
            except Exception as e:
                logger.warning(f"Could not load opportunity_pricing.yaml, using defaults: {e}")

    def detect_opportunities(
        self,
        pains: list[dict[str, Any]],
        company_metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Maps pain points into structured sales opportunities with:
        - estimated_value_low/high: US Market TAM sizing (for lead prioritization)
        - billing_model: fixed_project vs monthly_recurring
        - offshore_quote_range: Single source of truth quoting range (per-month for recurring, fixed for projects)
        - pilot_sprint_quote: Entry-level proof-of-concept sprint
        """
        opportunities = []
        seen_opp_types = set()

        pos_profile = self.positioning_profiles.get(self.active_positioning, {
            "recommended_cta": "Complimentary 15-minute architecture audit + trial sprint",
        })

        for pain in pains:
            pain_type = pain.get("type")
            catalog_item = self.service_catalog.get(pain_type)
            if not catalog_item:
                continue

            opp_type = catalog_item["opp_type"]
            if opp_type in seen_opp_types:
                continue
            seen_opp_types.add(opp_type)

            confidence = pain.get("confidence", catalog_item.get("confidence_default", 0.85))
            quote_positioning = catalog_item.get("quote_positioning", self.active_positioning)
            billing_model = catalog_item.get("billing_model", "fixed_project")

            offshore_quote_low = catalog_item.get("offshore_new_vendor_quote_low", int(catalog_item["deal_low"] * 0.3))
            offshore_quote_high = catalog_item.get("offshore_new_vendor_quote_high", int(catalog_item["deal_high"] * 0.3))

            opp_record = {
                "type": opp_type,
                "recommended_service": catalog_item["service"],
                "billing_model": billing_model,
                # Internal Lead Scoring TAM (US Market Equivalent)
                "estimated_value_low": catalog_item["deal_low"],
                "estimated_value_high": catalog_item["deal_high"],
                # Single Source of Truth Offshore Quoting Range (Per-Month for recurring, fixed for project)
                "offshore_quote_range": [offshore_quote_low, offshore_quote_high],
                "pilot_sprint_range": [
                    catalog_item.get("pilot_sprint_quote_low", int(catalog_item["deal_low"] * 0.1)),
                    catalog_item.get("pilot_sprint_quote_high", int(catalog_item["deal_high"] * 0.1)),
                ],
                "pricing_version": self.pricing_version,
                "currency": self.currency,
                "confidence": confidence,
                "quote_positioning": quote_positioning,
                "positioning_metadata": {
                    "active_positioning": self.active_positioning,
                    "recommended_cta": pos_profile.get("recommended_cta", "Audit first trial sprint"),
                },
                "evidence": {
                    "pain_title": pain.get("title"),
                    "pain_description": pain.get("description"),
                    "pain_severity": pain.get("severity"),
                    "raw_evidence": pain.get("evidence"),
                },
                "status": "detected",
            }

            if billing_model == "monthly_recurring":
                opp_record["typical_duration_months"] = catalog_item.get("typical_duration_months", 6)

            opportunities.append(opp_record)

        return opportunities


def get_opportunity_detector() -> OpportunityDetector:
    return OpportunityDetector()
