import json
from argparse import Namespace

import pytest

from hermes_cli.loop import (
    _stable_goal_id,
    decide_continuation_for_session,
    verify_progress_for_session,
    loop_command,
    loop_run_command,
    loop_list_command,
    loop_status_command,
    loop_pause_command,
    loop_resume_command,
    loop_stop_command,
)
from hermes_cli.main import cmd_loop, cmd_loop_run, cmd_loop_list, cmd_loop_status, cmd_loop_pause, cmd_loop_resume, cmd_loop_stop
from hermes_loop.store import LoopStore


class _FakeSessionDB:
    def __init__(self, *args, **kwargs):
        self.closed = False

    def get_session(self, session_id):
        if session_id != "sess-1":
            return None
        return {
            "id": "sess-1",
            "model": "test-model",
            "model_config": json.dumps({"provider": "openai-codex", "base_url": "https://example.invalid/v1"}),
            "title": "Test Session",
        }

    def get_messages_as_conversation(self, session_id):
        return [
            {"role": "user", "content": "initial goal"},
            {"role": "assistant", "content": "initial answer"},
        ]

    def search_sessions(self, source=None, limit=1):
        return [{"id": "sess-1"}]

    def close(self):
        self.closed = True


class _DecisionAgent:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        _DecisionAgent.instances.append(self)

    def run_conversation(self, user_message, conversation_history=None, task_id=None):
        self.calls.append({
            "user_message": user_message,
            "conversation_history": conversation_history,
            "task_id": task_id,
        })
        if len(_DecisionAgent.instances) == 1:
            return {"final_response": json.dumps({"action": "stop", "reason": "done"})}
        return {"final_response": "should not run"}


class _ContinueAgent:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        _ContinueAgent.instances.append(self)

    def run_conversation(self, user_message, conversation_history=None, task_id=None):
        self.calls.append({
            "user_message": user_message,
            "conversation_history": conversation_history,
            "task_id": task_id,
        })
        if len(_ContinueAgent.instances) == 1:
            return {
                "final_response": json.dumps(
                    {
                        "action": "continue",
                        "reason": "clear next slice",
                        "next_prompt": "Implement the next thin slice.",
                        "expected_evidence": "tests/foo.py",
                    }
                )
            }
        return {"final_response": "Implemented the next thin slice. See tests/foo.py."}


class _ExpectedEvidenceAgent:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        _ExpectedEvidenceAgent.instances.append(self)

    def run_conversation(self, user_message, conversation_history=None, task_id=None):
        self.calls.append({
            "user_message": user_message,
            "conversation_history": conversation_history,
            "task_id": task_id,
        })
        return {
            "final_response": json.dumps(
                {
                    "action": "continue",
                    "reason": "clear next slice",
                    "next_prompt": "Implement the next thin slice.",
                    "expected_evidence": "tests/foo.py",
                }
            )
        }


class _WaitAgent:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        _WaitAgent.instances.append(self)

    def run_conversation(self, user_message, conversation_history=None, task_id=None):
        self.calls.append({
            "user_message": user_message,
            "conversation_history": conversation_history,
            "task_id": task_id,
        })
        return {
            "final_response": json.dumps(
                {
                    "action": "wait",
                    "reason": "wait for a bounded retry window",
                    "next_prompt": "Resume once the wake window opens.",
                    "wake_after": "5m",
                    "expected_evidence": "tests/bar.py",
                }
            )
        }


def _make_args(**overrides):
    defaults = {
        "loop_command": "once",
        "goal": "Continue improving phase2/3 runtime behavior.",
        "resume": "sess-1",
        "continue_last": None,
        "dry_run": False,
        "model": None,
        "provider": None,
        "max_turns": None,
        "max_cycles": 1,
        "max_runs": 3,
    }
    defaults.update(overrides)
    return Namespace(**defaults)


def _last_json_line(text):
    lines = [line for line in text.splitlines() if line.strip()]
    return json.loads(lines[-1])


def _read_background_reviews(tmp_path):
    path = tmp_path / "logs" / "background_reviews.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_loop_command_stop_path(monkeypatch, capsys, tmp_path):
    _DecisionAgent.instances = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _DecisionAgent)

    result = loop_command(_make_args())

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "Decision: stop" in out
    assert "done" in out
    assert len(_DecisionAgent.instances) == 1
    assert result["outcome"] == "stopped"
    assert result["stop_reason"] == "model_stop"
    assert result["exit_code"] == 0
    assert summary["outcome"] == "stopped"
    assert summary["stop_reason"] == "model_stop"
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "stop"
    assert reviews[-1]["stop_reason"] == "model_stop"


def test_decide_continuation_for_session_returns_session_scoped_decision(monkeypatch, tmp_path):
    _DecisionAgent.instances = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _DecisionAgent)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs" / "background_reviews.jsonl").write_text(
        json.dumps({
            "session_id": "sess-1",
            "source": "bounded_loop",
            "goal_id": _stable_goal_id("sess-1", "Keep going"),
            "progress_state": "meaningful_result",
            "result_preview": "prior review preview",
        }) + "\n",
        encoding="utf-8",
    )

    result = decide_continuation_for_session("sess-1", "Keep going")

    assert result["action"] == "stop"
    assert result["stop_reason"] == "model_stop"
    assert result["session_id"] == "sess-1"
    assert len(_DecisionAgent.instances) == 1
    assert _DecisionAgent.instances[0].kwargs["enabled_toolsets"] == []
    decision_prompt = _DecisionAgent.instances[0].calls[0]["user_message"]
    assert "recent_history" in decision_prompt
    assert "initial goal" in decision_prompt
    assert "initial answer" in decision_prompt
    assert "prior review preview" in decision_prompt


def test_verify_progress_for_session_returns_scoped_verdict(monkeypatch, tmp_path):
    class _VerifierAgent(_DecisionAgent):
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _VerifierAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({"user_message": user_message})
            return {"final_response": json.dumps({"verdict": "stalled", "reason": "Mostly restated status.", "should_continue": False})}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _VerifierAgent)

    result = verify_progress_for_session("sess-1", "Keep going", "Latest response")

    assert result["verdict"] == "stalled"
    assert result["should_continue"] is False
    assert len(_VerifierAgent.instances) == 1
    verifier_prompt = _VerifierAgent.instances[0].calls[0]["user_message"]
    assert "latest_final_response" in verifier_prompt
    assert "Latest response" in verifier_prompt


def test_decide_continuation_for_session_continue_without_expected_evidence_fails_closed(monkeypatch, tmp_path):
    class _MissingExpectedEvidenceAgent(_DecisionAgent):
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _MissingExpectedEvidenceAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({"user_message": user_message})
            return {
                "final_response": json.dumps(
                    {
                        "action": "continue",
                        "reason": "clear next slice",
                        "next_prompt": "Implement the next thin slice.",
                    }
                )
            }

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _MissingExpectedEvidenceAgent)

    result = decide_continuation_for_session("sess-1", "Keep going")

    assert result["action"] == "stop"
    assert result["stop_reason"] == "missing_expected_evidence"
    assert "expected evidence" in result["reason"].lower()


def test_decide_continuation_for_session_preserves_expected_evidence(monkeypatch, tmp_path):
    _ExpectedEvidenceAgent.instances = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _ExpectedEvidenceAgent)

    result = decide_continuation_for_session("sess-1", "Keep going")

    assert result["action"] == "continue"
    assert result["expected_evidence"] == "tests/foo.py"


def test_decide_continuation_for_session_wait_without_wake_after_fails_closed(monkeypatch, tmp_path):
    class _MissingWakeAfterAgent(_DecisionAgent):
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _MissingWakeAfterAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({"user_message": user_message})
            return {
                "final_response": json.dumps(
                    {
                        "action": "wait",
                        "reason": "wait for external signal",
                        "next_prompt": "Resume after wake.",
                        "expected_evidence": "tests/foo.py",
                    }
                )
            }

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _MissingWakeAfterAgent)

    result = decide_continuation_for_session("sess-1", "Keep going")

    assert result["action"] == "stop"
    assert result["stop_reason"] == "missing_wake_after"
    assert "wake_after" in result["reason"]



def test_decide_continuation_for_session_wait_preserves_deferred_fields(monkeypatch, tmp_path):
    class _WaitAgent(_DecisionAgent):
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _WaitAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({"user_message": user_message})
            return {
                "final_response": json.dumps(
                    {
                        "action": "wait",
                        "reason": "wait for a bounded retry window",
                        "next_prompt": "Resume once the wake window opens.",
                        "wake_after": "5m",
                        "expected_evidence": "tests/bar.py",
                    }
                )
            }

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _WaitAgent)

    result = decide_continuation_for_session("sess-1", "Keep going")

    assert result["action"] == "wait"
    assert result["wake_after"] == "5m"
    assert result["next_prompt"] == "Resume once the wake window opens."
    assert result["expected_evidence"] == "tests/bar.py"



def test_verify_progress_for_session_prompt_includes_expected_evidence(monkeypatch, tmp_path):
    class _VerifierAgent(_DecisionAgent):
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _VerifierAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({"user_message": user_message})
            return {"final_response": json.dumps({"verdict": "progress", "reason": "real progress", "should_continue": True})}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _VerifierAgent)

    result = verify_progress_for_session(
        "sess-1",
        "Keep going",
        "Latest response with tests/foo.py",
        expected_evidence="tests/foo.py",
    )

    assert result["verdict"] == "progress"
    verifier_prompt = _VerifierAgent.instances[0].calls[0]["user_message"]
    assert "expected_evidence" in verifier_prompt
    assert "tests/foo.py" in verifier_prompt


def test_verify_progress_for_session_invalid_payload_fails_closed(monkeypatch, tmp_path):
    class _BadVerifierAgent(_DecisionAgent):
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _BadVerifierAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({"user_message": user_message})
            return {"final_response": "not valid json"}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _BadVerifierAgent)

    result = verify_progress_for_session("sess-1", "Keep going", "Latest response")

    assert result["verdict"] == "stalled"
    assert result["should_continue"] is False
    assert result["stop_reason"] == "invalid_progress_verifier_payload"
    assert "invalid verifier payload" in result["reason"].lower()


def test_loop_command_continue_executes_one_step(monkeypatch, capsys, tmp_path):
    _ContinueAgent.instances = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _ContinueAgent)

    result = loop_command(_make_args())

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "Decision: continue" in out
    assert "Implemented the next thin slice." in out
    assert len(_ContinueAgent.instances) == 2
    assert _ContinueAgent.instances[1].calls[0]["user_message"] == "Implement the next thin slice."
    assert _ContinueAgent.instances[1].calls[0]["conversation_history"][0]["content"] == "initial goal"
    assert result["outcome"] == "continued"
    assert result["stop_reason"] == "max_cycles_reached"
    assert result["executed"] is True
    assert result["cycles_completed"] == 1
    assert summary["outcome"] == "continued"
    assert summary["stop_reason"] == "max_cycles_reached"
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "max_cycles"
    assert reviews[-2]["progress_state"] == "meaningful_result"
    assert reviews[-1]["goal_id"] == reviews[-2]["goal_id"]
    assert reviews[-1]["run_id"] == reviews[-2]["run_id"]


def test_loop_command_malformed_decision_defaults_stop(monkeypatch, capsys, tmp_path):
    class _BadDecisionAgent(_DecisionAgent):
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _BadDecisionAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({"user_message": user_message})
            return {"final_response": "not json at all"}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _BadDecisionAgent)

    result = loop_command(_make_args())

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "Decision: stop" in out
    assert "invalid decision payload" in out.lower()
    assert result["outcome"] == "error"
    assert result["stop_reason"] == "invalid_decision_payload"
    assert result["exit_code"] == 1
    assert summary["outcome"] == "error"
    assert summary["stop_reason"] == "invalid_decision_payload"


def test_decide_continuation_for_session_handles_missing_session(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)

    result = decide_continuation_for_session("missing-session", "Keep going")

    assert result["action"] == "stop"
    assert result["stop_reason"] == "session_not_found"
    assert "missing-session" in result["reason"]


def test_loop_command_wait_returns_structured_waiting_result(monkeypatch, capsys, tmp_path):
    _WaitAgent.instances = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _WaitAgent)

    result = loop_command(_make_args())

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "Decision: wait" in out
    assert "Wake after: 5m" in out
    assert "Resume once the wake window opens." in out
    assert len(_WaitAgent.instances) == 1
    assert result["outcome"] == "waiting"
    assert result["stop_reason"] == "wait_requested"
    assert result["wake_after"] == "5m"
    assert result["next_prompt"] == "Resume once the wake window opens."
    assert result["expected_evidence"] == "tests/bar.py"
    assert result["executed"] is False
    assert summary["outcome"] == "waiting"
    assert summary["wake_after"] == "5m"
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "wait"
    assert reviews[-1]["stop_reason"] == "wait_requested"


def test_loop_command_dry_run_skips_execution(monkeypatch, capsys, tmp_path):
    _ContinueAgent.instances = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _ContinueAgent)

    result = loop_command(_make_args(dry_run=True))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "Decision: continue" in out
    assert "Dry run" in out
    assert result["outcome"] == "dry_run"
    assert result["executed"] is False
    assert result["stop_reason"] == "dry_run"
    assert summary["outcome"] == "dry_run"


def test_loop_command_honors_max_cycles(monkeypatch, capsys, tmp_path):
    class _MultiCycleAgent:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _MultiCycleAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({
                "user_message": user_message,
                "conversation_history": conversation_history,
                "task_id": task_id,
            })
            if len(_MultiCycleAgent.instances) == 1:
                return {"final_response": json.dumps({"action": "continue", "reason": "step 1", "next_prompt": "Do step 1", "expected_evidence": "tests/foo.py"})}
            if len(_MultiCycleAgent.instances) == 2:
                return {"final_response": "Did step 1 (tests/foo.py)"}
            return {"final_response": json.dumps({"action": "stop", "reason": "done"})}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _MultiCycleAgent)

    result = loop_command(_make_args(max_cycles=2))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "Cycle 1/2" in out
    assert "Cycle 2/2" in out
    assert "Did step 1" in out
    assert "Decision: stop" in out
    assert result["cycles_attempted"] == 2
    assert result["cycles_completed"] == 1
    assert result["outcome"] == "stopped"
    assert result["stop_reason"] == "model_stop"
    assert summary["cycles_attempted"] == 2


def test_loop_command_stops_on_empty_continuation_result(monkeypatch, capsys, tmp_path):
    class _EmptyResultAgent:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _EmptyResultAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({
                "user_message": user_message,
                "conversation_history": conversation_history,
                "task_id": task_id,
            })
            if len(_EmptyResultAgent.instances) == 1:
                return {"final_response": json.dumps({"action": "continue", "reason": "step 1", "next_prompt": "Do step 1", "expected_evidence": "tests/foo.py"})}
            return {"final_response": "   "}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _EmptyResultAgent)

    result = loop_command(_make_args())

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "no visible result" in out.lower()
    assert result["outcome"] == "stopped"
    assert result["stop_reason"] == "empty_continuation_result"
    assert summary["stop_reason"] == "empty_continuation_result"
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "empty_result"
    assert reviews[-1]["stop_reason"] == "empty_continuation_result"


def test_loop_command_stops_on_duplicate_result_preview(monkeypatch, capsys, tmp_path):
    class _DuplicateResultAgent:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _DuplicateResultAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({
                "user_message": user_message,
                "conversation_history": conversation_history,
                "task_id": task_id,
            })
            if len(_DuplicateResultAgent.instances) == 1:
                return {"final_response": json.dumps({"action": "continue", "reason": "step 1", "next_prompt": "Do step 1", "expected_evidence": "tests/foo.py"})}
            if len(_DuplicateResultAgent.instances) == 2:
                return {"final_response": "Repeated summary tests/foo.py"}
            if len(_DuplicateResultAgent.instances) == 3:
                return {"final_response": json.dumps({"action": "continue", "reason": "step 2", "next_prompt": "Do step 2", "expected_evidence": "tests/foo.py"})}
            return {"final_response": "Repeated summary tests/foo.py"}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _DuplicateResultAgent)

    result = loop_command(_make_args(max_cycles=4))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "no meaningful new result preview" in out.lower()
    assert result["outcome"] == "stopped"
    assert result["stop_reason"] == "duplicate_result_preview"
    assert summary["stop_reason"] == "duplicate_result_preview"
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "duplicate_result"
    assert reviews[-1]["stop_reason"] == "duplicate_result_preview"


def test_loop_command_stops_on_missing_observable_evidence(monkeypatch, capsys, tmp_path):
    class _SelfReportOnlyAgent:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _SelfReportOnlyAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({
                "user_message": user_message,
                "conversation_history": conversation_history,
                "task_id": task_id,
            })
            if len(_SelfReportOnlyAgent.instances) == 1:
                return {"final_response": json.dumps({"action": "continue", "reason": "step 1", "next_prompt": "Do step 1", "expected_evidence": "tests/foo.py"})}
            return {"final_response": "Great, I implemented and verified the change. Done."}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _SelfReportOnlyAgent)

    result = loop_command(_make_args(max_cycles=2))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "no observable evidence" in out.lower()
    assert result["outcome"] == "stopped"
    assert result["stop_reason"] == "missing_observable_evidence"
    assert summary["stop_reason"] == "missing_observable_evidence"
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "missing_observable_evidence"
    assert reviews[-1]["stop_reason"] == "missing_observable_evidence"


def test_loop_command_stops_on_repeated_next_prompt(monkeypatch, capsys, tmp_path):
    class _RepeatPromptAgent:
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _RepeatPromptAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({
                "user_message": user_message,
                "conversation_history": conversation_history,
                "task_id": task_id,
            })
            if len(_RepeatPromptAgent.instances) == 1:
                return {"final_response": json.dumps({"action": "continue", "reason": "step 1", "next_prompt": "Do step 1", "expected_evidence": "tests/foo.py"})}
            if len(_RepeatPromptAgent.instances) == 2:
                return {"final_response": "Did step 1 tests/foo.py"}
            return {"final_response": json.dumps({"action": "continue", "reason": "still thinks step 1", "next_prompt": "  do   STEP 1  ", "expected_evidence": "tests/foo.py"})}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _RepeatPromptAgent)

    result = loop_command(_make_args(max_cycles=3))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "Cycle 2/3" in out
    assert "stall suppression" in out.lower()
    assert len(_RepeatPromptAgent.instances) == 3
    assert result["outcome"] == "stopped"
    assert result["stop_reason"] == "repeated_next_prompt"
    assert result["cycles_completed"] == 1
    assert summary["stop_reason"] == "repeated_next_prompt"
    reviews = _read_background_reviews(tmp_path)
    assert reviews[-1]["progress_state"] == "repeated_prompt"
    assert reviews[-1]["stop_reason"] == "repeated_next_prompt"


def test_background_reviews_filtered_by_goal_id(monkeypatch, tmp_path):
    """Reviews that carry a different goal_id are excluded from the decision context."""
    from hermes_cli.loop import _stable_goal_id

    _DecisionAgent.instances = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _DecisionAgent)

    reviews_path = tmp_path / "logs" / "background_reviews.jsonl"
    reviews_path.parent.mkdir(parents=True, exist_ok=True)

    # Review from a different goal on the same session — must be excluded.
    other_goal_id = _stable_goal_id("sess-1", "Completely different goal")
    reviews_path.write_text(
        json.dumps({
            "session_id": "sess-1",
            "source": "bounded_loop",
            "goal": "Completely different goal",
            "goal_id": other_goal_id,
            "progress_state": "meaningful_result",
            "result_preview": "secret-cross-goal-data",
        }) + "\n",
        encoding="utf-8",
    )

    decide_continuation_for_session("sess-1", "Keep going")

    assert len(_DecisionAgent.instances) == 1
    decision_prompt = _DecisionAgent.instances[0].calls[0]["user_message"]
    assert "secret-cross-goal-data" not in decision_prompt


def test_cmd_loop_raises_system_exit_for_error(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.loop.loop_command",
        lambda args: {"exit_code": 1, "outcome": "error", "stop_reason": "invalid_decision_payload"},
    )

    with pytest.raises(SystemExit) as excinfo:
        cmd_loop(Namespace())

    assert excinfo.value.code == 1


def test_cmd_loop_does_not_raise_on_success(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.loop.loop_command",
        lambda args: {"exit_code": 0, "outcome": "stopped", "stop_reason": "model_stop"},
    )

    cmd_loop(Namespace())


def test_loop_run_command_repeats_until_terminal_stop(monkeypatch, capsys):
    results = [
        {"session_id": "sess-1", "goal": "g", "outcome": "continued", "stop_reason": "max_cycles_reached", "exit_code": 0},
        {"session_id": "sess-1", "goal": "g", "outcome": "stopped", "stop_reason": "model_stop", "exit_code": 0},
    ]
    calls = []

    def _fake_loop_once(args):
        calls.append(args.max_cycles)
        return results[len(calls) - 1]

    monkeypatch.setattr("hermes_cli.loop.loop_command", _fake_loop_once)

    result = loop_run_command(_make_args(loop_command="run", max_runs=4))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert calls == [1, 1]
    assert "Run 1/4" in out
    assert "Run 2/4" in out
    assert result["outcome"] == "stopped"
    assert result["stop_reason"] == "model_stop"
    assert result["runs_attempted"] == 2
    assert result["runs_completed"] == 1
    assert result["last_result"]["outcome"] == "stopped"
    assert summary["runs_attempted"] == 2


def test_loop_run_command_stops_on_waiting_outcome(monkeypatch, capsys):
    calls = []

    def _fake_loop_once(args):
        calls.append(args.max_cycles)
        return {
            "session_id": "sess-1",
            "goal": "g",
            "outcome": "waiting",
            "stop_reason": "wait_requested",
            "wake_after": "5m",
            "next_prompt": "Resume once the wake window opens.",
            "expected_evidence": "tests/bar.py",
            "exit_code": 0,
        }

    monkeypatch.setattr("hermes_cli.loop.loop_command", _fake_loop_once)

    result = loop_run_command(_make_args(loop_command="run", max_runs=4))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert calls == [1]
    assert "Run 1/4" in out
    assert "Run 2/4" not in out
    assert result["outcome"] == "waiting"
    assert result["stop_reason"] == "wait_requested"
    assert result["runs_attempted"] == 1
    assert result["runs_completed"] == 0
    assert result["last_result"]["wake_after"] == "5m"
    assert summary["outcome"] == "waiting"


def test_loop_run_command_stops_after_max_runs(monkeypatch, capsys):
    calls = []

    def _fake_loop_once(args):
        calls.append(args.max_cycles)
        return {"session_id": "sess-1", "goal": "g", "outcome": "continued", "stop_reason": "max_cycles_reached", "exit_code": 0}

    monkeypatch.setattr("hermes_cli.loop.loop_command", _fake_loop_once)

    result = loop_run_command(_make_args(loop_command="run", max_runs=2))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert calls == [1, 1]
    assert "Run 1/2" in out
    assert "Run 2/2" in out
    assert result["outcome"] == "continued"
    assert result["stop_reason"] == "max_runs_reached"
    assert result["runs_attempted"] == 2
    assert result["runs_completed"] == 2
    assert summary["stop_reason"] == "max_runs_reached"


def test_cmd_loop_run_raises_system_exit_for_error(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.loop.loop_run_command",
        lambda args: {"exit_code": 1, "outcome": "error", "stop_reason": "invalid_decision_payload"},
    )

    with pytest.raises(SystemExit) as excinfo:
        cmd_loop_run(Namespace())

    assert excinfo.value.code == 1


def test_cmd_loop_run_does_not_raise_on_success(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.loop.loop_run_command",
        lambda args: {"exit_code": 0, "outcome": "stopped", "stop_reason": "model_stop"},
    )

    cmd_loop_run(Namespace())


def test_loop_list_command_defaults_to_active_checkpoints(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-active",
        session_key="telegram:u1:c1",
        payload={"goal": "Keep going", "active": True},
    )
    store.write_checkpoint(
        session_id="sess-inactive",
        session_key="telegram:u2:c2",
        payload={"goal": "Already stopped", "active": False, "stop_reason": "done"},
    )

    result = loop_list_command(Namespace(all=False))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "Active persisted loops:" in out
    assert "sess-active" in out
    assert "sess-inactive" not in out
    assert result["count"] == 1
    assert result["active_only"] is True
    assert summary["count"] == 1
    assert summary["active_only"] is True
    assert summary["events"][0]["session_id"] == "sess-active"


def test_loop_list_command_all_includes_inactive_checkpoints(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-active",
        session_key="telegram:u1:c1",
        payload={"goal": "Keep going", "active": True},
    )
    store.write_checkpoint(
        session_id="sess-inactive",
        session_key="telegram:u2:c2",
        payload={"goal": "Already stopped", "active": False, "stop_reason": "done"},
    )

    result = loop_list_command(Namespace(all=True))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "Persisted loops:" in out
    assert "sess-active" in out
    assert "sess-inactive" in out
    assert result["count"] == 2
    assert result["active_only"] is False
    assert summary["count"] == 2
    assert summary["active_only"] is False


def test_loop_list_command_empty_state(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = loop_list_command(Namespace(all=False))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "No active persisted loops found." in out
    assert result["count"] == 0
    assert result["exit_code"] == 0
    assert summary["events"] == []


def test_loop_status_command_shows_checkpoint_and_recent_events(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-active",
        session_key="telegram:u1:c1",
        payload={
            "goal": "Keep going",
            "remaining_auto_turns": 2,
            "last_result_preview": "Previous result preview.",
            "active": True,
        },
    )
    store.append_event(
        session_id="sess-active",
        event_type="loop_followup_scheduled",
        payload={"goal": "Keep going", "remaining_auto_turns": 1},
    )
    store.append_event(
        session_id="sess-active",
        event_type="loop_stopped",
        payload={"stop_reason": "model_stop", "last_result_preview": "Final result preview."},
    )

    result = loop_status_command(Namespace(session_id="sess-active"))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "Checkpoint summary:" in out
    assert "- session_id: sess-active" in out
    assert "Recent events:" in out
    assert "loop_followup_scheduled" in out
    assert "loop_stopped" in out
    assert "model_stop" in out
    assert result["checkpoint"]["session_id"] == "sess-active"
    assert len(result["events"]) == 2
    assert summary["checkpoint"]["remaining_auto_turns"] == 2


def test_loop_status_command_summary_includes_expected_evidence_and_pending_wakeup_at(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-waiting",
        session_key="telegram:u1:c1",
        payload={
            "goal": "Wait for CI to complete",
            "active": True,
            "state": "waiting",
            "expected_evidence": "tests/hermes_cli/test_loop.py",
            "pending_wakeup_at": "2026-04-22T04:30:00+00:00",
        },
    )

    result = loop_status_command(Namespace(session_id="sess-waiting"))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "- expected_evidence: tests/hermes_cli/test_loop.py" in out
    assert "- pending_wakeup_at: 2026-04-22T04:30:00+00:00" in out
    assert result["checkpoint"]["expected_evidence"] == "tests/hermes_cli/test_loop.py"
    assert summary["checkpoint"]["pending_wakeup_at"] == "2026-04-22T04:30:00+00:00"


def test_loop_list_command_shows_waiting_details(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-waiting",
        session_key="telegram:u1:c1",
        payload={
            "goal": "Wait for CI to complete",
            "active": True,
            "state": "waiting",
            "expected_evidence": "tests/hermes_cli/test_loop.py",
            "pending_wakeup_at": "2026-04-22T04:30:00+00:00",
        },
    )

    result = loop_list_command(Namespace(all=False))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "expected_evidence=tests/hermes_cli/test_loop.py" in out
    assert "wakeup_at=2026-04-22T04:30:00+00:00" in out
    assert result["events"][0]["expected_evidence"] == "tests/hermes_cli/test_loop.py"
    assert summary["events"][0]["pending_wakeup_at"] == "2026-04-22T04:30:00+00:00"


def test_loop_status_command_event_rendering_shows_deferred_details(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-deferred",
        session_key="telegram:u1:c1",
        payload={"goal": "Wait for external signal", "active": True, "state": "waiting"},
    )
    store.append_event(
        session_id="sess-deferred",
        event_type="loop_followup_scheduled",
        payload={
            "goal": "Wait for external signal",
            "next_prompt": "Resume after CI posts the final build artifact and rerun the narrow CLI verification slice.",
            "expected_evidence": "tests/hermes_cli/test_loop.py",
            "pending_wakeup_at": "2026-04-22T04:45:00+00:00",
            "deferred": True,
        },
    )

    result = loop_status_command(Namespace(session_id="sess-deferred"))

    out = capsys.readouterr().out
    assert "loop_followup_scheduled" in out
    assert "next_prompt=Resume after CI posts the final build artifact and rerun the narrow CLI verification slice." in out
    assert "expected_evidence=tests/hermes_cli/test_loop.py" in out
    assert "pending_wakeup_at=2026-04-22T04:45:00+00:00" in out
    assert "deferred=True" in out
    assert result["events"][0]["deferred"] is True


def test_loop_status_command_missing_session_returns_nonzero(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))

    result = loop_status_command(Namespace(session_id="missing-session"))

    out = capsys.readouterr().out
    summary = _last_json_line(out)
    assert "missing-session" in out
    assert result["exit_code"] == 1
    assert summary["checkpoint"] is None
    assert summary["events"] == []


def test_cmd_loop_list_does_not_raise_on_success(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.loop.loop_list_command",
        lambda args: {"exit_code": 0, "count": 0, "events": []},
    )

    cmd_loop_list(Namespace())


def test_cmd_loop_status_raises_system_exit_for_error(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.loop.loop_status_command",
        lambda args: {"exit_code": 1, "checkpoint": None, "events": []},
    )

    with pytest.raises(SystemExit) as excinfo:
        cmd_loop_status(Namespace(session_id="missing-session"))

    assert excinfo.value.code == 1


def test_loop_pause_resume_stop_commands_mutate_checkpoint(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    store = LoopStore()
    store.write_checkpoint(
        session_id="sess-active",
        session_key="telegram:u1:c1",
        payload={
            "goal": "Keep going",
            "active": True,
            "state": "waiting",
            "resumable": True,
            "last_prompt": "Implement the next thin slice.",
        },
    )

    paused = loop_pause_command(Namespace(session_id="sess-active"))
    paused_checkpoint = LoopStore().read_checkpoint("sess-active")
    assert paused["exit_code"] == 0
    assert paused_checkpoint["state"] == "paused"
    assert paused_checkpoint["stop_reason"] == "operator_pause"
    assert paused_checkpoint["resumable"] is True

    resumed = loop_resume_command(Namespace(session_id="sess-active"))
    resumed_checkpoint = LoopStore().read_checkpoint("sess-active")
    assert resumed["exit_code"] == 0
    assert resumed_checkpoint["state"] == "waiting"
    assert resumed_checkpoint["active"] is True
    assert resumed_checkpoint["pending_wakeup_at"] == ""

    stopped = loop_stop_command(Namespace(session_id="sess-active"))
    stopped_checkpoint = LoopStore().read_checkpoint("sess-active")
    assert stopped["exit_code"] == 0
    assert stopped_checkpoint["state"] == "stopped"
    assert stopped_checkpoint["stop_reason"] == "operator_stop"
    assert stopped_checkpoint["resumable"] is False


def test_loop_resume_command_uses_runtime_and_ticks_cli_only_when_due(monkeypatch, capsys):
    seen_runtime_sessions = []
    loop_calls = []

    class _FakeRuntime:
        def __init__(self, *args, **kwargs):
            pass

        def resume(self, session_id):
            seen_runtime_sessions.append(session_id)
            return {
                "ok": True,
                "checkpoint": {
                    "session_id": session_id,
                    "session_key": "cli:sess-active",
                    "goal": "Keep going",
                    "state": "waiting",
                    "pending_wakeup_at": "",
                },
                "should_tick_now": True,
            }

    def _fake_loop_command(args):
        loop_calls.append(args)
        return {"exit_code": 0, "outcome": "continued"}

    monkeypatch.setattr("hermes_cli.loop.LoopRuntime", _FakeRuntime)
    monkeypatch.setattr("hermes_cli.loop.loop_command", _fake_loop_command)

    result = loop_resume_command(Namespace(session_id="sess-active"))

    assert result["exit_code"] == 0
    assert seen_runtime_sessions == ["sess-active"]
    assert len(loop_calls) == 1
    assert loop_calls[0].resume == "sess-active"

    class _FutureWakeRuntime(_FakeRuntime):
        def resume(self, session_id):
            seen_runtime_sessions.append(f"future:{session_id}")
            return {
                "ok": True,
                "checkpoint": {
                    "session_id": session_id,
                    "session_key": "cli:sess-active",
                    "goal": "Keep going",
                    "state": "waiting",
                    "pending_wakeup_at": "2026-04-22T04:30:00+00:00",
                },
                "should_tick_now": False,
            }

    monkeypatch.setattr("hermes_cli.loop.LoopRuntime", _FutureWakeRuntime)

    deferred = loop_resume_command(Namespace(session_id="sess-active"))

    assert deferred["exit_code"] == 0
    assert seen_runtime_sessions[-1] == "future:sess-active"
    assert len(loop_calls) == 1


def test_cmd_loop_pause_resume_stop_wrap_exit_codes(monkeypatch):
    monkeypatch.setattr("hermes_cli.loop.loop_pause_command", lambda args: {"exit_code": 0})
    monkeypatch.setattr("hermes_cli.loop.loop_resume_command", lambda args: {"exit_code": 0})
    monkeypatch.setattr("hermes_cli.loop.loop_stop_command", lambda args: {"exit_code": 0})

    cmd_loop_pause(Namespace(session_id="sess-active"))
    cmd_loop_resume(Namespace(session_id="sess-active"))
    cmd_loop_stop(Namespace(session_id="sess-active"))


def test_cmd_loop_pause_raises_system_exit_for_error(monkeypatch):
    monkeypatch.setattr("hermes_cli.loop.loop_pause_command", lambda args: {"exit_code": 1})
    with pytest.raises(SystemExit):
        cmd_loop_pause(Namespace(session_id="missing"))


def test_cmd_loop_resume_raises_system_exit_for_error(monkeypatch):
    monkeypatch.setattr("hermes_cli.loop.loop_resume_command", lambda args: {"exit_code": 1})
    with pytest.raises(SystemExit):
        cmd_loop_resume(Namespace(session_id="missing"))


def test_cmd_loop_stop_raises_system_exit_for_error(monkeypatch):
    monkeypatch.setattr("hermes_cli.loop.loop_stop_command", lambda args: {"exit_code": 1})
    with pytest.raises(SystemExit):
        cmd_loop_stop(Namespace(session_id="missing"))


# Goal artifact preference tests

def test_decide_continuation_prefers_goal_artifact_text_when_present(monkeypatch, tmp_path):
    """When a matching goal artifact exists, decide uses its goal_text."""
    _DecisionAgent.instances = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _DecisionAgent)

    store = LoopStore()
    goal_id = _stable_goal_id("sess-1", "Keep going")
    store.write_goal_artifact(
        session_id="sess-1",
        goal_id=goal_id,
        goal_text="Keep going",
        created_by="gateway",
    )

    result = decide_continuation_for_session("sess-1", "Keep going")

    assert result["action"] == "stop"
    assert result["stop_reason"] == "model_stop"
    assert len(_DecisionAgent.instances) == 1
    # goal_text from the artifact should appear in the decision prompt
    decision_prompt = _DecisionAgent.instances[0].calls[0]["user_message"]
    assert "Keep going" in decision_prompt


def test_decide_continuation_stops_conservatively_on_goal_artifact_goal_id_mismatch(monkeypatch, tmp_path):
    """Mismatched artifact goal_id triggers a conservative stop before agent is called."""
    _DecisionAgent.instances = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _DecisionAgent)

    LoopStore().write_goal_artifact(
        session_id="sess-1",
        goal_id="completely-different-id",
        goal_text="A different goal entirely",
        created_by="gateway",
    )

    result = decide_continuation_for_session("sess-1", "Keep going")

    assert result["action"] == "stop"
    assert result["stop_reason"] == "goal_artifact_mismatch"
    assert _DecisionAgent.instances == []


def test_decide_continuation_proceeds_normally_without_goal_artifact(monkeypatch, tmp_path):
    """No artifact present — falls through to _decide_once with original goal."""
    _DecisionAgent.instances = []
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _DecisionAgent)

    # No goal artifact written
    result = decide_continuation_for_session("sess-1", "Keep going")

    assert result["action"] == "stop"
    assert result["stop_reason"] == "model_stop"
    assert len(_DecisionAgent.instances) == 1


def test_verify_progress_stops_conservatively_on_goal_artifact_goal_id_mismatch(monkeypatch, tmp_path):
    """Mismatched artifact goal_id causes verifier to return stalled without calling agent."""
    class _VerifierAgent(_DecisionAgent):
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _VerifierAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({"user_message": user_message})
            return {"final_response": json.dumps({"verdict": "progress", "reason": "ok", "should_continue": True})}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _VerifierAgent)

    LoopStore().write_goal_artifact(
        session_id="sess-1",
        goal_id="completely-different-id",
        goal_text="A different goal entirely",
        created_by="gateway",
    )

    result = verify_progress_for_session("sess-1", "Keep going", "response tests/foo.py")

    assert result["verdict"] == "stalled"
    assert result["should_continue"] is False
    assert result["stop_reason"] == "goal_artifact_mismatch"
    assert _VerifierAgent.instances == []


def test_verify_progress_proceeds_normally_without_goal_artifact(monkeypatch, tmp_path):
    """No artifact present — verifier proceeds with original goal."""
    class _VerifierAgent(_DecisionAgent):
        instances = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            _VerifierAgent.instances.append(self)

        def run_conversation(self, user_message, conversation_history=None, task_id=None):
            self.calls.append({"user_message": user_message})
            return {"final_response": json.dumps({"verdict": "progress", "reason": "ok", "should_continue": True})}

    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr("hermes_cli.loop.SessionDB", _FakeSessionDB)
    monkeypatch.setattr("hermes_cli.loop.AIAgent", _VerifierAgent)

    result = verify_progress_for_session("sess-1", "Keep going", "response tests/foo.py")

    assert result["verdict"] == "progress"
    assert result["should_continue"] is True
    assert len(_VerifierAgent.instances) == 1
