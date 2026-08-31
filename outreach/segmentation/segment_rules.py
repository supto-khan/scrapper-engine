import logging
from typing import Any

logger = logging.getLogger(__name__)


class LeadSegmenter:
    """
    Lead Segmentation Rules Engine for Nexidiant Outreach Campaigns.
    Categorizes leads into high-converting sales segment buckets:
    - laravel_modernization (outdated WP, PHP tech debt, custom Laravel migration)
    - frontend_modernization (legacy jQuery 1.x/2.x, Angular/React rebuilds)
    - speed_optimization (low mobile performance, slow LCP > 2.5s)
    - staff_augmentation (active engineering hiring posts, capacity shortage)
    """

    def segment_lead(
        self,
        company_data: dict[str, Any],
        tech_fingerprint: dict[str, Any] | None = None,
        opportunities: list[dict[str, Any]] | None = None,
        signals: list[dict[str, Any]] | None = None,
    ) -> str:
        """
        Determines the highest priority campaign segment for a lead.
        """
        opps = opportunities or []
        tech = tech_fingerprint or {}
        sigs = signals or []

        opp_types = [o.get("type", "") for o in opps]

        # 0. Highest Priority: No Website / New Website Creation
        if (
            "new_website_creation" in opp_types
            or company_data.get("has_website") is False
            or company_data.get("is_high_priority_nowebsite")
            or any(s.get("signal_type") == "missing_website" for s in sigs)
        ):
            return "new_website_creation"

        # 1. Staff Augmentation / Active Hiring
        if "staff_augmentation" in opp_types or any(
            s.get("type") == "hiring_skill_match" for s in sigs
        ):
            return "staff_augmentation"

        # 2. WordPress to Laravel Migration
        if (
            "cms_to_laravel_migration" in opp_types
            or "wordpress" in str(tech.get("cms", "")).lower()
        ):
            return "laravel_modernization"

        # 3. Frontend Modernization (React / Angular)
        fe_raw = tech.get("frontend_stack", [])
        if isinstance(fe_raw, str):
            try:
                import json
                fe_list = json.loads(fe_raw)
                if not isinstance(fe_list, list):
                    fe_list = [fe_raw]
            except Exception:
                fe_list = [fe_raw]
        elif isinstance(fe_raw, list):
            fe_list = fe_raw
        else:
            fe_list = [str(fe_raw)]

        if "frontend_modernization" in opp_types or any(
            "jquery" in str(x).lower() for x in fe_list
        ):
            return "frontend_modernization"

        # 4. Performance & Core Web Vitals Optimization
        if (
            "performance_optimization" in opp_types
            or "backend_optimization" in opp_types
        ):
            return "speed_optimization"

        return "general_engineering"


def get_lead_segmenter() -> LeadSegmenter:
    return LeadSegmenter()
