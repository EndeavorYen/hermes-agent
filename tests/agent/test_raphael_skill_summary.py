from datetime import datetime, timezone

from agent.raphael.models import SkillTraceSummary
from agent.raphael.skill_trace import render_skill_summary


def test_render_skill_summary_empty_state_includes_read_only_boundary():
    output = render_skill_summary([])

    assert "Raphael Skill Trace" in output
    assert "Mode: read-only skill usage summary" in output
    assert "Skill Usage:" in output
    assert "No skill usage or trace events recorded." in output
    assert "does not propose or modify skills" in output


def test_render_skill_summary_lists_counts_latest_metadata_and_outcomes():
    output = render_skill_summary(
        [
            SkillTraceSummary(
                skill_name="test-driven-development",
                use_count=4,
                view_count=2,
                patch_count=1,
                latest_activity_at=datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc),
                state="active",
                created_by="user",
                outcome_counts={"success": 3, "needs_review": 1},
            )
        ]
    )

    assert "- test-driven-development:" in output
    assert "use=4" in output
    assert "view=2" in output
    assert "patch=1" in output
    assert "latest=2026-06-16T12:00:00+00:00" in output
    assert "state=active" in output
    assert "created_by=user" in output
    assert "outcomes=needs_review=1, success=3" in output
