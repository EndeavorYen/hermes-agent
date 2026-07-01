from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
from typing import Any

from agent.raphael.models import RaphaelMission
from agent.raphael.router import RaphaelRoute


_CLAIM_PROOFS: dict[str, tuple[str, ...]] = {
    "runtime": ("runtime_smoke_when_live_wiring",),
    "llm": ("live_llm_smoke",),
    "install": ("package_install_smoke",),
    "media": (
        "artifact_quality_evidence",
        "selected_current_artifact_only",
        "delivery_cleanliness",
    ),
    "artifact": ("artifact_quality_evidence", "stale_artifact_guard"),
}

_ROUTE_PROOFS: dict[str, tuple[str, ...]] = {
    "general_chat": ("answer_grounded_in_context",),
    "tool_task": ("focused_tests", "diff_hygiene"),
    "image_generation": (
        "artifact_quality_evidence",
        "selected_current_artifact_only",
        "stale_artifact_guard",
    ),
    "video_generation": (
        "artifact_quality_evidence",
        "selected_current_artifact_only",
        "image_first_video_source_evidence",
    ),
    "visual_edit": (
        "artifact_quality_evidence",
        "selected_current_artifact_only",
        "stale_artifact_guard",
    ),
    "prompt_disclosure": ("prompt_trace_available", "no_generation_tool_call"),
    "followup": ("answer_grounded_in_context",),
    "clarification": ("clarification_question_present",),
}

_FAILURE_ACTIONS: dict[str, str] = {
    "provider_health": "Check provider health or choose a fallback provider.",
    "prompt_moderation": "Revise the user-visible prompt or ask for a safe alternative.",
    "handoff_failure": "Repair handoff metadata before retrying the specialist mode.",
    "browser_automation_failure": "Run browser readiness smoke before polling for artifacts.",
    "artifact_quality_failure": "Regenerate or repair the artifact with quality evidence.",
}

_NEXT_ACTIONS: dict[str, str] = {
    "artifact_quality_evidence": "Collect artifact quality evidence before claiming success.",
    "selected_current_artifact_only": (
        "Verify the selected current artifact before claiming completion."
    ),
    "stale_artifact_guard": "Run the stale artifact guard before delivery.",
    "delivery_cleanliness": "Verify clean delivery before reporting success.",
    "runtime_smoke_when_live_wiring": "Run runtime smoke before claiming completion.",
    "live_llm_smoke": "Run an LLM smoke before claiming the LLM slice is ready.",
    "package_install_smoke": "Run package install smoke before claiming install readiness.",
    "focused_tests": "Run focused tests before claiming completion.",
    "diff_hygiene": "Run diff hygiene before claiming completion.",
    "prompt_trace_available": "Verify the prompt trace exists before answering.",
    "no_generation_tool_call": "Prove no generation tool was called for disclosure.",
    "answer_grounded_in_context": "Ground the answer in available context before completion.",
    "clarification_question_present": "Ask one precise clarification before continuing.",
    "image_first_video_source_evidence": (
        "Verify the selected source image before video generation."
    ),
}

_PROOF_COMMANDS: dict[str, str] = {
    "artifact_quality_evidence": "raphael visual-quality-review <selected-artifact>",
    "selected_current_artifact_only": "raphael artifact verify-current <artifact-id>",
    "stale_artifact_guard": "raphael artifact verify-current <artifact-id>",
    "delivery_cleanliness": "raphael delivery-audit <artifact-id>",
    "runtime_smoke_when_live_wiring": "hermes gateway status",
    "live_llm_smoke": "hermes chat --smoke",
    "package_install_smoke": "raphael package-install-smoke",
    "focused_tests": "python -m pytest <focused-test-target> -q",
    "diff_hygiene": "git diff --check",
    "prompt_trace_available": "raphael prompt-trace latest",
    "no_generation_tool_call": "raphael prompt-trace audit-no-generation",
    "answer_grounded_in_context": "review current context and cite evidence",
    "clarification_question_present": "ask one precise clarification",
    "image_first_video_source_evidence": "raphael artifact verify-current <source-image-id>",
}

_TRUSTED_PROOF_TOOLS = {
    "exec_command",
    "terminal",
    "shell",
    "bash",
    "run_command",
    "hermes_cli",
}


@dataclass(frozen=True)
class RaphaelProofEvidence:
    proof_type: str
    layer: str
    success: bool
    summary: str
    source: str
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "proof_type", _normalize_proof(self.proof_type))
        object.__setattr__(self, "layer", str(self.layer))
        object.__setattr__(self, "success", bool(self.success))
        object.__setattr__(self, "summary", str(self.summary))
        object.__setattr__(self, "source", str(self.source))
        if self.metadata is not None:
            object.__setattr__(self, "metadata", dict(self.metadata))


@dataclass(frozen=True)
class RaphaelSelfReview:
    proven: tuple[str, ...]
    weaknesses: tuple[str, ...]
    next_action: str
    summary: str


@dataclass(frozen=True)
class RaphaelProofGateResult:
    status: str
    route_kind: str
    required_proofs: tuple[str, ...]
    available_proofs: tuple[str, ...]
    missing_proofs: tuple[str, ...]
    failure_layer: str | None
    next_action: str
    next_proof_command: str
    self_review: RaphaelSelfReview
    active_mission_id: str | None = None


def required_proofs_for_claim(claim_kind: str | None) -> tuple[str, ...]:
    key = str(claim_kind or "").strip().lower().replace("-", "_")
    return _CLAIM_PROOFS.get(key, ())


def claim_kind_from_text(text: str) -> str | None:
    lowered = str(text or "").lower()
    if any(token in lowered for token in ("runtime", "gateway", "service")):
        return "runtime"
    if any(token in lowered for token in ("llm", "model", "chat smoke")):
        return "llm"
    if any(token in lowered for token in ("install", "installation", "安裝")):
        return "install"
    if any(
        token in lowered
        for token in ("media", "visual delivery", "image delivery", "video delivery")
    ):
        return "media"
    if "delivery" in lowered and any(
        token in lowered for token in ("artifact", "image", "video", "visual")
    ):
        return "media"
    if any(token in lowered for token in ("artifact", "selected image", "成品")):
        return "artifact"
    return None


def required_proofs_for_route(route: RaphaelRoute) -> tuple[str, ...]:
    return _ROUTE_PROOFS.get(route.kind, ("answer_grounded_in_context",))


def extract_raphael_proof_evidence(
    messages: Sequence[dict[str, Any]] | None,
) -> tuple[RaphaelProofEvidence, ...]:
    tool_call_names = _tool_call_name_map(messages)
    tool_call_commands = _tool_call_command_map(messages)
    events: list[RaphaelProofEvidence] = []
    for message in messages or ():
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        tool_call_id = str(message.get("tool_call_id") or "")
        tool_name = str(message.get("name") or message.get("tool_name") or "").lower()
        if not tool_name:
            tool_name = tool_call_names.get(tool_call_id, "")
        if tool_name not in _TRUSTED_PROOF_TOOLS:
            continue
        content = str(message.get("content") or "")
        command = tool_call_commands.get(tool_call_id) or _first_line(content)
        success = _looks_like_successful_tool_output(message, content)
        if not success:
            failed_layer = _classify_failed_tool_layer(content)
            if failed_layer:
                events.append(
                    RaphaelProofEvidence(
                        proof_type="failed_tool_evidence",
                        layer=failed_layer,
                        success=False,
                        summary=_first_line(content) or failed_layer,
                        source=tool_name,
                    )
                )
            continue
        proof_types = _classify_successful_tool_proofs(content, command)
        for proof_type in proof_types:
            events.append(
                RaphaelProofEvidence(
                    proof_type=proof_type,
                    layer=_proof_layer(proof_type),
                    success=True,
                    summary=command or _first_line(content) or proof_type,
                    source=tool_name,
                )
            )
    return tuple(events)


def evaluate_raphael_proof_gate(
    *,
    route: RaphaelRoute,
    evidence: Sequence[RaphaelProofEvidence] | None = None,
    mission: RaphaelMission | None = None,
    required_proofs: Sequence[str] | None = None,
    claim_kind: str | None = None,
) -> RaphaelProofGateResult:
    evidence_items = tuple(evidence or ())
    required = _resolve_required_proofs(
        route,
        mission=mission,
        required_proofs=required_proofs,
        claim_kind=claim_kind,
    )
    available = tuple(
        sorted(
            {
                event.proof_type
                for event in evidence_items
                if event.success and event.proof_type
            }
        )
    )
    missing = tuple(proof for proof in required if proof not in available)
    failed_event = next(
        (
            event
            for event in evidence_items
            if not event.success and event.layer in _FAILURE_ACTIONS
        ),
        None,
    )

    if failed_event is not None:
        status = "failed"
        failure_layer = failed_event.layer
        next_action = _FAILURE_ACTIONS[failure_layer]
        next_proof_command = _proof_command_for_failure(failure_layer)
        weaknesses = (failure_layer, *missing)
    elif missing:
        status = "blocked"
        failure_layer = "proof_gate"
        next_action = _next_action_for_missing(missing)
        next_proof_command = _next_proof_command_for_missing(missing)
        weaknesses = missing
    else:
        status = "passed"
        failure_layer = None
        next_action = "Report success with the passing proof evidence."
        next_proof_command = ""
        weaknesses = ()

    self_review = RaphaelSelfReview(
        proven=available,
        weaknesses=tuple(weaknesses),
        next_action=next_action,
        summary=_self_review_summary(status, available, weaknesses),
    )
    return RaphaelProofGateResult(
        status=status,
        route_kind=route.kind,
        required_proofs=required,
        available_proofs=available,
        missing_proofs=missing,
        failure_layer=failure_layer,
        next_action=next_action,
        next_proof_command=next_proof_command,
        self_review=self_review,
        active_mission_id=(
            mission.mission_id if mission is not None else route.active_mission_id
        ),
    )


def render_proof_gate_user_message(result: RaphaelProofGateResult) -> str:
    if result.status == "passed":
        return "Raphael proof gate passed. Success can be reported with evidence."
    if result.status == "failed":
        return (
            "Raphael proof gate failed. "
            f"failure_layer: {result.failure_layer}. "
            f"Next fix: {result.next_action}"
            + (
                f" Proof command: {result.next_proof_command}"
                if result.next_proof_command
                else ""
            )
        )
    tool_success_note = (
        " Tool success alone is not enough."
        if "tool_success" in result.available_proofs
        else ""
    )
    return (
        "Raphael proof gate blocked an unsupported success claim."
        f"{tool_success_note} "
        f"failure_layer: {result.failure_layer}. "
        f"Missing proofs: {', '.join(result.missing_proofs) or 'none'}. "
        f"Next fix: {result.next_action} "
        f"Proof command: {result.next_proof_command or 'none'}"
    )


def render_proof_gate_context(result: RaphaelProofGateResult) -> str:
    required = ", ".join(result.required_proofs) or "none"
    available = ", ".join(result.available_proofs) or "none"
    missing = ", ".join(result.missing_proofs) or "none"
    tool_success_only = (
        "true"
        if "tool_success" in result.available_proofs or result.status == "blocked"
        else "false"
    )
    lines = [
        "Raphael Proof Gate (internal):",
        f"status: {result.status}",
        f"route_kind: {result.route_kind}",
        f"failure_layer: {result.failure_layer or 'none'}",
        f"required_proofs: {required}",
        f"available_proofs: {available}",
        f"missing_proofs: {missing}",
        f"tool_success_is_not_enough: {tool_success_only}",
        f"next_action: {result.next_action}",
        f"next_proof_command: {result.next_proof_command or 'none'}",
    ]
    if result.active_mission_id:
        lines.append(f"active_mission_id: {result.active_mission_id}")
    lines.append(
        "instruction: do not claim completion until required proofs are present"
    )
    return "\n".join(lines)


def should_render_proof_gate_for_text(text: str) -> bool:
    lowered = str(text or "").lower()
    completion_markers = (
        "complete",
        "completed",
        "done",
        "fixed",
        "passed",
        "ready to ship",
        "release is ready",
        "完成",
        "修好了",
        "通過",
        "上線",
        "可以說完成",
        "可用了",
    )
    return any(marker in lowered for marker in completion_markers)


def _resolve_required_proofs(
    route: RaphaelRoute,
    *,
    mission: RaphaelMission | None,
    required_proofs: Sequence[str] | None,
    claim_kind: str | None,
) -> tuple[str, ...]:
    if required_proofs is not None:
        return _normalize_many(required_proofs)
    if mission is not None and mission.required_proofs:
        return _normalize_many(mission.required_proofs)
    claim_proofs = required_proofs_for_claim(claim_kind)
    if claim_proofs:
        return claim_proofs
    return required_proofs_for_route(route)


def _next_action_for_missing(missing: Sequence[str]) -> str:
    for proof in missing:
        action = _NEXT_ACTIONS.get(proof)
        if action:
            return action
    return "Collect the required proof before claiming completion."


def _next_proof_command_for_missing(missing: Sequence[str]) -> str:
    for proof in missing:
        command = _PROOF_COMMANDS.get(proof)
        if command:
            return command
    return "collect required proof evidence"


def _proof_command_for_failure(failure_layer: str) -> str:
    return {
        "provider_health": "hermes provider health",
        "prompt_moderation": "review and revise prompt",
        "handoff_failure": "raphael route inspect",
        "browser_automation_failure": "chrome-cdp-ex doctor",
        "artifact_quality_failure": "raphael visual-quality-review <selected-artifact>",
    }.get(failure_layer, "collect failure evidence")


def _self_review_summary(
    status: str,
    available: Sequence[str],
    weaknesses: Sequence[str],
) -> str:
    if status == "passed":
        return "Required proofs are present; reporting success is allowed."
    if available:
        return (
            "Some evidence is present, but missing or failed proof changes the "
            "next action before success can be claimed."
        )
    if weaknesses:
        return "No sufficient proof is present; the next action must collect evidence."
    return "No proof requirement was triggered."


def _normalize_many(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(_normalize_proof(value) for value in values if str(value).strip())


def _normalize_proof(value: str) -> str:
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "unit_tests": "focused_tests",
        "unit_test": "focused_tests",
        "runtime_smoke": "runtime_smoke_when_live_wiring",
        "runtime_smoke_when_live": "runtime_smoke_when_live_wiring",
        "artifact_match": "selected_current_artifact_only",
        "visual_self_review": "artifact_quality_evidence",
    }
    return aliases.get(key, key)


def _tool_call_name_map(messages: Sequence[dict[str, Any]] | None) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages or ():
        if not isinstance(message, dict):
            continue
        for tool_call in message.get("tool_calls") or ():
            if not isinstance(tool_call, dict):
                continue
            call_id = str(tool_call.get("id") or "")
            function = tool_call.get("function")
            function = function if isinstance(function, dict) else {}
            name = str(function.get("name") or "").lower()
            if call_id and name:
                names[call_id] = name
    return names


def _tool_call_command_map(messages: Sequence[dict[str, Any]] | None) -> dict[str, str]:
    commands: dict[str, str] = {}
    for message in messages or ():
        if not isinstance(message, dict):
            continue
        for tool_call in message.get("tool_calls") or ():
            if not isinstance(tool_call, dict):
                continue
            call_id = str(tool_call.get("id") or "")
            function = tool_call.get("function")
            function = function if isinstance(function, dict) else {}
            command = _extract_command_from_arguments(function.get("arguments"))
            if call_id and command:
                commands[call_id] = command
    return commands


def _extract_command_from_arguments(arguments: Any) -> str:
    parsed = arguments
    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
        except json.JSONDecodeError:
            return arguments.strip()
    if isinstance(parsed, dict):
        for key in ("cmd", "command", "shell_command"):
            value = parsed.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        args = parsed.get("args")
        if isinstance(args, list) and args:
            return " ".join(str(item) for item in args if str(item).strip())
    return ""


def _looks_like_successful_tool_output(message: dict[str, Any], content: str) -> bool:
    exit_code = _extract_exit_code(message, content)
    if exit_code is not None and exit_code != 0:
        return False
    lowered = content.lower()
    if _contains_failure_marker(lowered):
        return False
    if exit_code == 0:
        return True
    status = str(message.get("status") or message.get("state") or "").strip().lower()
    return status in {"success", "succeeded", "completed", "ok"}


def _extract_exit_code(message: dict[str, Any], content: str) -> int | None:
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
        "returncode=1",
    )
    return any(marker in content for marker in failure_markers)


def _classify_successful_tool_proofs(
    content: str,
    command: str,
) -> tuple[str, ...]:
    lowered = content.lower()
    command = str(command or "").strip().lower()
    if command.startswith(("echo ", "printf ")):
        return ()
    if "pytest" in command and any(
        marker in lowered for marker in (" passed", "1 passed", "exit code 0")
    ):
        return ("focused_tests",)
    if "git diff --check" in command:
        return ("diff_hygiene",)
    if "ruff" in command and "all checks passed" in lowered:
        return ("static_checks",)
    if "gateway status" in command and any(
        marker in lowered for marker in ("pid", "loaded", "running", "service")
    ):
        return ("runtime_smoke_when_live_wiring",)
    if "hermes chat" in command and any(
        marker in lowered for marker in ("session_id", " ok", "_ok", "passed")
    ):
        return ("live_llm_smoke",)
    if "package-install-smoke" in command:
        return ("package_install_smoke",)
    if "visual-quality-review" in command:
        return ("artifact_quality_evidence",)
    if "artifact verify-current" in command:
        return ("selected_current_artifact_only", "stale_artifact_guard")
    if "delivery-audit" in command:
        return ("delivery_cleanliness",)
    return ()


def _classify_failed_tool_layer(content: str) -> str | None:
    lowered = content.lower()
    if any(token in lowered for token in ("provider health", "timeout", "quota")):
        return "provider_health"
    if any(token in lowered for token in ("moderation", "policy", "refusal")):
        return "prompt_moderation"
    if any(token in lowered for token in ("handoff", "provider_contract")):
        return "handoff_failure"
    if any(token in lowered for token in ("browser", "cdp", "prosemirror")):
        return "browser_automation_failure"
    if any(token in lowered for token in ("artifact quality", "stale artifact")):
        return "artifact_quality_failure"
    return None


def _proof_layer(proof_type: str) -> str:
    if proof_type in {"focused_tests", "diff_hygiene", "static_checks"}:
        return "test"
    if proof_type in {"runtime_smoke_when_live_wiring", "live_llm_smoke"}:
        return "runtime"
    return "proof"


def _first_line(value: str) -> str:
    return value.splitlines()[0].strip() if value.splitlines() else ""


__all__ = [
    "RaphaelProofEvidence",
    "RaphaelProofGateResult",
    "RaphaelSelfReview",
    "claim_kind_from_text",
    "evaluate_raphael_proof_gate",
    "extract_raphael_proof_evidence",
    "render_proof_gate_context",
    "render_proof_gate_user_message",
    "required_proofs_for_claim",
    "required_proofs_for_route",
    "should_render_proof_gate_for_text",
]
