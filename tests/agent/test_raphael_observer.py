from agent.raphael.observer import (
    build_raphael_observation_context,
    decide_raphael_auto_status_portrait,
    decide_raphael_visual_trigger,
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


def test_visual_trigger_suggests_portrait_for_explicit_visual_request():
    observation = observe_raphael_turn("請產生一張現在的狀態圖")
    decision = decide_raphael_visual_trigger(observation, ())

    assert decision["visual_trigger"] == "suggest_status_portrait"
    assert decision["reason"] == "explicit_visual_request"
    assert decision["auto_call_image_tool"] is False


def test_visual_trigger_suggests_portrait_for_milestone_sketch():
    observation = observe_raphael_turn("接下來呢？")
    decision = decide_raphael_visual_trigger(
        observation,
        ("狀態：Phase 9 已完成並上線。", "下一步：Phase 10 gate。"),
    )

    assert decision["visual_trigger"] == "suggest_status_portrait"
    assert decision["reason"] == "state_transition"
    assert decision["auto_call_image_tool"] is False


def test_visual_trigger_stays_quiet_for_casual_turns():
    observation = observe_raphael_turn("你好呀")
    decision = decide_raphael_visual_trigger(observation, ())

    assert decision["visual_trigger"] == "none"
    assert decision["reason"] == "not_needed"
    assert decision["auto_call_image_tool"] is False


def test_observation_context_renders_visual_trigger_gate():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    context = build_raphael_observation_context("請產生一張現在的狀態圖", config)

    assert "Raphael Visual Trigger Gate (suggestion only):" in context
    assert "visual_trigger: suggest_status_portrait" in context
    assert "reason: explicit_visual_request" in context
    assert "auto_call_image_tool: false" in context


def test_observation_context_omits_visual_gate_when_not_needed():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    context = build_raphael_observation_context("你好呀", config)

    assert "Raphael Visual Trigger Gate" not in context
    assert "visual_trigger: none" not in context


def test_auto_status_portrait_allows_explicit_visual_request_without_cooldown():
    observation = observe_raphael_turn("請產生一張現在的狀態圖")
    visual_decision = decide_raphael_visual_trigger(observation, ())

    decision = decide_raphael_auto_status_portrait(
        observation,
        visual_decision,
        (),
    )

    assert decision["auto_status_portrait"] == "allowed"
    assert decision["reason"] == "explicit_visual_request"
    assert decision["cooldown_turns"] == 3
    assert "Raphael Status Portrait" in decision["marker"]


def test_auto_status_portrait_suppresses_mutation_turns():
    observation = observe_raphael_turn("請改 skill、寫 memory，並產生狀態圖")
    visual_decision = decide_raphael_visual_trigger(observation, ())

    decision = decide_raphael_auto_status_portrait(
        observation,
        visual_decision,
        (),
    )

    assert decision["auto_status_portrait"] == "suppressed"
    assert decision["reason"] == "mutation_or_delivery_turn"


def test_auto_status_portrait_suppresses_recent_portrait_history():
    observation = observe_raphael_turn("請產生一張現在的狀態圖")
    visual_decision = decide_raphael_visual_trigger(observation, ())
    history = [
        {
            "role": "assistant",
            "content": "Raphael Status Portrait: generated /tmp/status.png",
        }
    ]

    decision = decide_raphael_auto_status_portrait(
        observation,
        visual_decision,
        history,
    )

    assert decision["auto_status_portrait"] == "suppressed"
    assert decision["reason"] == "cooldown"


def test_observation_context_renders_auto_status_portrait_gate():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    context = build_raphael_observation_context("請產生一張現在的狀態圖", config)

    assert "Raphael Auto Status Portrait Gate (MVP):" in context
    assert "auto_status_portrait: allowed" in context
    assert "cooldown_turns: 3" in context
    assert "marker: Raphael Status Portrait" in context


def test_observation_context_renders_status_portrait_tool_call_when_allowed():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    context = build_raphael_observation_context("請產生一張現在的狀態圖", config)

    assert "Raphael Status Portrait Tool Call (MVP):" in context
    assert "tool: image_generate" in context
    assert "call_policy: call_once_when_available" in context
    assert "aspect_ratio: portrait" in context
    assert "original non-infringing RPG status portrait" in context
    assert "do not depict copyrighted characters" in context
    assert "final_marker_required: 狀態：Raphael Status Portrait: <image path or URL>" in context
    assert "arguments.prompt:" in context
    assert "arguments.aspect_ratio: portrait" in context


def test_observation_context_omits_tool_call_when_auto_portrait_suppressed():
    config = {
        "raphael": {
            "enabled": True,
            "default_conversation_mode_enabled": True,
            "mode": "advisor",
        }
    }

    context = build_raphael_observation_context(
        "請改 skill、寫 memory，並產生一張狀態圖",
        config,
    )

    assert "auto_status_portrait: suppressed" in context
    assert "Raphael Status Portrait Tool Call (MVP):" not in context
    assert "tool: image_generate" not in context
