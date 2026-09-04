import re
from typing import Tuple

# RFC 5321 / 5322 compliance pattern for email format
# Allows alphanumeric and safe punctuation in local part; enforces valid domain labels
_EMAIL_SYNTAX_REGEX = re.compile(
    r"^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+$"
)


def validate_email_syntax(email: str | None) -> Tuple[bool, str | None]:
    """
    Validates email address syntax according to RFC 5321 and RFC 5322.
    
    Checks:
    - Non-empty string and presence of single '@'
    - Total length <= 254 characters (RFC 5321 section 4.5.3.1.3)
    - Local part length <= 64 characters (RFC 5321 section 4.5.3.1.1)
    - Domain part length <= 253 characters
    - No leading or trailing dots in local part
    - No consecutive dots ('..') in local part or domain part
    - Domain contains at least one dot with valid TLD (>= 2 characters)
    - No leading or trailing hyphens in domain labels
    
    Returns:
        (is_valid: bool, error_reason: str | None)
    """
    if not email or not isinstance(email, str):
        return False, "Email address is empty or not a string"

    email = email.strip()

    # Total length limit
    if len(email) > 254:
        return False, "Email exceeds maximum RFC length of 254 characters"

    if "@" not in email:
        return False, "Email address missing '@' symbol"

    parts = email.split("@")
    if len(parts) != 2:
        return False, "Email address contains multiple '@' symbols"

    local_part, domain_part = parts[0], parts[1]

    # Local part checks
    if not local_part:
        return False, "Local part before '@' is empty"

    if len(local_part) > 64:
        return False, "Local part exceeds maximum length of 64 characters"

    if local_part.startswith(".") or local_part.endswith("."):
        return False, "Local part cannot begin or end with a dot"

    if ".." in local_part:
        return False, "Local part cannot contain consecutive dots"

    # Domain part checks
    if not domain_part:
        return False, "Domain part after '@' is empty"

    if len(domain_part) > 253:
        return False, "Domain part exceeds maximum length of 253 characters"

    if domain_part.startswith(".") or domain_part.endswith("."):
        return False, "Domain part cannot begin or end with a dot"

    if ".." in domain_part:
        return False, "Domain part cannot contain consecutive dots"

    labels = domain_part.split(".")
    if len(labels) < 2:
        return False, "Domain must contain a top-level domain (TLD)"

    for label in labels:
        if not label:
            return False, "Domain contains an empty label"
        if len(label) > 63:
            return False, f"Domain label '{label}' exceeds maximum 63 characters"
        if label.startswith("-") or label.endswith("-"):
            return False, f"Domain label '{label}' cannot start or end with a hyphen"

    # TLD must be at least 2 chars and only alphabetic (or punycode xn--)
    tld = labels[-1]
    if len(tld) < 2:
        return False, f"Top-level domain '{tld}' is too short"
    if not (tld.isalpha() or tld.startswith("xn--")):
        return False, f"Top-level domain '{tld}' is invalid"

    # Overall regex check
    if not _EMAIL_SYNTAX_REGEX.match(email):
        return False, "Email syntax violates RFC 5322 format"

    return True, None
