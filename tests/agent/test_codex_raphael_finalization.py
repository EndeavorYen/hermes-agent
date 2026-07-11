from tests.agent.test_codex_app_server_persist import _make_agent

from agent.codex_runtime import run_codex_app_server_turn


def test_codex_runtime_uses_same_completion_gate():
    agent = _make_agent(session_db=None)
    agent._codex_session.run_turn.return_value.final_text = "完成了，測試都通過。"
    agent._codex_session.run_turn.return_value.projected_messages = [
        {"role": "assistant", "content": "完成了，測試都通過。"}
    ]

    result = run_codex_app_server_turn(
        agent,
        user_message="修正問題",
        original_user_message="修正問題",
        messages=[{"role": "user", "content": "修正問題"}],
        effective_task_id="task-codex-raphael",
        turn_id="turn-codex-raphael",
        raphael_decision={
            "turn_id": "turn-codex-raphael",
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
    assert result["messages"][-1]["content"] == result["final_response"]
