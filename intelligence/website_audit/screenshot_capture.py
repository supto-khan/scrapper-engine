"""
Nexidant Signal Engine — Website Screenshot Capture Engine
Uses Playwright headless Chromium to capture high-resolution, above-the-fold
screenshots of target websites for embedding in branded PDF audit reports.
"""

import logging
import os
import time
from typing import Optional

from PIL import Image
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class WebsiteScreenshotCapture:
    """
    Captures live website screenshots for PDF report embedding.
    """

    def __init__(self, output_dir: Optional[str] = None):
        base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.output_dir = output_dir or os.path.join(base, "reports", "screenshots")
        os.makedirs(self.output_dir, exist_ok=True)

    def capture_screenshot(
        self,
        url: str,
        domain: str,
        viewport_width: int = 1280,
        viewport_height: int = 800,
        timeout_ms: int = 12000,
    ) -> Optional[str]:
        """
        Captures an above-the-fold screenshot of url, compresses it,
        and saves it to reports/screenshots/{domain_slug}.png.
        Returns the absolute file path, or None on failure.
        """
        clean_domain = domain.strip().lower().replace("http://", "").replace("https://", "").strip("/").replace(".", "_")
        raw_filepath = os.path.join(self.output_dir, f"{clean_domain}_raw.png")
        final_filepath = os.path.join(self.output_dir, f"{clean_domain}_preview.png")

        # Normalize URL
        target_url = url
        if not target_url.startswith("http://") and not target_url.startswith("https://"):
            target_url = f"https://{target_url}"

        logger.info(f"📸 Capturing above-the-fold screenshot for {domain} ({target_url})...")
        t_start = time.time()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )
                context = browser.new_context(
                    viewport={"width": viewport_width, "height": viewport_height},
                    user_agent=USER_AGENT,
                    ignore_https_errors=True,
                )
                page = context.new_page()

                try:
                    # Navigate and wait for DOM content or load
                    page.goto(target_url, timeout=timeout_ms, wait_until="domcontentloaded")
                    # Brief pause for webfonts / hero images to render
                    time.sleep(1.0)
                except Exception as nav_err:
                    logger.debug(f"Navigation timeout/notice for {domain}, attempting screenshot anyway: {nav_err}")

                # Capture viewport only (above the fold)
                page.screenshot(path=raw_filepath, full_page=False)
                browser.close()

            # Optimize image via Pillow: resize to standard aspect ratio & compress
            if os.path.exists(raw_filepath):
                with Image.open(raw_filepath) as img:
                    # Convert to RGB if needed
                    if img.mode in ("RGBA", "P"):
                        rgb_img = Image.new("RGB", img.size, (255, 255, 255))
                        if img.mode == "RGBA":
                            rgb_img.paste(img, mask=img.split()[3])
                        else:
                            rgb_img.paste(img)
                        img = rgb_img

                    # Resize to crisp 640x400 thumbnail (half resolution for sharp PDF rendering)
                    img.thumbnail((640, 400), Image.Resampling.LANCZOS)
                    img.save(final_filepath, "PNG", optimize=True)

                # Remove raw file
                try:
                    os.remove(raw_filepath)
                except Exception:
                    pass

                elapsed = round(time.time() - t_start, 2)
                logger.info(f"✅ Screenshot captured for {domain} in {elapsed}s: {final_filepath}")
                return final_filepath

        except Exception as e:
            logger.warning(f"⚠️ Failed to capture screenshot for {domain}: {e}")
            try:
                if os.path.exists(raw_filepath):
                    os.remove(raw_filepath)
            except Exception:
                pass
            return None


# ─── Module Accessor ──────────────────────────────────────────────────────

_screenshot_instance: Optional[WebsiteScreenshotCapture] = None


def get_screenshot_capture() -> WebsiteScreenshotCapture:
    global _screenshot_instance
    if _screenshot_instance is None:
        _screenshot_instance = WebsiteScreenshotCapture()
    return _screenshot_instance
