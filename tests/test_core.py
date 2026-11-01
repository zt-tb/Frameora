# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import analyzer


def _make(tmp_path, fps, name):
    out = tmp_path / name
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         f"testsrc=duration=1:size=320x568:rate={fps}", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", str(out)], check=True)
    return str(out)


def test_vfr_detected(tmp_path):
    out = tmp_path / "vfr.mp4"
    subprocess.run(
        ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
         "testsrc=duration=3:size=320x568:rate=60", "-vf",
         "select='not(mod(n,3))+not(mod(n,7))'", "-fps_mode", "vfr",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(out)], check=True)
    assert asyncio.run(analyzer.probe(str(out))).is_vfr
