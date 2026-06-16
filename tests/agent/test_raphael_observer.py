from agent.raphael.observer import (
    build_raphael_observation_context,
    extract_raphael_turn_sketches,
    observe_raphael_turn,
    render_raphael_observation,
    should_inject_raphael_observation,
)


def test_observer_defaults_to_low_risk_direct_answer():
    observation = observe_raphael_turn("你好呀")

    assert observation.task_state == "casual_or_direct"
    assert observation.risk_signal == "low"
    assert observation.suggested_next_move == "answer directly"
    assert observation.visual_status_needed is False


def test_observer_flags_public_or_persistent_mutation_risk():
    observation = observe_raphael_turn(
        "請幫我改 skill、寫 memory、開 cron、發 Slack，然後 push 上線"
    )

    assert observation.task_state == "mutation_or_delivery_request"
    assert observation.risk_signal == "persistent_or_public_side_effect"
    assert "scope" in observation.suggested_next_move
    assert "approval" in observation.suggested_next_move
    assert observation.visual_status_needed is False


def test_observer_flags_visual_status_request():
    observation = observe_raphael_turn("偶爾產生一張狀態圖，呈現 RPG 樣貌")

    assert observation.task_state == "visual_status_request"
    assert observation.risk_signal == "visual_generation_requested"
    assert "status card" in observation.suggested_next_move
    assert observation.visual_status_needed is True


def test_render_observation_context_is_compact_and_ephemeral():
    observation = observe_raphael_turn("請產生一張狀態圖")

    context = render_raphael_observation(observation)

    assert "Raphael State Observer (ephemeral, internal)" in context
    assert "task_state: visual_status_request" in context
    assert "risk_signal: visual_generation_requested" in context
    assert "suggested_next_move:" in context
    assert "visual_status_needed: true" in context


def test_observation_context_uses_raphael_default_mode_gate():
    enabled_config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }
    disabled_config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": False,
            "mode": "advisor",
        }
    }
    non_advisor_config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "planner",
        }
    }

    assert should_inject_raphael_observation(enabled_config)
    assert not should_inject_raphael_observation(disabled_config)
    assert not should_inject_raphael_observation(non_advisor_config)
    assert build_raphael_observation_context("請產生一張狀態圖", disabled_config) == ""


def test_extracts_recent_judgment_lines_as_turn_sketches():
    history = [
        {"role": "assistant", "content": "狀態：舊狀態。\n風險：舊風險。"},
        {"role": "user", "content": "下一步？"},
        {
            "role": "assistant",
            "content": (
                "前言：略。\n"
                "狀態：Phase 8 已完成。\n"
                "風險：還沒有短期局勢感。\n"
                "下一步：加入最近 turn sketch。"
            ),
        },
    ]

    sketches = extract_raphael_turn_sketches(history, max_items=3)

    assert sketches == (
        "狀態：Phase 8 已完成。",
        "風險：還沒有短期局勢感。",
        "下一步：加入最近 turn sketch。",
    )


def test_observation_context_includes_recent_turn_sketches():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }
    history = [
        {
            "role": "assistant",
            "content": "狀態：Phase 8 已完成。\n風險：缺少短期局勢感。",
        }
    ]

    context = build_raphael_observation_context(
        "請往下推進至 phase9",
        config,
        conversation_history=history,
    )

    assert "Raphael Turn Sketch (recent, derived):" in context
    assert "- 狀態：Phase 8 已完成。" in context
    assert "- 風險：缺少短期局勢感。" in context
