# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Optional

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config
import i18n
from i18n import t

try:
    from pyrogram.enums import ButtonStyle

    STYLES = True
except ImportError:
    STYLES = False

    class ButtonStyle:
        PRIMARY = DANGER = SUCCESS = None


def btn(text: str, data: str | None = None, *, url: str | None = None, style):
    kw = {"url": url} if url else {"callback_data": data}
    if STYLES:
        kw["style"] = style
    return InlineKeyboardButton(text, **kw)


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([list(r) for r in rows])


P, D, S = ButtonStyle.PRIMARY, ButtonStyle.DANGER, ButtonStyle.SUCCESS
LINE = "━━━━━━━━━━━━━━━━"
SIGNATURE = "© Mohsen Al-Taie | @K0_MG"


def __getattr__(name: str) -> str:
    if name == "HELP":
        return help_text()
    if name.isupper() and i18n.has(name):
        return t(name)
    raise AttributeError(f"module 'ui' has no attribute {name!r}")


def fmt_date(dt: Optional[datetime]) -> str:
    return t("PERMANENT") if dt is None else dt.astimezone(timezone.utc).strftime("%Y-%m-%d")


def fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024


def days_left(dt: datetime) -> int:
    return max(0, (dt - datetime.now(timezone.utc)).days)


def sub_alert(uid: int) -> str:
    offer = t("SUB30_OFFER", stars=config.STARS_SUB_30D_PRICE) if config.STARS_SUB_30D_PRICE > 0 else ""
    return t("sub_alert", uid=uid, stars=config.STARS_VIDEO_PRICE, sub30=offer)


def wait_msg(seconds: int) -> str:
    return t("wait_msg", seconds=seconds)


def wait_popup(seconds: int) -> str:
    return t("wait_popup", seconds=seconds)


def sub_alert_kb() -> InlineKeyboardMarkup:
    rows = [[btn(t("BTN_BUY_STARS", stars=config.STARS_VIDEO_PRICE), "stars:buy", style=S)]]
    if config.STARS_SUB_30D_PRICE > 0:
        rows.append([btn(t("BTN_BUY_SUB30", stars=config.STARS_SUB_30D_PRICE), "stars:sub30", style=S)])
    rows.extend([[btn(t("BTN_CONTACT"), url=config.DEV_URL, style=P)],
                 [btn(t("BTN_LANG"), "lang", style=P)]])
    return kb(*rows)


def welcome(name: str, status: str) -> str:
    return t("welcome", name=name, status=status)


def help_text() -> str:
    sub30 = t("STARS_SUB30_HELP", stars=config.STARS_SUB_30D_PRICE) if config.STARS_SUB_30D_PRICE > 0 else ""
    return t("HELP", stars=config.STARS_VIDEO_PRICE, sub30=sub30)


def sub30_terms_text() -> str:
    return t("STARS_SUB30_HELP", stars=config.STARS_SUB_30D_PRICE) if config.STARS_SUB_30D_PRICE > 0 else ""


def queued(pos: int) -> str:
    return t("queued", pos=pos)


def progress(label: str, pct: float) -> str:
    filled = int(pct // 10)
    return f"{label}\n<code>[{'█' * filled}{'░' * (10 - filled)}] {pct:.0f}%</code>"


LRM = "\u200e"


def ltr(text: str) -> str:
    return f"{LRM}{text}{LRM}"


def _res_txt(info) -> str:
    return ltr(f"{info.view_w}×{info.view_h}") if info and info.view_w and info.view_h else "—"


def _fps_txt(info) -> str:
    if not info or not info.fps:
        return "—"
    return ltr(f"{info.fps:.2f}".rstrip("0").rstrip("."))


def _bitrate_txt(info) -> str:
    return ltr(f"{info.bitrate_kbps / 1000:.1f} Mbps") if info and info.bitrate_kbps else "—"


def done_caption(fps: int, size: int, *, before=None, after=None, verified: bool = False,
                 media_intact: bool | None = None, tips: list[str] | None = None,
                 method: str = "ZETA1", reencoded: bool = False,
                 warned: bool = False) -> str:
    lines = [t("DONE_TITLE"), LINE]
    if before is not None and after is not None:
        lines += [
            t("DONE_RES", before=_res_txt(before), after=_res_txt(after)),
            t("DONE_FPS", before=_fps_txt(before), after=_fps_txt(after)),
            t("DONE_BITRATE", before=_bitrate_txt(before), after=_bitrate_txt(after)),
        ]
    else:
        lines.append(t("DONE_FPS", before=fps, after=fps))
    lines += [
        t("DONE_SIZE", size=fmt_size(size)),
        t("DONE_REENCODED") if reencoded else t("DONE_SAFE"),
        t("DONE_METHOD", method=method_label(method)),
    ]
    if warned:
        lines.append(t("DONE_WARNED"))
    lines += [LINE, t("DONE_UPLOAD_TIP"), t("TIP_LINE"), t("DONE_CHECK_TIP"), SIGNATURE]
    return "\n".join(lines)


def me_text(uid: int, status: str, st: dict | None) -> str:
    text = t("ME_HEAD", uid=uid, status=status)
    if st:
        text += t("ME_STATS", total=st["total"], today=st["today"], fps120=st["fps120"])
    return text


def expiry_warning(days: int, expires: Optional[datetime]) -> str:
    left = t("EXP_DAYS", days=days) if days > 0 else t("EXP_LT1")
    return t("expiry_warning", date=fmt_date(expires), left=left)


def main_kb(is_admin: bool, compress: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [btn(t("BTN_ANALYZE"), "analyze", style=S), btn(t("BTN_CHECK"), "check", style=S)],
        [btn(t("BTN_HELP"), "help", style=P), btn(t("BTN_ME"), "me", style=P)],
        [btn(t("BTN_CMP_ON") if compress else t("BTN_CMP_OFF"), "cmp", style=S if compress else D)],
        [btn(t("BTN_LANG"), "lang", style=P)],
    ]
    if is_admin:
        rows.append([btn(t("BTN_ADMIN"), "adm", style=S)])
    return kb(*rows)


METHOD_BUTTONS = (
    ("ZETA1", "BTN_M_ZETA1", S),
    ("ZETA2", "BTN_M_ZETA2", P),
    ("ZETA3", "BTN_M_ZETA3", P),
)
def method_label(method: str) -> str:
    normalized = method.upper()
    key = f"BTN_M_{'ZETA3' if normalized == 'TIMECODE' else normalized}"
    return t(key) if i18n.has(key) else method


def method_kb(msg_id: int, compress: bool = False) -> InlineKeyboardMarkup:
    rows = [[btn(t(label), f"pm:{method}:{msg_id}", style=style) for method, label, style in METHOD_BUTTONS]]
    rows.append([btn(t("BTN_CMP_ON") if compress else t("BTN_CMP_OFF"), f"pc:{msg_id}",
                     style=S if compress else D)])
    rows.append([btn(t("BTN_CANCEL"), f"px:{msg_id}", style=D)])
    return kb(*rows)


def pick_card(*, size: int = 0, width: int = 0, height: int = 0, duration: int = 0, name: str = "") -> str:
    info = ""
    if name:
        info += t("PICK_NAME", name=html.escape(name[:60]))
    if size:
        info += t("PICK_SIZE", size=fmt_size(size))
    if width and height:
        info += t("PICK_RES", w=width, h=height)
    if duration:
        info += t("PICK_DUR", dur=f"{duration // 60}:{duration % 60:02d}")
    return t("PICK_TITLE", info=info)


def lang_kb() -> InlineKeyboardMarkup:
    rows = [[btn(i18n.LANG_NAMES[code], f"lang:{code}", style=P)] for code in i18n.SUPPORTED]
    rows.append([btn(t("BTN_BACK"), "home", style=P)])
    return kb(*rows)


def back_kb() -> InlineKeyboardMarkup:
    return kb([btn(t("BTN_BACK"), "home", style=P)])


def admin_kb(is_owner: bool) -> InlineKeyboardMarkup:
    rows = [
        [btn(t("BTN_ADD_SUB"), "adm:add", style=S), btn(t("BTN_DEL_SUB"), "adm:del", style=D)],
        [btn(t("BTN_STATS"), "adm:stats", style=P), btn(t("BTN_BC"), "adm:bc", style=P)],
    ]
    if is_owner:
        rows.append(
            [btn(t("BTN_ADD_ADMIN"), "adm:addadmin", style=S), btn(t("BTN_DEL_ADMIN"), "adm:deladmin", style=D)]
        )
    rows.append([btn(t("BTN_BACK"), "home", style=P)])
    return kb(*rows)


def cancel_kb() -> InlineKeyboardMarkup:
    return kb([btn(t("BTN_CANCEL"), "adm:cancel", style=D)])


def stats_text(s: dict) -> str:
    return t("stats_text", users=s["users"], subs=s["subs"], active_week=s["active_week"], jobs=s["jobs"],
             jobs_today=s["jobs_today"], jobs_week=s["jobs_week"], jobs_120=s["jobs_120"],
             admins=s["admins"])


def stats_kb() -> InlineKeyboardMarkup:
    return kb([btn(t("BTN_REFRESH"), "adm:stats", style=P)], [btn(t("BTN_BACK"), "adm", style=P)])


def ask_duration(uid: int) -> str:
    return t("ask_duration", uid=uid)


def duration_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn(t("DUR_7"), "adm:dur:7", style=S), btn(t("DUR_30"), "adm:dur:30", style=S)],
        [btn(t("DUR_90"), "adm:dur:90", style=S), btn(t("DUR_365"), "adm:dur:365", style=S)],
        [btn(t("PERMANENT"), "adm:dur:0", style=S)],
        [btn(t("BTN_CANCEL"), "adm:cancel", style=D)],
    )


def sub_added(uid: int, expires: Optional[datetime]) -> str:
    return t("sub_added", uid=uid, date=fmt_date(expires))


def sub_added_user(expires: Optional[datetime]) -> str:
    return t("sub_added_user", date=fmt_date(expires))


def confirm_remove(uid: int, sub: dict) -> str:
    return t("confirm_remove", uid=uid, date=fmt_date(sub["expires_at"]))


def confirm_remove_kb(uid: int) -> InlineKeyboardMarkup:
    return kb(
        [btn(t("BTN_CONFIRM_DEL"), f"adm:delok:{uid}", style=D)],
        [btn(t("BTN_CANCEL"), "adm:cancel", style=D)],
    )


def bc_confirm(total: int) -> str:
    return t("bc_confirm", total=total)


def bc_confirm_kb() -> InlineKeyboardMarkup:
    return kb(
        [btn(t("BTN_BC_GO"), "adm:bcok", style=S)],
        [btn(t("BTN_CANCEL"), "adm:cancel", style=D)],
    )


def bc_progress(done: int, total: int, ok: int, fail: int) -> str:
    return t("bc_progress", done=done, total=total, ok=ok, fail=fail)


def bc_done(total: int, ok: int, fail: int) -> str:
    return t("bc_done", total=total, ok=ok, fail=fail)


def reencoding(reasons: list[str], compress: bool = False) -> str:
    if compress:
        return t("REENC_COMPRESS")
    return t("REENC_AUTO", reasons=t("SEP").join(reasons))


def compress_popup(on: bool) -> str:
    return t("CMP_POP_ON") if on else t("CMP_POP_OFF")


def check_again_kb() -> InlineKeyboardMarkup:
    return kb([btn(t("CHECK_BTN_AGAIN"), "check", style=P)], [btn(t("BTN_BACK"), "home", style=P)])
