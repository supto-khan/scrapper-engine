import logging
import random
import re
import time
import urllib.parse
from typing import Any
from bs4 import BeautifulSoup
from shared import http_client

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
]


class GoogleMapsCrawler:
    """
    Crawls and extracts business listings from Google Maps local searches.
    Exhaustively paginates through all available result pages until end of results.
    """

    def __init__(self, timeout: int = 15):
        self.timeout = timeout

    def search_local_businesses(self, category: str, city: str, max_pages: int = 20, limit_per_page: int = 20) -> list[dict[str, Any]]:
        """
        Queries Google local listings for a category in a specific city/market,
        exhaustively paginating through every page until the very end of Google Maps results.
        """
        results: list[dict[str, Any]] = []
        seen_place_keys: set[str] = set()
        search_query = f"{category} in {city}"
        encoded_query = urllib.parse.quote_plus(search_query)

        for page in range(1, max_pages + 1):
            start_offset = (page - 1) * 20
            url = f"https://www.google.com/search?q={encoded_query}&tbm=lcl&hl=en&gl=us&start={start_offset}"

            headers = {
                "User-Agent": random.choice(USER_AGENTS),
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"macOS"',
            }

            try:
                r = http_client.get(url, headers=headers, impersonate="chrome124", timeout=self.timeout)
                if r.status_code != 200:
                    logger.warning(f"Google Maps local query returned HTTP {r.status_code} for query: '{search_query}' on Page {page}")
                    break

                soup = BeautifulSoup(r.text, "html.parser")

                # Multi-selector fallback for Google Local Pack cards
                cards = soup.select("div.VkpGBb, div.C8daKB, div[jscontroller='AtSb']")
                if not cards:
                    cards = soup.select("div[data-cid], div.rllt__details")

                if not cards:
                    logger.info(f"   ℹ️ Reached end of Google Maps results on Page {page} for '{search_query}'.")
                    break

                new_on_page = 0
                for card in cards[:limit_per_page]:
                    name_elem = card.select_one("div.dbg0pd, span.OSrXXb, div.qBF1Pd, div.fontHeadlineSmall")
                    name = name_elem.get_text(strip=True) if name_elem else ""
                    if not name:
                        continue

                    # Extract website link
                    website_url = None
                    links = card.select("a[href]")
                    for link in links:
                        href = link.get("href", "")
                        text = link.get_text(strip=True).lower()
                        if "website" in text or "site" in text:
                            if "/url?q=" in href:
                                parsed_q = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                                website_url = parsed_q.get("q", [None])[0]
                            elif href.startswith("http") and "google.com" not in href:
                                website_url = href
                            break
                        elif href.startswith("http") and not any(k in href for k in ["google.com", "maps.google", "search?"]):
                            website_url = href
                            break

                    # Extract rating & review count
                    rating = None
                    review_count = None
                    rating_elem = card.select_one("span.Y0A0hc, span.yi40Hd, span.MW4etd")
                    if rating_elem:
                        try:
                            rating = float(rating_elem.get_text(strip=True).replace(",", "."))
                        except ValueError:
                            rating = None

                    reviews_elem = card.select_one("span.RDApEe, span.hG4AEc, span.UY7F9")
                    if reviews_elem:
                        rev_text = re.sub(r"\D+", "", reviews_elem.get_text(strip=True))
                        if rev_text:
                            try:
                                review_count = int(rev_text)
                            except ValueError:
                                review_count = None

                    # Extract phone number
                    details_text = card.get_text(" ", strip=True)
                    phone_match = re.search(r"(\+?1[-.\s]?)?(\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})", details_text)
                    phone = phone_match.group(0).strip() if phone_match else None

                    # Local page deduplication key
                    place_key = f"{name.lower()}:{phone or ''}"
                    if place_key in seen_place_keys:
                        continue
                    seen_place_keys.add(place_key)
                    new_on_page += 1

                    results.append({
                        "name": name,
                        "city": city,
                        "category": category,
                        "website_url": website_url,
                        "phone": phone,
                        "rating": rating,
                        "review_count": review_count,
                        "raw_details": details_text[:300],
                    })

                logger.info(f"   ✓ [Page {page}] Extracted {new_on_page} fresh listings (Total so far: {len(results)}) for '{category} in {city}'")

                # If no new cards or fewer than 6 cards on page, we have hit the end of Google Maps results
                if new_on_page == 0 or len(cards) < 6:
                    logger.info(f"   🏁 Completed full search traversal for '{search_query}' ({len(results)} total leads).")
                    break

                # Humanized inter-page jitter
                time.sleep(random.uniform(2.0, 3.5))

            except Exception as e:
                logger.error(f"Error scraping Google Maps page {page} for '{search_query}': {e}")
                break

        logger.info(f"📍 Google Maps Query Finished: {len(results)} businesses found for '{category} in {city}' (No-website: {sum(1 for x in results if not x.get('website_url'))})")
        return results

