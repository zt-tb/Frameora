# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import analyzer
from i18n import t
import config
import mp4box
import patcher
from analyzer import VideoInfo
from helpers import audio_md5, frame_hashes, has_encoder, make_video

ROOT = Path(__file__).resolve().parents[1]
CODECS = {
    "h264": ("libx264", ()),
    "hevc": ("libx265", ("-tag:v", "hvc1", "-x265-params", "log-level=none")),
    "vp9": ("libvpx-vp9", ("-deadline", "realtime", "-cpu-used", "8")),
    "av1": ("libsvtav1", ("-preset", "12")),
}


def _top(path):
    with open(path, "rb") as f:
        return mp4box._scan_top(f, os.path.getsize(path))


def _major_brand(path):
    with open(path, "rb") as f:
        f.seek(8)
        return f.read(4)


def _moov_before_mdat(path):
    kinds = [k for k, _, _ in _top(path)]
    return kinds.index(b"moov") < kinds.index(b"mdat")


def _probe(p):
    return asyncio.run(analyzer.probe(str(p)))


def _info(**kw):
    base = dict(codec="h264", width=1080, height=1920, avg_fps=60.0, r_fps=60.0, bitrate_kbps=20000,
                duration=10, has_audio=True, audio_codec="aac")
    base.update(kw)
    return VideoInfo(**base)


def _config_in_clean_env(**env):
    clean = {k: v for k, v in os.environ.items() if k not in ("SMART_REENCODE", "MAX_FILE_MB")}
    clean.update(env, PYTHONPATH=str(ROOT))
    out = subprocess.run([sys.executable, "-c", "import config; print(config.SMART_REENCODE, config.MAX_FILE_MB)"],
                         capture_output=True, text=True, env=clean, cwd=os.path.dirname(sys.executable))
    return out.stdout.split()


def test_defaults_are_lossless_and_500mb():
    assert _config_in_clean_env() == ["False", "500"]
    assert _config_in_clean_env(MAX_FILE_MB="25", SMART_REENCODE="1") == ["True", "25"]
    assert _config_in_clean_env(MAX_FILE_MB="0")[1] == "500" and _config_in_clean_env(MAX_FILE_MB="abc")[1] == "500"


@pytest.mark.parametrize("name", ["h264", "hevc", "vp9", "av1"])
def test_no_default_reencode_any_codec(tmp_path, name):
    enc, extra = CODECS[name]
    if not has_encoder(enc):
        pytest.skip(f"{enc} not available")
    assert config.SMART_REENCODE is False or os.getenv("SMART_REENCODE")
    src = make_video(tmp_path / "in.mp4", codec=enc, audio=True, extra=extra)
    dst = str(tmp_path / "out.mp4")
    shutil.copy(src, dst)
    res = asyncio.run(patcher.process_video(dst, method="ZETA1"))
    assert not res.reencoded and not res.remuxed and res.verified and res.media_intact
    assert _probe(dst).codec == _probe(src).codec
    assert frame_hashes(src) == frame_hashes(dst) and audio_md5(src) == audio_md5(dst)


def test_vfr_is_patched_without_reencode_and_only_warns(tmp_path):
    out = tmp_path / "vfr.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=duration=3:size=320x568:rate=60", "-vf", "select='not(mod(n,3))+not(mod(n,7))'",
                    "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    info = _probe(out)
    assert info.is_vfr and any("VFR" in w for w in analyzer.warning_lines(info))
    res = asyncio.run(patcher.process_video(str(out), info, method="ZETA1"))
    assert not res.reencoded and res.verified and res.fps == 60


def test_remux_command_is_stream_copy_faststart():
    j = " ".join(analyzer.build_remux_cmd("a.mov", "b.mp4"))
    assert "-c copy" in j and "+faststart" in j and "libx264" not in j and j.endswith("b.mp4")


@pytest.mark.parametrize("name", ["h264", "hevc"])
def test_mov_is_remuxed_to_mp4_losslessly(tmp_path, name):
    enc, extra = CODECS[name]
    src = make_video(tmp_path / "in.mov", codec=enc, audio=True, extra=extra)
    assert _probe(src).is_mov
    dst = str(tmp_path / "work.mp4")
    shutil.copy(src, dst)
    res = asyncio.run(patcher.process_video(dst, method="ZETA1"))
    assert res.remuxed and res.remux_intact is True and not res.reencoded
    assert not _probe(dst).is_mov and _major_brand(dst) == b"isom"
    assert _moov_before_mdat(dst)
    assert _probe(dst).codec == _probe(src).codec
    assert frame_hashes(src) == frame_hashes(dst) and audio_md5(src) == audio_md5(dst)
    before = asyncio.run(analyzer.payload_hashes(src))["a"]
    assert asyncio.run(analyzer.payload_hashes(dst))["a"] == before


def test_remux_payload_mismatch_is_rejected_and_file_untouched(tmp_path, monkeypatch):
    src = make_video(tmp_path / "in.mov", audio=True)
    work = str(tmp_path / "w.mp4")
    shutil.copy(src, work)
    calls = []

    async def fake(path, timeout=300):
        calls.append(path)
        return {"v": "a" * 64 if len(calls) == 1 else "b" * 64}

    monkeypatch.setattr(patcher, "payload_hashes", fake)
    with pytest.raises(patcher.PatchError):
        asyncio.run(patcher.process_video(work, method="ZETA1"))
    assert _probe(work).is_mov and not os.path.exists(work + ".remux.mp4")


def test_mov_with_compress_outputs_mp4_without_double_work(tmp_path):
    src = make_video(tmp_path / "in.mov", audio=True)
    work = str(tmp_path / "w.mp4")
    shutil.copy(src, work)
    res = asyncio.run(patcher.process_video(work, method="ZETA1", compress=True))
    assert res.reencoded and res.compressed and not res.remuxed
    assert not _probe(work).is_mov and _probe(work).codec == "h264"


def test_no_audio_warns_but_does_not_block(tmp_path):
    src = make_video(tmp_path / "silent.mp4", audio=False)
    info = _probe(src)
    assert not info.has_audio
    assert t("WARN_NO_AUDIO") in analyzer.warning_lines(info)
    assert t("WARN_NO_AUDIO") in analyzer.advise(info)
    res = asyncio.run(patcher.process_video(src, info, method="ZETA1"))
    assert res.verified
    with_audio = _probe(make_video(tmp_path / "a.mp4", audio=True))
    assert t("WARN_NO_AUDIO") not in analyzer.warning_lines(with_audio)


def test_size_limit(monkeypatch):
    monkeypatch.setattr(config, "MAX_FILE_MB", 90)
    mb = 1024 * 1024
    assert not config.exceeds_size_limit(90 * mb) and config.exceeds_size_limit(90 * mb + 1)
    assert not config.exceeds_size_limit(0) and not config.exceeds_size_limit(None)
    monkeypatch.setattr(config, "MAX_FILE_MB", 10)
    assert config.exceeds_size_limit(11 * mb)


def test_compress_size_rules():
    assert analyzer.compress_size(_info(width=2160, height=3840)) == (1080, 1920)
    assert analyzer.compress_size(_info(width=1440, height=2560)) == (1080, 1920)
    assert analyzer.compress_size(_info(width=3840, height=2160)) == (1920, 1080)
    assert analyzer.compress_size(_info(width=1080, height=1920)) is None
    assert analyzer.compress_size(_info(width=1920, height=1080, rotation=90)) is None
    assert analyzer.compress_size(_info(width=720, height=1280)) is None


def test_compress_command_scales_cfr_h264_only_when_asked():
    on = " ".join(analyzer.build_reencode_cmd("a", "b", _info(width=2160, height=3840), compress=True))
    assert "-vf scale=1080:1920" in on and "-c:v libx264" in on and "-fps_mode cfr" in on and "-r 60" in on
    assert "-vf" not in " ".join(analyzer.build_reencode_cmd("a", "b", _info(width=2160, height=3840)))


def test_compress_first_end_to_end_and_off_by_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMPRESS_SHORT_SIDE", 240)
    src = make_video(tmp_path / "h.mp4", codec="libx265", audio=True, extra=("-tag:v", "hvc1"))
    plain = str(tmp_path / "plain.mp4")
    shutil.copy(src, plain)
    assert not asyncio.run(patcher.process_video(plain, method="ZETA1")).reencoded
    assert _probe(plain).codec == "hevc"
    packed = str(tmp_path / "packed.mp4")
    shutil.copy(src, packed)
    res = asyncio.run(patcher.process_video(packed, method="ZETA1", compress=True))
    info = _probe(packed)
    assert res.reencoded and res.compressed and res.fps == 60 and info.codec == "h264"
    assert (info.view_w, info.view_h) == (240, 426) and not info.is_vfr
