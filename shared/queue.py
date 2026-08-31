import json
from typing import Any

from shared.redis_client import RedisClient, get_redis_client


class RedisQueue:
    """
    Redis list-backed FIFO queue for worker decoupling.
    """

    def __init__(self, name: str, redis_client: RedisClient | None = None):
        self.name = f"queue:{name}"
        self.client = (redis_client or get_redis_client()).client

    def push(self, item: Any) -> int:
        """Pushes an item (serialized to JSON) to the tail of the queue."""
        payload = json.dumps(item)
        return self.client.rpush(self.name, payload)

    def pop(self, timeout: int = 0) -> Any | None:
        """Pops an item from the head of the queue. If timeout > 0, performs blocking pop (BLPOP)."""
        if timeout > 0:
            result = self.client.blpop(self.name, timeout=timeout)
            if result:
                _, payload = result
                return json.loads(payload)
            return None
        else:
            payload = self.client.lpop(self.name)
            if payload:
                return json.loads(payload)
            return None

    def size(self) -> int:
        """Returns the number of elements in the queue."""
        return self.client.llen(self.name)

    def clear(self) -> None:
        """Clears all items in the queue."""
        self.client.delete(self.name)
