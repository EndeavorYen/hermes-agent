from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any


def latest_selected_artifact_id(
    history: Sequence[Mapping[str, Any]] | None,
) -> str | None:
    for message in reversed(tuple(history or ())):
        artifact_id = _artifact_id_from_mapping(message)
        if artifact_id:
            return artifact_id
    return None


def _artifact_id_from_mapping(payload: Mapping[str, Any]) -> str | None:
    for key in ("artifact_id", "selected_artifact_id"):
        artifact_id = str(payload.get(key) or "").strip()
        if artifact_id:
            return artifact_id
    metadata = payload.get("metadata")
    if isinstance(metadata, Mapping):
        artifact_id = _artifact_id_from_mapping(metadata)
        if artifact_id:
            return artifact_id
        artifact_id = _artifact_id_from_delivery_metadata(metadata.get("delivery_metadata"))
        if artifact_id:
            return artifact_id
    artifact_id = _artifact_id_from_delivery_metadata(payload.get("delivery_metadata"))
    if artifact_id:
        return artifact_id
    content = payload.get("content")
    if isinstance(content, Mapping):
        return _artifact_id_from_mapping(content)
    if isinstance(content, str):
        parsed = _parse_json_object(content)
        if isinstance(parsed, Mapping):
            return _artifact_id_from_mapping(parsed)
    return None


def _artifact_id_from_delivery_metadata(value: Any) -> str | None:
    if not isinstance(value, Mapping):
        return None
    selected = value.get("selected_visual_artifact_ids")
    if isinstance(selected, Sequence) and not isinstance(selected, (str, bytes, bytearray)):
        for item in selected:
            artifact_id = str(item or "").strip()
            if artifact_id:
                return artifact_id
    artifacts = value.get("visual_artifacts")
    if isinstance(artifacts, Mapping):
        for artifact in artifacts.values():
            if not isinstance(artifact, Mapping):
                continue
            artifact_id = str(artifact.get("artifact_id") or "").strip()
            if artifact_id:
                return artifact_id
    return None


def _parse_json_object(value: str) -> Mapping[str, Any] | None:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


__all__ = ["latest_selected_artifact_id"]
