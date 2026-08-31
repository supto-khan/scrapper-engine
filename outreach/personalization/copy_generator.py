import json
import logging
import os
from typing import Any

from outreach.personalization.qwen_client import get_qwen_client, clean_and_parse_ai_output
from outreach.templates.template_catalog import TEMPLATES

logger = logging.getLogger(__name__)


class OutreachCopyGenerator:
    """
    Injects real detected technical and business evidence into personalized outreach copy.
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
    ) -> dict[str, str]:
        """
        Generates personalized subject and body for a decision maker contact (Step 1 or Step 2 follow-up).
        """
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

        # 2. Extract Tech & Evidence Tokens
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

        # Speed Latency Evidence
        speed_parts = []
        if audit.get("performance_score"):
            speed_parts.append(
                f"a mobile performance score of {audit['performance_score']}/100"
            )
        if audit.get("lcp_ms"):
            speed_parts.append(f"Largest Contentful Paint of {audit['lcp_ms']}ms")
        elif tech.get("ttfb_ms"):
            speed_parts.append(f"server response time (TTFB) of {tech['ttfb_ms']}ms")
        speed_evidence = (
            ", ".join(speed_parts) if speed_parts else "unoptimized Core Web Vitals"
        )

        pain_point = (
            f"bottlenecks around {speed_evidence}"
            if "performance" in segment
            else f"maintaining {tech_evidence}"
        )

        # Google Maps Rating & Reviews Evidence (Strictly for Google Maps / No-Website leads)
        reviews_evidence = "great customer traction and strong local Google reviews"
        gmaps_rating = None
        gmaps_reviews = None

        if segment == "new_website_creation" or company_data.get("source") == "google_maps":
            for s in sigs:
                if s.get("signal_type") == "missing_website":
                    ev = s.get("detail") or s.get("evidence_data") or {}
                    if isinstance(ev, str):
                        try:
                            ev = json.loads(ev)
                        except Exception:
                            ev = {}
                    gmaps_rating = ev.get("rating")
                    gmaps_reviews = ev.get("review_count")
                    break

            if not gmaps_rating and opportunities:
                for opp in opportunities:
                    ev = opp.get("evidence") or {}
                    if isinstance(ev, str):
                        try:
                            ev = json.loads(ev)
                        except Exception:
                            ev = {}
                    if ev.get("rating"):
                        gmaps_rating = ev.get("rating")
                        gmaps_reviews = ev.get("review_count")
                        break

            if gmaps_rating and gmaps_reviews:
                reviews_evidence = f"an impressive {gmaps_rating}-star rating with over {gmaps_reviews}+ verified Google reviews"
            elif gmaps_rating:
                reviews_evidence = f"a strong {gmaps_rating}-star rating on Google"

        # 3. Try Qwen3.5-0.8B AI Generation First
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
            # Double-check cleaned output to guarantee no leftover reasoning tags or raw subject headers in body
            sanitized = clean_and_parse_ai_output(ai_res["body"], company_name=company_name, step=step)
            clean_body = sanitized["body"] if sanitized.get("body") else ai_res["body"].strip()
            subject = ai_res.get("subject") or sanitized.get("subject") or f"Scaling {company_name}'s web platform"

            body = f"{clean_body}\n\n{signature}"
            generator_type = "qwen3.5_0.8b"
        else:
            # 4. Fallback to High-Converting Deterministic Template
            if step == 2:
                subject = f"Re: Scaling {company_name}'s web platform"
                body = (
                    f"Hi {first_name},\n\n"
                    f"Just following up on my previous note regarding {company_name}'s {tech_evidence}.\n\n"
                    "Did you have a chance to review the modernization ideas we drafted for your team?\n\n"
                    f"{signature}"
                )
            else:
                template = TEMPLATES.get(segment) or TEMPLATES["laravel_modernization"]
                tokens = {
                    "{{first_name}}": first_name,
                    "{{company_name}}": company_name,
                    "{{reviews_evidence}}": reviews_evidence,
                    "{{tech_evidence}}": tech_evidence,
                    "{{hiring_role_evidence}}": hiring_evidence,
                    "{{speed_evidence}}": speed_evidence,
                    "{{sender_name}}": self.sender_name,
                    "{{sender_title}}": self.sender_title,
                    "{{company_name_brand}}": self.company_name,
                    "{{sender_address}}": self.sender_address,
                    "{{unsubscribe_link}}": f"{self.unsubscribe_base_url}{contact_email}",
                }

                subject = template["subject"]
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
            "generator_type": generator_type,
        }


def get_copy_generator() -> OutreachCopyGenerator:
    return OutreachCopyGenerator()
