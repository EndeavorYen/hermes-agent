from __future__ import annotations

from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.feedback import parse_visual_feedback
from agent.visual.prompt_arsenal import record_approved_prompt_arsenal_entry_for_feedback


def record_visual_feedback_for_request(
    ledger: VisualAttemptLedger,
    *,
    request_id: str,
    feedback_text: str,
    artifact_ids: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    parsed = parse_visual_feedback(feedback_text)
    candidates = artifact_ids or _artifact_ids_for_request(ledger, request_id)
    default_artifact_id = _selected_artifact_for_request(ledger, request_id)
    if default_artifact_id and candidates and default_artifact_id not in candidates:
        default_artifact_id = None
    artifact_id, method = _select_artifact(
        parsed.selection_hint,
        candidates,
        default_artifact_id=default_artifact_id,
    )
    parsed_record = {
        **parsed.parsed,
        "attribution": {
            "method": method,
            "selection_hint": parsed.selection_hint,
            "selection_label": parsed.selection_label,
        },
    }
    feedback_id = ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text=parsed.text,
        polarity=parsed.polarity,
        parsed=parsed_record,
        metadata=_safe_metadata(metadata),
    )
    record_approved_prompt_arsenal_entry_for_feedback(ledger, feedback_id=feedback_id)
    return feedback_id


def _artifact_ids_for_request(ledger: VisualAttemptLedger, request_id: str) -> list[str]:
    try:
        rows = ledger._list("visual_artifacts", where="request_id = ?", params=(request_id,))
    except Exception:
        return []
    artifact_ids = []
    for row in rows:
        artifact_id = row.get("artifact_id") or row.get("id")
        if isinstance(artifact_id, str) and artifact_id:
            artifact_ids.append(artifact_id)
    return artifact_ids


def _select_artifact(
    selection_hint: int | None,
    artifact_ids: list[str],
    *,
    default_artifact_id: str | None = None,
) -> tuple[str | None, str]:
    if selection_hint is None:
        if default_artifact_id:
            return default_artifact_id, "selected_ranking_default"
        if len(artifact_ids) == 1:
            return artifact_ids[0], "single_artifact_default"
        return None, "unbound"
    index = selection_hint - 1
    if index < 0 or index >= len(artifact_ids):
        return None, "selection_out_of_range"
    return artifact_ids[index], "selection_hint"


def _selected_artifact_for_request(ledger: VisualAttemptLedger, request_id: str) -> str | None:
    try:
        rows = ledger._list("visual_rankings", where="request_id = ?", params=(request_id,))
    except Exception:
        return None
    for row in reversed(rows):
        value = row.get("selected_artifact_id")
        if isinstance(value, str) and value:
            return value
    return None


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    return {
        key: value
        for key, value in metadata.items()
        if key in {"platform", "channel_id", "thread_id", "source", "message_id"}
    }
