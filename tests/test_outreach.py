from unittest.mock import patch, MagicMock

from outreach.personalization.copy_generator import OutreachCopyGenerator
from outreach.personalization.qwen_client import clean_and_parse_ai_output
from outreach.queue.queue_manager import OutreachQueueManager
from outreach.segmentation.segment_rules import LeadSegmenter


def test_clean_and_parse_ai_output_with_think_tags():
    raw_ai = (
        "<think>\n"
        "Analyze the company stack:\n"
        "- They use jQuery and Bootstrap.\n"
        "- Recommend React.\n"
        "</think>\n\n"
        "Subject: Modernizing Thinkitive's frontend stack\n\n"
        "Hello Marcus,\n\n"
        "We noticed a persistent technical signal in your frontend libraries: legacy imports (jQuery 3.6.0, Bootstrap).\n\n"
        "Open to checking out the 3 quick fixes we drafted?\n\n"
        "Best,\n"
        "Supto Khan\n"
        "CEO, Nexidant\n"
    )

    result = clean_and_parse_ai_output(raw_ai, company_name="Thinkitive", step=1)
    
    assert "<think>" not in result["body"]
    assert "</think>" not in result["body"]
    assert "Analyze the company stack" not in result["body"]
    assert result["subject"] == "Modernizing Thinkitive's frontend stack"
    assert result["body"].startswith("Hello Marcus,")
    assert not result["body"].startswith("Subject:")
    assert "Open to checking out the 3 quick fixes we drafted?" in result["body"]
    # Model's hallucinated signature is stripped so canonical signature isn't duplicated
    assert "Supto Khan" not in result["body"]


def test_clean_and_parse_ai_output_bold_subject_and_markdown():
    raw_ai = (
        "```markdown\n"
        "<think>Reasoning...</think>\n"
        "**Subject:** Tech signal: Legacy libraries\n\n"
        "Hi John,\n\n"
        "Noticed your frontend setup is running jQuery 3.6.0.\n"
        "```"
    )

    result = clean_and_parse_ai_output(raw_ai, company_name="Acme", step=1)
    assert result["subject"] == "Tech signal: Legacy libraries"
    assert result["body"].startswith("Hi John,")
    assert "<think>" not in result["body"]
    assert "```" not in result["body"]


def test_frontend_stack_json_string_formatting():
    copy_gen = OutreachCopyGenerator(
        sender_name="Supto",
        sender_address="Nexidant, Dhaka",
        unsubscribe_base_url="https://nexidant.com/unsub?email=",
    )

    company = {"name": "Thinkitive", "domain": "thinkitive.com"}
    contact = {"first_name": "Marcus", "email": "marcus@thinkitive.com"}
    # tech_fingerprint with JSON-serialized string as returned from MySQL
    tech = {"frontend_stack": '["jQuery 3.6.0", "Bootstrap"]'}

    msg = copy_gen.generate_message(
        segment="frontend_modernization",
        company_data=company,
        contact_data=contact,
        tech_fingerprint=tech,
    )

    assert "jQuery 3.6.0, Bootstrap" in msg["body_text"]
    assert "[, \", j, Q" not in msg["body_text"]
    assert "<think>" not in msg["body_text"]


def test_lead_segmentation_rules():
    segmenter = LeadSegmenter()

    # 1. Staff Augmentation
    opps_staff = [{"type": "staff_augmentation"}]
    seg1 = segmenter.segment_lead(company_data={}, opportunities=opps_staff)
    assert seg1 == "staff_augmentation"

    # 2. WordPress to Laravel
    opps_wp = [{"type": "cms_to_laravel_migration"}]
    seg2 = segmenter.segment_lead(company_data={}, opportunities=opps_wp)
    assert seg2 == "laravel_modernization"

    # 3. Frontend Rebuild
    opps_fe = [{"type": "frontend_modernization"}]
    seg3 = segmenter.segment_lead(company_data={}, opportunities=opps_fe)
    assert seg3 == "frontend_modernization"

    # 4. Frontend Rebuild with JSON string frontend_stack
    tech_json = {"frontend_stack": '["jQuery 2.2.4"]'}
    seg4 = segmenter.segment_lead(company_data={}, tech_fingerprint=tech_json)
    assert seg4 == "frontend_modernization"


def test_personalized_copy_generator():
    copy_gen = OutreachCopyGenerator(
        sender_name="Supto",
        sender_address="Nexidiant, 123 Tech St, NY",
        unsubscribe_base_url="https://nexidiant.com/unsub?email=",
    )

    company = {"name": "Apex Digital", "domain": "apexdigital.com"}
    contact = {
        "first_name": "Marcus",
        "full_name": "Marcus Vance",
        "email": "marcus@apexdigital.com",
    }
    tech = {"cms": "WordPress 5.4"}

    msg = copy_gen.generate_message(
        segment="laravel_modernization",
        company_data=company,
        contact_data=contact,
        tech_fingerprint=tech,
    )

    assert "Marcus" in msg["body_text"]
    assert "Apex Digital" in msg["subject"]
    assert "WordPress 5.4" in msg["body_text"]
    assert "Nexidiant, 123 Tech St, NY" in msg["body_text"]
    assert (
        "https://nexidiant.com/unsub?email=marcus@apexdigital.com" in msg["body_text"]
    )


def test_queue_manager_stages_message():
    queue_mgr = OutreachQueueManager()
    company = {"id": 10, "name": "Modern Corp", "domain": "moderncorp.io"}
    contacts = [
        {
            "id": 101,
            "first_name": "Elena",
            "full_name": "Elena Rostova",
            "email": "elena@moderncorp.io",
            "email_status": "valid",
        },
        {
            "id": 102,
            "first_name": "Bad",
            "full_name": "Bad Lead",
            "email": "bad@moderncorp.io",
            "email_status": "invalid",
        },
    ]

    with patch.object(queue_mgr.mysql, "has_existing_outreach", return_value=False), \
         patch.object(queue_mgr.mysql, "save_outreach_message", return_value=999), \
         patch.object(queue_mgr.email_validator, "validate", return_value={"is_deliverable": True, "status": "valid"}):
        staged_ids = queue_mgr.stage_outreach_for_company(
            company_data=company,
            contacts=contacts,
            opportunities=[{"type": "frontend_modernization"}],
        )

        # Only 1 valid contact should be staged, invalid skipped
        assert len(staged_ids) == 1
        assert staged_ids[0] == 999


def test_queue_manager_skips_unverified_synthetic_contacts():
    queue_mgr = OutreachQueueManager()
    company = {"id": 11, "name": "Fake Corp", "domain": "fakecorp.io"}
    contacts = [
        {
            "id": 201,
            "first_name": "Guess",
            "full_name": "Guess Lead",
            "email": "hello@fakecorp.io",
            "email_status": "valid",
            "source": "canonical_synthesizer",
        },
        {
            "id": 202,
            "first_name": "Permutated",
            "full_name": "Permutated Lead",
            "email": "jdoe@fakecorp.io",
            "email_status": "valid",
            "source": "email_permutator",
        },
        {
            "id": 203,
            "first_name": "Real",
            "full_name": "Real Lead",
            "email": "contact@realcorp.io",
            "email_status": "valid",
            "source": "website_crawler",
        },
    ]

    def mock_validate(email):
        if "fakecorp.io" in email:
            return {"is_deliverable": False, "status": "invalid", "reason": "Mailbox rejected 550"}
        return {"is_deliverable": True, "status": "valid"}

    with patch.object(queue_mgr.mysql, "has_existing_outreach", return_value=False), \
         patch.object(queue_mgr.mysql, "save_outreach_message", return_value=888), \
         patch.object(queue_mgr.email_validator, "validate", side_effect=mock_validate):
        staged_ids = queue_mgr.stage_outreach_for_company(
            company_data=company,
            contacts=contacts,
            opportunities=[{"type": "frontend_modernization"}],
        )

        # Only the real scraped contact (203) should be staged; 201 & 202 skipped
        assert len(staged_ids) == 1
        assert staged_ids[0] == 888
