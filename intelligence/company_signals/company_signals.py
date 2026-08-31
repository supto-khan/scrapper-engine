import logging
import re
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class CompanySignalDetector:
    """
    Extracts scale indicators, team size growth, technology churn, and company maturity signals.
    """

    SCALE_PATTERNS = [
        (
            re.compile(
                r"\b([0-9]+k?|\d+\+?)\s*(clients|customers|projects delivered|case studies)\b",
                re.IGNORECASE,
            ),
            "client_scale",
        ),
        (
            re.compile(
                r"\b(founded in\s*(?:19|20)\d{2}|est\.?\s*(?:19|20)\d{2}|established\s*(?:19|20)\d{2})\b",
                re.IGNORECASE,
            ),
            "company_age",
        ),
        (
            re.compile(
                r"\b(series [a-d]|seed round|venture backed|funded by|raised \$[0-9]+[mk]?)\b",
                re.IGNORECASE,
            ),
            "funding_round",
        ),
        (
            re.compile(
                r"\b(inc\.?\s*5000|clutch top|fastest growing|award winning)\b",
                re.IGNORECASE,
            ),
            "industry_award",
        ),
    ]

    def analyze(self, url: str, html_content: str) -> list[dict[str, Any]]:
        """
        Extracts growth, scale, and funding signals from HTML content.
        """
        signals = []
        soup = BeautifulSoup(html_content, "html.parser")
        text = soup.get_text(separator=" ", strip=True)

        for pattern, signal_subtype in self.SCALE_PATTERNS:
            matches = pattern.findall(text)
            if matches:
                sample = (
                    matches[0] if isinstance(matches[0], str) else " ".join(matches[0])
                )
                signals.append(
                    {
                        "type": f"company_signal_{signal_subtype}",
                        "detail": {
                            "subtype": signal_subtype,
                            "sample": sample,
                            "url": url,
                        },
                        "confidence": 0.80,
                    }
                )

        return signals


def get_company_signal_detector() -> CompanySignalDetector:
    return CompanySignalDetector()
