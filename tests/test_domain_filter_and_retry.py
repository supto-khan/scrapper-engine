"""
Unit tests for domain filtering and retry logic.
"""

from shared.domain_filter import (
    is_excluded_domain,
    is_retryable_failure,
    DIRECTORY_AGGREGATOR_DOMAINS,
)


def test_directory_aggregator_domains_excluded():
    assert is_excluded_domain("najibdeema.localsearch.com")[0] is True
    assert is_excluded_domain("localsearch.com")[0] is True
    assert is_excluded_domain("localsearch.com.au")[0] is True
    assert is_excluded_domain("business.yellowpages.com.au")[0] is True
    assert is_excluded_domain("subdomain.yelp.com")[0] is True
    assert is_excluded_domain("profile.clutch.co")[0] is True
    assert is_excluded_domain("facebook.com")[0] is True


def test_internal_and_empty_domains_excluded():
    assert is_excluded_domain("")[0] is True
    assert is_excluded_domain("test.local")[0] is True
    assert is_excluded_domain("dev.localhost")[0] is True
    assert is_excluded_domain("cluster.internal")[0] is True


def test_legitimate_domains_allowed():
    assert is_excluded_domain("sydneyplumbing.com.au")[0] is False
    assert is_excluded_domain("nexidant.com")[0] is False
    assert is_excluded_domain("apex-legal.co.uk")[0] is False


def test_retryable_failure_classification():
    # Permanent errors -> Should NOT retry
    assert is_retryable_failure(400, "Bad Request") is False
    assert is_retryable_failure(401, "Unauthorized") is False
    assert is_retryable_failure(403, "Forbidden") is False
    assert is_retryable_failure(404, "Not Found") is False
    assert is_retryable_failure(410, "Gone") is False
    assert is_retryable_failure(0, "nodename nor servname provided, or not known") is False
    assert is_retryable_failure(0, "DNS_PROBE_FINISHED_NXDOMAIN") is False

    # Transient errors -> Should retry
    assert is_retryable_failure(500, "Internal Server Error") is True
    assert is_retryable_failure(502, "Bad Gateway") is True
    assert is_retryable_failure(503, "Service Unavailable") is True
    assert is_retryable_failure(504, "Gateway Timeout") is True
    assert is_retryable_failure(0, "Connection timed out") is True
    assert is_retryable_failure(0, "Remote disconnected") is True
