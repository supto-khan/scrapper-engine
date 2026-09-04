from unittest.mock import MagicMock, patch

from enrichment.smtp_verifier import SmtpVerifier, get_smtp_verifier


def test_smtp_verifier_singleton():
    """
    Ensures get_smtp_verifier() returns the same singleton instance
    so that in-memory catch-all caching persists across calls.
    """
    v1 = get_smtp_verifier()
    v2 = get_smtp_verifier()
    assert v1 is v2


def test_smtp_verifier_valid_mailbox_confidence_by_provider():
    verifier = SmtpVerifier(check_catchall=False)
    # Google Workspace should get 65.0 confidence
    with patch.object(verifier, "get_mx_hosts", return_value=["aspmx.l.google.com"]):
        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = (250, b"OK")
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.return_value = (250, b"Recipient OK")

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("test@googlecorp.com")
            assert res["is_deliverable"] is True
            assert res["status"] == "valid"
            assert res["sub_status"] == "smtp_accepted"
            assert res["provider"] == "google_workspace"
            assert res["confidence"] == 65.0

    # Custom SMTP should get 85.0 confidence
    with patch.object(verifier, "get_mx_hosts", return_value=["mail.customcorp.com"]):
        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = (250, b"OK")
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.return_value = (250, b"Recipient OK")

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("test@customcorp.com")
            assert res["provider"] == "custom_smtp"
            assert res["confidence"] == 85.0


def test_smtp_verifier_invalid_mailbox_positive_user_unknown_match():
    verifier = SmtpVerifier(check_catchall=False)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com"]):
        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = (250, b"OK")
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.return_value = (550, b"5.1.1 User unknown")

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("nonexistent@example.com")
            assert res["is_deliverable"] is False
            assert res["status"] == "invalid"
            assert res["sub_status"] == "mailbox_not_found"
            assert res["confidence"] == 0.0


def test_smtp_verifier_generic_5xx_not_flattened_to_mailbox_not_found():
    """
    Ensures ambiguous 5xx responses (e.g. 554 Transaction failed) are categorized
    as 'generic_5xx_rejection' instead of falsely claiming the mailbox does not exist.
    """
    verifier = SmtpVerifier(check_catchall=False)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com"]):
        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = (250, b"OK")
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.return_value = (554, b"Transaction failed")

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("ambiguous@example.com")
            assert res["is_deliverable"] is False
            assert res["status"] == "unknown"
            assert res["sub_status"] == "generic_5xx_rejection"
            assert res["confidence"] == 25.0


def test_smtp_verifier_safe_quit_on_server_hangup():
    verifier = SmtpVerifier(check_catchall=False)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com"]):
        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = (250, b"OK")
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.return_value = (550, b"5.1.1 Recipient address rejected")
        mock_smtp.quit.side_effect = BrokenPipeError("Connection reset by peer")

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("dead_user@example.com")
            assert res["is_deliverable"] is False
            assert res["status"] == "invalid"
            assert res["sub_status"] == "mailbox_not_found"


def test_smtp_verifier_multi_mx_retry_on_4xx():
    """
    Ensures that when MX1 returns a temporary 451 greylist, the verifier
    continues to MX2 and succeeds if MX2 accepts.
    """
    verifier = SmtpVerifier(check_catchall=False)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com", "mx2.example.com"]):
        mock_smtp1 = MagicMock()
        mock_smtp1.ehlo.return_value = (250, b"OK")
        mock_smtp1.mail.return_value = (250, b"Sender OK")
        mock_smtp1.rcpt.return_value = (451, b"4.7.1 Greylisted, please try later")

        mock_smtp2 = MagicMock()
        mock_smtp2.ehlo.return_value = (250, b"OK")
        mock_smtp2.mail.return_value = (250, b"Sender OK")
        mock_smtp2.rcpt.return_value = (250, b"Recipient OK")

        with patch("smtplib.SMTP", side_effect=[mock_smtp1, mock_smtp2]):
            res = verifier.verify_mailbox("person@example.com")
            assert res["is_deliverable"] is True
            assert res["status"] == "valid"
            assert res["sub_status"] == "smtp_accepted"


def test_smtp_verifier_catchall_caching():
    verifier = SmtpVerifier(check_catchall=True)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com"]):
        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = (250, b"OK")
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.side_effect = [
            (250, b"OK"),
            (250, b"Probe OK"),
            (250, b"OK"),
        ]

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res1 = verifier.verify_mailbox("person1@catchalldomain.com")
            assert res1["status"] == "catch_all"
            assert verifier.catchall_cache["catchalldomain.com"]["is_catchall"] is True

            res2 = verifier.verify_mailbox("person2@catchalldomain.com")
            assert res2["status"] == "catch_all"
            assert mock_smtp.rcpt.call_count == 3


def test_catch_all_checked_false_when_check_catchall_disabled():
    """
    Refinement 1: When check_catchall=False, catch_all.checked must be False,
    never claiming a probe ran when it was intentionally disabled.
    """
    verifier = SmtpVerifier(check_catchall=False)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com"]):
        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = (250, b"OK")
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.return_value = (250, b"Recipient OK")

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("test@example.com")
            assert res["status"] == "valid"
            assert res["catch_all"] == {"checked": False, "detected": False}


def test_redis_cross_worker_catchall_cache():
    """
    Refinement 2: Ensures catch-all lookups query and populate Redis
    so independent worker processes share domain catch-all verdicts.
    """
    mock_redis_client = MagicMock()
    mock_redis_client.client.get.return_value = None  # Cache miss first time

    verifier = SmtpVerifier(check_catchall=True, redis_client=mock_redis_client)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com"]):
        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = (250, b"OK")
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.side_effect = [
            (250, b"OK"),
            (250, b"Catch-all probe accepted"),
        ]

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("test@redisdomain.com")
            assert res["status"] == "catch_all"
            assert res["catch_all"] == {"checked": True, "detected": True}

            # Verify SETEX was called on Redis with rich JSON metadata
            assert mock_redis_client.client.setex.call_count == 1
            call_args = mock_redis_client.client.setex.call_args[0]
            assert call_args[0] == "email_verifier:catchall:redisdomain.com"
            assert call_args[1] == 43200
            import json
            payload = json.loads(call_args[2])
            assert payload["is_catchall"] is True
            assert payload["domain"] == "redisdomain.com"
            assert payload["mx_host"] == "mx1.example.com"

    # Now simulate a second worker process reading the Redis key
    mock_redis_worker2 = MagicMock()
    mock_redis_worker2.client.get.return_value = "1"  # Cached as catch-all
    worker2_verifier = SmtpVerifier(check_catchall=True, redis_client=mock_redis_worker2)

    with patch.object(worker2_verifier, "get_mx_hosts", return_value=["mx1.example.com"]):
        mock_smtp2 = MagicMock()
        mock_smtp2.ehlo.return_value = (250, b"OK")
        mock_smtp2.mail.return_value = (250, b"Sender OK")
        mock_smtp2.rcpt.return_value = (250, b"OK")

        with patch("smtplib.SMTP", return_value=mock_smtp2):
            res2 = worker2_verifier.verify_mailbox("another@redisdomain.com")
            assert res2["status"] == "catch_all"
            # No second probe email was sent to SMTP server because Redis had it
            assert mock_smtp2.rcpt.call_count == 1


def test_stale_last_code_does_not_mislabel_subsequent_timeout():
    """
    Refinement 3: If MX1 returns 451 greylisted and MX2 encounters a socket timeout,
    the failure must be reported as connection_failed (timeout), NOT greylisted.
    """
    import socket

    verifier = SmtpVerifier(check_catchall=False)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com", "mx2.example.com"]):
        mock_smtp1 = MagicMock()
        mock_smtp1.ehlo.return_value = (250, b"OK")
        mock_smtp1.mail.return_value = (250, b"Sender OK")
        mock_smtp1.rcpt.return_value = (451, b"4.7.1 Greylisted")

        mock_smtp2 = MagicMock()
        mock_smtp2.connect.side_effect = socket.timeout("Timed out connecting to port 25")

        with patch("smtplib.SMTP", side_effect=[mock_smtp1, mock_smtp2]):
            res = verifier.verify_mailbox("test@timeoutaftergrey.com")
            assert res["status"] == "unknown"
            assert res["sub_status"] == "connection_failed"
            assert res["smtp_code"] is None
            assert "Connection timed out" in res["reason"]


def test_custom_provider_weights_override():
    """
    Refinement 4: Provider confidence weights should be configurable and overridable
    via provider_weights parameter in SmtpVerifier.
    """
    verifier = SmtpVerifier(
        check_catchall=False,
        provider_weights={"google_workspace": 92.5},
    )
    with patch.object(verifier, "get_mx_hosts", return_value=["aspmx.l.google.com"]):
        mock_smtp = MagicMock()
        mock_smtp.ehlo.return_value = (250, b"OK")
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.return_value = (250, b"Recipient OK")

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("test@googlecorp.com")
            assert res["status"] == "valid"
            assert res["confidence"] == 92.5
            assert res["score"] == 92.5


def test_mx_priority_and_authoritative_metadata():
    """
    Refinement 5: Response metadata tracks mx_priority and mx_primary so downstream
    code knows if a secondary/spool MX responded.
    """
    verifier = SmtpVerifier(check_catchall=False)
    # When secondary MX answers
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com", "mx2.example.com"]):
        mock_smtp1 = MagicMock()
        mock_smtp1.ehlo.return_value = (250, b"OK")
        mock_smtp1.mail.return_value = (250, b"Sender OK")
        mock_smtp1.rcpt.return_value = (451, b"Greylisted")

        mock_smtp2 = MagicMock()
        mock_smtp2.ehlo.return_value = (250, b"OK")
        mock_smtp2.mail.return_value = (250, b"Sender OK")
        mock_smtp2.rcpt.return_value = (250, b"Recipient OK")

        with patch("smtplib.SMTP", side_effect=[mock_smtp1, mock_smtp2]):
            res = verifier.verify_mailbox("test@backupmx.com")
            assert res["status"] == "valid"
            assert res["domain"]["mx_host"] == "mx2.example.com"
            assert res["domain"]["mx_rank"] == 2
            assert res["domain"]["mx_preference"] == 20
            assert res["domain"]["mx_primary"] is False
            assert "backup MX" in res["reason"]

