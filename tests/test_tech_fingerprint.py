from intelligence.technology.tech_fingerprint import TechFingerprintDetector


def test_fingerprint_wordpress_and_jquery():
    detector = TechFingerprintDetector()
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="generator" content="WordPress 5.8.1" />
        <link rel="stylesheet" href="/wp-content/themes/legacy/style.css" />
        <script src="https://code.jquery.com/jquery-1.12.4.min.js"></script>
    </head>
    <body>
        <h1>Agency Home</h1>
    </body>
    </html>
    """
    headers = {"Strict-Transport-Security": "max-age=31536000; includeSubDomains"}
    result = detector.analyze(
        url="https://legacy-agency.com",
        html_content=sample_html,
        headers=headers,
        ttfb_ms=450,
    )

    assert result["https"] is True
    assert result["hsts"] is True
    assert result["cms"] == "WordPress 5.8.1"
    assert "PHP" in result["backend_stack"]
    assert "jQuery 1.12.4" in result["frontend_stack"]
    assert result["ttfb_ms"] == 450
    assert result["evidence"]["wordpress"]["version"] == "5.8.1"
    assert result["evidence"]["jquery"]["version"] == "1.12.4"


def test_fingerprint_no_https():
    detector = TechFingerprintDetector()
    sample_html = "<html><body>Clean modern site without legacy libraries</body></html>"
    result = detector.analyze(
        url="http://insecure-site.org",
        html_content=sample_html,
        headers={},
    )
    assert result["https"] is False
    assert result["hsts"] is False
    assert result["cms"] is None
    assert len(result["frontend_stack"]) == 0
