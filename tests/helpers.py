# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import subprocess


def make_video(path, *, fps=60, codec="libx264", seconds=2, audio=False, faststart=False, size="320x568", extra=()):
    cmd = ["ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
           f"testsrc=duration={seconds}:size={size}:rate={fps}"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=duration={seconds}", "-c:a", "aac", "-shortest"]
    cmd += ["-c:v", codec, "-pix_fmt", "yuv420p"]
    if codec == "libx265":
        cmd += ["-tag:v", "hvc1", "-x265-params", "log-level=none"]
    if faststart:
        cmd += ["-movflags", "+faststart"]
    cmd += list(extra)
    cmd.append(str(path))
    subprocess.run(cmd, check=True)
    return str(path)


def frame_hashes(path):
    out = subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(path), "-map", "0:v", "-f", "framemd5", "-"],
                         capture_output=True, text=True).stdout
    return [ln.split(",")[-1].strip() for ln in out.splitlines() if ln and not ln.startswith("#")]


def has_encoder(name):
    out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    return name in out


def audio_md5(path):
    return subprocess.run(["ffmpeg", "-v", "quiet", "-i", str(path), "-map", "0:a", "-f", "md5", "-"],
                          capture_output=True, text=True).stdout
