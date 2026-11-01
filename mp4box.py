# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

from __future__ import annotations

import struct
from typing import Optional

from patcher_errors import PatchError

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}

MAX_STCO = 0xFFFFFFFF


class Box:
    __slots__ = ("type", "payload", "children")

    def __init__(self, typ: bytes, payload: bytes = b"", children: Optional[list] = None):
        self.type = typ
        self.payload = payload
        self.children = children

    def find(self, typ: bytes) -> Optional["Box"]:
        for c in self.children or []:
            if c.type == typ:
                return c
        return None

    def set_child(self, typ: bytes, payload: bytes) -> None:
        for c in self.children or []:
            if c.type == typ:
                c.payload = payload
                return
        raise KeyError(typ)

    def serialize(self) -> bytes:
        body = b"".join(c.serialize() for c in self.children) if self.children is not None else self.payload
        size = 8 + len(body)
        if size > 0xFFFFFFFF:
            raise PatchError("MP4: box too large")
        return struct.pack(">I4s", size, self.type) + body


def parse_boxes(buf: bytes, start: int = 0, end: Optional[int] = None) -> list[Box]:
    end = len(buf) if end is None else end
    out: list[Box] = []
    pos = start
    while pos + 8 <= end:
        size, typ = struct.unpack_from(">I4s", buf, pos)
        hdr = 8
        if size == 1:
            if pos + 16 > end:
                raise PatchError("MP4: truncated box")
            size = struct.unpack_from(">Q", buf, pos + 8)[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            raise PatchError("MP4: corrupt box size")
        body_s, body_e = pos + hdr, pos + size
        if typ in CONTAINERS:
            out.append(Box(typ, children=parse_boxes(buf, body_s, body_e)))
        else:
            out.append(Box(typ, bytes(buf[body_s:body_e])))
        pos += size
    return out


def _walk(boxes: list[Box]):
    for b in boxes:
        yield b
        if b.children is not None:
            yield from _walk(b.children)


def _handler_type(mdia: Box) -> bytes:
    hdlr = mdia.find(b"hdlr")
    return hdlr.payload[8:12] if hdlr and len(hdlr.payload) >= 12 else b""


def read_offsets(payload: bytes, is64: bool) -> list[int]:
    n = struct.unpack_from(">I", payload, 4)[0]
    fmt = ">%d%s" % (n, "Q" if is64 else "I")
    return list(struct.unpack_from(fmt, payload, 8))


def pack_offsets(offsets: list[int], is64: bool, ver_flags: int = 0) -> bytes:
    fmt = ">II%d%s" % (len(offsets), "Q" if is64 else "I")
    return struct.pack(fmt, ver_flags, len(offsets), *offsets)


def shift_offsets(offsets: list[int], boundary: int, delta: int) -> list[int]:
    return [o + delta if o >= boundary else o for o in offsets]


def _scan_top(f, file_size: int) -> list[tuple[bytes, int, int]]:
    out, pos = [], 0
    while pos + 8 <= file_size:
        f.seek(pos)
        hdr = f.read(16)
        if len(hdr) < 8:
            break
        size, typ = struct.unpack_from(">I4s", hdr, 0)
        if size == 1 and len(hdr) >= 16:
            size = struct.unpack_from(">Q", hdr, 8)[0]
        elif size == 0:
            size = file_size - pos
        if size < 8:
            break
        out.append((typ, pos, min(size, file_size - pos)))
        pos += size
    return out


def _copy(src, dst, start: int, end: int, bufsize: int = 8 * 1024 * 1024) -> None:
    src.seek(start)
    left = end - start
    while left > 0:
        chunk = src.read(min(bufsize, left))
        if not chunk:
            raise PatchError("MP4: unexpected end of file")
        dst.write(chunk)
        left -= len(chunk)
