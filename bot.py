# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from pyrogram import Client
from pyrogram.enums import ParseMode

import config

def create_app() -> Client:
    return Client(
        "tiktok_fps_bot",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        parse_mode=ParseMode.HTML,
        in_memory=True,
        max_concurrent_transmissions=config.MAX_CONCURRENT_TRANSMISSIONS,
    )
