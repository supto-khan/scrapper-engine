import logging
import os

import yaml

logger = logging.getLogger(__name__)


class ProxyMiddleware:
    """
    Downloader middleware to configure HTTP/HTTPS/SOCKS proxy per request.
    Reads config from config/proxies.yaml or .env.
    """

    def __init__(self, proxy_url=None, enabled=False):
        self.proxy_url = proxy_url
        self.enabled = enabled

    @classmethod
    def from_crawler(cls, crawler):
        config_path = "config/proxies.yaml"
        proxy_url = os.getenv("PROXY_URL", "")
        enabled = os.getenv("USE_PROXIES", "false").lower() == "true"

        if os.path.exists(config_path):
            try:
                with open(config_path, "r") as f:
                    cfg = yaml.safe_load(f) or {}
                    if cfg.get("enabled"):
                        enabled = True
                        proxy_url = (
                            cfg.get("http_proxy")
                            or cfg.get("https_proxy")
                            or cfg.get("socks_proxy")
                            or proxy_url
                        )
            except Exception as e:
                logger.warning(f"Failed to read {config_path}: {e}")

        return cls(proxy_url=proxy_url, enabled=enabled)

    def process_request(self, request, spider):
        if self.enabled and self.proxy_url:
            request.meta["proxy"] = self.proxy_url
