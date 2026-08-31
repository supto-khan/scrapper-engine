from unittest.mock import MagicMock, patch

from enrichment.apollo_client import ApolloClient
from enrichment.email_validator import EmailValidator
from enrichment.enrichment_worker import EnrichmentWorker
from enrichment.hunter_client import HunterClient


def test_hunter_client_parsing():
    hunter = HunterClient(api_key="mock_hunter_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "data": {
            "emails": [
                {
                    "value": "alex@acmestudios.com",
                    "first_name": "Alex",
                    "last_name": "Rivers",
                    "position": "Chief Technology Officer",
                    "confidence": 92,
                    "linkedin": "https://linkedin.com/in/alexrivers",
                }
            ]
        }
    }

    with patch("requests.get", return_value=mock_resp):
        contacts = hunter.search_domain("acmestudios.com")
        assert len(contacts) == 1
        c = contacts[0]
        assert c["full_name"] == "Alex Rivers"
        assert c["email"] == "alex@acmestudios.com"
        assert c["title"] == "Chief Technology Officer"
        assert c["role_category"] == "technical_executive"
        assert c["email_score"] == 92.0


def test_apollo_client_parsing():
    apollo = ApolloClient(api_key="mock_apollo_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "people": [
            {
                "name": "Sarah Connor",
                "first_name": "Sarah",
                "last_name": "Connor",
                "title": "VP of Engineering",
                "email": "sarah@techlead.io",
                "linkedin_url": "https://linkedin.com/in/sarahconnor",
            }
        ]
    }

    with patch("requests.post", return_value=mock_resp):
        contacts = apollo.search_people("techlead.io")
        assert len(contacts) == 1
        c = contacts[0]
        assert c["full_name"] == "Sarah Connor"
        assert c["email"] == "sarah@techlead.io"
        assert c["role_category"] == "technical_executive"


def test_email_validator():
    validator = EmailValidator()
    # Valid syntax
    res1 = validator.validate("john.doe@company.com")
    assert res1["status"] == "valid"
    assert res1["is_deliverable"] is True

    # Invalid syntax
    res2 = validator.validate("not-an-email")
    assert res2["status"] == "invalid"
    assert res2["is_deliverable"] is False

    # Disposable domain
    res3 = validator.validate("test@mailinator.com")
    assert res3["status"] == "invalid"
    assert res3["is_deliverable"] is False


def test_enrichment_worker_flow():
    mock_apollo = MagicMock()
    mock_apollo.search_people.return_value = [
        {
            "full_name": "Sarah Connor",
            "first_name": "Sarah",
            "last_name": "Connor",
            "title": "VP of Engineering",
            "role_category": "technical_executive",
            "email": "sarah@techlead.io",
            "email_score": 85.0,
            "verification_source": "apollo",
            "source": "apollo",
        }
    ]

    mock_validator = MagicMock()
    mock_validator.validate.return_value = {
        "status": "valid",
        "score": 90.0,
        "source": "zerobounce",
    }

    worker = EnrichmentWorker(
        apollo_client=mock_apollo,
        email_validator=mock_validator,
    )

    with patch.object(worker.mysql, "save_contact", return_value=123):
        saved = worker.enrich_company(company_id=1, domain="techlead.io")
        assert len(saved) == 1
        assert saved[0]["id"] == 123
        assert saved[0]["email_status"] == "valid"


def test_enrichment_website_scraper_fallback_flow():
    mock_apollo = MagicMock()
    mock_apollo.search_people.return_value = []

    mock_scraper = MagicMock()
    mock_scraper.scrape_domain_contacts.return_value = [
        {
            "full_name": "Acme Agency Contact / Inquiries",
            "first_name": "Acme",
            "last_name": "Contact / Inquiries",
            "title": "Contact / Inquiries",
            "role_category": "general",
            "email": "hello@acmeagency.com",
            "email_score": 80.0,
            "verification_source": "website_crawler",
            "source": "website_crawler",
        }
    ]

    mock_validator = MagicMock()
    mock_validator.validate.return_value = {
        "status": "valid",
        "score": 85.0,
        "source": "zerobounce",
    }

    worker = EnrichmentWorker(
        apollo_client=mock_apollo,
        website_scraper=mock_scraper,
        email_validator=mock_validator,
    )

    with patch.object(worker.mysql, "save_contact", return_value=456):
        saved = worker.enrich_company(company_id=2, domain="acmeagency.com")
        assert len(saved) == 1
        assert saved[0]["id"] == 456
        assert saved[0]["email"] == "hello@acmeagency.com"
        assert saved[0]["source"] == "website_crawler"


def test_website_contact_scraper_advanced_parsing():
    from enrichment.website_contact_scraper import WebsiteContactScraper

    scraper = WebsiteContactScraper()

    # 1. Cloudflare XOR decoding test
    encoded = "5a3935342e3b392e1a3b3d3f34392374393537"  # XOR with 0x5a for 'contact@agency.com'
    decoded = scraper._decode_cloudflare_email(encoded)
    assert decoded == "contact@agency.com"

    # 2. Test HTML with mailto, JSON-LD, and Obfuscated anti-spam text
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Organization",
          "name": "Dev Studio",
          "email": "partnerships@devstudio.com"
        }
        </script>
      </head>
      <body>
        <p>Reach us at hello [at] devstudio [dot] com</p>
        <a href="mailto:info@devstudio.com">Email Us</a>
        <img src="/assets/logo@2x.png">
      </body>
    </html>
    """
    extracted = scraper._extract_emails_from_html(html, "devstudio.com")
    emails = [e["email"] for e in extracted]
    assert "info@devstudio.com" in emails
    assert "partnerships@devstudio.com" in emails
    assert "hello@devstudio.com" in emails
    assert not any("logo@2x.png" in em for em in emails)


def test_canonical_mx_synthesizer_flow():
    mock_apollo = MagicMock()
    mock_apollo.search_people.return_value = []

    mock_scraper = MagicMock()
    mock_scraper.scrape_domain_contacts.return_value = []
    mock_scraper.resolve_canonical_domain.return_value = "req.co"

    mock_validator = MagicMock()
    mock_validator.has_mx_records.return_value = True
    mock_validator.validate.return_value = {
        "status": "valid",
        "score": 75.0,
        "source": "dns_mx_verified",
    }

    worker = EnrichmentWorker(
        apollo_client=mock_apollo,
        website_scraper=mock_scraper,
        email_validator=mock_validator,
    )

    with patch.object(worker.mysql, "save_contact", return_value=789):
        saved = worker.enrich_company(company_id=3, domain="req.co")
        assert len(saved) == 1
        assert saved[0]["id"] == 789
        assert saved[0]["email"] == "hello@req.co"
        assert saved[0]["source"] == "canonical_synthesizer"


