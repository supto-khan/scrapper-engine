import os
import urllib.parse

import redis
from dotenv import load_dotenv

load_dotenv()


def normalize_domain(url_or_domain: str) -> str:
    """
    Normalizes a URL or domain string into a clean lowercase domain format.
    Example: 'https://www.example.com/path/?a=1' -> 'example.com'
             'sub.example.com/' -> 'sub.example.com'
    """
    if not url_or_domain:
        return ""

    raw = url_or_domain.strip().lower()

    # Ensure URL has a scheme for urllib parsing
    if not (raw.startswith("http://") or raw.startswith("https://")):
        raw = "http://" + raw

    try:
        parsed = urllib.parse.urlparse(raw)
        netloc = parsed.netloc or parsed.path
    except Exception:
        netloc = raw

    # Strip port if present
    netloc = netloc.split(":")[0]

    # Strip leading 'www.'
    netloc = netloc.removeprefix("www.")

    # Remove non-domain artifacts and trailing slashes
    netloc = netloc.strip("/ ")
    return netloc


class RedisClient:
    """
    Redis client manager providing connection testing, domain deduplication,
    and queue management.
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        db: int | None = None,
        password: str | None = None,
    ):
        self.host = host or os.getenv("REDIS_HOST", "127.0.0.1")
        self.port = int(port or os.getenv("REDIS_PORT", 6379))
        self.db = int(db or os.getenv("REDIS_DB", 0))
        self.password = password or os.getenv("REDIS_PASSWORD") or None

        self._pool = redis.ConnectionPool(
            host=self.host,
            port=self.port,
            db=self.db,
            password=self.password,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        self.client = redis.Redis(connection_pool=self._pool)

    def ping(self) -> bool:
        """Checks if Redis server is reachable."""
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def is_domain_seen(self, domain_or_url: str, set_key: str = "seen_domains") -> bool:
        """Checks if a normalized domain has already been seen in Redis."""
        domain = normalize_domain(domain_or_url)
        if not domain:
            return True
        return bool(self.client.sismember(set_key, domain))

    def mark_domain_seen(
        self, domain_or_url: str, set_key: str = "seen_domains"
    ) -> bool:
        """
        Adds a normalized domain to the seen set in Redis.
        Returns True if the domain was new and added, False if it was already present.
        """
        domain = normalize_domain(domain_or_url)
        if not domain:
            return False
        return self.client.sadd(set_key, domain) > 0


# Shared singleton instance
_redis_instance: RedisClient | None = None


def get_redis_client() -> RedisClient:
    global _redis_instance
    if _redis_instance is None:
        _redis_instance = RedisClient()
    return _redis_instance
