# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

import config
import patcher_errors as pe
from i18n import t

log = logging.getLogger(__name__)

HDR_TRANSFERS = {"smpte2084": "HDR10 (PQ)", "arib-std-b67": "HLG"}


@dataclass
class VideoInfo:
    container: str = ""
    size: int = 0
    duration: float = 0.0
    bitrate_kbps: int = 0
    codec: str = ""
    profile: str = ""
    width: int = 0
    height: int = 0
    rotation: int = 0
    pix_fmt: str = ""
    bit_depth: int = 0
    avg_fps: float = 0.0
    r_fps: float = 0.0
    nb_frames: int = 0
    hdr: str = ""
    has_audio: bool = False
    audio_codec: str = ""
    is_vfr: bool = False
    audio_tags: dict = field(default_factory=dict)
    color_primaries: str = ""
    color_transfer: str = ""
    color_space: str = ""
    major_brand: str = ""
    warnings: list = field(default_factory=list)

    @property
    def is_mov(self) -> bool:
        return self.major_brand.strip().lower() == "qt"

    @property
    def looks_inflated(self) -> bool:
        return self.r_fps > 0 and self.avg_fps >= self.r_fps * 2.5

    @property
    def is_h264(self) -> bool:
        return self.codec in ("h264", "avc1")

    @property
    def is_hevc(self) -> bool:
        return self.codec in ("hevc", "h265")

    @property
    def is_av1(self) -> bool:
        return self.codec in ("av1", "av01")

    @property
    def is_vp9(self) -> bool:
        return self.codec in ("vp9", "vp09")

    @property
    def view_w(self) -> int:
        return self.height if self.rotation in (90, 270) else self.width

    @property
    def view_h(self) -> int:
        return self.width if self.rotation in (90, 270) else self.height

    @property
    def fps(self) -> float:
        if self.looks_inflated:
            return self.r_fps
        if self.is_vfr and self.nb_frames and self.duration:
            return self.nb_frames / self.duration
        return self.avg_fps or self.r_fps


def _frac(value: str) -> float:
    try:
        if "/" in str(value):
            a, b = str(value).split("/", 1)
            return float(a) / float(b) if float(b) else 0.0
        return float(value)
    except (ValueError, ZeroDivisionError, TypeError):
        return 0.0


def _int(v, default=0) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _rotation(stream: dict) -> int:
    rot = 0
    try:
        rot = int((stream.get("tags") or {}).get("rotate", 0))
    except (TypeError, ValueError):
        pass
    for sd in stream.get("side_data_list") or []:
        if "rotation" in sd:
            try:
                rot = int(float(sd["rotation"]))
            except (TypeError, ValueError):
                pass
    return rot % 360


def _bitrate_kbps(fmt: dict, streams: list, size: int, duration: float) -> int:
    kbps = _int(fmt.get("bit_rate")) // 1000
    if kbps:
        return kbps
    kbps = sum(_int(s.get("bit_rate")) for s in streams) // 1000
    if kbps:
        return kbps
    return int(size * 8 / duration / 1000) if size and duration > 0 else 0


def parse_probe(data: dict) -> VideoInfo:
    streams = data.get("streams") or []
    fmt = data.get("format") or {}
    v = next((s for s in streams if s.get("codec_type") == "video"
              and not (s.get("disposition") or {}).get("attached_pic")), None)
    if v is None:
        raise pe.PatchError("no video stream found")
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)

    info = VideoInfo(
        container=(fmt.get("format_name") or "").split(",")[0],
        size=_int(fmt.get("size")),
        duration=float(fmt.get("duration") or v.get("duration") or 0),
        bitrate_kbps=0,
        codec=v.get("codec_name", ""),
        profile=v.get("profile", "") or "",
        width=_int(v.get("width")),
        height=_int(v.get("height")),
        rotation=_rotation(v),
        pix_fmt=v.get("pix_fmt", "") or "",
        bit_depth=_int(v.get("bits_per_raw_sample")) or (10 if "10" in (v.get("pix_fmt") or "") else 8),
        avg_fps=_frac(v.get("avg_frame_rate", "0")),
        r_fps=_frac(v.get("r_frame_rate", "0")),
        nb_frames=_int(v.get("nb_frames")),
        hdr=HDR_TRANSFERS.get(v.get("color_transfer", ""), ""),
        has_audio=a is not None,
        audio_codec=(a or {}).get("codec_name", ""),
        color_primaries=v.get("color_primaries", "") or "",
        color_transfer=v.get("color_transfer", "") or "",
        color_space=v.get("color_space", "") or "",
        major_brand=str((fmt.get("tags") or {}).get("major_brand", "") or ""),
    )
    info.bitrate_kbps = _bitrate_kbps(fmt, streams, info.size, info.duration)
    tags: dict = {}
    for src in (fmt.get("tags"), (a or {}).get("tags")):
        for k, val in (src or {}).items():
            tags[str(k).lower()] = str(val)
    info.audio_tags = tags
    if info.avg_fps <= 0 and info.r_fps <= 0:
        raise pe.PatchError("cannot detect fps")

    if info.avg_fps > 0 and info.r_fps > 0:
        info.is_vfr = (abs(info.avg_fps - info.r_fps) / info.r_fps > 0.02
                       and not info.looks_inflated)
    return info


async def probe(path: str, timeout: int = 90) -> VideoInfo:
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", path,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except FileNotFoundError as exc:
        raise pe.PatchError("ffprobe is not installed") from exc
    except asyncio.TimeoutError as exc:
        raise pe.PatchError("ffprobe timed out") from exc
    try:
        data = json.loads(out or b"{}")
    except json.JSONDecodeError as exc:
        raise pe.PatchError("cannot read video info") from exc
    return parse_probe(data)


def warning_lines(info: VideoInfo) -> list[str]:
    lines: list[str] = []
    if info.is_vfr:
        lines.append(t("WARN_VFR", fps=info.fps))
    if not info.has_audio:
        lines.append(t("WARN_NO_AUDIO"))
    return lines


def advise(info: VideoInfo, *, sent_as_video: bool = False) -> list[str]:
    tips: list[str] = []

    if info.looks_inflated:
        tips.append(t("TIP_INFLATED"))
    if sent_as_video:
        tips.append(t("TIP_AS_VIDEO"))
    tips.extend(warning_lines(info))
    if info.is_av1:
        tips.append(t("TIP_AV1"))
    elif info.is_vp9:
        tips.append(t("TIP_VP9"))
    elif info.is_hevc:
        tips.append(t("TIP_HEVC"))
    elif not info.is_h264:
        tips.append(t("TIP_CODEC", codec=html.escape(info.codec or "?")))
    if info.bit_depth > 8 and not info.hdr:
        tips.append(t("TIP_10BIT"))
    if info.hdr:
        tips.append(t("TIP_HDR", hdr=html.escape(str(info.hdr))))
    longest = max(info.view_w, info.view_h)
    if longest and longest < 1920:
        tips.append(t("TIP_RES", w=info.view_w, h=info.view_h))
    if longest > 4096:
        tips.append(t("TIP_RES_MAX"))
    if info.view_w > info.view_h and info.view_w:
        tips.append(t("TIP_LANDSCAPE"))
    if info.duration and info.bitrate_kbps and info.bitrate_kbps < 8000 and longest >= 1920:
        tips.append(t("TIP_LOW_BITRATE", mbps=info.bitrate_kbps / 1000))
    if info.has_audio and audio_hints(info):
        tips.append(t("TIP_MUSIC", hints=t("SEP").join(audio_hints(info)[:3])))
    if config.SMART_REENCODE:
        why = needs_reencode(info)
        if why:
            tips.append(t("TIP_AUTO_REENC", crf=config.REENCODE_CRF, reasons=t("SEP").join(why)))
    return tips


def format_report(info: VideoInfo) -> str:
    flags = []
    if info.is_vfr:
        flags.append("VFR ⚠️")
    if info.hdr:
        flags.append(html.escape(str(info.hdr)))
    dur = f"{int(info.duration // 60)}:{int(info.duration % 60):02d}" if info.duration else "—"
    mb = info.size / (1024 * 1024) if info.size else 0
    bitrate = f"  •  📊 <b>{info.bitrate_kbps / 1000:.1f} Mbps</b>" if info.bitrate_kbps else ""
    audio = html.escape(info.audio_codec.upper()) if info.has_audio else t("NONE")
    return t(
        "REPORT", fps=info.fps, w=info.view_w, h=info.view_h,
        codec=html.escape(info.codec.upper() or "?"), depth=info.bit_depth, dur=dur, mb=mb,
        bitrate=bitrate, audio=audio, flags=(f"\n🏷 {' • '.join(flags)}" if flags else ""),
    )


_MUSIC_TAGS = {
    "artist": "MT_ARTIST", "album_artist": "MT_ARTIST", "album": "MT_ALBUM", "composer": "MT_COMPOSER",
    "isrc": "MT_ISRC", "copyright": "MT_COPYRIGHT", "publisher": "MT_PUBLISHER", "label": "MT_LABEL",
    "genre": "MT_GENRE",
}


def audio_hints(info: VideoInfo) -> list[str]:
    if not info.has_audio:
        return []
    hints = []
    for key, label_key in _MUSIC_TAGS.items():
        val = (info.audio_tags.get(key) or "").strip()
        label = t(label_key)
        if val and label not in hints:
            hints.append(label)
    return hints


def needs_reencode(info: VideoInfo) -> list[str]:
    reasons: list[str] = []
    if info.is_vfr:
        reasons.append("VFR")
    if not info.is_h264:
        reasons.append(t("R_CODEC", codec=html.escape(info.codec.upper() or "?")))
    longest = max(info.view_w, info.view_h)
    if (info.bitrate_kbps and longest >= 1080 and info.bitrate_kbps < config.LOW_BITRATE_KBPS):
        reasons.append(t("R_LOW_BITRATE", mbps=info.bitrate_kbps / 1000))
    return reasons


def target_fps(info: VideoInfo) -> str:
    fps = info.fps
    for nominal, exact in ((60, "60000/1001"), (120, "120000/1001")):
        if abs(fps - nominal) <= 0.5 and info.r_fps and abs(info.r_fps - nominal * 1000 / 1001) < 0.02:
            return exact
    for nominal in (60, 120):
        if abs(fps - nominal) <= max(1.5, nominal * 0.12):
            return str(nominal)
    return f"{info.r_fps or fps:.3f}"


def compress_size(info: VideoInfo) -> Optional[tuple[int, int]]:
    w, h = info.view_w, info.view_h
    short = min(w, h)
    if not short or short <= config.COMPRESS_SHORT_SIDE:
        return None
    k = config.COMPRESS_SHORT_SIDE / short
    return max(2, round(w * k / 2) * 2), max(2, round(h * k / 2) * 2)


def build_reencode_cmd(src: str, dst: str, info: VideoInfo, *, compress: bool = False) -> list[str]:
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
        "-map", "0:v:0", "-map", "0:a:0?",
        "-c:v", "libx264", "-preset", config.REENCODE_PRESET, "-crf", str(config.REENCODE_CRF),
    ]
    size = compress_size(info) if compress else None
    if size:
        cmd += ["-vf", f"scale={size[0]}:{size[1]}:flags=lanczos"]
    cmd += [
        "-fps_mode", "cfr", "-r", target_fps(info),
        "-profile:v", "high", "-tag:v", "avc1",
    ]
    if info.hdr:
        cmd += ["-pix_fmt", "yuv420p10le"]
        for flag, val in (("-color_primaries", info.color_primaries),
                          ("-color_trc", info.color_transfer),
                          ("-colorspace", info.color_space)):
            if val:
                cmd += [flag, val]
    else:
        cmd += ["-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "copy" if info.audio_codec == "aac" else "aac"]
    if info.audio_codec != "aac":
        cmd += ["-b:a", "256k"]
    cmd += ["-map_metadata", "0", "-movflags", "+faststart", dst]
    return cmd


async def _run_ffmpeg(cmd: list[str], dst: str, timeout: Optional[int], what: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise pe.PatchError("ffmpeg is not installed") from exc
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout or config.REENCODE_TIMEOUT)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        _silent_remove(dst)
        raise pe.PatchError(f"{what} timed out") from exc
    except asyncio.CancelledError:
        proc.kill()
        _silent_remove(dst)
        raise
    if proc.returncode != 0 or not os.path.exists(dst) or os.path.getsize(dst) == 0:
        _silent_remove(dst)
        log.error("ffmpeg %s failed: %s", what, (err or b"").decode("utf-8", "replace")[-500:])
        raise pe.PatchError("PE_REENCODE_FAILED" if what == "re-encode" else "PE_REMUX_FAILED")
    return dst


async def reencode(src: str, info: VideoInfo, timeout: Optional[int] = None, *, compress: bool = False) -> str:
    dst = src + ".h264.mp4"
    return await _run_ffmpeg(build_reencode_cmd(src, dst, info, compress=compress), dst, timeout, "re-encode")


def build_remux_cmd(src: str, dst: str) -> list[str]:
    return ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
            "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-movflags", "+faststart", dst]


async def remux(src: str, timeout: Optional[int] = None) -> str:
    dst = src + ".remux.mp4"
    return await _run_ffmpeg(build_remux_cmd(src, dst), dst, timeout, "remux")


async def payload_hashes(path: str, timeout: int = 300) -> dict[str, str]:
    cmd = ["ffmpeg", "-hide_banner", "-v", "error", "-i", path, "-map", "0:v:0", "-map", "0:a:0?",
           "-c", "copy", "-f", "streamhash", "-hash", "sha256", "-"]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except FileNotFoundError as exc:
        raise pe.PatchError("ffmpeg is not installed") from exc
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise pe.PatchError("payload hashing timed out") from exc
    hashes: dict[str, str] = {}
    for line in (out or b"").decode("utf-8", "replace").splitlines():
        parts = line.strip().split(",", 2)
        if len(parts) == 3 and parts[2].upper().startswith("SHA256="):
            hashes[parts[1]] = parts[2].split("=", 1)[1].lower()
    if proc.returncode != 0 or "v" not in hashes:
        log.error("payload hash failed: %s", (err or b"").decode("utf-8", "replace")[-300:])
        raise pe.PatchError("PE_HASH_FAILED")
    return hashes


def _silent_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
