from unittest.mock import MagicMock, patch

from enrichment.decision_engine import DecisionEngine
from enrichment.disposable_checker import is_disposable_email
from enrichment.email_validator import EmailValidator
from enrichment.role_checker import is_role_account
from enrichment.smtp_verifier import SmtpVerifier
from enrichment.syntax_checker import validate_email_syntax


def test_syntax_checker_rfc_rules():
    # Valid emails
    valid_cases = [
        "simple@example.com",
        "very.common@example.com",
        "disposable.style.email.with+symbol@example.com",
        "other.email-with-hyphen@example.com",
        "fully-qualified-domain@example.co.uk",
        "user.name+tag@subdomain.domain.org",
    ]
    for email in valid_cases:
        is_val, err = validate_email_syntax(email)
        assert is_val is True, f"Expected '{email}' to be valid, got error: {err}"

    # Invalid emails
    invalid_cases = [
        ("plainaddress", "missing '@'"),
        ("@missing-username.com", "empty"),
        ("username@.com", "dot"),
        ("username@com", "TLD"),
        ("user..name@example.com", "consecutive dots"),
        (".leadingdot@example.com", "begin or end with a dot"),
        ("trailingdot.@example.com", "begin or end with a dot"),
        ("user@example..com", "consecutive dots"),
        ("user@-example.com", "hyphen"),
        ("user@example-.com", "hyphen"),
        ("a" * 65 + "@example.com", "64 characters"),
    ]
    for email, reason_fragment in invalid_cases:
        is_val, err = validate_email_syntax(email)
        assert is_val is False, f"Expected '{email}' to be invalid"
        assert reason_fragment.lower() in (err or "").lower()


def test_disposable_checker_expanded_list():
    disposable_examples = [
        "test@10minutemail.com",
        "fake@guerrillamail.biz",
        "user@sharklasers.com",
        "trash@yopmail.fr",
        "temp@throwawaymail.com",
        "burn@burnermail.io",
        "anon@mailinator.net",
    ]
    for email in disposable_examples:
        assert is_disposable_email(email) is True

    # Legitimate corporate domains must not be flagged
    assert is_disposable_email("alex@google.com") is False
    assert is_disposable_email("sarah@microsoft.com") is False
    assert is_disposable_email("support@nexidant.com") is False


def test_role_checker():
    role_cases = [
        ("admin@corp.com", "admin"),
        ("support+tier1@service.io", "support"),
        ("sales@enterprise.com", "sales"),
        ("billing-team@saas.com", "billing"),
        ("customer.service@store.com", "service"),
        ("hello@startup.io", "hello"),
        ("jobs@company.org", "jobs"),
    ]
    for email, expected_prefix in role_cases:
        is_role, prefix = is_role_account(email)
        assert is_role is True, f"Expected {email} to be flagged as role account"
        assert prefix == expected_prefix

    # Personal executive emails
    non_role_cases = [
        "tim.cook@apple.com",
        "satya.nadella@microsoft.com",
        "alex.rivers@acmestudios.com",
        "john.doe@company.com",
    ]
    for email in non_role_cases:
        is_role, _ = is_role_account(email)
        assert is_role is False, f"Expected {email} not to be role account"


def test_mx_metadata_preference_and_rank():
    verifier = SmtpVerifier(check_catchall=False)
    mock_record1 = MagicMock()
    mock_record1.exchange = "mx1.example.com."
    mock_record1.preference = 10

    mock_record2 = MagicMock()
    mock_record2.exchange = "mx2.example.com."
    mock_record2.preference = 20

    with patch("dns.resolver.Resolver.resolve", return_value=[mock_record2, mock_record1]):
        records = verifier.get_mx_records("example.com")
        assert len(records) == 2
        # Sorted by preference (10 then 20)
        assert records[0]["host"] == "mx1.example.com"
        assert records[0]["preference"] == 10
        assert records[0]["rank"] == 1

        assert records[1]["host"] == "mx2.example.com"
        assert records[1]["preference"] == 20
        assert records[1]["rank"] == 2


def test_decision_engine_taxonomy():
    # 1. Malformed syntax
    res1 = DecisionEngine.evaluate(
        email="bad..syntax@example.com",
        syntax_valid=False,
        syntax_error="Consecutive dots",
    )
    assert res1["status"] == "invalid"
    assert res1["sub_status"] == "malformed_syntax"
    assert res1["is_deliverable"] is False

    # 2. Disposable
    res2 = DecisionEngine.evaluate(
        email="temp@mailinator.com",
        syntax_valid=True,
        is_disposable=True,
    )
    assert res2["status"] == "invalid"
    assert res2["sub_status"] == "disposable_email"
    assert res2["is_deliverable"] is False

    # 3. Role account accepted at gateway
    smtp_res = {
        "status": "valid",
        "sub_status": "smtp_accepted",
        "score": 75.0,
        "is_deliverable": True,
        "provider": "google_workspace",
    }
    res3 = DecisionEngine.evaluate(
        email="support@company.com",
        syntax_valid=True,
        is_disposable=False,
        is_role=True,
        role_prefix="support",
        smtp_result=smtp_res,
    )
    assert res3["status"] == "valid"
    assert res3["sub_status"] == "role_account"
    assert res3["is_role_account"] is True
    assert res3["is_deliverable"] is True
    # Role account gets calibrated score
    assert res3["score"] == 65.0


def test_full_email_validator_pipeline_integration():
    mock_smtp_verifier = MagicMock()
    mock_smtp_verifier.get_mx_records.return_value = [
        {"host": "mail.company.com", "preference": 10, "rank": 1}
    ]
    mock_smtp_verifier.verify_mailbox.return_value = {
        "email": "ceo@company.com",
        "status": "valid",
        "sub_status": "smtp_accepted",
        "score": 85.0,
        "confidence": 85.0,
        "is_deliverable": True,
        "provider": "custom_smtp",
        "domain": {
            "name": "company.com",
            "mx_host": "mail.company.com",
            "mx_preference": 10,
            "mx_rank": 1,
            "mx_primary": True,
        },
        "smtp": {"connected": True, "rcpt_code": 250, "rcpt_accepted": True},
        "catch_all": {"checked": True, "detected": False},
        "source": "smtp_handshake",
        "reason": "Mailbox accepted by primary MX mail.company.com (custom_smtp)",
        "smtp_code": 250,
    }

    validator = EmailValidator(
        enable_smtp_handshake=True,
        smtp_verifier=mock_smtp_verifier,
    )

    # 1. Test personal decision maker email
    res = validator.validate("ceo@company.com")
    assert res["status"] == "valid"
    assert res["sub_status"] == "smtp_accepted"
    assert res["is_deliverable"] is True
    assert res["is_role_account"] is False
    assert res["is_disposable"] is False

    # 2. Test disposable email rejected before touching SMTP
    mock_smtp_verifier.verify_mailbox.reset_mock()
    disp_res = validator.validate("junk@10minutemail.com")
    assert disp_res["status"] == "invalid"
    assert disp_res["sub_status"] == "disposable_email"
    mock_smtp_verifier.verify_mailbox.assert_not_called()

    # 3. Test malformed syntax rejected before touching SMTP
    syntax_res = validator.validate("user..name@company.com")
    assert syntax_res["status"] == "invalid"
    assert syntax_res["sub_status"] == "malformed_syntax"
    mock_smtp_verifier.verify_mailbox.assert_not_called()
