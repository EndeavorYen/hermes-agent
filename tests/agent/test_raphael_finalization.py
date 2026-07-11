from agent.raphael.finalization import enforce_raphael_completion


def _tool_task_decision(*, required=("focused_tests",)):
    return {
        "turn_id": "turn-finalization",
        "mission_id": "mission-finalization",
        "mode": "tool_task",
        "completion_policy": "mutation",
        "evidence": {"required_proofs": list(required)},
        "next_action": "run focused verification",
    }


def test_tool_task_completion_is_blocked_without_focused_test_evidence():
    result = enforce_raphael_completion(
        decision=_tool_task_decision(),
        final_response="完成了，測試都通過。",
        messages=(),
    )

    assert result.status == "blocked_unverified_completion"
    assert result.missing_proofs == ("focused_tests",)
    assert "尚缺驗證" in result.final_response


def test_informational_response_is_unchanged_without_proof():
    response = "這個模組負責將請求路由到工具。"

    result = enforce_raphael_completion(
        decision=_tool_task_decision(),
        final_response=response,
        messages=(),
    )

    assert result.status == "no_completion_claim"
    assert result.final_response == response


def test_tool_task_completion_passes_with_real_focused_test_evidence():
    response = "完成了，測試已通過。"
    messages = (
        {
            "role": "tool",
            "name": "exec_command",
            "exit_code": 0,
            "content": "python -m pytest tests/foo.py -q\n1 passed",
        },
    )

    result = enforce_raphael_completion(
        decision=_tool_task_decision(),
        final_response=response,
        messages=messages,
    )

    assert result.status == "passed"
    assert result.final_response == response
    assert result.available_proofs == ("focused_tests",)
