"""
Signal Engine — Deep 360° Multi-Page Website & Conversion Auditor
Executes thorough 10-20s multi-page technical, CRO, SEO, security, and DNS diagnostics.
Includes Google PageSpeed Lighthouse integration, SSL cert expiry, broken link detection,
and image optimization analysis.
"""

import concurrent.futures
import json
import logging
import os
import re
import socket
import ssl
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Optional

import dns.resolver
import requests
from bs4 import BeautifulSoup

from intelligence.website_audit.pagespeed_client import PageSpeedClient
from shared import http_client
from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Request pacing delay (seconds) between subpage requests to the same domain
REQUEST_DELAY_S = float(os.getenv("AUDIT_REQUEST_DELAY_MS", "500")) / 1000.0

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

COMMON_SUBPAGE_PATTERNS = [
    r"/contact", r"/booking", r"/book", r"/services", r"/service",
    r"/about", r"/pricing", r"/appointment", r"/schedule", r"/menu"
]

BOOKING_WIDGET_DOMAINS = [
    "calendly.com", "acuityscheduling.com", "zocdoc.com", "jane.app",
    "mindbodyonline.com", "setmore.com", "squareup.com/appointments",
    "appointlet.com", "timely.com", "vagaro.com"
]

MODERN_IMAGE_EXTENSIONS = {".webp", ".avif", ".svg"}
LEGACY_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff"}


class DeepWebsiteAuditor:
    """
    Executes a comprehensive, multi-pillar audit across:
    1. Multi-Page Latency & TTFB Backend Discrepancy
    2. Mobile CRO & Calling Friction (tel: links, form fields, booking widgets)
    3. Local SEO & OpenGraph Social Sharing Cards
    4. Security Headers, SSL Cert Expiry & Exposed CMS Endpoints
    5. DNS Health & Email Deliverability (SPF/DMARC spam risk)
    6. Google PageSpeed Lighthouse Scores (Performance, Accessibility, SEO, LCP, CLS)
    7. Broken Internal Link Detection (404s)
    8. Image Optimization Analysis (lazy loading, WebP, alt text)
    """

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.pagespeed_client = PageSpeedClient()
        self.redis = get_redis_client()

    def audit_domain(self, domain: str, website_url: Optional[str] = None) -> dict[str, Any]:
        """
        Runs full 10-20s deep audit across target domain.
        Returns a structured dictionary of 360-degree technical and conversion evidence.
        """
        clean_domain = domain.strip().lower().replace("http://", "").replace("https://", "").strip("/")
        base_url = website_url or f"https://{clean_domain}"
        if not base_url.startswith("http"):
            base_url = f"https://{base_url}"

        logger.info(f"🔬 Starting Deep 360° Audit for {clean_domain} ({base_url})...")
        t_start = time.time()

        # 1. Fetch Homepage & Discover Key Inner Pages
        homepage_data = self._fetch_and_profile_page(base_url, is_homepage=True)
        if not homepage_data.get("reachable"):
            # Try http fallback
            if base_url.startswith("https://"):
                http_fallback = base_url.replace("https://", "http://")
                homepage_data = self._fetch_and_profile_page(http_fallback, is_homepage=True)
                if homepage_data.get("reachable"):
                    base_url = http_fallback

        discovered_subpages = self._discover_key_subpages(base_url, homepage_data.get("html", ""))

        # 2. Concurrently Profile Key Subpages (max 2 workers for politeness)
        subpage_results: list[dict[str, Any]] = []
        if discovered_subpages:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
                future_to_url = {executor.submit(self._fetch_and_profile_page, url): url for url in discovered_subpages[:3]}
                for future in concurrent.futures.as_completed(future_to_url):
                    res = future.result()
                    if res.get("reachable"):
                        subpage_results.append(res)

        # 3. Analyze Multi-Page Speed & Latency Discrepancy
        speed_analysis = self._analyze_speed_and_assets(homepage_data, subpage_results)

        # 4. Analyze Mobile UX, Calling & Form Friction
        conversion_analysis = self._analyze_conversion_and_ux(homepage_data, subpage_results)

        # 5. Analyze Local SEO, Schema & OpenGraph Cards
        seo_analysis = self._analyze_seo_and_schema(clean_domain, homepage_data)

        # 6. Analyze Security, Headers, SSL Cert & CMS Endpoints
        security_analysis = self._analyze_security(base_url, homepage_data, clean_domain)

        # 7. Analyze DNS Health & Email Deliverability (SPF/DMARC)
        dns_analysis = self._analyze_dns_and_email_health(clean_domain)

        # 8. Detect Broken Internal Links (404s)
        link_health = self._detect_broken_links(base_url, homepage_data.get("html", ""))

        # 9. Analyze Image Optimization
        image_analysis = self._analyze_image_optimization(homepage_data, subpage_results)

        # 10. Google PageSpeed Lighthouse Scores (async-safe, may add 3-8s)
        lighthouse_metrics = self._run_lighthouse_audit(base_url)

        total_audit_time = round(time.time() - t_start, 2)
        logger.info(f"✅ Completed Deep 360° Audit for {clean_domain} in {total_audit_time}s")

        # 10. Record domain audit timestamp in Redis (24h cooldown key)
        try:
            self.redis.client.set(f"audit:last_audited:{clean_domain}", int(time.time()), ex=86400)
        except Exception:
            pass

        return {
            "domain": clean_domain,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "audit_duration_seconds": round(total_audit_time, 2),
            "pages_audited_count": 1 + len(subpage_results),
            "speed_metrics": speed_analysis,
            "conversion_metrics": conversion_analysis,
            "seo_metrics": seo_analysis,
            "security_metrics": security_analysis,
            "dns_email_metrics": dns_analysis,
            "link_health": link_health,
            "image_optimization": image_analysis,
            "lighthouse_metrics": lighthouse_metrics,
        }

    # ─── Page Fetching & Profiling ─────────────────────────────────────────────

    def _fetch_and_profile_page(self, url: str, is_homepage: bool = False) -> dict[str, Any]:
        """Fetches a page, measuring TTFB, total latency, and parsing DOM structure."""
        res: dict[str, Any] = {
            "url": url,
            "path": urllib.parse.urlparse(url).path or "/",
            "reachable": False,
            "status_code": 0,
            "ttfb_ms": 0,
            "total_duration_ms": 0,
            "html_size_kb": 0,
            "html": "",
            "headers": {},
            "images_count": 0,
            "total_image_bytes_estimate": 0,
            "heavy_images_count": 0,
            "render_blocking_scripts_count": 0,
        }

        try:
            t0 = time.time()
            r = http_client.get(
                url,
                impersonate="chrome124",
                timeout=self.timeout,
                headers={"User-Agent": USER_AGENT},
            )
            total_duration_ms = int((time.time() - t0) * 1000)
            ttfb_ms = int(r.elapsed.total_seconds() * 1000) if hasattr(r, "elapsed") else total_duration_ms

            res["reachable"] = r.status_code == 200
            res["status_code"] = r.status_code
            res["ttfb_ms"] = ttfb_ms
            res["total_duration_ms"] = total_duration_ms
            res["headers"] = dict(r.headers)
            res["html"] = r.text
            res["html_size_kb"] = round(len(r.content) / 1024, 1)

            if r.status_code == 200 and r.text:
                soup = BeautifulSoup(r.text, "html.parser")
                imgs = soup.select("img[src]")
                res["images_count"] = len(imgs)

                # Check scripts in <head>
                head = soup.select_one("head")
                if head:
                    scripts = head.select("script[src]:not([async]):not([defer])")
                    res["render_blocking_scripts_count"] = len(scripts)

        except Exception as e:
            logger.debug(f"Error fetching {url}: {e}")

        return res

    def _discover_key_subpages(self, base_url: str, html: str) -> list[str]:
        """Discovers key conversion and service subpages from homepage links."""
        discovered: list[str] = []
        if not html:
            return discovered

        parsed_base = urllib.parse.urlparse(base_url)
        base_netloc = parsed_base.netloc.lower()
        soup = BeautifulSoup(html, "html.parser")

        seen_paths: set[str] = set()
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
                continue

            full_url = urllib.parse.urljoin(base_url, href)
            parsed = urllib.parse.urlparse(full_url)

            # Must belong to same domain
            if parsed.netloc.lower() != base_netloc:
                continue

            path = parsed.path.rstrip("/")
            if not path or path == "":
                continue

            if path.lower() in seen_paths:
                continue

            # Match high-value conversion subpage patterns
            if any(re.search(pat, path, re.I) for pat in COMMON_SUBPAGE_PATTERNS):
                seen_paths.add(path.lower())
                discovered.append(full_url)
                if len(discovered) >= 4:
                    break

        return discovered

    # ─── Pillar 1: Speed & Asset Analysis ──────────────────────────────────────

    def _analyze_speed_and_assets(self, homepage: dict[str, Any], subpages: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyzes multi-page latency discrepancy, TTFB backend delays, and asset bloat."""
        hp_speed_ms = homepage.get("total_duration_ms", 0)
        hp_ttfb_ms = homepage.get("ttfb_ms", 0)

        all_pages = [homepage] + subpages
        slowest_page = max(all_pages, key=lambda p: p.get("total_duration_ms", 0)) if all_pages else homepage
        slowest_path = slowest_page.get("path", "/")
        slowest_speed_ms = slowest_page.get("total_duration_ms", 0)

        speed_discrepancy_detected = (slowest_speed_ms - hp_speed_ms) > 1500 and slowest_speed_ms > 3000
        backend_db_bottleneck = hp_ttfb_ms > 1200 or any(p.get("ttfb_ms", 0) > 1200 for p in subpages)

        total_blocking_scripts = sum(p.get("render_blocking_scripts_count", 0) for p in all_pages)
        total_images_scanned = sum(p.get("images_count", 0) for p in all_pages)

        return {
            "homepage_speed_ms": hp_speed_ms,
            "homepage_speed_s": round(hp_speed_ms / 1000, 2),
            "homepage_ttfb_ms": hp_ttfb_ms,
            "slowest_subpage_path": slowest_path,
            "slowest_subpage_speed_ms": slowest_speed_ms,
            "slowest_subpage_speed_s": round(slowest_speed_ms / 1000, 2),
            "speed_discrepancy_detected": speed_discrepancy_detected,
            "backend_db_bottleneck": backend_db_bottleneck,
            "render_blocking_scripts_count": total_blocking_scripts,
            "total_images_scanned": total_images_scanned,
            "gzip_enabled": "gzip" in homepage.get("headers", {}).get("content-encoding", "").lower() or "br" in homepage.get("headers", {}).get("content-encoding", "").lower(),
        }

    # ─── Pillar 2: Conversion & Mobile UX ──────────────────────────────────────

    def _analyze_conversion_and_ux(self, homepage: dict[str, Any], subpages: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyzes mobile click-to-call, form field friction, and booking widget embeds."""
        all_html = " ".join([p.get("html", "") for p in [homepage] + subpages if p.get("html")])
        soup = BeautifulSoup(all_html, "html.parser")

        # 1. Phone number calling audit
        raw_text = soup.get_text()
        phone_matches = re.findall(r"(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})", raw_text)
        tel_links = soup.select("a[href^='tel:']")

        has_visible_phone = len(phone_matches) > 0
        has_clickable_tel_link = len(tel_links) > 0
        missing_mobile_tel_link = has_visible_phone and not has_clickable_tel_link

        # 2. Form friction audit
        forms = soup.select("form")
        max_form_inputs = 0
        has_autocomplete = False
        for f in forms:
            inputs = f.select("input:not([type='hidden']), textarea, select")
            if len(inputs) > max_form_inputs:
                max_form_inputs = len(inputs)
            if any(i.get("autocomplete") for i in inputs):
                has_autocomplete = True

        high_form_friction = max_form_inputs >= 7

        # 3. Third-party booking widget detection
        detected_booking_widgets: list[str] = []
        iframes = soup.select("iframe[src]")
        for ifr in iframes:
            src = ifr.get("src", "").lower()
            for b_dom in BOOKING_WIDGET_DOMAINS:
                if b_dom in src and b_dom not in detected_booking_widgets:
                    detected_booking_widgets.append(b_dom)

        # 4. Sticky CTA check
        has_sticky_cta = bool(
            soup.select(".sticky-cta, .floating-btn, .mobile-call-bar, [class*='sticky-call'], [class*='floating-call']")
        )

        return {
            "has_visible_phone": has_visible_phone,
            "has_clickable_tel_link": has_clickable_tel_link,
            "missing_mobile_tel_link": missing_mobile_tel_link,
            "max_form_inputs": max_form_inputs,
            "high_form_friction": high_form_friction,
            "has_form_autocomplete": has_autocomplete,
            "detected_booking_widgets": detected_booking_widgets,
            "has_sticky_mobile_cta": has_sticky_cta,
        }

    # ─── Pillar 3: SEO & Schema ────────────────────────────────────────────────

    def _analyze_seo_and_schema(self, domain: str, homepage: dict[str, Any]) -> dict[str, Any]:
        """Audits JSON-LD LocalBusiness schema, OpenGraph sharing cards, and page structure."""
        html = homepage.get("html", "")
        if not html:
            return {
                "has_json_ld_schema": False,
                "has_local_business_schema": False,
                "has_opengraph_image": False,
                "has_h1": False,
                "h1_count": 0,
            }

        soup = BeautifulSoup(html, "html.parser")

        # 1. JSON-LD Schema
        has_json_ld = False
        has_local_biz = False
        for script in soup.select("script[type='application/ld+json']"):
            has_json_ld = True
            text = script.get_text().lower()
            if any(k in text for k in ["localbusiness", "dentist", "physician", "legalservice", "roofingcontractor", "hvacbusiness", "medicalbusiness", "restaurant", "store"]):
                has_local_biz = True
                break

        # 2. OpenGraph Sharing Cards
        og_image = soup.select_one("meta[property='og:image'], meta[name='og:image']")
        og_title = soup.select_one("meta[property='og:title'], meta[name='og:title']")
        has_og_image = bool(og_image and og_image.get("content"))
        has_og_title = bool(og_title and og_title.get("content"))
        broken_social_cards = not (has_og_image and has_og_title)

        # 3. Headings & Meta
        h1_tags = soup.select("h1")
        meta_desc = soup.select_one("meta[name='description']")

        return {
            "has_json_ld_schema": has_json_ld,
            "has_local_business_schema": has_local_biz,
            "has_opengraph_image": has_og_image,
            "broken_social_cards": broken_social_cards,
            "h1_count": len(h1_tags),
            "has_meta_description": bool(meta_desc and meta_desc.get("content")),
        }

    # ─── Pillar 4: Security, SSL Cert & Exposed Endpoints ─────────────────────

    def _analyze_security(self, base_url: str, homepage: dict[str, Any], domain: str) -> dict[str, Any]:
        """Audits HTTPS/HSTS, SSL cert expiry, mixed content, and exposed CMS user enumeration endpoints."""
        headers = homepage.get("headers", {})
        headers_lower = {k.lower(): v for k, v in headers.items()}
        html = homepage.get("html", "")

        has_https = base_url.startswith("https://")
        has_hsts = "strict-transport-security" in headers_lower
        has_csp = "content-security-policy" in headers_lower
        has_x_frame = "x-frame-options" in headers_lower

        # Mixed content check
        has_mixed_content = False
        if has_https and html:
            has_mixed_content = bool(re.search(r'src=["\']http://', html))

        # SSL Certificate Expiry Check
        ssl_cert_info = self._check_ssl_certificate(domain)

        # Check for exposed WordPress user enumeration
        exposed_wp_users = False
        try:
            wp_user_url = urllib.parse.urljoin(base_url, "/wp-json/wp/v2/users")
            r_wp = requests.get(wp_user_url, timeout=4, headers={"User-Agent": USER_AGENT})
            if r_wp.status_code == 200 and "[" in r_wp.text and "name" in r_wp.text:
                exposed_wp_users = True
        except Exception:
            pass

        return {
            "has_https": has_https,
            "has_hsts": has_hsts,
            "has_csp": has_csp,
            "has_x_frame_options": has_x_frame,
            "has_mixed_content": has_mixed_content,
            "exposed_wp_users": exposed_wp_users,
            **ssl_cert_info,
        }

    def _check_ssl_certificate(self, domain: str) -> dict[str, Any]:
        """Checks SSL certificate validity and days until expiry."""
        result = {
            "ssl_cert_checked": False,
            "ssl_cert_valid": False,
            "ssl_cert_days_remaining": None,
            "ssl_cert_expiry_date": None,
            "ssl_cert_issuer": None,
            "ssl_cert_expiring_soon": False,
        }

        clean_domain = domain.split("/")[0].split(":")[0]
        if not clean_domain or "." not in clean_domain:
            return result

        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((clean_domain, 443), timeout=5) as sock:
                with ctx.wrap_socket(sock, server_hostname=clean_domain) as ssock:
                    cert = ssock.getpeercert()
                    if cert:
                        result["ssl_cert_checked"] = True
                        result["ssl_cert_valid"] = True

                        not_after_str = cert.get("notAfter", "")
                        if not_after_str:
                            expiry_dt = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
                            now = datetime.now(timezone.utc)
                            days_remaining = (expiry_dt - now).days

                            result["ssl_cert_days_remaining"] = days_remaining
                            result["ssl_cert_expiry_date"] = expiry_dt.strftime("%Y-%m-%d")
                            result["ssl_cert_expiring_soon"] = days_remaining < 30

                        issuer = cert.get("issuer")
                        if issuer:
                            issuer_parts = [v for kv_tuple in issuer for k, v in kv_tuple if k in ("organizationName", "commonName")]
                            result["ssl_cert_issuer"] = issuer_parts[0] if issuer_parts else None

        except Exception as e:
            logger.debug(f"SSL cert check failed for {clean_domain}: {e}")
            result["ssl_cert_checked"] = True
            result["ssl_cert_valid"] = False

        return result

    # ─── Pillar 5: DNS & Email Health ──────────────────────────────────────────

    def _analyze_dns_and_email_health(self, domain: str) -> dict[str, Any]:
        """Resolves live SPF, DMARC, and MX records to determine spam/deliverability risk."""
        has_mx = False
        has_spf = False
        has_dmarc = False
        spf_record = None
        dmarc_record = None

        resolver = dns.resolver.Resolver()
        resolver.timeout = 4
        resolver.lifetime = 4

        # 1. MX Query
        try:
            mx_answers = resolver.resolve(domain, "MX")
            has_mx = len(mx_answers) > 0
        except Exception:
            pass

        # 2. SPF Query (TXT record on domain)
        try:
            txt_answers = resolver.resolve(domain, "TXT")
            for rdata in txt_answers:
                txt_str = rdata.to_text().strip('"')
                if "v=spf1" in txt_str.lower():
                    has_spf = True
                    spf_record = txt_str
                    break
        except Exception:
            pass

        # 3. DMARC Query (TXT record on _dmarc.domain)
        try:
            dmarc_answers = resolver.resolve(f"_dmarc.{domain}", "TXT")
            for rdata in dmarc_answers:
                txt_str = rdata.to_text().strip('"')
                if "v=dmarc1" in txt_str.lower():
                    has_dmarc = True
                    dmarc_record = txt_str
                    break
        except Exception:
            pass

        email_deliverability_risk = has_mx and (not has_dmarc or not has_spf)

        return {
            "has_mx_record": has_mx,
            "has_spf_record": has_spf,
            "spf_record": spf_record,
            "has_dmarc_record": has_dmarc,
            "dmarc_record": dmarc_record,
            "email_deliverability_risk": email_deliverability_risk,
        }

    # ─── Pillar 6: Broken Internal Links ──────────────────────────────────────

    def _detect_broken_links(self, base_url: str, html: str) -> dict[str, Any]:
        """Crawls internal links from homepage and detects 404s and other broken pages."""
        result = {
            "total_internal_links_checked": 0,
            "broken_links_count": 0,
            "broken_link_urls": [],
            "redirect_chain_detected": False,
        }

        if not html:
            return result

        parsed_base = urllib.parse.urlparse(base_url)
        base_netloc = parsed_base.netloc.lower()
        soup = BeautifulSoup(html, "html.parser")

        internal_urls: set[str] = set()
        for a in soup.select("a[href]"):
            href = a.get("href", "").strip()
            if not href or href.startswith("#") or href.startswith("javascript:") or href.startswith("mailto:") or href.startswith("tel:"):
                continue

            full_url = urllib.parse.urljoin(base_url, href)
            parsed = urllib.parse.urlparse(full_url)
            if parsed.netloc.lower() != base_netloc:
                continue

            # Normalize and deduplicate
            normalized = f"{parsed.scheme}://{parsed.netloc}{parsed.path.rstrip('/')}"
            if normalized != base_url.rstrip("/"):
                internal_urls.add(normalized)

        # Check up to 10 internal links to stay within time budget
        urls_to_check = list(internal_urls)[:10]
        result["total_internal_links_checked"] = len(urls_to_check)

        broken: list[str] = []

        def _check_url(url: str) -> tuple[str, int, bool]:
            try:
                time.sleep(REQUEST_DELAY_S)  # Polite delay
                r = requests.head(url, timeout=5, headers={"User-Agent": USER_AGENT}, allow_redirects=True)
                has_redirect_chain = len(r.history) >= 2
                return url, r.status_code, has_redirect_chain
            except Exception:
                return url, 0, False

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = {executor.submit(_check_url, u): u for u in urls_to_check}
            for future in concurrent.futures.as_completed(futures):
                checked_url, status, has_chain = future.result()
                if status >= 400 or status == 0:
                    broken.append(checked_url)
                if has_chain:
                    result["redirect_chain_detected"] = True

        result["broken_links_count"] = len(broken)
        result["broken_link_urls"] = broken[:5]  # Cap at 5 for storage

        return result

    # ─── Pillar 7: Image Optimization ──────────────────────────────────────────

    def _analyze_image_optimization(self, homepage: dict[str, Any], subpages: list[dict[str, Any]]) -> dict[str, Any]:
        """Analyzes image lazy loading, format optimization, and alt text coverage."""
        all_html = " ".join([p.get("html", "") for p in [homepage] + subpages if p.get("html")])
        soup = BeautifulSoup(all_html, "html.parser")

        imgs = soup.select("img")
        total_images = len(imgs)

        missing_lazy = 0
        missing_alt = 0
        non_modern_format = 0

        for img in imgs:
            # Lazy loading check (skip first 2 above-fold images)
            loading_attr = (img.get("loading") or "").lower()
            if loading_attr != "lazy":
                missing_lazy += 1

            # Alt text check
            alt = img.get("alt")
            if alt is None or alt.strip() == "":
                missing_alt += 1

            # Image format check
            src = (img.get("src") or img.get("data-src") or "").lower().split("?")[0]
            if src:
                ext = "." + src.rsplit(".", 1)[-1] if "." in src.rsplit("/", 1)[-1] else ""
                if ext in LEGACY_IMAGE_EXTENSIONS:
                    non_modern_format += 1

        # Discount first 2 images from lazy count (above the fold should eager-load)
        images_missing_lazy = max(0, missing_lazy - 2) if total_images > 2 else 0

        return {
            "total_images": total_images,
            "images_missing_lazy_load": images_missing_lazy,
            "images_missing_alt_text": missing_alt,
            "images_non_modern_format": non_modern_format,
            "has_image_optimization_issues": (images_missing_lazy > 2 or non_modern_format > 3 or missing_alt > 3),
        }

    # ─── Pillar 8: Google PageSpeed Lighthouse ─────────────────────────────────

    def _run_lighthouse_audit(self, url: str) -> dict[str, Any]:
        """Runs Google PageSpeed Insights API for real Lighthouse metrics."""
        result = {
            "available": False,
            "performance_score": None,
            "accessibility_score": None,
            "seo_score": None,
            "lcp_ms": None,
            "cls": None,
            "inp_ms": None,
            "fcp_ms": None,
            "ttfb_ms": None,
        }

        # If API key is not configured, Google allows limited anonymous queries.
        # We attempt PageSpeed and gracefully fall back if rate-limited.
        try:
            raw_data = self.pagespeed_client.run_pagespeed(url, strategy="mobile")
            if not raw_data:
                return result

            lighthouse = raw_data.get("lighthouseResult", {})
            categories = lighthouse.get("categories", {})
            audits = lighthouse.get("audits", {})

            result["available"] = True
            result["performance_score"] = int(categories.get("performance", {}).get("score", 0) * 100) if categories.get("performance") else None
            result["accessibility_score"] = int(categories.get("accessibility", {}).get("score", 0) * 100) if categories.get("accessibility") else None
            result["seo_score"] = int(categories.get("seo", {}).get("score", 0) * 100) if categories.get("seo") else None
            result["lcp_ms"] = int(audits.get("largest-contentful-paint", {}).get("numericValue", 0)) if audits.get("largest-contentful-paint") else None
            result["cls"] = round(float(audits.get("cumulative-layout-shift", {}).get("numericValue", 0.0)), 3) if audits.get("cumulative-layout-shift") else None
            result["inp_ms"] = int(audits.get("interaction-to-next-paint", {}).get("numericValue", 0)) if audits.get("interaction-to-next-paint") else None
            result["fcp_ms"] = int(audits.get("first-contentful-paint", {}).get("numericValue", 0)) if audits.get("first-contentful-paint") else None
            result["ttfb_ms"] = int(audits.get("server-response-time", {}).get("numericValue", 0)) if audits.get("server-response-time") else None

            logger.info(f"   🚦 Lighthouse: Performance={result['performance_score']}/100 | Accessibility={result['accessibility_score']}/100 | SEO={result['seo_score']}/100 | LCP={result['lcp_ms']}ms")

        except Exception as e:
            logger.warning(f"Lighthouse audit failed: {e}")

        return result


# Singleton accessor
_deep_auditor_instance: Optional[DeepWebsiteAuditor] = None


def get_deep_auditor() -> DeepWebsiteAuditor:
    global _deep_auditor_instance
    if _deep_auditor_instance is None:
        _deep_auditor_instance = DeepWebsiteAuditor()
    return _deep_auditor_instance
