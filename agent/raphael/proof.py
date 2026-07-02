from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


TRUSTED_PROOF_TOOLS = {
    "exec_command",
    "terminal",
    "shell",
    "bash",
    "run_command",
    "hermes_cli",
}


@dataclass(frozen=True)
class RaphaelProofEvent:
    source: str
    proof_type: str
    command: str
    success: bool
    content: str


def extract_raphael_proof_events(
    messages: Sequence[Mapping[str, Any]] | None,
) -> tuple[RaphaelProofEvent, ...]:
    tool_call_names = _tool_call_name_map(messages)
    events: list[RaphaelProofEvent] = []
    for message in messages or ():
        if not isinstance(message, Mapping) or message.get("role") != "tool":
            continue
        tool_name = str(message.get("name") or message.get("tool_name") or "").lower()
        if not tool_name:
            tool_name = tool_call_names.get(str(message.get("tool_call_id") or ""), "")
        if tool_name not in TRUSTED_PROOF_TOOLS:
            continue
        content = str(message.get("content") or "")
        success = _looks_like_successful_tool_output(message, content)
        command = _first_line(content)
        proof_type = _classify_proof_type(content.lower(), command.lower()) if success else None
        if proof_type:
            events.append(
                RaphaelProofEvent(
                    source=tool_name,
                    proof_type=proof_type,
                    command=command,
                    success=success,
                    content=content,
                )
            )
    return tuple(events)


def raphael_has_required_proof(
    messages: Sequence[Mapping[str, Any]] | None,
    required_proofs: Sequence[str],
) -> bool:
    events = extract_raphael_proof_events(messages)
    available = {event.proof_type for event in events if event.success}
    normalized_required = {_normalize_required_proof(item) for item in required_proofs}
    normalized_required.discard("unverifiable")
    if not normalized_required:
        return bool(available)
    return normalized_required <= available


def _tool_call_name_map(messages: Sequence[Mapping[str, Any]] | None) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages or ():
        if not isinstance(message, Mapping):
            continue
        for tool_call in message.get("tool_calls") or ():
            if not isinstance(tool_call, Mapping):
                continue
            call_id = str(tool_call.get("id") or "")
            function = tool_call.get("function")
            function = function if isinstance(function, Mapping) else {}
            name = str(function.get("name") or "").lower()
            if call_id and name:
                names[call_id] = name
    return names


def _classify_proof_type(content: str, command: str) -> str | None:
    if _contains_failure_marker(content):
        return None
    if _command_is_echo_like(command):
        return None
    if _command_mentions(command, "pytest") and "pytest" in content and any(
        marker in content for marker in (" passed", "1 passed", "exit code 0")
    ):
        return "focused_tests"
    if _command_mentions(command, "ruff") and "ruff" in content and "all checks passed" in content:
        return "static_checks"
    if _command_mentions(command, "git diff --check") and "git diff --check" in content and "exit code 0" in content:
        return "diff_hygiene"
    if _command_mentions(command, "gateway status") and "gateway status" in content and any(
        marker in content for marker in ("pid", "loaded", "running", "service")
    ):
        return "runtime_smoke_when_live_wiring"
    if _command_mentions(command, "hermes chat") and "session_id" in content and any(
        marker in content for marker in (" ok", "_ok", "passed")
    ):
        return "live_llm_smoke"
    return None


def _command_is_echo_like(command: str) -> bool:
    stripped = command.strip().lower()
    return stripped.startswith(("echo ", "printf "))


def _command_mentions(command: str, expected: str) -> bool:
    return expected.lower() in command.lower()


def _looks_like_successful_tool_output(message: Mapping[str, Any], content: str) -> bool:
    exit_code = _extract_exit_code(message, content)
    if exit_code is not None and exit_code != 0:
        return False
    lowered = content.lower()
    if _contains_failure_marker(lowered):
        return False
    if exit_code == 0:
        return True
    status = str(message.get("status") or message.get("state") or "").strip().lower()
    if status in {"failed", "failure", "error"}:
        return False
    if status in {"success", "succeeded", "completed", "ok"}:
        return True
    return False


def _extract_exit_code(message: Mapping[str, Any], content: str) -> int | None:
    for key in ("exit_code", "returncode", "return_code", "code"):
        value = message.get(key)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value.strip())
    lowered = content.lower()
    markers = ("process exited with code ", "exit code ", "returncode=")
    for marker in markers:
        index = lowered.rfind(marker)
        if index == -1:
            continue
        suffix = lowered[index + len(marker) :].strip()
        number = suffix.split(maxsplit=1)[0].strip(".,;:")
        if number.lstrip("-").isdigit():
            return int(number)
    return None


def _contains_failure_marker(content: str) -> bool:
    failure_markers = (
        " failed",
        " failures",
        " error",
        " errors",
        "traceback",
        "assertionerror",
        "process exited with code 1",
        "exit code 1",
        "exit code 2",
        "exit code 3",
        "exit code 4",
        "exit code 5",
        "returncode=1",
    )
    return any(marker in content for marker in failure_markers)


def _normalize_required_proof(value: str) -> str:
    if value in {"runtime_smoke", "runtime_smoke_when_live_wiring"}:
        return "runtime_smoke_when_live_wiring"
    if value in {"unit_tests", "focused_tests"}:
        return "focused_tests"
    return str(value)


def _first_line(value: str) -> str:
    return value.splitlines()[0].strip() if value.splitlines() else ""


__all__ = [
    "RaphaelProofEvent",
    "extract_raphael_proof_events",
    "raphael_has_required_proof",
]
