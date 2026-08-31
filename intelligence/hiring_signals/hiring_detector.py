import logging
import re
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class HiringSignalDetector:
    """
    Detects hiring signals from company website pages (careers, about, job widgets).
    Identifies relevant engineering roles matching Nexidiant capabilities (Laravel, Angular, React, WordPress, DevOps).
    """

    # Keyword patterns matching target technologies and roles
    TECH_PATTERNS = {
        "laravel": re.compile(
            r"\b(laravel|php developer|backend engineer|php engineer)\b", re.IGNORECASE
        ),
        "angular": re.compile(
            r"\b(angular|angularjs|frontend engineer|frontend developer)\b",
            re.IGNORECASE,
        ),
        "react": re.compile(
            r"\b(react|reactjs|next\.js|frontend engineer)\b", re.IGNORECASE
        ),
        "wordpress": re.compile(
            r"\b(wordpress|wp developer|theme developer|plugin developer)\b",
            re.IGNORECASE,
        ),
        "devops": re.compile(
            r"\b(devops|aws|cloud engineer|site reliability|kubernetes|docker)\b",
            re.IGNORECASE,
        ),
        "fullstack": re.compile(
            r"\b(full[\s-]?stack|software engineer|lead developer)\b", re.IGNORECASE
        ),
    }

    CAREER_LINK_PATTERNS = re.compile(
        r"(careers|jobs|join-us|we-are-hiring|work-with-us|openings)", re.IGNORECASE
    )

    # Job board iframe / embed patterns
    ATS_EMBED_PATTERNS = [
        re.compile(r"greenhouse\.io", re.IGNORECASE),
        re.compile(r"lever\.co", re.IGNORECASE),
        re.compile(r"workable\.com", re.IGNORECASE),
        re.compile(r"breezy\.hr", re.IGNORECASE),
        re.compile(r"ashbyhq\.com", re.IGNORECASE),
    ]

    def analyze(self, url: str, html_content: str) -> list[dict[str, Any]]:
        """
        Analyzes HTML content for hiring indicators and relevant job roles.
        Returns a list of structured signals.
        """
        signals = []
        soup = BeautifulSoup(html_content, "html.parser")
        text = soup.get_text(separator=" ", strip=True)

        # 1. Check for ATS embeds (indicates active hiring infrastructure)
        detected_ats = []
        for script_or_iframe in soup.find_all(["script", "iframe", "a"]):
            src_or_href = (
                script_or_iframe.get("src") or script_or_iframe.get("href") or ""
            )
            for pattern in self.ATS_EMBED_PATTERNS:
                if pattern.search(src_or_href):
                    ats_name = pattern.pattern.split(r"\.")[0]
                    detected_ats.append(ats_name)

        detected_ats = list(set(detected_ats))
        if detected_ats:
            signals.append(
                {
                    "type": "hiring_ats_detected",
                    "detail": {
                        "ats_platforms": detected_ats,
                        "url": url,
                    },
                    "confidence": 0.95,
                }
            )

        # 2. Check for Career / Job links
        career_links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            anchor_text = a.get_text(strip=True)
            if self.CAREER_LINK_PATTERNS.search(
                href
            ) or self.CAREER_LINK_PATTERNS.search(anchor_text):
                career_links.append({"text": anchor_text, "href": href})

        if career_links:
            signals.append(
                {
                    "type": "career_page_detected",
                    "detail": {
                        "career_links": career_links[:3],
                        "url": url,
                    },
                    "confidence": 0.90,
                }
            )

        # 3. Match relevant tech stack hiring keywords
        matched_roles = []
        for tech, pattern in self.TECH_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                matched_roles.append(
                    {
                        "skill": tech,
                        "count": len(matches),
                        "sample": matches[0],
                    }
                )

        if matched_roles:
            signals.append(
                {
                    "type": "hiring_skill_match",
                    "detail": {
                        "matched_skills": matched_roles,
                        "url": url,
                    },
                    "confidence": 0.85,
                }
            )

        return signals


def get_hiring_detector() -> HiringSignalDetector:
    return HiringSignalDetector()
