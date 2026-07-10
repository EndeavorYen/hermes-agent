from datetime import datetime, timezone

import pytest

from agent.raphael import SkillTrace, SkillTraceSummary
from agent.raphael.models import SKILL_TRACE_SCHEMA_VERSION


def test_skill_trace_round_trips_with_schema_version_and_normalized_values():
    created_at = datetime(2026, 6, 16, 11, 30)
    trace = SkillTrace(
        trace_id="trace-1",
        task_id="task-1",
        created_at=created_at,
        source="codex",
        skills_used=["test-driven-development", "verification-before-completion"],
        tools_used=["exec_command"],
        outcome="success",
        user_corrections=["keep phase 2 separate"],
        risk_incidents=["attempted-skill-write"],
        metadata={"path": "docs/superpowers/plans/phase-2.md"},
    )

    payload = trace.to_dict()

    assert trace.created_at.tzinfo == timezone.utc
    assert trace.skills_used == (
        "test-driven-development",
        "verification-before-completion",
    )
    assert trace.tools_used == ("exec_command",)
    assert payload == {
        "schema_version": SKILL_TRACE_SCHEMA_VERSION,
        "trace_id": "trace-1",
        "task_id": "task-1",
        "created_at": "2026-06-16T11:30:00+00:00",
        "source": "codex",
        "skills_used": [
            "test-driven-development",
            "verification-before-completion",
        ],
        "tools_used": ["exec_command"],
        "outcome": "success",
        "user_corrections": ["keep phase 2 separate"],
        "risk_incidents": ["attempted-skill-write"],
        "metadata": {"path": "docs/superpowers/plans/phase-2.md"},
    }
    assert SkillTrace.from_dict(payload) == trace


@pytest.mark.parametrize("schema_version", [None, "raphael.skill_trace.v2"])
def test_skill_trace_rejects_missing_or_wrong_schema_version(schema_version):
    payload = {
        "trace_id": "trace-1",
        "task_id": "task-1",
        "created_at": "2026-06-16T11:30:00+00:00",
        "source": "codex",
        "skills_used": [],
        "tools_used": [],
        "outcome": "success",
    }
    if schema_version is not None:
        payload["schema_version"] = schema_version

    with pytest.raises(ValueError, match="Unsupported Raphael skill trace schema"):
        SkillTrace.from_dict(payload)


def test_skill_trace_summary_round_trips_usage_and_outcomes():
    summary = SkillTraceSummary(
        skill_name="test-driven-development",
        use_count=4,
        view_count=2,
        patch_count=1,
        latest_activity_at=datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc),
        state="active",
        created_by="user",
        outcome_counts={"success": 3, "needs_review": 1},
    )

    payload = summary.to_dict()

    assert payload == {
        "skill_name": "test-driven-development",
        "use_count": 4,
        "view_count": 2,
        "patch_count": 1,
        "latest_activity_at": "2026-06-16T12:00:00+00:00",
        "state": "active",
        "created_by": "user",
        "outcome_counts": {"success": 3, "needs_review": 1},
    }
    assert SkillTraceSummary.from_dict(payload) == summary


def test_skill_trace_summary_allows_missing_latest_activity():
    summary = SkillTraceSummary(
        skill_name="verification-before-completion",
        use_count=0,
        view_count=0,
        patch_count=0,
        latest_activity_at=None,
        state=None,
        created_by=None,
        outcome_counts={},
    )

    assert summary.to_dict()["latest_activity_at"] is None
    assert SkillTraceSummary.from_dict(summary.to_dict()) == summary
