# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import logging

import config
from cache import cache

log = logging.getLogger(__name__)
_RATE_KEY = "owner_log:send_rate"
_RATE_SECONDS = 3


async def notify_owner(client, message: str) -> bool:
    if not config.LOG_CHAT_ID:
        return False
    try:
        if not await cache.acquire(_RATE_KEY, _RATE_SECONDS):
            return False
        await client.send_message(
            config.LOG_CHAT_ID,
            message[:1000],
            parse_mode=None,
            disable_web_page_preview=True,
        )
        return True
    except Exception:
        log.warning("could not deliver an operational notice to LOG_CHAT_ID", exc_info=True)
        return False
