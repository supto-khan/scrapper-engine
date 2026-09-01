from unittest.mock import patch
from discovery.directories.google_maps_discovery import GoogleMapsDiscoveryFeed
from enrichment.local_business_email_finder import LocalBusinessEmailFinder
from outreach.segmentation.segment_rules import LeadSegmenter
from scoring.fit_score import CompanyFitScorer
from scoring.opportunity_score import OpportunityScorer


def test_google_maps_feed_with_website():
    feed = GoogleMapsDiscoveryFeed()
    raw = {
        "name": "Apex Roofing Specialists",
        "website_url": "https://apexroofingtx.com",
        "city": "Austin",
        "category": "Roofing Contractor",
        "phone": "(512) 555-0199",
        "rating": 4.8,
        "review_count": 87,
    }
    parsed = feed.parse_entry(raw)
    assert parsed["name"] == "Apex Roofing Specialists"
    assert parsed["domain"] == "apexroofingtx.com"
    assert parsed["has_website"] is True
    assert parsed["is_high_priority_nowebsite"] is False
    assert parsed["source"] == "google_maps"


def test_google_maps_feed_no_website():
    feed = GoogleMapsDiscoveryFeed()
    raw = {
        "name": "Biscayne Bay Dental Spa",
        "website_url": None,
        "city": "Miami",
        "category": "Dental Clinic",
        "phone": "(305) 555-0144",
        "rating": 4.9,
        "review_count": 142,
    }
    parsed = feed.parse_entry(raw)
    assert parsed["name"] == "Biscayne Bay Dental Spa"
    assert parsed["domain"] == "biscayne-bay-dental-spa-miami.local"
    assert parsed["has_website"] is False
    assert parsed["is_high_priority_nowebsite"] is True
    assert parsed["website_url"] is None


def test_no_website_lead_scores_immediate_priority():
    scorer = OpportunityScorer()
    company_data = {
        "name": "Sunset Auto Care",
        "domain": "sunset-auto-care-dallas.local",
        "has_website": False,
        "is_high_priority_nowebsite": True,
        "source": "google_maps",
    }
    signals = [{"signal_type": "missing_website"}]
    opportunities = [{
        "type": "new_website_creation",
        "estimated_value_low": 2500,
        "estimated_value_high": 5000,
    }]

    breakdown = scorer.calculate_score(
        company_data=company_data,
        signals=signals,
        opportunities=opportunities,
    )

    assert breakdown["opportunity_score"] >= 90.0
    assert breakdown["priority_tier"] == "immediate"
    assert breakdown["total_deal_range"] == [2500, 5000]


def test_lead_segmenter_prioritizes_new_website_creation():
    segmenter = LeadSegmenter()
    company_data = {
        "name": "Downtown Orthodontics",
        "has_website": False,
    }
    opportunities = [{"type": "new_website_creation"}]
    segment = segmenter.segment_lead(company_data=company_data, opportunities=opportunities)
    assert segment == "new_website_creation"


def test_local_business_email_finder_filters_junk():
    finder = LocalBusinessEmailFinder()
    assert finder._is_valid_lead_email("drsmith@biscaynedental.com") is True
    assert finder._is_valid_lead_email("biscayneortho@gmail.com") is True
    assert finder._is_valid_lead_email("support@wix.com") is False
    assert finder._is_valid_lead_email("noreply@google.com") is False
    assert finder._is_valid_lead_email("privacy@facebook.com") is False


def test_local_business_email_finder_search():
    finder = LocalBusinessEmailFinder()
    mock_emails = ["drsmith@biscaynedental.com", "biscayneortho@gmail.com"]
    with patch.object(finder, "_search_and_extract_emails", return_value=mock_emails):
        contacts = finder.find_business_email("Biscayne Bay Dental", "Miami", "305-555-0144")
        assert len(contacts) == 2
        assert contacts[0]["email"] == "drsmith@biscaynedental.com"
        assert contacts[0]["email_status"] == "valid"

