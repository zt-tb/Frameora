# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import pytest

pytest.importorskip("pyrogram")
import config
import ui

TECHNIQUE_WORDS = ("ghost", "inflate", "crf", "hevc", "شبح", "stts", "stco", "mdat", "moov", "isom")


@pytest.mark.parametrize("reencoded", [False, True])
@pytest.mark.parametrize("warned", [False, True])
def test_done_caption_has_tip_and_hides_technique(reencoded, warned):
    text = ui.done_caption(60, 5_000_000, verified=True, media_intact=True, method="ZETA1",
                           reencoded=reencoded, warned=warned)
    for needed in ("TikTok Studio", "Firefox", "Downloads"):
        assert needed in text
    assert not any(w in text.lower() for w in TECHNIQUE_WORDS)
    assert len(text) <= 1024 and "<" not in text


def test_done_caption_shows_real_before_and_after_numbers():
    from analyzer import VideoInfo
    before = VideoInfo(codec="h264", width=2160, height=3840, avg_fps=60.0, r_fps=60.0, bitrate_kbps=24500)
    after = VideoInfo(codec="h264", width=1080, height=1920, avg_fps=59.94, r_fps=59.94, bitrate_kbps=9800)
    text = ui.done_caption(60, 5_000_000, before=before, after=after, verified=True, media_intact=True)
    for needed in ("2160×3840", "1080×1920", "24.5 Mbps", "9.8 Mbps", "59.94"):
        assert needed in text
    assert len(text) <= 1024


def test_too_big_message_shows_size_and_limit():
    msg = ui.TOO_BIG.format(size=ui.fmt_size(120 * 1024 * 1024), mb=config.MAX_FILE_MB)
    assert "120.0 MB" in msg and str(config.MAX_FILE_MB) in msg


def test_compress_button_is_off_by_default_and_toggles_label():
    def labels(kb):
        return [(b.text, b.callback_data) for row in kb.inline_keyboard for b in row]
    off = [x for x in labels(ui.main_kb(False)) if x[1] == "cmp"]
    on = [x for x in labels(ui.main_kb(False, compress=True)) if x[1] == "cmp"]
    assert len(off) == 1 and "⬜" in off[0][0] and len(on) == 1 and "✅" in on[0][0]
    assert "H.264" not in ui.reencoding([], True) and "CRF" not in ui.reencoding([], True)
    assert len(ui.compress_popup(True)) <= 200 and len(ui.compress_popup(False)) <= 200


def test_main_and_admin_ui_have_no_auto_publish_or_draft_actions():
    for markup in (ui.main_kb(False), ui.admin_kb(False)):
        data = [b.callback_data for row in markup.inline_keyboard for b in row]
        assert not any(x and (x.startswith("ap:") or x.startswith("tt")) for x in data)
    assert not hasattr(ui, "post_kb")


def test_picker_shows_only_zeta_choices_and_hides_implementation_details():
    buttons = [b for row in ui.method_kb(123).inline_keyboard for b in row]
    labels = " ".join(b.text for b in buttons)
    callbacks = [b.callback_data for b in buttons]
    assert "timecode" not in labels.lower()
    assert "Spark" in labels and "Blaze" in labels and "Pulse" in labels and "zeta" not in labels.lower()
    assert {"pm:ZETA1:123", "pm:ZETA2:123", "pm:ZETA3:123"} <= set(callbacks)
    assert not any(x and x.startswith(("pm:GHOST", "pm:INFLATE", "pm:HEADER", "pm:TIMECODE")) for x in callbacks)
    assert "timecode" not in ui.HELP.lower() and "timecode" not in ui.PICK_TITLE.lower()

def test_stars_payment_button_is_available_to_unsubscribed_users():
    data = [b.callback_data for row in ui.sub_alert_kb().inline_keyboard for b in row]
    assert "stars:buy" in data

def test_every_button_has_a_color():
    import ast
    import pathlib

    tree = ast.parse(pathlib.Path(ui.__file__).read_text(encoding="utf-8"))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "btn"]
    assert calls
    for call in calls:
        style = [k.value for k in call.keywords if k.arg == "style"]
        assert style, f"button without style at line {call.lineno}"
        assert not (isinstance(style[0], ast.Constant) and style[0].value is None), call.lineno
