"""
Role-based email account detector.
Identifies generic departmental and functional mailboxes (e.g. admin@, support@, info@)
which should be flagged or differentiated from named individual decision makers in B2B outreach.
"""

from typing import Set, Tuple

ROLE_ACCOUNT_PREFIXES: Set[str] = {
    # Administrative & Management
    "admin",
    "administrator",
    "root",
    "sysadmin",
    "superuser",
    "webmaster",
    "postmaster",
    "hostmaster",
    "noc",
    "operations",
    "ops",
    # Customer Service & Support
    "support",
    "help",
    "helpdesk",
    "service",
    "customercare",
    "customersupport",
    "customerservice",
    "clientcare",
    # Sales & Inquiries
    "sales",
    "orders",
    "billing",
    "invoices",
    "accounts",
    "accounting",
    "finance",
    "inquiry",
    "inquiries",
    "commercial",
    "partnerships",
    "leads",
    "deals",
    # General Corporate & Communication
    "info",
    "information",
    "contact",
    "contactus",
    "hello",
    "hi",
    "team",
    "office",
    "reception",
    "general",
    "feedback",
    "frontdesk",
    # Marketing, PR & Media
    "marketing",
    "press",
    "media",
    "news",
    "communications",
    "pr",
    "social",
    "affiliates",
    # Human Resources & Careers
    "hr",
    "humanresources",
    "jobs",
    "careers",
    "recruiting",
    "recruitment",
    "talent",
    "people",
    "work",
    # Legal, Compliance & Security
    "legal",
    "compliance",
    "privacy",
    "security",
    "abuse",
    "spam",
    "copyright",
    "dmca",
    "gdpr",
    # Automated & System
    "noreply",
    "no-reply",
    "mailer-daemon",
    "bounce",
    "notifications",
    "alert",
    "alerts",
    "robot",
    "daemon",
    "devnull",
}


def is_role_account(email: str | None) -> Tuple[bool, str | None]:
    """
    Checks if an email address is a generic role account rather than an individual.
    
    Handles:
    - Standard aliases (e.g. support+tier1@company.com -> support)
    - Sub-addressing and dots (e.g. customer.support@company.com)
    
    Returns:
        (is_role: bool, matched_prefix: str | None)
    """
    if not email or "@" not in email:
        return False, None

    local_part = email.split("@")[0].lower().strip()

    # Strip plus-addressing (e.g. info+newsletter -> info)
    base_local = local_part.split("+")[0]

    # Direct match
    if base_local in ROLE_ACCOUNT_PREFIXES:
        return True, base_local

    # Check dot or hyphen joined tokens (e.g. "sales-team", "customer.support")
    tokens = [t for t in base_local.replace("-", ".").replace("_", ".").split(".") if t]
    for token in tokens:
        if token in ROLE_ACCOUNT_PREFIXES:
            return True, token

    return False, None
