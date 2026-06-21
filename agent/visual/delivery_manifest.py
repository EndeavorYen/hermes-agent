from __future__ import annotations

from typing import Any


def build_visual_delivery_manifest(package_payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(package_payload, dict):
        package_payload = {}
    delivery_metadata = package_payload.get("delivery_metadata")
    if not isinstance(delivery_metadata, dict):
        delivery_metadata = {}

    selected_ids = {
        str(item)
        for item in delivery_metadata.get("selected_visual_artifact_ids", [])
        if item
    }
    artifacts = delivery_metadata.get("visual_artifacts")
    if not isinstance(artifacts, dict):
        artifacts = {}

    deliverables = []
    for ref, entry in artifacts.items():
        if not isinstance(entry, dict):
            continue
        artifact_id = str(entry.get("artifact_id") or "")
        if selected_ids and artifact_id not in selected_ids:
            continue
        deliverables.append(_deliverable(str(ref), entry, package_payload))

    return {
        "version": "visual_delivery_manifest.v0.1",
        "request_id": package_payload.get("visual_request_id") or delivery_metadata.get("visual_request_id"),
        "deliverables": deliverables,
    }


def select_deliverable_artifacts(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    deliverables = manifest.get("deliverables") if isinstance(manifest, dict) else []
    if not isinstance(deliverables, list):
        return []
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in deliverables:
        if not isinstance(item, dict):
            continue
        identity = str(item.get("identity") or item.get("ref") or "")
        if not identity or identity in seen:
            continue
        seen.add(identity)
        selected.append(item)
    return selected


def _deliverable(ref: str, entry: dict[str, Any], package_payload: dict[str, Any]) -> dict[str, Any]:
    identity = (
        entry.get("content_hash")
        or entry.get("source_identity")
        or entry.get("source_url")
        or entry.get("uri")
        or ref
    )
    return {
        "request_id": entry.get("request_id") or package_payload.get("visual_request_id"),
        "attempt_id": entry.get("attempt_id"),
        "artifact_id": entry.get("artifact_id"),
        "kind": entry.get("kind") or _kind_from_ref(ref, package_payload),
        "ref": ref,
        "identity": str(identity),
        "width": entry.get("width"),
        "height": entry.get("height"),
    }


def _kind_from_ref(ref: str, package_payload: dict[str, Any]) -> str | None:
    if ref in set(package_payload.get("images") or []):
        return "image"
    if ref in set(package_payload.get("videos") or []):
        return "video"
    lowered = ref.lower()
    if lowered.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif")):
        return "image"
    if lowered.endswith((".mp4", ".mov", ".webm", ".mkv")):
        return "video"
    return None
