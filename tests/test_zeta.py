# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio
import os
import shutil
import struct
import subprocess
from datetime import datetime, timezone

import pytest

import config
import patcher
import zeta
from helpers import audio_md5, frame_hashes, make_video
from patcher_errors import PatchError

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is required")


def _top(path):
    with open(path, "rb") as f:
        return zeta._scan_top(f, os.path.getsize(path))


def _mvhd(path):
    raw = open(path, "rb").read()
    i = raw.find(b"mvhd") + 4
    version = raw[i]
    if version == 0:
        return version, struct.unpack_from(">I", raw, i + 16)[0]
    return version, struct.unpack_from(">Q", raw, i + 24)[0]


def _source(tmp_path, **kw):
    return make_video(tmp_path / "src.mp4", fps=kw.pop("fps", 30), audio=True, **kw)


@pytest.mark.parametrize("fps", [24, 30, 60])
def test_lite_only_touches_duration_and_appends_signature(tmp_path, fps):
    src = _source(tmp_path, fps=fps)
    out = str(tmp_path / "out.mp4")
    shutil.copy(src, out)
    before = zeta.mdat_hash(out)
    size = os.path.getsize(out)
    res = zeta.zeta_mp4(out, zeta.LITE)
    assert zeta.verify(out, before, res) is None
    assert res.moov_growth == 0 and res.shift == 0
    assert os.path.getsize(out) == size + res.tail_bytes
    assert _mvhd(out) == (0, zeta.OPEN32)
    assert _top(out)[-1][0] == b"free"
    assert frame_hashes(out) == frame_hashes(src)
    assert audio_md5(out) == audio_md5(src)


@pytest.mark.parametrize("faststart", [True, False])
def test_best_upgrades_mvhd_and_keeps_offsets_valid(tmp_path, faststart):
    src = _source(tmp_path, faststart=faststart)
    out = str(tmp_path / "out.mp4")
    shutil.copy(src, out)
    before = zeta.mdat_hash(out)
    res = zeta.zeta_mp4(out, zeta.BEST)
    assert zeta.verify(out, before, res) is None
    assert _mvhd(out) == (1, zeta.OPEN64)
    assert (res.shift != 0) == faststart
    assert b"\xa9too" in open(out, "rb").read()
    assert frame_hashes(out) == frame_hashes(src)
    assert audio_md5(out) == audio_md5(src)
    decode = subprocess.run(["ffmpeg", "-v", "error", "-i", out, "-f", "null", "-"],
                            capture_output=True, text=True)
    assert decode.stderr.strip() == ""


def test_signature_and_tag_are_ours(tmp_path):
    src = _source(tmp_path)
    out = str(tmp_path / "out.mp4")
    shutil.copy(src, out)
    zeta.zeta_mp4(out, zeta.BEST, when=datetime(2026, 1, 2, 3, 4, 5, 678000, tzinfo=timezone.utc))
    raw = open(out, "rb").read()
    assert b"FRAMEORA/BLAZE 2026-01-02T03:04:05.678Z" in raw
    assert b"Frameora" in raw
    assert b"zilem" not in raw.lower()


def test_unknown_method_and_bad_file_are_rejected(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not an mp4 at all, just text")
    with pytest.raises(PatchError):
        zeta.zeta_mp4(str(bad), zeta.LITE)
    src = _source(tmp_path)
    with pytest.raises(PatchError):
        zeta.zeta_mp4(src, "NOPE")


@pytest.mark.parametrize("method", list(zeta.METHODS))
def test_process_video_accepts_any_fps(tmp_path, method):
    src = _source(tmp_path, fps=30)
    out = str(tmp_path / "out.mp4")
    shutil.copy(src, out)
    res = asyncio.run(patcher.process_video(out, method=method))
    assert res.method == method and res.verified and res.zeta is not None
    assert res.fps == 30
    assert frame_hashes(out) == frame_hashes(src)


def test_every_configured_method_has_a_button_label():
    import i18n

    for method in config.PATCH_METHODS:
        label = "ZETA3" if method == "TIMECODE" else method
        assert i18n.has(f"BTN_M_{label}")
