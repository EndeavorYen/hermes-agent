from __future__ import annotations

import types

from agent.turn_finalizer import finalize_turn


class _FakeBudget:
    remaining = 10
    used = 0
    max_total = 10


class _FakeAgent:
    max_iterations = 20
    quiet_mode = True
    model = "grok-4.3"
    provider = "xai-oauth"
    base_url = "https://api.x.ai/v1"
    session_id = "sess-1"
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
    context_compressor = types.SimpleNamespace(last_prompt_tokens=0)
    _tool_guardrail_halt_decision = None
    _response_was_previewed = False
    _interrupt_message = None
    _skill_nudge_interval = 0
    _iters_since_skill = 0
    valid_tool_names = set()
    _stream_callback = None

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


def test_finalize_turn_applies_raphael_response_governor(monkeypatch):
    import agent.raphael.governor as governor

    monkeypatch.setattr(governor, "should_apply_raphael_response_governor", lambda: True)
    monkeypatch.setattr(
        governor,
        "apply_raphael_response_governor",
        lambda text, *, enabled: f"{text}\nRaphael governed={enabled}",
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response="Line one",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "hi"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="hi",
        original_user_message="hi",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == "Line one\nRaphael governed=True"
