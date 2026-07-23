from __future__ import annotations

import json
from types import SimpleNamespace


def _engine_result(path: str, *, provider: str = "xai") -> str:
    return json.dumps(
        {
            "success": True,
            "run": {
                "run_id": "run-current",
                "status": "completed",
                "selected_artifact_id": "artifact-current",
            },
            "artifact": {
                "artifact_id": "artifact-current",
                "alias": "G1",
                "local_path": path,
                "provider": provider,
            },
            "candidate_aliases": [
                {"alias": "G1", "artifact_id": "artifact-current"},
            ],
            "evidence": {
                "provider_attempt": {"status": "passed"},
                "artifact_quality": {"status": "passed"},
                "delivery": {"status": "passed"},
                "reference_mapping": {"status": "passed"},
            },
        },
        ensure_ascii=False,
    )


class _FakeBudget:
    remaining = 10
    used = 0
    max_total = 10


class _FakeAgent:
    api_mode = ""
    max_iterations = 20
    quiet_mode = True
    model = "gpt-5.6"
    provider = "openai-codex"
    base_url = "https://api.openai.test/v1"
    session_id = "sess-visual"
    valid_tool_names = {"visual_engine_generate"}
    iteration_budget = _FakeBudget()
    session_input_tokens = 0
    session_output_tokens = 0
    session_cache_read_tokens = 0
    session_cache_write_tokens = 0
    session_reasoning_tokens = 0
    session_prompt_tokens = 0
    session_completion_tokens = 0
    session_total_tokens = 0
    session_estimated_cost_usd = 0.0
    session_cost_status = ""
    session_cost_source = ""
    context_compressor = SimpleNamespace(last_prompt_tokens=0)
    _tool_guardrail_halt_decision = None
    _response_was_previewed = False
    _interrupt_message = None
    _skill_nudge_interval = 0
    _iters_since_skill = 0
    _stream_callback = None

    def __init__(self):
        self.interim_messages = []

    def _emit_interim_assistant_message(self, message):
        self.interim_messages.append(message)

    def _flush_messages_to_session_db(self, *_args, **_kwargs):
        pass

    def _save_trajectory(self, *_args, **_kwargs):
        pass

    def _cleanup_task_resources(self, *_args, **_kwargs):
        pass

    def _drop_trailing_empty_response_scaffolding(self, *_args, **_kwargs):
        pass

    def _persist_session(self, *_args, **_kwargs):
        pass

    def _file_mutation_verifier_enabled(self):
        return False

    def _turn_completion_explainer_enabled(self):
        return False

    def _drain_pending_steer(self):
        return None

    def clear_interrupt(self):
        pass

    def _sync_external_memory_for_turn(self, **_kwargs):
        pass

    def _spawn_background_review(self, **_kwargs):
        pass


def test_run_conversation_executes_direct_visual_handoff_before_base_llm(
    monkeypatch,
    tmp_path,
):
    import agent.conversation_loop as conversation_loop
    from tools.registry import registry

    agent = _FakeAgent()
    dispatched = {}
    artifact_path = tmp_path / "current-composition.png"
    artifact_path.write_bytes(b"current")

    def fake_build_turn_context(*_args, **_kwargs):
        user_message = "現在用 openai 幫我產出構圖，一樣產出四張不同構圖讓我挑選"
        return SimpleNamespace(
            user_message=user_message,
            original_user_message=user_message,
            messages=[{"role": "user", "content": user_message}],
            conversation_history=[],
            active_system_prompt="",
            effective_task_id="task-visual",
            turn_id="turn-visual",
            current_turn_user_idx=0,
            should_review_memory=False,
            plugin_user_context="",
            ext_prefetch_cache=None,
            turn_control={
                "schema_version": "raphael.turn-decision.v1",
                "decision_id": "decision-visual",
                "mission_id": "mission-visual",
                "mode": "visual_agent_generation",
                "completion_policy": "verify",
                "failure_policy": "fail_closed",
                "required_proofs": [],
            },
        )

    def fake_dispatch(name, args, **_kwargs):
        dispatched["name"] = name
        dispatched["args"] = dict(args)
        return _engine_result(str(artifact_path), provider="openai-codex")

    monkeypatch.setattr(conversation_loop, "build_turn_context", fake_build_turn_context)
    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    result = conversation_loop.run_conversation(agent, "ignored by fake context")

    assert result["api_calls"] == 0
    assert result["turn_exit_reason"] == "direct_visual_agent_handoff"
    assert dispatched["name"] == "visual_engine_generate"
    assert dispatched["args"]["session_id"] == "sess-visual"
    assert dispatched["args"]["message_id"] == "turn-visual"
    assert result["final_response"] == "已產出圖片：G1。後續可直接指定編號繼續編輯。"
    assert dispatched["args"]["provider"] == "openai-codex"
    assert dispatched["args"]["candidate_count"] == 4
    tool_turns = [msg for msg in result["messages"] if msg.get("tool_calls")]
    assert len(tool_turns) == 1
    assert tool_turns[0]["tool_calls"][0]["function"]["name"] == "visual_engine_generate"
    tool_results = [msg for msg in result["messages"] if msg.get("role") == "tool"]
    assert len(tool_results) == 1
    payload = json.loads(tool_results[0]["content"])
    assert payload["direct_visual_agent_handoff"]["mode"] == "pre_llm_direct"


def test_codex_app_server_executes_direct_xai_handoff_before_runtime(
    monkeypatch,
    tmp_path,
):
    import agent.conversation_loop as conversation_loop
    from tools.registry import registry

    agent = _FakeAgent()
    agent.api_mode = "codex_app_server"
    dispatched = {}
    artifact_path = tmp_path / "current-xai.png"
    artifact_path.write_bytes(b"current")

    def fail_codex_runtime(**_kwargs):
        raise AssertionError("Codex app-server must not receive a direct visual request")

    agent._run_codex_app_server_turn = fail_codex_runtime

    def fake_build_turn_context(*_args, **_kwargs):
        user_message = "用 xai imagine 產出四張高品質圖片讓我挑選"
        return SimpleNamespace(
            user_message=user_message,
            original_user_message=user_message,
            messages=[{"role": "user", "content": user_message}],
            conversation_history=[],
            active_system_prompt="",
            effective_task_id="task-xai-visual",
            turn_id="turn-xai-visual",
            current_turn_user_idx=0,
            should_review_memory=False,
            plugin_user_context="",
            ext_prefetch_cache=None,
        )

    def fake_dispatch(name, args, **_kwargs):
        dispatched["name"] = name
        dispatched["args"] = dict(args)
        return _engine_result(str(artifact_path))

    monkeypatch.setattr(conversation_loop, "build_turn_context", fake_build_turn_context)
    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    result = conversation_loop.run_conversation(agent, "ignored by fake context")

    assert result["api_calls"] == 0
    assert result["turn_exit_reason"] == "direct_visual_agent_handoff"
    assert dispatched["name"] == "visual_engine_generate"
    assert dispatched["args"]["provider"] == "xai"
    assert dispatched["args"]["candidate_count"] == 4


def test_codex_app_server_routes_slack_regenerate_output_through_visual_tool(
    monkeypatch,
    tmp_path,
):
    import agent.conversation_loop as conversation_loop
    from gateway.session_context import reset_visual_reference_context, set_visual_reference_context
    from tools.registry import registry

    agent = _FakeAgent()
    agent.api_mode = "codex_app_server"
    dispatched = {}
    artifact_path = tmp_path / "current-regenerated.png"
    artifact_path.write_bytes(b"current")

    def fail_codex_runtime(**_kwargs):
        raise AssertionError("Slack visual regeneration must bypass Codex app-server")

    agent._run_codex_app_server_turn = fail_codex_runtime
    user_message = (
        '[Replying to: "用 xai imagine，locked ref 人物，產出類似但不同姿勢，'
        '給我 4 張挑選"]\n\n'
        "[Thread context — prior messages in this thread (not yet in conversation history):]\n"
        "[thread parent] simon: 用 xai imagine，locked ref 人物，產出類似但不同姿勢，給我 4 張挑選\n"
        "[End of thread context]\n\n"
        "請重新產出"
    )

    def fake_build_turn_context(*_args, **_kwargs):
        return SimpleNamespace(
            user_message=user_message,
            original_user_message=user_message,
            messages=[{"role": "user", "content": user_message}],
            conversation_history=[],
            active_system_prompt="",
            effective_task_id="task-slack-regenerate",
            turn_id="turn-slack-regenerate",
            current_turn_user_idx=0,
            should_review_memory=False,
            plugin_user_context="",
            ext_prefetch_cache=None,
            turn_control={
                "mode": "visual_agent_generation",
                "completion_policy": "visual",
                "route": {},
                "runtime_contract": {},
            },
        )

    def fake_dispatch(name, args, **_kwargs):
        dispatched["name"] = name
        dispatched["args"] = dict(args)
        return _engine_result(str(artifact_path))

    monkeypatch.setattr(conversation_loop, "build_turn_context", fake_build_turn_context)
    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    token = set_visual_reference_context(
        [
            {
                "uri": "/tmp/locked-character.png",
                "role_hint": "character_identity",
                "source": "previous_tool_reference",
                "user_ref_index": 1,
            }
        ]
    )
    try:
        result = conversation_loop.run_conversation(agent, "ignored by fake context")
    finally:
        reset_visual_reference_context(token)

    assert result["api_calls"] == 0
    assert result["turn_exit_reason"] == "direct_visual_agent_handoff"
    assert dispatched["name"] == "visual_engine_generate"
    assert dispatched["args"]["provider"] == "xai"
    assert [item["source_path"] for item in dispatched["args"]["references"]] == [
        "/tmp/locked-character.png"
    ]
    assert dispatched["args"]["candidate_count"] == 4
    tool_results = [msg for msg in result["messages"] if msg.get("role") == "tool"]
    assert len(tool_results) == 1
    payload = json.loads(tool_results[0]["content"])
    assert payload["artifact"]["local_path"] == str(artifact_path)
    assert payload["direct_visual_agent_handoff"]["mode"] == "pre_llm_direct"


def test_codex_app_server_routes_current_attachment_generation_before_runtime(
    monkeypatch,
    tmp_path,
):
    import agent.conversation_loop as conversation_loop
    from gateway.session_context import reset_visual_reference_context, set_visual_reference_context
    from tools.registry import registry

    agent = _FakeAgent()
    agent.api_mode = "codex_app_server"
    dispatched = {}
    artifact_path = tmp_path / "current-selected.png"
    artifact_path.write_bytes(b"current")

    def fail_codex_runtime(**_kwargs):
        raise AssertionError("Current-attachment generation must bypass Codex app-server")

    agent._run_codex_app_server_turn = fail_codex_runtime
    user_message = """用 xai imagine，參考附件的圖片，產出類似但不同姿勢、高品質，給我 4 張挑選

[Visual Arsenal source images]
1. image_path: /tmp/current-slack-reference.png (image/png)

[Image attached at: /tmp/current-slack-reference.png]
[screenshot]"""

    def fake_build_turn_context(*_args, **_kwargs):
        return SimpleNamespace(
            user_message=user_message,
            original_user_message=user_message,
            messages=[{"role": "user", "content": user_message}],
            conversation_history=[],
            active_system_prompt="",
            effective_task_id="task-current-attachment",
            turn_id="turn-current-attachment",
            current_turn_user_idx=0,
            should_review_memory=False,
            plugin_user_context="",
            ext_prefetch_cache=None,
            turn_control={
                "mode": "visual_agent_generation",
                "completion_policy": "visual",
                "route": {
                    "visual_media_provider": "xai",
                    "visual_media_provider_source": "prompt_override",
                },
                "runtime_contract": {"image_provider": "xai"},
            },
        )

    def fake_dispatch(name, args, **_kwargs):
        dispatched["name"] = name
        dispatched["args"] = dict(args)
        return _engine_result(str(artifact_path))

    monkeypatch.setattr(conversation_loop, "build_turn_context", fake_build_turn_context)
    monkeypatch.setattr(registry, "dispatch", fake_dispatch)
    token = set_visual_reference_context(
        [
            {
                "uri": "/tmp/current-slack-reference.png",
                "role_hint": "visual_reference",
                "source": "gateway_attachment",
                "user_ref_index": 0,
            }
        ]
    )
    try:
        result = conversation_loop.run_conversation(agent, "ignored by fake context")
    finally:
        reset_visual_reference_context(token)

    assert result["api_calls"] == 0
    assert result["turn_exit_reason"] == "direct_visual_agent_handoff"
    assert dispatched["name"] == "visual_engine_generate"
    assert [item["source_path"] for item in dispatched["args"]["references"]] == [
        "/tmp/current-slack-reference.png"
    ]
    assert dispatched["args"]["provider"] == "xai"
    assert dispatched["args"]["candidate_count"] == 4


def test_gateway_attachment_context_reaches_visual_handoff_consumer():
    from gateway.run import _run_conversation_with_visual_reference_context
    from gateway.session_context import get_visual_reference_context_entries

    seen = {}

    class _GatewayAgent:
        def run_conversation(self, message, **kwargs):
            seen["message"] = message
            seen["kwargs"] = kwargs
            seen["references"] = get_visual_reference_context_entries()
            return {"final_response": "ok", "messages": []}

    result = _run_conversation_with_visual_reference_context(
        _GatewayAgent(),
        [{"type": "text", "text": "use this"}],
        visual_references=[
            {
                "uri": "/tmp/current-reference.png",
                "role_hint": "visual_reference",
                "source": "gateway_attachment",
                "user_ref_index": 0,
            }
        ],
        conversation_kwargs={"task_id": "gateway-visual"},
    )

    assert result["final_response"] == "ok"
    assert seen["kwargs"]["task_id"] == "gateway-visual"
    assert seen["references"] == [
        {
            "uri": "/tmp/current-reference.png",
            "role_hint": "visual_reference",
            "source": "gateway_attachment",
            "user_ref_index": 0,
        }
    ]
    assert get_visual_reference_context_entries() == []


def test_gateway_recovers_original_thread_reference_for_visual_followup():
    from gateway.run import _visual_reference_context_for_turn

    prompt = """[Replying to: "用 xai imagine，locked ref 角色，給我 4 張挑選"]

[Thread context — prior messages in this thread (not yet in conversation history):]
[thread parent] user: 用 xai imagine，locked ref 角色，給我 4 張挑選
[End of thread context]

visual agent : 用原本的ref, 再產2張不同姿勢的圖"""
    history = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "用這張原圖鎖定人物"},
                {
                    "type": "image_url",
                    "image_url": {"url": "/tmp/original-locked-ref.png"},
                },
            ],
        },
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "visual-1",
                    "function": {
                        "name": "visual_agent_generate",
                        "arguments": json.dumps(
                            {
                                "attachments": [
                                    "/tmp/original-locked-ref.png",
                                    "/tmp/generated-last-turn.png",
                                ]
                            }
                        ),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "visual-1",
            "content": json.dumps(
                {
                    "success": True,
                    "images": ["/tmp/generated-last-turn.png"],
                    "delivery_metadata": {
                        "selected_visual_artifact_ids": ["selected-last"],
                        "visual_artifacts": {
                            "/tmp/generated-last-turn.png": {
                                "artifact_id": "selected-last",
                                "kind": "image",
                            }
                        },
                    },
                }
            ),
        },
    ]

    references = _visual_reference_context_for_turn(
        prompt,
        current_attachment_paths=[],
        agent_history=history,
    )

    assert references == [
        {
            "uri": "/tmp/original-locked-ref.png",
            "role_hint": "visual_reference",
            "source": "previous_tool_reference",
        }
    ]
