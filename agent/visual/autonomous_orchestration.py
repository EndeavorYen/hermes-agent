from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.visual.autonomous_validation import validate_visual_generation_payload
from agent.visual.tracking import default_visual_ledger_path


def build_post_generation_orchestration(
    payload: dict[str, Any],
    *,
    db_path: str | Path | None = None,
    require_video: bool,
    autonomy_level: int = 2,
    validation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    db_path = Path(db_path) if db_path is not None else default_visual_ledger_path()
    validation = validation or validate_visual_generation_payload(
        payload,
        db_path=db_path,
        require_video=require_video,
    )
    evidence = validation.get("evidence") if isinstance(validation.get("evidence"), dict) else {}
    next_action = _next_action(str(validation.get("decision") or ""))
    return {
        "runtime_hook": "post_generation",
        "request_id": str(payload.get("visual_request_id") or ""),
        "autonomy_level": _coerce_autonomy_level(autonomy_level),
        "validation": {
            "success": validation.get("success") is True,
            "decision": validation.get("decision"),
            "failures": list(validation.get("failures") or []),
        },
        "health": {
            "image_count": _int(evidence.get("image_count")),
            "video_count": _int(evidence.get("video_count")),
            "attempt_count": _int(evidence.get("attempt_count")),
            "artifact_count": _int(evidence.get("artifact_count")),
            "judgment_count": _int(evidence.get("judgment_count")),
            "ranking_count": _int(evidence.get("ranking_count")),
            "learning_trace_count": _int(evidence.get("learning_trace_count")),
        },
        "next_action": next_action,
        "self_review": {
            "requires_human_input": next_action == "ask_user",
            "safe_for_runtime_hook": True,
            "privacy_safe": True,
        },
    }


def _next_action(validation_decision: str) -> str:
    return {
        "accept": "accept_and_monitor",
        "retry_generation": "retry_generation",
        "retry_or_rejudge": "rejudge_before_delivery",
        "provider_blocked": "provider_blocked",
    }.get(validation_decision, "ask_user")


def _coerce_autonomy_level(value: Any) -> int:
    try:
        return max(0, min(5, int(value)))
    except (TypeError, ValueError):
        return 0


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0

