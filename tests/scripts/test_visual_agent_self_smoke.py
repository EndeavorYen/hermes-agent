from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_visual_agent_self_smoke_emits_strict_success(tmp_path, capsys):
    from scripts.visual_agent_self_smoke import main

    exit_code = main(["--work-dir", str(tmp_path), "--json"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["success"] is True
    assert payload["proof"]["success"] is True
    assert payload["proof"]["counts"]["artifact_kind_counts"] == {
        "image": 1,
        "video": 1,
    }
    assert payload["proof"]["counts"]["missing_request_source_metadata_count"] == 0
    assert payload["proof"]["counts"]["duplicate_artifact_delivery_count"] == 0
    assert payload["report"]["delivery"]["sent"] == 2
    assert payload["report"]["source_metadata"]["missing_request_source_metadata"] == 0
    assert payload["feedback"]["recorded"] is True
    assert payload["feedback"]["count"] == 2
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "raw_prompts" not in serialized
    assert "private prompt" not in serialized


def test_visual_agent_self_smoke_script_runs_by_file_path(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "visual_agent_self_smoke.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--work-dir",
            str(tmp_path),
            "--json",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["success"] is True
    assert payload["proof"]["success"] is True
