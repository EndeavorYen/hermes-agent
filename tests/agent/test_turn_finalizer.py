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


def _run_finalize(
    *,
    final_response: str,
    messages: list[dict] | None = None,
    user_message: str = "請幫我看一下目前狀態",
):
    return finalize_turn(
        _FakeAgent(),
        final_response=final_response,
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=messages
        or [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": final_response},
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message=user_message,
        original_user_message=user_message,
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )


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


def test_finalize_turn_blocks_completion_claim_without_required_tool_proof(monkeypatch):
    import agent.raphael.governor as governor

    monkeypatch.setattr(governor, "should_apply_raphael_response_governor", lambda: True)
    monkeypatch.setattr(
        governor,
        "apply_raphael_response_governor",
        lambda text, *, enabled: text,
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response="完成了，測試也通過。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "請修復 repo 裡的測試失敗"},
            {"role": "assistant", "content": "完成了，測試也通過。"},
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請修復 repo 裡的測試失敗",
        original_user_message="請修復 repo 裡的測試失敗",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "Raphael proof gate blocked" in result["final_response"]
    assert "failure_layer: proof_gate" in result["final_response"]
    assert "python -m pytest <focused-test-target> -q" in result["final_response"]
    assert result["raphael_proof_gate"]["status"] == "blocked"
    assert result["raphael_proof_gate"]["missing_proofs"] == [
        "focused_tests",
        "diff_hygiene",
    ]


def test_finalize_turn_records_repeated_proof_gate_failures_as_evolution_proposal(
    monkeypatch,
    tmp_path,
):
    import agent.raphael.governor as governor
    from agent.raphael.models import RaphaelState
    from agent.raphael.state import read_state, write_state

    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    monkeypatch.setattr(governor, "should_apply_raphael_response_governor", lambda: True)
    monkeypatch.setattr(
        governor,
        "apply_raphael_response_governor",
        lambda text, *, enabled: text,
    )
    write_state(RaphaelState.empty())

    first = _run_finalize(
        final_response="完成了，測試也通過。",
        user_message="請修復 repo 裡的測試失敗",
    )
    after_first = read_state()
    second = _run_finalize(
        final_response="完成了，測試也通過。",
        user_message="請修復 repo 裡的測試失敗",
    )
    after_second = read_state()

    assert first["raphael_proof_gate"]["status"] == "blocked"
    assert second["raphael_proof_gate"]["status"] == "blocked"
    assert after_first.action_proposals == ()
    assert len(after_second.action_proposals) == 1
    proposal = after_second.action_proposals[0]
    assert proposal.status == "pending"
    assert proposal.metadata["affected_capability"] == "raphael.proof_gate"
    assert proposal.metadata["recurring_signal_count"] == 2


def test_finalize_turn_allows_completion_claim_with_required_tool_proof(monkeypatch):
    import agent.raphael.governor as governor

    monkeypatch.setattr(governor, "should_apply_raphael_response_governor", lambda: True)
    monkeypatch.setattr(
        governor,
        "apply_raphael_response_governor",
        lambda text, *, enabled: text,
    )

    result = finalize_turn(
        _FakeAgent(),
        final_response="完成了，測試與 diff hygiene 都通過。",
        api_call_count=1,
        interrupted=False,
        failed=False,
        messages=[
            {"role": "user", "content": "請修復 repo 裡的測試失敗"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_pytest",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd": "python -m pytest tests/foo.py -q"}',
                        },
                    },
                    {
                        "id": "call_diff",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd": "git diff --check"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_pytest",
                "exit_code": 0,
                "content": "1 passed",
            },
            {
                "role": "tool",
                "tool_call_id": "call_diff",
                "exit_code": 0,
                "content": "",
            },
            {
                "role": "assistant",
                "content": "完成了，測試與 diff hygiene 都通過。",
            },
        ],
        conversation_history=None,
        effective_task_id="task-1",
        turn_id="turn-1",
        user_message="請修復 repo 裡的測試失敗",
        original_user_message="請修復 repo 裡的測試失敗",
        _should_review_memory=False,
        _turn_exit_reason="text_response",
    )

    assert "Raphael proof gate blocked" not in result["final_response"]
    assert result["raphael_proof_gate"]["status"] == "passed"
    assert result["raphael_proof_gate"]["missing_proofs"] == []


def test_finalize_turn_maps_claim_kind_to_distinct_required_proof(monkeypatch):
    import agent.raphael.governor as governor

    monkeypatch.setattr(governor, "should_apply_raphael_response_governor", lambda: True)
    monkeypatch.setattr(
        governor,
        "apply_raphael_response_governor",
        lambda text, *, enabled: text,
    )

    cases = (
        (
            "Runtime is working and complete.",
            ["runtime_smoke_when_live_wiring"],
            "hermes gateway status",
        ),
        ("The LLM slice is ready to ship.", ["live_llm_smoke"], "hermes chat --smoke"),
        (
            "Install is complete.",
            ["package_install_smoke"],
            "raphael package-install-smoke",
        ),
        (
            "Media delivery is complete.",
            [
                "artifact_quality_evidence",
                "selected_current_artifact_only",
                "delivery_cleanliness",
            ],
            "raphael visual-quality-review <selected-artifact>",
        ),
        (
            "The selected artifact is complete.",
            ["artifact_quality_evidence", "stale_artifact_guard"],
            "raphael visual-quality-review <selected-artifact>",
        ),
    )

    for response, required, command in cases:
        result = _run_finalize(final_response=response)

        assert result["raphael_proof_gate"]["status"] == "blocked"
        assert result["raphael_proof_gate"]["required_proofs"] == required
        assert result["raphael_proof_gate"]["next_proof_command"] == command


def test_finalize_turn_install_claim_passes_with_package_install_smoke(monkeypatch):
    import agent.raphael.governor as governor

    monkeypatch.setattr(governor, "should_apply_raphael_response_governor", lambda: True)
    monkeypatch.setattr(
        governor,
        "apply_raphael_response_governor",
        lambda text, *, enabled: text,
    )

    result = _run_finalize(
        final_response="Install is complete.",
        messages=[
            {"role": "user", "content": "請確認 install"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_install",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd": "raphael package-install-smoke"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_install",
                "exit_code": 0,
                "content": "package install smoke passed",
            },
            {"role": "assistant", "content": "Install is complete."},
        ],
    )

    assert result["raphael_proof_gate"]["status"] == "passed"
    assert result["raphael_proof_gate"]["missing_proofs"] == []


def test_finalize_turn_media_claim_passes_with_artifact_delivery_proofs(monkeypatch):
    import agent.raphael.governor as governor

    monkeypatch.setattr(governor, "should_apply_raphael_response_governor", lambda: True)
    monkeypatch.setattr(
        governor,
        "apply_raphael_response_governor",
        lambda text, *, enabled: text,
    )

    result = _run_finalize(
        final_response="Media delivery is complete.",
        messages=[
            {"role": "user", "content": "請確認 media"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_quality",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd": "raphael visual-quality-review selected.png"}',
                        },
                    },
                    {
                        "id": "call_artifact",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd": "raphael artifact verify-current image-1"}',
                        },
                    },
                    {
                        "id": "call_delivery",
                        "function": {
                            "name": "exec_command",
                            "arguments": '{"cmd": "raphael delivery-audit image-1"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_quality",
                "exit_code": 0,
                "content": "artifact quality evidence passed",
            },
            {
                "role": "tool",
                "tool_call_id": "call_artifact",
                "exit_code": 0,
                "content": "selected current artifact verified",
            },
            {
                "role": "tool",
                "tool_call_id": "call_delivery",
                "exit_code": 0,
                "content": "delivery cleanliness passed",
            },
            {"role": "assistant", "content": "Media delivery is complete."},
        ],
    )

    assert result["raphael_proof_gate"]["status"] == "passed"
    assert result["raphael_proof_gate"]["missing_proofs"] == []
