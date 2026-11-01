# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


class Cache:
    def __init__(self) -> None:
        self._redis = None
        self._mem: dict[str, tuple[str, float]] = {}

    async def connect(self, url: str) -> None:
        if not url:
            log.warning("REDIS_URL not set – using in-memory cache (state is lost on restart)")
            return
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(url, decode_responses=True)
            await client.ping()
            self._redis = client
            log.info("Redis connected")
        except Exception as exc:
            log.error("Redis unavailable (%s) – falling back to in-memory cache", exc)

    async def close(self) -> None:
        if self._redis:
            await self._redis.aclose()

    async def get(self, key: str) -> Optional[str]:
        if self._redis:
            return await self._redis.get(key)
        item = self._mem.get(key)
        if not item:
            return None
        value, exp = item
        if exp and exp < time.monotonic():
            self._mem.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl: int = 0) -> None:
        if self._redis:
            await self._redis.set(key, value, ex=ttl or None)
            return
        if len(self._mem) > 5000:
            self._prune()
        self._mem[key] = (value, time.monotonic() + ttl if ttl else 0)

    def _prune(self) -> None:
        now = time.monotonic()
        for k in [k for k, (_, exp) in self._mem.items() if exp and exp < now]:
            self._mem.pop(k, None)

    async def ttl(self, key: str) -> int:
        if self._redis:
            try:
                return max(0, int(await self._redis.ttl(key)))
            except Exception:
                return 0
        item = self._mem.get(key)
        if not item or not item[1]:
            return 0
        return max(0, int(item[1] - time.monotonic() + 0.999))

    async def refresh(self, key: str, ttl: int) -> bool:
        ttl = max(1, int(ttl))
        if self._redis:
            return bool(await self._redis.expire(key, ttl))
        value = await self.get(key)
        if value is None:
            return False
        await self.set(key, value, ttl)
        return True

    async def expire(self, key: str, ttl: int) -> bool:
        return await self.refresh(key, ttl)

    async def delete(self, *keys: str) -> None:
        if self._redis:
            await self._redis.delete(*keys)
            return
        for k in keys:
            self._mem.pop(k, None)

    async def clear_job_locks(self) -> int:
        patterns = ("job:*", "chk:*")
        if self._redis:
            removed = 0
            for pattern in patterns:
                batch = []
                async for key in self._redis.scan_iter(match=pattern, count=200):
                    batch.append(key)
                    if len(batch) >= 200:
                        removed += await self._redis.delete(*batch)
                        batch.clear()
                if batch:
                    removed += await self._redis.delete(*batch)
            return int(removed)
        keys = [k for k in self._mem if k.startswith(("job:", "chk:"))]
        for key in keys:
            self._mem.pop(key, None)
        return len(keys)

    async def pop(self, key: str) -> Optional[str]:
        if self._redis:
            async with self._redis.pipeline(transaction=True) as pipe:
                pipe.get(key)
                pipe.delete(key)
                value, _ = await pipe.execute()
            return value
        value = await self.get(key)
        self._mem.pop(key, None)
        return value

    async def acquire(self, key: str, ttl: int = 3600) -> bool:
        if self._redis:
            return bool(await self._redis.set(key, "1", nx=True, ex=ttl))
        if await self.get(key) is not None:
            return False
        await self.set(key, "1", ttl)
        return True

    async def release(self, key: str) -> None:
        await self.delete(key)


cache = Cache()
