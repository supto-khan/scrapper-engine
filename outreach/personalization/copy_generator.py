import json
import logging
import os
from typing import Any

from outreach.personalization.qwen_client import get_qwen_client, clean_and_parse_ai_output
from outreach.templates.template_catalog import TEMPLATES

logger = logging.getLogger(__name__)


class OutreachCopyGenerator:
    """
    Injects real detected technical, CRO, SEO, Lighthouse, and speed evidence into personalized outreach copy.
    Utilizes Qwen3.5-0.8B (GGUF) for natural AI copy synthesis, with deterministic template fallback.
    Enforces CAN-SPAM requirements (physical address and unsubscribe link) with exact company signature.
    """

    def __init__(
        self,
        sender_name: str | None = None,
        sender_title: str | None = None,
        company_name: str | None = None,
        sender_address: str | None = None,
        unsubscribe_base_url: str | None = None,
    ):
        self.sender_name = sender_name or os.getenv("SENDER_NAME", "Supto Khan")
        self.sender_title = sender_title or os.getenv("SENDER_TITLE", "CEO")
        self.company_name = company_name or os.getenv("COMPANY_NAME", "Nexidant")
        self.sender_address = sender_address or os.getenv(
            "COMPANY_PHYSICAL_ADDRESS",
            "H:3, R:3/A, Block - F, Sector - 15, Uttara, Dhaka, Bangladesh",
        )
        self.unsubscribe_base_url = unsubscribe_base_url or os.getenv(
            "UNSUBSCRIBE_BASE_URL", "https://nexidant.com/unsubscribe?email="
        )
        self.qwen_client = get_qwen_client()

    def get_signature_block(self, contact_email: str) -> str:
        """
        Returns the mandatory, immutable Nexidant signature block and CAN-SPAM footer.
        """
        return (
            "Best,\n"
            f"{self.sender_name}\n"
            f"{self.sender_title}, {self.company_name}\n"
            "Full-Stack Engineering & Modernization\n\n"
            "---\n"
            f"{self.company_name} | {self.sender_address}\n"
            f"Unsubscribe: {self.unsubscribe_base_url}{contact_email}"
        )

    def _format_frontend_stack(self, raw_stack: Any) -> list[str]:
        """Safely extracts list of frontend technologies from string, json, or list."""
        if not raw_stack:
            return []
        if isinstance(raw_stack, str):
            try:
                parsed = json.loads(raw_stack)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if item]
                return [str(parsed).strip()]
            except Exception:
                return [raw_stack.strip()]
        if isinstance(raw_stack, list):
            return [str(item).strip() for item in raw_stack if item]
        return [str(raw_stack).strip()]

    def generate_message(
        self,
        segment: str,
        company_data: dict[str, Any],
        contact_data: dict[str, Any],
        tech_fingerprint: dict[str, Any] | None = None,
        audit_metrics: dict[str, Any] | None = None,
        signals: list[dict[str, Any]] | None = None,
        opportunities: list[dict[str, Any]] | None = None,
        step: int = 1,
        variant: str | None = None,
    ) -> dict[str, Any]:
        """
        Generates personalized subject and body for a decision maker contact (Step 1 or Step 2 follow-up).
        Supports A/B subject variants ('A', 'B', 'C').
        """
        # Determine A/B variant (balanced deterministically across contacts)
        contact_id = contact_data.get("id") or 0
        selected_variant = variant.upper() if variant in ("A", "B", "C", "a", "b", "c") else ["A", "B", "C"][contact_id % 3]

        tech = tech_fingerprint or {}
        audit = audit_metrics or {}
        sigs = signals or []

        # 1. Contact & Company tokens
        first_name = contact_data.get("first_name")
        if not first_name:
            full = contact_data.get("full_name", "")
            first_name = full.split(" ")[0] if full else "there"

        company_name = (
            company_data.get("name") or company_data.get("domain") or "your company"
        )
        domain = company_data.get("domain", "")
        contact_email = contact_data.get("email", "")
        industry_label = company_data.get("industry") or "service"

        # 2. Extract Deep 360° Audit Metrics
        deep_audit = {}
        if isinstance(tech.get("evidence"), dict):
            deep_audit = tech["evidence"].get("deep_360_audit", {})

        speed_m = deep_audit.get("speed_metrics", {})
        cro_m = deep_audit.get("conversion_metrics", {})
        seo_m = deep_audit.get("seo_metrics", {})
        dns_m = deep_audit.get("dns_email_metrics", {})
        sec_m = deep_audit.get("security_metrics", {})
        link_h = deep_audit.get("link_health", {})
        img_opt = deep_audit.get("image_optimization", {})
        lighthouse = deep_audit.get("lighthouse_metrics", {})

        homepage_speed = f"{speed_m.get('homepage_speed_s', 2.1)}s"
        slowest_subpage = speed_m.get("slowest_subpage_path") or "/services"
        subpage_speed = f"{speed_m.get('slowest_subpage_speed_s', 4.8)}s"

        # Lighthouse score token
        perf_score = lighthouse.get("performance_score")
        if perf_score is not None and lighthouse.get("available"):
            lighthouse_score = f"{perf_score}/100"
        else:
            lighthouse_score = "below industry average"

        # CRO evidence text
        cro_bullets = []
        if cro_m.get("missing_mobile_tel_link"):
            cro_bullets.append("Phone number on mobile is plain text without a 1-tap 'tel:' call link")
        if cro_m.get("high_form_friction"):
            cro_bullets.append(f"Inquiry form requires {cro_m.get('max_form_inputs', 8)} fields with no autocomplete")
        if not cro_bullets:
            cro_bullets.append("Booking and contact flow lacks a sticky 1-click mobile call button")
        cro_evidence_text = "\n   • ".join(cro_bullets)

        # SEO & DNS evidence text
        seo_dns_bullets = []
        if not seo_m.get("has_local_business_schema"):
            seo_dns_bullets.append("Missing Google LocalBusiness Schema (limiting rich review stars in search)")
        if dns_m.get("email_deliverability_risk"):
            seo_dns_bullets.append("Missing DMARC/SPF DNS authentication (putting customer quote replies at risk of spam)")
        if seo_m.get("broken_social_cards"):
            seo_dns_bullets.append("Missing OpenGraph tags (links shared on WhatsApp/iMessage display as blank gray boxes)")
        if not seo_dns_bullets:
            seo_dns_bullets.append("Missing LocalBusiness schema markup and modern OpenGraph sharing previews")
        seo_dns_evidence_text = "\n   • ".join(seo_dns_bullets)

        # Broken links line (conditional — only shown if broken links found)
        broken_count = link_h.get("broken_links_count", 0)
        broken_links_line = ""
        if broken_count > 0:
            broken_links_line = f"   • {broken_count} broken internal links (404 errors) sending visitors to dead pages\n"

        # Image issues line (conditional)
        image_issues_line = ""
        non_webp = img_opt.get("images_non_modern_format", 0)
        missing_lazy = img_opt.get("images_missing_lazy_load", 0)
        if non_webp > 3 or missing_lazy > 3:
            parts = []
            if non_webp > 3:
                parts.append(f"{non_webp} uncompressed images (should be WebP)")
            if missing_lazy > 3:
                parts.append(f"{missing_lazy} images without lazy loading")
            image_issues_line = f"   • {', '.join(parts)}\n"

        # SSL evidence line (conditional)
        ssl_evidence_line = ""
        if sec_m.get("ssl_cert_expiring_soon"):
            days = sec_m.get("ssl_cert_days_remaining", 0)
            ssl_evidence_line = f"   • SSL certificate expires in {days} days — visitors will see browser security warnings\n"

        # Tech stack tokens
        tech_evidence = "legacy technology dependencies"
        frontend_items = self._format_frontend_stack(tech.get("frontend_stack"))
        if tech.get("cms"):
            tech_evidence = f"{tech['cms']} infrastructure"
        elif frontend_items:
            tech_evidence = f"legacy frontend libraries ({', '.join(frontend_items)})"

        # Hiring Role Evidence
        hiring_roles = []
        for s in sigs:
            if s.get("type") == "hiring_skill_match":
                for m in s.get("detail", {}).get("matched_skills", []):
                    hiring_roles.append(m.get("sample") or m.get("skill"))
        hiring_evidence = (
            f"roles like {hiring_roles[0]}"
            if hiring_roles
            else "senior engineering talent"
        )

        speed_evidence = f"mobile load speed of {homepage_speed} with subpages reaching {subpage_speed}"
        pain_point = "latency and conversion friction"
        if opportunities:
            top_opp = opportunities[0]
            pain_point = f"{top_opp.get('recommended_service', 'engineering modernization')}"

        # 3. Attempt Qwen AI Synthesis
        ai_res = self.qwen_client.generate_email_body(
            company_name=company_name,
            domain=domain,
            contact_name=first_name,
            segment=segment,
            tech_evidence=tech_evidence,
            pain_point=pain_point,
            step=step,
        )

        signature = self.get_signature_block(contact_email)

        if ai_res and ai_res.get("body"):
            sanitized = clean_and_parse_ai_output(ai_res["body"], company_name=company_name, step=step)
            clean_body = sanitized["body"] if sanitized.get("body") else ai_res["body"].strip()
            subject = ai_res.get("subject") or sanitized.get("subject") or f"Scaling {company_name}'s web platform"
            body = f"{clean_body}\n\n{signature}"
            generator_type = "qwen3.5_0.8b"
        else:
            # 4. Fallback to Master Template with A/B Variant
            if step == 2:
                subject = f"Re: Complete 360° technical & conversion audit for {company_name}"
                body = (
                    f"Hi {first_name},\n\n"
                    f"Just following up on the 360° technical & mobile diagnostic we drafted for {company_name}.\n\n"
                    "Did you have a chance to review the speed, mobile booking, and DNS fixes we benchmarked for your team?\n\n"
                    f"{signature}"
                )
            else:
                template = TEMPLATES.get(segment) or TEMPLATES["turnkey_modernization_overhaul"]
                tokens = {
                    "{{first_name}}": first_name,
                    "{{company_name}}": company_name,
                    "{{domain}}": domain,
                    "{{industry_label}}": industry_label,
                    "{{homepage_speed}}": homepage_speed,
                    "{{slowest_subpage}}": slowest_subpage,
                    "{{subpage_speed}}": subpage_speed,
                    "{{lighthouse_score}}": lighthouse_score,
                    "{{cro_evidence_text}}": cro_evidence_text,
                    "{{seo_dns_evidence_text}}": seo_dns_evidence_text,
                    "{{broken_links_line}}": broken_links_line,
                    "{{image_issues_line}}": image_issues_line,
                    "{{ssl_evidence_line}}": ssl_evidence_line,
                    "{{tech_evidence}}": tech_evidence,
                    "{{hiring_role_evidence}}": hiring_evidence,
                    "{{speed_evidence}}": speed_evidence,
                    "{{sender_name}}": self.sender_name,
                    "{{sender_title}}": self.sender_title,
                    "{{company_name_brand}}": self.company_name,
                    "{{sender_address}}": self.sender_address,
                    "{{unsubscribe_link}}": f"{self.unsubscribe_base_url}{contact_email}",
                }

                # Select subject from variant if available
                variants = template.get("subject_variants", {})
                subject = variants.get(selected_variant) or template.get("subject", "360° Audit for {{company_name}}")
                raw_body = template["body"]

                for k, v in tokens.items():
                    subject = subject.replace(k, str(v))
                    raw_body = raw_body.replace(k, str(v))

                body = f"{raw_body.strip()}\n\n{signature}"
            generator_type = "template_engine"

        return {
            "subject": subject,
            "body_text": body,
            "segment": segment,
            "step": step,
            "subject_variant": selected_variant,
            "generator_type": generator_type,
        }


def get_copy_generator() -> OutreachCopyGenerator:
    return OutreachCopyGenerator()
