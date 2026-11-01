# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio
import os


import config
import quality
from helpers import make_video


def test_only_tiktok_urls_are_accepted():
    ok = ["https://www.tiktok.com/@u/video/1", "https://vm.tiktok.com/abc/", "http://tiktok.com/x"]
    bad = ["https://evil.com/?u=tiktok.com", "https://nottiktok.com/x", "http://127.0.0.1/x",
           "ftp://tiktok.com/x", "https://tiktok.com.evil.com/x", "not a url"]
    assert all(quality.is_tiktok_url(u) for u in ok)
    assert not any(quality.is_tiktok_url(u) for u in bad)


def test_extract_url():
    assert quality.extract_url("شوف https://vm.tiktok.com/abc/ شكراً") == "https://vm.tiktok.com/abc/"
    assert quality.extract_url("no link") is None


def test_parse_metrics():
    assert quality.parse_ssim("[Parsed_ssim_4 @ 0x1] SSIM Y:0.9 (10) U:0.9 (10) V:0.9 (10) All:0.912345 (10.5)") == 0.912345
    assert quality.parse_ssim("nothing") is None
    assert quality.parse_vmaf("[libvmaf @ 0x1] VMAF score: 93.456") == 93.456


def test_verdict_thresholds():
    from analyzer import VideoInfo

    v = VideoInfo(codec="h264", width=1080, height=1920, avg_fps=60, r_fps=60, bitrate_kbps=10000)
    def mk(m, s):
        return quality.build_report(v, v, m, s, 10)
    assert "ممتاز" in mk("ssim", 0.99).verdict and "جيد" in mk("ssim", 0.95).verdict and "ضعيف" in mk("ssim", 0.8).verdict
    assert "ممتاز" in mk("vmaf", 95).verdict and "ضعيف" in mk("vmaf", 60).verdict
    report = quality.format_report(mk("ssim", 0.97))
    assert "SSIM" not in report and "ممتازة" in report


def test_reference_store_and_expiry(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REF_DIR", str(tmp_path / "refs"))
    monkeypatch.setattr(config, "KEEP_REFERENCE", True)
    src = make_video(tmp_path / "a.mp4", seconds=1)
    assert quality.store_reference_sync(7, src, source_duration=1.0)
    ref = quality.get_reference(7)
    assert ref
    original = open(ref, "rb").read()
    assert quality.get_reference_duration(7) == 1.0
    assert os.stat(src).st_ino != os.stat(ref).st_ino
    replacement = tmp_path / "replacement.mp4"
    replacement.write_bytes(b"processed version")
    os.replace(replacement, src)
    assert open(ref, "rb").read() == original
    os.utime(quality.get_reference(7), (1, 1))
    assert quality.get_reference(7) is None
    monkeypatch.setattr(config, "KEEP_REFERENCE", False)
    assert quality.store_reference_sync(8, src) is False


def test_reference_is_trimmed_to_check_window_and_compare_uses_first_window(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REF_DIR", str(tmp_path / "refs"))
    monkeypatch.setattr(config, "KEEP_REFERENCE", True)
    monkeypatch.setattr(config, "CHECK_MAX_SECONDS", 2)
    source = make_video(tmp_path / "long.mp4", seconds=6)
    source_size = os.path.getsize(source)
    assert quality.store_reference_sync(17, source, source_duration=6.0)
    ref = quality.get_reference(17)
    assert ref
    from analyzer import probe
    ref_info = asyncio.run(probe(ref))
    assert 1.5 <= ref_info.duration <= 2.5
    assert os.path.getsize(ref) < source_size
    assert quality.get_reference_duration(17) == 6.0
    report = asyncio.run(quality.compare(ref, source, metric="ssim", reference_duration=6.0))
    assert report.seconds == 2
    assert report.reference_duration == 6.0
    assert not quality.duration_mismatch(report.ref, report.pub, report.reference_duration)


def test_trim_failure_falls_back_to_hardlink_then_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REF_DIR", str(tmp_path / "refs"))
    monkeypatch.setattr(config, "KEEP_REFERENCE", True)
    source = make_video(tmp_path / "fallback.mp4", seconds=1)
    monkeypatch.setattr(quality, "_trim_reference", lambda _src, _dst: False)

    def no_hardlink(_src, _dst):
        raise OSError("cross-device link")

    monkeypatch.setattr(quality.os, "link", no_hardlink)
    assert quality.store_reference_sync(18, source, source_duration=1.0)
    ref = quality.get_reference(18)
    assert ref and open(ref, "rb").read() == open(source, "rb").read()


def test_compare_identical_and_degraded(tmp_path):
    import subprocess

    ref = make_video(tmp_path / "ref.mp4", seconds=2)
    bad = tmp_path / "bad.mp4"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", ref, "-c:v", "libx264", "-b:v", "60k",
                    "-vf", "scale=240:426", "-r", "30", str(bad)], check=True)
    same = asyncio.run(quality.compare(ref, ref, metric="ssim"))
    worse = asyncio.run(quality.compare(ref, str(bad), metric="ssim"))
    assert same.score > 0.99 and worse.score < same.score
    assert (worse.ref.view_w, worse.pub.view_w) == (320, 240)


def test_missing_container_bitrate_is_computed_not_zero():
    import analyzer

    data = {"format": {"size": "12500000", "duration": "10.0"},
            "streams": [{"codec_type": "video", "codec_name": "hevc", "width": 1080, "height": 1920,
                         "avg_frame_rate": "60/1", "r_frame_rate": "60/1"}]}
    assert analyzer.parse_probe(data).bitrate_kbps == 10000
    data["streams"][0]["bit_rate"] = "9000000"
    assert analyzer.parse_probe(data).bitrate_kbps == 9000


def test_unknown_published_bitrate_is_not_reported_as_heavy_compression():
    from analyzer import VideoInfo

    ref = VideoInfo(codec="hevc", width=1080, height=1920, avg_fps=60, r_fps=60, bitrate_kbps=52900, duration=17.7)
    pub = VideoInfo(codec="hevc", width=1080, height=1920, avg_fps=60, r_fps=60, bitrate_kbps=0, duration=17.7)
    text = quality.format_report(quality.build_report(ref, pub, "ssim", 0.99, 17))
    assert not quality.build_report(ref, pub, "ssim", 0.99, 17).aggressive_compression
    assert "-100%" not in text and "ضغط الفيديو بقوة" not in text


def test_different_length_is_flagged():
    from analyzer import VideoInfo

    ref = VideoInfo(codec="h264", width=1080, height=1920, avg_fps=60, r_fps=60, bitrate_kbps=9000, duration=17.7)
    pub = VideoInfo(codec="h264", width=1080, height=1920, avg_fps=60, r_fps=60, bitrate_kbps=9000, duration=1.2)
    assert quality.duration_mismatch(ref, pub)
    assert "مدة الفيديو المنشور تختلف" in quality.format_report(quality.build_report(ref, pub, "ssim", 1.0, 1))


def test_patched_file_with_unknown_header_duration_is_not_flagged_as_wrong_video():
    from analyzer import VideoInfo

    ref = VideoInfo(codec="hevc", width=1080, height=1920, avg_fps=60, r_fps=60, bitrate_kbps=52900, duration=18.6)
    pub = VideoInfo(codec="hevc", width=1080, height=1920, avg_fps=60, r_fps=60, bitrate_kbps=53000, duration=0.001)
    assert not quality.duration_mismatch(ref, pub)
    text = quality.format_report(quality.build_report(ref, pub, "ssim", 1.0, 18))
    assert "18.6s" in text and "مدة الفيديو المنشور تختلف" not in text


def test_numbers_keep_their_order_inside_arabic_text():
    from analyzer import VideoInfo

    v = VideoInfo(codec="hevc", width=2042, height=3840, avg_fps=60, r_fps=60, bitrate_kbps=52900, duration=18.6)
    text = quality.format_report(quality.build_report(v, v, "ssim", 1.0, 18))
    assert "\u200e2042×3840\u200e" in text and "\u200e+0%\u200e" in text
