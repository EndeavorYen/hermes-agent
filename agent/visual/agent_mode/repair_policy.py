"""Bounded repair decisions for Visual Agent Mode."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict


RETRYABLE_ERROR_TYPES = {
    "qc_failed",
    "empty_response",
    "timeout",
    "provider_timeout",
    "transient_provider",
    "rate_limited",
}


@dataclass(frozen=True)
class VisualRepairDecision:
    action: str
    reason: str
    remaining_budget: int
    confidence: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def decide_visual_repair(
    mission: Any,
    stage_result: Dict[str, Any],
    reward_trace: Dict[str, Any],
) -> VisualRepairDecision:
    data = dict(stage_result or {})
    confidence = _confidence(reward_trace)
    budget = _repair_budget(mission)
    attempt_count = _int_value(data.get("repair_attempt_count"), default=0)
    remaining_before = max(0, budget - attempt_count)
    error_type = _error_type(data)

    if data.get("success"):
        return VisualRepairDecision(
            action="stop",
            reason="stage_success",
            remaining_budget=remaining_before,
            confidence=confidence,
        )
    if _int_value(_value(mission, "autonomy_level"), default=0) < 3:
        return VisualRepairDecision(
            action="ask_user",
            reason="autonomy_below_repair",
            remaining_budget=remaining_before,
            confidence=confidence,
        )
    if remaining_before <= 0:
        return VisualRepairDecision(
            action="stop",
            reason="repair_budget_exhausted",
            remaining_budget=0,
            confidence=confidence,
        )
    if error_type == "content_moderation":
        if _bool_value(_value(mission, "safe_reframe_allowed")):
            return VisualRepairDecision(
                action="reframe",
                reason="safe_reframe_allowed",
                remaining_budget=remaining_before - 1,
                confidence=confidence,
            )
        return VisualRepairDecision(
            action="stop",
            reason="content_moderation",
            remaining_budget=remaining_before,
            confidence=confidence,
        )
    if error_type in RETRYABLE_ERROR_TYPES:
        reason = (
            "retryable_qc_failure"
            if error_type == "qc_failed"
            else f"retryable_{error_type}"
        )
        return VisualRepairDecision(
            action="retry",
            reason=reason,
            remaining_budget=remaining_before - 1,
            confidence=confidence,
        )
    return VisualRepairDecision(
        action="ask_user",
        reason=error_type or "unknown_failure",
        remaining_budget=remaining_before,
        confidence=confidence,
    )


def _repair_budget(mission: Any) -> int:
    raw = _value(mission, "repair_budget")
    if raw is None:
        constraints = _value(mission, "constraints")
        if isinstance(constraints, dict):
            raw = constraints.get("repair_budget")
    return max(0, min(2, _int_value(raw, default=1)))


def _error_type(stage_result: Dict[str, Any]) -> str:
    direct = str(stage_result.get("error_type") or "").strip()
    if direct:
        return direct
    failures = stage_result.get("failures")
    if isinstance(failures, list):
        for failure in failures:
            if isinstance(failure, dict):
                candidate = str(failure.get("error_type") or "").strip()
                if candidate:
                    return candidate
    return ""


def _confidence(reward_trace: Dict[str, Any]) -> float:
    if isinstance(reward_trace, dict):
        if "confidence" in reward_trace:
            return _float_value(reward_trace.get("confidence"))
        reward = reward_trace.get("reward")
        if isinstance(reward, dict) and "confidence" in reward:
            return _float_value(reward.get("confidence"))
    return 0.0


def _value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


def _int_value(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _float_value(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.0
    return max(0.0, min(1.0, number))


def _bool_value(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
