import logging
import re
from typing import Any
from bs4 import BeautifulSoup
from shared import http_client

from shared.redis_client import normalize_domain

logger = logging.getLogger(__name__)


class PublicJobAPICollector:
    """
    Collects high-intent job postings from public developer job APIs.
    Stores probabilistic confidence weights per source:
    - Remotive: 65.0
    - Arbeitnow: 60.0
    - Jobicy: 60.0
    - RemoteOK: 60.0
    """

    def __init__(self, timeout: int = 12):
        self.timeout = timeout

    def fetch_all(self, max_pages_per_api: int = 3) -> list[dict[str, Any]]:
        jobs = []
        jobs.extend(self.fetch_remotive())
        jobs.extend(self.fetch_arbeitnow(max_pages=max_pages_per_api))
        jobs.extend(self.fetch_jobicy())
        jobs.extend(self.fetch_remoteok())
        return jobs

    def fetch_remotive(self) -> list[dict[str, Any]]:
        results = []
        urls = [
            "https://remotive.com/api/remote-jobs?category=software-dev&limit=100",
            "https://remotive.com/api/remote-jobs?category=front-end&limit=60",
            "https://remotive.com/api/remote-jobs?category=devops&limit=40",
            "https://remotive.com/api/remote-jobs?category=product&limit=40",
        ]
        for url in urls:
            try:
                r = http_client.get(url, impersonate="chrome124", timeout=self.timeout)
                if r.status_code != 200:
                    continue
                data = r.json()
                for j in data.get("jobs", []):
                    company = j.get("company_name", "").strip()
                    title = j.get("title", "").strip()
                    desc = j.get("description", "")
                    job_url = j.get("url", "")
                    clean_desc = BeautifulSoup(desc, "html.parser").get_text(separator=" ")
                    domain = self._extract_domain(company, job_url, clean_desc)
                    if company and domain:
                        results.append({
                            "company_name": company,
                            "domain": domain,
                            "website_url": f"https://{domain}",
                            "job_title": title,
                            "summary": clean_desc[:350],
                            "job_url": job_url,
                            "source": "remotive_api",
                            "confidence": 65.0,
                        })
            except Exception as e:
                logger.debug(f"Remotive fetch error: {e}")
        return results

    def fetch_arbeitnow(self, max_pages: int = 3) -> list[dict[str, Any]]:
        results = []
        for page in range(1, max_pages + 1):
            url = f"https://www.arbeitnow.com/api/job-board-api?page={page}"
            try:
                r = http_client.get(url, impersonate="chrome124", timeout=self.timeout)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    if not data:
                        break
                    for j in data:
                        company = j.get("company_name", "").strip()
                        title = j.get("title", "").strip()
                        desc = j.get("description", "")
                        job_url = j.get("url", "")
                        clean_desc = BeautifulSoup(desc, "html.parser").get_text(separator=" ")
                        domain = self._extract_domain(company, job_url, clean_desc)
                        if company and domain:
                            results.append({
                                "company_name": company,
                                "domain": domain,
                                "website_url": f"https://{domain}",
                                "job_title": title,
                                "summary": clean_desc[:350],
                                "job_url": job_url,
                                "source": "arbeitnow_api",
                                "confidence": 60.0,
                            })
                else:
                    break
            except Exception as e:
                logger.debug(f"Arbeitnow fetch error on page {page}: {e}")
                break
        return results

    def fetch_jobicy(self) -> list[dict[str, Any]]:
        results = []
        tags = [
            "engineering,web-development",
            "react,javascript",
            "python,django",
            "php,laravel",
            "shopify,ecommerce",
            "full-stack,backend"
        ]
        for tag in tags:
            url = f"https://jobicy.com/api/v2/remote-jobs?count=50&tag={tag}"
            try:
                r = http_client.get(url, impersonate="chrome124", timeout=self.timeout)
                if r.status_code == 200:
                    jobs = r.json().get("jobs", [])
                    for j in jobs:
                        company = j.get("companyName", "").strip()
                        title = j.get("jobTitle", "").strip()
                        desc = j.get("jobDescription", "")
                        job_url = j.get("url", "")
                        clean_desc = BeautifulSoup(desc, "html.parser").get_text(separator=" ")
                        domain = self._extract_domain(company, job_url, clean_desc)
                        if company and domain:
                            results.append({
                                "company_name": company,
                                "domain": domain,
                                "website_url": f"https://{domain}",
                                "job_title": title,
                                "summary": clean_desc[:350],
                                "job_url": job_url,
                                "source": "jobicy_api",
                                "confidence": 60.0,
                            })
            except Exception as e:
                logger.debug(f"Jobicy fetch error for tag {tag}: {e}")
        return results

    def fetch_remoteok(self) -> list[dict[str, Any]]:
        results = []
        url = "https://remoteok.com/api"
        try:
            r = http_client.get(url, impersonate="chrome124", timeout=self.timeout)
            if r.status_code == 200:
                data = r.json()
                if isinstance(data, list):
                    for j in data[1:]:  # Skip legal notice index 0
                        company = j.get("company", "").strip()
                        title = j.get("position", "").strip()
                        desc = j.get("description", "")
                        job_url = j.get("url", "")
                        clean_desc = BeautifulSoup(desc, "html.parser").get_text(separator=" ")
                        domain = self._extract_domain(company, job_url, clean_desc)
                        if company and domain:
                            results.append({
                                "company_name": company,
                                "domain": domain,
                                "website_url": f"https://{domain}",
                                "job_title": title,
                                "summary": clean_desc[:350],
                                "job_url": job_url,
                                "source": "remoteok_api",
                                "confidence": 60.0,
                            })
        except Exception as e:
            logger.debug(f"RemoteOK fetch error: {e}")
        return results

    def _extract_domain(self, company_name: str, job_url: str, description: str) -> str | None:
        clean = company_name.lower().strip()
        if not clean or len(clean.split()) > 4:
            return None
        if any(w in clean for w in ["confidential", "stealth", "various", "multiple", "unknown", "developer", "engineer", "specialist", "manager", "director", "consultant", "coordinator"]):
            return None

        urls = re.findall(r"https?://(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})", description)
        for u in urls:
            if not any(excl in u.lower() for excl in [
                "remotive", "arbeitnow", "jobicy", "remoteok", "greenhouse",
                "lever.co", "workable", "ashbyhq", "linkedin", "twitter", "github"
            ]):
                return normalize_domain(u)

        slug = re.sub(r"[^a-z0-9]", "", clean)
        if 3 <= len(slug) <= 25 and len(clean.split()) <= 3:
            return f"{slug}.com"
        return None
