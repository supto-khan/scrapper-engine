"""
Qwen 3.5 0.8B Local AI Copy Generator
Optimized for 1 vCPU / 2 GB RAM VPS environments using llama-cpp-python (GGUF Q4_K_M).
Includes deterministic fallback to the template engine if model weights are not loaded.
"""

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

# Try importing llama_cpp
try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
except ImportError:
    LLAMA_AVAILABLE = False


def clean_and_parse_ai_output(raw_text: str, company_name: str, step: int = 1) -> dict[str, str] | None:
    """
    Strips internal thinking tokens (<think>...</think>), cleans markdown artifacts,
    and reliably parses the Subject and Body from AI output.
    Returns None if output or body is empty so caller can safely fall back to templates.
    """
    if not raw_text:
        return None

    # 1. Strip <think>...</think> reasoning blocks (even unclosed ones if output was truncated)
    cleaned = re.sub(r"<think>.*?(?:</think>|$)", "", raw_text, flags=re.DOTALL).strip()
    if not cleaned:
        return None

    # 2. Strip code block wrappers if model wrapped the email in ``` or ```markdown
    cleaned = re.sub(r"^```[a-zA-Z]*\n", "", cleaned)
    cleaned = re.sub(r"\n```$", "", cleaned).strip()

    # 3. Default subjects
    default_subj = (
        f"Re: Scaling {company_name}'s web platform"
        if step == 2
        else f"Scaling {company_name}'s web platform"
    )
    subject = default_subj
    body = cleaned

    # 4. Look for SUBJECT: / Subject: / **Subject:** / Subject Line: headers
    subject_pattern = re.compile(
        r"^(?:\s*(?:\*\*|__)?\s*subject(?:\s*line)?\s*(?:\*\*|__)?\s*[:\-])\s*(.*)$",
        re.IGNORECASE | re.MULTILINE,
    )
    match = subject_pattern.search(cleaned)

    if match:
        extracted_subject = match.group(1).strip()
        # Clean quotes, markdown bolding around subject
        extracted_subject = re.sub(r"^[\"\'\*\_]+|[\"\'\*\_]+$", "", extracted_subject).strip()
        if extracted_subject:
            subject = extracted_subject

        # Email body is everything after the subject line
        body_part = cleaned[match.end():].strip()
        body = body_part
    else:
        # Fallback: check if the first line looks like a subject without prefix
        lines = cleaned.split("\n", 1)
        if len(lines) > 1 and len(lines[0]) < 80 and not lines[0].lower().startswith(("hi ", "hello ", "hey ", "dear ")):
            first_line = lines[0].strip()
            # If it's a short title-like line, use it
            if any(term in first_line.lower() for term in ["moderniz", "scaling", "tech", "platform", "frontend", "engineering", "question", "audit"]):
                subject = re.sub(r"^[\"\'\*\_]+|[\"\'\*\_]+$", "", first_line).strip()
                body = lines[1].strip()

    # 5. Clean up any model-hallucinated signature blocks (as copy generator appends canonical CAN-SPAM signature)
    body = re.split(r"\n+(?:---\s*\n)?(?:Best|Regards|Sincerely|Thanks|Cheers|Warmly),?\s*\n", body, flags=re.IGNORECASE)[0].strip()

    if not body:
        return None

    return {"subject": subject, "body": body}


class QwenCopyClient:
    def __init__(
        self,
        model_path: str | None = None,
        n_ctx: int = 1024,
        n_threads: int = 1,
    ):
        self.model_path = model_path or os.getenv(
            "QWEN_MODEL_PATH",
            os.path.expanduser("~/.cache/models/qwen3.5-0.8b-instruct-q4_k_m.gguf"),
        )
        self.n_ctx = n_ctx
        self.n_threads = n_threads
        self.llm = None
        self._initialize_model()

    def _initialize_model(self):
        if not LLAMA_AVAILABLE:
            logger.info("llama-cpp-python not installed; running in template fallback mode.")
            return

        if not os.path.exists(self.model_path):
            logger.info(f"Qwen model file not found at {self.model_path}; running in template fallback mode.")
            return

        try:
            logger.info(f"Loading Qwen3.5-0.8B GGUF from {self.model_path} (threads={self.n_threads}, ctx={self.n_ctx})...")
            self.llm = Llama(
                model_path=self.model_path,
                n_ctx=self.n_ctx,
                n_threads=self.n_threads,
                verbose=False,
            )
            logger.info("Qwen3.5-0.8B loaded successfully into memory.")
        except Exception as e:
            logger.warning(f"Failed to load Qwen model: {e}. Falling back to template mode.")
            self.llm = None

    def is_active(self) -> bool:
        return self.llm is not None

    def generate_email_body(
        self,
        company_name: str,
        domain: str,
        contact_name: str,
        segment: str,
        tech_evidence: str,
        pain_point: str,
        step: int = 1,
    ) -> dict[str, str] | None:
        """
        Generates personalized subject and body for Step 1 (Initial Hook) or Step 2 (3-Day Follow-Up).
        Returns None if model is unavailable.
        """
        if not self.is_active():
            return None

        if step == 1:
            if segment == "new_website_creation":
                system_prompt = (
                    "You are a friendly, direct digital partner writing brief, high-reply cold emails to local business owners who have good Google reviews but NO website.\n"
                    "Follow the exact style of the example: under 55 words, conversational, direct (you/your), complimentary, and ending with a low-friction question."
                )
                few_shot_user = (
                    "Business: Cedar Plumbing\n"
                    "Contact: Tom\n"
                    "Reputation: 35 Google reviews (4.8 stars)\n"
                    "Core Gap: no mobile website for customers searching online\n\n"
                    "Write the brief cold email."
                )
                few_shot_assistant = (
                    "SUBJECT: quick question for Cedar Plumbing\n\n"
                    "Hi Tom,\n\n"
                    "Saw your 35 Google reviews and 4.8-star rating—solid reputation in the community.\n\n"
                    "I noticed customers finding you on mobile don't have a direct way to view your services or request an estimate online.\n\n"
                    "Would you be open to seeing a quick 2-minute mobile concept we sketched for Cedar Plumbing?"
                )
                actual_user = (
                    f"Business: {company_name}\n"
                    f"Contact: {contact_name}\n"
                    f"Reputation: {tech_evidence}\n"
                    f"Core Gap: {pain_point}\n\n"
                    "Write the brief cold email."
                )
            elif segment in ["speed_optimization", "turnkey_modernization_overhaul"]:
                system_prompt = (
                    "You are an executive web performance specialist writing brief, high-reply cold emails to decision makers.\n"
                    "Follow the exact style of the example: under 55 words, direct (you/your), citing the concrete latency metric and bounce impact, ending with a low-friction question."
                )
                few_shot_user = (
                    "Company: Apex Dental\n"
                    "Contact: Dr. Evans\n"
                    "Evidence: mobile LCP latency of 4.1s (PageSpeed 36/100)\n"
                    "Bottleneck: mobile patients dropping off before booking form finishes loading\n\n"
                    "Write the brief cold email."
                )
                few_shot_assistant = (
                    "SUBJECT: quick question on Apex Dental's mobile load speed\n\n"
                    "Hi Dr. Evans,\n\n"
                    "Took a look at Apex Dental's mobile experience and noticed the page takes 4.1 seconds to load (Google PageSpeed 36/100).\n\n"
                    "When mobile pages take over 3 seconds, a large share of visitors drop off before your booking form finishes rendering.\n\n"
                    "Would you be open to seeing a quick 2-minute breakdown of the 2 bottlenecks slowing it down?"
                )
                actual_user = (
                    f"Company: {company_name} ({domain})\n"
                    f"Contact: {contact_name}\n"
                    f"Evidence: {tech_evidence}\n"
                    f"Bottleneck: {pain_point}\n\n"
                    "Write the brief cold email."
                )
            elif segment == "laravel_modernization":
                system_prompt = (
                    "You are a senior full-stack architect writing brief, high-reply cold emails to engineering leaders.\n"
                    "Follow the exact style of the example: under 55 words, direct (you/your), referencing tech stack debt, ending with a low-friction question."
                )
                few_shot_user = (
                    "Company: FleetFlow Logistics\n"
                    "Contact: David\n"
                    "Evidence: legacy WordPress and PHP 7.4 backend\n"
                    "Bottleneck: slow database queries and heavy plugin maintenance during peak traffic\n\n"
                    "Write the brief cold email."
                )
                few_shot_assistant = (
                    "SUBJECT: quick question on FleetFlow Logistics's backend\n\n"
                    "Hi David,\n\n"
                    "Noticed FleetFlow Logistics's platform is currently running on a legacy WordPress and PHP 7.4 backend.\n\n"
                    "Teams on older monolithic setups usually run into slow database queries and high maintenance overhead as traffic grows.\n\n"
                    "Would you be open to seeing a quick breakdown of how similar platforms modernised to a clean Laravel API with zero downtime?"
                )
                actual_user = (
                    f"Company: {company_name} ({domain})\n"
                    f"Contact: {contact_name}\n"
                    f"Evidence: {tech_evidence}\n"
                    f"Bottleneck: {pain_point}\n\n"
                    "Write the brief cold email."
                )
            elif segment == "frontend_modernization":
                system_prompt = (
                    "You are a frontend performance architect writing brief, high-reply cold emails to tech leaders.\n"
                    "Follow the exact style of the example: under 55 words, direct (you/your), referencing client-side scripts, ending with a low-friction question."
                )
                few_shot_user = (
                    "Company: TalentPro\n"
                    "Contact: Sarah\n"
                    "Evidence: legacy jQuery and 3.2MB unminified JS bundle\n"
                    "Bottleneck: delayed UI rendering and slow component development velocity\n\n"
                    "Write the brief cold email."
                )
                few_shot_assistant = (
                    "SUBJECT: quick question on TalentPro's frontend\n\n"
                    "Hi Sarah,\n\n"
                    "Noticed TalentPro's client-side experience is loading multiple legacy script bundles totaling over 3MB.\n\n"
                    "Cutting that payload with modern reactive components usually speeds up page rendering by 50% and makes rolling out new UI features much faster.\n\n"
                    "Would you be open to seeing a quick 2-minute audit of the scripts that can be streamlined?"
                )
                actual_user = (
                    f"Company: {company_name} ({domain})\n"
                    f"Contact: {contact_name}\n"
                    f"Evidence: {tech_evidence}\n"
                    f"Bottleneck: {pain_point}\n\n"
                    "Write the brief cold email."
                )
            elif segment == "staff_augmentation":
                system_prompt = (
                    "You are an engineering partner writing brief, high-reply cold emails to tech leaders hiring developers.\n"
                    "Follow the exact style of the example: under 50 words, direct (you/your), referencing open roles, ending with a low-friction question."
                )
                few_shot_user = (
                    "Company: CloudSync\n"
                    "Contact: Alex\n"
                    "Evidence: hiring senior full-stack Python and React engineers\n"
                    "Bottleneck: sprint deliverables delayed while searching for senior engineering talent\n\n"
                    "Write the brief cold email."
                )
                few_shot_assistant = (
                    "SUBJECT: quick question regarding CloudSync's engineering sprint\n\n"
                    "Hi Alex,\n\n"
                    "Saw that CloudSync is actively hiring senior full-stack developers.\n\n"
                    "If your upcoming sprint deliverables are waiting on engineering bandwidth, we have senior full-stack engineers who can embed directly into your sprint this week with zero recruiter fees.\n\n"
                    "Would you be open to seeing 2 profiles to see if either could help unblock your roadmap?"
                )
                actual_user = (
                    f"Company: {company_name}\n"
                    f"Contact: {contact_name}\n"
                    f"Evidence: {tech_evidence}\n"
                    f"Bottleneck: {pain_point}\n\n"
                    "Write the brief cold email."
                )
            else:
                system_prompt = (
                    "You are an executive technology consultant writing brief, high-reply B2B cold emails.\n"
                    "Follow the exact style of the example: under 55 words, direct (you/your), mentioning technical signals, ending with a low-friction question."
                )
                few_shot_user = (
                    "Company: Vantage Media\n"
                    "Contact: Chris\n"
                    "Evidence: legacy web stack\n"
                    "Bottleneck: high infrastructure maintenance overhead\n\n"
                    "Write the brief cold email."
                )
                few_shot_assistant = (
                    "SUBJECT: quick question on Vantage Media's web platform\n\n"
                    "Hi Chris,\n\n"
                    "Took a quick look at Vantage Media's platform and noticed a few opportunities to streamline maintenance and infrastructure overhead.\n\n"
                    "Would you be open to seeing a quick 2-minute audit we put together showing how similar teams improved delivery velocity?"
                )
                actual_user = (
                    f"Company: {company_name} ({domain})\n"
                    f"Contact: {contact_name}\n"
                    f"Evidence: {tech_evidence}\n"
                    f"Bottleneck: {pain_point}\n\n"
                    "Write the brief cold email."
                )

            full_prompt = (
                f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
                f"<|im_start|>user\n{few_shot_user}<|im_end|>\n"
                f"<|im_start|>assistant\n{few_shot_assistant}<|im_end|>\n"
                f"<|im_start|>user\n{actual_user}<|im_end|>\n"
                f"<|im_start|>assistant\n"
            )
        else:
            # Step 2: 3-Day Follow-up (Reply-Driven, Ultra Short, Zero Pressure)
            system_prompt = (
                "You write brief, polite, zero-pressure 3-day follow-up emails. Maximum 30 words total.\n"
                "Follow the exact style of the example."
            )
            few_shot_user = (
                "Company: Cedar Plumbing\n"
                "Contact: Tom\n"
                "Context: sent note earlier this week about 2-minute mobile concept\n\n"
                "Write the 2-sentence follow-up email."
            )
            few_shot_assistant = (
                "SUBJECT: Re: quick question for Cedar Plumbing\n\n"
                "Hi Tom,\n\n"
                "Following up on my note from earlier this week—wanted to see if you had a chance to check out the quick mobile concept we sketched for Cedar Plumbing?\n\n"
                "No pressure at all if the timing isn't right."
            )
            actual_user = (
                f"Company: {company_name}\n"
                f"Contact: {contact_name}\n"
                f"Context: sent note earlier this week about {tech_evidence}\n\n"
                "Write the 2-sentence follow-up email."
            )
            full_prompt = (
                f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
                f"<|im_start|>user\n{few_shot_user}<|im_end|>\n"
                f"<|im_start|>assistant\n{few_shot_assistant}<|im_end|>\n"
                f"<|im_start|>user\n{actual_user}<|im_end|>\n"
                f"<|im_start|>assistant\n"
            )

        try:
            if hasattr(self.llm, "reset"):
                self.llm.reset()
            output = self.llm(
                full_prompt,
                max_tokens=220,
                temperature=0.5,
                stop=["<|im_end|>", "<|im_start|>"],
            )
            raw_text = output["choices"][0]["text"].strip()
            res = clean_and_parse_ai_output(raw_text, company_name=company_name, step=step)
            if not res or not res.get("body"):
                logger.warning(f"Qwen produced invalid output for {company_name}; falling back to template.")
                return None
            return res
        except Exception as e:
            logger.error(f"Error during Qwen inference: {e}")
            return None


# Global singleton instance
_qwen_instance: QwenCopyClient | None = None


def get_qwen_client() -> QwenCopyClient:
    global _qwen_instance
    if _qwen_instance is None:
        _qwen_instance = QwenCopyClient()
    return _qwen_instance
