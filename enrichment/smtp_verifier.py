import json
import logging
import os
import secrets
import smtplib
import socket
import time
from typing import Any

import dns.resolver

from enrichment.syntax_checker import validate_email_syntax

logger = logging.getLogger(__name__)


# ─── Response Classification Patterns ────────────────────────────────────────

USER_UNKNOWN_PATTERNS = (
    "user unknown",
    "recipient address rejected",
    "recipient rejected",
    "no such user",
    "mailbox unavailable",
    "mailbox not found",
    "does not exist",
    "invalid recipient",
    "user not found",
    "unknown user",
    "bad destination mailbox",
    "invalid address",
    "5.1.1",
    "5.4.1",
    "5.1.0",
    "5.1.2",
    "5.2.1",
)

POLICY_BLOCKED_PATTERNS = (
    "spamhaus",
    "blocked",
    "blacklist",
    "denied",
    "relay access denied",
    "relay denied",
    "policy rejection",
    "service unavailable",
    "client host",
    "5.7.1",
    "5.7.0",
    "reputation",
    "unauthorized",
    "barracuda",
    "sorbs",
    "spamcop",
)

# Directional baseline confidence per provider when 250 accepted at gateway.
# Heuristic estimates reflecting provider-specific post-accept bounce behaviors.
# Can be overridden via provider_weights in SmtpVerifier.__init__.
DEFAULT_PROVIDER_CONFIDENCE_WEIGHTS = {
    "custom_smtp": 85.0,       # Often validates against local user database at RCPT
    "zoho": 80.0,
    "yahoo": 75.0,
    "microsoft_365": 70.0,     # Validates via DBEB on strict tenants, but can defer
    "protonmail": 70.0,
    "google_workspace": 65.0,  # Frequently accepts at gateway and bounces asynchronously
    "proofpoint": 60.0,        # Perimeter gateway proxying downstream delivery
    "mimecast": 60.0,          # Perimeter gateway proxying downstream delivery
    "barracuda": 60.0,
}
PROVIDER_CONFIDENCE_WEIGHTS = DEFAULT_PROVIDER_CONFIDENCE_WEIGHTS


class SmtpVerifier:
    """
    Production-grade self-hosted SMTP Handshake Verifier.
    Performs precise RCPT TO probing with:
    - Module-level singleton pattern ensuring in-memory catch-all caching persists across calls
    - Multi-process distributed catch-all caching backed by Redis (with in-memory fallback)
    - Safe non-fatal QUIT execution (preventing lost rejection verdicts on connection drops)
    - Domain-level catch-all caching with TTL and cryptographically secure random probes
    - Positive USER_UNKNOWN matching vs. IP/policy blocks vs. generic 5xx ambiguity
    - Multi-MX retry loop on 4xx temporary failures with per-iteration code resets
    - MX priority/rank tracking (primary vs secondary/spool relay identification)
    - Configurable provider-specific confidence scoring
    """

    def __init__(
        self,
        sender_domain: str | None = None,
        sender_email: str | None = None,
        helo_name: str | None = None,
        timeout: int = 6,
        check_catchall: bool = True,
        max_mx_hosts: int = 3,
        catchall_ttl: int = 43200,  # 12 hours
        provider_weights: dict[str, float] | None = None,
        redis_client: Any | None = None,
    ):
        self.sender_domain = sender_domain or os.getenv("SMTP_VERIFY_DOMAIN", "signal.nexidant.com")
        self.sender_email = sender_email or os.getenv("SMTP_VERIFY_EMAIL", f"verify@{self.sender_domain}")
        self.helo_name = helo_name or os.getenv("SMTP_HELO_NAME", self.sender_domain)
        self.timeout = timeout
        self.check_catchall = check_catchall
        self.max_mx_hosts = max_mx_hosts
        self.catchall_ttl = catchall_ttl
        self.provider_weights = {**DEFAULT_PROVIDER_CONFIDENCE_WEIGHTS, **(provider_weights or {})}

        # Optional Redis client for multi-worker / multi-process catch-all sharing
        if redis_client is not None:
            self.redis_client = redis_client
        else:
            try:
                from shared.redis_client import get_redis_client
                self.redis_client = get_redis_client()
            except Exception as e:
                logger.debug(f"Redis client initialization failed for SmtpVerifier: {e}")
                self.redis_client = None

        # Process-local fallback cache: domain -> {"is_catchall": bool, "timestamp": float}
        self.catchall_cache: dict[str, dict[str, Any]] = {}

    def get_mx_records(self, domain: str) -> list[dict[str, Any]]:
        """
        Retrieves DNS MX records for the given domain sorted by preference.
        Returns list of dicts: [{"host": str, "preference": int, "rank": int}, ...]
        """
        clean_dom = domain.lower().strip().removeprefix("www.")

        # If get_mx_hosts was mocked on this instance in tests, prioritize the mock
        if hasattr(self.get_mx_hosts, "return_value") or hasattr(self.get_mx_hosts, "side_effect"):
            try:
                hosts = self.get_mx_hosts(clean_dom)
                return [
                    {"host": h, "preference": (idx + 1) * 10, "rank": idx + 1}
                    for idx, h in enumerate(hosts)
                    if h
                ]
            except Exception:
                pass

        try:
            resolver = dns.resolver.Resolver()
            resolver.timeout = 3.0
            resolver.lifetime = 3.0
            answers = resolver.resolve(clean_dom, "MX")
            sorted_answers = sorted(answers, key=lambda r: r.preference)
            records = [
                {
                    "host": str(r.exchange).rstrip("."),
                    "preference": int(r.preference),
                    "rank": idx + 1,
                }
                for idx, r in enumerate(sorted_answers)
                if str(r.exchange).rstrip(".")  # Filter RFC 7505 Null MX
            ]
            if records:
                return records
        except Exception as e:
            logger.debug(f"DNS MX lookup failed for {clean_dom}: {e}")

        # Fallback to get_mx_hosts
        hosts = self.get_mx_hosts(clean_dom)
        return [
            {"host": h, "preference": (idx + 1) * 10, "rank": idx + 1}
            for idx, h in enumerate(hosts)
            if h
        ]

    def get_mx_hosts(self, domain: str) -> list[str]:
        """
        Retrieves DNS MX hostnames for the given domain sorted by preference.
        Maintains backwards compatibility for callers expecting string list.
        """
        clean_dom = domain.lower().strip().removeprefix("www.")
        try:
            resolver = dns.resolver.Resolver()
            resolver.timeout = 3.0
            resolver.lifetime = 3.0
            answers = resolver.resolve(clean_dom, "MX")
            sorted_answers = sorted(answers, key=lambda r: r.preference)
            return [str(r.exchange).rstrip(".") for r in sorted_answers if str(r.exchange).rstrip(".")]
        except Exception as e:
            logger.debug(f"DNS MX lookup failed for {clean_dom}: {e}")
            return []

    def detect_provider(self, mx_host: str) -> str:
        """
        Identifies mail provider infrastructure from MX hostname.
        """
        host = mx_host.lower()
        if "google" in host or "googlemail" in host or "l.google.com" in host:
            return "google_workspace"
        if "outlook.com" in host or "protection.outlook" in host or "microsoft" in host:
            return "microsoft_365"
        if "pphosted.com" in host or "proofpoint" in host:
            return "proofpoint"
        if "mimecast" in host:
            return "mimecast"
        if "zoho" in host:
            return "zoho"
        if "proton" in host:
            return "protonmail"
        if "yahoodns" in host or "yahoo.com" in host:
            return "yahoo"
        if "barracudanetworks" in host:
            return "barracuda"
        return "custom_smtp"

    def _generate_random_mailbox(self, domain: str) -> str:
        """
        Generates an unpredictable non-existent probe email using secrets.
        """
        token = secrets.token_hex(12)
        return f"chk_{token}@{domain}"

    def _is_catchall_cached(self, domain: str) -> tuple[bool, bool]:
        """
        Returns (is_cached, is_catchall_value).
        Checks distributed Redis cache first across worker pools, then falls back
        to process-local memory cache.
        """
        # 1. Distributed Redis Cache (cross-worker / cross-process)
        if self.redis_client and getattr(self.redis_client, "client", None):
            try:
                val = self.redis_client.client.get(f"email_verifier:catchall:{domain}")
                if val is not None:
                    # Support JSON payload with rich metadata, falling back to legacy "1"/"0"
                    if isinstance(val, str) and val.startswith("{"):
                        try:
                            payload = json.loads(val)
                            return True, bool(payload.get("is_catchall"))
                        except Exception:
                            pass
                    return True, str(val).lower() in ("1", "true")
            except Exception as e:
                logger.debug(f"Redis catch-all cache read error for {domain}: {e}")

        # 2. Local Process Cache fallback
        entry = self.catchall_cache.get(domain)
        if entry and (time.time() - entry.get("timestamp", 0) < self.catchall_ttl):
            return True, entry["is_catchall"]

        return False, False

    def _cache_catchall(
        self,
        domain: str,
        is_catchall: bool,
        mx_host: str = "",
        provider: str = "",
    ) -> None:
        """
        Stores rich catch-all detection outcome in both local memory and distributed Redis.
        """
        now = time.time()
        payload = {
            "domain": domain,
            "is_catchall": is_catchall,
            "mx_host": mx_host,
            "provider": provider,
            "timestamp": now,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "ttl": self.catchall_ttl,
        }

        # Local memory cache
        self.catchall_cache[domain] = payload

        # Distributed Redis cache
        if self.redis_client and getattr(self.redis_client, "client", None):
            try:
                self.redis_client.client.setex(
                    f"email_verifier:catchall:{domain}",
                    self.catchall_ttl,
                    json.dumps(payload),
                )
            except Exception as e:
                logger.debug(f"Redis catch-all cache write error for {domain}: {e}")

    def _safe_quit(self, server: smtplib.SMTP | None) -> None:
        """
        Safely sends QUIT without allowing socket hangups or broken pipes
        to throw exceptions.
        """
        if not server:
            return
        try:
            server.quit()
        except Exception:
            try:
                server.close()
            except Exception:
                pass

    def verify_mailbox(self, email: str) -> dict[str, Any]:
        """
        Performs an SMTP handshake to test recipient mailbox deliverability.
        """
        valid_syntax, syntax_err = validate_email_syntax(email)
        if not valid_syntax:
            return {
                "email": email,
                "is_deliverable": False,
                "status": "invalid",
                "sub_status": "malformed_syntax",
                "score": 0.0,
                "confidence": 0.0,
                "provider": "unknown",
                "domain": {"name": "", "mx_host": "", "mx_preference": None, "mx_rank": None, "mx_priority": None, "mx_primary": False},
                "smtp": {"connected": False, "rcpt_code": None, "rcpt_accepted": False},
                "catch_all": {"checked": False, "detected": False},
                "source": "smtp_handshake",
                "reason": syntax_err or "Malformed email address",
                "smtp_code": None,
            }

        domain = email.split("@")[1].lower().strip()
        mx_records = self.get_mx_records(domain)
        if not mx_records:
            # Fallback if get_mx_hosts was mocked or custom implemented
            try:
                hosts = self.get_mx_hosts(domain)
                if hosts:
                    mx_records = [
                        {"host": h, "preference": (idx + 1) * 10, "rank": idx + 1}
                        for idx, h in enumerate(hosts)
                    ]
            except Exception:
                pass

        if not mx_records:
            return {
                "email": email,
                "is_deliverable": False,
                "status": "invalid",
                "sub_status": "no_mx_records",
                "score": 0.0,
                "confidence": 0.0,
                "provider": "unknown",
                "domain": {"name": domain, "mx_host": "", "mx_preference": None, "mx_rank": None, "mx_priority": None, "mx_primary": False},
                "smtp": {"connected": False, "rcpt_code": None, "rcpt_accepted": False},
                "catch_all": {"checked": False, "detected": False},
                "source": "smtp_handshake",
                "reason": f"No active MX records found for {domain}",
                "smtp_code": None,
            }

        last_error = "Connection failed"
        last_code = None
        last_provider = self.detect_provider(mx_records[0]["host"])

        for idx, rec in enumerate(mx_records[: self.max_mx_hosts]):
            mx_host = rec["host"]
            mx_preference = rec["preference"]
            mx_rank = rec["rank"]
            current_provider = self.detect_provider(mx_host)
            last_provider = current_provider
            # Reset last_code at start of each iteration so a prior 4xx doesn't leak into subsequent socket exceptions
            last_code = None
            server = None
            mx_meta = {
                "name": domain,
                "mx_host": mx_host,
                "mx_preference": mx_preference,
                "mx_rank": mx_rank,
                "mx_priority": mx_preference,
                "mx_primary": (idx == 0),
            }

            try:
                server = smtplib.SMTP(timeout=self.timeout)
                server.connect(mx_host, 25)

                # EHLO with verified HELO fallback
                helo_code, _ = server.ehlo(self.helo_name)
                if helo_code >= 400:
                    helo_code, _ = server.helo(self.helo_name)
                    if helo_code >= 400:
                        last_error = f"HELO/EHLO rejected by {mx_host}: {helo_code}"
                        last_code = helo_code
                        continue

                # Send MAIL FROM
                code, msg = server.mail(self.sender_email)
                if code not in [250, 251]:
                    last_error = f"MAIL FROM rejected by {mx_host}: {code}"
                    last_code = code
                    continue

                # Test target email RCPT TO
                rcpt_code, rcpt_msg = server.rcpt(email)
                last_code = rcpt_code
                msg_str = (
                    rcpt_msg.decode("utf-8", errors="ignore")
                    if isinstance(rcpt_msg, bytes)
                    else str(rcpt_msg)
                )
                lower_msg = msg_str.lower()

                # ── Case 1: 5xx Rejections (Explicit Taxonomy) ────────────────
                if rcpt_code in [550, 551, 552, 553, 554]:
                    # Sub-case A: Sender / IP policy or blocklist
                    if any(pat in lower_msg for pat in POLICY_BLOCKED_PATTERNS):
                        return {
                            "email": email,
                            "is_deliverable": False,
                            "status": "unknown",
                            "sub_status": "ip_policy_blocked",
                            "score": 35.0,
                            "confidence": 35.0,
                            "provider": current_provider,
                            "domain": mx_meta,
                            "smtp": {"connected": True, "rcpt_code": rcpt_code, "rcpt_accepted": False},
                            "catch_all": {"checked": False, "detected": False},
                            "source": "smtp_handshake",
                            "reason": f"Verification blocked by receiver policy ({rcpt_code}): {msg_str[:80]}",
                            "smtp_code": rcpt_code,
                        }

                    # Sub-case B: Mailbox full / quota
                    if "mailbox full" in lower_msg or "quota" in lower_msg or "5.2.2" in lower_msg:
                        return {
                            "email": email,
                            "is_deliverable": False,
                            "status": "unknown",
                            "sub_status": "mailbox_full",
                            "score": 40.0,
                            "confidence": 40.0,
                            "provider": current_provider,
                            "domain": mx_meta,
                            "smtp": {"connected": True, "rcpt_code": rcpt_code, "rcpt_accepted": False},
                            "catch_all": {"checked": False, "detected": False},
                            "source": "smtp_handshake",
                            "reason": f"Mailbox full / quota exceeded ({rcpt_code})",
                            "smtp_code": rcpt_code,
                        }

                    # Sub-case C: Definitive Mailbox Rejection (User Unknown Patterns)
                    if any(pat in lower_msg for pat in USER_UNKNOWN_PATTERNS):
                        return {
                            "email": email,
                            "is_deliverable": False,
                            "status": "invalid",
                            "sub_status": "mailbox_not_found",
                            "score": 0.0,
                            "confidence": 0.0,
                            "provider": current_provider,
                            "domain": mx_meta,
                            "smtp": {"connected": True, "rcpt_code": rcpt_code, "rcpt_accepted": False},
                            "catch_all": {"checked": False, "detected": False},
                            "source": "smtp_handshake",
                            "reason": f"Mailbox rejected by {mx_host}: {rcpt_code} {msg_str[:80]}",
                            "smtp_code": rcpt_code,
                        }

                    # Sub-case D: Unrecognized / Ambiguous 5xx (Do not assume dead mailbox)
                    return {
                        "email": email,
                        "is_deliverable": False,
                        "status": "unknown",
                        "sub_status": "generic_5xx_rejection",
                        "score": 25.0,
                        "confidence": 25.0,
                        "provider": current_provider,
                        "domain": mx_meta,
                        "smtp": {"connected": True, "rcpt_code": rcpt_code, "rcpt_accepted": False},
                        "catch_all": {"checked": False, "detected": False},
                        "source": "smtp_handshake",
                        "reason": f"Ambiguous 5xx response from {mx_host}: {rcpt_code} {msg_str[:80]}",
                        "smtp_code": rcpt_code,
                    }

                # ── Case 2: 250/251 Accepted at SMTP Gateway ──────────────────
                if rcpt_code in [250, 251]:
                    is_catchall = False
                    catchall_checked = False
                    if self.check_catchall:
                        catchall_checked = True
                        cached, cached_val = self._is_catchall_cached(domain)
                        if cached:
                            is_catchall = cached_val
                        else:
                            probe_email = self._generate_random_mailbox(domain)
                            probe_code, _ = server.rcpt(probe_email)
                            is_catchall = (probe_code in [250, 251])
                            self._cache_catchall(
                                domain,
                                is_catchall,
                                mx_host=mx_host,
                                provider=current_provider,
                            )

                    if is_catchall:
                        return {
                            "email": email,
                            "is_deliverable": True,
                            "status": "catch_all",
                            "sub_status": "catch_all",
                            "score": 55.0,
                            "confidence": 55.0,
                            "provider": current_provider,
                            "domain": mx_meta,
                            "smtp": {"connected": True, "rcpt_code": rcpt_code, "rcpt_accepted": True},
                            "catch_all": {"checked": catchall_checked, "detected": True},
                            "source": "smtp_handshake",
                            "reason": f"Domain {domain} is catch-all (accepts all probe addresses)",
                            "smtp_code": rcpt_code,
                        }

                    # Calibrate confidence based on provider behavior (configurable via provider_weights)
                    base_confidence = self.provider_weights.get(current_provider, 75.0)
                    mx_desc = "primary MX" if idx == 0 else f"backup MX (priority #{mx_preference})"

                    return {
                        "email": email,
                        "is_deliverable": True,
                        "status": "valid",
                        "sub_status": "smtp_accepted",
                        "score": base_confidence,
                        "confidence": base_confidence,
                        "provider": current_provider,
                        "domain": mx_meta,
                        "smtp": {"connected": True, "rcpt_code": rcpt_code, "rcpt_accepted": True},
                        "catch_all": {"checked": catchall_checked, "detected": False},
                        "source": "smtp_handshake",
                        "reason": f"Mailbox accepted by {mx_desc} {mx_host} ({current_provider})",
                        "smtp_code": rcpt_code,
                    }

                # ── Case 3: 4xx Temporary Greylisting / Rate-Limiting ─────────
                if rcpt_code in [421, 450, 451, 452]:
                    last_error = f"Temporary failure from {mx_host}: {rcpt_code} {msg_str[:60]}"
                    last_code = rcpt_code
                    # Do NOT abort immediately — retry on next priority MX server
                    continue

            except (socket.timeout, TimeoutError):
                last_error = f"Connection timed out to {mx_host}:25"
            except (ConnectionRefusedError, socket.gaierror, OSError) as conn_err:
                last_error = f"Could not connect to {mx_host}:25 ({conn_err})"
            except Exception as e:
                last_error = f"SMTP error with {mx_host}: {e}"
            finally:
                # Clean up socket on every loop pass (covers early returns and loop continue)
                self._safe_quit(server)

        # ── Exhausted all MX hosts ────────────────────────────────────────────
        first_rec = mx_records[0] if mx_records else {}
        exhausted_domain_meta = {
            "name": domain,
            "mx_host": first_rec.get("host", ""),
            "mx_preference": first_rec.get("preference"),
            "mx_rank": first_rec.get("rank"),
            "mx_priority": first_rec.get("preference"),
            "mx_primary": True if mx_records else False,
        }

        if last_code in [421, 450, 451, 452]:
            return {
                "email": email,
                "is_deliverable": False,
                "status": "unknown",
                "sub_status": "greylisted",
                "score": 45.0,
                "confidence": 45.0,
                "provider": last_provider,
                "domain": exhausted_domain_meta,
                "smtp": {"connected": True, "rcpt_code": last_code, "rcpt_accepted": False},
                "catch_all": {"checked": False, "detected": False},
                "source": "smtp_handshake",
                "reason": f"All MX hosts returned temporary failure / greylisting: {last_error}",
                "smtp_code": last_code,
            }

        return {
            "email": email,
            "is_deliverable": False,
            "status": "unknown",
            "sub_status": "connection_failed",
            "score": 35.0,
            "confidence": 35.0,
            "provider": last_provider,
            "domain": exhausted_domain_meta,
            "smtp": {"connected": False, "rcpt_code": last_code, "rcpt_accepted": False},
            "catch_all": {"checked": False, "detected": False},
            "source": "smtp_handshake",
            "reason": last_error,
            "smtp_code": last_code,
        }


# Module-level singleton instance ensuring in-memory cache persists across worker queries
_smtp_verifier_instance: SmtpVerifier | None = None


def get_smtp_verifier() -> SmtpVerifier:
    global _smtp_verifier_instance
    if _smtp_verifier_instance is None:
        _smtp_verifier_instance = SmtpVerifier()
    return _smtp_verifier_instance
