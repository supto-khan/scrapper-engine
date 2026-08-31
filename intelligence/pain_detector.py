import logging
from typing import Any

logger = logging.getLogger(__name__)


class PainDetector:
    """
    Translates detected technologies, performance audit metrics, and hiring signals
    into actionable business pain points.
    """

    def detect_pains(
        self,
        tech_fingerprint: dict[str, Any] | None = None,
        audit_metrics: dict[str, Any] | None = None,
        signals: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Evaluates company intelligence and outputs a list of structured pain points:
        - legacy_jquery (security vulnerability & legacy frontend maintenance)
        - outdated_wordpress (maintenance debt, plugin vulnerabilities)
        - insecure_transport (missing HTTPS or HSTS)
        - slow_performance (LCP > 2.5s or high TTFB > 800ms)
        - hiring_bottleneck (active engineering roles indicating engineering capacity shortage)
        """
        pains = []
        tech = tech_fingerprint or {}
        audit = audit_metrics or {}
        sig_list = signals or []

        # 1. Check Legacy jQuery & Frontend Version Debts
        frontend = tech.get("frontend_stack", [])
        evidence = tech.get("evidence", {})
        jquery_info = evidence.get("jquery")
        if any("jquery" in str(item).lower() for item in frontend) or jquery_info:
            version = (jquery_info or {}).get("version", "")
            jq_debt = (jquery_info or {}).get("debt")
            is_legacy = False
            if jq_debt:
                is_legacy = jq_debt.get("is_eol") or jq_debt.get("years_outdated", 0) >= 4
            elif version:
                try:
                    major = int(version.split(".")[0])
                    if major < 3:
                        is_legacy = True
                except Exception:
                    pass
            else:
                is_legacy = True

            debt_desc = jq_debt.get("summary") if jq_debt else None
            pains.append(
                {
                    "type": "legacy_jquery",
                    "severity": "critical" if (jq_debt and jq_debt.get("cve_risk_level") == "critical") else ("high" if is_legacy else "medium"),
                    "title": "Legacy jQuery Dependency & Frontend Tech Debt",
                    "description": (
                        debt_desc or (
                            f"Website uses jQuery ({version or 'detected'}), which introduces performance bottlenecks, "
                            "DOM manipulation vulnerabilities, and lack of modern component architecture."
                        )
                    ),
                    "evidence": jquery_info or {"frontend_stack": frontend},
                    "confidence": 0.95 if is_legacy else 0.85,
                }
            )

        # 1b. Check Legacy AngularJS (EOL Debt)
        angular_info = evidence.get("angularjs")
        if any("angular" in str(item).lower() for item in frontend) or angular_info:
            ng_debt = (angular_info or {}).get("debt")
            ng_ver = (angular_info or {}).get("version", "")
            pains.append(
                {
                    "type": "legacy_angularjs_eol",
                    "severity": "critical",
                    "title": "End-of-Life AngularJS Legacy Frontend",
                    "description": (
                        (ng_debt.get("summary") if ng_debt else None) or
                        f"Website is built with AngularJS ({ng_ver or 'v1.x'}), which reached official End-of-Life in 2022 and presents urgent security and maintainability risks."
                    ),
                    "evidence": angular_info or {"frontend_stack": frontend},
                    "confidence": 0.95,
                }
            )

        # 1c. Check Legacy Bootstrap Debt
        bs_info = evidence.get("bootstrap")
        if bs_info:
            bs_debt = bs_info.get("debt")
            if bs_debt and (bs_debt.get("is_eol") or bs_debt.get("years_outdated", 0) >= 5):
                pains.append(
                    {
                        "type": "legacy_bootstrap_debt",
                        "severity": "medium",
                        "title": "Outdated UI Framework (Legacy Bootstrap)",
                        "description": bs_debt.get("summary") or f"Website uses outdated Bootstrap v{bs_info.get('version')}, needing Tailwind CSS / modern UI modernization.",
                        "evidence": bs_info,
                        "confidence": 0.85,
                    }
                )

        # 2. Check WordPress & Version
        cms = tech.get("cms") or ""
        wp_info = evidence.get("wordpress")
        if "wordpress" in cms.lower() or wp_info:
            wp_version = (wp_info or {}).get("version", "")
            wp_debt = (wp_info or {}).get("debt")
            is_old_wp = False
            if wp_debt:
                is_old_wp = wp_debt.get("is_eol") or wp_debt.get("years_outdated", 0) >= 2
            elif wp_version:
                try:
                    major_minor = float(".".join(wp_version.split(".")[:2]))
                    if major_minor < 6.0:
                        is_old_wp = True
                except Exception:
                    pass

            wp_desc = wp_debt.get("summary") if wp_debt else None
            pains.append(
                {
                    "type": "outdated_wordpress"
                    if is_old_wp
                    else "wordpress_maintenance_debt",
                    "severity": "high" if is_old_wp else "medium",
                    "title": f"WordPress {'Outdated Version' if is_old_wp else 'Architecture Debt'}",
                    "description": (
                        wp_desc or (
                            f"WordPress site ({wp_version or 'detected'}) requires active maintenance, plugin patching, "
                            "or migration to modern decoupled architecture (e.g. Laravel / Next.js / React)."
                        )
                    ),
                    "evidence": wp_info or {"cms": cms},
                    "confidence": 0.95 if is_old_wp else 0.85,
                }
            )

        # 3. Check HTTPS & HSTS
        if not tech.get("https", True):
            pains.append(
                {
                    "type": "insecure_transport_http",
                    "severity": "critical",
                    "title": "Insecure HTTP Protocol",
                    "description": "Production domain runs on insecure HTTP, risking browser security warnings and SEO penalties.",
                    "evidence": {"https": False},
                    "confidence": 1.0,
                }
            )
        elif not tech.get("hsts", True):
            pains.append(
                {
                    "type": "missing_hsts",
                    "severity": "low",
                    "title": "Missing Strict-Transport-Security (HSTS)",
                    "description": "Domain lacks HSTS header, leaving users susceptible to protocol downgrade attacks.",
                    "evidence": {"hsts": False},
                    "confidence": 0.80,
                }
            )

        # 4. Check Performance & Core Web Vitals
        perf_score = audit.get("performance_score")
        lcp_ms = audit.get("lcp_ms")
        ttfb_ms = audit.get("ttfb_ms") or tech.get("ttfb_ms")

        if perf_score is not None and perf_score < 60:
            pains.append(
                {
                    "type": "poor_mobile_performance",
                    "severity": "high",
                    "title": f"Poor Mobile Performance Score ({perf_score}/100)",
                    "description": "Mobile performance is severely degraded, impacting user conversion rates and Google Core Web Vitals ranking.",
                    "evidence": {
                        "performance_score": perf_score,
                        "lcp_ms": lcp_ms,
                        "ttfb_ms": ttfb_ms,
                    },
                    "confidence": 0.90,
                }
            )
        elif lcp_ms is not None and lcp_ms > 2500:
            pains.append(
                {
                    "type": "slow_lcp",
                    "severity": "medium",
                    "title": f"Slow Largest Contentful Paint ({lcp_ms}ms)",
                    "description": "LCP exceeds Google's recommended 2.5s threshold, creating friction in first user experience.",
                    "evidence": {"lcp_ms": lcp_ms},
                    "confidence": 0.85,
                }
            )

        if ttfb_ms is not None and ttfb_ms > 800:
            pains.append(
                {
                    "type": "slow_backend_ttfb",
                    "severity": "medium",
                    "title": f"Slow Server Response Time ({ttfb_ms}ms TTFB)",
                    "description": "Initial server response time indicates unoptimized backend queries, lack of Redis caching, or poor hosting.",
                    "evidence": {"ttfb_ms": ttfb_ms},
                    "confidence": 0.85,
                }
            )

        # 5. Check Hiring Signals (Engineering Capacity Shortage)
        hiring_skills = []
        for s in sig_list:
            if s.get("type") == "hiring_skill_match":
                hiring_skills.extend(s.get("detail", {}).get("matched_skills", []))

        if hiring_skills:
            matched_names = [item["skill"] for item in hiring_skills]
            pains.append(
                {
                    "type": "hiring_capacity_bottleneck",
                    "severity": "high",
                    "title": f"Active Engineering Hiring ({', '.join(matched_names)})",
                    "description": (
                        f"Company has active engineering job openings for {', '.join(matched_names)}, "
                        "signaling active development budgets and potential project delivery bottlenecks."
                    ),
                    "evidence": {"matched_skills": hiring_skills},
                    "confidence": 0.90,
                }
            )

        return pains


def get_pain_detector() -> PainDetector:
    return PainDetector()
