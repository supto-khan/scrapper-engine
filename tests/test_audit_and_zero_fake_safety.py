from unittest.mock import MagicMock, patch
import pytest

from discovery.directories.google_maps_crawler import GoogleMapsCrawler
from enrichment.email_permutator import EmailPermutator
from enrichment.enrichment_worker import EnrichmentWorker
from outreach.queue.queue_manager import OutreachQueueManager
from shared.mysql_client import MySQLClient


def test_permutator_rejects_unverified_and_catchall():
    mock_validator = MagicMock()
    # Case 1: MX exists and status is valid, but SMTP was NOT accepted (e.g. only dns_mx_verified)
    mock_validator.validate.return_value = {
        "status": "valid",
        "sub_status": "dns_mx_verified",
        "smtp": {"rcpt_accepted": False},
        "catch_all": {"detected": False},
    }
    permutator = EmailPermutator(validator=mock_validator)
    contacts = permutator.synthesize_verified_contacts(
        executives=[{"first_name": "John", "last_name": "Doe"}],
        domain="example.com",
    )
    assert len(contacts) == 0, "Permutator must reject candidates that lack 250 OK SMTP handshake acceptance"

    # Case 2: Catch-all domain (even if code is 250, catch_all is detected)
    mock_validator.validate.return_value = {
        "status": "valid",
        "sub_status": "smtp_accepted",
        "smtp": {"rcpt_accepted": True},
        "catch_all": {"detected": True},
    }
    contacts_catchall = permutator.synthesize_verified_contacts(
        executives=[{"first_name": "John", "last_name": "Doe"}],
        domain="catchall-domain.com",
    )
    assert len(contacts_catchall) == 0, "Permutator must reject guessed emails on catch-all domains"

    # Case 3: Genuine 250 OK accepted on non-catchall domain
    mock_validator.validate.return_value = {
        "status": "valid",
        "sub_status": "smtp_accepted",
        "score": 90.0,
        "smtp": {"rcpt_accepted": True},
        "catch_all": {"detected": False},
    }
    contacts_valid = permutator.synthesize_verified_contacts(
        executives=[{"first_name": "John", "last_name": "Doe"}],
        domain="real-domain.com",
    )
    assert len(contacts_valid) == 1
    assert contacts_valid[0]["verification_source"] == "smtp_handshake"
    assert contacts_valid[0]["email"] == "john.doe@real-domain.com"


def test_canonical_synthesizer_rejects_unverified_inboxes():
    mock_apollo = MagicMock()
    mock_apollo.search_people.return_value = []
    mock_scraper = MagicMock()
    mock_scraper.scrape_domain_contacts.return_value = []
    mock_scraper.resolve_canonical_domain.return_value = "corp.com"

    mock_validator = MagicMock()
    mock_validator.has_mx_records.return_value = True

    # When SMTP handshake fails or is only DNS-level:
    mock_validator.validate.return_value = {
        "status": "valid",
        "sub_status": "dns_mx_verified",
        "smtp": {"rcpt_accepted": False},
        "catch_all": {"detected": False},
    }

    worker = EnrichmentWorker(
        apollo_client=mock_apollo,
        website_scraper=mock_scraper,
        email_validator=mock_validator,
    )
    worker.local_finder.find_business_website_and_email = MagicMock(return_value={"contacts": []})

    with patch.object(worker.mysql, "save_contact", return_value=123):
        saved = worker.enrich_company(company_id=10, domain="corp.com")
        assert len(saved) == 0, "Canonical synthesizer must not create contacts if SMTP did not explicitly accept mailbox"


def test_queue_manager_blocks_synthetic_and_unverified_emails():
    mock_validator = MagicMock()
    mock_mysql = MagicMock()
    mock_mysql.has_existing_outreach.return_value = False

    qm = OutreachQueueManager()
    qm.mysql = mock_mysql
    qm.email_validator = mock_validator

    company = {
        "id": 1,
        "name": "Target Co",
        "domain": "target.com",
        "last_crawled_at": "2026-03-01 10:00:00",
    }
    tech = {"cms": "WordPress", "frontend_stack": ["React"], "evidence": {}}

    # Case A: Synthetic contact marked 'unverified'
    unverified_contact = {
        "id": 101,
        "email": "contact@target.com",
        "email_status": "unverified",
        "source": "canonical_synthesizer",
        "verification_source": "unverified",
    }
    res_unverified = qm.stage_outreach_for_company(
        company_data=company,
        contacts=[unverified_contact],
        tech_fingerprint=tech,
    )
    assert len(res_unverified) == 0, "QueueManager must reject contacts with email_status 'unverified'"

    # Case B: Synthetic contact with catch_all status
    catchall_synth = {
        "id": 102,
        "email": "info@target.com",
        "email_status": "catch_all",
        "source": "canonical_synthesizer",
        "verification_source": "smtp_handshake",
    }
    res_catchall = qm.stage_outreach_for_company(
        company_data=company,
        contacts=[catchall_synth],
        tech_fingerprint=tech,
    )
    assert len(res_catchall) == 0, "QueueManager must reject synthetic contacts from catch-all mailboxes"


def test_prune_low_scores_never_overwrites_disqualified_or_pending():
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cursor

    client = MySQLClient()
    with patch.object(client, "get_connection", return_value=mock_conn):
        mock_cursor.fetchall.return_value = []
        client.prune_low_score_companies(min_score=40.0)

        # Inspect the SQL query executed
        executed_sql = mock_cursor.execute.call_args[0][0]
        assert "AND s.priority_tier NOT IN ('ignore', 'disqualified', 'pending_audit')" in executed_sql
