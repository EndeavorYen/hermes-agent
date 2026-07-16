from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_eighteen_shot_batch_benchmark_passes(tmp_path) -> None:
    repo = Path(__file__).resolve().parents[3]
    fixture = (
        repo
        / "tests"
        / "plugins"
        / "story_video"
        / "fixtures"
        / "batch_performance_18_shots.json"
    )
    report_path = tmp_path / "batch_performance_report.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "story_video_batch_benchmark.py"),
            "--fixture",
            str(fixture),
            "--output",
            str(report_path),
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["status"] == "PASS"
    assert report["image_generations"] == 22
    assert report["orchestration_api_calls"] <= 9
    assert report["session_rotations"] == 0
    assert report["max_parallelism"] == 3
