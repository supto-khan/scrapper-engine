import re
from typing import Any

from bs4 import BeautifulSoup
from intelligence.technology.version_debt import VersionDebtCalculator


class TechFingerprintDetector:
    """
    Phase 1 & Intelligence technology fingerprint detector:
    - jQuery detection (legacy versions vs modern, CDN vs local scripts)
    - AngularJS / Angular detection (legacy 1.x EOL vs modern)
    - Bootstrap detection (v2/v3/v4 legacy vs v5 modern)
    - Vue / React framework detection
    - WordPress detection (legacy versions vs modern, /wp-content/, /wp-includes/, generator meta)
    - HTTPS and HSTS status
    - Automated CDNJS version debt, age, and CVE risk calculation
    """

    # Library version regex patterns
    JQUERY_SRC_PATTERN = re.compile(
        r"jquery[.-]([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE
    )
    JQUERY_INLINE_PATTERN = re.compile(
        r"jQuery\s+v?([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE
    )
    ANGULAR_SRC_PATTERN = re.compile(
        r"angular[.-]([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE
    )
    BOOTSTRAP_SRC_PATTERN = re.compile(
        r"bootstrap[.-]([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE
    )
    VUE_SRC_PATTERN = re.compile(
        r"vue[.-]([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE
    )
    REACT_SRC_PATTERN = re.compile(
        r"react[.-]([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE
    )

    # WordPress version regex pattern
    WP_GENERATOR_PATTERN = re.compile(
        r"wordpress\s+([0-9]+\.[0-9]+(?:\.[0-9]+)?)", re.IGNORECASE
    )

    def __init__(self) -> None:
        self.debt_calculator = VersionDebtCalculator()

    def analyze(
        self,
        url: str,
        html_content: str,
        headers: dict[str, Any] | None = None,
        ttfb_ms: int | None = None,
    ) -> dict[str, Any]:
        """
        Extracts technology fingerprints and computes exact version debts.
        """
        headers = headers or {}
        evidence: dict[str, Any] = {}
        frontend_stack: list[str] = []
        backend_stack: list[str] = []
        version_debts: list[dict[str, Any]] = []
        cms: str | None = None

        # 1. Protocol & Security Checks
        is_https = url.lower().startswith("https://")

        # Check HSTS header (case-insensitive)
        hsts_header = any(
            k.lower() == "strict-transport-security" for k in headers.keys()
        )

        evidence["security"] = {
            "https": is_https,
            "hsts": hsts_header,
        }

        # 2. Parse HTML
        soup = BeautifulSoup(html_content, "html.parser")

        # 3. WordPress Detection
        is_wp = False
        wp_version = None

        # Check generator meta tag
        generator_tag = soup.find(
            "meta", attrs={"name": re.compile(r"^generator$", re.IGNORECASE)}
        )
        if generator_tag and generator_tag.get("content"):
            content = generator_tag.get("content", "")
            match = self.WP_GENERATOR_PATTERN.search(content)
            if match:
                is_wp = True
                wp_version = match.group(1)
                evidence["wordpress"] = {
                    "detected_via": "meta_generator",
                    "version": wp_version,
                    "raw_content": content,
                }

        # Check script / link paths for wp-content / wp-includes
        if not is_wp:
            wp_resources = soup.find_all(
                lambda tag: (
                    tag.name in ["script", "link", "img"]
                    and (
                        "wp-content" in (tag.get("src") or tag.get("href") or "")
                        or "wp-includes" in (tag.get("src") or tag.get("href") or "")
                    )
                )
            )
            if wp_resources:
                is_wp = True
                evidence["wordpress"] = {
                    "detected_via": "resource_paths",
                    "sample_path": (
                        wp_resources[0].get("src") or wp_resources[0].get("href")
                    ),
                }

        if is_wp:
            cms = "WordPress"
            backend_stack.append("PHP")
            backend_stack.append("WordPress")
            if wp_version:
                cms = f"WordPress {wp_version}"
                wp_debt = self.debt_calculator.calculate("wordpress", wp_version)
                if wp_debt:
                    evidence["wordpress"]["debt"] = wp_debt.__dict__
                    version_debts.append(wp_debt.__dict__)

        # 4. Frontend Script Inspection
        scripts = soup.find_all("script")
        script_srcs = [s.get("src", "") for s in scripts if s.get("src")]

        # Helper to check scripts for a library
        def _check_lib(lib_name: str, src_pattern: re.Pattern) -> tuple[bool, str | None, str | None]:
            for src in script_srcs:
                if lib_name in src.lower():
                    m = src_pattern.search(src)
                    if m:
                        return True, m.group(1), src
                    return True, None, src
            return False, None, None

        # jQuery
        has_jq, jq_ver, jq_src = _check_lib("jquery", self.JQUERY_SRC_PATTERN)
        if not has_jq:
            for s in scripts:
                if s.string and "jQuery" in s.string:
                    m = self.JQUERY_INLINE_PATTERN.search(s.string)
                    if m:
                        has_jq, jq_ver = True, m.group(1)
                        break

        if has_jq:
            jq_entry = {"detected_via": "script", "version": jq_ver, "src": jq_src}
            if jq_ver:
                frontend_stack.append(f"jQuery {jq_ver}")
                jq_debt = self.debt_calculator.calculate("jquery", jq_ver)
                if jq_debt:
                    jq_entry["debt"] = jq_debt.__dict__
                    version_debts.append(jq_debt.__dict__)
            else:
                frontend_stack.append("jQuery")
            evidence["jquery"] = jq_entry

        # AngularJS (Critical Modernization Signal)
        has_ng, ng_ver, ng_src = _check_lib("angular", self.ANGULAR_SRC_PATTERN)
        if has_ng:
            ng_entry = {"detected_via": "script", "version": ng_ver, "src": ng_src}
            if ng_ver:
                frontend_stack.append(f"AngularJS {ng_ver}")
                ng_debt = self.debt_calculator.calculate("angularjs", ng_ver)
                if ng_debt:
                    ng_entry["debt"] = ng_debt.__dict__
                    version_debts.append(ng_debt.__dict__)
            else:
                frontend_stack.append("AngularJS")
            evidence["angularjs"] = ng_entry

        # Bootstrap
        has_bs, bs_ver, bs_src = _check_lib("bootstrap", self.BOOTSTRAP_SRC_PATTERN)
        if has_bs:
            bs_entry = {"detected_via": "script", "version": bs_ver, "src": bs_src}
            if bs_ver:
                frontend_stack.append(f"Bootstrap {bs_ver}")
                bs_debt = self.debt_calculator.calculate("bootstrap", bs_ver)
                if bs_debt:
                    bs_entry["debt"] = bs_debt.__dict__
                    version_debts.append(bs_debt.__dict__)
            else:
                frontend_stack.append("Bootstrap")
            evidence["bootstrap"] = bs_entry

        # Vue.js
        has_vue, vue_ver, vue_src = _check_lib("vue", self.VUE_SRC_PATTERN)
        if has_vue:
            vue_entry = {"detected_via": "script", "version": vue_ver, "src": vue_src}
            if vue_ver:
                frontend_stack.append(f"Vue {vue_ver}")
                vue_debt = self.debt_calculator.calculate("vue", vue_ver)
                if vue_debt:
                    vue_entry["debt"] = vue_debt.__dict__
                    version_debts.append(vue_debt.__dict__)
            else:
                frontend_stack.append("Vue.js")
            evidence["vue"] = vue_entry

        # React
        has_react, react_ver, react_src = _check_lib("react", self.REACT_SRC_PATTERN)
        if has_react:
            react_entry = {"detected_via": "script", "version": react_ver, "src": react_src}
            if react_ver:
                frontend_stack.append(f"React {react_ver}")
                react_debt = self.debt_calculator.calculate("react", react_ver)
                if react_debt:
                    react_entry["debt"] = react_debt.__dict__
                    version_debts.append(react_debt.__dict__)
            else:
                frontend_stack.append("React")
            evidence["react"] = react_entry

        evidence["version_debts"] = version_debts

        return {
            "cms": cms,
            "frontend_stack": list(set(frontend_stack)),
            "backend_stack": list(set(backend_stack)),
            "https": is_https,
            "hsts": hsts_header,
            "ttfb_ms": ttfb_ms,
            "evidence": evidence,
            "version_debts": version_debts,
        }


def get_fingerprint_detector() -> TechFingerprintDetector:
    return TechFingerprintDetector()
