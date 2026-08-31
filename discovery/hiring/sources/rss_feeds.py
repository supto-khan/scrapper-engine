import logging
import re
from typing import Any
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from shared import http_client

from shared.redis_client import normalize_domain

logger = logging.getLogger(__name__)


class RSSJobFeedCollector:
    """
    Collects high-intent job postings from developer & design RSS feeds.
    Assigns stored probabilistic confidence weights per source:
    - LaraJobs: 75.0 (Ecosystem match)
    - Himalayas: 70.0 (Curated profiles)
    - Working Nomads: 60.0
    - Arc.dev: 65.0
    - JS Remotely: 65.0
    - Jobspresso: 60.0
    - Dribbble: 65.0 (Active redesigns)
    """

    RSS_FEEDS = [
        {"name": "larajobs", "url": "https://larajobs.com/feed", "default_industry": "Custom Laravel & Web Applications", "confidence": 75.0},
        {"name": "himalayas", "url": "https://himalayas.app/jobs/rss", "default_industry": "Commercial Web & Cloud Platforms", "confidence": 70.0},
        {"name": "working_nomads", "url": "https://www.workingnomads.com/jobs?category=development&format=rss", "default_industry": "Custom Business Software", "confidence": 60.0},
        {"name": "arc_dev", "url": "https://arc.dev/remote-jobs/rss", "default_industry": "Commercial Web Development", "confidence": 65.0},
        {"name": "js_remotely", "url": "https://jsremotely.com/rss.xml", "default_industry": "Modern Frontend & React Stores", "confidence": 65.0},
        {"name": "jobspresso", "url": "https://jobspresso.co/category/tech/feed/", "default_industry": "Custom Business Applications", "confidence": 60.0},
        {"name": "dribbble", "url": "https://dribbble.com/jobs.rss", "default_industry": "E-Commerce & Digital Design", "confidence": 65.0},
        {"name": "wwr_fullstack", "url": "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss", "default_industry": "Custom Business Applications", "confidence": 70.0},
        {"name": "wwr_frontend", "url": "https://weworkremotely.com/categories/remote-front-end-programming-jobs.rss", "default_industry": "Modern Frontend & Web Applications", "confidence": 70.0},
        {"name": "wwr_backend", "url": "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss", "default_industry": "Custom Backend & Software Architecture", "confidence": 70.0},
        {"name": "vuejobs", "url": "https://vuejobs.com/feed", "default_industry": "Modern Frontend & Web Apps", "confidence": 65.0},
        {"name": "ruby_on_remote", "url": "https://rubyonremote.com/feed.xml", "default_industry": "E-Commerce & SaaS Platforms", "confidence": 65.0},
    ]

    def __init__(self, timeout: int = 12):
        self.timeout = timeout

    def fetch_all(self) -> list[dict[str, Any]]:
        all_jobs = []
        for feed in self.RSS_FEEDS:
            try:
                jobs = self.fetch_feed(feed)
                all_jobs.extend(jobs)
            except Exception as e:
                logger.debug(f"RSS feed {feed['name']} error: {e}")
        return all_jobs

    def fetch_feed(self, feed_info: dict[str, Any]) -> list[dict[str, Any]]:
        results = []
        name = feed_info["name"]
        url = feed_info["url"]
        default_industry = feed_info["default_industry"]
        confidence = feed_info.get("confidence", 60.0)

        try:
            r = http_client.get(url, impersonate="chrome124", timeout=self.timeout)
            if r.status_code != 200:
                return results

            root = ET.fromstring(r.content)
            for item in root.findall(".//item"):
                title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                description = item.findtext("description") or ""

                company_name, job_title = self._parse_title(title)
                if not company_name or len(company_name) < 2:
                    continue

                clean_desc = BeautifulSoup(description, "html.parser").get_text(separator=" ")
                domain = self._extract_domain(company_name, link, clean_desc)
                if not domain:
                    continue

                results.append({
                    "company_name": company_name,
                    "domain": domain,
                    "website_url": f"https://{domain}",
                    "job_title": job_title,
                    "summary": clean_desc[:350],
                    "job_url": link,
                    "source": f"rss_{name}",
                    "default_industry": default_industry,
                    "confidence": confidence,
                })
        except Exception as e:
            logger.debug(f"Error parsing RSS {name}: {e}")

        return results

    def _parse_title(self, raw_title: str) -> tuple[str, str]:
        if ":" in raw_title:
            parts = raw_title.split(":", 1)
            return parts[0].strip(), parts[1].strip()
        elif " at " in raw_title:
            parts = raw_title.split(" at ", 1)
            return parts[1].strip(), parts[0].strip()
        elif " is hiring " in raw_title:
            parts = raw_title.split(" is hiring ", 1)
            return parts[0].strip(), parts[1].strip()
        elif " - " in raw_title:
            parts = raw_title.split(" - ", 1)
            # Check which part is shorter (likely company name)
            if len(parts[0]) <= 30 and len(parts[0].split()) <= 3:
                return parts[0].strip(), parts[1].strip()
            elif len(parts[1]) <= 30 and len(parts[1].split()) <= 3:
                return parts[1].strip(), parts[0].strip()

        return "", ""

    def _extract_domain(self, company_name: str, job_url: str, description: str) -> str | None:
        clean = company_name.lower().strip()
        if not clean or len(clean.split()) > 4:
            return None
        if any(w in clean for w in [
            "confidential", "stealth", "various", "multiple", "unknown", "developer",
            "engineer", "specialist", "manager", "director", "consultant", "weworkremotely",
            "we work remotely", "larajobs", "himalayas", "remoteok", "jobicy", "dribbble"
        ]):
            return None

        urls = re.findall(r"https?://(?:www\.)?([a-zA-Z0-9-]+\.[a-zA-Z]{2,})", description)
        for u in urls:
            if not any(excl in u.lower() for excl in [
                "larajobs", "himalayas", "workingnomads", "arc.dev", "jsremotely",
                "jobspresso", "dribbble", "greenhouse", "lever.co", "workable", "ashbyhq",
                "remotive", "arbeitnow", "jobicy", "remoteok", "linkedin", "twitter", "weworkremotely"
            ]):
                return normalize_domain(u)

        slug = re.sub(r"[^a-z0-9]", "", clean)
        if 3 <= len(slug) <= 25 and len(clean.split()) <= 3:
            return f"{slug}.com"
        return None
