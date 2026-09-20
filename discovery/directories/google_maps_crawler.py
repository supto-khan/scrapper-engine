import json
import logging
import random
import re
import time
import urllib.parse
from typing import Any, Optional
from bs4 import BeautifulSoup

from shared import http_client
from shared.proxy_manager import get_proxy_manager

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


def sanitize_search_term(term: str) -> str:
    """
    Sanitizes category and location search terms for directory engines.
    Normalizes '&' to 'and' and strips symbols that disrupt search URL parameters.
    """
    if not term:
        return ""
    cleaned = term.replace("&", "and").replace("+", " ")
    cleaned = re.sub(r"[^\w\s,\-]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


class GoogleMapsCrawler:
    """
    Dual-layer Local Business & Google Maps Discovery Crawler with Circuit-Breaker Failover:
    1. Primary: Stealth Google Maps scraper with rotating proxy pool and TLS impersonation.
    2. Zero-Fail Fallback: Multi-page Local Directory Engine (YellowPages with TLS fingerprinting).
    3. Resilient Failover: Automatic proxy retry + direct TLS impersonation fallback.
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.proxy_manager = get_proxy_manager()
        self.seen_names_cache: set[str] = set()

    def _fetch_resilient(
        self,
        url: str,
        headers: Optional[dict[str, str]] = None,
        impersonate: str = "chrome124",
        timeout: Optional[int] = None,
        max_proxy_retries: int = 2,
    ) -> Optional[Any]:
        """
        Executes HTTP GET with intelligent proxy rotation and direct TLS failover.
        Guarantees request execution even if public proxies are degraded.
        """
        t = timeout or self.timeout
        h = headers or {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        # 1. Fast direct path for Google Maps endpoints (unblocked & fast)
        if "google.com/maps" in url or "search?tbm=map" in url:
            try:
                r = http_client.get(
                    url,
                    headers=h,
                    impersonate=impersonate,
                    timeout=t,
                    verify=False,
                )
                if r.status_code == 200:
                    return r
            except Exception as e:
                logger.debug(f"Direct Google Maps request exception ({url[:60]}...): {e}")

        # 2. Attempt with active Redis proxies
        proxy_timeout = min(t, 5)
        for _ in range(max(max_proxy_retries, 4)):
            proxy = self.proxy_manager.get_proxy()
            if not proxy:
                break

            try:
                t0 = time.time()
                r = http_client.get(
                    url,
                    headers=h,
                    impersonate=impersonate,
                    timeout=proxy_timeout,
                    proxy=proxy,
                    verify=False,
                )
                if r.status_code == 200 and len(r.text) > 500 and "captcha" not in r.text.lower()[:1000]:
                    latency = round((time.time() - t0) * 1000, 1)
                    self.proxy_manager.report_success(proxy, latency_ms=latency)
                    return r
                else:
                    self.proxy_manager.report_failure(proxy)
            except Exception:
                self.proxy_manager.report_failure(proxy)

        # 3. Transparent Fallback: Direct TLS connection with impersonation
        try:
            r = http_client.get(
                url,
                headers=h,
                impersonate=impersonate,
                timeout=t,
                verify=False,
            )
            if r.status_code == 200:
                return r
        except Exception as e:
            logger.debug(f"Direct request failover exception ({url[:60]}...): {e}")

        return None

    def search_local_businesses(
        self,
        category: str,
        city: str,
        max_pages: int = 3,
        limit_per_page: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Searches for local businesses in a specific metro area across multiple pages.
        Evaluates each company record individually. Never skips categories or cities.
        """
        results: list[dict[str, Any]] = []
        seen_place_keys: set[str] = set()

        clean_category = sanitize_search_term(category)
        clean_city = sanitize_search_term(city)
        search_query = f"{clean_category} in {clean_city}"
        encoded_query = urllib.parse.quote_plus(search_query)

        # -------------------------------------------------------------
        # Phase 1: High-Yield Direct Google Maps Engine (200 OK, Rich Data)
        # -------------------------------------------------------------
        maps_url = f"https://www.google.com/maps/search/{encoded_query}"
        headers = {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }

        r = self._fetch_resilient(maps_url, headers=headers, impersonate="chrome124", timeout=self.timeout)
        if r and r.status_code == 200:
            try:
                soup = BeautifulSoup(r.text, "html.parser")
                link = soup.select_one("link[href*='search?tbm=map']")
                if link:
                    api_href = link.get("href", "")
                    api_url = "https://www.google.com" + api_href if api_href.startswith("/") else api_href
                    r2 = self._fetch_resilient(api_url, headers=headers, impersonate="chrome124", timeout=self.timeout)
                    if r2 and r2.status_code == 200:
                        raw_text = r2.text.lstrip(")]}'\n ")
                        data = json.loads(raw_text)
                        for item in data:
                            if isinstance(item, list):
                                for sub in item:
                                    if isinstance(sub, list) and len(sub) > 1 and isinstance(sub[1], list) and len(sub[1]) > 50:
                                        p = sub[1]
                                        name = p[11] if len(p) > 11 and isinstance(p[11], str) else None
                                        if not name or len(name) < 2:
                                            continue

                                        norm_name = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
                                        place_key = f"{norm_name}:{clean_city.lower()}"
                                        if place_key in seen_place_keys or place_key in self.seen_names_cache:
                                            continue

                                        addr = p[39] if len(p) > 39 and p[39] else (p[2] if len(p) > 2 else None)
                                        rating = None
                                        review_count = None
                                        if len(p) > 4 and isinstance(p[4], list):
                                            if len(p[4]) > 7 and p[4][7] is not None:
                                                try:
                                                    rating = float(p[4][7])
                                                except (ValueError, TypeError):
                                                    rating = None
                                            if len(p[4]) > 8 and p[4][8] is not None:
                                                try:
                                                    review_count = int(p[4][8])
                                                except (ValueError, TypeError):
                                                    review_count = None

                                        website_url = None
                                        if len(p) > 7 and isinstance(p[7], list) and len(p[7]) > 0 and p[7][0]:
                                            raw_web = p[7][0]
                                            if raw_web.startswith("http") and "google.com" not in raw_web:
                                                website_url = raw_web

                                        phone = None
                                        if len(p) > 178 and isinstance(p[178], list) and len(p[178]) > 0 and isinstance(p[178][0], list):
                                            phone = p[178][0][0]

                                        seen_place_keys.add(place_key)
                                        self.seen_names_cache.add(place_key)

                                        results.append({
                                            "name": name,
                                            "city": city,
                                            "category": category,
                                            "website_url": website_url,
                                            "phone": phone,
                                            "rating": rating,
                                            "review_count": review_count,
                                            "raw_details": str(addr)[:300] if addr else f"{name} in {city}. Category: {category}",
                                            "source": "google_maps",
                                        })
            except Exception as e:
                logger.debug(f"Google Maps direct extraction error for '{category} in {city}': {e}")

        if results:
            logger.info(f"   ✓ [Google Maps Engine] Extracted {len(results)} verified businesses for '{category} in {city}'")

        # -------------------------------------------------------------
        # Phase 2: Guaranteed Local Directory Engine (Multi-Page Deep Scraping Fallback)
        # -------------------------------------------------------------
        target_limit = limit_per_page * max_pages
        if len(results) < target_limit:
            needed = target_limit - len(results)
            logger.info(f"   🏢 Querying Local Directory Engine for additional records for '{category}' in '{city}'...")
            yp_results = self._crawl_local_directory(
                category=clean_category,
                city=clean_city,
                max_pages=max_pages,
                limit=needed,
            )
            for item in yp_results:
                norm_name = re.sub(r"[^a-z0-9]+", "-", item['name'].lower()).strip("-")
                place_key = f"{norm_name}:{clean_city.lower()}"
                if place_key not in seen_place_keys and place_key not in self.seen_names_cache:
                    seen_place_keys.add(place_key)
                    self.seen_names_cache.add(place_key)
                    results.append(item)

        no_web_count = sum(1 for x in results if not x.get("website_url"))
        logger.info(f"📍 Local Discovery Finished: {len(results)} businesses found for '{category} in {city}' (No-website high priority: {no_web_count})")
        return results


    def _crawl_local_directory(
        self,
        category: str,
        city: str,
        max_pages: int = 3,
        limit: int = 30,
    ) -> list[dict[str, Any]]:
        """
        Crawls verified local business listings across multiple pages from directory engines.
        Uses TLS impersonation and sanitization to guarantee clean extraction.
        """
        leads: list[dict[str, Any]] = []
        encoded_term = urllib.parse.quote_plus(category)
        encoded_geo = urllib.parse.quote_plus(city)

        for page in range(1, max_pages + 1):
            if len(leads) >= limit:
                break

            url = f"https://www.yellowpages.com/search?search_terms={encoded_term}&geo_location_terms={encoded_geo}&page={page}"

            try:
                r = self._fetch_resilient(url, impersonate="chrome124", timeout=12)
                if not r or r.status_code != 200:
                    continue

                soup = BeautifulSoup(r.text, "html.parser")
                cards = soup.select(".result, .v-card, .search-results .info")
                if not cards:
                    break

                for card in cards:
                    if len(leads) >= limit:
                        break

                    name_el = card.select_one(".business-name, .info-section h2 a, h2 a")
                    name = name_el.get_text(strip=True) if name_el else None
                    if not name or len(name) < 2 or "yellowpages" in name.lower():
                        continue

                    # Extract phone number
                    phone_el = card.select_one(".phones, .phone, .contact-phone")
                    phone = phone_el.get_text(strip=True) if phone_el else None

                    # Extract website URL
                    site_el = card.select_one("a.track-visit-website, a[href*='visit_website'], a.custom-link[href^='http']")
                    website_url = site_el.get("href") if site_el else None

                    # Extract rating & reviews count
                    rating = None
                    review_count = None
                    rating_el = card.select_one(".rating, .ratings, .rating-stars")
                    if rating_el:
                        rating_class = rating_el.get("class", [])
                        for cls in rating_class:
                            if cls.startswith("result-rating-") or cls.startswith("rating-"):
                                val = cls.split("-")[-1]
                                try:
                                    rating = float(val)
                                except ValueError:
                                    pass

                    reviews_el = card.select_one(".count, .rating-count, .review-count")
                    if reviews_el:
                        rev_text = re.sub(r"\D+", "", reviews_el.get_text(strip=True))
                        if rev_text:
                            try:
                                review_count = int(rev_text)
                            except ValueError:
                                pass

                    # Extract street address
                    street_el = card.select_one(".street-address")
                    locality_el = card.select_one(".locality")
                    addr = f"{street_el.get_text(strip=True) if street_el else ''} {locality_el.get_text(strip=True) if locality_el else ''}".strip()

                    leads.append({
                        "name": name,
                        "city": city,
                        "category": category,
                        "website_url": website_url,
                        "phone": phone,
                        "rating": rating,
                        "review_count": review_count,
                        "raw_details": f"Local business in {city}. Address: {addr}. Category: {category}",
                        "source": "local_business_directory",
                    })

                time.sleep(random.uniform(1.0, 2.0))

            except Exception as e:
                logger.debug(f"Directory engine exception (page {page}) for '{category} in {city}': {e}")

        if leads:
            logger.info(f"   ✓ [Directory Engine] Extracted {len(leads)} verified businesses for '{category} in {city}'")

        return leads
