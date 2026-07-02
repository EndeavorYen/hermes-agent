from agent.raphael.governor import (
    apply_raphael_response_governor,
    should_apply_raphael_response_governor,
)


def test_should_apply_requires_enabled_default_advisor_mode():
    assert should_apply_raphael_response_governor(
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "mode": "advisor",
            }
        }
    )
    assert should_apply_raphael_response_governor(
        {
            "plugins": {"enabled": ["raphael"], "disabled": []},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "mode": "sage_king",
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
    assert not should_apply_raphael_response_governor(
        {
            "plugins": {"enabled": ["raphael"], "disabled": ["raphael"]},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "mode": "sage_king",
            },
        }
    )


def test_governor_preserves_normal_answers_without_labeled_judgment():
    text = "\n".join(
        [
            "第一行",
            "",
            "第二行",
            "第三行",
            "第四行",
            "第五行",
            "第六行",
            "第七行",
        ]
    )

    governed = apply_raphael_response_governor(text, enabled=True, max_lines=6)

    assert governed == text


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


def test_governor_preserves_review_findings_and_evidence_reports():
    text = "\n".join(
        [
            "Findings",
            "- [P0] Direct visual handoff drops reference_binding at tools/visual_agent_tool.py:77.",
            "- [P1] Prompt disclosure can leak another Slack thread.",
            "",
            "Evidence",
            "- pytest tests/tools/test_visual_agent_tool.py -q",
            "- non-live repro captured missing image_operation.",
            "",
            "Next",
            "- Patch the merge path and rerun the visual agent suite.",
        ]
    )

    assert apply_raphael_response_governor(text, enabled=True, max_lines=3) == text


def test_governor_disabled_returns_original_text():
    text = "a\nb\nc"

    assert apply_raphael_response_governor(text, enabled=False, max_lines=1) == text


def test_governor_extracts_labeled_judgment_lines_before_chatter():
    text = "\n".join(
        [
            "我先完整說明一下背景。",
            "這裡其實有很多面向可以展開。",
            "先看第一個面向。",
            "再看第二個面向。",
            "狀態：目前問題不是缺功能，是輸出紀律不穩。",
            "風險：單純裁前 6 行會留下前言，反而切掉判斷。",
            "下一步：優先保留判斷行，沒有判斷行才裁切。",
            "補充：這行不該保留。",
        ]
    )

    governed = apply_raphael_response_governor(text, enabled=True, max_lines=6)

    assert governed == "\n".join(
        [
            "狀態：目前問題不是缺功能，是輸出紀律不穩。",
            "風險：單純裁前 6 行會留下前言，反而切掉判斷。",
            "下一步：優先保留判斷行，沒有判斷行才裁切。",
        ]
    )


def test_governor_extracts_bulleted_labeled_judgment_lines():
    text = "\n".join(
        [
            "前言：略。",
            "- 狀態：已進入 Phase 7。",
            "- 風險：過度設計會拖慢。",
            "- 下一步：只做抽取。",
            "補充：不用。",
        ]
    )

    governed = apply_raphael_response_governor(text, enabled=True, max_lines=6)

    assert governed == "\n".join(
        [
            "- 狀態：已進入 Phase 7。",
            "- 風險：過度設計會拖慢。",
            "- 下一步：只做抽取。",
        ]
    )


def test_governor_does_not_fall_back_to_line_cap_without_labeled_judgment():
    text = "a\nb\nc\nd"

    assert apply_raphael_response_governor(text, enabled=True, max_lines=2) == text
