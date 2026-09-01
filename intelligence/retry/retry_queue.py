"""
Nexidant Signal Engine — Per-Company Retry Queue

When a deep audit fails for a company (network timeout, CloudFlare block,
DNS issue), queue it for retry on the next pipeline run with exponential
backoff instead of permanently skipping it.

Uses Redis sorted set keyed by next-retry timestamp for efficient pop.
After MAX_RETRIES, moves to dead-letter queue for manual inspection.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

from shared.redis_client import get_redis_client

logger = logging.getLogger(__name__)

# Configuration
MAX_RETRIES = 4
BASE_BACKOFF_MINUTES = 30  # 2^retry_count * 30 minutes
RETRY_QUEUE_KEY = "queue:audit_retry"
DEAD_LETTER_KEY = "queue:audit_dead_letter"


class CompanyRetryQueue:
    """
    Redis-backed retry queue for failed company audits.
    Uses a sorted set with score = next_retry_at (unix timestamp)
    so we can efficiently pop only items whose retry time has arrived.
    """

    def __init__(self):
        self.redis = get_redis_client()

    def push_retry(
        self,
        company_id: int,
        domain: str,
        error: str,
        retry_count: int = 0,
    ):
        """
        Push a failed audit into the retry queue with exponential backoff.
        If max retries exceeded, send to dead-letter queue.
        """
        next_retry_count = retry_count + 1

        if next_retry_count > MAX_RETRIES:
            # Dead letter — manual inspection needed
            dead_item = json.dumps({
                "company_id": company_id,
                "domain": domain,
                "retry_count": retry_count,
                "last_error": str(error)[:500],
                "dead_lettered_at": datetime.now(timezone.utc).isoformat(),
            })
            self.redis.client.rpush(DEAD_LETTER_KEY, dead_item)
            logger.warning(
                f"💀 Company {domain} (#{company_id}) moved to dead-letter queue "
                f"after {retry_count} failed retries. Last error: {error}"
            )
            return

        # Calculate backoff: 2^retry_count * BASE_BACKOFF_MINUTES
        backoff_minutes = (2 ** next_retry_count) * BASE_BACKOFF_MINUTES
        next_retry_at = time.time() + (backoff_minutes * 60)

        item = json.dumps({
            "company_id": company_id,
            "domain": domain,
            "retry_count": next_retry_count,
            "last_error": str(error)[:500],
            "queued_at": datetime.now(timezone.utc).isoformat(),
            "next_retry_at": datetime.fromtimestamp(next_retry_at, tz=timezone.utc).isoformat(),
        })

        self.redis.client.zadd(RETRY_QUEUE_KEY, {item: next_retry_at})
        logger.info(
            f"🔄 Queued retry #{next_retry_count}/{MAX_RETRIES} for {domain} (#{company_id}) "
            f"— next attempt in {backoff_minutes} minutes"
        )

    def pop_due_retries(self, max_items: int = 20) -> list[dict[str, Any]]:
        """
        Pop all retry items whose next_retry_at has passed.
        Returns list of dicts with company_id, domain, retry_count.
        """
        now = time.time()
        results = []

        # Fetch items with score <= now (due for retry)
        items = self.redis.client.zrangebyscore(
            RETRY_QUEUE_KEY, "-inf", now, start=0, num=max_items
        )

        if not items:
            return results

        for raw_item in items:
            try:
                item = json.loads(raw_item)
                results.append(item)
                # Remove from sorted set
                self.redis.client.zrem(RETRY_QUEUE_KEY, raw_item)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Failed to parse retry item: {e}")
                self.redis.client.zrem(RETRY_QUEUE_KEY, raw_item)

        if results:
            logger.info(
                f"📋 Popped {len(results)} due retries from queue: "
                + ", ".join(f"{r['domain']} (attempt #{r['retry_count']})" for r in results)
            )

        return results

    def pending_count(self) -> int:
        """Returns total number of items in the retry queue (including future)."""
        return self.redis.client.zcard(RETRY_QUEUE_KEY)

    def due_count(self) -> int:
        """Returns number of items that are currently due for retry."""
        return self.redis.client.zcount(RETRY_QUEUE_KEY, "-inf", time.time())

    def dead_letter_count(self) -> int:
        """Returns number of items in the dead-letter queue."""
        return self.redis.client.llen(DEAD_LETTER_KEY)

    def peek_dead_letter(self, count: int = 10) -> list[dict[str, Any]]:
        """Peek at items in the dead-letter queue without removing them."""
        items = self.redis.client.lrange(DEAD_LETTER_KEY, 0, count - 1)
        results = []
        for raw in items:
            try:
                results.append(json.loads(raw))
            except Exception:
                pass
        return results

    def clear_dead_letter(self) -> int:
        """Clear the dead-letter queue. Returns count of items removed."""
        count = self.redis.client.llen(DEAD_LETTER_KEY)
        self.redis.client.delete(DEAD_LETTER_KEY)
        return count


# ─── Module Accessor ──────────────────────────────────────────────────────

_retry_queue: CompanyRetryQueue | None = None


def get_retry_queue() -> CompanyRetryQueue:
    global _retry_queue
    if _retry_queue is None:
        _retry_queue = CompanyRetryQueue()
    return _retry_queue
