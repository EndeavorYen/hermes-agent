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
    model = "gpt-5.5"
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
