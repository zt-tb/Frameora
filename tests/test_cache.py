# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio

from cache import Cache
import handlers


def test_startup_cleanup_removes_only_job_lock_keys():
    async def run():
        cache = Cache()
        await cache.set("job:123", "1", 3600)
        await cache.set("chk:123", "1", 900)
        await cache.set("lang:123", "ar", 3600)
        assert await cache.clear_job_locks() == 2
        assert await cache.get("job:123") is None
        assert await cache.get("chk:123") is None
        assert await cache.get("lang:123") == "ar"
    asyncio.run(run())


def test_memory_lock_refresh_and_expire_extend_existing_key_only():
    async def run():
        cache = Cache()
        await cache.set("job:1", "1", 1)
        await asyncio.sleep(0.55)
        assert await cache.refresh("job:1", 2)
        assert await cache.ttl("job:1") >= 1
        await asyncio.sleep(0.55)
        assert await cache.get("job:1") == "1"
        assert await cache.expire("job:1", 1)
        await asyncio.sleep(1.1)
        assert await cache.get("job:1") is None
        assert not await cache.refresh("job:1", 10)
    asyncio.run(run())


def test_redis_refresh_uses_expire_and_returns_existing_key_state():
    class FakeRedis:
        def __init__(self):
            self.keys = {"job:2": "1"}
            self.expiration = None

        async def expire(self, key, ttl):
            self.expiration = (key, ttl)
            return key in self.keys

    async def run():
        cache = Cache()
        redis = FakeRedis()
        cache._redis = redis
        assert await cache.refresh("job:2", 600)
        assert redis.expiration == ("job:2", 600)
        assert not await cache.expire("job:missing", 600)
    asyncio.run(run())


def test_heartbeat_stops_if_lock_was_removed(monkeypatch):
    class GoneLockCache:
        def __init__(self):
            self.refreshed = []

        async def refresh(self, key, ttl):
            self.refreshed.append((key, ttl))
            return False

    async def run():
        cache = GoneLockCache()
        monkeypatch.setattr(handlers, "cache", cache)
        monkeypatch.setattr(handlers.config, "JOB_LOCK_TTL_SECONDS", 30)
        real_sleep = asyncio.sleep

        async def instant_sleep(_):
            await real_sleep(0)

        monkeypatch.setattr(handlers.asyncio, "sleep", instant_sleep)
        await handlers._job_lock_heartbeat(77)
        assert cache.refreshed == [("job:77", 30)]
    asyncio.run(run())
