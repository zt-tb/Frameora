# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

import config
import timecode
import zeta
from i18n import t
from analyzer import (VideoInfo, _frac, needs_reencode, payload_hashes, probe, reencode, remux,
                      target_fps)
from patcher_errors import PatchError


@dataclass
class PatchResult:
    fps: int
    info: Optional[VideoInfo] = None
    after_info: Optional[VideoInfo] = None
    verified: bool = False
    media_intact: Optional[bool] = None
    method: str = zeta.LITE
    reencoded: bool = False
    reencode_reasons: list = field(default_factory=list)
    timecoded: Optional[timecode.TimecodeResult] = None
    zeta: Optional[zeta.ZetaResult] = None
    remuxed: bool = False
    remux_intact: Optional[bool] = None
    compressed: bool = False


def _check_fields(before: VideoInfo, after: VideoInfo, *, check_duration: bool = True) -> None:
    diffs = []
    if after.codec != before.codec:
        diffs.append(f"codec {before.codec}->{after.codec}")
    if check_duration and abs(after.duration - before.duration) > 0.05:
        diffs.append(f"duration {before.duration:.3f}->{after.duration:.3f}")
    if abs(after.r_fps - before.r_fps) > 0.5:
        diffs.append(f"fps {before.r_fps:.3f}->{after.r_fps:.3f}")
    if diffs:
        raise PatchError("PE_VERIFY_FIELDS", detail=", ".join(diffs))


StageCb = Callable[[str], Awaitable[None]]


async def _stage(cb: Optional[StageCb], name: str) -> None:
    if cb:
        try:
            await cb(name)
        except Exception:
            pass


def _zeta_and_verify(path: str, method: str):
    before = zeta.mdat_hash(path)
    res = zeta.zeta_mp4(path, method)
    return res, zeta.verify(path, before, res)


def _timecode_and_verify(path: str, fps: int):
    snap = timecode.snapshot(path, hash_outside=config.VERIFY_INTEGRITY)
    res = timecode.timecode_mp4(path, fps)
    return res, timecode.verify(path, snap, res)


def reencode_reasons(info: VideoInfo, compress: bool = False) -> list[str]:
    if compress:
        return [t("COMPRESS_REASON")]
    return needs_reencode(info) if config.SMART_REENCODE else []


def _starts_with_ftyp(path: str) -> bool:
    with open(path, "rb") as f:
        return f.read(8)[4:8] == b"ftyp"


async def _remux_to_mp4(path: str) -> Optional[bool]:
    verify = config.VERIFY_INTEGRITY
    before = await payload_hashes(path) if verify else None
    new_path = await remux(path)
    intact: Optional[bool] = None
    try:
        if verify:
            intact = (await payload_hashes(new_path)) == before
            if not intact:
                raise PatchError("PE_VERIFY_REMUX")
        os.replace(new_path, path)
    except BaseException:
        if os.path.exists(new_path):
            os.remove(new_path)
        raise
    return intact


async def process_video(path: str, info: Optional[VideoInfo] = None, *,
                        method: Optional[str] = None,
                        on_stage: Optional[StageCb] = None,
                        compress: bool = False) -> PatchResult:
    method = (method or config.PATCH_METHOD).upper()
    if method == "ZETA3":
        method = "TIMECODE"
    if method not in config.PATCH_METHODS:
        raise PatchError("PE_ZETA_UNSUPPORTED")
    info = info or await probe(path)

    reasons = reencode_reasons(info, compress)
    reencoded = remuxed = False
    remux_intact: Optional[bool] = None
    if reasons:
        await _stage(on_stage, "reencode")
        new_path = await reencode(path, info, compress=compress)
        os.replace(new_path, path)
        info = await probe(path)
        reencoded = True
    elif info.is_mov or not _starts_with_ftyp(path):
        await _stage(on_stage, "remux")
        remux_intact = await _remux_to_mp4(path)
        info = await probe(path)
        remuxed = True

    fps = round(_frac(target_fps(info)) if info.is_vfr else info.fps)
    await _stage(on_stage, "patch")
    loop = asyncio.get_running_loop()
    before = info

    if method in zeta.METHODS:
        res, reason = await loop.run_in_executor(None, _zeta_and_verify, path, method)
        if reason:
            raise PatchError("PE_VERIFY_FILE_REASON", reason=reason)
        after = await probe(path)
        _check_fields(before, after, check_duration=False)
        return PatchResult(fps=fps, info=info, after_info=after, verified=True,
                           media_intact=True if config.VERIFY_INTEGRITY else None, method=method,
                           reencoded=reencoded, reencode_reasons=reasons, zeta=res, remuxed=remuxed,
                           remux_intact=remux_intact, compressed=compress and reencoded)

    hashes_before = await payload_hashes(path) if config.VERIFY_INTEGRITY else None
    res, reason = await loop.run_in_executor(None, _timecode_and_verify, path, fps)
    if reason:
        raise PatchError("PE_VERIFY_FILE_REASON", reason=reason)
    media_ok: Optional[bool] = None
    if hashes_before is not None:
        media_ok = (await payload_hashes(path)) == hashes_before
        if not media_ok:
            raise PatchError("PE_VERIFY_FILE_MEDIA")
    after = await probe(path)
    _check_fields(before, after, check_duration=False)
    return PatchResult(fps=fps, info=info, after_info=after, verified=True, media_intact=media_ok, method="TIMECODE",
                       reencoded=reencoded, reencode_reasons=reasons, timecoded=res, remuxed=remuxed,
                       remux_intact=remux_intact, compressed=compress and reencoded)
