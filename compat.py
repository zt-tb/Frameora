# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import inspect
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

try:
    from pyrogram.types import ReplyParameters
except Exception:
    ReplyParameters = None


def reply_kwargs(method: Any, message_id: Optional[int]) -> dict:
    if not message_id:
        return {}
    try:
        params = inspect.signature(method).parameters
    except (TypeError, ValueError):
        params = {}
    if "reply_parameters" in params and ReplyParameters is not None:
        return {"reply_parameters": ReplyParameters(message_id=message_id)}
    if "reply_to_message_id" in params:
        return {"reply_to_message_id": message_id}
    return {}


async def send_text(client, chat_id: int, text: str, *, reply_to: Optional[int] = None,
                    markup=None, **kw):
    extra = reply_kwargs(client.send_message, reply_to)
    try:
        return await client.send_message(chat_id, text, reply_markup=markup, **extra, **kw)
    except TypeError as exc:
        log.warning("send_message reply kwarg rejected (%s) – sending without quote", exc)
        return await client.send_message(chat_id, text, reply_markup=markup, **kw)


async def reply(m, text: str, markup=None, *, quote: bool = False, reply_markup=None, **kw):
    return await send_text(
        m._client, m.chat.id, text,
        reply_to=m.id if quote else None, markup=markup or reply_markup, **kw,
    )


async def send_document(client, chat_id: int, path: str, *, reply_to: Optional[int] = None, **kw):
    extra = reply_kwargs(client.send_document, reply_to)
    try:
        return await client.send_document(chat_id, path, **extra, **kw)
    except TypeError as exc:
        log.warning("send_document reply kwarg rejected (%s) – sending without quote", exc)
        return await client.send_document(chat_id, path, **kw)
