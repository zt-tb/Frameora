# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import asyncio
import glob
import html
import importlib.util
import logging
import os
import random
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import config
from analyzer import VideoInfo, probe
from i18n import t
from patcher_errors import PatchError

log = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def extract_url(text: str) -> Optional[str]:
    m = _URL_RE.search(text or "")
    return m.group(0).rstrip(").,،") if m else None


def is_tiktok_url(url: str) -> bool:
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    return u.scheme in ("http", "https") and (host == "tiktok.com" or host.endswith(".tiktok.com"))


def _ref_path(uid: int) -> str:
    return os.path.join(config.REF_DIR, f"ref_{uid}.mp4")


def _ref_duration_path(uid: int) -> str:
    return os.path.join(config.REF_DIR, f"ref_{uid}.duration")


def get_reference_duration(uid: int) -> Optional[float]:
    try:
        with open(_ref_duration_path(uid), encoding="ascii") as f:
            value = float(f.read().strip())
        return value if value > 0 else None
    except (OSError, ValueError):
        return None


def _trim_reference(src: str, dst: str) -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", src,
             "-t", str(config.CHECK_MAX_SECONDS), "-map", "0:v:0", "-map", "0:a?",
             "-c", "copy", "-movflags", "+faststart", dst],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=max(30, config.CHECK_MAX_SECONDS * 3), check=False,
        )
        return result.returncode == 0 and os.path.isfile(dst) and os.path.getsize(dst) > 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def store_reference_sync(uid: int, src: str, source_duration: Optional[float] = None) -> bool:
    if not config.KEEP_REFERENCE:
        return False
    tmp = _ref_path(uid) + ".tmp.mp4"
    duration_tmp = _ref_duration_path(uid) + ".tmp"
    try:
        os.makedirs(config.REF_DIR, exist_ok=True)
        for stale in (tmp, duration_tmp):
            try:
                os.remove(stale)
            except FileNotFoundError:
                pass
        size_limit = config.CHECK_REF_MAX_MB * 1024 * 1024
        trimmed = _trim_reference(src, tmp)
        if trimmed and os.path.getsize(tmp) <= size_limit:
            pass
        else:
            try:
                os.remove(tmp)
            except OSError:
                pass
            if os.path.getsize(src) > size_limit:
                return False
            try:
                os.link(src, tmp)
            except OSError:
                shutil.copy2(src, tmp)
        os.replace(tmp, _ref_path(uid))
        if source_duration and source_duration > 0:
            with open(duration_tmp, "w", encoding="ascii") as f:
                f.write(f"{source_duration:.6f}\n")
            os.replace(duration_tmp, _ref_duration_path(uid))
        else:
            try:
                os.remove(_ref_duration_path(uid))
            except OSError:
                pass
        return True
    except OSError as exc:
        for path in (tmp, duration_tmp):
            try:
                os.remove(path)
            except OSError:
                pass
        log.warning("could not store reference for %s: %s", uid, exc)
        return False


async def store_reference(uid: int, src: str, source_duration: Optional[float] = None) -> bool:
    return await asyncio.to_thread(store_reference_sync, uid, src, source_duration)


def get_reference(uid: int) -> Optional[str]:
    p = _ref_path(uid)
    try:
        age = time.time() - os.path.getmtime(p)
    except OSError:
        return None
    if age > config.CHECK_REF_TTL_HOURS * 3600:
        for expired in (p, _ref_duration_path(uid)):
            try:
                os.remove(expired)
            except OSError:
                pass
        return None
    return p


def cleanup_references() -> int:
    removed = 0
    limit = time.time() - config.CHECK_REF_TTL_HOURS * 3600
    for p in glob.glob(os.path.join(config.REF_DIR, "ref_*")):
        try:
            if os.path.getmtime(p) < limit:
                os.remove(p)
                removed += 1
        except OSError:
            pass
    return removed


_CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
_UA_TARGET = "chrome-131"
_PRIMARY_TARGET = os.getenv("YTDLP_IMPERSONATE", _UA_TARGET).strip()
_FALLBACK_TARGET = "chrome"

_FATAL_MARKERS = ("private", "removed", "deleted", "under review", "no longer available")


def _curl_cffi_available() -> bool:
    return importlib.util.find_spec("curl_cffi") is not None


def _impersonate_names() -> list[Optional[str]]:
    if not _curl_cffi_available():
        log.warning("curl_cffi is not installed – TikTok requests are NOT impersonated and will likely 403. "
                    "Install it with: pip install 'yt-dlp[default,curl-cffi]'")
        return [None]
    names = [n for n in (_PRIMARY_TARGET, _FALLBACK_TARGET) if n]
    return list(dict.fromkeys(names))


def _build_headers(target: Optional[str]) -> dict[str, str]:
    headers = {
        "Referer": "https://www.tiktok.com/",
        "Accept-Language": "en-US,en;q=0.9",
    }
    if target in (None, _UA_TARGET):
        headers["User-Agent"] = _CHROME_UA
    return headers


def _build_opts(outdir: str, target: Optional[str], target_obj) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "outtmpl": os.path.join(outdir, "published.%(ext)s"),
        "format": "bv*+ba/b",
        "format_sort": ["res", "fps", "br"],
        "merge_output_format": "mp4",
        "max_filesize": config.CHECK_MAX_DOWNLOAD_MB * 1024 * 1024,
        "socket_timeout": 30,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 3,
        "file_access_retries": 3,
        "retry_sleep_functions": {
            "http": lambda n: min(2 ** n, 10),
            "fragment": lambda n: min(2 ** n, 10),
            "extractor": lambda n: min(2 ** n, 10),
        },
        "http_headers": _build_headers(target),
    }
    if target_obj is not None:
        opts["impersonate"] = target_obj
    if config.PROXY_URL:
        opts["proxy"] = config.PROXY_URL
    return opts


def _target_available(ydl, target_obj) -> bool:
    check = getattr(ydl, "_impersonate_target_available", None)
    if check is None:
        return True
    try:
        return bool(check(target_obj))
    except Exception:
        return True


def _is_fatal(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(m in msg for m in _FATAL_MARKERS)


def _clean_partials(outdir: str) -> None:
    for f in glob.glob(os.path.join(outdir, "published.*")):
        try:
            os.remove(f)
        except OSError:
            pass


def _download_sync(url: str, outdir: str) -> str:
    try:
        import yt_dlp
    except ImportError as exc:
        raise PatchError("yt-dlp is not installed") from exc
    try:
        from yt_dlp.networking.impersonate import ImpersonateTarget
    except ImportError:
        ImpersonateTarget = None

    names = _impersonate_names() if ImpersonateTarget is not None else [None]
    state = {"ran": 0, "exc": None, "done": False}

    def run(plan: list[Optional[str]]) -> Optional[str]:
        for name in plan:
            target_obj = None
            if name is not None:
                try:
                    target_obj = ImpersonateTarget.from_str(name)
                except Exception as exc:
                    log.warning("invalid impersonation target %r: %s", name, exc)
                    continue
            if state["ran"]:
                time.sleep(min(1.5 * 2 ** (state["ran"] - 1), 8) + random.random())
            _clean_partials(outdir)
            opts = _build_opts(outdir, name, target_obj)
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    if target_obj is not None and not _target_available(ydl, target_obj):
                        log.info("impersonation target %s unavailable in this yt-dlp build, skipping", name)
                        continue
                    state["ran"] += 1
                    ydl.download([url])
            except Exception as exc:
                state["exc"] = exc
                log.warning("yt-dlp attempt %d failed for %s (impersonate=%s): %s",
                            state["ran"], url, name, exc)
                if _is_fatal(exc):
                    state["done"] = True
                    return None
                continue
            files = [f for f in glob.glob(os.path.join(outdir, "published.*"))
                     if not f.endswith((".part", ".ytdl"))]
            if files:
                log.info("yt-dlp ok for %s (impersonate=%s)", url, name)
                return max(files, key=os.path.getsize)
            log.warning("yt-dlp finished without a file for %s (file too large?)", url)
            state["done"] = True
            return None
        return None

    path = run(list(names))
    if path is None and not state["ran"] and not state["done"]:
        log.warning("no usable impersonation target – falling back to a plain request")
        path = run([None])
    if path:
        return path

    exc = state["exc"]
    if exc is not None and _is_fatal(exc):
        raise PatchError("MSG_DL_PRIVATE") from exc
    raise PatchError("MSG_DL_BLOCKED") from exc


async def download_published(url: str, outdir: str) -> str:
    return await asyncio.to_thread(_download_sync, url, outdir)


_SSIM_RE = re.compile(r"SSIM .*?All:([0-9.]+)")
_VMAF_RE = re.compile(r"VMAF score:\s*([0-9.]+)")
_vmaf_available: Optional[bool] = None


def parse_ssim(stderr: str) -> Optional[float]:
    m = _SSIM_RE.findall(stderr or "")
    return float(m[-1]) if m else None


def parse_vmaf(stderr: str) -> Optional[float]:
    m = _VMAF_RE.findall(stderr or "")
    return float(m[-1]) if m else None


async def vmaf_available() -> bool:
    global _vmaf_available
    if _vmaf_available is None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-hide_banner", "-filters",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            _vmaf_available = b"libvmaf" in out
        except FileNotFoundError:
            _vmaf_available = False
    return _vmaf_available


def _even(n: int) -> int:
    return max(2, n - (n % 2))


def build_metric_cmd(published: str, reference: str, ref: VideoInfo, metric: str) -> list[str]:
    w, h = _even(ref.view_w), _even(ref.view_h)
    fps = ref.fps or 30
    prep = f"scale={w}:{h}:flags=bicubic,fps={fps:.3f},format=yuv420p,setpts=PTS-STARTPTS"
    flt = f"[0:v]{prep}[d];[1:v]{prep}[r];[d][r]" + ("libvmaf=n_threads=2" if metric == "vmaf" else "ssim")
    t = str(config.CHECK_MAX_SECONDS)
    return ["ffmpeg", "-hide_banner", "-nostats", "-t", t, "-i", published, "-t", t, "-i", reference,
            "-lavfi", flt, "-an", "-f", "null", "-"]


async def compute_metric(published: str, reference: str, ref: VideoInfo, metric: str,
                         timeout: int = 900) -> float:
    cmd = build_metric_cmd(published, reference, ref, metric)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
        )
    except FileNotFoundError as exc:
        raise PatchError("ffmpeg is not installed") from exc
    try:
        _, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.wait()
        raise PatchError("PE_COMPARE_TIMEOUT") from exc
    text = (err or b"").decode("utf-8", "replace")
    score = parse_vmaf(text) if metric == "vmaf" else parse_ssim(text)
    if proc.returncode != 0 or score is None:
        log.error("metric %s failed: %s", metric, text[-400:])
        raise PatchError("PE_COMPARE_FAILED")
    return score


@dataclass
class QualityReport:
    ref: VideoInfo
    pub: VideoInfo
    metric: str
    score: float
    seconds: int
    reference_duration: Optional[float] = None

    @property
    def similarity_pct(self) -> float:
        return self.score * 100 if self.metric == "ssim" else self.score

    @property
    def excellent(self) -> bool:
        return self.similarity_pct >= 95.0 or min(self.pub.view_w, self.pub.view_h) >= 1080

    @property
    def aggressive_compression(self) -> bool:
        ref_bitrate = self.ref.bitrate_kbps
        pub_bitrate = self.pub.bitrate_kbps
        return (self.ref.view_w, self.ref.view_h) != (self.pub.view_w, self.pub.view_h) or (
            ref_bitrate > 0 and 0 < pub_bitrate < ref_bitrate * 0.5
        )

    @property
    def verdict(self) -> str:
        pct = self.similarity_pct
        hi, mid = (97.0, 93.0) if self.metric == "ssim" else (93.0, 80.0)
        if pct >= hi:
            return t("Q_EXCELLENT")
        if pct >= mid:
            return t("Q_GOOD")
        return t("Q_POOR")


def _ltr(text: str) -> str:
    return f"\u200e{text}\u200e"


def _pct_diff(a: float, b: float) -> str:
    if not a or not b:
        return "—"
    d = (b - a) * 100 / a
    return _ltr(f"{d:+.0f}%")


def _mbps(kbps: int) -> str:
    return _ltr(f"{kbps / 1000:.1f} Mbps") if kbps > 0 else t("QR_UNKNOWN")


def _secs(v: float) -> str:
    return _ltr(f"{v:.1f}s") if v >= 1 else t("QR_UNKNOWN")


def duration_mismatch(ref: VideoInfo, pub: VideoInfo, reference_duration: Optional[float] = None) -> bool:
    ref_duration = reference_duration if reference_duration and reference_duration > 0 else ref.duration
    return ref_duration >= 1 and pub.duration >= 1 and abs(ref_duration - pub.duration) > max(2.0, ref_duration * 0.1)


def build_report(ref: VideoInfo, pub: VideoInfo, metric: str, score: float, seconds: int,
                 reference_duration: Optional[float] = None) -> QualityReport:
    return QualityReport(ref, pub, metric, score, seconds, reference_duration)


def format_report(r: QualityReport) -> str:
    rb, pb = r.ref.bitrate_kbps, r.pub.bitrate_kbps
    res_same = (r.ref.view_w, r.ref.view_h) == (r.pub.view_w, r.pub.view_h)
    fps_drop = r.pub.fps - r.ref.fps
    note = t("QR_AGGRESSIVE") if r.aggressive_compression else ""
    if duration_mismatch(r.ref, r.pub, r.reference_duration):
        note += "\n" + t("QR_DURATION_MISMATCH")
    return t(
        "QR", rb=_mbps(rb), pb=_mbps(pb), bdiff=_pct_diff(rb, pb),
        rres=_ltr(f"{r.ref.view_w}×{r.ref.view_h}"), pres=_ltr(f"{r.pub.view_w}×{r.pub.view_h}"),
        res_mark=" ✅" if res_same else " ⚠️",
        res_diff=t("QR_RES_SAME") if res_same else t("QR_RES_DROP"),
        rfps=_ltr(f"{r.ref.fps:.2f}"), pfps=_ltr(f"{r.pub.fps:.2f}"), fps_drop=_ltr(f"{fps_drop:+.2f}"),
        rdur=_secs(r.reference_duration or r.ref.duration), pdur=_secs(r.pub.duration),
        rcodec=html.escape(r.ref.codec.upper()), pcodec=html.escape(r.pub.codec.upper()),
        verdict=r.verdict, note=note, seconds=r.seconds,
    )


async def compare(reference: str, published: str, metric: Optional[str] = None,
                  reference_duration: Optional[float] = None) -> QualityReport:
    ref, pub = await probe(reference), await probe(published)
    metric = (metric or config.QUALITY_METRIC).lower()
    if metric == "auto":
        metric = "vmaf" if await vmaf_available() else "ssim"
    elif metric == "vmaf" and not await vmaf_available():
        metric = "ssim"
    pub_len = pub.duration if pub.duration >= 1 else config.CHECK_MAX_SECONDS
    original_duration = reference_duration or ref.duration
    span = int(min(config.CHECK_MAX_SECONDS, original_duration or config.CHECK_MAX_SECONDS, pub_len))
    score = await compute_metric(published, reference, ref, metric)
    return build_report(ref, pub, metric, score, max(1, span), reference_duration)
