from shared.redis_client import normalize_domain


def test_domain_normalization():
    assert normalize_domain("https://www.example.com") == "example.com"
    assert (
        normalize_domain("http://sub.domain.co.uk/path/to/page?query=1")
        == "sub.domain.co.uk"
    )
    assert normalize_domain("www.agency-site.io/") == "agency-site.io"
    assert normalize_domain("HTTP://EXAMPLE.COM:8080/test") == "example.com"
    assert normalize_domain("   https://clutch.co/profile   ") == "clutch.co"
    assert normalize_domain("") == ""
