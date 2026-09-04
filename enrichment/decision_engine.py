"""
Verification Decision Engine.
Evaluates multiple validation signals (syntax, disposable domain, role account,
DNS MX records, and raw SMTP handshake) to synthesize an authoritative deliverability verdict.
"""

from typing import Any, Dict


class DecisionEngine:
    """
    Synthesizes and classifies verification signals into a standardized taxonomy:
    
    Statuses:
        - valid
        - invalid
        - catch_all
        - unknown

    Sub-statuses:
        - smtp_accepted
        - mailbox_not_found
        - policy_blocked
        - mailbox_full
        - greylisted
        - generic_5xx_rejection
        - connection_failed
        - malformed_syntax
        - no_mx_records
        - disposable_email
        - role_account
    """

    @staticmethod
    def evaluate(
        email: str,
        syntax_valid: bool,
        syntax_error: str | None = None,
        is_disposable: bool = False,
        is_role: bool = False,
        role_prefix: str | None = None,
        has_mx: bool = True,
        mx_error: str | None = None,
        smtp_result: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        domain = email.split("@")[-1].lower().strip() if ("@" in (email or "")) else ""

        # 1. Syntax Check
        if not syntax_valid:
            return {
                "email": email,
                "status": "invalid",
                "sub_status": "malformed_syntax",
                "is_deliverable": False,
                "score": 0.0,
                "confidence": 0.0,
                "is_role_account": False,
                "is_disposable": False,
                "provider": "unknown",
                "domain": {"name": domain, "mx_host": "", "mx_preference": None, "mx_rank": None, "mx_primary": False},
                "smtp": {"connected": False, "rcpt_code": None, "rcpt_accepted": False},
                "catch_all": {"checked": False, "detected": False},
                "source": "syntax_check",
                "reason": syntax_error or "Invalid email syntax format",
                "smtp_code": None,
            }

        # 2. Disposable Email Filter
        if is_disposable:
            return {
                "email": email,
                "status": "invalid",
                "sub_status": "disposable_email",
                "is_deliverable": False,
                "score": 0.0,
                "confidence": 99.0,
                "is_role_account": False,
                "is_disposable": True,
                "provider": "unknown",
                "domain": {"name": domain, "mx_host": "", "mx_preference": None, "mx_rank": None, "mx_primary": False},
                "smtp": {"connected": False, "rcpt_code": None, "rcpt_accepted": False},
                "catch_all": {"checked": False, "detected": False},
                "source": "disposable_filter",
                "reason": f"Domain {domain} is a temporary/disposable email provider",
                "smtp_code": None,
            }

        # 3. DNS MX Check
        if not has_mx:
            return {
                "email": email,
                "status": "invalid",
                "sub_status": "no_mx_records",
                "is_deliverable": False,
                "score": 0.0,
                "confidence": 0.0,
                "is_role_account": is_role,
                "is_disposable": False,
                "provider": "unknown",
                "domain": {"name": domain, "mx_host": "", "mx_preference": None, "mx_rank": None, "mx_primary": False},
                "smtp": {"connected": False, "rcpt_code": None, "rcpt_accepted": False},
                "catch_all": {"checked": False, "detected": False},
                "source": "dns_mx_check",
                "reason": mx_error or f"Domain {domain} has no active mail exchanger (MX) records",
                "smtp_code": None,
            }

        # 4. Process SMTP Handshake Result if present
        if smtp_result:
            result = dict(smtp_result)
            result["email"] = email
            result["is_role_account"] = is_role
            result["is_disposable"] = False

            # If mailbox was accepted at gateway (250 OK)
            if result.get("sub_status") == "smtp_accepted":
                # If it is a role account, flag sub_status so outreach knows it's a generic inbox
                if is_role:
                    result["sub_status"] = "role_account"
                    result["reason"] = f"Mailbox accepted at gateway, but identified as role account ({role_prefix}@)"
                    # Slight downward calibration for non-personal role inboxes
                    result["score"] = max(40.0, float(result.get("score", 75.0)) - 10.0)

            return result

        # 5. Baseline MX-verified fallback (when SMTP handshake probe is not executed)
        base_score = 65.0 if is_role else 85.0
        sub_status = "role_account" if is_role else "dns_mx_verified"
        reason = (
            f"Domain {domain} has active MX servers (role account: {role_prefix}@)"
            if is_role
            else f"Syntax valid and domain {domain} has verified MX servers"
        )

        return {
            "email": email,
            "status": "valid",
            "sub_status": sub_status,
            "is_deliverable": True,
            "score": base_score,
            "confidence": 60.0,
            "is_role_account": is_role,
            "is_disposable": False,
            "provider": "unknown",
            "domain": {"name": domain, "mx_host": "", "mx_preference": None, "mx_rank": None, "mx_primary": False},
            "smtp": {"connected": False, "rcpt_code": None, "rcpt_accepted": False},
            "catch_all": {"checked": False, "detected": False},
            "source": "dns_mx_verified",
            "reason": reason,
            "smtp_code": None,
        }
