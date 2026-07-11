from __future__ import annotations

import types

import agent.background_review as background_review
import agent.raphael.evolution as evolution
import hermes_cli.config as hermes_config
import hermes_cli.plugins as hermes_plugins
import run_agent as run_agent_module
from agent.raphael.skill_trace import read_skill_traces
from agent.turn_finalizer import finalize_turn
from run_agent import AIAgent


class _FakeBudget:
    remaining = 10
    used = 0
    max_total = 10


class _ImmediateThread:
    def __init__(self, *, target, daemon=None, name=None):
        self._target = target

    def start(self):
        self._target()


class _FakeAgent:
    max_iterations = 20
    quiet_mode = True
    model = "test-model"
    provider = "test-provider"
    base_url = ""
    session_id = "sess-1"
    platform = "cli"
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
    valid_tool_names = {"skill_manage"}
    _stream_callback = None
    _spawn_background_review = AIAgent._spawn_background_review

    def __init__(self):
        self._credential_pool = None
        self._memory_store = object()
        self._memory_enabled = True
        self._user_profile_enabled = False
        self._cached_system_prompt = "cached prompt"
        self.session_start = None
        self.enabled_toolsets = None
        self.disabled_toolsets = None
        self.memory_notifications = "on"
        self.safe_prints: list[str] = []
        self.background_callbacks: list[str] = []
        self.background_review_callback = self.background_callbacks.append

    def _current_main_runtime(self):
        return {
            "api_key": None,
            "base_url": self.base_url,
            "api_mode": None,
        }

    def _safe_print(self, *args, **_kwargs):
        self.safe_prints.append(" ".join(str(item) for item in args))

    def _emit_auxiliary_failure(self, label, error):
        raise AssertionError(f"unexpected {label}: {error}")

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


def _active_raphael_config():
    return {
        "plugins": {"enabled": ["raphael"], "disabled": []},
        "raphael": {
            "enabled": True,
            "mode": "sage_king",
            "skill_writes_enabled": True,
            "memory_writes_enabled": False,
            "evolution": {
                "enabled": True,
                "skill_review_enabled": True,
                "memory_review_enabled": True,
            },
        },
    }


def test_temp_home_evolution_forwards_review_contract_without_spawn_failure(
    monkeypatch,
    tmp_path,
):
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(
        hermes_config,
        "load_config_readonly",
        lambda: _active_raphael_config(),
    )

    decision = evolution.RaphaelEvolutionDecision(
        should_review=True,
        review_skills=True,
        review_memory=False,
        proposal_only=False,
        mode="active_evolution",
        reason_codes=("user_correction",),
        evidence_summary="user corrected Raphael behavior",
        review_label="Raphael evolution review",
        risk_level="R1",
        user_message_preview="不對，要主動進化",
    )
    review_prompts: list[str] = []

    monkeypatch.setattr(evolution, "decide_raphael_evolution", lambda **_kwargs: decision)
    monkeypatch.setattr(
        evolution,
        "build_raphael_evolution_review_prompt",
        lambda _decision: "CUSTOM RAPHAEL EVOLUTION PROMPT",
    )

    class FakeReviewAgent:
        def __init__(self, **_kwargs):
            self._session_messages = []

        def run_conversation(self, **kwargs):
            review_prompts.append(kwargs["user_message"])
            self._session_messages = [
                {
                    "role": "tool",
                    "tool_call_id": "call_review",
                    "content": (
                        '{"success": true, "message": "Skill updated", '
                        '"target": "skill"}'
                    ),
                }
            ]

        def shutdown_memory_provider(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(run_agent_module, "AIAgent", FakeReviewAgent)
    monkeypatch.setattr(run_agent_module.threading, "Thread", _ImmediateThread)

    agent = _FakeAgent()
    result = finalize_turn(
        agent,
        final_response="收到，我會修正",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "不對，要主動進化"}],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="不對，要主動進化",
        original_user_message="不對，要主動進化",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == "收到，我會修正"
    assert review_prompts
    assert review_prompts[0].startswith("CUSTOM RAPHAEL EVOLUTION PROMPT")
    assert agent.safe_prints == ["  💾 Raphael evolution review: Skill updated"]
    assert agent.background_callbacks == ["💾 Raphael evolution review: Skill updated"]
    outcomes = [record.get("status") for record in evolution.read_evolution_records()]
    assert "scheduled" in outcomes
    assert "background_spawn_failed" not in outcomes


def test_disabled_raphael_uses_readonly_gate_without_loading_evolution_stack(
    monkeypatch,
):
    calls: list[str] = []
    disabled = {
        "plugins": {"enabled": [], "disabled": ["raphael"]},
        "raphael": {"enabled": False},
    }
    monkeypatch.setattr(
        hermes_config,
        "load_config_readonly",
        lambda: calls.append("readonly") or disabled,
    )
    monkeypatch.setattr(
        hermes_config,
        "load_config",
        lambda: calls.append("deepcopy") or disabled,
    )
    monkeypatch.setattr(
        evolution,
        "decide_raphael_evolution",
        lambda **_kwargs: calls.append("evolution"),
    )
    monkeypatch.setattr(hermes_plugins, "invoke_hook", lambda *_args, **_kwargs: None)

    result = finalize_turn(
        _FakeAgent(),
        final_response="done",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "hello"}],
        conversation_history=None,
        effective_task_id="task-disabled",
        turn_id="turn-disabled",
        user_message="hello",
        original_user_message="hello",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert result["final_response"] == "done"
    assert calls == ["readonly"]


def test_real_turn_finalizer_blocks_unverified_mutation_before_persistence(
    monkeypatch,
):
    monkeypatch.setattr(hermes_plugins, "invoke_hook", lambda *_args, **_kwargs: [])
    agent = _FakeAgent()
    persisted = []
    agent._persist_session = lambda persisted_messages, _history: persisted.append(
        [dict(message) for message in persisted_messages]
    )
    messages = [
        {"role": "user", "content": "修正問題"},
        {"role": "assistant", "content": "完成了，測試都通過。"},
    ]

    result = finalize_turn(
        agent,
        final_response="完成了，測試都通過。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=messages,
        conversation_history=None,
        effective_task_id="task-proof-gate",
        turn_id="turn-proof-gate",
        user_message="修正問題",
        original_user_message="修正問題",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
        raphael_decision={
            "turn_id": "turn-proof-gate",
            "mode": "tool_task",
            "completion_policy": "mutation",
            "evidence": {"required_proofs": ["focused_tests"]},
            "next_action": "run focused verification",
        },
    )

    assert result["raphael_finalization"]["status"] == (
        "blocked_unverified_completion"
    )
    assert "尚缺驗證" in result["final_response"]
    assert messages[-1]["content"] == result["final_response"]
    persisted_messages = persisted[-1]
    assert persisted_messages[-1]["content"] == result["final_response"]


def test_background_spawn_error_is_sanitized_before_persistent_records(
    monkeypatch,
    tmp_path,
):
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(
        hermes_config,
        "load_config_readonly",
        lambda: _active_raphael_config(),
    )
    decision = evolution.RaphaelEvolutionDecision(
        should_review=True,
        review_skills=True,
        review_memory=False,
        proposal_only=False,
        mode="active_evolution",
        reason_codes=("user_correction",),
        evidence_summary="user corrected behavior",
    )
    monkeypatch.setattr(evolution, "decide_raphael_evolution", lambda **_kwargs: decision)
    secret = "sk-" + "secret1234567890"
    raw_error = (
        f"provider failed at /Users/example/private/trace.json with {secret}\n"
        + "x" * 500
    )
    agent = _FakeAgent()

    def fail_spawn(**_kwargs):
        raise RuntimeError(raw_error)

    agent._spawn_background_review = fail_spawn
    finalize_turn(
        agent,
        final_response="I will correct it",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[{"role": "user", "content": "不對"}],
        conversation_history=None,
        effective_task_id="task-error",
        turn_id="turn-error",
        user_message="不對",
        original_user_message="不對",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    failed_record = next(
        record
        for record in reversed(evolution.read_evolution_records())
        if record["status"] == "background_spawn_failed"
    )
    failed_trace = next(
        trace
        for trace in reversed(read_skill_traces())
        if trace.outcome == "background_spawn_failed"
    )
    persisted_errors = (
        failed_record["metadata"]["error"],
        failed_trace.metadata["error"],
    )
    for persisted_error in persisted_errors:
        assert secret not in persisted_error
        assert "/Users/example/private/trace.json" not in persisted_error
        assert "\n" not in persisted_error
        assert len(persisted_error) <= 240


def test_review_label_is_single_line_redacted_and_bounded():
    secret = "sk-" + "secret1234567890"
    label = f" Raphael\nreview {secret} " + "x" * 200

    sanitized = background_review._sanitize_review_label(label)

    assert "\n" not in sanitized
    assert secret not in sanitized
    assert len(sanitized) <= 80
