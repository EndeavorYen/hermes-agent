from __future__ import annotations

import json
from types import SimpleNamespace


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
    valid_tool_names = {"visual_agent_generate"}
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


def test_run_conversation_executes_direct_visual_handoff_before_base_llm(monkeypatch):
    import agent.conversation_loop as conversation_loop
    from agent.visual.agent_mode import handoff as handoff_module
    from tools.registry import registry

    agent = _FakeAgent()
    dispatched = {}

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
        )

    def fake_dispatch(name, args, **_kwargs):
        dispatched["name"] = name
        dispatched["args"] = dict(args)
        return json.dumps(
            {
                "success": True,
                "package_status": "completed",
                "images": ["/tmp/current-composition.png"],
                "videos": [],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(conversation_loop, "build_turn_context", fake_build_turn_context)
    monkeypatch.setattr(
        handoff_module,
        "_raphael_handoff_control_enabled",
        lambda: False,
    )
    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    result = conversation_loop.run_conversation(agent, "ignored by fake context")

    assert result["api_calls"] == 0
    assert result["turn_exit_reason"] == "direct_visual_agent_handoff"
    assert result["final_response"] == "已產出圖片。"
    assert dispatched["name"] == "visual_agent_generate"
    assert dispatched["args"]["include_image"] is True
    assert dispatched["args"]["include_video"] is False
    assert dispatched["args"]["image_provider"] == "openai-codex"
    assert dispatched["args"]["candidate_budget"] == 4
    tool_turns = [msg for msg in result["messages"] if msg.get("tool_calls")]
    assert len(tool_turns) == 1
    assert tool_turns[0]["tool_calls"][0]["function"]["name"] == "visual_agent_generate"
    tool_results = [msg for msg in result["messages"] if msg.get("role") == "tool"]
    assert len(tool_results) == 1
    payload = json.loads(tool_results[0]["content"])
    assert payload["direct_visual_agent_handoff"]["mode"] == "pre_llm_direct"


def test_codex_app_server_executes_direct_xai_handoff_before_runtime(monkeypatch):
    import agent.conversation_loop as conversation_loop
    from agent.visual.agent_mode import handoff as handoff_module
    from tools.registry import registry

    agent = _FakeAgent()
    agent.api_mode = "codex_app_server"
    dispatched = {}

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
        return json.dumps(
            {
                "success": True,
                "package_status": "completed",
                "images": ["/tmp/current-xai.png"],
                "videos": [],
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(conversation_loop, "build_turn_context", fake_build_turn_context)
    monkeypatch.setattr(handoff_module, "_raphael_handoff_control_enabled", lambda: False)
    monkeypatch.setattr(registry, "dispatch", fake_dispatch)

    result = conversation_loop.run_conversation(agent, "ignored by fake context")

    assert result["api_calls"] == 0
    assert result["turn_exit_reason"] == "direct_visual_agent_handoff"
    assert dispatched["name"] == "visual_agent_generate"
    assert dispatched["args"]["image_provider"] == "xai"
    assert dispatched["args"]["candidate_budget"] == 4


def test_codex_app_server_routes_slack_regenerate_output_through_visual_tool(monkeypatch):
    import agent.conversation_loop as conversation_loop
    from gateway.session_context import reset_visual_reference_context, set_visual_reference_context
    from tools.registry import registry

    agent = _FakeAgent()
    agent.api_mode = "codex_app_server"
    dispatched = {}

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
            raphael_decision={
                "mode": "visual_agent_generation",
                "completion_policy": "visual",
                "route": {},
                "runtime_contract": {},
            },
        )

    def fake_dispatch(name, args, **_kwargs):
        dispatched["name"] = name
        dispatched["args"] = dict(args)
        return json.dumps(
            {
                "success": True,
                "package_status": "completed",
                "images": ["/tmp/current-regenerated.png"],
                "videos": [],
                "selected_artifact": "/tmp/current-regenerated.png",
            },
            ensure_ascii=False,
        )

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
    assert dispatched["name"] == "visual_agent_generate"
    assert dispatched["args"]["image_provider"] == "xai"
    assert dispatched["args"]["attachments"] == ["/tmp/locked-character.png"]
    assert dispatched["args"]["candidate_budget"] == 4
    tool_results = [msg for msg in result["messages"] if msg.get("role") == "tool"]
    assert len(tool_results) == 1
    payload = json.loads(tool_results[0]["content"])
    assert payload["selected_artifact"] == "/tmp/current-regenerated.png"
    assert payload["direct_visual_agent_handoff"]["mode"] == "pre_llm_direct"


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
