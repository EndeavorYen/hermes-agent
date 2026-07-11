from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
from typing import Any

from agent.raphael.proof import extract_raphael_proof_events


@dataclass(frozen=True)
class RaphaelFinalizationResult:
    status: str
    final_response: str
    required_proofs: tuple[str, ...]
    available_proofs: tuple[str, ...]
    missing_proofs: tuple[str, ...]
    next_action: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "final_response": self.final_response,
            "required_proofs": list(self.required_proofs),
            "available_proofs": list(self.available_proofs),
            "missing_proofs": list(self.missing_proofs),
            "next_action": self.next_action,
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

    evidence = decision.get("evidence")
    evidence = evidence if isinstance(evidence, Mapping) else {}
    required = tuple(
        str(item)
        for item in evidence.get("required_proofs", ())
        if str(item).strip()
    )
    available = _available_proofs(messages)
    missing = tuple(proof for proof in required if proof not in available)
    completion_policy = str(decision.get("completion_policy") or "informational")
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


def _available_proofs(
    messages: Sequence[Mapping[str, Any]] | None,
) -> tuple[str, ...]:
    available = {
        event.proof_type
        for event in extract_raphael_proof_events(messages)
        if event.success
    }
    for message in messages or ():
        if not isinstance(message, Mapping):
            continue
        _collect_structured_proofs(message, available)
        content = message.get("content")
        if not isinstance(content, str) or not content.lstrip().startswith(("{", "[")):
            continue
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError):
            continue
        _collect_structured_proofs(parsed, available)
    return tuple(sorted(available))


def _collect_structured_proofs(value: Any, available: set[str]) -> None:
    if isinstance(value, Mapping):
        proof_type = str(value.get("proof_type") or "")
        if proof_type and str(value.get("status") or "") == "passed":
            available.add(proof_type)
        for key, nested in value.items():
            if key in {"prompt", "raw_prompt", "content"}:
                continue
            _collect_structured_proofs(nested, available)
    elif isinstance(value, list):
        for nested in value:
            _collect_structured_proofs(nested, available)


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
    "replace_terminal_assistant_response",
]
