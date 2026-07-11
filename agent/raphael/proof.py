from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any


TRUSTED_PROOF_TOOLS = {
    "exec_command",
    "terminal",
    "shell",
    "bash",
    "run_command",
    "hermes_cli",
}

_STRUCTURED_EVIDENCE_SOURCES_BY_TOOL = {
    "visual_agent_generate": frozenset({"visual_agent_handoff"}),
}
_STRUCTURED_EVIDENCE_FIELDS = (
    "evidence_id",
    "mission_id",
    "turn_id",
    "proof_type",
    "source",
    "status",
    "command",
    "artifact_id",
    "provider",
    "observed_at",
    "payload_digest",
)
_SHA256_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")

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


@dataclass(frozen=True)
class RaphaelProofEvent:
    source: str
    proof_type: str
    command: str
    success: bool
    content: str


@dataclass(frozen=True)
class RaphaelEvidenceEvent:
    """Sanitized, turn-scoped evidence emitted by a production proof surface."""

    evidence_id: str
    mission_id: str
    turn_id: str
    proof_type: str
    source: str
    status: str
    command: str
    artifact_id: str
    provider: str
    observed_at: str
    payload_digest: str

    def to_dict(self) -> dict[str, str]:
        return {
            "evidence_id": self.evidence_id,
            "mission_id": self.mission_id,
            "turn_id": self.turn_id,
            "proof_type": self.proof_type,
            "source": self.source,
            "status": self.status,
            "command": self.command,
            "artifact_id": self.artifact_id,
            "provider": self.provider,
            "observed_at": self.observed_at,
            "payload_digest": self.payload_digest,
        }


def build_raphael_evidence_event(
    *,
    mission_id: str,
    turn_id: str,
    proof_type: str,
    source: str,
    status: str,
    command: str,
    artifact_id: str,
    provider: str,
    payload_digest: str,
    observed_at: str | None = None,
) -> RaphaelEvidenceEvent:
    observed = observed_at or datetime.now(timezone.utc).isoformat()
    identity = "|".join(
        (
            mission_id,
            turn_id,
            proof_type,
            source,
            status,
            artifact_id,
            provider,
            payload_digest,
        )
    )
    evidence_id = f"evidence-{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
    return RaphaelEvidenceEvent(
        evidence_id=evidence_id,
        mission_id=mission_id,
        turn_id=turn_id,
        proof_type=proof_type,
        source=source,
        status=status,
        command=command,
        artifact_id=artifact_id,
        provider=provider,
        observed_at=observed,
        payload_digest=payload_digest,
    )


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


def evaluate_raphael_proof_gate(
    *,
    route: Any,
    evidence: Sequence[Any] | None = None,
    mission: Any | None = None,
    required_proofs: Sequence[str] | None = None,
    claim_kind: str | None = None,
) -> RaphaelProofGateResult:
    required = _legacy_required_proofs(
        route,
        mission=mission,
        required_proofs=required_proofs,
        claim_kind=claim_kind,
    )
    available = tuple(
        sorted(
            {
                str(getattr(item, "proof_type", ""))
                for item in evidence or ()
                if getattr(item, "success", False) and getattr(item, "proof_type", "")
            }
        )
    )
    missing = tuple(proof for proof in required if proof not in available)
    if missing:
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
        route_kind=str(getattr(route, "kind", "")),
        required_proofs=required,
        available_proofs=available,
        missing_proofs=missing,
        failure_layer=failure_layer,
        next_action=next_action,
        next_proof_command=next_proof_command,
        self_review=self_review,
        active_mission_id=(
            getattr(mission, "mission_id", None)
            if mission is not None
            else getattr(route, "active_mission_id", None)
        ),
    )


def render_proof_gate_user_message(result: RaphaelProofGateResult) -> str:
    if result.status == "passed":
        return "Raphael proof gate passed. Success can be reported with evidence."
    return (
        "Raphael proof gate blocked an unsupported success claim. "
        f"failure_layer: {result.failure_layer}. "
        f"Missing proofs: {', '.join(result.missing_proofs) or 'none'}. "
        f"Next fix: {result.next_action} "
        f"Proof command: {result.next_proof_command or 'none'}"
    )


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


def extract_raphael_evidence_events(
    messages: Sequence[Mapping[str, Any]] | None,
    *,
    turn_id: str = "",
    mission_id: str = "",
) -> tuple[RaphaelEvidenceEvent, ...]:
    """Extract validated structured proof from allowlisted production tools."""
    tool_call_names = _tool_call_name_map(messages)
    events: list[RaphaelEvidenceEvent] = []
    for message in messages or ():
        if not isinstance(message, Mapping) or message.get("role") != "tool":
            continue
        tool_name = str(message.get("name") or message.get("tool_name") or "").lower()
        if not tool_name:
            tool_name = tool_call_names.get(str(message.get("tool_call_id") or ""), "")
        allowed_sources = _STRUCTURED_EVIDENCE_SOURCES_BY_TOOL.get(tool_name)
        if not allowed_sources:
            continue
        parsed = _parse_structured_tool_content(message.get("content"))
        if parsed is None:
            continue
        for candidate in _structured_evidence_candidates(parsed):
            event = _validated_evidence_event(
                candidate,
                tool_name=tool_name,
                allowed_sources=allowed_sources,
                turn_id=str(turn_id or ""),
                mission_id=str(mission_id or ""),
            )
            if event is not None:
                events.append(event)
    return tuple(events)


def _parse_structured_tool_content(value: Any) -> Any | None:
    if isinstance(value, (Mapping, list)):
        return value
    if not isinstance(value, str) or not value.lstrip().startswith(("{", "[")):
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _structured_evidence_candidates(value: Any) -> tuple[Mapping[str, Any], ...]:
    candidates: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        raw_events = value.get("evidence_events")
        if isinstance(raw_events, list):
            candidates.extend(item for item in raw_events if isinstance(item, Mapping))
        for key, nested in value.items():
            if key in {"prompt", "raw_prompt", "content", "evidence_events"}:
                continue
            candidates.extend(_structured_evidence_candidates(nested))
    elif isinstance(value, list):
        for nested in value:
            candidates.extend(_structured_evidence_candidates(nested))
    return tuple(candidates)


def _validated_evidence_event(
    candidate: Mapping[str, Any],
    *,
    tool_name: str,
    allowed_sources: frozenset[str],
    turn_id: str,
    mission_id: str,
) -> RaphaelEvidenceEvent | None:
    if any(not isinstance(candidate.get(field), str) for field in _STRUCTURED_EVIDENCE_FIELDS):
        return None
    values = {field: str(candidate[field]).strip() for field in _STRUCTURED_EVIDENCE_FIELDS}
    if any(not values[field] for field in _STRUCTURED_EVIDENCE_FIELDS):
        return None
    if values["status"] != "passed" or values["source"] not in allowed_sources:
        return None
    if values["command"] != tool_name:
        return None
    if turn_id and values["turn_id"] != turn_id:
        return None
    if mission_id and values["mission_id"] != mission_id:
        return None
    if _SHA256_DIGEST_RE.fullmatch(values["payload_digest"]) is None:
        return None
    try:
        observed_at = datetime.fromisoformat(values["observed_at"].replace("Z", "+00:00"))
    except ValueError:
        return None
    if observed_at.tzinfo is None:
        return None
    rebuilt = build_raphael_evidence_event(
        mission_id=values["mission_id"],
        turn_id=values["turn_id"],
        proof_type=values["proof_type"],
        source=values["source"],
        status=values["status"],
        command=values["command"],
        artifact_id=values["artifact_id"],
        provider=values["provider"],
        payload_digest=values["payload_digest"],
        observed_at=values["observed_at"],
    )
    if values["evidence_id"] != rebuilt.evidence_id:
        return None
    return rebuilt


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


def _legacy_required_proofs(
    route: Any,
    *,
    mission: Any | None,
    required_proofs: Sequence[str] | None,
    claim_kind: str | None,
) -> tuple[str, ...]:
    if required_proofs is not None:
        return tuple(_normalize_required_proof(str(item)) for item in required_proofs)
    if claim_kind:
        claim_proofs = _CLAIM_PROOFS.get(str(claim_kind).replace("-", "_"), ())
        if claim_proofs:
            return tuple(_normalize_required_proof(item) for item in claim_proofs)
    mission_proofs = getattr(mission, "required_proofs", None)
    if mission_proofs:
        return tuple(_normalize_required_proof(str(item)) for item in mission_proofs)
    route_kind = str(getattr(route, "kind", "") or "")
    return tuple(
        _normalize_required_proof(item)
        for item in _ROUTE_PROOFS.get(route_kind, ("answer_grounded_in_context",))
    )


def _next_action_for_missing(missing: Sequence[str]) -> str:
    first = str(next(iter(missing), "") or "")
    return _NEXT_ACTIONS.get(first, "Collect the missing proof before claiming success.")


def _next_proof_command_for_missing(missing: Sequence[str]) -> str:
    first = str(next(iter(missing), "") or "")
    return _PROOF_COMMANDS.get(first, "collect missing proof evidence")


def _self_review_summary(
    status: str,
    available: Sequence[str],
    weaknesses: Sequence[str],
) -> str:
    if status == "passed":
        return f"Proof gate passed with {len(tuple(available))} proof types."
    return (
        "Proof gate blocked the claim; missing or weak proofs: "
        f"{', '.join(tuple(weaknesses)) or 'none'}."
    )


def _first_line(value: str) -> str:
    return value.splitlines()[0].strip() if value.splitlines() else ""


__all__ = [
    "RaphaelEvidenceEvent",
    "RaphaelProofEvent",
    "RaphaelProofGateResult",
    "RaphaelSelfReview",
    "claim_kind_from_text",
    "evaluate_raphael_proof_gate",
    "extract_raphael_evidence_events",
    "extract_raphael_proof_events",
    "raphael_has_required_proof",
    "render_proof_gate_user_message",
]
