# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import analyzer
from analyzer import VideoInfo


def _info(**kw):
    base = dict(codec="h264", width=1080, height=1920, avg_fps=60.0, r_fps=60.0, bitrate_kbps=20000,
                duration=10, has_audio=True, audio_codec="aac")
    base.update(kw)
    return VideoInfo(**base)


def _text(info):
    return "\n".join(analyzer.advise(info))


def test_av1_and_vp9_tips():
    assert "AV1" in _text(_info(codec="av1"))
    assert "VP9" in _text(_info(codec="vp9"))
    assert "HEVC" in _text(_info(codec="hevc"))
    assert "AV1" not in _text(_info())


def test_audio_hints_only_from_music_metadata():
    assert analyzer.audio_hints(_info()) == []
    tagged = _info(audio_tags={"artist": "X", "isrc": "US123", "title": "song"})
    assert set(analyzer.audio_hints(tagged)) == {"اسم فنان", "ISRC"}
    assert "🎵" in _text(tagged)
    assert "🎵" not in _text(_info(audio_tags={"encoder": "Lavf"}))
    assert analyzer.audio_hints(_info(has_audio=False, audio_tags={"artist": "X"})) == []


def test_inflated_file_is_recognised():
    inflated = _info(avg_fps=600.0, r_fps=60.0)
    assert inflated.looks_inflated and not inflated.is_vfr and inflated.fps == 60.0
    assert "يبدو معدّل" in _text(inflated)
