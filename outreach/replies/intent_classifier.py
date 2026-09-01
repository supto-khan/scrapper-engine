"""
Nexidant Signal Engine — Inbound Reply Intent Classifier
Classifies incoming email responses into high-confidence buyer intent categories:
1. positive_interest (meeting request, pricing inquiry, curiosity)
2. not_interested (unsubscribe, removal, polite decline)
3. out_of_office (automated autoresponder, holiday, parental leave)
4. neutral_question (vendor question, forwarding note)
5. unknown
"""

import logging
import re
from typing import Any, Tuple

logger = logging.getLogger(__name__)

# ─── Regular Expression & Keyword Patterns ──────────────────────────────────

POSITIVE_PATTERNS = [
    r"\b(let'?s\s+(talk|chat|connect|discuss|meet|schedule|call|jump|hop))\b",
    r"\b((hop|jump)\s+on\s+(a\s+)?(quick\s+)?call)\b",
    r"\b(interested|sounds\s+(good|great|interesting|like\s+a\s+plan)|tell\s+me\s+more|send\s+(more\s+)?(info|details|pricing|deck))\b",
    r"\b(how\s+much|what'?s\s+(the\s+)?(cost|price|pricing|rate))\b",
    r"\b(calendar|calendly|schedule|availability|when\s+are\s+you\s+free|free\s+this\s+(week|monday|tuesday|wednesday|thursday|friday))\b",
    r"\b(can\s+we\s+(talk|chat|connect|meet|set\s+up|schedule)|book\s+a\s+time|give\s+me\s+a\s+call|reach\s+me\s+at)\b",
    r"\b(yes|sure|definitely|absolutely|happy\s+to\s+chat|love\s+to\s+connect)\b",
    r"\b(forwarding\s+to\s+our\s+(cto|vp|head|lead|engineering|dev|team|founder))\b",
]

NEGATIVE_PATTERNS = [
    r"\b(unsubscribe|opt\s*out|remove\s+(me|my\s+email)|stop\s+(emailing|contacting))\b",
    r"\b(not\s+interested|no\s+thanks|pass|do\s+not\s+contact|leave\s+me\s+alone)\b",
    r"\b(we\s+have\s+an\s+in-?house\s+team|we\s+already\s+have|we\s+don'?t\s+need)\b",
    r"\b(wrong\s+person|no\s+budget|not\s+looking|not\s+hiring)\b",
    r"\b(spam|cease\s+and\s+desist|take\s+me\s+off\s+your\s+list)\b",
]

OUT_OF_OFFICE_PATTERNS = [
    r"\b(out\s+of\s+(the\s+)?office|away\s+from\s+(my\s+)?desk|on\s+annual\s+leave)\b",
    r"\b(auto-?reply|automatic\s+reply|automated\s+response)\b",
    r"\b(maternity\s+leave|paternity\s+leave|medical\s+leave|on\s+vacation|on\s+holiday)\b",
    r"\b(returning\s+(on|back)|back\s+in\s+the\s+office\s+on)\b",
    r"\b(limited\s+access\s+to\s+email|i\s+will\s+respond\s+upon\s+my\s+return)\b",
]

NEUTRAL_PATTERNS = [
    r"\b(who\s+is\s+this|where\s+did\s+you\s+get|how\s+did\s+you\s+find)\b",
    r"\b(are\s+you\s+an\s+agency|what\s+services\s+do\s+you\s+provide)\b",
]


class ReplyIntentClassifier:
    """
    Classifies buyer intent from email subject and body content.
    """

    def classify(self, subject: str, body_text: str) -> dict[str, Any]:
        """
        Analyzes the reply text and returns:
        {
            "intent": "positive_interest" | "not_interested" | "out_of_office" | "neutral_question" | "unknown",
            "confidence": 0.0 - 1.0,
            "matched_pattern": str or None,
            "snippet": str
        }
        """
        combined_text = f"{subject}\n{body_text}".strip().lower()
        cleaned_body = body_text.strip()[:400]

        # 1. Out of Office Check (highest priority for auto-replies)
        for pat in OUT_OF_OFFICE_PATTERNS:
            match = re.search(pat, combined_text, re.IGNORECASE)
            if match:
                return {
                    "intent": "out_of_office",
                    "confidence": 0.95,
                    "matched_pattern": match.group(0),
                    "snippet": cleaned_body,
                }

        # 2. Negative / Unsubscribe Check (critical for CAN-SPAM compliance)
        for pat in NEGATIVE_PATTERNS:
            match = re.search(pat, combined_text, re.IGNORECASE)
            if match:
                return {
                    "intent": "not_interested",
                    "confidence": 0.92,
                    "matched_pattern": match.group(0),
                    "snippet": cleaned_body,
                }

        # 3. Positive Interest Check (sales opportunities)
        for pat in POSITIVE_PATTERNS:
            match = re.search(pat, combined_text, re.IGNORECASE)
            if match:
                return {
                    "intent": "positive_interest",
                    "confidence": 0.90,
                    "matched_pattern": match.group(0),
                    "snippet": cleaned_body,
                }

        # 4. Neutral Questions
        for pat in NEUTRAL_PATTERNS:
            match = re.search(pat, combined_text, re.IGNORECASE)
            if match:
                return {
                    "intent": "neutral_question",
                    "confidence": 0.75,
                    "matched_pattern": match.group(0),
                    "snippet": cleaned_body,
                }

        # 5. Short positive fallback (e.g. single word "Interested", "Yes", "Let's do it")
        short_words = set(re.findall(r"\w+", combined_text))
        if short_words & {"yes", "sure", "interested", "yep", "ok", "okay"}:
            return {
                "intent": "positive_interest",
                "confidence": 0.80,
                "matched_pattern": "short_affirmative_word",
                "snippet": cleaned_body,
            }

        return {
            "intent": "unknown",
            "confidence": 0.50,
            "matched_pattern": None,
            "snippet": cleaned_body,
        }


# ─── Module Accessor ──────────────────────────────────────────────────────

_classifier_instance: ReplyIntentClassifier | None = None


def get_intent_classifier() -> ReplyIntentClassifier:
    global _classifier_instance
    if _classifier_instance is None:
        _classifier_instance = ReplyIntentClassifier()
    return _classifier_instance
