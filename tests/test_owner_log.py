# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio

from cache import Cache
import owner_log


class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        if self.fail:
            raise RuntimeError("network unavailable")
        self.sent.append((chat_id, text, kwargs))


def test_owner_log_is_disabled_without_chat_id(monkeypatch):
    async def run():
        client = FakeClient()
        monkeypatch.setattr(owner_log.config, "LOG_CHAT_ID", 0)
        assert not await owner_log.notify_owner(client, "start")
        assert not client.sent
    asyncio.run(run())


def test_owner_log_is_rate_limited_and_contains_only_given_safe_message(monkeypatch):
    async def run():
        client = FakeClient()
        monkeypatch.setattr(owner_log.config, "LOG_CHAT_ID", -100123)
        monkeypatch.setattr(owner_log, "cache", Cache())
        assert await owner_log.notify_owner(client, "Frameora started.")
        assert not await owner_log.notify_owner(client, "another message")
        assert client.sent == [(-100123, "Frameora started.", {
            "parse_mode": None, "disable_web_page_preview": True,
        })]
    asyncio.run(run())


def test_owner_log_send_failure_does_not_raise(monkeypatch):
    async def run():
        monkeypatch.setattr(owner_log.config, "LOG_CHAT_ID", 123)
        monkeypatch.setattr(owner_log, "cache", Cache())
        assert not await owner_log.notify_owner(FakeClient(fail=True), "notice")
    asyncio.run(run())
