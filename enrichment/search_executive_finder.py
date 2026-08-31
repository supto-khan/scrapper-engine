import logging
import re
from typing import Any
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class SearchExecutiveFinder:
    """
    Zero-cost Executive Decision Maker Discovery via Search Engine Parsing.
    Discovers Founder / CEO / Owner / CTO names for small-to-mid companies
    when proprietary database quotas (Apollo/Hunter) are exhausted.
    """

    EXECUTIVE_TITLES = [
        "Founder",
        "Co-Founder",
        "CEO",
        "Owner",
        "President",
        "Managing Director",
        "CTO",
        "VP of Engineering",
        "Head of E-Commerce",
    ]

    NAME_REGEX = re.compile(
        r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s*[-–—:|]\s*(?:Co-Founder|Founder|CEO|Owner|President|Managing Director|CTO|Principal)",
        re.IGNORECASE,
    )

    def __init__(self, timeout: int = 6):
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

    def find_executives(self, domain: str, company_name: str | None = None) -> list[dict[str, Any]]:
        """
        Discovers executive decision makers for a target domain via DuckDuckGo HTML queries.
        """
        clean_domain = domain.lower().replace("http://", "").replace("https://", "").strip().strip("/")
        name_query = company_name or clean_domain.split(".")[0].capitalize()
        query = f'"{name_query}" "{clean_domain}" (CEO OR Founder OR Owner OR "Managing Director" OR CTO)'
        
        executives = []
        try:
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                snippets = soup.find_all("a", class_="result__snippet") or soup.find_all("div", class_="result__snippet")
                
                for snip in snippets[:6]:
                    text = snip.get_text(separator=" ", strip=True)
                    match = self.NAME_REGEX.search(text)
                    if match:
                        full_name = match.group(1).strip()
                        parts = full_name.split()
                        first_name = parts[0]
                        last_name = parts[-1] if len(parts) > 1 else ""
                        
                        # Match title from snippet
                        title = "Founder / Executive"
                        for t in self.EXECUTIVE_TITLES:
                            if re.search(rf"\b{re.escape(t)}\b", text, re.IGNORECASE):
                                title = t
                                break

                        executives.append({
                            "full_name": full_name,
                            "first_name": first_name,
                            "last_name": last_name,
                            "title": title,
                            "role_category": "executive",
                            "source": "search_executive_finder",
                            "evidence_snippet": text[:200],
                        })
                        logger.info(f"Discovered executive {full_name} ({title}) for {domain} via search")
                        break
        except Exception as e:
            logger.debug(f"SearchExecutiveFinder failed for {domain}: {e}")

        return executives


def get_search_executive_finder() -> SearchExecutiveFinder:
    return SearchExecutiveFinder()
