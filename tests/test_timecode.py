# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import asyncio
import os
import shutil
import struct

import pytest

import config
import patcher
import timecode
from helpers import audio_md5, frame_hashes, has_encoder, make_video
from patcher_errors import PatchError


def _leaves(path):
    return dict(timecode.snapshot(path, hash_outside=False).leaves)


def _patch(src, dst, fps=60):
    shutil.copy(src, dst)
    snap = timecode.snapshot(dst)
    res = timecode.timecode_mp4(dst, fps)
    assert timecode.verify(dst, snap, res) is None
    return snap, res


def _top(path):
    with open(path, "rb") as f:
        return timecode._scan_top(f, os.path.getsize(path))


def test_templates_match_observed_bytes():
    assert timecode._TKHD.hex() == (
        "0000005c746b6864000000030000000000000000000000030000000000000000"
        "0000000000000000000000000000000000010000000000000000000000000000"
        "00010000000000000000000000000000400000000000000000000000"
    )
    assert timecode._stsd(60).hex() == (
        "0000003273747364000000000000000100000022746d63640000000000000001"
        "000000000000000000015f90000005dc3c00"
    )
    assert timecode._stts(60).hex() == "0000001873747473000000000000000100000001000005dc"
    assert timecode._stsd(120)[-6:] == struct.pack(">IBB", 750, 120, 0)
    assert len(timecode.new_track(3, 60, 1000)) == 411


def test_only_listed_boxes_change_moov_last(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, audio=True)
    before = _leaves(src)
    out = str(tmp_path / "out.mp4")
    snap, res = _patch(src, out)
    after = _leaves(out)

    assert res.moov_growth == 443 and not res.moov_first and res.shift == 0
    changed = {p for p in before if before[p] != after.get(p)}
    assert changed == {"moov/mvhd[0]", "moov/trak[0]/tkhd[0]"}
    added = set(after) - set(before)
    assert "moov/trak[0]/tref[0]" in added
    assert all(p.startswith(("moov/trak[0]/tref", "moov/trak[2]")) for p in added)
    assert not any(p.startswith("moov/trak[1]") and before[p] != after[p] for p in before)


def test_mvhd_and_tkhd_edits(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, audio=True)
    before = _leaves(src)
    out = str(tmp_path / "out.mp4")
    _patch(src, out)
    after = _leaves(out)

    old, new = before["moov/mvhd[0]"], after["moov/mvhd[0]"]
    assert len(old) == 100 and len(new) == 112 and new[0] == 1
    assert struct.unpack_from(">Q", new, 24)[0] == timecode.OPEN_DURATION
    assert struct.unpack_from(">I", new, 108)[0] == struct.unpack_from(">I", old, 96)[0]

    old_t, new_t = before["moov/trak[0]/tkhd[0]"], after["moov/trak[0]/tkhd[0]"]
    diff = [i for i in range(len(old_t)) if old_t[i] != new_t[i]]
    assert diff == [35]
    assert struct.unpack_from(">h", new_t, 34)[0] == 1


def test_appended_structure_and_no_branding(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, audio=True)
    out = str(tmp_path / "out.mp4")
    _, res = _patch(src, out)
    top = _top(out)
    assert [t for t, _, _ in top][-2:] == [b"moov", b"mdat"]
    typ, pos, size = top[-1]
    assert size == 12 and pos == res.new_mdat_pos
    with open(out, "rb") as f:
        data = f.read()
    assert data[pos + 8:] == b"\x00\x00\x00\x00"
    assert top[-2][0] == b"moov" and b"free" not in [t for t, _, _ in top[-2:]]


def test_decoded_frames_and_audio_identical(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, audio=True)
    out = str(tmp_path / "out.mp4")
    _patch(src, out)
    assert frame_hashes(out) == frame_hashes(src)
    assert audio_md5(out) == audio_md5(src)


def test_moov_first_offsets_shift(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, audio=True, faststart=True)
    top = [t for t, _, _ in _top(src)]
    assert top.index(b"moov") < top.index(b"mdat")
    out = str(tmp_path / "out.mp4")
    snap, res = _patch(src, out)
    assert res.moov_first and res.shift == res.moov_growth > 0
    before, after = _leaves(src), _leaves(out)
    for path in before:
        if path.endswith("/stco[0]"):
            old = timecode.read_offsets(before[path], False)
            new = timecode.read_offsets(after[path], False)
            assert new == [o + res.shift for o in old]
    assert frame_hashes(out) == frame_hashes(src)
    assert audio_md5(out) == audio_md5(src)


def test_no_audio_file(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, audio=False)
    out = str(tmp_path / "out.mp4")
    _patch(src, out)
    assert frame_hashes(out) == frame_hashes(src)


@pytest.mark.skipif(not has_encoder("libx265"), reason="libx265 is not available")
def test_hevc_file(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, codec="libx265", audio=True)
    out = str(tmp_path / "out.mp4")
    _patch(src, out)
    assert frame_hashes(out) == frame_hashes(src)
    assert audio_md5(out) == audio_md5(src)


def test_120_fps_file(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=120, audio=True)
    out = str(tmp_path / "out.mp4")
    _patch(src, out, fps=120)
    assert frame_hashes(out) == frame_hashes(src)
    trak = _leaves(out)["moov/trak[2]/mdia[0]/minf[0]/stbl[0]/stsd[0]"]
    assert trak[-6:] == struct.pack(">IBB", 750, 120, 0)


def test_edts_is_untouched(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, audio=True, extra=("-bf", "2"))
    before = _leaves(src)
    edts = [p for p in before if "/edts[" in p]
    assert edts
    out = str(tmp_path / "out.mp4")
    _patch(src, out)
    after = _leaves(out)
    for p in edts:
        assert after[p] == before[p]
    for p in before:
        if p.endswith(("/mdhd[0]", "/stts[0]", "/stsz[0]", "/stsc[0]")):
            assert after[p] == before[p]


def test_second_run_is_refused(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, audio=True)
    out = str(tmp_path / "out.mp4")
    _patch(src, out)
    with pytest.raises(PatchError) as exc:
        timecode.timecode_mp4(out, 60)
    assert exc.value.key == "PE_TC_ALREADY"


def test_fragmented_file_is_refused(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, extra=("-movflags", "frag_keyframe+empty_moov"))
    with pytest.raises(PatchError) as exc:
        timecode.snapshot(src)
    assert exc.value.key == "PE_TC_UNSUPPORTED"


def test_verify_detects_tampering(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, audio=True)
    out = str(tmp_path / "out.mp4")
    snap, res = _patch(src, out)
    with open(out, "r+b") as f:
        f.seek(60)
        byte = f.read(1)
        f.seek(60)
        f.write(bytes([byte[0] ^ 0xFF]))
    assert timecode.verify(out, snap, res) is not None


def test_process_video_timecode_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VERIFY_INTEGRITY", True)
    src = make_video(tmp_path / "a.mp4", fps=60, audio=True)
    ref_frames, ref_audio = frame_hashes(src), audio_md5(src)
    result = asyncio.run(patcher.process_video(src, method="TIMECODE"))
    assert result.method == "TIMECODE" and result.verified and result.media_intact
    assert result.timecoded.track_id == 3
    assert frame_hashes(src) == ref_frames and audio_md5(src) == ref_audio


def test_process_video_timecode_from_mov(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VERIFY_INTEGRITY", True)
    src = make_video(tmp_path / "a.mov", fps=60, audio=True)
    ref_frames = frame_hashes(src)
    result = asyncio.run(patcher.process_video(src, method="TIMECODE"))
    assert result.remuxed and result.method == "TIMECODE" and result.verified
    assert frame_hashes(src) == ref_frames


def test_zeta_methods_are_the_only_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VERIFY_INTEGRITY", True)
    assert config.PATCH_METHODS == ("ZETA1", "ZETA2", "TIMECODE")
    for method in config.PATCH_METHODS:
        src = make_video(tmp_path / f"{method}.mp4", fps=60, audio=True)
        result = asyncio.run(patcher.process_video(src, method=method))
        assert result.method == method and result.verified
    with pytest.raises(PatchError):
        asyncio.run(patcher.process_video(make_video(tmp_path / "x.mp4"), method="GHOST"))


def test_non_observed_fps_uses_video_timescale(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=30, audio=True)
    out = str(tmp_path / "out.mp4")
    _, res = _patch(src, out, fps=30)
    assert res.timescale % 30 == 0 and res.timescale != timecode.TIMESCALE
    leaves = _leaves(out)
    stsd = leaves["moov/trak[2]/mdia[0]/minf[0]/stbl[0]/stsd[0]"]
    assert stsd[-6:] == struct.pack(">IBB", res.timescale // 30, 30, 0)
    mdhd = leaves["moov/trak[2]/mdia[0]/mdhd[0]"]
    assert struct.unpack_from(">I", mdhd, 12)[0] == res.timescale
    assert frame_hashes(out) == frame_hashes(src)


def test_60_and_120_keep_the_observed_clock(tmp_path):
    src = make_video(tmp_path / "a.mp4", fps=60, audio=True)
    _, res = _patch(src, str(tmp_path / "out.mp4"))
    assert res.timescale == timecode.TIMESCALE


def test_process_video_timecode_accepts_30_fps(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "VERIFY_INTEGRITY", True)
    src = make_video(tmp_path / "a.mp4", fps=30, audio=True)
    ref_frames, ref_audio = frame_hashes(src), audio_md5(src)
    result = asyncio.run(patcher.process_video(src, method="TIMECODE"))
    assert result.method == "TIMECODE" and result.verified and result.fps == 30
    assert frame_hashes(src) == ref_frames and audio_md5(src) == ref_audio
