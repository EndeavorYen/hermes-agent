from __future__ import annotations

import types

import agent.background_review as background_review
import agent.raphael.evolution as evolution
import run_agent as run_agent_module
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


def test_temp_home_evolution_forwards_review_contract_without_spawn_failure(
    monkeypatch,
    tmp_path,
):
    hermes_home = tmp_path / "hermes-home"
    monkeypatch.setenv("HERMES_HOME", str(hermes_home))

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
    captured: dict = {}

    monkeypatch.setattr(evolution, "decide_raphael_evolution", lambda **_kwargs: decision)
    monkeypatch.setattr(
        evolution,
        "build_raphael_evolution_review_prompt",
        lambda _decision: "CUSTOM RAPHAEL EVOLUTION PROMPT",
    )

    def fake_spawn(
        agent,
        messages_snapshot,
        review_memory=False,
        review_skills=False,
        review_prompt=None,
        review_label=None,
    ):
        captured.update(
            review_memory=review_memory,
            review_skills=review_skills,
            review_prompt=review_prompt,
            review_label=review_label,
        )
        return (lambda: None), review_prompt

    monkeypatch.setattr(background_review, "spawn_background_review_thread", fake_spawn)
    monkeypatch.setattr(run_agent_module.threading, "Thread", _ImmediateThread)

    result = finalize_turn(
        _FakeAgent(),
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
    assert captured == {
        "review_memory": False,
        "review_skills": True,
        "review_prompt": "CUSTOM RAPHAEL EVOLUTION PROMPT",
        "review_label": "Raphael evolution review",
    }
    outcomes = [record.get("status") for record in evolution.read_evolution_records()]
    assert "scheduled" in outcomes
    assert "background_spawn_failed" not in outcomes
