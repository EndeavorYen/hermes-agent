from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
from urllib.parse import unquote
from urllib.parse import urlparse

from hermes_constants import get_hermes_home

from agent.visual.artifact_store import ArtifactStore
from agent.visual.attempt_ledger import VisualAttemptLedger
from agent.visual.media_probe import probe_media_reference

logger = logging.getLogger(__name__)


def default_visual_ledger_path() -> Path:
    return get_hermes_home() / "visual" / "attempt_ledger.sqlite3"


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
        "selected_visual_artifact_ids": selected_artifact_ids or artifact_ids,
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
        "content_hash": artifact.get("content_hash"),
        "platform": platform,
        "destination": destination,
        "destination_id": destination_id,
        "thread_id": effective_thread_id,
        "skip_status": skip_status,
    }


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
