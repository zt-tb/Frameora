# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio

import main


class LockSequence:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = 0

    async def acquire_instance_lock(self):
        self.calls += 1
        return next(self.results, False)


def test_wait_for_instance_lock_retries_until_available(monkeypatch):
    async def run():
        fake = LockSequence([False, False, True])
        monkeypatch.setattr(main, "db", fake)
        real_sleep = asyncio.sleep

        async def instant_sleep(_):
            await real_sleep(0)

        monkeypatch.setattr(main.asyncio, "sleep", instant_sleep)
        assert await main._wait_for_instance_lock(timeout=1, interval=0.001)
        assert fake.calls == 3
    asyncio.run(run())


def test_wait_for_instance_lock_returns_false_after_timeout(monkeypatch):
    async def run():
        fake = LockSequence([])
        monkeypatch.setattr(main, "db", fake)
        assert not await main._wait_for_instance_lock(timeout=0, interval=0.001)
        assert fake.calls == 1
    asyncio.run(run())
