from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from agent.raphael.models import SKILL_TRACE_SCHEMA_VERSION, SkillTrace
from agent.raphael.skill_trace import (
    append_skill_trace,
    read_skill_traces,
    summarize_skill_usage,
)
from agent.raphael.state import get_raphael_skill_traces_path


def _hermes_home_env(path: Path):
    return patch.dict(os.environ, {"HERMES_HOME": str(path)})


def _trace(
    trace_id: str,
    *,
    skills_used: tuple[str, ...] = ("test-driven-development",),
    outcome: str = "success",
) -> SkillTrace:
    return SkillTrace(
        trace_id=trace_id,
        task_id="task-1",
        created_at=datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc),
        source="codex",
        skills_used=skills_used,
        tools_used=("exec_command",),
        outcome=outcome,
        metadata={"note": "x" * 20, "api_key": "sk-secret"},
    )


def test_skill_trace_path_uses_active_hermes_home(tmp_path):
    home = tmp_path / "hermes-home"

    with _hermes_home_env(home):
        assert get_raphael_skill_traces_path() == home / "raphael" / "skill_traces.jsonl"


def test_missing_skill_traces_return_empty_without_creating_directory(tmp_path):
    home = tmp_path / "hermes-home"

    with _hermes_home_env(home):
        traces = read_skill_traces()

    assert traces == []
    assert not (home / "raphael").exists()


def test_append_skill_trace_writes_redacted_jsonl_and_round_trips(tmp_path):
    home = tmp_path / "hermes-home"

    with _hermes_home_env(home):
        append_skill_trace(_trace("trace-1"), max_string_length=10)
        lines = get_raphael_skill_traces_path().read_text(encoding="utf-8").splitlines()
        traces = read_skill_traces()

    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["schema_version"] == SKILL_TRACE_SCHEMA_VERSION
    assert payload["metadata"] == {
        "note": "x" * 10 + "[truncated]",
        "api_key": "[redacted]",
    }
    assert traces[0].metadata == payload["metadata"]


def test_read_skill_traces_respects_zero_and_recent_limits(tmp_path):
    home = tmp_path / "hermes-home"

    with _hermes_home_env(home):
        append_skill_trace(_trace("trace-1"))
        append_skill_trace(_trace("trace-2"))
        assert read_skill_traces(limit=0) == []
        recent = read_skill_traces(limit=1)

    assert [trace.trace_id for trace in recent] == ["trace-2"]


def test_summarize_skill_usage_combines_usage_records_and_trace_outcomes(tmp_path):
    home = tmp_path / "hermes-home"
    skills_dir = home / "skills"
    skills_dir.mkdir(parents=True)
    usage_path = skills_dir / ".usage.json"
    usage_path.write_text(
        json.dumps(
            {
                "test-driven-development": {
                    "use_count": 2,
                    "view_count": 3,
                    "patch_count": 1,
                    "last_used_at": "2026-06-16T11:00:00+00:00",
                    "last_viewed_at": "2026-06-16T11:30:00+00:00",
                    "last_patched_at": "2026-06-16T10:00:00+00:00",
                    "state": "active",
                    "created_by": "user",
                }
            }
        ),
        encoding="utf-8",
    )

    with _hermes_home_env(home):
        append_skill_trace(
            _trace(
                "trace-1",
                skills_used=("test-driven-development", "verification-before-completion"),
                outcome="success",
            )
        )
        append_skill_trace(
            _trace(
                "trace-2",
                skills_used=("test-driven-development",),
                outcome="needs_review",
            )
        )
        before = usage_path.read_text(encoding="utf-8")
        summaries = summarize_skill_usage(max_rows=10, max_trace_events=500)
        after = usage_path.read_text(encoding="utf-8")

    assert after == before
    by_name = {summary.skill_name: summary for summary in summaries}
    assert set(by_name) == {
        "test-driven-development",
        "verification-before-completion",
    }
    assert by_name["test-driven-development"].use_count == 2
    assert by_name["test-driven-development"].view_count == 3
    assert by_name["test-driven-development"].patch_count == 1
    assert by_name["test-driven-development"].latest_activity_at == datetime(
        2026, 6, 16, 11, 30, tzinfo=timezone.utc
    )
    assert by_name["test-driven-development"].state == "active"
    assert by_name["test-driven-development"].created_by == "user"
    assert by_name["test-driven-development"].outcome_counts == {
        "success": 1,
        "needs_review": 1,
    }
    assert by_name["verification-before-completion"].outcome_counts == {"success": 1}
