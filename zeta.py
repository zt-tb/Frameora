# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from mp4box import (MAX_STCO, Box, _copy, _handler_type, _scan_top, _walk, pack_offsets,
                      parse_boxes, read_offsets, shift_offsets)
from patcher_errors import PatchError
from timecode import convert_mvhd

OPEN32 = 0xFFFFFFFF
OPEN64 = 0xFFFFFFFFFFFFFFFF
SIGNATURE = "FRAMEORA"
ENCODER_TAG = "Frameora"
TAG_WIDTH = 65

LITE = "ZETA1"
BEST = "ZETA2"
METHODS = (LITE, BEST)


@dataclass
class ZetaResult:
    method: str
    moov_growth: int
    shift: int
    tail_bytes: int


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), typ) + payload


PUBLIC_NAMES = {LITE: "SPARK", BEST: "BLAZE"}


def signature_box(method: str, when: Optional[datetime] = None, label: str = SIGNATURE) -> bytes:
    when = when or datetime.now(timezone.utc)
    stamp = when.strftime("%Y-%m-%dT%H:%M:%S.") + f"{when.microsecond // 1000:03d}Z"
    return _box(b"free", f"{label}/{PUBLIC_NAMES.get(method, method)} {stamp}".encode("utf-8"))


def encoder_udta(tag: str = ENCODER_TAG) -> bytes:
    text = tag.encode("utf-8").ljust(TAG_WIDTH, b"\x00")
    hdlr = _box(b"hdlr", b"\x00" * 8 + b"mdir" + b"\x00" * 13)
    data = _box(b"data", struct.pack(">II", 1, 0) + text)
    ilst = _box(b"ilst", _box(b"\xa9too", data))
    return _box(b"meta", b"\x00\x00\x00\x00" + hdlr + ilst)


def _open_duration(payload: bytes) -> bytes:
    if payload[0] == 0:
        return payload[:16] + struct.pack(">I", OPEN32) + payload[20:]
    if payload[0] == 1:
        return payload[:24] + struct.pack(">Q", OPEN64) + payload[32:]
    raise PatchError("PE_ZETA_UNSUPPORTED")


def _best_mvhd(payload: bytes) -> bytes:
    if payload[0] == 0:
        return convert_mvhd(payload)[0]
    return _open_duration(payload)


def _read_layout(path: str):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        top = _scan_top(f, size)
        if not top or top[0][0] != b"ftyp":
            raise PatchError("PE_ZETA_UNSUPPORTED")
        moovs = [(p, s) for t, p, s in top if t == b"moov"]
        mdats = [(p, s) for t, p, s in top if t == b"mdat"]
        if len(moovs) != 1 or not mdats or any(t in (b"moof", b"sidx") for t, _, _ in top):
            raise PatchError("PE_ZETA_UNSUPPORTED")
        f.seek(moovs[0][0])
        raw = f.read(moovs[0][1])
    return moovs[0], mdats, raw, size


def _video_trak(moov: Box) -> Box:
    traks = [c for c in moov.children if c.type == b"trak"]
    for trak in traks:
        mdia = trak.find(b"mdia")
        if mdia is not None and _handler_type(mdia) == b"vide":
            return trak
    raise PatchError("PE_ZETA_UNSUPPORTED")


def _shift_chunks(moov: Box, mdat_lo: int, mdat_hi: int, boundary: int, delta: int) -> None:
    for box in list(_walk(moov.children)):
        if box.type not in (b"stco", b"co64"):
            continue
        is64 = box.type == b"co64"
        ver_flags = struct.unpack_from(">I", box.payload, 0)[0]
        offs = read_offsets(box.payload, is64)
        if any(not mdat_lo <= o <= mdat_hi for o in offs):
            raise PatchError("PE_ZETA_UNSUPPORTED")
        offs = shift_offsets(offs, boundary, delta)
        if not is64 and offs and max(offs) > MAX_STCO:
            raise PatchError("PE_ZETA_UNSUPPORTED")
        box.payload = pack_offsets(offs, is64, ver_flags)


def _build_moov(raw: bytes, method: str, tag: str, shift: int, mdat: tuple[int, int],
                boundary: int) -> bytes:
    moov = parse_boxes(raw)[0]
    if moov.type != b"moov" or moov.find(b"mvex") is not None:
        raise PatchError("PE_ZETA_UNSUPPORTED")
    mvhd = moov.find(b"mvhd")
    if mvhd is None or not mvhd.payload:
        raise PatchError("PE_ZETA_UNSUPPORTED")
    if method == LITE:
        mvhd.payload = _open_duration(mvhd.payload)
    else:
        mvhd.payload = _best_mvhd(mvhd.payload)
        moov.children = [c for c in moov.children if c.type != b"udta"]
        trak = _video_trak(moov)
        trak.children = [c for c in trak.children if c.type != b"udta"]
        trak.children.append(Box(b"udta", encoder_udta(tag)))
    if shift:
        _shift_chunks(moov, mdat[0], mdat[0] + mdat[1], boundary, shift)
    return moov.serialize()


def zeta_mp4(path: str, method: str, *, tag: str = ENCODER_TAG, label: str = SIGNATURE,
             when: Optional[datetime] = None) -> ZetaResult:
    method = method.upper()
    if method not in METHODS:
        raise PatchError("PE_ZETA_UNSUPPORTED")
    (moov_pos, moov_size), mdats, raw, file_size = _read_layout(path)
    moov_end = moov_pos + moov_size
    mdat = (min(p for p, _ in mdats), max(p + s for p, s in mdats) - min(p for p, _ in mdats))
    moov_first = moov_pos < mdat[0]

    blob = _build_moov(raw, method, tag, 0, mdat, moov_end)
    growth = len(blob) - moov_size
    shift = growth if moov_first else 0
    if shift:
        blob = _build_moov(raw, method, tag, shift, mdat, moov_end)
        if len(blob) - moov_size != growth:
            raise PatchError("PE_ZETA_UNSUPPORTED")
    tail = signature_box(method, when, label)

    tmp = path + ".zeta.tmp"
    try:
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            _copy(src, dst, 0, moov_pos)
            dst.write(blob)
            _copy(src, dst, moov_end, file_size)
            dst.write(tail)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return ZetaResult(method=method, moov_growth=growth, shift=shift, tail_bytes=len(tail))


def mdat_hash(path: str) -> str:
    import hashlib

    h = hashlib.sha256()
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        for typ, pos, sz in _scan_top(f, size):
            if typ != b"mdat":
                continue
            f.seek(pos)
            left = sz
            while left > 0:
                chunk = f.read(min(8 * 1024 * 1024, left))
                if not chunk:
                    break
                h.update(chunk)
                left -= len(chunk)
    return h.hexdigest()


def verify(path: str, before_mdat: str, res: ZetaResult) -> Optional[str]:
    if mdat_hash(path) != before_mdat:
        return "media payload changed"
    (moov_pos, moov_size), mdats, raw, size = _read_layout(path)
    moov = parse_boxes(raw)[0]
    mvhd = moov.find(b"mvhd")
    want = OPEN32 if (res.method == LITE and mvhd.payload[0] == 0) else OPEN64
    got = (struct.unpack_from(">I", mvhd.payload, 16)[0] if mvhd.payload[0] == 0
           else struct.unpack_from(">Q", mvhd.payload, 24)[0])
    if got != want:
        return "mvhd duration was not updated"
    lo = min(p for p, _ in mdats)
    hi = max(p + s for p, s in mdats)
    for box in _walk(moov.children):
        if box.type in (b"stco", b"co64"):
            offs = read_offsets(box.payload, box.type == b"co64")
            if any(not lo <= o <= hi for o in offs):
                return "chunk offsets point outside the media data"
    with open(path, "rb") as f:
        last = _scan_top(f, size)[-1]
    if last[0] != b"free" or last[2] != res.tail_bytes:
        return "signature box is missing"
    return None
