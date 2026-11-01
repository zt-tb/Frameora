# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import asyncio
import contextlib
import functools
import html
import json
import logging
import os
import re
import shutil
import tempfile
import time
import uuid
from typing import Optional

from pyrogram import Client, filters
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    MessageNotModified,
    PeerIdInvalid,
    UserIsBlocked,
)
from pyrogram.types import CallbackQuery, Message, LabeledPrice

import compat
import config
import i18n
import quality
import ui
from analyzer import advise, format_report, probe, warning_lines
from cache import cache
from database import db
from i18n import t
from patcher import PatchError, process_video, reencode_reasons
from owner_log import notify_owner

log = logging.getLogger(__name__)

JOB_SLOTS = asyncio.Semaphore(config.MAX_CONCURRENT_JOBS)
_bg_tasks: set[asyncio.Task] = set()
_waiting = 0


VIDEO_EXT = (".mp4", ".mov", ".m4v")
VIDEO_MIME = ("video/mp4", "video/quicktime", "video/x-m4v")


def spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _bg_tasks.add(task)
    task.add_done_callback(_bg_tasks.discard)


_job_tasks: dict[tuple[str, int], asyncio.Task] = {}


def _track(kind: str, uid: int) -> None:
    _job_tasks[(kind, uid)] = asyncio.current_task()


def _untrack(kind: str, uid: int) -> None:
    if _job_tasks.get((kind, uid)) is asyncio.current_task():
        _job_tasks.pop((kind, uid), None)


async def cancel_user_jobs(uid: int) -> None:
    tasks = [t for kind in ("job", "chk") if (t := _job_tasks.get((kind, uid))) and not t.done()]
    for t in tasks:
        t.cancel()
    if tasks:
        await asyncio.wait(tasks, timeout=10)
    await cache.delete(f"job:{uid}", f"chk:{uid}")
    await clear_state(uid)


def is_video_msg(m: Message) -> bool:
    if m.video:
        mime = (m.video.mime_type or "").lower()
        name = (m.video.file_name or "").lower()
        return not mime or mime in VIDEO_MIME or name.endswith(VIDEO_EXT)
    d = m.document
    if not d:
        return False
    return (d.file_name or "").lower().endswith(VIDEO_EXT) or (d.mime_type or "").lower() in VIDEO_MIME


async def is_admin(uid: int) -> bool:
    if uid == config.OWNER_ID:
        return True
    try:
        cached = await cache.get(f"adm:{uid}")
        if cached is not None:
            return cached == "1"
        ok = await db.is_admin(uid)
        await cache.set(f"adm:{uid}", "1" if ok else "0", 30)
        return ok
    except Exception as e:
        log.error(f"is_admin failed for user {uid}: {e}")
        return False


async def has_access(uid: int) -> bool:
    if uid == config.OWNER_ID:
        return True
    try:
        cached = await cache.get(f"acc:{uid}")
        if cached is not None:
            return cached == "1"
        ok = await is_admin(uid) or await db.has_active_sub(uid)
        await cache.set(f"acc:{uid}", "1" if ok else "0", 20)
        return ok
    except Exception as e:
        log.error(f"has_access failed for user {uid}: {e}")
        return False


COMPRESS_PREF_TTL = 90 * 24 * 3600


async def _compress_on(uid: int) -> bool:
    return await cache.get(f"cmp:{uid}") == "1"


async def _main_kb(uid: int):
    return ui.main_kb(await is_admin(uid), compress=await _compress_on(uid))


async def invalidate(uid: int) -> None:
    await cache.delete(f"acc:{uid}", f"adm:{uid}", f"rate_limit:{uid}", f"wait_notice:{uid}")


async def status_line(uid: int) -> str:
    if uid == config.OWNER_ID:
        return t("STATUS_OWNER")
    if await is_admin(uid):
        return t("STATUS_ADMIN")
    try:
        sub = await db.get_sub(uid)
        if not sub or not sub["active"]:
            return t("STATUS_EXPIRED")
        if sub["expires_at"] is None:
            return t("PERMANENT")
        return t("STATUS_DAYS", date=ui.fmt_date(sub["expires_at"]), days=ui.days_left(sub["expires_at"]))
    except Exception:
        return t("STATUS_ERR")


LANG_TTL = 7 * 24 * 3600


async def lang_of(uid: int, hint: Optional[str] = None) -> str:
    code = i18n.normalize(await cache.get(f"lang:{uid}"))
    if code:
        return code
    try:
        code = i18n.normalize(await db.get_lang(uid))
    except Exception:
        code = None
    if not code:
        code = i18n.guess(hint)
    await cache.set(f"lang:{uid}", code, LANG_TTL)
    return code


async def activate_lang(user) -> str:
    code = await lang_of(user.id, getattr(user, "language_code", None))
    i18n.set_lang(code)
    return code


async def set_user_lang(uid: int, code: str) -> None:
    code = i18n.normalize(code) or i18n.DEFAULT
    try:
        await db.set_lang(uid, code)
    except Exception as e:
        log.warning("could not persist language for %s: %s", uid, e)
    await cache.set(f"lang:{uid}", code, LANG_TTL)
    i18n.set_lang(code)


@contextlib.asynccontextmanager
async def as_user(uid: int):
    token = i18n.set_lang(await lang_of(uid))
    try:
        yield
    finally:
        i18n.reset_lang(token)


def localized(fn):
    @functools.wraps(fn)
    async def wrapper(client, update, *args, **kwargs):
        user = getattr(update, "from_user", None)
        if user is not None:
            await activate_lang(user)
            try:
                if await cache.acquire(f"seen_touch:{user.id}", 300):
                    await db.touch_user(user.id)
            except Exception as e:
                log.debug("could not update last_seen for %s: %s", user.id, e)
        return await fn(client, update, *args, **kwargs)

    return wrapper


async def _send_sub_alert(update: Message | CallbackQuery, uid: int) -> None:
    text, markup = ui.sub_alert(uid), ui.sub_alert_kb()
    is_cb = isinstance(update, CallbackQuery)
    try:
        if is_cb:
            try:
                await update.answer(ui.SUB_POPUP, show_alert=True)
            except Exception:
                pass
            await compat.send_text(update._client, uid, text, markup=markup)
        else:
            await compat.reply(update, text, markup)
    except Exception as e:
        log.error("could not send subscription notice to user %s: %s", uid, e)
        try:
            link = t("CONTACT_LINK", url=html.escape(config.DEV_URL))
            fallback = f"{text}\n\n{link}"
            if is_cb:
                await compat.send_text(update._client, uid, fallback)
            else:
                await compat.reply(update, fallback)
        except Exception as e2:
            log.error("fallback notice failed for user %s: %s", uid, e2)


async def deny_sub(update: Message | CallbackQuery) -> None:
    uid = update.from_user.id
    await _send_sub_alert(update, uid)


async def set_state(uid: int, **data) -> None:
    await cache.set(f"st:{uid}", json.dumps(data), 600)


async def get_state(uid: int) -> Optional[dict]:
    raw = await cache.get(f"st:{uid}")
    return json.loads(raw) if raw else None


async def clear_state(uid: int) -> None:
    await cache.delete(f"st:{uid}")


async def safe_edit(msg: Message, text: str, markup=None) -> None:
    try:
        await msg.edit_text(text, reply_markup=markup)
    except MessageNotModified:
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value)


async def _home_text(user) -> str:
    return ui.welcome(html.escape(user.first_name or t("FRIEND")), await status_line(user.id))


async def _grant(c, msg: Optional[Message], admin_id: int, target: int, days: Optional[int], reply=None):
    expires = await db.add_subscription(target, days, admin_id)
    await invalidate(target)
    await clear_state(admin_id)
    text, markup = ui.sub_added(target, expires), ui.admin_kb(admin_id == config.OWNER_ID)
    if msg:
        await safe_edit(msg, text, markup)
    elif reply:
        await compat.reply(reply, text, reply_markup=markup)
    try:
        async with as_user(target):
            note = ui.sub_added_user(expires)
        await c.send_message(target, note)
    except Exception:
        pass


async def _revoke(c, msg: Message, admin_id: int, target: int):
    removed = await db.remove_subscription(target)
    await invalidate(target)
    markup = ui.admin_kb(admin_id == config.OWNER_ID)
    await safe_edit(msg, ui.SUB_REMOVED.format(uid=target) if removed else ui.NO_SUB, markup)
    if removed:
        try:
            async with as_user(target):
                note = ui.SUB_REMOVED_USER
            await c.send_message(target, note)
        except Exception:
            pass


async def _broadcast(c, status: Message, from_chat: int, mid: int):
    ids = await db.all_user_ids()
    total, ok, fail = len(ids), 0, 0
    for i, target in enumerate(ids, 1):
        for attempt in range(2):
            try:
                await c.copy_message(target, from_chat, mid)
                ok += 1
                break
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
            except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
                fail += 1
                break
            except Exception:
                fail += 1
                break
        else:
            fail += 1
        await asyncio.sleep(0.05)
        if i % 50 == 0:
            await safe_edit(status, ui.bc_progress(i, total, ok, fail))
    await safe_edit(status, ui.bc_done(total, ok, fail), ui.admin_kb(from_chat == config.OWNER_ID))


async def admin_callback(c, q: CallbackQuery, uid: int, data: str):
    msg, is_owner = q.message, uid == config.OWNER_ID
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action in ("addadmin", "deladmin") and not is_owner:
        return await q.answer(ui.OWNER_ONLY, show_alert=True)

    if action in ("", "cancel"):
        await clear_state(uid)
        await safe_edit(msg, ui.ADMIN_PANEL, ui.admin_kb(is_owner))

    elif action == "stats":
        await safe_edit(msg, ui.stats_text(await db.stats()), ui.stats_kb())

    elif action in ("add", "del", "bc", "addadmin", "deladmin"):
        asks = {
            "add": ("add_id", ui.ASK_ADD),
            "del": ("del_id", ui.ASK_DEL),
            "bc": ("bc", ui.ASK_BC),
            "addadmin": ("addadmin_id", ui.ASK_ADD_ADMIN),
            "deladmin": ("deladmin_id", ui.ASK_DEL_ADMIN),
        }
        step, text = asks[action]
        await set_state(uid, step=step, panel=msg.id)
        await safe_edit(msg, text, ui.cancel_kb())

    elif action == "dur":
        st = await get_state(uid)
        if not st or st.get("step") != "add_dur":
            return await q.answer(ui.SESSION_EXPIRED, show_alert=True)
        days = int(parts[2])
        await _grant(c, msg, uid, st["target"], days or None)

    elif action == "delok":
        await _revoke(c, msg, uid, int(parts[2]))

    elif action == "bcok":
        st = await get_state(uid)
        if not st or st.get("step") != "bc_confirm":
            return await q.answer(ui.SESSION_EXPIRED, show_alert=True)
        await clear_state(uid)
        task = asyncio.create_task(_broadcast(c, msg, st["chat"], st["mid"]))
        _bg_tasks.add(task)
        task.add_done_callback(_bg_tasks.discard)

    await q.answer()


def _parse_int(text: str) -> Optional[int]:
    try:
        return int(text.strip())
    except (ValueError, AttributeError):
        return None


async def handle_admin_input(c, m: Message, st: dict):
    uid, step = m.from_user.id, st["step"]
    is_owner = uid == config.OWNER_ID

    if step == "bc":
        total = len(await db.all_user_ids())
        await set_state(uid, step="bc_confirm", chat=m.chat.id, mid=m.id)
        return await compat.reply(m, ui.bc_confirm(total), reply_markup=ui.bc_confirm_kb())

    if step in ("bc_confirm", "add_dur"):
        return await compat.reply(m, ui.PICK_BUTTONS)

    text = (m.text or "").split()
    target = _parse_int(text[0]) if text else None
    if target is None or target <= 0:
        return await compat.reply(m, ui.BAD_ID, reply_markup=ui.cancel_kb())

    if step == "add_id":
        if len(text) >= 2:
            days = _parse_int(text[1])
            if days is not None and days >= 0:
                return await _grant(c, None, uid, target, days or None, reply=m)
        await set_state(uid, step="add_dur", target=target)
        await compat.reply(m, ui.ask_duration(target), reply_markup=ui.duration_kb())

    elif step == "del_id":
        sub = await db.get_sub(target)
        if not sub:
            await clear_state(uid)
            return await compat.reply(m, ui.NO_SUB, reply_markup=ui.admin_kb(is_owner))
        await clear_state(uid)
        await compat.reply(m, ui.confirm_remove(target, sub), reply_markup=ui.confirm_remove_kb(target))

    elif step == "addadmin_id" and is_owner:
        await db.add_admin(target, uid)
        await invalidate(target)
        await clear_state(uid)
        await compat.reply(m, ui.ADMIN_ADDED.format(uid=target), reply_markup=ui.admin_kb(True))

    elif step == "deladmin_id" and is_owner:
        removed = await db.remove_admin(target)
        await invalidate(target)
        await clear_state(uid)
        await compat.reply(m,
            ui.ADMIN_REMOVED.format(uid=target) if removed else ui.ADMIN_NOT_FOUND,
            reply_markup=ui.admin_kb(True),
        )
    else:
        await clear_state(uid)


def _progress_cb(status: Message, label: str):
    last = [0.0]

    async def cb(current: int, total: int):
        now = time.monotonic()
        if current != total and now - last[0] < 3:
            return
        last[0] = now
        pct = current * 100 / total if total else 0
        try:
            await status.edit_text(ui.progress(label, pct))
        except Exception:
            pass

    return cb


@contextlib.asynccontextmanager
async def _processing_slot(status: Optional[Message]):
    global _waiting
    counted = False
    if JOB_SLOTS.locked():
        _waiting += 1
        counted = True
        if status:
            await safe_edit(status, ui.queued(_waiting))
    try:
        async with JOB_SLOTS:
            if counted:
                _waiting = max(0, _waiting - 1)
                counted = False
            yield
    finally:
        if counted:
            _waiting = max(0, _waiting - 1)


def _has_disk_space(required_file_bytes: int = 0, copies: int = 2) -> bool:
    try:
        free = shutil.disk_usage(config.WORK_DIR).free
    except OSError as exc:
        log.warning("could not inspect work disk space: %s", exc)
        return False
    reserve = config.MIN_FREE_DISK_MB * 1024 * 1024
    return free >= reserve + max(0, required_file_bytes) * max(1, copies)


async def _job_lock_heartbeat(uid: int) -> None:
    key = f"job:{uid}"
    interval = max(5, min(30, config.JOB_LOCK_TTL_SECONDS // 3))
    while True:
        await asyncio.sleep(interval)
        try:
            if not await cache.refresh(key, config.JOB_LOCK_TTL_SECONDS):
                log.warning("job lock disappeared while job is active for user %s", uid)
                return
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("could not refresh job lock for user %s", uid)


def _reason(exc: Exception) -> str:
    return html.escape(re.sub(r"^MP4:\s*", "", str(exc)))


async def handle_video(c, m: Message, analyze_only: bool = False, method: Optional[str] = None):
    uid = m.from_user.id
    media = m.video or m.document
    name = getattr(media, "file_name", None) or "video.mp4"
    size = getattr(media, "file_size", 0) or 0
    if not is_video_msg(m):
        return await compat.reply(m, ui.NOT_MP4, quote=True)
    if config.exceeds_size_limit(size):
        return await compat.reply(m, ui.TOO_BIG.format(size=ui.fmt_size(size), mb=config.MAX_FILE_MB), quote=True)

    job_id = uuid.uuid4().hex
    payment = None
    if not await has_access(uid):
        payment = await db.claim_star_payment(uid, job_id)
        if not payment:
            return await compat.reply(m, ui.sub_alert(uid), reply_markup=ui.sub_alert_kb(), quote=True)
    if not await cache.acquire(f"job:{uid}", config.JOB_LOCK_TTL_SECONDS):
        if payment:
            await db.settle_star_payment(payment["invoice_payload"], "available")
        return await compat.reply(m, ui.BUSY, quote=True)

    delivery_ok = False
    heartbeat = asyncio.create_task(_job_lock_heartbeat(uid))
    workdir = None
    status: Optional[Message] = None
    _track("job", uid)
    try:
        if not _has_disk_space(size):
            if payment:
                await db.settle_star_payment(payment["invoice_payload"], "available")
                payment = None
            return await compat.reply(m, ui.DISK_FULL, quote=True)
        workdir = tempfile.mkdtemp(prefix="job_", dir=config.WORK_DIR)
        status = await compat.reply(m, ui.RECEIVED, quote=True)
        src = os.path.join(workdir, "input.mp4")
        await m.download(file_name=src, progress=_progress_cb(status, ui.LBL_DOWNLOADING))
        real_size = os.path.getsize(src) if os.path.exists(src) else 0
        if config.exceeds_size_limit(real_size):
            return await safe_edit(status, ui.TOO_BIG.format(size=ui.fmt_size(real_size), mb=config.MAX_FILE_MB))
        if not _has_disk_space(real_size, copies=1):
            return await safe_edit(status, ui.DISK_FULL)
        await safe_edit(status, ui.ANALYZING)
        try:
            info = await probe(src)
        except PatchError as e:
            await notify_owner(c, "Video analysis failed.")
            return await safe_edit(status, ui.FAIL.format(reason=_reason(e)))
        tips = advise(info, sent_as_video=bool(m.video))
        if analyze_only:
            text = format_report(info)
            if tips:
                text += "\n\n" + t("TIPS_HEADER") + "\n" + "\n".join(tips)
            return await safe_edit(status, text[:4000], ui.back_kb())
        if config.KEEP_REFERENCE:
            await quality.store_reference(uid, src, source_duration=info.duration)
        compress = await _compress_on(uid)
        reasons = reencode_reasons(info, compress)

        async def on_stage(stage: str) -> None:
            if stage == "reencode":
                await safe_edit(status, ui.reencoding(reasons, compress))
            elif stage == "remux":
                await safe_edit(status, ui.REMUXING)
            else:
                await safe_edit(status, ui.LBL_PATCHING)

        try:
            async with _processing_slot(status):
                result = await process_video(src, info, method=method, on_stage=on_stage, compress=compress)
        except PatchError as e:
            log.warning("patch failed for user %s (method=%s): %s", uid, method or config.PATCH_METHOD, e)
            await notify_owner(c, "Video processing failed.")
            return await safe_edit(status, ui.FAIL.format(reason=_reason(e)))

        warns = warning_lines(info)
        if warns:
            await compat.reply(m, "\n\n".join(warns), quote=True)
        stem = os.path.splitext(os.path.basename(name))[0] or "video"
        out_size = os.path.getsize(src)
        caption = ui.done_caption(
            result.fps, out_size, before=info, after=result.after_info,
            verified=result.verified, media_intact=result.media_intact, tips=tips,
            method=result.method, reencoded=result.reencoded, warned=bool(warns),
        )
        await compat.send_document(
            c, m.chat.id, src, reply_to=m.id, file_name=f"{stem}_patched.mp4",
            caption=caption[:1024], force_document=True,
            progress=_progress_cb(status, ui.LBL_SENDING),
        )
        delivery_ok = True
        if payment:
            await db.settle_star_payment(payment["invoice_payload"], "used")
        try:
            await db.log_job(uid, result.fps, out_size, info.view_h, job_id=job_id)
        except Exception as e:
            log.error("could not record job for user %s: %s", uid, e)
        await status.delete()
        status = None
    except asyncio.CancelledError:
        if status:
            try:
                await safe_edit(status, ui.JOB_CANCELLED)
            except Exception:
                pass
        raise
    except Exception:
        log.exception("video processing failed for %s", uid)
        await notify_owner(c, "Unexpected video-processing error.")
        if status:
            await safe_edit(status, ui.FAIL_GENERIC)
    finally:
        if payment and not delivery_ok:
            await _refund_star_payment(c, uid, payment)
        _untrack("job", uid)
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        await cache.release(f"job:{uid}")
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)


async def handle_check(c, chat_id: int, uid: int, url: str, reply_to: Optional[int] = None):
    if not quality.is_tiktok_url(url):
        return await compat.send_text(c, chat_id, ui.BAD_URL, reply_to=reply_to, markup=ui.back_kb())
    ref = quality.get_reference(uid)
    if not ref:
        return await compat.send_text(c, chat_id, ui.NO_REF, reply_to=reply_to, markup=ui.back_kb())
    if not await cache.acquire(f"chk:{uid}", 900):
        return await compat.send_text(c, chat_id, ui.BUSY, reply_to=reply_to)

    _track("chk", uid)
    status: Optional[Message] = None
    workdir = None
    try:
        workdir = tempfile.mkdtemp(prefix="job_chk_", dir=config.WORK_DIR)
        status = await compat.send_text(c, chat_id, ui.CHECK_DOWNLOADING, reply_to=reply_to)
        if not _has_disk_space(config.CHECK_MAX_DOWNLOAD_MB * 1024 * 1024, copies=1):
            return await safe_edit(status, ui.DISK_FULL, ui.back_kb())
        try:
            published = await quality.download_published(url, workdir)
            await safe_edit(status, ui.CHECK_COMPARING)
            async with _processing_slot(status):
                report = await quality.compare(
                    ref, published, reference_duration=quality.get_reference_duration(uid)
                )
        except PatchError as e:
            return await safe_edit(status, ui.FAIL.format(reason=html.escape(str(e))), ui.back_kb())
        await safe_edit(status, quality.format_report(report)[:4000], ui.check_again_kb())
    except asyncio.CancelledError:
        if status:
            try:
                await safe_edit(status, ui.JOB_CANCELLED)
            except Exception:
                pass
        raise
    except Exception:
        log.exception("quality check failed for %s", uid)
        await notify_owner(c, "Unexpected /check comparison error.")
        if status:
            await safe_edit(status, ui.FAIL_GENERIC, ui.back_kb())
    finally:
        _untrack("chk", uid)
        await cache.release(f"chk:{uid}")
        if workdir:
            shutil.rmtree(workdir, ignore_errors=True)


async def method_callback(c, q: CallbackQuery, uid: int, data: str) -> None:
    kind, _, rest = data.partition(":")
    method, _, raw_id = rest.rpartition(":")
    method = method if kind == "pm" else ""
    if method == "ZETA3":
        method = "TIMECODE"
    msg = q.message
    try:
        msg_id = int(raw_id)
    except ValueError:
        return await q.answer(ui.ERR_POPUP, show_alert=True)

    if kind == "px":
        await _drop(msg)
        return await q.answer(ui.PICK_CANCELLED)
    if kind == "pc":
        on = not await _compress_on(uid)
        if on:
            await cache.set(f"cmp:{uid}", "1", COMPRESS_PREF_TTL)
        else:
            await cache.delete(f"cmp:{uid}")
        try:
            await msg.edit_reply_markup(ui.method_kb(msg_id, on))
        except MessageNotModified:
            pass
        return await q.answer(ui.compress_popup(on))

    if method not in config.PATCH_METHODS:
        return await q.answer(ui.ERR_POPUP, show_alert=True)
    try:
        original = await c.get_messages(msg.chat.id, msg_id)
    except Exception:
        original = None
    if not original or original.empty or not is_video_msg(original):
        await _drop(msg)
        return await q.answer(ui.PICK_GONE, show_alert=True)
    await _drop(msg)
    await q.answer(ui.method_label(method))
    spawn(handle_video(c, original, method=method))


async def _drop(msg: Message) -> None:
    try:
        await msg.delete()
    except Exception:
        pass


async def expiry_loop(client: Client):
    await asyncio.sleep(30)
    while True:
        try:
            for row in await db.expiring_subs(config.EXPIRY_WARN_DAYS):
                uid, exp = row["user_id"], row["expires_at"]
                try:
                    async with as_user(uid):
                        text, markup = ui.expiry_warning(ui.days_left(exp), exp), ui.sub_alert_kb()
                    await compat.send_text(client, uid, text, markup=markup)
                except FloodWait as e:
                    await asyncio.sleep(e.value + 1)
                    continue
                except (UserIsBlocked, InputUserDeactivated, PeerIdInvalid):
                    pass
                except Exception as e:
                    log.warning("expiry reminder for %s: %s", uid, e)
                    try:
                        await compat.send_text(client, uid, text)
                    except Exception:
                        pass
                await db.mark_warned(uid)
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("expiry loop error")
        await asyncio.sleep(3600)


async def refs_cleanup_loop():
    while True:
        try:
            n = await asyncio.to_thread(quality.cleanup_references)
            if n:
                log.info("removed %s expired reference file(s)", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("refs cleanup error")
        await asyncio.sleep(3600)


async def _refund_star_payment(c, uid: int, payment: dict) -> None:
    try:
        refunded = await c.refund_star_payment(
            user_id=uid, telegram_payment_charge_id=payment["charge_id"]
        )
        if not refunded:
            raise RuntimeError("Telegram did not confirm the Stars refund")
    except Exception:
        log.exception("Telegram Stars refund failed for user=%s invoice=%s", uid, payment.get("invoice_payload"))
        await notify_owner(c, "A Telegram Stars refund attempt failed; user support may be required.")
        try:
            await db.settle_star_payment(payment["invoice_payload"], "refund_pending")
        except Exception:
            log.exception("could not save pending refund for invoice=%s", payment.get("invoice_payload"))
        try:
            await c.send_message(uid, t("STARS_REFUND_PENDING"))
        except Exception:
            pass
        return
    try:
        await db.settle_star_payment(payment["invoice_payload"], "refunded")
    except Exception:
        log.exception("refund succeeded but could not save final state for invoice=%s", payment.get("invoice_payload"))
        return
    await notify_owner(c, "A Telegram Stars refund succeeded.")
    try:
        await c.send_message(uid, t("STARS_REFUNDED", stars=payment.get("amount", config.STARS_VIDEO_PRICE)))
    except Exception:
        log.warning("refund was recorded but its confirmation could not be sent to user=%s", uid)

async def payments_recovery_loop(client: Client):
    while True:
        try:
            recovered = await db.recover_stale_star_payments()
            expired = await db.cleanup_star_invoices(config.STAR_INVOICE_TTL_HOURS)
            if recovered or expired:
                log.warning("payment recovery: %s stale payments queued for refund; %s invoices expired",
                            recovered, expired)
            for payment in await db.claim_pending_refunds():
                async with as_user(payment["user_id"]):
                    await _refund_star_payment(client, payment["user_id"], payment)
                await asyncio.sleep(0.2)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Stars payment recovery loop failed")
        await asyncio.sleep(3600)


async def _send_stars_invoice(c, chat_id: int, uid: int, product_type: str = "video") -> bool:
    if product_type not in ("video", "sub30"):
        raise ValueError("invalid Stars product type")
    if product_type == "sub30" and config.STARS_SUB_30D_PRICE <= 0:
        return False
    lock_key = f"stars_invoice:{uid}"
    if not await cache.acquire(lock_key, config.STAR_INVOICE_COOLDOWN_SECONDS):
        return False
    amount = config.STARS_SUB_30D_PRICE if product_type == "sub30" else config.STARS_VIDEO_PRICE
    payload_prefix = "ffsub30" if product_type == "sub30" else "ffstars"
    payload = f"{payload_prefix}:{uid}:{uuid.uuid4().hex}"
    created = await db.create_star_invoice(
        uid, payload, amount, config.MAX_OPEN_STAR_INVOICES,
        config.STAR_INVOICE_TTL_HOURS, product_type=product_type,
    )
    if not created:
        return False
    try:
        await c.send_invoice(
            chat_id=chat_id,
            title=t("STARS_SUB30_TITLE") if product_type == "sub30" else t("STARS_TITLE"),
            description=t("STARS_SUB30_DESCRIPTION") if product_type == "sub30" else t("STARS_DESCRIPTION"),
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(
                label=t("STARS_SUB30_PRICE_LABEL") if product_type == "sub30" else t("STARS_PRICE_LABEL"),
                amount=amount,
            )],
        )
    except Exception:
        await db.expire_star_invoice(payload)
        await cache.delete(lock_key)
        raise
    return True

def register_handlers(app: Client):

    @app.on_message(filters.private & filters.command("start"))
    @localized
    async def cmd_start(_, m: Message):
        u = m.from_user
        try:
            await db.upsert_user(u.id, u.first_name, u.username)
        except Exception as e:
            log.error("database error while saving user %s: %s", u.id, e)

        try:
            if not await has_access(u.id):
                return await deny_sub(m)
            await clear_state(u.id)
            await compat.reply(m, await _home_text(u), reply_markup=await _main_kb(u.id))
        except Exception as e:
            log.error("unexpected error in /start for user %s: %s", u.id, e)
            try:
                await compat.reply(m, ui.INTERNAL_ERROR)
            except Exception:
                pass

    @app.on_message(filters.private & filters.command("lang"))
    @localized
    async def cmd_lang(_, m: Message):
        try:
            await compat.reply(m, ui.LANG_MENU, reply_markup=ui.lang_kb())
        except Exception as e:
            log.error("/lang failed: %s", e)

    @app.on_message(filters.private & filters.command("help"))
    @localized
    async def cmd_help(_, m: Message):
        try:
            if not await has_access(m.from_user.id):
                return await deny_sub(m)
            await compat.reply(m, ui.help_text(), reply_markup=ui.back_kb())
        except Exception as e:
            log.error("/help failed: %s", e)

    @app.on_message(filters.private & filters.command("terms"))
    @localized
    async def cmd_terms(_, m: Message):
        await compat.reply(m, t(
            "TERMS", stars=config.STARS_VIDEO_PRICE, sub30=ui.sub30_terms_text()
        ), reply_markup=ui.back_kb())

    @app.on_message(filters.private & filters.command("paysupport"))
    @localized
    async def cmd_paysupport(_, m: Message):
        await compat.reply(m, t("PAY_SUPPORT", url=html.escape(config.DEV_URL)), reply_markup=ui.back_kb())

    @app.on_message(filters.private & filters.command("analyze"))
    @localized
    async def cmd_analyze(_, m: Message):
        uid = m.from_user.id
        try:
            if not await has_access(uid):
                return await deny_sub(m)
            await set_state(uid, step="analyze")
            await compat.reply(m, ui.ASK_ANALYZE, reply_markup=ui.back_kb())
        except Exception as e:
            log.error("/analyze failed: %s", e)

    @app.on_message(filters.private & filters.command("check"))
    @localized
    async def cmd_check(c, m: Message):
        uid = m.from_user.id
        try:
            if not await has_access(uid):
                return await deny_sub(m)
            url = quality.extract_url(m.text or "")
            if url:
                return spawn(handle_check(c, m.chat.id, uid, url, reply_to=m.id))
            await set_state(uid, step="check")
            await compat.reply(m, ui.ASK_CHECK, reply_markup=ui.back_kb())
        except Exception as e:
            log.error("/check failed: %s", e)


    @app.on_message(filters.private & filters.command("cancel"))
    @localized
    async def cmd_cancel(_, m: Message):
        uid = m.from_user.id
        try:
            await cancel_user_jobs(uid)
            await compat.reply(m, ui.CANCEL_DONE)
        except Exception as e:
            log.error("/cancel failed: %s", e)


    @app.on_message(filters.private & filters.command("admin"))
    @localized
    async def cmd_admin(_, m: Message):
        uid = m.from_user.id
        try:
            if not await has_access(uid):
                return await deny_sub(m)
            if not await is_admin(uid):
                return await compat.reply(m, ui.ACCESS_DENIED)
            await clear_state(uid)
            await compat.reply(m, ui.ADMIN_PANEL, reply_markup=ui.admin_kb(uid == config.OWNER_ID))
        except Exception as e:
            log.error("/admin failed: %s", e)

    @app.on_pre_checkout_query()
    async def on_pre_checkout(_, q):
        try:
            invoice = await db.get_star_invoice(q.from_user.id, q.invoice_payload, q.total_amount)
            valid = q.currency == "XTR" and invoice is not None and invoice["product_type"] in ("video", "sub30")
            await q.answer(ok=valid, error_message=None if valid else "This invoice is invalid or expired.")
        except Exception:
            log.exception("pre-checkout validation failed for %s", q.from_user.id)
            await q.answer(ok=False, error_message="Payment validation failed. Please try again.")

    @app.on_message(filters.private & filters.successful_payment)
    @localized
    async def on_successful_payment(c, m: Message):
        payment = m.successful_payment
        uid = m.from_user.id
        try:
            if (payment.invoice_payload or "").startswith("ffsub30:"):
                outcome = await db.record_subscription_payment(
                    uid, payment.invoice_payload, payment.telegram_payment_charge_id, payment.total_amount
                )
                if outcome not in ("granted", "duplicate"):
                    log.error("unmatched Stars subscription payment for user=%s", uid)
                    await notify_owner(c, "An unmatched 30-day Stars subscription payment needs review.")
                    return await compat.reply(m, t("STARS_SUPPORT"))
                await invalidate(uid)
                await notify_owner(c, "Telegram Stars payment received for a 30-day subscription.")
                return await compat.reply(m, t("STARS_SUB30_PAID"), reply_markup=await _main_kb(uid))

            saved = await db.record_star_payment(
                uid, payment.invoice_payload, payment.telegram_payment_charge_id, payment.total_amount
            )
            if not saved:
                log.error("unmatched/duplicate Stars payment user=%s payload=%s", uid, payment.invoice_payload)
                await notify_owner(c, "An unmatched video-processing Stars payment needs review.")
                return await compat.reply(m, t("STARS_SUPPORT"))
            await notify_owner(c, "Telegram Stars payment received for a video-processing job.")
            await compat.reply(m, t("STARS_PAID"), reply_markup=await _main_kb(uid))
        except Exception:
            log.exception("could not persist Stars payment for %s", uid)
            await compat.reply(m, t("STARS_SUPPORT"))

    @app.on_callback_query()
    @localized
    async def on_callback(c, q: CallbackQuery):
        uid, data = q.from_user.id, q.data or ""
        try:
            if data == "lang":
                await safe_edit(q.message, ui.LANG_MENU, ui.lang_kb())
                return await q.answer()
            if data.startswith("lang:"):
                code = i18n.normalize(data.split(":", 1)[1])
                if code:
                    await set_user_lang(uid, code)
                    if await has_access(uid):
                        await safe_edit(q.message, await _home_text(q.from_user), await _main_kb(uid))
                    else:
                        await safe_edit(q.message, ui.LANG_MENU, ui.lang_kb())
                    return await q.answer(ui.LANG_SET)
            if data == "stars:buy":
                sent = await _send_stars_invoice(c, q.message.chat.id, uid)
                if not sent:
                    return await q.answer(t("INVOICE_LIMIT"), show_alert=True)
                return await q.answer()
            if data == "stars:sub30":
                sent = await _send_stars_invoice(c, q.message.chat.id, uid, product_type="sub30")
                if not sent:
                    return await q.answer(t("INVOICE_LIMIT"), show_alert=True)
                return await q.answer()
            if not await has_access(uid):
                if data.startswith(("pm:", "pc:", "px:")) and await db.has_available_star(uid):
                    pass
                else:
                    return await deny_sub(q)

            if data.startswith("adm"):
                if not await is_admin(uid):
                    return await q.answer(ui.ACCESS_DENIED, show_alert=True)
                return await admin_callback(c, q, uid, data)

            if data.startswith(("pm:", "pc:", "px:")):
                return await method_callback(c, q, uid, data)

            msg = q.message
            if data == "home":
                await clear_state(uid)
                await safe_edit(msg, await _home_text(q.from_user), await _main_kb(uid))
            elif data == "help":
                await safe_edit(msg, ui.help_text(), ui.back_kb())
            elif data == "analyze":
                await set_state(uid, step="analyze")
                await safe_edit(msg, ui.ASK_ANALYZE, ui.back_kb())
            elif data == "check":
                await set_state(uid, step="check")
                await safe_edit(msg, ui.ASK_CHECK, ui.back_kb())
            elif data == "cmp":
                on = not await _compress_on(uid)
                if on:
                    await cache.set(f"cmp:{uid}", "1", COMPRESS_PREF_TTL)
                else:
                    await cache.delete(f"cmp:{uid}")
                try:
                    await msg.edit_reply_markup(await _main_kb(uid))
                except MessageNotModified:
                    pass
                return await q.answer(ui.compress_popup(on))
            elif data == "me":
                try:
                    st = await db.user_stats(uid)
                except Exception:
                    st = None
                await safe_edit(msg, ui.me_text(uid, await status_line(uid), st), ui.back_kb())
            await q.answer()
        except Exception as e:
            log.error("callback failed for user %s: %s", uid, e)
            try:
                await q.answer(ui.ERR_POPUP, show_alert=True)
            except Exception:
                pass

    @app.on_message(
        filters.private
        & ~filters.command(["start", "help", "admin", "analyze", "check", "cancel", "lang", "terms", "paysupport"])
        & ~filters.service
    )
    @localized
    async def on_any(c, m: Message):
        if not m.from_user:
            return
        uid = m.from_user.id
        try:
            authorized = await has_access(uid)
            st = await get_state(uid)
            paid_once = await db.has_available_star(uid) if not authorized else False
            if not authorized and not paid_once:
                return await deny_sub(m)
            if st and st.get("step") == "analyze":
                if not authorized:
                    return await deny_sub(m)
                if m.video or m.document:
                    await clear_state(uid)
                    return spawn(handle_video(c, m, analyze_only=True))
                return await compat.reply(m, ui.ASK_ANALYZE, reply_markup=ui.back_kb())
            if st and st.get("step") == "check":
                if not authorized:
                    return await deny_sub(m)
                url = quality.extract_url(m.text or m.caption or "")
                if url:
                    await clear_state(uid)
                    return spawn(handle_check(c, m.chat.id, uid, url, reply_to=m.id))
                return await compat.reply(m, ui.ASK_CHECK, reply_markup=ui.back_kb())
            if st and await is_admin(uid):
                return await handle_admin_input(c, m, st)

            if m.video or m.document:
                if not is_video_msg(m):
                    return await compat.reply(m, ui.NOT_MP4, quote=True)
                media = m.video or m.document
                card = ui.pick_card(
                    size=getattr(media, "file_size", 0) or 0,
                    width=getattr(media, "width", 0) or 0,
                    height=getattr(media, "height", 0) or 0,
                    duration=int(getattr(media, "duration", 0) or 0),
                    name=getattr(media, "file_name", "") or "",
                )
                return await compat.reply(m, card, quote=True,
                                          reply_markup=ui.method_kb(m.id, await _compress_on(uid)))

            await compat.reply(m, ui.SEND_VIDEO_HINT, reply_markup=await _main_kb(uid))
        except Exception as e:
            log.error("message handling failed for %s: %s", uid, e)
