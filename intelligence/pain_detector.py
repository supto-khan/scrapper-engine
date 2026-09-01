import logging
from typing import Any

logger = logging.getLogger(__name__)


class PainDetector:
    """
    Translates detected technologies, 360° deep website audit metrics, and hiring signals
    into actionable business pain points.
    """

    def detect_pains(
        self,
        tech_fingerprint: dict[str, Any] | None = None,
        audit_metrics: dict[str, Any] | None = None,
        signals: list[dict[str, Any]] | None = None,
        deep_audit: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Evaluates company intelligence and outputs a list of structured pain points:
        - legacy_jquery (security vulnerability & legacy frontend maintenance)
        - outdated_wordpress (maintenance debt, plugin vulnerabilities)
        - insecure_transport (missing HTTPS or HSTS)
        - slow_performance (LCP > 2.5s or high TTFB > 800ms)
        - subpage_speed_discrepancy (inner pages taking significantly longer)
        - missing_mobile_tel_link (phone number not 1-tap clickable)
        - high_form_friction (form with too many fields or missing autocomplete)
        - missing_local_schema (lost Google rich search visibility)
        - broken_social_cards (blank preview cards on WhatsApp/iMessage)
        - email_deliverability_risk (missing SPF/DMARC causing quote replies to go to spam)
        - hiring_bottleneck (active engineering roles indicating capacity shortage)
        """
        pains = []
        tech = tech_fingerprint or {}
        audit = audit_metrics or {}
        sig_list = signals or []
        deep = dict(deep_audit) if deep_audit else {}

        if audit:
            if not deep.get("speed_metrics"):
                deep["speed_metrics"] = {
                    "homepage_speed_ms": audit.get("lcp_ms", 0),
                    "homepage_speed_s": round(audit.get("lcp_ms", 0) / 1000, 1),
                    "homepage_ttfb_ms": audit.get("ttfb_ms", 0),
                    "backend_db_bottleneck": audit.get("ttfb_ms", 0) > 800,
                }
            if not deep.get("lighthouse"):
                deep["lighthouse"] = audit

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
                            "or migration to modern decoupled architecture (e.g. Next.js / React / Modern CMS)."
                        )
                    ),
                    "evidence": wp_info or {"cms": cms},
                    "confidence": 0.95 if is_old_wp else 0.85,
                }
            )

        # 3. Check HTTPS & Security
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

        # 4. Check 360° Deep Speed & Multi-Page Discrepancy
        speed = deep.get("speed_metrics", {})
        if speed.get("speed_discrepancy_detected"):
            pains.append(
                {
                    "type": "subpage_speed_discrepancy",
                    "severity": "high",
                    "title": f"Inner Page Latency Friction ({speed.get('slowest_subpage_path')} loads in {speed.get('slowest_subpage_speed_s')}s)",
                    "description": (
                        f"While homepage loads in {speed.get('homepage_speed_s')}s, inner conversion pages like "
                        f"{speed.get('slowest_subpage_path')} take {speed.get('slowest_subpage_speed_s')}s, causing major mobile visitor drop-offs."
                    ),
                    "evidence": speed,
                    "confidence": 0.95,
                }
            )
        elif speed.get("homepage_speed_ms", 0) > 3000:
            pains.append(
                {
                    "type": "slow_website_speed",
                    "severity": "high",
                    "title": f"Slow Mobile Load Speed ({speed.get('homepage_speed_s')}s)",
                    "description": "Initial mobile page load exceeds 3.0s threshold, impacting conversion rates and Google Core Web Vitals ranking.",
                    "evidence": speed,
                    "confidence": 0.90,
                }
            )

        if speed.get("backend_db_bottleneck"):
            pains.append(
                {
                    "type": "slow_backend_ttfb",
                    "severity": "medium",
                    "title": f"Server & Database Latency ({speed.get('homepage_ttfb_ms')}ms TTFB)",
                    "description": "Server takes over 1.2s to respond before serving assets, indicating unoptimized database queries or missing edge caching.",
                    "evidence": speed,
                    "confidence": 0.85,
                }
            )

        # 5. Check 360° Mobile CRO & Calling Friction
        cro = deep.get("conversion_metrics", {})
        if cro.get("missing_mobile_tel_link"):
            pains.append(
                {
                    "type": "missing_mobile_tel_link",
                    "severity": "high",
                    "title": "Non-Clickable Mobile Phone Number",
                    "description": "Phone number is displayed as plain unlinked text without a 1-tap 'tel:' call link, preventing mobile visitors from calling directly.",
                    "evidence": cro,
                    "confidence": 0.95,
                }
            )

        if cro.get("high_form_friction"):
            pains.append(
                {
                    "type": "high_form_friction",
                    "severity": "medium",
                    "title": f"High Form Friction ({cro.get('max_form_inputs')} input fields)",
                    "description": f"Lead form requires {cro.get('max_form_inputs')} fields without browser autocomplete, increasing friction and inquiry abandonment.",
                    "evidence": cro,
                    "confidence": 0.85,
                }
            )

        # 6. Check 360° Local SEO & Social Sharing Cards
        seo = deep.get("seo_metrics", {})
        if not seo.get("has_local_business_schema") and not seo.get("has_json_ld_schema"):
            pains.append(
                {
                    "type": "missing_local_schema",
                    "severity": "medium",
                    "title": "Missing Google LocalBusiness Schema Markup",
                    "description": "Website lacks JSON-LD structured data schema, preventing Google from displaying rich review stars and opening hours in search.",
                    "evidence": seo,
                    "confidence": 0.90,
                }
            )

        if seo.get("broken_social_cards"):
            pains.append(
                {
                    "type": "broken_social_opengraph",
                    "severity": "low",
                    "title": "Missing OpenGraph Social Sharing Cards",
                    "description": "Website lacks og:image and og:title tags, causing shared links on WhatsApp, iMessage, and LinkedIn to show as blank gray boxes.",
                    "evidence": seo,
                    "confidence": 0.85,
                }
            )

        # 7. Check 360° DNS & Email Deliverability (Spam Risk)
        dns_m = deep.get("dns_email_metrics", {})
        if dns_m.get("email_deliverability_risk"):
            missing_records = []
            if not dns_m.get("has_spf_record"):
                missing_records.append("SPF")
            if not dns_m.get("has_dmarc_record"):
                missing_records.append("DMARC")

            pains.append(
                {
                    "type": "dns_email_deliverability_risk",
                    "severity": "high",
                    "title": f"DNS Email Deliverability Risk (Missing {', '.join(missing_records)})",
                    "description": (
                        f"Domain is missing {', '.join(missing_records)} DNS authentication records. "
                        "Customer inquiry replies from company domain are at high risk of landing in spam folders."
                    ),
                    "evidence": dns_m,
                    "confidence": 0.95,
                }
            )

        # 8. Check Exposed CMS Endpoints
        sec = deep.get("security_metrics", {})
        if sec.get("exposed_wp_users"):
            pains.append(
                {
                    "type": "exposed_cms_security_risk",
                    "severity": "critical",
                    "title": "Exposed WordPress REST API User Enumeration",
                    "description": "Public /wp-json/wp/v2/users endpoint reveals administrator usernames, exposing the site to automated brute-force attacks.",
                    "evidence": sec,
                    "confidence": 1.0,
                }
            )

        # 9. Check Hiring Signals (Engineering Capacity Shortage)
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

        # 10. Check SSL Certificate Expiry
        if sec.get("ssl_cert_expiring_soon"):
            days_left = sec.get("ssl_cert_days_remaining", 0)
            severity = "critical" if days_left < 14 else "high"
            pains.append(
                {
                    "type": "ssl_cert_expiring_soon",
                    "severity": severity,
                    "title": f"SSL Certificate Expiring in {days_left} Days",
                    "description": (
                        f"SSL certificate expires on {sec.get('ssl_cert_expiry_date', 'unknown')} "
                        f"({days_left} days remaining). Once expired, visitors will see browser security warnings "
                        "and Google will flag the site as 'Not Secure'."
                    ),
                    "evidence": sec,
                    "confidence": 1.0,
                }
            )
        elif sec.get("ssl_cert_checked") and not sec.get("ssl_cert_valid"):
            pains.append(
                {
                    "type": "ssl_cert_invalid",
                    "severity": "critical",
                    "title": "Invalid or Missing SSL Certificate",
                    "description": "SSL certificate validation failed — visitors may see browser security warnings.",
                    "evidence": sec,
                    "confidence": 0.95,
                }
            )

        # 11. Check Broken Internal Links (404s)
        link_health = deep.get("link_health", {})
        broken_count = link_health.get("broken_links_count", 0)
        if broken_count > 0:
            broken_urls = link_health.get("broken_link_urls", [])
            pains.append(
                {
                    "type": "broken_internal_links",
                    "severity": "high" if broken_count >= 3 else "medium",
                    "title": f"{broken_count} Broken Internal Links (404 Errors)",
                    "description": (
                        f"Website has {broken_count} broken internal links returning 404 errors. "
                        "These dead pages frustrate visitors and damage SEO crawl authority."
                    ),
                    "evidence": {"broken_count": broken_count, "sample_urls": broken_urls[:3]},
                    "confidence": 1.0,
                }
            )

        # 12. Check Image Optimization Issues
        img_opt = deep.get("image_optimization", {})
        if img_opt.get("has_image_optimization_issues"):
            issues = []
            if img_opt.get("images_non_modern_format", 0) > 2:
                issues.append(f"{img_opt['images_non_modern_format']} images in legacy PNG/JPG format (should be WebP)")
            if img_opt.get("images_missing_lazy_load", 0) > 2:
                issues.append(f"{img_opt['images_missing_lazy_load']} images without lazy loading")
            if img_opt.get("images_missing_alt_text", 0) > 2:
                issues.append(f"{img_opt['images_missing_alt_text']} images missing alt text (accessibility)")

            pains.append(
                {
                    "type": "unoptimized_images",
                    "severity": "medium",
                    "title": f"Image Optimization Issues ({img_opt.get('total_images', 0)} images scanned)",
                    "description": ". ".join(issues) + ". Unoptimized images increase load time and hurt mobile Core Web Vitals.",
                    "evidence": img_opt,
                    "confidence": 0.90,
                }
            )

        # 13. Check Google Lighthouse Performance Score
        lighthouse = deep.get("lighthouse_metrics", {})
        if lighthouse.get("available"):
            perf_score = lighthouse.get("performance_score")
            if perf_score is not None and perf_score < 70:
                severity = "high" if perf_score < 50 else "medium"
                lcp_ms = lighthouse.get("lcp_ms")
                lcp_text = f" with LCP of {lcp_ms}ms" if lcp_ms else ""
                pains.append(
                    {
                        "type": "poor_lighthouse_score",
                        "severity": severity,
                        "title": f"Google Lighthouse Performance: {perf_score}/100",
                        "description": (
                            f"Google PageSpeed Insights benchmarked the mobile site at {perf_score}/100{lcp_text}. "
                            "Scores below 70 directly impact Google search rankings and mobile conversion rates."
                        ),
                        "evidence": lighthouse,
                        "confidence": 1.0,
                    }
                )

        return pains


def get_pain_detector() -> PainDetector:
    return PainDetector()

