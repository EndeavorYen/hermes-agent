from __future__ import annotations

from typing import Any

from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.feedback import parse_visual_feedback
from agent.visual.feedback_attribution import record_visual_feedback_for_request


def ingest_slack_visual_feedback(
    ledger: VisualAttemptLedger,
    event: dict[str, Any],
    *,
    request_id: str | None = None,
    artifact_ids: list[str] | None = None,
) -> dict[str, Any]:
    text = str(event.get("text") or "").strip()
    resolved_request_id = request_id or _resolve_request_id(ledger, event)
    if not text or not resolved_request_id:
        return {
            "success": False,
            "request_id": resolved_request_id,
            "feedback_ids": [],
            "recorded_feedback_count": 0,
            "attribution_scope": "none",
            "reason": "missing_text_or_request",
        }
    if not is_visual_feedback_text(text):
        return {
            "success": False,
            "request_id": resolved_request_id,
            "feedback_ids": [],
            "recorded_feedback_count": 0,
            "attribution_scope": "none",
            "reason": "not_visual_feedback",
        }

    candidates = artifact_ids or _artifact_ids_for_request(ledger, resolved_request_id)
    metadata = _slack_metadata(event)
    if _applies_to_all_current_artifacts(text) and candidates:
        parsed = parse_visual_feedback(text)
        feedback_ids = [
            ledger.record_feedback(
                request_id=resolved_request_id,
                artifact_id=artifact_id,
                feedback_text=parsed.text,
                polarity=parsed.polarity,
                parsed={
                    **parsed.parsed,
                    "attribution": {
                        "method": "all_artifacts",
                        "selection_hint": parsed.selection_hint,
                        "selection_label": parsed.selection_label,
                    },
                },
                metadata=metadata,
            )
            for artifact_id in candidates
        ]
        return {
            "success": True,
            "request_id": resolved_request_id,
            "feedback_ids": feedback_ids,
            "recorded_feedback_count": len(feedback_ids),
            "attribution_scope": "all_artifacts",
        }

    feedback_id = record_visual_feedback_for_request(
        ledger,
        request_id=resolved_request_id,
        feedback_text=text,
        artifact_ids=candidates,
        metadata=metadata,
    )
    return {
        "success": True,
        "request_id": resolved_request_id,
        "feedback_ids": [feedback_id],
        "recorded_feedback_count": 1,
        "attribution_scope": "selection_or_unbound",
    }


def _resolve_request_id(ledger: VisualAttemptLedger, event: dict[str, Any]) -> str | None:
    channel_id = str(event.get("channel") or event.get("channel_id") or "").strip()
    thread_id = str(event.get("thread_ts") or event.get("ts") or "").strip()
    if not channel_id or not thread_id:
        return None
    rows = ledger._list(
        "visual_requests",
        where="platform = ? AND channel_id = ? AND thread_id = ?",
        params=("slack", channel_id, thread_id),
    )
    if not rows:
        rows = ledger._list(
            "visual_requests",
            where="platform = ? AND channel_id = ? AND message_id = ?",
            params=("slack", channel_id, thread_id),
        )
    if not rows:
        return None
    row = rows[-1]
    value = row.get("request_id") or row.get("id")
    return str(value) if value else None


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


def _slack_metadata(event: dict[str, Any]) -> dict[str, Any]:
    channel_id = str(event.get("channel") or event.get("channel_id") or "").strip()
    thread_id = str(event.get("thread_ts") or event.get("ts") or "").strip()
    message_id = str(event.get("ts") or "").strip()
    return {
        "platform": "slack",
        "channel_id": channel_id,
        "thread_id": thread_id,
        "message_id": message_id,
        "source": "slack_feedback_ingestion",
    }


def _applies_to_all_current_artifacts(text: str) -> bool:
    lowered = text.lower()
    return any(token in lowered for token in ("全部退貨", "全部", "全都", "all rejected", "reject all"))


def is_visual_feedback_text(text: str) -> bool:
    parsed = parse_visual_feedback(text)
    if parsed.selection_hint is not None:
        return True
    if parsed.parsed.get("signals") or parsed.parsed.get("issues"):
        return True
    lowered = text.lower()
    return any(
        token in lowered
        for token in (
            "過關",
            "好評",
            "給過",
            "扣分",
            "差評",
            "退貨",
            "不錯",
            "普普",
            "漂亮",
            "性感",
            "reference",
            "舊圖",
            "重複貼",
            "slow motion",
        )
    )
