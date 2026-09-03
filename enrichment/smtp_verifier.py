import logging
import os
import random
import smtplib
import socket
import string
from typing import Any

import dns.resolver

logger = logging.getLogger(__name__)


class SmtpVerifier:
    """
    Self-hosted 100% free SMTP Handshake Verifier.
    Verifies if a specific mailbox actually exists on the target mail server
    using standard SMTP protocol (RCPT TO) without sending any actual email.
    """

    def __init__(
        self,
        sender_domain: str | None = None,
        sender_email: str | None = None,
        timeout: int = 6,
        check_catchall: bool = True,
    ):
        self.sender_domain = sender_domain or os.getenv("SMTP_VERIFY_DOMAIN", "signal.nexidant.com")
        self.sender_email = sender_email or f"verify@{self.sender_domain}"
        self.timeout = timeout
        self.check_catchall = check_catchall

    def get_mx_hosts(self, domain: str) -> list[str]:
        """
        Retrieves DNS MX hosts for the given domain sorted by priority.
        """
        clean_dom = domain.lower().strip().removeprefix("www.")
        try:
            resolver = dns.resolver.Resolver()
            resolver.timeout = 3.0
            resolver.lifetime = 3.0
            answers = resolver.resolve(clean_dom, "MX")
            sorted_answers = sorted(answers, key=lambda r: r.preference)
            return [str(r.exchange).rstrip(".") for r in sorted_answers]
        except Exception as e:
            logger.debug(f"DNS MX lookup failed for {clean_dom}: {e}")
            return []

    def _generate_random_mailbox(self, domain: str) -> str:
        rand_str = "".join(random.choices(string.ascii_lowercase + string.digits, k=14))
        return f"chk_{rand_str}@{domain}"

    def verify_mailbox(self, email: str) -> dict[str, Any]:
        """
        Performs an SMTP handshake to test if the recipient email mailbox exists.

        Returns:
            dict containing:
                - is_deliverable: bool
                - status: 'valid' | 'invalid' | 'catch_all' | 'unknown'
                - score: float
                - source: 'smtp_handshake'
                - reason: str
                - smtp_code: int | None
        """
        if not email or "@" not in email:
            return {
                "is_deliverable": False,
                "status": "invalid",
                "score": 0.0,
                "source": "smtp_handshake",
                "reason": "Malformed email address",
                "smtp_code": None,
            }

        domain = email.split("@")[1].lower().strip()
        mx_hosts = self.get_mx_hosts(domain)

        if not mx_hosts:
            return {
                "is_deliverable": False,
                "status": "invalid",
                "score": 0.0,
                "source": "smtp_handshake",
                "reason": f"No active MX records found for {domain}",
                "smtp_code": None,
            }

        last_error = "Connection failed"
        last_code = None

        for mx_host in mx_hosts[:2]:  # Try primary and secondary MX servers
            server = None
            try:
                server = smtplib.SMTP(timeout=self.timeout)
                server.connect(mx_host, 25)
                server.ehlo(self.sender_domain)

                # Send MAIL FROM
                code, msg = server.mail(self.sender_email)
                if code not in [250, 251]:
                    last_error = f"MAIL FROM rejected by {mx_host}: {code}"
                    last_code = code
                    server.quit()
                    continue

                # Test target email RCPT TO
                rcpt_code, rcpt_msg = server.rcpt(email)
                last_code = rcpt_code
                msg_str = rcpt_msg.decode("utf-8", errors="ignore") if isinstance(rcpt_msg, bytes) else str(rcpt_msg)

                # Case 1: Mailbox directly rejected by server (Hard bounce prevented!)
                if rcpt_code in [550, 551, 552, 553, 554]:
                    server.quit()
                    return {
                        "is_deliverable": False,
                        "status": "invalid",
                        "score": 0.0,
                        "source": "smtp_handshake",
                        "reason": f"Mailbox rejected by {mx_host}: {rcpt_code} {msg_str[:80]}",
                        "smtp_code": rcpt_code,
                    }

                # Case 2: Mailbox accepted (250 OK)
                if rcpt_code in [250, 251]:
                    # Check for catch-all if configured
                    is_catchall = False
                    if self.check_catchall:
                        probe_email = self._generate_random_mailbox(domain)
                        probe_code, _ = server.rcpt(probe_email)
                        if probe_code in [250, 251]:
                            is_catchall = True

                    server.quit()

                    if is_catchall:
                        return {
                            "is_deliverable": True,
                            "status": "catch_all",
                            "score": 65.0,
                            "source": "smtp_handshake",
                            "reason": f"Domain {domain} is catch-all (accepts all addresses)",
                            "smtp_code": rcpt_code,
                        }

                    return {
                        "is_deliverable": True,
                        "status": "valid",
                        "score": 95.0,
                        "source": "smtp_handshake",
                        "reason": f"Mailbox verified deliverable on {mx_host} (250 OK)",
                        "smtp_code": rcpt_code,
                    }

                # Case 3: Temporary greylisting or rate limit
                if rcpt_code in [421, 450, 451, 452]:
                    server.quit()
                    return {
                        "is_deliverable": False,
                        "status": "unknown",
                        "score": 50.0,
                        "source": "smtp_handshake",
                        "reason": f"Mail server greylisted/rate-limited verification: {rcpt_code}",
                        "smtp_code": rcpt_code,
                    }

            except (socket.timeout, TimeoutError):
                last_error = f"Connection timed out to {mx_host}:25"
            except (ConnectionRefusedError, socket.gaierror, OSError) as conn_err:
                last_error = f"Could not connect to {mx_host}:25 ({conn_err})"
            except Exception as e:
                last_error = f"SMTP error with {mx_host}: {e}"
            finally:
                if server:
                    try:
                        server.close()
                    except Exception:
                        pass

        # If all MX servers were unreachable or timed out (e.g. port 25 blocked)
        return {
            "is_deliverable": False,
            "status": "unknown",
            "score": 40.0,
            "source": "smtp_handshake",
            "reason": last_error,
            "smtp_code": last_code,
        }


def get_smtp_verifier() -> SmtpVerifier:
    return SmtpVerifier()
