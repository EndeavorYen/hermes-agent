from agent.raphael.governor import (
    apply_raphael_response_governor,
    should_apply_raphael_response_governor,
)


def test_should_apply_requires_enabled_default_advisor_mode():
    assert should_apply_raphael_response_governor(
        {
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "mode": "advisor",
            }
        }
    )

    assert not should_apply_raphael_response_governor(
        {"raphael": {"enabled": True, "default_conversation_mode_enabled": False}}
    )
    assert not should_apply_raphael_response_governor(
        {"raphael": {"enabled": False, "default_conversation_mode_enabled": True}}
    )
    assert not should_apply_raphael_response_governor(
        {
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "mode": "planner",
            }
        }
    )


def test_governor_caps_non_empty_lines_when_enabled():
    text = "\n".join(
        [
            "狀態：一",
            "",
            "風險：二",
            "下一步：三",
            "補充：四",
            "補充：五",
            "補充：六",
            "補充：七",
        ]
    )

    governed = apply_raphael_response_governor(text, enabled=True, max_lines=6)

    lines = [line for line in governed.splitlines() if line.strip()]
    assert len(lines) == 6
    assert lines[-1] == "補充：六"
    assert "補充：七" not in governed


def test_governor_preserves_code_blocks():
    text = "\n".join(
        [
            "狀態：需要程式碼。",
            "```python",
            "print('hello')",
            "```",
            "風險：裁切會破壞程式碼。",
            "下一步：保留原文。",
            "補充：超過上限也不要裁。",
        ]
    )

    assert apply_raphael_response_governor(text, enabled=True, max_lines=3) == text


def test_governor_preserves_file_mutation_safety_footer():
    text = "\n".join(
        [
            "狀態：完成部分修改。",
            "風險：有檔案沒有改到。",
            "⚠️ 2 file(s) were NOT modified.",
            "• `/tmp/a.py`: patch failed",
            "• `/tmp/b.py`: patch failed",
        ]
    )

    assert apply_raphael_response_governor(text, enabled=True, max_lines=2) == text


def test_governor_disabled_returns_original_text():
    text = "a\nb\nc"

    assert apply_raphael_response_governor(text, enabled=False, max_lines=1) == text
