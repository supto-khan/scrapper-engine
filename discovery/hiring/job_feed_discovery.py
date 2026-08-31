import logging
import os
import sys
from typing import Any

# Ensure project root is in sys.path when running standalone
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from discovery.company_discovery import CompanyDiscoveryOrchestrator
from discovery.hiring.sources.public_apis import PublicJobAPICollector
from discovery.hiring.sources.rss_feeds import RSSJobFeedCollector
from shared.mysql_client import get_mysql_client

logger = logging.getLogger(__name__)


class JobBoardIntentDiscovery:
    """
    Job Board & Hiring Intent Discovery Orchestrator.
    Discovers high-intent commercial buyers actively recruiting for:
    - Custom web applications (React, Next.js, Laravel, PHP, Shopify, Python)
    - Slow site & performance optimizations
    - Legacy monolith modernizations

    Sources:
    1. Public APIs (Remotive, Arbeitnow, Jobicy, RemoteOK)
    2. RSS/Atom Feeds (LaraJobs, Himalayas, Working Nomads, Arc.dev, JS Remotely, Dribbble)
    """

    def __init__(self, orchestrator: CompanyDiscoveryOrchestrator | None = None):
        self.orchestrator = orchestrator or CompanyDiscoveryOrchestrator()
        self.mysql_client = get_mysql_client()
        self.api_collector = PublicJobAPICollector()
        self.rss_collector = RSSJobFeedCollector()

    def discover_hiring_leads(self) -> int:
        """
        Executes discovery across all active job board APIs and RSS streams.
        Filters out dev agencies and ingests high-intent commercial companies.
        """
        logger.info("🔍 [Job Intent Discovery] Scanning Public APIs and Developer RSS streams...")
        all_jobs: list[dict[str, Any]] = []

        # 1. Fetch from Public Developer APIs
        try:
            api_jobs = self.api_collector.fetch_all()
            logger.info(f"   ✓ [Public APIs] Found {len(api_jobs)} active job postings.")
            all_jobs.extend(api_jobs)
        except Exception as e:
            logger.error(f"Error fetching from Public APIs: {e}")

        # 2. Fetch from RSS & Atom Feeds
        try:
            rss_jobs = self.rss_collector.fetch_all()
            logger.info(f"   ✓ [RSS Feeds] Found {len(rss_jobs)} active job postings.")
            all_jobs.extend(rss_jobs)
        except Exception as e:
            logger.error(f"Error fetching from RSS feeds: {e}")

        # 3. Filter and Ingest Commercial Businesses
        total_ingested = 0
        for job in all_jobs:
            company_name = job["company_name"]
            domain = job["domain"]
            job_title = job["job_title"]
            summary = job["summary"]
            source = job["source"]

            # Classify industry based on company name, title, and job description
            classified_industry = self.orchestrator.classify_target_industry(
                f"{company_name} {job_title} {summary}",
                default_industry=job.get("default_industry", "Commercial Web & Software Applications")
            )

            # Ingest candidate through the agency exclusion filter
            accepted = self.orchestrator.ingest_candidate({
                "name": company_name,
                "website_url": f"https://{domain}",
                "domain": domain,
                "source": source,
                "industry": classified_industry,
                "project_summary": f"Hiring: {job_title} - {summary[:150]}",
                "employee_count_estimate": "10-100",
            })

            if accepted:
                total_ingested += 1
                confidence_score = float(job.get("confidence", 60.0))
                self._save_hiring_signal(domain, job_title, summary, job.get("job_url", f"https://{domain}"), confidence_score)

        logger.info(f"🎉 [Job Intent Discovery] Completed! Ingested {total_ingested} high-intent commercial buyers.")
        return total_ingested

    def _save_hiring_signal(self, domain: str, job_title: str, snippet: str, job_url: str, confidence_score: float = 60.0) -> None:
        """Persists high-intent hiring signal with source confidence weight to MySQL."""
        try:
            conn = self.mysql_client.get_connection()
            with conn.cursor() as cursor:
                cursor.execute("SELECT id FROM companies WHERE domain = %s", (domain,))
                row = cursor.fetchone()
                if row:
                    company_id = row["id"]
                    self.mysql_client.save_signal(
                        company_id=company_id,
                        signal_type="active_hiring_intent",
                        source_url=job_url,
                        confidence_score=confidence_score,
                        evidence_data={
                            "job_title": job_title,
                            "summary": snippet[:250],
                            "intent_type": "engineering_capacity_shortage",
                            "confidence_weight": confidence_score,
                        },
                    )
            conn.close()
        except Exception as e:
            logger.debug(f"Could not persist hiring signal for {domain}: {e}")


def get_job_board_discovery() -> JobBoardIntentDiscovery:
    return JobBoardIntentDiscovery()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    discovery = get_job_board_discovery()
    ingested = discovery.discover_hiring_leads()
    print(f"\nDone! Ingested {ingested} active hiring buyer leads.")
