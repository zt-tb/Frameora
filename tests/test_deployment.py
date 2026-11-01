# Copyright (c) 2026 Mohsen Al-Taie (@K0_MG). See LICENSE (attribution required).

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_entrypoint_just_runs_the_given_command():
    result = subprocess.run(["sh", str(ROOT / "docker-entrypoint.sh"), "printf", "APP_STARTED"],
                            text=True, capture_output=True, check=True)
    assert result.stdout == "APP_STARTED"


def test_railway_explicitly_uses_startup_wrapper_and_init():
    railway = json.loads((ROOT / "railway.json").read_text())
    assert railway["deploy"]["startCommand"] == "/usr/bin/tini -g -- /usr/local/bin/docker-entrypoint.sh python main.py"
    dockerfile = (ROOT / "Dockerfile").read_text()
    assert 'ENTRYPOINT ["/usr/bin/tini", "-g", "--", "/usr/local/bin/docker-entrypoint.sh"]' in dockerfile


def test_runtime_requirements_are_exactly_pinned_and_yt_dlp_has_reviewed_updates():
    requirements = [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    assert requirements
    assert all("==" in line and ">=" not in line for line in requirements)
    assert any(line.startswith("kurigram==") for line in requirements)
    assert any(line.startswith("yt-dlp[") and "==" in line for line in requirements)
    dependabot = (ROOT / ".github" / "dependabot.yml").read_text()
    assert 'interval: weekly' in dependabot and 'dependency-name: "yt-dlp"' in dependabot
