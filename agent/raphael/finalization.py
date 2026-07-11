from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from agent.raphael.proof import (
    extract_raphael_evidence_events,
    extract_raphael_proof_events,
)


@dataclass(frozen=True)
class RaphaelFinalizationResult:
    status: str
    final_response: str
    required_proofs: tuple[str, ...]
    available_proofs: tuple[str, ...]
    missing_proofs: tuple[str, ...]
    next_action: str
    failure_layer: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "final_response": self.final_response,
            "required_proofs": list(self.required_proofs),
            "available_proofs": list(self.available_proofs),
            "missing_proofs": list(self.missing_proofs),
            "next_action": self.next_action,
            "failure_layer": self.failure_layer,
        }


def enforce_raphael_completion(
    *,
    decision: Mapping[str, Any] | None,
    final_response: str | None,
    messages: Sequence[Mapping[str, Any]] | None,
) -> RaphaelFinalizationResult:
    response = str(final_response or "")
    if not isinstance(decision, Mapping) or not decision:
        return RaphaelFinalizationResult(
            status="not_applicable",
            final_response=response,
            required_proofs=(),
            available_proofs=(),
            missing_proofs=(),
            next_action="",
        )

    if decision.get("control_decision_failed") is True:
        next_action = str(
            decision.get("next_action") or "repair Raphael control decision"
        )
        return RaphaelFinalizationResult(
            status="blocked_unverified_completion",
            final_response=(
                "Raphael 已因控制決策失敗而採取 fail-closed。"
                "failure_layer: control_decision。"
                f"下一步：{next_action}。"
            ),
            required_proofs=("control_decision",),
            available_proofs=(),
            missing_proofs=("control_decision",),
            next_action=next_action,
            failure_layer="control_decision",
        )

    evidence = decision.get("evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    required = tuple(
        str(item)
        for item in evidence.get("required_proofs", ())
        if str(item).strip()
    )
    available = _available_proofs(messages, decision=decision)
    completion_policy = str(decision.get("completion_policy") or "informational")
    missing = tuple(proof for proof in required if proof not in available)
    if completion_policy in {"mutation", "visual"}:
        missing = missing + tuple(
            label
            for label, value in (
                ("turn_identity", decision.get("turn_id")),
                ("mission_identity", decision.get("mission_id")),
            )
            if not str(value or "").strip()
        )
    next_action = str(decision.get("next_action") or "collect required proof")

    if completion_policy not in {"mutation", "visual"}:
        status = "informational"
    elif not _claims_completion(response):
        status = "no_completion_claim"
    elif missing:
        status = "blocked_unverified_completion"
        response = _blocked_response(missing, next_action)
    else:
        status = "passed"

    return RaphaelFinalizationResult(
        status=status,
        final_response=response,
        required_proofs=required,
        available_proofs=available,
        missing_proofs=missing,
        next_action=next_action,
        failure_layer=("proof_gate" if status == "blocked_unverified_completion" else None),
    )


def replace_terminal_assistant_response(
    messages: list[dict[str, Any]],
    final_response: str,
) -> None:
    for message in reversed(messages):
        if message.get("role") == "user":
            break
        if message.get("role") == "assistant" and not message.get("tool_calls"):
            message["content"] = final_response
            return
    messages.append({"role": "assistant", "content": final_response})


def record_raphael_finalization_outcome(
    *,
    decision: Mapping[str, Any] | None,
    result: RaphaelFinalizationResult,
) -> None:
    if not isinstance(decision, Mapping):
        return
    if str(decision.get("origin") or "foreground") != "foreground":
        return
    if result.status not in {"passed", "blocked_unverified_completion"}:
        return

    from agent.raphael.state import read_active_mission, write_active_mission

    mission = read_active_mission()
    mission_id = str(decision.get("mission_id") or "")
    if mission is None or not mission_id or mission.mission_id != mission_id:
        return

    if result.status == "passed":
        next_action = (
            "deliver_selected_visual_artifact"
            if str(decision.get("completion_policy")) == "visual"
            else "mission_complete"
        )
        updated = replace(
            mission,
            phase="proof_passed",
            proof_status="passed",
            blockers=(),
            last_evidence=result.available_proofs,
            next_action=next_action,
            updated_at=datetime.now(timezone.utc),
        )
    else:
        updated = replace(
            mission,
            phase="blocked",
            proof_status="blocked",
            blockers=tuple(
                f"missing proof: {proof}" for proof in result.missing_proofs
            ),
            next_action=result.next_action,
            updated_at=datetime.now(timezone.utc),
        )
    write_active_mission(updated)


def _available_proofs(
    messages: Sequence[Mapping[str, Any]] | None,
    *,
    decision: Mapping[str, Any],
) -> tuple[str, ...]:
    available = {
        event.proof_type
        for event in extract_raphael_proof_events(messages)
        if event.success
    }
    available.update(
        event.proof_type
        for event in extract_raphael_evidence_events(
            messages,
            turn_id=str(decision.get("turn_id") or ""),
            mission_id=str(decision.get("mission_id") or ""),
        )
        if event.status == "passed"
    )
    return tuple(sorted(available))


def _claims_completion(response: str) -> bool:
    lowered = response.strip().lower()
    if not lowered:
        return False
    negative_markers = (
        "尚未完成",
        "還沒完成",
        "未完成",
        "尚缺",
        "cannot complete",
        "not complete",
        "not done",
        "still need",
        "blocked",
    )
    if any(marker in lowered for marker in negative_markers):
        return False
    completion_markers = (
        "完成了",
        "已完成",
        "已修正",
        "已修復",
        "測試都通過",
        "測試已通過",
        "已通過測試",
        "已產出",
        "成功交付",
        "done",
        "completed",
        "implemented",
        "fixed",
        "tests pass",
        "tests passed",
        "successfully delivered",
    )
    return any(marker in lowered for marker in completion_markers)


def _blocked_response(missing: tuple[str, ...], next_action: str) -> str:
    return (
        "Raphael 已阻止未驗證的完成宣告。"
        f"尚缺驗證：{', '.join(missing)}。"
        f"下一步：{next_action}。"
    )


__all__ = [
    "RaphaelFinalizationResult",
    "enforce_raphael_completion",
    "record_raphael_finalization_outcome",
    "replace_terminal_assistant_response",
]
