import logging
from typing import Any

logger = logging.getLogger(__name__)


class PainAndTechGapScorer:
    """
    Decoupled Evaluation:
    1. Technology Gap Score (0 - 100): Evaluates Codebase Modernity & Stack Debt
       (Absence of modern frameworks, legacy script dependencies, transport security headers).
    2. Pain Signal Score (0 - 100): Evaluates Quantifiable Business & Revenue Friction
       (Conversion-killing Core Web Vitals, severe TTFB bounce rates, active engineering bottlenecks).
    """

    def compute_technology_gap(
        self,
        tech_fingerprint: dict[str, Any] | None,
        audit_metrics: dict[str, Any] | None = None,
    ) -> float:
        """
        Evaluates technical debt and architectural obsolescence (independent of business symptoms).
        """
        gap_score = 0.0
        tech = tech_fingerprint or {}

        evidence = tech.get("evidence", {})
        frontend = tech.get("frontend_stack", [])
        backend = tech.get("backend_stack", [])
        cms = (tech.get("cms") or "").lower()

        # 1. Legacy Monolith / CMS Architecture (+30)
        wp_info = evidence.get("wordpress")
        if "wordpress" in cms or wp_info:
            wp_version = (wp_info or {}).get("version", "")
            if wp_version:
                try:
                    v_num = float(".".join(wp_version.split(".")[:2]))
                    gap_score += 30.0 if v_num < 6.0 else 15.0
                except Exception:
                    gap_score += 20.0
            else:
                gap_score += 20.0
        elif "joomla" in cms or "drupal" in cms:
            gap_score += 25.0

        # 2. Obsolete Script Libraries (+25)
        jquery_info = evidence.get("jquery")
        if any("jquery" in str(x).lower() for x in frontend) or jquery_info:
            version = (jquery_info or {}).get("version", "")
            if version and (version.startswith("1.") or version.startswith("2.")):
                gap_score += 25.0
            else:
                gap_score += 15.0

        # 3. Insecure Transport / Missing Modern Protocol Headers (+25)
        if not tech.get("https", True):
            gap_score += 25.0
        elif not tech.get("hsts", True):
            gap_score += 10.0

        # 4. Absence of Modern Reactive Frameworks (+20)
        modern_frameworks = ["react", "next.js", "vue", "nuxt", "svelte", "laravel", "angular"]
        has_modern = any(
            any(mf in str(f).lower() for mf in modern_frameworks)
            for f in (frontend + backend)
        )
        if not has_modern and (cms or frontend):
            gap_score += 20.0

        return min(100.0, max(0.0, gap_score))

    def compute_pain_signal(
        self,
        pains: list[dict[str, Any]],
        audit_metrics: dict[str, Any] | None = None,
    ) -> float:
        """
        Evaluates active business pain, conversion friction, and operational bottlenecks.
        """
        if not pains:
            return 0.0

        score = 0.0
        severity_weights = {
            "critical": 35.0,
            "high": 30.0,
            "medium": 20.0,
            "low": 10.0,
        }

        seen_pain_types = set()
        for pain in pains:
            p_type = pain.get("type", "")
            if p_type and p_type in seen_pain_types:
                continue
            if p_type:
                seen_pain_types.add(p_type)

            sev = pain.get("severity", "medium").lower()
            weight = severity_weights.get(sev, 20.0)
            raw_conf = pain.get("confidence", 1.0)
            confidence = float(raw_conf) if raw_conf is not None else 1.0
            score += weight * confidence

        return min(100.0, max(0.0, round(score, 2)))


def get_pain_and_tech_scorer() -> PainAndTechGapScorer:
    return PainAndTechGapScorer()
