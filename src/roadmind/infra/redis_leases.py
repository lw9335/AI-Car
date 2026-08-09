from __future__ import annotations

from redis import Redis

from roadmind.application.ports import LeaseConflict

_COMPARE_AND_DELETE = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


class RedisResourceLeaseBook:
    def __init__(self, client: Redis) -> None:
        self._client = client

    def _key(self, resource_id: str) -> str:
        return f"resource:{resource_id}"

    def reserve(self, resource_id: str, order_id: str, *, ttl_seconds: int = 120) -> None:
        key = self._key(resource_id)
        current = self._client.get(key)
        if current is not None:
            holder = current.decode() if isinstance(current, bytes) else str(current)
            if holder != order_id:
                raise LeaseConflict(resource_id)
            self._client.pexpire(key, ttl_seconds * 1000)
            return
        ok = self._client.set(key, order_id, nx=True, px=ttl_seconds * 1000)
        if not ok:
            raise LeaseConflict(resource_id)

    def release(self, resource_id: str, order_id: str) -> None:
        self._client.eval(_COMPARE_AND_DELETE, 1, self._key(resource_id), order_id)
