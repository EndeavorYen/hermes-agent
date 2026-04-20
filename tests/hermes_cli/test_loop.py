import json
from argparse import Namespace

import pytest

from hermes_cli.loop import loop_command, loop_run_command
from hermes_cli.main import cmd_loop, cmd_loop_run


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
                    }
                )
            }
        return {"final_response": "Implemented the next thin slice."}


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
                return {"final_response": json.dumps({"action": "continue", "reason": "step 1", "next_prompt": "Do step 1"})}
            if len(_MultiCycleAgent.instances) == 2:
                return {"final_response": "Did step 1"}
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
                return {"final_response": json.dumps({"action": "continue", "reason": "step 1", "next_prompt": "Do step 1"})}
            if len(_RepeatPromptAgent.instances) == 2:
                return {"final_response": "Did step 1"}
            return {"final_response": json.dumps({"action": "continue", "reason": "still thinks step 1", "next_prompt": "  do   STEP 1  "})}

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
