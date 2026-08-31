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


def clean_and_parse_ai_output(raw_text: str, company_name: str, step: int = 1) -> dict[str, str]:
    """
    Strips internal thinking tokens (<think>...</think>), cleans markdown artifacts,
    and reliably parses the Subject and Body from AI output.
    """
    if not raw_text:
        default_subj = f"Re: Scaling {company_name}'s web platform" if step == 2 else f"Scaling {company_name}'s web platform"
        return {"subject": default_subj, "body": ""}

    # 1. Strip <think>...</think> reasoning blocks (even unclosed ones if output was truncated)
    cleaned = re.sub(r"<think>.*?(?:</think>|$)", "", raw_text, flags=re.DOTALL).strip()

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
            system_prompt = (
                "You are an executive engineering consultant at Nexidant writing a brief, highly personalized B2B cold email to a tech decision maker. "
                "Rules:\n"
                "1. Keep the body between 60 and 85 words.\n"
                "2. Mention the specific technical signal observed without being pushy.\n"
                "3. End with a low-friction question (e.g. 'Open to checking out the 3 quick fixes we drafted?').\n"
                "4. Do NOT include the signature block or unsubscribe link (it will be appended automatically).\n"
                "5. Return output in format: SUBJECT: <subject line>\\n\\n<email body>"
            )
            user_prompt = (
                f"Company: {company_name} ({domain})\n"
                f"Contact First Name: {contact_name}\n"
                f"Offering: {segment}\n"
                f"Technical Evidence: {tech_evidence}\n"
                f"Core Pain Point: {pain_point}\n\n"
                "Generate the initial outreach email."
            )
        else:
            # Step 2: 3-Day Follow-up
            system_prompt = (
                "You are an executive engineering consultant at Nexidant writing a polite, 2-sentence 3-day follow-up email. "
                "Rules:\n"
                "1. Maximum 40 words.\n"
                "2. Reference the previous note about their technical stack briefly.\n"
                "3. Casual, zero-pressure tone.\n"
                "4. Do NOT include the signature block or unsubscribe link.\n"
                "5. Return output in format: SUBJECT: Re: <original topic>\\n\\n<follow-up body>"
            )
            user_prompt = (
                f"Company: {company_name}\n"
                f"Contact First Name: {contact_name}\n"
                f"Technical Area: {tech_evidence}\n\n"
                "Generate the 3-day follow-up email."
            )

        full_prompt = (
            f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
            f"<|im_start|>user\n{user_prompt}<|im_end|>\n"
            f"<|im_start|>assistant\n"
        )

        try:
            output = self.llm(
                full_prompt,
                max_tokens=180,
                temperature=0.6,
                stop=["<|im_end|>", "<|im_start|>"],
            )
            raw_text = output["choices"][0]["text"].strip()
            return clean_and_parse_ai_output(raw_text, company_name=company_name, step=step)
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
