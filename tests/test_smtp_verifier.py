from unittest.mock import MagicMock, patch

from enrichment.smtp_verifier import SmtpVerifier


def test_smtp_verifier_valid_mailbox():
    verifier = SmtpVerifier(check_catchall=False)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com"]):
        mock_smtp = MagicMock()
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.return_value = (250, b"Recipient OK")

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("valid@example.com")
            assert res["is_deliverable"] is True
            assert res["status"] == "valid"
            assert res["smtp_code"] == 250


def test_smtp_verifier_invalid_mailbox_550():
    verifier = SmtpVerifier(check_catchall=False)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com"]):
        mock_smtp = MagicMock()
        mock_smtp.mail.return_value = (250, b"Sender OK")
        mock_smtp.rcpt.return_value = (550, b"User unknown")

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("nonexistent@example.com")
            assert res["is_deliverable"] is False
            assert res["status"] == "invalid"
            assert res["smtp_code"] == 550
            assert "rejected" in res["reason"].lower()


def test_smtp_verifier_catchall_detection():
    verifier = SmtpVerifier(check_catchall=True)
    with patch.object(verifier, "get_mx_hosts", return_value=["mx1.example.com"]):
        mock_smtp = MagicMock()
        mock_smtp.mail.return_value = (250, b"Sender OK")
        # Target email returns 250, probe email also returns 250
        mock_smtp.rcpt.side_effect = [(250, b"OK"), (250, b"Catch-all OK")]

        with patch("smtplib.SMTP", return_value=mock_smtp):
            res = verifier.verify_mailbox("test@example.com")
            assert res["is_deliverable"] is True
            assert res["status"] == "catch_all"


def test_smtp_verifier_no_mx():
    verifier = SmtpVerifier()
    with patch.object(verifier, "get_mx_hosts", return_value=[]):
        res = verifier.verify_mailbox("test@nomxdomain.xyz")
        assert res["is_deliverable"] is False
        assert res["status"] == "invalid"
