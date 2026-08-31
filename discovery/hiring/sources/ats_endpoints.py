import logging
import re
from typing import Any
from bs4 import BeautifulSoup
from shared import http_client

from shared.redis_client import normalize_domain

logger = logging.getLogger(__name__)


class ATSEndpointCollector:
    """
    Direct ATS Board API Scraper:
    Fetches live engineering and web development job listings from target company ATS portals:
    - Greenhouse: boards-api.greenhouse.io/v1/boards/{token}/jobs
    - Lever: api.lever.co/v0/postings/{slug}?mode=json
    - Ashby: api.ashbyhq.com/posting-api/job-board/{slug}
    - Workable: apply.workable.com/api/v1/widget/accounts/{slug}
    - SmartRecruiters: api.smartrecruiters.com/v1/companies/{slug}/postings
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout

    def fetch_greenhouse(self, token: str) -> list[dict[str, Any]]:
        results = []
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        try:
            r = http_client.get(url, impersonate="chrome124", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                for j in data.get("jobs", []):
                    title = j.get("title", "")
                    content = j.get("content", "")
                    clean_desc = BeautifulSoup(content, "html.parser").get_text(separator=" ")
                    domain = f"{token.lower().replace('-', '').replace('_', '')}.com"
                    results.append({
                        "company_name": token.capitalize(),
                        "domain": domain,
                        "website_url": f"https://{domain}",
                        "job_title": title,
                        "summary": clean_desc[:350],
                        "job_url": j.get("absolute_url", url),
                        "source": "ats_greenhouse",
                    })
        except Exception as e:
            logger.debug(f"Greenhouse fetch error for {token}: {e}")
        return results

    def fetch_lever(self, slug: str) -> list[dict[str, Any]]:
        results = []
        url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
        try:
            r = http_client.get(url, impersonate="chrome124", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                for j in data:
                    title = j.get("text", "")
                    desc = j.get("descriptionPlain", "")
                    domain = f"{slug.lower().replace('-', '').replace('_', '')}.com"
                    results.append({
                        "company_name": slug.capitalize(),
                        "domain": domain,
                        "website_url": f"https://{domain}",
                        "job_title": title,
                        "summary": desc[:350],
                        "job_url": j.get("hostedUrl", url),
                        "source": "ats_lever",
                    })
        except Exception as e:
            logger.debug(f"Lever fetch error for {slug}: {e}")
        return results

    def fetch_ashby(self, slug: str) -> list[dict[str, Any]]:
        results = []
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
        try:
            r = http_client.get(url, impersonate="chrome124", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                for j in data.get("jobs", []):
                    title = j.get("title", "")
                    desc = j.get("descriptionPlain", "")
                    domain = f"{slug.lower().replace('-', '').replace('_', '')}.com"
                    results.append({
                        "company_name": slug.capitalize(),
                        "domain": domain,
                        "website_url": f"https://{domain}",
                        "job_title": title,
                        "summary": desc[:350],
                        "job_url": j.get("jobUrl", url),
                        "source": "ats_ashby",
                    })
        except Exception as e:
            logger.debug(f"Ashby fetch error for {slug}: {e}")
        return results
