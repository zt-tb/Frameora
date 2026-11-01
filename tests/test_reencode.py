# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio
import subprocess


import analyzer
import config
import patcher
from analyzer import VideoInfo
from helpers import make_video


def _info(**kw):
    base = dict(codec="h264", width=1080, height=1920, avg_fps=60.0, r_fps=60.0, bitrate_kbps=20000,
                duration=10, has_audio=True, audio_codec="aac")
    base.update(kw)
    return VideoInfo(**base)


def test_needs_reencode_rules():
    assert analyzer.needs_reencode(_info()) == []
    assert analyzer.needs_reencode(_info(is_vfr=True)) == ["VFR"]
    assert "HEVC" in analyzer.needs_reencode(_info(codec="hevc"))[0]
    assert any("AV1" in r for r in analyzer.needs_reencode(_info(codec="av1")))
    assert any("بتريت" in r for r in analyzer.needs_reencode(_info(bitrate_kbps=1500)))
    assert analyzer.needs_reencode(_info(bitrate_kbps=1500, width=360, height=640)) == []


def test_target_fps_snaps_to_nominal():
    assert analyzer.target_fps(_info(avg_fps=60, r_fps=60)) == "60"
    assert analyzer.target_fps(_info(avg_fps=59.94, r_fps=60000 / 1001)) == "60000/1001"
    assert analyzer.target_fps(_info(is_vfr=True, avg_fps=54.0, r_fps=60, nb_frames=540, duration=10)) == "60"
    assert analyzer.target_fps(_info(avg_fps=120, r_fps=120)) == "120"


def test_reencode_command_is_crf18_cfr_same_fps():
    cmd = analyzer.build_reencode_cmd("a.mp4", "b.mp4", _info())
    j = " ".join(cmd)
    assert "-c:v libx264" in j and "-crf 18" in j and "-fps_mode cfr" in j and "-r 60" in j
    assert "-pix_fmt yuv420p" in j and cmd[-1] == "b.mp4"
    assert "-c:a copy" in j
    assert "-c:a aac" in " ".join(analyzer.build_reencode_cmd("a", "b", _info(audio_codec="opus")))


def test_reencode_crf_follows_config(monkeypatch):
    monkeypatch.setattr(config, "REENCODE_CRF", 20)
    assert "-crf 20" in " ".join(analyzer.build_reencode_cmd("a", "b", _info()))


def test_hevc_is_reencoded_to_h264_and_fps_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SMART_REENCODE", True)
    src = make_video(tmp_path / "h.mp4", codec="libx265", audio=False)
    res = asyncio.run(patcher.process_video(src, method="ZETA1"))
    assert res.reencoded and res.fps == 60
    info = asyncio.run(analyzer.probe(src))
    assert info.codec == "h264"


def test_vfr_becomes_cfr_60(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SMART_REENCODE", True)
    out = tmp_path / "vfr.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=duration=3:size=320x568:rate=60", "-vf", "select='not(mod(n,3))+not(mod(n,7))'",
                    "-fps_mode", "vfr", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    assert asyncio.run(analyzer.probe(str(out))).is_vfr
    res = asyncio.run(patcher.process_video(str(out), method="ZETA1"))
    assert res.reencoded and "VFR" in res.reencode_reasons
    after = asyncio.run(analyzer.probe(str(out)))
    assert not after.is_vfr and round(after.fps) == 60


def test_clean_h264_cfr_is_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SMART_REENCODE", True)
    src = make_video(tmp_path / "ok.mp4")
    res = asyncio.run(patcher.process_video(src, method="ZETA1"))
    assert not res.reencoded


def test_30_fps_is_accepted_by_every_method(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SMART_REENCODE", False)
    for method in ("ZETA1", "ZETA2", "ZETA3"):
        src = make_video(tmp_path / f"{method}.mp4", fps=30)
        assert asyncio.run(patcher.process_video(src, method=method)).fps == 30


def test_smart_reencode_can_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SMART_REENCODE", False)
    src = make_video(tmp_path / "h.mp4", codec="libx265")
    res = asyncio.run(patcher.process_video(src, method="ZETA1"))
    assert not res.reencoded and asyncio.run(analyzer.probe(src)).codec == "hevc"
