# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio
import glob
import logging
import os
import shutil
import time

from pyrogram import idle
from pyrogram.types import BotCommand

import config
import i18n
from bot import create_app
from cache import cache
from database import db
from handlers import expiry_loop, payments_recovery_loop, refs_cleanup_loop, register_handlers
from owner_log import notify_owner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("main")

def _clean_stale_jobs() -> None:
    for d in glob.glob(os.path.join(config.WORK_DIR, "job_*")):
        shutil.rmtree(d, ignore_errors=True)


COMMANDS = (
    ("start", "CMD_START"),
    ("analyze", "CMD_ANALYZE"),
    ("check", "CMD_CHECK"),
    ("lang", "CMD_LANG"),
    ("help", "CMD_HELP"),
    ("terms", "CMD_TERMS"),
    ("paysupport", "CMD_PAYSUPPORT"),
)


async def _set_commands(app) -> None:
    try:
        for code in i18n.SUPPORTED:
            with i18n.use(code):
                commands = [BotCommand(name, i18n.t(key)) for name, key in COMMANDS]
            await app.set_bot_commands(commands, language_code=code)
        with i18n.use(i18n.DEFAULT):
            await app.set_bot_commands([BotCommand(name, i18n.t(key)) for name, key in COMMANDS])
    except Exception as exc:
        log.warning("set_bot_commands failed: %s", exc)


async def _wait_for_instance_lock(timeout: float = 90, interval: float = 3) -> bool:
    deadline = time.monotonic() + timeout
    warned = False
    while True:
        if await db.acquire_instance_lock():
            if warned:
                log.info("acquired PostgreSQL instance lock after waiting")
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            log.error("PostgreSQL instance lock remained busy for %.0f seconds; exiting", timeout)
            return False
        if not warned:
            log.warning("another Frameora instance is still stopping; retrying lock acquisition")
            warned = True
        await asyncio.sleep(min(interval, remaining))


async def main() -> None:
    config.validate()
    os.makedirs(config.WORK_DIR, exist_ok=True)
    os.makedirs(config.REF_DIR, exist_ok=True)
    await db.connect(config.DATABASE_URL)
    if not await _wait_for_instance_lock():
        raise SystemExit("Could not acquire the PostgreSQL instance lock within 90 seconds")
    _clean_stale_jobs()
    await cache.connect(config.REDIS_URL)
    cleared = await cache.clear_job_locks()
    if cleared:
        log.info("cleared %s stale job locks", cleared)
    recovered = await db.recover_stale_star_payments(processing_hours=0, refund_minutes=0)
    if recovered:
        log.warning("queued %s interrupted Stars payment(s) for refund recovery", recovered)

    app = create_app()
    register_handlers(app)

    await app.start()
    me = await app.get_me()
    log.info("Bot started as @%s (owner=%s)", me.username, config.OWNER_ID)
    await notify_owner(app, "Frameora bot started.")
    await _set_commands(app)
    reminder = asyncio.create_task(expiry_loop(app))
    cleaner = asyncio.create_task(refs_cleanup_loop())
    payments = asyncio.create_task(payments_recovery_loop(app))

    log.info("Prepared video files are delivered through Telegram only; nothing is published to TikTok")

    try:
        await idle()
    finally:
        await notify_owner(app, "Frameora bot stopping.")
        reminder.cancel()
        cleaner.cancel()
        payments.cancel()
        await asyncio.gather(reminder, cleaner, payments, return_exceptions=True)
        await app.stop()
        await cache.close()
        await db.close()

if __name__ == "__main__":
    asyncio.run(main())
