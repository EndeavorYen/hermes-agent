from datetime import datetime, timezone

from agent.raphael.models import SkillTraceSummary
from agent.raphael.skill_trace import render_skill_summary


def test_render_skill_summary_empty_state_includes_evolution_audit_boundary():
    output = render_skill_summary([])

    assert "Raphael Skill Evolution Trace" in output
    assert "Mode: skill usage and evolution audit" in output
    assert "Skill Evolution Brief:" in output
    assert "追蹤技能：0 個" in output
    assert "已修補技能：0 個" in output
    assert "學習結果：尚無" in output
    assert "Skill Usage:" in output
    assert "No skill usage or trace events recorded." in output
    assert "安全邊界：" in output
    assert "學習結果：none" not in output
    assert "gated background review" not in output
    assert "auditable" not in output
    assert "rollback" not in output


def test_render_skill_summary_starts_with_brief_and_humanized_rows():
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

    assert output.index("Skill Evolution Brief:") < output.index("Skill Usage:")
    assert "追蹤技能：1 個" in output
    assert "活躍技能：1 個" in output
    assert "已修補技能：1 個" in output
    assert "最近活動：2026-06-16T12:00:00+00:00" in output
    assert "學習結果：needs_review=1、success=3" in output
    assert "- test-driven-development:" in output
    assert "使用：4 次；檢視：2 次；修補：1 次" in output
    assert "狀態：啟用；建立者：使用者；結果：needs_review=1、success=3" in output
    assert "狀態：active" not in output
    assert "建立者：user" not in output
    assert "use=4" not in output
    assert "view=2" not in output
    assert "patch=1" not in output
    assert "latest=" not in output
    assert "state=" not in output
    assert "created_by=" not in output
    assert "outcomes=" not in output
