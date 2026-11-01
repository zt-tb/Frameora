# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import pytest

import patcher
from analyzer import VideoInfo
from patcher_errors import PatchError


def _info(duration):
    return VideoInfo(duration=duration, codec="h264", r_fps=60, avg_fps=60)


def test_strict_check_still_catches_duration_change():
    with pytest.raises(PatchError):
        patcher._check_fields(_info(30.934), _info(0.001))


def test_zeta_mode_ignores_unknown_duration_but_not_codec():
    patcher._check_fields(_info(30.934), _info(0.001), check_duration=False)
    after = _info(0.001)
    after.codec = "hevc"
    with pytest.raises(PatchError):
        patcher._check_fields(_info(30.934), after, check_duration=False)
