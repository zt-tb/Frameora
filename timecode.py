# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import hashlib
import os
import struct
from dataclasses import dataclass
from typing import Optional

from mp4box import (MAX_STCO, Box, _copy, _handler_type, _scan_top, _walk, pack_offsets,
                      parse_boxes, read_offsets, shift_offsets)
from patcher_errors import PatchError

TIMESCALE = 90000
OPEN_DURATION = 0xFFFFFFFFFFFFFFFF
NEW_MDAT = struct.pack(">I4s", 12, b"mdat") + b"\x00\x00\x00\x00"

_TKHD = bytes.fromhex(
    "0000005c746b6864000000030000000000000000000000030000000000000000"
    "0000000000000000000000000000000000010000000000000000000000000000"
    "00010000000000000000000000000000400000000000000000000000"
)
_MDHD = bytes.fromhex("000000206d64686400000000000000000000000000015f900000000055c40000")
_HDLR = bytes.fromhex("0000002168646c720000000000000000746d636400000000000000000000000000")
_GMHD = bytes.fromhex("00000028676d686400000018676d696e000000000000000000000000000000000000000874657874")
_DINF = bytes.fromhex("00000024" "64696e66" "0000001c" "64726566" "00000000" "00000001"
                      "0000000c" "75726c20" "00000001")
_STSC = bytes.fromhex("0000001c737473630000000000000001000000010000000100000001")
_STSZ = bytes.fromhex("000000187374737a00000000000000040000000100000004")


def _box(typ: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), typ) + payload


OBSERVED_FPS = (60, 120)


def pick_timescale(fps: int, video_timescale: int = 0) -> int:
    if fps not in OBSERVED_FPS and video_timescale > 0 and 0 < fps <= 255 and video_timescale % fps == 0:
        return video_timescale
    return TIMESCALE


def frame_timing(fps: int, timescale: int = TIMESCALE) -> tuple[int, int]:
    if fps <= 0 or fps > 255 or timescale % fps:
        raise PatchError("PE_TC_UNSUPPORTED")
    return timescale // fps, fps


def _stsd(fps: int, timescale: int = TIMESCALE) -> bytes:
    frame_duration, frames = frame_timing(fps, timescale)
    entry = _box(b"tmcd", b"\x00" * 6 + struct.pack(">H", 1)
                 + struct.pack(">IIIIBB", 0, 0, timescale, frame_duration, frames, 0))
    return _box(b"stsd", struct.pack(">II", 0, 1) + entry)


def _stts(fps: int, timescale: int = TIMESCALE) -> bytes:
    return _box(b"stts", struct.pack(">IIII", 0, 1, 1, frame_timing(fps, timescale)[0]))


def new_track(track_id: int, fps: int, data_offset: int, timescale: int = TIMESCALE) -> bytes:
    if data_offset > MAX_STCO:
        raise PatchError("PE_TC_UNSUPPORTED")
    tkhd = _TKHD[:20] + struct.pack(">I", track_id) + _TKHD[24:]
    stco = _box(b"stco", struct.pack(">III", 0, 1, data_offset))
    stbl = _box(b"stbl", _stsd(fps, timescale) + _stts(fps, timescale) + _STSC + _STSZ + stco)
    minf = _box(b"minf", _GMHD + _DINF + stbl)
    mdhd = _MDHD[:20] + struct.pack(">I", timescale) + _MDHD[24:]
    return _box(b"trak", tkhd + _box(b"mdia", mdhd + _HDLR + minf))


def convert_mvhd(payload: bytes) -> tuple[bytes, int]:
    if len(payload) != 100 or payload[0] != 0:
        raise PatchError("PE_TC_UNSUPPORTED")
    created, modified, timescale, _ = struct.unpack_from(">IIII", payload, 4)
    next_id = struct.unpack_from(">I", payload, 96)[0]
    head = b"\x01\x00\x00\x00" + struct.pack(">QQIQ", created, modified, timescale, OPEN_DURATION)
    return head + payload[20:], next_id


def _alt_group_offset(payload: bytes) -> int:
    off = {0: 34, 1: 46}.get(payload[0] if payload else -1)
    if off is None or len(payload) < off + 2:
        raise PatchError("PE_TC_UNSUPPORTED")
    return off


def patch_tkhd(payload: bytes) -> bytes:
    off = _alt_group_offset(payload)
    return payload[:off] + struct.pack(">h", 1) + payload[off + 2:]


def _track_timescale(trak: Box) -> int:
    mdia = trak.find(b"mdia")
    mdhd = mdia.find(b"mdhd") if mdia is not None else None
    if mdhd is None or not mdhd.payload:
        return 0
    off = {0: 12, 1: 20}.get(mdhd.payload[0])
    if off is None or len(mdhd.payload) < off + 4:
        return 0
    return struct.unpack_from(">I", mdhd.payload, off)[0]


def _tref(track_id: int) -> bytes:
    return _box(b"tref", _box(b"tmcd", struct.pack(">I", track_id)))


@dataclass
class TimecodeResult:
    track_id: int
    fps: int
    moov_growth: int
    moov_first: bool
    shift: int
    boundary: int
    promoted_co64: bool
    new_mdat_pos: int
    timescale: int = TIMESCALE


@dataclass
class Snapshot:
    leaves: list
    video_index: int
    track_count: int
    next_track_id: int
    outside_hash: Optional[str]


def _flatten(boxes: list[Box], prefix: str, out: list) -> None:
    seen: dict[bytes, int] = {}
    for b in boxes:
        idx = seen.get(b.type, 0)
        seen[b.type] = idx + 1
        _flatten_box(b, f"{prefix}/{b.type.decode('latin1')}[{idx}]", out)


def _flatten_box(box: Box, path: str, out: list) -> None:
    if box.children is not None:
        _flatten(box.children, path, out)
    else:
        out.append((path, box.payload))


def _normalize(path: str, payload: bytes):
    if path.endswith("/co64[0]") or path.endswith("/stco[0]"):
        is64 = path.endswith("/co64[0]")
        return path.replace("co64[0]", "stco[0]"), tuple(read_offsets(payload, is64))
    return path, payload


def _read_layout(path: str):
    file_size = os.path.getsize(path)
    with open(path, "rb") as f:
        top = _scan_top(f, file_size)
        if not top or top[0][0] != b"ftyp":
            raise PatchError("PE_TC_UNSUPPORTED")
        moovs = [(p, s) for t, p, s in top if t == b"moov"]
        mdats = [(p, s) for t, p, s in top if t == b"mdat"]
        if len(moovs) != 1 or not mdats or any(t == b"moof" for t, _, _ in top):
            raise PatchError("PE_TC_UNSUPPORTED")
        f.seek(moovs[0][0])
        raw = f.read(moovs[0][1])
    return top, moovs[0], mdats, raw, file_size


def _video_index(moov: Box) -> int:
    traks = [c for c in moov.children if c.type == b"trak"]
    for i, trak in enumerate(traks):
        mdia = trak.find(b"mdia")
        if mdia is not None and _handler_type(mdia) == b"vide":
            return i
    raise PatchError("PE_TC_UNSUPPORTED")


def _outside_hash(path: str, drop_last: bool) -> str:
    file_size = os.path.getsize(path)
    h = hashlib.sha256()
    with open(path, "rb") as f:
        top = [e for e in _scan_top(f, file_size) if e[0] != b"moov"]
        if drop_last:
            top = top[:-1]
        for typ, pos, size in top:
            h.update(typ)
            f.seek(pos)
            left = size
            while left > 0:
                chunk = f.read(min(8 * 1024 * 1024, left))
                if not chunk:
                    break
                h.update(chunk)
                left -= len(chunk)
    return h.hexdigest()


def snapshot(path: str, hash_outside: bool = True) -> Snapshot:
    _, _, _, raw, _ = _read_layout(path)
    moov = parse_boxes(raw)[0]
    leaves: list = []
    _flatten_box(moov, "moov", leaves)
    mvhd = moov.find(b"mvhd")
    next_id = struct.unpack_from(">I", mvhd.payload, 96)[0] if mvhd and len(mvhd.payload) == 100 else 0
    return Snapshot(
        leaves=leaves,
        video_index=_video_index(moov),
        track_count=sum(1 for c in moov.children if c.type == b"trak"),
        next_track_id=next_id,
        outside_hash=_outside_hash(path, drop_last=False) if hash_outside else None,
    )


def timecode_mp4(path: str, fps: int) -> TimecodeResult:
    _, (moov_pos, moov_size), mdats, moov_raw, file_size = _read_layout(path)
    moov_end = moov_pos + moov_size

    probe = parse_boxes(moov_raw)[0]
    if probe.type != b"moov" or probe.find(b"mvex") is not None:
        raise PatchError("PE_TC_UNSUPPORTED")
    traks = [c for c in probe.children if c.type == b"trak"]
    for trak in traks:
        mdia = trak.find(b"mdia")
        if mdia is not None and _handler_type(mdia) == b"tmcd":
            raise PatchError("PE_TC_ALREADY")
    if len(mdats) != 1:
        raise PatchError("PE_TC_UNSUPPORTED")
    mdat_pos, mdat_size = mdats[0]
    moov_first = moov_pos < mdat_pos
    video = traks[_video_index(probe)]
    if video.find(b"tref") is not None or video.find(b"tkhd") is None:
        raise PatchError("PE_TC_UNSUPPORTED")
    timescale = pick_timescale(fps, _track_timescale(video))
    frame_timing(fps, timescale)
    mvhd = probe.find(b"mvhd")
    if mvhd is None:
        raise PatchError("PE_TC_UNSUPPORTED")
    new_mvhd, new_id = convert_mvhd(mvhd.payload)
    for trak in traks:
        tkhd = trak.find(b"tkhd")
        if tkhd is not None and len(tkhd.payload) >= 16 and struct.unpack_from(
                ">I", tkhd.payload, 12 if tkhd.payload[0] == 0 else 20)[0] == new_id:
            raise PatchError("PE_TC_UNSUPPORTED")

    def build(promote: bool, growth: int):
        moov = parse_boxes(moov_raw)[0]
        moov.set_child(b"mvhd", new_mvhd)
        vtrak = [c for c in moov.children if c.type == b"trak"][_video_index(moov)]
        vtrak.set_child(b"tkhd", patch_tkhd(vtrak.find(b"tkhd").payload))
        vtrak.children.append(Box(b"tref", _tref(new_id)[8:]))
        shift = growth if mdat_pos > moov_pos else 0
        for box in list(_walk(moov.children)):
            if box.type not in (b"stco", b"co64"):
                continue
            is64 = box.type == b"co64"
            ver_flags = struct.unpack_from(">I", box.payload, 0)[0]
            offs = read_offsets(box.payload, is64)
            if any(not mdat_pos <= o <= mdat_pos + mdat_size for o in offs):
                raise PatchError("PE_TC_UNSUPPORTED")
            offs = shift_offsets(offs, moov_end, shift)
            if promote and not is64:
                box.type, is64 = b"co64", True
            if not is64 and offs and max(offs) > MAX_STCO:
                return None
            box.payload = pack_offsets(offs, is64, ver_flags)
        new_mdat_pos = file_size + growth
        moov.children.append(parse_boxes(new_track(new_id, fps, new_mdat_pos + 8, timescale))[0])
        return moov.serialize(), shift, new_mdat_pos

    promote, growth, built = False, 0, None
    for _ in range(6):
        built = build(promote, growth)
        if built is None:
            if promote:
                raise PatchError("PE_TC_UNSUPPORTED")
            promote = True
            continue
        if len(built[0]) - moov_size == growth:
            break
        growth = len(built[0]) - moov_size
    else:
        raise PatchError("PE_TC_UNSUPPORTED")
    blob, shift, new_mdat_pos = built

    tmp = path + ".tc.tmp"
    try:
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            _copy(src, dst, 0, moov_pos)
            dst.write(blob)
            _copy(src, dst, moov_end, file_size)
            dst.write(NEW_MDAT)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)

    return TimecodeResult(track_id=new_id, fps=fps, moov_growth=growth, moov_first=moov_first, shift=shift,
                          boundary=moov_end, promoted_co64=promote, new_mdat_pos=new_mdat_pos,
                          timescale=timescale)


def _expected_leaves(before: Snapshot, res: TimecodeResult) -> list:
    vprefix = f"moov/trak[{before.video_index}]/"
    out: list = []
    last_video = -1
    for path, payload in before.leaves:
        if path == "moov/mvhd[0]":
            payload = convert_mvhd(payload)[0]
        elif path == vprefix + "tkhd[0]":
            payload = patch_tkhd(payload)
        elif path.endswith("/stco[0]") or path.endswith("/co64[0]"):
            offs = shift_offsets(read_offsets(payload, path.endswith("/co64[0]")), res.boundary, res.shift)
            out.append((path.replace("co64[0]", "stco[0]"), tuple(offs)))
            if path.startswith(vprefix):
                last_video = len(out) - 1
            continue
        out.append(_normalize(path, payload))
        if path.startswith(vprefix):
            last_video = len(out) - 1
    out.insert(last_video + 1, (vprefix + "tref[0]", _box(b"tmcd", struct.pack(">I", res.track_id))))
    tail: list = []
    trak = parse_boxes(new_track(res.track_id, res.fps, res.new_mdat_pos + 8, res.timescale))[0]
    _flatten_box(trak, f"moov/trak[{before.track_count}]", tail)
    return out + [_normalize(p, b) for p, b in tail]


def verify(path: str, before: Snapshot, res: TimecodeResult) -> Optional[str]:
    after = snapshot(path, hash_outside=False)
    if _expected_leaves(before, res) != [_normalize(p, b) for p, b in after.leaves]:
        return "unexpected change inside moov"
    file_size = os.path.getsize(path)
    with open(path, "rb") as f:
        top = _scan_top(f, file_size)
        typ, pos, size = top[-1]
        f.seek(pos)
        if typ != b"mdat" or size != len(NEW_MDAT) or f.read(size) != NEW_MDAT or pos != res.new_mdat_pos:
            return "appended mdat is wrong"
    if before.outside_hash is not None and _outside_hash(path, drop_last=True) != before.outside_hash:
        return "data outside moov changed"
    return None
