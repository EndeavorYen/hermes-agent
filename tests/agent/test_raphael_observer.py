from agent.raphael.observer import (
    build_raphael_observation_context,
    decide_raphael_auto_status_portrait,
    decide_raphael_visual_trigger,
    extract_raphael_turn_sketches,
    observe_raphael_turn,
    render_raphael_observation,
    should_inject_raphael_observation,
)


def _raphael_config(
    *,
    enabled: bool = True,
    default_conversation_mode_enabled: bool = True,
    mode: str = "advisor",
):
    return {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": enabled,
            "default_conversation_mode_enabled": default_conversation_mode_enabled,
            "mode": mode,
        },
    }


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


def test_observer_does_not_treat_general_character_art_as_raphael_status_request():
    observation = observe_raphael_turn(
        "幫我畫 Velina Airgid - Zenless Zone Zero 這個角色（動漫圖）"
    )

    assert observation.task_state == "casual_or_direct"
    assert observation.risk_signal == "low"
    assert observation.visual_status_needed is False


def test_render_observation_context_is_compact_and_ephemeral():
    observation = observe_raphael_turn("請產生一張狀態圖")

    context = render_raphael_observation(observation)

    assert "Raphael State Observer (ephemeral, internal)" in context
    assert "task_state: visual_status_request" in context
    assert "risk_signal: visual_generation_requested" in context
    assert "suggested_next_move:" in context
    assert "visual_status_needed: true" in context


def test_observation_context_uses_raphael_default_mode_gate():
    enabled_config = _raphael_config()
    sage_king_config = _raphael_config(mode="sage_king")
    disabled_config = _raphael_config(default_conversation_mode_enabled=False)
    non_advisor_config = _raphael_config(mode="planner")

    assert should_inject_raphael_observation(enabled_config)
    assert should_inject_raphael_observation(sage_king_config)
    assert not should_inject_raphael_observation(disabled_config)
    assert not should_inject_raphael_observation(
        {
            "plugins": {"enabled": ["raphael"], "disabled": ["raphael"]},
            "raphael": {
                "enabled": True,
                "default_conversation_mode_enabled": True,
                "mode": "sage_king",
            },
        }
    )
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
    config = _raphael_config()
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
    config = _raphael_config()

    context = build_raphael_observation_context("請產生一張現在的狀態圖", config)

    assert "Raphael Visual Trigger Gate (suggestion only):" in context
    assert "visual_trigger: suggest_status_portrait" in context
    assert "reason: explicit_visual_request" in context
    assert "auto_call_image_tool: false" in context


def test_observation_context_omits_visual_gate_when_not_needed():
    config = _raphael_config()

    context = build_raphael_observation_context("你好呀", config)

    assert "Raphael Visual Trigger Gate" not in context
    assert "visual_trigger: none" not in context


def test_observation_context_includes_control_layer_for_visual_requests():
    config = _raphael_config()

    context = build_raphael_observation_context(
        "請產出一張圖片和一段影片",
        config,
    )

    assert "Raphael Control Layer (ephemeral, internal):" in context
    assert "mode: visual_agent_generation" in context
    assert "handoff_tool: visual_agent_generate" in context
    assert "required_proofs:" in context


def test_observation_context_includes_invocation_gate_for_summon():
    config = _raphael_config(mode="sage_king")

    context = build_raphael_observation_context("拉斐爾，解析這個任務", config)

    assert "Raphael Invocation Gate:" in context
    assert "summoned: true" in context
    assert "public_reply_style: natural_status_risk_next_step" in context
    assert "do_not_echo_internal_labels: true" in context
    assert "parallel_routes" not in context
    assert "chosen_route" not in context


def test_observation_context_does_not_create_mission_for_casual_summon(
    monkeypatch,
    tmp_path,
):
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    config = _raphael_config(mode="sage_king")

    context = build_raphael_observation_context("拉斐爾？", config)

    assert "Raphael Invocation Gate:" in context
    assert "summoned: true" in context
    assert state.read_mission_state() is None


def test_observation_context_does_not_overwrite_mission_for_casual_summon(
    monkeypatch,
    tmp_path,
):
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    config = _raphael_config(mode="sage_king")

    build_raphael_observation_context("請修復 gateway fallback bug 並驗證", config)
    first_mission = state.read_mission_state()
    build_raphael_observation_context("拉斐爾？", config)
    second_mission = state.read_mission_state()

    assert first_mission is not None
    assert second_mission is not None
    assert second_mission.mission_id == first_mission.mission_id
    assert second_mission.goal == first_mission.goal
    assert second_mission.required_proofs == first_mission.required_proofs


def test_observation_context_binds_vague_takeover_summon_to_current_mission(
    monkeypatch,
    tmp_path,
):
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    config = _raphael_config(mode="sage_king")

    build_raphael_observation_context("請修復 gateway fallback bug 並驗證", config)
    first_mission = state.read_mission_state()
    build_raphael_observation_context("拉斐爾，接管這個任務", config)
    second_mission = state.read_mission_state()

    assert first_mission is not None
    assert second_mission is not None
    assert second_mission.mission_id == first_mission.mission_id
    assert second_mission.goal == first_mission.goal
    assert second_mission.required_proofs == first_mission.required_proofs


def test_observation_context_uses_multimodal_attachments_for_ref_mapping(
    monkeypatch,
    tmp_path,
):
    import agent.raphael.state as state

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    config = _raphael_config(mode="sage_king")
    message = [
        {"type": "text", "text": "拉斐爾，用 ref1 的服裝產出圖片"},
        {"type": "image_url", "image_url": {"url": "file:///tmp/ref1.png"}},
    ]

    context = build_raphael_observation_context(message, config)
    mission = state.read_mission_state()

    assert "missing_ref1" not in context
    assert mission is not None
    assert "missing_ref1" not in mission.blockers
    assert "reference_mapping_confirmed" not in mission.required_proofs


def test_observation_context_surfaces_mission_state_failure(monkeypatch, tmp_path):
    import agent.raphael.state as state

    def fail_write_mission_state(_mission):
        raise RuntimeError("private mission state path leaked")

    monkeypatch.setattr(state, "get_hermes_home", lambda: tmp_path)
    monkeypatch.setattr(state, "write_mission_state", fail_write_mission_state)
    config = _raphael_config(mode="sage_king")

    context = build_raphael_observation_context(
        "請修復 Hermes gateway fallback bug 並驗證",
        config,
    )

    assert "Raphael Control Layer Degraded (ephemeral, internal):" in context
    assert "failure_layer: mission_state" in context
    assert "error_class: RuntimeError" in context
    assert "inspect Raphael state writer" in context
    assert "private mission state path leaked" not in context


def test_observation_context_surfaces_control_decision_failure(monkeypatch):
    import agent.raphael.control as control

    def fail_build_control_decision(*_args, **_kwargs):
        raise ValueError("secret control prompt")

    monkeypatch.setattr(
        control,
        "build_raphael_control_decision",
        fail_build_control_decision,
    )
    config = _raphael_config(mode="sage_king")

    context = build_raphael_observation_context(
        "請產出一張圖片和一段影片",
        config,
    )

    assert "Raphael Control Layer Degraded (ephemeral, internal):" in context
    assert "failure_layer: control_decision" in context
    assert "error_class: ValueError" in context
    assert "inspect Raphael control decision" in context
    assert "secret control prompt" not in context


def test_auto_status_portrait_suppresses_explicit_visual_request_by_default():
    observation = observe_raphael_turn("請產生一張現在的狀態圖")
    visual_decision = decide_raphael_visual_trigger(observation, ())

    decision = decide_raphael_auto_status_portrait(
        observation,
        visual_decision,
        (),
    )

    assert decision["auto_status_portrait"] == "suppressed"
    assert decision["reason"] == "disabled_by_default"
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
    config = _raphael_config()

    context = build_raphael_observation_context("請產生一張現在的狀態圖", config)

    assert "Raphael Auto Status Portrait Gate (MVP):" in context
    assert "auto_status_portrait: suppressed" in context
    assert "reason: disabled_by_default" in context
    assert "cooldown_turns: 3" in context
    assert "marker: Raphael Status Portrait" in context
    assert "may call image_generate" not in context


def test_observation_context_omits_status_portrait_tool_call_by_default():
    config = _raphael_config()

    context = build_raphael_observation_context("請產生一張現在的狀態圖", config)

    assert "Raphael Status Portrait Tool Call (MVP):" not in context
    assert "image_generate" not in context
    assert "arguments.prompt:" not in context


def test_observation_context_does_not_block_general_user_image_generation():
    config = _raphael_config()

    context = build_raphael_observation_context(
        "幫我畫 Velina Airgid - Zenless Zone Zero 這個角色（動漫圖）",
        config,
    )

    assert "Raphael Auto Status Portrait Gate" not in context
    assert "answer with text only" not in context
    assert "disabled_by_default" not in context


def test_observation_context_omits_tool_call_when_auto_portrait_suppressed():
    config = _raphael_config()

    context = build_raphael_observation_context(
        "請改 skill、寫 memory，並產生一張狀態圖",
        config,
    )

    assert "auto_status_portrait: suppressed" in context
    assert "Raphael Status Portrait Tool Call (MVP):" not in context
    assert "tool: image_generate" not in context
