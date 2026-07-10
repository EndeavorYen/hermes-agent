from agent.raphael.proof import extract_raphael_proof_events, raphael_has_required_proof


def test_rejects_assistant_text_that_mentions_pytest_passed():
    messages = [{"role": "assistant", "content": "pytest passed"}]

    assert extract_raphael_proof_events(messages) == ()
    assert not raphael_has_required_proof(messages, ("focused_tests",))


def test_rejects_read_file_tool_result_that_mentions_pytest_passed():
    messages = [
        {"role": "tool", "name": "read_file", "content": "README says pytest passed"},
    ]

    assert not raphael_has_required_proof(messages, ("focused_tests",))


def test_accepts_exec_command_pytest_success_for_focused_tests():
    messages = [
        {
            "role": "tool",
            "name": "exec_command",
            "exit_code": 0,
            "content": "venv/bin/python -m pytest tests/foo.py -q\n1 passed",
        }
    ]

    assert raphael_has_required_proof(messages, ("focused_tests",))


def test_rejects_echoed_pytest_success_even_with_exit_code_zero():
    messages = [
        {
            "role": "tool",
            "name": "exec_command",
            "exit_code": 0,
            "content": "echo 'pytest 1 passed'\npytest 1 passed\nProcess exited with code 0",
        }
    ]

    assert not raphael_has_required_proof(messages, ("focused_tests",))


def test_rejects_echoed_gateway_status_even_with_exit_code_zero():
    messages = [
        {
            "role": "tool",
            "name": "exec_command",
            "exit_code": 0,
            "content": "printf 'hermes gateway status pid 123 running'\nhermes gateway status pid 123 running",
        }
    ]

    assert not raphael_has_required_proof(
        messages,
        ("runtime_smoke_when_live_wiring",),
    )


def test_rejects_exec_command_text_without_execution_metadata():
    messages = [
        {
            "role": "tool",
            "name": "exec_command",
            "content": "venv/bin/python -m pytest tests/foo.py -q\n1 passed",
        }
    ]

    assert not raphael_has_required_proof(messages, ("focused_tests",))


def test_requires_all_required_proof_types_not_any_one():
    messages = [
        {
            "role": "tool",
            "name": "exec_command",
            "exit_code": 0,
            "content": "venv/bin/python -m pytest tests/foo.py -q\n1 passed",
        }
    ]

    assert not raphael_has_required_proof(
        messages,
        ("focused_tests", "runtime_smoke_when_live_wiring"),
    )


def test_rejects_pytest_output_with_failures_even_when_passes_are_present():
    messages = [
        {
            "role": "tool",
            "name": "exec_command",
            "content": (
                "venv/bin/python -m pytest tests/foo.py -q\n"
                "1 failed, 1 passed in 0.10s\n"
                "Process exited with code 1"
            ),
        }
    ]

    assert not raphael_has_required_proof(messages, ("focused_tests",))


def test_accepts_combined_focused_and_runtime_smoke_only_when_both_exist():
    messages = [
        {
            "role": "tool",
            "name": "exec_command",
            "exit_code": 0,
            "content": "venv/bin/python -m pytest tests/foo.py -q\n1 passed",
        },
        {
            "role": "tool",
            "name": "exec_command",
            "exit_code": 0,
            "content": "hermes gateway status\nservice loaded, pid 123, running",
        },
    ]

    assert raphael_has_required_proof(
        messages,
        ("focused_tests", "runtime_smoke_when_live_wiring"),
    )


def test_resolves_nameless_tool_result_through_tool_call_id():
    messages = [
        {
            "role": "assistant",
            "tool_calls": [
                {"id": "call_read", "function": {"name": "read_file"}},
                {"id": "call_exec", "function": {"name": "exec_command"}},
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call_read",
            "content": "pytest passed in README",
        },
        {
            "role": "tool",
            "tool_call_id": "call_exec",
            "exit_code": 0,
            "content": "venv/bin/python -m pytest tests/foo.py -q\n1 passed",
        },
    ]

    events = extract_raphael_proof_events(messages)

    assert [event.source for event in events] == ["exec_command"]
    assert raphael_has_required_proof(messages, ("focused_tests",))
