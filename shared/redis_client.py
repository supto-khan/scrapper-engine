import os
import re
import urllib.parse

try:
    import redis
except ImportError:
    redis = None

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


def normalize_company_name(name: str) -> str:
    """
    Normalizes a business or company name into a clean lowercase slug for deduplication.
    Example: 'Aspen Dental, LLC' -> 'aspen-dental'
             'Apex Roofing Specialists & Co.' -> 'apex-roofing-specialists'
    """
    if not name:
        return ""
    cleaned = name.lower().strip()
    # Strip common legal suffixes
    cleaned = re.sub(r"\b(llc|inc|corp|corporation|co|ltd|pllc|pc|dds|dmd|group)\b", "", cleaned)
    # Convert punctuation/whitespace to single hyphen
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return cleaned


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

        if redis is not None:
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
        else:
            self._pool = None
            self.client = None

    def ping(self) -> bool:
        """Checks if Redis server is reachable."""
        if not self.client:
            return False
        try:
            return bool(self.client.ping())
        except Exception:
            return False

    def is_domain_seen(self, domain_or_url: str, set_key: str = "seen_domains") -> bool:
        """Checks if a normalized domain has already been seen in Redis."""
        domain = normalize_domain(domain_or_url)
        if not domain or not self.client:
            return False
        try:
            return bool(self.client.sismember(set_key, domain))
        except Exception:
            return False

    def mark_domain_seen(
        self, domain_or_url: str, set_key: str = "seen_domains"
    ) -> bool:
        """
        Adds a normalized domain to the seen set in Redis.
        Returns True if the domain was new and added, False if it was already present.
        """
        domain = normalize_domain(domain_or_url)
        if not domain or not self.client:
            return False
        try:
            return self.client.sadd(set_key, domain) > 0
        except Exception:
            return False

    def is_name_seen(self, name: str, city: str = "", set_key: str = "seen_names") -> bool:
        """Checks if a normalized company name or (name + city) has already been seen in Redis."""
        slug = normalize_company_name(name)
        if not slug or not self.client:
            return False
        try:
            if bool(self.client.sismember(set_key, slug)):
                return True
            if city:
                slug_city = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")
                if slug_city and bool(self.client.sismember(set_key, f"{slug}:{slug_city}")):
                    return True
        except Exception:
            return False
        return False

    def mark_name_seen(self, name: str, city: str = "", set_key: str = "seen_names") -> bool:
        """Marks a company name and (name + city) as seen in Redis."""
        slug = normalize_company_name(name)
        if not slug or not self.client:
            return False
        try:
            added = self.client.sadd(set_key, slug) > 0
            if city:
                slug_city = re.sub(r"[^a-z0-9]+", "-", city.lower()).strip("-")
                if slug_city:
                    self.client.sadd(set_key, f"{slug}:{slug_city}")
            return added
        except Exception:
            return False


# Shared singleton instance
_redis_instance: RedisClient | None = None


def get_redis_client() -> RedisClient:
    global _redis_instance
    if _redis_instance is None:
        _redis_instance = RedisClient()
    return _redis_instance
