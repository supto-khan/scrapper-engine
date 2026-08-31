import logging

logger = logging.getLogger(__name__)


class PlaywrightFallbackMiddleware:
    """
    Middleware to safely intercept and log Playwright errors or fall back gracefully.
    """

    def process_exception(self, request, exception, spider):
        if request.meta.get("playwright"):
            logger.warning(
                f"Playwright request for {request.url} encountered: {exception}. "
                "Note: If Upwork hangs or drops TLS handshakes, please enable your VPN or set PROXY_URL in .env."
            )
