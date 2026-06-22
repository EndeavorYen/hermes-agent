from __future__ import annotations

import logging
import json
import time
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from urllib.parse import urlparse

from hermes_constants import get_hermes_home

from agent.visual.artifact_store import ArtifactStore
from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.media_probe import probe_media_reference

logger = logging.getLogger(__name__)

_VISUAL_DELIVERY_METADATA_TTL_SECONDS = 600.0
_VISUAL_DELIVERY_METADATA_BY_REF: dict[str, tuple[float, dict[str, Any]]] = {}


def default_visual_ledger_path() -> Path:
    return get_hermes_home() / "visual" / "attempt_ledger.sqlite3"


def register_visual_delivery_metadata_by_ref(metadata_by_ref: dict[str, dict[str, Any]]) -> None:
    now = time.time()
    _prune_visual_delivery_metadata(now)
    for ref, metadata in metadata_by_ref.items():
        if not isinstance(ref, str) or not isinstance(metadata, dict):
            continue
        for key in _artifact_lookup_keys(ref):
            _VISUAL_DELIVERY_METADATA_BY_REF[key] = (now, dict(metadata))


def lookup_visual_delivery_metadata(artifact_ref: str) -> dict[str, Any] | None:
    now = time.time()
    _prune_visual_delivery_metadata(now)
    for key in _artifact_lookup_keys(artifact_ref):
        entry = _VISUAL_DELIVERY_METADATA_BY_REF.get(key)
        if entry is not None:
            return dict(entry[1])
    return None


def _prune_visual_delivery_metadata(now: float) -> None:
    cutoff = now - _VISUAL_DELIVERY_METADATA_TTL_SECONDS
    stale = [
        key
        for key, (registered_at, _) in _VISUAL_DELIVERY_METADATA_BY_REF.items()
        if registered_at < cutoff
    ]
    for key in stale:
        _VISUAL_DELIVERY_METADATA_BY_REF.pop(key, None)


def visual_delivery_metadata(
    *,
    request_id: str,
    attempt_id: str | None,
    artifact_ids: list[str],
    artifact_paths: list[str],
    selected_artifact_ids: list[str] | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    artifacts: dict[str, dict[str, str | None]] = {}
    for artifact_id, artifact_path in zip(artifact_ids, artifact_paths, strict=False):
        if not artifact_id or not artifact_path:
            continue
        entry = {
            "request_id": request_id,
            "attempt_id": attempt_id,
            "artifact_id": artifact_id,
        }
        for key in _artifact_lookup_keys(artifact_path):
            artifacts[key] = entry

    return {
        "visual_request_id": request_id,
        "visual_attempt_id": attempt_id,
        "visual_thread_id": thread_id,
        "selected_visual_artifact_ids": artifact_ids if selected_artifact_ids is None else selected_artifact_ids,
        "visual_artifacts": artifacts,
    }


def visual_delivery_context(
    metadata: dict[str, Any] | None,
    artifact_ref: str,
    *,
    platform: str,
    destination_id: str,
    thread_id: str | None = None,
) -> dict[str, Any] | None:
    metadata = _merge_registered_visual_delivery_metadata(metadata, artifact_ref)
    if not metadata:
        return None

    artifacts = metadata.get("visual_artifacts")
    if not isinstance(artifacts, dict):
        return None

    artifact_entry = None
    for key in _artifact_lookup_keys(artifact_ref):
        artifact_entry = artifacts.get(key)
        if isinstance(artifact_entry, dict):
            break
    if not isinstance(artifact_entry, dict):
        return None

    request_id = artifact_entry.get("request_id") or metadata.get("visual_request_id")
    artifact_id = artifact_entry.get("artifact_id")
    if not request_id or not artifact_id:
        return None

    ledger = VisualAttemptLedger(default_visual_ledger_path())
    artifact_id_text = str(artifact_id)
    artifact = ledger.get_artifact(artifact_id_text)
    effective_thread_id = thread_id or metadata.get("visual_thread_id")
    destination = _delivery_destination(platform, destination_id, effective_thread_id)
    selected_artifact_ids = metadata.get("selected_visual_artifact_ids")
    skip_status = None
    if isinstance(selected_artifact_ids, list) and selected_artifact_ids:
        selected_set = {str(item) for item in selected_artifact_ids}
        if artifact_id_text not in selected_set:
            skip_status = "skipped_unselected"
    if artifact.get("freshness_status") not in {None, "fresh"} or artifact.get("is_stable") is False:
        skip_status = "skipped_stale"

    return {
        "ledger": ledger,
        "request_id": str(request_id),
        "attempt_id": artifact_entry.get("attempt_id") or metadata.get("visual_attempt_id"),
        "artifact_id": artifact_id_text,
        "artifact_kind": artifact.get("kind"),
        "content_hash": artifact.get("content_hash"),
        "platform": platform,
        "destination": destination,
        "destination_id": destination_id,
        "thread_id": effective_thread_id,
        "skip_status": skip_status,
        "metadata": metadata,
    }


def _merge_registered_visual_delivery_metadata(
    metadata: dict[str, Any] | None,
    artifact_ref: str,
) -> dict[str, Any] | None:
    if isinstance(metadata, dict) and isinstance(metadata.get("visual_artifacts"), dict):
        return metadata
    registered = lookup_visual_delivery_metadata(artifact_ref)
    if not registered:
        return metadata
    merged = dict(registered)
    if isinstance(metadata, dict):
        merged.update(metadata)
    return merged


def record_visual_delivery_status(
    context: dict[str, Any] | None,
    delivery_status: str,
    *,
    message_id: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
) -> None:
    if not context:
        return
    ledger = context["ledger"]
    ledger.record_delivery(
        request_id=context["request_id"],
        attempt_id=context.get("attempt_id"),
        artifact_id=context["artifact_id"],
        platform=context["platform"],
        destination=context["destination"],
        destination_id=context["destination_id"],
        thread_id=context.get("thread_id"),
        message_id=message_id,
        delivery_status=delivery_status,
        error_type=error_type,
        error_message=error_message,
    )
    _record_visual_delivery_quality_run(context, delivery_status)


def _record_visual_delivery_quality_run(context: dict[str, Any], delivery_status: str) -> None:
    if delivery_status != "sent":
        return
    metadata = context.get("metadata") if isinstance(context.get("metadata"), dict) else {}
    quality_run = metadata.get("visual_quality_run") if isinstance(metadata, dict) else None
    if not isinstance(quality_run, dict):
        return
    requires_video = quality_run.get("requires_video") is True
    artifact_kind = str(context.get("artifact_kind") or "")
    if requires_video and artifact_kind != "video":
        return

    run_id = _delivery_quality_run_id(str(context.get("request_id") or ""))
    if not run_id:
        return
    output_dir = get_hermes_home() / "visual" / "live_quality_burn"
    runs_dir = output_dir / "runs"
    path = runs_dir / f"{run_id}.json"
    if path.exists():
        return

    summary = _visual_quality_run_summary(quality_run.get("summary"))
    payload = {
        "success": _visual_quality_run_success(quality_run, summary),
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "live",
        "source": "slack_delivery",
        "summary": summary,
        "next_actions": _visual_quality_run_actions(quality_run.get("next_actions")),
        "self_review": _visual_quality_run_self_review(
            quality_run.get("self_review"),
            artifact_kind=artifact_kind,
            requires_video=requires_video,
        ),
        "privacy": {
            "raw_prompt_omitted": True,
            "stores_prompt_hash_only": True,
        },
    }
    try:
        runs_dir.mkdir(parents=True, exist_ok=True)
        _write_json(path, payload)
        _write_json(output_dir / "latest.json", payload)
    except Exception as exc:  # noqa: BLE001 - delivery tracking must not break sends
        logger.warning("Visual delivery quality run recording skipped: %s", exc)


def _delivery_quality_run_id(request_id: str) -> str:
    text = request_id.strip()
    if not text:
        return ""
    return f"slack_delivery_{text}"


def _visual_quality_run_summary(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    return {
        "case_count": _non_negative_int(source.get("case_count"), default=1),
        "failed_case_count": _non_negative_int(source.get("failed_case_count")),
        "failed_case_ids": _strings(source.get("failed_case_ids")),
        "min_quality_score": _score_or_none(source.get("min_quality_score")),
        "quality_issue_count": _non_negative_int(source.get("quality_issue_count")),
        "quality_issues": _strings(source.get("quality_issues")),
        "provider_failure_count": _non_negative_int(source.get("provider_failure_count")),
        "video_missing_after_image_count": _non_negative_int(
            source.get("video_missing_after_image_count")
        ),
        "video_missing_after_image_case_ids": _strings(
            source.get("video_missing_after_image_case_ids")
        ),
        "image_first_video_source_case_count": _non_negative_int(
            source.get("image_first_video_source_case_count")
        ),
        "image_first_video_source_covered_count": _non_negative_int(
            source.get("image_first_video_source_covered_count")
        ),
        "image_first_video_source_failure_count": _non_negative_int(
            source.get("image_first_video_source_failure_count")
        ),
        "image_first_video_source_failure_case_ids": _strings(
            source.get("image_first_video_source_failure_case_ids")
        ),
        "preference_dimension_failure_count": _non_negative_int(
            source.get("preference_dimension_failure_count")
        ),
        "preference_dimension_failures": _preference_dimension_failures(
            source.get("preference_dimension_failures")
        ),
    }


def _visual_quality_run_success(quality_run: dict[str, Any], summary: dict[str, Any]) -> bool:
    if isinstance(quality_run.get("success"), bool):
        return quality_run["success"]
    return (
        _non_negative_int(summary.get("failed_case_count")) == 0
        and _non_negative_int(summary.get("quality_issue_count")) == 0
        and _non_negative_int(summary.get("provider_failure_count")) == 0
        and _non_negative_int(summary.get("video_missing_after_image_count")) == 0
        and _non_negative_int(summary.get("image_first_video_source_failure_count")) == 0
        and _non_negative_int(summary.get("preference_dimension_failure_count")) == 0
    )


def _visual_quality_run_actions(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _visual_quality_run_self_review(
    value: Any,
    *,
    artifact_kind: str,
    requires_video: bool,
) -> dict[str, Any]:
    source = value if isinstance(value, dict) else {}
    native_video_upload_covered = source.get("native_video_upload_covered")
    if native_video_upload_covered is None:
        native_video_upload_covered = artifact_kind == "video" if requires_video else False
    return {
        "native_video_upload_covered": native_video_upload_covered is True,
        "image_first_video_source_covered": source.get("image_first_video_source_covered")
        is True,
        "privacy_safe": True,
        "raw_prompt_omitted": True,
    }


def _preference_dimension_failures(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    failures: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        dimension = str(item.get("dimension") or "").strip()
        if not dimension:
            continue
        entry = {
            "dimension": dimension,
            "issue": str(item.get("issue") or "").strip(),
        }
        score = _score_or_none(item.get("score"))
        if score is not None:
            entry["score"] = score
        failures.append(entry)
    return failures


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in result:
            result.append(text)
    return result


def _non_negative_int(value: Any, *, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _score_or_none(value: Any) -> float | None:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _artifact_lookup_keys(artifact_ref: str) -> list[str]:
    keys = [artifact_ref]
    parsed = urlparse(artifact_ref)
    if parsed.scheme == "file":
        local_path = unquote(parsed.path)
        keys.append(local_path)
        keys.append(str(Path(local_path)))
    elif parsed.scheme == "":
        path = str(Path(artifact_ref))
        keys.append(path)
        keys.append(Path(path).as_uri() if Path(path).is_absolute() else artifact_ref)
    return list(dict.fromkeys(keys))


def _delivery_destination(platform: str, destination_id: str, thread_id: str | None) -> str:
    return f"{platform}:{destination_id}:{thread_id or ''}"


def record_visual_generation_attempt(
    payload: dict[str, Any],
    *,
    user_prompt: str,
    prompt_original: str,
    prompt_mediated: str,
    modality: str,
    operation: str,
    artifact_key: str,
    kind: str,
    provider: str,
    model: str,
    parameters_requested: dict[str, Any] | None = None,
    parameters_effective: dict[str, Any] | None = None,
    platform: str | None = None,
    channel_id: str | None = None,
    thread_id: str | None = None,
    user_id: str | None = None,
    message_id: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    try:
        return _record_visual_generation_attempt(
            payload,
            user_prompt=user_prompt,
            prompt_original=prompt_original,
            prompt_mediated=prompt_mediated,
            modality=modality,
            operation=operation,
            artifact_key=artifact_key,
            kind=kind,
            provider=provider,
            model=model,
            parameters_requested=parameters_requested,
            parameters_effective=parameters_effective,
            platform=platform,
            channel_id=channel_id,
            thread_id=thread_id,
            user_id=user_id,
            message_id=message_id,
            conversation_id=conversation_id,
        )
    except Exception as exc:  # noqa: BLE001 - tracking must not break generation
        logger.warning("Visual generation tracking skipped: %s", exc)
        return payload


def _record_visual_generation_attempt(
    payload: dict[str, Any],
    *,
    user_prompt: str,
    prompt_original: str,
    prompt_mediated: str,
    modality: str,
    operation: str,
    artifact_key: str,
    kind: str,
    provider: str,
    model: str,
    parameters_requested: dict[str, Any] | None,
    parameters_effective: dict[str, Any] | None,
    platform: str | None,
    channel_id: str | None,
    thread_id: str | None,
    user_id: str | None,
    message_id: str | None,
    conversation_id: str | None,
) -> dict[str, Any]:
    ledger = VisualAttemptLedger(default_visual_ledger_path())
    ledger.initialize()

    success = bool(payload.get("success"))
    request_id = ledger.record_request(
        user_prompt=user_prompt,
        normalized_intent={"modality": modality, "operation": operation},
        modality=modality,
        operation=operation,
        platform=platform,
        channel_id=channel_id,
        thread_id=thread_id,
        user_id=user_id,
        message_id=message_id,
        conversation_id=conversation_id,
        status="completed" if success else "failed",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider=provider,
        model=model,
        prompt_original=prompt_original,
        prompt_mediated=prompt_mediated,
        parameters_requested=parameters_requested,
        parameters_effective=parameters_effective,
        status="completed" if success else "failed",
        error_type=payload.get("error_type") if not success else None,
        error_message=payload.get("error") if not success else None,
    )

    tracked = dict(payload)
    tracked["visual_request_id"] = request_id
    tracked["visual_attempt_id"] = attempt_id

    artifact_ref = payload.get(artifact_key)
    if success and isinstance(artifact_ref, str) and artifact_ref.strip():
        artifact_id = _record_artifact(
            ledger,
            artifact_ref.strip(),
            request_id=request_id,
            attempt_id=attempt_id,
            kind=kind,
        )
        tracked["visual_artifact_id"] = artifact_id

    return tracked


def _record_artifact(
    ledger: VisualAttemptLedger,
    artifact_ref: str,
    *,
    request_id: str,
    attempt_id: str,
    kind: str,
) -> str:
    meta = probe_media_reference(artifact_ref)
    if meta.exists and meta.local_path:
        store = ArtifactStore(default_visual_ledger_path().parent / "artifacts")
        artifact = store.import_local_file(
            meta.local_path,
            request_id=request_id,
            attempt_id=attempt_id,
            kind=kind,
        )
        return ledger.record_artifact(
            request_id=request_id,
            attempt_id=attempt_id,
            kind=kind,
            local_path=artifact.local_path,
            uri=artifact_ref,
            content_hash=artifact.content_hash,
            mime_type=artifact.mime_type,
            bytes=artifact.bytes,
            width=artifact.width,
            height=artifact.height,
            is_stable=artifact.is_stable,
            freshness_status=artifact.freshness_status,
        )

    return ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind=kind,
        local_path=meta.local_path,
        uri=artifact_ref,
        content_hash=meta.sha256,
        mime_type=meta.mime_type,
        bytes=meta.bytes,
        width=meta.width,
        height=meta.height,
        is_stable=meta.is_stable,
        freshness_status=meta.freshness_status,
    )
