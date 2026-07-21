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


def recover_reference_attachment_paths(
    history: Sequence[Mapping[str, Any]] | None,
) -> tuple[str, ...]:
    """Recover the latest user reference bundle from durable turn evidence."""
    for message in reversed(tuple(history or ())):
        if message.get("role") == "assistant":
            for call in reversed(tuple(message.get("tool_calls") or ())):
                if not isinstance(call, Mapping):
                    continue
                function = call.get("function")
                function = function if isinstance(function, Mapping) else {}
                arguments = function.get("arguments") or call.get("arguments")
                arguments = (
                    _parse_json_object(arguments)
                    if isinstance(arguments, str)
                    else arguments
                )
                if not isinstance(arguments, Mapping):
                    continue
                references = _reference_paths(arguments.get("attachments"))
                if not references:
                    references = _reference_paths(
                        arguments.get("reference_image_urls")
                        or arguments.get("reference_images")
                    )
                if references:
                    return references
        if message.get("role") == "user":
            references = _reference_paths_from_user_content(message.get("content"))
            if references:
                return references
    return ()


def _reference_paths(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        path = value.strip()
        return (path,) if path else ()
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def _reference_paths_from_user_content(value: Any) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    paths: list[str] = []
    for part in value:
        if not isinstance(part, Mapping) or part.get("type") != "image_url":
            continue
        image_url = part.get("image_url")
        uri = image_url.get("url") if isinstance(image_url, Mapping) else image_url
        path = str(uri or "").strip()
        if path:
            paths.append(path)
    return tuple(paths)


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


__all__ = ["latest_selected_artifact_id", "recover_reference_attachment_paths"]
