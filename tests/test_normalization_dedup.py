from shared.redis_client import normalize_company_name, normalize_domain


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


def test_company_name_normalization():
    assert normalize_company_name("Aspen Dental, LLC") == "aspen-dental"
    assert normalize_company_name("Apex Roofing Specialists & Co.") == "apex-roofing-specialists"
    assert normalize_company_name("Dr. Smith DDS & Associates PC") == "dr-smith-associates"
    assert normalize_company_name("   Biscayne Bay Dental Spa   ") == "biscayne-bay-dental-spa"
    assert normalize_company_name("") == ""
